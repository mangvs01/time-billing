"""Manual lines of a draft invoice (rc37, P1): reading the form, validation, persistence.

A draft invoice keeps its service line (hours → /suggest) and its single « AUTRES » line exactly as before; the manual lines are ADDED in the table
`invoice_lines` (one row per line, immutable once the invoice is issued: triggers in app.init). Persistence is one transaction per save:
rows of the form that carry a known `line_id` are updated, rows without one are inserted (idempotent by `line_uid`: a double submission of the same
form creates nothing twice), rows of the draft absent from the form are deleted. The issuance freezes the printed copy in the header of the snapshot.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

from app import billing_rules as rules, pdf_layout

PLAIN_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
MAX_QTY = Decimal("1000000"); MAX_RATE = Decimal("1000000000"); MAX_DESCRIPTION_CHARS = 200
FIELDS = ("line_id", "line_uid", "line_description", "line_qty", "line_unit", "line_rate", "line_vat_mode")
DEFAULT_UNIT = "flat"; DEFAULT_VAT_MODE = "soumis"        # a manual line is subject to the invoice's VAT unless the user chooses « hors TVA » (decision D2)


def from_form(form):
    """Raw rows of the posted form, in order (strings, not validated). A new row left completely empty is a blank row the user never filled: ignored."""
    cols = {k: form.getlist(k) for k in FIELDS}
    n = max((len(v) for v in cols.values()), default=0)
    rows = []
    for i in range(n):
        r = {k: (cols[k][i] if i < len(cols[k]) else "").strip() for k in FIELDS}
        if not r["line_id"] and not any(r[k] for k in ("line_description", "line_qty", "line_rate")): continue
        rows.append(r)
    return rows


def blank_row(uid=""):
    return {"line_id": "", "line_uid": uid, "line_description": "", "line_qty": "1", "line_unit": DEFAULT_UNIT, "line_rate": "", "line_vat_mode": DEFAULT_VAT_MODE}


def as_form_rows(lines):
    """Stored lines → the same raw shape as from_form (editor opening)."""
    def g(v): return format(Decimal(str(v)).normalize(), "f")
    return [{"line_id": str(ln["id"]), "line_uid": ln.get("client_uid") or "", "line_description": ln["description"], "line_qty": g(ln["qty"]), "line_unit": ln["unit"],
             "line_rate": g(ln["unit_rate"]), "line_vat_mode": ln["vat_mode"]} for ln in lines]


def _number(raw, label, n, hi, lo_open):
    v = (raw or "").replace(",", ".").replace(" ", "").strip()
    if not PLAIN_NUMBER.fullmatch(v): raise ValueError(f"ligne {n} : {label} invalide")
    d = Decimal(v)
    if d > hi or d < 0 or (lo_open and d == 0): raise ValueError(f"ligne {n} : {label} invalide ou hors limites")
    return d


def validate(rows, table_unit=None):
    """Validated lines [{id, uid, description, qty, unit, unit_rate, vat_mode}], raises ValueError (message prefixed « ligne n : »). Same rules at the form and at the server."""
    out = []; seen_uid = set()
    for n, r in enumerate(rows, 1):
        desc = " ".join(r["line_description"].split())
        if not desc: raise ValueError(f"ligne {n} : description obligatoire (pour retirer une ligne, utiliser « Supprimer »)")
        if len(desc) > MAX_DESCRIPTION_CHARS: raise ValueError(f"ligne {n} : description trop longue ({MAX_DESCRIPTION_CHARS} caractères au maximum)")
        qty = _number(r["line_qty"], "quantité", n, MAX_QTY, True).quantize(Decimal("0.000001"), ROUND_HALF_UP)
        rate = _number(r["line_rate"], "prix unitaire (CHF)", n, MAX_RATE, False).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        unit = r["line_unit"] or DEFAULT_UNIT
        if unit not in rules.MANUAL_UNITS: raise ValueError(f"ligne {n} : unité inconnue")
        vat_mode = r["line_vat_mode"] or DEFAULT_VAT_MODE
        if vat_mode not in rules.OTHER_VAT_MODES: raise ValueError(f"ligne {n} : régime de TVA inconnu")
        lid = None
        if r["line_id"]:
            if not r["line_id"].isdigit(): raise ValueError(f"ligne {n} : identifiant de ligne invalide")
            lid = int(r["line_id"])
        uid = r["line_uid"][:64] or None
        if uid and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", uid): raise ValueError(f"ligne {n} : identifiant de ligne invalide")
        if uid:
            if uid in seen_uid: raise ValueError(f"ligne {n} : ligne en double (même identifiant de saisie)")
            seen_uid.add(uid)
        out.append({"id": lid, "uid": uid, "description": desc, "qty": float(qty), "unit": unit, "unit_rate": float(rate), "vat_mode": vat_mode})
    problem = pdf_layout.manual_lines_problem(out, table_unit)
    if problem: raise ValueError(problem)
    return out


def save(c, iid, lines):
    """Replace the manual lines of the DRAFT iid by `lines` (validated). The caller owns the transaction. Returns (inserted, updated, deleted)."""
    st = c.execute("SELECT status FROM invoices WHERE id=?", (iid,)).fetchone()
    if not st or st["status"] != "draft": raise ValueError("brouillon introuvable ou déjà émis")
    have = {r["id"]: r for r in c.execute("SELECT id,client_uid FROM invoice_lines WHERE invoice_id=?", (iid,))}
    by_uid = {r["client_uid"]: r["id"] for r in have.values() if r["client_uid"]}
    keep = set()
    for ln in lines:
        lid = ln["id"] if ln["id"] in have else None
        if ln["id"] and lid is None: raise ValueError("une ligne de ce brouillon n'existe plus (modifiée dans un autre onglet ?) : rouvrir le brouillon")
        if lid is None and ln["uid"] in by_uid: lid = by_uid[ln["uid"]]       # the same new line submitted twice: it is the existing one
        ln["_id"] = lid
        if lid is not None:
            if lid in keep: raise ValueError("ligne en double dans le formulaire")
            keep.add(lid)
    gone = [i for i in have if i not in keep]
    for i in gone: c.execute("DELETE FROM invoice_lines WHERE id=? AND invoice_id=?", (i, iid))
    c.execute("UPDATE invoice_lines SET position=position+100000 WHERE invoice_id=?", (iid,))   # free the (invoice, position) slots while rows move
    ins = upd = 0; now = rules.utc_now_iso()
    for pos, ln in enumerate(lines, 1):
        vals = (pos, ln["description"], ln["qty"], ln["unit"], ln["unit_rate"], ln["vat_mode"])
        if ln["_id"] is not None:
            c.execute("UPDATE invoice_lines SET position=?,description=?,qty=?,unit=?,unit_rate=?,vat_mode=? WHERE id=? AND invoice_id=?", (*vals, ln["_id"], iid)); upd += 1
        else:
            c.execute("INSERT INTO invoice_lines(invoice_id,position,description,qty,unit,unit_rate,vat_mode,client_uid,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (iid, pos, ln["description"], ln["qty"], ln["unit"], ln["unit_rate"], ln["vat_mode"], ln["uid"], now)); ins += 1
    return ins, upd, len(gone)
