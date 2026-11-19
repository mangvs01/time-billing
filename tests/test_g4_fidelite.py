"""G4 — fidelity review of 2026-10-06 (corrections, entries, Excel imports, historical registry). Synthetic data only, on a COPY of the
staging database (see test_import.py for the run command).

B1/B2  a line already imported is recognised by its source line (sheet, row, cell values), not only by the sha256 of the file: a re-saved or
       completed copy of the workbook cannot import it again, even mapped to another mandate, and a line corrected since its import does not
       come back with its old value. B3: a line excluded on purpose by an earlier import is said again.
       Review 2026-10-06 (R-IMP-1..4) then OVERWRITE_MATCHING (Decision Center, 2026-10-07): a line matching an existing entry overwrites it only by an
       explicit per-line choice (traced correction; never a second entry); a row inserted above moves nothing
       back in; 0.8000000000000007 and 0.800000000000001 are the same cell; an excluded line is still recognised after a shift.
C1     a period holding 7 h 20 (or 20 min) passes check 12: the period hours are compared unrounded.
N1     the number printed on a real historical invoice (CIRSE 2026 = « 2026-09 ») is never given to a Time Billing invoice: from the registry, or
       before it is loaded from EXTERNAL_INVOICE_NUMBERS (deployment files); the loader stops if a Time Billing invoice already has the number.
D-02   rejecting a historical invoice keeps its provenance note (D4): the reason is appended, never written over it.
C2/C3/C5  entry form: « 7:05 » is read as 07:05, « 1_5 » / « 1e1 » / non-ASCII digits are refused, invisible characters are refused in a reason.
Review of the integrated patch (2026-10-06 20:30): R-CHK-1 a gap of exactly 0.5 j made of clock entries is not a gap (float noise of the sum);
R-CHK-2 / R-PO-B2 a draft left at a 0 rate says how to take the mandate's rate filled in since, and saving the draft takes it; R-E3-1 / R-E3-2 the « AUTRES » label: said « not printed »
when its amount is 0, refused (and failing check 11) when it would run over its amount in the totals; R-E5-1 a 3-line description and its period
stay beside the SOUS-TOTAL: the totals never move (D6 (a)).
"""
import hashlib, json, re, sqlite3
from datetime import datetime, time

import app.app as m
from tests import test_g4, test_rc19          # base classes only: importing a class that holds tests would run its tests again here
from tests.test_g4 import text
from tests.test_import import workbook


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N


def resaved(sheets, title):
    """Same cell values, other bytes: what Excel produces when the workbook is saved again (or completed with new months)."""
    from openpyxl import load_workbook
    import io
    wb = load_workbook(io.BytesIO(workbook(sheets)))
    wb.properties.title = title
    b = io.BytesIO(); wb.save(b); return b.getvalue()


MAR = [(datetime(2025, 3, 3), 'réunion client', 'Alpha', time(8, 0), time(10, 0), 2),
       (datetime(2025, 3, 4), 'rédaction', 'Alpha', None, None, 1.5)]


class ImportIdentity(test_rc19.RC19):
    def statuses(self, token):
        return {r['description']: (r['status'], r['issues']) for r in self.summary(token)[0]}

    def test_B1_a_resaved_copy_cannot_import_the_same_lines_again_even_on_another_mandate(self):
        first = workbook({'MAR': MAR}); self.import_batch(None, data=first)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 2)
        copy = resaved({'MAR': MAR, 'AVR': [(datetime(2025, 4, 2), 'nouveau mois', 'Alpha', time(9, 0), time(10, 0), 1)]}, 'copie complétée')
        self.assertNotEqual(hashlib.sha256(copy).hexdigest(), hashlib.sha256(first).hexdigest())
        for target in (self.p1, self.p2):                       # mapped to the same project, then to another one: never a duplicate
            t = self.upload(copy); self.save(t, {'Alpha': target})
            st = self.statuses(t)
            self.assertEqual(st['réunion client'][0], 'error'); self.assertIn('already_imported', st['réunion client'][1])
            self.assertEqual(st['rédaction'][0], 'error'); self.assertIn('already_imported', st['rédaction'][1])
            self.assertEqual(st['nouveau mois'][0], 'ok')
        form = self.save(t, {'Alpha': self.p1}, {'0': 'include', '1': 'include'})          # an explicit « import » cannot force them either
        r, fl = self.commit(t, form); self.assertIn('Import validé : 1', ' '.join(fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 3)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE description='réunion client'"), 1)

    def test_B2_a_line_corrected_since_its_import_does_not_come_back_with_its_old_value_unless_the_user_overwrites(self):
        self.import_batch(None, data=workbook({'MAR': MAR}))
        eid = self.eid('réunion client')
        r, fl = self.edit(eid, end_time='10:30'); self.assertIn('modifiée', fl)
        t = self.upload(resaved({'MAR': MAR}, 'réenregistré')); form = self.save(t, {'Alpha': self.p1})
        st = self.statuses(t)
        self.assertEqual(st['réunion client'][0], 'keep'); self.assertIn('entry_corrected_since_import', st['réunion client'][1])   # OVERWRITE_MATCHING: kept by default
        self.assertEqual(st['rédaction'][0], 'error'); self.assertIn('already_imported', st['rédaction'][1])                         # unchanged on both sides
        self.assertIn(f'écraser la saisie n° {eid}', text(self.c.get(f'/import/review/{t}')))
        r, fl = self.commit(t, form); self.assertIn('Aucune ligne importable', ' '.join(fl))
        self.assertEqual([(x['start_time'], x['end_time'], x['hours']) for x in self.sql("SELECT * FROM entries WHERE description='réunion client'")],
                         [('08:00', '10:30', 2.5)])
        form = self.save(t, {'Alpha': self.p1}, {'0': 'overwrite'})                    # the user's explicit choice: the workbook value comes back, traced
        r, fl = self.commit(t, form); self.assertIn('1 saisie(s) existante(s) écrasée(s)', ' '.join(fl))
        self.assertEqual([(x['id'], x['start_time'], x['end_time'], x['hours']) for x in self.sql("SELECT * FROM entries WHERE description='réunion client'")],
                         [(eid, '08:00', '10:00', 2.0)])
        self.assertIn('réimport volontaire', self.changes(eid)[-1]['reason'])

    def test_B1_a_line_changed_in_the_workbook_since_its_import_overwrites_its_entry_only_by_explicit_choice(self):
        self.import_batch(None, data=workbook({'MAR': MAR}))
        eid, n = self.eid('rédaction'), self.scalar('SELECT COUNT(*) FROM entries')
        changed = [MAR[0], (datetime(2025, 3, 4), 'rédaction', 'Alpha', None, None, 2.5)]      # same sheet and row, other duration
        t = self.upload(resaved({'MAR': changed}, 'modifié')); form = self.save(t, {'Alpha': self.p1}, {'1': 'include'})
        st = self.statuses(t)
        self.assertEqual(st['rédaction'][0], 'keep'); self.assertIn('source_row_changed', st['rédaction'][1])     # « importer » can never add a second entry
        self.assertIn('Ligne déjà importée, modifiée depuis dans le classeur', text(self.c.get(f'/import/review/{t}')))
        form = self.save(t, {'Alpha': self.p1}, {'1': 'overwrite'})
        r, fl = self.commit(t, form); self.assertIn('1 saisie(s) existante(s) écrasée(s)', ' '.join(fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), n)                                           # same entry, new value
        ref = self.row(eid)['source_ref']; self.assertEqual(self.row(eid)['hours'], 2.5)
        ch = self.changes(eid)[-1]
        self.assertEqual((ch['action'], json.loads(ch['before_json'])['hours'], json.loads(ch['after_json'])['hours']), ('update', 1.5, 2.5))
        self.assertRegex(ch['reason'], r'^réimport volontaire : lot [0-9a-f]{32}, ligne ' + re.escape(ref) + ' du classeur$')
        batch = self.scalar("SELECT id FROM import_batches WHERE status='COMMITTED' ORDER BY created_at DESC, rowid DESC LIMIT 1")
        self.flashes(); self.c.post(f'/imports/rollback/{batch}')
        self.assertIn('ne peut pas être annulé en bloc', ' '.join(self.flashes())); self.assertEqual(self.row(eid)['hours'], 2.5)
        t = self.upload(resaved({'MAR': changed}, 'modifié 2')); self.save(t, {'Alpha': self.p1})                   # the same line again: nothing left to do
        st = self.statuses(t); self.assertEqual(st['rédaction'][0], 'error'); self.assertIn('already_imported', st['rédaction'][1])
        r, fl = self.delete(eid, reason='remplacée par la ligne corrigée du classeur')       # an entry deleted since: a new import is a decision
        t = self.upload(resaved({'MAR': [MAR[0], (datetime(2025, 3, 4), 'rédaction', 'Alpha', None, None, 3)]}, 'modifié 3')); self.save(t, {'Alpha': self.p1})
        st = self.statuses(t)
        self.assertEqual(st['rédaction'][0], 'needs_decision'); self.assertIn('source_row_changed_entry_deleted', st['rédaction'][1])

    def test_B1b_an_entry_edited_after_the_preview_stops_the_overwrite(self):
        self.import_batch(None, data=workbook({'MAR': MAR}))
        eid = self.eid('rédaction')
        changed = [MAR[0], (datetime(2025, 3, 4), 'rédaction', 'Alpha', None, None, 2.5)]
        t = self.upload(resaved({'MAR': changed}, 'modifié')); form = self.save(t, {'Alpha': self.p1}, {'1': 'overwrite'})
        fp = re.search(r'name="fingerprint" value="([0-9a-f]+)"', text(self.c.get(f'/import/review/{t}'))).group(1)
        self.edit(eid, manual_hours='1.75')                                                  # another tab corrects the entry meanwhile
        r, fl = self.commit(t, form, fingerprint=fp); self.assertIn('La situation a changé', ' '.join(fl))
        self.assertEqual(self.row(eid)['hours'], 1.75)

    def test_B1c_a_row_matching_two_living_entries_is_never_overwritten(self):
        self.import_batch(None, data=workbook({'MAR': MAR}))
        eid = self.eid('rédaction'); bid = self.scalar("SELECT batch_id FROM import_batch_rows WHERE entry_id=?", (eid,))
        c = m.db()
        try:      # a second living entry recorded for the same line (state the application never writes; defence in depth)
            new = c.execute("INSERT INTO entries(work_date,project_id,hours,description,source,source_ref) SELECT work_date,project_id,hours,description,source,source_ref FROM entries WHERE id=?", (eid,)).lastrowid
            c.execute("INSERT INTO import_batches(id,source_filename,status,source_rows,inserted_rows,file_sha256,backup_filename,backup_sha256,committed_at) "
                      "SELECT 'lot-double',source_filename,status,source_rows,1,file_sha256,backup_filename,backup_sha256,committed_at FROM import_batches WHERE id=?", (bid,))
            c.execute("INSERT INTO import_batch_rows(batch_id,source_sheet,source_row,raw_json,issues,decision,entry_id) SELECT 'lot-double',source_sheet,source_row,raw_json,issues,decision,? FROM import_batch_rows WHERE entry_id=?", (new, eid))
            c.commit()
        finally: c.close()
        t = self.upload(resaved({'MAR': [MAR[0], (datetime(2025, 3, 4), 'rédaction', 'Alpha', None, None, 2.5)]}, 'modifié')); self.save(t, {'Alpha': self.p1}, {'1': 'overwrite'})
        st = self.statuses(t); self.assertEqual(st['rédaction'][0], 'error'); self.assertIn('source_row_ambiguous', st['rédaction'][1])

    def test_B1d_review_a_row_inserted_above_with_the_same_slot_never_overwrites_its_neighbour(self):
        rows = [(datetime(2025, 3, 3), 'analyse', 'Alpha', time(8, 0), time(12, 0), 4), (datetime(2025, 3, 4), 'dev', 'Alpha', time(8, 0), time(12, 0), 4)]
        self.import_batch(None, data=workbook({'MAR': rows}))
        new = (datetime(2025, 3, 2), 'atelier', 'Alpha', time(8, 0), time(12, 0), 4)
        t = self.upload(resaved({'MAR': [new] + rows}, 'ligne insérée')); self.save(t, {'Alpha': self.p1})
        st = self.statuses(t)
        self.assertEqual(st['atelier'][0], 'ok', st['atelier'])                                   # a new line, imported: nothing proposed for « écraser »
        self.assertEqual((st['analyse'][0], st['dev'][0]), ('error', 'error'))

    def test_B1e_review_a_row_removed_above_never_shifts_the_entries(self):
        rows = [(datetime(2025, 3, d), m, 'Alpha', None, None, 8) for d, m in ((3, 'A'), (4, 'B'), (5, 'C'))]
        self.import_batch(None, data=workbook({'MAR': rows}))
        t = self.upload(resaved({'MAR': rows[1:]}, 'ligne supprimée')); self.save(t, {'Alpha': self.p1})
        st = self.statuses(t)
        self.assertFalse([k for k, v in st.items() if v[0] in ('keep', 'overwrite')], st)          # B and C are recognised as moved, not as edits of A and B
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 3)

    def test_B1f_review_going_back_to_the_previous_value_and_an_empty_overwrite(self):
        self.import_batch(None, data=workbook({'MAR': MAR}))
        eid = self.eid('rédaction')
        v2 = [MAR[0], (datetime(2025, 3, 4), 'rédaction', 'Alpha', None, None, 2.5)]
        t = self.upload(resaved({'MAR': v2}, 'v2')); form = self.save(t, {'Alpha': self.p1}, {'1': 'overwrite'}); self.commit(t, form)
        self.assertEqual(self.row(eid)['hours'], 2.5)
        t = self.upload(resaved({'MAR': MAR}, 'retour v1')); self.save(t, {'Alpha': self.p1})       # the previous value matches the entry's current line
        st = self.statuses(t); self.assertEqual(st['rédaction'][0], 'keep'); self.assertIn('source_row_changed', st['rédaction'][1])
        c = m.db()
        try: rows = m.historical_import.validate(c, dict(m.load_stage(t)), {'Alpha': str(self.p2)}, {})[0]
        finally: c.close()
        self.assertTrue(any(r.get('match_entry_id') == eid for r in rows))                       # mapped elsewhere: still offered (the page says it moves)
        v2b = [MAR[0], (datetime(2025, 3, 4, 0, 0), 'rédaction', 'Alpha', None, None, 2.50)]       # same values written again: nothing to overwrite
        t = self.upload(resaved({'MAR': v2b}, 'v2 bis')); self.save(t, {'Alpha': self.p1})
        self.assertEqual(self.statuses(t)['rédaction'][0], 'error')

    def test_B1g_review_an_entry_that_lost_the_provenance_of_the_line_is_never_overwritten(self):
        self.import_batch(None, data=workbook({'MAR': MAR}))
        eid = self.eid('rédaction')
        c = m.db()
        try: c.execute("UPDATE entries SET source_ref='autre!9' WHERE id=?", (eid,)); c.commit()
        finally: c.close()
        t = self.upload(resaved({'MAR': [MAR[0], (datetime(2025, 3, 4), 'rédaction', 'Alpha', None, None, 2.5)]}, 'modifié')); self.save(t, {'Alpha': self.p1})
        self.assertNotIn(self.statuses(t)['rédaction'][0], ('keep', 'overwrite'))

    def test_R_IMP_1_a_row_inserted_above_neither_reimports_nor_flags_the_new_line(self):
        self.import_batch(None, data=workbook({'MAR': MAR}))
        new = (datetime(2025, 3, 2), 'oubli du 2 mars', 'Alpha', None, None, 1)
        for target in (self.p1, self.p2):
            t = self.upload(resaved({'MAR': [new] + MAR}, 'ligne insérée')); self.save(t, {'Alpha': target})
            st = self.statuses(t)
            self.assertEqual(st['réunion client'][0], 'error'); self.assertIn('already_imported', st['réunion client'][1])        # clocked: by content
            self.assertEqual(st['rédaction'][0], 'needs_decision'); self.assertIn('possible_already_imported', st['rédaction'][1])  # unclocked, moved down
            self.assertEqual(st['oubli du 2 mars'][0], 'ok', st['oubli du 2 mars'])                                                   # new at a reused row

    def test_R_IMP_2_a_value_written_with_fewer_digits_is_the_same_line(self):
        from app import historical_import as hi
        a = {'date': '2025-03-04T00:00:00', 'project': 'Alpha', 'start': '', 'end': '', 'hours': '0.8000000000000007', 'description': 'x'}
        self.assertEqual(hi._line_key(a), hi._line_key(dict(a, hours='0.800000000000001', date='2025-03-04')))
        self.assertEqual(hi._line_key(dict(a, hours='2')), hi._line_key(dict(a, hours='2.0')))
        self.assertNotEqual(hi._line_key(dict(a, hours='0.81')), hi._line_key(a))
        self.assertEqual(hi._line_key(dict(a, hours='1e400'))[4], '1e400')                       # an absurd number stays as written, no crash

    def test_R_IMP_4_an_excluded_clocked_line_is_said_again_after_a_shift(self):
        rows = MAR + [(datetime(2025, 4, 20), 'hors mois', 'Alpha', time(14, 0), time(15, 0), 1)]
        t = self.upload(workbook({'MAR': rows})); self.save(t, {'Alpha': self.p1})
        idx = next(r['idx'] for r in self.summary(t)[0] if r['description'] == 'hors mois')
        form = self.save(t, {'Alpha': self.p1}, {str(idx): 'exclude'}); self.commit(t, form)
        t2 = self.upload(resaved({'MAR': [(datetime(2025, 3, 2), 'oubli du 2 mars', 'Alpha', None, None, 1)] + rows}, 'copie décalée')); self.save(t2, {'Alpha': self.p1})
        st = self.statuses(t2)
        self.assertIn('previously_excluded', st['hors mois'][1])

    def test_B3_a_line_excluded_on_purpose_is_said_again(self):
        rows = MAR + [(datetime(2025, 4, 20), 'hors mois', 'Alpha', time(14, 0), time(15, 0), 1)]   # April date on the March sheet: warning
        t = self.upload(workbook({'MAR': rows})); form = self.save(t, {'Alpha': self.p1})
        idx = next(r['idx'] for r in self.summary(t)[0] if r['description'] == 'hors mois')
        form = self.save(t, {'Alpha': self.p1}, {str(idx): 'exclude'})
        r, fl = self.commit(t, form); self.assertIn('Import validé : 2', ' '.join(fl))
        t2 = self.upload(resaved({'MAR': rows}, 'copie')); self.save(t2, {'Alpha': self.p1})
        st = self.statuses(t2)
        self.assertEqual(st['hors mois'][0], 'needs_decision'); self.assertIn('previously_excluded', st['hors mois'][1])

    def test_a_rolled_back_batch_no_longer_counts(self):
        b = self.import_batch(None, data=workbook({'MAR': MAR}))
        self.flashes(); self.c.post(f'/imports/rollback/{b}'); self.assertIn('Lot annulé', ' '.join(self.flashes()))
        t = self.upload(resaved({'MAR': MAR}, 'après annulation')); self.save(t, {'Alpha': self.p1})
        self.assertEqual({v[0] for v in self.statuses(t).values()}, {'ok'})


class PeriodHours(test_g4.G4):
    checks = test_g4.Checks.checks
    neutral_identity = test_g4.Checks.neutral_identity

    def test_C1_seven_hours_twenty_and_twenty_minutes_pass_check_12(self):
        self.neutral_identity()
        for s, e in (('08:00', '15:20'), ('16:00', '16:20')):
            self.c.post('/entry', data={'work_date': '2026-09-11', 'project_id': str(self.pid), 'entry_mode': 'clock', 'start_time': s, 'end_time': e, 'description': 'rédaction'})
        iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2.958333)[0]    # 16 + 7.3333 + 0.3333 = 23.6667 h = 2.958333 j (rc41: no tolerance either way, the quantity is the work to the minute)
        ck = self.checks(iid)
        self.assertEqual({n: x['status'] for n, x in ck.items() if x['status'] != 'ok'}, {}, ck)
        self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())

    def test_R_CHK_1_an_exact_half_day_gap_from_clock_entries_is_not_a_gap(self):
        self.neutral_identity()
        cases = (('Mandat 3,5 j', (('08:00', '10:20'), ('08:00', '08:40'), ('08:00', '16:20'), ('08:00', '16:20'), ('08:00', '16:20')), 3.5),     # 28 h, summed 28.000000000000004 (rc41: quantity = the work, no 0.5 j tolerance)
                 ('Mandat 2 j', (('08:00', '08:40'), ('08:00', '13:20'), ('08:00', '13:20'), ('08:00', '08:20'), ('08:00', '12:20')), 2))      # 16 h, summed 15.999999999999998
        for k, (name, spans, qty) in enumerate(cases):
            pid = self.mandate(name=name, rate='650', vat='0', ordered='20', legal_id=f'CHE-000.000.07{k}')
            c = sqlite3.connect(self.db)
            c.execute("UPDATE projects SET client='Client SA', client_legal_name='Client SA', billing_address='Client SA\nRue 1\n1000 Ville', po='PO-0001', project_number='NP-0001', billing_contact='Contact' WHERE id=?", (pid,))
            c.commit(); c.close()
            for d, (s, e) in enumerate(spans, 1):
                self.c.post('/entry', data={'work_date': f'2026-09-{d:02d}', 'project_id': str(pid), 'entry_mode': 'clock', 'start_time': s, 'end_time': e, 'description': 'rédaction'})
            self.assertNotEqual(sum(r[0] for r in self.sql('SELECT hours FROM entries WHERE project_id=? ORDER BY work_date', (pid,))) % 4, 0)   # the noise is there
            iid = self.draft(pid, '2026-09-01', '2026-09-30', qty)[0]
            ck = self.checks(iid)
            self.assertEqual(ck[12]['status'], 'ok', ck[12]['detail'])
            self.flashes(); self.issue(iid)
            self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        pid = self.mandate(name='Mandat écart', rate='650', vat='0', ordered='20', legal_id='CHE-000.000.079')
        self.entry(pid, '2026-09-02', 16, 'rédaction'); self.entry(pid, '2026-09-03', 12.5, 'rédaction')   # 3.5625 j billed 3: a real gap above 0.5 j is still one
        ck = self.checks(self.draft(pid, '2026-09-01', '2026-09-30', 3)[0])
        self.assertEqual((ck[12]['status'], ck[12]['derogable']), ('fail', True)); self.assertIn('quantité facturée 3.0 j pour 3.5625 j', ck[12]['detail'])


class HistoricalNumbers(test_g4.G4):
    def test_N1_the_number_of_a_real_historical_invoice_is_reserved(self):
        other = self.mandate(name='Mandat CIRSE fictif', rate='650', vat='0', ordered='8', legal_id='CHE-000.000.009')
        self.hist(pid=other, date='2026-10-01', days=8.0, amount=5200.0, cell='Q12', invoice_ref=f'{YEAR}-1')   # proposed is enough: the number exists
        self.assertIn(f'n° {YEAR}-1 (facture réelle)', text(self.c.get('/historique')))
        iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0]
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (iid,)), f'{YEAR}-2')       # the draft RESERVES the first number the real invoice does not hold
        self.assertIn(f'{YEAR}-2', text(self.c.get(f'/issue/{iid}')))
        self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (iid,)), f'{YEAR}-2', self.flashes())

    def test_N1_a_known_external_number_is_reserved_before_the_registry_is_loaded(self):
        import os, unittest.mock as mock
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM historical_invoices'), 0)
        with mock.patch.dict(os.environ, {'EXTERNAL_INVOICE_NUMBERS': f'{YEAR}-1'}):          # set by procedure/docker-compose.*.yml (F-N1-1)
            iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0]
            self.assertIn(f'{YEAR}-2', text(self.c.get(f'/issue/{iid}')))
            self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (iid,)), f'{YEAR}-2', self.flashes())

    def test_N1_the_other_way_round_the_loader_stops_on_a_number_already_issued(self):
        from app import historical_billing
        from outils import charger_factures_historiques as tool
        iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0]
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (iid,)), f'{YEAR}-1', self.flashes())
        rec = dict(mandate='Mandat G4', source_file=tool.SOURCE_FILE, source_sheet='SUIVI 2026', source_cell='Q12', source_column='Facture 01.10', invoice_date='2026-10-01',
                   invoice_ref=f'{YEAR}-1', qty_days=8.0, amount_ht=5200.0, unit_rate=650.0, basis='amount', qty_derived=1, note='', raw=5200)
        c = m.db()
        try:
            with self.assertRaises(SystemExit) as e: tool.insert(c, [rec], {'Mandat G4': self.pid}, tool.WORKBOOK_SHA256, historical_billing)
        finally: c.rollback(); c.close()
        self.assertIn('déjà attribué à une facture Time Billing', str(e.exception))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM historical_invoices'), 0)

    def test_D02_a_rejection_keeps_the_provenance_note(self):
        hid = self.hist(note='Provenance (D4) : 1,75 h de doublons A1 ; effet possible 0,169 j')
        self.assertIn('Provenance (D4)', json.loads(self.scalar("SELECT detail FROM audit WHERE event='historical_invoice_proposed' ORDER BY id DESC LIMIT 1"))['note'])
        self.set_status(hid, 'validated')
        r, fl = self.set_status(hid, 'rejected', 'pièce comptable introuvable'); self.assertIn('rejetée', fl)
        note = self.scalar('SELECT note FROM historical_invoices WHERE id=?', (hid,))
        self.assertTrue(note.startswith('Provenance (D4) : 1,75 h de doublons A1'), note); self.assertIn(': pièce comptable introuvable', note)
        self.assertRegex(note, r'Rejet du \d\d\.\d\d\.\d{4} : ')                                 # the Zurich day, as every date of the page
        self.set_status(hid, 'validated')
        self.assertEqual(self.scalar('SELECT note FROM historical_invoices WHERE id=?', (hid,)), note)    # re-validation keeps the whole story


class EntryForm(test_rc19.RC19):
    def test_C5_a_one_digit_hour_is_read_as_HH_MM(self):
        self.clock(self.pid, '2026-09-01', '7:05', '9:35', 'heure courte'); e = self.row(self.eid('heure courte'))
        self.assertEqual((e['start_time'], e['end_time'], e['hours']), ('07:05', '09:35', 2.5))

    def test_C2_only_plain_decimal_durations(self):
        for bad in ('1_5', '1e1', '٣', 'inf', '0x2'):
            self.c.post('/entry', data={'work_date': '2026-09-01', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': bad, 'description': f'durée {bad}'})
            self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries WHERE description=?', (f'durée {bad}',)), 0, bad)
        self.flashes()
        self.c.post('/entry', data={'work_date': '2026-09-01', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': '-1', 'description': 'durée négative'})
        self.assertIn('positive', ' '.join(self.flashes()))           # a negative duration keeps its precise message (recette A5)
        for good, h in (('7,3333', 7.3333), ('.5', 0.5), ('4.', 4.0)):
            self.c.post('/entry', data={'work_date': '2026-09-01', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': good, 'description': f'durée {good}'})
            self.assertEqual(self.row(self.eid(f'durée {good}'))['hours'], h)

    def test_C3_invisible_characters_refused_in_a_reason(self):
        for bad, cp in (('a\u2028b', 'U+2028'), ('a\u2029b', 'U+2029'), ('x\u202ey', 'U+202E'), ('a\u2063b', 'U+2063'), ('\u3164', 'U+3164'), ('motif \u2800', 'U+2800')):
            with self.assertRaises(ValueError) as e: m.change_reason(bad)
            self.assertIn(cp, str(e.exception))                                               # the refused character is named
        # review 2026-10-06 (F-C3-2): what a word processor or a web page pastes invisibly is removed, an emoji keeps its joiner
        self.assertEqual(m.change_reason('co\u00adordination'), 'coordination'); self.assertEqual(m.change_reason('a\u200bb'), 'ab')
        self.assertEqual(m.change_reason('\ufeffmotif'), 'motif'); self.assertEqual(m.change_reason('motif \U0001F468\u200d\U0001F4BB'), 'motif \U0001F468\u200d\U0001F4BB')
        self.assertEqual(m.change_reason('  motif accentué — ok  '), 'motif accentué — ok')



class LayoutD6(test_g4.G4):
    checks = test_g4.Checks.checks

    def test_E3_an_empty_others_line_prints_AUTRES_alone(self):
        from tests.test_functional import pdf_text
        iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, other_label='Frais divers', other_amount='0')[0]
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn('AUTRES', t); self.assertNotIn('Frais divers', t)
        self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'unit': 'day', 'rounding': 'exact',
                                                   'rounding_step': '0.25', 'vat': '0', 'other_amount': '12.5', 'other_label': 'Frais divers'})
        self.assertIn('AUTRES — Frais divers (hors TVA)', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))

    def test_E6_a_rate_of_zero_fails_check_3(self):
        pid = self.mandate(name='Mandat sans tarif', rate='0', vat='0', ordered='15', legal_id='CHE-000.000.008')
        self.entry(pid, '2026-09-10', 8, 'septembre')
        iid = self.draft(pid, '2026-09-01', '2026-09-30', 1)[0]
        ck = self.checks(iid)
        self.assertEqual(ck[3]['status'], 'fail'); self.assertFalse(ck[3]['derogable']); self.assertIn('tarif nul : renseigner le tarif journalier du mandat', ck[3]['detail'])
        c = sqlite3.connect(self.db); c.execute('UPDATE projects SET rate=650 WHERE id=?', (pid,)); c.commit(); c.close()     # R-CHK-2: filled in since (D5 c)
        ck = self.checks(iid)
        self.assertEqual(ck[3]['status'], 'fail'); self.assertNotIn('renseigner le tarif', ck[3]['detail'])
        self.assertIn('tarif nul sur ce brouillon (tarif du mandat renseigné depuis : 650.0) : enregistrer de nouveau le brouillon pour le reprendre', ck[3]['detail'])
        self.flashes(); self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1', 'unit': 'day', 'rounding': 'exact',
                                                                'rounding_step': '0.25', 'vat': '0'})
        self.assertIn('Tarif du brouillon repris du mandat : 650,00', ' '.join(self.flashes()))                      # R-PO-B2: saving the draft takes it (a rate
                                                                                                                       # other than 0 is kept: rc11 QA-02)
        self.assertEqual(self.scalar('SELECT unit_rate FROM invoices WHERE id=?', (iid,)), 650.0); self.assertEqual(self.checks(iid)[3]['status'], 'ok')

    def test_E3_a_long_others_label_is_refused_where_it_would_run_over_its_amount(self):
        from tests.test_functional import pdf_text
        long = 'Frais de déplacement et d hébergement Bruxelles Genève aller retour du congrès annuel avec taxis'   # 4 lines in a cell, too wide for the totals row
        form = {'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25', 'vat': '0'}
        iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0]
        r = self.c.post(f'/invoice/{iid}/edit', data=dict(form, other_amount='120', other_label=long))      # refused: the edit page is shown again with the reason
        self.assertIn('Brouillon non modifié : libellé « autres » trop long pour la ligne des totaux', text(r)); self.assertEqual(self.scalar('SELECT other_label FROM invoices WHERE id=?', (iid,)) or '', '')
        self.c.post(f'/invoice/{iid}/edit', data=dict(form, other_amount='0', other_label=long))          # not printed with a 0 amount: accepted
        self.assertEqual(self.scalar('SELECT other_label FROM invoices WHERE id=?', (iid,)), long)
        self.c.post(f'/invoice/{iid}/edit', data=dict(form, other_amount='120', other_label='Frais de déplacement Bruxelles'))
        self.assertIn('AUTRES — Frais de déplacement Bruxelles (hors TVA)', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))
        c = sqlite3.connect(self.db); c.execute('UPDATE invoices SET other_label=? WHERE id=?', (long, iid)); c.commit(); c.close()   # saved before the rule
        ck = self.checks(iid); self.assertEqual(ck[11]['status'], 'fail'); self.assertIn('libellé « autres » trop long pour la ligne des totaux', ck[11]['detail'])

    def test_E5_a_three_line_description_moves_nothing_of_the_reference_model(self):
        from app import pdf_layout
        from tests.test_g4 import PeriodInDescription
        three = ' '.join(['mot'] * 20); self.assertEqual(pdf_layout.description_line_count(three), 3)
        seen = {}
        for desc in ('Production septembre', 'Production PM/DM - Mandat G4 - NP-0001 deuxième ligne de la description', three):
            iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, description=desc)[0]
            try: w = PeriodInDescription.words(self, self.c.get(f'/invoice/{iid}.pdf').data)
            except Exception: self.skipTest('pdftotext absent')
            pos = {k: next(x for x in w if x[0] == k) for k in ('SOUS-TOTAL', 'TOTAL', 'Période')}
            seen[pdf_layout.description_line_count(desc)] = pos
            self.assertAlmostEqual(pos['Période'][1], 50.3, 1)                               # the period stays in the description column
            self.c.post(f'/invoice/{iid}/delete')
        self.assertEqual(sorted(seen), [1, 2, 3])
        for n in (1, 3):
            for k in ('SOUS-TOTAL', 'TOTAL'): self.assertAlmostEqual(seen[n][k][2], seen[2][k][2], 1, (n, k))   # 342.4 / 430.7 as on the reference
        self.assertAlmostEqual(seen[2]['SOUS-TOTAL'][2], 342.4, 0)

    def test_E3_a_label_not_printed_is_said_so_by_check_10(self):
        import os, unittest.mock as mock
        iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, other_label='Cadeau unn jour', other_amount='0')[0]
        env = dict(os.environ); env.pop('INVOICE_CHECK_WORDS', None)
        with mock.patch.dict(os.environ, env, clear=True):
            ck = self.checks(iid)
        self.assertEqual(ck[10]['status'], 'fail'); self.assertIn('other_label (non imprimé tant que le montant « autres » est nul : le vider) : « Cadeau unn jour » (unn)', ck[10]['detail'])

    def test_R_E7_1_a_credit_note_on_a_later_invoice_is_not_cancelled_at_this_cutoff(self):
        checks = test_g4.Checks.checks
        a = self.draft(self.pid, '2026-08-01', '2026-08-31', 1, invoice_date='2026-09-01')[0]; self.issue(a, derogate=(12,))      # D9: dated before c, counted
        b = self.draft(self.pid, '2026-10-01', '2026-10-05', 2, invoice_date='2026-10-05')[0]; self.issue(b, derogate=(12,))
        self.c.post(f'/invoice/{b}/credit', data={'reason': 'ajustement', 'qty': '1', 'treatment': 'remboursement'})
        n = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{n}/issue')
        self.assertEqual(self.scalar("SELECT status FROM credit_notes WHERE id=?", (n,)), 'issued')
        c = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, invoice_date='2026-10-01')[0]
        pos = self.header(c)[0]['position']
        self.assertEqual((pos['previous'], pos['current'], pos['credited'], pos['balance'], pos['later']), (1.0, 2.0, 0, 9.0, 2.0))   # 12 − (1 + 2) at 30.09
        ck = checks(self, c)
        self.assertEqual((ck[7]['status'], ck[8]['status']), ('ok', 'ok'), (ck[7], ck[8]))
        self.assertIn('12.0 j commandés − (0 + 1.0 + 2.0 − 0) = 9.0 j', ck[8]['detail'])

    def test_F_C3_1_a_derogation_reason_obeys_the_same_rule(self):
        iid = self.draft(self.pid, '2026-10-01', '2026-10-31', 2)[0]
        c = sqlite3.connect(self.db); c.execute("UPDATE invoices SET invoice_date='2026-10-01' WHERE id=?", (iid,)); c.commit(); c.close()
        base = {'reliquat_treatment': 'reporte', 'confirm_backdate': '2026-10-01', 'derogation_12': 'forfait convenu avec le client'}
        for why in ('\u200b' * 12, '\u3164' * 12, '\u202etneilc ud ednameD'):
            self.flashes(); self.c.post(f'/issue/{iid}', data=dict(base, derogation_13=why))
            self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft', repr(why))
        self.c.post(f'/issue/{iid}', data=dict(base, derogation_13="facture d'acompte demandée par le client"))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())

    def test_E7_the_summary_says_which_earlier_invoices_are_counted(self):
        import re
        from tests.test_functional import pdf_text
        iid = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0]
        t = re.sub(r'\s+', ' ', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))
        from app.billing_rules import local_today                                                             # D9 (2026-10-07): counted by their date
        self.assertIn(f"factures Time Billing émises datées au plus tard du {local_today().strftime('%d.%m.%Y')}", t)
