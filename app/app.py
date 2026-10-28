import os, sqlite3, io, json, csv, secrets, re, hashlib, time, base64, math, zipfile, unicodedata
from urllib import parse as urllib_parse
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
from functools import wraps
from werkzeug.exceptions import HTTPException
from flask import Flask, request, redirect, render_template, flash, send_file, jsonify, session, abort, g, url_for, make_response
# Package-qualified imports: gunicorn loads "app.app" from /app, so /app/app is not on sys.path.
from app import pdf_layout, historical_import, import_service, invoice_service, credit_service as credits, billing_rules as rules, forecast as forecast_mod, restore_service, security, post_billing, historical_billing, invoice_checks, calendar_service as cal, invoice_lines as manual_lines, address_service as addresses, credit_lines
from app.rollback_service import rollback_import
os.umask(0o077)  # RC10: every file the service creates (backups, staged imports, restore copies) is private to its owner
# RC8: secrets from the environment only, validated at startup (fail closed); values never logged
SEC=security.load(os.environ)
APP=Flask(__name__); APP.secret_key=SEC["key"]; APP.config.update(security.cookie_config(SEC))
if SEC["trust_proxy"]:
 from werkzeug.middleware.proxy_fix import ProxyFix
 APP.wsgi_app=ProxyFix(APP.wsgi_app,x_for=1,x_proto=1,x_host=1)
APP.config["MAX_CONTENT_LENGTH"]=15*1024*1024
# Calendrier : rc36 CANDIDATE (tests only; not built, not deployed) — rc35 = thème sombre (autre mission)
VERSION="9.2-rc42"
# Optional label shown in the page title (e.g. "STAGING" on the test instance); empty in production.
ENV_LABEL=(os.environ.get("ENV_LABEL") or "").strip()[:30]
DB=os.environ.get("DB_PATH","/data/timebilling.db")
TOKEN_RE=re.compile(r"^[A-Za-z0-9_-]{32}$")
def connect(path,autocommit=False):
 c=sqlite3.connect(path,timeout=15,isolation_level=None if autocommit else ""); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); return c
def db(autocommit=False):
 # autocommit=True: caller manages BEGIN IMMEDIATE / COMMIT / ROLLBACK explicitly.
 return connect(DB,autocommit)
def import_dir(): return os.path.join(os.path.dirname(DB),"import-staging")
def backup_dir(): return os.path.join(os.path.dirname(DB),"backups")
def ensure_column(c, table, name, definition):
 cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})")]
 if name in cols:
  return
 try:
  c.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
 except sqlite3.OperationalError as e:
  if "duplicate column name" not in str(e).lower():
   raise
  cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})")]
  if name not in cols:
   raise

ANNEX_TABLE="CREATE TABLE invoice_annex_entries(invoice_id INTEGER NOT NULL REFERENCES invoices(id), entry_id INTEGER NOT NULL, PRIMARY KEY(invoice_id,entry_id))"
ANNEX_TRIGGERS=("CREATE TRIGGER invoice_annex_no_update BEFORE UPDATE ON invoice_annex_entries BEGIN SELECT RAISE(ABORT,'Frozen invoice annex is immutable'); END;",
                "CREATE TRIGGER invoice_annex_no_delete BEFORE DELETE ON invoice_annex_entries BEGIN SELECT RAISE(ABORT,'Frozen invoice annex cannot be deleted'); END;")
# rc19 (defence in depth): any entry may change, but never silently, even outside the application: the database itself appends the
# before / after values to the (append-only) audit log; 'invoiced' tells whether a frozen annex lists the entry
_ENTRY_JSON="json_object('work_date',{0}.work_date,'project_id',{0}.project_id,'start_time',{0}.start_time,'end_time',{0}.end_time,'hours',{0}.hours,'description',{0}.description)"
_INVOICED="'invoiced',EXISTS(SELECT 1 FROM invoice_annex_entries WHERE entry_id=OLD.id)"
ENTRY_TRIGGERS=(
 "CREATE TRIGGER entry_update_traced AFTER UPDATE ON entries "
 "BEGIN INSERT INTO audit(event,detail) VALUES('entry_row_updated',json_object('id',OLD.id,"+_INVOICED+",'before',"+_ENTRY_JSON.format("OLD")+",'after',"+_ENTRY_JSON.format("NEW")+")); END;",
 "CREATE TRIGGER entry_delete_traced AFTER DELETE ON entries "
 "BEGIN INSERT INTO audit(event,detail) VALUES('entry_row_deleted',json_object('id',OLD.id,"+_INVOICED+",'before',"+_ENTRY_JSON.format("OLD")+")); END;")
ENTRY_TRIGGERS+=(
 # an id that ever existed (history, frozen annex, import register) is never given again: a new entry may not inherit them
 "CREATE TRIGGER entry_id_never_reused BEFORE INSERT ON entries WHEN EXISTS(SELECT 1 FROM entry_changes WHERE entry_id=NEW.id) "
 "OR EXISTS(SELECT 1 FROM invoice_annex_entries WHERE entry_id=NEW.id) OR EXISTS(SELECT 1 FROM import_batch_rows WHERE entry_id=NEW.id) "
 "BEGIN SELECT RAISE(ABORT,'An entry id that ever existed is never given again'); END;",)
RC19_TRIGGER_NAMES=("annexed_entry_no_update","annexed_entry_no_delete","invoiced_entry_update_traced","invoiced_entry_delete_traced","entry_update_traced","entry_delete_traced","entry_id_never_reused")
def migrate_rc19(path):
 """rc19: an entry listed in the frozen annex of an issued invoice can be corrected AND deleted; the invoice keeps its frozen copy
 (snapshot annex_json + link rows, both immutable). SQLite cannot drop a constraint, so the foreign key
 invoice_annex_entries.entry_id -> entries(id) is removed by rebuilding the table once.
 Every start (each gunicorn worker runs init()): ONE transaction under BEGIN IMMEDIATE, so a second worker waits and then sees the finished
 state. Inside it: the key is checked again; every trigger reading the annex table is dropped BEFORE the rename (ALTER TABLE ... RENAME
 rewrites them to the temporary name); same rows, primary key, index and immutability triggers are checked; the rc19 triggers are dropped
 and created again (a stale or broken definition heals at the next start). Then compile probes: a trigger pointing to a missing table
 passes integrity_check and foreign_key_check, not a compiled write. Any failure: ROLLBACK and the service does not start.
 A new database is created without the key: the rebuild (and its audit row) never runs on a fresh file, e.g. a restore rebuild."""
 c=sqlite3.connect(path,timeout=30,isolation_level=None)
 try:
  c.execute("PRAGMA foreign_keys=OFF")            # effective only outside a transaction: set before BEGIN
  c.execute("BEGIN IMMEDIATE")
  try:
   rebuilt=None
   if any(r[2]=="entries" for r in c.execute("PRAGMA foreign_key_list(invoice_annex_entries)")):
    before=c.execute("SELECT invoice_id,entry_id FROM invoice_annex_entries ORDER BY invoice_id,entry_id").fetchall()
    for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name<>'invoice_annex_entries' AND sql LIKE '%invoice_annex_entries%'").fetchall():
     c.execute(f'DROP TRIGGER "{name}"')
    c.execute("ALTER TABLE invoice_annex_entries RENAME TO invoice_annex_entries_rc18")
    c.execute(ANNEX_TABLE)
    c.execute("INSERT INTO invoice_annex_entries(invoice_id,entry_id) SELECT invoice_id,entry_id FROM invoice_annex_entries_rc18")
    c.execute("DROP TABLE invoice_annex_entries_rc18")   # its triggers and index go with it
    c.execute("CREATE INDEX idx_annex_entry ON invoice_annex_entries(entry_id)")
    for t in ANNEX_TRIGGERS: c.execute(t)
    after=c.execute("SELECT invoice_id,entry_id FROM invoice_annex_entries ORDER BY invoice_id,entry_id").fetchall()
    if after!=before: raise RuntimeError("migration rc19 : liens d'annexe différents après reconstruction")
    if c.execute("PRAGMA foreign_key_check(invoice_annex_entries)").fetchall(): raise RuntimeError("migration rc19 : clé étrangère invalide")
    if any(r[2]=="entries" for r in c.execute("PRAGMA foreign_key_list(invoice_annex_entries)")): raise RuntimeError("migration rc19 : clé étrangère toujours présente")
    rebuilt=len(after)
   for name in RC19_TRIGGER_NAMES: c.execute(f"DROP TRIGGER IF EXISTS {name}")
   for t in ENTRY_TRIGGERS: c.execute(t)
   for t in ANNEX_TRIGGERS: c.execute(t.replace("CREATE TRIGGER ","CREATE TRIGGER IF NOT EXISTS ",1))
   left=c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'invoice_annex_entries_%'").fetchall()
   if left: raise RuntimeError(f"migration rc19 : table temporaire restante {left}")
   if rebuilt is not None: c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("schema_rc19_annex_rebuilt",f"links={rebuilt}"))
   from app.schema_checks import PROBES
   for q in PROBES: c.execute(q).fetchall()            # fresh connection: no cached statement
   c.execute("COMMIT")
  except Exception:
   c.execute("ROLLBACK"); raise
  finally: c.execute("PRAGMA foreign_keys=ON")
 finally: c.close()
def ensure_number_index(c):
 """rc37 (P3): case- and space-insensitive unicity of invoice numbers, on top of the binary UNIQUE column. Created only when the existing numbers hold no such duplicate (a unique index
 over duplicates would fail and stop the start-up): otherwise it is skipped, recorded once in the audit log, and reported by schema_checks; the application still refuses duplicates
 itself. Returns True when the index exists."""
 dup=c.execute("SELECT upper(trim(number)) k,COUNT(*) n FROM invoices WHERE number IS NOT NULL GROUP BY k HAVING n>1").fetchall()
 if dup:
  if not c.execute("SELECT 1 FROM audit WHERE event='invoice_number_index_skipped'").fetchone():
   c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("invoice_number_index_skipped","duplicates (case/space): "+", ".join(r["k"] for r in dup)))
  return False
 c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_number_norm ON invoices(upper(trim(number))) WHERE number IS NOT NULL")
 return True
def init(path=None):
 """Additive, idempotent schema migration. path: alternate DB file (restore rebuild)."""
 path=path or DB
 with connect(path) as c:
  c.executescript("""
  CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,client TEXT DEFAULT '',po TEXT DEFAULT '',rate REAL DEFAULT 0,day_hours REAL DEFAULT 8,vat REAL DEFAULT 0,ordered_days REAL DEFAULT 0,start_date TEXT DEFAULT '',duration_months INTEGER DEFAULT 12,active INTEGER DEFAULT 1);
  CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY,work_date TEXT NOT NULL,project_id INTEGER NOT NULL REFERENCES projects(id),start_time TEXT DEFAULT '',end_time TEXT DEFAULT '',hours REAL NOT NULL,description TEXT DEFAULT '',source TEXT DEFAULT 'manual',source_ref TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY,number TEXT UNIQUE,project_id INTEGER NOT NULL REFERENCES projects(id),period_from TEXT NOT NULL,period_to TEXT NOT NULL,qty REAL NOT NULL,unit TEXT NOT NULL DEFAULT 'day',unit_rate REAL NOT NULL,vat REAL NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'draft',issued_at TEXT,note TEXT DEFAULT '',rounding TEXT DEFAULT 'exact',rounding_step REAL DEFAULT 0.25,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,event TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS import_batches(id TEXT PRIMARY KEY, source_filename TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('PREPARED','COMMITTED','ROLLED_BACK','FAILED')), source_rows INTEGER NOT NULL DEFAULT 0, inserted_rows INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, rolled_back_at TEXT, backup_filename TEXT, notes TEXT DEFAULT '');
  CREATE TRIGGER IF NOT EXISTS issued_invoice_no_update BEFORE UPDATE ON invoices WHEN OLD.status='issued' BEGIN SELECT RAISE(ABORT,'Issued invoices are immutable'); END;
  CREATE TRIGGER IF NOT EXISTS issued_invoice_no_delete BEFORE DELETE ON invoices WHEN OLD.status='issued' BEGIN SELECT RAISE(ABORT,'Issued invoices cannot be deleted'); END;
  CREATE TABLE IF NOT EXISTS web_sessions(sid TEXT PRIMARY KEY, created_at TEXT NOT NULL, last_seen TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS kept_forms(sid TEXT PRIMARY KEY, path TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS login_failures(id INTEGER PRIMARY KEY, ip TEXT NOT NULL, at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_login_failures ON login_failures(ip, at);
  CREATE TABLE IF NOT EXISTS credit_notes(id INTEGER PRIMARY KEY, reference TEXT UNIQUE, invoice_id INTEGER NOT NULL REFERENCES invoices(id), amount REAL NOT NULL, reason TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  """)
  ensure_column(c, "entries", "import_batch_id", "import_batch_id TEXT REFERENCES import_batches(id)")
  c.execute("CREATE INDEX IF NOT EXISTS idx_entries_import_batch ON entries(import_batch_id)")
  for t,col,d in [("projects","start_date","TEXT DEFAULT ''"),("projects","duration_months","INTEGER DEFAULT 12"),("invoices","rounding","TEXT DEFAULT 'exact'"),("invoices","rounding_step","REAL DEFAULT 0.25"),
                  ("import_batches","file_sha256","TEXT"),("import_batches","backup_sha256","TEXT"),("import_batches","error","TEXT"),
                  # V9.2: billing identity per mandate, closure, document fields, reliquat decision, credit-note workflow
                  ("projects","project_number","TEXT DEFAULT ''"),("projects","billing_contact","TEXT DEFAULT ''"),("projects","billing_address","TEXT DEFAULT ''"),("projects","dates_label","TEXT DEFAULT ''"),
                  ("projects","closed_at","TEXT"),("projects","closed_reason","TEXT DEFAULT ''"),
                  ("invoices","description","TEXT DEFAULT ''"),("invoices","other_amount","REAL DEFAULT 0"),("invoices","other_label","TEXT DEFAULT ''"),("invoices","invoice_date","TEXT"),
                  ("invoices","reliquat_days","REAL"),("invoices","reliquat_treatment","TEXT"),("invoices","reliquat_note","TEXT DEFAULT ''"),
                  ("credit_notes","status","TEXT NOT NULL DEFAULT 'draft'"),("credit_notes","issued_at","TEXT"),("credit_notes","qty","REAL"),("credit_notes","unit_rate","REAL"),
                  ("credit_notes","vat","REAL NOT NULL DEFAULT 0"),("credit_notes","description","TEXT DEFAULT ''"),
                  # V9.2 credit settlement: per-document choice, refund or offset (NULL only for notes created before it)
                  ("credit_notes","treatment","TEXT"),("credit_notes","tva_amount","REAL"),
                  # rc3: explicit AUTRES VAT, legal client identity, optional refund deadline, traceable replacement
                  ("invoices","other_vat_mode","TEXT"),("projects","client_legal_name","TEXT DEFAULT ''"),("projects","client_legal_id","TEXT DEFAULT ''"),
                  ("credit_notes","other_amount","REAL DEFAULT 0"),("credit_notes","other_vat_mode","TEXT"),("credit_notes","refund_delay_days","INTEGER"),
                  ("credit_notes","refund_due_on","TEXT"),("credit_notes","replaces_credit_id","INTEGER REFERENCES credit_notes(id)"),
                  # rc4: short mandate name printed in the annex / summary (falls back to the full name)
                  ("projects","short_name","TEXT DEFAULT ''"),
                  # rc37 (P1): revision counter of a draft (a stale editor tab is refused instead of overwriting a newer save)
                  ("invoices","revision","INTEGER NOT NULL DEFAULT 0"),
                  # rc37 (P2): billing address chosen for the invoice = id of billing_addresses + the COPIED text (instantané); NULL = the mandate's own address, as before
                  ("invoices","billing_address_id","INTEGER"),("invoices","bill_label","TEXT"),("invoices","bill_contact","TEXT"),("invoices","bill_address","TEXT"),
                  # rc37 (P3): 1 = the number of the draft was typed by the user (never replaced automatically), 0 = proposed by the application
                  ("invoices","number_manual","INTEGER NOT NULL DEFAULT 0"),
                  # rc38: HT credited on the manual lines of the invoice, by VAT regime (the detail is in credit_note_lines, see app/credit_lines.py)
                  ("credit_notes","lines_taxed","REAL NOT NULL DEFAULT 0"),("credit_notes","lines_untaxed","REAL NOT NULL DEFAULT 0")]:
   ensure_column(c, t, col, f"{col} {d}")
  c.execute(addresses.DDL); addresses.make_global(c)   # rc37 (P2) ; rc40: the four seeded addresses become the global list: reusable billing addresses (one definition, shared with scripts/seed_adresses_egg.py)
  c.executescript("""
  CREATE TABLE IF NOT EXISTS import_batch_rows(id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES import_batches(id), source_sheet TEXT NOT NULL, source_row INTEGER NOT NULL, raw_json TEXT NOT NULL, issues TEXT NOT NULL DEFAULT '', decision TEXT NOT NULL, entry_id INTEGER, UNIQUE(batch_id,source_sheet,source_row));
  CREATE INDEX IF NOT EXISTS idx_import_rows_source ON import_batch_rows(source_sheet,source_row);
  CREATE TABLE IF NOT EXISTS invoice_snapshots(invoice_id INTEGER PRIMARY KEY REFERENCES invoices(id), number TEXT NOT NULL, frozen_at TEXT NOT NULL, frozen_by TEXT NOT NULL, header_json TEXT NOT NULL, annex_json TEXT NOT NULL, pdf BLOB NOT NULL, pdf_sha256 TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS invoice_annex_entries(invoice_id INTEGER NOT NULL REFERENCES invoices(id), entry_id INTEGER NOT NULL, PRIMARY KEY(invoice_id,entry_id));
  CREATE INDEX IF NOT EXISTS idx_annex_entry ON invoice_annex_entries(entry_id);
  -- rc37 (P1): manual lines of a draft invoice. Additive; rows of a draft are free, a frozen invoice (snapshot taken at issuance) never changes again:
  -- the printed copy lives in the snapshot header. The insert guard looks at the SNAPSHOT (not the status) so a restore can rebuild issued invoices' lines first.
  CREATE TABLE IF NOT EXISTS invoice_lines(id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL REFERENCES invoices(id), position INTEGER NOT NULL CHECK(position>0),
    kind TEXT NOT NULL DEFAULT 'manual' CHECK(kind='manual'), description TEXT NOT NULL CHECK(length(trim(description))>0), qty REAL NOT NULL CHECK(qty>0),
    unit TEXT NOT NULL CHECK(unit IN ('day','hour','flat','piece')), unit_rate REAL NOT NULL CHECK(unit_rate>=0), vat_mode TEXT NOT NULL CHECK(vat_mode IN ('soumis','hors_tva')),
    client_uid TEXT, created_at TEXT NOT NULL, UNIQUE(invoice_id,position), UNIQUE(invoice_id,client_uid));
  CREATE TRIGGER IF NOT EXISTS invoice_lines_no_insert_frozen BEFORE INSERT ON invoice_lines WHEN EXISTS(SELECT 1 FROM invoice_snapshots WHERE invoice_id=NEW.invoice_id) BEGIN SELECT RAISE(ABORT,'Lines of an issued invoice are immutable'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_lines_no_update_issued BEFORE UPDATE ON invoice_lines WHEN (SELECT status FROM invoices WHERE id=OLD.invoice_id)='issued' BEGIN SELECT RAISE(ABORT,'Lines of an issued invoice are immutable'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_lines_no_delete_issued BEFORE DELETE ON invoice_lines WHEN (SELECT status FROM invoices WHERE id=OLD.invoice_id)='issued' BEGIN SELECT RAISE(ABORT,'Lines of an issued invoice cannot be deleted'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_snapshot_no_update BEFORE UPDATE ON invoice_snapshots BEGIN SELECT RAISE(ABORT,'Frozen invoice snapshots are immutable'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_snapshot_no_delete BEFORE DELETE ON invoice_snapshots BEGIN SELECT RAISE(ABORT,'Frozen invoice snapshots cannot be deleted'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_annex_no_update BEFORE UPDATE ON invoice_annex_entries BEGIN SELECT RAISE(ABORT,'Frozen invoice annex is immutable'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_annex_no_delete BEFORE DELETE ON invoice_annex_entries BEGIN SELECT RAISE(ABORT,'Frozen invoice annex cannot be deleted'); END;
  -- rc19: no trigger forbids changing an entry listed in a frozen annex any more (see migrate_rc19): the issued invoice keeps its
  -- frozen copy (snapshot + annex links above, both immutable) and the entry stays editable, with its history
  CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS credit_note_snapshots(credit_note_id INTEGER PRIMARY KEY REFERENCES credit_notes(id), reference TEXT NOT NULL, frozen_at TEXT NOT NULL, header_json TEXT NOT NULL, pdf BLOB NOT NULL, pdf_sha256 TEXT NOT NULL);
  CREATE TRIGGER IF NOT EXISTS issued_credit_no_update BEFORE UPDATE ON credit_notes WHEN OLD.status='issued' BEGIN SELECT RAISE(ABORT,'Issued credit notes are immutable'); END;
  CREATE TRIGGER IF NOT EXISTS issued_credit_no_delete BEFORE DELETE ON credit_notes WHEN OLD.status='issued' BEGIN SELECT RAISE(ABORT,'Issued credit notes cannot be deleted'); END;
  CREATE TRIGGER IF NOT EXISTS credit_snapshot_no_update BEFORE UPDATE ON credit_note_snapshots BEGIN SELECT RAISE(ABORT,'Frozen credit notes are immutable'); END;
  CREATE TRIGGER IF NOT EXISTS credit_snapshot_no_delete BEFORE DELETE ON credit_note_snapshots BEGIN SELECT RAISE(ABORT,'Frozen credit notes cannot be deleted'); END;
  CREATE TRIGGER IF NOT EXISTS credit_only_on_issued BEFORE INSERT ON credit_notes WHEN (SELECT status FROM invoices WHERE id=NEW.invoice_id)<>'issued' BEGIN SELECT RAISE(ABORT,'Credit notes require an issued invoice'); END;
  CREATE TRIGGER IF NOT EXISTS credit_treatment_valid BEFORE INSERT ON credit_notes WHEN NEW.treatment IS NOT NULL AND NEW.treatment NOT IN ('remboursement','compensation') BEGIN SELECT RAISE(ABORT,'Unknown credit treatment'); END;
  CREATE TRIGGER IF NOT EXISTS credit_treatment_valid_upd BEFORE UPDATE OF treatment ON credit_notes WHEN NEW.treatment IS NOT NULL AND NEW.treatment NOT IN ('remboursement','compensation') BEGIN SELECT RAISE(ABORT,'Unknown credit treatment'); END;
  CREATE TRIGGER IF NOT EXISTS credit_issue_needs_treatment BEFORE UPDATE OF status ON credit_notes WHEN NEW.status='issued' AND NEW.treatment IS NULL BEGIN SELECT RAISE(ABORT,'Credit treatment required before issuance'); END;
  -- target_invoice_id has no FK on purpose: a deleted draft keeps its (reversed) history; target_label records what it was
  CREATE TABLE IF NOT EXISTS credit_operations(id INTEGER PRIMARY KEY AUTOINCREMENT, credit_note_id INTEGER NOT NULL REFERENCES credit_notes(id),
    kind TEXT NOT NULL CHECK(kind IN ('refund','refund_reversal','offset','offset_reversal')), amount REAL NOT NULL CHECK(amount>0),
    target_invoice_id INTEGER, target_label TEXT DEFAULT '', reverses_id INTEGER UNIQUE REFERENCES credit_operations(id),
    executed_on TEXT, external_ref TEXT DEFAULT '', note TEXT DEFAULT '', created_at TEXT NOT NULL,
    CHECK((kind LIKE '%_reversal')=(reverses_id IS NOT NULL)), CHECK(kind<>'offset' OR target_invoice_id IS NOT NULL), CHECK(kind<>'refund' OR executed_on IS NOT NULL));
  CREATE INDEX IF NOT EXISTS idx_credit_ops_note ON credit_operations(credit_note_id);
  -- cancellation document of an issued credit note (the note itself stays unchanged and visible)
  CREATE TABLE IF NOT EXISTS credit_note_cancellations(credit_note_id INTEGER PRIMARY KEY REFERENCES credit_notes(id), reference TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL, issued_at TEXT NOT NULL, header_json TEXT NOT NULL, pdf BLOB NOT NULL, pdf_sha256 TEXT NOT NULL);
  CREATE TRIGGER IF NOT EXISTS credit_cancel_no_update BEFORE UPDATE ON credit_note_cancellations BEGIN SELECT RAISE(ABORT,'Credit note cancellations are immutable'); END;
  CREATE TRIGGER IF NOT EXISTS credit_cancel_no_delete BEFORE DELETE ON credit_note_cancellations BEGIN SELECT RAISE(ABORT,'Credit note cancellations are immutable'); END;
  CREATE TRIGGER IF NOT EXISTS credit_cancel_issued_only BEFORE INSERT ON credit_note_cancellations WHEN (SELECT status FROM credit_notes WHERE id=NEW.credit_note_id) IS NOT 'issued' BEGIN SELECT RAISE(ABORT,'Only an issued credit note can be cancelled'); END;
  CREATE TRIGGER IF NOT EXISTS credit_ops_not_cancelled BEFORE INSERT ON credit_operations WHEN EXISTS(SELECT 1 FROM credit_note_cancellations WHERE credit_note_id=NEW.credit_note_id) BEGIN SELECT RAISE(ABORT,'Cancelled credit note'); END;
  CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_replaces ON credit_notes(replaces_credit_id) WHERE replaces_credit_id IS NOT NULL;
  CREATE INDEX IF NOT EXISTS idx_credit_ops_target ON credit_operations(target_invoice_id);
  CREATE TRIGGER IF NOT EXISTS credit_ops_no_update BEFORE UPDATE ON credit_operations BEGIN SELECT RAISE(ABORT,'Credit operations are append-only'); END;
  CREATE TRIGGER IF NOT EXISTS credit_ops_no_delete BEFORE DELETE ON credit_operations BEGIN SELECT RAISE(ABORT,'Credit operations are append-only'); END;
  CREATE TRIGGER IF NOT EXISTS credit_ops_issued_only BEFORE INSERT ON credit_operations WHEN (SELECT status FROM credit_notes WHERE id=NEW.credit_note_id) IS NOT 'issued' BEGIN SELECT RAISE(ABORT,'Operations require an issued credit note'); END;
  CREATE TRIGGER IF NOT EXISTS credit_ops_match_treatment BEFORE INSERT ON credit_operations
    WHEN (NEW.kind LIKE 'refund%' AND (SELECT treatment FROM credit_notes WHERE id=NEW.credit_note_id) IS NOT 'remboursement')
      OR (NEW.kind LIKE 'offset%' AND (SELECT treatment FROM credit_notes WHERE id=NEW.credit_note_id) IS NOT 'compensation')
    BEGIN SELECT RAISE(ABORT,'Operation kind does not match the credit treatment'); END;
  -- rc5 (decision 5): every invoice-date change made on a draft, append-only; no FK so a deleted draft keeps its trace
  CREATE TABLE IF NOT EXISTS invoice_date_changes(id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL, old_date TEXT, new_date TEXT,
    context TEXT NOT NULL DEFAULT '', changed_at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_invoice_date_changes ON invoice_date_changes(invoice_id);
  CREATE TRIGGER IF NOT EXISTS invoice_date_changes_no_update BEFORE UPDATE ON invoice_date_changes BEGIN SELECT RAISE(ABORT,'Invoice date history is append-only'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_date_changes_no_delete BEFORE DELETE ON invoice_date_changes BEGIN SELECT RAISE(ABORT,'Invoice date history is append-only'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_date_changes_draft_only BEFORE INSERT ON invoice_date_changes WHEN (SELECT status FROM invoices WHERE id=NEW.invoice_id)='issued'
    BEGIN SELECT RAISE(ABORT,'The date of an issued invoice cannot change'); END;
  -- rc7 (A6): the real issuance timestamp is written once, by the draft → issued transition, and never afterwards
  CREATE TRIGGER IF NOT EXISTS invoice_issued_at_only_at_issue BEFORE UPDATE OF issued_at ON invoices
    WHEN OLD.status='draft' AND NEW.issued_at IS NOT NULL AND NEW.status IS NOT 'issued'
    BEGIN SELECT RAISE(ABORT,'issued_at is set only when the invoice is issued'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_issue_needs_issued_at BEFORE UPDATE OF status ON invoices
    WHEN OLD.status='draft' AND NEW.status='issued' AND (NEW.issued_at IS NULL OR NEW.issued_at='')
    BEGIN SELECT RAISE(ABORT,'An issued invoice needs its real issuance timestamp'); END;
  CREATE TRIGGER IF NOT EXISTS credit_ops_reversal_matches BEFORE INSERT ON credit_operations WHEN NEW.reverses_id IS NOT NULL AND
    (SELECT kind||'_reversal' FROM credit_operations WHERE id=NEW.reverses_id AND credit_note_id=NEW.credit_note_id AND amount=NEW.amount) IS NOT NEW.kind
    BEGIN SELECT RAISE(ABORT,'A reversal must cancel one operation of the same note, kind and amount'); END;
  -- rc10: every correction or deletion of a manual time entry, append-only (full before/after copy); no FK so a deleted entry keeps its trace
  CREATE TABLE IF NOT EXISTS entry_changes(id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL, action TEXT NOT NULL CHECK(action IN ('update','delete')),
    before_json TEXT NOT NULL, after_json TEXT, changed_at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_entry_changes_entry ON entry_changes(entry_id);
  CREATE TRIGGER IF NOT EXISTS entry_changes_no_update BEFORE UPDATE ON entry_changes BEGIN SELECT RAISE(ABORT,'Time entry history is append-only'); END;
  CREATE TRIGGER IF NOT EXISTS entry_changes_no_delete BEFORE DELETE ON entry_changes BEGIN SELECT RAISE(ABORT,'Time entry history is append-only'); END;
  -- rc13 (QA-S3): defence in depth below the application. The audit log is append-only; the net refunded / offset amount of a credit note
  -- can never exceed what the note can carry (service + AUTRES, VAT at the note's rate; 5 centimes of slack for per-note rounding)
  CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'The audit log is append-only'); END;
  CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'The audit log is append-only'); END;
  CREATE TRIGGER IF NOT EXISTS credit_ops_within_note BEFORE INSERT ON credit_operations WHEN NEW.kind IN ('refund','offset') AND
    COALESCE((SELECT SUM(CASE WHEN kind IN ('refund','offset') THEN amount ELSE -amount END) FROM credit_operations WHERE credit_note_id=NEW.credit_note_id),0)+NEW.amount >
    (SELECT (amount+COALESCE(other_amount,0))*(1+COALESCE(vat,0)/100.0)+0.05 FROM credit_notes WHERE id=NEW.credit_note_id)
    BEGIN SELECT RAISE(ABORT,'The operations of a credit note cannot exceed its amount'); END;
  """)
  # rc19: who changed an entry, why, and which issued invoices were concerned (append-only like the rest of the history)
  for col in ("reason","actor","invoices_json"):           # NULL = row written before rc19
   ensure_column(c,"entry_changes",col,f"{col} TEXT")
  c.executescript("""
  CREATE INDEX IF NOT EXISTS idx_import_rows_entry ON import_batch_rows(entry_id);
  -- rc19: the user's decision on the post-invoicing variance of an issued invoice (credit note, compensation, or no action), append-only.
  -- fingerprint = the variance it answers: a later change of a billed entry makes it outdated (the alert comes back)
  CREATE TABLE IF NOT EXISTS invoice_variance_decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    decision TEXT NOT NULL CHECK(decision IN ('avoir','compensation','aucune')), credit_note_id INTEGER REFERENCES credit_notes(id),
    variance_hours REAL NOT NULL, fingerprint TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT '', decided_at TEXT NOT NULL,
    CHECK(decision<>'avoir' OR credit_note_id IS NOT NULL));
  CREATE INDEX IF NOT EXISTS idx_variance_decisions ON invoice_variance_decisions(invoice_id);
  CREATE TRIGGER IF NOT EXISTS variance_decisions_no_update BEFORE UPDATE ON invoice_variance_decisions BEGIN SELECT RAISE(ABORT,'Variance decisions are append-only'); END;
  CREATE TRIGGER IF NOT EXISTS variance_decisions_no_delete BEFORE DELETE ON invoice_variance_decisions BEGIN SELECT RAISE(ABORT,'Variance decisions are append-only'); END;
  CREATE TRIGGER IF NOT EXISTS variance_decisions_issued_only BEFORE INSERT ON invoice_variance_decisions WHEN (SELECT status FROM invoices WHERE id=NEW.invoice_id) IS NOT 'issued'
    BEGIN SELECT RAISE(ABORT,'A variance decision concerns an issued invoice'); END;
  CREATE TRIGGER IF NOT EXISTS variance_decisions_issued_note BEFORE INSERT ON invoice_variance_decisions WHEN NEW.credit_note_id IS NOT NULL AND
    (SELECT status FROM credit_notes WHERE id=NEW.credit_note_id AND invoice_id=NEW.invoice_id) IS NOT 'issued'
    BEGIN SELECT RAISE(ABORT,'A credit note decision needs an issued credit note of the same invoice'); END;
  -- G4: invoices issued OUTSIDE the application (the user's SUIVI workbook), kept apart from `invoices`: never editable as an invoice, never given
  -- a number or a PDF, never recreated as an issued invoice. Each row carries the cell it was read from. Only 'validated' rows feed the indicators
  -- (billed days, PO balance, annual turnover, annex position); 'proposed' rows (loaded by the import tool) and 'rejected' rows count for nothing.
  CREATE TABLE IF NOT EXISTS historical_invoices(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id),
    source_file TEXT NOT NULL, source_sha256 TEXT NOT NULL DEFAULT '', source_sheet TEXT NOT NULL, source_cell TEXT NOT NULL, source_column TEXT NOT NULL DEFAULT '',
    invoice_date TEXT, invoice_ref TEXT, qty_days REAL, amount_ht REAL, unit_rate REAL,
    basis TEXT NOT NULL CHECK(basis IN ('days','amount','amount_only')), qty_derived INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK(status IN ('proposed','validated','rejected')), note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, validated_at TEXT, validated_by TEXT,
    CHECK(qty_days IS NOT NULL OR amount_ht IS NOT NULL), CHECK(qty_days IS NULL OR qty_days>0), CHECK(amount_ht IS NULL OR amount_ht>=0),
    CHECK(status<>'validated' OR (validated_at IS NOT NULL AND validated_by IS NOT NULL AND validated_by<>'')),
    CHECK(status<>'rejected' OR note<>''),
    UNIQUE(source_file, source_sheet, source_cell));
  CREATE INDEX IF NOT EXISTS idx_historical_project ON historical_invoices(project_id,status);
  CREATE TRIGGER IF NOT EXISTS historical_invoices_no_delete BEFORE DELETE ON historical_invoices BEGIN SELECT RAISE(ABORT,'Historical invoices are never deleted (reject them instead)'); END;
  CREATE TRIGGER IF NOT EXISTS historical_invoices_source_values BEFORE UPDATE ON historical_invoices WHEN OLD.id IS NOT NEW.id OR OLD.project_id IS NOT NEW.project_id
    OR OLD.source_file IS NOT NEW.source_file OR OLD.source_sha256 IS NOT NEW.source_sha256 OR OLD.source_sheet IS NOT NEW.source_sheet OR OLD.source_cell IS NOT NEW.source_cell
    OR OLD.source_column IS NOT NEW.source_column OR OLD.invoice_date IS NOT NEW.invoice_date OR OLD.invoice_ref IS NOT NEW.invoice_ref OR OLD.qty_days IS NOT NEW.qty_days
    OR OLD.amount_ht IS NOT NEW.amount_ht OR OLD.unit_rate IS NOT NEW.unit_rate OR OLD.basis IS NOT NEW.basis OR OLD.qty_derived IS NOT NEW.qty_derived OR OLD.created_at IS NOT NEW.created_at
    BEGIN SELECT RAISE(ABORT,'A historical invoice keeps the values read from its source; only its status can change'); END;
  -- rc37 (P3): history of the numbers of draft invoices (append-only, like invoice_date_changes) ; a number printed on a historical invoice is never given to a draft or to an invoice
  -- (only DRAFT rows and the issuance are guarded here: restoring a backup rebuilds issued invoices as they were)
  CREATE TABLE IF NOT EXISTS invoice_number_changes(id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL, old_number TEXT, new_number TEXT,
    manual INTEGER NOT NULL DEFAULT 0, context TEXT NOT NULL, changed_at TEXT NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_number_changes_invoice ON invoice_number_changes(invoice_id);
  CREATE TRIGGER IF NOT EXISTS invoice_number_changes_no_update BEFORE UPDATE ON invoice_number_changes BEGIN SELECT RAISE(ABORT,'Invoice number history is append-only'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_number_changes_no_delete BEFORE DELETE ON invoice_number_changes BEGIN SELECT RAISE(ABORT,'Invoice number history is append-only'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_number_not_historical_ins BEFORE INSERT ON invoices WHEN NEW.number IS NOT NULL AND NEW.status='draft'
    AND EXISTS(SELECT 1 FROM historical_invoices WHERE upper(trim(invoice_ref))=upper(trim(NEW.number)))
    BEGIN SELECT RAISE(ABORT,'Invoice number already used by a historical invoice'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_number_not_historical_upd BEFORE UPDATE OF number,status ON invoices WHEN NEW.number IS NOT NULL AND OLD.status='draft'
    AND EXISTS(SELECT 1 FROM historical_invoices WHERE upper(trim(invoice_ref))=upper(trim(NEW.number)))
    BEGIN SELECT RAISE(ABORT,'Invoice number already used by a historical invoice'); END;
  CREATE TRIGGER IF NOT EXISTS invoice_issue_needs_number BEFORE UPDATE OF status ON invoices WHEN NEW.status='issued' AND OLD.status='draft' AND (NEW.number IS NULL OR trim(NEW.number)='')
    BEGIN SELECT RAISE(ABORT,'An issued invoice needs a number'); END;
  """)
  ensure_number_index(c)
  credit_lines.migrate(c)   # rc38: credit notes on manual lines (table, guards, operations cap)
 migrate_rc19(path)
 c=connect(path,autocommit=True)
 try:
  c.execute("BEGIN IMMEDIATE")
  frozen=invoice_service.freeze_legacy_issued(c)
  if frozen: c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("legacy_invoices_frozen",f"count={frozen}"))
  c.execute("COMMIT")
 except Exception:
  c.execute("ROLLBACK"); raise
 finally: c.close()
init()
def log(e,d):
 with db() as c:c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",(e,str(d)))
SESSION_MAX_HOURS=24  # absolute lifetime of a web session, whatever its sliding cookie lifetime
def session_valid():
 """The cookie only proves a past login: the session must also exist server-side (logout revokes it) and be younger than SESSION_MAX_HOURS."""
 sid=session.get("sid")
 if not session.get("auth") or not sid: return False
 try:
  with db() as c:
   r=c.execute("SELECT created_at FROM web_sessions WHERE sid=?",(sid,)).fetchone()
   if not r: return False
   if r["created_at"]<(rules.utc_now()-timedelta(hours=SESSION_MAX_HOURS)).isoformat(timespec="seconds"):
    c.execute("DELETE FROM web_sessions WHERE sid=?",(sid,)); return False
 except sqlite3.Error: return False
 return True
def login_required(fn):
 @wraps(fn)
 def inner(*a,**k):
  if not session_valid():
   session.clear()
   if request.method!="GET": flash("Session expirée : l'opération n'a pas été enregistrée. Se reconnecter puis recommencer.")
   return redirect(url_for("login",next=request.path if request.method=="GET" else "/"))
  return fn(*a,**k)
 return inner
# French number formatting on screen (rc4, R9): filters |nb |nbg |chf
fr_num,fr_g,fr_chf=rules.fr_num,rules.fr_g,rules.fr_chf
APP.jinja_env.filters.update(nb=fr_num,nbg=fr_g,chf=fr_chf,hm=rules.fr_hm)
from markupsafe import Markup, escape
def ts_html(v):
 """A3 + RC8: shown in Europe/Zurich (03.10.2026 à 15:13:26); the stored UTC value stays machine-readable in
 datetime (with its Z) and visible on hover (title « UTC … »)."""
 if not v: return ""
 raw=str(v).strip(); iso=raw.replace(" ","T")+("Z" if rules.to_zurich(raw) else "")
 return Markup(f'<time datetime="{escape(iso)}" title="UTC {escape(raw)}">{escape(rules.fr_ts(v))}</time>')
APP.jinja_env.filters.update(ts=ts_html,tstext=rules.fr_ts,d=rules.fr_date,periods=rules.fr_periods_in,localdate=rules.local_date)
# --- UX lot 1 (2026-10-20, owner decisions B-1 and B-2): DISPLAY ONLY. Nothing computed, checked, stored or written to the audit log changes:
# these filters only reformat on screen a value or a text that the application already produced.
_EN_NUM=re.compile(r"(?<![\w.,])(-?)(\d+)\.(\d+)(?![\w.]|,\d)")
def _swiss_token(m):
 frac=m[3]
 return ("−" if m[1] else "")+f"{int(m[2]):,}".replace(",",rules.NNBSP)+("" if frac=="0" else ","+frac)
def fr_detail(s):
 """B-1: the detail text of a check (« 13.0 × 1200.0 = 15600.00 CHF HT ») shown in the screen's number format (« 13 × 1 200 = 15 600,00 CHF HT »).
 Every digit is kept (no rounding); only a float's lone « .0 » is dropped. Quoted user text (« … ») and dates (31.08.2026) are left as they are.
 The detail itself is unchanged: the audit log of a derogation keeps the original text (decision B-1)."""
 if s is None: return ""
 return "".join(p if p.startswith("«") else _EN_NUM.sub(_swiss_token,p) for p in re.split(r"(«[^»]*»)",str(s)))
def fr_exact(v,max_places=6):
 """B-2: a quantity with the precision the PDF prints (pdf_layout.qty_label: 2 decimals at least, up to 6 when the stored value has them),
 in the screen format. Never rounded below what will be printed. max_places=4 gives the printed precision of a unit rate (pdf_layout.rate_money)."""
 if v is None or v=="": return ""
 d=Decimal(str(v)).quantize(Decimal(1).scaleb(-max_places),ROUND_HALF_UP).normalize()
 e=d.as_tuple().exponent
 return fr_num(d,max(2,-e) if e<0 else 2)
def fr_days2(v):
 """B-2: management figure in days, 2 decimals; the exact value (up to 6 decimals) in a tooltip when the 2 decimals hide digits."""
 if v is None or v=="": return ""
 short=fr_num(v); exact=fr_g(v)
 if Decimal(str(round(float(v),6)))==Decimal(str(v)).quantize(Decimal("0.01"),ROUND_HALF_UP): return short
 return Markup(f'<span class="exact" title="valeur exacte : {escape(exact)}">{escape(short)}</span>')
APP.jinja_env.filters.update(swiss=fr_detail,qtyp=fr_exact,nbt=fr_days2)
APP.jinja_env.globals["manual_lines_blocked"]=lambda:rules.MANUAL_LINES_ISSUANCE_BLOCKED   # rc38: read at each render (the owner's go-ahead flips the constant, tests patch it)
# --- UX lot 2 (2026-10-23, owner decision « tout le lot 2 », R-1 to R-7): DISPLAY ONLY, like lot 1. No billing, check, issuance, VAT, rounding or
# numbering rule changes; nothing below writes to the database.
DASH_CHECKS_MAX=5   # R-4: the dashboard runs the 14 existing checks of each draft only while there are at most this many drafts (else « à contrôler »)
def dashboard_todo(c,ins,cnotes,open_variances,settings_missing,backup_advice,today):
 """n° 1: the « À traiter » list, most urgent first (decision required, to do, advice). Each line links to the page where the action is taken;
 nothing is executed from the dashboard. Figures come from what the dashboard already reads, and, for at most DASH_CHECKS_MAX drafts, from
 invoice_checks.run_checks (read-only, the same checks as the issue page)."""
 names={x["id"]:x["project"] for x in ins}
 out=[dict(kind="variance",level="err",v=v,project=names.get(v["invoice_id"],""),first=n==0) for n,v in enumerate(open_variances)]
 for n_ in cnotes:
  if n_["balance"]>0 and n_["treatment"] in ("remboursement","compensation"):
   due=n_.get("due_on"); days=(date.fromisoformat(due)-today).days if due and re.fullmatch(r"\d{4}-\d{2}-\d{2}",str(due)) else None
   out.append(dict(kind="credit",level="err" if n_.get("overdue") else "todo",n=n_,due_in=days))
 drafts=sorted((x for x in ins if x["status"]=="draft"),key=lambda x:(x["period_to"],x["id"]))
 run=len(drafts)<=DASH_CHECKS_MAX
 for d in drafts:
  out.append(dict(kind="draft",level="todo",i=d,failed=[k["n"] for k in invoice_checks.failures(invoice_checks.run_checks(c,d["id"]))] if run else None))
 if settings_missing: out.append(dict(kind="settings",level="todo",missing=settings_missing))
 if backup_advice: out.append(dict(kind="backup",level="advice"))
 rank={"err":0,"todo":1,"advice":2}
 return sorted(out,key=lambda t:rank[t["level"]])   # stable: within a level, the order above
TABS=("dashboard","time","mandates","billing","archive","migration","settings")
def back(tab): return redirect(url_for("index",tab=tab))
def iso_date(v,label):
 try: return date.fromisoformat((v or "").strip()).isoformat()
 except ValueError: raise ValueError(f"{label} invalide (format AAAA-MM-JJ attendu)")
def contract(c,p,upto=None): return rules.contract(c,p,upto)
MAX_MONEY=1e9; MAX_DAYS=1e5
# F-C2-1 (2026-10-07): a number is written with ASCII digits, an optional sign and an optional decimal part. float()/Decimal() alone also take
# « 1_5 », « 1e1 », « inf » or digits of other scripts (« ٣ »), which no form of the application produces: a forged request only.
PLAIN_NUMBER=re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
def money_field(v,label):
 raw=str(v or "0").replace(",",".").strip() or "0"
 if not PLAIN_NUMBER.fullmatch(raw): raise ValueError(f"{label} invalide")
 try: d=Decimal(raw).quantize(Decimal("0.01"),ROUND_HALF_UP)
 except Exception: raise ValueError(f"{label} invalide")
 if abs(d)>Decimal(str(MAX_MONEY)): raise ValueError(f"{label} hors limites (1 000 000 000 au maximum)")
 return float(d)
def num_field(v,label,lo=0.0,hi=MAX_DAYS,lo_open=False,default=None):
 """Finite decimal number within [lo, hi] (lo excluded when lo_open): never NaN, infinity or an absurd magnitude, which would make every page of the application fail."""
 raw=str(v).strip().replace(",",".") if v is not None else ""
 if raw=="" and default is not None: return default
 if not PLAIN_NUMBER.fullmatch(raw): raise ValueError(f"{label} invalide")
 try: x=float(raw)
 except ValueError: raise ValueError(f"{label} invalide")
 if not math.isfinite(x) or x>hi or x<lo or (lo_open and x==lo): raise ValueError(f"{label} invalide ou hors limites")
 return x
@APP.errorhandler(OverflowError)
def too_big(e): return "Not found",404
@APP.errorhandler(413)
def payload_too_large(e):
 if request.path=="/login": return ("Requête de connexion trop volumineuse.",413)
 return ("Fichier trop volumineux pour cette opération (limite : 15 Mo ; la restauration d'une sauvegarde complète accepte davantage). Revenir à l'accueil.",413)
@APP.errorhandler(Exception)
def unexpected(e):
 """Never show an internal message (SQL, Python) to the browser; keep it in the service log."""
 if isinstance(e,HTTPException): return e
 APP.logger.exception("erreur interne")
 return ("Erreur interne : l'opération n'a pas abouti (le détail technique est dans le journal du service). Revenir à l'accueil et vérifier l'état avant de recommencer.",500)
@APP.before_request
def refuse_cross_site():
 # RC8: a state-changing request from another site is refused (SameSite=Lax already withholds the cookie)
 if security.cross_site(request): abort(403)
@APP.before_request
def csp_nonce_for_request(): g.csp_nonce=secrets.token_urlsafe(16)
@APP.context_processor
def inject_csp_nonce(): return {"csp_nonce":g.get("csp_nonce",""),"env_label":ENV_LABEL}  # rc14: environment tag on every page, detail pages included
KEPT_MAX_AGE_S=120
def keep_form():
 """QA-09 (rc12): a refused form keeps what was typed. One slot per web session (kept_forms, transient: never saved
 nor restored); the next page that contains the same form fills it back in (see _confirm.html). Hidden fields are never kept."""
 sid=session.get("sid")
 if not sid: return
 data={k:v[:5000] for k,v in request.form.items()}
 try:
  with db() as c:
   c.execute("INSERT OR REPLACE INTO kept_forms(sid,path,data_json,created_at) VALUES(?,?,?,?)",(sid,request.path,json.dumps(data),rules.utc_now_iso()))
   c.execute("DELETE FROM kept_forms WHERE created_at<?",((rules.utc_now()-timedelta(hours=1)).isoformat(timespec="seconds"),))
 except sqlite3.Error: pass
def refused(msg):
 keep_form(); flash(msg)
@APP.context_processor
def inject_kept_form():
 """Consumed once: by the page re-rendered by the refused POST itself, or by the GET that follows its redirect."""
 sid=session.get("sid")
 if not sid or g.get("kept_done"): return {"kept":None}
 g.kept_done=True
 try:
  with db() as c:
   r=c.execute("SELECT path,data_json,created_at FROM kept_forms WHERE sid=?",(sid,)).fetchone()
   if not r: return {"kept":None}
   fresh=r["created_at"]>=(rules.utc_now()-timedelta(seconds=KEPT_MAX_AGE_S)).isoformat(timespec="seconds")
   if not (fresh and (r["path"]==request.path or request.method=="GET")): return {"kept":None}
   c.execute("DELETE FROM kept_forms WHERE sid=?",(sid,))
   return {"kept":{"path":r["path"],"data":json.loads(r["data_json"])}}
 except (sqlite3.Error,ValueError): return {"kept":None}
@APP.after_request
def hardened(resp): return security.harden(resp,bool(session.get("auth")),request.is_secure,g.get("csp_nonce",""))
# A login form weighs well under 1 KB. Bodies announced larger are refused on their Content-Length, before any read: behind the proxy
# buffer (80-site-caddy.sh, request_buffers 64KB) a client sending a body drop by drop can then no longer hold one of the 16 server threads.
LOGIN_MAX_BODY=16*1024
@APP.route("/login",methods=["GET","POST"])
def login():
 if request.method=="POST":
  request.max_content_length=LOGIN_MAX_BODY
  ip=request.remote_addr or "?"
  with db() as c:
   if security.locked(c,ip):
    if not security.throttle_logged(c,ip): c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("login_throttled",f"ip={ip}"))  # one row per client and window
    flash(f"Trop de tentatives de connexion : réessayer dans {security.WINDOW_MIN} minutes.")
    return render_template("login.html",env_label=ENV_LABEL),429
   if security.credentials_ok(SEC,request.form.get("username",""),request.form.get("password","")):
    security.clear_failures(c,ip)
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("login_ok",f"ip={ip}"))
    nxt=request.args.get("next") or "/"
    # Only same-site paths: refuses absolute URLs and protocol-relative //host redirects.
    if not nxt.startswith("/") or nxt.startswith("//") or any(ord(ch)<32 or ch in "\\\x7f" for ch in nxt): nxt="/"
    sid=secrets.token_urlsafe(24); now_=rules.utc_now_iso()
    c.execute("DELETE FROM web_sessions WHERE created_at<?",((rules.utc_now()-timedelta(hours=2*SESSION_MAX_HOURS)).isoformat(timespec="seconds"),))
    c.execute("INSERT INTO web_sessions(sid,created_at,last_seen) VALUES(?,?,?)",(sid,now_,now_))
    session.clear(); session["auth"]=True; session["sid"]=sid; session.permanent=True  # fresh session (no fixation), bounded lifetime, revocable server-side
    return redirect(nxt)
   # neither the typed name nor the password is ever recorded
   security.record_failure(c,ip); c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("login_failed",f"ip={ip}"))
  flash("Identifiants incorrects.")
 return render_template("login.html",env_label=ENV_LABEL)
@APP.route("/logout",methods=["GET","POST"])
def logout():
 if request.method=="GET": return redirect("/")      # RC11: a cross-site link can no longer sign the owner out ; the button is a POST form
 sid=session.get("sid")
 if sid:
  with db() as c: c.execute("DELETE FROM web_sessions WHERE sid=?",(sid,))
 session.clear();return redirect("/login")
@APP.route("/imports/rollback/<batch_id>",methods=["POST"])
@login_required
def rollback_batch_route(batch_id):
 c=db(autocommit=True)
 try:
  deleted=rollback_import(c,batch_id)
  flash(f"Lot annulé : {deleted} entrée(s) retirée(s).")
 except Exception as e: flash(str(e) if str(e).startswith("Rollback refusé") else "Rollback refusé : "+str(e))
 finally: c.close()
 return back("migration")
@APP.route("/health")
def health():return jsonify(status="ok",version=VERSION)
@APP.route("/")
@login_required
def index():
 tab=request.args.get("tab") if request.args.get("tab") in TABS else "dashboard"
 with db() as c:
  ps=c.execute("SELECT p.*,COALESCE(SUM(e.hours),0) hours FROM projects p LEFT JOIN entries e ON e.project_id=p.id GROUP BY p.id ORDER BY COALESCE(p.start_date,'') DESC, p.id DESC").fetchall()
  positions={p["id"]:contract(c,p) for p in ps}
  es=annotate_entries(c,[dict(r) for r in c.execute(ENTRY_SQL+" ORDER BY e.work_date DESC,e.id DESC LIMIT 15")])
  by_inv={}; cnotes=[]
  for cn in c.execute("SELECT cn.*,i.number inv_number FROM credit_notes cn JOIN invoices i ON i.id=cn.invoice_id ORDER BY cn.id"):
   pos=credits.position(c,cn); row=dict(cn,**{k:v for k,v in pos.items() if k not in ("operations","status")},cn_status=pos["status"])
   by_inv.setdefault(cn["invoice_id"],[]).append(row)
   if cn["status"]=="issued": cnotes.append(row)
  ins=[]; vc=post_billing.variance_candidates(c); all_lines=rules.invoice_lines_by_id(c)
  for i in c.execute("SELECT i.*,p.name project FROM invoices i JOIN projects p ON p.id=i.project_id ORDER BY i.id DESC"):
   mlines=all_lines.get(i["id"],[]); a=rules.invoice_amounts(i,mlines); a=dict(a,ht=a["subtotal"]); off=credits.offsets_total_on(c,i["id"])   # rc37: the HT shown is the printed sub-total (service + manual lines)
   k=credits.creditable(c,i) if i["status"]=="issued" else None
   ins.append(dict(i,**a,manual_lines=mlines,credits=by_inv.get(i["id"],[]),offsets=off,net_due=a["ttc"]-off,k=k,date_hist=date_history(c,i["id"]),
                   total_block=credits.total_credit_blockers(c,i) if i["status"]=="issued" else "",
                   var=post_billing.invoice_variance(c,i) if i["id"] in vc else None))  # rc19: post-invoicing variance, never written
  batches=c.execute("SELECT id,source_filename,status,source_rows,inserted_rows,created_at,committed_at,rolled_back_at,error FROM import_batches ORDER BY created_at DESC LIMIT 30").fetchall()
  settings=rules.get_settings(c)
  last_backup=c.execute("SELECT MAX(created_at) FROM audit WHERE event='json_backup_exported'").fetchone()[0]
  has_docs=c.execute("SELECT COUNT(*) FROM invoices WHERE status='issued'").fetchone()[0]>0
  fc=forecast_mod.build(c,rules.local_today())
 # rc19: issued invoices whose billed entries changed after issuance and whose current variance has no decision recorded yet
 open_variances=[x["var"] for x in ins if x.get("var") and x["var"]["needs_decision"]]
 from app.pdf_layout import FONTS_USED
 missing=[label for k,(label,req,_) in rules.ISSUER_FIELDS.items() if req and not settings.get(k)]
 _today=rules.local_today()
 _mstart=_today.replace(day=1).isoformat()
 _mend=date(_today.year+(_today.month==12),_today.month%12+1,1).isoformat()
 with db() as _c: month_hours=_c.execute("SELECT COALESCE(SUM(hours),0) FROM entries WHERE work_date>=? AND work_date<?",(_mstart,_mend)).fetchone()[0]
 month_label=_today.strftime("%m.%Y")
 # UX lot 1 (n° 5, B-3 ; n° 6) — display only: what the entry and billing forms propose, never a stored value.
 saved=session.pop("entry_saved",None) if session.get("entry_saved") else None
 active_ids={p["id"]:p["name"] for p in ps if p["active"]}
 entry_pid=saved.get("pid") if isinstance(saved,dict) and saved.get("pid") in active_ids else None
 if entry_pid is None:
  with db() as _c:
   r=_c.execute("SELECT e.project_id FROM entries e JOIN projects p ON p.id=e.project_id WHERE p.active=1 ORDER BY e.created_at DESC,e.id DESC LIMIT 1").fetchone()
  entry_pid=r[0] if r and r[0] in active_ids else None
 entry_date=saved.get("date") if isinstance(saved,dict) and re.fullmatch(r"\d{4}-\d{2}-\d{2}",str(saved.get("date") or "")) else _today.isoformat()
 backup_stale=(not last_backup) or last_backup<(rules.utc_now()-timedelta(days=30)).isoformat(timespec="seconds")
 with db() as _c: todo=dashboard_todo(_c,ins,cnotes,open_variances,missing,has_docs and backup_stale,_today)
 with db() as _c: cal_resume=cal.resume_tableau_de_bord(_c,_today,settings)   # candidat rc36 : encart « Calendrier et alertes », lecture seule
 draft_done=None; did=session.pop("draft_created",None) if session.get("draft_created") else None
 if isinstance(did,int):
  with db() as _c: d=_c.execute("SELECT i.id,i.period_from,i.period_to,i.qty,i.unit,i.invoice_date,p.name project FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id=? AND i.status='draft'",(did,)).fetchone()
  if d: draft_done=dict(d,after_date=d["period_to"]>(d["invoice_date"] or _today.isoformat()))
 return render_template("index.html",month_hours=month_hours,month_label=month_label,cnotes=cnotes,projects=ps,active=[p for p in ps if p["active"]],closed=[p for p in ps if not p["active"]],positions=positions,recent=es,invoices=ins,
  fc=fc,batches=batches,tab=tab,settings=settings,fields=rules.ISSUER_FIELDS,settings_missing=missing,treatments=rules.TREATMENTS,options=rules.OPTION_FIELDS,other_vat_modes=rules.OTHER_VAT_MODES,fonts_used=FONTS_USED,version=VERSION,env_label=ENV_LABEL,no_mandate=not ps,current_year=rules.local_today().year,
  last_backup=last_backup,backup_stale=backup_stale,has_docs=has_docs,todo=todo,
  cal_resume=cal_resume,cal_cfg=cal.reglages(settings),cal_reglages=cal.REGLAGES,cal_tva=cal.TVA_PERIODICITES,retour="settings",
  open_variances=open_variances,entry_date=entry_date,entry_pid=entry_pid,entry_pname=active_ids.get(entry_pid,""),entry_saved=bool(saved and entry_pid==saved.get("pid")),
  focus_entry=bool(saved) or request.args.get("focus")=="start",draft_done=draft_done,today_iso=_today.isoformat(),yesterday_iso=(_today-timedelta(days=1)).isoformat())

# --- calendrier (candidat rc36) : lecture seule des données existantes ; seules écritures : réglages cal_* et jeton d'abonnement (table settings, aucune migration) ----
CAL_TOKEN_KEY="cal_ics_token_sha256"
CAL_TOKEN_RE=re.compile(r"^[A-Za-z0-9_-]{43}$")
def cal_page(nouveau_lien=None):
 today=rules.local_today(); y,mo=cal.mois_valide(request.args.get("mois"),today)
 premier=date(y,mo,1); suivant=cal.ajouter_mois(premier,1); precedent=cal.ajouter_mois(premier,-1)
 with db() as c:
  settings=rules.get_settings(c); cfg=cal.reglages(settings)
  try:
   donnees=cal.charger(); erreur=""
   mois_ev=cal.agenda(c,donnees,cfg,premier,suivant-timedelta(days=1))
   prochains=cal.agenda(c,donnees,cfg,today,today+timedelta(days=30))
   revoir=cal.a_revoir(donnees,today)
  except cal.CalendarDataError as e: erreur=str(e); mois_ev=prochains=[]; revoir=[]
  alertes=cal.alertes(c,today,cfg)
 vus=set()
 for e in mois_ev:   # un seul repère d'ancre (#j-AAAA-MM-JJ) par jour, sur le premier événement qui n'est pas une vacance : cible des liens de la grille
  if e["genre"]!="vacances" and e["date"] not in vus: e["ancre"]=True; vus.add(e["date"])
 return render_template("calendrier.html",version=VERSION,env_label=ENV_LABEL,erreur=erreur,alertes=alertes,prochains=prochains,mois_ev=mois_ev,a_revoir=revoir,
  semaines=cal.grille_mois(y,mo,mois_ev,today),annee=y,mois=mo,mois_nom=("janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre")[mo-1],
  precedent=precedent.strftime("%Y-%m"),suivant=suivant.strftime("%Y-%m"),courant=today.strftime("%Y-%m"),today=today,debut_mois=premier,cal_cfg=cfg,cal_reglages=cal.REGLAGES,cal_tva=cal.TVA_PERIODICITES,
  retour="calendrier",jeton_actif=bool(settings.get(CAL_TOKEN_KEY)),nouveau_lien=nouveau_lien,genres=cal.GENRES,statuts=cal.STATUTS,active_tab="calendrier")
@APP.route("/calendrier")
@login_required
def calendrier(): return cal_page()
@APP.route("/calendrier.ics")
@login_required
def calendrier_ics():
 """Agenda complet (échéances, fériés, vacances, jalons des mandats) : derrière la connexion existante, jamais public."""
 today=rules.local_today()
 with db() as c:
  cfg=cal.reglages(rules.get_settings(c))
  try: ev=cal.agenda(c,cal.charger(),cfg,today-timedelta(days=90),today+timedelta(days=730))
  except cal.CalendarDataError as e: return _texte_erreur("Calendrier indisponible : "+str(e),500)
 r=make_response(cal.ics(ev,rules.utc_now().replace(tzinfo=timezone.utc)))
 r.headers["Content-Type"]="text/calendar; charset=utf-8"; r.headers["Content-Disposition"]='attachment; filename="time-billing-calendrier.ics"'
 return r
def _texte_erreur(msg,code):
 r=make_response(msg,code); r.headers["Content-Type"]="text/plain; charset=utf-8"; return r
@APP.route("/calendrier/abonnement/<token>.ics")
def calendrier_abonnement(token):
 """Flux d'abonnement par jeton secret révocable (pas de session). Il ne contient AUCUNE donnée client ni de mandat : échéances, fériés, vacances seulement.
 Seule l'empreinte SHA-256 du jeton est conservée ; mauvais ou révoqué = 404 (rien ne dit lequel)."""
 with db() as c:
  row=c.execute("SELECT value FROM settings WHERE key=?",(CAL_TOKEN_KEY,)).fetchone()
  cfg=cal.reglages(rules.get_settings(c))
 if not (CAL_TOKEN_RE.fullmatch(token) and row and row[0] and secrets.compare_digest(cal.jeton_empreinte(token),row[0])): abort(404)
 today=rules.local_today()
 try: ev=cal.agenda(None,cal.charger(),cfg,today-timedelta(days=90),today+timedelta(days=730),mandats=False)
 except cal.CalendarDataError: abort(503)
 r=make_response(cal.ics(ev,rules.utc_now().replace(tzinfo=timezone.utc),"Time Billing — échéances et jours fériés"))
 r.headers["Content-Type"]="text/calendar; charset=utf-8"; r.headers["Cache-Control"]="no-store"; r.headers["X-Robots-Tag"]="noindex"
 return r
@APP.route("/calendrier/abonnement",methods=["POST"])
@login_required
def calendrier_abonnement_creer():
 token=secrets.token_urlsafe(32)
 with db() as c:
  c.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(CAL_TOKEN_KEY,cal.jeton_empreinte(token)))
  c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("calendar_feed_token_created","jeton d'abonnement (seule l'empreinte est conservée)"))
 return cal_page(nouveau_lien=url_for("calendrier_abonnement",token=token,_external=True))
@APP.route("/calendrier/abonnement/revoquer",methods=["POST"])
@login_required
def calendrier_abonnement_revoquer():
 with db() as c:
  if c.execute("DELETE FROM settings WHERE key=?",(CAL_TOKEN_KEY,)).rowcount: c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("calendar_feed_token_revoked","jeton d'abonnement révoqué"))
 flash("Lien d'abonnement révoqué : il ne donne plus accès à rien.")
 return redirect(url_for("calendrier"))
@APP.route("/calendrier/reglages",methods=["POST"])
@login_required
def calendrier_reglages():
 retour=request.form.get("retour")
 try:
  vals=cal.valider_reglages(request.form)
  with db() as c:
   changed=[]
   for k,v in vals.items():
    r=c.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone()
    if (r[0] if r else cal.REGLAGES[k][1])!=v:
     c.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(k,v)); changed.append(k)
   if changed: c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("settings_updated","calendrier : "+", ".join(changed)))
  flash("Réglages du calendrier enregistrés." if changed else "Réglages du calendrier inchangés.")
 except ValueError as e: refused("Réglages du calendrier non enregistrés : "+str(e))
 return back("settings") if retour=="settings" else redirect(url_for("calendrier"))

# --- mandates -----------------------------------------------------------------------------------
def form_text(v):
 r"""Stripped text of a form field, line breaks stored as \n: a browser sends the line breaks of a textarea as \r\n (HTML rule), so
 saving an unchanged mandate or issuer address rewrote the stored value (seen by 90-rollback and the G4 promotion as a modified row)."""
 return re.sub(r"\r\n?","\n",v or "").strip()
PROJECT_TEXT=("short_name","client","po","project_number","billing_contact","billing_address","dates_label","client_legal_name","client_legal_id")
def project_values(form):
 name=(form.get("name") or "").strip()
 if not name: raise ValueError("nom du projet obligatoire")
 start=form.get("start_date","").strip()
 if start: iso_date(start,"date de début")
 try: months=int(str(form.get("duration_months") or "12").strip())
 except ValueError: raise ValueError("durée prévisionnelle invalide (nombre entier de mois)")
 v={"name":name,"rate":num_field(form.get("rate"),"tarif journalier",0.0,1e6,default=0.0),"day_hours":num_field(form.get("day_hours"),"heures par jour",0.0,24.0,lo_open=True,default=8.0),
    "vat":num_field(form.get("vat"),"TVA",0.0,100.0,default=0.0),"ordered_days":num_field(form.get("ordered_days"),"jours commandés",0.0,1e5,default=0.0),
    "start_date":start,"duration_months":months}
 if months<1: raise ValueError("durée prévisionnelle invalide : au moins 1 mois")
 if len(name)>200: raise ValueError("nom du projet trop long (200 caractères au maximum)")
 if not all(math.isfinite(v[k]) for k in ("rate","day_hours","vat","ordered_days")): raise ValueError("valeurs numériques invalides")
 if v["rate"]<0 or v["ordered_days"]<0 or v["vat"]<0 or v["day_hours"]<=0: raise ValueError("valeurs numériques invalides")
 if not (v["rate"]<=1e6 and v["ordered_days"]<=1e5 and v["vat"]<=100 and v["day_hours"]<=24 and v["duration_months"]<=600): raise ValueError("valeurs numériques hors limites (tarif ≤ 1 000 000, jours ≤ 100 000, TVA ≤ 100 %, heures par jour ≤ 24, durée ≤ 600 mois)")
 v.update({k:form_text(form.get(k)) for k in PROJECT_TEXT})
 return v
@APP.route("/project",methods=["POST"])
@login_required
def project():
 try:
  v=project_values(request.form)
  with db() as c:c.execute(f"INSERT INTO projects({','.join(v)}) VALUES({','.join('?'*len(v))})",tuple(v.values()))
  log("project_created",v["name"]);flash("Projet enregistré.")
 except sqlite3.IntegrityError: refused("Projet non enregistré : un mandat porte déjà ce nom.")
 except Exception as e:refused("Projet non enregistré : "+str(e))
 return back("mandates")
@APP.route("/project/<int:pid>/edit",methods=["GET","POST"])
@login_required
def project_edit(pid):
 with db() as c:
  p=c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
  if not p: abort(404)
  if request.method=="POST":
   try:
    v=project_values(request.form)
    if abs(float(v["day_hours"])-float(p["day_hours"] or 8))>1e-9 and c.execute("SELECT 1 FROM invoices WHERE project_id=? AND status='issued' LIMIT 1",(pid,)).fetchone():
     raise ValueError("les heures par jour ne peuvent plus changer : des factures sont émises (leurs jours réalisés seraient réécrits). Si nécessaire, clôturer ce mandat et en ouvrir un nouveau.")
    if (v["client_legal_name"],v["client_legal_id"])!=(p["client_legal_name"] or "",p["client_legal_id"] or "") and c.execute(
      "SELECT 1 FROM credit_operations o JOIN invoices i ON i.id=o.target_invoice_id WHERE i.project_id=? AND i.status='draft' AND o.kind='offset' "
      "AND NOT EXISTS(SELECT 1 FROM credit_operations r WHERE r.reverses_id=o.id) LIMIT 1",(pid,)).fetchone():
     raise ValueError("l'identité juridique du client ne peut pas changer : un brouillon de ce mandat reçoit une imputation de note de crédit réservée (règle « même client juridique »). Annuler d'abord l'imputation ou émettre le brouillon.")
    c.execute(f"UPDATE projects SET {','.join(k+'=?' for k in v)} WHERE id=?",(*v.values(),pid))
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("project_updated",f"id={pid}"))
    flash("Mandat mis à jour. Les factures déjà émises conservent les données figées à leur émission.")
    return back("mandates")
   except Exception as e: refused("Mandat non modifié : "+str(e))
 return render_template("project_edit.html",p=p,legal_display=rules.legal_display(p["client_legal_id"]))
def address_groups(c):
 """P2: the clients as the application knows them (the legal identity of their mandates, no clients table) with their reusable billing addresses and how many invoices copied each."""
 groups={}
 for p in c.execute("SELECT id,name,client,client_legal_name,client_legal_id FROM projects ORDER BY name"):
  k=addresses.client_key(p)
  if not k: continue
  g=groups.setdefault(k,{"key":k,"client":p["client"] or p["client_legal_name"] or k,"legal":p["client_legal_name"] or "","mandates":[],"addresses":[]}); g["mandates"].append(p["name"])
 for a in c.execute("SELECT a.*,(SELECT COUNT(*) FROM invoices i WHERE i.billing_address_id=a.id) used FROM billing_addresses a ORDER BY a.client_key,a.sort_order,a.label,a.id"):
  g=groups.setdefault(a["client_key"],{"key":a["client_key"],"client":"Tous les mandats" if a["client_key"]==addresses.GLOBAL_KEY else "(aucun mandat actuel)","legal":"","mandates":[],"addresses":[]}); g["addresses"].append(dict(a))
 return sorted(groups.values(),key=lambda g:(g["client"] or "").casefold())
@APP.route("/adresses")
@login_required
def addresses_page():
 with db() as c: groups=address_groups(c)
 return render_template("adresses.html",groups=groups,active_tab="mandates",max_lines=addresses.MAX_LINES)
@APP.route("/adresses/ajouter",methods=["POST"])
@login_required
def address_add():
 try:
  with db() as c:
   key=request.form.get("client_key","")
   if key not in {g["key"] for g in address_groups(c)}: raise ValueError("client inconnu")
   label,contact,address=addresses.validate(request.form.get("label"),request.form.get("contact"),request.form.get("address"))
   nxt=c.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM billing_addresses WHERE client_key=?",(key,)).fetchone()[0]
   try: c.execute("INSERT INTO billing_addresses(client_key,label,contact,address,active,sort_order,created_at) VALUES(?,?,?,?,1,?,?)",(key,label,contact,address,nxt,rules.utc_now_iso()))
   except sqlite3.IntegrityError: raise ValueError(f"une adresse « {label} » existe déjà pour ce client")
   c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("billing_address_added",f"client_key={key};label={label}"))
  flash(f"Adresse « {label} » ajoutée.")
 except Exception as e: flash("Adresse non ajoutée : "+str(e))
 return redirect(url_for("addresses_page"))
@APP.route("/adresses/<int:aid>",methods=["POST"])
@login_required
def address_update(aid):
 """Edit the text / label, or (de)activate. The invoices that copied it keep their copy (their own « Actualiser » re-copies it); an address is never deleted."""
 try:
  with db() as c:
   a=addresses.get(c,aid)
   if not a: abort(404)
   if request.form.get("act") in ("activer","desactiver"):
    c.execute("UPDATE billing_addresses SET active=?,updated_at=? WHERE id=?",(1 if request.form["act"]=="activer" else 0,rules.utc_now_iso(),aid))
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("billing_address_"+request.form["act"],f"id={aid};label={a['label']}")); flash(f"Adresse « {a['label']} » {'réactivée' if request.form['act']=='activer' else 'désactivée'}.")
   else:
    label,contact,address=addresses.validate(request.form.get("label"),request.form.get("contact"),request.form.get("address"))
    try: c.execute("UPDATE billing_addresses SET label=?,contact=?,address=?,updated_at=? WHERE id=?",(label,contact,address,rules.utc_now_iso(),aid))
    except sqlite3.IntegrityError: raise ValueError(f"une adresse « {label} » existe déjà pour ce client")
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("billing_address_updated",f"id={aid};label={label}")); flash(f"Adresse « {label} » enregistrée. Les brouillons qui l'ont déjà choisie gardent leur copie jusqu'à « Actualiser ».")
 except HTTPException: raise
 except Exception as e: flash("Adresse non modifiée : "+str(e))
 return redirect(url_for("addresses_page"))
@APP.route("/project/<int:pid>/close",methods=["POST"])
@login_required
def project_close(pid):
 try:
  reason=(request.form.get("reason") or "").strip()
  if not reason: raise ValueError("motif de clôture obligatoire")
  with db() as c:
   p=c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
   if not p or not p["active"]: raise ValueError("mandat introuvable ou déjà clôturé")
   drafts=c.execute("SELECT COUNT(*) FROM invoices WHERE project_id=? AND status='draft'",(pid,)).fetchone()[0]
   cdrafts=c.execute("SELECT COUNT(*) FROM credit_notes cn JOIN invoices i ON i.id=cn.invoice_id WHERE i.project_id=? AND cn.status='draft'",(pid,)).fetchone()[0]
   if drafts or cdrafts: raise ValueError(f"{drafts} brouillon(s) de facture et {cdrafts} brouillon(s) de note de crédit à émettre ou supprimer avant clôture")
   pos=contract(c,p)
   c.execute("UPDATE projects SET active=0,closed_at=?,closed_reason=? WHERE id=?",(rules.utc_now_iso(),reason,pid))
   c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("project_closed",f"id={pid};reason={reason};unbilled_days={pos['unbilled_days']};po_balance_days={pos['po_balance_days']}"))
  flash(f"Mandat clôturé. Historique conservé. Position à la clôture : {fr_g(pos['unbilled_days'])} j réalisés non facturés, solde PO {fr_g(pos['po_balance_days'])} j.")
 except Exception as e: flash("Clôture refusée : "+str(e))
 return back("mandates")
@APP.route("/project/<int:pid>/reopen",methods=["POST"])
@login_required
def project_reopen(pid):
 with db() as c:
  n=c.execute("UPDATE projects SET active=1,closed_at=NULL,closed_reason='' WHERE id=? AND active=0",(pid,)).rowcount
  if n: c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("project_reopened",f"id={pid}"))
 flash("Mandat rouvert." if n else "Mandat non clôturé.")
 return back("mandates")
def active_project(c,pid):
 p=c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
 if not p: raise ValueError("projet inconnu")
 if not p["active"]: raise ValueError(f"le mandat « {p['name']} » est clôturé")
 return p

# --- time entries -------------------------------------------------------------------------------
CLOCK_RE=re.compile(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])(:[0-5][0-9])?$")   # stored clock time, seconds possible in an imported entry
TIME_RE=re.compile(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$")   # ASCII digits only (\d takes « ٥ »): what a time field sends
MAX_DESC=1000
def clock_minutes(start,end):
 """Duration in minutes of a clock-mode entry, or None when end == start (refused). An end BEFORE the start means the entry runs past
 midnight (22:00 -> 02:00 = 240 min): ONE entry, kept on its start day, never split. Wall-clock arithmetic, like every other entry."""
 s=int(start[:2])*60+int(start[3:5]); e=int(end[:2])*60+int(end[3:5])
 if e==s: return None
 return e-s if e>s else e+1440-s
def crosses_midnight(start,end): return bool(start and end and end<start)
def entry_span(work_date,start,end):
 """Absolute (begin,end) in minutes of a clock entry, for overlap checks across days; None when it has no clock times, or when end = start
 (refused by the form, possible in an imported entry: no span, it overlaps nothing)."""
 if not (start and end) or clock_minutes(start,end) is None: return None
 d=date.fromisoformat(work_date).toordinal()*1440; s=int(start[:2])*60+int(start[3:5])
 return d+s,d+s+clock_minutes(start,end)
def dst_note(work_date,start,end):
 """Wall-clock vs real elapsed time for a night entry spanning a Europe/Zurich clock change; None when both agree."""
 try:
  d0=date.fromisoformat(work_date); d1=d0+timedelta(days=1)
  a=datetime(d0.year,d0.month,d0.day,int(start[:2]),int(start[3:5]),tzinfo=rules.ZURICH)
  b=datetime(d1.year,d1.month,d1.day,int(end[:2]),int(end[3:5]),tzinfo=rules.ZURICH)
  real=(b.astimezone(timezone.utc)-a.astimezone(timezone.utc)).total_seconds()/60
 except (ValueError,TypeError,OverflowError): return None   # 31.12.9999 has no next day
 wall=clock_minutes(start,end)
 return None if abs(real-wall)<1 else (wall,real)
def parse_entry_form(form,keep=None):
 """Validated (work_date,start,end,hours) of a time-entry form. Either start AND end (clock mode), or a duration
 (duration mode): never both required. Nothing is guessed or corrected: a bad value is refused with its reason.
 keep = the stored entry being corrected: a value the user did not change is kept as stored and never re-validated, so an imported
 entry the form would refuse today (> 24 h, < 0,01 h, times with seconds, start = end, lone start or end, long or multi-line
 description: import warnings only) stays correctable (REVUE-CODE-RC19 « verrou partiel », condition G4). New values: same rules."""
 mode=form.get("entry_mode","clock")
 work_date=iso_date(form.get("work_date"),"date de prestation")
 start=(form.get("start_time") or "").strip(); end=(form.get("end_time") or "").strip()
 kept=False
 if mode=="clock" and keep is not None and start and end and (start,end)==(keep["start_time"],keep["end_time"]):
  h=keep["hours"]; kept=True   # unchanged clock times: the stored (declared) hours, as entry_edit already keeps them
 elif mode=="clock":
  if not start or not end: raise ValueError("renseigner l'heure de début et l'heure de fin")
  # a time field showing seconds (step="1", imported « 07:05:30 ») sends « 10:00:00 »: whole minutes are read, other seconds refused
  start,end=(re.sub(r"^([0-9]{1,2}:[0-9]{2}):00$",r"\1",x) for x in (start,end))
  for x in (start,end):
   if re.fullmatch(r"[0-9]{1,2}:[0-9]{2}:[0-9]{2}",x): raise ValueError(f"heure {x} avec secondes : indiquer l'heure à la minute (HH:MM), début et fin")
  ms,me=TIME_RE.match(start),TIME_RE.match(end)
  if not ms or not me: raise ValueError("heure invalide (format HH:MM attendu)")
  start,end=f"{int(ms.group(1)):02d}:{ms.group(2)}",f"{int(me.group(1)):02d}:{me.group(2)}"   # « 7:05 » is stored as 07:05 (same time, the format every calculation reads)
  minutes=clock_minutes(start,end)
  if minutes is None: raise ValueError("l'heure de fin ne peut pas être identique à l'heure de début (une prestation passant minuit s'écrit par exemple 22:00 → 02:00 : la fin est alors antérieure au début)")
  h=minutes/60
 elif mode=="duration":
  raw=(form.get("manual_hours") or "").strip().replace(",",".")
  if not raw: raise ValueError("renseigner la durée travaillée")
  if not re.fullmatch(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)",raw): raise ValueError("durée invalide (nombre d'heures attendu, ex. 4,25 pour 4 h 15)")   # no « 1_5 », « 1e1 », non-ASCII digits ; a sign is read, « -1 » is then refused as not positive
  try: h=float(raw)
  except ValueError: raise ValueError("durée invalide (nombre d'heures attendu, ex. 4,25 pour 4 h 15)")
  if not math.isfinite(h): raise ValueError("durée invalide (nombre d'heures attendu, ex. 4,25 pour 4 h 15)")
  start=""; end=""
  if keep is not None and h==keep["hours"]:
   kept=True
   # a lone imported start or end time is not shown by the duration form (hint on the page): kept while the duration is unchanged
   if bool(keep["start_time"])!=bool(keep["end_time"]): start,end=keep["start_time"],keep["end_time"]
 else: raise ValueError("mode de saisie inconnu")
 if not kept:
  if h<=0: raise ValueError("durée doit être positive")
  if h<0.01: raise ValueError("durée inférieure à 0,01 h (36 secondes) refusée")
  if h>24: raise ValueError("durée supérieure à 24 h pour une seule prestation")
 desc=form.get("description","")
 # the one-line description field drops line breaks when it sends a stored multi-line description: unchanged otherwise, kept as stored
 if keep is not None and desc!=keep["description"] and desc==re.sub(r"[\r\n]","",keep["description"] or ""): desc=keep["description"]
 if len(desc)>MAX_DESC and not (keep is not None and desc==keep["description"]): raise ValueError(f"description trop longue ({len(desc)} caractères ; {MAX_DESC} au maximum)")
 return work_date,start,end,h,desc
def _add_months(d,n):
 import calendar
 y,m=divmod(d.month-1+n,12); y+=d.year; m+=1
 return date(y,m,min(d.day,calendar.monthrange(y,m)[1]))
def entry_coherence_warnings(c,p,work_date,start,end,eid):
 """Non-blocking warnings after a time entry is saved (same checks as the historical import: overlap, long day, suspect date). The entry is kept."""
 w=[]
 if start and end and clock_minutes(start,end) is not None:   # imported start = end (to the minute): no span, nothing to warn about
  if crosses_midnight(start,end):
   w.append(f"Saisie passant minuit : {start} → {end} (le lendemain), soit {fr_g(clock_minutes(start,end)/60)} h, enregistrée en une seule saisie rattachée au {rules.fr_date(work_date)} (jour de début).")
   n=dst_note(work_date,start,end)
   if n: w.append(f"Attention : nuit de changement d'heure — durée calculée sur l'horloge {fr_g(n[0]/60)} h, durée réellement écoulée {fr_g(n[1]/60)} h. Corriger en mode « durée » si la durée réelle doit être facturée.")
  mine=entry_span(work_date,start,end); day=date.fromisoformat(work_date).toordinal()
  near=[date.fromordinal(min(max(day+k,1),date.max.toordinal())).isoformat() for k in (-1,1)]   # bounded: 01.01.0001 and 31.12.9999 are valid dates
  others=c.execute("SELECT e.id,e.work_date,e.start_time,e.end_time,pr.name FROM entries e JOIN projects pr ON pr.id=e.project_id WHERE e.work_date BETWEEN ? AND ? AND e.id<>? AND e.start_time<>'' AND e.end_time<>''",(*near,eid)).fetchall()
  for o in others:
   sp=entry_span(o["work_date"],o["start_time"],o["end_time"])
   if sp and mine and sp[0]<mine[1] and mine[0]<sp[1]:
    od=f"{rules.fr_date(o['work_date'])} " if o["work_date"]!=work_date else ""
    w.append(f"Attention : cette plage ({start}–{end}) chevauche une autre saisie ({od}{o['start_time']}–{o['end_time']}, {o['name']}). Vérifier qu'il ne s'agit pas d'un doublon (liste des saisies).")
    break
 total=c.execute("SELECT COALESCE(SUM(hours),0) FROM entries WHERE work_date=?",(work_date,)).fetchone()[0]
 if total>12: w.append(f"Attention : {fr_g(total)} h enregistrées pour le {rules.fr_date(work_date)} (plus de 12 h).")
 if work_date>rules.local_today().isoformat(): w.append("Attention : date dans le futur.")
 if p["start_date"]:
  try:
   s0=date.fromisoformat(p["start_date"]); s1=_add_months(s0,int(p["duration_months"] or 12))
   if work_date<s0.isoformat() or work_date>s1.isoformat(): w.append(f"Attention : date hors de la période prévue du mandat ({rules.fr_date(s0.isoformat())} → {rules.fr_date(s1.isoformat())}).")
  except ValueError: pass
 return w
@APP.route("/entry",methods=["POST"])
@login_required
def entry():
 try:
  work_date,start,end,h,desc=parse_entry_form(request.form)
  mode=request.form.get("entry_mode","clock")
  with db() as c:
   p=active_project(c,int(request.form.get("project_id") or 0))
   cur=c.execute(f"INSERT INTO entries(id,work_date,project_id,start_time,end_time,hours,description) VALUES({post_billing.NEXT_ENTRY_ID},?,?,?,?,?,?)",(work_date,p["id"],start,end,h,desc))
   last=contract(c,p)["last_issued_to"]
   for w in entry_coherence_warnings(c,p,work_date,start,end,cur.lastrowid): flash(w)
   draft_warning(c,p["id"],work_date)
  log("time_entry_created",f"{work_date} / {h}h / {mode}");flash(f"Temps enregistré : {fr_g(h)} h.")
  session["entry_saved"]={"pid":p["id"],"date":work_date}   # UX lot 1 (B-3, n° 5): the next entry form keeps this date and this mandate, shown with an indicator
  if last and work_date<=last:
   flash(f"Attention : période déjà facturée (facture émise jusqu'au {rules.fr_date(last)}). Cette prestation n'apparaît pas dans la facture émise et doit être traitée comme un reliquat sur une prochaine facture.")
 except Exception as e:refused("Saisie refusée : "+str(e))
 return back("time")

# --- time entries: list, correction, deletion (rc10) -----------------------------------------------
ENTRY_SQL="""SELECT e.*,p.name project,p.active project_active,p.day_hours FROM entries e JOIN projects p ON p.id=e.project_id"""
def entry_rev(e):
 """QA-25 (rc12): version token of a time entry, carried by its correction form: a second tab that saved first changes it."""
 return hashlib.sha256(json.dumps([e["work_date"],e["project_id"],e["start_time"],e["end_time"],e["hours"],e["description"]]).encode()).hexdigest()[:16]
def annotate_entries(c,rows):
 """rc19: no entry is locked any more (old, imported, closed mandate or invoiced). For display only: the issued invoice that billed
 the entry (the first issued invoice that billed it: post_billing.owners, decision billing-facturee-par-date = A), whether the entry
 changed since, and an invoice whose cumulative annex merely lists it."""
 info=post_billing.entries_invoices(c,[r["id"] for r in rows])
 for r in rows:
  invs=info.get(r["id"],[]); billed=[x for x in invs if x["role"]=="billed"]
  r["billed_by"]=", ".join(x["number"] for x in billed) or None
  r["billed_changed"]=any(post_billing.changed_since(x,r) for x in billed)
  r["annex_of"]=next((x["number"] for x in invs if x["role"]=="annex"),None)
 return rows
def entry_json(e):
 return json.dumps({"id":e["id"],"work_date":e["work_date"],"project_id":e["project_id"],"project":e["project"],"start_time":e["start_time"],"end_time":e["end_time"],
                    "hours":e["hours"],"description":e["description"],"source":e["source"],"created_at":e["created_at"],
                    "import_batch_id":e["import_batch_id"],"source_ref":e["source_ref"]},ensure_ascii=False)
MAX_REASON=500
_BIDI={0x200E,0x200F,0x061C}|set(range(0x202A,0x202F))|set(range(0x2066,0x206A))
_DROPPED=dict.fromkeys((0xAD,0x200B,0x2060,0xFEFF))       # soft hyphen, zero-width space, word joiner, BOM: pasted from Word or the web, they print nothing
_JOINERS={0x200C,0x200D}|set(range(0xE0020,0xE0080))     # (non-)joiners and tags: part of an emoji or of a script's visible glyph
_BLANK={0x115F,0x1160,0x3164,0xFFA0,0x2800}               # letters / symbols that print as nothing
def change_reason(v):
 """Free-text reason of a correction or deletion (rc19): kept as typed (trimmed), bounded, never interpreted. Control characters
 (line breaks included), bidirectional overrides and the other invisible characters are refused: they could make the history read differently
 from what it stores. G4 (2026-10-06): the invisible characters pasted from a word processor are removed instead, the refused one is named."""
 v=(v or "").translate(_DROPPED).strip()
 if len(v)>MAX_REASON: raise ValueError(f"motif trop long ({len(v)} caractères ; {MAX_REASON} au maximum)")
 bad=next(((i,ch) for i,ch in enumerate(v,1) if ord(ch)<32 or 0x7f<=ord(ch)<0xa0 or ord(ch) in _BIDI or ord(ch) in _BLANK
           or (unicodedata.category(ch) in ("Zl","Zp","Cf") and ord(ch) not in _JOINERS)),None)
 if bad: raise ValueError(f"motif : caractères de contrôle, invisibles ou d'inversion du sens d'écriture refusés (une seule ligne de texte) : U+{ord(bad[1]):04X} en position {bad[0]}")
 return v
def target_project(c,pid,current_pid,allow_closed):
 """Mandate of an existing entry after a correction (rc19). Its own mandate, even closed: old entries stay editable. Another active
 mandate. Another CLOSED mandate only with the explicit confirmation: a closed mandate takes no new time by default."""
 p=c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
 if not p: raise ValueError("projet inconnu")
 if not p["active"] and p["id"]!=current_pid and not allow_closed:
  raise ValueError(f"le mandat « {p['name']} » est clôturé : cocher « Rattacher à un mandat clôturé » pour y déplacer cette saisie (correction d'historique ; aucune nouvelle saisie n'y est acceptée)")
 return p
def concerned_invoices(invs,arrival=None):
 """invoices_json of a history row: issued invoices whose frozen annex lists the entry (role billed / annex), plus the issued invoice
 whose period receives the entry after the correction when it did not bill it (role arrival)."""
 out=[{"id":x["id"],"number":x["number"],"period_from":x["period_from"],"period_to":x["period_to"],"role":x["role"]} for x in invs]
 if arrival and arrival["id"] not in {x["id"] for x in invs if x["role"]=="billed"}:
  out.append({"id":arrival["id"],"number":arrival["number"],"period_from":arrival["period_from"],"period_to":arrival["period_to"],"role":"arrival"})
 return out
def billed_shown(form,billed):
 """The confirmation ticked on the page answers the invoices that page showed: refused if the billing of the entry changed since."""
 shown=form.get("billed_ids")
 if shown is not None and {x for x in shown.split(",") if x}!={str(x["id"]) for x in billed}:
  raise ValueError("la facturation de cette saisie a changé depuis l'ouverture de la page (une facture a été émise entre-temps) : vérifier l'avertissement puis recommencer")
def flash_variances(c,invoice_ids):
 """After a change of a billed entry: the issued invoice is untouched, its post-invoicing variance is shown, the user decides."""
 for iid in invoice_ids:
  i=c.execute("SELECT * FROM invoices WHERE id=?",(iid,)).fetchone()
  v=post_billing.invoice_variance(c,i) if i else None
  if not v: continue
  sense="aucun" if not v["has_variance"] else ("facturé en trop" if v["variance_hours"]<0 else "non facturé")
  flash(f"Attention : saisie facturée — la facture {v['number']} reste inchangée (document émis, jamais modifié). Écart post-facturation de {v['number']} : "
        f"{fr_num(v['variance_hours'])} h ({fr_num(v['variance_days'],4)} j, {sense}) entre les saisies facturées et leur valeur actuelle. À décider ensuite : "
        f"note de crédit (avoir), compensation, ou aucune action — Factures et brouillons, « Écart post-facturation ».")
def safe_return(v,default):
 v=v or ""
 ok=(v.startswith("/entries") or v.startswith("/?tab=") or bool(re.fullmatch(r"/invoice/\d+/ecart",v))) and not v.startswith("//") and not any(ord(ch)<32 or ch in "\\\x7f" for ch in v)
 return v if ok else default
def draft_warning(c,pid,work_date):
 n=c.execute("SELECT COUNT(*) FROM invoices WHERE project_id=? AND status='draft' AND period_from<=? AND period_to>=?",(pid,work_date,work_date)).fetchone()[0]
 if n: flash(f"Attention : {n} brouillon(s) de facture couvre(nt) cette date. Recalculer la quantité du brouillon avant de l'émettre.")
ENTRY_PER_PAGE=50
def entry_filters(args):
 """(where, params, filters) of the entries list; unknown or malformed filter values are ignored, never guessed."""
 where=[]; params=[]; f={}
 pid=args.get("project","")
 if pid.isascii() and pid.isdigit(): where.append("e.project_id=?"); params.append(int(pid)); f["project"]=pid   # « ² ».isdigit() is True but int() refuses it
 for k,op in (("date_from",">="),("date_to","<=")):
  v=(args.get(k) or "").strip()
  try: d=date.fromisoformat(v).isoformat() if v else None
  except ValueError: d=None
  if d: where.append(f"e.work_date{op}?"); params.append(d); f[k]=v
 q=(args.get("q") or "").strip()
 if q:
  like="%"+q.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
  where.append("e.description LIKE ? ESCAPE '\\'"); params.append(like); f["q"]=q
 if args.get("origin") in ("manual","import"):
  where.append("e.import_batch_id IS NULL" if args["origin"]=="manual" else "e.import_batch_id IS NOT NULL"); f["origin"]=args["origin"]
 return (" WHERE "+" AND ".join(where)) if where else "", params, f
@APP.route("/entries")
@login_required
def entries_list():
 where,params,f=entry_filters(request.args)
 try: page=max(1,int(request.args.get("page","1")))
 except ValueError: page=1
 with db() as c:
  total=c.execute("SELECT COUNT(*) FROM entries e"+where,params).fetchone()[0]
  pages=max(1,-(-total//ENTRY_PER_PAGE)); page=min(page,pages)
  rows=annotate_entries(c,[dict(r) for r in c.execute(ENTRY_SQL+where+" ORDER BY e.work_date DESC,e.id DESC LIMIT ? OFFSET ?",(*params,ENTRY_PER_PAGE,(page-1)*ENTRY_PER_PAGE))])
  sums=c.execute("SELECT COALESCE(SUM(e.hours),0) h,COALESCE(SUM(e.hours/COALESCE(NULLIF(p.day_hours,0),8)),0) d FROM entries e JOIN projects p ON p.id=e.project_id"+where,params).fetchone()
  projects=[dict(r) for r in c.execute("SELECT id,name,active FROM projects ORDER BY name")]
  last_changes=c.execute("SELECT COUNT(*) FROM entry_changes").fetchone()[0]
  # UX lot 2 (n° 7): totals per day and per ISO week of the days shown, over the WHOLE filtered selection (not only this page); read-only, display only
  day_tot,day_n,week_of={},{},{}
  if rows:
   shown=[date.fromisoformat(r["work_date"]) for r in rows if re.fullmatch(r"\d{4}-\d{2}-\d{2}",r["work_date"] or "")]
   if shown:
    def clamp(d,k):          # extreme dates (0001-01-01, 9999-12-31): the week is cut at the calendar's ends, never an overflow
     try: return d+timedelta(days=k)
     except OverflowError: return date.min if k<0 else date.max
    lo=clamp(min(shown),-min(shown).weekday()); hi=clamp(max(shown),6-max(shown).weekday())
    weeks={}
    for r in c.execute("SELECT e.work_date d,COUNT(*) n,COALESCE(SUM(e.hours),0) h FROM entries e"+where+(" AND " if where else " WHERE ")+"e.work_date BETWEEN ? AND ? GROUP BY e.work_date",(*params,lo.isoformat(),hi.isoformat())):
     day_tot[r["d"]]=r["h"]; day_n[r["d"]]=r["n"]
     try: y,w,_=date.fromisoformat(r["d"]).isocalendar()
     except ValueError: continue
     weeks[(y,w)]=weeks.get((y,w),0)+r["h"]
    for d_ in shown:
     y,w,_=d_.isocalendar(); mon=clamp(d_,-d_.weekday())
     week_of[d_.isoformat()]={"key":f"{y}-{w}","label":f"Semaine {w}","from":mon.isoformat(),"to":clamp(d_,6-d_.weekday()).isoformat(),"hours":weeks.get((y,w),0)}
 today=rules.local_today(); mon=today-timedelta(days=today.weekday()); first=today.replace(day=1); prev_last=first-timedelta(days=1)
 keep={k:v for k,v in f.items() if k not in ("date_from","date_to")}
 quick=[(label,a.isoformat(),b.isoformat()) for label,a,b in (("Cette semaine",mon,today),("Semaine dernière",mon-timedelta(days=7),mon-timedelta(days=1)),
        ("Ce mois",first,today),("Mois dernier",prev_last.replace(day=1),prev_last))]
 quick=[{"label":l,"href":"/entries?"+urllib_parse.urlencode(dict(keep,date_from=a,date_to=b)),"on":f.get("date_from")==a and f.get("date_to")==b} for l,a,b in quick]
 return render_template("entries.html",rows=rows,total=total,page=page,pages=pages,per_page=ENTRY_PER_PAGE,sum_hours=sums["h"],sum_days=sums["d"],projects=projects,f=f,
                        query=urllib_parse.urlencode(f),changes=last_changes,version=VERSION,env_label=ENV_LABEL,here=request.full_path.rstrip("?"),
                        day_tot=day_tot,day_n=day_n,week_of=week_of,quick=quick)
@APP.route("/entries.csv")
@login_required
def entries_csv():
 where,params,_=entry_filters(request.args)
 with db() as c: rows=[dict(r) for r in c.execute(ENTRY_SQL+where+" ORDER BY e.work_date,e.id",params)]
 out=io.StringIO(); w=csv.writer(out,delimiter=";",lineterminator="\r\n")
 w.writerow(["id","date","projet","debut","fin","heures","jours_equivalents","description","origine","reference_source"])
 for r in rows:
  w.writerow([csv_cell(x) for x in [r["id"],r["work_date"],r["project"],r["start_time"],r["end_time"],f"{r['hours']:.6f}".rstrip("0").rstrip(".").replace(".",","),
              f"{r['hours']/(r['day_hours'] or 8):.5f}".rstrip("0").rstrip(".").replace(".",","),r["description"],"import" if r["import_batch_id"] else "manuelle",r["source_ref"]]])
 log("entries_exported",f"rows={len(rows)}")
 resp=make_response("\ufeff"+out.getvalue()); resp.headers["Content-Type"]="text/csv; charset=utf-8"
 resp.headers["Content-Disposition"]=f'attachment; filename="saisies-{rules.local_today().isoformat()}.csv"'; return resp
def entry_provenance(c,e):
 """rc19: where an imported entry comes from (file, sheet, row, batch, import date, values read in the workbook). Shown, never edited."""
 if not e["import_batch_id"] and (e["source"] or "manual")=="manual": return None
 r=c.execute("""SELECT r.batch_id,r.source_sheet,r.source_row,r.raw_json,b.source_filename,b.created_at,b.committed_at,b.status FROM import_batch_rows r
                JOIN import_batches b ON b.id=r.batch_id WHERE r.entry_id=? AND r.batch_id IS ? ORDER BY r.id LIMIT 1""",(e["id"],e["import_batch_id"])).fetchone()
 out={"source_ref":e["source_ref"],"batch_id":e["import_batch_id"],"source":e["source"]}
 if r:
  try: raw=json.loads(r["raw_json"]) if r["raw_json"] else {}
  except ValueError: raw={}
  out.update(file=r["source_filename"],sheet=r["source_sheet"],row=r["source_row"],batch_id=r["batch_id"],imported_at=r["committed_at"] or r["created_at"],
             batch_status=r["status"],raw=raw if isinstance(raw,dict) else {})
 elif e["import_batch_id"]:
  b=c.execute("SELECT source_filename,created_at,committed_at,status FROM import_batches WHERE id=?",(e["import_batch_id"],)).fetchone()
  if b: out.update(file=b["source_filename"],imported_at=b["committed_at"] or b["created_at"],batch_status=b["status"])
 return out
def entry_page_context(c,e,eid):
 hist=[dict(r) for r in c.execute("SELECT * FROM entry_changes WHERE entry_id=? ORDER BY id",(eid,))]
 for h_ in hist:
  for k in ("before","after"): h_[k]=json.loads(h_[k+"_json"]) if h_.get(k+"_json") else None
  try: h_["invoices"]=json.loads(h_.get("invoices_json") or "[]")
  except ValueError: h_["invoices"]=[]
 return {"hist":hist,"projects":[dict(r) for r in c.execute("SELECT id,name,active FROM projects ORDER BY name")],
         "invs":post_billing.entry_invoices(c,eid),"provenance":entry_provenance(c,e),
         # rc19: imported entries keep their declared hours, which may differ from their clock times: said on the page
         "clock_hours":(clock_minutes(e["start_time"],e["end_time"]) or 0)/60 if e["start_time"] and e["end_time"] and CLOCK_RE.match(e["start_time"]) and CLOCK_RE.match(e["end_time"]) else None}
@APP.route("/entry/<int:eid>/edit",methods=["GET","POST"])
@login_required
def entry_edit(eid):
 """rc19: every entry stays editable (old, imported, of a closed mandate, invoiced). An entry billed by an issued invoice needs a
 reason and an explicit confirmation; the invoice never changes, its post-invoicing variance is shown afterwards."""
 back_to=safe_return(request.values.get("return_to"),"/entries")
 c=db(autocommit=True)
 try:
  c.execute("BEGIN IMMEDIATE")
  e=c.execute(ENTRY_SQL+" WHERE e.id=?",(eid,)).fetchone()
  if not e:
   c.execute("ROLLBACK")
   if c.execute("SELECT 1 FROM entry_changes WHERE entry_id=? AND action='delete'",(eid,)).fetchone():
    flash(f"Saisie n° {eid} supprimée entre-temps : son historique reste consultable ci-dessous."); return redirect(url_for("entry_history",eid=eid))
   abort(404)
  if request.method=="POST":
   committed=False
   try:
    seen=request.form.get("rev")
    work_date,start,end,h,desc=parse_entry_form(request.form,keep=e)
    # rc19: a field the user did not change keeps its stored value. Imported entries keep the DECLARED hours of the workbook, which may
    # differ from their clock times: unchanged start AND end never recompute the duration (only a new start or end time does)
    if start and end and (start,end)==(e["start_time"],e["end_time"]): h=e["hours"]
    p=target_project(c,int(request.form.get("project_id") or 0),e["project_id"],request.form.get("allow_closed")=="1")
    same=(work_date,p["id"],start,end,h,desc)==(e["work_date"],e["project_id"],e["start_time"],e["end_time"],e["hours"],e["description"])
    if seen and seen!=entry_rev(e):
     if same: c.execute("ROLLBACK"); flash("Cette correction est déjà enregistrée (formulaire envoyé deux fois)."); return redirect(back_to)
     raise ValueError("cette saisie a été modifiée depuis l'ouverture du formulaire (autre onglet ou autre session) : les valeurs saisies sont conservées ci-dessous ; vérifier l'historique des corrections, puis enregistrer de nouveau pour écraser, ou abandonner")
    if same: c.execute("ROLLBACK"); flash("Aucune modification : la saisie est identique."); return redirect(back_to)
    reason=change_reason(request.form.get("reason"))
    if p["id"]!=e["project_id"] and not p["active"] and not reason:
     raise ValueError(f"motif obligatoire pour rattacher cette saisie au mandat clôturé « {p['name']} » (correction d'historique)")
    invs=post_billing.entry_invoices(c,eid); billed=[x for x in invs if x["role"]=="billed"]
    billed_shown(request.form,billed)
    if billed:
     nums=", ".join(x["number"] for x in billed)
     if not reason: raise ValueError(f"motif obligatoire : cette saisie est facturée par la facture émise {nums} (la facture ne sera pas modifiée ; un écart post-facturation sera affiché)")
     if request.form.get("confirm_billed")!="1": raise ValueError(f"cocher la confirmation : la facture émise {nums} reste inchangée et un écart post-facturation sera affiché")
    arrival=post_billing.period_invoice(c,p["id"],work_date)
    concerned=concerned_invoices(invs,arrival)
    before=entry_json(e)
    c.execute("UPDATE entries SET work_date=?,project_id=?,start_time=?,end_time=?,hours=?,description=? WHERE id=?",(work_date,p["id"],start,end,h,desc,eid))
    after=entry_json(c.execute(ENTRY_SQL+" WHERE e.id=?",(eid,)).fetchone())
    c.execute("INSERT INTO entry_changes(entry_id,action,before_json,after_json,changed_at,reason,actor,invoices_json) VALUES(?,?,?,?,?,?,?,?)",
              (eid,"update",before,after,rules.utc_now_iso(),reason,SEC["user"],json.dumps(concerned,ensure_ascii=False)))
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("time_entry_updated",json.dumps({"id":eid,"before":f"{e['work_date']}/{e['hours']}h/{e['project']}",
              "after":f"{work_date}/{h}h/{p['name']}","invoices":[f"{x['number']}:{x['role']}" for x in concerned],"by":SEC["user"],"reason":reason},ensure_ascii=False)))
    c.execute("COMMIT"); committed=True
    flash(f"Saisie n° {eid} modifiée (l'ancienne valeur reste dans l'historique des corrections).")
    with db() as c2:
     flash_variances(c2,[x["id"] for x in billed])
     annexed_only=[x for x in invs if x["role"]=="annex"]
     if not billed and annexed_only:
      flash(f"Saisie listée dans l'annexe cumulative de {', '.join(x['number'] for x in annexed_only)} sans y être facturée (hors période) : ces factures restent inchangées et leur montant n'en dépend pas.")
     if not billed and not annexed_only:
      last=contract(c2,p)["last_issued_to"]
      if arrival: flash(f"Attention : période déjà facturée par la facture émise {arrival['number']} ({rules.fr_date(arrival['period_from'])} → {rules.fr_date(arrival['period_to'])}). Cette prestation n'apparaît pas dans cette facture : reliquat à traiter sur une prochaine facture.")
      elif last and work_date<=last: flash(f"Attention : période déjà facturée (facture émise jusqu'au {rules.fr_date(last)}). Cette prestation n'apparaît pas dans la facture émise : reliquat à traiter sur une prochaine facture.")
     else:
      for b in billed:
       if p["id"]!=b["project_id"]:
        flash(f"Attention : saisie facturée par {b['number']} et désormais rattachée au mandat « {p['name']} » : {b['number']} garde ces heures (écart ci-dessus) ; sur « {p['name']} » elles ne sont pas facturées.")
       elif not (b["period_from"]<=work_date<=b["period_to"]):
        if arrival: flash(f"Attention : date déplacée dans la période de la facture émise {arrival['number']}, qui ne l'a pas facturée : la saisie reste facturée par {b['number']} (aucune double facturation).")
        else: flash(f"Attention : cette saisie reste facturée par {b['number']} ; datée du {rules.fr_date(work_date)} (période non encore facturée), elle n'est pas comptée une seconde fois : le prochain brouillon de « {p['name']} » l'exclut de la période (la première facture émise qui l'a facturée la garde).")
     if p["id"]!=e["project_id"] and not p["active"]:
      flash(f"Attention : heures ajoutées au mandat clôturé « {p['name']} » : elles ne peuvent pas être facturées tant qu'il reste clôturé ; sa position enregistrée à la clôture est modifiée.")
     if p["id"]!=e["project_id"] and not e["project_active"]:
      flash(f"Attention : heures retirées du mandat clôturé « {e['project']} » : sa position enregistrée à la clôture est modifiée.")
     if p["id"]==e["project_id"] and not p["active"] and (h,work_date)!=(e["hours"],e["work_date"]):
      flash(f"Attention : saisie du mandat clôturé « {p['name']} » modifiée : sa position enregistrée à la clôture est modifiée.")
     for w in entry_coherence_warnings(c2,p,work_date,start,end,eid): flash(w)
     draft_warning(c2,p["id"],work_date)
     if p["id"]!=e["project_id"] or work_date!=e["work_date"]: draft_warning(c2,e["project_id"],e["work_date"])
    return redirect(back_to)
   except HTTPException:
    raise
   except Exception as ex:
    if committed:   # the correction is saved: an error while computing the warnings must not say « non modifiée »
     APP.logger.exception("avertissements après correction de la saisie %s",eid)
     flash("Avertissements non calculés (erreur interne, détail dans le journal du service) : vérifier la saisie, le mandat et les brouillons concernés."); return redirect(back_to)
    try: c.execute("ROLLBACK")
    except Exception: pass
    flash("Saisie non modifiée : "+str(ex)); e=dict(e)
  else: c.execute("ROLLBACK")
  ctx=entry_page_context(c,e,eid)
 finally: c.close()
 billed=[x for x in ctx["invs"] if x["role"]=="billed"]
 return render_template("entry_edit.html",e=e,rev=entry_rev(e),billed=billed,annexed=[x for x in ctx["invs"] if x["role"]=="annex"],return_to=back_to,
                        version=VERSION,env_label=ENV_LABEL,form=request.form if request.method=="POST" else None,max_reason=MAX_REASON,
                        hours_plain=format(Decimal(repr(e["hours"])),"f"),secs=len(e["start_time"] or "")>5 or len(e["end_time"] or "")>5,multiline=bool(re.search(r"[\r\n]",e["description"] or "")),
                        **{k:v for k,v in ctx.items() if k!="invs"})
@APP.route("/entry/<int:eid>/historique")
@login_required
def entry_history(eid):
 """rc19: the full correction history of an entry, readable even once it has been deleted (before values, date, user, reason, invoices)."""
 with db() as c:
  e=c.execute(ENTRY_SQL+" WHERE e.id=?",(eid,)).fetchone()
  hist=entry_page_context(c,e,eid)["hist"] if e else [dict(r) for r in c.execute("SELECT * FROM entry_changes WHERE entry_id=? ORDER BY id",(eid,))]
 if not e:
  if not hist: abort(404)
  for h_ in hist:
   for k in ("before","after"): h_[k]=json.loads(h_[k+"_json"]) if h_.get(k+"_json") else None
   try: h_["invoices"]=json.loads(h_.get("invoices_json") or "[]")
   except ValueError: h_["invoices"]=[]
 return render_template("entry_history.html",eid=eid,e=e,hist=hist,deleted=next((h_ for h_ in reversed(hist) if h_["action"]=="delete"),None) if not e else None)
@APP.route("/entry/<int:eid>/delete",methods=["POST"])
@login_required
def entry_delete(eid):
 """rc19: any entry can be deleted (a copy stays in the history). An entry billed by an issued invoice needs a reason and the
 explicit confirmation (form of its correction page); the invoice keeps its frozen annex, the variance shows the removed hours."""
 back_to=safe_return(request.form.get("return_to"),"/entries")
 c=db(autocommit=True); billed=[]; committed=False
 try:
  c.execute("BEGIN IMMEDIATE")
  e=c.execute(ENTRY_SQL+" WHERE e.id=?",(eid,)).fetchone()
  if not e:
   if c.execute("SELECT 1 FROM entry_changes WHERE entry_id=? AND action='delete'",(eid,)).fetchone(): raise ValueError(f"saisie n° {eid} déjà supprimée (historique conservé)")
   raise ValueError("saisie introuvable")
  seen=request.form.get("rev")
  if seen and seen!=entry_rev(e): raise ValueError("cette saisie a été modifiée depuis l'ouverture de la page (autre onglet ou autre session) : vérifier son historique avant de la supprimer")
  reason=change_reason(request.form.get("reason"))
  invs=post_billing.entry_invoices(c,eid); billed=[x for x in invs if x["role"]=="billed"]
  billed_shown(request.form,billed)
  if billed:
   nums=", ".join(x["number"] for x in billed)
   if not reason or request.form.get("confirm_billed")!="1":
    raise ValueError(f"saisie facturée par la facture émise {nums} : la supprimer depuis sa page de correction (« Modifier »), avec un motif et la confirmation explicite (la facture émise ne sera pas modifiée)")
  c.execute("INSERT INTO entry_changes(entry_id,action,before_json,after_json,changed_at,reason,actor,invoices_json) VALUES(?,?,?,?,?,?,?,?)",
            (eid,"delete",entry_json(e),None,rules.utc_now_iso(),reason,SEC["user"],json.dumps(concerned_invoices(invs),ensure_ascii=False)))
  n=c.execute("DELETE FROM entries WHERE id=?",(eid,)).rowcount
  if n!=1: raise ValueError("saisie introuvable")
  c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("time_entry_deleted",json.dumps({"id":eid,"before":f"{e['work_date']}/{e['hours']}h/{e['project']}",
            "invoices":[f"{x['number']}:{x['role']}" for x in invs],"by":SEC["user"],"reason":reason},ensure_ascii=False)))
  c.execute("COMMIT"); committed=True; flash(f"Saisie n° {eid} supprimée ({e['work_date']}, {fr_g(e['hours'])} h). Une copie reste dans l'historique des corrections.")
  if not e["project_active"]: flash(f"Attention : heures retirées du mandat clôturé « {e['project']} » : sa position enregistrée à la clôture est modifiée.")
  with db() as c2:
   flash_variances(c2,[x["id"] for x in billed])
   draft_warning(c2,e["project_id"],e["work_date"])
 except Exception as ex:
  if committed:   # the deletion is saved: an error while computing the warnings must not say « refusée »
   APP.logger.exception("avertissements après suppression de la saisie %s",eid)
   flash("Avertissements non calculés (erreur interne, détail dans le journal du service) : vérifier le mandat et les brouillons concernés."); return redirect(back_to)
  try: c.execute("ROLLBACK")
  except Exception: pass
  flash("Suppression refusée : "+str(ex))
  if billed: return redirect(url_for("entry_edit",eid=eid,return_to=back_to)+"#supprimer")
 finally: c.close()
 return redirect(back_to)

# --- drafts -------------------------------------------------------------------------------------
ROUNDING_MODES=("exact","nearest","up","down"); ROUNDING_STEPS=("0.25","0.5","1")
def rounding(q,mode,step="0.25"):
 d=Decimal(str(q)); increment=Decimal(str(step))
 if increment<=0: raise ValueError("pas d'arrondi invalide")
 units=d/increment
 if mode=="up": units=units.to_integral_value(rounding=ROUND_CEILING)
 elif mode=="down": units=units.to_integral_value(rounding=ROUND_FLOOR)
 elif mode=="nearest": units=units.to_integral_value(rounding=ROUND_HALF_UP)
 else: return float(d)
 return float(units*increment)
def billing_params(form):
 mode=form.get("rounding","exact"); step=str(form.get("rounding_step","0.25"))
 if mode not in ROUNDING_MODES: raise ValueError("règle d'arrondi inconnue")
 if step not in ROUNDING_STEPS: raise ValueError("pas d'arrondi invalide")
 f=iso_date(form.get("period_from"),"début de période"); t=iso_date(form.get("period_to"),"fin de période")
 if f>t: raise ValueError("la date de début doit précéder la date de fin")
 return f,t,mode,step
@APP.route("/suggest",methods=["POST"])
@login_required
def suggest():
 try:
  start,end,mode,step=billing_params(request.form)
  with db() as c:
   p=c.execute("SELECT * FROM projects WHERE id=?",(int(request.form.get("project_id") or 0),)).fetchone()
   if not p: raise ValueError("projet inconnu")
   hours=c.execute("SELECT COALESCE(SUM(hours),0) h FROM entries WHERE project_id=? AND work_date BETWEEN ? AND ?",(p["id"],start,end)).fetchone()["h"]
   # rc19: an entry already billed by an issued invoice (its date was reclassified afterwards) is never proposed a second time
   ids=[r["id"] for r in c.execute("SELECT id FROM entries WHERE project_id=? AND work_date BETWEEN ? AND ? AND id IN (SELECT entry_id FROM invoice_annex_entries)",(p["id"],start,end))]
   # only an invoice of THIS mandate counts: an entry billed by another mandate's invoice and moved here is not billed here
   billed=post_billing.entries_invoices(c,ids); bids=[i for i in ids if any(x["role"]=="billed" and x["project_id"]==p["id"] for x in billed.get(i,[]))]
   already=c.execute(f"SELECT COALESCE(SUM(hours),0) FROM entries WHERE id IN ({','.join('?'*len(bids))})",bids).fetchone()[0] if bids else 0.0
   pos=contract(c,p,upto=end)
   # UX lot 2 (n° 3, R-1): what the draft form announces BEFORE the draft exists, all read-only and computed here (never in the browser)
   n_period=c.execute("SELECT COUNT(*) FROM entries WHERE project_id=? AND work_date BETWEEN ? AND ?",(p["id"],start,end)).fetchone()[0]-len(bids)
   overlap=[dict(r) for r in c.execute("SELECT id,period_from,period_to,qty,unit FROM invoices WHERE project_id=? AND status='draft' AND period_from<=? AND period_to>=? ORDER BY id",(p["id"],end,start))]
   clash=credits.period_clash(c,p["id"],start,end)
   whole=contract(c,p)          # the same figures as the PO warning given after the draft is created (po_warning)
 except ValueError as e: return jsonify(error=str(e)),400
 # Entries are minute-based: 6 decimals cannot cross a real rounding boundary but absorb float summation error.
 raw=round((hours-already)/(p["day_hours"] or 8),6); qty=rounding(raw,mode,step)
 def preview(q):
  """Check 12 (its narrative part, invoice_checks.period_story: the rule itself) and the PO balance, for a quantity q in days. Indicative: issuance runs every check again."""
  notes=invoice_checks.period_story(q,raw,n_period>0,start,end)
  over_po=bool(whole["ordered_days"]) and whole["billed_days"]+whole["draft_days"]+q>whole["ordered_days"]+1e-9
  return {"qty":q,"amount":float(rules.amounts(q,p["rate"],0)["ht"]),"gap_days":round(q-raw,6),"check12_ok":not notes,"check12":[fr_detail(n) for n in notes],"po_over":over_po}
 typed=None
 if (request.form.get("qty") or "").strip():
  try: typed=preview(num_field(request.form.get("qty"),"quantité",0.0,MAX_DAYS,lo_open=True))
  except ValueError: typed=None
 return jsonify(hours=round(hours,3),already_billed_hours=round(already,3),raw_days=round(raw,5),suggested_qty=qty,unit_rate=p["rate"],suggested_amount=float(rules.amounts(qty,p["rate"],0)["ht"]),rounding=mode,rounding_step=step,
  billed_days_before=pos["billed_days"],unbilled_days_to_date=pos["unbilled_days"],po_balance_days=pos["po_balance_days"],ordered_days=pos["ordered_days"],offered_days=pos["offered_days"],
  entries_in_period=n_period,options={m_:preview(rounding(raw,m_,step)) for m_ in ROUNDING_MODES},typed=typed,
  overlapping_drafts=[dict(d,period_label=f"{rules.fr_date(d['period_from'])} → {rules.fr_date(d['period_to'])}",qty_label=fr_exact(d["qty"])+(" j" if d["unit"]=="day" else " h")) for d in overlap],
  issued_clash=({"number":clash["number"],"period_label":f"{rules.fr_date(clash['period_from'])} → {rules.fr_date(clash['period_to'])}"} if clash else None),
  po_ordered_days=whole["ordered_days"],po_billed_days=whole["billed_days"],po_draft_days=whole["draft_days"])
def _other_amount(v):
 d=money_field(v,"montant « autres »")
 if d<0: raise ValueError("le montant « autres » ne peut pas être négatif (pour un geste commercial, utiliser une note de crédit)")
 return d
def _checked_description(v,lines=pdf_layout.INVOICE_DESCRIPTION_LINES):
 """The frozen PDF prints at most 4 lines of description: refuse a longer text instead of truncating it silently on an immutable document.
 D6 (2026-10-06): on an invoice the 4th line of the cell carries the invoiced period, so 3 lines; a credit note keeps 4."""
 d=(v or "").strip()
 if pdf_layout.description_line_count(d)>lines: raise ValueError(f"description trop longue pour le document imprimé ({lines} lignes au maximum, environ {35*lines} caractères"+(" ; la 4e ligne porte la période" if lines<pdf_layout.MAX_DESCRIPTION_LINES else "")+") : la raccourcir")
 return d
def _checked_other_label(v,amount=0,vat_mode="hors_tva"):
 """rc12: the « AUTRES » label (with its VAT suffix) wraps on at most 4 printed lines: refuse a longer one instead of cutting it.
 G4 (2026-10-06, R-E3-2): with an amount, the totals of the invoice print it on ONE line before that amount: refuse a label that would run over it."""
 lab=(v or "").strip()
 if pdf_layout.description_line_count(pdf_layout.other_label({"other_label":lab},1))>pdf_layout.MAX_DESCRIPTION_LINES: raise ValueError(f"libellé « autres » trop long pour le document imprimé ({pdf_layout.MAX_DESCRIPTION_LINES} lignes au maximum) : le raccourcir")
 if not pdf_layout.other_label_fits({"other_label":lab,"other_vat_mode":vat_mode},amount): raise ValueError("libellé « autres » trop long pour la ligne des totaux de la facture (il déborderait sur le montant) : le raccourcir")
 return lab
def _checked_note(v):
 """E-4 (decision B, 2026-10-07): the invoice prints its free note in a fixed zone of ONE line: refuse a longer note instead of moving the page."""
 n=" ".join((v or "").split())
 if not pdf_layout.note_fits(n): raise ValueError("note de facture trop longue : elle s'imprime sur une seule ligne de la facture (environ 90 caractères) : la raccourcir")
 return n
def draft_values(c,form,pid,exclude=None):
 unit=form.get("unit","day")
 if unit not in ("day","hour"): raise ValueError("unité inconnue")
 qty=num_field(form.get("qty"),"quantité",0.0,MAX_DAYS*(24 if unit=="hour" else 1),lo_open=True)
 f,t,mode,step=billing_params(form)
 clash=credits.period_clash(c,pid,f,t)   # rc25: an entirely credited invoice no longer stands, its period may be invoiced again
 if clash: raise ValueError(f"la période chevauche la facture émise {clash['number']} ({rules.fr_date(clash['period_from'])} → {rules.fr_date(clash['period_to'])}) : pour la facturer de nouveau, créditer d'abord cette facture intégralement (note de crédit totale émise)")
 ovm=form.get("other_vat_mode") or rules.get_settings(c).get("other_vat_default") or "hors_tva"
 if ovm not in rules.OTHER_VAT_MODES: raise ValueError("traitement TVA de la ligne « AUTRES » inconnu")
 inv_date=(form.get("invoice_date") or "").strip()
 if inv_date:
  inv_date=iso_date(inv_date,"date de facture")
  if inv_date<f: raise ValueError("la date de facture ne peut pas précéder le début de la période facturée")
 return {"invoice_date":inv_date or None,"other_vat_mode":ovm,"period_from":f,"period_to":t,"qty":qty,"unit":unit,"rounding":mode,"rounding_step":float(step),"note":_checked_note(form.get("note")),
         "description":_checked_description(form.get("description")),"other_amount":(oa:=_other_amount(form.get("other_amount"))),"other_label":_checked_other_label(form.get("other_label"),oa,ovm)}
ISSUE_DAY="date d'émission"
def record_date_change(c,iid,old,new,context):
 """Trace an invoice-date change on a draft (rc5). Empty = the real issuance day will be printed."""
 if (old or None)==(new or None): return
 c.execute("INSERT INTO invoice_date_changes(invoice_id,old_date,new_date,context,changed_at) VALUES(?,?,?,?,?)",(iid,old or None,new or None,context,rules.utc_now_iso()))
 c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("draft_invoice_date_changed",f"id={iid};from={old or ISSUE_DAY};to={new or ISSUE_DAY};context={context}"))
def record_number_change(c,iid,old,new,manual,context):
 """Trace the number of a draft (rc37, P3): append-only table + audit line. Nothing when it does not change."""
 if (old or None)==(new or None): return
 c.execute("INSERT INTO invoice_number_changes(invoice_id,old_number,new_number,manual,context,changed_at) VALUES(?,?,?,?,?,?)",(iid,old,new,1 if manual else 0,context,rules.utc_now_iso()))
 c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("draft_number_changed",f"id={iid};from={old or '-'};to={new or '-'};manual={1 if manual else 0};context={context}"))
def number_year(invoice_date): return int((invoice_date or rules.local_today().isoformat())[:4])
def number_hint(c,iid=None,year=None):
 """The free number proposed (never written by itself)."""
 return rules.propose_invoice_number(c,year or number_year(None),exclude_id=iid)
def number_refusal(c,number,iid,year):
 x=rules.number_conflict(c,number,exclude_id=iid)
 return None if not x else (f"le numéro {number} est déjà utilisé par {rules.describe_conflict(x)} ; numéro libre proposé : {number_hint(c,iid,year)}. "
                            "Rien n'a été modifié : aucun numéro n'est jamais remplacé automatiquement")
def date_history(c,iid): return [dict(r) for r in c.execute("SELECT * FROM invoice_date_changes WHERE invoice_id=? ORDER BY id",(iid,))]
def po_warning(c,p):
 pos=contract(c,p)
 if pos["ordered_days"] and pos["billed_days"]+pos["draft_days"]>pos["ordered_days"]+1e-9:
  flash(f"Attention : les brouillons et factures émises ({fr_g(pos['billed_days']+pos['draft_days'])} j) dépassent le solde du bon de commande ({fr_g(pos['ordered_days'])} j commandés).")
@APP.route("/invoice",methods=["POST"])
@login_required
def invoice():
 try:
  with db() as c:
   p=active_project(c,int(request.form.get("project_id") or 0))
   v=draft_values(c,request.form,p["id"])
   v["unit_rate"]=p["rate"] if v["unit"]=="day" else p["rate"]/(p["day_hours"] or 8)
   v["vat"]=p["vat"]; v["project_id"]=p["id"]; v["description"]=v["description"] or p["name"]
   c.execute("BEGIN IMMEDIATE")   # rc37 (P3): the proposal of the number and the insertion are one step (two creations cannot take the same number)
   v["id"]=c.execute("SELECT MAX(COALESCE((SELECT MAX(id) FROM invoices),0),COALESCE((SELECT MAX(invoice_id) FROM invoice_date_changes),0),COALESCE((SELECT MAX(target_invoice_id) FROM credit_operations),0))+1").fetchone()[0]
   v["number"]=number_hint(c,None,number_year(v["invoice_date"])); v["number_manual"]=0      # the draft RESERVES its proposed number at once (rc37, owner request 26.10)
   new_id=c.execute(f"INSERT INTO invoices({','.join(v)}) VALUES({','.join('?'*len(v))})",tuple(v.values())).lastrowid
   record_date_change(c,new_id,None,v["invoice_date"],"création du brouillon"); record_number_change(c,new_id,None,v["number"],False,"création du brouillon")
   dup=c.execute("SELECT COUNT(*) FROM invoices WHERE project_id=? AND status='draft' AND id<>? AND period_from<=? AND period_to>=?",(p["id"],new_id,v["period_to"],v["period_from"])).fetchone()[0]
   if dup: flash(f"Attention : {dup} autre(s) brouillon(s) couvre(nt) déjà cette période du mandat. Un seul des deux pourra être émis (le second sera refusé à l'émission).")
   log_msg=f"project={p['id']};qty={v['qty']};invoice_date={v['invoice_date']};number={v['number']}"; created_number=v["number"]
  log("draft_created",log_msg);flash("Brouillon créé.")
  flash(f"Numéro de facture proposé et réservé : {created_number} (modifiable dans l'éditeur du brouillon).")
  flash("Il figure dans « Factures et brouillons » (statut brouillon) : le modifier ou l'émettre depuis cette page.")
  session["draft_created"]=new_id   # UX lot 1 (n° 6): « Ouvrir le brouillon » / « Contrôler avant émission » on the next page, no redirection
  with db() as c: po_warning(c,p)
 except Exception as e:refused("Brouillon non créé : "+str(e))
 return back("billing")
EDIT_FIELDS=("period_from","period_to","qty","unit","rounding","rounding_step","vat","description","other_amount","other_label","other_vat_mode","invoice_date","note","number")
def edit_view(i,form=None):
 """Values shown by the draft editor: the stored draft, or (a refused / unsaved form shown again) what was typed. rc37: the lines are read from the form rows,
 never through kept_forms (that mechanism keeps one value per field name, a list of lines would collapse)."""
 v=dict(i)
 v["number_shown"]=i["number"] or ""
 if form is not None:
  for k in EDIT_FIELDS:
   if k in form: v[k]=form.get(k)
  if "number" in form: v["number_shown"]=form.get("number")
  try: v["rounding_step"]=float(v["rounding_step"])
  except (TypeError,ValueError): v["rounding_step"]=0.25
 return v
def edit_recap(v,rows,unit_rate):
 """Totals shown in the editor, computed on the server with the same function as the PDF and the issuance (None when a typed value is not a number yet)."""
 try:
  lines=manual_lines.validate([r for r in rows if r["line_description"] or r["line_qty"] or r["line_rate"]],v.get("unit")) if rows else []
  qty=num_field(v.get("qty"),"quantité",0.0,MAX_DAYS*(24 if v.get("unit")=="hour" else 1),lo_open=True)
  vat=num_field(v.get("vat"),"taux de TVA",0.0,100.0,default=float(v.get("vat") or 0))
  oa=_other_amount(v.get("other_amount"))
  a=rules.amounts(qty,unit_rate,vat,oa,v.get("other_vat_mode"),lines)
  return {"a":a,"lines":[dict(l,amount=rules.line_amount(l["qty"],l["unit_rate"])) for l in lines],"qty":qty,"unit_rate":unit_rate,"error":None}
 except ValueError as e: return {"a":None,"lines":[],"qty":None,"unit_rate":unit_rate,"error":str(e)}
def edit_rate(i,unit):
 """Unit price the draft would have once saved with this unit: its own rate, or the mandate's when the unit changes (same rule as the save)."""
 want=float(i["rate"] or 0) if unit=="day" else float(i["rate"] or 0)/(i["day_hours"] or 8)
 return float(i["unit_rate"]) if unit==i["unit"] and not (float(i["unit_rate"])<=0<want) else want
def fmt_rate(x):
 """Unit rate as shown in the editor field: 4 decimals at most, 2 at least, no useless zero."""
 s=f"{Decimal(str(round(float(x),4))):.4f}".rstrip("0"); a,_,b=s.partition(".")
 return a+"."+b.ljust(2,"0")
def typed_rate(exc,form):
 """rc41 (exception mandate only): the rate TYPED in the editor, as a float, or None when the field is absent, empty or still the one displayed (an untouched field leaves the
 usual rule: the draft keeps its rate, or takes the mandate's when the unit changes). Raises ValueError for an invalid rate. Always None for any other mandate: a forged field is ignored."""
 if not exc or form is None: return None
 raw=form.get("unit_rate")
 if raw is None or not raw.strip(): return None
 d=rules.unit_rate_typed(raw)
 try:
  if d==rules.unit_rate_typed(form.get("unit_rate_shown")): return None
 except ValueError: pass
 return float(d)
def edit_address_context(c,i,choice=None):
 """Billing-address menu of the editor: the active addresses of this client (grouped by legal identity), the one the draft carries even when deactivated, and the
 text that the draft prints for the current choice (the mandate's own address while no choice was saved: decision D8)."""
 proj=c.execute("SELECT * FROM projects WHERE id=?",(i["project_id"],)).fetchone()
 opts=addresses.listing(c,addresses.client_key(proj))
 have=i["billing_address_id"]
 if have is not None and have not in [o["id"] for o in opts]:
  cur=addresses.get(c,have)
  if cur: opts.append(cur)
 sel=str(have or "") if choice is None else str(choice)
 if sel and sel.isdigit() and int(sel)!=have:
  pick=next((o for o in opts if o["id"]==int(sel)),None); label,contact,text=(pick["label"],pick["contact"],pick["address"]) if pick else ("","","")
 elif sel:
  label,contact,text,_=addresses.effective(i,proj)
 else: label,contact,text,_=("",proj["billing_contact"] or "",proj["billing_address"] or "","mandat")
 return {"options":opts,"choice":sel,"label":label,"text":"\n".join(x for x in (contact,text) if x),"saved_id":have,"client_key":addresses.client_key(proj)}
def edit_number_context(c,i,v):
 """Number box of the editor: what is reserved by the draft (or, for a draft created before rc37 that has none yet, the free number that would be proposed)."""
 year=number_year(v.get("invoice_date") if isinstance(v.get("invoice_date"),str) else i["invoice_date"])
 try: proposal=number_hint(c,i["id"],year)
 except Exception: proposal=""
 return {"value":v.get("number_shown") if v.get("number_shown") not in (None,"") else (i["number"] or proposal),"reserved":i["number"] is not None,"manual":bool(i["number_manual"]),
         "proposal":proposal,"unsaved_proposal":i["number"] is None,"max":rules.INVOICE_NUMBER_MAX,"history":[dict(r) for r in c.execute("SELECT * FROM invoice_number_changes WHERE invoice_id=? ORDER BY id",(i["id"],))]}
def render_edit(c,i,iid,v,rows,hist):
 proj=c.execute("SELECT * FROM projects WHERE id=?",(i["project_id"],)).fetchone(); exc=rules.exception_mandate(proj)
 posted=request.method=="POST"
 try: typed=typed_rate(exc,request.form if posted else None)
 except ValueError: typed=None
 rate=typed if typed is not None else edit_rate(i,v.get("unit"))
 rate_field=(request.form.get("unit_rate") if posted and exc and request.form.get("unit_rate") is not None else fmt_rate(rate))
 rate_shown=(request.form.get("unit_rate_shown") if posted and exc and request.form.get("unit_rate_shown") is not None else fmt_rate(i["unit_rate"]))
 return render_template("invoice_edit.html",rate_exception=exc,rate_field=rate_field,rate_shown=rate_shown,max_unit_rate=rules.MAX_UNIT_RATE,i=v,iid=iid,rows=rows,num=edit_number_context(c,i,v),addr=edit_address_context(c,i,request.form.get("billing_address_id") if request.method=="POST" and "billing_address_id" in request.form else None),other_vat_modes=rules.OTHER_VAT_MODES,date_hist=hist,units=rules.MANUAL_UNITS,max_lines=pdf_layout.MAX_MANUAL_LINES,
                        max_rows_budget=pdf_layout.MANUAL_ROWS_BUDGET,recap=edit_recap(v,rows,rate),revision=(request.form.get("revision") if request.method=="POST" and request.form.get("revision") is not None else i["revision"]),
                        project_rate=float(i["rate"] or 0),new_uid=secrets.token_urlsafe(9),status=200)
@APP.route("/invoice/<int:iid>/edit",methods=["GET","POST"])
@login_required
def invoice_edit(iid):
 with db() as c:
  i=c.execute("SELECT i.*,p.name project,p.rate,p.day_hours FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id=?",(iid,)).fetchone()
  if not i: abort(404)
  if i["status"]!="draft": flash("Seul un brouillon peut être modifié. Une facture émise se corrige par une note de crédit."); return back("archive")
  hist=date_history(c,iid)
  if request.method=="POST":
   rows=manual_lines.from_form(request.form)
   # « Ajouter une ligne » / « Supprimer » work without JavaScript: they show the form again (nothing is written) with the row added or removed
   if request.form.get("add_line"):
    if len(rows)>=pdf_layout.MAX_MANUAL_LINES: flash(f"{pdf_layout.MAX_MANUAL_LINES} lignes manuelles au maximum sur la page 1 de la facture.")
    else: rows.append(manual_lines.blank_row(secrets.token_urlsafe(9)))
    return render_edit(c,i,iid,edit_view(i,request.form),rows,hist)
   if request.form.get("remove_line"):
    key=request.form.get("remove_line"); rows=[r for r in rows if key not in (r["line_id"],r["line_uid"])]
    return render_edit(c,i,iid,edit_view(i,request.form),rows,hist)
   try:
    v=draft_values(c,request.form,i["project_id"])
    want=float(i["rate"] or 0) if v["unit"]=="day" else float(i["rate"] or 0)/(i["day_hours"] or 8)
    # rc11 (QA-02): an edit keeps the draft's rate; G4 (R-PO-B2): except a rate of 0, never issuable, once the mandate has one (draft n°1, D5 c)
    v["unit_rate"]=float(i["unit_rate"]) if v["unit"]==i["unit"] and not (float(i["unit_rate"])<=0<want) else want
    exc=rules.exception_mandate(c.execute("SELECT * FROM projects WHERE id=?",(i["project_id"],)).fetchone())
    override=typed_rate(exc,request.form)      # rc41: the one place where a draft rate may differ from the mandate's, and only on an exception mandate
    if override is not None: v["unit_rate"]=override
    v["vat"]=num_field(request.form.get("vat"),"taux de TVA",0.0,100.0,default=float(i["vat"]))
    empty_description=not v["description"]
    v["description"]=v["description"] or i["project"]
    lines=manual_lines.validate(rows,v["unit"])
    # rc37 (P2): the address choice is COPIED into the draft at the first save that carries a choice (D8) ; a form without the field (old script) leaves the draft as it is
    chosen=None
    if "billing_address_id" in request.form:
     proj=c.execute("SELECT * FROM projects WHERE id=?",(i["project_id"],)).fetchone(); want_id=request.form.get("billing_address_id") or ""
     if want_id!=str(i["billing_address_id"] or "") or (want_id and request.form.get("refresh_address")):
      chosen=addresses.choose(c,i,proj,want_id); v.update(chosen)
      if chosen["bill_address"] and pdf_layout.block_rows(chosen["bill_contact"],chosen["bill_address"])>pdf_layout.BILLING_MAX_ROWS: raise ValueError("adresse trop longue pour le bloc de facturation du document imprimé : choisir une adresse plus courte")
    # rc37 (P3): the number of the draft. Typed number = manual (never replaced automatically), unique among every invoice (case and spaces ignored), the historical invoices and the
    # external numbers; a conflict is explained and a free number only PROPOSED. Blank = back to the automatic proposal. An automatic number follows the year of the invoice date.
    c.execute("BEGIN IMMEDIATE")      # the checks of the number and the write are one step: two saves cannot take the same number
    yr=number_year(v["invoice_date"]); cur=i["number"]; manual=bool(i["number_manual"]); newnum,newman=cur,manual
    typed=request.form.get("number")
    if typed is not None:
     typed=typed.strip()
     if typed=="" or (cur is None and typed==(request.form.get("number_proposed") or "")):
      newnum,newman=rules.propose_invoice_number(c,yr,exclude_id=iid),False
     elif typed!=(cur or ""):
      newnum,newman=rules.check_invoice_number(typed),True
      why=number_refusal(c,newnum,iid,yr)
      if why: raise ValueError(why[0].upper()+why[1:])
    if cur is not None and not newman and (rules.parse_number(newnum) or (0,))[0]!=yr: newnum=rules.propose_invoice_number(c,yr,exclude_id=iid)     # the year of the date changed
    if newnum!=cur: v["number"]=newnum
    if newman!=manual or newnum!=cur: v["number_manual"]=1 if newman else 0
    off=credits.offsets_total_on(c,iid); new_ttc=rules.amounts(v["qty"],v["unit_rate"],v["vat"],v["other_amount"],v["other_vat_mode"],lines)["ttc"]
    if off>new_ttc: raise ValueError(f"des notes de crédit sont imputées sur ce brouillon pour {fr_chf(off)} ; le nouveau total ({fr_chf(new_ttc)}) serait inférieur — annuler d'abord une imputation")
    seen=request.form.get("revision")
    # the whole save is one transaction (the connection of this request): a stale tab cannot overwrite a newer save, a failure leaves the draft untouched
    if seen is not None and seen!=str(i["revision"]): raise ValueError("ce brouillon a été modifié depuis l'ouverture de cette page (autre onglet ?) : rouvrir le brouillon pour voir sa dernière version ; rien n'a été enregistré")
    n=c.execute(f"UPDATE invoices SET {','.join(k+'=?' for k in v)},revision=revision+1 WHERE id=? AND status='draft' AND revision=?",(*v.values(),iid,i["revision"])).rowcount
    if n!=1: raise ValueError("brouillon introuvable ou modifié entre-temps : rouvrir le brouillon")
    ins,upd,gone=manual_lines.save(c,iid,lines)
    record_number_change(c,iid,cur,newnum,newman,"modification du brouillon")
    if chosen is not None: c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("draft_billing_address_set",f"id={iid};address_id={chosen['billing_address_id']};label={chosen['bill_label']};refresh={'yes' if request.form.get('refresh_address') else 'no'}"))
    record_date_change(c,iid,i["invoice_date"],v["invoice_date"],"modification du brouillon")
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("draft_updated",f"id={iid};qty={v['qty']};manual_lines={len(lines)};lines_added={ins};lines_changed={upd};lines_removed={gone}"))
    if override is not None and abs(override-float(i["unit_rate"]))>1e-9:
     c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("draft_rate_changed",json.dumps({"invoice_id":iid,"number":newnum,"mandate":i["project"],"unit":v["unit"],"old_rate":float(i["unit_rate"]),"new_rate":override,
               "by":SEC["user"],"at":rules.utc_now().isoformat(timespec="seconds"),"exception":rules.EXCEPTION_LABEL},ensure_ascii=False)))
     flash(f"Tarif du brouillon modifié ({rules.EXCEPTION_LABEL}) : {fr_chf(override)} par {'jour' if v['unit']=='day' else 'heure'} (il était de {fr_chf(float(i['unit_rate']))}). Les totaux et le PDF sont calculés avec ce tarif.")
    flash("Brouillon modifié."+(f" {len(lines)} ligne(s) manuelle(s) enregistrée(s)." if lines or gone else "")+(f" Adresse de facturation : {chosen['bill_label']}." if chosen and chosen["bill_label"] else " Adresse de facturation : celle de la fiche du mandat." if chosen is not None else "")+(f" Numéro de facture {'saisi' if newman and newnum!=cur else 'proposé'} : {newnum}." if newnum!=cur else ""))
    if empty_description: flash(f"Description vide : le nom du mandat (« {i['project']} ») sera imprimé à sa place.")
    if v["other_label"] and not v["other_amount"]: flash("Le libellé « AUTRES » n'est imprimé que si un montant est saisi : avec un montant nul, la facture affiche « AUTRES » seul. Saisir le montant, ou ajouter une ligne manuelle.")
    po_warning(c,c.execute("SELECT * FROM projects WHERE id=?",(i["project_id"],)).fetchone())
    if override is None and v["unit"]==i["unit"] and abs(v["unit_rate"]-float(i["unit_rate"]))>1e-9:
     flash(f"Tarif du brouillon repris du mandat : {fr_chf(v['unit_rate'])} par {'jour' if v['unit']=='day' else 'heure'} (il était de {fr_chf(float(i['unit_rate']))}).")
    return back("archive")
   except Exception as e:
    c.rollback()      # nothing of a refused save stays (the draft row may already have been updated when a line is refused)
    flash("Brouillon non modifié : "+str(e)); return render_edit(c,i,iid,edit_view(i,request.form),rows,hist)
  return render_edit(c,i,iid,edit_view(i),manual_lines.as_form_rows(rules.invoice_lines(c,iid)),hist)
@APP.route("/invoice/<int:iid>/preview",methods=["POST"])
@login_required
def invoice_preview(iid):
 """P1: totals of the draft as typed in the editor, computed on the server by the same function as the PDF (never in the browser). Writes nothing."""
 with db() as c:
  i=c.execute("SELECT i.*,p.rate,p.day_hours FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id=?",(iid,)).fetchone()
  if not i or i["status"]!="draft": abort(404)
  try: typed=typed_rate(rules.exception_mandate(c.execute("SELECT * FROM projects WHERE id=?",(i["project_id"],)).fetchone()),request.form)
  except ValueError as e: return jsonify(ok=False,error=str(e))
  v=edit_view(i,request.form); r=edit_recap(v,manual_lines.from_form(request.form),typed if typed is not None else edit_rate(i,v.get("unit")))
 if r["a"] is None: return jsonify(ok=False,error=r["error"])
 a=r["a"]; f=lambda d: fr_chf(d)
 return jsonify(ok=True,service=f(a["ht"]),lines=[f(l["amount"]) for l in r["lines"]],subtotal=f(a["subtotal"]),vat=f(a["tva"]),other=f(a["other"]),total=f(a["ttc"]))
@APP.route("/invoice/<int:iid>/delete",methods=["POST"])
@login_required
def invoice_delete(iid):
 c=db(autocommit=True)
 try:
  c.execute("BEGIN IMMEDIATE")
  st=c.execute("SELECT status,number FROM invoices WHERE id=?",(iid,)).fetchone()
  released=credits.release_draft_offsets(c,iid,"brouillon de facture supprimé : imputation libérée") if st and st["status"]=="draft" else 0
  nl=c.execute("DELETE FROM invoice_lines WHERE invoice_id=? AND invoice_id IN (SELECT id FROM invoices WHERE id=? AND status='draft')",(iid,iid)).rowcount   # rc37: the manual lines go with their draft
  n=c.execute("DELETE FROM invoices WHERE id=? AND status='draft'",(iid,)).rowcount
  if n: c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("draft_deleted",f"id={iid};number_released={st['number'] if st else None};offsets_released={released};manual_lines_deleted={nl}"))
  c.execute("COMMIT")
 except Exception:
  c.execute("ROLLBACK"); raise
 finally: c.close()
 flash(("Brouillon supprimé."+(f" {released} imputation(s) de note de crédit libérée(s) ; le solde redevient disponible." if released else "")) if n else "Suppression refusée : seul un brouillon non émis peut être supprimé.")
 return back("archive")

# --- issuance with explicit reliquat decision ---------------------------------------------------
def issue_number(c,i):
 """Number the invoice will carry once issued (rc37, P3): the one its draft reserved; when the draft has none (created before rc37) or when an AUTOMATIC number is not of the year of the
 printed date, the first free number of that year. A number typed by the user is kept as typed."""
 year=int((i["invoice_date"] or rules.local_today().isoformat())[:4]); cur=i["number"]
 if cur and (i["number_manual"] or (rules.parse_number(cur) or (0,))[0]==year): return cur
 return rules.propose_invoice_number(c,year,exclude_id=i["id"])
def issue_context(c,iid):
 i=c.execute("SELECT i.*,p.name project FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id=?",(iid,)).fetchone()
 if not i: abort(404)
 p=c.execute("SELECT * FROM projects WHERE id=?",(i["project_id"],)).fetchone()
 pos=rules.contract(c,p,upto=i["period_to"],exclude_invoice=iid,historical_upto=i["invoice_date"] or rules.local_today().isoformat(),through=i["period_to"])   # G4: historical invoices dated up to the printed date; rc25: invoices of later periods do not weigh on this reliquat
 this=rules.days(i["qty"],i["unit"],p["day_hours"])
 reliquat=round(pos["consumed_days"]-pos["billed_through_days"]-pos["offered_through_days"]-this,5)
 return {"i":i,"p":p,"pos":pos,"this_days":this,"reliquat":reliquat,"number":issue_number(c,i),
         "missing":rules.missing_for_issue(rules.get_settings(c),dict(p,billing_address=addresses.effective(i,p)[2]),i["vat"]),"amounts":rules.invoice_amounts_full(c,i),"manual_lines":rules.invoice_lines(c,iid),"lines_block":rules.manual_lines_issuance_problem(c,iid),
         "checks":(chk:=invoice_checks.run_checks(c,iid)),"check_failed":invoice_checks.failures(chk),"check_blocking":invoice_checks.blocking(chk),"min_reason":invoice_checks.MIN_REASON,
         "date_problem":rules.issue_date_problem(i,rules.local_today()),"printed_date":i["invoice_date"] or rules.local_today().isoformat(),"date_hist":date_history(c,iid),
         "backdated":rules.is_backdated(i,rules.local_today()),"today":rules.local_today().isoformat(),
         "offsets":credits.active_offsets_on(c,iid),
         "po_over":bool(pos["ordered_days"]) and pos["po_balance_days"]-this<-1e-9,
         "later_issued":c.execute("SELECT number FROM invoices WHERE project_id=? AND status='issued' AND period_to>? ORDER BY period_to LIMIT 1",(i["project_id"],i["period_to"])).fetchone(),
         "variances":[v for v in (post_billing.invoice_variance(c,x) for x in c.execute("SELECT * FROM invoices WHERE project_id=? AND status='issued' AND id IN (%s) ORDER BY id"
                      % ",".join(str(int(k)) for k in post_billing.variance_candidates(c) or [0]),(i["project_id"],)).fetchall()) if v and v["changed"]]}
@APP.route("/issue/<int:iid>",methods=["GET"])
@login_required
def issue_confirm(iid):
 with db() as c: ctx=issue_context(c,iid)
 if ctx["i"]["status"]!="draft": flash("Facture déjà émise."); return back("archive")
 return render_template("issue_confirm.html",treatments=rules.TREATMENTS,**ctx)
@APP.route("/issue/<int:iid>",methods=["POST"])
@login_required
def issue(iid):
 # Numbering, reliquat decision, status change and annex/PDF freeze happen in one transaction.
 c=db(autocommit=True)
 try:
  c.execute("BEGIN IMMEDIATE")
  if not c.execute("SELECT 1 FROM invoices WHERE id=?",(iid,)).fetchone(): raise ValueError("ce brouillon n'existe plus (supprimé depuis un autre onglet ?)")
  ctx=issue_context(c,iid); i=ctx["i"]
  if i["status"]!="draft": raise ValueError("facture déjà émise")
  if ctx["lines_block"]: raise ValueError(ctx["lines_block"])   # rc38: draft with manual lines allowed, issuance suspended until the credit notes on these lines are in service
  if ctx["missing"]: raise ValueError("champs à compléter avant émission : "+", ".join(ctx["missing"]))
  clash=credits.period_clash(c,i["project_id"],i["period_from"],i["period_to"],exclude_id=iid)
  if clash: raise ValueError(f"la période chevauche la facture déjà émise {clash['number']} : modifier la période ou supprimer ce brouillon")
  derog=invoice_checks.derogations(ctx["checks"],request.form)   # G4/D8: strict; only 12 and 13 may be overridden, each with a written reason
  gaps=invoice_checks.exception_gaps(ctx["checks"])   # rc41: empty for every mandate but an exception mandate
  if ctx["date_problem"]: raise ValueError(ctx["date_problem"])
  if not pdf_layout.block_fits(invoice_service.live_data(c,iid)[0]): raise ValueError("adresse trop longue pour le document imprimé (bloc émetteur ou facturation) : la raccourcir dans les paramètres ou la fiche du mandat")
  if ctx["amounts"]["ttc"]<=0: raise ValueError("le total de la facture est nul ou négatif : modifier le brouillon (quantité, montant « autres »)")
  seen=request.form.get("expected_reliquat")
  if seen is not None and abs(float(seen)-ctx["reliquat"])>1e-6: raise ValueError("la position du mandat a changé depuis l'affichage ; vérifier le reliquat")
  treatment=request.form.get("reliquat_treatment",""); note=(request.form.get("reliquat_note") or "").strip()
  if abs(ctx["reliquat"])<1e-6: treatment,note="aucun",""
  else:
   if treatment not in rules.TREATMENTS: raise ValueError(f"choisir le traitement du reliquat de {fr_g(ctx['reliquat'])} j (offert, reporté ou autre)")
   if treatment=="offert" and ctx["reliquat"]<0: raise ValueError("un reliquat négatif (facturé d'avance) ne peut pas être offert")
   if treatment=="autre" and not note: raise ValueError("préciser le traitement « autre »")
  number=ctx["number"]; now=rules.utc_now(); today=rules.local_today()  # RC8: issued_at UTC, business day Zurich
  seen_no=request.form.get("expected_number")
  if seen_no is not None and seen_no!=number: raise ValueError(f"le numéro de facture a changé depuis l'affichage ({seen_no} → {number}) ; vérifier le numéro")
  why=number_refusal(c,number,iid,int((i["invoice_date"] or today.isoformat())[:4]))      # held by another invoice, a historical invoice added since, an external number
  if why: raise ValueError(why[0].upper()+why[1:]+" : modifier le numéro du brouillon avant d'émettre")
  inv_date=rules.issue_date(i,today)
  seen_date=request.form.get("expected_invoice_date")
  if seen_date is not None and seen_date!=inv_date: raise ValueError("la date de facture a changé depuis l'affichage ; vérifier la date")
  # A6 (rc7): a date earlier than the real issuance day is allowed without any day limit, but only with an explicit confirmation
  backdated=rules.is_backdated(i,today)
  if backdated and request.form.get("confirm_backdate")!=inv_date:
   raise ValueError(f"date de facture {rules.fr_date(inv_date)} antérieure à la date réelle d'émission ({rules.fr_date(today.isoformat())}) : cocher la confirmation explicite de l'antidatage")
  try:
   c.execute("UPDATE invoices SET number=?,status='issued',issued_at=?,invoice_date=?,reliquat_days=?,reliquat_treatment=?,reliquat_note=? WHERE id=? AND status='draft'",
             (number,now.isoformat(timespec="seconds"),inv_date,ctx["reliquat"],treatment,note,iid))
  except sqlite3.IntegrityError as e: raise ValueError(f"le numéro {number} vient d'être pris ({e}) : modifier le numéro du brouillon (numéro libre proposé : {number_hint(c,iid,number_year(inv_date))})")
  record_number_change(c,iid,i["number"],number,bool(i["number_manual"]),"émission")
  n=invoice_service.freeze(c,iid,"issue")
  c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("invoice_issued",f"{number};invoice_date={inv_date};issued_at={now.isoformat(timespec='seconds')};backdated={'confirmed' if backdated else 'no'};annex_entries={n};reliquat={ctx['reliquat']};treatment={treatment};derogations={','.join(str(k) for k in sorted(derog)) or 'none'}"+(f";{rules.EXCEPTION_LABEL}=yes;exception_gaps={','.join(str(x['n']) for x in gaps) or 'none'}" if rules.exception_mandate(ctx["p"]) else "")))
  for x in ctx["check_failed"]:   # D8: reason, author, date and the exact anomaly overridden; printed nowhere
   c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("invoice_check_derogation",json.dumps({"invoice_id":iid,"number":number,"check":x["n"],"title":x["title"],"anomaly":x["detail"],
             "reason":derog[x["n"]],"by":SEC["user"],"at":now.isoformat(timespec="seconds")},ensure_ascii=False)))
  for x in gaps:   # rc41: the gaps of an exception mandate do not block, but each is kept with the exact anomaly, the author and the mention « exception STC GEM »
   c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("invoice_check_exception",json.dumps({"invoice_id":iid,"number":number,"check":x["n"],"title":x["title"],"anomaly":x["detail"],
             "exception":rules.EXCEPTION_LABEL,"mandate":ctx["p"]["name"],"by":SEC["user"],"at":now.isoformat(timespec="seconds")},ensure_ascii=False)))
  for o in credits.active_offsets_on(c,iid):
   c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("credit_offset_applied",f"{o['reference']};op={o['id']};amount={o['amount']};invoice={number}"))
  c.execute("COMMIT"); flash(f"Facture {number} émise le {rules.fr_ts(now.isoformat(timespec='seconds'))}"+(f", datée du {rules.fr_date(inv_date)} (antidatage confirmé)." if backdated else "."))
 except Exception as e:
  c.execute("ROLLBACK"); flash("Émission refusée : "+str(e))
  if request.form.get("from_confirm"): return redirect(url_for("issue_confirm",iid=iid))
 finally: c.close()
 return back("archive")
@APP.route("/invoice/<int:iid>.pdf")
@login_required
def pdf(iid):
 with db() as c:
  status=c.execute("SELECT status FROM invoices WHERE id=?",(iid,)).fetchone()
  if not status:return "Not found",404
  if status["status"]=="issued":
   # Issued invoices are never re-rendered: serve the bytes frozen at issuance.
   number,data=invoice_service.frozen_pdf(c,iid)
   if data is None:return "Facture émise sans PDF figé : émission à reprendre par un mécanisme de correction.",409
   return send_file(io.BytesIO(data),mimetype="application/pdf",as_attachment=True,download_name=f"facture-{_safe_name(number)}.pdf")
  data,_=invoice_service.render(c,iid)
 return send_file(io.BytesIO(data),mimetype="application/pdf",as_attachment=True,download_name="facture-brouillon.pdf")

# --- credit notes (separate documents; the original invoice is never touched) ----------------------
def credit_note_lines_save(c,cid,inv,line_amts):
 """rc38: the rows of the manual lines credited by the draft note cid (description and VAT regime copied from the invoice line). The caller owns the transaction."""
 now=rules.utc_now_iso()
 for ln in rules.invoice_lines(c,inv["id"]):
  if ln["id"] in line_amts:
   c.execute("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,position,description,amount,vat_mode,created_at) VALUES(?,?,?,?,?,?,?)",
             (cid,ln["id"],ln["position"],ln["description"],float(line_amts[ln["id"]]),ln["vat_mode"],now))
def credit_page_problem(c,cid):
 """rc38: why the document of the credit note cid would not fit on its page (None = fits). Same measure as the check 11 of an invoice: a dry rendering of page 1."""
 h=invoice_service.credit_data(c,cid)
 low=pdf_layout.credit_page_bottom(h)
 if low>pdf_layout.PAGE_ONE_LIMIT: return f"la note de crédit ne tient pas sur une page ({low:.0f} pt pour {pdf_layout.PAGE_ONE_LIMIT:.0f} pt au plus) : créditer moins de lignes à la fois (plusieurs notes) ou raccourcir le motif"
 return None
def credit_values(c,inv,form,exclude=None):
 reason=(form.get("reason") or "").strip(); desc=_checked_description(form.get("description"),pdf_layout.MAX_DESCRIPTION_LINES)
 if not reason: raise ValueError("motif obligatoire")
 treatment=form.get("treatment","")
 if treatment not in credits.TREATMENTS: raise ValueError("choisir le mode de traitement : remboursement ou compensation")
 ovm=rules.other_vat_mode(inv["other_vat_mode"])  # a credit mirrors the original invoice's AUTRES VAT treatment
 if form.get("scope")=="total":
  # Total credit = everything still creditable on both lines. Service line in days at the invoiced rate
  # when not yet credited by amount, so the mandate's billed days are reversed too.
  k=credits.creditable(c,inv,exclude)
  if k["remaining_ht"]<=0: raise ValueError("cette facture est déjà entièrement créditée")
  amount_only=c.execute("""SELECT COUNT(*) FROM credit_notes WHERE invoice_id=? AND qty IS NULL AND amount>0 AND status IN ('draft','issued') AND id IS NOT ?
                           AND id NOT IN (SELECT credit_note_id FROM credit_note_cancellations)""",(inv["id"],exclude)).fetchone()[0]
  other=float(k["remaining_other"])
  line_amts={l["id"]:l["remaining"] for l in k["lines"] if l["remaining"]>0}   # rc38: a total credit takes what is left of every manual line
  if k["remaining_service"]<=0: qty,rate,amount=0,None,0
  # days kept for the mandate position, HT = the exact creditable balance (remaining days × rate may differ by a cent)
  elif not amount_only and k["remaining_qty"]>0: qty,rate,amount=k["remaining_qty"],inv["unit_rate"],float(k["remaining_service"])
  else: qty,rate,amount=0,None,float(k["remaining_service"])
 else:
  qty=num_field(form.get("qty"),"quantité de jours",0.0,MAX_DAYS,default=0.0); amount=money_field(form.get("amount"),"montant"); other=money_field(form.get("other_amount"),"montant « AUTRES » crédité")
  if qty<0 or amount<0 or other<0: raise ValueError("valeurs négatives refusées")
  if qty>0 and amount>0: raise ValueError("prestation : indiquer soit une quantité de jours, soit un montant HT (l'un des deux)")
  line_amts={}                                                       # rc38: one HT amount per manual line (field cl_<id>), empty = not credited
  for l in credits.creditable(c,inv,exclude)["lines"]:
   raw=(form.get(f"cl_{l['id']}") or "").strip()
   if not raw: continue
   v=money_field(raw,f"montant crédité de la ligne {l['position']}")
   if v<0: raise ValueError("valeurs négatives refusées")
   if v>0: line_amts[l["id"]]=Decimal(str(v))
  if not (qty>0 or amount>0 or other>0 or line_amts): raise ValueError("indiquer des jours, un montant HT de prestation, un montant « AUTRES » ou un montant sur une ligne manuelle à créditer")
  if other>0 and not inv["other_amount"]: raise ValueError("la facture d'origine ne comporte pas de ligne « AUTRES »")
  rate=num_field(form.get("unit_rate"),"tarif",0.0,MAX_MONEY,lo_open=True,default=float(inv["unit_rate"])) if qty>0 else None
  if rate is not None and abs(rate-float(inv["unit_rate"]))>1e-9: raise ValueError(f"le tarif de la note de crédit ({fr_g(rate)}) doit être celui de la facture d'origine ({fr_g(float(inv['unit_rate']))}) ; pour un autre montant, créditer un montant HT")
 if qty>0 and not amount: amount=float(rules.amounts(qty,rate,0)["ht"])
 mode_of={l["id"]:l["vat_mode"] for l in credits.creditable(c,inv,exclude)["lines"]}
 lt=sum((v for i,v in line_amts.items() if mode_of.get(i)=="soumis"),Decimal(0)); lu=sum((v for i,v in line_amts.items() if mode_of.get(i)=="hors_tva"),Decimal(0))
 a=rules.amounts(1,amount,inv["vat"],other,ovm,[{"qty":1,"unit_rate":x,"vat_mode":m} for x,m in ((lt,"soumis"),(lu,"hors_tva")) if x])
 tva=credits.closing_vat(c,inv,a,inv["vat"],exclude)
 if tva is not None: a["tva"]=tva; a["ttc"]=a["ht"]+a["lines_ht"]+tva+a["other"]
 credits.check_creditable(c,inv,qty if qty>0 else 0,a,exclude,line_amts)
 delay=credits.parse_delay(form.get("refund_delay_days")) if treatment=="remboursement" else None
 replaces=None
 if form.get("replaces_credit_id"):
  replaces=int(form.get("replaces_credit_id"))
  if replaces not in [r["id"] for r in credits.replaceable(c,inv["id"])]: raise ValueError("la note remplacée doit être une note annulée de cette facture, non encore remplacée")
 return {"reason":reason,"description":desc or f"Note de crédit sur facture {inv['number']}","qty":qty if qty>0 else None,"unit_rate":rate,"amount":float(a["ht"]),
         "other_amount":float(a["other"]),"other_vat_mode":ovm,"vat":inv["vat"],"treatment":treatment,"tva_amount":None if tva is None else float(tva),
         "refund_delay_days":delay,"replaces_credit_id":replaces,"lines_taxed":float(lt),"lines_untaxed":float(lu),"_lines":line_amts}
@APP.route("/invoice/<int:iid>/ecart")
@login_required
def invoice_variance_page(iid):
 """rc19: post-invoicing variance of one issued invoice (frozen billed entries vs their current values). Read-only: the invoice is
 never changed; the user decides afterwards (credit note, compensation, or nothing)."""
 with db() as c:
  inv=c.execute("SELECT i.*,p.name project,p.active project_active FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id=?",(iid,)).fetchone()
  if not inv: abort(404)
  if inv["status"]!="issued": flash("Un écart post-facturation ne concerne qu'une facture émise."); return back("archive")
  v=post_billing.invoice_variance(c,inv)
  if not v: flash("Facture émise sans copie figée : écart non calculable."); return back("archive")
  compensation_ok=bool(rules.legal_key(credits.legal_identity(c,iid)[1]))   # an offset needs the client's legal id frozen on F
 credit_qty=None
 if v["changed"] and v["remaining_days"]<-post_billing.EPS:   # billed more than the corrected entries: a credit note can balance it
  credit_qty=round(-v["remaining_units"],6)
 return render_template("invoice_variance.html",inv=inv,v=v,credit_qty=credit_qty,compensation_ok=compensation_ok,max_reason=MAX_REASON,treatments=rules.TREATMENTS,
                        unit_label={"day":"j","hour":"h"}.get(inv["unit"],inv["unit"]))
@APP.route("/invoice/<int:iid>/ecart/decision",methods=["POST"])
@login_required
def invoice_variance_decision(iid):
 """rc19: the user's decision on the CURRENT post-invoicing variance of an issued invoice, append-only (credit note issued on that
 invoice, compensation, or no action). Refused when the variance changed since the page was shown (fingerprint)."""
 c=db(autocommit=True)
 try:
  c.execute("BEGIN IMMEDIATE")
  inv=c.execute("SELECT * FROM invoices WHERE id=?",(iid,)).fetchone()
  if not inv: abort(404)
  v=post_billing.invoice_variance(c,inv)
  if not v or not v["changed"]: raise ValueError("aucune saisie facturée n'a changé depuis l'émission : rien à décider")
  if request.form.get("fingerprint")!=v["fingerprint"]: raise ValueError("l'écart a changé depuis l'affichage de la page (autre correction) : vérifier puis décider de nouveau")
  decision=request.form.get("decision","")
  if decision not in ("avoir","compensation","aucune"): raise ValueError("choisir une décision : note de crédit, compensation ou aucune action")
  reason=change_reason(request.form.get("reason")); cid=None
  if decision=="avoir":
   try: cid=int(request.form.get("credit_note_id") or 0)
   except ValueError: cid=0
   if not any(n["id"]==cid for n in v["credit_notes"]): raise ValueError("choisir la note de crédit émise sur cette facture qui traite l'écart (la créer puis l'émettre d'abord)")
  elif not reason: raise ValueError("motif obligatoire pour une compensation ou l'absence d'action (ex. « déduit de la facture suivante », « écart accepté »)")
  c.execute("INSERT INTO invoice_variance_decisions(invoice_id,decision,credit_note_id,variance_hours,fingerprint,reason,actor,decided_at) VALUES(?,?,?,?,?,?,?,?)",
            (iid,decision,cid,v["variance_hours"],v["fingerprint"],reason,SEC["user"],rules.utc_now_iso()))
  c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("variance_decision_recorded",json.dumps({"invoice":inv["number"],"decision":decision,"credit_note":cid,
            "variance_hours":v["variance_hours"],"fingerprint":v["fingerprint"],"by":SEC["user"],"reason":reason},ensure_ascii=False)))
  c.execute("COMMIT")
  flash(f"Décision enregistrée pour l'écart post-facturation de la facture {inv['number']} ({ {'avoir':'note de crédit','compensation':'compensation','aucune':'aucune action'}[decision] }). La facture émise reste inchangée.")
 except HTTPException:
  c.execute("ROLLBACK"); raise
 except Exception as e:
  c.execute("ROLLBACK"); refused("Décision non enregistrée : "+str(e))
 finally: c.close()
 return redirect(url_for("invoice_variance_page",iid=iid))
@APP.route("/invoice/<int:iid>/credit",methods=["GET","POST"])
@login_required
def credit_new(iid):
 if request.method=="POST":
  # check-then-insert under BEGIN IMMEDIATE: two concurrent notes cannot both pass the creditable check
  c=db(autocommit=True)
  try:
   c.execute("BEGIN IMMEDIATE")
   inv=c.execute("SELECT * FROM invoices WHERE id=?",(iid,)).fetchone()
   if not inv: abort(404)
   if inv["status"]!="issued": raise LookupError
   v=credit_values(c,inv,request.form); v["invoice_id"]=iid; line_amts=v.pop("_lines")
   cid=c.execute(f"INSERT INTO credit_notes({','.join(v)}) VALUES({','.join('?'*len(v))})",tuple(v.values())).lastrowid
   credit_note_lines_save(c,cid,inv,line_amts)
   why=credit_page_problem(c,cid)
   if why: raise ValueError(why)
   c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("credit_draft_created",f"invoice={inv['number']};ht={v['amount']};other={v['other_amount']};lines_taxed={v['lines_taxed']};lines_untaxed={v['lines_untaxed']};credited_lines={len(line_amts)};qty={v['qty']};treatment={v['treatment']};scope={request.form.get('scope','partial')};refund_delay_days={v['refund_delay_days']};replaces={v['replaces_credit_id']}"))
   c.execute("COMMIT"); flash("Brouillon de note de crédit créé. La facture d'origine reste inchangée."); return back("archive")
  except HTTPException:
   c.execute("ROLLBACK"); raise
  except LookupError:
   c.execute("ROLLBACK"); flash("Une note de crédit se rattache uniquement à une facture émise."); return back("archive")
  except Exception as e:
   c.execute("ROLLBACK"); refused("Note de crédit non créée : "+str(e))
  finally: c.close()
 with db() as c:
  inv=c.execute("SELECT i.*,p.name project FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id=?",(iid,)).fetchone()
  if not inv: abort(404)
  if inv["status"]!="issued": flash("Une note de crédit se rattache uniquement à une facture émise."); return back("archive")
  invoiced=credits.inv_amounts(c,inv)   # rc38: with the manual lines
  k=credits.creditable(c,inv); repl=credits.replaceable(c,iid); default_delay=rules.get_settings(c).get("refund_delay_days","")
  total_block=credits.total_credit_blockers(c,inv)
  # rc19: « Créer une note de crédit » from the post-invoicing variance page (?ecart=1): quantity and reason computed here from the
  # current variance (never taken from the link: the reason is printed); the user still checks, chooses the treatment and issues
  prefill={}
  if request.args.get("ecart")=="1":
   v=post_billing.invoice_variance(c,inv)
   if v and v["changed"] and v["remaining_days"]<-post_billing.EPS:
    q=round(-v["remaining_units"],6)
    prefill={"qty":f"{q:.6f}".rstrip("0").rstrip("."),"reason":f"Ajustement des heures facturées sur la facture {inv['number']} (correction des saisies)"}
 return render_template("credit_new.html",inv=inv,k=k,invoiced=invoiced,treatments=credits.TREATMENTS,replaceable=repl,default_delay=default_delay,
                        other_vat_modes=rules.OTHER_VAT_MODES,total_block=total_block,prefill=prefill)
@APP.route("/credit/<int:cid>/issue",methods=["POST"])
@login_required
def credit_issue(cid):
 c=db(autocommit=True)
 try:
  c.execute("BEGIN IMMEDIATE")
  cn=c.execute("SELECT * FROM credit_notes WHERE id=?",(cid,)).fetchone()
  if not cn or cn["status"]!="draft": raise ValueError("brouillon de note de crédit introuvable")
  if cn["treatment"] not in credits.TREATMENTS: raise ValueError("mode de traitement (remboursement ou compensation) non choisi : supprimer et recréer le brouillon")
  inv=c.execute("SELECT * FROM invoices WHERE id=?",(cn["invoice_id"],)).fetchone()
  # VAT balance re-derived at issuance: other drafts may have been deleted since this one was created
  if cn["replaces_credit_id"] and not credits.is_cancelled(c,cn["replaces_credit_id"]): raise ValueError("la note remplacée n'est pas annulée")
  tva=credits.closing_vat(c,inv,credits.credit_amounts(dict(cn,tva_amount=None)),cn["vat"],exclude=cid)
  c.execute("UPDATE credit_notes SET tva_amount=? WHERE id=? AND status='draft'",(None if tva is None else float(tva),cid))
  cn=c.execute("SELECT * FROM credit_notes WHERE id=?",(cid,)).fetchone(); a=credits.credit_amounts(cn)
  credits.check_creditable(c,inv,cn["qty"] or 0,a,exclude=cid,line_amounts={x["invoice_line_id"]:x["amount"] for x in credits.note_lines(c,cid)})
  why=credit_page_problem(c,cid)
  if why: raise ValueError(why)
  ref=rules.next_credit_number(c,inv["number"]); now=rules.utc_now_iso()
  due=credits.due_date(now,cn["refund_delay_days"]) if cn["treatment"]=="remboursement" else None
  c.execute("UPDATE credit_notes SET status='issued',reference=?,issued_at=?,refund_due_on=? WHERE id=? AND status='draft'",(ref,now,due,cid))
  invoice_service.freeze_credit(c,cid)
  c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("credit_note_issued",f"{ref};invoice={inv['number']};ht={cn['amount']};other={cn['other_amount']};lines_taxed={cn['lines_taxed']};lines_untaxed={cn['lines_untaxed']};ttc={a['ttc']};treatment={cn['treatment']};refund_due_on={due};replaces={cn['replaces_credit_id']}"))
  c.execute("COMMIT"); flash(f"Note de crédit {ref} émise (facture {inv['number']} inchangée). Mode : {credits.TREATMENTS[cn['treatment']]}.")
 except Exception as e:
  c.execute("ROLLBACK"); flash("Émission de la note de crédit refusée : "+str(e))
 finally: c.close()
 return back("archive")
@APP.route("/credit/<int:cid>/delete",methods=["POST"])
@login_required
def credit_delete(cid):
 with db() as c:
  c.execute("DELETE FROM credit_note_lines WHERE credit_note_id=? AND credit_note_id IN (SELECT id FROM credit_notes WHERE id=? AND status='draft')",(cid,cid))   # rc38: the rows go with their draft note
  n=c.execute("DELETE FROM credit_notes WHERE id=? AND status='draft'",(cid,)).rowcount
  if n: c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("credit_draft_deleted",f"id={cid}"))
 flash("Brouillon de note de crédit supprimé." if n else "Suppression refusée : seule une note de crédit non émise peut être supprimée.")
 return back("archive")
@APP.route("/credit/<int:cid>")
@login_required
def credit_detail(cid):
 with db() as c:
  cn=c.execute("SELECT * FROM credit_notes WHERE id=?",(cid,)).fetchone()
  if not cn: abort(404)
  inv=c.execute("SELECT i.*,p.name project,p.client FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id=?",(cn["invoice_id"],)).fetchone()
  pos=credits.position(c,cn); hist=credits.history(c,cn)
  targets,targets_why=credits.target_candidates(c,cn) if cn["status"]=="issued" and cn["treatment"]=="compensation" and not pos["cancelled"] else ([],"")
  cancel_why=credits.cancellation_blockers(c,cn)
  replaced_by=c.execute("SELECT id,reference,status FROM credit_notes WHERE replaces_credit_id=?",(cid,)).fetchone()
  replaces=c.execute("SELECT id,reference FROM credit_notes WHERE id=?",(cn["replaces_credit_id"],)).fetchone() if cn["replaces_credit_id"] else None
  ops=pos["operations"]; reversed_ids={o["reverses_id"] for o in ops if o["reverses_id"]}
  frozen={}
  for o in ops:
   if o["kind"]=="offset" and o["id"] not in reversed_ids:
    t=c.execute("SELECT status FROM invoices WHERE id=?",(o["target_invoice_id"],)).fetchone()
    frozen[o["id"]]=bool(t and t["status"]=="issued" and o["id"] in credits.frozen_offset_ids(c,o["target_invoice_id"]))
  k=credits.creditable(c,inv); note_lines=credits.note_lines(c,cid)   # rc38
 return render_template("credit_detail.html",cn=cn,inv=inv,pos=pos,hist=hist,note_lines=note_lines,targets=targets,ops=ops,reversed_ids=reversed_ids,frozen=frozen,k=k,
                        kinds=credits.KIND_LABELS,today=rules.local_today().isoformat(),
                        targets_why=targets_why,cancel_why=cancel_why,replaced_by=replaced_by,replaces=replaces,ovm_labels=rules.OTHER_VAT_MODES)
def credit_op(cid,fn,ok):
 c=db(autocommit=True)
 try:
  c.execute("BEGIN IMMEDIATE"); fn(c); c.execute("COMMIT"); flash(ok)
 except Exception as e:
  c.execute("ROLLBACK"); flash("Opération refusée : "+str(e))
 finally: c.close()
 return redirect(url_for("credit_detail",cid=cid))
@APP.route("/credit/<int:cid>/cancel",methods=["POST"])
@login_required
def credit_cancel(cid):
 return credit_op(cid,lambda c:credits.cancel(c,cid,request.form.get("reason")),
                  "Note de crédit annulée par un document d'annulation figé. Le mode reste inchangé ; la correction passe par une nouvelle note de crédit qui la remplace.")
@APP.route("/credit/<int:cid>/cancellation.pdf")
@login_required
def credit_cancellation_pdf(cid):
 with db() as c: ref,data=invoice_service.frozen_cancellation_pdf(c,cid)
 if data is None: return "Not found",404
 return send_file(io.BytesIO(data),mimetype="application/pdf",as_attachment=True,download_name=f"annulation-{_safe_name(ref)}.pdf")
@APP.route("/credit/<int:cid>/refund",methods=["POST"])
@login_required
def credit_refund(cid):
 f=request.form
 return credit_op(cid,lambda c:credits.record_refund(c,cid,f.get("amount"),f.get("executed_on"),f.get("external_ref"),f.get("note")),"Remboursement enregistré.")
@APP.route("/credit/<int:cid>/offset",methods=["POST"])
@login_required
def credit_offset(cid):
 f=request.form
 return credit_op(cid,lambda c:credits.record_offset(c,cid,f.get("target_invoice_id"),f.get("amount"),f.get("note")),
                  "Imputation enregistrée. Sur un brouillon, elle figurera sur la facture et deviendra définitive à son émission.")
@APP.route("/credit/<int:cid>/reverse/<int:op_id>",methods=["POST"])
@login_required
def credit_reverse(cid,op_id):
 def run(c):
  o=c.execute("SELECT credit_note_id FROM credit_operations WHERE id=?",(op_id,)).fetchone()
  if not o or o[0]!=cid: raise ValueError("opération introuvable pour cette note de crédit")
  credits.reverse(c,op_id,request.form.get("note"),request.form.get("executed_on") or None)
 return credit_op(cid,run,"Opération annulée par une écriture d'annulation (l'opération d'origine reste dans l'historique).")
@APP.route("/credit/<int:cid>.pdf")
@login_required
def credit_pdf(cid):
 with db() as c:
  cn=c.execute("SELECT status FROM credit_notes WHERE id=?",(cid,)).fetchone()
  if not cn: return "Not found",404
  if cn["status"]=="issued":
   ref,data=invoice_service.frozen_credit_pdf(c,cid)
   return send_file(io.BytesIO(data),mimetype="application/pdf",as_attachment=True,download_name=f"note-de-credit-{_safe_name(ref)}.pdf")
  data,_=invoice_service.render_credit(c,cid)
 return send_file(io.BytesIO(data),mimetype="application/pdf",as_attachment=True,download_name="note-de-credit-brouillon.pdf")

# --- archive export (rc10) --------------------------------------------------------------------------
def _safe_name(v): return re.sub(r"[^A-Za-z0-9._-]+","_",str(v or "x")).strip("._") or "x"
@APP.route("/archive.zip")
@login_required
def archive_zip():
 """ZIP of every issued document exactly as frozen at issuance (invoices, credit notes, cancellations) with an index and
 SHA-256 sums, for the accountant or the legal archive. Nothing is regenerated: the stored bytes are checked against
 their stored hash first, and the export is refused (never silently degraded) when one does not match."""
 year=(request.args.get("year") or "").strip()
 if year and not re.fullmatch(r"\d{4}",year): flash("Année invalide (AAAA attendu)."); return back("archive")
 files=[]; index=[["type","numero","date_document","emission_reelle_zurich","mandat","periode_du","periode_au","ht","tva","autres","ttc","statut","sha256_pdf","fichier"]]
 try:
  with db() as c:
   for i in c.execute("""SELECT i.*,p.name project FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.status='issued' ORDER BY i.issued_at,i.id"""):
    doc_date=i["invoice_date"] or rules.local_date(i["issued_at"])
    if year and doc_date[:4]!=year: continue
    number,pdf=invoice_service.frozen_pdf(c,i["id"])
    if pdf is None: raise RuntimeError(f"facture {i['number']} sans copie figée")
    a=rules.invoice_amounts_full(c,i); name=f"factures/facture-{_safe_name(number)}.pdf"; files.append((name,pdf))
    index.append(["facture",number,doc_date,rules.fr_ts(i["issued_at"]),i["project"],i["period_from"],i["period_to"],a["subtotal"],a["tva"],a["other"],a["ttc"],"émise",hashlib.sha256(pdf).hexdigest(),name])
   for n in c.execute("""SELECT cn.*,i.number inv_number,p.name project,p.id pid FROM credit_notes cn JOIN invoices i ON i.id=cn.invoice_id JOIN projects p ON p.id=i.project_id
                         WHERE cn.status='issued' ORDER BY cn.issued_at,cn.id"""):
    doc_date=rules.local_date(n["issued_at"])
    if year and doc_date[:4]!=year: continue
    ref,pdf=invoice_service.frozen_credit_pdf(c,n["id"])
    if pdf is None: raise RuntimeError(f"note de crédit {n['reference']} sans copie figée")
    a=credits.credit_amounts(n); canc=c.execute("SELECT reference FROM credit_note_cancellations WHERE credit_note_id=?",(n["id"],)).fetchone()
    name=f"notes-de-credit/note-de-credit-{_safe_name(ref)}.pdf"; files.append((name,pdf))
    index.append(["note de crédit",ref,doc_date,rules.fr_ts(n["issued_at"]),n["project"],"","",-a["subtotal"],-a["tva"],-a["other"],-a["ttc"],("annulée ("+canc["reference"]+")") if canc else credits.TREATMENTS.get(n["treatment"],""),hashlib.sha256(pdf).hexdigest(),name])
    if canc:
     cref,cpdf=invoice_service.frozen_cancellation_pdf(c,n["id"]); cname=f"annulations/annulation-{_safe_name(cref)}.pdf"; files.append((cname,cpdf))
     index.append(["annulation de note de crédit",cref,rules.local_date(c.execute("SELECT issued_at FROM credit_note_cancellations WHERE credit_note_id=?",(n["id"],)).fetchone()[0]),"",n["project"],"","","","","","","document d'annulation",hashlib.sha256(cpdf).hexdigest(),cname])
 except Exception as e:
  flash("Archive non produite : "+str(e)); return back("archive")
 if year and not files: flash(f"Aucun document émis en {year} : rien à archiver."); return back("archive")   # rc12 (QA-24): no empty ZIP for a year without document
 out=io.StringIO(); w=csv.writer(out,delimiter=";",lineterminator="\r\n")
 for r in index: w.writerow([x if isinstance(x,Decimal) else csv_cell(x) for x in r])  # amounts stay numeric (a leading minus is not a formula); text is neutralised
 readme=(f"Archive des documents émis — Time Billing {VERSION}\r\nGénérée le {rules.fr_ts(rules.utc_now_iso())} (heure de Zurich)\r\nPériode : {year or 'toutes les années'}\r\n"
         f"Documents : {len(files)}\r\n\r\nChaque PDF est la copie figée à l'émission (jamais régénérée). SHA256SUMS permet de les vérifier : sha256sum -c SHA256SUMS\r\n")
 sums="".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n,d in files)
 buf=io.BytesIO()
 with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
  for n,d in files: z.writestr(zipfile.ZipInfo(n,date_time=(2026,1,1,0,0,0)),d,zipfile.ZIP_DEFLATED)
  z.writestr("index.csv","\ufeff"+out.getvalue()); z.writestr("SHA256SUMS",sums); z.writestr("LISEZMOI.txt",readme)
 log("archive_exported",f"year={year or 'all'};documents={len(files)}")
 buf.seek(0); return send_file(buf,mimetype="application/zip",as_attachment=True,download_name=f"archive-documents-emis-{year or 'toutes-annees'}-{rules.local_today().isoformat()}.zip")

# --- issuer settings ----------------------------------------------------------------------------
@APP.route("/settings",methods=["POST"])
@login_required
def settings_save():
 try:
  with db() as c:
   def put(k,v,default=""):
    # rc24 (aller-retour des formulaires) : une valeur inchangée n'est pas réécrite — identique à l'enregistrée, ou clé absente et valeur = celle affichée
    # par défaut ; avant, enregistrer sans rien changer réécrivait l'horodatage des 9 champs et ajoutait 2 options : « paramètres modifiés » pour 90-rollback
    r=c.execute("SELECT value FROM settings WHERE key=?",(k,)).fetchone()
    if (r[0] if r else default)!=v: c.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(k,v))
   for k in rules.ISSUER_FIELDS: put(k,form_text(request.form.get(k)))
   for k in rules.OPTION_FIELDS:
    if k not in request.form: continue  # option fields absent from a partial form keep their value
    v=(request.form.get(k) or "").strip()
    if k=="refund_delay_days": v="" if credits.parse_delay(v,"délai de remboursement par défaut") is None else str(credits.parse_delay(v))
    if k=="other_vat_default" and v not in rules.OTHER_VAT_MODES: raise ValueError("traitement TVA « AUTRES » inconnu")
    put(k,v,"hors_tva" if k=="other_vat_default" else "")   # valeurs par défaut lues ailleurs : other_vat_default absent = hors_tva, délai absent = aucun
   logo=request.files.get("logo")
   if logo and logo.filename:
    data=logo.read()
    if len(data)>1024*1024: raise ValueError("logo trop volumineux (1 Mo max)")
    try:
     from PIL import Image
     im=Image.open(io.BytesIO(data))
     if im.format not in ("PNG","JPEG") or im.width*im.height>4_000_000: raise ValueError   # size read from the header: a decompression bomb is refused before any decoding
     im.verify()
    except Exception: raise ValueError("logo illisible ou trop grand (PNG ou JPEG, 4 mégapixels au maximum)")
    c.execute("INSERT INTO settings(key,value) VALUES('logo_png_b64',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(base64.b64encode(data).decode(),))
   if request.form.get("remove_logo")=="1": c.execute("DELETE FROM settings WHERE key='logo_png_b64'")
   c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("settings_updated","issuer"))
  flash("Paramètres enregistrés. Ils s'appliquent aux prochaines émissions ; les documents émis restent figés.")
 except Exception as e: flash("Paramètres non enregistrés : "+str(e))
 return back("settings")

# --- JSON backup and safe restore ---------------------------------------------------------------
# --- G4: invoices issued outside the application (SUIVI workbook), recorded with their source and validated by the user ----------------------
@APP.route("/historique")
@login_required
def historical_page():
 """Registry of the historical invoices: provenance of each row, proposed / validated / rejected. Only validated rows feed the indicators."""
 flt=request.args.get("statut","")
 with db() as c:
  rows=historical_billing.list_rows(c,flt if flt in historical_billing.STATUSES else None)
  cnt=historical_billing.counts(c); tot=historical_billing.totals_by_project(c)
  per={}; replaced={}
  for r in rows:
   per.setdefault((r["project_id"],r["project"],r["project_active"]),[]).append(r)
   if r["status"]!="validated":   # rc23: a row replaced by a validated correction points to it instead of offering a correction that would be refused
    fam=historical_billing.family(c,r)
    if any(historical_billing.is_manual(x) for x in fam):
     x=next((x for x in fam if x["status"]=="validated" and x["id"]!=r["id"]),None)
     if x: replaced[r["id"]]=x["id"]
 return render_template("historical.html",groups=[(k,v) for k,v in per.items()],counts=cnt,totals=tot,flt=flt,labels=historical_billing.STATUS_LABEL,basis=historical_billing.BASIS_LABEL,
                        manual_file=historical_billing.MANUAL_FILE,label=historical_billing.cell_label,replaced=replaced,
                        active_tab="mandates",max_reason=MAX_REASON)
@APP.route("/historique/<int:hid>/statut",methods=["POST"])
@login_required
def historical_status(hid):
 """Validate / reject one historical invoice (explicit action of the user; rejection needs a reason). The invoice itself is never touched."""
 c=db(autocommit=True)
 try:
  c.execute("BEGIN IMMEDIATE")
  new=request.form.get("statut","")
  project,old=historical_billing.set_status(c,hid,new,SEC["user"],change_reason(request.form.get("motif")))
  c.execute("COMMIT"); flash(f"Facture historique {'validée' if new=='validated' else 'rejetée'} ({project}). Les indicateurs sont recalculés à l'affichage.")
 except LookupError:
  c.execute("ROLLBACK"); abort(404)
 except Exception as e:
  c.execute("ROLLBACK"); flash("Statut non modifié : "+str(e))
 finally: c.close()
 return redirect(url_for("historical_page"))
@APP.route("/historique/mandat/<int:pid>/valider",methods=["POST"])
@login_required
def historical_validate_project(pid):
 """Validate every proposed historical invoice of one mandate in one click (the page lists them first, with their source cells)."""
 c=db(autocommit=True)
 try:
  c.execute("BEGIN IMMEDIATE")
  p=c.execute("SELECT name FROM projects WHERE id=?",(pid,)).fetchone()
  if not p: raise LookupError
  done,kept=historical_billing.validate_project(c,pid,SEC["user"])
  c.execute("COMMIT"); flash(f"{done} facture(s) historique(s) validée(s) pour « {p['name']} »."+(" Non validées : "+" ; ".join(kept) if kept else ""))
 except LookupError:
  c.execute("ROLLBACK"); abort(404)
 except Exception as e:
  c.execute("ROLLBACK"); flash("Validation refusée : "+str(e))
 finally: c.close()
 return redirect(url_for("historical_page"))
def historical_form_values(f):
 """rc23: values of the correction / addition form of a historical invoice (empty days or amount = none)."""
 days=(f.get("qty_days") or "").strip(); amount=(f.get("amount_ht") or "").strip()
 return historical_billing.parse_values(f.get("invoice_date"),num_field(days,"Jours facturés",lo=0.0,lo_open=True) if days else None,
                                        money_field(amount,"Montant HT") if amount else None,f.get("invoice_ref"))
def historical_edit(orig_id=None):
 """rc23 (Decision Center billing-g4-correction-historiques = A): correct a historical invoice by replacement, or add a missing one.
 The values read from the workbook are never rewritten; the replaced row is rejected with its reason, the new row is validated by this gesture."""
 with db() as c:
  orig=None
  if orig_id is not None:
   orig=c.execute("SELECT h.*,p.name project FROM historical_invoices h JOIN projects p ON p.id=h.project_id WHERE h.id=?",(orig_id,)).fetchone()
   if not orig: abort(404)
   orig=dict(orig)
  projects=c.execute("SELECT id,name,active FROM projects ORDER BY active DESC,name").fetchall()
 v=dict(orig) if orig else {}
 if request.method=="POST":
  v={k:request.form.get(k,"") for k in ("project_id","invoice_date","qty_days","amount_ht","invoice_ref","motif","confirm_similar")}
  c=db(autocommit=True)
  try:
   vals=historical_form_values(request.form); reason=change_reason(request.form.get("motif"))
   c.execute("BEGIN IMMEDIATE")
   if orig:
    new,project,warn=historical_billing.correct(c,orig_id,vals,SEC["user"],reason)
    msg=f"Facture historique corrigée ({project}) : la ligne n° {orig_id} est remplacée par la ligne n° {new}, validée. Les indicateurs sont recalculés à l'affichage."
   else:
    try: pid=int(v["project_id"])
    except ValueError: raise ValueError("mandat à choisir")
    new,project,warn=historical_billing.add(c,pid,vals,SEC["user"],reason,confirm_similar=v["confirm_similar"]=="1")
    msg=f"Facture historique ajoutée ({project}) : ligne n° {new}, validée. Les indicateurs sont recalculés à l'affichage."
   c.execute("COMMIT"); flash(msg)
   for w in warn: flash(w)
   return redirect(url_for("historical_page"))
  except LookupError:
   if c.in_transaction: c.execute("ROLLBACK")
   abort(404)
  except Exception as e:
   if c.in_transaction: c.execute("ROLLBACK")
   flash(("Correction non enregistrée : " if orig else "Facture historique non ajoutée : ")+str(e))
  finally: c.close()
 return render_template("historical_edit.html",orig=orig,v=v,projects=projects,labels=historical_billing.STATUS_LABEL,label=historical_billing.cell_label,
                        max_reason=MAX_REASON,max_ref=historical_billing.MAX_REF,active_tab="mandates")
@APP.route("/historique/<int:hid>/corriger",methods=["GET","POST"])
@login_required
def historical_correct(hid): return historical_edit(hid)
@APP.route("/historique/ajouter",methods=["GET","POST"])
@login_required
def historical_add(): return historical_edit()
@APP.route("/backup")
@login_required
def backup():
 # Every table, BLOBs (frozen PDFs) as base64, plus the schema needed to rebuild.
 log("json_backup_exported",rules.utc_now_iso())
 with db() as c:
  names=[r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name") if r["name"] not in restore_service.TRANSIENT]
  tables={t:[{k:(base64.b64encode(v).decode() if isinstance(v,bytes) else v) for k,v in dict(r).items()} for r in c.execute(f"SELECT * FROM {t}")] for t in names}
  schema=[r["sql"] for r in c.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC,name")]
 stamp=rules.utc_now().strftime("%Y%m%dT%H%M%SZ")
 obj={"meta":{"generated_at":rules.utc_now_iso(),"app_version":VERSION,"row_counts":{t:len(v) for t,v in tables.items()},"blob_encoding":"base64","schema":schema},"tables":tables}
 return send_file(io.BytesIO(json.dumps(obj,ensure_ascii=False,indent=2).encode()),mimetype="application/json",as_attachment=True,download_name=f"time-billing-v9-backup-{stamp}.json")
@APP.route("/restore",methods=["POST"])
@login_required
def restore_upload():
 request.max_content_length=1024*1024*1024  # a JSON backup holds every frozen PDF (base64): it outgrows the 15 MB default after ~80 invoices
 f=request.files.get("backup")
 if not f or not f.filename.lower().endswith(".json"): flash("Sélectionner un fichier de sauvegarde .json."); return back("settings")
 raw=f.read()
 try:
  with db() as c: restore_service.validate(c,raw)
 except restore_service.RestoreRefused as e: flash("Restauration impossible : "+str(e)); return back("settings")
 os.makedirs(import_dir(),mode=0o700,exist_ok=True); token=secrets.token_urlsafe(24)
 with open(os.path.join(import_dir(),f"restore-{token}.json"),"wb") as out: out.write(raw)
 log("restore_previewed",f"file={os.path.basename(f.filename)};sha256={hashlib.sha256(raw).hexdigest()}")
 return redirect(url_for("restore_review",token=token))
def restore_file(token):
 if not TOKEN_RE.match(token or ""): abort(404)
 p=os.path.join(import_dir(),f"restore-{token}.json")
 if not os.path.isfile(p): abort(404)
 return p
@APP.route("/restore/<token>")
@login_required
def restore_review(token):
 raw=open(restore_file(token),"rb").read()
 with db() as c: data=restore_service.validate(c,raw); pv=restore_service.preview(c,data)
 return render_template("restore_review.html",token=token,pv=pv,sha=hashlib.sha256(raw).hexdigest())
@APP.route("/restore/<token>",methods=["POST"])
@login_required
def restore_commit(token):
 path=restore_file(token)
 if request.form.get("action")=="cancel":
  os.remove(path); flash("Restauration abandonnée : aucune donnée modifiée."); return back("settings")
 raw=open(path,"rb").read(); tmp=None
 try:
  if request.form.get("confirm")!="RESTAURER": raise restore_service.RestoreRefused("saisir RESTAURER pour confirmer")
  with db() as c: data=restore_service.validate(c,raw); pv=restore_service.preview(c,data)
  if pv["blocking"]: raise restore_service.RestoreRefused("; ".join(pv["blocking"]))
  backup=import_service.sqlite_backup(DB,backup_dir(),"pre-restore")
  tmp=restore_service.temp_path(DB); restore_service.rebuild(tmp,data,init,keep_from=DB)
  kept,appended=restore_service.swap(DB,tmp,data["tables"]["audit"]); tmp=None  # rc25: current audit log kept verbatim, file rows only appended
  with db() as c: c.execute("INSERT INTO audit(event,detail) VALUES(?,?)",("json_restored",f"sha256={hashlib.sha256(raw).hexdigest()};pre_restore_backup={backup[0]};audit_kept={kept};audit_appended={appended}"))
  os.remove(path)
  flash(f"Restauration effectuée. Sauvegarde préalable vérifiée : {backup[0]}.")
  return back("settings")
 except Exception as e:
  flash(f"Restauration refusée, base inchangée : {e}")
  return redirect(url_for("restore_review",token=token))
 finally:
  if tmp and os.path.exists(tmp): os.remove(tmp)

# --- historical import (unchanged from V9.1) -----------------------------------------------------
def stage_path(token):
 if not TOKEN_RE.match(token or ""): abort(404)
 return os.path.join(import_dir(),token+".json")
def load_stage(token):
 path=stage_path(token)
 if not os.path.isfile(path): abort(404)
 with open(path,encoding="utf-8") as src: return json.load(src)
def save_stage(token,payload):
 os.makedirs(import_dir(),mode=0o700,exist_ok=True); path=stage_path(token); tmp=path+".tmp"
 with open(tmp,"w",encoding="utf-8") as out: json.dump(payload,out,ensure_ascii=False)
 os.replace(tmp,path)
def purge_stages(max_age=86400):
 if not os.path.isdir(import_dir()): return
 for n in os.listdir(import_dir()):
  p=os.path.join(import_dir(),n)
  if os.path.isfile(p) and time.time()-os.path.getmtime(p)>max_age: os.remove(p)
@APP.route("/export/classeur.xlsx")
@login_required
def export_workbook():
 """Decision Center billing-gsheet-export-mechanism = DOWNLOADABLE_EXCEL (2026-10-07): the time entries as a .xlsx with the structure of the base
 workbook, imported by hand into Google Sheets; nothing is sent anywhere. billing-gsheet-export-scope = B: plus the SUIVI sheets rebuilt from Billing."""
 from app import gsheet_export
 with db() as c: data,summ=gsheet_export.build(c)
 log("gsheet_export_downloaded",json.dumps({"sheets":len(summ["sheets"]),"entries":summ["entries"],"hours":summ["hours"],"suivi":summ["suivi"]}))
 resp=make_response(data); resp.headers["Content-Type"]="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
 resp.headers["Content-Disposition"]=f'attachment; filename="time-sheet-billing-{rules.local_today().isoformat()}.xlsx"'; return resp
@APP.route("/import",methods=["POST"])
@login_required
def import_file():
 f=request.files.get("workbook")
 if not f or not f.filename.lower().endswith((".xlsx",".xlsm")):
  flash("Sélectionner un classeur .xlsx ou .xlsm."); return back("migration")
 data=f.read(); filename=os.path.basename(f.filename)
 try: parsed=historical_import.parse_workbook(data)
 except historical_import.WorkbookRefused as e:
  flash(str(e)); return back("migration")
 except Exception as e:
  flash(f"Classeur illisible ({type(e).__name__}) : aucun import préparé."); return back("migration")
 if not parsed["rows"]:
  flash("Aucune prestation détectée dans le classeur. Onglets ignorés : "+(", ".join(f"{x['sheet']} ({x['reason']})" for x in parsed["skipped_sheets"]) or "aucun")); return back("migration")
 purge_stages(); token=secrets.token_urlsafe(24)
 save_stage(token,{"filename":filename,"file_sha256":hashlib.sha256(data).hexdigest(),"sheets":parsed["sheets"],"skipped":parsed["skipped_sheets"],"rows":parsed["rows"],"ignored_blank":parsed.get("ignored_blank_rows",{}),
  "project_names":sorted({r["project_name"] for r in parsed["rows"] if r["project_name"]}),"mapping":{},"decisions":{},"created_at":rules.utc_now().isoformat(timespec="seconds")})
 log("historical_import_previewed",f"file={filename};rows={len(parsed['rows'])}")
 return redirect(url_for("import_review",token=token))
@APP.route("/import/review/<token>")
@login_required
def import_review(token):
 payload=load_stage(token)
 with db() as c:
  rows,summary=historical_import.validate(c,payload,payload["mapping"],payload["decisions"])
  projects=[dict(r) for r in c.execute("SELECT id,name FROM projects ORDER BY name")]
 per_project={}
 for r in rows: per_project[r["project_name"]]=per_project.get(r["project_name"],0)+1
 suggestions=historical_import.suggest_mapping(payload["project_names"],projects)
 for r in rows: r["cat"],r["sub"]=historical_import.classify(r)
 # sections follow the data defect, not the unmapped-project step: a row stays where it is while projects are being mapped
 blocking=[r for r in rows if r["cat"]=="bloquante"]
 groups={"blocking":blocking,
  "arbitrate":[r for r in rows if r["cat"]=="a_arbitrer" and r["status"] not in ("overwrite","keep")],
  "overwrite":[r for r in rows if r["status"] in ("overwrite","keep")],
  "valid":[r for r in rows if r["cat"]=="valide"],
  "excluded":[r for r in rows if r["cat"]=="exclue_projet"],
  "totals":[r for r in rows if r["cat"]=="total_ou_sous_total"]}
 def hsum(lst): return historical_import.fmt_hours(sum((Decimal(r["hours"]) for r in lst if r["hours"]),Decimal(0)))
 rec={"valid":hsum(groups["valid"]),"arbitrate":hsum(groups["arbitrate"]),"blocking":hsum(groups["blocking"]),"excluded":hsum(groups["excluded"]),"totals":hsum(groups["totals"]),
  "inc":(len([r for r in groups["arbitrate"] if r["decision"]=="include"]),hsum([r for r in groups["arbitrate"] if r["decision"]=="include"])),
  "exc":(len([r for r in groups["arbitrate"] if r["decision"]=="exclude"]),hsum([r for r in groups["arbitrate"] if r["decision"]=="exclude"])),
  "pend":(len([r for r in groups["arbitrate"] if not r["decision"]]),hsum([r for r in groups["arbitrate"] if not r["decision"]])),
  "valid_exc":(len([r for r in groups["valid"] if r["decision"]=="exclude"]),hsum([r for r in groups["valid"] if r["decision"]=="exclude"])),
  "ow":(len([r for r in rows if r["status"]=="overwrite"]),hsum([r for r in rows if r["status"]=="overwrite"])),
  "keep":(len([r for r in rows if r["status"]=="keep"]),hsum([r for r in rows if r["status"]=="keep"]))}
 return render_template("import_review.html",token=token,payload=payload,rows=rows,groups=groups,rec=rec,suggestions=suggestions,summary=summary,projects=projects,per_project=per_project,issues=historical_import.ISSUES)
CSV_STATUS={"ok":"importée (valide)","include":"importée (décision)","exclude":"non importée (décision)","needs_decision":"décision attendue","error":"non importable (erreur)","excluded_project":"non importée (projet exclu)",
 "overwrite":"écrase la saisie existante (décision)","keep":"saisie existante conservée"}
def csv_cell(v):
 # spreadsheet formula injection: a text cell starting with = + - @ tab or CR is neutralised with a leading apostrophe
 v="" if v is None else str(v)
 return "'"+v if v[:1] in ("=","+","-","@","\t","\r") else v
@APP.route("/import/review/<token>/export.csv")
@login_required
def import_export(token):
 # read-only: exports the SAVED state of the preview (mapping and decisions as last recorded), writes nothing
 payload=load_stage(token)
 with db() as c:
  rows,summary=historical_import.validate(c,payload,payload["mapping"],payload["decisions"])
  projects={str(r["id"]):r["name"] for r in c.execute("SELECT id,name FROM projects")}
 out=io.StringIO(); w=csv.writer(out,delimiter=";",lineterminator="\r\n")
 w.writerow(["source_ref","onglet","ligne","date","projet_source","mandat_cible","debut","fin","heures_declarees","heures_calculees","motif","categorie","sous_categorie","statut","decision_enregistree","controles","copie_de","proposition_non_appliquee","brut_date","brut_debut","brut_fin","brut_heures"])
 for r in rows:
  cat,sub=historical_import.classify(r); tgt=payload["mapping"].get(r["project_name"],"")
  w.writerow([csv_cell(x) for x in [f"{r['source_sheet']}!{r['source_row']}",r["source_sheet"],r["source_row"],r["work_date"],r["project_name"],"(projet exclu)" if tgt=="skip" else projects.get(tgt,""),r["start_time"],r["end_time"],r["hours"],r["clock_hours"],r["description"],cat,sub,CSV_STATUS.get(r["status"],r["status"]),payload["decisions"].get(str(r["idx"]),""),";".join(r["issues"]),r.get("duplicate_of",""),r.get("proposal",""),r["raw"]["date"],r["raw"]["start"],r["raw"]["end"],r["raw"]["hours"]]])
 log("historical_import_exported",f"rows={len(rows)}")
 resp=make_response("\ufeff"+out.getvalue()); resp.headers["Content-Type"]="text/csv; charset=utf-8"; resp.headers["Content-Disposition"]=f'attachment; filename="apercu-import-{payload["file_sha256"][:8]}.csv"'; return resp
@APP.route("/import/review/<token>",methods=["POST"])
@login_required
def import_review_post(token):
 payload=load_stage(token)
 mapping={}
 for i,name in enumerate(payload["project_names"]):
  v=request.form.get(f"map_{i}","")
  mapping[name]=v if v=="skip" or v.isdigit() else ""
 decisions={str(r["idx"]):request.form[f"d_{r['idx']}"] for r in payload["rows"] if request.form.get(f"d_{r['idx']}") in ("include","exclude","overwrite")}
 changed=mapping!=payload["mapping"] or decisions!=payload["decisions"]
 payload["mapping"]=mapping; payload["decisions"]=decisions; save_stage(token,payload)
 if request.form.get("action")!="commit":
  flash("Associations et décisions enregistrées. Aperçu recalculé."); return redirect(url_for("import_review",token=token))
 if changed:
  flash("Les associations ou décisions ont changé : vérifier l'aperçu recalculé, puis valider à nouveau."); return redirect(url_for("import_review",token=token))
 ack=request.form.get("ack")=="1"; fp=request.form.get("fingerprint","")
 try:
  with db() as c:
   _,summary=historical_import.validate(c,payload,mapping,decisions)
  import_service.ensure_committable(summary,fp,ack)
  backup=import_service.sqlite_backup(DB,backup_dir(),"pre-import")
  c=db(autocommit=True)
  try: batch,inserted,summary=import_service.commit_batch(c,payload,mapping,decisions,fp,ack,backup,SEC["user"])
  finally: c.close()
 except import_service.ImportRefused as e:
  flash("Import non exécuté : "+str(e)); return redirect(url_for("import_review",token=token))
 except Exception as e:
  flash(f"Import annulé, aucune ligne enregistrée ({type(e).__name__}: {e})."); return redirect(url_for("import_review",token=token))
 os.remove(stage_path(token))
 flash(f"Import validé : {inserted} prestation(s) ajoutée(s)"+(f", {summary['overwrites']} saisie(s) existante(s) écrasée(s) (corrections tracées)" if summary.get("overwrites") else "")
       +f" sur {summary['total']} ligne(s) source. Lot {batch}. Sauvegarde préalable : {backup[0]}.")
 return back("migration")
@APP.route("/import/review/<token>/cancel",methods=["POST"])
@login_required
def import_cancel(token):
 path=stage_path(token)
 if os.path.isfile(path): os.remove(path)
 flash("Prévisualisation abandonnée : aucune donnée importée."); return back("migration")
