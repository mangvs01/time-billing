"""9.2-rc42 (owner decisions of 2026-10-28): mission BILLING-STC-GEM-EXCEPTION.

1  no tolerance below the work of the period either (UNDER_TOLERANCE = 0, like OVER_TOLERANCE): every gap is a gap of check 12 (derogable with a written reason)
2  mandate « STC GEM » ONLY: no check blocks the issuance (not even the non-derogable 14), no reason is asked; the gaps stay SHOWN (warnings) and are written to the
   audit log with the mention « exception STC GEM »; the PDF and the amounts do not change; every other mandate keeps the rules (negative tests below)
3  the rate of a draft of that mandate may be typed in the editor (positive, bounded, 4 decimals), is kept on the invoice and its frozen copy, audited (old, new, user);
   issued invoices never change; any other mandate ignores the field

Synthetic data only. Run with the isolated runner (see docs/FACTURES-IMPLEMENTATION.md): this file needs the test container (the supervisor runs it).
"""
import json, os, unittest
from decimal import Decimal
from unittest import mock

import app.app as m
from app import billing_rules as rules, invoice_checks, invoice_service
from tests.test_rc25 import RC25, text

EXC = 'exception STC GEM'


class Setting(unittest.TestCase):
    """The configuration and the rate validation: no database."""

    def names(self, value):
        env = {k: v for k, v in os.environ.items() if k != 'BILLING_EXCEPTION_MANDATES'}
        if value is not None: env['BILLING_EXCEPTION_MANDATES'] = value
        return mock.patch.dict(os.environ, env, clear=True)

    def test_default_is_stc_gem_and_matching_ignores_case_and_spaces(self):
        with self.names(None):
            self.assertEqual(rules.exception_mandate_names(), ('STC GEM*',))
            for n in ('STC GEM', 'stc gem', '  Stc   Gem ', 'STC GEM Avril', 'STC GEM Oct - DM job', 'stc gem 2'):
                self.assertEqual(rules.exception_mandate({'id': 1, 'name': n, 'short_name': ''}), 'STC GEM*', n)
            self.assertEqual(rules.exception_mandate({'id': 1, 'name': 'Autre', 'short_name': ' stc gem'}), 'STC GEM*')       # the short name counts too

    def test_only_the_whole_name_matches_never_a_part_or_the_client(self):
        with self.names(None):
            for n in ('GEM STC', 'Mandat STC', 'STC', 'XSTC GEM', 'STCGEM', 'STC GEMINI', 'NC STC Sept', 'Mandat STC GEM Phase 2', ''):
                self.assertIsNone(rules.exception_mandate({'id': 1, 'name': n, 'short_name': '', 'client': 'STC GEM'}), n)       # the client is not matched

    def test_empty_setting_switches_the_exception_off_and_ids_can_be_named(self):
        with self.names(''):
            self.assertEqual(rules.exception_mandate_names(), ()); self.assertIsNone(rules.exception_mandate({'id': 1, 'name': 'STC GEM', 'short_name': ''}))
        with self.names('id:7, Autre Mandat'):
            self.assertIsNone(rules.exception_mandate({'id': 1, 'name': 'STC GEM', 'short_name': ''}))                        # the default is replaced, not completed
            self.assertEqual(rules.exception_mandate({'id': 7, 'name': 'Quelconque', 'short_name': ''}), 'id:7')
            self.assertIsNone(rules.exception_mandate({'id': 17, 'name': 'Quelconque', 'short_name': ''}))
            self.assertEqual(rules.exception_mandate({'id': 2, 'name': 'autre  mandat', 'short_name': ''}), 'Autre Mandat')

    def test_rate_validation(self):
        ok = rules.unit_rate_typed
        self.assertEqual(ok('650'), Decimal('650.0000')); self.assertEqual(ok('650,1234'), Decimal('650.1234')); self.assertEqual(ok(' .5 '), Decimal('0.5000'))
        self.assertEqual(ok('1000000000'), Decimal('1000000000.0000'))
        for bad in ('', None, '0', '0.0000', '-1', '+5', 'abc', '1e3', '650.12345', '1000000000.0001', '1000000001', 'inf', 'nan', '1_0', '٣', '6 50'):
            with self.assertRaises(ValueError, msg=repr(bad)): ok(bad)

    def test_no_tolerance_in_the_rule_itself(self):
        self.assertEqual(invoice_checks.UNDER_TOLERANCE, 0.0); self.assertEqual(invoice_checks.OVER_TOLERANCE, 0.0)
        s = invoice_checks.period_story
        self.assertEqual(s(1, 1, True, '2026-09-01', '2026-09-30'), [])
        self.assertEqual(s(2, 2 + 1e-7, True, '2026-09-01', '2026-09-30'), [])
        self.assertEqual(len(s(1.99, 2, True, '2026-09-01', '2026-09-30')), 1)
        self.assertIn('tolérance de sous-facturation : 0 j', s(1.5, 2, True, '2026-09-01', '2026-09-30')[0])
        self.assertIn('tolérance de sur-facturation : 0 j', s(2.5, 2, True, '2026-09-01', '2026-09-30')[0])


class World(RC25):
    """Two mandates with the same incoherent situation: 1 j worked in September, 2 j of registry invoice, 3 j billed (checks 12 and 14 fail, 14 is never derogable)."""
    RECORD_WORK = False

    def setUp(self):
        super().setUp()
        env = {k: v for k, v in os.environ.items() if k != 'BILLING_EXCEPTION_MANDATES'}
        p = mock.patch.dict(os.environ, env, clear=True); p.start(); self.addCleanup(p.stop)        # the default setting: « STC GEM »
        self.stc = self.mandate(name='STC GEM', rate='650', vat='0', ordered='20', legal_id='CHE-000.000.101')
        self.autre = self.mandate(name='Mandat ordinaire', rate='650', vat='0', ordered='20', legal_id='CHE-000.000.102')

    def historical(self, pid, days, date, ref):
        """Same registry invoice as RC25.historical, with a cell of its own: several mandates of one test each hold one (unique source cell)."""
        self._cell = getattr(self, '_cell', 0) + 1
        self.sql_exec("""INSERT INTO historical_invoices(project_id,source_file,source_sheet,source_cell,invoice_date,invoice_ref,qty_days,basis,status,created_at,validated_at,validated_by)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (pid, 'SUIVI.xlsx', 'SUIVI 2026', f'Q{11 + self._cell}', date, ref, days, 'days', 'validated', date, date, 'admin'))

    def incoherent(self, pid, qty=3):
        self.entry(pid, '2026-09-02', 8)
        self.historical(pid, 2, '2026-10-01', '2026-09')
        return self.draft(pid, '2026-09-01', '2026-09-30', qty, invoice_date='2026-09-30')[0]

    def edit_form(self, iid, **over):
        i = self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]
        d = dict(period_from=i['period_from'], period_to=i['period_to'], qty=str(i['qty']), unit=i['unit'], rounding='exact', rounding_step='0.25', vat=str(i['vat']),
                 description=i['description'] or '', other_amount='0', other_label='', other_vat_mode='hors_tva', invoice_date=i['invoice_date'] or '', note='',
                 revision=str(i['revision']), number=i['number'] or '')
        d.update(over); return d

    def save(self, iid, **over):
        self.flashes(); r = self.c.post(f'/invoice/{iid}/edit', data=self.edit_form(iid, **over), follow_redirects=False)
        return r, ' '.join(self.flashes()) + (' ' + text(r) if r.status_code == 200 else '')

    def rate(self, iid): return self.scalar('SELECT unit_rate FROM invoices WHERE id=?', (iid,))
    def audit(self, event): return [json.loads(r['detail']) for r in self.sql('SELECT detail FROM audit WHERE event=? ORDER BY id', (event,))]


class Tolerance(World):
    def test_under_billing_by_half_a_day_is_a_derogable_gap_on_every_mandate(self):
        self.entry(self.autre, '2026-09-02', 8); self.entry(self.autre, '2026-09-03', 8)            # 2 j
        iid = self.draft(self.autre, '2026-09-01', '2026-09-30', 1.5, invoice_date='2026-09-30')[0]
        ck = self.checks(iid); self.assertEqual(self.failing(iid), [12]); self.assertTrue(ck[12]['derogable'])
        self.issue(iid); self.assertEqual(self.status(iid), 'draft')
        self.issue(iid, derogate=(12,)); self.assertEqual(self.status(iid), 'issued', self.flashes())
        self.assertEqual([r['check'] for r in self.derogation_audit()], [12])

    def test_over_and_exact(self):
        self.entry(self.autre, '2026-09-02', 8)
        self.assertEqual(self.failing(self.draft(self.autre, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')[0]), [])
        self.assertEqual(self.failing(self.draft(self.autre, '2026-09-01', '2026-09-30', 1.25, invoice_date='2026-09-30')[0]), [12, 14])   # 0.25 j over: check 12, and 14 (net quantity invoiced above the quantity worked)


class Exception_(World):
    def test_checks_are_computed_and_shown_but_none_fails(self):
        iid = self.incoherent(self.stc); ck = self.checks(iid)
        self.assertEqual(self.failing(iid), [])
        gaps = sorted(n for n, x in ck.items() if x.get('would_fail'))
        self.assertEqual(gaps, [12, 14])                                                            # the same anomalies as an ordinary mandate would have
        for n in gaps: self.assertEqual((ck[n]['status'], ck[n]['derogable'], ck[n]['exception']), ('warning', False, 'STC GEM*'))
        self.assertEqual(m.invoice_checks.blocking(m.invoice_checks.run_checks(m.db(), iid)), [])
        ordinary = self.checks(self.incoherent_other())
        self.assertEqual(sorted(n for n, x in ordinary.items() if x['status'] == 'fail'), [12, 14])  # same figures: the ordinary mandate fails them

    def incoherent_other(self):
        return self.incoherent(self.autre)

    def test_issue_page_shows_the_gaps_and_allows_the_issuance_without_reason(self):
        iid = self.incoherent(self.stc); page = text(self.c.get(f'/issue/{iid}'))
        self.assertIn(EXC, page); self.assertIn('non bloquant', page); self.assertIn('exceptionNotice', page)
        self.assertNotIn('Émission impossible', page); self.assertNotIn('name="derogation_', page)
        self.assertNotRegex(page, r'<button disabled>Émettre')
        other = text(self.c.get(f'/issue/{self.incoherent_other()}'))
        self.assertNotIn(EXC, other); self.assertIn('Émission impossible', other); self.assertNotIn('exceptionNotice', other)

    def test_full_scenario_incoherent_invoices_and_changed_rate_are_issued_and_audited(self):
        # an older invoice of the same mandate, issued before: it must never change
        self.entry(self.stc, '2026-08-10', 8)
        old = self.draft(self.stc, '2026-08-01', '2026-08-31', 1, invoice_date='2026-08-31')[0]
        self.issue(old); self.assertEqual(self.status(old), 'issued', self.flashes())
        before = self.frozen_state(old); old_header = invoice_service.frozen_header(m.db(), old)
        iid = self.incoherent(self.stc)
        self.assertEqual(self.rate(iid), 650.0)
        # 1. the editor shows the field, a typed rate is validated, kept and audited
        page = text(self.c.get(f'/invoice/{iid}/edit'))
        self.assertIn('name="unit_rate"', page); self.assertIn('name="unit_rate_shown"', page); self.assertIn(EXC, page)
        for bad in ('0', '-3', 'abc', '650.12345', '1000000001', ''):
            r, fl = self.save(iid, unit_rate=bad, unit_rate_shown='650.00')
            if bad == '':
                self.assertEqual(self.rate(iid), 650.0)                                              # empty = untouched
            else:
                self.assertIn('Brouillon non modifié', fl, bad); self.assertEqual(self.rate(iid), 650.0, bad)
        self.assertEqual(self.audit('draft_rate_changed'), [])
        r, fl = self.save(iid, unit_rate='700,5', unit_rate_shown='650.00')
        self.assertIn('Brouillon modifié', fl, fl); self.assertEqual(self.rate(iid), 700.5)
        ch = self.audit('draft_rate_changed'); self.assertEqual(len(ch), 1)
        self.assertEqual((ch[0]['old_rate'], ch[0]['new_rate'], ch[0]['invoice_id'], ch[0]['exception']), (650.0, 700.5, iid, EXC)); self.assertTrue(ch[0]['by'])
        # an untouched save keeps the typed rate and writes nothing more
        self.save(iid, unit_rate='700.50', unit_rate_shown='700.50'); self.assertEqual(self.rate(iid), 700.5); self.assertEqual(len(self.audit('draft_rate_changed')), 1)
        # the preview (server side) and the editor use the typed rate
        pv = self.c.post(f'/invoice/{iid}/preview', data=self.edit_form(iid, unit_rate='701', unit_rate_shown='700.50')).get_json()
        self.assertTrue(pv['ok']); self.assertEqual(self.c.post(f'/invoice/{iid}/preview', data=self.edit_form(iid, unit_rate='abc')).get_json()['ok'], False)
        # 2. the issuance: no reason, nothing blocks
        self.flashes(); self.issue(iid); self.assertEqual(self.status(iid), 'issued', self.flashes())
        c = m.db()
        try:
            h = invoice_service.frozen_header(c, iid); num, pdf = invoice_service.frozen_pdf(c, iid)
        finally: c.close()
        self.assertEqual(h['unit_rate'], 700.5); self.assertEqual(h['amounts']['ht'], '2101.50'); self.assertEqual(h['exception'], EXC); self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(self.derogation_audit(), [])
        ex = self.audit('invoice_check_exception'); self.assertTrue({3, 12, 14} <= {x['check'] for x in ex})   # 3: the rate typed is not the mandate's (shown, never blocking)
        for x in ex: self.assertEqual((x['exception'], x['mandate'], x['invoice_id']), (EXC, 'STC GEM', iid)); self.assertTrue(x['anomaly'] and x['by'])
        issued = self.sql("SELECT detail FROM audit WHERE event='invoice_issued' ORDER BY id DESC LIMIT 1")[0]['detail']
        self.assertIn(f'{EXC}=yes', issued); self.assertIn('derogations=none', issued)
        # 3. the older invoice is byte for byte what it was
        self.assertEqual(self.frozen_state(old), before); self.assertEqual(invoice_service.frozen_header(m.db(), old), old_header)
        self.assertEqual(self.rate(old), 650.0)

    def test_amounts_and_pdf_are_those_of_the_stored_rate_only(self):
        """Without any rate change the exception changes nothing in what is printed: same amounts as an ordinary mandate with the same figures."""
        iid = self.incoherent(self.stc, qty=1.5); other = self.incoherent(self.autre, qty=1.5)
        a = invoice_service.live_data(m.db(), iid)[0]['amounts']; b = invoice_service.live_data(m.db(), other)[0]['amounts']
        self.assertEqual(a, b)

    def test_hourly_invoice_rate_is_typed_per_hour(self):
        self.entry(self.stc, '2026-09-02', 8)
        iid = self.draft(self.stc, '2026-09-01', '2026-09-30', 8, unit='hour', invoice_date='2026-09-30')[0]
        self.assertAlmostEqual(self.rate(iid), 650 / 8)
        self.save(iid, unit='hour', qty='8', unit_rate='90.1234', unit_rate_shown='81.25')
        self.assertEqual(self.rate(iid), 90.1234)
        self.assertEqual(invoice_service.live_data(m.db(), iid)[0]['amounts']['ht'], Decimal('720.99'))   # 8 × 90.1234 = 720.9872

    def test_changing_the_unit_without_touching_the_rate_takes_the_mandate_rate(self):
        self.entry(self.stc, '2026-09-02', 8)
        iid = self.draft(self.stc, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')[0]
        self.save(iid, unit='hour', qty='8', unit_rate='650.00', unit_rate_shown='650.00')
        self.assertAlmostEqual(self.rate(iid), 650 / 8); self.assertEqual(self.audit('draft_rate_changed'), [])


class OtherMandatesUnchanged(World):
    """Negative tests: everything the exception allows is refused or ignored elsewhere."""

    def test_incoherent_invoices_stay_blocked(self):
        iid = self.incoherent(self.autre); self.flashes()
        self.assertEqual(self.failing(iid), [12, 14]); self.assertFalse(self.checks(iid)[14]['derogable'])
        for given in ((), (12,), (14,), (12, 13, 14)):
            self.issue(iid, derogate=given); self.assertEqual(self.status(iid), 'draft', given); self.assertIn('14.', ' '.join(self.flashes()))
        self.assertEqual(self.audit('invoice_check_exception'), []); self.assertEqual(self.derogation_audit(), [])
        self.assertEqual(self.sql("SELECT COUNT(*) n FROM audit WHERE event='invoice_issued'")[0]['n'], 0)
        self.assertTrue(all('would_fail' not in x and 'exception' not in x for x in self.checks(iid).values()))

    def test_check_12_alone_still_needs_its_own_reason(self):
        self.entry(self.autre, '2026-09-02', 8)
        iid = self.draft(self.autre, '2026-09-01', '2026-09-30', 0.5, invoice_date='2026-09-30')[0]      # 0.5 j under: a gap now
        self.assertEqual(self.failing(iid), [12])
        self.issue(iid); self.assertEqual(self.status(iid), 'draft')
        self.issue(iid, derogate=(12,)); self.assertEqual(self.status(iid), 'issued', self.flashes())
        self.assertEqual(self.audit('invoice_check_exception'), [])
        self.assertNotIn('exception', invoice_service.frozen_header(m.db(), iid)); self.assertNotIn(EXC, self.sql("SELECT detail FROM audit WHERE event='invoice_issued'")[0]['detail'])

    def test_the_rate_field_is_absent_and_a_forged_one_is_ignored(self):
        self.entry(self.autre, '2026-09-02', 8)
        iid = self.draft(self.autre, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')[0]
        page = text(self.c.get(f'/invoice/{iid}/edit')); self.assertNotIn('name="unit_rate"', page); self.assertIn('lecture seule', page)
        r, fl = self.save(iid, unit_rate='999', unit_rate_shown='650.00')
        self.assertIn('Brouillon modifié', fl, fl); self.assertEqual(self.rate(iid), 650.0); self.assertEqual(self.audit('draft_rate_changed'), [])
        r, fl = self.save(iid, unit_rate='abc'); self.assertEqual(self.rate(iid), 650.0)                  # not even validated: ignored
        pv = self.c.post(f'/invoice/{iid}/preview', data=self.edit_form(iid, unit_rate='999')).get_json()
        self.assertTrue(pv['ok']); self.assertNotIn('999', pv['service'])                                   # the preview ignores the forged rate too
        self.assertEqual(invoice_service.live_data(m.db(), iid)[0]['amounts']['ht'], Decimal('650.00'))

    def test_similar_names_are_not_exceptions(self):
        for k, n in enumerate(('GEM STC', 'STC GEMINI', 'Mandat STC GEM Phase 2')):
            pid = self.mandate(name=n, rate='650', vat='0', ordered='20', legal_id=f'CHE-000.000.2{k:02d}')
            iid = self.incoherent(pid)
            self.assertEqual(self.failing(iid), [12, 14], n)
            r, fl = self.save(iid, unit_rate='1', unit_rate_shown='650.00'); self.assertEqual(self.rate(iid), 650.0, n)

    def test_switching_the_setting_off_restores_the_rules_for_stc_gem_too(self):
        iid = self.incoherent(self.stc); self.assertEqual(self.failing(iid), [])
        with mock.patch.dict(os.environ, {'BILLING_EXCEPTION_MANDATES': ''}):
            self.assertEqual(self.failing(iid), [12, 14])
            self.issue(iid, derogate=(12, 14)); self.assertEqual(self.status(iid), 'draft')
            self.assertNotIn('name="unit_rate"', text(self.c.get(f'/invoice/{iid}/edit')))
            self.save(iid, unit_rate='1', unit_rate_shown='650.00'); self.assertEqual(self.rate(iid), 650.0)
        with mock.patch.dict(os.environ, {'BILLING_EXCEPTION_MANDATES': f'id:{self.stc}'}):              # an explicit identifier works too
            self.assertEqual(self.failing(iid), [])

    def test_a_draft_rate_changed_under_the_exception_is_flagged_when_the_exception_is_switched_off(self):
        iid = self.incoherent(self.stc); self.save(iid, unit_rate='700', unit_rate_shown='650.00'); self.assertEqual(self.rate(iid), 700.0)
        with mock.patch.dict(os.environ, {'BILLING_EXCEPTION_MANDATES': ''}):
            self.assertIn(3, self.failing(iid))                                                            # check 3: the rate is no longer the mandate's (rolled back by recreating the draft)


class Version(World):
    def test_version_and_health(self):
        self.assertEqual(m.VERSION, '9.2-rc47'); self.assertEqual(self.c.get('/health').get_json()['version'], '9.2-rc47')
        self.assertEqual(m.invoice_checks.DEROGABLE, (12, 13))


if __name__ == '__main__':
    unittest.main()
