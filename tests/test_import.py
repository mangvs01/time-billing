"""Historical import, invoice freezing and rollback tests.

Run inside the staging image with a COPY of the staging database:
  docker run --rm --network none -v <app>:/app/app:ro -v <tests>:/app/tests:ro -v <data>:/data -e SECRET_KEY=<random 64 hex> -e COOKIE_SECURE=0 \
    -e BASE_DB=/data/base.db -e DB_PATH=/data/boot.db -e APP_PASSWORD=<random> -w /app <image> \
    python -m unittest -v tests.test_import
Synthetic data only.
"""
import hashlib, io, os, re, shutil, sqlite3, tempfile, unittest
from datetime import date, datetime, time, timedelta

from openpyxl import Workbook

import app.app as m

FAKE_ISSUER = {'issuer_name': 'Émetteur Fictif Sàrl', 'issuer_address': 'Rue de Test 2\n1200 Genève', 'account_holder': 'Émetteur Fictif Sàrl',
               'iban': 'CH00 0000 0000 0000 0000 0', 'payment_terms': 'Paiement à 30 jours sur le compte:', 'issuer_vat_number': 'CHE-000.000.000 TVA (fictif)'}
HEADER = ['Date(s)', 'Motif', 'Projet', 'Heure début', 'Heure fin', 'Heures de travail']


def workbook(sheets, header=True, title_rows=1):
    wb = Workbook(); wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for _ in range(title_rows): ws.append([f'Feuille de temps {name}'])
        if header: ws.append(HEADER)
        for r in rows: ws.append(list(r))
    b = io.BytesIO(); wb.save(b); return b.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir='/data')
        self.db = os.path.join(self.tmp, 'timebilling.db')
        shutil.copy(os.environ['BASE_DB'], self.db)  # copy of the staging DB, never the original
        m.DB = self.db; m.init()
        m.APP.config['TESTING'] = True
        self.c = m.APP.test_client()
        r = self.c.post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
        self.assertEqual(r.status_code, 302)
        self.c.post('/settings', data=FAKE_ISSUER)  # fictitious issuer, required before any issuance
        self.p1 = self.project('Projet Alpha'); self.p2 = self.project('Projet Beta')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sql(self, q, a=()):
        c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
        try: return c.execute(q, a).fetchall()
        finally: c.close()

    def scalar(self, q, a=()):
        return self.sql(q, a)[0][0]

    def project(self, name):
        self.c.post('/project', data={'name': name, 'rate': '1000', 'day_hours': '8', 'vat': '8.1', 'client': 'Client Fictif',
                                      'billing_address': 'Client Fictif SA\nRue Imaginaire 1\n9999 Nulle-Part'})
        return self.scalar('SELECT id FROM projects WHERE name=?', (name,))

    def flashes(self):
        # RC10: reading CONSUMES the messages (a redirect never renders them), otherwise an old message can satisfy a later assertion
        with self.c.session_transaction() as s: return [m for _, m in s.pop('_flashes', [])]

    def upload(self, data, name='Time sheet test.xlsx'):
        r = self.c.post('/import', data={'workbook': (io.BytesIO(data), name)}, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 302)
        loc = r.headers['Location']
        return loc.rsplit('/', 1)[-1] if '/import/review/' in loc else None

    def review(self, token):
        r = self.c.get(f'/import/review/{token}'); self.assertEqual(r.status_code, 200); return r.get_data(as_text=True)

    def payload_names(self, token):
        return m.load_stage(token)['project_names']

    def save(self, token, mapping, decisions=None):
        names = self.payload_names(token)
        form = {f'map_{i}': str(mapping.get(n, '')) for i, n in enumerate(names)}
        for k, v in (decisions or {}).items(): form[f'd_{k}'] = v
        form['action'] = 'save'
        self.c.post(f'/import/review/{token}', data=form)
        return form

    def commit(self, token, form, ack=True, fingerprint=None):
        html = self.review(token)
        fp = fingerprint or re.search(r'name="fingerprint" value="([0-9a-f]+)"', html).group(1)
        data = dict(form, action='commit', fingerprint=fp)
        if ack: data['ack'] = '1'
        self.flashes()  # drain
        r = self.c.post(f'/import/review/{token}', data=data)
        return r, self.flashes()

    def summary(self, token):
        p = m.load_stage(token)
        c = m.db()
        try: return m.historical_import.validate(c, p, p['mapping'], p['decisions'])
        finally: c.close()

    def integrity(self):
        self.assertEqual(self.scalar('PRAGMA integrity_check'), 'ok')
        self.assertEqual(self.sql('PRAGMA foreign_key_check'), [])

    DEROGATE = ()     # rc25: no reason by default; a class whose fixtures bill on a period past today names the checks it overrides
    RECORD_WORK = False   # rc25: a class whose fixtures bill days sets True: the work billed is recorded first (check 14 is never derogable)

    def record_work(self, pid, f, t, qty, unit='day'):
        """Record, inside [f, t], the hours still missing for `qty` to be worked (nothing is added when the period already holds them)."""
        need = float(qty) * (1 if unit == 'hour' else self.scalar('SELECT day_hours FROM projects WHERE id=?', (pid,)))
        missing = round(need - self.scalar('SELECT COALESCE(SUM(hours),0) FROM entries WHERE project_id=? AND work_date BETWEEN ? AND ?', (pid, f, t)), 6)
        while missing > 0.0099:
            h = min(missing, 24.0)
            self.c.post('/entry', data={'work_date': f, 'project_id': str(pid), 'entry_mode': 'duration', 'manual_hours': str(h), 'description': 'travail enregistré pour le jeu de test'})
            missing = round(missing - h, 6)

    def issue(self, iid, treatment='reporte', derogate=None):
        from tests.test_functional import derogations
        return self.c.post(f'/issue/{iid}', data=dict({'reliquat_treatment': treatment}, **derogations(*(self.DEROGATE if derogate is None else derogate))))

    def issue_invoice(self, pid, period_from, period_to, qty='1'):
        if self.RECORD_WORK: self.record_work(pid, period_from, period_to, qty)
        self.c.post('/invoice', data={'project_id': pid, 'period_from': period_from, 'period_to': period_to, 'qty': qty})
        iid = self.scalar('SELECT MAX(id) FROM invoices')
        self.assertIsNotNone(iid, self.flashes())
        self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        return iid


class FileValidation(Base):
    def test_invalid_excel_file(self):
        self.assertIsNone(self.upload(b'not an excel file at all', 'faux.xlsx'))
        self.assertTrue(any('Classeur illisible' in f for f in self.flashes()))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM import_batches'), 0)
        self.assertFalse(os.listdir(m.import_dir()) if os.path.isdir(m.import_dir()) else [])

    def test_wrong_extension_refused(self):
        self.assertIsNone(self.upload(b'a,b\n', 'export.csv'))
        self.assertTrue(any('.xlsx' in f for f in self.flashes()))

    def test_workbook_without_prestations(self):
        data = workbook({'Résumé': [('x', 'y')], 'JAN': []})
        self.assertIsNone(self.upload(data))
        f = ' '.join(self.flashes())
        self.assertIn('Aucune prestation', f); self.assertIn('Résumé', f)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)

    def test_month_sheet_without_header_is_reported(self):
        data = workbook({'FEV': [(datetime(2025, 2, 3), 'x', 'Alpha', None, None, 1)]}, header=False)
        self.assertIsNone(self.upload(data))
        self.assertIn('en-tête', ' '.join(self.flashes()))


class Parsing(Base):
    def rows_by_desc(self, token):
        rows, summary = self.summary(token)
        return {r['description']: r for r in rows}, summary

    def test_invalid_dates_are_not_corrected(self):
        data = workbook({'MAR': [
            ('31.02.2025', 'date impossible', 'Alpha', None, None, 1),
            (45000, 'numéro de série nu', 'Alpha', None, None, 1),
            (None, 'sans date', 'Alpha', None, None, 1),
            ('15.03.2025', 'date texte lisible', 'Alpha', None, None, 1),
            (datetime(2025, 4, 2), 'hors mois', 'Alpha', None, None, 1),
            (datetime(2099, 3, 2), 'future', 'Alpha', None, None, 1),
        ]})
        t = self.upload(data); self.save(t, {'Alpha': self.p1})
        r, s = self.rows_by_desc(t)
        self.assertIn('date_unparseable', r['date impossible']['issues']); self.assertEqual(r['date impossible']['status'], 'error')
        self.assertIn('date_unparseable', r['numéro de série nu']['issues'])
        self.assertIn('date_missing', r['sans date']['issues'])
        self.assertEqual(r['date texte lisible']['work_date'], '2025-03-15'); self.assertEqual(r['date texte lisible']['status'], 'ok')
        self.assertEqual(r['hors mois']['work_date'], '2025-04-02')  # kept, not moved into March
        self.assertIn('date_outside_sheet_month', r['hors mois']['issues']); self.assertEqual(r['hors mois']['status'], 'needs_decision')
        self.assertIn('date_suspect', r['future']['issues'])
        self.assertEqual(r['date impossible']['raw']['date'], '31.02.2025')

    def test_incomplete_times_need_decision_and_keep_values(self):
        data = workbook({'MAR': [
            (datetime(2025, 3, 3), 'début seul', 'Alpha', time(9, 0), None, 2),
            (datetime(2025, 3, 3), 'fin seule', 'Alpha', None, time(17, 0), 1),
            (datetime(2025, 3, 4), 'ordre inversé', 'Alpha', time(14, 0), time(13, 0), 1),
        ]})
        t = self.upload(data); self.save(t, {'Alpha': self.p1})
        r, s = self.rows_by_desc(t)
        self.assertIn('incomplete_time_pair', r['début seul']['issues']); self.assertEqual(r['début seul']['start_time'], '09:00')
        self.assertIn('incomplete_time_pair', r['fin seule']['issues'])
        self.assertIn('time_order_ambiguous', r['ordre inversé']['issues'])
        self.assertEqual(s['by_status'].get('needs_decision'), 3)

    def test_declared_vs_clock_mismatch_is_flagged_not_fixed(self):
        data = workbook({'MAR': [
            (datetime(2025, 3, 5), 'écart', 'Alpha', time(8, 0), time(10, 0), 1.5),
            (datetime(2025, 3, 5), 'cohérent', 'Alpha', time(10, 0), time(10, 20), 0.33),
            (datetime(2025, 3, 5), 'décimal', 'Alpha', 13.5, 14.25, 0.75),
        ]})
        t = self.upload(data); self.save(t, {'Alpha': self.p1})
        r, s = self.rows_by_desc(t)
        self.assertIn('declared_vs_clock_mismatch', r['écart']['issues'])
        self.assertEqual(r['écart']['hours'], '1.5'); self.assertEqual(r['écart']['clock_hours'], '2.0000')
        self.assertNotIn('declared_vs_clock_mismatch', r['cohérent']['issues'])
        self.assertEqual((r['décimal']['start_time'], r['décimal']['end_time']), ('13:30', '14:15'))
        self.assertEqual(r['décimal']['status'], 'ok')

    def test_ambiguous_clock_fraction_is_not_guessed(self):
        data = workbook({'MAR': [(datetime(2025, 3, 6), 'fraction', 'Alpha', 0.375, 0.5, 3)]})
        t = self.upload(data); self.save(t, {'Alpha': self.p1})
        r, _ = self.rows_by_desc(t)
        self.assertIn('clock_ambiguous', r['fraction']['issues']); self.assertEqual(r['fraction']['start_time'], '')
        self.assertEqual(r['fraction']['raw']['start'], '0.375')

    def test_manual_duration_and_short_durations_preserved(self):
        data = workbook({'MAR': [
            (datetime(2025, 3, 7), 'quinze', 'Alpha', None, None, 0.25),
            (datetime(2025, 3, 7), 'trente', 'Alpha', None, None, 0.5),
            (datetime(2025, 3, 7), 'quinze format heure', 'Alpha', None, None, time(0, 15)),
            (datetime(2025, 3, 7), 'trente texte', 'Alpha', None, None, '0:30'),
            (datetime(2025, 3, 7), 'quarante-cinq virgule', 'Alpha', None, None, '0,75'),
            (datetime(2025, 3, 7), 'horaires 15 min', 'Alpha', time(11, 0), time(11, 15), 0.25),
        ]})
        t = self.upload(data); form = self.save(t, {'Alpha': self.p1})
        r, s = self.rows_by_desc(t)
        self.assertIn('manual_duration', r['quinze']['issues'])
        self.assertEqual(s['by_status'], {'ok': 6})
        resp, fl = self.commit(t, form)
        self.assertIn('Import validé', ' '.join(fl))
        got = {x['description']: x['hours'] for x in self.sql('SELECT description,hours FROM entries')}
        self.assertEqual(got, {'quinze': 0.25, 'trente': 0.5, 'quinze format heure': 0.25, 'trente texte': 0.5,
                               'quarante-cinq virgule': 0.75, 'horaires 15 min': 0.25})
        self.integrity()

    def test_repeated_prestations_are_never_merged(self):
        same = (datetime(2025, 3, 10), 'réunion', 'Alpha', time(9, 0), time(9, 30), 0.5)
        data = workbook({'MAR': [same, same, same, (datetime(2025, 3, 10), 'réunion', 'Alpha', None, None, 0.25)]})
        t = self.upload(data); form = self.save(t, {'Alpha': self.p1})
        rows, s = self.summary(t)
        self.assertEqual(s['total'], 4); self.assertEqual(s['importable'], 4)
        self.assertEqual(sum('repeated_in_file' in r['issues'] for r in rows), 3)
        self.commit(t, form)
        e = self.sql("SELECT source_ref,hours FROM entries ORDER BY id")
        self.assertEqual(len(e), 4)
        self.assertEqual([x['source_ref'] for x in e], ['MAR!3', 'MAR!4', 'MAR!5', 'MAR!6'])

    def test_total_row_is_reported_not_imported(self):
        data = workbook({'MAR': [(datetime(2025, 3, 3), 'x', 'Alpha', None, None, 1), ('TOTAL', None, None, None, None, 1)]})
        t = self.upload(data); self.save(t, {'Alpha': self.p1})
        rows, s = self.summary(t)
        self.assertIn('total_row', rows[1]['issues']); self.assertEqual(rows[1]['status'], 'error')


class Mapping(Base):
    DATA = {'MAR': [(datetime(2025, 3, 3), 'a', 'Alpha', None, None, 1),
                    (datetime(2025, 3, 3), 'b', 'Inconnu SA', None, None, 2)]}

    def test_unmapped_project_blocks_and_nothing_is_created(self):
        t = self.upload(workbook(self.DATA)); form = self.save(t, {'Alpha': self.p1})
        html = self.review(t)
        self.assertIn('Inconnu SA', html)
        self.assertRegex(html, r'id="commitBtn"\s+disabled')
        rows, s = self.summary(t)
        self.assertEqual(s['unmapped_projects'], ['Inconnu SA'])
        resp, fl = self.commit(t, form)
        self.assertIn('Associer ou exclure', ' '.join(fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM projects'), 2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM import_batches'), 0)
        self.assertFalse(os.path.isdir(m.backup_dir()) and os.listdir(m.backup_dir()))  # no backup for a refused commit

    def test_explicit_project_exclusion(self):
        t = self.upload(workbook(self.DATA)); form = self.save(t, {'Alpha': self.p1, 'Inconnu SA': 'skip'})
        resp, fl = self.commit(t, form, ack=False)
        self.assertIn('Confirmer explicitement', ' '.join(fl))
        resp, fl = self.commit(t, form, ack=True)
        self.assertIn('Import validé : 1 prestation', ' '.join(fl))
        self.assertEqual(self.scalar("SELECT decision FROM import_batch_rows WHERE source_row=4"), 'excluded_project')

    def test_decision_required_for_warnings(self):
        data = workbook({'MAR': [(datetime(2025, 3, 3), 'écart', 'Alpha', time(8, 0), time(10, 0), 1),
                                 (datetime(2025, 3, 3), 'propre', 'Alpha', None, None, 1)]})
        t = self.upload(data); form = self.save(t, {'Alpha': self.p1})
        resp, fl = self.commit(t, form)
        self.assertIn('attendent une décision', ' '.join(fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)
        form = self.save(t, {'Alpha': self.p1}, {0: 'include'})
        resp, fl = self.commit(t, form)
        self.assertIn('Import validé : 2', ' '.join(fl))
        e = self.sql("SELECT hours,start_time,end_time FROM entries WHERE description='écart'")[0]
        self.assertEqual((e['hours'], e['start_time'], e['end_time']), (1.0, '08:00', '10:00'))  # declared hours kept

    def test_changed_decisions_require_resave(self):
        t = self.upload(workbook({'MAR': [(datetime(2025, 3, 3), 'a', 'Alpha', None, None, 1)]}))
        form = self.save(t, {'Alpha': self.p1})
        form['map_0'] = 'skip'  # changed in the commit post without saving
        resp, fl = self.commit(t, form)
        self.assertIn('ont changé', ' '.join(fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)


class Transactions(Base):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def test_sql_failure_mid_import_leaves_nothing(self):
        rows = [(datetime(2025, 3, d), f'ligne {d}', 'Alpha', None, None, 1) for d in range(1, 6)]
        rows[3] = (datetime(2025, 3, 4), 'BOOM', 'Alpha', None, None, 1)
        t = self.upload(workbook({'MAR': rows})); form = self.save(t, {'Alpha': self.p1})
        c = sqlite3.connect(self.db)
        c.execute("CREATE TRIGGER test_fail BEFORE INSERT ON entries WHEN NEW.description='BOOM' BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        c.commit(); c.close()
        before = self.scalar('SELECT COUNT(*) FROM audit')
        resp, fl = self.commit(t, form)
        self.assertIn('Import annulé, aucune ligne enregistrée', ' '.join(fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM import_batch_rows'), 0)
        failed = self.sql('SELECT * FROM import_batches')
        self.assertEqual([b['status'] for b in failed], ['FAILED']); self.assertIn('injected failure', failed[0]['error'])
        self.assertEqual(failed[0]['inserted_rows'], 0)
        self.assertTrue(os.path.isfile(os.path.join(m.backup_dir(), failed[0]['backup_filename'])))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM audit') - before, 1)
        self.assertTrue(os.path.isfile(m.stage_path(t)))  # preview kept so the user can retry
        self.integrity()

    def test_preview_outdated_by_issued_invoice_is_refused(self):
        t = self.upload(workbook({'MAR': [(datetime(2025, 3, 3), 'a', 'Alpha', None, None, 1)]}))
        form = self.save(t, {'Alpha': self.p1})
        fp = re.search(r'name="fingerprint" value="([0-9a-f]+)"', self.review(t)).group(1)
        self.issue_invoice(self.p1, '2025-03-01', '2025-03-31')  # happens after the preview
        resp, fl = self.commit(t, form, fingerprint=fp)
        self.assertIn('a changé depuis la prévisualisation', ' '.join(fl))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE source='historical_excel'"), 0)

    def test_commit_provenance_and_backup(self):
        data = workbook({'MAR': [(datetime(2025, 3, 3), 'a', 'Alpha', time(8, 0), time(9, 0), 1)],
                         'AVR': [(datetime(2025, 4, 1), 'b', 'Beta', None, None, 0.5)]})
        t = self.upload(data); form = self.save(t, {'Alpha': self.p1, 'Beta': self.p2})
        resp, fl = self.commit(t, form)
        b = self.sql('SELECT * FROM import_batches')[0]
        self.assertEqual((b['status'], b['source_rows'], b['inserted_rows']), ('COMMITTED', 2, 2))
        self.assertEqual(b['file_sha256'], hashlib.sha256(data).hexdigest())
        bk = os.path.join(m.backup_dir(), b['backup_filename'])
        with open(bk, 'rb') as f: self.assertEqual(hashlib.sha256(f.read()).hexdigest(), b['backup_sha256'])
        e = self.sql("SELECT * FROM entries ORDER BY id")
        self.assertEqual([(x['source'], x['source_ref'], x['import_batch_id']) for x in e],
                         [('historical_excel', 'MAR!3', b['id']), ('historical_excel', 'AVR!3', b['id'])])
        raw = self.sql("SELECT raw_json FROM import_batch_rows WHERE source_sheet='MAR'")[0][0]
        self.assertIn('08:00:00', raw)
        self.assertFalse(os.path.isfile(m.stage_path(t)))
        self.integrity()

    def test_reimport_same_file_flags_existing_rows(self):
        data = workbook({'MAR': [(datetime(2025, 3, 3), 'a', 'Alpha', None, None, 1)]})
        t = self.upload(data); form = self.save(t, {'Alpha': self.p1}); self.commit(t, form)
        t2 = self.upload(data); self.save(t2, {'Alpha': self.p1})
        rows, s = self.summary(t2)
        self.assertIn('already_imported', rows[0]['issues']); self.assertIn('possible_existing_entry', rows[0]['issues'])
        self.assertEqual(rows[0]['status'], 'error')  # rc16 : bloquant, pas une simple décision
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 1)  # nothing deleted or merged
        # même une décision explicite « importer » ne peut pas créer de doublon
        form = self.save(t2, {'Alpha': self.p1}, {0: 'include'})
        rows, s = self.summary(t2); self.assertEqual(rows[0]['status'], 'error'); self.assertEqual(s['importable'], 0)
        resp, fl = self.commit(t2, form)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 1)
        self.assertNotIn('Import validé', ' '.join(fl))

    def test_reimport_allowed_after_batch_rollback(self):
        data = workbook({'MAR': [(datetime(2025, 3, 3), 'a', 'Alpha', None, None, 1)]})
        t = self.upload(data); form = self.save(t, {'Alpha': self.p1}); self.commit(t, form)
        b = self.scalar("SELECT id FROM import_batches WHERE status='COMMITTED'")
        self.c.post(f"/imports/rollback/{b}")
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)
        t2 = self.upload(data); form2 = self.save(t2, {'Alpha': self.p1})
        rows, s = self.summary(t2); self.assertNotIn('already_imported', rows[0]['issues'])
        resp, fl = self.commit(t2, form2); self.assertIn('Import validé : 1', ' '.join(fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 1)

    def test_import_before_issued_invoice_refused(self):
        self.issue_invoice(self.p1, '2025-03-01', '2025-03-31')
        data = workbook({'MAR': [(datetime(2025, 3, 15), 'dans période', 'Alpha', None, None, 1),
                                 (datetime(2025, 2, 10), 'avant', 'Alpha', None, None, 1)],
                         'AVR': [(datetime(2025, 4, 2), 'après', 'Alpha', None, None, 1),
                                 (datetime(2025, 3, 20), 'autre projet', 'Beta', None, None, 1)]})
        t = self.upload(data); form = self.save(t, {'Alpha': self.p1, 'Beta': self.p2})
        rows, s = self.summary(t)
        st = {r['description']: r['status'] for r in rows}
        self.assertEqual(st['dans période'], 'error'); self.assertEqual(st['avant'], 'error')
        self.assertEqual(st['après'], 'ok')
        self.assertEqual(rows[3]['status'], 'needs_decision')  # outside AVR month: warning only, other project
        form = self.save(t, {'Alpha': self.p1, 'Beta': self.p2}, {3: 'include'})
        snapshot_before = self.sql('SELECT pdf_sha256, annex_json FROM invoice_snapshots')
        resp, fl = self.commit(t, form)
        self.assertIn('Import validé : 2', ' '.join(fl))
        self.assertEqual(self.sql('SELECT pdf_sha256, annex_json FROM invoice_snapshots'), snapshot_before)


class InvoiceAndRollback(Base):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def import_rows(self, rows, mapping=None):
        t = self.upload(workbook({'MAR': rows})); form = self.save(t, mapping or {'Alpha': self.p1})
        resp, fl = self.commit(t, form); self.assertIn('Import validé', ' '.join(fl))
        return self.scalar("SELECT id FROM import_batches WHERE status='COMMITTED' ORDER BY created_at DESC, rowid DESC LIMIT 1")

    def test_draft_creation_route_works(self):
        r = self.c.post('/invoice', data={'project_id': self.p1, 'period_from': '2025-03-01', 'period_to': '2025-03-31', 'qty': '1.5'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'), 1, self.flashes())
        self.assertEqual(self.scalar('SELECT status FROM invoices'), 'draft')

    def test_full_cycle_pdf_frozen_and_immutable(self):
        batch = self.import_rows([(datetime(2025, 3, 3), 'historique', 'Alpha', None, None, 2)])
        self.c.post('/entry', data={'work_date': '2025-03-05', 'project_id': self.p1, 'entry_mode': 'duration', 'manual_hours': '1.5', 'description': 'manuelle'})
        self.c.post('/invoice', data={'project_id': self.p1, 'period_from': '2025-03-01', 'period_to': '2025-03-31', 'qty': '0.4375'})
        iid = self.scalar('SELECT id FROM invoices')
        draft = self.c.get(f'/invoice/{iid}.pdf'); self.assertEqual(draft.status_code, 200); self.assertTrue(draft.data.startswith(b'%PDF'))
        self.issue(iid)
        snap = self.sql('SELECT * FROM invoice_snapshots WHERE invoice_id=?', (iid,))[0]
        self.assertEqual(snap['frozen_by'], 'issue')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_annex_entries WHERE invoice_id=?', (iid,)), 2)
        pdf1 = self.c.get(f'/invoice/{iid}.pdf').data
        self.assertEqual(hashlib.sha256(pdf1).hexdigest(), snap['pdf_sha256'])
        # later entry inside the issued period: the issued PDF must not change
        self.c.post('/entry', data={'work_date': '2025-03-20', 'project_id': self.p1, 'entry_mode': 'duration', 'manual_hours': '3', 'description': 'tardive'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 3)
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').data, pdf1)
        c = sqlite3.connect(self.db); c.execute('PRAGMA foreign_keys=ON')
        for q in ("UPDATE invoices SET qty=99 WHERE id=%d" % iid, "DELETE FROM invoices WHERE id=%d" % iid,
                  "UPDATE invoice_snapshots SET pdf_sha256='x'", "DELETE FROM invoice_snapshots",
                  "DELETE FROM invoice_annex_entries", "UPDATE invoice_annex_entries SET entry_id=entry_id+1000"):
            with self.assertRaises(sqlite3.DatabaseError, msg=q): c.execute(q)
        # rc19: the billed entries themselves stay editable, even outside the application, but never silently (audit trace in the
        # database); the issued invoice, its frozen annex and its PDF do not move
        n0 = c.execute("SELECT COUNT(*) FROM audit WHERE event LIKE 'entry_row_%' AND detail LIKE '%\"invoiced\":1%'").fetchone()[0]
        c.execute("UPDATE entries SET hours=9 WHERE description='historique'"); c.execute("DELETE FROM entries WHERE description='manuelle'"); c.commit()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE event LIKE 'entry_row_%' AND detail LIKE '%\"invoiced\":1%'").fetchone()[0], n0 + 2)
        c.close()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_annex_entries WHERE invoice_id=?', (iid,)), 2)
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').data, pdf1)
        self.issue(iid)  # re-issue is a no-op
        self.assertEqual(self.sql('SELECT pdf_sha256 FROM invoice_snapshots WHERE invoice_id=?', (iid,))[0][0], snap['pdf_sha256'])
        self.integrity()

    def test_rollback_batch(self):
        batch = self.import_rows([(datetime(2025, 3, 3), 'a', 'Alpha', None, None, 1), (datetime(2025, 3, 4), 'b', 'Alpha', None, None, 0.25)])
        self.c.post('/entry', data={'work_date': '2025-03-05', 'project_id': self.p1, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'manuelle'})
        self.flashes(); self.c.post(f'/imports/rollback/{batch}')
        self.assertIn('Lot annulé : 2', ' '.join(self.flashes()))
        self.assertEqual([r[0] for r in self.sql('SELECT description FROM entries')], ['manuelle'])
        b = self.sql('SELECT status, rolled_back_at FROM import_batches WHERE id=?', (batch,))[0]
        self.assertEqual(b['status'], 'ROLLED_BACK'); self.assertIsNotNone(b['rolled_back_at'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM import_batch_rows WHERE batch_id=?', (batch,)), 2)  # trace kept
        self.c.post(f'/imports/rollback/{batch}')
        self.assertIn('non annulable', ' '.join(self.flashes()))
        self.integrity()

    def test_rollback_refused_when_batch_used_by_issued_invoice(self):
        batch = self.import_rows([(datetime(2025, 3, 3), 'a', 'Alpha', None, None, 1)])
        iid = self.issue_invoice(self.p1, '2025-03-01', '2025-03-31', qty='0.125')      # the imported entry holds 1 h = 0.125 j
        self.flashes(); self.c.post(f'/imports/rollback/{batch}')
        self.assertIn('Rollback refusé', ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 1)
        self.assertEqual(self.scalar('SELECT status FROM import_batches WHERE id=?', (batch,)), 'COMMITTED')
        # rc19: below the service, a billed entry is no longer frozen (entries stay editable), but its removal is traced by the
        # database itself and the issued invoice keeps its frozen copy and annex link
        snap = [tuple(r) for r in self.sql('SELECT * FROM invoice_snapshots')]
        c = sqlite3.connect(self.db); c.execute('PRAGMA foreign_keys=ON')
        c.execute('DELETE FROM entries WHERE import_batch_id=?', (batch,)); c.commit(); c.close()
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='entry_row_deleted' AND detail LIKE '%\"invoiced\":1%'"), 1)
        self.assertEqual([tuple(r) for r in self.sql('SELECT * FROM invoice_snapshots')], snap)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_annex_entries WHERE invoice_id=?', (iid,)), 1)
        self.integrity()

    def test_rollback_refused_when_invoice_period_covers_without_annex_link(self):
        batch = self.import_rows([(datetime(2025, 3, 3), 'a', 'Alpha', None, None, 1)])
        c = sqlite3.connect(self.db)  # simulate an issued invoice whose annex predates the batch
        c.execute("INSERT INTO invoices(number,project_id,period_from,period_to,qty,unit,unit_rate,status,issued_at) VALUES('2025-900',?,'2025-03-10','2025-03-31',1,'day',1000,'issued','2025-04-01')", (self.p1,))
        c.commit(); c.close()
        self.flashes(); self.c.post(f'/imports/rollback/{batch}')
        self.assertIn('Rollback refusé', ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 1)

    def test_rollback_failure_is_atomic(self):
        batch = self.import_rows([(datetime(2025, 3, d), f'r{d}', 'Alpha', None, None, 1) for d in (3, 4, 5)])
        c = sqlite3.connect(self.db)
        c.execute("CREATE TRIGGER test_fail_del BEFORE DELETE ON entries WHEN OLD.description='r5' BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        c.commit(); c.close()
        self.flashes(); self.c.post(f'/imports/rollback/{batch}')
        self.assertIn('injected failure', ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 3)
        self.assertEqual(self.scalar('SELECT status FROM import_batches WHERE id=?', (batch,)), 'COMMITTED')

    def test_legacy_issued_invoice_frozen_by_migration(self):
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO entries(work_date,project_id,hours,description) VALUES('2025-01-10',?,4,'ancienne')", (self.p1,))
        c.execute("INSERT INTO invoices(number,project_id,period_from,period_to,qty,unit,unit_rate,status,issued_at) VALUES('2025-001',?,'2025-01-01','2025-01-31',0.5,'day',1000,'issued','2025-02-01')", (self.p1,))
        c.commit(); c.close()
        m.init(); m.init()  # idempotent
        s = self.sql("SELECT frozen_by FROM invoice_snapshots")
        self.assertEqual([r[0] for r in s], ['migration-v9.2 (rendu V9.0)'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_annex_entries'), 1)
        iid = self.scalar("SELECT id FROM invoices WHERE number='2025-001'")
        self.assertTrue(self.c.get(f'/invoice/{iid}.pdf').data.startswith(b'%PDF'))


class Routes(Base):
    def test_token_validation(self):
        self.assertEqual(self.c.get('/import/review/..%2F..%2Fetc').status_code, 404)
        self.assertEqual(self.c.get('/import/review/' + 'a' * 32).status_code, 404)

    def test_review_page_renders_all_rows(self):
        rows = [(datetime(2025, 3, 1) + timedelta(days=i % 28), f'l{i}', 'Alpha', None, None, 0.25) for i in range(300)]
        t = self.upload(workbook({'MAR': rows}))
        html = self.review(t)
        self.assertEqual(html.count('data-status='), 300)
        self.assertIn('MAR!302', html)

    def test_index_tabs(self):
        html = self.c.get('/').get_data(as_text=True)
        self.assertIn('>Édition des factures</button>', html); self.assertNotIn('Réalisation des factures', html)
        for t in ('Tableau de bord', 'Saisie des heures', 'Mandats & prévisionnel', 'Import historique'):
            self.assertIn(t, html)

    def test_login_required(self):
        anon = m.APP.test_client()
        for url in ('/import/review/' + 'a' * 32, '/'):
            self.assertEqual(anon.get(url).status_code, 302)
        self.assertEqual(anon.post('/imports/rollback/x').status_code, 302)


if __name__ == '__main__':
    unittest.main()
