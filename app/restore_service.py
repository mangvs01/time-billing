"""Safe restore of a V9 JSON backup.

1. validate: structure, version, tables/columns known to the current schema, frozen PDF hashes;
2. preview: row counts current vs file, and issued documents that the restore would remove or alter
   (blocking: issued invoices and credit notes are never discarded by a restore);
3. restore: verified SQLite backup of the live DB, rebuild into a separate file with the current
   schema, integrity + foreign keys + PDF hashes checked, then atomic file swap.
rc25 (TB-05): an amputated file (business table missing, rows not matching meta.row_counts) is blocked, and the swap keeps the
CURRENT append-only audit log verbatim: the file's audit rows are only appended when the current log does not hold them.
"""
import base64, hashlib, json, os, re, secrets, sqlite3
from collections import Counter
from decimal import Decimal

SNAPSHOT_TABLES = {"invoice_snapshots": "invoice_id", "credit_note_snapshots": "credit_note_id", "credit_note_cancellations": "credit_note_id"}
# parents before children so the rebuilt file never depends on deferred FK checks
ORDER = ["settings", "projects", "billing_addresses", "historical_invoices", "import_batches", "entries", "entry_changes", "import_batch_rows", "invoice_date_changes", "invoice_number_changes", "invoices", "invoice_lines", "invoice_snapshots",
         "invoice_annex_entries", "credit_notes", "credit_note_lines", "credit_note_snapshots", "credit_note_cancellations", "credit_operations", "invoice_variance_decisions", "audit"]


# Operational state, never part of a backup: a restore must neither log the owner out nor bring a revoked session back to life.
TRANSIENT = ("web_sessions", "login_failures", "kept_forms")


class RestoreRefused(ValueError):
    pass


def _schema(conn):
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: {r[1]: (r[2] or "").upper() for r in conn.execute(f"PRAGMA table_info({t})")} for t in tables}


def validate(conn, raw):
    try: data = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError) as e: raise RestoreRefused(f"fichier JSON illisible ({type(e).__name__})")
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict) or not isinstance(data.get("tables"), dict):
        raise RestoreRefused("ce fichier n'est pas une sauvegarde JSON V9 (bloc meta/tables absent)")
    if not str(data["meta"].get("app_version", "")).startswith("9."):
        raise RestoreRefused(f"version de sauvegarde non prise en charge : {data['meta'].get('app_version')!r}")
    schema = _schema(conn); problems = []
    for t, rows in data["tables"].items():
        if t not in schema: problems.append(f"table inconnue : {t}"); continue
        if not isinstance(rows, list): problems.append(f"table {t} mal formée"); continue
        bad = next((r for r in rows if not isinstance(r, dict) or any(not isinstance(k, str) or isinstance(v, (dict, list)) for k, v in r.items())), None)
        if bad is not None: problems.append(f"table {t} : ligne mal formée (objet à valeurs simples attendu)"); continue
        for r in rows:
            extra = set(r) - set(schema[t])
            if extra: problems.append(f"{t} : colonnes inconnues {sorted(extra)}"); break
    for t, key in SNAPSHOT_TABLES.items():
        for r in data["tables"].get(t, []):
            try: pdf = base64.b64decode(r["pdf"], validate=True)
            except Exception: problems.append(f"{t} {r.get(key)} : PDF non décodable"); continue
            if hashlib.sha256(pdf).hexdigest() != r.get("pdf_sha256"): problems.append(f"{t} {r.get(key)} : empreinte du PDF figé invalide")
    if problems: raise RestoreRefused("sauvegarde refusée : " + " ; ".join(problems[:10]))
    return data


def _created_tables(schema_sql):
    """Tables created by the backup's own schema (meta.schema), or None when it is not a list of SQL strings."""
    if not isinstance(schema_sql, list) or not all(isinstance(x, str) for x in schema_sql): return None
    return {m.group(1) for x in schema_sql for m in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"?(\w+)', x, re.I)}


def completeness(conn, data):
    """rc25 (TB-05): every business table is in the file and every table holds exactly the rows declared in meta.row_counts.
    A table may only be absent from a file whose own schema predates it (not created in meta.schema, not counted), and only while
    it is empty in the current database: a restore never empties a table silently."""
    tables, declared = data["tables"], data["meta"].get("row_counts")
    if not isinstance(declared, dict) or any(type(v) is not int or v < 0 for v in declared.values()):
        return ["meta.row_counts absent ou mal formé : impossible de vérifier que la sauvegarde est complète"]
    out = []
    for t in sorted(set(declared) | set(tables)):
        if t not in tables: out.append(f"table {t} déclarée ({declared[t]} ligne(s)) mais absente de la sauvegarde")
        elif t not in declared: out.append(f"table {t} : nombre de lignes non déclaré dans meta.row_counts")
        elif declared[t] != len(tables[t]): out.append(f"table {t} : {len(tables[t])} ligne(s) pour {declared[t]} déclarée(s) dans meta.row_counts")
    created = _created_tables(data["meta"].get("schema"))
    for t in sorted(_schema(conn)):
        if t in TRANSIENT or t in tables or t in declared: continue
        if created is None or t in created: out.append(f"table métier {t} absente de la sauvegarde")
        elif conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone():
            out.append(f"table {t} absente d'une sauvegarde antérieure à sa création, mais non vide dans la base actuelle : ses lignes seraient perdues")
    return out


def preview(conn, data):
    counts = []
    for t in sorted(t for t in _schema(conn) if t not in TRANSIENT):
        counts.append({"table": t, "current": conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], "file": len(data["tables"].get(t, []))})
    file_inv = {r["id"]: r for r in data["tables"].get("invoices", [])}
    file_snap = {r["invoice_id"]: r["pdf_sha256"] for r in data["tables"].get("invoice_snapshots", [])}
    blocking = completeness(conn, data)
    for r in conn.execute("SELECT i.id,i.number,s.pdf_sha256 FROM invoices i LEFT JOIN invoice_snapshots s ON s.invoice_id=i.id WHERE i.status='issued'"):
        f = file_inv.get(r["id"])
        if not f or f.get("status") != "issued" or f.get("number") != r["number"]:
            blocking.append(f"la facture émise {r['number']} disparaîtrait ou changerait")
        elif file_snap.get(r["id"]) != r["pdf_sha256"]:
            blocking.append(f"la copie figée de la facture {r['number']} serait différente")
    file_cn = {r["id"]: r for r in data["tables"].get("credit_notes", [])}
    for r in conn.execute("SELECT id,reference FROM credit_notes WHERE status='issued'"):
        f = file_cn.get(r["id"])
        if not f or f.get("status") != "issued" or f.get("reference") != r["reference"]:
            blocking.append(f"la note de crédit émise {r['reference']} disparaîtrait ou changerait")
    if "credit_note_cancellations" in _schema(conn):
        file_k = {r["credit_note_id"]: r for r in data["tables"].get("credit_note_cancellations", [])}
        for r in conn.execute("SELECT credit_note_id,reference,pdf_sha256 FROM credit_note_cancellations"):
            f = file_k.get(r["credit_note_id"])
            if not f or f.get("reference") != r["reference"] or f.get("pdf_sha256") != r["pdf_sha256"]:
                blocking.append(f"le document d'annulation {r['reference']} disparaîtrait ou changerait")
    # the refund / offset ledger is append-only: a restore may not drop or alter any recorded operation
    if "credit_operations" in _schema(conn):
        file_ops = {r["id"]: r for r in data["tables"].get("credit_operations", [])}
        for r in conn.execute("SELECT o.id,o.kind,o.amount,o.credit_note_id,cn.reference FROM credit_operations o JOIN credit_notes cn ON cn.id=o.credit_note_id"):
            f = file_ops.get(r["id"])
            if not f or f.get("kind") != r["kind"] or f.get("amount") != r["amount"] or f.get("credit_note_id") != r["credit_note_id"]:
                blocking.append(f"l'opération n° {r['id']} ({r['kind']}) de la note de crédit {r['reference']} disparaîtrait ou changerait")
    # rc5: the invoice-date history is append-only as well
    if "invoice_date_changes" in _schema(conn):
        file_dc = {r["id"]: r for r in data["tables"].get("invoice_date_changes", [])}
        for r in conn.execute("SELECT id,invoice_id,old_date,new_date FROM invoice_date_changes"):
            f = file_dc.get(r["id"])
            if not f or (f.get("invoice_id"), f.get("old_date"), f.get("new_date")) != (r["invoice_id"], r["old_date"], r["new_date"]):
                blocking.append(f"la trace n° {r['id']} de modification de date (facture {r['invoice_id']}) disparaîtrait ou changerait")
    # rc10: the time-entry correction history is append-only too
    if "entry_changes" in _schema(conn):
        file_ec = {r["id"]: r for r in data["tables"].get("entry_changes", [])}
        for r in conn.execute("SELECT id,entry_id,action,before_json,after_json FROM entry_changes"):
            f = file_ec.get(r["id"])
            if not f or (f.get("entry_id"), f.get("action"), f.get("before_json"), f.get("after_json")) != (r["entry_id"], r["action"], r["before_json"], r["after_json"]):
                blocking.append(f"la trace n° {r['id']} de correction de saisie (saisie {r['entry_id']}) disparaîtrait ou changerait")
    blocking += immutable_diffs(conn, data)
    # rc23 (review 2026-10-08): a file may not validate one historical invoice twice (two validated rows of a corrected family, or one number twice)
    from app import historical_billing
    blocking += historical_billing.validation_conflicts(data["tables"].get("historical_invoices", []))
    blocking += annex_consistency(data)
    blocking += lines_consistency(data)
    blocking += annex_trail(data)
    return {"counts": counts, "blocking": blocking, "generated_at": data["meta"].get("generated_at"), "app_version": data["meta"].get("app_version")}


# --- immutability of issued documents: full-row comparison (security audit SEC-01) -------------------------
# table -> (key columns, SQL filter selecting, in the CURRENT database, the rows that must survive unchanged).
# Every column is compared, so a backup edited by hand (quantity, rate, frozen header, annex, history) is refused
# even when the status, number and PDF hash still match. The audit log is append-only in the database (rc13) but not listed here:
# it also records logins, exports and other routine events, so requiring every current row would block every restore of an older backup.
IMMUTABLE = {
    "invoices": (("id",), "WHERE status='issued'"),
    "credit_notes": (("id",), "WHERE status='issued'"),
    "invoice_snapshots": (("invoice_id",), ""),
    "credit_note_snapshots": (("credit_note_id",), ""),
    "credit_note_lines": (("id",), "WHERE credit_note_id IN (SELECT id FROM credit_notes WHERE status='issued')"),   # rc38: the credited manual lines of an issued note
    "invoice_lines": (("id",), "WHERE invoice_id IN (SELECT id FROM invoices WHERE status='issued')"),     # review rc40: the manual lines of an issued invoice (credit notes, turnover and exports read this table)
    "credit_note_cancellations": (("credit_note_id",), ""),
    "invoice_annex_entries": (("invoice_id", "entry_id"), ""),
    # rc19: annexed entries are no longer frozen here (a newer backup may carry a traced correction): annex_trail() requires instead that
    # every annexed entry of the file equals its frozen row, or is explained by the file's own history (correction or deletion)
    "credit_operations": (("id",), ""),
    "invoice_date_changes": (("id",), ""),
    "entry_changes": (("id",), ""),
    "invoice_variance_decisions": (("id",), ""),   # rc19: the user's decisions on post-invoicing variances are append-only
    # G4: historical invoices keep the values read from their source; only their status / validation / note can change, so a restore may not
    # drop or alter a recorded row (validating or rejecting it again is possible through the page, never through an older file)
    "historical_invoices": (("id",), "", ("project_id", "source_file", "source_sheet", "source_cell", "invoice_date", "qty_days", "amount_ht", "basis")),
}


def _jv(v):
    return base64.b64encode(v).decode() if isinstance(v, (bytes, bytearray)) else v


def annex_consistency(data):
    """The entries linked to an invoice must be exactly those of its frozen annex: a forged file may not add (and thereby lock) other entries."""
    linked = {}
    for r in data["tables"].get("invoice_annex_entries", []):
        if isinstance(r, dict): linked.setdefault(r.get("invoice_id"), set()).add(r.get("entry_id"))
    out = []
    for r in data["tables"].get("invoice_snapshots", []):
        try: ids = {x["id"] for x in json.loads(r["annex_json"])}
        except (ValueError, KeyError, TypeError): out.append(f"annexe figée illisible (facture {r.get('number')})"); continue
        if ids != linked.get(r.get("invoice_id"), set()): out.append(f"les saisies liées à la facture {r.get('number')} ne correspondent pas à son annexe figée")
    return out


def lines_consistency(data):
    """Review rc40: the manual lines of an issued invoice (and the credited lines of an issued credit note) in the file must be exactly the printed copy frozen in its snapshot:
    the credit-note caps, the turnover and the exports read the tables, the PDF and the screens of the document read the snapshot, so a forged file may not make them differ."""
    t = data["tables"]; out = []
    by_inv = {}
    for r in t.get("invoice_lines", []):
        if isinstance(r, dict): by_inv.setdefault(r.get("invoice_id"), []).append(r)
    for r in t.get("invoice_snapshots", []):
        try: header = json.loads(r["header_json"]); frozen = header.get("lines") or []
        except (ValueError, KeyError, TypeError, AttributeError): out.append(f"copie figée illisible (facture {r.get('number')})"); continue
        try:
            want = [(int(x["position"]), x["description"], float(x["qty"]), x["unit"], float(x["unit_rate"]), x["vat_mode"]) for x in frozen]
            have = sorted((int(x.get("position")), x.get("description"), float(x.get("qty")), x.get("unit"), float(x.get("unit_rate")), x.get("vat_mode")) for x in by_inv.get(r.get("invoice_id"), []))
        except (KeyError, TypeError, ValueError): out.append(f"lignes manuelles illisibles (facture {r.get('number')})"); continue
        if sorted(want) != have: out.append(f"les lignes manuelles de la facture {r.get('number')} ne correspondent pas à sa copie figée")
    by_cn = {}
    for r in t.get("credit_note_lines", []):
        if isinstance(r, dict): by_cn.setdefault(r.get("credit_note_id"), []).append(r)
    for r in t.get("credit_note_snapshots", []):
        try:
            frozen = json.loads(r["header_json"]).get("lines") or []
            want = sorted((int(x["invoice_line_id"]), x["description"], str(Decimal(str(x["amount"])).quantize(Decimal("0.01"))), x["vat_mode"]) for x in frozen)
            have = sorted((int(x.get("invoice_line_id")), x.get("description"), str(Decimal(str(x.get("amount"))).quantize(Decimal("0.01"))), x.get("vat_mode")) for x in by_cn.get(r.get("credit_note_id"), []))
        except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError): out.append(f"lignes créditées illisibles (note de crédit {r.get('reference')})"); continue
        if want != have: out.append(f"les lignes créditées de la note de crédit {r.get('reference')} ne correspondent pas à sa copie figée")
    return out[:10]


def annex_trail(data):
    """rc19: in the file, every entry listed in a frozen annex is either unchanged, or deleted / corrected WITH its history row
    (a hand-edited backup can neither resurrect a deleted billed entry nor carry an untraced change of one)."""
    from app.schema_checks import annex_trail_problems
    t = data["tables"]; rows = lambda n: [r for r in t.get(n, []) if isinstance(r, dict)]
    return annex_trail_problems(rows("invoice_snapshots"), {r.get("id"): r for r in rows("invoices")}, {r.get("id"): r for r in rows("entries")},
                                rows("entry_changes"))[:10]


def immutable_diffs(conn, data):
    """Every current row of an immutable table must be present, column for column, in the backup."""
    problems = []; schema = _schema(conn)
    for t, spec in IMMUTABLE.items():
        keys, flt = spec[:2]; only = spec[2] if len(spec) > 2 else None   # only: compare these columns (the others may legitimately change)
        if t not in schema: continue
        cols = list(schema[t])
        file_rows = {tuple(r.get(k) for k in keys): r for r in data["tables"].get(t, []) if isinstance(r, dict)}
        for row in conn.execute(f"SELECT * FROM {t} {flt}"):
            cur = dict(zip(cols, [_jv(v) for v in tuple(row)]))
            key = tuple(cur[k] for k in keys); f = file_rows.get(key)
            if f is None: problems.append(f"{t} {key} : ligne absente de la sauvegarde"); break
            cmp = [c for c in cols if only is None or c in only]
            diff = [c for c in cmp if c in f and f[c] != cur[c]] + [c for c in cmp if c not in f and cur[c] is not None]
            if diff: problems.append(f"{t} {key} : colonnes modifiées {diff[:4]}"); break
    return problems


def rebuild(target, data, init_schema, keep_from=None):
    """Create a fresh DB file at `target` with the current schema and the backup's rows.
    rc25: with keep_from (a live DB), the audit table is left empty here and filled by swap() under its lock (current log + new file rows)."""
    init_schema(target)
    c = sqlite3.connect(target, isolation_level=None)
    try:
        c.execute("PRAGMA foreign_keys=OFF"); c.execute("BEGIN IMMEDIATE")
        schema = _schema(c)
        for t in [t for t in schema if t not in ORDER and t not in TRANSIENT] + [t for t in ORDER if t in schema]:
            c.execute(f"DELETE FROM {t}")  # init may seed rows (none today); the file is authoritative
            if t == "audit" and keep_from: continue
            for r in data["tables"].get(t, []):
                cols = list(r)
                vals = [base64.b64decode(r[k]) if schema[t].get(k) == "BLOB" and r[k] is not None else r[k] for k in cols]
                c.execute(f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
        if keep_from:                      # current sessions and login throttling carry over unchanged
            live = sqlite3.connect(f"file:{keep_from}?mode=ro", uri=True)
            try:
                for t in TRANSIENT:
                    if t not in schema: continue
                    rows = live.execute(f"SELECT * FROM {t}").fetchall(); n = len(schema[t])
                    c.executemany(f"INSERT INTO {t} VALUES({','.join('?' * n)})", rows)
            finally:
                live.close()
        c.execute("COMMIT")
        c.execute("PRAGMA foreign_keys=ON")
        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise RestoreRefused("intégrité de la base reconstruite invalide")
        fk = c.execute("PRAGMA foreign_key_check").fetchall()
        if fk: raise RestoreRefused(f"{len(fk)} violation(s) de clé étrangère dans la sauvegarde")
        declared = data["meta"].get("row_counts")
        if not isinstance(declared, dict): raise RestoreRefused("meta.row_counts absent ou mal formé")
        for t in set(data["tables"]) | set(declared):
            if t in TRANSIENT or (t == "audit" and keep_from): continue
            if t not in data["tables"] or t not in declared: raise RestoreRefused(f"{t} : table ou nombre de lignes absent de la sauvegarde")
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            if n != len(data["tables"][t]) or n != declared[t]:
                raise RestoreRefused(f"{t} : {n} ligne(s) reconstruites pour {len(data['tables'][t])} dans le fichier et {declared[t]} déclarée(s)")
        for t in SNAPSHOT_TABLES:
            for pdf, sha in c.execute(f"SELECT pdf,pdf_sha256 FROM {t}"):
                if hashlib.sha256(pdf).hexdigest() != sha: raise RestoreRefused(f"{t} : empreinte invalide après reconstruction")
    finally:
        c.close()


def merge_audit(live, rebuilt, file_rows):
    """rc25 (TB-05): the rebuilt audit = every current row verbatim (same id, same content), then the file's rows that the current log
    does not already hold (compared without the id), appended with new ids. A restore never drops or rewrites a current audit row."""
    c = sqlite3.connect(rebuilt, isolation_level=None)
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(audit)")]; body = [k for k in cols if k != "id"]
        current = live.execute(f"SELECT {','.join(cols)} FROM audit ORDER BY id").fetchall()
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]: raise RestoreRefused("journal d'audit de la base reconstruite non vide")
        c.executemany(f"INSERT INTO audit({','.join(cols)}) VALUES({','.join('?' * len(cols))})", current)
        held = Counter(tuple(r[1:]) for r in current); appended = 0
        for r in sorted((r for r in file_rows if isinstance(r, dict)), key=lambda r: (r.get("id") is None, r.get("id") or 0)):
            key = tuple(r.get(k) for k in body)
            if held[key]: held[key] -= 1; continue
            c.execute(f"INSERT INTO audit({','.join(body)}) VALUES({','.join('?' * len(body))})", key); appended += 1
        if c.execute("SELECT COUNT(*) FROM audit").fetchone()[0] != len(current) + appended: raise RestoreRefused("journal d'audit incomplet après fusion")
        c.execute("COMMIT")
        return len(current), appended
    except Exception:
        if c.in_transaction: c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def swap(db_path, rebuilt, file_audit):
    """Replace the live DB file while holding an exclusive lock on it, so no writer is mid-transaction.
    rc25: the current audit log and the file's audit rows (file_audit) are merged into the rebuilt file under that same lock,
    so no audit row written between rebuild() and the swap is lost. Returns (current rows kept, file rows appended)."""
    lock = sqlite3.connect(db_path, isolation_level=None, timeout=15)
    try:
        lock.execute("BEGIN EXCLUSIVE")
        kept = merge_audit(lock, rebuilt, file_audit)
        os.replace(rebuilt, db_path)
    finally:
        try: lock.execute("ROLLBACK")
        except Exception: pass
        lock.close()
    return kept


def temp_path(db_path):
    return f"{db_path}.restore-{secrets.token_hex(4)}"
