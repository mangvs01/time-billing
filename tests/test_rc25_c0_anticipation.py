"""RC25 — Claude0 2026-10-12: regression of the over-billing defect reproduced on 416ada3 (launch report 20261012-2046).

On 416ada3 a draft of 1,25 j for 1,125 j worked was ISSUED when the form carried a written reason for check 12 AND a written reason for billing in
advance (negative_reliquat_reason, UI of 9d59fd1, excluded from this candidate by owner decision 3). Check 14 is not derogable (B-01, D8): whatever
the form carries, such a draft stays a draft, nothing is numbered, nothing is audited as issued or derogated. Once the quantity matches the work, the
same draft issues (positive control: the refusals below are not an artefact of the test harness).
Synthetic data only (see test_import.py for the run command).
"""
from tests.test_rc25 import RC25

ADVANCE = 'facturation d\'avance motivée par écrit : acompte convenu avec le client, test de non-régression'
REASON12 = 'exception voulue du contrôle 12 : quantité supérieure au travail de la période'


class C0_AdvanceBillingStaysDraft(RC25):
    def world(self):
        self.entry(self.pid, '2026-08-04', 3.5); self.entry(self.pid, '2026-08-12', 4.25); self.entry(self.pid, '2026-08-27', 1.25)   # 9 h = 1,125 j
        return self.draft(self.pid, '2026-08-01', '2026-08-31', 1.25)[0]

    def refused(self, iid, form):
        self.flashes(); self.c.post(f'/issue/{iid}', data=form); fl = ' '.join(self.flashes())
        self.assertEqual(self.status(iid), 'draft', form); self.assertIn('14.', fl, form)

    def nothing_issued(self):
        self.assertEqual(self.derogation_audit(), [])
        self.assertEqual(self.sql("SELECT COUNT(*) n FROM audit WHERE event='invoice_issued'")[0]['n'], 0)

    def test_the_draft_fails_check_14_which_is_not_derogable(self):
        iid = self.world(); ck = self.checks(iid)
        self.assertIn(14, self.failing(iid)); self.assertFalse(ck[14]['derogable'])

    def test_exception_and_advance_justification_together_keep_the_draft(self):
        iid = self.world(); d = self.scalar('SELECT invoice_date FROM invoices WHERE id=?', (iid,))
        for treatment in ('reporte', 'autre', 'offert'):
            self.refused(iid, {'reliquat_treatment': treatment, 'derogation_12': REASON12, 'negative_reliquat_reason': ADVANCE,
                               'reliquat_note': ADVANCE, 'confirm_backdate': d or ''})
        self.refused(iid, {'reliquat_treatment': 'reporte', 'derogation_12': REASON12, 'derogation_13': REASON12, 'derogation_14': ADVANCE,
                           'negative_reliquat_reason': ADVANCE, 'confirm_backdate': d or ''})
        self.nothing_issued()

    def test_exception_alone_keeps_the_draft(self):
        iid = self.world(); d = self.scalar('SELECT invoice_date FROM invoices WHERE id=?', (iid,))
        for form in ({'derogation_12': REASON12}, {'derogation_14': ADVANCE}, {'negative_reliquat_reason': ADVANCE}, {}):
            self.refused(iid, dict({'reliquat_treatment': 'reporte', 'confirm_backdate': d or ''}, **form))
        self.nothing_issued()

    def test_the_quantity_the_work_supports_issues_without_exception(self):
        iid = self.world(); self.c.post(f'/invoice/{iid}/delete'); self.flashes()
        iid = self.draft(self.pid, '2026-08-01', '2026-08-31', 1.125)[0]
        self.assertEqual(self.failing(iid), []); self.issue(iid); self.assertEqual(self.status(iid), 'issued', self.flashes())
        self.assertEqual(self.derogation_audit(), [])
