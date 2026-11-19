"""V9.2-rc25 (owner decisions of 2026-10-09): regression tests of the six billing defects B-01 … B-06 found by the independent audit.

B-01 / decision 3   check 14: the net quantity invoiced, cumulated, never exceeds the quantity worked, cumulated. NOT derogable (D8 limits the exceptions to
                    checks 12 and 13; no business decision extends it): no written reason, for 14 or for 12, issues an invoice that fails it
B-02 / decisions 1+2  an entry belongs to the first issued invoice that really billed it; a date moved afterwards never allows a second billing and never
                    changes the issued invoice; a late entry is not attributed to a later invoice just because its cumulative annex lists it
B-03 / decision 3   overriding check 12 (even together with a reason typed for 14) never issues an invoice that fails check 14
B-04 / decision 4   a period is invoiced again only when the previous invoice is entirely credited by ISSUED, non-cancelled credit notes; full history kept
B-05 / decision 5   the reliquat is bounded by the end of the invoice's own period: catch-up invoices in both chronological orders
B-06 / decision 6   zero over-billing tolerance (exception explicit and audited), 0.5 day under-billing tolerance (removed in rc41: zero both ways); the test helper no longer
                    overrides checks by default
Synthetic data only, on a COPY of the staging database (see test_import.py for the run command). Periods stay in the past: the tests do not depend on the clock.
"""
import json, sqlite3

import app.app as m
from tests.test_functional import derogations
from tests.test_rc19 import RC19, text


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N (year of the invoice date = today's year, then the sequence of the year)


class RC25(RC19):
    def sql_exec(self, q, args=()):
        c = sqlite3.connect(self.db); c.execute(q, args); c.commit(); c.close()

    def checks(self, iid):
        c = m.db()
        try: return {x['n']: x for x in m.invoice_checks.run_checks(c, iid)}
        finally: c.close()

    def failing(self, iid): return sorted(n for n, x in self.checks(iid).items() if x['status'] == 'fail')

    def status(self, iid): return self.scalar('SELECT status FROM invoices WHERE id=?', (iid,))

    def derogation_audit(self):
        return [json.loads(r['detail']) for r in self.sql("SELECT detail FROM audit WHERE event='invoice_check_derogation' ORDER BY id")]

    def owners(self, pid=None):
        c = m.db()
        try: return m.post_billing.owners(c, pid or self.pid)
        finally: c.close()

    def credit(self, iid, **kw):
        form = dict({'reason': 'erreur de facturation', 'treatment': 'remboursement'}, **kw)
        self.flashes(); self.c.post(f'/invoice/{iid}/credit', data=form)
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.flashes()
        self.c.post(f'/credit/{cid}/issue'); fl = self.flashes()
        self.assertEqual(self.scalar('SELECT status FROM credit_notes WHERE id=?', (cid,)), 'issued', fl)
        return cid

    def historical(self, pid, days, date, ref):
        self.sql_exec("""INSERT INTO historical_invoices(project_id,source_file,source_sheet,source_cell,invoice_date,invoice_ref,qty_days,basis,status,created_at,validated_at,validated_by)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (pid, 'SUIVI.xlsx', 'SUIVI 2026', 'Q12', date, ref, days, 'days', 'validated', date, date, 'admin'))


class TestHelper(RC25):
    def test_the_helper_overrides_no_check_by_default(self):
        self.assertEqual(derogations(), {}); self.assertEqual(self.DEROGATE, ())
        self.assertEqual(derogations(12, 14), {'derogation_12': 'jeu de données de test : exception voulue du contrôle 12',
                                               'derogation_14': 'jeu de données de test : exception voulue du contrôle 14'})


class B01_Check14(RC25):
    """Registry (historical) invoice + a Time Billing invoice for the same work: 2 days worked, 4 days invoiced."""
    def world(self):
        self.entry(self.pid, '2026-09-01', 8); self.entry(self.pid, '2026-09-02', 8)
        self.historical(self.pid, 2, '2026-10-01', '2026-09')           # issued outside the application on 01.10 for September
        return self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0]

    def test_check_14_fails_names_the_excess_and_is_not_derogable(self):
        iid = self.world(); ck = self.checks(iid)
        self.assertEqual(self.failing(iid), [14]); self.assertFalse(ck[14]['derogable'])
        self.assertIn('excédent 2', ck[14]['detail']); self.assertIn('aucune dérogation possible', ck[14]['detail']); self.assertEqual(len(ck), 14)
        self.assertEqual(sorted(n for n, x in ck.items() if x['derogable'] is False and x['status'] == 'fail'), [14])
        self.assertEqual(m.invoice_checks.DEROGABLE, (12, 13))

    def test_no_written_reason_issues_it(self):
        iid = self.world(); self.flashes()
        for given in ((), (12,), (13,), (14,), (12, 13, 14)):
            self.issue(iid, derogate=given); fl = ' '.join(self.flashes())
            self.assertEqual(self.status(iid), 'draft', given); self.assertIn('14.', fl)
        self.c.post(f'/issue/{iid}', data={'reliquat_treatment': 'reporte', 'derogation_14': 'accord du client confirmé par courriel du 5 octobre'})
        self.assertEqual(self.status(iid), 'draft')
        self.assertEqual(self.derogation_audit(), [])
        self.assertEqual(self.sql("SELECT COUNT(*) n FROM audit WHERE event='invoice_issued'")[0]['n'], 0)

    def test_the_issue_page_blocks_and_offers_no_reason_field(self):
        iid = self.world(); page = text(self.c.get(f'/issue/{iid}'))
        self.assertIn('Émission impossible', page); self.assertNotIn('name="derogation_14"', page); self.assertNotIn('name="derogation_12"', page)
        self.assertRegex(page, r'<button disabled>Émettre')

    def test_the_exit_is_to_correct_the_data_and_the_history_is_kept(self):
        iid = self.world(); hid = self.scalar('SELECT id FROM historical_invoices')
        self.flashes(); self.c.post(f'/historique/{hid}/statut', data={'statut': 'rejected', 'motif': 'doublon de la facture 2026-09 émise dans Time Billing'})
        self.assertEqual(self.scalar('SELECT status FROM historical_invoices WHERE id=?', (hid,)), 'rejected', self.flashes())   # rejected, never deleted
        self.assertEqual(self.failing(iid), [])
        self.issue(iid); self.assertEqual(self.status(iid), 'issued', self.flashes())
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM historical_invoices'), 1)

    def test_a_catch_up_is_not_weighed_by_invoices_of_later_periods(self):
        self.entry(self.pid, '2026-07-10', 8); self.entry(self.pid, '2026-08-10', 8)
        self.issued(self.pid, '2026-08-01', '2026-08-31', 1, treatment='reporte')
        iid = self.draft(self.pid, '2026-07-01', '2026-07-31', 1)[0]
        self.assertEqual(self.failing(iid), [])                                                      # through July: 1 j invoiced for 1 j worked


class B03_Check12CannotBypass14(RC25):
    def test_overriding_12_never_opens_14(self):
        self.entry(self.pid, '2026-08-20', 8); self.entry(self.pid, '2026-09-10', 4)
        f8 = self.issued(self.pid, '2026-08-01', '2026-08-31', 1)
        s = self.scalar("SELECT id FROM entries WHERE work_date='2026-08-20'")
        self.edit(s, work_date='2026-09-15', reason='mauvaise date', confirm_billed='1')
        f9 = self.draft(self.pid, '2026-09-01', '2026-09-30', 1.5)[0]                               # 2.5 j invoiced for 1.5 j worked
        self.assertEqual(self.failing(f9), [12, 14]); self.flashes()
        for given in ((12,), (14,), (12, 14), (12, 13, 14)):
            self.issue(f9, derogate=given); fl = ' '.join(self.flashes())
            self.assertEqual(self.status(f9), 'draft', given); self.assertIn('14.', fl)
        self.assertEqual(self.derogation_audit(), [])
        self.assertEqual(self.status(f8), 'issued')
        self.c.post(f'/invoice/{f9}/delete'); self.flashes()
        f9 = self.draft(self.pid, '2026-09-01', '2026-09-30', 0.5)[0]                               # the quantity the work supports needs no exception
        self.assertEqual(self.failing(f9), []); self.issue(f9); self.assertEqual(self.status(f9), 'issued', self.flashes())


class B02_Ownership(RC25):
    def test_a_date_moved_after_billing_never_allows_a_second_billing_nor_changes_the_invoice(self):
        self.entry(self.pid, '2026-08-20', 8, 'S'); self.entry(self.pid, '2026-09-10', 4, 'T')
        f8 = self.issued(self.pid, '2026-08-01', '2026-08-31', 1); s = self.eid('S')
        before = self.frozen_state(f8)
        r, fl = self.edit(s, work_date='2026-09-15', reason='mauvaise date', confirm_billed='1'); self.assertIn('modifiée', fl)
        self.assertEqual(self.owners()[s]['id'], f8)                                               # still the first invoice that billed it
        st, sug = self.suggest(self.pid, '2026-09-01', '2026-09-30')
        self.assertEqual((sug['hours'], sug['already_billed_hours'], sug['suggested_qty']), (12.0, 8.0, 0.5))
        f9 = self.draft(self.pid, '2026-09-01', '2026-09-30', 1.5)[0]                               # the whole September hours: a second billing of S
        self.assertEqual(self.failing(f9), [12, 14]); self.flashes()
        self.issue(f9); self.assertEqual(self.status(f9), 'draft')
        self.c.post(f'/invoice/{f9}/delete'); self.flashes()
        f9 = self.draft(self.pid, '2026-09-01', '2026-09-30', 0.5)[0]
        self.assertEqual(self.failing(f9), [])                                                       # the right quantity needs no exception
        self.issue(f9); self.assertEqual(self.status(f9), 'issued', self.flashes())
        self.assertEqual(self.derogation_audit(), [])
        h9 = m.invoice_service.frozen_header(m.db(), f9)
        self.assertEqual((h9['period_hours'], h9['period_billed_elsewhere']), (4.0, [self.scalar('SELECT number FROM invoices WHERE id=?', (f8,))]))
        self.assertEqual(self.frozen_state(f8), before)                                              # the issued invoice never changed, PDF bytes included
        self.assertEqual(self.owners()[s]['id'], f8)

    def test_a_billed_entry_moved_beyond_the_next_period_keeps_blocking_the_next_invoice_by_check_14(self):
        """Owner decision O2 (Q1, 2026-10-11): check 14 stays as it is. S (8 h) is billed on August, then its date is moved to October: the legitimate September
        invoice (T, 4 h = 0.5 j) is blocked, not derogable — the way out is to fix the date or to credit, never an exception."""
        self.entry(self.pid, '2026-08-20', 8, 'S'); self.entry(self.pid, '2026-09-10', 4, 'T')
        f8 = self.issued(self.pid, '2026-08-01', '2026-08-31', 1); s = self.eid('S')
        r, fl = self.edit(s, work_date='2026-10-15', reason='mauvaise date', confirm_billed='1'); self.assertIn('modifiée', fl)
        self.assertEqual(self.owners()[s]['id'], f8)                                                 # S still belongs to the August invoice
        f9 = self.draft(self.pid, '2026-09-01', '2026-09-30', 0.5)[0]                               # exactly what September supports
        self.assertIn(14, self.failing(f9)); self.flashes()                                          # 1 j (August) + 0.5 j > 0.5 j worked through September
        for given in ((), (12,), (14,), (12, 13, 14)):
            self.issue(f9, derogate=given); fl = ' '.join(self.flashes())
            self.assertEqual(self.status(f9), 'draft', given); self.assertIn('14.', fl)
        self.assertEqual(self.derogation_audit(), [])
        self.edit(s, work_date='2026-08-20', reason='date rétablie', confirm_billed='1'); self.flashes()   # the way out: put the date back
        self.assertEqual(self.failing(f9), [])
        self.issue(f9); self.assertEqual(self.status(f9), 'issued', self.flashes())

    def test_variance_and_credit_proposal_follow_the_owner(self):
        self.entry(self.pid, '2026-08-20', 8, 'S'); self.entry(self.pid, '2026-09-10', 4, 'T')
        f8 = self.issued(self.pid, '2026-08-01', '2026-08-31', 1); s = self.eid('S')
        self.edit(s, work_date='2026-09-15', reason='mauvaise date', confirm_billed='1')
        f9 = self.issued(self.pid, '2026-09-01', '2026-09-30', 0.5)
        self.edit(s, manual_hours='6', reason='durée réelle', confirm_billed='1')
        v8, v9 = self.variance(f8), self.variance(f9)
        self.assertEqual((v8['variance_hours'], v8['remaining_units'], v8['needs_decision']), (-2, -0.25, True))   # the owner carries the credit-note proposal
        self.assertEqual((v9['variance_hours'], v9['changed'], v9['needs_decision']), (0, [], False))            # F09 did not bill S: no variance, no proposal
        self.assertEqual([x['id'] for x in v9['earlier_changed']], [s])                                          # shown for information (listed by F09's annex), not part of its variance

    def test_a_late_entry_is_not_attributed_to_the_next_invoice_by_its_cumulative_annex(self):
        self.entry(self.pid, '2026-07-10', 8, 'J'); self.entry(self.pid, '2026-08-10', 8, 'A')
        f7 = self.issued(self.pid, '2026-07-01', '2026-07-31', 1)
        self.entry(self.pid, '2026-07-15', 8, 'L'); late = self.eid('L')                              # added after July was issued, into July
        c = m.db()
        try: rel = m.issue_context(c, self.draft(self.pid, '2026-08-01', '2026-08-31', 1)[0])['reliquat']
        finally: c.close()
        self.assertEqual(rel, 1.0)                                                                    # the late day is still unbilled
        f8 = self.scalar('SELECT MAX(id) FROM invoices'); self.flashes()
        self.issue(f8, treatment='offert'); self.assertEqual(self.status(f8), 'issued', self.flashes())
        self.assertNotIn(late, self.owners())                                                         # listed by F08's annex, billed by nobody
        c = m.db()
        try: roles = [(x['number'], x['role']) for x in m.post_billing.entry_invoices(c, late)]
        finally: c.close()
        self.assertEqual(roles, [(self.scalar('SELECT number FROM invoices WHERE id=?', (f8,)), 'annex')])
        r, fl = self.delete(late)                                                                     # no billed entry: no reason needed
        self.assertIn('supprimée', fl)
        v = self.variance(f8)
        self.assertEqual((v['changed'], v['variance_hours'], v['remaining_units'], v['needs_decision']), ([], 0, 0, False))   # no credit note is proposed on F08
        self.assertEqual(self.variance(f7)['changed'], [])

    def test_a_late_entry_taken_up_by_a_larger_quantity_is_an_explicit_exception(self):
        self.entry(self.pid, '2026-07-10', 8, 'J'); self.entry(self.pid, '2026-08-10', 8, 'A')
        self.issued(self.pid, '2026-07-01', '2026-07-31', 1)
        self.entry(self.pid, '2026-07-15', 8, 'L')
        f8 = self.draft(self.pid, '2026-08-01', '2026-08-31', 2)[0]                                   # bills the late day too, by hand
        self.assertEqual(self.failing(f8), [12])                                                      # over-billing against the period: reason required
        self.issue(f8); self.assertEqual(self.status(f8), 'draft')
        self.issue(f8, derogate=(12,)); self.assertEqual(self.status(f8), 'issued', self.flashes())
        self.assertEqual([r['check'] for r in self.derogation_audit()], [12])
        # LIMIT OF PROOF (documented in post_billing.owners): the quantity was typed by hand, and an annex plus a period do not prove that it covers L.
        # The late entry therefore stays without owner even though the quantity was raised on purpose: it is never silently attributed.
        late = self.eid('L'); self.assertNotIn(late, self.owners())
        r, fl = self.delete(late); self.assertIn('supprimée', fl)
        self.assertEqual(self.variance(f8)['changed'], [])


class B04_CreditThenReissue(RC25):
    def setUp(self):
        super().setUp()
        self.entry(self.pid, '2026-08-10', 8, 'août')
        self.f1 = self.issued(self.pid, '2026-08-01', '2026-08-31', 1)

    def refused(self):
        iid, fl = self.draft(self.pid, '2026-08-01', '2026-08-31', 1)
        return 'chevauche' in ' '.join(fl)

    def test_partial_or_draft_credit_keeps_the_period_blocked(self):
        self.assertTrue(self.refused())
        self.flashes(); self.c.post(f'/invoice/{self.f1}/credit', data={'reason': 'x', 'treatment': 'remboursement', 'qty': '0.5'})   # a DRAFT credit note
        self.assertTrue(self.refused())
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue'); self.flashes()                    # issued: half of the invoice
        self.assertTrue(self.refused())
        c = m.db()
        try: self.assertFalse(m.credits.fully_credited(c, self.f1))
        finally: c.close()

    def test_total_credit_allows_a_new_invoice_and_keeps_every_document(self):
        before = self.frozen_state(self.f1)
        cid = self.credit(self.f1, scope='total')
        self.assertFalse(self.refused())
        self.c.post(f'/invoice/{self.scalar("SELECT MAX(id) FROM invoices")}/delete'); self.flashes()
        f2 = self.draft(self.pid, '2026-08-01', '2026-08-31', 1)[0]
        self.assertEqual(self.failing(f2), [])                                                       # 1 j invoiced, 1 j credited, 1 j worked: no exception needed
        self.issue(f2); self.assertEqual(self.status(f2), 'issued', self.flashes())
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (f2,)), f'{YEAR}-2')
        self.assertEqual(self.frozen_state(self.f1), before)                                         # F1: row, snapshot, annex links, PDF bytes untouched
        self.assertEqual(self.scalar("SELECT status FROM credit_notes WHERE id=?", (cid,)), 'issued')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices WHERE status="issued"'), 2)
        e = self.eid('août'); self.assertEqual(self.owners()[e]['id'], f2)                           # the re-issued invoice bills the entry, once
        self.assertEqual(self.variance(self.f1)['billed_rows'], [])

    def test_cancelling_the_credit_note_is_refused_once_the_period_was_invoiced_again(self):
        cid = self.credit(self.f1, scope='total')
        f2 = self.draft(self.pid, '2026-08-01', '2026-08-31', 1)[0]; self.issue(f2); self.assertEqual(self.status(f2), 'issued', self.flashes())
        self.flashes(); self.c.post(f'/credit/{cid}/cancel', data={'reason': 'erreur de saisie'}); fl = ' '.join(self.flashes())
        self.assertIn('double facturation', fl); self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_cancellations'), 0)

    def test_cancelling_the_credit_note_before_a_new_invoice_blocks_the_period_again(self):
        cid = self.credit(self.f1, scope='total'); self.assertFalse(self.refused())
        self.c.post(f'/invoice/{self.scalar("SELECT MAX(id) FROM invoices")}/delete'); self.flashes()
        self.c.post(f'/credit/{cid}/cancel', data={'reason': 'avoir émis par erreur'}); self.flashes()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_cancellations'), 1)
        self.assertTrue(self.refused())                                                              # F1 stands again: no second invoice for its period

    def test_the_issue_step_applies_the_same_rule(self):
        self.credit(self.f1, scope='total')
        f2 = self.draft(self.pid, '2026-08-01', '2026-08-31', 1)[0]
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 1)
        c = m.db()
        try: self.assertIsNone(m.credits.period_clash(c, self.pid, '2026-08-01', '2026-08-31', exclude_id=f2))
        finally: c.close()
        self.issue(f2); self.assertEqual(self.status(f2), 'issued', self.flashes())


class B05_CatchUp(RC25):
    def entries(self, pid):
        for d in ('2026-07-10', '2026-07-11', '2026-08-10', '2026-08-11'): self.entry(pid, d, 8)

    def reliquat(self, iid): return self.scalar('SELECT reliquat_days FROM invoices WHERE id=?', (iid,))

    def test_chronological_order(self):
        self.entries(self.pid)
        jul = self.issued(self.pid, '2026-07-01', '2026-07-31', 2); aug = self.issued(self.pid, '2026-08-01', '2026-08-31', 2)
        self.assertEqual((self.reliquat(jul), self.reliquat(aug)), (0, 0))

    def test_catch_up_issued_after_a_later_period(self):
        self.entries(self.pid2)
        aug = self.issued(self.pid2, '2026-08-01', '2026-08-31', 2)
        self.assertEqual(self.reliquat(aug), 2)                                                      # July (2 j) is still to bill when August is issued
        jul = self.draft(self.pid2, '2026-07-01', '2026-07-31', 2)[0]; self.flashes()
        page = text(self.c.get(f'/issue/{jul}'))
        self.assertIn("ne sont pas comptés dans le reliquat", page)                                  # the warning no longer says the later days are counted
        self.assertEqual(self.failing(jul), [])
        self.issue(jul); self.assertEqual(self.status(jul), 'issued', self.flashes())
        self.assertEqual(self.reliquat(jul), 0)                                                      # was -2: August's days were wrongly deducted
        self.assertEqual(self.scalar('SELECT reliquat_treatment FROM invoices WHERE id=?', (jul,)), 'aucun')

    def test_position_is_bounded_by_the_period_end_but_the_global_figures_stay_global(self):
        self.entries(self.pid2)
        self.issued(self.pid2, '2026-08-01', '2026-08-31', 2)
        c = m.db()
        try:
            p = c.execute('SELECT * FROM projects WHERE id=?', (self.pid2,)).fetchone()
            jul = m.rules.contract(c, p, upto='2026-07-31', through='2026-07-31'); glob = m.rules.contract(c, p)
        finally: c.close()
        self.assertEqual((jul['consumed_days'], jul['billed_through_days'], jul['offered_through_days']), (2, 0, 0))
        self.assertEqual((glob['billed_days'], glob['billed_through_days'], glob['unbilled_days']), (2, 2, 2))


class B06_Tolerance(RC25):
    def test_zero_over_billing_tolerance_with_an_explicit_audited_exception(self):
        self.entry(self.pid, '2026-07-10', 8); self.entry(self.pid, '2026-08-10', 8)
        iid = self.draft(self.pid, '2026-08-01', '2026-08-31', 1.01)[0]                              # 0.01 j above the work of the period
        ck = self.checks(iid); self.assertEqual(self.failing(iid), [12])
        self.assertIn('sur-facturation', ck[12]['detail']); self.assertTrue(ck[12]['derogable'])
        self.issue(iid); self.assertEqual(self.status(iid), 'draft')
        self.issue(iid, derogate=(12,)); self.assertEqual(self.status(iid), 'issued', self.flashes())
        rows = self.derogation_audit(); self.assertEqual([r['check'] for r in rows], [12]); self.assertIn('sur-facturation', rows[0]['anomaly'])

    def test_under_billing_has_no_tolerance_since_rc41(self):
        self.entry(self.pid, '2026-08-10', 8); self.entry(self.pid, '2026-08-11', 8)                   # 2 j worked
        self.assertEqual(m.invoice_checks.UNDER_TOLERANCE, 0.0); self.assertEqual(m.invoice_checks.OVER_TOLERANCE, 0.0)
        self.assertEqual(self.failing(self.draft(self.pid, '2026-08-01', '2026-08-31', 2)[0]), [])     # exactly the work: fine
        self.assertEqual(self.failing(self.draft(self.pid2, '2026-08-01', '2026-08-31', 1)[0]), [12, 14])  # no work on this mandate: 1 j over
        iid = self.draft(self.pid, '2026-08-01', '2026-08-31', 1.5)[0]                                 # 0.5 j under: tolerated up to rc40, a gap now
        ck = self.checks(iid); self.assertEqual(self.failing(iid), [12]); self.assertIn('tolérance de sous-facturation : 0 j', ck[12]['detail']); self.assertTrue(ck[12]['derogable'])
        iid = self.draft(self.pid, '2026-08-01', '2026-08-31', 1.99)[0]
        self.assertEqual(self.failing(iid), [12])
        self.issue(iid); self.assertEqual(self.status(iid), 'draft')                                    # no reason: refused
        self.issue(iid, derogate=(12,)); self.assertEqual(self.status(iid), 'issued', self.flashes())   # a written reason for check 12 still issues it
        self.assertEqual([r['check'] for r in self.derogation_audit()], [12])

    def test_rounding_up_beyond_the_recorded_work_cannot_be_issued(self):
        self.entry(self.pid, '2026-08-10', 7)                                                          # 0.875 j, rounded UP to the quarter: 1 j
        st, sug = self.suggest(self.pid, '2026-08-01', '2026-08-31', mode='up')
        self.assertEqual(sug['suggested_qty'], 1.0)
        iid = self.draft(self.pid, '2026-08-01', '2026-08-31', sug['suggested_qty'], rounding='up', rounding_step='0.25')[0]
        self.assertEqual(self.failing(iid), [12, 14])                                                   # documented consequence of decisions 3 and 6
        self.issue(iid, derogate=(12, 13)); self.assertEqual(self.status(iid), 'draft')                   # check 14 admits no exception: the quantity must follow the work


class B04b_CreditCases(RC25):
    """Partial, amount-only, cancelled and replacing credit notes, cent rounding, entire credit and re-issue."""
    def setUp(self):
        super().setUp()
        self.entry(self.pid, '2026-08-10', 8)
        self.f1 = self.issued(self.pid, '2026-08-01', '2026-08-31', 1)

    def full(self, pid=None, iid=None):
        c = m.db()
        try: return m.credits.fully_credited(c, iid or self.f1)
        finally: c.close()

    def blocked(self, pid=None):
        c = m.db()
        try: return m.credits.period_clash(c, pid or self.pid, '2026-08-01', '2026-08-31') is not None
        finally: c.close()

    def test_two_partial_credits_make_the_invoice_entirely_credited(self):
        before = self.frozen_state(self.f1)
        self.credit(self.f1, qty='0.5'); self.assertFalse(self.full()); self.assertTrue(self.blocked())
        self.credit(self.f1, qty='0.5'); self.assertTrue(self.full()); self.assertFalse(self.blocked())
        f2 = self.draft(self.pid, '2026-08-01', '2026-08-31', 1)[0]
        self.assertEqual(self.failing(f2), [])                                                        # 1 j + 1 j - 1 j credited = 1 j worked
        self.issue(f2); self.assertEqual(self.status(f2), 'issued', self.flashes())
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (f2,)), f'{YEAR}-2')
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM credit_notes WHERE status='issued'"), 2)
        self.assertEqual(self.frozen_state(self.f1), before)

    def test_an_amount_only_credit_never_frees_the_period(self):
        self.credit(self.f1, amount='800')                       # the whole service line, but no day credited: the position in days is unchanged
        self.assertFalse(self.full()); self.assertTrue(self.blocked())
        iid, fl = self.draft(self.pid, '2026-08-01', '2026-08-31', 1)
        self.assertIn('chevauche', ' '.join(fl))

    def test_days_and_amount_together_still_leave_days_uncredited(self):
        self.credit(self.f1, qty='0.5'); self.credit(self.f1, amount='400')
        self.assertFalse(self.full()); self.assertTrue(self.blocked())

    def test_a_cancelled_note_does_not_count_and_its_replacement_does(self):
        before = self.frozen_state(self.f1)
        cid = self.credit(self.f1, scope='total'); self.assertTrue(self.full())
        self.flashes(); self.c.post(f'/credit/{cid}/cancel', data={'reason': 'avoir émis par erreur'}); self.flashes()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_cancellations'), 1)
        self.assertFalse(self.full()); self.assertTrue(self.blocked())                                # the cancelled note credits nothing any more
        cid2 = self.credit(self.f1, scope='total', replaces_credit_id=str(cid))
        self.assertTrue(self.full()); self.assertFalse(self.blocked())
        f2 = self.draft(self.pid, '2026-08-01', '2026-08-31', 1)[0]
        self.assertEqual(self.failing(f2), []); self.issue(f2); self.assertEqual(self.status(f2), 'issued', self.flashes())
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM credit_notes WHERE status='issued'"), 2)    # both notes and the cancellation document are kept
        self.assertEqual(self.scalar('SELECT replaces_credit_id FROM credit_notes WHERE id=?', (cid2,)), cid)
        self.assertEqual(self.frozen_state(self.f1), before)

    def test_rounding_to_the_cent_two_partials_overshoot_and_the_total_scope_finishes(self):
        pid = self.mandate(name='Mandat arrondi haut', rate='333.33', vat='0', ordered='20', legal_id='CHE-000.000.009')
        self.entry(pid, '2026-08-10', 10)                         # 1.25 j x 333.33 = 416.66
        f = self.issued(pid, '2026-08-01', '2026-08-31', 1.25)
        self.credit(f, qty='0.5')                                 # 166.665 -> 166.67
        self.flashes(); r = self.c.post(f'/invoice/{f}/credit', data={'reason': 'x', 'treatment': 'remboursement', 'qty': '0.75'})   # 249.9975 -> 250.00 > 249.99 left
        self.assertIn('dépasserait', text(r) + ' '.join(self.flashes())); self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes WHERE invoice_id=?', (f,)), 1)
        self.assertFalse(self.full(iid=f))
        self.credit(f, scope='total')                             # the exact balance, 249.99, with the 0.75 j
        self.assertTrue(self.full(iid=f)); self.assertFalse(self.blocked(pid))
        self.assertAlmostEqual(self.scalar('SELECT SUM(amount) FROM credit_notes WHERE invoice_id=?', (f,)), 416.66, places=9)

    def test_rounding_to_the_cent_two_partials_undershoot_and_one_cent_keeps_the_period_blocked(self):
        pid = self.mandate(name='Mandat arrondi bas', rate='333.33', vat='0', ordered='20', legal_id='CHE-000.000.010')
        self.entry(pid, '2026-08-10', 12)                         # 1.5 j x 333.33 = 500.00
        f = self.issued(pid, '2026-08-01', '2026-08-31', 1.5)
        self.credit(f, qty='0.25'); self.credit(f, qty='1.25')    # 83.33 + 416.66 = 499.99: every day credited, one cent left
        self.assertFalse(self.full(iid=f)); self.assertTrue(self.blocked(pid))
        self.credit(f, amount='0.01')
        self.assertTrue(self.full(iid=f)); self.assertFalse(self.blocked(pid))
        f2 = self.draft(pid, '2026-08-01', '2026-08-31', 1.5)[0]
        self.assertEqual(self.failing(f2), []); self.issue(f2); self.assertEqual(self.status(f2), 'issued', self.flashes())

    def test_a_credit_note_still_in_draft_never_counts(self):
        self.flashes(); self.c.post(f'/invoice/{self.f1}/credit', data={'reason': 'x', 'treatment': 'remboursement', 'scope': 'total'}); self.flashes()
        self.assertEqual(self.scalar("SELECT status FROM credit_notes ORDER BY id DESC LIMIT 1"), 'draft')
        self.assertFalse(self.full()); self.assertTrue(self.blocked())
