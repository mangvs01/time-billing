"""BILL-FA1FT (F_T1): a draft invoice line cannot be moved under an issued (or frozen) invoice by an UPDATE of invoice_lines.invoice_id.

The existing guard `invoice_lines_no_update_issued` (app.py, BEFORE UPDATE) only looks at OLD.invoice_id (the invoice the row leaves), so a direct SQL `UPDATE invoice_lines SET invoice_id=<issued>`
slipped through and made the issued invoice's lines change. This additive trigger looks at the invoice the row ARRIVES in, with the same test as the insert guard (`invoice_lines_no_insert_frozen`:
snapshot taken) plus the status, so a restore (which only INSERTs) is not affected. Not reachable from the interface (no code writes invoice_id of an existing line).
Migration: CREATE TRIGGER IF NOT EXISTS, replayed at each start by `migrate` (called by app.init()); no table, column or row is touched.
Rollback (documented): `rollback(c)` = DROP TRIGGER; note that the next start of this code re-creates it, so a lasting rollback needs the previous code as well.
"""

NAME = "invoice_line_no_move_to_issued"
TRIGGER = f"""CREATE TRIGGER IF NOT EXISTS {NAME} BEFORE UPDATE OF invoice_id ON invoice_lines
  WHEN NEW.invoice_id IS NOT OLD.invoice_id AND (EXISTS(SELECT 1 FROM invoice_snapshots WHERE invoice_id=NEW.invoice_id)
                                                  OR (SELECT status FROM invoices WHERE id=NEW.invoice_id)='issued')
  BEGIN SELECT RAISE(ABORT,'Lines of an issued invoice are immutable'); END;"""


def is_present(c):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?", (NAME,)).fetchone() is not None


def migrate(c):
    """Idempotent and additive. Returns True when the trigger was created by this call."""
    if is_present(c): return False
    c.execute(TRIGGER); return True


def rollback(c):
    c.execute(f"DROP TRIGGER IF EXISTS {NAME}")
