# Frozen copy of the rc5 PDF layout (non-regression oracle for rc6). Do not edit.
"""Invoice and credit-note PDF layout modelled on the reference invoice 2026-09.

Page 1 (A4 portrait): logo, title, date/number/PO block, issuer and billing addresses (with the
client's legal identity), line table, SOUS-TOTAL / TAUX TVA / TVA / AUTRES / TOTAL, payment block, footer.
Annex (A4 landscape): one "Feuille de temps" per month, cumulative up to the period end, ruled like the
reference workbook, numbered "Page x of y" (numbering starts on the first annex page, as in the reference).
Summary page (A4 landscape): framed PROJET / Dates / Client / Num projet / PO / NB J PO / NB J.
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


def money(v, dash_zero=False):
    return "- CHF" if dash_zero and Decimal(str(v)) == 0 else f"{num(v)} CHF"


def days_label(v):
    s = num(v)
    return s[:-3] if s.endswith(",00") else s


def dmy(iso, sep="."):
    return date.fromisoformat(iso[:10]).strftime(f"%d{sep}%m{sep}%Y") if iso else ""


def clock_decimal(hhmm):
    if not hhmm: return ""
    p = [int(x) for x in hhmm.split(":")]
    return num(Decimal(p[0]) + Decimal(p[1]) / 60 + (Decimal(p[2]) / 3600 if len(p) > 2 else 0))


def month_label(ym):
    return f"{MONTHS[int(ym[5:7]) - 1]}-{ym[2:4]}"


class Doc:
    def __init__(self, placeholders=True):
        # placeholders only on drafts: an issued document never shows [À COMPLÉTER] markers
        self.buf = io.BytesIO(); self.c = canvas.Canvas(self.buf, pagesize=A4, initialFontName=BODY, initialFontSize=8); self.missing = []; self.placeholders = placeholders

    def text(self, x, top, s, size=8, font=BODY, color=black, align="left", label=None):
        """Draw s with its baseline `top` points from the top of the current page; empty + label → red placeholder."""
        c = self.c; h = c._pagesize[1]
        if not s and label:
            self.missing.append(label)
            if not self.placeholders: return
            s = f"[À COMPLÉTER : {label}]"; color = RED
        c.setFont(font, size); c.setFillColor(color)
        {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align](x, h - top, s)
        c.setFillColor(black)

    def fit(self, s, width, size, font=BODY):
        """Truncate with an ellipsis so a cell never overlaps the next column."""
        s = s or ""
        if self.c.stringWidth(s, font, size) <= width: return s
        while s and self.c.stringWidth(s + "…", font, size) > width: s = s[:-1]
        return s + "…"

    def lines(self, x, top, block, step=12.48, size=8, label=None, **kw):
        rows = [l.strip() for l in (block or "").splitlines() if l.strip()]
        if not rows:
            self.text(x, top, "", size=size, label=label, **kw); return top + step
        for r in rows:
            self.text(x, top, r, size=size, **kw); top += step
        return top

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


def _wrap(d, text, width, font=BODY, size=8):
    words, row, out = (text or "").split(), "", []
    for wd in words:
        if d.c.stringWidth(row + " " + wd, font, size) > width and row: out.append(row); row = wd
        else: row = (row + " " + wd).strip()
    out.append(row)
    return out


def _first_page(d, h, title, ref_rows, table, totals, extra_lines=(), payment=True, thanks=True):
    s = h["issuer"]
    _logo(d, s.get("logo_png_b64"))
    d.text(554.3, 74.5, title, size=20, align="right")
    top = 99.4
    for label, value, field in ref_rows:
        d.text(210, top, label); d.text(390.7, top, value, label=field); top += 11.1
    # short placeholder labels: the issuer column is ~150 pt wide
    nxt = d.lines(50.3, 185.4, s.get("issuer_name"), label="Raison sociale")
    d.lines(50.3, nxt, s.get("issuer_address"), label="Adresse émetteur")
    d.text(210, 185.4, "Adresse de facturation :")
    nxt = d.lines(390.7, 185.4, h.get("billing_contact")) if h.get("billing_contact") else 185.4
    nxt = d.lines(390.7, nxt, h.get("billing_address"), label="Adresse de facturation")
    for line in legal_identity_lines(h):
        d.text(390.7, nxt, line); nxt += 12.48
    # line table: one row per line (the invoice has one; a credit note may add its « AUTRES » part)
    _, unit_head, rate_head = table["head"]
    d.text(50.3, 295.6, "DESCRIPTION"); d.text(264.3, 295.6, unit_head, align="right"); d.text(380.6, 295.6, rate_head, align="right"); d.text(555.4, 295.6, "MONTANT", align="right")
    top = 317.9
    for line in table["lines"]:
        rows = _wrap(d, line["description"], 150)[:4]
        mid = top + 5.1 * (min(len(rows), 2) - 1)
        for i, r in enumerate(rows): d.text(50.3, top + i * 10.3, r)
        d.text(261.9, mid, line.get("qty", ""), align="right"); d.text(384.0, mid, line.get("rate", ""), align="right"); d.text(552.4, mid, line["amount"], align="right")
        top += max(len(rows), 2) * 10.3 + 6
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
    for line in extra_lines:
        d.text(210, top, line, size=7.5, color=NOTE); top += 11
    if thanks and s.get("thanks_text"): d.text(552.0, max(top + 14, 482.5), s["thanks_text"], font=ITALIC, align="right")
    if payment:
        pay = max(top + 50, 549.2)
        d.text(50.3, pay, s.get("payment_terms") or "", label="Conditions de paiement")
        d.text(50.3, pay + 22.08, "Titulaire: " + (s.get("account_holder") or "")) if s.get("account_holder") else d.text(50.3, pay + 22.08, "", label="Titulaire du compte")
        d.text(50.3, pay + 44.16, "IBAN: " + (s.get("iban") or "")) if s.get("iban") else d.text(50.3, pay + 44.16, "", label="IBAN")
        d.text(50.3, pay + 66.24, "BIC: " + s["bic"]) if s.get("bic") else d.text(50.3, pay + 66.24, "", label="BIC")
    foot = []
    if s.get("issuer_rc"): foot.append(f"N° registre commerce: {s['issuer_rc']}")
    if s.get("issuer_vat_number"): foot.append(f"N° TVA: {s['issuer_vat_number']}")
    if s.get("iban"): foot.append(f"IBAN: {s['iban']}")
    d.text(W / 2, 816.4, "   ".join(foot), color=GREY, align="center")
    if not s.get("issuer_rc"): d.text(W / 2, 826, "", size=6.5, align="center", label="N° registre du commerce (pied de page)")


def rounded_line(qty, rate):
    return (Decimal(str(qty)) * Decimal(str(rate))).quantize(Decimal("0.01"), ROUND_HALF_UP)


OTHER_VAT_SHORT = {"hors_tva": "hors TVA", "soumis": "soumis à TVA"}


def other_label(h, amount, prefix="AUTRES"):
    """« AUTRES » line label; its VAT treatment is printed whenever the line carries an amount."""
    label = prefix + (f" — {h['other_label']}" if h.get("other_label") else "")
    if Decimal(str(amount or 0)) != 0:
        label += f" ({OTHER_VAT_SHORT.get(h.get('other_vat_mode') or 'hors_tva', 'hors TVA')})"
    return label


def unit_heads(unit):
    return (None, "HEURES", "COUT HORAIRE") if unit == "hour" else (None, "JOUR", "COUT JOURNALIER")


# --- annex ----------------------------------------------------------------------------------------
ROWS_PER_PAGE = 21          # 21 rows + the total row fit above the page number at the reference row pitch
ROW_PITCH = 16.76
A_LEFT, A_RIGHT = 43.8, 809.9
HEAD_COLS = [(45.5, "Date(s)", "left"), (207.6, "Motif", "center"), (343.7, "Projet", "left"), (442.1, "Numéro de projet", "left"),
             (540.5, "Heure début", "left"), (636.3, "Heure fin", "left"), (724.8, "Heures de travail", "left")]


def annex_plan(annex):
    """[(month, rows on this page, month's last page?, month total, page index within the month)], computed
    before drawing so every page can print its "Page x of y"."""
    by_month = {}
    for e in annex: by_month.setdefault(e["work_date"][:7], []).append(e)
    plan = []
    for ym in sorted(by_month):
        rows = by_month[ym]; total = sum(Decimal(str(e["hours"])) for e in rows)
        chunks = [rows[i:i + ROWS_PER_PAGE] for i in range(0, len(rows), ROWS_PER_PAGE)]
        for k, chunk in enumerate(chunks): plan.append((ym, chunk, k == len(chunks) - 1, total, k))
    return plan


def _page_number(d, k, n):
    d.text(LW / 2, 569.4, f"Page {k} of {n}", size=9, font=SHEET, align="center")


def _timesheet_page(d, h, ym, rows, last, total, cont):
    d.bar(A_LEFT, A_RIGHT, 29.8, 58.7, BAND); d.bar(A_LEFT, A_RIGHT, 28.1, 30.5, BLUE)
    d.text(46.8, 52.3, "Feuille de temps", size=19.7, font=SHEET_LIGHT, color=Color(1, 1, 1))
    d.text(46.0, 83.2, month_label(ym) + (" (suite)" if cont else ""), size=13.1, font=SHEET_LIGHT)
    d.text(45.6, 108.4, "Total des heures", size=9.8, font=SHEET_LIGHT); d.text(45.6, 121.2, "de travail du mois", size=9.8, font=SHEET_LIGHT)
    d.text(46.4, 145.0, num(total), size=16.4, font=SHEET_LIGHT)
    d.bar(A_LEFT, A_RIGHT, 150.0, 150.8, BLUE)
    for x, label, al in HEAD_COLS: d.text(x, 179.8, label, size=9, font=SHEET, align=al)
    d.bar(44.6, A_RIGHT, 183.0, 184.6)                       # header rule (thick, black)
    top = 196.5
    project = h.get("project_short") or h["project"]
    for e in rows:
        d.text(172.4, top, dmy(e["work_date"], "/"), size=9, font=SHEET, align="center")
        d.text(204.0, top, d.fit(e["description"] or "", 133, 9, SHEET), size=9, font=SHEET)
        d.text(343.7, top, d.fit(project, 94, 9, SHEET), size=9, font=SHEET)
        d.text(442.1, top, d.fit(h.get("project_number") or "", 94, 9, SHEET), size=9, font=SHEET)
        d.text(633.0, top, clock_decimal(e["start_time"]), size=9, font=SHEET, align="right")
        d.text(721.4, top, clock_decimal(e["end_time"]), size=9, font=SHEET, align="right")
        d.text(808.0, top, num(e["hours"]), size=9, font=SHEET, align="right")
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


def _summary_page(d, h):
    d.text(53.3, 72.8, h["period_to"][:4], size=15, font=SHEET_BOLD, color=PURPLE)
    cols = [52.7, 178.7, 304.7, 361.8, 455.9, 625.3, 706.9]
    heads = ["PROJET", "Dates", "Client", "Num projet", "PO", "NB J PO", "NB J"]
    for t in (74.2, 87.5, 100.8): d.bar(50.9, 786.8, t - 0.42, t + 0.42)
    d.bar(50.5, 51.4, 73.8, 101.3); d.bar(786.4, 787.2, 73.8, 101.3)
    for x, t in zip(cols, heads): d.text(x, 84.6, t, size=10.3, font=SHEET_BOLD)
    # mandate information; on drafts a missing value is flagged, never invented
    vals = [(h.get("project_short") or h["project"], None), (h.get("dates_label") or "", "Dates"), (h.get("client") or "", "Client"),
            (h.get("project_number") or "", "N° projet"), (h.get("po") or "", "PO"), (days_label(h.get("ordered_days") or 0), None), (days_label(h["consumed_days"]), None)]
    edges = cols[1:] + [786.8]
    for x, (v, label), nxt in zip(cols, vals, edges):
        if v: d.text(x, 97.9, d.fit(v, nxt - x - 6, 10.3, SHEET), size=10.3, font=SHEET)
        elif label: d.text(x, 97.9, "", size=6, font=SHEET, label=label)
    if h.get("reliquat_treatment") == "offert" and h.get("reliquat_days"):
        d.text(52.7, 118, f"Dont {num(h['reliquat_days'])} jour(s) réalisé(s) offert(s), non facturé(s).", size=10, font=SHEET)


def render_invoice(h, annex, issued=True):
    """h: frozen-style header (see invoice_service.live_data); annex: cumulative entries up to period_to."""
    d = Doc(placeholders=not issued)
    a = h["amounts"]
    if issued: date_value = dmy(h["invoice_date"])
    elif h.get("invoice_date"): date_value = dmy(h["invoice_date"]) + " (prévue)"
    else: date_value = "(date d'émission)"
    ref_rows = [("Date :", date_value, None),
                ("N° Facture :", h["number"] if issued else "(attribué à l'émission)", None),
                ("PO:", h.get("po") or "", None)]
    table = {"head": unit_heads(h["unit"]),
             "lines": [{"description": h.get("description") or h["project"], "qty": num(h["qty"]), "rate": money(h["unit_rate"]), "amount": money(a["ht"])}]}
    totals = [("SOUS-TOTAL", money(a["ht"])), ("TAUX TVA", num(h["vat"]) + "%"), ("TVA", money(a["tva"], True)),
              (other_label(h, a["other"]), money(a["other"], True)), ("TOTAL", money(a["ttc"]))]
    offsets = h.get("offsets") or []
    if offsets:
        # TOTAL stays the invoiced amount (VAT unchanged); the credit note is a settlement deducted from what is due
        totals[-1] = ("TOTAL FACTURE", money(a["ttc"]))
        totals += [(f"Imputation note de crédit {o['reference']}", "- " + money(o["amount"])) for o in offsets]
        totals.append(("NET À PAYER", money(h["net_due"])))
    extra = [f"Période facturée : du {dmy(h['period_from'])} au {dmy(h['period_to'])}"]
    if h.get("note"): extra.append(h["note"])
    _first_page(d, h, "FACTURE" if issued else "FACTURE — BROUILLON", ref_rows, table, totals, extra)
    if not issued: d.text(W / 2, 30, "BROUILLON — document non émis, sans valeur comptable", size=9, color=RED, align="center")
    plan = annex_plan(annex); n = len(plan) + 1
    for k, (ym, rows, last, total, part) in enumerate(plan, 1):
        d.c.showPage(); d.c.setPageSize(landscape(A4))
        _timesheet_page(d, h, ym, rows, last, total, part > 0); _page_number(d, k, n)
    d.c.showPage(); d.c.setPageSize(landscape(A4))
    _summary_page(d, h); _page_number(d, n, n)
    return d.finish(), d.missing


def _credit_lines(h, a, inv, label_prefix):
    """Line table of a credit / cancellation: the service part, and the « AUTRES » part when there is one
    (an AUTRES-only credit no longer prints a 0,00 service line)."""
    lines = []
    if Decimal(str(a["ht"])) != 0 or Decimal(str(a["other"])) == 0:
        lines.append({"description": h.get("description") or "", "qty": num(h["qty"]) if h.get("qty") else "",
                      "rate": money(h["unit_rate"]) if h.get("qty") else "", "amount": money(a["ht"])})
    if Decimal(str(a["other"])) != 0:
        lines.append({"description": other_label(dict(h, other_label=inv.get("other_label")), a["other"], label_prefix), "amount": money(a["other"])})
    return lines


def render_credit_note(h, issued=True):
    """h: credit-note header with the original invoice's frozen header in h['invoice']."""
    d = Doc(placeholders=not issued); inv = h["invoice"]; a = h["amounts"]
    title = "NOTE DE CRÉDIT" if issued else "NOTE DE CRÉDIT — BROUILLON"
    ref_rows = [("Date :", dmy(h["issued_at"]) if issued else "(date d'émission)", None),
                ("N° Note de crédit :", h["reference"] if issued else "(attribué à l'émission)", None),
                ("Facture d'origine :", f"{inv['number']} du {dmy(inv['invoice_date'])}", None),
                ("PO:", inv.get("po") or "", None)]
    table = {"head": unit_heads(inv.get("unit")), "lines": _credit_lines(h, a, inv, "AUTRES")}
    totals = [("SOUS-TOTAL CRÉDITÉ", money(a["ht"], True)), ("TAUX TVA", num(h["vat"]) + "%"), ("TVA", money(a["tva"], True))]
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
    _first_page(d, hh, title, ref_rows, table, totals, extra, payment=False)
    if not issued: d.text(W / 2, 30, "BROUILLON — document non émis, sans valeur comptable", size=9, color=RED, align="center")
    return d.finish(), d.missing


def render_cancellation(h):
    """Cancellation document of an issued credit note. h: reference, reason, issued_at, note (frozen note header), invoice, issuer."""
    d = Doc(placeholders=False); note = h["note"]; inv = h["invoice"]; a = {k: Decimal(str(v)) for k, v in note["amounts"].items()}
    ref_rows = [("Date :", dmy(h["issued_at"]), None), ("N° Annulation :", h["reference"], None),
                ("Note de crédit annulée :", f"{note['reference']} du {dmy(note['issued_at'])}", None),
                ("Facture d'origine :", f"{inv['number']} du {dmy(inv.get('invoice_date') or inv.get('issued_at') or '')}", None), ("PO:", inv.get("po") or "", None)]
    lines = _credit_lines(dict(note, description=f"Annulation de la note de crédit {note['reference']}"), a, inv, "AUTRES ANNULÉ")
    totals = [("SOUS-TOTAL ANNULÉ", money(a["ht"], True)), ("TAUX TVA", num(note["vat"]) + "%"), ("TVA", money(a["tva"], True))]
    if a["other"] != 0: totals.append((other_label(dict(note, other_label=inv.get("other_label")), a["other"], "AUTRES ANNULÉ"), money(a["other"])))
    totals.append(("TOTAL ANNULÉ", money(a["ttc"])))
    extra = [f"Motif : {h['reason']}", f"La note de crédit {note['reference']} est annulée et sans effet ; aucun montant n'est dû à ce titre.",
             f"Facture d'origine {inv['number']} inchangée. Une correction éventuelle fait l'objet d'une nouvelle note de crédit."]
    _first_page(d, dict(inv, issuer=h["issuer"]), "ANNULATION DE NOTE DE CRÉDIT", ref_rows, {"head": unit_heads(inv.get("unit")), "lines": lines},
                totals, extra, payment=False, thanks=False)
    return d.finish(), d.missing
