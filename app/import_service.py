"""Transactional commit of a previewed historical import batch."""
import hashlib, json, os, secrets, sqlite3
from datetime import datetime, timezone

from app.historical_import import validate, entry_state
from app import billing_rules as rules, post_billing


class ImportRefused(ValueError):
    pass


def sqlite_backup(db_path, folder, label):
    """Consistent online copy via the SQLite backup API, verified before use."""
    os.makedirs(folder, mode=0o700, exist_ok=True)
    name = f"{label}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}.db"
    path = os.path.join(folder, name)
    src = sqlite3.connect(db_path); dst = sqlite3.connect(path)
    try: src.backup(dst)
    finally: dst.close(); src.close()
    chk = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try: ok = chk.execute('PRAGMA integrity_check').fetchone()[0]
    finally: chk.close()
    if ok != 'ok': raise RuntimeError(f'sauvegarde pré-import invalide ({ok})')
    os.chmod(path, 0o600)
    with open(path, 'rb') as f: digest = hashlib.sha256(f.read()).hexdigest()
    return name, digest


def ensure_committable(summary, fingerprint, acknowledged):
    if summary['fingerprint'] != fingerprint:
        raise ImportRefused("La situation a changé depuis la prévisualisation (base ou décisions). Recharger l'aperçu avant de valider.")
    if summary['unmapped_projects']:
        raise ImportRefused('Associer ou exclure explicitement chaque projet source : ' + ', '.join(summary['unmapped_projects']))
    if summary['by_status'].get('needs_decision'):
        raise ImportRefused(f"{summary['by_status']['needs_decision']} ligne(s) en anomalie attendent une décision (importer / ne pas importer).")
    excluded = summary['total'] - summary['importable'] - summary.get('overwrites', 0)
    if excluded and not acknowledged:
        raise ImportRefused(f'Confirmer explicitement que {excluded} ligne(s) ne seront pas importées.')
    if not summary['importable'] and not summary.get('overwrites'):
        raise ImportRefused('Aucune ligne importable.')


ENTRY_SQL = "SELECT e.*,p.name project FROM entries e JOIN projects p ON p.id=e.project_id WHERE e.id=?"


def _entry_json(e):
    # same shape as app.entry_json (history of the corrections)
    return json.dumps({"id": e["id"], "work_date": e["work_date"], "project_id": e["project_id"], "project": e["project"], "start_time": e["start_time"],
                       "end_time": e["end_time"], "hours": e["hours"], "description": e["description"], "source": e["source"], "created_at": e["created_at"],
                       "import_batch_id": e["import_batch_id"], "source_ref": e["source_ref"]}, ensure_ascii=False)


def overwrite_entry(conn, batch, r, actor):
    """OVERWRITE_MATCHING (Decision Center billing-import-overwrite-scope, 2026-10-07): the matched entry takes the values of the re-imported line, as a
    traced correction (history before/after, reason naming the batch and the line, audit). Its id, source, source_ref and original batch stay. Issued
    invoices never change: the post-invoicing variance shows, as after a manual correction."""
    eid = r['match_entry_id']
    e = conn.execute(ENTRY_SQL, (eid,)).fetchone()
    if not e or entry_state(e) != r['match_state']:
        raise ImportRefused(f"La saisie n° {eid} a changé depuis la prévisualisation : recharger l'aperçu avant de valider.")
    invs = post_billing.entry_invoices(conn, eid)
    arrival = post_billing.period_invoice(conn, r['project_id'], r['work_date'])
    concerned = [{"id": x["id"], "number": x["number"], "period_from": x["period_from"], "period_to": x["period_to"], "role": x["role"]} for x in invs]
    if arrival and arrival["id"] not in {x["id"] for x in invs if x["role"] == "billed"}: concerned.append(dict(arrival, role="arrival"))
    conn.execute("UPDATE entries SET work_date=?,project_id=?,start_time=?,end_time=?,hours=?,description=? WHERE id=?",
                 (r['work_date'], r['project_id'], r['start_time'], r['end_time'], float(r['hours']), r['description'], eid))
    after = conn.execute(ENTRY_SQL, (eid,)).fetchone()
    reason = f"réimport volontaire : lot {batch}, ligne {r['source_sheet']}!{r['source_row']} du classeur"
    conn.execute("INSERT INTO entry_changes(entry_id,action,before_json,after_json,changed_at,reason,actor,invoices_json) VALUES(?,?,?,?,?,?,?,?)",
                 (eid, "update", _entry_json(e), _entry_json(after), rules.utc_now_iso(),
                  reason, actor, json.dumps(concerned, ensure_ascii=False)))
    conn.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("time_entry_updated", json.dumps(
        {"id": eid, "before": f"{e['work_date']}/{e['hours']}h/{e['project']}", "after": f"{after['work_date']}/{after['hours']}h/{after['project']}",
         "invoices": [f"{x['number']}:{x['role']}" for x in concerned], "by": actor, "reason": reason}, ensure_ascii=False)))
    return eid


def commit_batch(conn, payload, mapping, decisions, fingerprint, acknowledged, backup, actor=''):
    """Insert all importable rows of one batch atomically.

    conn must be in autocommit mode (isolation_level=None) so this function owns
    the transaction. Everything is re-validated inside BEGIN IMMEDIATE; if the
    result differs from what the user approved, nothing is written.
    """
    conn.execute('BEGIN IMMEDIATE')
    try:
        rows, summary = validate(conn, payload, mapping, decisions)
        ensure_committable(summary, fingerprint, acknowledged)
        batch = secrets.token_hex(16)
        conn.execute("""INSERT INTO import_batches(id,source_filename,status,source_rows,file_sha256,backup_filename,backup_sha256,notes)
                        VALUES(?,?,'PREPARED',?,?,?,?,?)""",
                     (batch, payload['filename'], summary['total'], payload['file_sha256'], backup[0], backup[1],
                      json.dumps({'mapping': mapping, 'issue_counts': summary['issue_counts']}, ensure_ascii=False)))
        inserted = overwritten = 0
        for r in rows:
            entry_id = None
            if r['status'] == 'overwrite':
                entry_id = overwrite_entry(conn, batch, r, actor); overwritten += 1
            elif r['status'] in ('ok', 'include'):
                cur = conn.execute(f"""INSERT INTO entries(id,work_date,project_id,start_time,end_time,hours,description,source,source_ref,import_batch_id)
                                       VALUES({post_billing.NEXT_ENTRY_ID},?,?,?,?,?,?,'historical_excel',?,?)""",
                                   (r['work_date'], r['project_id'], r['start_time'], r['end_time'], float(r['hours']),
                                    r['description'], f"{r['source_sheet']}!{r['source_row']}", batch))
                entry_id = cur.lastrowid; inserted += 1
            conn.execute("""INSERT INTO import_batch_rows(batch_id,source_sheet,source_row,raw_json,issues,decision,entry_id)
                            VALUES(?,?,?,?,?,?,?)""",
                         (batch, r['source_sheet'], r['source_row'], json.dumps(r['raw'], ensure_ascii=False),
                          ','.join(r['issues']), r['status'], entry_id))
        conn.execute("UPDATE import_batches SET status='COMMITTED',inserted_rows=?,committed_at=CURRENT_TIMESTAMP WHERE id=?", (inserted, batch))
        conn.execute('INSERT INTO audit(event,detail) VALUES(?,?)',
                     ('historical_import_committed', f'batch={batch};rows={summary["total"]};inserted={inserted};overwritten={overwritten};file_sha256={payload["file_sha256"]}'))
        conn.execute('COMMIT')
        return batch, inserted, summary
    except Exception as e:
        conn.execute('ROLLBACK')
        if not isinstance(e, ImportRefused): _record_failure(conn, payload, backup, e)
        raise


def _record_failure(conn, payload, backup, error):
    """Trace a failed attempt in its own transaction; the failed batch itself left nothing behind."""
    try:
        conn.execute('BEGIN IMMEDIATE')
        fid = secrets.token_hex(16)
        conn.execute("""INSERT INTO import_batches(id,source_filename,status,source_rows,inserted_rows,file_sha256,backup_filename,backup_sha256,error)
                        VALUES(?,?,'FAILED',?,0,?,?,?,?)""",
                     (fid, payload['filename'], len(payload['rows']), payload['file_sha256'], backup[0], backup[1], f'{type(error).__name__}: {error}'[:500]))
        conn.execute('INSERT INTO audit(event,detail) VALUES(?,?)', ('historical_import_failed', f'batch={fid};error={type(error).__name__}'))
        conn.execute('COMMIT')
    except Exception:
        try: conn.execute('ROLLBACK')
        except Exception: pass
