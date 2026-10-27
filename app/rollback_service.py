"""Transactional rollback of a committed historical import batch."""
from datetime import datetime, timezone
import sqlite3


class RollbackRefused(ValueError):
    pass


def rollback_import(conn: sqlite3.Connection, batch_id: str) -> int:
    """Remove only rows inserted by a committed batch, all or nothing.

    conn must be in autocommit mode (isolation_level=None). Refused when any
    batch row appears in a frozen issued-invoice annex, or when an issued
    invoice of the same project is dated on or after the row (cumulative annex
    covers everything up to period_to). The database triggers enforce the
    first rule a second time.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        batch = conn.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch or batch["status"] != "COMMITTED":
            raise RollbackRefused("Lot absent ou non annulable (statut : %s)" % (batch["status"] if batch else "inconnu"))
        linked = conn.execute("""
          SELECT COUNT(DISTINCT e.id) n FROM entries e
          JOIN invoice_annex_entries a ON a.entry_id=e.id JOIN invoices i ON i.id=a.invoice_id
          WHERE e.import_batch_id=? AND i.status='issued'""", (batch_id,)).fetchone()["n"]
        covered = conn.execute("""
          SELECT COUNT(DISTINCT e.id) n FROM entries e
          JOIN invoices i ON i.project_id=e.project_id
          WHERE e.import_batch_id=? AND i.status='issued' AND e.work_date <= i.period_to""", (batch_id,)).fetchone()["n"]
        if linked or covered:
            raise RollbackRefused(f"Rollback refusé : {max(linked, covered)} prestation(s) du lot sont couvertes par une facture émise")
        # OVERWRITE_MATCHING (2026-10-07): a batch that overwrote existing entries is not undone as a whole (deleting its rows would leave those entries
        # with the new values); each overwrite stays visible and correctable in the history of its entry.
        ow = conn.execute("SELECT COUNT(*) n FROM import_batch_rows WHERE batch_id=? AND decision='overwrite'", (batch_id,)).fetchone()["n"]
        if ow:
            raise RollbackRefused(f"Rollback refusé : ce lot a écrasé {ow} saisie(s) existante(s) (corrections tracées) ; il ne peut pas être annulé en bloc. "
                                  "Chaque écrasement se corrige depuis l'historique de la saisie ; le lot reste en place.")
        # rc19: imported entries are ordinary, editable entries. Once one of them was corrected, moved or deleted (history row),
        # removing the batch would silently erase that correction: refused, with the count.
        # Correlated with the batch: history written after its commit (before rc19 an id could be reused by a later import), plus the
        # database trace of a change made outside the application (audit rows written by the rc19 triggers)
        since = (batch["committed_at"] or batch["created_at"] or "").replace(" ", "T")[:19]
        ids = "SELECT entry_id FROM import_batch_rows WHERE batch_id=? AND entry_id IS NOT NULL"
        touched = conn.execute(f"""
          SELECT COUNT(DISTINCT n) n FROM (
            SELECT ec.entry_id n FROM entry_changes ec WHERE ec.entry_id IN ({ids}) AND ec.changed_at>=?
            UNION SELECT CASE WHEN json_valid(a.detail) THEN json_extract(a.detail,'$.id') END FROM audit a
              WHERE a.event IN ('entry_row_updated','entry_row_deleted') AND replace(a.created_at,' ','T')>=?
              AND CASE WHEN json_valid(a.detail) THEN json_extract(a.detail,'$.id') END IN ({ids}))""", (batch_id, since, since, batch_id)).fetchone()["n"]
        refs = [r["ref"] for r in conn.execute(f"""SELECT source_sheet||'!'||source_row ref FROM import_batch_rows WHERE batch_id=? AND entry_id IN (
                   SELECT entry_id FROM entry_changes WHERE changed_at>=?) ORDER BY id LIMIT 3""", (batch_id, since))] if touched else []
        if touched:
            raise RollbackRefused(f"Rollback refusé : {touched} saisie(s) de ce lot ont été corrigées, réaffectées ou supprimées depuis l'import"
                                  + (f" (par ex. {', '.join(refs)})" if refs else "") + " ; annuler le lot effacerait ces corrections. "
                                  "Les corriger ou les supprimer une par une reste possible ; le lot reste en place.")
        deleted = conn.execute("DELETE FROM entries WHERE import_batch_id=?", (batch_id,)).rowcount
        if deleted != batch["inserted_rows"]:
            raise RollbackRefused(f"Rollback refusé : {deleted} saisie(s) trouvées pour {batch['inserted_rows']} importées (une saisie du lot a disparu sans "
                                  "trace dans l'historique) ; rien n'a été annulé")
        conn.execute("UPDATE import_batches SET status='ROLLED_BACK', rolled_back_at=? WHERE id=?",
                     (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds'), batch_id))
        conn.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("import_rolled_back", f"batch={batch_id};deleted={deleted}"))
        conn.execute("COMMIT")
        return deleted
    except Exception:
        conn.execute("ROLLBACK")
        raise
