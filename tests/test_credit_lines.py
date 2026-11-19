"""rc38 — credit notes on the manual lines of an invoice, and the suspension of the issuance of invoices that carry manual lines (owner decision 26.10.2026, Q1 = B then C).

Part 1  IssuanceBlock : a draft with manual lines is allowed, its ISSUANCE is refused (route, page, list, constant) until the block is lifted.
Part 2  CreditOnLines : columns, amounts, caps (application and SQL triggers), VAT rounding, PDF of the credit note and of its cancellation, settlement (refund / offset),
        exports, backup / restore, migration from the rc37 shape.
Reference invoice: 2 days × 650 CHF (service) + L1 « Frais de déplacement » 1 × 100 CHF soumis à TVA + L2 « Hébergement » 1 × 50 CHF hors TVA, VAT 8.1 %:
HT 1300.00 + lines 150.00, VAT (1300 + 100) × 8.1 % = 113.40, TTC 1563.40.
Synthetic data only. Run with the isolated runner (see docs/FACTURES-AVOIRS-LIGNES.md)."""
import html as H, io, json, os, re, sqlite3, sys, unittest, zipfile
from decimal import Decimal

import app.app as m
from app import billing_rules as rules, credit_service, gsheet_export, invoice_service, pdf_layout, schema_checks
from app.billing_rules import local_today
from tests.test_functional import pdf_text
from tests.test_invoice_lines import line
from tests.test_v92 import V92

D = Decimal
YEAR = local_today().year
TODAY = local_today().isoformat()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

L1 = ('Frais de déplacement', '1', '100', 'flat', 'soumis')
L2 = ('Hébergement', '1', '50', 'flat', 'hors_tva')


class Base(V92):
    LIFT = True          # the block is lifted for the tests that are about credit notes (they must issue invoices that carry lines)

    def setUp(self):
        super().setUp()
        if self.LIFT:
            old = rules.MANUAL_LINES_ISSUANCE_BLOCKED; rules.MANUAL_LINES_ISSUANCE_BLOCKED = False
            self.addCleanup(setattr, rules, 'MANUAL_LINES_ISSUANCE_BLOCKED', old)
        self.pid = self.mandate(name='Mandat NCL', rate='650', vat='8.1', ordered='12')
        self.entry(self.pid, '2026-09-10', 16); self._worked = {('2026-09-01', '2026-09-30')}

    # --- drafts and invoices ---------------------------------------------------------------------------------------------------------
    def rev(self, iid): return str(self.scalar('SELECT revision FROM invoices WHERE id=?', (iid,)))

    def form(self, iid, lines=(), **over):
        d = dict(period_from='2026-09-01', period_to='2026-09-30', qty='2', unit='day', rounding='exact', rounding_step='0.25', vat='8.1', description='Prestation', other_amount='0',
                 other_label='', other_vat_mode='hors_tva', invoice_date='', note='', revision=self.rev(iid))
        d.update(over)
        d.update({'line_id': [l['id'] for l in lines], 'line_uid': [l['uid'] for l in lines], 'line_description': [l['description'] for l in lines], 'line_qty': [l['qty'] for l in lines],
                  'line_unit': [l['unit'] for l in lines], 'line_rate': [l['rate'] for l in lines], 'line_vat_mode': [l['vat_mode'] for l in lines]})
        return d

    def save(self, iid, lines=(), **over):
        self.flashes(); r = self.c.post(f'/invoice/{iid}/edit', data=self.form(iid, lines, **over), follow_redirects=False)
        return r, ' '.join(self.flashes()) + (' ' + H.unescape(r.get_data(as_text=True)) if r.status_code == 200 else '')

    def draft_with(self, lines=(L1, L2), period=('2026-09-01', '2026-09-30'), qty='2', **over):
        if period[0] < '2026-09-01' and period not in self._worked:      # an earlier month is billed only for work that was recorded (check 14 is never derogable)
            self.entry(self.pid, period[0][:7] + '-10', 16); self._worked.add(period)
        iid, fl = self.draft(self.pid, period[0], period[1], qty); self.assertIn('Brouillon créé.', fl)
        ls = [line(d, q, r, unit=u, vat_mode=v, uid=f'u{n}{iid}') for n, (d, q, r, u, v) in enumerate(lines)]
        if ls or over:
            r, fl = self.save(iid, ls, period_from=period[0], period_to=period[1], qty=qty, **over); self.assertIn('Brouillon modifié.', fl)
        return iid

    def issued_with(self, lines=(L1, L2), **over):
        iid = self.draft_with(lines, **over); self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))
        return iid

    def line_ids(self, iid): return [r['id'] for r in self.sql('SELECT id FROM invoice_lines WHERE invoice_id=? ORDER BY position', (iid,))]

    # --- credit notes ----------------------------------------------------------------------------------------------------------------
    def page_msgs(self, r): return self.flashes() + ([H.unescape(r.get_data(as_text=True))] if r.status_code == 200 else [])

    def credit(self, iid, **form):
        form.setdefault('reason', 'motif fictif'); form.setdefault('treatment', 'remboursement')
        self.flashes(); before = self.scalar('SELECT COUNT(*) FROM credit_notes'); r = self.c.post(f'/invoice/{iid}/credit', data=form)
        made = self.scalar('SELECT COUNT(*) FROM credit_notes') > before
        return (self.scalar('SELECT MAX(id) FROM credit_notes') if made else None), ' '.join(self.page_msgs(r))

    def issue_cn(self, cid):
        self.flashes(); self.c.post(f'/credit/{cid}/issue'); fl = ' '.join(self.flashes())
        return self.scalar('SELECT status FROM credit_notes WHERE id=?', (cid,)), fl

    def issued_cn(self, iid, **form):
        cid, fl = self.credit(iid, **form); self.assertIsNotNone(cid, fl); self.assertIn('Brouillon de note de crédit créé', fl)
        st, fl = self.issue_cn(cid); self.assertEqual(st, 'issued', fl); return cid

    def cn(self, cid):
        c = m.db()
        try: return c.execute('SELECT * FROM credit_notes WHERE id=?', (cid,)).fetchone()
        finally: c.close()

    def amounts(self, cid):
        return credit_service.credit_amounts(self.cn(cid))

    def creditable(self, iid):
        c = m.db()
        try: return credit_service.creditable(c, c.execute('SELECT * FROM invoices WHERE id=?', (iid,)).fetchone())
        finally: c.close()

    def rows_of(self, cid): return [tuple(r) for r in self.sql('SELECT credit_note_id,invoice_line_id,position,description,amount,vat_mode FROM credit_note_lines WHERE credit_note_id=? ORDER BY position', (cid,))]

    def raw(self, *sqls):
        """Run statements on a plain connection (the triggers are the only guard there); returns the first DatabaseError message or None."""
        c = sqlite3.connect(self.db)
        try:
            for q in sqls:
                try: c.execute(q)
                except sqlite3.DatabaseError as e: return str(e)
            c.commit(); return None
        finally: c.close()


# ===================================================================================================================================================
class IssuanceBlock(Base):
    LIFT = False        # these tests exercise the BLOCK mechanism: it is switched on for them (the shipped value is False since rc39, owner's go-ahead 26.10.2026)

    def setUp(self):
        super().setUp()
        self.shipped = rules.MANUAL_LINES_ISSUANCE_BLOCKED
        rules.MANUAL_LINES_ISSUANCE_BLOCKED = True
        self.addCleanup(setattr, rules, 'MANUAL_LINES_ISSUANCE_BLOCKED', self.shipped)

    def test_a_draft_with_manual_lines_cannot_be_issued_but_stays_editable_and_viewable(self):
        iid = self.draft_with(); number = self.scalar('SELECT number FROM invoices WHERE id=?', (iid,))
        self.flashes(); self.issue(iid); fl = ' '.join(self.flashes())
        self.assertIn('Émission refusée', fl); self.assertIn('suspendue', fl); self.assertIn('2 ligne(s) manuelle(s)', fl)
        self.assertEqual(self.sql('SELECT status,number FROM invoices WHERE id=?', (iid,))[0][:], ('draft', number))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_snapshots WHERE invoice_id=?', (iid,)), 0)
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').status_code, 200)                                      # the draft PDF stays available
        r, fl = self.save(iid, [line('Frais de déplacement', '1', '110', uid='ux')]); self.assertIn('Brouillon modifié.', fl)          # and the draft stays editable
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?', (iid,)), 1)

    def test_the_issue_page_says_so_and_disables_the_button(self):
        iid = self.draft_with(); html = H.unescape(self.c.get(f'/issue/{iid}').get_data(as_text=True))
        self.assertIn('id="linesBlock"', html); self.assertIn('Émission impossible', html); self.assertIn('lignes manuelles (émission suspendue)', html)
        self.assertRegex(html, r'<button disabled>Émettre définitivement')
        self.assertIn('Modifier le brouillon', html)

    def test_the_editor_and_the_list_show_the_suspension(self):
        iid = self.draft_with()
        self.assertIn('id="tb-issue-block"', self.c.get(f'/invoice/{iid}/edit').get_data(as_text=True))
        self.assertIn('émission suspendue (lignes manuelles)', H.unescape(self.c.get('/?tab=archive').get_data(as_text=True)))

    def test_a_draft_without_manual_lines_is_issued_as_before(self):
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 2); self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))

    def test_removing_the_lines_unblocks_the_draft(self):
        iid = self.draft_with(); self.save(iid, [])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?', (iid,)), 0)
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))

    def test_lifting_the_constant_is_the_only_thing_needed(self):
        iid = self.draft_with(); c = m.db()
        try:
            self.assertIn('2 ligne(s)', rules.manual_lines_issuance_problem(c, iid))
            rules.MANUAL_LINES_ISSUANCE_BLOCKED = False
            try: self.assertIsNone(rules.manual_lines_issuance_problem(c, iid))
            finally: rules.MANUAL_LINES_ISSUANCE_BLOCKED = True
        finally: c.close()
        self.assertFalse(self.shipped)                                                                                # the shipped value (rc39: issuance allowed)
        rules.MANUAL_LINES_ISSUANCE_BLOCKED = False
        try: self.flashes(); self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))
        finally: rules.MANUAL_LINES_ISSUANCE_BLOCKED = True


# ===================================================================================================================================================
class CreditOnLines(Base):
    def setUp(self):
        super().setUp()
        self.iid = self.issued_with()
        self.l1, self.l2 = self.line_ids(self.iid)
        self.inv_row = tuple(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0])
        self.inv_snap = tuple(self.sql('SELECT * FROM invoice_snapshots WHERE invoice_id=?', (self.iid,))[0])
        self.inv_pdf = self.c.get(f'/invoice/{self.iid}.pdf').data

    def assert_original_untouched(self):
        self.assertEqual(tuple(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0]), self.inv_row)
        self.assertEqual(tuple(self.sql('SELECT * FROM invoice_snapshots WHERE invoice_id=?', (self.iid,))[0]), self.inv_snap)
        self.assertEqual(self.c.get(f'/invoice/{self.iid}.pdf').data, self.inv_pdf)

    # --- amounts -----------------------------------------------------------------------------------------------------------------------
    def test_the_reference_invoice_is_what_the_docstring_says(self):
        a = rules.invoice_amounts(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0], rules.invoice_lines(m.db(), self.iid))
        self.assertEqual((a['ht'], a['lines_ht'], a['tva'], a['ttc']), (D('1300.00'), D('150.00'), D('113.40'), D('1563.40')))

    def test_total_credit_takes_the_service_and_both_lines_and_equals_the_invoice(self):
        cid = self.issued_cn(self.iid, scope='total'); row = self.cn(cid)
        self.assertEqual((row['qty'], row['unit_rate'], row['amount'], row['other_amount'], row['lines_taxed'], row['lines_untaxed']), (2.0, 650.0, 1300.0, 0.0, 100.0, 50.0))
        a = self.amounts(cid)
        self.assertEqual((a['ht'], a['lines_ht'], a['subtotal'], a['tva'], a['ttc']), (D('1300.00'), D('150.00'), D('1450.00'), D('113.40'), D('1563.40')))
        self.assertEqual(self.rows_of(cid)[0][1:], (self.l1, 1, 'Frais de déplacement', 100.0, 'soumis')); self.assertEqual(self.rows_of(cid)[1][1:], (self.l2, 2, 'Hébergement', 50.0, 'hors_tva'))
        c = m.db()
        try:
            self.assertTrue(credit_service.fully_credited(c, self.iid)); k = credit_service.creditable(c, c.execute('SELECT * FROM invoices WHERE id=?', (self.iid,)).fetchone())
        finally: c.close()
        self.assertEqual((k['remaining_ht'], k['remaining_lines'], k['remaining_ttc']), (D('0.00'), D('0.00'), D('0.00')))
        self.assert_original_untouched()

    def test_total_credit_with_an_autres_line_and_the_lines(self):
        iid = self.issued_with(other_amount='30', other_label='Frais divers', other_vat_mode='hors_tva', period=('2026-08-01', '2026-08-31'))
        cid = self.issued_cn(iid, scope='total'); a = self.amounts(cid)
        self.assertEqual((a['ht'], a['other'], a['lines_ht'], a['tva'], a['ttc']), (D('1300.00'), D('30.00'), D('150.00'), D('113.40'), D('1593.40')))
        c = m.db()
        try: self.assertTrue(credit_service.fully_credited(c, iid))
        finally: c.close()

    def test_a_partial_credit_of_one_line_is_an_amount_with_the_vat_of_that_line(self):
        cid, fl = self.credit(self.iid, scope='partial', **{f'cl_{self.l1}': '40'}); self.assertIn('Brouillon de note de crédit créé', fl)
        row = self.cn(cid); self.assertEqual((row['qty'], row['amount'], row['lines_taxed'], row['lines_untaxed']), (None, 0.0, 40.0, 0.0))
        a = self.amounts(cid); self.assertEqual((a['ht'], a['lines_ht'], a['tva'], a['ttc']), (D('0.00'), D('40.00'), D('3.24'), D('43.24')))
        self.assertEqual(self.rows_of(cid), [(cid, self.l1, 1, 'Frais de déplacement', 40.0, 'soumis')])
        cid2, fl = self.credit(self.iid, scope='partial', **{f'cl_{self.l2}': '20'}); a = self.amounts(cid2)
        self.assertEqual((a['lines_untaxed'], a['tva'], a['ttc']), (D('20.00'), D('0.00'), D('20.00')))              # « hors TVA »: no VAT on that line
        k = self.creditable(self.iid)      # drafts count against the cap too
        self.assertEqual((k['remaining_lines'], k['lines'][0]['remaining'], k['lines'][1]['remaining']), (D('90.00'), D('60.00'), D('30.00')))

    def test_a_service_credit_and_a_line_credit_in_one_note(self):
        cid, fl = self.credit(self.iid, scope='partial', qty='1', **{f'cl_{self.l2}': '50'}); self.assertIsNotNone(cid, fl)
        row = self.cn(cid); self.assertEqual((row['qty'], row['unit_rate'], row['amount'], row['lines_untaxed']), (1.0, 650.0, 650.0, 50.0))
        a = self.amounts(cid); self.assertEqual((a['ht'], a['lines_ht'], a['tva'], a['ttc']), (D('650.00'), D('50.00'), D('52.65'), D('752.65')))

    def test_the_vat_of_successive_credits_adds_up_to_the_vat_of_the_invoice(self):
        iid = self.issued_with(lines=[('Prestation annexe', '3', '11.11', 'piece', 'soumis'), L2], period=('2026-08-01', '2026-08-31'))      # 33.33 subject to VAT
        l1, l2 = self.line_ids(iid)
        for amt in ('11.11', '11.11'): self.issued_cn(iid, scope='partial', **{f'cl_{l1}': amt})
        self.issued_cn(iid, scope='partial', qty='1'); self.issued_cn(iid, scope='total')                      # the closing note takes the exact balance
        c = m.db()
        try:
            inv = c.execute('SELECT * FROM invoices WHERE id=?', (iid,)).fetchone(); full = rules.invoice_amounts_full(c, inv); done = credit_service.credited_on(c, iid, statuses=('issued',))
            self.assertEqual((done['tva'], done['ttc']), (full['tva'], full['ttc'])); self.assertTrue(credit_service.fully_credited(c, iid))
        finally: c.close()

    # --- caps: application ---------------------------------------------------------------------------------------------------------------
    def test_a_line_cannot_be_credited_beyond_its_amount_in_total_over_all_notes(self):
        self.assertIsNotNone(self.credit(self.iid, scope='partial', **{f'cl_{self.l1}': '40'})[0])
        cid, fl = self.credit(self.iid, scope='partial', **{f'cl_{self.l1}': '70'}); self.assertIsNone(cid)
        self.assertIn('dépasserait son montant', fl); self.assertIn('solde créditable', fl); self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_lines'), 1)                                  # nothing of the refused note was written
        self.assertIsNotNone(self.credit(self.iid, scope='partial', **{f'cl_{self.l1}': '60'})[0])               # exactly what is left
        self.assertIn('dépasserait', self.credit(self.iid, scope='partial', **{f'cl_{self.l1}': '0.01'})[1])

    def test_bad_values_are_refused(self):
        for raw, why in (('abc', 'invalide'), ('-5', 'négatives'), ('1e3', 'invalide'), ('100.01', 'dépasserait')):
            cid, fl = self.credit(self.iid, scope='partial', **{f'cl_{self.l1}': raw}); self.assertIsNone(cid, raw); self.assertIn(why, fl, raw)
        cid, fl = self.credit(self.iid, scope='partial'); self.assertIsNone(cid); self.assertIn('ligne manuelle à créditer', fl)
        cid, fl = self.credit(self.iid, scope='partial', **{f'cl_{self.l1}': '0'}); self.assertIsNone(cid)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 0)

    def test_a_total_credit_after_a_partial_one_takes_only_what_is_left(self):
        self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l1}': '100', f'cl_{self.l2}': '20'})
        cid = self.issued_cn(self.iid, scope='total'); a = self.amounts(cid); row = self.cn(cid)
        self.assertEqual((row['lines_taxed'], row['lines_untaxed']), (0.0, 30.0)); self.assertEqual(self.rows_of(cid), [(cid, self.l2, 2, 'Hébergement', 30.0, 'hors_tva')])
        self.assertEqual((a['ht'], a['tva']), (D('1300.00'), D('105.30')))
        cid2, fl = self.credit(self.iid, scope='total'); self.assertIsNone(cid2); self.assertIn('déjà entièrement créditée', fl)

    def test_a_credit_note_of_another_invoice_cannot_take_the_line(self):
        other = self.issued_with(lines=[('Autre ligne', '1', '10', 'flat', 'soumis')], period=('2026-08-01', '2026-08-31'))
        (lo,) = self.line_ids(other)
        cid, fl = self.credit(self.iid, scope='partial', **{f'cl_{lo}': '5'}); self.assertIsNone(cid)               # the field of a line of another invoice is not read at all
        self.assertIn('ligne manuelle à créditer', fl)

    # --- caps: SQL triggers --------------------------------------------------------------------------------------------------------------
    def test_sql_guards_on_the_rows(self):
        cid, _ = self.credit(self.iid, scope='partial', **{f'cl_{self.l1}': '100'}); self.assertIsNotNone(cid)          # L1 fully credited by this draft note
        cid2, _ = self.credit(self.iid, scope='partial', **{f'cl_{self.l2}': '10'}); self.assertIsNotNone(cid2)
        ins = "INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,position,description,amount,vat_mode,created_at) VALUES(%d,%d,%d,'x',%s,'%s','')"
        self.assertIn('exceed', self.raw(ins % (cid2, self.l1, 3, '0.01', 'soumis')))                                  # the cap counts the drafts of other notes
        self.assertIn('VAT regime', self.raw(ins % (cid2, self.l2, 3, '1', 'soumis')))                                 # L2 is « hors TVA »
        other = self.draft_with(lines=[('Autre', '1', '10', 'flat', 'soumis')], period=('2026-10-01', '2026-10-31')); (lo,) = self.line_ids(other)
        self.assertIn('belongs to the invoice', self.raw(ins % (cid2, lo, 4, '1', 'soumis')))
        self.assertIn('CHECK', self.raw(ins % (cid2, self.l2, 5, '0', 'hors_tva')))
        self.assertIn('CHECK', self.raw(ins % (cid2, self.l2, 5, '-1', 'hors_tva')))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_lines'), 2)                                      # nothing slipped through

    def test_rows_of_an_issued_note_are_immutable_and_the_totals_must_match_at_issuance(self):
        cid = self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l1}': '40'})
        self.assertIn('immutable', self.raw("UPDATE credit_note_lines SET amount=1 WHERE credit_note_id=%d" % cid))
        self.assertIn('cannot be deleted', self.raw("DELETE FROM credit_note_lines WHERE credit_note_id=%d" % cid))
        self.assertIn('immutable', self.raw("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,position,description,amount,vat_mode,created_at) VALUES(%d,%d,2,'x',1,'hors_tva','')" % (cid, self.l2)))
        cid2, _ = self.credit(self.iid, scope='partial', **{f'cl_{self.l2}': '10'})
        self.raw("UPDATE credit_notes SET lines_untaxed=11 WHERE id=%d" % cid2)                                          # totals no longer equal the sum of the rows
        self.assertIn('line totals', self.raw("UPDATE credit_notes SET status='issued',reference='X-1',issued_at='2026-10-26T10:00:00' WHERE id=%d" % cid2))
        st, fl = self.issue_cn(cid2); self.assertEqual(st, 'draft'); self.assertIn('refusée', fl)

    def test_the_cap_of_refunds_and_imputations_counts_the_lines(self):
        cid = self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l1}': '100', f'cl_{self.l2}': '50'}); a = self.amounts(cid)
        self.assertEqual(a['ttc'], D('158.10'))                                                                          # 100 + 8.10 VAT + 50 without VAT
        self.flashes(); self.c.post(f'/credit/{cid}/refund', data={'amount': '158.10', 'executed_on': TODAY}); self.assertIn('Remboursement enregistré', ' '.join(self.flashes()))
        self.assertEqual(credit_service.position(m.db(), self.cn(cid))['status'], 'remboursée')
        self.assertIn('cannot exceed', self.raw("INSERT INTO credit_operations(credit_note_id,kind,amount,executed_on,created_at) VALUES(%d,'refund',0.10,'%s','')" % (cid, TODAY)))

    def test_the_operations_cap_trigger_is_the_new_one_after_a_restart(self):
        self.assertIn('lines_taxed', self.scalar("SELECT sql FROM sqlite_master WHERE name='credit_ops_within_note'"))
        m.init(); m.init()
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name='credit_ops_within_note'"), 1)

    # --- documents -----------------------------------------------------------------------------------------------------------------------
    def test_the_credit_note_pdf_prints_the_credited_lines_and_totals(self):
        cid = self.issued_cn(self.iid, scope='total'); t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        for needle in ('NOTE DE CRÉDIT', f'NC-{YEAR}-1', 'Frais de déplacement', 'Hébergement', '100,00 CHF', '50,00 CHF', 'SOUS-TOTAL CRÉDITÉ', '1 450,00 CHF', 'TVA', '113,40 CHF',
                       'TOTAL EN VOTRE FAVEUR', '1 563,40 CHF'):
            self.assertIn(needle, t)
        h = json.loads(self.scalar('SELECT header_json FROM credit_note_snapshots WHERE credit_note_id=?', (cid,)))
        self.assertEqual([(l['position'], l['description'], l['amount'], l['vat_mode']) for l in h['lines']], [(1, 'Frais de déplacement', '100.00', 'soumis'), (2, 'Hébergement', '50.00', 'hors_tva')])
        self.assertEqual(h['amounts']['lines_ht'], '150.00')
        frozen = self.c.get(f'/credit/{cid}.pdf').data
        c = sqlite3.connect(self.db); c.execute('DROP TRIGGER credit_lines_no_update_issued'); c.execute("UPDATE credit_note_lines SET description='Modifiée hors application'"); c.commit(); c.close()
        self.assertEqual(self.c.get(f'/credit/{cid}.pdf').data, frozen)                                                  # the issued PDF is frozen: it never reads the table again

    def test_a_lines_only_credit_prints_no_empty_service_row(self):
        cid = self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l2}': '20'}); t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        self.assertIn('Hébergement', t); self.assertIn('20,00 CHF', t)
        h = invoice_service.credit_data(m.db(), cid); self.assertEqual([l['description'] for l in pdf_layout._credit_lines(h, h['amounts'], h['invoice'], 'AUTRES')], ['Hébergement'])

    def test_the_draft_note_shows_its_lines_and_the_detail_page_lists_them(self):
        cid, _ = self.credit(self.iid, scope='partial', **{f'cl_{self.l1}': '40'}); t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        self.assertIn('Frais de déplacement', t); self.assertIn('BROUILLON', t)
        html = H.unescape(self.c.get(f'/credit/{cid}').get_data(as_text=True)); self.assertIn('Lignes manuelles créditées', html); self.assertIn('Frais de déplacement', html)

    def test_the_credit_form_lists_the_lines_with_what_is_left(self):
        html = H.unescape(self.c.get(f'/invoice/{self.iid}/credit').get_data(as_text=True))
        self.assertIn('id="creditLines"', html); self.assertIn(f'name="cl_{self.l1}"', html); self.assertIn(f'name="cl_{self.l2}"', html); self.assertIn('Hébergement', html)
        self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l1}': '100'})
        html = H.unescape(self.c.get(f'/invoice/{self.iid}/credit').get_data(as_text=True)); self.assertNotIn(f'name="cl_{self.l1}"', html); self.assertIn('entièrement créditée', html)

    def test_a_note_that_does_not_fit_on_its_page_is_refused_whole(self):
        old = pdf_layout.PAGE_ONE_LIMIT; pdf_layout.PAGE_ONE_LIMIT = 100.0
        try:
            cid, fl = self.credit(self.iid, scope='total'); self.assertIsNone(cid); self.assertIn('ne tient pas sur une page', fl)
        finally: pdf_layout.PAGE_ONE_LIMIT = old
        self.assertEqual((self.scalar('SELECT COUNT(*) FROM credit_notes'), self.scalar('SELECT COUNT(*) FROM credit_note_lines')), (0, 0))
        self.assertIsNotNone(self.credit(self.iid, scope='total')[0])

    def test_six_two_line_lines_are_credited_on_one_page(self):
        lines = [(f'Frais de coordination logistique et de suivi administratif {n}', '1', str(10 + n), 'flat', 'soumis' if n % 2 else 'hors_tva') for n in range(6)]
        iid = self.issued_with(lines=lines, period=('2026-08-01', '2026-08-31'))
        cid = self.issued_cn(iid, scope='total'); self.assertEqual(len(self.rows_of(cid)), 6)
        h = invoice_service.credit_data(m.db(), cid); self.assertLessEqual(pdf_layout.credit_page_bottom(h), pdf_layout.PAGE_ONE_LIMIT)
        t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        self.assertEqual(t.count('Frais de coordination logistique'), 6)       # one row per credited line (the wrap may split the end of a description)

    # --- cancellation and replacement ---------------------------------------------------------------------------------------------------------
    def test_a_cancelled_note_frees_its_lines_and_its_cancellation_document_lists_them(self):
        cid = self.issued_cn(self.iid, scope='total')
        self.flashes(); self.c.post(f'/credit/{cid}/cancel', data={'reason': 'erreur de saisie (test)'}); self.assertIn('annulée', ' '.join(self.flashes()))
        t = pdf_text(self.c.get(f'/credit/{cid}/cancellation.pdf').data)
        for needle in ('ANNULATION DE NOTE DE CRÉDIT', f'ANN-NC-{YEAR}-1', 'Frais de déplacement', 'Hébergement', 'TOTAL ANNULÉ', '1 563,40 CHF'): self.assertIn(needle, t)
        c = m.db()
        try: self.assertFalse(credit_service.fully_credited(c, self.iid))
        finally: c.close()
        k = self.creditable(self.iid); self.assertEqual((k['remaining_lines'], k['credited_lines']), (D('150.00'), D('0.00')))     # the lines are creditable again
        cid2, fl = self.credit(self.iid, scope='total', replaces_credit_id=str(cid)); self.assertIsNotNone(cid2, fl)
        self.assertEqual(self.rows_of(cid2)[0][4], 100.0)
        self.assertEqual(self.rows_of(cid)[0][4], 100.0)                                                                  # the cancelled note keeps its rows (history)

    def test_deleting_a_draft_note_deletes_its_rows(self):
        cid, _ = self.credit(self.iid, scope='total'); self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_lines'), 2)
        self.flashes(); self.c.post(f'/credit/{cid}/delete'); self.assertIn('supprimé', ' '.join(self.flashes()))
        self.assertEqual((self.scalar('SELECT COUNT(*) FROM credit_notes'), self.scalar('SELECT COUNT(*) FROM credit_note_lines')), (0, 0))
        self.assertEqual(self.creditable(self.iid)['remaining_lines'], D('150.00'))

    # --- settlement ----------------------------------------------------------------------------------------------------------------------
    def test_offset_targets_are_measured_with_their_manual_lines(self):
        cid = self.issued_cn(self.iid, scope='total', treatment='compensation')
        target = self.draft_with(lines=[('Frais cible', '1', '200', 'flat', 'soumis')], period=('2026-10-01', '2026-10-31'), qty='1')
        self.flashes(); self.c.post(f'/credit/{cid}/offset', data={'target_invoice_id': str(target), 'amount': '1000'}); fl = H.unescape(' '.join(self.flashes()))
        self.assertIn('dépasse le montant restant dû sur la facture cible', fl); self.assertIn('918,85', fl)             # (650 + 200) × 1.081
        self.c.post(f'/credit/{cid}/offset', data={'target_invoice_id': str(target), 'amount': '918.85'}); self.assertIn('Imputation enregistrée', ' '.join(self.flashes()))

    def test_refund_of_a_total_credit_on_lines(self):
        cid = self.issued_cn(self.iid, scope='total')
        self.flashes(); self.c.post(f'/credit/{cid}/refund', data={'amount': '1563.40', 'executed_on': TODAY}); self.assertIn('Remboursement enregistré', ' '.join(self.flashes()))
        self.assertEqual(credit_service.position(m.db(), self.cn(cid))['status'], 'remboursée')

    # --- exports --------------------------------------------------------------------------------------------------------------------------
    def test_the_turnover_and_the_archive_count_the_credited_lines(self):
        cid = self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l1}': '100', f'cl_{self.l2}': '50'})
        with m.db() as c: docs = [d for d in gsheet_export.documents(c) if d['kind'] == 'credit']
        self.assertEqual((docs[0]['ht'], docs[0]['days']), (D('-150.00'), 0.0))
        with m.db() as c: fc = m.forecast_mod.build(c, local_today())
        self.assertEqual(next(y for y in fc['years'] if y['year'] == str(YEAR))['actual'], D('1300.00'))                 # 1450 invoiced − 150 credited
        z = zipfile.ZipFile(io.BytesIO(self.c.get('/archive.zip').data)); idx = z.read([n for n in z.namelist() if n.endswith('.csv')][0]).decode('utf-8-sig').splitlines()
        row = next(r for r in idx if r.startswith('note de crédit')); self.assertIn('-150.00', row); self.assertIn('-158.10', row)

    def test_the_credit_listing_shows_the_credit(self):
        self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l1}': '100'})
        html = H.unescape(self.c.get('/?tab=archive').get_data(as_text=True)); self.assertIn(f'NC-{YEAR}-1', html); self.assertIn('créditée partiellement', html)

    # --- backup / restore ------------------------------------------------------------------------------------------------------------------
    def test_credited_lines_survive_a_json_backup_and_restore(self):
        cid = self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l1}': '60'}); before = [tuple(r) for r in self.sql('SELECT * FROM credit_note_lines ORDER BY id')]
        pdf = self.c.get(f'/credit/{cid}.pdf').data; raw = self.c.get('/backup').data
        draft, _ = self.credit(self.iid, scope='partial', **{f'cl_{self.l2}': '10'}); self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_lines'), 2)   # later work
        r = self.c.post('/restore', data={'backup': (io.BytesIO(raw), 'sauvegarde.json')}, content_type='multipart/form-data')
        token = r.headers['Location'].rsplit('/', 1)[-1]; self.flashes()
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'}); self.assertIn('Restauration effectuée', ' '.join(self.flashes()))
        self.assertEqual([tuple(r) for r in self.sql('SELECT * FROM credit_note_lines ORDER BY id')], before)
        self.assertEqual(self.c.get(f'/credit/{cid}.pdf').data, pdf); self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 1)
        self.assertIn('immutable', self.raw("UPDATE credit_note_lines SET amount=1"))                                  # the guards are back after the rebuild

    def test_restore_order_holds_the_rows_between_the_notes_and_their_snapshots(self):
        from app import restore_service
        o = restore_service.ORDER
        self.assertLess(o.index('credit_notes'), o.index('credit_note_lines')); self.assertLess(o.index('credit_note_lines'), o.index('credit_note_snapshots'))
        self.assertLess(o.index('invoice_lines'), o.index('credit_note_lines'))


# ===================================================================================================================================================
class Migration(Base):
    def test_additive_migration_from_the_rc37_shape(self):
        iid = self.issued_with(lines=()); cid = self.issued_cn(iid, scope='partial', amount='100')                  # a credit note of rc37 (no manual line)
        c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
        for t in ('credit_lines_totals_match', 'credit_ops_within_note'): c.execute(f'DROP TRIGGER {t}')
        c.execute('DROP TABLE credit_note_lines')
        for col in ('lines_taxed', 'lines_untaxed'): c.execute(f'ALTER TABLE credit_notes DROP COLUMN {col}')
        c.execute("""CREATE TRIGGER credit_ops_within_note BEFORE INSERT ON credit_operations WHEN NEW.kind IN ('refund','offset') AND
    COALESCE((SELECT SUM(CASE WHEN kind IN ('refund','offset') THEN amount ELSE -amount END) FROM credit_operations WHERE credit_note_id=NEW.credit_note_id),0)+NEW.amount >
    (SELECT (amount+COALESCE(other_amount,0))*(1+COALESCE(vat,0)/100.0)+0.05 FROM credit_notes WHERE id=NEW.credit_note_id)
    BEGIN SELECT RAISE(ABORT,'The operations of a credit note cannot exceed its amount'); END;""")
        c.commit()
        width = len([r[1] for r in c.execute('PRAGMA table_info(credit_notes)')])
        before = {t: [tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in ('invoices', 'invoice_snapshots', 'credit_notes', 'credit_note_snapshots', 'credit_operations', 'invoice_lines', 'audit')}
        self.assertTrue(schema_checks.rc19_problems(c))                                                              # the rc38 checks see the rc37 shape
        c.close()
        m.init(); m.init()                                                                                          # restart twice
        c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
        try:
            now = {t: [tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in before}
            for t in ('invoices', 'invoice_snapshots', 'credit_note_snapshots', 'credit_operations', 'invoice_lines', 'audit'): self.assertEqual(now[t], before[t], t)
            self.assertEqual([r[:width] for r in now['credit_notes']], before['credit_notes']); self.assertEqual([r[width:] for r in now['credit_notes']], [(0.0, 0.0)])
            self.assertEqual(schema_checks.rc19_problems(c), [])
            self.assertIn('lines_taxed', c.execute("SELECT sql FROM sqlite_master WHERE name='credit_ops_within_note'").fetchone()[0])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'credit_lines_%'").fetchone()[0], 7)
        finally: c.close()
        pos = credit_service.position(m.db(), self.cn(cid)); self.assertEqual(pos['ttc'], D('108.10'))                # the note of rc37 reads as before
        self.assertEqual(self.amounts(cid)['lines_ht'], D('0.00'))


if __name__ == '__main__':
    unittest.main()
