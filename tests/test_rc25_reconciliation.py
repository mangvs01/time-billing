"""RC25 réconciliation (root-83, 2026-10-11) : scénarios TB-01/03/07 de la lignée b réécrits dans l'API de la lignée a (P1 et P3 : questions métier ouvertes, non codées ici).
Oracle = décisions du propriétaire 2026-10-09 (RAPPORT-RC25.md, décisions 1-6) et D8 ; jamais le code de la lignée b. Données synthétiques.
Chaque test imprime l'état observé (ligne OBS) avant d'affirmer, pour que le rapport cite le comportement réel."""
import json
import app.app as m
from app import historical_billing, invoice_checks, post_billing
from tests.test_rc19 import RC19


class Probe(RC19):
    def post_issue(self, iid, **data):
        data.setdefault('reliquat_treatment', 'reporte')
        d = self.scalar('SELECT invoice_date FROM invoices WHERE id=?', (iid,))
        data.setdefault('confirm_backdate', d)
        self.flashes(); self.c.post(f'/issue/{iid}', data=data)
        return self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), ' '.join(self.flashes())

    def ctx(self, iid):
        c = m.db()
        try: return m.issue_context(c, iid)
        finally: c.close()

    def failing(self, iid):
        c = m.db()
        try: return sorted(x['n'] for x in invoice_checks.run_checks(c, iid) if x['status'] != 'ok')
        finally: c.close()

    def owner(self, eid):
        c = m.db()
        try: return (post_billing.owners(c, self.pid).get(eid) or {}).get('number')
        finally: c.close()

    def obs(self, **kw): print('\nOBS', self.id().split('.')[-1], json.dumps(kw, ensure_ascii=False, default=str))


class P(Probe):
    def test_P2_TB03_backdated_invoice_cannot_rebill_later_historical(self):
        # décision 3 / contrôle 14 : quantité nette facturée cumulée <= réalisée cumulée, historique validé compris
        self.entry(self.pid, '2026-09-10', 8, 'septembre')
        c = m.db()
        c.execute("""INSERT INTO historical_invoices(project_id,source_file,source_sheet,source_cell,invoice_date,invoice_ref,qty_days,amount_ht,unit_rate,basis,
                     status,created_at,validated_at,validated_by) VALUES(?,?,?,?,?,?,?,?,?,'days','validated','2026-10-01T00:00:00','2026-10-01T00:00:00','test')""",
                  (self.pid, 'classeur fictif', 'SUIVI', 'A1', '2026-10-01', None, 1, 800, 800)); c.commit(); c.close()
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        fails = self.failing(iid); st, fl = self.post_issue(iid)
        self.obs(failing_checks=fails, status=st, flash=fl[:240])
        self.assertEqual(st, 'draft', 'double facturation : le jour de septembre déjà facturé par l historique du 1er octobre est refacturé')

    def test_P4_TB01_row_frozen_billed_elsewhere_not_claimed_after_credit(self):
        # décision 1 : propriétaire = première facture émise qui l'a RÉELLEMENT facturée
        self.entry(self.pid, '2026-08-10', 8, 'août'); self.entry(self.pid, '2026-09-10', 8, 'septembre')
        f9 = self.issued(self.pid, '2026-09-01', '2026-09-30', 1)
        e = self.eid('septembre')
        self.edit(e, work_date='2026-10-02', reason='mauvaise date', confirm_billed='1')
        self.entry(self.pid, '2026-10-05', 4, 'octobre')
        self.issued(self.pid, '2026-10-01', '2026-10-07', 0.5)
        self.flashes(); self.c.post(f'/invoice/{f9}/credit', data={'scope': 'total', 'reason': 'Facture annulée (test)', 'treatment': 'remboursement'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes WHERE invoice_id=?', (f9,)); self.c.post(f'/credit/{cid}/issue')
        cst = self.scalar('SELECT status FROM credit_notes WHERE id=?', (cid,))
        own = self.owner(e)
        self.obs(credit_status=cst, owner_after_total_credit=own)
        self.assertEqual(cst, 'issued', self.flashes())
        self.assertIsNone(own, 'la saisie figée « facturée ailleurs » par la facture d octobre lui est attribuée après crédit de septembre : travail jamais refacturable')

    def test_P5_TB07_catch_up_reliquat_bounded_to_its_period(self):
        # décision 5 : reliquat borné par la fin de la période de la facture (rattrapages dans les deux sens)
        self.entry(self.pid, '2026-08-10', 8, 'août'); self.entry(self.pid, '2026-09-10', 8, 'septembre')
        self.issued(self.pid, '2026-09-01', '2026-09-30', 1)
        self.entry(self.pid, '2026-09-20', 4, 'septembre tardive')
        iid, _ = self.draft(self.pid, '2026-08-01', '2026-08-31', 1)
        ctx = self.ctx(iid); fails = self.failing(iid)
        st, fl = self.post_issue(iid, reliquat_treatment='')
        self.obs(later_issued=ctx.get('later_issued'), reliquat=ctx['reliquat'], failing_checks=fails, status=st, flash=fl[:240])
        self.assertEqual(st, 'issued', fl)

    def test_P6_TB07_catch_up_cannot_take_up_another_period(self):
        self.entry(self.pid, '2026-08-10', 8, 'août'); self.entry(self.pid, '2026-09-10', 8, 'septembre')
        self.issued(self.pid, '2026-09-01', '2026-09-30', 1)
        self.entry(self.pid, '2026-09-20', 4, 'septembre tardive')
        iid, _ = self.draft(self.pid, '2026-08-01', '2026-08-31', 1.5)
        fails = self.failing(iid); st, fl = self.post_issue(iid, derogation_12='rattrapage voulu')
        self.obs(failing_checks=fails, status=st, flash=fl[:240])
        self.assertEqual(st, 'draft', fl)
