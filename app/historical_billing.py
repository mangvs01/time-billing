"""G4: invoices issued OUTSIDE the application (recorded from the user's SUIVI workbook), kept apart from `invoices`.

A historical invoice is a fact with a source cell, not a document of the application: it has no number, no PDF, cannot be edited or issued, is never
recreated as an issued invoice and is never deleted. It feeds the indicators (billed days, PO balance, annual turnover, annex position) ONLY once the
user validated it; a 'proposed' row (loaded by the import tool) or a 'rejected' row counts for nothing.

rc23 (Decision Center billing-g4-correction-historiques = A_CORRIGER_PAR_REMPLACEMENT, 2026-10-08): the values read from the workbook are still
never rewritten. A wrong row is CORRECTED BY REPLACEMENT: it is rejected (its values stay visible, with « remplacée par la correction n° X ») and a
corrected row is recorded and validated in the same operation, provenance « SUIVI 2026!M15 (correction 1) », source file MANUAL_FILE. A missing
historical invoice is ADDED the same way (« ajout manuel n° 1 »). Reason mandatory, both traced in the audit log. The rows of one source cell
(the imported one and its corrections) form a family: at most one of them is validated at a time once a correction exists, so re-validating a
replaced row never counts the same invoice twice. Adversarial review (2026-10-08): a real invoice number is validated once only, an added or
corrected row identical (mandate, date, days, amount) to another validated row is refused, an addition resembling an existing row of the mandate
needs an explicit confirmation, and an invoice number is plain text (no invisible or direction character: N1 compares numbers exactly).
"""
import json, re
from datetime import date

from app import billing_rules as rules

STATUSES = ("proposed", "validated", "rejected")
MANUAL_FILE = "saisie dans Time Billing"            # source_file of the corrected and added rows (rc23)
ADD_SHEET = "ajout manuel"                          # source_sheet of an added row; its source_cell is « n° 1 », « n° 2 »…
_CORR = re.compile(r"^(.*) \(correction (\d+)\)$")
MAX_REF = 40
REF_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z./_-]*")   # « 2026-09 », « F2025/11 » : what is printed on an invoice, compared exactly (N1)
TB_NUMBER_RE = re.compile(r"\d{4}-\d{1,6}(?:-\d{1,6})?")   # a number of the format Time Billing issues (rc37: AAAA-N « 2026-11 » ; earlier releases AAAA-MM[-N] « 2026-09 », « 2026-09-2 »)
STATUS_LABEL = {"proposed": "à valider", "validated": "validée", "rejected": "rejetée"}
BASIS_LABEL = {"days": "jours lus dans le classeur ; montant = jours × tarif de la ligne",
               "amount": "montant lu dans le classeur ; jours = montant ÷ tarif de la ligne",
               "amount_only": "montant seul : aucune quantité dans le classeur"}


def list_rows(c, status=None, project_id=None):
    """Rows with their mandate, ordered by mandate then invoice date. Plain dicts."""
    q = ("SELECT h.*,p.name project,p.active project_active FROM historical_invoices h JOIN projects p ON p.id=h.project_id WHERE 1=1"
         + (" AND h.status=?" if status else "") + (" AND h.project_id=?" if project_id else "") + " ORDER BY p.name,COALESCE(h.invoice_date,'9999'),h.id")
    args = [x for x in (status, project_id) if x]
    return [dict(r) for r in c.execute(q, args)]


def counts(c):
    out = {s: 0 for s in STATUSES}
    for st, n in c.execute("SELECT status,COUNT(*) FROM historical_invoices GROUP BY status"): out[st] = n
    return out


def totals_by_project(c):
    """{project_id: {'days','amount','n'}} of the VALIDATED rows."""
    return {r["project_id"]: {"days": r["d"], "amount": r["a"], "n": r["n"]} for r in c.execute(
        "SELECT project_id,COALESCE(SUM(qty_days),0) d,COALESCE(SUM(amount_ht),0) a,COUNT(*) n FROM historical_invoices WHERE status='validated' GROUP BY project_id")}


def amounts_by_year(c):
    """{'2026': Decimal HT} of the VALIDATED rows that have a date and an amount (turnover of the year, issued outside the application)."""
    out = {}
    for y, a in c.execute("SELECT substr(invoice_date,1,4),COALESCE(SUM(amount_ht),0) FROM historical_invoices WHERE status='validated' AND invoice_date IS NOT NULL "
                          "AND amount_ht IS NOT NULL GROUP BY 1"):
        out[y] = rules.amounts(1, a, 0)["ht"]
    return out


def add_proposed(c, rec, now=None):
    """Insert one PROPOSED row (the import tool). The caller owns the transaction. rec: dict of the columns of the table."""
    cols = ("project_id", "source_file", "source_sha256", "source_sheet", "source_cell", "source_column", "invoice_date", "invoice_ref", "qty_days", "amount_ht",
            "unit_rate", "basis", "qty_derived", "note")
    row = {k: rec.get(k) for k in cols}
    row["qty_derived"] = int(bool(row["qty_derived"])); row["note"] = row["note"] or ""; row["source_sha256"] = row["source_sha256"] or ""; row["source_column"] = row["source_column"] or ""
    row["created_at"] = now or rules.utc_now_iso(); row["status"] = "proposed"
    cur = c.execute(f"INSERT INTO historical_invoices({','.join(row)}) VALUES({','.join('?' * len(row))})", tuple(row.values()))
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("historical_invoice_proposed", json.dumps(
        {"id": cur.lastrowid, "project_id": row["project_id"], "cell": f"{row['source_sheet']}!{row['source_cell']}", "date": row["invoice_date"], "days": row["qty_days"],
         "amount_ht": row["amount_ht"], "note": row["note"]}, ensure_ascii=False)))
    return cur.lastrowid


def cell_label(sheet, cell):
    """Provenance as printed (page, annex of an invoice, audit): « SUIVI 2026!M15 », « SUIVI 2026!M15 (correction 1) », « ajout manuel n° 1 »."""
    return f"{sheet} {cell}" if sheet == ADD_SHEET else f"{sheet}!{cell}"


def is_manual(r):
    return r["source_file"] == MANUAL_FILE


def _root_cell(r):
    m = _CORR.match(r["source_cell"]) if is_manual(r) else None
    return m.group(1) if m else r["source_cell"]


def family(c, r):
    """Rows recorded for the same source cell as r (r included): the imported row and its manual corrections, or an added row and its corrections."""
    root = _root_cell(r)
    out = [x for x in c.execute("SELECT * FROM historical_invoices WHERE source_sheet=? AND (source_cell=? OR source_cell LIKE ?) ORDER BY id",
                                (r["source_sheet"], root, root + " (correction %)"))
           if _root_cell(x) == root and (x["id"] == r["id"] or is_manual(x) or x["source_cell"] == root)]
    return out


def _check_family(c, r):
    """Validating r: refused while another row of its family is validated, once the family holds a correction (an import alone keeps its rules)."""
    fam = family(c, r)
    if not any(is_manual(x) for x in fam): return
    other = next((x for x in fam if x["id"] != r["id"] and x["status"] == "validated"), None)
    if other: raise ValueError(f"la ligne n° {other['id']} ({cell_label(other['source_sheet'], other['source_cell'])}) est déjà validée pour la même facture : "
                               "la retirer d'abord (une facture n'est comptée qu'une fois)")


def _check_not_time_billing_number(c, r):
    """Validating r: refused when its reference is the number of an invoice of Time Billing (owner decision O3, 2026-10-11): that invoice already counts in
    the cumulated quantities, so the row would count it twice. A number of the same format that Time Billing never issued (an invoice issued outside the
    application, e.g. « 2026-09 » for CIRSE 2026, for which Time Billing numbers its own invoice « 2026-09-2 ») stays valid."""
    ref = r["invoice_ref"]
    if not ref or not TB_NUMBER_RE.fullmatch(ref): return
    x = c.execute("SELECT id,status FROM invoices WHERE number=? AND status='issued'", (ref,)).fetchone()     # rc37: a draft only RESERVES its number (its conflict is reported at issuance)
    if x: raise ValueError(f"le n° {ref} est celui d'une facture Time Billing (facture n° {x['id']}, déjà comptée dans les quantités facturées) : une facture "
                           "historique ne peut pas porter un numéro Time Billing (elle serait comptée deux fois) ; corriger le n° ou rejeter la ligne")


def _check_duplicates(c, r):
    """Validating r: never two validated rows for one real invoice — same invoice number, or (a manual row involved) same mandate, date, days and amount."""
    if r["invoice_ref"]:
        x = c.execute("SELECT id,source_sheet,source_cell FROM historical_invoices WHERE invoice_ref=? AND status='validated' AND id<>?", (r["invoice_ref"], r["id"])).fetchone()
        if x: raise ValueError(f"le n° {r['invoice_ref']} est déjà validé sur la ligne n° {x['id']} ({cell_label(x['source_sheet'], x['source_cell'])}) : "
                               "une facture n'est comptée qu'une fois (retirer d'abord cette ligne)")
    for x in c.execute("""SELECT * FROM historical_invoices WHERE project_id=? AND status='validated' AND id<>? AND invoice_date IS ? AND qty_days IS ? AND amount_ht IS ?""",
                       (r["project_id"], r["id"], r["invoice_date"], r["qty_days"], r["amount_ht"])):
        if is_manual(x) or is_manual(r):
            raise ValueError(f"la ligne n° {x['id']} ({cell_label(x['source_sheet'], x['source_cell'])}) est déjà validée avec la même date, les mêmes jours et "
                             "le même montant sur ce mandat : une facture n'est comptée qu'une fois (retirer d'abord cette ligne)")


def set_status(c, hid, new, actor, note=""):
    """Validate / reject / re-validate one row, with its audit line. A rejection needs a reason. Returns (project name, old status). Caller owns the transaction."""
    r = c.execute("SELECT h.*,p.name project FROM historical_invoices h JOIN projects p ON p.id=h.project_id WHERE h.id=?", (hid,)).fetchone()
    if not r: raise LookupError("facture historique introuvable")
    if new not in ("validated", "rejected"): raise ValueError("statut inconnu")
    if r["status"] == new: raise ValueError(f"cette facture historique est déjà {STATUS_LABEL[new]}")
    note = (note or "").strip()
    if new == "rejected" and not note: raise ValueError("motif obligatoire pour rejeter ou retirer une facture historique")
    if new == "validated" and r["invoice_date"] is None and r["qty_days"] is not None:
        raise ValueError("date de facture inconnue : une facture historique sans date ne peut pas être validée (le cumul ne saurait pas où la placer)")
    if new == "validated": _check_family(c, r); _check_not_time_billing_number(c, r); _check_duplicates(c, r)
    now = rules.utc_now_iso()
    # The note only grows: a rejection is appended after the provenance note (D4 notes are never lost), a re-validation keeps the whole story.
    kept = r["note"] or ""
    if new == "rejected": kept = (kept + " · " if kept else "") + f"Rejet du {rules.fr_date(rules.local_date(now))} : {note}"   # the Zurich day, as the page shows dates
    c.execute("UPDATE historical_invoices SET status=?,note=?,validated_at=?,validated_by=? WHERE id=?",
              (new, kept, now if new == "validated" else r["validated_at"], actor if new == "validated" else r["validated_by"], hid))
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", (f"historical_invoice_{new}", json.dumps(
        {"id": hid, "project": r["project"], "cell": cell_label(r["source_sheet"], r["source_cell"]), "from": r["status"], "date": r["invoice_date"], "days": r["qty_days"],
         "amount_ht": r["amount_ht"], "by": actor, "reason": note}, ensure_ascii=False)))
    return r["project"], r["status"]


def validate_project(c, project_id, actor):
    """Validate every PROPOSED row of one mandate (explicit action of the user on the page). Rows that cannot be validated stay proposed and are reported."""
    done, kept = 0, []
    for r in c.execute("SELECT id,source_sheet,source_cell FROM historical_invoices WHERE project_id=? AND status='proposed' ORDER BY id", (project_id,)).fetchall():
        try: set_status(c, r["id"], "validated", actor); done += 1
        except ValueError as e: kept.append(f"{r['source_sheet']}!{r['source_cell']} : {e}")
    return done, kept


def parse_values(form_date, days, amount, ref):
    """Values typed in the correction / addition form, already parsed as numbers by the caller (None = empty). Same rules as the registry:
    a date (the invoice is placed by it: D9), days > 0 and/or an amount >= 0, the invoice really issued (not after today, Zurich)."""
    try: d = date.fromisoformat((form_date or "").strip())
    except ValueError: raise ValueError("date de facture obligatoire (format AAAA-MM-JJ)")
    if d.year < 2000: raise ValueError("date de facture invalide (avant 2000)")
    if d > rules.local_today(): raise ValueError("date de facture dans le futur : une facture historique est déjà émise")
    if days is None and amount is None: raise ValueError("indiquer les jours facturés, le montant HT, ou les deux")
    if days is not None and days <= 0: raise ValueError("jours facturés : nombre positif attendu")
    if amount is not None and amount < 0: raise ValueError("montant HT : nombre positif ou nul attendu")
    ref = (ref or "").strip()
    if len(ref) > MAX_REF: raise ValueError(f"n° de facture trop long ({MAX_REF} caractères au maximum)")
    if ref and not REF_RE.fullmatch(ref):
        raise ValueError("n° de facture : chiffres, lettres latines et « - / . _ » seulement (aucun espace ni caractère invisible), tel qu'imprimé sur la facture")
    return {"invoice_date": d.isoformat(), "qty_days": days, "amount_ht": amount, "invoice_ref": ref or None}


def _check_ref(c, ref, exclude_ids=()):
    if not ref: return
    if c.execute("SELECT 1 FROM invoices WHERE number=? AND status='issued'", (ref,)).fetchone():
        raise ValueError(f"le n° {ref} est celui d'une facture Time Billing : une facture historique ne peut pas le porter")
    for x in c.execute("SELECT id,source_sheet,source_cell FROM historical_invoices WHERE invoice_ref=? AND status<>'rejected'", (ref,)):
        if x["id"] not in exclude_ids:
            raise ValueError(f"le n° {ref} est déjà porté par la facture historique n° {x['id']} ({cell_label(x['source_sheet'], x['source_cell'])})")


def _insert_manual(c, project_id, sheet, cell, column, vals, unit_rate, note, now):
    days, amount = vals["qty_days"], vals["amount_ht"]
    rate = round(amount / days, 2) if days and amount is not None else unit_rate
    cur = c.execute("""INSERT INTO historical_invoices(project_id,source_file,source_sha256,source_sheet,source_cell,source_column,invoice_date,invoice_ref,qty_days,
                       amount_ht,unit_rate,basis,qty_derived,status,note,created_at) VALUES(?,?,'',?,?,?,?,?,?,?,?,?,0,'proposed',?,?)""",
                    (project_id, MANUAL_FILE, sheet, cell, column or "", vals["invoice_date"], vals["invoice_ref"], days, amount, rate,
                     "amount_only" if days is None else "days", note, now))
    return cur.lastrowid


def _values(r):
    return {"date": r["invoice_date"], "days": r["qty_days"], "amount_ht": r["amount_ht"], "ref": r["invoice_ref"]}


def correct(c, hid, vals, actor, reason):
    """Correct row hid by replacement (A): a new row with the typed values, validated, and row hid rejected « remplacée par la correction n° X »
    (already rejected: the note says so). Returns (new id, project name, rate warnings). The caller owns the transaction."""
    r = c.execute("SELECT h.*,p.name project FROM historical_invoices h JOIN projects p ON p.id=h.project_id WHERE h.id=?", (hid,)).fetchone()
    if not r: raise LookupError("facture historique introuvable")
    reason = (reason or "").strip()
    if not reason: raise ValueError("motif obligatoire pour corriger une facture historique")
    if (vals["invoice_date"], vals["qty_days"], vals["amount_ht"], vals["invoice_ref"] or None) == (r["invoice_date"], r["qty_days"], r["amount_ht"], r["invoice_ref"] or None):
        raise ValueError("aucune valeur modifiée : rien n'est enregistré")
    for k, msg in (("qty_days", "les jours facturés ne peuvent pas être vidés"), ("amount_ht", "le montant HT ne peut pas être vidé")):
        if r[k] is not None and vals[k] is None: raise ValueError(f"{msg} : la ligne d'origine en a (indiquer la valeur juste)")
    fam = family(c, r)
    _check_ref(c, vals["invoice_ref"], {x["id"] for x in fam})
    root = _root_cell(r)
    k = 1 + max([int(m.group(2)) for x in fam if is_manual(x) for m in [_CORR.match(x["source_cell"])] if m] + [0])
    now = rules.utc_now_iso()
    src = cell_label(r["source_sheet"], r["source_cell"])
    new = _insert_manual(c, r["project_id"], r["source_sheet"], f"{root} (correction {k})", r["source_column"], vals, r["unit_rate"],
                         f"Correction de {src} (ligne n° {hid}) le {rules.fr_date(rules.local_date(now))} : {reason}", now)
    if r["status"] == "rejected":
        c.execute("UPDATE historical_invoices SET note=? WHERE id=?", ((r["note"] + " · " if r["note"] else "") + f"Corrigée par la ligne n° {new}", hid))
    else:
        set_status(c, hid, "rejected", actor, f"remplacée par la correction n° {new} : {reason}")
    set_status(c, new, "validated", actor)
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("historical_invoice_corrected", json.dumps(
        {"id": new, "replaces": hid, "project": r["project"], "cell": src, "before": _values(r), "after": {"date": vals["invoice_date"], "days": vals["qty_days"],
         "amount_ht": vals["amount_ht"], "ref": vals["invoice_ref"]}, "by": actor, "reason": reason}, ensure_ascii=False)))
    return new, r["project"], rate_warnings(c, r["project_id"], vals)


def rate_warnings(c, project_id, vals):
    """Non-blocking: the implied daily rate of the typed values differs from the mandate's rate (a value forgotten in the form)."""
    days, amount = vals["qty_days"], vals["amount_ht"]
    p = c.execute("SELECT rate FROM projects WHERE id=?", (project_id,)).fetchone()
    if not (days and amount is not None and p and p["rate"]): return []
    implied = amount / days
    if abs(implied - float(p["rate"])) <= 0.01: return []
    return [f"Attention : {rules.fr_num(amount)} CHF pour {rules.fr_num(days, 4)} j = {rules.fr_num(implied)} CHF/j, alors que le tarif du mandat est "
            f"{rules.fr_num(float(p['rate']))} CHF/j. Vérifier les jours et le montant (corriger à nouveau si besoin)."]


def similar_rows(c, project_id, vals):
    """Non-rejected rows of the mandate with the same date and the same days or the same amount (an addition that may already be recorded)."""
    return [x for x in c.execute("SELECT * FROM historical_invoices WHERE project_id=? AND status<>'rejected' AND invoice_date=?", (project_id, vals["invoice_date"]))
            if (vals["qty_days"] is not None and x["qty_days"] == vals["qty_days"]) or (vals["amount_ht"] is not None and x["amount_ht"] == vals["amount_ht"])]


def validation_conflicts(rows):
    """Restore guard: rows (dicts of a backup file) that would count one invoice twice — two validated rows of a family holding a correction,
    or two validated rows with the same invoice number. Pure function on the file's rows."""
    out, fam, refs = [], {}, {}
    for r in rows:
        if not isinstance(r, dict) or r.get("status") != "validated": continue
        cell = str(r.get("source_cell") or ""); m = _CORR.match(cell) if r.get("source_file") == MANUAL_FILE else None
        fam.setdefault((r.get("source_sheet"), m.group(1) if m else cell), []).append(r)
        if r.get("invoice_ref"): refs.setdefault(r["invoice_ref"], []).append(r)
    for (sheet, cell), lst in fam.items():
        if len(lst) > 1 and any(x.get("source_file") == MANUAL_FILE for x in lst):
            out.append(f"factures historiques : {len(lst)} lignes validées pour {cell_label(sheet, cell)} (lignes {', '.join(str(x.get('id')) for x in lst)})")
    for ref, lst in refs.items():
        if len(lst) > 1: out.append(f"factures historiques : n° {ref} validé sur {len(lst)} lignes ({', '.join(str(x.get('id')) for x in lst)})")
    return out


def add(c, project_id, vals, actor, reason, confirm_similar=False):
    """Record a historical invoice missing from the workbook import, validated by this gesture (« ajout manuel n° k »). Returns (new id, project name, rate warnings).
    An addition resembling a non-rejected row of the mandate (same date, same days or amount) needs confirm_similar."""
    p = c.execute("SELECT id,name FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p: raise ValueError("mandat inconnu")
    reason = (reason or "").strip()
    if not reason: raise ValueError("motif obligatoire pour ajouter une facture historique")
    _check_ref(c, vals["invoice_ref"])
    sim = similar_rows(c, p["id"], vals)
    if sim and not confirm_similar:
        x = sim[0]
        raise ValueError(f"la ligne n° {x['id']} ({cell_label(x['source_sheet'], x['source_cell'])}, {labels_of(x)}) a la même date et les mêmes jours ou le même "
                         "montant sur ce mandat : si c'est une autre facture, cocher « Il s'agit d'une autre facture » ; sinon, la corriger plutôt que l'ajouter")
    k = 1 + max([int(x[0][3:]) for x in c.execute("SELECT source_cell FROM historical_invoices WHERE source_file=? AND source_sheet=?", (MANUAL_FILE, ADD_SHEET))
                 if re.fullmatch(r"n° \d+", x[0])] + [0])
    now = rules.utc_now_iso()
    new = _insert_manual(c, p["id"], ADD_SHEET, f"n° {k}", "", vals, None, f"Ajout manuel le {rules.fr_date(rules.local_date(now))} : {reason}", now)
    set_status(c, new, "validated", actor)
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("historical_invoice_added", json.dumps(
        {"id": new, "project": p["name"], "cell": cell_label(ADD_SHEET, f"n° {k}"), "after": {"date": vals["invoice_date"], "days": vals["qty_days"],
         "amount_ht": vals["amount_ht"], "ref": vals["invoice_ref"]}, "by": actor, "reason": reason}, ensure_ascii=False)))
    return new, p["name"], rate_warnings(c, p["id"], vals)


def labels_of(x):
    return f"{STATUS_LABEL.get(x['status'], x['status'])}, {x['qty_days'] if x['qty_days'] is not None else '—'} j, {x['amount_ht'] if x['amount_ht'] is not None else '—'} CHF"
