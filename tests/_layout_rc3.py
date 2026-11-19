# Frozen copy of the V9.2-rc3 PDF layout (app/pdf_layout.py before rc4), used only by tests/test_rc4.py as a
# non-regression oracle: rc4 changes presentation, never the printed values.
"""Invoice and credit-note PDF layout modelled on the reference invoice 2026-09.

Page 1 (A4 portrait): logo, title, date/number/PO block, issuer and billing addresses,
one line table, SOUS-TOTAL / TAUX TVA / TVA / AUTRES / TOTAL, payment block, footer.
Annex (A4 landscape): one "Feuille de temps" per month, cumulative up to the period end.
Summary page (A4 landscape): PROJET / Dates / Client / Num projet / PO / NB J PO / NB J.
Missing data is printed as a red [À COMPLÉTER : …] marker, never invented.
"""
import base64, io
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from reportlab.lib.colors import Color, HexColor, black
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

GREY = HexColor("#8a8a8a"); BAND = HexColor("#a6a6a6"); LIGHT = HexColor("#ececec"); RED = HexColor("#c62828")
BLUE = HexColor("#4f81bd"); PURPLE = HexColor("#9b19f5")
MONTHS = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"]
W, H = A4


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
        self.buf = io.BytesIO(); self.c = canvas.Canvas(self.buf, pagesize=A4); self.missing = []; self.placeholders = placeholders

    def text(self, x, top, s, size=8, font="Helvetica", color=black, align="left", label=None):
        """Draw s at `top` points from the top of the current page; empty + label → red placeholder."""
        c = self.c; h = c._pagesize[1]
        if not s and label:
            self.missing.append(label)
            if not self.placeholders: return
            s = f"[À COMPLÉTER : {label}]"; color = RED
        c.setFont(font, size); c.setFillColor(color)
        {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align](x, h - top, s)
        c.setFillColor(black)

    def fit(self, s, width, size, font="Helvetica"):
        """Truncate with an ellipsis so a cell never overlaps the next column."""
        s = s or ""
        if self.c.stringWidth(s, font, size) <= width: return s
        while s and self.c.stringWidth(s + "…", font, size) > width: s = s[:-1]
        return s + "…"

    def lines(self, x, top, block, step=12, size=8, label=None, **kw):
        rows = [l.strip() for l in (block or "").splitlines() if l.strip()]
        if not rows:
            self.text(x, top, "", size=size, label=label, **kw); return top + step
        for r in rows:
            self.text(x, top, r, size=size, **kw); top += step
        return top

    def hline(self, x1, x2, top, color=black, width=0.6):
        h = self.c._pagesize[1]; self.c.setStrokeColor(color); self.c.setLineWidth(width); self.c.line(x1, h - top, x2, h - top); self.c.setStrokeColor(black)

    def rect(self, x, top, w, hgt, fill):
        h = self.c._pagesize[1]; self.c.setFillColor(fill); self.c.rect(x, h - top - hgt, w, hgt, stroke=0, fill=1); self.c.setFillColor(black)

    def finish(self):
        self.c.save(); return self.buf.getvalue()


def _logo(d, logo_b64):
    if logo_b64:
        try:
            d.c.drawImage(ImageReader(io.BytesIO(base64.b64decode(logo_b64))), 48, H - 160, width=110, height=110, preserveAspectRatio=True, mask="auto")
            return
        except Exception:
            pass
    if d.placeholders: d.text(55, 100, "[Logo à fournir — Paramètres]", size=7, color=GREY)


def _first_page(d, h, title, ref_rows, table, totals, extra_lines=(), payment=True, thanks=True):
    s = h["issuer"]
    _logo(d, s.get("logo_png_b64"))
    d.text(550, 70, title, size=20, align="right")
    top = 96
    for label, value, field in ref_rows:
        d.text(208, top, label); d.text(387, top, value, label=field); top += 12
    # short placeholder labels: the issuer column is ~150 pt wide
    d.lines(50, 180, s.get("issuer_name"), label="Raison sociale", size=8)
    d.lines(50, 192, s.get("issuer_address"), label="Adresse émetteur", size=8)
    d.text(208, 180, "Adresse de facturation :")
    nxt = d.lines(387, 180, h.get("billing_contact")) if h.get("billing_contact") else 180
    d.lines(387, nxt, h.get("billing_address"), label="Adresse de facturation")
    # line table
    head, unit_head, rate_head = table["head"]
    d.text(50, 290, "DESCRIPTION"); d.text(262, 290, unit_head, align="right"); d.text(375, 290, rate_head, align="right"); d.text(550, 290, "MONTANT", align="right")
    desc = table["description"] or ""
    words, row, out = desc.split(), "", []
    for wd in words:
        if d.c.stringWidth(row + " " + wd, "Helvetica", 8) > 150 and row: out.append(row); row = wd
        else: row = (row + " " + wd).strip()
    out.append(row)
    for i, r in enumerate(out[:4]): d.text(50, 316 + i * 11, r)
    d.text(262, 322, table["qty"], align="right"); d.text(375, 322, table["rate"], align="right"); d.text(550, 322, table["amount"], align="right")
    top = 352
    for i, (label, value) in enumerate(totals):
        last = i == len(totals) - 1
        if last: d.rect(208, top - 10, 345, 15, LIGHT)
        d.hline(208, 553, top - 11 if i else top - 11, color=HexColor("#d9d9d9"), width=0.4)
        d.text(212, top, label, font="Helvetica-Bold" if last else "Helvetica"); d.text(550, top, value, align="right", font="Helvetica-Bold" if last else "Helvetica")
        top += 22
    top += 6
    for line in extra_lines:
        d.text(208, top, line, size=7.5, color=HexColor("#444444")); top += 11
    if thanks and s.get("thanks_text"): d.text(550, max(top + 14, 476), s["thanks_text"], font="Helvetica-Oblique", align="right")
    if payment:
        pay = max(top + 50, 541)
        d.text(50, pay, s.get("payment_terms") or "", label="Conditions de paiement")
        d.text(50, pay + 22, "Titulaire: " + (s.get("account_holder") or "")) if s.get("account_holder") else d.text(50, pay + 22, "", label="Titulaire du compte")
        d.text(50, pay + 44, "IBAN: " + (s.get("iban") or "")) if s.get("iban") else d.text(50, pay + 44, "", label="IBAN")
        d.text(50, pay + 66, "BIC: " + s["bic"]) if s.get("bic") else d.text(50, pay + 66, "", label="BIC")
    foot = []
    if s.get("issuer_rc"): foot.append(f"N° registre commerce: {s['issuer_rc']}")
    if s.get("issuer_vat_number"): foot.append(f"N° TVA: {s['issuer_vat_number']}")
    if s.get("iban"): foot.append(f"IBAN: {s['iban']}")
    d.text(W / 2, 810, "   ".join(foot), size=7, color=GREY, align="center")
    if not s.get("issuer_rc"): d.text(W / 2, 821, "", size=6.5, align="center", label="N° registre du commerce (pied de page)")


def rounded_line(qty, rate):
    return (Decimal(str(qty)) * Decimal(str(rate))).quantize(Decimal("0.01"), ROUND_HALF_UP)


OTHER_VAT_SHORT = {"hors_tva": "hors TVA", "soumis": "soumis à TVA"}


def other_label(h, amount, prefix="AUTRES"):
    """« AUTRES » line label; its VAT treatment is printed whenever the line carries an amount."""
    label = prefix + (f" — {h['other_label']}" if h.get("other_label") else "")
    if Decimal(str(amount or 0)) != 0:
        label += f" ({OTHER_VAT_SHORT.get(h.get('other_vat_mode') or 'hors_tva', 'hors TVA')})"
    return label


def render_invoice(h, annex, issued=True):
    """h: frozen-style header (see invoice_service.live_data); annex: cumulative entries up to period_to."""
    d = Doc(placeholders=not issued)
    a = h["amounts"]
    hour = h["unit"] == "hour"
    title = "FACTURE" if issued else "FACTURE — BROUILLON"
    ref_rows = [("Date :", dmy(h["invoice_date"]) if issued else "(attribuée à l'émission)", None),
                ("N° Facture :", h["number"] if issued else "(attribué à l'émission)", None),
                ("PO:", h.get("po") or "", None)]
    table = {"head": None, "description": h.get("description") or h["project"],
             "qty": num(h["qty"]), "rate": money(h["unit_rate"]), "amount": money(a["ht"])}
    table["head"] = (None, "HEURES" if hour else "JOUR", "COUT HORAIRE" if hour else "COUT JOURNALIER")
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
    _first_page(d, h, title, ref_rows, table, totals, extra)
    if not issued: d.text(W / 2, 30, "BROUILLON — document non émis, sans valeur comptable", size=9, color=RED, align="center")
    # annex: one "Feuille de temps" per month
    by_month = {}
    for e in annex: by_month.setdefault(e["work_date"][:7], []).append(e)
    LW = landscape(A4)[0]
    cols = [(43, "Date(s)", "left"), (193, "Motif", "center"), (336, "Projet", "left"), (433, "Numéro de projet", "left"),
            (560, "Heure début", "right"), (655, "Heure fin", "right"), (789, "Heures de travail", "right")]
    for ym in sorted(by_month):
        rows = by_month[ym]; total = sum(Decimal(str(e["hours"])) for e in rows); i = 0
        while i < len(rows) or i == 0:
            d.c.showPage(); d.c.setPageSize(landscape(A4))
            d.rect(43, 28, 746, 26, BAND); d.hline(43, 789, 28, color=BLUE, width=1.5)
            d.text(48, 48, "Feuille de temps", size=15, color=Color(1, 1, 1))
            d.text(43, 78, month_label(ym), size=10)
            d.text(43, 100, "Total des heures", size=7); d.text(43, 109, "de travail du mois", size=7)
            d.text(43, 128, num(total), size=12); d.hline(43, 789, 136, color=GREY, width=0.4)
            for x, label, al in cols: d.text(x, 166, label, size=7, align=al)
            d.hline(43, 789, 170, width=0.8)
            top = 182
            while i < len(rows) and top < 560:
                e = rows[i]
                vals = [dmy(e["work_date"], "/"), (e["description"] or "")[:40], h["project"], h.get("project_number") or "",
                        clock_decimal(e["start_time"]), clock_decimal(e["end_time"]), num(e["hours"])]
                vals[1] = d.fit(vals[1], 130, 7); vals[2] = d.fit(vals[2], 92, 7); vals[3] = d.fit(vals[3], 70, 7)
                for (x, _, al), v in zip(cols, vals): d.text(x if x != 43 else 125, top, v, size=7, align="center" if x == 43 else al)
                top += 12; i += 1
            if i >= len(rows):
                d.hline(43, 789, top - 8, width=0.8); d.text(43, top + 2, "Total", size=7); d.text(789, top + 2, num(total), size=7, align="right")
            if not rows: break
    # summary page
    d.c.showPage(); d.c.setPageSize(landscape(A4))
    d.text(48, 61, h["period_to"][:4], size=13, font="Helvetica-Bold", color=PURPLE)
    heads = [(48, "PROJET"), (168, "Dates"), (268, "Client"), (368, "Num projet"), (458, "PO"), (640, "NB J PO"), (715, "NB J")]
    d.hline(46, 781, 66, width=0.8)
    for x, t in heads: d.text(x, 76, t, size=7.5, font="Helvetica-Bold")
    d.hline(46, 781, 80, width=0.6)
    vals = [h["project"], h.get("dates_label") or "", h.get("client") or "", h.get("project_number") or "", h.get("po") or "",
            days_label(h.get("ordered_days") or 0), days_label(h["consumed_days"])]
    edges = [x for x, _ in heads[1:]] + [781]
    for (x, _), v, nxt in zip(heads, vals, edges): d.text(x, 90, d.fit(v, nxt - x - 6, 7.5), size=7.5)
    d.hline(46, 781, 94, width=0.8)
    if h.get("reliquat_treatment") == "offert" and h.get("reliquat_days"):
        d.text(48, 112, f"Dont {num(h['reliquat_days'])} jour(s) réalisé(s) offert(s), non facturé(s).", size=7.5)
    return d.finish(), d.missing


def render_credit_note(h, issued=True):
    """h: credit-note header with the original invoice's frozen header in h['invoice']."""
    d = Doc(placeholders=not issued); inv = h["invoice"]; a = h["amounts"]
    title = "NOTE DE CRÉDIT" if issued else "NOTE DE CRÉDIT — BROUILLON"
    ref_rows = [("Date :", dmy(h["issued_at"]) if issued else "(attribuée à l'émission)", None),
                ("N° Note de crédit :", h["reference"] if issued else "(attribué à l'émission)", None),
                ("Facture d'origine :", f"{inv['number']} du {dmy(inv['invoice_date'])}", None),
                ("PO:", inv.get("po") or "", None)]
    # amount-only credit: no quantity / rate printed (the reference layout has no meaningful value there)
    table = {"head": (None, "JOUR", "COUT JOURNALIER"), "description": h.get("description") or "",
             "qty": num(h["qty"]) if h.get("qty") else "", "rate": money(h["unit_rate"]) if h.get("qty") else "", "amount": money(a["ht"])}
    totals = [("SOUS-TOTAL CRÉDITÉ", money(a["ht"])), ("TAUX TVA", num(h["vat"]) + "%"), ("TVA", money(a["tva"], True))]
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
        else: extra.append(f"Mode de traitement : remboursement — {money(a['ttc'])} vous sera remboursé.")
    elif treatment == "compensation":
        extra.append(f"Mode de traitement : compensation — {money(a['ttc'])} imputé sur une prochaine facture.")
    elif d.placeholders:
        d.text(208, 470, "", size=7.5, label="Mode de traitement (remboursement ou compensation)")
    hh = dict(inv, issuer=h["issuer"])
    # no payment instructions: the amount is in the client's favour (refund terms are a business decision)
    _first_page(d, hh, title, ref_rows, table, totals, extra, payment=False)
    if not issued: d.text(W / 2, 30, "BROUILLON — document non émis, sans valeur comptable", size=9, color=RED, align="center")
    return d.finish(), d.missing


def render_cancellation(h):
    """Cancellation document of an issued credit note. h: reference, reason, issued_at, note (frozen note header), invoice, issuer."""
    d = Doc(placeholders=False); note = h["note"]; inv = h["invoice"]; a = {k: Decimal(str(v)) for k, v in note["amounts"].items()}
    ref_rows = [("Date :", dmy(h["issued_at"]), None), ("N° Annulation :", h["reference"], None),
                ("Note de crédit annulée :", f"{note['reference']} du {dmy(note['issued_at'])}", None),
                ("Facture d'origine :", f"{inv['number']} du {dmy(inv.get('invoice_date') or inv.get('issued_at') or '')}", None), ("PO:", inv.get("po") or "", None)]
    table = {"head": (None, "JOUR", "COUT JOURNALIER"), "description": f"Annulation de la note de crédit {note['reference']}",
             "qty": num(note["qty"]) if note.get("qty") else "", "rate": money(note["unit_rate"]) if note.get("qty") else "", "amount": money(a["ht"])}
    totals = [("SOUS-TOTAL ANNULÉ", money(a["ht"])), ("TAUX TVA", num(note["vat"]) + "%"), ("TVA", money(a["tva"], True))]
    if a["other"] != 0: totals.append((other_label(dict(note, other_label=inv.get("other_label")), a["other"], "AUTRES ANNULÉ"), money(a["other"])))
    totals.append(("TOTAL ANNULÉ", money(a["ttc"])))
    extra = [f"Motif : {h['reason']}", f"La note de crédit {note['reference']} est annulée et sans effet ; aucun montant n'est dû à ce titre.",
             f"Facture d'origine {inv['number']} inchangée. Une correction éventuelle fait l'objet d'une nouvelle note de crédit."]
    _first_page(d, dict(inv, issuer=h["issuer"]), "ANNULATION DE NOTE DE CRÉDIT", ref_rows, table, totals, extra, payment=False, thanks=False)
    return d.finish(), d.missing
