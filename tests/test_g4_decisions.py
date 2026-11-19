"""G4 — user decisions of 2026-10-07 (Decision Center). Synthetic data only, on a COPY of the staging database (see test_import.py for the run command).

D9 (B)   the date of the invoice is the cutoff of its position for every document: historical invoices, earlier Time Billing invoices and credit notes
         (and their cancellations) count when they are dated on or before it; the year of a document is the year of its date.
E-4 (B)  the free note of an invoice has a fixed zone of one line under the totals: nothing below it moves; a longer note is refused when the draft
         is saved, and a draft saved before the limit fails check 11.
F-C2-1   (technical, review of 2026-10-06) a quantity or an amount is written with ASCII digits: « 1_5 », « 1e1 », « inf », « ٣ » (forged requests) are refused.
"""
import sqlite3

import app.app as m
from app import billing_rules as rules, pdf_layout
from tests import test_g4
from tests.test_functional import pdf_text
from tests.test_g4 import text


class Base(test_g4.G4):
    checks = test_g4.Checks.checks; clean_draft = test_g4.Checks.clean_draft      # helpers only: subclassing Checks would run its tests again here


class Cutoff(Base):
    def dated(self, iid, d):
        c = sqlite3.connect(self.db); c.execute('UPDATE invoices SET invoice_date=? WHERE id=?', (d, iid)); c.commit(); c.close()

    def test_an_invoice_dated_after_this_one_is_not_counted_even_for_an_earlier_period(self):
        a = self.draft(self.pid, '2026-08-01', '2026-08-31', 1, invoice_date='2026-10-05')[0]; self.issue(a)
        self.assertEqual(self.scalar('SELECT invoice_date FROM invoices WHERE id=?', (a,)), '2026-10-05')
        b = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, invoice_date='2026-10-01')[0]
        pos = self.header(b)[0]['position']
        self.assertEqual((pos['previous'], pos['current'], pos['later'], pos['balance'], pos['cutoff']), (0, 2.0, 1.0, 10.0, '2026-10-01'))
        ck = self.checks(b)
        self.assertEqual({x['status'] for x in ck.values()}, {'ok'}, ck)
        self.assertIn('facturé jusqu\'à la date de facture 01.10.2026', ck[6]['detail'])
        self.assertIn('1.0 j de factures émises datées après cette facture ne sont pas comptés', ck[6]['detail'])
        t = ' '.join(pdf_text(self.c.get(f'/invoice/{b}.pdf').data).split())
        self.assertIn('Position contractuelle en jours au 01.10.2026', t)
        self.assertIn('factures Time Billing émises datées au plus tard du 01.10.2026', t)
        self.dated(b, '2026-10-06')                                                              # dated after it: now counted
        pos = self.header(b)[0]['position']; self.assertEqual((pos['previous'], pos['later'], pos['balance']), (1.0, 0, 9.0))
        self.assertEqual({x['status'] for x in self.checks(b).values()}, {'ok'})

    def test_a_credit_note_counts_from_its_own_date(self):
        a = self.draft(self.pid, '2026-08-01', '2026-08-31', 1, invoice_date='2026-09-01')[0]; self.issue(a)
        self.c.post(f'/invoice/{a}/credit', data={'reason': 'ajustement', 'qty': '0.5', 'treatment': 'remboursement'})
        n = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{n}/issue')
        cn_day = rules.local_date(self.scalar('SELECT issued_at FROM credit_notes WHERE id=?', (n,)))
        b = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, invoice_date='2026-10-01')[0]
        if cn_day > '2026-10-01':                                                                # the note was issued today, after 01.10: not yet at this cutoff
            pos = self.header(b)[0]['position']; self.assertEqual((pos['previous'], pos['credited'], pos['balance']), (1.0, 0, 9.0))
            ck = self.checks(b); self.assertEqual({x['status'] for x in ck.values()}, {'ok'}, ck); self.assertIn('0 j annulés', ck[7]['detail'])
        self.dated(b, None)                                                                      # dated on the day of issuance: the note counts
        pos = self.header(b)[0]['position']; self.assertEqual((pos['previous'], pos['credited'], pos['balance']), (1.0, 0.5, 9.5))
        ck = self.checks(b); self.assertEqual({x['status'] for x in ck.values()}, {'ok'}, ck); self.assertIn('0.5 j annulés', ck[7]['detail'])

    def test_historical_invoices_still_count_by_their_date(self):
        self.set_status(self.hist(date='2026-10-03', days=1.0), 'validated')
        b = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, invoice_date='2026-10-01')[0]
        self.assertEqual(self.header(b)[0]['position']['historical'], 0)
        self.dated(b, '2026-10-03'); self.assertEqual(self.header(b)[0]['position']['historical'], 1.0)
        self.assertEqual({x['status'] for x in self.checks(b).values()}, {'ok'})

    def test_the_year_of_a_document_is_the_year_of_its_date(self):
        self.assertEqual(rules.doc_date(_Row(invoice_date='2027-01-04', issued_at='2026-12-20T08:00:00')), '2027-01-04')     # the printed date wins
        self.assertEqual(rules.doc_date(_Row(invoice_date=None, issued_at='2026-12-31T23:30:00')), '2027-01-01')   # legacy row: the Zurich day of issuance
        self.assertEqual(rules.doc_date(_Row(issued_at='2026-12-31T22:30:00')), '2026-12-31')                     # credit note: no invoice_date column


class _Row(dict):
    """sqlite3.Row-like: keys() and [] (doc_date reads both)."""
    def __init__(self, **kw): super().__init__(**kw)


class NoteZone(Base):
    LONG = 'Merci de rappeler le numéro de bon de commande et la référence du projet sur chacun de vos paiements, ainsi que la période'

    def placed(self, iid):
        """(text, y) of every string drawn on the first page of the draft's PDF (Doc.text intercepted: no external tool needed)."""
        import unittest.mock as mock
        seen, real = [], pdf_layout.Doc.text
        def spy(doc, x, y, s, *a, **k):
            if doc.c.getPageNumber() == 1: seen.append((s, round(y, 2)))
            return real(doc, x, y, s, *a, **k)
        with mock.patch.object(pdf_layout.Doc, 'text', spy): self.c.get(f'/invoice/{iid}.pdf')
        return seen

    def test_a_note_longer_than_one_line_is_refused_at_creation_and_edition(self):
        self.assertFalse(pdf_layout.note_fits(self.LONG))
        n = self.scalar('SELECT COUNT(*) FROM invoices')
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, note=self.LONG)
        self.assertIn("note de facture trop longue : elle s'imprime sur une seule ligne", ' '.join(fl)); self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'), n)
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, note='Bon de commande reçu le 30.09.2026')
        self.assertIn('Brouillon créé.', fl)
        self.flashes(); r = self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'note': self.LONG})
        self.assertIn('Brouillon non modifié : note de facture trop longue', text(r) + ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT note FROM invoices WHERE id=?', (iid,)), 'Bon de commande reçu le 30.09.2026')
        self.assertIn('Une seule ligne sous les totaux', text(self.c.get(f'/invoice/{iid}/edit')))

    def test_a_one_line_note_moves_nothing_on_the_page(self):
        iid = self.clean_draft()
        c = sqlite3.connect(self.db); c.execute("INSERT INTO settings(key,value) VALUES('thanks_text','Je vous remercie de votre confiance.') "
                                                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"); c.commit(); c.close()
        bare = self.placed(iid)
        note = 'Bon de commande reçu le 30.09.2026, ' + 'référence à rappeler ' * 2
        self.assertTrue(pdf_layout.note_fits(note))
        self.flashes(); self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'note': note})
        self.assertIn('Brouillon modifié.', self.flashes())
        noted = self.placed(iid)
        self.assertEqual([x for x in noted if x[0] != ' '.join(note.split())], bare)                # every other string at the same place
        y_note = next(y for t, y in noted if t == ' '.join(note.split()))
        y_total = max(y for t, y in bare if t == 'TOTAL'); y_thanks = next(y for t, y in bare if t.startswith('Je vous remercie'))
        self.assertTrue(y_total < y_note < y_thanks, (y_total, y_note, y_thanks))                   # the fixed zone: under the totals, above the thanks
        self.assertEqual(self.checks(iid)[11]['status'], 'ok')

    def test_a_draft_saved_before_the_limit_fails_check_11_and_still_prints_its_whole_note(self):
        iid = self.clean_draft()
        c = sqlite3.connect(self.db); c.execute("UPDATE invoices SET note=? WHERE id=?", (self.LONG, iid)); c.commit(); c.close()
        ck = self.checks(iid)
        self.assertEqual(ck[11]['status'], 'fail'); self.assertFalse(ck[11]['derogable'])
        self.assertIn('note de facture sur plusieurs lignes', ck[11]['detail'])
        t = ' '.join(pdf_text(self.c.get(f'/invoice/{iid}.pdf').data).split()); self.assertIn('ainsi que la période', t)


class PlainNumbers(Base):
    def test_quantities_and_amounts_are_plain_ascii_decimals(self):
        n = self.scalar('SELECT COUNT(*) FROM invoices')
        for bad in ('1_5', '1e1', 'inf', '\u0663', '0x2', 'nan'):
            iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', bad)
            self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'), n, bad); self.assertIn('quantité invalide', ' '.join(fl), bad)
            iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, other_amount=bad)
            self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'), n, bad); self.assertIn('invalide', ' '.join(fl), bad)
        for good, q in (('2', 2.0), ('1,5', 1.5), ('.5', 0.5), ('2.', 2.0)):
            iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', good, other_amount='12,50')
            self.assertIn('Brouillon créé.', fl, good)
            self.assertEqual((self.scalar('SELECT qty FROM invoices WHERE id=?', (iid,)), self.scalar('SELECT other_amount FROM invoices WHERE id=?', (iid,))), (q, 12.5))
            self.c.post(f'/invoice/{iid}/delete')
