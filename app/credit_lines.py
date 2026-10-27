"""Credit notes on the manual lines of an invoice (rc38; owner decision 26.10.2026, Q1 = B then C).

An invoice carries a service line, an « AUTRES » line and, since rc37, manual lines (`invoice_lines`). A credit note may now credit each manual line, in whole or in part,
by an HT AMOUNT per line (a line is not made of days: the mandate's position in days is not touched).

Data (additive, replayed at every start by `migrate`):
  credit_notes.lines_taxed / lines_untaxed   HT credited on the manual lines « soumis à TVA » / « hors TVA » (the totals the amounts and the PDF read)
  credit_note_lines                          one row per credited line: credit note, invoice line, description (copied: the printed text), HT amount, VAT regime (copied)
SQL guards (triggers): a credited line belongs to the invoice of the note and keeps the regime of the invoice line; the cumulative credit of a line (draft and issued notes,
cancelled ones excluded) never exceeds the line's amount; the rows of an issued note are immutable; a note cannot be issued if its totals differ from the sum of its rows;
`credit_ops_within_note` (cap of refunds / imputations) now counts the lines.
"""

DDL = """
CREATE TABLE IF NOT EXISTS credit_note_lines(id INTEGER PRIMARY KEY AUTOINCREMENT, credit_note_id INTEGER NOT NULL REFERENCES credit_notes(id),
  invoice_line_id INTEGER NOT NULL REFERENCES invoice_lines(id), position INTEGER NOT NULL CHECK(position>0), description TEXT NOT NULL CHECK(length(trim(description))>0),
  amount REAL NOT NULL CHECK(amount>0), vat_mode TEXT NOT NULL CHECK(vat_mode IN ('soumis','hors_tva')), created_at TEXT NOT NULL,
  UNIQUE(credit_note_id,invoice_line_id));
CREATE INDEX IF NOT EXISTS idx_credit_lines_invoice_line ON credit_note_lines(invoice_line_id);
-- the insert guard looks at the SNAPSHOT of the note (not its status) so that a restore can rebuild the rows of an issued note before its snapshot
CREATE TRIGGER IF NOT EXISTS credit_lines_no_insert_frozen BEFORE INSERT ON credit_note_lines WHEN EXISTS(SELECT 1 FROM credit_note_snapshots WHERE credit_note_id=NEW.credit_note_id)
  BEGIN SELECT RAISE(ABORT,'Lines of an issued credit note are immutable'); END;
CREATE TRIGGER IF NOT EXISTS credit_lines_no_update_issued BEFORE UPDATE ON credit_note_lines WHEN (SELECT status FROM credit_notes WHERE id=OLD.credit_note_id)='issued'
  BEGIN SELECT RAISE(ABORT,'Lines of an issued credit note are immutable'); END;
CREATE TRIGGER IF NOT EXISTS credit_lines_no_delete_issued BEFORE DELETE ON credit_note_lines WHEN (SELECT status FROM credit_notes WHERE id=OLD.credit_note_id)='issued'
  BEGIN SELECT RAISE(ABORT,'Lines of an issued credit note cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS credit_lines_same_invoice BEFORE INSERT ON credit_note_lines
  WHEN (SELECT invoice_id FROM invoice_lines WHERE id=NEW.invoice_line_id) IS NOT (SELECT invoice_id FROM credit_notes WHERE id=NEW.credit_note_id)
  BEGIN SELECT RAISE(ABORT,'A credited line belongs to the invoice of the credit note'); END;
CREATE TRIGGER IF NOT EXISTS credit_lines_same_vat_mode BEFORE INSERT ON credit_note_lines
  WHEN NEW.vat_mode IS NOT (SELECT vat_mode FROM invoice_lines WHERE id=NEW.invoice_line_id)
  BEGIN SELECT RAISE(ABORT,'A credited line keeps the VAT regime of the invoice line'); END;
CREATE TRIGGER IF NOT EXISTS credit_lines_within_line BEFORE INSERT ON credit_note_lines
  WHEN COALESCE((SELECT SUM(l.amount) FROM credit_note_lines l WHERE l.invoice_line_id=NEW.invoice_line_id
                   AND l.credit_note_id NOT IN (SELECT credit_note_id FROM credit_note_cancellations)),0)+NEW.amount
       > (SELECT ROUND(qty*unit_rate,2) FROM invoice_lines WHERE id=NEW.invoice_line_id)+0.005
  BEGIN SELECT RAISE(ABORT,'The credits of an invoice line cannot exceed its amount'); END;
CREATE TRIGGER IF NOT EXISTS credit_lines_totals_match BEFORE UPDATE OF status ON credit_notes WHEN NEW.status='issued' AND OLD.status='draft' AND
  (ABS(COALESCE(NEW.lines_taxed,0)-COALESCE((SELECT SUM(amount) FROM credit_note_lines WHERE credit_note_id=NEW.id AND vat_mode='soumis'),0))>0.005
   OR ABS(COALESCE(NEW.lines_untaxed,0)-COALESCE((SELECT SUM(amount) FROM credit_note_lines WHERE credit_note_id=NEW.id AND vat_mode='hors_tva'),0))>0.005)
  BEGIN SELECT RAISE(ABORT,'The line totals of a credit note must equal the sum of its credited lines'); END;
"""

# cap of the refunds / imputations of a note: its TTC (the VAT only on what is subject to it) + 5 cents. Before rc38 the same formula without the lines.
OPS_CAP_TRIGGER = """CREATE TRIGGER credit_ops_within_note BEFORE INSERT ON credit_operations WHEN NEW.kind IN ('refund','offset') AND
    COALESCE((SELECT SUM(CASE WHEN kind IN ('refund','offset') THEN amount ELSE -amount END) FROM credit_operations WHERE credit_note_id=NEW.credit_note_id),0)+NEW.amount >
    (SELECT (amount+COALESCE(other_amount,0)+COALESCE(lines_taxed,0))*(1+COALESCE(vat,0)/100.0)+COALESCE(lines_untaxed,0)+0.05 FROM credit_notes WHERE id=NEW.credit_note_id)
    BEGIN SELECT RAISE(ABORT,'The operations of a credit note cannot exceed its amount'); END;"""


def ops_cap_is_current(c):
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='credit_ops_within_note'").fetchone()
    return bool(row and row[0] and "lines_taxed" in row[0])


def migrate(c):
    """Additive: the table, its indexes and triggers (IF NOT EXISTS), then the replacement of the operations cap, in one transaction. The columns of credit_notes are added
    by init() (ensure_column) before this runs. Idempotent; a second worker starting at the same time re-reads the trigger inside the transaction and finds it done."""
    c.executescript(DDL)
    if ops_cap_is_current(c): return False
    c.execute("BEGIN IMMEDIATE")
    try:
        if not ops_cap_is_current(c):
            c.execute("DROP TRIGGER IF EXISTS credit_ops_within_note")
            c.execute(OPS_CAP_TRIGGER)
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK"); raise
    return True
