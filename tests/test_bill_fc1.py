"""BILL-FC1 : plafond d'avoir par ligne = montant FACTURÉ de la ligne (arrondi décimal demi-supérieur exact, comme billing_rules.line_amount).
Données synthétiques uniquement. Trois volets : (1) le déclencheur seul, en mémoire, comparé à l'application sur beaucoup de produits ;
(2) la migration (base « ancienne » avec l'ancien déclencheur → migrée, empreinte métier identique, retour arrière) ; (3) l'application de bout en bout."""
import hashlib, sqlite3, unittest
from decimal import Decimal, ROUND_HALF_UP

import app.app as m
from app import billing_rules as rules, credit_lines
from tests import test_credit_lines as tcl

D = Decimal


def mini(trigger):
    c = sqlite3.connect(':memory:')
    c.executescript("CREATE TABLE invoice_lines(id INTEGER PRIMARY KEY, qty REAL, unit_rate REAL);"
                    "CREATE TABLE credit_note_cancellations(credit_note_id INTEGER);"
                    "CREATE TABLE credit_note_lines(id INTEGER PRIMARY KEY, credit_note_id INTEGER, invoice_line_id INTEGER, amount REAL);")
    c.execute(trigger); return c


def accepts(c, qty, rate, amount):
    c.execute("DELETE FROM invoice_lines"); c.execute("DELETE FROM credit_note_lines"); c.execute("INSERT INTO invoice_lines VALUES(1,?,?)", (qty, rate))
    try: c.execute("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,amount) VALUES(1,1,?)", (float(amount),)); return True
    except sqlite3.DatabaseError as e:
        assert 'cannot exceed' in str(e), e; return False


class Trigger(unittest.TestCase):
    CASES = [('1.5', '0.15'), ('3', '0.075'), ('1.005', '1'), ('2.675', '1'), ('7', '0.145'), ('1', '10'), ('2', '33.3333'), ('0.000001', '0.0001'), ('1.25', '0.1'),
             ('0.333333', '3'), ('99999.999999', '99999.9999'), ('12.5', '0.02'), ('4', '0.0125'), ('0.5', '0.01'), ('100', '0.005')]

    def test_new_trigger_accepts_the_invoiced_amount_and_refuses_one_cent_more(self):
        c = mini(credit_lines.WITHIN_LINE_TRIGGER)
        for q, r in self.CASES:
            billed = rules.line_amount(float(q), float(r))
            self.assertTrue(accepts(c, float(q), float(r), billed), (q, r, billed))
            self.assertFalse(accepts(c, float(q), float(r), billed + D('0.01')), (q, r, billed))

    def test_the_known_half_cent_cases_were_refused_by_the_legacy_trigger_and_are_accepted_now(self):
        old, new = mini(credit_lines.LEGACY_WITHIN_LINE_TRIGGER), mini(credit_lines.WITHIN_LINE_TRIGGER)
        for q, r in (('1.5', '0.15'), ('3', '0.075'), ('1.005', '1'), ('2.675', '1'), ('7', '0.145')):
            billed = rules.line_amount(float(q), float(r))
            self.assertFalse(accepts(old, float(q), float(r), billed), ('legacy', q, r)); self.assertTrue(accepts(new, float(q), float(r), billed), ('new', q, r))

    def test_cases_without_half_cent_behave_as_before(self):
        old, new = mini(credit_lines.LEGACY_WITHIN_LINE_TRIGGER), mini(credit_lines.WITHIN_LINE_TRIGGER)
        for q, r in (('1', '10'), ('2', '33.3333'), ('3', '12.5'), ('1', '0.01'), ('10', '0.1')):
            billed = rules.line_amount(float(q), float(r))
            for amt in (billed, billed - D('0.01'), billed + D('0.01'), billed + D('0.5'), D('0.01')):
                if amt <= 0: continue
                self.assertEqual(accepts(old, float(q), float(r), amt), accepts(new, float(q), float(r), amt), (q, r, amt))

    def test_cumulative_credits_never_exceed_the_invoiced_amount(self):
        c = mini(credit_lines.WITHIN_LINE_TRIGGER); c.execute("INSERT INTO invoice_lines VALUES(1,1.5,0.15)")
        c.execute("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,amount) VALUES(1,1,0.20)")
        with self.assertRaises(sqlite3.DatabaseError): c.execute("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,amount) VALUES(2,1,0.04)")
        c.execute("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,amount) VALUES(2,1,0.03)")           # 0.23 in total
        c.execute("INSERT INTO credit_note_cancellations VALUES(1)")                                                   # a cancelled note frees its part
        c.execute("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,amount) VALUES(3,1,0.20)")

    def test_values_beyond_the_integer_range_fall_back_without_error(self):
        c = mini(credit_lines.WITHIN_LINE_TRIGGER)
        self.assertTrue(accepts(c, 1000000.0, 1000000000.0, 1e15)); self.assertFalse(accepts(c, 1000000.0, 1000000000.0, 1e16))


class App(tcl.Base):
    def test_total_credit_of_a_half_cent_line_is_accepted_and_one_cent_more_refused(self):
        iid = self.issued_with(lines=(('Demi-cent', '1.5', '0.15', 'flat', 'soumis'),)); (l1,) = self.line_ids(iid)
        cid, fl = self.credit(iid, scope='partial', **{f'cl_{l1}': '0.24'}); self.assertIsNone(cid, fl)
        cid, fl = self.credit(iid, scope='partial', **{f'cl_{l1}': '0.23'}); self.assertIsNotNone(cid, fl)

    def test_a_credit_above_the_invoiced_amount_is_still_refused_by_the_database(self):
        iid = self.issued_with(); l1, _ = self.line_ids(iid); cid, fl = self.credit(iid, scope='partial', **{f'cl_{l1}': '1'}); self.assertIsNotNone(cid, fl)
        msg = self.raw("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,position,description,amount,vat_mode,created_at) "
                       "SELECT %d,%d,9,'x',99999,vat_mode,'2026-10-01T00:00:00' FROM invoice_lines WHERE id=%d" % (cid, l1, l1))
        self.assertIsNotNone(msg); self.assertIn('cannot exceed', msg)

    def fingerprint(self):
        c = sqlite3.connect(self.db); h = hashlib.sha256()
        try:
            for t in sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")):
                h.update(t.encode())
                for r in c.execute('SELECT * FROM "%s" ORDER BY 1' % t): h.update(repr(tuple(r)).encode())
            return h.hexdigest()
        finally: c.close()

    def test_an_existing_database_is_migrated_without_loss_and_the_change_is_reversible(self):
        iid = self.issued_with(); l1, _ = self.line_ids(iid); cid = self.issued_cn(iid, scope='partial', **{f'cl_{l1}': '5'})
        c = sqlite3.connect(self.db); credit_lines.rollback_within_line(c); c.commit()                                  # a database as it was before BILL-FC1
        self.assertFalse(credit_lines.within_line_is_current(c)); c.close()
        before = self.fingerprint(); m.init()
        c = sqlite3.connect(self.db)
        try:
            self.assertTrue(credit_lines.within_line_is_current(c)); self.assertEqual(self.fingerprint(), before)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='credit_lines_within_line'").fetchone()[0], 1)
            self.assertFalse(credit_lines.migrate(c))                                                                    # idempotent
            credit_lines.rollback_within_line(c); self.assertFalse(credit_lines.within_line_is_current(c)); c.commit()   # documented rollback
        finally: c.close()
        self.assertEqual(self.fingerprint(), before); m.init()
        c = sqlite3.connect(self.db)
        try: self.assertTrue(credit_lines.within_line_is_current(c))
        finally: c.close()


if __name__ == '__main__':
    unittest.main()
