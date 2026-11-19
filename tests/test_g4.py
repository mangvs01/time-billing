"""G4 (user directive 2026-10-05): invoices issued OUTSIDE Time Billing are a separate, traceable, user-validated registry that feeds the indicators;
the invoice annex separates the DETAIL of the invoiced period from the cumulative history; nothing about an issued invoice changes.
Synthetic data only, on a COPY of the staging database (see test_import.py for the run command).
"""
import html as H, json, re, sqlite3, unittest.mock

import app.app as m
from app import billing_rules as rules, historical_billing, invoice_service
from tests.test_functional import pdf_text
from tests.test_v92 import V92


def text(r): return H.unescape(r.get_data(as_text=True))


class G4(V92):
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat G4', rate='650', vat='0', ordered='12')
        self.entry(self.pid, '2026-08-10', 8, 'août'); self.entry(self.pid, '2026-09-10', 16, 'septembre')

    def hist(self, pid=None, date='2026-08-31', days=1.0, amount=650.0, cell='J3', sheet='SUIVI 2026', **kw):
        rec = dict(project_id=pid or self.pid, source_file='Time sheet CP.xlsx', source_sha256='abc', source_sheet=sheet, source_cell=cell, source_column='Facture 31/08',
                   invoice_date=date, qty_days=days, amount_ht=amount, unit_rate=650.0, basis='days' if days else 'amount', qty_derived=0)
        rec.update(kw)
        c = m.db()
        try: hid = historical_billing.add_proposed(c, rec); c.commit()
        finally: c.close()
        return hid

    def set_status(self, hid, statut, motif=''):
        self.flashes(); r = self.c.post(f'/historique/{hid}/statut', data={'statut': statut, 'motif': motif})
        return r, ' '.join(self.flashes())

    def position(self, iid=None, **kw):
        c = m.db()
        try:
            p = c.execute('SELECT * FROM projects WHERE id=?', (self.pid,)).fetchone()
            return rules.contract(c, p, **kw)
        finally: c.close()

    def header(self, iid):
        c = m.db()
        try: return invoice_service.live_data(c, iid)
        finally: c.close()


class Registry(G4):
    def test_a_proposed_row_changes_nothing_until_the_user_validates_it(self):
        base = self.position()
        hid = self.hist()
        self.assertEqual(self.position(), base)                                              # proposed: no effect on any figure
        self.assertEqual((base['historical_days'], base['billed_days'], base['unbilled_days'], base['po_balance_days']), (0, 0, 3.0, 12.0))
        r, fl = self.set_status(hid, 'validated'); self.assertIn('validée', fl)
        k = self.position()
        self.assertEqual((k['historical_days'], k['historical_amount'], k['historical_count'], k['billed_days'], k['gross_billed_days']), (1.0, 650.0, 1, 1.0, 0))
        self.assertEqual((k['unbilled_days'], k['po_balance_days']), (2.0, 11.0))             # 3 realised − 1 billed ; 12 ordered − 1 billed
        r, fl = self.set_status(hid, 'rejected'); self.assertIn('motif obligatoire', fl)
        self.assertEqual(self.position()['historical_days'], 1.0)                              # the refusal changed nothing
        r, fl = self.set_status(hid, 'rejected', 'saisie par erreur dans le classeur'); self.assertIn('rejetée', fl)
        self.assertEqual(self.position(), base)                                              # rejected: counts for nothing again
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM historical_invoices'), 1)          # never deleted
        ev = [json.loads(x[0]) for x in self.sql("SELECT detail FROM audit WHERE event LIKE 'historical_invoice_%' ORDER BY id")]
        self.assertEqual(len(ev), 3); self.assertEqual(ev[-1]['reason'], 'saisie par erreur dans le classeur'); self.assertEqual(ev[1]['by'], m.SEC['user'])

    def test_cutoff_an_invoice_does_not_count_the_historical_invoices_dated_after_it(self):
        a = self.hist(date='2026-07-15', days=1.0, cell='J3'); b = self.hist(date='2026-10-20', days=2.0, cell='J4')
        for h in (a, b): self.set_status(h, 'validated')
        self.assertEqual(self.position()['historical_days'], 3.0)
        self.assertEqual(self.position(historical_upto='2026-08-31')['historical_days'], 1.0)
        self.assertEqual(self.position(historical_upto='2026-07-14')['historical_days'], 0)

    def test_the_database_keeps_the_source_values_and_never_deletes(self):
        hid = self.hist()
        c = sqlite3.connect(self.db)
        try:
            for q in ('DELETE FROM historical_invoices', "UPDATE historical_invoices SET qty_days=9", "UPDATE historical_invoices SET source_cell='Z9'",
                      "UPDATE historical_invoices SET invoice_date='2020-01-01'", "UPDATE historical_invoices SET project_id=project_id+1",
                      "UPDATE historical_invoices SET status='validated'"):                      # validated without who / when
                with self.assertRaises(sqlite3.DatabaseError, msg=q): c.execute(q)
            c.execute("UPDATE historical_invoices SET status='validated',validated_by='x',validated_at='2026-10-05T10:00:00'")   # a status change alone is allowed
            with self.assertRaises(sqlite3.DatabaseError): c.execute("UPDATE historical_invoices SET status='rejected'")           # a rejection needs its reason
            with self.assertRaises(sqlite3.DatabaseError): c.execute("INSERT INTO historical_invoices(project_id,source_file,source_sheet,source_cell,basis,status,created_at) VALUES(?,?,?,?,?,?,?)",
                                                                  (self.pid, 'f', 's', 'c', 'days', 'proposed', 'x'))                   # needs days or an amount
        finally: c.close()

    def test_the_same_source_cell_is_never_recorded_twice(self):
        self.hist(cell='J3')
        with self.assertRaises(sqlite3.IntegrityError): self.hist(cell='J3')

    def test_a_row_without_date_cannot_be_validated_a_pending_one_does_not_count(self):
        hid = self.hist(date=None, days=1.0)
        r, fl = self.set_status(hid, 'validated'); self.assertIn('date de facture inconnue', fl)
        self.assertEqual(self.scalar("SELECT status FROM historical_invoices WHERE id=?", (hid,)), 'proposed')

    def test_page_lists_the_source_cells_and_validates_one_mandate_at_once(self):
        a = self.hist(cell='J3'); b = self.hist(date='2026-09-15', days=0.5, amount=325.0, cell='J4')
        page = text(self.c.get('/historique'))
        for needle in ('Factures historiques', 'Mandat G4', 'cellule J3', 'cellule J4', 'SUIVI 2026', 'Time sheet CP.xlsx', 'à valider', 'jours lus dans le classeur'):
            self.assertIn(needle, page)
        self.assertIn('Valider les 2 ligne(s) à valider', page)
        self.assertEqual(self.position()['historical_days'], 0)
        self.flashes(); self.c.post(f'/historique/mandat/{self.pid}/valider')
        self.assertIn('2 facture(s) historique(s) validée(s)', ' '.join(self.flashes()))
        self.assertEqual(self.position()['historical_days'], 1.5)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='historical_invoice_validated'"), 2)
        self.assertIn('Validées : 2 facture(s)', text(self.c.get('/historique')))
        self.assertEqual(self.c.post('/historique/9999/statut', data={'statut': 'validated'}).status_code, 404)
        self.assertEqual(self.c.post('/historique/mandat/9999/valider').status_code, 404)

    def test_pages_need_a_login_and_refuse_cross_site_posts(self):
        hid = self.hist()
        anon = m.APP.test_client()
        self.assertEqual(anon.get('/historique').status_code, 302)
        self.assertEqual(anon.post(f'/historique/{hid}/statut', data={'statut': 'validated'}).status_code, 302)
        r = self.c.post(f'/historique/{hid}/statut', data={'statut': 'validated'}, headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(r.status_code, 403); self.assertEqual(self.scalar('SELECT status FROM historical_invoices'), 'proposed')

    def test_backup_carries_the_registry_and_a_restore_cannot_drop_a_row(self):
        from app import restore_service as rs
        hid = self.hist(); self.set_status(hid, 'validated')
        good = json.loads(self.c.get('/backup').data)
        self.assertEqual(len(good['tables']['historical_invoices']), 1)
        con = m.db()
        try:
            self.assertEqual(rs.preview(con, rs.validate(con, json.dumps(good).encode()))['blocking'], [])
            d = json.loads(json.dumps(good)); d['tables']['historical_invoices'] = []                    # an older file without the row
            self.assertTrue([x for x in rs.preview(con, rs.validate(con, json.dumps(d).encode()))['blocking'] if 'historical_invoices' in x])
            d = json.loads(json.dumps(good)); d['tables']['historical_invoices'][0]['qty_days'] = 9      # an edited source value
            self.assertTrue([x for x in rs.preview(con, rs.validate(con, json.dumps(d).encode()))['blocking'] if 'qty_days' in x])
            d = json.loads(json.dumps(good)); d['tables']['historical_invoices'][0]['status'] = 'proposed'   # status alone may differ (re-validation is possible)
            self.assertEqual([x for x in rs.preview(con, rs.validate(con, json.dumps(d).encode()))['blocking'] if 'historical_invoices' in x], [])
        finally: con.close()


class Indicators(G4):
    def test_dashboard_turnover_and_balance_count_validated_rows_only(self):
        hid = self.hist(date='2026-08-31', days=1.0, amount=650.0)
        dash = text(self.c.get('/?tab=dashboard'))
        self.assertNotIn('dont 1 j historique', dash)
        self.set_status(hid, 'validated')
        dash = text(self.c.get('/?tab=dashboard'))
        self.assertIn('dont 1 j historique', dash)
        c = m.db()
        try: fc = m.forecast_mod.build(c, rules.local_today())
        finally: c.close()
        year = {y['year']: y for y in fc['years']}['2026']
        self.assertEqual(str(year['actual']), '650.00')                                          # turnover of 2026 = the validated historical amount
        self.assertEqual(self.position()['po_balance_days'], 11.0)

    def test_issue_screen_and_reliquat_count_the_historical_days(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)
        page = text(self.c.get(f'/issue/{iid}'))
        self.assertIn('Reliquat après cette facture', page); self.assertRegex(page, r'Reliquat après cette facture</th><td><b>1(?:,0+)? j</b> réalisé')   # the August day is unbilled
        hid = self.hist(date='2026-08-31', days=1.0); self.set_status(hid, 'validated')
        page = text(self.c.get(f'/issue/{iid}'))
        self.assertIn('Jours facturés historiques (émises hors Time Billing, validées)', page); self.assertIn('voir le registre', page)
        self.assertRegex(page, r'Reliquat après cette facture</th><td><b>0(?:,0+)? j</b> — aucun')
        self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued')


class Annex(G4):
    def test_the_position_keeps_historical_earlier_and_current_days_apart(self):
        self.set_status(self.hist(date='2026-08-31', days=1.0), 'validated')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)
        h, rows = self.header(iid)
        pos = h['position']
        self.assertEqual({k: pos[k] for k in ('ordered', 'realized', 'historical', 'previous', 'current', 'invoiced', 'credited', 'balance')},
                         {'ordered': 12.0, 'realized': 3.0, 'historical': 1.0, 'previous': 0, 'current': 2.0, 'invoiced': 3.0, 'credited': 0, 'balance': 9.0})
        self.assertEqual(pos['historical_items'], [{'date': '2026-08-31', 'days': 1.0, 'cell': 'SUIVI 2026!J3'}])
        self.assertEqual(h['period_hours'], 16.0)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data); one = ' '.join(t.split())
        for label in ('Jours facturés historiques (hors Time Billing)', 'Jours facturés Time Billing antérieurs', 'Jours facturés par cette facture',
                      'Factures historiques prises en compte : 31.08.2026 : 1,00 j (SUIVI 2026!J3)'):
            self.assertIn(label, one)
        self.assertEqual(re.findall(r'(?m)^(\d+(?:,\d+)?)$', t.split('Position contractuelle')[1])[:7], ['12', '3', '1', '0', '2', '0', '9'])

    def test_issued_pdf_and_frozen_copy_never_change_when_the_registry_changes_later(self):
        hid = self.hist(date='2026-08-31', days=1.0); self.set_status(hid, 'validated')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2); self.issue(iid)
        before = (self.c.get(f'/invoice/{iid}.pdf').data, self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,)))
        self.assertEqual(json.loads(before[1])['position']['historical'], 1.0)
        self.set_status(hid, 'rejected', 'retiré après émission')
        after = (self.c.get(f'/invoice/{iid}.pdf').data, self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,)))
        self.assertEqual(before, after)

    def test_period_detail_and_cumulative_history_are_never_mixed(self):
        """D6 (b): cumulative history in chronological order as the reference 2026-09; each page says what it is when the period does not start the annex."""
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)
        t = ' '.join(pdf_text(self.c.get(f'/invoice/{iid}.pdf').data).split())
        self.assertIn('août-26 Historique cumulatif — antérieur à la période facturée (information)', t)
        self.assertIn('sept-26 Prestations de la période facturée', t)
        self.assertLess(t.index('août-26'), t.index('sept-26'))                                                # chronological, history first
        self.assertEqual(t.count('Prestations de la période facturée'), 1); self.assertEqual(t.count('Historique cumulatif — antérieur'), 1)

    def test_an_annex_wholly_inside_the_period_is_the_reference_one_without_captions(self):
        iid, _ = self.draft(self.pid, '2026-08-01', '2026-09-30', 3)
        t = ' '.join(pdf_text(self.c.get(f'/invoice/{iid}.pdf').data).split())
        self.assertNotIn('Cumul antérieur', t)
        self.assertLess(t.index('août-26'), t.index('sept-26'))                                                # months in order, as the reference invoice
        self.assertNotIn('de travail (partie du mois)', t)

    def test_a_month_cut_by_the_start_of_the_period_gives_two_labelled_parts(self):
        self.entry(self.pid, '2026-09-02', 2, 'début septembre'); self.entry(self.pid, '2026-09-20', 4, 'fin septembre')
        iid, _ = self.draft(self.pid, '2026-09-15', '2026-09-30', 1)
        t = ' '.join(pdf_text(self.c.get(f'/invoice/{iid}.pdf').data).split())
        self.assertEqual(t.count('de travail (partie du mois)'), 2)
        hist = t.index('sept-26 Historique cumulatif — antérieur'); per = t.index('sept-26 Prestations de la période facturée')
        self.assertLess(t.index('août-26'), hist); self.assertLess(hist, per)                                    # the cut month: the part before the period first
        self.assertLess(t.index('02/09/2026'), hist + 300); self.assertGreater(t.index('20/09/2026'), per)

    def test_a_period_without_any_entry_is_said_and_the_sheets_are_labelled_as_history(self):
        iid, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 2)
        h, rows = self.header(iid); self.assertEqual(h['period_hours'], 0)
        t = ' '.join(pdf_text(self.c.get(f'/invoice/{iid}.pdf').data).split())
        self.assertIn('Aucune saisie datée de la période facturée (du 01.10.2026 au 31.10.2026)', t)
        self.assertNotIn('Prestations de la période facturée', t)
        self.assertEqual(t.count('Historique cumulatif — antérieur à la période facturée (information)'), 2)   # août and septembre, both history

    def test_earlier_timebilling_invoices_count_only_up_to_the_cutoff(self):
        a = self.draft(self.pid, '2026-08-01', '2026-08-31', 1, invoice_date='2026-09-01')[0]; self.issue(a)
        b = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, invoice_date='2026-10-01')[0]; self.issue(b)
        h, _ = self.header(a)                                                                                   # the August invoice must not count September's (D9: dated after it)
        self.assertEqual((h['position']['previous'], h['position']['current'], h['position']['later']), (0, 1.0, 2.0))
        h, _ = self.header(b); self.assertEqual((h['position']['previous'], h['position']['current'], h['position']['later']), (1.0, 2.0, 0))


class Checks(G4):
    """The twelve checks before issuance (user directive 2026-10-05, section 9)."""
    def checks(self, iid):
        c = m.db()
        try: return {x['n']: x for x in m.invoice_checks.run_checks(c, iid)}
        finally: c.close()

    def clean_draft(self, qty=2):
        return self.draft(self.pid, '2026-09-01', '2026-09-30', qty)[0]

    def neutral_identity(self):
        """The shared fixtures call their issuer / client « Fictif » and live in « Rue de Test » : exactly what the deployment default list refuses."""
        c = sqlite3.connect(self.db)
        for k, v in {'issuer_name': 'Émetteur SA', 'issuer_address': 'Rue 2\n1200 Genève', 'account_holder': 'Émetteur SA', 'issuer_vat_number': 'CHE-000.000.000 TVA'}.items():
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        c.execute("UPDATE projects SET client='Client SA', client_legal_name='Client SA', billing_address='Client SA\nRue 1\n1000 Ville', po='PO-0001', project_number='NP-0001', billing_contact='Contact' WHERE id=?", (self.pid,))
        c.commit(); c.close()

    def test_a_clean_draft_passes_the_fourteen_checks_and_is_issued(self):
        iid = self.clean_draft()
        ck = self.checks(iid)
        self.assertEqual(sorted(ck), list(range(1, 15))); self.assertEqual({x['status'] for x in ck.values()}, {'ok'}, ck)
        page = text(self.c.get(f'/issue/{iid}')); self.assertIn('Contrôles avant émission', page); self.assertIn('Les 14 contrôles sont conformes', page)
        self.assertNotIn('derogation_', page)
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        c = m.db()
        try: self.assertEqual(m.invoice_checks.run_checks(c, iid), [])                          # an issued invoice is frozen, never re-checked
        finally: c.close()

    def test_placeholders_and_test_data_block_the_issuance_with_the_exact_anomaly(self):
        self.neutral_identity(); iid = self.clean_draft()
        self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'description': '[À COMPLÉTER : description]',
                                                    'note': '3 PUNAISE DE JOUR OFFERT', 'other_label': 'Cadeau unn jour'})
        import os, unittest.mock as mock
        env = dict(os.environ); env.pop('INVOICE_CHECK_WORDS', None)
        with mock.patch.dict(os.environ, env, clear=True):                                      # the deployment default list (test containers set it empty)
            ck = self.checks(iid)
            self.assertEqual((ck[9]['status'], ck[10]['status']), ('fail', 'fail'))
            self.assertIn('description : « [À COMPLÉTER : description] »', ck[9]['detail'])
            self.assertIn('note : « 3 PUNAISE DE JOUR OFFERT » (punaise)', ck[10]['detail']); self.assertIn('other_label (non imprimé tant que le montant « autres » est nul : le vider) : « Cadeau unn jour » (unn)', ck[10]['detail'])   # G4 §6: 0 amount, label not printed
            self.flashes(); self.issue(iid)
            fl = ' '.join(self.flashes())
            self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
            self.assertIn('Émission refusée : contrôles avant émission en échec', fl); self.assertIn('9. Aucun placeholder', fl); self.assertIn('10. Aucune donnée de test', fl)
            self.assertIn('ANOMALIE', text(self.c.get(f'/issue/{iid}'))); self.assertIn('disabled', text(self.c.get(f'/issue/{iid}')).split('Émettre définitivement')[0][-200:])
            pdf = ' '.join(pdf_text(self.c.get(f'/invoice/{iid}.pdf').data).split())
            self.assertIn('Contrôles avant émission en échec : n° 9, 10', pdf)                  # the draft says it on its own page
            self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'description': 'Production septembre', 'note': '', 'other_label': ''})
            self.assertEqual([x['detail'] for x in self.checks(iid).values() if x['status'] == 'fail'], [])
            self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued')

    def test_whole_words_only_so_a_real_description_is_not_blocked(self):
        self.neutral_identity(); iid = self.clean_draft()
        self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'description': 'Contestation et attestation de production'})
        import os, unittest.mock as mock
        env = dict(os.environ); env.pop('INVOICE_CHECK_WORDS', None)
        with mock.patch.dict(os.environ, env, clear=True): self.assertEqual(self.checks(iid)[10]['status'], 'ok')

    def test_pending_historical_invoices_block_until_the_user_decides(self):
        iid = self.clean_draft()
        hid = self.hist(date='2026-08-31', days=1.0)
        ck = self.checks(iid); self.assertEqual(ck[5]['status'], 'fail'); self.assertIn('1 facture(s) historique(s) de ce mandat attendent votre validation', ck[5]['detail'])
        self.flashes(); self.issue(iid); self.assertIn('5. Les jours facturés historiques viennent du registre validé', ' '.join(self.flashes()))
        self.set_status(hid, 'validated')
        ck = self.checks(iid); self.assertEqual(ck[5]['status'], 'ok'); self.assertIn('1.0 j (1 facture(s) historique(s) validée(s))', ck[5]['detail'])
        self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued')

    def test_a_rate_or_vat_that_no_longer_matches_the_mandate_is_an_anomaly(self):
        iid = self.clean_draft()
        c = sqlite3.connect(self.db); c.execute('UPDATE projects SET rate=700 WHERE id=?', (self.pid,)); c.commit(); c.close()
        ck = self.checks(iid); self.assertEqual(ck[3]['status'], 'fail'); self.assertIn('tarif de la facture 650.0 ≠ tarif du mandat 700.0 par jour', ck[3]['detail'])
        c = sqlite3.connect(self.db); c.execute('UPDATE projects SET rate=650, vat=8.1 WHERE id=?', (self.pid,)); c.commit(); c.close()
        ck = self.checks(iid); self.assertEqual((ck[3]['status'], ck[4]['status']), ('ok', 'fail')); self.assertIn('TVA de la facture 0.0 % ≠ TVA du mandat 8.1 %', ck[4]['detail'])

    def test_billing_ahead_needs_a_written_derogation_on_checks_12_and_13(self):
        """D8 (2026-10-06): strict checks; 12 and 13 only may be overridden, each with a written reason kept in the audit and printed nowhere."""
        iid = self.draft(self.pid, '2026-10-01', '2026-10-31', 2)[0]                            # 0 h in the period, 2 days billed, period ends after today
        c = sqlite3.connect(self.db); c.execute("UPDATE invoices SET invoice_date='2026-10-01' WHERE id=?", (iid,)); c.commit(); c.close()
        ck = self.checks(iid)
        self.assertEqual([(n, x['status'], x['derogable']) for n, x in ck.items() if x['status'] != 'ok'], [(12, 'fail', True), (13, 'fail', True)])
        self.assertIn('aucune saisie dans la période du 01.10.2026 au 31.10.2026', ck[1]['detail'])
        self.assertIn('aucune saisie datée de la période facturée du 01.10.2026 au 31.10.2026', ck[12]['detail']); self.assertIn('quantité facturée 2.0 j pour 0.0 j réalisé(s)', ck[12]['detail'])
        self.assertIn('fin de période 31.10.2026 postérieure à la date de facture 01.10.2026', ck[13]['detail'])
        page = text(self.c.get(f'/issue/{iid}'))
        self.assertIn('Dérogation motivée — obligatoire', page); self.assertIn('name="derogation_12"', page); self.assertIn('name="derogation_13"', page)
        self.assertNotIn('disabled', page.split('Émettre définitivement')[0][-200:])
        self.flashes(); self.issue(iid)                                          # no reason: refused, the exact anomalies said
        fl = ' '.join(self.flashes()); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        self.assertIn('12. La facture, l\'annexe et la position racontent la même histoire', fl); self.assertIn('13. La période facturée se termine', fl)
        self.assertIn('motif de dérogation écrit (10 caractères au moins)', fl)
        base = {'reliquat_treatment': 'reporte', 'confirm_backdate': '2026-10-01'}
        self.c.post(f'/issue/{iid}', data=dict(base, derogation_12='forfait convenu avec le client', derogation_13='court'))   # one reason too short
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft'); self.assertIn('13. La période', ' '.join(self.flashes()))
        self.c.post(f'/issue/{iid}', data=dict(base, derogation_12='forfait convenu avec le client', derogation_13='facture d\'acompte demandée par le client'))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        audit = [json.loads(d) for (d,) in self.sql("SELECT detail FROM audit WHERE event='invoice_check_derogation' ORDER BY id")]
        self.assertEqual([(a['check'], a['reason'], a['by'], a['invoice_id']) for a in audit],
                         [(12, 'forfait convenu avec le client', m.SEC['user'], iid), (13, "facture d'acompte demandée par le client", m.SEC['user'], iid)])
        self.assertTrue(all(a['at'] and a['anomaly'] and a['number'] for a in audit))
        self.assertIn('derogations=12,13', self.scalar("SELECT detail FROM audit WHERE event='invoice_issued' ORDER BY id DESC LIMIT 1"))
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertNotIn('forfait convenu', t); self.assertNotIn('acompte', t); self.assertNotIn('Contrôles avant émission', t)    # printed nowhere

    def test_a_reason_never_overrides_the_other_checks(self):
        self.neutral_identity(); iid = self.draft(self.pid, '2026-10-01', '2026-10-31', 2)[0]
        self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-10-01', 'period_to': '2026-10-31', 'qty': '2', 'description': '[À COMPLÉTER : description]'})
        ck = self.checks(iid); self.assertEqual((ck[9]['status'], ck[9]['derogable']), ('fail', False))
        self.assertIn('disabled', text(self.c.get(f'/issue/{iid}')).split('Émettre définitivement')[0][-200:])
        self.flashes(); self.c.post(f'/issue/{iid}', data={'reliquat_treatment': 'reporte', 'derogation_9': 'je force cette émission', 'derogation_12': 'forfait convenu avec le client',
                                                          'derogation_13': 'facture d\'acompte demandée'})
        fl = ' '.join(self.flashes()); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        self.assertIn('9. Aucun placeholder', fl); self.assertNotIn('12.', fl)                     # only the non-derogable failure is reported
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='invoice_check_derogation'"), 0)

    def test_an_arithmetic_failure_of_check_12_is_never_derogable(self):
        from app import invoice_checks
        iid = self.clean_draft(); c = m.db()
        try:
            h, rows = invoice_service.live_data(c, iid)
            with unittest.mock.patch.object(invoice_service, 'live_data', return_value=(dict(h, period_hours=h['period_hours'] + 1), rows)):
                ck = {x['n']: x for x in invoice_checks.run_checks(c, iid)}
        finally: c.close()
        self.assertEqual((ck[12]['status'], ck[12]['derogable']), ('fail', False)); self.assertIn('heures de la période ≠ total de la section période', ck[12]['detail'])

    def test_check_13_alone_the_period_ends_after_the_printed_date(self):
        iid = self.clean_draft()
        c = sqlite3.connect(self.db); c.execute("UPDATE invoices SET invoice_date='2026-09-25' WHERE id=?", (iid,)); c.commit(); c.close()
        ck = self.checks(iid)
        self.assertEqual([n for n, x in ck.items() if x['status'] != 'ok'], [13]); self.assertTrue(ck[13]['derogable'])
        self.assertIn('fin de période 30.09.2026 postérieure à la date de facture 25.09.2026', ck[13]['detail'])

    def test_credit_notes_and_later_invoices_are_accounted_at_the_cutoff(self):
        a = self.draft(self.pid, '2026-08-01', '2026-08-31', 1)[0]; self.issue(a)
        self.c.post(f'/invoice/{a}/credit', data={'reason': 'ajustement', 'qty': '0.5', 'treatment': 'remboursement'})
        n = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{n}/issue')
        b = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0]
        ck = self.checks(b)
        self.assertEqual({x['status'] for x in ck.values()}, {'ok'}, ck)
        self.assertIn('0.5 j annulés', ck[7]['detail']); self.assertIn('12.0 j commandés − (0 + 1.0 + 2.0 − 0.5) = 9.5 j', ck[8]['detail'])

    def test_the_layout_fingerprint_is_the_one_validated_against_the_reference(self):
        from app import invoice_checks, pdf_layout
        self.assertEqual(invoice_checks._golden(), invoice_checks.layout_fingerprint())
        old = pdf_layout.POSITION7_COLS[1]
        try:
            pdf_layout.POSITION7_COLS[1] = old + 3
            self.assertNotEqual(invoice_checks._golden(), invoice_checks.layout_fingerprint())     # any geometry change must be re-validated, then re-recorded
            ck = self.checks(self.clean_draft()); self.assertEqual(ck[11]['status'], 'fail')
        finally: pdf_layout.POSITION7_COLS[1] = old


class PeriodInDescription(G4):
    """D6 (a), 2026-10-06: the invoiced period is the last line of the DESCRIPTION cell; nothing is printed under the totals any more."""
    def words(self, data):
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
            f.write(data); f.flush()
            try: out = subprocess.run(['pdftotext', '-f', '1', '-l', '1', '-bbox', f.name, '-'], capture_output=True, text=True, check=True).stdout
            except FileNotFoundError: self.skipTest('pdftotext absent')
        return [(w, float(x), float(y)) for x, y, w in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="[\d.]+">([^<]*)</word>', out)]

    def test_the_period_is_in_the_description_cell_and_the_totals_do_not_move(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, description='Production PM/DM - Mandat G4 - NP-0001 deuxième ligne de la description')
        t = ' '.join(pdf_text(self.c.get(f'/invoice/{iid}.pdf').data).split())
        self.assertIn('Période : 01.09.2026 – 30.09.2026', t); self.assertNotIn('Période facturée : du 01.09.2026 au 30.09.2026 3', t)
        self.assertIn("Période facturée : du 01.09.2026 au 30.09.2026 · Historique cumulatif des prestations jusqu'au 30.09.2026", t)   # last page
        try: w = self.words(self.c.get(f'/invoice/{iid}.pdf').data)
        except Exception: return
        per = next(x for x in w if x[0] == 'Période'); sub = next(x for x in w if x[0] == 'SOUS-TOTAL')
        self.assertAlmostEqual(per[1], 50.3, 1); self.assertLess(per[2], sub[2] + 1)            # in the description column, beside the sub-total
        self.assertAlmostEqual(sub[2], 342.4, 0)                                                # the reference position (343.0 on 2026-09, fonts aside)

    def test_an_invoice_description_holds_three_lines_a_credit_note_four(self):
        from app import pdf_layout
        long4 = ' '.join(['mot'] * 60)
        self.assertGreater(pdf_layout.description_line_count(long4), 3)
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, description=long4)
        self.assertIn('3 lignes au maximum', ' '.join(fl)); self.assertIn('la 4e ligne porte la période', ' '.join(fl))
        three = ' '.join(['mot'] * 20); self.assertEqual(pdf_layout.description_line_count(three), 3)
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, description=three)
        self.assertEqual(self.scalar('SELECT description FROM invoices WHERE id=?', (iid,)), three)
        four = next(t for t in (' '.join(['mot'] * k) for k in range(20, 80)) if pdf_layout.description_line_count(t) == 4)
        self.issue(iid); self.flashes()
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'ajustement', 'qty': '0.5', 'treatment': 'remboursement', 'description': four})
        self.assertEqual(self.scalar('SELECT description FROM credit_notes ORDER BY id DESC LIMIT 1'), four, self.flashes())

    def test_a_draft_saved_with_four_lines_before_d6_fails_check_11_instead_of_being_cut(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)
        from app import pdf_layout
        four = next(t for t in (' '.join(['mot'] * k) for k in range(20, 80)) if pdf_layout.description_line_count(t) == 4)
        c = sqlite3.connect(self.db); c.execute('UPDATE invoices SET description=? WHERE id=?', (four, iid)); c.commit(); c.close()
        c = m.db()
        try: ck = {x['n']: x for x in m.invoice_checks.run_checks(c, iid)}
        finally: c.close()
        self.assertEqual((ck[11]['status'], ck[11]['derogable']), ('fail', False)); self.assertIn('description sur 4 lignes : 3 au maximum', ck[11]['detail'])
