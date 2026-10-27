"""Billing rules shared by routes, PDF rendering and forecasts.

Issuer settings, required-field checks, contract position (days) and document numbering.
Nothing here invents legal mentions: missing values are reported, never filled in.
"""
import os, re
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

CENT = Decimal("0.01")

# --- French number format for the screen and messages (rc4, R9): 5 200,00 CHF · 8,15 j ---------------
NNBSP = "\u202f"; NBSP = "\u00a0"


def fr_num(v, places=2):
    if v is None or v == "": return ""
    d = Decimal(str(v)).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
    return ("−" if d < 0 else "") + f"{abs(d):,.{places}f}".replace(",", NNBSP).replace(".", ",")


def fr_g(v):
    """Like '%g' (no useless zeros, at most 6 decimals), with a decimal comma."""
    if v is None or v == "": return ""
    d = Decimal(str(round(float(v), 6))); s = f"{abs(d):f}"
    if "." in s: s = s.rstrip("0").rstrip(".")
    i, _, f = s.partition("."); i = f"{int(i):,}".replace(",", NNBSP)
    return ("−" if d < 0 and s.strip("0.") else "") + i + ("," + f if f else "")


# --- time (RC8): technical timestamps are stored in UTC (naive ISO, 'YYYY-MM-DDTHH:MM:SS', the format already in
# the database); everything shown to a person is in Europe/Zurich, summer / winter time handled by zoneinfo. --------
ZURICH = ZoneInfo("Europe/Zurich")
TS_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?")


def utc_now():
    """Current UTC time, naive, whatever the container's TZ."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def utc_now_iso():
    return utc_now().isoformat(timespec="seconds")


def local_today():
    """Business day in Zurich (invoice date, refund dates, forecasts): after 00:00 in Zurich it is already the next day."""
    return datetime.now(ZURICH).date()


def to_zurich(v):
    """Stored UTC timestamp → aware Zurich datetime (None for a plain date or an unparsable value)."""
    m = TS_RE.fullmatch(str(v or "").strip())
    if not m or not m[4]: return None
    return datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6] or 0), tzinfo=timezone.utc).astimezone(ZURICH)


def local_date(v):
    """Zurich calendar day of a stored UTC timestamp ('YYYY-MM-DD'); a plain date is returned as is."""
    z = to_zurich(v)
    return z.date().isoformat() if z else str(v or "")[:10]


def fr_ts(v):
    """A3 (rc7) + RC8: stored UTC '2026-10-03T13:13:26' → '03.10.2026 à 15:13:26' in Europe/Zurich (CEST +2 / CET +1,
    switched automatically); a plain date '2026-10-03' → '03.10.2026' (no conversion: it is a calendar day). A time
    stored without seconds is shown with :00. Unparsable values are returned unchanged. Display only."""
    s = str(v or "").strip()
    m = TS_RE.fullmatch(s)
    if not m: return s
    if not m[4]: return f"{m[3]}.{m[2]}.{m[1]}"
    return to_zurich(s).strftime("%d.%m.%Y à %H:%M:%S")


def fr_date(v):
    """rc7 (A3): plain ISO date → JJ.MM.AAAA (a timestamp keeps its time, see fr_ts)."""
    return fr_ts(v)


PERIOD_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}) → (\d{4}-\d{2}-\d{2})\b")


def fr_periods_in(text):
    """'2026-07-01 → 2026-07-31' inside a stored label → '01.07.2026 → 31.07.2026' (display only; only date pairs
    around an arrow are touched, so an invoice number such as 2026-07-12 is never reshaped)."""
    return PERIOD_RE.sub(lambda m: f"{fr_date(m[1])} → {fr_date(m[2])}", str(text or ""))


def fr_hm(v):
    """Decimal hours → '3 h 30 min' (nearest minute, display only; the stored value is never rounded)."""
    if v is None or v == "": return ""
    total = int((Decimal(str(v)) * 60).quantize(Decimal(1), ROUND_HALF_UP)); h, m = divmod(total, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def fr_chf(v):
    return "" if v is None or v == "" else fr_num(v) + NBSP + "CHF"

# key: (label, required for issuing, hint)
ISSUER_FIELDS = {
    "issuer_name": ("Raison sociale de l'émetteur", True, ""),
    "issuer_address": ("Adresse de l'émetteur (une ligne par ligne d'adresse)", True, ""),
    "issuer_rc": ("N° registre du commerce", False, "affiché en pied de page"),
    "issuer_vat_number": ("N° TVA (IDE TVA)", False, "obligatoire dès qu'une facture comporte de la TVA"),
    "account_holder": ("Titulaire du compte", True, ""),
    "iban": ("IBAN", True, ""),
    "bic": ("BIC", False, ""),
    "payment_terms": ("Conditions de paiement", True, "texte affiché avant les coordonnées bancaires"),
    "thanks_text": ("Formule de remerciement", False, "facultatif"),
}
PROJECT_REQUIRED = {"client": "Client (nom court)", "billing_address": "Adresse de facturation"}
TREATMENTS = {"offert": "Offert au client", "reporte": "Reporté sur une prochaine facture", "autre": "Autre traitement (préciser)"}


def get_settings(c):
    s = {k: "" for k in ISSUER_FIELDS}
    s.update({r["key"]: r["value"] for r in c.execute("SELECT key,value FROM settings")})
    return s


def missing_for_issue(settings, project, vat):
    """Labels of fields that must be completed before an invoice can be issued."""
    miss = [label for k, (label, req, _) in ISSUER_FIELDS.items() if req and not (settings.get(k) or "").strip()]
    if float(vat or 0) > 0 and not (settings.get("issuer_vat_number") or "").strip():
        miss.append(ISSUER_FIELDS["issuer_vat_number"][0] + " (facture avec TVA)")
    miss += [label for k, label in PROJECT_REQUIRED.items() if not (project[k] or "").strip()]
    if not float(project["rate"] or 0) > 0: miss.append("Tarif journalier du mandat (une facture à 0,00 CHF ne peut pas être émise)")
    return miss


# VAT treatment of the « AUTRES » line. hors_tva = behaviour since V9.2 (outside the VAT base, added after VAT).
OTHER_VAT_MODES = {"hors_tva": "hors TVA (ajouté après la TVA)", "soumis": "soumis à TVA (inclus dans la base TVA)"}
# billing options (not issuer mentions): key: (label, hint)
OPTION_FIELDS = {
    "refund_delay_days": ("Délai de remboursement par défaut (jours)", "facultatif ; vide = aucune échéance imprimée ni suivie"),
    "other_vat_default": ("Traitement TVA par défaut de la ligne « AUTRES »", "appliqué aux nouveaux brouillons ; modifiable par facture"),
}


def other_vat_mode(v):
    """NULL / unknown (documents created before the option existed) = hors_tva, the behaviour they were computed with."""
    return v if v in OTHER_VAT_MODES else "hors_tva"


# rc37 (P1): manual lines of a draft (invoice_lines). Closed list of units; the VAT regime of a line uses the same vocabulary as « AUTRES ».
MANUAL_UNITS = {"day": "jour", "hour": "heure", "flat": "forfait", "piece": "pièce"}
MANUAL_UNIT_SHORT = {"day": "j", "hour": "h", "flat": "forf.", "piece": "pièce"}


# rc38 (owner decision 26.10, Q1 = B then C): the credit-note circuit now credits the manual lines (app/credit_lines.py, credit_service). UNTIL THAT IS DELIVERED AND TESTED the
# ISSUANCE of an invoice carrying manual lines is blocked (a draft with lines stays allowed): a mistake on such an invoice could not be corrected by a credit note.
# Lifting the block = setting this constant to False (one line, after the supervisor's test run), nothing else; every issuance path reads it at the moment of use.
MANUAL_LINES_ISSUANCE_BLOCKED = False
MANUAL_LINES_ISSUANCE_REFUSAL = ("émission impossible pour le moment : ce brouillon comporte {n} ligne(s) manuelle(s) et l'émission des factures à lignes manuelles est suspendue "
                                 "jusqu'à la mise en service des notes de crédit sur ces lignes (décision du propriétaire du 26.10.2026). Le brouillon reste modifiable et son PDF "
                                 "consultable ; pour émettre aujourd'hui, supprimer les lignes manuelles du brouillon")


def manual_lines_issuance_problem(c, iid):
    """Why the invoice iid cannot be issued because of its manual lines (None = nothing in the way). Read at each use: tests and the owner's go-ahead flip the constant."""
    if not MANUAL_LINES_ISSUANCE_BLOCKED: return None
    n = c.execute("SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?", (iid,)).fetchone()[0]
    return MANUAL_LINES_ISSUANCE_REFUSAL.format(n=n) if n else None


def line_amount(qty, unit_rate):
    """HT of one manual line: quantity × unit price, rounded to the cent half-up (like the service line)."""
    return (Decimal(str(qty or 0)) * Decimal(str(unit_rate or 0))).quantize(CENT, ROUND_HALF_UP)


def amounts(qty, unit_rate, vat, other=0, other_vat="hors_tva", lines=()):
    """Subtotal, VAT, other amount and total, rounded to the cent half-up.

    VAT base = service line, plus the manual lines that are « soumis » (rc37), plus the « AUTRES » amount when other_vat == 'soumis' (one rounding on the whole base).
    lines: manual lines (qty, unit_rate, vat_mode). Without lines the result is the one of every release before rc37: `ht` stays the SERVICE line only
    (the credit notes read it), `lines_ht` is the sum of the manual lines (0 without), `subtotal` = ht + lines_ht (the printed SOUS-TOTAL),
    `ttc` = ht + lines_ht + tva + other."""
    ht = (Decimal(str(qty or 0)) * Decimal(str(unit_rate or 0))).quantize(CENT, ROUND_HALF_UP)
    oth = Decimal(str(other or 0)).quantize(CENT, ROUND_HALF_UP)
    taxed = untaxed = Decimal(0)
    for ln in lines or ():
        amt = line_amount(ln["qty"], ln["unit_rate"])
        if (ln["vat_mode"] if "vat_mode" in ln.keys() else "soumis") == "hors_tva": untaxed += amt
        else: taxed += amt
    base = ht + taxed + (oth if other_vat_mode(other_vat) == "soumis" else Decimal(0))
    tva = (base * Decimal(str(vat)) / 100).quantize(CENT, ROUND_HALF_UP)
    return {"ht": ht, "tva": tva, "other": oth, "ttc": ht + taxed + untaxed + tva + oth,
            "lines_ht": taxed + untaxed, "lines_taxed": taxed, "lines_untaxed": untaxed, "subtotal": ht + taxed + untaxed}


def invoice_amounts(i, lines=()):
    """Amounts of an invoice row with its own, explicit « AUTRES » VAT treatment (and, rc37, its manual lines)."""
    keys = i.keys()
    return amounts(i["qty"], i["unit_rate"], i["vat"], i["other_amount"], i["other_vat_mode"] if "other_vat_mode" in keys else None, lines)


def invoice_lines(c, iid):
    """Manual lines of an invoice (draft: live table; issued: the table is immutable, the frozen header carries the printed copy), in printed order."""
    return [dict(r) for r in c.execute("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY position,id", (iid,))]


def invoice_lines_by_id(c):
    """{invoice id: [lines]} in one query (lists of invoices)."""
    out = {}
    for r in c.execute("SELECT * FROM invoice_lines ORDER BY invoice_id,position,id"): out.setdefault(r["invoice_id"], []).append(dict(r))
    return out


def invoice_amounts_full(c, i):
    """invoice_amounts of an invoice row WITH its manual lines read from the database."""
    return invoice_amounts(i, invoice_lines(c, i["id"]))


def issue_date_problem(i, today):
    """Why the draft cannot be issued today because of its invoice date (None = fine).
    Rule A6 (rc7): the printed date is the real issuance day unless a date was set on the draft. A date set on the
    draft may be earlier than the real issuance day without any arbitrary limit (no 30/90-day window) — issuing it
    then requires an explicit confirmation (see is_backdated); it never precedes the start of the billed period and
    is never later than the issuance day. It can change only while the invoice is a draft. The real issuance
    timestamp (issued_at) is recorded separately and is immutable; the number follows the billed period."""
    d = i["invoice_date"]
    if not d: return None
    if d < i["period_from"]: return "la date de facture précède le début de la période facturée"
    if d > today.isoformat(): return f"date de facture {fr_date(d)} postérieure au jour d'émission ({fr_date(today.isoformat())}) : modifier la date du brouillon ou émettre ce jour-là"
    return None


def is_backdated(i, today):
    """A6: the draft carries an invoice date earlier than the real issuance day → explicit confirmation required."""
    return bool(i["invoice_date"]) and i["invoice_date"] < today.isoformat()


def issue_date(i, today):
    problem = issue_date_problem(i, today)
    if problem: raise ValueError(problem)
    return i["invoice_date"] or today.isoformat()


def legal_key(v):
    """Normalised legal identifier (IDE/UID or foreign register number): letters and digits only, upper case,
    without a trailing VAT suffix, so 'CHE-123.456.789 TVA' and 'che123456789' are the same legal client."""
    k = re.sub(r"[^0-9A-Za-z]", "", v or "").upper()
    return re.sub(r"(TVA|MWST|IVA|VAT)$", "", k)


def legal_display(v):
    """Printed form of a legal identifier (rc5, decision 4). The stored value is never changed.

    A Swiss UID (CHE + 9 digits, whatever the separators/case) is printed CHE-123.456.789, followed by its VAT
    suffix when one was entered; digits stay text, so leading zeros survive. Any other format is printed as
    entered (trimmed): an unknown format is never reshaped."""
    raw = (v or "").strip()
    k = re.sub(r"[^0-9A-Za-z]", "", raw).upper()
    m = re.fullmatch(r"CHE(\d{3})(\d{3})(\d{3})(TVA|MWST|IVA|VAT)?", k)
    if not m: return raw
    return f"CHE-{m[1]}.{m[2]}.{m[3]}" + (f" {m[4]}" if m[4] else "")


def days(qty, unit, day_hours):
    return float(qty) / (day_hours or 8) if unit == "hour" else float(qty)


def doc_date(row):
    """Date of an issued document as printed: the invoice date, else the Zurich day of its issuance (invoices issued before rc5, credit notes, cancellations).
    D9 (decision B, 2026-10-07): this date, not the period, places a document in a position and in a financial year."""
    return (row["invoice_date"] if "invoice_date" in row.keys() else None) or local_date(row["issued_at"])


def contract(c, p, upto=None, exclude_invoice=None, historical_upto=None, through=None):
    """Contract position of one mandate, in days.

    gross_billed = days of issued invoices (rc7, A4: shown apart from the days cancelled by credit notes)
    historical   = days of VALIDATED historical invoices (G4: invoices issued outside the application, recorded with their source cell
                   in historical_invoices; a 'proposed' or 'rejected' row counts for nothing). historical_upto: only those dated on or
                   before this day (an invoice cannot count the invoices that came after it)
    credited = days cancelled by issued, non-cancelled credit notes (notes credited in days only; an amount-only
               note does not change the position in days)
    billed  = historical + gross_billed − credited (net); po_balance = ordered − billed (contract balance)
    offered = reliquats explicitly offered at issuance
    through (rc25, B-05): a period end 'AAAA-MM-JJ'. billed_through_days / offered_through_days count only the Time Billing invoices whose
               period ends on or before it (and the credit notes on them), like consumed_days (upto) counts the work up to it: the reliquat of an
               invoice issued late (catch-up of an earlier period) is then not offset by invoices of LATER periods. Validated historical
               invoices keep their own cutoff (historical_upto); billed_days / po_balance_days / unbilled_days stay global.
    unbilled = consumed − billed − offered (positive: still to bill; negative: billed ahead)
    """
    dh = p["day_hours"] or 8
    consumed = c.execute("SELECT COALESCE(SUM(hours),0) FROM entries WHERE project_id=?" + (" AND work_date<=?" if upto else ""),
                         (p["id"], upto) if upto else (p["id"],)).fetchone()[0]
    inv = c.execute("SELECT id,qty,unit,status,reliquat_days,reliquat_treatment,period_to FROM invoices WHERE project_id=?", (p["id"],)).fetchall()
    billed = sum(days(i["qty"], i["unit"], dh) for i in inv if i["status"] == "issued" and i["id"] != exclude_invoice)
    drafts = sum(days(i["qty"], i["unit"], dh) for i in inv if i["status"] == "draft")
    offered = sum(i["reliquat_days"] or 0 for i in inv if i["status"] == "issued" and i["reliquat_treatment"] == "offert" and i["id"] != exclude_invoice)
    credited = c.execute("""SELECT COALESCE(SUM(CASE WHEN i.unit='hour' THEN cn.qty/? ELSE cn.qty END),0) FROM credit_notes cn
                            JOIN invoices i ON i.id=cn.invoice_id WHERE i.project_id=? AND cn.status='issued' AND cn.qty IS NOT NULL
                            AND cn.id NOT IN (SELECT credit_note_id FROM credit_note_cancellations)""", (dh, p["id"])).fetchone()[0]
    gross = billed
    upto_ok = lambda i: through is None or i["period_to"] <= through
    billed_t = sum(days(i["qty"], i["unit"], dh) for i in inv if i["status"] == "issued" and i["id"] != exclude_invoice and upto_ok(i))
    offered_t = sum(i["reliquat_days"] or 0 for i in inv if i["status"] == "issued" and i["reliquat_treatment"] == "offert" and i["id"] != exclude_invoice and upto_ok(i))
    credited_t = c.execute("""SELECT COALESCE(SUM(CASE WHEN i.unit='hour' THEN cn.qty/? ELSE cn.qty END),0) FROM credit_notes cn
                            JOIN invoices i ON i.id=cn.invoice_id WHERE i.project_id=? AND cn.status='issued' AND cn.qty IS NOT NULL
                            AND cn.id NOT IN (SELECT credit_note_id FROM credit_note_cancellations)""" + (" AND i.period_to<=?" if through else ""),
                           (dh, p["id"], through) if through else (dh, p["id"])).fetchone()[0]
    hq = "SELECT COALESCE(SUM(qty_days),0), COALESCE(SUM(amount_ht),0), COUNT(*) FROM historical_invoices WHERE project_id=? AND status='validated'"
    hist_days, hist_amount, hist_count = c.execute(hq + (" AND invoice_date IS NOT NULL AND invoice_date<=?" if historical_upto else ""),
                                                  (p["id"], historical_upto) if historical_upto else (p["id"],)).fetchone()
    billed = billed + hist_days - credited
    billed_through = billed_t + hist_days - credited_t
    last = c.execute("SELECT MAX(period_to) FROM invoices WHERE project_id=? AND status='issued'", (p["id"],)).fetchone()[0]
    ordered = float(p["ordered_days"] or 0)
    r = lambda v: round(v, 5)
    return {"consumed_hours": r(consumed), "consumed_days": r(consumed / dh), "billed_days": r(billed), "draft_days": r(drafts),
            "offered_days": r(offered), "billed_through_days": r(billed_through), "offered_through_days": r(offered_t), "credited_days": r(credited), "gross_billed_days": r(gross), "unbilled_days": r(consumed / dh - billed - offered),
            "historical_days": r(hist_days), "historical_amount": round(hist_amount, 2), "historical_count": hist_count,
            "ordered_days": ordered, "po_balance_days": r(ordered - billed), "last_issued_to": last}


def external_invoice_numbers():
    """G4 (N1, review F-N1-1 2026-10-06): numbers of real invoices issued outside the application, taken even before the registry holds them (the D1
    rows are loaded after the deployment, on a separate go). Comma-separated EXTERNAL_INVOICE_NUMBERS, set by the deployment files
    (procedure/docker-compose.*.yml: « 2026-09 » = SUIVI 2026!Q12, CIRSE 2026, invoiced on 01.10.2026); unset in the test containers, whose
    fictitious September 2026 invoices are numbered 2026-09 like the reference invoice."""
    return tuple(n.strip() for n in os.environ.get("EXTERNAL_INVOICE_NUMBERS", "").split(",") if n.strip())


# --- invoice numbers (rc37, P3) ---------------------------------------------------------------------------------------------------------------
# Proposed format AAAA-N (year of the invoice date, then a sequence that restarts every year, no leading zero: 2026-11 follows 2026-10). A draft RESERVES its number
# as soon as it is saved (invoices.number, the column that is already UNIQUE): the issuance keeps it. The numbers of earlier releases (AAAA-MM, AAAA-MM-N) still count
# as taken; their month is read as the sequence of the year (2026-10 → 10), which is what makes « 2026-11 » follow the real invoice « 2026-10 ».
INVOICE_NUMBER_MAX = 20
INVOICE_NUMBER_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9/-]{0,%d}" % (INVOICE_NUMBER_MAX - 1))     # no space, « . », « _ », « % » (credit-note references NC-<n>.2 and the LIKE searches rely on it)
NUMBER_SEQ = re.compile(r"(\d{4})-(\d{1,6})(?:-\d{1,6})?")


def number_key(n):
    """Comparison key of an invoice number: case and surrounding spaces never make two numbers different."""
    return (n or "").strip().upper()


def check_invoice_number(raw):
    """The number typed by the user, trimmed, or ValueError with the reason. Free format within the limits (decision D5 c): 1 to 20 characters among letters, digits, « - » and « / »,
    starting with a letter or a digit, not the prefix of a credit note, short enough for the « N° Facture » box of the document."""
    v = (raw or "").strip()
    if not v: raise ValueError("numéro de facture vide")
    if len(v) > INVOICE_NUMBER_MAX: raise ValueError(f"numéro trop long ({INVOICE_NUMBER_MAX} caractères au maximum)")
    if not INVOICE_NUMBER_OK.fullmatch(v):
        bad = sorted({ch for ch in v if not re.fullmatch(r"[A-Za-z0-9/-]", ch)})
        raise ValueError("numéro invalide : lettres latines, chiffres, « - » et « / » seulement, en commençant par une lettre ou un chiffre"
                         + (f" (caractère refusé : {', '.join(repr(ch) if ch.strip() else 'espace' for ch in bad)})" if bad else ""))
    if v.upper().startswith("NC-"): raise ValueError("le préfixe « NC- » est réservé aux notes de crédit")
    return v


def parse_number(n):
    """(year, sequence) of a number in the proposed format or in the one of earlier releases (AAAA-MM, AAAA-MM-N), else None."""
    m = NUMBER_SEQ.fullmatch((n or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _number_sources(c, exclude_id=None):
    """[(number, kind, label, id)] of every number that is not free: invoices of every status (a draft RESERVES its number), historical invoices of any status (real numbers printed
    outside the application, never given again), EXTERNAL_INVOICE_NUMBERS."""
    out = [(r["number"], "issued" if r["status"] == "issued" else "draft", r["project"], r["id"]) for r in c.execute(
        "SELECT i.id,i.number,i.status,p.name project FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.number IS NOT NULL AND i.id IS NOT ?", (exclude_id,))]
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='historical_invoices'").fetchone():
        out += [(r["invoice_ref"], "historical", None, r["id"]) for r in c.execute("SELECT id,invoice_ref FROM historical_invoices WHERE invoice_ref IS NOT NULL AND trim(invoice_ref)<>''")]
    out += [(n, "external", None, None) for n in external_invoice_numbers()]
    return out


def number_conflict(c, number, exclude_id=None):
    """Who already holds this number (case and surrounding spaces ignored), as {'kind': issued | draft | historical | external, 'label', 'id', 'number'}; None when it is free."""
    k = number_key(number)
    for n, kind, label, i in _number_sources(c, exclude_id):
        if number_key(n) == k: return {"kind": kind, "label": label, "id": i, "number": n}
    return None


def describe_conflict(x):
    return {"issued": f"la facture émise {x['number']} (mandat « {x['label']} »)", "draft": f"le brouillon n° {x['id']} (mandat « {x['label']} », numéro réservé)",
            "historical": f"une facture historique (hors application) n° {x['number']}", "external": f"un numéro de facture externe réservé ({x['number']})"}[x["kind"]]


def propose_invoice_number(c, year, exclude_id=None):
    """First free number of the year: AAAA-N with N above the highest sequence already ISSUED (invoices, historical invoices, external numbers: earlier-release numbers read as
    seen above) and not reserved by an active draft. A deleted draft's number is free again (decision D5 b: the first free one is proposed, gaps are filled)."""
    year = int(year); rows = _number_sources(c, exclude_id)
    top = max([p[1] for n, kind, _, _ in rows if kind != "draft" and (p := parse_number(n)) and p[0] == year] + [0])
    reserved = {number_key(n) for n, _, _, _ in rows}
    n = top + 1
    while f"{year}-{n}".upper() in reserved: n += 1
    return f"{year}-{n}"


def next_credit_number(c, invoice_number):
    """NC-<invoice number>, then NC-<invoice number>.2, .3… ('.' never occurs in invoice numbers,
    so NC-2026-09.2 (2nd note on 2026-09) cannot collide with NC-2026-09-2 (1st note on 2026-09-2))."""
    base = "NC-" + invoice_number
    taken = [r[0] for r in c.execute("SELECT reference FROM credit_notes WHERE reference=? OR reference LIKE ?", (base, base + ".%"))]
    if base not in taken: return base
    suffixes = [int(n.rsplit(".", 1)[1]) for n in taken if re.fullmatch(re.escape(base) + r"\.\d+", n)]
    return f"{base}.{max(suffixes + [1]) + 1}"
