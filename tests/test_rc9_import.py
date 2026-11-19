"""RC9 historical-import improvements P1-P5, synthetic data only. Same harness as tests.test_import."""
import io, json, unittest
from datetime import datetime, time
from openpyxl import Workbook
from tests.test_import import Base, HEADER


def wb_with_header_date(sheets):
    """Monthly sheets like the real workbook: B2 holds a header date, the column header comes after."""
    wb = Workbook(); wb.remove(wb.active)
    for name, (hdr, rows) in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(['Mois', hdr]); ws.append([]); ws.append(['Total', None])
        ws.append(HEADER)
        for r in rows: ws.append(list(r))
    b = io.BytesIO(); wb.save(b); return b.getvalue()


class ImportRC9(Base):
    def go(self, data, mapping=None):
        t = self.upload(data); self.save(t, mapping or {'Alpha': self.p1, 'Beta': self.p2}); rows, s = self.summary(t)
        return t, {(r['source_sheet'], r['source_row']): r for r in rows}, s

    # P1
    def test_p1_year_from_header_date_flags_2015_and_never_corrects(self):
        d = wb_with_header_date({'JAN': (datetime(2025, 1, 1), [
            (datetime(2015, 1, 7), 'ancienne', 'Alpha', None, None, 1), (datetime(2025, 1, 8), 'normale', 'Alpha', None, None, 1)])})
        t, r, s = self.go(d)
        a = r[('JAN', 5)]
        self.assertIn('year_differs_from_sheet', a['issues']); self.assertEqual(a['work_date'], '2015-01-07')  # not corrected
        self.assertEqual(a['status'], 'needs_decision'); self.assertEqual(a['raw']['date'][:10], '2015-01-07')
        self.assertEqual(r[('JAN', 6)]['status'], 'ok')

    # P2
    def test_p2_unlabelled_subtotal_is_a_total_not_an_entry(self):
        d = wb_with_header_date({'JAN 26': (datetime(2026, 1, 1), [
            (datetime(2026, 1, 5), 'x', 'Alpha', None, None, 1), (None, None, None, None, None, 82.5), (datetime(2026, 1, 6), None, None, None, None, 122.65)])})
        t, r, s = self.go(d)
        self.assertEqual([i for i in r[('JAN 26', 6)]['issues'] if i != 'manual_duration'], ['total_row']); self.assertEqual(r[('JAN 26', 6)]['status'], 'error')
        self.assertEqual([i for i in r[('JAN 26', 7)]['issues'] if i != 'manual_duration'], ['total_row'])  # a dated one too

    # P3
    def test_p3_blank_template_rows_ignored_and_counted_not_errors(self):
        d = wb_with_header_date({'JAN': (datetime(2025, 1, 1), [
            (datetime(2025, 1, 8), 'a', 'Alpha', None, None, 1), (None, None, None, None, None, 0), (None, None, None, None, None, 0)])})
        t, r, s = self.go(d)
        self.assertEqual(s['total'], 1); self.assertEqual(s['by_status'], {'ok': 1})
        self.assertEqual(self.m_load(t)['ignored_blank'], {'JAN': 2})

    def m_load(self, t):
        import app.app as m; return m.load_stage(t)

    def test_p3_other_sheet_copy_needs_decision_same_sheet_copies_kept(self):
        e = (datetime(2025, 9, 12), 'réunion', 'Alpha', time(9, 0), time(9, 30), 0.5)
        d = wb_with_header_date({'AUG': (datetime(2025, 8, 1), [e]), 'SEPT': (datetime(2025, 9, 1), [e, e])})
        t, r, s = self.go(d)
        c = r[('AUG', 5)]
        self.assertIn('duplicate_other_sheet', c['issues']); self.assertEqual(c['status'], 'needs_decision'); self.assertEqual(c['duplicate_of'], 'SEPT!5')
        self.assertEqual(r[('SEPT', 5)]['status'], 'ok'); self.assertEqual(r[('SEPT', 6)]['status'], 'ok')  # repeated in same sheet: preserved
        self.assertIn('repeated_in_file', r[('SEPT', 6)]['issues'])
        self.assertEqual(s['importable'], 2)  # nothing removed automatically: the AUG copy waits for a decision

    def test_p3_same_day_same_project_distinct_entries_all_kept(self):
        d = wb_with_header_date({'MAR': (datetime(2025, 3, 1), [
            (datetime(2025, 3, 10), 'a', 'Alpha', time(9, 0), time(10, 0), 1), (datetime(2025, 3, 10), 'b', 'Alpha', time(10, 0), time(11, 0), 1),
            (datetime(2025, 3, 10), 'a', 'Alpha', time(13, 0), time(14, 0), 1)])})
        t, r, s = self.go(d); self.assertEqual(s['importable'], 3)

    # P4
    def test_p4_overlap_flagged_but_not_for_back_to_back_or_exact_copies(self):
        d = wb_with_header_date({'MAR': (datetime(2025, 3, 1), [
            (datetime(2025, 3, 10), 'a', 'Alpha', time(13, 15), time(14, 30), 1.25), (datetime(2025, 3, 10), 'b', 'Beta', time(14, 0), time(14, 15), 0.25),
            (datetime(2025, 3, 11), 'c', 'Alpha', time(9, 0), time(10, 0), 1), (datetime(2025, 3, 11), 'd', 'Alpha', time(10, 0), time(11, 0), 1)])})
        t, r, s = self.go(d)
        self.assertIn('time_overlap', r[('MAR', 5)]['issues']); self.assertIn('time_overlap', r[('MAR', 6)]['issues'])
        self.assertEqual(r[('MAR', 5)]['status'], 'needs_decision')
        self.assertNotIn('time_overlap', r[('MAR', 7)]['issues']); self.assertNotIn('time_overlap', r[('MAR', 8)]['issues'])

    # P5
    def test_p5_clock_stored_as_date_is_read_with_info_and_raw_kept(self):
        d = wb_with_header_date({'AVR': (datetime(2025, 4, 1), [
            (datetime(2025, 4, 4), 'a', 'Alpha', datetime(1900, 1, 13, 12, 0), datetime(1900, 1, 15, 12, 0), 2)])})
        t, r, s = self.go(d); x = r[('AVR', 5)]
        self.assertEqual((x['start_time'], x['end_time']), ('13:30', '15:30')); self.assertIn('clock_from_date_format', x['issues'])
        self.assertEqual(x['status'], 'ok'); self.assertTrue(x['raw']['start'].startswith('1900-01-13'))  # provenance kept

    def test_declared_duration_never_silently_changed(self):
        d = wb_with_header_date({'JUN': (datetime(2025, 6, 1), [(datetime(2025, 6, 10), 'a', 'Alpha', time(9, 0), time(12, 0), 4)])})
        t, r, s = self.go(d); x = r[('JUN', 5)]
        self.assertIn('declared_vs_clock_mismatch', x['issues']); self.assertEqual(x['hours'], '4'); self.assertEqual(x['clock_hours'], '3.0000'); self.assertEqual(x['status'], 'needs_decision')

    # mapping, reconciliation, rollback
    def test_mapping_suggestion_is_proposal_only_and_commit_stays_blocked(self):
        d = wb_with_header_date({'MAR': (datetime(2025, 3, 1), [(datetime(2025, 3, 10), 'a', 'Projet Alpha 2025', None, None, 1)])})
        t = self.upload(d); html = self.review(t)
        self.assertIn('Proposition (non appliquée) : Projet Alpha', html)
        rows, s = self.summary(t); self.assertEqual(rows[0]['status'], 'error'); self.assertEqual(s['unmapped_projects'], ['Projet Alpha 2025'])

    def test_review_sections_and_reconciliation(self):
        d = wb_with_header_date({'MAR': (datetime(2025, 3, 1), [
            (datetime(2025, 3, 10), 'ok', 'Alpha', None, None, 1), (None, 'sans date', 'Alpha', None, None, 1), (datetime(2025, 4, 2), 'hors mois', 'Alpha', None, None, 2)])})
        t = self.upload(d); self.save(t, {'Alpha': self.p1}); html = self.review(t)
        for h in ('1. Anomalies bloquantes (1)', '2. Anomalies à arbitrer (1)', '3. Lignes valides (1)', 'Rapprochement des heures'): self.assertIn(h, html)
        rows, s = self.summary(t)
        self.assertEqual(s['hours_importable_by_year'], {'2025': '1'}); self.assertEqual(s['hours_by_status']['needs_decision'], '2'); self.assertEqual(s['hours_by_status']['error'], '1')

    def test_full_batch_rollback_and_raw_provenance(self):
        d = wb_with_header_date({'MAR': (datetime(2025, 3, 1), [
            (datetime(2025, 3, 10), 'ok', 'Alpha', None, None, 1), (datetime(2025, 4, 2), 'hors mois', 'Alpha', None, None, 2)])})
        t = self.upload(d); form = self.save(t, {'Alpha': self.p1}, {'1': 'include'}); self.commit(t, form)
        batch = self.scalar("SELECT id FROM import_batches WHERE status='COMMITTED'")
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 2)
        raw = json.loads(self.scalar('SELECT raw_json FROM import_batch_rows WHERE source_row=6'))
        self.assertTrue(raw['date'].startswith('2025-04-02')); self.assertEqual(self.scalar("SELECT source_ref FROM entries WHERE description='hors mois'"), 'MAR!6')
        self.c.post(f'/imports/rollback/{batch}'); 
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0); self.assertEqual(self.scalar("SELECT status FROM import_batches WHERE id=?", (batch,)), 'ROLLED_BACK')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM import_batch_rows WHERE batch_id=?', (batch,)), 2)  # ledger kept
        self.integrity()


class ImportRC9Review(Base):
    """Preview tooling added after the arbitrage round: proposals (never applied), exclusion of a valid row, CSV export, rollback precision."""
    def go(self, data, mapping=None):
        t = self.upload(data); self.save(t, mapping or {'Alpha': self.p1, 'Beta': self.p2}); rows, s = self.summary(t)
        return t, {(r['source_sheet'], r['source_row']): r for r in rows}, s

    PAIR = (datetime(2025, 2, 13), 'ECIO', 'Alpha', time(15, 30), time(15, 45), 0.25)

    def pair_wb(self):
        e = (datetime(2025, 9, 12), 'réunion', 'Alpha', time(9, 0), time(9, 30), 0.5)
        return wb_with_header_date({'FEV': (datetime(2025, 2, 1), [self.PAIR, self.PAIR]),
                                    'AUG': (datetime(2025, 8, 1), [e]), 'SEPT': (datetime(2025, 9, 1), [e])})

    def test_proposals_exist_but_are_never_applied(self):
        t, r, s = self.go(self.pair_wb())
        first, second = r[('FEV', 5)], r[('FEV', 6)]
        self.assertEqual(first['proposal'], ''); self.assertIn('FEV!5', second['proposal'])        # one occurrence per pair
        self.assertEqual((first['status'], second['status']), ('ok', 'ok'))                         # nothing applied
        self.assertIn('SEPT!5', r[('AUG', 5)]['proposal']); self.assertEqual(r[('AUG', 5)]['status'], 'needs_decision')
        self.assertEqual(r[('SEPT', 5)]['proposal'], '')                                            # the original is never proposed for exclusion

    def test_repeated_entries_kept_by_default_and_exclusion_is_explicit(self):
        d = self.pair_wb(); t = self.upload(d)
        form = self.save(t, {'Alpha': self.p1}, {'1': 'exclude'})   # idx 1 = FEV!6, the second occurrence, valid row excluded by the user
        rows, s = self.summary(t); by = {(x['source_sheet'], x['source_row']): x for x in rows}
        self.assertEqual(by[('FEV', 6)]['status'], 'exclude'); self.assertEqual(by[('FEV', 5)]['status'], 'ok')
        # the AUG copy still waits for its own decision
        form = self.save(t, {'Alpha': self.p1}, {'1': 'exclude', '2': 'exclude'}); r2, s2 = self.summary(t)
        self.commit(t, form)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE source_ref LIKE 'FEV!%'"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE source_ref LIKE 'SEPT!%'"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE source_ref LIKE 'AUG!%'"), 0)
        self.assertEqual(self.scalar("SELECT decision FROM import_batch_rows WHERE source_sheet='FEV' AND source_row=6"), 'exclude')   # provenance of the exclusion kept
        self.assertEqual(self.scalar("SELECT entry_id FROM import_batch_rows WHERE source_sheet='FEV' AND source_row=6"), None)

    def test_both_repeated_entries_imported_when_user_keeps_them(self):
        t = self.upload(self.pair_wb()); form = self.save(t, {'Alpha': self.p1}, {'2': 'exclude'}); self.commit(t, form)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE source_ref LIKE 'FEV!%'"), 2)

    def test_categories_are_stable_while_projects_are_unmapped(self):
        t = self.upload(self.pair_wb())  # no mapping yet: every row has project_unmapped, none is a data defect
        import app.app as app_m
        with app_m.db() as c:
            rows, _ = app_m.historical_import.validate(c, app_m.load_stage(t), {}, {})
        cats = {(r['source_sheet'], r['source_row']): app_m.historical_import.classify(r)[0] for r in rows}
        self.assertEqual(cats[('FEV', 5)], 'valide'); self.assertEqual(cats[('AUG', 5)], 'a_arbitrer')
        html = self.review(t); self.assertIn('3. Lignes valides (3)', html); self.assertIn('2. Anomalies à arbitrer (1)', html)
        self.assertIn('name="d_3"', html)   # decisions can be recorded before the mapping is done (AUG copy = idx 3), the commit stays blocked
        self.assertIn('name="d_1"', html)   # and so can the exclusion of the second occurrence of an exact pair

    def test_csv_export_content_readonly_and_formula_safe(self):
        d = wb_with_header_date({'MAR': (datetime(2025, 3, 1), [
            (datetime(2025, 3, 10), '+SUM(1)', 'Alpha', None, None, 1), (datetime(2025, 4, 2), '@cmd', 'Alpha', None, None, 2), (None, 'sans date', 'Alpha', None, None, 1)])})
        self.c.post('/entry', data={'work_date': '2025-01-02', 'project_id': self.p1, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'saisie existante'})
        t = self.upload(d); self.save(t, {'Alpha': self.p1}, {'1': 'include'})
        before = (self.scalar('SELECT COUNT(*) FROM entries'), self.scalar('SELECT COUNT(*) FROM import_batches'), self.scalar('SELECT COUNT(*) FROM audit'))
        r = self.c.get(f'/import/review/{t}/export.csv'); self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r.headers['Content-Type']); self.assertIn('attachment', r.headers['Content-Disposition'])
        txt = r.get_data(as_text=True); self.assertTrue(txt.startswith('\ufeff'))
        import csv, io as _io
        rows = list(csv.DictReader(_io.StringIO(txt.lstrip('\ufeff')), delimiter=';'))
        self.assertEqual(len(rows), 3); self.assertEqual([x['source_ref'] for x in rows], ['MAR!5', 'MAR!6', 'MAR!7'])
        self.assertEqual(rows[0]['motif'], "'+SUM(1)"); self.assertEqual(rows[1]['motif'], "'@cmd")   # no cell can start with = + - @
        self.assertEqual(rows[1]['statut'], 'importée (décision)'); self.assertEqual(rows[1]['decision_enregistree'], 'include'); self.assertEqual(rows[1]['mandat_cible'], 'Projet Alpha')
        self.assertEqual(rows[2]['categorie'], 'bloquante'); self.assertEqual(rows[2]['sous_categorie'], 'date_missing')
        self.assertEqual(rows[1]['brut_date'][:10], '2025-04-02')
        after = (self.scalar('SELECT COUNT(*) FROM entries'), self.scalar('SELECT COUNT(*) FROM import_batches'), self.scalar('SELECT COUNT(*) FROM audit'))
        self.assertEqual(before[:2], after[:2]); self.assertEqual(before[0], 1)  # existing data untouched, no batch; only an audit trace is added
        self.c.post('/logout'); self.assertEqual(self.c.get(f'/import/review/{t}/export.csv').status_code, 302)  # login required

    def test_rollback_touches_only_rows_of_its_own_batch(self):
        # manual entry + a first committed batch + a second committed batch; rolling back the second changes nothing else
        self.c.post('/entry', data={'work_date': '2025-01-02', 'project_id': self.p2, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'saisie manuelle'})
        manual = self.scalar("SELECT COUNT(*) FROM entries WHERE source IS NOT 'historical_excel'")
        d1 = wb_with_header_date({'JAN': (datetime(2025, 1, 1), [(datetime(2025, 1, 8), 'lot1', 'Alpha', None, None, 1)])})
        t1 = self.upload(d1); self.commit(t1, self.save(t1, {'Alpha': self.p1}))
        d2 = wb_with_header_date({'FEV': (datetime(2025, 2, 1), [(datetime(2025, 2, 6), 'lot2a', 'Alpha', None, None, 1), (datetime(2025, 2, 7), 'lot2b', 'Beta', None, None, 2)])})
        t2 = self.upload(d2); self.commit(t2, self.save(t2, {'Alpha': self.p1, 'Beta': self.p2}))
        snap = lambda w: [tuple(x) for x in self.sql(f'SELECT * FROM entries WHERE {w} ORDER BY id')]
        keep_before = snap("import_batch_id IS NULL OR description='lot1'")
        b2 = self.scalar("SELECT id FROM import_batches WHERE source_filename=? AND inserted_rows=2 AND status='COMMITTED'", ('Time sheet test.xlsx',))
        self.c.post(f'/imports/rollback/{b2}')
        self.assertEqual(self.scalar("SELECT status FROM import_batches WHERE id=?", (b2,)), 'ROLLED_BACK')
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE description IN ('lot2a','lot2b')"), 0)
        self.assertEqual(snap("import_batch_id IS NULL OR description='lot1'"), keep_before)       # byte-identical rows
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE source IS NOT 'historical_excel'"), manual)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM import_batches WHERE status='COMMITTED'"), 1)
        self.integrity()

    def test_identical_subtotals_are_not_a_repeated_entry_and_float_noise_never_displayed(self):
        d = wb_with_header_date({'JAN 26': (datetime(2026, 1, 1), [
            (datetime(2026, 1, 5), 'x', 'Alpha', None, None, 0.8000000000000007), (None, None, None, None, None, 82.5), ('Total', None, None, None, None, 82.5)])})
        t, r, s = self.go(d)
        for k in (('JAN 26', 6), ('JAN 26', 7)):
            self.assertNotIn('repeated_in_file', r[k]['issues']); self.assertEqual(r[k]['proposal'], '')
        self.assertEqual(r[('JAN 26', 5)]['hours'], '0.8000000000000007')      # the row keeps the source value
        self.assertEqual(s['hours_importable'], '0.8'); self.assertEqual(s['hours_importable_by_year'], {'2026': '0.8'})  # sums are displayed rounded


if __name__ == '__main__': unittest.main()
