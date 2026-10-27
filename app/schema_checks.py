"""rc19 (+ G4 registry of historical invoices): one shared check of the schema state the release needs, used by the deployment procedures (30-rehearse, 50-verify,
verifier-sauvegarde) and the tests. integrity_check and foreign_key_check do not see a trigger pointing to a missing table:
compiled writes do (EXPLAIN prepares the statement with its triggers)."""
import itertools, json

from app.post_billing import same_values

_nonce = itertools.count()   # a fresh SQL text per probe: a cached EXPLAIN statement is not prepared again after a schema change

PROBES = ("EXPLAIN UPDATE entries SET id=id WHERE 0", "EXPLAIN DELETE FROM entries WHERE 0",
          # 2026-10-08 (revue rc19) : l'insertion d'une saisie passe par entry_id_never_reused (lecture de entry_changes) : sondée aussi
          "EXPLAIN INSERT INTO entries(work_date,project_id,hours) SELECT '',0,0 WHERE 0",
          "EXPLAIN UPDATE invoice_annex_entries SET entry_id=entry_id WHERE 0", "EXPLAIN DELETE FROM invoice_annex_entries WHERE 0",
          "EXPLAIN INSERT INTO invoice_annex_entries(invoice_id,entry_id) SELECT invoice_id,entry_id FROM invoice_annex_entries WHERE 0",
          "EXPLAIN INSERT INTO invoice_variance_decisions(invoice_id,decision,variance_hours,fingerprint,decided_at) SELECT 0,'aucune',0,'',''  WHERE 0",
          # G4: the registry of historical invoices (insert by the loading tool, status change by the user, delete always refused)
          "EXPLAIN INSERT INTO historical_invoices(project_id,source_file,source_sheet,source_cell,basis,qty_days,created_at) SELECT 0,'','','','days',1,'' WHERE 0",
          "EXPLAIN UPDATE historical_invoices SET status=status,note=note,validated_at=validated_at,validated_by=validated_by WHERE 0",
          "EXPLAIN DELETE FROM historical_invoices WHERE 0",
          # rc37: the draft number is guarded against historical invoices by triggers that read historical_invoices; manual lines and the number history are written by the editor
          "EXPLAIN UPDATE invoices SET number=number,status=status WHERE 0",
          "EXPLAIN INSERT INTO invoices(project_id,period_from,period_to,qty,unit_rate) SELECT 0,'','',0,0 WHERE 0",
          "EXPLAIN INSERT INTO invoice_number_changes(invoice_id,context,changed_at) SELECT 0,'','' WHERE 0",
          "EXPLAIN INSERT INTO invoice_lines(invoice_id,position,description,qty,unit,unit_rate,vat_mode,created_at) SELECT 0,1,'x',1,'flat',0,'soumis','' WHERE 0",
          "EXPLAIN UPDATE invoice_lines SET description=description WHERE 0", "EXPLAIN DELETE FROM invoice_lines WHERE 0",
          # rc38: credit notes on manual lines (guards read invoice_lines, credit_notes, the snapshots and the cancellations; the operations cap reads the line totals)
          "EXPLAIN INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,position,description,amount,vat_mode,created_at) SELECT 0,0,1,'x',1,'soumis','' WHERE 0",
          "EXPLAIN UPDATE credit_note_lines SET amount=amount WHERE 0", "EXPLAIN DELETE FROM credit_note_lines WHERE 0",
          "EXPLAIN UPDATE credit_notes SET status=status WHERE 0",
          "EXPLAIN INSERT INTO credit_operations(credit_note_id,kind,amount,created_at) SELECT 0,'refund',1,'' WHERE 0")


def rc19_problems(c):
    """List of problems ([] = the database is in the rc19 state). c: sqlite3 connection (any row factory)."""
    out = []
    trig = {r[0]: r[1] for r in c.execute("SELECT name,tbl_name FROM sqlite_master WHERE type='trigger'")}
    for name, table in (("invoice_annex_no_update", "invoice_annex_entries"), ("invoice_annex_no_delete", "invoice_annex_entries"),
                        ("entry_update_traced", "entries"), ("entry_delete_traced", "entries"), ("entry_changes_no_update", "entry_changes"),
                        ("entry_changes_no_delete", "entry_changes"), ("variance_decisions_no_update", "invoice_variance_decisions"),
                        ("variance_decisions_no_delete", "invoice_variance_decisions")):
        if trig.get(name) != table: out.append(f"déclencheur {name} absent ou mal rattaché ({trig.get(name)})")
    for name, table in (("historical_invoices_no_delete", "historical_invoices"), ("historical_invoices_source_values", "historical_invoices")):   # G4
        if trig.get(name) != table: out.append(f"déclencheur {name} absent ou mal rattaché ({trig.get(name)})")
    # rc37: invoice numbers, manual lines, billing addresses
    for name, table in (("invoice_number_changes_no_update", "invoice_number_changes"), ("invoice_number_changes_no_delete", "invoice_number_changes"),
                        ("invoice_number_not_historical_ins", "invoices"), ("invoice_number_not_historical_upd", "invoices"), ("invoice_issue_needs_number", "invoices"),
                        ("invoice_lines_no_insert_frozen", "invoice_lines"), ("invoice_lines_no_update_issued", "invoice_lines"), ("invoice_lines_no_delete_issued", "invoice_lines"),
                        # rc38
                        ("credit_lines_no_insert_frozen", "credit_note_lines"), ("credit_lines_no_update_issued", "credit_note_lines"), ("credit_lines_no_delete_issued", "credit_note_lines"),
                        ("credit_lines_same_invoice", "credit_note_lines"), ("credit_lines_same_vat_mode", "credit_note_lines"), ("credit_lines_within_line", "credit_note_lines"),
                        ("credit_lines_totals_match", "credit_notes"), ("credit_ops_within_note", "credit_operations")):
        if trig.get(name) != table: out.append(f"déclencheur {name} absent ou mal rattaché ({trig.get(name)})")
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("invoice_lines", "billing_addresses", "invoice_number_changes", "credit_note_lines"):
        if t not in tables: out.append(f"table {t} absente")
    icols = {r[1] for r in c.execute("PRAGMA table_info(invoices)")}
    miss = {"revision", "number_manual", "billing_address_id", "bill_label", "bill_contact", "bill_address"} - icols
    if miss: out.append(f"colonnes rc37 de invoices absentes : {', '.join(sorted(miss))}")
    ccols = {r[1] for r in c.execute("PRAGMA table_info(credit_notes)")}
    if not {"lines_taxed", "lines_untaxed"} <= ccols: out.append("colonnes rc38 de credit_notes absentes (lines_taxed, lines_untaxed)")
    cap = c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='credit_ops_within_note'").fetchone()
    if cap and "lines_taxed" not in (cap[0] or ""): out.append("déclencheur credit_ops_within_note à l'ancienne formule (sans les lignes manuelles) : redémarrer l'application")
    if "idx_invoices_number_norm" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}:
        dup = c.execute("SELECT upper(trim(number)) k,COUNT(*) n FROM invoices WHERE number IS NOT NULL GROUP BY k HAVING n>1").fetchall()
        out.append("index d'unicité normalisée des numéros de facture absent" + (f" (doublons à la casse près : {', '.join(r[0] for r in dup)} : à régler avant de le créer)" if dup else " (redémarrer l'application pour le créer)"))
    hcols = {r[1] for r in c.execute("PRAGMA table_info(historical_invoices)")}
    need = {"project_id", "source_file", "source_sha256", "source_sheet", "source_cell", "source_column", "invoice_date", "invoice_ref", "qty_days", "amount_ht",
            "unit_rate", "basis", "qty_derived", "status", "note", "created_at", "validated_at", "validated_by"}
    if not need <= hcols: out.append("registre historical_invoices absent ou incomplet" + (f" (colonnes manquantes : {', '.join(sorted(need - hcols))})" if hcols else ""))
    for old in ("annexed_entry_no_update", "annexed_entry_no_delete", "invoiced_entry_update_traced", "invoiced_entry_delete_traced"):
        if old in trig: out.append(f"déclencheur {old} encore présent")
    idx = {r[0]: r[1] for r in c.execute("SELECT name,tbl_name FROM sqlite_master WHERE type='index'")}
    if idx.get("idx_annex_entry") != "invoice_annex_entries": out.append("index idx_annex_entry absent")
    if idx.get("idx_historical_project") != "historical_invoices": out.append("index idx_historical_project absent")      # G4
    fks = {r[2] for r in c.execute("PRAGMA foreign_key_list(invoice_annex_entries)")}
    if "entries" in fks: out.append("clé étrangère invoice_annex_entries.entry_id -> entries encore présente")
    if "invoices" not in fks: out.append("clé étrangère invoice_annex_entries.invoice_id -> invoices absente")
    left = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'invoice_annex_entries_%'")]
    if left: out.append(f"table temporaire restante {left}")
    cols = {r[1] for r in c.execute("PRAGMA table_info(entry_changes)")}
    if not {"reason", "actor", "invoices_json"} <= cols: out.append("colonnes rc19 de entry_changes absentes")
    for q in PROBES:
        try: c.execute(f"{q} /* sonde {next(_nonce)} */").fetchall()
        except Exception as e: out.append(f"écriture non compilable ({q.split(' WHERE')[0][8:]}) : {e}")
    # every annex link resolves to an entry, or to the trace of its deletion; a deleted id never exists again
    dangling = c.execute("""SELECT COUNT(*) FROM invoice_annex_entries a LEFT JOIN entries e ON e.id=a.entry_id WHERE e.id IS NULL
                            AND NOT EXISTS(SELECT 1 FROM entry_changes x WHERE x.entry_id=a.entry_id AND x.action='delete')""").fetchone()[0]
    if dangling: out.append(f"{dangling} lien(s) d'annexe vers une saisie absente sans trace de suppression")
    reused = c.execute("SELECT COUNT(*) FROM entry_changes WHERE action='delete' AND entry_id IN (SELECT id FROM entries)").fetchone()[0]
    if reused: out.append(f"{reused} identifiant(s) de saisie supprimée réutilisé(s)")
    if trig.get("entry_id_never_reused") != "entries": out.append(f"déclencheur entry_id_never_reused absent ou mal rattaché ({trig.get('entry_id_never_reused')})")   # revue rc19 : nom ET table
    q = lambda sql: [dict(zip([d[0] for d in cur.description], r)) for cur in [c.execute(sql)] for r in cur.fetchall()]
    out += annex_trail_problems(q("SELECT invoice_id,number,annex_json FROM invoice_snapshots"), {r["id"]: r for r in q("SELECT id,project_id,number FROM invoices")},
                                {r["id"]: r for r in q("SELECT id,work_date,project_id,start_time,end_time,hours,description FROM entries")},
                                q("SELECT id,entry_id,action,after_json FROM entry_changes"))
    return out


def annex_trail_problems(snapshots, invoices, entries, changes):
    """rc19: an entry listed in a frozen annex may be corrected or deleted, never without its history. For every annex row:
    absent entry -> its last history row is a deletion; present entry -> its last history row is not a deletion (no resurrection);
    entry different from the frozen row -> its last history row is a correction whose 'after' values are the entry's.
    Works on plain dicts: used on a live database (checks above) and on a JSON backup before a restore."""
    last = {}
    for r in sorted(changes, key=lambda r: r.get("id") or 0): last[r.get("entry_id")] = r
    out = []
    for s in snapshots:
        try: annex = json.loads(s.get("annex_json") or "[]")
        except (ValueError, TypeError): continue            # unreadable annex: reported elsewhere (restore annex_consistency)
        inv = invoices.get(s.get("invoice_id")) or {}
        for a in annex:
            if not isinstance(a, dict) or "id" not in a: continue
            e, h = entries.get(a["id"]), last.get(a["id"])
            if e is None:
                if not h or h.get("action") != "delete": out.append(f"saisie n° {a['id']} de l'annexe figée de {s.get('number')} absente sans trace de suppression")
            elif h and h.get("action") == "delete":
                out.append(f"saisie n° {a['id']} supprimée selon l'historique mais présente")
            elif not same_values(a, e) or (inv.get("project_id") is not None and e.get("project_id") != inv.get("project_id")):
                try: after = json.loads(h["after_json"]) if h and h.get("after_json") else None
                except (ValueError, TypeError): after = None
                if not after or not same_values(after, e) or after.get("project_id") != e.get("project_id"):
                    out.append(f"saisie n° {a['id']} différente de l'annexe figée de {s.get('number')} sans correction tracée correspondante")
    return list(dict.fromkeys(out))
