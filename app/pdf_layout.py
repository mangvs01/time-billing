"""Invoice and credit-note PDF layout modelled on the reference invoice 2026-09.

Page 1 (A4 portrait): logo, title, date/number/PO block, issuer and billing addresses (with the
client's legal identity), line table, SOUS-TOTAL / TAUX TVA / TVA / AUTRES / TOTAL, payment block, footer.
Annex (A4 landscape): one "Feuille de temps" per month, cumulative up to the period end, ruled like the
reference workbook, numbered "Page x of y" (numbering starts on the first annex page, as in the reference).
Summary page (A4 landscape): framed PROJET / Dates / Client / Num projet / PO / NB J PO / Jours réalisés cumulés (rc7, A4:
"NB J" renamed), then the contract position: ordered, realised, invoiced, cancelled by credit notes, contract balance.
Missing data is printed as a red [À COMPLÉTER : …] marker on drafts, never invented.

Coordinates are those measured on the reference PDF (points from the top of the page, text at its baseline).

Typography (rc4): the reference uses Avenir Next LT Pro Light (page 1), Cambria (page-1 sub-total amount) and
Calibri / Calibri Light / Calibri Bold (annex). Those are licensed fonts: they are used only if their files are
placed in the licensed-font directory (LICENSED_FONT_DIR). Otherwise the bundled SIL OFL substitutes are
embedded: Nunito Sans Light (≈ Avenir Next Light, widths within ±3 %), Caladea (metric-compatible with Cambria)
and Carlito (metric-compatible with Calibri). An issued document keeps the fonts embedded in its frozen PDF.
"""
import base64, io, os
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from reportlab.lib.colors import Color, HexColor, black
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from app import billing_rules as rules

RED = HexColor("#c62828"); GREY = HexColor("#6e747a")         # reference footer / sub-total grey
BAND = HexColor("#a5a5a5"); BLUE = HexColor("#4472c4")        # annex title band and rules
TOTAL_BAND = HexColor("#e7e6e6"); RULE = HexColor("#404040")  # page-1 totals
GRID = HexColor("#aeaaaa"); PURPLE = HexColor("#9b19f5"); NOTE = HexColor("#444444")
MONTHS = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"]
W, H = A4
LW, LH = landscape(A4)

# --- fonts ----------------------------------------------------------------------------------------
BUNDLED_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
LICENSED_FONT_DIR = os.environ.get("LICENSED_FONT_DIR") or os.path.join(os.path.dirname(os.environ.get("DB_PATH", "/data/timebilling.db")), "fonts")
# role: (reference font, licensed file names accepted, bundled OFL substitute)
FONT_ROLES = {
    "body": ("Avenir Next LT Pro Light", ("AvenirNextLTPro-Light.ttf",), "NunitoSans-Light.ttf"),
    "italic": ("Avenir Next LT Pro Light Italic", ("AvenirNextLTPro-LightIt.ttf", "AvenirNextLTPro-LightItalic.ttf"), "NunitoSans-LightItalic.ttf"),
    "serif": ("Cambria", ("cambria.ttf", "Cambria.ttf"), "Caladea-Regular.ttf"),
    "sheet": ("Calibri", ("calibri.ttf", "Calibri.ttf"), "Carlito-Regular.ttf"),
    "sheet_light": ("Calibri Light", ("calibril.ttf", "Calibri-Light.ttf", "CalibriLight.ttf"), "Carlito-Regular.ttf"),
    "sheet_bold": ("Calibri Bold", ("calibrib.ttf", "Calibri-Bold.ttf", "CalibriBold.ttf"), "Carlito-Bold.ttf"),
}
FONTS_USED = {}


def _register_fonts():
    for role, (ref, licensed, free) in FONT_ROLES.items():
        name = "TB-" + role
        if name in pdfmetrics.getRegisteredFontNames(): continue
        path = next((os.path.join(LICENSED_FONT_DIR, f) for f in licensed if os.path.isfile(os.path.join(LICENSED_FONT_DIR, f))), None)
        source = "police de référence (fichier sous licence)" if path else "substitut libre (SIL OFL)"
        try:
            pdfmetrics.registerFont(TTFont(name, path or os.path.join(BUNDLED_FONT_DIR, free)))
        except Exception:
            if not path: raise
            pdfmetrics.registerFont(TTFont(name, os.path.join(BUNDLED_FONT_DIR, free))); path = None; source = "substitut libre (fichier sous licence illisible)"
        FONTS_USED[role] = {"reference": ref, "file": os.path.basename(path or free), "source": source}


_register_fonts()
BODY, ITALIC, SERIF, SHEET, SHEET_LIGHT, SHEET_BOLD = ("TB-" + r for r in FONT_ROLES)


# --- formatting -----------------------------------------------------------------------------------
def num(v, places=2):
    s = f"{Decimal(str(v)):,.{places}f}"
    return s.replace(",", " ").replace(".", ",")


def qty_label(v):
    """Quantity as printed: at least 2 decimals, up to 6 when the stored value has them (quantity x unit price must match the printed amount)."""
    d = Decimal(str(v)).quantize(Decimal("0.000001"), ROUND_HALF_UP).normalize()
    places = max(2, -d.as_tuple().exponent) if d.as_tuple().exponent < 0 else 2
    return num(d, places)


def rate_money(v):
    """Unit price: 2 decimals, up to 4 when needed (hour rate = day rate / hours per day)."""
    d = Decimal(str(v)).quantize(Decimal("0.0001"), ROUND_HALF_UP).normalize()
    places = max(2, -d.as_tuple().exponent) if d.as_tuple().exponent < 0 else 2
    return f"{num(d, places)} CHF"


def money(v, dash_zero=False):
    return "- CHF" if dash_zero and Decimal(str(v)) == 0 else f"{num(v)} CHF"


def days_label(v):
    s = num(v)
    return s[:-3] if s.endswith(",00") else s


def dmy(iso, sep="."):
    # RC8: a stored UTC timestamp is printed as its Zurich calendar day; a plain date as is
    return date.fromisoformat(rules.local_date(iso)).strftime(f"%d{sep}%m{sep}%Y") if iso else ""


def clock_decimal(hhmm):
    if not hhmm: return ""
    p = [int(x) for x in hhmm.split(":")]
    return num(Decimal(p[0]) + Decimal(p[1]) / 60 + (Decimal(p[2]) / 3600 if len(p) > 2 else 0))


def month_label(ym):
    return f"{MONTHS[int(ym[5:7]) - 1]}-{ym[2:4]}"


def wrap_text(s, width, size, font=BODY):
    """Word-wrap s into lines no wider than width (measured with the registered font). A word wider than the column is hyphenated."""
    sw = pdfmetrics.stringWidth
    out, row = [], ""
    for word in (s or "").split():
        while sw(word, font, size) > width:
            cut = len(word) - 1
            while cut > 1 and sw(word[:cut] + "-", font, size) > width: cut -= 1
            if row: out.append(row); row = ""
            out.append(word[:cut] + "-"); word = word[cut:]
        cand = (row + " " + word).strip()
        if row and sw(cand, font, size) > width: out.append(row); row = word
        else: row = cand
    if row: out.append(row)
    return out or [""]


class Doc:
    def __init__(self, placeholders=True):
        # placeholders only on drafts: an issued document never shows [À COMPLÉTER] markers
        self.buf = io.BytesIO(); self.c = canvas.Canvas(self.buf, pagesize=A4, initialFontName=BODY, initialFontSize=8); self.missing = []; self.placeholders = placeholders; self.low = 0.0

    def text(self, x, top, s, size=8, font=BODY, color=black, align="left", label=None):
        """Draw s with its baseline `top` points from the top of the current page; empty + label → red placeholder."""
        c = self.c; h = c._pagesize[1]
        if not s and label:
            self.missing.append(label)
            if not self.placeholders: return
            s = f"[À COMPLÉTER : {label}]"; color = RED
        c.setFont(font, size); c.setFillColor(color)
        if c.getPageNumber() == 1 and top < PAGE_ONE_FOOTER_TOP - 2: self.low = max(self.low, top)    # rc37: lowest text of page 1 above the footer (first_page_bottom)
        {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align](x, h - top, s)
        c.setFillColor(black)

    def fit(self, s, width, size, font=BODY):
        """Truncate with an ellipsis so a cell never overlaps the next column."""
        s = s or ""
        if self.c.stringWidth(s, font, size) <= width: return s
        while s and self.c.stringWidth(s + "…", font, size) > width: s = s[:-1]
        return s + "…"

    def wrap(self, s, width, size, font=BODY):
        """Word-wrap s into lines no wider than width. A word wider than the column is hyphenated (last resort)."""
        return wrap_text(s, width, size, font)

    def fit_cell(self, s, width, size, font=BODY):
        """A1 (rc7): never truncate, never shrink. One line at the normal size when it fits; otherwise the text wraps
        between words at the same size (the row grows). A single word wider than the column is hyphenated (last resort)."""
        if self.c.stringWidth(s or "", font, size) <= width: return size, [s or ""]
        return size, self.wrap(s, width, size, font)

    def lines(self, x, top, block, step=12.48, size=8, label=None, width=None, **kw):
        rows = [l.strip() for l in (block or "").splitlines() if l.strip()]
        if not rows:
            self.text(x, top, "", size=size, label=label, **kw); return top + step
        if width:  # rc12: a line wider than its column wraps instead of running off the page
            rows = [part for r in rows for part in self.wrap(r, width, size)]
        for r in rows:
            self.text(x, top, r, size=size, **kw); top += step
        return top

    def block(self, x, top, parts, width, bottom):
        """rc12: draw several blocks (text, placeholder label) one under the other in a column `width` wide that must end
        above `bottom`. Wraps between words; when the whole does not fit the height, the type size and pitch shrink
        (8 → 7 → 6.5 pt). Returns the next free baseline. See block_fits() for the matching refusal at issue time."""
        parts = [(t, l) for t, l in parts if (t or "").strip() or l]   # an empty block without placeholder takes no room
        for size, step in BLOCK_SIZES:
            rows = [r for text, _ in parts for r in self._block_rows(text, width, size)]
            if top + step * (len(rows) - 1) <= bottom: break
        for text, label in parts:
            top = self.lines(x, top, text, step=step, size=size, label=label, width=width)
        return top

    def _block_rows(self, text, width, size):
        rows = [l.strip() for l in (text or "").splitlines() if l.strip()]
        return [part for r in rows for part in self.wrap(r, width, size)] or [""]

    def bar(self, x1, x2, top, bottom, color=black):
        """Filled box between two distances from the top: the reference draws its rules as thin filled boxes."""
        h = self.c._pagesize[1]; self.c.setFillColor(color); self.c.rect(x1, h - bottom, x2 - x1, bottom - top, stroke=0, fill=1); self.c.setFillColor(black)

    def finish(self):
        self.c.save(); return self.buf.getvalue()


def _logo(d, logo_b64):
    if logo_b64:
        try:
            d.c.drawImage(ImageReader(io.BytesIO(base64.b64decode(logo_b64))), 49.9, H - 159.8, width=105.6, height=105.6, preserveAspectRatio=True, mask="auto")
            return
        except Exception:
            pass
    if d.placeholders: d.text(55, 100, "[Logo à fournir — Paramètres]", size=7, color=GREY)


def legal_identity_lines(h):
    """Client legal identity frozen with the invoice (rc3): name when not already in the address block, then identifier."""
    shown = " ".join([h.get("billing_contact") or "", h.get("billing_address") or ""]).casefold()
    out = []
    name = (h.get("client_legal_name") or "").strip()
    if name and name.casefold() not in shown: out.append(name)
    # normalised display (rc5); the frozen header keeps the value as entered in client_legal_id
    shown_id = h.get("client_legal_id_display") or rules.legal_display(h.get("client_legal_id"))
    if shown_id: out.append(f"N° d'identification : {shown_id}")
    return out


BLOCK_SIZES = ((8, 12.48), (7, 10.6), (6.5, 9.6))
ISSUER_WIDTH, BILLING_WIDTH, BLOCK_BOTTOM = 150, 164, 283
BILLING_MAX_ROWS = int((BLOCK_BOTTOM - 185.4) // BLOCK_SIZES[-1][1]) + 1     # rows of the billing block at the smallest size (same capacity as block_fits)


def block_fits(h):
    """rc12: True when the issuer and billing blocks fit their column at the smallest type size (else refuse at issue time)."""
    s = h["issuer"]; size, step = BLOCK_SIZES[-1]
    def n(parts, width): return sum(len(_measure_rows(t, width, size)) for t in parts)
    cap = int((BLOCK_BOTTOM - 185.4) // step) + 1
    return (n([s.get("issuer_name"), s.get("issuer_address")], ISSUER_WIDTH) <= cap
            and n([h.get("billing_contact"), h.get("billing_address")] + legal_identity_lines(h), BILLING_WIDTH) <= cap)


def block_rows(*texts):
    """Printed rows of an address block (contact + address) at the smallest type size, in the billing column."""
    size, step = BLOCK_SIZES[-1]
    return sum(len(_measure_rows(t, BILLING_WIDTH, size)) for t in texts if (t or "").strip())


def _measure_rows(text, width, size):
    rows = [l.strip() for l in (text or "").splitlines() if l.strip()] or [""]
    out = []
    for r in rows:
        row = ""
        for wd in r.split():
            while pdfmetrics.stringWidth(wd, BODY, size) > width:   # hyphenated like Doc.wrap
                cut = len(wd) - 1
                while cut > 1 and pdfmetrics.stringWidth(wd[:cut] + "-", BODY, size) > width: cut -= 1
                if row: out.append(row); row = ""
                out.append(wd[:cut] + "-"); wd = wd[cut:]
            cand = (row + " " + wd).strip()
            if row and pdfmetrics.stringWidth(cand, BODY, size) > width: out.append(row); row = wd
            else: row = cand
        out.append(row)
    return out


MAX_DESCRIPTION_LINES = 4          # lines available for the description in the line table of the first page
INVOICE_DESCRIPTION_LINES = MAX_DESCRIPTION_LINES - 1   # D6 (2026-10-06): an invoice keeps the last line of the cell for its period
DESCRIPTION_WIDTH = 150


def period_line(f, t):
    """D6 (a): the invoiced period, printed in the DESCRIPTION cell under the description (as the project number on the reference invoice)."""
    return f"Période : {dmy(f)} – {dmy(t)}"


def description_line_count(text):
    """Number of printed lines the description needs (same wrapping as the page): used to refuse a text that would be cut."""
    row, n = "", 1
    for wd in (text or "").split():
        if pdfmetrics.stringWidth(row + " " + wd, BODY, 8) > DESCRIPTION_WIDTH and row: n += 1; row = wd
        else: row = (row + " " + wd).strip()
    return n


def _wrap(d, text, width, font=BODY, size=8):
    words, row, out = (text or "").split(), "", []
    for wd in words:
        if d.c.stringWidth(row + " " + wd, font, size) > width and row: out.append(row); row = wd
        else: row = (row + " " + wd).strip()
    out.append(row)
    return out


def note_fits(note):
    """E-4 (decision B, 2026-10-07): the free note of an invoice has a FIXED zone of one line under the totals (7.5 pt, 347 pt wide): True when it fits."""
    return len(wrap_text(" ".join((note or "").split()), 347, 7.5)) <= 1


# --- rc37 (P1): manual lines of a draft, printed as extra rows of the line table under the service line ---------------------------------------
PAGE_ONE_FOOTER_TOP = 816.4        # baseline of the footer line (reference geometry)
PAGE_ONE_LIMIT = 807.0             # lowest baseline allowed for the body of page 1 (the BIC row of the payment block): 9 pt above the footer baseline
MAX_MANUAL_LINES = 8               # hard limit, fixed by the rendering test (tests/test_invoice_lines.py): beyond it the payment block would reach the footer
MANUAL_DESCRIPTION_LINES = 2       # a manual line wraps on at most two lines of the DESCRIPTION column (refused longer, never cut)
MANUAL_ROWS_BUDGET = 170.0         # points available under the service line before the totals leave their place (see the same test)
MANUAL_LINE_PITCH = 10.3           # same pitch as the service line description
MANUAL_ROW_GAP = 6.0
MANUAL_QTY_WIDTH = 52.0            # quantity cell: x 209 → 261.9 (right aligned), between the description column and the rate column


def manual_row_height(description):
    """Height in points of the printed row of one manual line."""
    return description_line_count(description) * MANUAL_LINE_PITCH + MANUAL_ROW_GAP


def manual_qty_text(line, table_unit=None):
    """Quantity as printed in the line table; the unit is added when it is not the one of the table heading (JOUR / HEURES)."""
    text = qty_label(line["qty"])
    if line.get("unit") and line["unit"] != table_unit: text += " " + rules.MANUAL_UNIT_SHORT.get(line["unit"], line["unit"])
    return text


def manual_lines_problem(lines, table_unit=None):
    """Why the manual lines cannot be printed on page 1 (None = they fit): count, description length, quantity cell, total height. Used by the form,
    by check 11 and by the issuance, so a document is never cut and the totals / payment block never run into the footer."""
    lines = list(lines or ())
    if len(lines) > MAX_MANUAL_LINES: return f"{len(lines)} lignes manuelles : {MAX_MANUAL_LINES} au maximum sur la page 1 de la facture"
    for n, ln in enumerate(lines, 1):
        if description_line_count(ln["description"]) > MANUAL_DESCRIPTION_LINES:
            return f"ligne {n} : description trop longue ({MANUAL_DESCRIPTION_LINES} lignes imprimées au maximum, environ {35 * MANUAL_DESCRIPTION_LINES} caractères) : la raccourcir"
        if any(pdfmetrics.stringWidth(w, BODY, 8) > DESCRIPTION_WIDTH for w in ln["description"].split()):
            return f"ligne {n} : un mot de la description est trop long pour la colonne du document imprimé : l'écrire en plusieurs mots"
        if pdfmetrics.stringWidth(manual_qty_text(ln, table_unit), BODY, 8) > MANUAL_QTY_WIDTH:
            return f"ligne {n} : quantité trop longue pour la colonne du document imprimé : réduire le nombre de décimales"
    if sum(manual_row_height(ln["description"]) for ln in lines) > MANUAL_ROWS_BUDGET + 1e-9:
        return "les lignes manuelles occupent plus de place que la page 1 n'en réserve : raccourcir des descriptions (une ligne imprimée tient sur 1 ou 2 lignes) ou retirer une ligne"
    return None


REF_ROW_PITCH = 11.1               # reference geometry: date / number / PO rows of an issued document
DRAFT_REF_ROW_PITCH = 14.0         # rc37: a DRAFT spreads these rows (8 pt type, line box 10.9 pt): the planned date and the proposed number no longer touch (owner remark 26.10.2026)


def _first_page(d, h, title, ref_rows, table, totals, extra_lines=(), payment=True, thanks=True, note_line=None, ref_pitch=REF_ROW_PITCH):
    s = h["issuer"]
    _logo(d, s.get("logo_png_b64"))
    d.text(554.3, 74.5, title, size=20, align="right")
    top = 99.4
    for label, value, field in ref_rows:
        d.text(210, top, label); d.text(390.7, top, value, label=field); top += ref_pitch
    # short placeholder labels: the issuer column is ~150 pt wide; rc12: both columns wrap and end above the table (295 pt)
    d.block(50.3, 185.4, [(s.get("issuer_name"), "Raison sociale"), (s.get("issuer_address"), "Adresse émetteur")], ISSUER_WIDTH, BLOCK_BOTTOM)
    d.text(210, 185.4, "Adresse de facturation :")
    d.block(390.7, 185.4, [(h.get("billing_contact"), None), (h.get("billing_address"), "Adresse de facturation")]
            + [(l, None) for l in legal_identity_lines(h)], BILLING_WIDTH, BLOCK_BOTTOM)
    # line table: one row per line (the invoice has one; a credit note may add its « AUTRES » part)
    _, unit_head, rate_head = table["head"]
    d.text(50.3, 295.6, "DESCRIPTION"); d.text(264.3, 295.6, unit_head, align="right"); d.text(380.6, 295.6, rate_head, align="right"); d.text(555.4, 295.6, "MONTANT", align="right")
    top = 317.9
    for idx, line in enumerate(table["lines"]):
        if line.get("manual"):
            # rc37: manual line = rows under the service line, same columns; 1 or 2 lines of description (validated upstream, never cut)
            rows = _wrap(d, line["description"], DESCRIPTION_WIDTH)[:MANUAL_DESCRIPTION_LINES]
            mid = top + 5.1 * (len(rows) - 1)
            for i, r in enumerate(rows): d.text(50.3, top + i * MANUAL_LINE_PITCH, r)
            d.text(261.9, mid, line.get("qty", ""), align="right"); d.text(384.0, mid, line.get("rate", ""), align="right"); d.text(552.4, mid, line["amount"], align="right")
            top += len(rows) * MANUAL_LINE_PITCH + MANUAL_ROW_GAP
            continue
        rows = _wrap(d, line["description"], DESCRIPTION_WIDTH)[:MAX_DESCRIPTION_LINES]
        if line.get("period"): rows = rows[:INVOICE_DESCRIPTION_LINES]       # D6 (a): 3 lines of description (refused longer, never cut) + the period
        mid = top + 5.1 * (min(len(rows) + bool(line.get("period")), 2) - 1)
        for i, r in enumerate(rows): d.text(50.3, top + i * 10.3, r)
        # D6 (a): the period is the cell's next line, in the DESCRIPTION column only (x 50–200, the totals start at x 208): with a description of
        # one or two lines as on the reference invoice, it takes the room left beside the SOUS-TOTAL and nothing of the reference model moves
        if line.get("period"): d.text(50.3, top + len(rows) * 10.3, line["period"])
        d.text(261.9, mid, line.get("qty", ""), align="right"); d.text(384.0, mid, line.get("rate", ""), align="right"); d.text(552.4, mid, line["amount"], align="right")
        # D6 (a) « aucun élément du modèle ne bouge » (R-E5-1, 2026-10-06): a 3rd line of description and the period stay in that column, beside the
        # SOUS-TOTAL row (x 50–175 < 208), so an invoice line never pushes the totals below their place on the reference; a credit note keeps 4 lines
        if idx + 1 < len(table["lines"]) and table["lines"][idx + 1].get("manual"):
            top += (len(rows) + bool(line.get("period"))) * 10.3 + 6      # rc37: manual rows follow: this row keeps its real height (description + period), they start under it
        else:
            top += max(min(len(rows), 2) if line.get("period") else len(rows), 2) * 10.3 + 6
    # totals: rule under each row, grey band on the closing row, as in the reference
    top = max(350.5, top + 6)
    for i, (label, value) in enumerate(totals):
        if i == len(totals) - 1: d.bar(208.3, 557.2, top - 13.9, top + 8.3, TOTAL_BAND)
        d.text(210, top, label)
        if i == 0: d.text(553.7, top, value, font=SERIF, color=GREY, align="right")  # reference: sub-total amount in Cambria, grey
        else: d.text(552.0, top, value, align="right")
        d.bar(208.3, 557.2, top + 7.5, top + 8.3, RULE)
        top += 22.08
    top += 2
    if note_line:       # E-4 (B): one fixed line in the gap above the thanks; nothing below it moves, with or without a note
        d.text(210, top, " ".join(note_line.split()), size=7.5, color=NOTE)
    for line in extra_lines:
        # rc6: a mention wider than the totals block (210 → 557 pt) wraps instead of running off the page
        for part in d.wrap(line, 347, 7.5):
            d.text(210, top, part, size=7.5, color=NOTE); top += 11
    if thanks and s.get("thanks_text"):
        tt = top + 14 if top + 14 > 482.5 else 482.5
        for part in d.wrap(s["thanks_text"], 347, 8, ITALIC): d.text(552.0, tt, part, font=ITALIC, align="right"); tt += 11   # rc12: wraps in the totals column
    if payment:
        pay = max(top + 50, 549.2)
        terms = d.wrap(s.get("payment_terms"), 507, 8)   # rc12: long terms wrap, the rows below move down
        if s.get("payment_terms"):
            for i, part in enumerate(terms): d.text(50.3, pay + i * 11, part)
            pay += 11 * (len(terms) - 1)
        else: d.text(50.3, pay, "", label="Conditions de paiement")
        d.text(50.3, pay + 22.08, "Titulaire: " + (s.get("account_holder") or "")) if s.get("account_holder") else d.text(50.3, pay + 22.08, "", label="Titulaire du compte")
        d.text(50.3, pay + 44.16, "IBAN: " + (s.get("iban") or "")) if s.get("iban") else d.text(50.3, pay + 44.16, "", label="IBAN")
        d.text(50.3, pay + 66.24, "BIC: " + s["bic"]) if s.get("bic") else d.text(50.3, pay + 66.24, "", label="BIC")
    foot = []
    if s.get("issuer_rc"): foot.append(f"N° registre commerce: {s['issuer_rc']}")
    if s.get("issuer_vat_number"): foot.append(f"N° TVA: {s['issuer_vat_number']}")
    if s.get("iban"): foot.append(f"IBAN: {s['iban']}")
    foot_text = "   ".join(foot)
    foot_size = 8
    while foot_size > 5.5 and d.c.stringWidth(foot_text, BODY, foot_size) > 500: foot_size -= 0.5   # rc12: the footer line keeps inside the margins
    d.text(W / 2, 816.4, foot_text, size=foot_size, color=GREY, align="center")
    if not s.get("issuer_rc"): d.text(W / 2, 826, "", size=6.5, align="center", label="N° registre du commerce (pied de page)")


def rounded_line(qty, rate):
    return (Decimal(str(qty)) * Decimal(str(rate))).quantize(Decimal("0.01"), ROUND_HALF_UP)


OTHER_VAT_SHORT = {"hors_tva": "hors TVA", "soumis": "soumis à TVA"}


def other_label(h, amount, prefix="AUTRES"):
    """« AUTRES » line label; its own label and VAT treatment are printed only when the line carries an amount (G4 §6: an empty « AUTRES » reads as on the reference)."""
    if Decimal(str(amount or 0)) == 0: return prefix
    label = prefix + (f" — {h['other_label']}" if h.get("other_label") else "")
    return label + f" ({OTHER_VAT_SHORT.get(h.get('other_vat_mode') or 'hors_tva', 'hors TVA')})"


def other_label_fits(h, amount):
    """The totals print the « AUTRES » row on ONE line, from x 210 up to its amount right-aligned at x 552: True when the label of the invoice
    (and the « AUTRES CRÉDITÉ » one of a credit note on it) stops 6 pt before that amount."""
    if Decimal(str(amount or 0)) == 0: return True
    room = 552.0 - 210 - pdfmetrics.stringWidth(money(amount, True), BODY, 8) - 6
    return all(pdfmetrics.stringWidth(other_label(h, amount, p), BODY, 8) <= room for p in ("AUTRES", "AUTRES CRÉDITÉ"))


def unit_heads(unit):
    return (None, "HEURES", "COUT HORAIRE") if unit == "hour" else (None, "JOUR", "COUT JOURNALIER")


# --- annex ----------------------------------------------------------------------------------------
ROWS_PER_PAGE = 21          # 21 rows + the total row fit above the page number at the reference row pitch
ROW_PITCH = 16.76
A_LEFT, A_RIGHT = 43.8, 809.9
HEAD_COLS = [(45.5, "Date(s)", "left"), (207.6, "Motif", "center"), (343.7, "Projet", "left"), (442.1, "Numéro de projet", "left"),
             (540.5, "Heure début", "left"), (636.3, "Heure fin", "left"), (724.8, "Heures de travail", "left")]


MOTIF_WIDTH = 133           # width of the "Motif" column (204 → 337 pt)
MOTIF_STEP = 10.8           # pitch of a wrapped Motif line (9 pt Calibri)
MOTIF_MAX_LINES = 28        # rc13 (QA-22): the Motif wraps; beyond ~28 lines (one page) it is cut with an ellipsis


def motif_lines(e):
    """rc13 (QA-22): the reason of an annex row, wrapped between words (whitespace and line breaks collapsed), never cut
    unless it exceeds a page."""
    rows = wrap_text(" ".join((e.get("description") or "").split()), MOTIF_WIDTH, 9, SHEET)
    if len(rows) > MOTIF_MAX_LINES:
        rows = rows[:MOTIF_MAX_LINES]; rows[-1] = rows[-1].rstrip(" .,;") + " …"
    return rows


def row_height(e):
    return ROW_PITCH + (len(motif_lines(e)) - 1) * MOTIF_STEP


def annex_plan(annex, period=None):
    """[(month, rows on this page, month's last page?, month total, page index within the month, section, partial month?)], computed
    before drawing so every page can print its "Page x of y". A page holds 21 single-line rows; rows whose Motif wraps
    take proportionally more room (rc13).
    G4 / D6 (b), 2026-10-06: the annex is the cumulative history up to the cutoff, in CHRONOLOGICAL order as the reference invoice 2026-09.
    period=(from, to) only tags each page: section 'C' (before the period: information) or 'P' (the invoiced period); the two are never mixed
    on a page, so a month cut by the start of the period gives two page groups (partial), history first. Without a period (or when every row lies
    in it) the plan is the reference one: months in order, section 'P', no label.
    Decision billing-facturee-par-date = A (2026-10-08): a row of the period already billed by an earlier invoice (billed_elsewhere, its
    date corrected since) is section 'F' (information), never mixed with the invoiced period's rows."""
    sec = (lambda e: ("F" if e.get("billed_elsewhere") else "P") if period[0] <= e["work_date"] <= period[1] else "C") if period else (lambda e: "P")
    groups = {}
    for e in annex: groups.setdefault((sec(e), e["work_date"][:7]), []).append(e)
    sections = {}
    for (sc, ym) in groups: sections.setdefault(ym, set()).add(sc)
    cut = {ym for ym, scs in sections.items() if len(scs) > 1}
    plan = []
    budget = ROWS_PER_PAGE * ROW_PITCH
    for key in sorted(groups, key=lambda k: (k[1], "CFP".index(k[0]))):      # month order; inside a cut month, the history before the period first
        sc, ym = key
        rows = groups[key]; total = sum(Decimal(str(e["hours"])) for e in rows)
        chunks, cur, used = [], [], 0.0
        for e in rows:
            h = row_height(e)
            if cur and used + h > budget + 0.01: chunks.append(cur); cur, used = [], 0.0
            cur.append(e); used += h
        if cur: chunks.append(cur)
        for k, chunk in enumerate(chunks): plan.append((ym, chunk, k == len(chunks) - 1, total, k, sc, ym in cut))
    return plan


def _page_number(d, k, n):
    d.text(LW / 2, 569.4, f"Page {k} of {n}", size=9, font=SHEET, align="center")


def _timesheet_page(d, h, ym, rows, last, total, cont, caption=None, partial=False):
    d.bar(A_LEFT, A_RIGHT, 29.8, 58.7, BAND); d.bar(A_LEFT, A_RIGHT, 28.1, 30.5, BLUE)
    d.text(46.8, 52.3, "Feuille de temps", size=19.7, font=SHEET_LIGHT, color=Color(1, 1, 1))
    d.text(46.0, 83.2, month_label(ym) + (" (suite)" if cont else ""), size=13.1, font=SHEET_LIGHT)
    if caption: d.text(46.0, 96.4, caption, size=8.5, font=SHEET, color=NOTE)      # G4 / D6 (b): only when the annex holds history before the period
    d.text(45.6, 108.4, "Total des heures", size=9.8, font=SHEET_LIGHT); d.text(45.6, 121.2, "de travail (partie du mois)" if partial else "de travail du mois", size=9.8, font=SHEET_LIGHT)
    d.text(46.4, 145.0, num(total), size=16.4, font=SHEET_LIGHT)
    d.bar(A_LEFT, A_RIGHT, 150.0, 150.8, BLUE)
    for x, label, al in HEAD_COLS: d.text(x, 179.8, label, size=9, font=SHEET, align=al)
    d.bar(44.6, A_RIGHT, 183.0, 184.6)                       # header rule (thick, black)
    top = 196.5
    project = h.get("project_short") or h["project"]
    for e in rows:
        d.text(172.4, top, dmy(e["work_date"], "/"), size=9, font=SHEET, align="center")
        mrows = motif_lines(e)
        for i, part in enumerate(mrows): d.text(204.0, top + i * MOTIF_STEP, part, size=9, font=SHEET)
        d.text(343.7, top, d.fit(project, 94, 9, SHEET), size=9, font=SHEET)
        d.text(442.1, top, d.fit(h.get("project_number") or "", 94, 9, SHEET), size=9, font=SHEET)
        d.text(633.0, top, clock_decimal(e["start_time"]), size=9, font=SHEET, align="right")
        d.text(721.4, top, clock_decimal(e["end_time"]), size=9, font=SHEET, align="right")
        d.text(808.0, top, num(e["hours"]), size=9, font=SHEET, align="right")
        top += (len(mrows) - 1) * MOTIF_STEP
        d.bar(44.6, A_RIGHT, top + 3.6, top + 4.4, GRID)      # row rule (thin, grey)
        top += ROW_PITCH
    if last:
        d.text(45.5, top, "Total", size=9, font=SHEET); d.text(808.0, top, num(total), size=9, font=SHEET_BOLD, align="right")
        d.bar(44.6, A_RIGHT, top + 3.6, top + 4.4)             # frame closed under the total
        bottom = top + 4.4
    else:
        bottom = top - ROW_PITCH + 4.4
    d.bar(43.1, 44.6, 183.0, bottom)                           # left frame (thick, as in the reference)
    d.bar(A_RIGHT - 0.8, A_RIGHT, 183.0, bottom)               # right frame


LINE = 10.3 * 1.2          # summary row pitch for a wrapped cell (Calibri 10.3 pt)


def _framed_table(d, top, cols, right, heads, vals):
    """Framed two-row table drawn with the reference summary metrics (rules every 13.3 pt, text 10.4 pt under a rule).
    Headings and values wrap between words inside their column (A1: never truncated, never shrunk); the row grows.
    vals: [(text, placeholder label or None)]. Returns the distance from the top of the page to the bottom rule."""
    edges = cols[1:] + [right]
    hcells = [d.wrap(t, nxt - x - 6, 10.3, SHEET_BOLD) for x, t, nxt in zip(cols, heads, edges)]
    vcells = [d.fit_cell(v, nxt - x - 6, 10.3, SHEET)[1] if v else [] for x, (v, _), nxt in zip(cols, vals, edges)]
    mid = top + 13.3 + (max(len(c) for c in hcells) - 1) * LINE
    bottom = mid + 13.3 + (max([len(c) for c in vcells] + [1]) - 1) * LINE
    for t in (top, mid, bottom): d.bar(cols[0] - 1.8, right, t - 0.42, t + 0.42)
    d.bar(cols[0] - 2.2, cols[0] - 1.3, top - 0.4, bottom + 0.5); d.bar(right - 0.4, right + 0.4, top - 0.4, bottom + 0.5)
    for x, cl in zip(cols, hcells):
        for i, line in enumerate(cl): d.text(x, top + 10.4 + i * LINE, line, size=10.3, font=SHEET_BOLD)
    for x, (v, label), cl in zip(cols, vals, vcells):
        for i, line in enumerate(cl): d.text(x, mid + 10.4 + i * LINE, line, size=10.3, font=SHEET)
        if not v and label: d.text(x, mid + 10.4, "", size=6, font=SHEET, label=label)
    return bottom


# A1 (rc7): Client column widened (57 → 150 pt) at the expense of PO (169 → 110 pt) and Dates; same overall frame
SUMMARY_COLS = [52.7, 172.7, 282.7, 432.7, 522.7, 632.7, 702.7]
SUMMARY_RIGHT = 786.8
POSITION_COLS = [52.7, 199.5, 346.3, 493.1, 639.9]
POSITION7_COLS = [52.7, 157.6, 262.4, 367.3, 472.2, 577.0, 681.9]   # G4: seven boxes over the same frame


def _summary_page(d, h):
    d.text(53.3, 72.8, h["period_to"][:4], size=15, font=SHEET_BOLD, color=PURPLE)
    if h.get("position") and "historical" in h["position"]:     # D6 (b): what the annex is (headers frozen before G4 keep their page unchanged)
        d.text(SUMMARY_RIGHT, 64.0, f"Période facturée : du {dmy(h['period_from'])} au {dmy(h['period_to'])} · Historique cumulatif des prestations jusqu'au {dmy(h['period_to'])}",
               size=8.5, font=SHEET, color=NOTE, align="right")
    heads = ["PROJET", "Dates", "Client", "Num projet", "PO", "NB J PO", "Jours réalisés cumulés"]
    # mandate information; on drafts a missing value is flagged, never invented
    vals = [(h.get("project_short") or h["project"], None), (h.get("dates_label") or "", "Dates"), (h.get("client") or "", "Client"),
            (h.get("project_number") or "", "N° projet"), (h.get("po") or "", "PO"), (days_label(h.get("ordered_days") or 0), None), (days_label(h["consumed_days"]), None)]
    top = _framed_table(d, 74.2, SUMMARY_COLS, SUMMARY_RIGHT, heads, vals) + 17.2
    if h.get("reliquat_treatment") == "offert" and h.get("reliquat_days"):
        d.text(52.7, top, f"Dont {num(h['reliquat_days'])} jour(s) réalisé(s) offert(s), non facturé(s).", size=10, font=SHEET); top += 20
    pos = h.get("position")
    if not pos: return  # header frozen before rc7: no position block
    # A4 (rc7): realised, invoiced, cancelled by credit notes and contract balance kept apart, in days
    cutoff = pos.get("cutoff") or h["period_to"]      # D9 (decision B, 2026-10-07): the date of the invoice; headers frozen before it keep their end of period
    d.text(52.7, top + 8, f"Position contractuelle en jours au {dmy(cutoff)}", size=10.3, font=SHEET_BOLD)
    if "historical" in pos:
        # G4: invoiced days are NEVER deduced from the time entries: historical invoices (outside Time Billing, validated in the registry), earlier Time Billing
        # invoices and this invoice are three separate figures
        heads = ["Jours commandés (PO)", "Jours réalisés cumulés", "Jours facturés historiques (hors Time Billing)", "Jours facturés Time Billing antérieurs",
                 "Jours facturés par cette facture", "Jours annulés par notes de crédit", "Solde contractuel"]
        vals = [(days_label(pos["ordered"]), None), (days_label(pos["realized"]), None), (days_label(pos["historical"]), None), (days_label(pos["previous"]), None),
                (days_label(pos["current"]), None), (days_label(pos["credited"]), None), (days_label(pos["balance"]) if pos["ordered"] else "sans bon de commande", None)]
        bottom = _framed_table(d, top + 16, POSITION7_COLS, SUMMARY_RIGHT, heads, vals)
        notes = [f"Jours réalisés cumulés : temps enregistré du début du mandat au {dmy(h['period_to'])} (fin de la période facturée).",
                 f"Les factures sont comptées à leur date : jours facturés historiques = factures émises hors Time Billing, validées dans le registre, datées au plus tard du {dmy(cutoff)} "
                 f"(date de cette facture). Jours facturés Time Billing antérieurs : factures Time Billing émises datées au plus tard du {dmy(cutoff)}. Jours annulés : notes de crédit "
                 "émises au plus tard à cette date et non annulées à cette date, sur ces factures antérieures, créditées en jours (un crédit en montant seul ne modifie pas les jours).",
                 "Solde contractuel = jours commandés − (historiques + antérieurs + cette facture − jours annulés par notes de crédit)."]
        items = pos.get("historical_items") or []
        if items:
            shown = " ; ".join(f"{dmy(x['date'])} : {num(x['days'], 2)} j ({x['cell']})" if x.get("date") else f"{num(x['days'], 2)} j ({x['cell']})" for x in items[:8])
            notes.append("Factures historiques prises en compte : " + shown + (" ; …" if len(items) > 8 else "") + ".")
        if h.get("period_hours") is not None and abs(float(h["period_hours"])) < 1e-9:
            if h.get("period_billed_elsewhere"):
                notes.append(f"Aucune prestation nouvelle dans la période facturée (du {dmy(h['period_from'])} au {dmy(h['period_to'])}) : les saisies datées de la période "
                             f"sont déjà facturées par la facture {', '.join(h['period_billed_elsewhere'])} ; les feuilles de temps jointes sont du cumul.")
            else:
                notes.append(f"Aucune saisie datée de la période facturée (du {dmy(h['period_from'])} au {dmy(h['period_to'])}) : les feuilles de temps jointes sont du cumul antérieur à la période.")
    else:
        heads = ["Jours commandés (PO)", "Jours réalisés cumulés", "Jours facturés", "Jours annulés par notes de crédit", "Solde contractuel"]
        vals = [(days_label(pos["ordered"]), None), (days_label(pos["realized"]), None), (days_label(pos["invoiced"]), None),
                (days_label(pos["credited"]), None), (days_label(pos["balance"]) if pos["ordered"] else "sans bon de commande", None)]
        bottom = _framed_table(d, top + 16, POSITION_COLS, SUMMARY_RIGHT, heads, vals)
        notes = ["Jours réalisés cumulés : temps enregistré du début du mandat à la fin de la période facturée.",
                 "Jours facturés : factures émises, y compris la présente facture. Jours annulés : notes de crédit émises et non annulées, "
                 "créditées en jours (un crédit en montant seul ne modifie pas les jours).",
                 "Solde contractuel = jours commandés − (jours facturés − jours annulés par notes de crédit)."]
    y = bottom + 14
    for n in notes:
        for part in d.wrap(n, SUMMARY_RIGHT - 52.7, 8.5, SHEET):
            d.text(52.7, y, part, size=8.5, font=SHEET, color=NOTE); y += 10.5


def first_page_bottom(h):
    """Lowest baseline of the body of page 1 (everything above the footer) for this header, measured by a dry rendering of that page alone. Check 11 refuses an
    invoice whose page 1 would run into the footer (many manual lines + credit imputations + long note / payment terms)."""
    d = Doc(placeholders=False); a = h["amounts"]
    table = {"head": unit_heads(h["unit"]), "lines": [{"description": h.get("description") or h["project"], "qty": qty_label(h["qty"]), "rate": rate_money(h["unit_rate"]),
                                                      "amount": money(a["ht"]), "period": period_line(h["period_from"], h["period_to"])}]}
    for ln in h.get("lines") or ():
        table["lines"].append({"manual": True, "description": ln["description"], "qty": manual_qty_text(ln, h["unit"]), "rate": rate_money(ln["unit_rate"]), "amount": money(rules.line_amount(ln["qty"], ln["unit_rate"]))})
    totals = [("SOUS-TOTAL", ""), ("TAUX TVA", ""), ("TVA", ""), ("AUTRES", ""), ("TOTAL", "")]
    offsets = h.get("offsets") or []
    if offsets: totals += [("", "")] * (len(offsets) + 1)      # one row per imputation + NET À PAYER (TOTAL FACTURE replaces TOTAL)
    fixed = h.get("note") if h.get("note") and note_fits(h["note"]) else None
    _first_page(d, h, "", [("", "", None)] * 3, table, totals, [h["note"]] if h.get("note") and not fixed else [], note_line=fixed)
    return d.low


def render_invoice(h, annex, issued=True):
    """h: frozen-style header (see invoice_service.live_data); annex: cumulative entries up to period_to."""
    d = Doc(placeholders=not issued)
    a = h["amounts"]
    if issued: date_value = dmy(h["invoice_date"])
    elif h.get("invoice_date"): date_value = dmy(h["invoice_date"]) + " (prévue)"
    else: date_value = "(date d'émission)"
    ref_rows = [("Date :", date_value, None),
                ("N° Facture :", h["number"] if issued else (f"{h['number']} (proposé)" if h.get("number") else "(attribué à l'émission)"), None),
                ("PO:", h.get("po") or "", None)]
    table = {"head": unit_heads(h["unit"]),
             "lines": [{"description": h.get("description") or h["project"], "qty": qty_label(h["qty"]), "rate": rate_money(h["unit_rate"]), "amount": money(a["ht"]),
                        "period": period_line(h["period_from"], h["period_to"])}]}
    for ln in h.get("lines") or ():       # rc37 (P1): manual lines, printed from the header (an issued invoice prints its frozen copy, never the table)
        table["lines"].append({"manual": True, "description": ln["description"], "qty": manual_qty_text(ln, h["unit"]), "rate": rate_money(ln["unit_rate"]),
                               "amount": money(rules.line_amount(ln["qty"], ln["unit_rate"]))})
    subtotal = a["ht"] + a.get("lines_ht", 0)
    totals = [("SOUS-TOTAL", money(subtotal)), ("TAUX TVA", num(h["vat"]) + "%"), ("TVA", money(a["tva"], True)),
              (other_label(h, a["other"]), money(a["other"], True)), ("TOTAL", money(a["ttc"]))]
    offsets = h.get("offsets") or []
    if offsets:
        # TOTAL stays the invoiced amount (VAT unchanged); the credit note is a settlement deducted from what is due
        totals[-1] = ("TOTAL FACTURE", money(a["ttc"]))
        totals += [(f"Imputation note de crédit {o['reference']}", "- " + money(o["amount"])) for o in offsets]
        totals.append(("NET À PAYER", money(h["net_due"])))
    # D6 (a): the period is in the DESCRIPTION cell, no longer under the totals. E-4 (B): the note takes its fixed one-line zone; a longer note (draft saved
    # before the limit) still prints whole, below, and fails check 11 until shortened
    fixed = h.get("note") if h.get("note") and note_fits(h["note"]) else None
    extra = [h["note"]] if h.get("note") and not fixed else []
    _first_page(d, h, "FACTURE" if issued else "FACTURE — BROUILLON", ref_rows, table, totals, extra, note_line=fixed, ref_pitch=REF_ROW_PITCH if issued else DRAFT_REF_ROW_PITCH)
    if not issued: d.text(W / 2, 30, "BROUILLON — document non émis, sans valeur comptable", size=9, color=RED, align="center")
    if not issued and h.get("checks_failed"):
        d.text(W / 2, 42, "Contrôles avant émission en échec : n° " + ", ".join(str(n) for n in h["checks_failed"]) + " (voir l'écran d'émission)", size=8, color=RED, align="center")
    period = (h["period_from"], h["period_to"]) if h.get("period_from") and h.get("period_to") else None
    plan = annex_plan(annex, period); n = len(plan) + 1
    mixed = any(pl[5] != "P" for pl in plan)            # captions only when the annex holds history before the period (or rows billed elsewhere)
    elsewhere = ", ".join(h.get("period_billed_elsewhere") or [])
    for k, (ym, rows, last, total, part, sc, partial) in enumerate(plan, 1):
        d.c.showPage(); d.c.setPageSize(landscape(A4))
        cap = None
        if mixed:
            cap = ("Prestations de la période facturée" if sc == "P"
                   else f"Déjà facturé par la facture {elsewhere} (date corrigée depuis) — non facturé ici (information)" if sc == "F"
                   else "Historique cumulatif — antérieur à la période facturée (information)")
        _timesheet_page(d, h, ym, rows, last, total, part > 0, cap, partial); _page_number(d, k, n)
    d.c.showPage(); d.c.setPageSize(landscape(A4))
    _summary_page(d, h); _page_number(d, n, n)
    return d.finish(), d.missing


def _credit_lines(h, a, inv, label_prefix):
    """Line table of a credit / cancellation: the service part, and the « AUTRES » part when there is one
    (an AUTRES-only credit no longer prints a 0,00 service line)."""
    lines = []
    credited = h.get("lines") or ()        # rc38: manual lines credited by the note (absent from the notes frozen before rc38)
    if Decimal(str(a["ht"])) != 0 or (Decimal(str(a["other"])) == 0 and not credited):
        lines.append({"description": h.get("description") or "", "qty": qty_label(h["qty"]) if h.get("qty") else "",
                      "rate": rate_money(h["unit_rate"]) if h.get("qty") else "", "amount": money(a["ht"])})
    for ln in credited:      # printed under the service line like on the invoice (same rows, no quantity / unit price: the credit is an amount)
        lines.append({"manual": True, "description": ln["description"], "qty": "", "rate": "", "amount": money(ln["amount"])})
    if Decimal(str(a["other"])) != 0:
        lines.append({"description": other_label(dict(h, other_label=inv.get("other_label")), a["other"], label_prefix), "amount": money(a["other"])})
    return lines


def render_credit_note(h, issued=True):
    """h: credit-note header with the original invoice's frozen header in h['invoice']."""
    d = Doc(placeholders=not issued)
    _credit_note_page(d, h, issued)
    return d.finish(), d.missing


def credit_page_bottom(h):
    """Lowest baseline of the body of the credit note's page (dry rendering, as first_page_bottom does for an invoice): refused above PAGE_ONE_LIMIT when the note is created
    and again when it is issued."""
    d = Doc(placeholders=False)
    _credit_note_page(d, dict(h, reference=h.get("reference") or "NC", issued_at=h.get("issued_at") or rules.utc_now_iso()), True)
    return d.low


def _credit_note_page(d, h, issued):
    inv = h["invoice"]; a = h["amounts"]
    title = "NOTE DE CRÉDIT" if issued else "NOTE DE CRÉDIT — BROUILLON"
    ref_rows = [("Date :", dmy(h["issued_at"]) if issued else "(date d'émission)", None),
                ("N° Note de crédit :", h["reference"] if issued else "(attribué à l'émission)", None),
                ("Facture d'origine :", f"{inv['number']} du {dmy(inv['invoice_date'])}", None),
                ("PO:", inv.get("po") or "", None)]
    table = {"head": unit_heads(inv.get("unit")), "lines": _credit_lines(h, a, inv, "AUTRES")}
    totals = [("SOUS-TOTAL CRÉDITÉ", money(Decimal(str(a["ht"])) + Decimal(str(a.get("lines_ht") or 0)), True)), ("TAUX TVA", num(h["vat"]) + "%"), ("TVA", money(a["tva"], True))]
    if Decimal(str(a["other"])) != 0:
        totals.append((other_label(dict(h, other_label=inv.get("other_label")), a["other"], "AUTRES CRÉDITÉ"), money(a["other"])))
    totals.append(("TOTAL EN VOTRE FAVEUR", money(a["ttc"])))
    extra = [f"Motif : {h.get('reason') or ''}", f"Note de crédit relative à la facture {inv['number']} du {dmy(inv['invoice_date'])} (facture d'origine inchangée)."]
    if h.get("qty") and rounded_line(h["qty"], h["unit_rate"]) != Decimal(str(a["ht"])):
        extra.append("Montant ajusté au solde créditable exact de la facture d'origine (écart d'arrondi).")
    rep = h.get("replaces")
    if rep: extra.append(f"Remplace la note de crédit {rep['reference']}" + (f", annulée par {rep['cancel_ref']}." if rep.get("cancel_ref") else "."))
    treatment = h.get("treatment")
    if treatment == "remboursement":
        if h.get("refund_due_on"): extra.append(f"Mode de traitement : remboursement — {money(a['ttc'])} vous sera remboursé au plus tard le {dmy(h['refund_due_on'])}.")
        elif not issued and h.get("refund_delay_days") is not None: extra.append(f"Mode de traitement : remboursement — {money(a['ttc'])}, sous {h['refund_delay_days']} jour(s) après émission.")
        else: extra.append(f"Mode de traitement : remboursement — {money(a['ttc'])} vous sera remboursé (sans délai fixé).")
    elif treatment == "compensation":
        extra.append(f"Mode de traitement : compensation — {money(a['ttc'])} imputé sur une prochaine facture.")
    elif d.placeholders:
        d.text(210, 470, "", size=7.5, label="Mode de traitement (remboursement ou compensation)")
    hh = dict(inv, issuer=h["issuer"])
    # no payment instructions: the amount is in the client's favour
    _first_page(d, hh, title, ref_rows, table, totals, extra, payment=False, ref_pitch=REF_ROW_PITCH if issued else DRAFT_REF_ROW_PITCH)
    if not issued: d.text(W / 2, 30, "BROUILLON — document non émis, sans valeur comptable", size=9, color=RED, align="center")


def render_cancellation(h):
    """Cancellation document of an issued credit note. h: reference, reason, issued_at, note (frozen note header), invoice, issuer."""
    d = Doc(placeholders=False); note = h["note"]; inv = h["invoice"]; a = {k: Decimal(str(v)) for k, v in note["amounts"].items()}
    ref_rows = [("Date :", dmy(h["issued_at"]), None), ("N° Annulation :", h["reference"], None),
                ("Note de crédit annulée :", f"{note['reference']} du {dmy(note['issued_at'])}", None),
                ("Facture d'origine :", f"{inv['number']} du {dmy(inv.get('invoice_date') or inv.get('issued_at') or '')}", None), ("PO:", inv.get("po") or "", None)]
    lines = _credit_lines(dict(note, description=f"Annulation de la note de crédit {note['reference']}"), a, inv, "AUTRES ANNULÉ")
    totals = [("SOUS-TOTAL ANNULÉ", money(a["ht"] + a.get("lines_ht", Decimal(0)), True)), ("TAUX TVA", num(note["vat"]) + "%"), ("TVA", money(a["tva"], True))]
    if a["other"] != 0: totals.append((other_label(dict(note, other_label=inv.get("other_label")), a["other"], "AUTRES ANNULÉ"), money(a["other"])))
    totals.append(("TOTAL ANNULÉ", money(a["ttc"])))
    extra = [f"Motif : {h['reason']}", f"La note de crédit {note['reference']} est annulée et sans effet ; aucun montant n'est dû à ce titre."]
    # rc6 (A2): the mode of the cancelled note, from its frozen copy; cancellation is allowed only with nothing refunded or imputed
    mode = {"remboursement": "remboursement", "compensation": "compensation sur facture ultérieure"}.get(note.get("treatment"))
    if mode:
        done = "aucun remboursement en vigueur" if note.get("treatment") == "remboursement" else "aucune imputation en vigueur"
        extra.append(f"Mode de traitement de la note annulée : {mode} ({done}).")
    extra += [
             f"Facture d'origine {inv['number']} inchangée. Une correction éventuelle fait l'objet d'une nouvelle note de crédit."]
    _first_page(d, dict(inv, issuer=h["issuer"]), "ANNULATION DE NOTE DE CRÉDIT", ref_rows, {"head": unit_heads(inv.get("unit")), "lines": lines},
                totals, extra, payment=False, thanks=False)
    return d.finish(), d.missing
