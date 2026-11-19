"""V9.2-rc10: numeric input hardening found by the independent audit (NaN, infinity and absurd magnitudes stored in a
draft made every page of the application fail with a 500). Synthetic data only, on a COPY of the staging database."""
import sqlite3

import app.app as m
from tests.test_credit_settlement import Settlement
from tests.test_v92 import V92


def text(r): return r.get_data(as_text=True)


class DraftQuantity(V92):
    def setUp(self):
        super().setUp(); self.pid = self.mandate(name='Mandat Nombres', rate='800', vat='8.1', ordered='20'); self.entry(self.pid, '2026-09-10', 16)

    def post_draft(self, **kw):
        self.flashes()
        data = {'project_id': self.pid, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1', 'rounding': 'exact', 'rounding_step': '0.25'}; data.update(kw)
        self.c.post('/invoice', data=data); return ' '.join(self.flashes())

    def test_non_finite_and_absurd_quantities_are_refused_and_pages_stay_up(self):
        for q in ('inf', '-inf', 'nan', '1e308', '1e30', '100001', '0', '-1', 'abc', '', '1,5,5'):
            self.assertIn('non créé', self.post_draft(qty=q), q)
        for u in ('hour',):
            self.assertIn('non créé', self.post_draft(qty='1e30', unit=u))
        self.assertEqual(self.sql('SELECT COUNT(*) FROM invoices')[0][0], 0)
        for tab in ('dashboard', 'archive', 'billing'): self.assertEqual(self.c.get(f'/?tab={tab}').status_code, 200)

    def test_comma_decimal_and_normal_values_still_work(self):
        self.assertIn('Brouillon créé', self.post_draft(qty='1,25')); self.assertEqual(self.scalar('SELECT qty FROM invoices'), 1.25)

    def test_other_amount_is_bounded(self):
        for v in ('1e30', '2000000000', 'inf', 'nan', 'abc'):
            self.assertIn('non créé', self.post_draft(other_amount=v), v)
        self.assertIn('Brouillon créé', self.post_draft(other_amount='1234,50'))

    def test_vat_edit_is_bounded(self):
        self.post_draft(); iid = self.scalar('SELECT MAX(id) FROM invoices')
        import html
        for v in ('inf', 'nan', '101', '-1', 'abc'):
            r = self.c.post(f'/invoice/{iid}/edit', data={'project_id': self.pid, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1', 'vat': v, 'rounding': 'exact', 'rounding_step': '0.25'})
            self.assertIn('non modifié', html.unescape(r.get_data(as_text=True)), v)
        self.assertEqual(self.scalar('SELECT vat FROM invoices WHERE id=?', (iid,)), 8.1)
        self.assertEqual(self.c.get('/?tab=archive').status_code, 200)


class CreditNumbers(Settlement):
    def test_credit_inputs_are_bounded(self):
        for kw in (dict(qty='inf'), dict(qty='nan'), dict(qty='1e30'), dict(amount='1e30'), dict(amount='inf'), dict(amount='nan'), dict(amount='2000000000'),
                   dict(other_amount='1e30'), dict(qty='1', unit_rate='nan'), dict(qty='1', unit_rate='inf'), dict(qty='1', unit_rate='0'), dict(qty='1', unit_rate='-5')):
            data = dict({'scope': 'partial', 'reason': 'test', 'treatment': 'remboursement'}, **kw)
            self.c.post(f'/invoice/{self.iid}/credit', data=data)
            self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 0, kw)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 0)
        self.assertEqual(self.c.get('/?tab=archive').status_code, 200)

    def test_refund_and_offset_amounts_are_bounded(self):
        cid = self.issued_cn(qty='0.5', treatment='remboursement')
        for v in ('inf', 'nan', '1e30', '-1', '0', 'abc'):
            self.refund(cid, v)
            self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_operations'), 0, v)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_operations'), 0)
        self.assertEqual(self.c.get(f'/credit/{cid}').status_code, 200)


class ProjectNumbers(V92):
    def test_friendly_messages(self):
        for kw, msg in ((dict(rate='abc'), 'tarif journalier invalide'), (dict(vat='nan'), 'TVA invalide'), (dict(duration_months='abc'), 'durée prévisionnelle invalide'),
                        (dict(day_hours='0'), 'heures par jour invalide'), (dict(ordered_days='-3'), 'jours commandés invalide')):
            data = {'name': 'Mandat Messages', 'rate': '650', 'day_hours': '8', 'vat': '8.1', 'ordered_days': '10', 'duration_months': '12'}; data.update(kw)
            self.flashes(); self.c.post('/project', data=data)
            self.assertIn(msg, ' '.join(self.flashes()), kw)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM projects WHERE name='Mandat Messages'")[0][0], 0)
