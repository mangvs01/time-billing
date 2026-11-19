"""rc23 (Decision Center billing-g4-correction-historiques = A_CORRIGER_PAR_REMPLACEMENT, 2026-10-08): a wrong historical invoice is rejected with
its reason and replaced by a corrected row, validated by the same gesture; a missing one can be added. The values read from the workbook are never
rewritten, everything is traced, and one invoice is never counted twice. Synthetic data only, on a COPY of the staging database.
"""
import json

import app.app as m
from app import billing_rules as rules, historical_billing as hb
from tests.test_g4 import G4, text


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N


class Base(G4):
    def correct(self, hid, **form):
        data = {'invoice_date': '2026-08-31', 'qty_days': '1', 'amount_ht': '650', 'invoice_ref': '', 'motif': 'montant de la facture réelle'}
        data.update(form)
        self.flashes(); r = self.c.post(f'/historique/{hid}/corriger', data=data)
        return r, ' '.join(self.flashes()) + (text(r) if r.status_code == 200 else '')       # a refusal shows the form again, with its message

    def add(self, **form):
        data = {'project_id': str(self.pid), 'invoice_date': '2026-07-31', 'qty_days': '2', 'amount_ht': '1300', 'invoice_ref': '', 'motif': 'facture Word absente du classeur'}
        data.update(form)
        self.flashes(); r = self.c.post('/historique/ajouter', data=data)
        return r, ' '.join(self.flashes()) + (text(r) if r.status_code == 200 else '')

    def row(self, hid):
        c = m.db()
        try: return dict(c.execute('SELECT * FROM historical_invoices WHERE id=?', (hid,)).fetchone())
        finally: c.close()

    def audit(self, event):
        c = m.db()
        try: return [json.loads(r[0]) for r in c.execute('SELECT detail FROM audit WHERE event=? ORDER BY id', (event,))]
        finally: c.close()


class Correction(Base):
    DEROGATE = (12,)   # rc25: fixtures of this class bill days without matching recorded work (or a period past today): these checks are overridden, explicitly
    def test_a_validated_row_is_replaced_and_its_source_values_are_kept(self):
        hid = self.hist(date='2026-08-31', days=1.0, amount=650.0); self.set_status(hid, 'validated')
        page = text(self.c.get(f'/historique/{hid}/corriger'))
        for needle in ('Corriger la facture historique n° %d' % hid, 'SUIVI 2026!J3', 'value="2026-08-31"', 'value="650.00"', 'jamais réécrites'):
            self.assertIn(needle, page)
        r, fl = self.correct(hid, invoice_date='2026-08-28', qty_days='1.5', amount_ht='975', invoice_ref='2026-08', motif='facture réelle du 28.08 : 1,5 j')
        self.assertEqual(r.status_code, 302); self.assertIn(f'la ligne n° {hid} est remplacée par la ligne n° {hid + 1}, validée', fl)
        old, new = self.row(hid), self.row(hid + 1)
        self.assertEqual((old['status'], old['invoice_date'], old['qty_days'], old['amount_ht'], old['source_file']),
                         ('rejected', '2026-08-31', 1.0, 650.0, 'Time sheet CP.xlsx'))                          # the workbook values stay as read
        self.assertIn(f'remplacée par la correction n° {hid + 1} : facture réelle du 28.08 : 1,5 j', old['note'])
        self.assertEqual((new['status'], new['invoice_date'], new['qty_days'], new['amount_ht'], new['invoice_ref'], new['unit_rate'], new['basis']),
                         ('validated', '2026-08-28', 1.5, 975.0, '2026-08', 650.0, 'days'))
        self.assertEqual((new['source_file'], new['source_sheet'], new['source_cell'], new['source_column'], new['validated_by']),
                         (hb.MANUAL_FILE, 'SUIVI 2026', 'J3 (correction 1)', 'Facture 31/08', 'admin'))
        self.assertIn(f'Correction de SUIVI 2026!J3 (ligne n° {hid})', new['note'])
        k = self.position()
        self.assertEqual((k['historical_days'], k['historical_amount'], k['historical_count']), (1.5, 975.0, 1))   # counted once, with the corrected values
        a = self.audit('historical_invoice_corrected')
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]['id'], a[0]['replaces'], a[0]['before'], a[0]['after'], a[0]['reason']),
                         (hid + 1, hid, {'date': '2026-08-31', 'days': 1.0, 'amount_ht': 650.0, 'ref': None},
                          {'date': '2026-08-28', 'days': 1.5, 'amount_ht': 975.0, 'ref': '2026-08'}, 'facture réelle du 28.08 : 1,5 j'))
        self.assertEqual([x['id'] for x in self.audit('historical_invoice_rejected')], [hid])
        page = text(self.c.get('/historique'))
        for needle in ('SUIVI 2026!J3 (correction 1)', 'valeurs saisies dans Time Billing', 'remplacée par la correction n°', 'Validées : 1 facture(s), 1,5000 j'):
            self.assertIn(needle, page)
        c = m.db()
        try: self.assertEqual(hb.amounts_by_year(c)['2026'], rules.amounts(1, 975.0, 0)['ht'])
        finally: c.close()                  # turnover of the year (D9: date of the invoice)

    def test_a_proposed_row_is_replaced_by_a_validated_one(self):
        hid = self.hist(days=1.0, amount=650.0)
        r, fl = self.correct(hid, amount_ht='700', motif='montant HT de la facture réelle')
        self.assertIn('remplacée', fl)
        self.assertEqual((self.row(hid)['status'], self.row(hid + 1)['status'], self.row(hid + 1)['unit_rate']), ('rejected', 'validated', 700.0))
        self.assertEqual(self.position()['historical_amount'], 700.0)

    def test_a_rejected_row_can_still_be_corrected_its_note_says_so(self):
        hid = self.hist(); self.set_status(hid, 'rejected', 'date fausse dans le classeur')
        r, fl = self.correct(hid, invoice_date='2026-08-30', motif='date de la facture réelle')
        self.assertIn('remplacée', fl)
        old = self.row(hid)
        self.assertEqual(old['status'], 'rejected'); self.assertIn('date fausse dans le classeur', old['note']); self.assertIn(f'Corrigée par la ligne n° {hid + 1}', old['note'])
        self.assertEqual(self.row(hid + 1)['status'], 'validated'); self.assertEqual(self.position()['historical_days'], 1.0)

    def test_refusals_leave_everything_unchanged(self):
        hid = self.hist(); self.set_status(hid, 'validated')
        iid = self.issued(self.pid, '2026-09-01', '2026-09-30', 1)
        number = self.scalar('SELECT number FROM invoices WHERE id=?', (iid,))
        other = self.hist(cell='J9', date='2026-07-31', invoice_ref='2026-07')
        tomorrow = rules.local_today().toordinal() + 1
        from datetime import date
        for form, msg in (({'motif': ''}, 'motif obligatoire'), ({}, 'aucune valeur modifiée'),
                          ({'invoice_date': date.fromordinal(tomorrow).isoformat()}, 'dans le futur'), ({'invoice_date': ''}, 'date de facture obligatoire'),
                          ({'qty_days': '', 'amount_ht': ''}, 'indiquer les jours facturés'),
                          ({'qty_days': '0'}, 'Jours facturés invalide'), ({'qty_days': '-1'}, 'Jours facturés invalide'), ({'amount_ht': '-5'}, 'montant HT : nombre positif ou nul attendu'),
                          ({'qty_days': '1e1'}, 'Jours facturés invalide'), ({'invoice_ref': number}, 'facture Time Billing'),
                          ({'invoice_ref': '2026-07'}, f'facture historique n° {other}'), ({'motif': 'a\u202eb'}, 'U+202E'), ({'invoice_ref': '2026-10\u200b'}, 'aucun espace ni caractère invisible'),
                          ({'invoice_ref': '2026 10'}, 'aucun espace ni caractère invisible'), ({'amount_ht': ''}, 'le montant HT ne peut pas être vidé')):
            r, fl = self.correct(hid, **form)
            self.assertEqual(r.status_code, 200, form); self.assertIn('Correction non enregistrée : ', fl, form)
            self.assertIn(msg, fl.split('Correction non enregistrée : ', 1)[1].split('</div>', 1)[0], form)       # in the refusal message itself, not elsewhere on the page
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM historical_invoices'), 2)
        self.assertEqual(self.row(hid)['status'], 'validated'); self.assertEqual(self.audit('historical_invoice_corrected'), [])
        self.assertEqual(self.c.get('/historique/9999/corriger').status_code, 404)
        self.assertEqual(self.c.post('/historique/9999/corriger', data={'invoice_date': '2026-08-31', 'qty_days': '1', 'motif': 'x'}).status_code, 404)

    def test_the_same_invoice_is_never_counted_twice_and_a_correction_can_be_corrected(self):
        hid = self.hist(); self.set_status(hid, 'validated')
        self.correct(hid, qty_days='2', amount_ht='1300', motif='2 jours facturés')
        r, fl = self.set_status(hid, 'validated')                                     # re-validating the replaced row: refused
        self.assertIn(f'la ligne n° {hid + 1} (SUIVI 2026!J3 (correction 1)) est déjà validée', fl)
        self.assertEqual(self.position()['historical_days'], 2.0)
        r, fl = self.correct(hid + 1, qty_days='2.5', amount_ht='1625', motif='2,5 jours en réalité')
        self.assertIn('remplacée', fl)
        self.assertEqual((self.row(hid + 1)['status'], self.row(hid + 2)['source_cell'], self.row(hid + 2)['status']), ('rejected', 'J3 (correction 2)', 'validated'))
        self.assertIn(f'Correction de SUIVI 2026!J3 (correction 1) (ligne n° {hid + 1})', self.row(hid + 2)['note'])
        r, fl = self.correct(hid, qty_days='3', amount_ht='1950', motif='depuis la ligne d’origine')     # from the original row: the validated correction blocks
        self.assertIn('Correction non enregistrée', fl); self.assertIn(f'la ligne n° {hid + 2}', fl)
        self.assertEqual(self.position()['historical_days'], 2.5)
        self.set_status(hid + 2, 'rejected', 'finalement fausse'); self.set_status(hid, 'validated')   # back to the workbook value: possible, traced
        self.assertEqual(self.position()['historical_days'], 1.0)
        other = self.hist(cell='J30', date='2026-06-30')                              # another cell, imported only: the usual rules
        self.set_status(other, 'validated'); self.assertEqual(self.position()['historical_count'], 2)

    def test_a_missing_invoice_is_added_validated_and_printed_with_its_provenance(self):
        page = text(self.c.get('/historique'))
        self.assertIn('Ajouter une facture historique manquante', page)
        self.assertIn('Mandat G4', text(self.c.get('/historique/ajouter')))
        r, fl = self.add(project_id='')
        self.assertIn('Facture historique non ajoutée : mandat à choisir', fl)
        r, fl = self.add(motif='')
        self.assertIn('motif obligatoire', fl)
        r, fl = self.add(); self.assertRegex(fl, r'Facture historique ajoutée \(Mandat G4\) : ligne n° \d+, validée')
        r, fl = self.add(invoice_date='2026-06-30', qty_days='', amount_ht='300', motif='frais facturés seuls')
        ids = [r[0] for r in m.db().execute("SELECT id FROM historical_invoices WHERE source_sheet='ajout manuel' ORDER BY id")]
        rows = [self.row(i) for i in ids]
        self.assertEqual([(x['source_sheet'], x['source_cell'], x['status'], x['basis'], x['qty_days'], x['amount_ht']) for x in rows],
                         [('ajout manuel', 'n° 1', 'validated', 'days', 2.0, 1300.0), ('ajout manuel', 'n° 2', 'validated', 'amount_only', None, 300.0)])
        self.assertEqual(len(self.audit('historical_invoice_added')), 2)
        k = self.position(); self.assertEqual((k['historical_days'], k['historical_amount']), (2.0, 1600.0))
        self.assertIn('ajout manuel n° 1', text(self.c.get('/historique')))
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 1)
        h, _ = self.header(iid)
        self.assertEqual(h['position']['historical_items'], [{'date': '2026-07-31', 'days': 2.0, 'cell': 'ajout manuel n° 1'}])
        self.correct(ids[0], qty_days='3', amount_ht='1950', motif='3 jours')
        self.assertEqual(self.row(ids[1] + 1)['source_cell'], 'n° 1 (correction 1)')
        self.assertEqual(self.position()['historical_days'], 3.0)

    def test_the_database_still_refuses_any_rewrite_of_a_recorded_value(self):
        hid = self.hist(); self.correct(hid, qty_days='2', amount_ht='1300', motif='2 jours')
        c = m.db()
        try:
            for hid_ in (hid, hid + 1):
                with self.assertRaises(Exception): c.execute('UPDATE historical_invoices SET qty_days=9 WHERE id=?', (hid_,))
                with self.assertRaises(Exception): c.execute('DELETE FROM historical_invoices WHERE id=?', (hid_,))
        finally: c.close()

    def test_backup_and_restore_carry_the_corrections(self):
        from app import restore_service as rs
        hid = self.hist(); self.set_status(hid, 'validated'); self.correct(hid, qty_days='2', amount_ht='1300', motif='2 jours')
        good = json.loads(self.c.get('/backup').data)
        self.assertEqual(len(good['tables']['historical_invoices']), 2)
        con = m.db()
        try: self.assertEqual(rs.preview(con, rs.validate(con, json.dumps(good).encode()))['blocking'], [])
        finally: con.close()

    def test_pages_need_a_login_and_refuse_cross_site_posts(self):
        hid = self.hist()
        anon = m.APP.test_client()
        for url in (f'/historique/{hid}/corriger', '/historique/ajouter'):
            self.assertEqual(anon.get(url).status_code, 302)
            self.assertEqual(anon.post(url, data={'invoice_date': '2026-08-31', 'qty_days': '2', 'motif': 'x', 'project_id': str(self.pid)}).status_code, 302)
            r = self.c.post(url, data={'invoice_date': '2026-08-31', 'qty_days': '2', 'motif': 'x', 'project_id': str(self.pid)},
                            headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'})
            self.assertEqual(r.status_code, 403)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM historical_invoices'), 1)


class ReviewFindings(Base):
    """Adversarial review of rc23 (2026-10-08): one real invoice is never counted twice, whatever the path."""

    def test_an_added_invoice_then_the_same_number_imported_is_never_validated_twice(self):
        r, fl = self.add(invoice_date='2026-10-01', qty_days='8', amount_ht='5200', invoice_ref='2026-09', motif='CIRSE ajoutée avant le chargement')
        self.assertIn('ajoutée', fl)
        from outils import charger_factures_historiques as tool
        rec = dict(mandate='Mandat G4', source_file=tool.SOURCE_FILE, source_sheet='SUIVI 2026', source_cell='Q12', source_column='Facture 01.10', invoice_date='2026-10-01',
                   invoice_ref='2026-09', qty_days=8.0, amount_ht=5200.0, unit_rate=650.0, basis='amount', qty_derived=1, note='', raw=5200)
        c = m.db()
        try:
            ids = {x['name']: x['id'] for x in c.execute('SELECT id,name FROM projects')}
            with self.assertRaises(SystemExit) as e: tool.insert(c, [rec], ids, tool.WORKBOOK_SHA256, hb)
            c.rollback()
        finally: c.close()
        self.assertIn('déjà enregistré sur la facture historique', str(e.exception))
        hid = self.hist(cell='Q12', date='2026-10-01', days=8.0, amount=5200.0, invoice_ref='2026-09')    # inserted anyway (bypassing the tool)
        self.flashes(); self.c.post(f'/historique/mandat/{self.pid}/valider')
        self.assertIn('le n° 2026-09 est déjà validé sur la ligne', ' '.join(self.flashes()))
        self.assertEqual(self.row(hid)['status'], 'proposed'); self.assertEqual(self.position()['historical_days'], 8.0)

    def test_a_double_submission_of_an_addition_records_one_row(self):
        self.add(); r, fl = self.add()
        self.assertIn('Facture historique non ajoutée', fl); self.assertIn("cocher « Il s'agit d'une autre facture »", fl)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM historical_invoices"), 1)
        r, fl = self.add(confirm_similar='1')                                        # identical in every value: still one invoice only
        self.assertIn('déjà validée avec la même date, les mêmes jours et le même montant', fl)
        r, fl = self.add(confirm_similar='1', amount_ht='1400', motif='seconde facture du même jour')   # confirmed, different amount: recorded
        self.assertIn('ajoutée', fl); self.assertEqual(self.scalar("SELECT COUNT(*) FROM historical_invoices WHERE status='validated'"), 2)

    def test_a_rejected_import_replaced_by_an_addition_cannot_be_revalidated_on_top(self):
        hid = self.hist(date='2026-08-31', days=1.0, amount=650.0); self.set_status(hid, 'rejected', 'mal lue')
        self.add(invoice_date='2026-08-31', qty_days='1', amount_ht='650', confirm_similar='1', motif='ressaisie')
        r, fl = self.set_status(hid, 'validated')
        self.assertIn('déjà validée avec la même date', fl); self.assertEqual(self.position()['historical_days'], 1.0)

    def test_a_replaced_row_points_to_its_correction_instead_of_offering_a_correction(self):
        hid = self.hist(); self.set_status(hid, 'validated'); self.correct(hid, qty_days='2', amount_ht='1300', motif='2 jours')
        page = text(self.c.get('/historique'))
        self.assertIn(f'remplacée par la ligne n° {hid + 1} (validée)', page)
        self.assertNotIn(f'/historique/{hid}/corriger', page); self.assertIn(f'/historique/{hid + 1}/corriger', page)

    def test_a_rate_different_from_the_mandate_is_flagged_after_saving(self):
        hid = self.hist(); self.set_status(hid, 'validated')
        r, fl = self.correct(hid, qty_days='1.5', motif='1,5 j')                    # amount left at 650: 433,33 CHF/j
        self.assertIn('remplacée', fl); self.assertIn('433,33 CHF/j, alors que le tarif du mandat est 650,00 CHF/j', fl)

    def test_a_restore_file_validating_one_invoice_twice_is_blocked(self):
        from app import restore_service as rs
        hid = self.hist(); self.set_status(hid, 'validated'); self.correct(hid, qty_days='2', amount_ht='1300', motif='2 jours')
        good = json.loads(self.c.get('/backup').data)
        d = json.loads(json.dumps(good))
        for r in d['tables']['historical_invoices']: r['status'] = 'validated'
        con = m.db()
        try:
            self.assertEqual(rs.preview(con, rs.validate(con, json.dumps(good).encode()))['blocking'], [])
            self.assertTrue([x for x in rs.preview(con, rs.validate(con, json.dumps(d).encode()))['blocking'] if '2 lignes validées pour SUIVI 2026!J3' in x])
        finally: con.close()
        self.assertEqual(hb.validation_conflicts([{'status': 'validated', 'invoice_ref': '2026-09', 'id': 1, 'source_sheet': 'A', 'source_cell': 'B1', 'source_file': 'x'},
                                                  {'status': 'validated', 'invoice_ref': '2026-09', 'id': 2, 'source_sheet': 'A', 'source_cell': 'B2', 'source_file': 'x'}]),
                         ['factures historiques : n° 2026-09 validé sur 2 lignes (1, 2)'])

    def test_a_real_restore_round_trip_keeps_the_corrections(self):
        import io
        hid = self.hist(); self.set_status(hid, 'validated'); self.correct(hid, qty_days='2', amount_ht='1300', motif='2 jours')
        raw = self.c.get('/backup').data
        before = self.sql('SELECT id,status,source_cell,qty_days,amount_ht,note FROM historical_invoices ORDER BY id')
        r = self.c.post('/restore', data={'backup': (io.BytesIO(raw), 'sauvegarde.json')}, content_type='multipart/form-data')
        token = r.headers['Location'].rstrip('/').rsplit('/', 1)[1]
        self.assertNotIn('Restauration bloquée', text(self.c.get(f'/restore/{token}')))
        self.flashes(); self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        self.assertIn('restaur', ' '.join(self.flashes()).lower())
        self.assertEqual(self.sql('SELECT id,status,source_cell,qty_days,amount_ht,note FROM historical_invoices ORDER BY id'), before)
        self.assertEqual(self.position()['historical_days'], 2.0)


class TimeBillingNumberRefused(Base):
    """Owner decision O3 (Q2, 2026-10-11): a historical row whose reference is the number of an invoice of Time Billing cannot be validated (double counting)."""

    def issued_tb(self, f='2026-08-01', t='2026-08-31', qty=1):
        iid, _ = self.draft(self.pid, f, t, qty); self.issue(iid); self.flashes()
        return self.scalar('SELECT number FROM invoices WHERE id=?', (iid,))

    def test_a_row_under_a_time_billing_number_is_refused_with_a_clear_message(self):
        n = self.issued_tb(); self.assertEqual(n, f'{YEAR}-1')
        hid = self.hist(date='2026-08-31', days=1.0, amount=650.0, invoice_ref=n)
        r, fl = self.set_status(hid, 'validated')
        self.assertIn(f"le n° {YEAR}-1 est celui d'une facture Time Billing", fl); self.assertIn('comptée deux fois', fl)
        self.assertEqual(self.row(hid)['status'], 'proposed'); self.assertEqual(self.position()['historical_days'], 0)
        self.assertEqual(self.audit('historical_invoice_validated'), [])

    def test_the_number_of_a_second_invoice_is_refused_too(self):
        self.entry(self.pid, '2026-08-25', 8, 'fin août')                                            # 1 j worked on 08-10 (setUp), 1 j on 08-25: one day per half-month, no check 12 gap
        a = self.issued_tb('2026-08-01', '2026-08-15'); b = self.issued_tb('2026-08-16', '2026-08-31')
        self.assertEqual((a, b), (f'{YEAR}-1', f'{YEAR}-2'))
        hid = self.hist(date='2026-08-31', days=1.0, invoice_ref=b)
        self.assertIn("est celui d'une facture Time Billing", self.set_status(hid, 'validated')[1])

    def test_the_refusal_also_stops_a_correction_and_a_manual_addition(self):
        n = self.issued_tb()
        r, fl = self.add(invoice_ref=n); self.assertIn("est celui d'une facture Time Billing", fl)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM historical_invoices WHERE status='validated'"), 0)
        hid = self.hist(); self.set_status(hid, 'validated')
        r, fl = self.correct(hid, invoice_ref=n); self.assertIn("est celui d'une facture Time Billing", fl)
        self.assertEqual(self.row(hid)['status'], 'validated')                                        # nothing replaced, nothing lost

    def test_a_number_that_time_billing_never_issued_is_accepted(self):
        self.issued_tb()                                                                              # Time Billing holds AAAA-1 only
        hid = self.hist(date='2026-09-30', days=1.0, amount=650.0, invoice_ref=f'{YEAR}-9')          # same format, issued outside (CIRSE-like): valid
        r, fl = self.set_status(hid, 'validated'); self.assertEqual(self.row(hid)['status'], 'validated', fl)
        self.assertEqual(self.position()['historical_days'], 1.0)

    def test_references_that_do_not_have_the_time_billing_format_are_accepted(self):
        self.issued_tb()
        for i, ref in enumerate(('F2025/11', '2026-8', '2026-08-1', '2026-13', '2026-08-2x', '', None)):
            hid = self.hist(cell=f'K{i}', date='2026-07-31', days=0.25, amount=162.5, invoice_ref=ref)
            r, fl = self.set_status(hid, 'validated'); self.assertEqual(self.row(hid)['status'], 'validated', (ref, fl))

    def test_the_format_is_the_one_of_the_proposed_numbers_and_of_earlier_releases(self):
        """rc37: AAAA-N (proposed) and AAAA-MM[-N] (earlier releases) are « numbers Time Billing issues »; nothing else is."""
        for ref, ok in (('2026-1', True), ('2026-11', True), ('2026-13', True), ('2026-09', True), ('2026-09-2', True), ('2026-09-02', True), ('2026-00', True),
                        ('2026-', False), ('2026-09-', False), (' 2026-09', False), ('2026-09\n', False), ('26-1', False), ('2026-1234567', False), ('F2025/11', False)):
            self.assertEqual(bool(hb.TB_NUMBER_RE.fullmatch(ref)), ok, repr(ref))