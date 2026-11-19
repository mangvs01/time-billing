"""V9.2-rc19 (user rule 2026-10-05): a time entry is NEVER locked because it is old, imported, of a closed mandate or invoiced.
The issued invoice stays IMMUTABLE. Synthetic data only, on a COPY of the staging database (see test_import.py for the run command).

Recette required by the user
R1  modify an imported historical entry (provenance kept: file, sheet, row, batch, import date)
R2  modify start / end
R3  modify the duration
R4  modify the description
R5  modify an entry of a closed mandate (new entries stay refused; moving to ANOTHER closed mandate needs the explicit box)
R6  modify an entry already invoiced (warning, reason and confirmation required)
R7  the issued invoice stays strictly unchanged (row, frozen copy, annex links, PDF bytes, archive ZIP)
R8  the post-invoicing variance is visible (message, archive line, detail page, dashboard alert)
R9  before / after audit (history row: values, date-time, user, reason, invoices; audit log; database-level trace)
R10 a credit note can then balance the variance
Also: deleting a billed entry, moves across periods / mandates, cumulative-annex entries, current indicators recomputed, the import-batch
rollback refused once an entry of the batch was corrected, re-import still refused, schema migration from rc18 (foreign key removed).
"""
import html as H, io, json, re, sqlite3, zipfile
from datetime import datetime

import app.app as m
from app import billing_rules as rules
from tests.test_import import workbook
from tests.test_v92 import V92
from tests._app_facts import APP_ROOT


def text(r): return H.unescape(r.get_data(as_text=True))


class RC19(V92):
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat RC19', rate='800', vat='0', ordered='20')
        self.pid2 = self.mandate(name='Mandat RC19 bis', rate='500', vat='0', ordered='5', legal_id='CHE-000.000.002')

    def eid(self, desc): return self.scalar('SELECT id FROM entries WHERE description=?', (desc,))
    def row(self, eid): return self.sql('SELECT * FROM entries WHERE id=?', (eid,))[0]
    def changes(self, eid): return self.sql('SELECT * FROM entry_changes WHERE entry_id=? ORDER BY id', (eid,))

    def edit(self, eid, **kw):
        r0 = self.row(eid)
        data = {'work_date': r0['work_date'], 'project_id': str(r0['project_id']), 'entry_mode': 'duration', 'manual_hours': str(r0['hours']),
                'description': r0['description']}
        if r0['start_time'] and r0['end_time']: data.update(entry_mode='clock', start_time=r0['start_time'], end_time=r0['end_time'], manual_hours='')
        data.update(kw)
        self.flashes(); r = self.c.post(f'/entry/{eid}/edit', data=data)
        return r, ' '.join(self.flashes()) + (' ' + text(r) if r.status_code == 200 else '')

    def delete(self, eid, **kw):
        self.flashes(); r = self.c.post(f'/entry/{eid}/delete', data=kw)
        return r, ' '.join(self.flashes())

    def clock(self, pid, d, s, e, desc):
        return self.c.post('/entry', data={'work_date': d, 'project_id': str(pid), 'entry_mode': 'clock', 'start_time': s, 'end_time': e, 'description': desc})

    def frozen_state(self, iid):
        return (tuple(self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]), tuple(self.sql('SELECT * FROM invoice_snapshots WHERE invoice_id=?', (iid,))[0]),
                [tuple(r) for r in self.sql('SELECT * FROM invoice_annex_entries WHERE invoice_id=? ORDER BY entry_id', (iid,))],
                self.c.get(f'/invoice/{iid}.pdf').data)

    def archive_pdfs(self):
        z = zipfile.ZipFile(io.BytesIO(self.c.get('/archive.zip').data))
        return {n: z.read(n) for n in z.namelist() if n.lower().endswith('.pdf')}

    def import_batch(self, rows, sheet='MAR', data=None):
        t = self.upload(data or workbook({sheet: rows})); form = self.save(t, {'Alpha': self.p1})
        pending = {str(r['idx']): 'include' for r in self.summary(t)[0] if r['status'] == 'needs_decision'}   # warnings: imported as declared
        if pending: form = self.save(t, {'Alpha': self.p1}, pending)
        r, fl = self.commit(t, form); self.assertIn('Import validé', ' '.join(fl))
        return self.scalar("SELECT id FROM import_batches WHERE status='COMMITTED' ORDER BY created_at DESC, rowid DESC LIMIT 1")

    def variance(self, iid):
        c = m.db()
        try: return m.post_billing.invoice_variance(c, c.execute('SELECT * FROM invoices WHERE id=?', (iid,)).fetchone())
        finally: c.close()

    def billed_world(self):
        """The user's example: one entry of 5 h, invoiced 5 h (0,625 j at 800 CHF)."""
        self.entry(self.pid, '2026-09-10', 5, 'atelier 5 h')
        self.iid = self.issued(self.pid, '2026-09-01', '2026-09-30', 0.625)
        return self.eid('atelier 5 h')


class ImportedHistory(RC19):
    def test_R1_imported_entry_is_editable_and_keeps_its_provenance(self):
        batch = self.import_batch([(datetime(2025, 3, 3), 'historique A', 'Alpha', None, None, 2), (datetime(2025, 3, 4), 'historique B', 'Alpha', None, None, 1)])
        e = self.eid('historique A')
        prov = tuple(self.sql('SELECT * FROM import_batch_rows WHERE entry_id=?', (e,))[0]); batch_row = tuple(self.sql('SELECT * FROM import_batches WHERE id=?', (batch,))[0])
        page = text(self.c.get(f'/entry/{e}/edit'))
        for needle in ('Provenance (import historique)', 'Time sheet test.xlsx', 'MAR · ligne', batch, 'Valeurs lues dans le classeur'):
            self.assertIn(needle, page)
        self.assertNotRegex(page, r'<(input|select|button)[^>]*\bdisabled\b')
        r, fl = self.edit(e, work_date='2025-03-05', manual_hours='2.5', description='historique A corrigée', project_id=str(self.pid2))
        self.assertEqual(r.status_code, 302, fl); self.assertIn('modifiée', fl)
        x = self.row(e)
        self.assertEqual((x['work_date'], x['hours'], x['description'], x['project_id']), ('2025-03-05', 2.5, 'historique A corrigée', self.pid2))
        self.assertEqual((x['source'], x['import_batch_id']), ('historical_excel', batch)); self.assertTrue(x['source_ref'].startswith('MAR!'))
        self.assertEqual(tuple(self.sql('SELECT * FROM import_batch_rows WHERE entry_id=?', (e,))[0]), prov)       # provenance untouched
        self.assertEqual(tuple(self.sql('SELECT * FROM import_batches WHERE id=?', (batch,))[0]), batch_row)
        ch = self.changes(e); self.assertEqual([c['action'] for c in ch], ['update'])
        before = json.loads(ch[0]['before_json']); after = json.loads(ch[0]['after_json'])
        self.assertEqual((before['hours'], before['work_date'], before['import_batch_id'], before['source_ref']), (2, '2025-03-03', batch, x['source_ref']))
        self.assertEqual((after['hours'], after['work_date'], after['project_id']), (2.5, '2025-03-05', self.pid2))
        self.assertEqual(ch[0]['actor'], m.SEC['user'])
        # deletion allowed as well (no invoice involved); the import register keeps the source row
        r, fl = self.delete(self.eid('historique B'), reason='doublon du classeur'); self.assertIn('supprimée', fl)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM import_batch_rows WHERE batch_id=? AND entry_id IS NOT NULL', (batch,)), 2)

    def test_batch_rollback_is_refused_once_an_entry_was_corrected_and_reimport_stays_refused(self):
        data = workbook({'MAR': [(datetime(2025, 3, 3), 'lot corrigé', 'Alpha', None, None, 2)]})
        b1 = self.import_batch(None, data=data)
        b2 = self.import_batch([(datetime(2025, 4, 3), 'lot intact', 'Alpha', None, None, 1)], sheet='AVR')
        self.edit(self.eid('lot corrigé'), manual_hours='3')
        self.flashes(); self.c.post(f'/imports/rollback/{b1}'); fl = ' '.join(self.flashes())
        self.assertIn('Rollback refusé : 1 saisie(s) de ce lot ont été corrigées', fl)
        self.assertEqual(self.scalar("SELECT status FROM import_batches WHERE id=?", (b1,)), 'COMMITTED')
        self.assertEqual(self.scalar('SELECT hours FROM entries WHERE description=?', ('lot corrigé',)), 3)
        self.flashes(); self.c.post(f'/imports/rollback/{b2}'); self.assertIn('Lot annulé : 1', ' '.join(self.flashes()))
        # the same workbook uploaded again: never a duplicate; OVERWRITE_MATCHING (2026-10-07): the corrected line matches its entry, kept unless « écraser »
        t = self.upload(data); self.save(t, {'Alpha': self.p1})
        self.assertEqual([(r['status'], 'entry_corrected_since_import' in r['issues']) for r in self.summary(t)[0]], [('keep', True)])


class EditAnyField(RC19):
    def test_R2_R3_R4_start_end_duration_description(self):
        self.clock(self.pid, '2026-08-12', '08:00', '12:00', 'horaires')
        e = self.eid('horaires')
        r, fl = self.edit(e, start_time='08:30', end_time='12:15'); self.assertIn('modifiée', fl)
        self.assertEqual((self.row(e)['start_time'], self.row(e)['end_time'], self.row(e)['hours']), ('08:30', '12:15', 3.75))
        r, fl = self.edit(e, start_time='22:00', end_time='02:00'); self.assertIn('passant minuit', fl)          # rc17 rule kept
        self.assertEqual(self.row(e)['hours'], 4)
        r, fl = self.edit(e, entry_mode='duration', manual_hours='4.25', start_time='', end_time=''); self.assertIn('modifiée', fl)
        self.assertEqual((self.row(e)['start_time'], self.row(e)['end_time'], self.row(e)['hours']), ('', '', 4.25))
        r, fl = self.edit(e, description='atelier de préparation'); self.assertIn('modifiée', fl)
        self.assertEqual(self.row(e)['description'], 'atelier de préparation')
        self.assertEqual(len(self.changes(e)), 4)
        r, fl = self.edit(e, manual_hours='0'); self.assertIn('durée doit être positive', fl)                  # validation unchanged
        r, fl = self.edit(e, manual_hours='4.5', reason='x' * 501); self.assertIn('motif trop long', fl)


class ClosedMandate(RC19):
    def test_R5_old_entries_of_a_closed_mandate_stay_editable_new_ones_refused(self):
        self.entry(self.pid2, '2026-06-10', 2, 'avant clôture'); self.entry(self.pid, '2026-06-11', 1, 'chez le premier')
        e = self.eid('avant clôture')
        self.c.post(f'/project/{self.pid2}/close', data={'reason': 'mandat terminé'})
        page = text(self.c.get(f'/entry/{e}/edit')); self.assertIn('clôturé', page); self.assertIn('Rattacher à un mandat clôturé', page)
        r, fl = self.edit(e, manual_hours='2.5', description='avant clôture (corrigée)'); self.assertIn('modifiée', fl)
        self.assertEqual((self.row(e)['hours'], self.row(e)['project_id']), (2.5, self.pid2))
        # a new entry on the closed mandate stays refused
        self.flashes(); self.c.post('/entry', data={'work_date': '2026-06-12', 'project_id': self.pid2, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'nouvelle'})
        self.assertIn('clôturé', ' '.join(self.flashes())); self.assertEqual(self.sql("SELECT id FROM entries WHERE description='nouvelle'"), [])
        # moving another entry INTO the closed mandate: refused by default, allowed with the explicit box (history correction)
        o = self.eid('chez le premier')
        r, fl = self.edit(o, project_id=str(self.pid2)); self.assertIn('Rattacher à un mandat clôturé', fl); self.assertEqual(self.row(o)['project_id'], self.pid)
        r, fl = self.edit(o, project_id=str(self.pid2), allow_closed='1', reason='affectation corrigée'); self.assertIn('modifiée', fl); self.assertEqual(self.row(o)['project_id'], self.pid2)
        # and out of it, to an active mandate
        r, fl = self.edit(e, project_id=str(self.pid)); self.assertIn('modifiée', fl); self.assertEqual(self.row(e)['project_id'], self.pid)
        r, fl = self.delete(o); self.assertIn('supprimée', fl)
        self.assertEqual(self.scalar('SELECT active FROM projects WHERE id=?', (self.pid2,)), 0)   # the mandate stays closed throughout


class PostInvoicing(RC19):
    def test_R6_R7_R8_R9_R10_the_users_example(self):
        e = self.billed_world()
        state = self.frozen_state(self.iid); zip0 = self.archive_pdfs()
        page = text(self.c.get(f'/entry/{e}/edit'))
        self.assertIn('Saisie déjà facturée', page); self.assertIn(self.scalar('SELECT number FROM invoices WHERE id=?', (self.iid,)), page)
        self.assertIn('name="confirm_billed"', page)
        # R6: refused without reason, then without confirmation
        r, fl = self.edit(e, manual_hours='4.5'); self.assertIn('motif obligatoire', fl)
        r, fl = self.edit(e, manual_hours='4.5', reason='durée réelle 4,5 h'); self.assertIn('cocher la confirmation', fl)
        self.assertEqual(self.row(e)['hours'], 5)
        t0 = rules.utc_now_iso()
        r, fl = self.edit(e, manual_hours='4.5', reason='durée réelle 4,5 h', confirm_billed='1')
        self.assertEqual(r.status_code, 302, fl); self.assertEqual(self.row(e)['hours'], 4.5)
        # R7: the issued invoice stays strictly unchanged
        self.assertEqual(self.frozen_state(self.iid), state); self.assertEqual(self.archive_pdfs(), zip0)
        # R8: variance visible
        self.assertIn('Écart post-facturation', fl); self.assertIn('−0,50 h', fl); self.assertIn('−0,0625 j', fl)
        v = self.variance(self.iid)
        self.assertEqual((v['frozen_hours'], v['current_hours'], v['variance_hours'], v['variance_days']), (5, 4.5, -0.5, -0.0625))
        self.assertEqual([(x['id'], x['status']) for x in v['changed']], [(e, 'modifiée')])
        arch = text(self.c.get('/?tab=archive')); self.assertIn('Écart post-facturation : −0,50 h (−0,0625 j)', arch)
        self.assertIn('variancesAlert', self.c.get('/').get_data(as_text=True))
        detail = text(self.c.get(f'/invoice/{self.iid}/ecart'))
        for needle in ('5,00 h', '4,50 h', '−0,50 h', '−0,0625 j', '−50,00\u00a0CHF', 'modifiée'): self.assertIn(needle, detail)
        # R9: audit before / after, date-time, user, reason, invoices
        ch = self.changes(e)[0]
        self.assertEqual((json.loads(ch['before_json'])['hours'], json.loads(ch['after_json'])['hours']), (5, 4.5))
        self.assertGreaterEqual(ch['changed_at'], t0[:19]); self.assertEqual(ch['actor'], m.SEC['user']); self.assertEqual(ch['reason'], 'durée réelle 4,5 h')
        num = self.scalar('SELECT number FROM invoices WHERE id=?', (self.iid,))
        self.assertEqual(json.loads(ch['invoices_json']), [{'id': self.iid, 'number': num, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'role': 'billed'}])
        a = json.loads(self.sql("SELECT detail FROM audit WHERE event='time_entry_updated' ORDER BY id DESC LIMIT 1")[0][0])
        self.assertEqual((a['invoices'], a['reason'], a['by']), ([f'{num}:billed'], 'durée réelle 4,5 h', m.SEC['user']))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='entry_row_updated' AND detail LIKE ?", (f'{{"id":{e},"invoiced":1%',)), 1)   # database-level trace
        hist = text(self.c.get(f'/entry/{e}/edit')); self.assertIn('motif : durée réelle 4,5 h', hist); self.assertIn(f'facturée par {num}', hist)
        # current indicators recomputed from the corrected entry; billed days unchanged
        p = self.sql('SELECT * FROM projects WHERE id=?', (self.pid,))[0]
        c = m.db()
        try: k = rules.contract(c, p)
        finally: c.close()
        self.assertEqual((k['consumed_hours'], k['gross_billed_days'], k['unbilled_days']), (4.5, 0.625, -0.0625))
        # R10: a credit note of the variance balances it (link pre-filled, the user still decides and issues)
        link = re.search(r'href="(/invoice/\d+/credit\?ecart=1)"', self.c.get(f'/invoice/{self.iid}/ecart').get_data(as_text=True)).group(1)
        form = text(self.c.get(H.unescape(link))); self.assertIn('value="0.0625"', form)
        self.flashes(); self.c.post(f'/invoice/{self.iid}/credit', data={'reason': 'écart post-facturation', 'qty': '0.0625', 'unit_rate': '800', 'treatment': 'remboursement'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.assertEqual(self.scalar('SELECT status FROM credit_notes WHERE id=?', (cid,)), 'issued', self.flashes())
        v = self.variance(self.iid); self.assertEqual((v['credited_after_days'], v['remaining_days']), (0.0625, 0))
        self.assertIn('variancesAlert', self.c.get('/').get_data(as_text=True))                   # the user still has to say what was done
        self.flashes(); self.c.post(f'/invoice/{self.iid}/ecart/decision', data={'fingerprint': v['fingerprint'], 'decision': 'avoir', 'credit_note_id': str(cid)})
        self.assertIn('Décision enregistrée', ' '.join(self.flashes()))
        self.assertNotIn('variancesAlert', self.c.get('/').get_data(as_text=True))
        self.assertEqual(self.variance(self.iid)['decision']['credit_note_id'], cid)
        c = m.db()
        try: k = rules.contract(c, p)
        finally: c.close()
        self.assertEqual((k['billed_days'], k['unbilled_days']), (0.5625, 0))
        self.assertEqual(self.frozen_state(self.iid), state)        # still the very same invoice

    def test_deleting_a_billed_entry(self):
        e = self.billed_world(); state = self.frozen_state(self.iid)
        r, fl = self.delete(e); self.assertIn('la supprimer depuis sa page de correction', fl)
        self.assertEqual(r.headers['Location'].split('#')[-1], 'supprimer')
        r, fl = self.delete(e, reason='doublon'); self.assertIn('Suppression refusée', fl)                          # confirmation missing
        r, fl = self.delete(e, reason='doublon', confirm_billed='1'); self.assertIn('supprimée', fl); self.assertIn('−5,00 h', fl)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries WHERE id=?', (e,)), 0)
        self.assertEqual(self.frozen_state(self.iid), state)          # the annex link to the deleted entry stays, frozen
        v = self.variance(self.iid); self.assertEqual((v['variance_hours'], v['changed'][0]['status']), (-5, 'supprimée'))
        self.assertEqual(self.changes(e)[-1]['action'], 'delete'); self.assertEqual(self.changes(e)[-1]['reason'], 'doublon')
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='entry_row_deleted' AND detail LIKE ?", (f'{{"id":{e},"invoiced":1%',)), 1)
        self.assertEqual(self.sql('PRAGMA foreign_key_check'), [])
        # a new entry never reuses the id of the deleted (invoiced) one
        self.entry(self.pid, '2026-10-01', 1, 'après suppression'); self.assertGreater(self.eid('après suppression'), e)
        self.assertIn('supprimée', text(self.c.get(f'/invoice/{self.iid}/ecart')))

    def test_moves_across_periods_and_mandates_and_late_entries(self):
        self.entry(self.pid, '2026-08-10', 8, 'août'); self.entry(self.pid, '2026-09-10', 4, 'septembre')
        f8 = self.issued(self.pid, '2026-08-01', '2026-08-31', 1); f9 = self.issued(self.pid, '2026-09-01', '2026-09-30', 0.5)
        e = self.eid('août')
        r, fl = self.edit(e, work_date='2026-09-02', reason='mauvaise date', confirm_billed='1'); self.assertIn('modifiée', fl)
        v8, v9 = self.variance(f8), self.variance(f9)
        self.assertEqual((v8['variance_hours'], v8['changed'][0]['status'], v8['changed'][0]['where']['invoice']), (0, 'date reclassée', v9['number']))
        self.assertEqual((v9['variance_hours'], v9['late'], [x['id'] for x in v9['reclassified']]), (0, [], [e]))   # billed once, by août
        self.assertIn('aucune double facturation', fl)
        r, fl = self.edit(e, work_date='2026-10-05', reason='date future', confirm_billed='1')       # into a period not billed yet
        self.assertIn("n'est pas comptée une seconde fois", fl); self.assertEqual(self.variance(f8)['changed'][0]['where']['invoice'], None)
        r, fl = self.edit(e, project_id=str(self.pid2), work_date='2026-08-10', reason='autre mandat', confirm_billed='1')
        v8 = self.variance(f8); self.assertEqual((v8['variance_hours'], v8['changed'][0]['status']), (-8, 'autre mandat'))
        r, fl = self.edit(e, project_id=str(self.pid), reason='retour', confirm_billed='1')
        v8 = self.variance(f8); self.assertEqual((v8['variance_hours'], v8['changed']), (0, []))     # back to what was billed
        self.entry(self.pid, '2026-09-20', 2, 'tardive')
        self.assertEqual([x['description'] for x in self.variance(f9)['late']], ['tardive'])
        self.assertEqual(self.variance(f9)['variance_hours'], 0)

    def test_cumulative_annex_entry_is_listed_not_billed(self):
        self.entry(self.pid, '2026-07-10', 6, 'juillet hors facture'); self.entry(self.pid, '2026-09-10', 4, 'septembre')
        f9 = self.issued(self.pid, '2026-09-01', '2026-09-30', 0.5)
        e = self.eid('juillet hors facture')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_annex_entries WHERE invoice_id=? AND entry_id=?', (f9, e)), 1)
        page = text(self.c.get(f'/entry/{e}/edit')); self.assertNotIn('Saisie déjà facturée', page); self.assertIn('annexe cumulative figée', page)
        r, fl = self.edit(e, manual_hours='5'); self.assertIn('modifiée', fl)                                      # no reason needed
        self.assertEqual(self.variance(f9)['variance_hours'], 0)
        self.assertEqual(json.loads(self.changes(e)[0]['invoices_json'])[0]['role'], 'annex')

    def test_draft_covering_a_corrected_entry_is_flagged_and_two_tabs_race(self):
        e = self.billed_world()
        page = self.c.get(f'/entry/{e}/edit').get_data(as_text=True); rev = re.search(r'name="rev" value="([0-9a-f]+)"', page).group(1)
        r, fl = self.edit(e, manual_hours='4', reason='a', confirm_billed='1', rev=rev); self.assertIn('modifiée', fl)
        r, fl = self.edit(e, manual_hours='3', reason='b', confirm_billed='1', rev=rev); self.assertIn('modifiée depuis l\'ouverture', fl)
        self.assertEqual(self.row(e)['hours'], 4)

    def test_hour_unit_invoice_variance_in_hours(self):
        self.entry(self.pid, '2026-09-10', 3, 'à l\'heure')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 3, unit='hour')
        if self.scalar('SELECT unit FROM invoices WHERE id=?', (iid,)) != 'hour': self.skipTest('hour unit not offered by the draft form')
        self.flashes(); self.issue(iid)
        e = self.eid('à l\'heure'); self.edit(e, manual_hours='2', reason='r', confirm_billed='1')
        v = self.variance(iid); self.assertEqual((v['variance_hours'], v['variance_days']), (-1, -0.125))


class Migration(RC19):
    def test_rc18_schema_is_migrated_once_without_touching_any_row(self):
        """A database still carrying the rc18 schema (foreign key annex -> entries, two blocking triggers) is migrated at start-up:
        same link rows, same entries, triggers replaced, foreign key gone; a second start does nothing."""
        e = self.billed_world()
        c = sqlite3.connect(self.db); c.isolation_level = None
        c.execute('PRAGMA foreign_keys=OFF'); c.execute('BEGIN')
        links = c.execute('SELECT invoice_id,entry_id FROM invoice_annex_entries ORDER BY 1,2').fetchall()
        for t in m.RC19_TRIGGER_NAMES: c.execute(f'DROP TRIGGER IF EXISTS {t}')        # an rc18 file has none of them
        c.execute('ALTER TABLE invoice_annex_entries RENAME TO x_annex')
        c.execute('CREATE TABLE invoice_annex_entries(invoice_id INTEGER NOT NULL REFERENCES invoices(id), entry_id INTEGER NOT NULL REFERENCES entries(id), PRIMARY KEY(invoice_id,entry_id))')
        c.execute('INSERT INTO invoice_annex_entries SELECT * FROM x_annex'); c.execute('DROP TABLE x_annex')
        c.execute('CREATE INDEX idx_annex_entry ON invoice_annex_entries(entry_id)')
        for t in m.ANNEX_TRIGGERS: c.execute(t)
        c.execute("CREATE TRIGGER annexed_entry_no_update BEFORE UPDATE ON entries WHEN EXISTS(SELECT 1 FROM invoice_annex_entries WHERE entry_id=OLD.id) BEGIN SELECT RAISE(ABORT,'Entry belongs to an issued invoice annex'); END")
        c.execute("CREATE TRIGGER annexed_entry_no_delete BEFORE DELETE ON entries WHEN EXISTS(SELECT 1 FROM invoice_annex_entries WHERE entry_id=OLD.id) BEGIN SELECT RAISE(ABORT,'Entry belongs to an issued invoice annex'); END")
        c.execute('COMMIT')
        with self.assertRaises(sqlite3.DatabaseError): c.execute('UPDATE entries SET hours=1 WHERE id=?', (e,))      # rc18 behaviour
        entries0 = c.execute('SELECT * FROM entries ORDER BY id').fetchall()
        n0 = c.execute("SELECT COUNT(*) FROM audit WHERE event='schema_rc19_annex_rebuilt'").fetchone()[0]; c.close()
        m.init()
        c = sqlite3.connect(self.db)
        try:
            self.assertEqual(c.execute('SELECT invoice_id,entry_id FROM invoice_annex_entries ORDER BY 1,2').fetchall(), links)
            self.assertEqual(c.execute('SELECT * FROM entries ORDER BY id').fetchall(), entries0)
            self.assertFalse([r for r in c.execute('PRAGMA foreign_key_list(invoice_annex_entries)') if r[2] == 'entries'])
            trig = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            self.assertTrue({'invoice_annex_no_update', 'invoice_annex_no_delete', 'entry_update_traced', 'entry_delete_traced'} <= trig)
            self.assertFalse({'annexed_entry_no_update', 'annexed_entry_no_delete'} & trig)
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok'); self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE event='schema_rc19_annex_rebuilt'").fetchone()[0], n0 + 1)
            for q in ('DELETE FROM invoice_annex_entries', 'UPDATE invoice_annex_entries SET entry_id=0'):
                with self.assertRaises(sqlite3.DatabaseError): c.execute(q)
        finally: c.close()
        m.init()
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='schema_rc19_annex_rebuilt'"), n0 + 1)     # idempotent
        r, fl = self.edit(e, manual_hours='4', reason='après migration', confirm_billed='1'); self.assertIn('modifiée', fl)
        cols = [r[1] for r in self.sql('PRAGMA table_info(entry_changes)')]
        self.assertTrue({'reason', 'actor', 'invoices_json'} <= set(cols))


class Robustness(RC19):
    def test_declared_hours_of_an_imported_entry_survive_a_description_only_correction(self):
        """Imports keep the DECLARED hours even when the clock times disagree (staging: SEPT 26!82 12:15-13:00 declared 0,7487 h)."""
        self.import_batch([(datetime(2025, 3, 3), 'déclarée', 'Alpha', 12.25, 13, 0.7487)])
        e = self.eid('déclarée'); r0 = self.row(e)
        self.assertEqual((r0['start_time'], r0['end_time'], r0['hours']), ('12:15', '13:00', 0.7487))
        page = text(self.c.get(f'/entry/{e}/edit')); self.assertIn('Durée enregistrée : 0,7487 h (durée déclarée dans le classeur)', page)
        r, fl = self.edit(e, description='déclarée (texte corrigé)'); self.assertIn('modifiée', fl)
        r1 = self.row(e); self.assertEqual((r1['start_time'], r1['end_time'], r1['hours']), ('12:15', '13:00', 0.7487))
        ch = self.changes(e)[0]; b, a = json.loads(ch['before_json']), json.loads(ch['after_json'])
        self.assertEqual({k for k in b if b[k] != a[k]}, {'description'})
        r, fl = self.edit(e, end_time='13:15'); self.assertEqual(self.row(e)['hours'], 1)            # a new end time recomputes

    def test_a_deleted_id_is_never_given_again_by_an_import(self):
        self.entry(self.pid, '2026-09-10', 5, 'dernière')
        iid = self.issued(self.pid, '2026-09-01', '2026-09-30', 0.625)
        e = self.eid('dernière'); self.assertEqual(e, self.scalar('SELECT MAX(id) FROM entries'))
        self.delete(e, reason='doublon', confirm_billed='1'); self.assertEqual(self.sql('SELECT id FROM entries WHERE id=?', (e,)), [])
        self.import_batch([(datetime(2025, 3, 3), 'nouvelle importée', 'Alpha', None, None, 1)])
        n = self.eid('nouvelle importée'); self.assertGreater(n, e)
        self.assertEqual(self.changes(n), []); self.assertEqual(self.sql('SELECT * FROM invoice_annex_entries WHERE entry_id=?', (n,)), [])
        self.entry(self.pid, '2026-10-01', 1, 'manuelle'); self.assertGreater(self.eid('manuelle'), n)

    def test_closed_mandate_override_needs_a_reason(self):
        self.entry(self.pid, '2026-06-11', 1, 'à déplacer'); e = self.eid('à déplacer')
        self.c.post(f'/project/{self.pid2}/close', data={'reason': 'fin'})
        r, fl = self.edit(e, project_id=str(self.pid2), allow_closed='1'); self.assertIn('motif obligatoire', fl); self.assertEqual(self.row(e)['project_id'], self.pid)
        r, fl = self.edit(e, project_id=str(self.pid2), allow_closed='1', reason='erreur d\'affectation à l\'import')
        self.assertIn('ne peuvent pas être facturées tant qu\'il reste clôturé', fl); self.assertEqual(self.row(e)['project_id'], self.pid2)
        self.assertEqual(self.changes(e)[0]['reason'], 'erreur d\'affectation à l\'import')
        r, fl = self.edit(e, project_id=str(self.pid)); self.assertIn('heures retirées du mandat clôturé', fl)

    def test_decisions_are_append_only_and_follow_the_current_variance(self):
        e = self.billed_world()
        self.edit(e, manual_hours='4.5', reason='r1', confirm_billed='1'); v = self.variance(self.iid)
        self.assertTrue(v['needs_decision'])
        post = lambda **kw: (self.flashes(), self.c.post(f'/invoice/{self.iid}/ecart/decision', data=kw), ' '.join(self.flashes()))[2]
        self.assertIn('l\'écart a changé', post(fingerprint='x', decision='aucune', reason='r'))
        self.assertIn('motif obligatoire', post(fingerprint=v['fingerprint'], decision='aucune'))
        self.assertIn('choisir la note de crédit', post(fingerprint=v['fingerprint'], decision='avoir', credit_note_id='999'))
        self.assertIn('Décision enregistrée', post(fingerprint=v['fingerprint'], decision='aucune', reason='écart accepté avec le client'))
        self.assertFalse(self.variance(self.iid)['needs_decision']); self.assertNotIn('variancesAlert', self.c.get('/').get_data(as_text=True))
        self.edit(e, manual_hours='4', reason='r2', confirm_billed='1')                                # a new change: the decision is outdated
        v2 = self.variance(self.iid); self.assertTrue(v2['needs_decision']); self.assertNotEqual(v2['fingerprint'], v['fingerprint'])
        self.assertIn('variancesAlert', self.c.get('/').get_data(as_text=True))
        self.assertIn('écart antérieur', text(self.c.get(f'/invoice/{self.iid}/ecart')))
        c = sqlite3.connect(self.db)
        try:
            for q in ('UPDATE invoice_variance_decisions SET decision=\'avoir\'', 'DELETE FROM invoice_variance_decisions'):
                with self.assertRaises(sqlite3.DatabaseError): c.execute(q)
        finally: c.close()

    def test_unrelated_and_amount_only_credit_notes(self):
        e = self.billed_world()
        # a commercial gesture BEFORE any correction is not counted against the variance
        self.c.post(f'/invoice/{self.iid}/credit', data={'reason': 'geste', 'amount': '100', 'treatment': 'remboursement'})
        g = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{g}/issue')
        from datetime import timedelta
        real = rules.utc_now
        try:   # the correction and the later note happen one minute after the gesture (timestamps have a one-second resolution)
            rules.utc_now = lambda: real() + timedelta(minutes=1)
            self.edit(e, manual_hours='4.5', reason='durée', confirm_billed='1')
            v = self.variance(self.iid); self.assertEqual((v['credited_after_days'], v['remaining_days']), (0, -0.0625))
            # an amount-only note issued after the correction counts at the invoice rate (50 CHF at 800 CHF/j = 0,0625 j)
            self.c.post(f'/invoice/{self.iid}/credit', data={'reason': 'écart', 'amount': '50', 'treatment': 'remboursement'})
            n = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{n}/issue')
        finally: rules.utc_now = real
        self.assertEqual(self.scalar('SELECT status FROM credit_notes WHERE id=?', (n,)), 'issued', self.flashes())
        v = self.variance(self.iid); self.assertEqual((v['credited_after_days'], v['remaining_days']), (0.0625, 0))
        page = text(self.c.get(f'/invoice/{self.iid}/ecart')); self.assertIn('montant converti au tarif', page); self.assertIn('après la correction', page)

    def test_compensation_note_unavailable_without_frozen_legal_id_is_said(self):
        e = self.billed_world()
        c = sqlite3.connect(self.db); c.execute("UPDATE projects SET client_legal_id='' WHERE id=?", (self.pid,)); c.commit(); c.close()
        self.entry(self.pid, '2026-10-02', 2, 'octobre'); f10 = self.issued(self.pid, '2026-10-01', '2026-10-04', 0.25)
        e10 = self.eid('octobre'); self.edit(e10, manual_hours='1', reason='r', confirm_billed='1')
        self.assertIn('compensation est impossible sur cette facture', text(self.c.get(f'/invoice/{f10}/ecart')))
        self.edit(e, manual_hours='4', reason='r', confirm_billed='1')
        self.assertNotIn('compensation est impossible', text(self.c.get(f'/invoice/{self.iid}/ecart')))

    def test_concurrent_start_of_two_workers_migrates_once_and_leaves_working_triggers(self):
        """gunicorn starts 2 workers, each running init(): on an rc18-shaped file holding issued invoices, the migration runs once and
        every trigger still compiles (a rename while another trigger reads the table would leave it pointing to a missing table)."""
        import os, subprocess, sys, shutil
        e = self.billed_world(); self.entry(self.pid, '2026-10-02', 2, 'oct'); self.issued(self.pid, '2026-10-01', '2026-10-04', 0.25)
        links = self.sql('SELECT invoice_id,entry_id FROM invoice_annex_entries ORDER BY 1,2'); self.assertTrue(links)
        for round_ in range(3):
            path = os.path.join(self.tmp, f'conc{round_}.db'); shutil.copy(self.db, path)
            c = sqlite3.connect(path); c.isolation_level = None; c.execute('PRAGMA foreign_keys=OFF'); c.execute('BEGIN')
            for t in m.RC19_TRIGGER_NAMES: c.execute(f'DROP TRIGGER IF EXISTS {t}')
            c.execute('ALTER TABLE invoice_annex_entries RENAME TO x_annex')
            c.execute('CREATE TABLE invoice_annex_entries(invoice_id INTEGER NOT NULL REFERENCES invoices(id), entry_id INTEGER NOT NULL REFERENCES entries(id), PRIMARY KEY(invoice_id,entry_id))')
            c.execute('INSERT INTO invoice_annex_entries SELECT * FROM x_annex'); c.execute('DROP TABLE x_annex'); c.execute('CREATE INDEX idx_annex_entry ON invoice_annex_entries(entry_id)')
            for t in m.ANNEX_TRIGGERS: c.execute(t)
            c.execute("CREATE TRIGGER annexed_entry_no_update BEFORE UPDATE ON entries WHEN EXISTS(SELECT 1 FROM invoice_annex_entries WHERE entry_id=OLD.id) BEGIN SELECT RAISE(ABORT,'x'); END")
            c.execute("CREATE TRIGGER annexed_entry_no_delete BEFORE DELETE ON entries WHEN EXISTS(SELECT 1 FROM invoice_annex_entries WHERE entry_id=OLD.id) BEGIN SELECT RAISE(ABORT,'x'); END")
            c.execute('COMMIT'); c.close()
            code = f"import app.app as m; m.init({path!r})"
            procs = [subprocess.Popen([sys.executable, '-c', code], cwd=APP_ROOT, env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
            outs = [p.communicate(timeout=120) for p in procs]
            self.assertEqual([p.returncode for p in procs], [0, 0], [o[1][-600:] for o in outs])
            c = sqlite3.connect(path)
            try:
                self.assertEqual(c.execute('SELECT invoice_id,entry_id FROM invoice_annex_entries ORDER BY 1,2').fetchall(), [tuple(r) for r in links])
                self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE event='schema_rc19_annex_rebuilt'").fetchone()[0],
                                 self.scalar("SELECT COUNT(*) FROM audit WHERE event='schema_rc19_annex_rebuilt'") + 1)
                c.execute('UPDATE entries SET hours=hours WHERE id=?', (e,)); c.execute('DELETE FROM entries WHERE id=?', (e,))      # triggers compile and run
                self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'invoice_annex_entries_%'").fetchone()[0], 0)
                self.assertFalse([r for r in c.execute('PRAGMA foreign_key_list(invoice_annex_entries)') if r[2] == 'entries'])
            finally: c.close()

    def test_restore_of_a_pre_rc19_backup_with_legacy_history_and_of_an_rc19_backup_with_a_deleted_billed_entry(self):
        from app import restore_service as rs
        self.entry(self.pid, '2026-08-10', 2, 'ancienne correction')
        o = self.eid('ancienne correction')
        c = sqlite3.connect(self.db)      # a correction made before rc19: the three columns are NULL
        c.execute("INSERT INTO entry_changes(entry_id,action,before_json,after_json,changed_at) VALUES(?,?,?,?,?)", (o, 'update', '{}', '{}', '2026-09-01T10:00:00'))
        c.commit(); c.close()
        d = json.loads(self.c.get('/backup').data)
        for r in d['tables']['entry_changes']:
            for k in ('reason', 'actor', 'invoices_json'): r.pop(k, None)
        d['tables'].pop('invoice_variance_decisions', None)
        con = m.db()          # rc25 (TB-05): the table cut out of a file that still declares it is an amputated backup, refused
        try: self.assertTrue([b for b in rs.preview(con, rs.validate(con, json.dumps(d).encode()))['blocking'] if 'invoice_variance_decisions' in b])
        finally: con.close()
        d['meta']['row_counts'].pop('invoice_variance_decisions', None)   # a real pre-rc19 file neither counts nor creates the table
        d['meta']['schema'] = [s for s in d['meta']['schema'] if 'invoice_variance_decisions' not in s]
        con = m.db()
        try: self.assertEqual(rs.preview(con, rs.validate(con, json.dumps(d).encode()))['blocking'], [])
        finally: con.close()
        e = self.billed_world(); self.delete(e, reason='doublon', confirm_billed='1')
        raw = self.c.get('/backup').data
        con = m.db()
        try:
            data = rs.validate(con, raw); self.assertEqual(rs.preview(con, data)['blocking'], [])
            tmp = rs.temp_path(self.db); rs.rebuild(tmp, data, m.init)            # foreign keys checked on the rebuilt file
        finally: con.close()
        t = sqlite3.connect(tmp)
        try: self.assertEqual(t.execute('SELECT COUNT(*) FROM invoice_annex_entries WHERE entry_id=?', (e,)).fetchone()[0], 1)
        finally: t.close()


class SchemaChecks(RC19):
    def test_shared_check_is_clean_after_migration_and_catches_a_broken_trigger(self):
        from app import schema_checks
        e = self.billed_world(); self.delete(e, reason='doublon', confirm_billed='1')
        c = sqlite3.connect(self.db)
        try:
            self.assertEqual(schema_checks.rc19_problems(c), [])                    # deleted billed entry: explained by its trace
            c.execute("CREATE TRIGGER broken AFTER UPDATE ON entries BEGIN INSERT INTO table_disparue VALUES(1); END")
            self.assertTrue(any('non compilable' in p for p in schema_checks.rc19_problems(c)))
            c.execute('DROP TRIGGER broken'); c.commit()
            self.entry(self.pid, '2026-10-01', 1, 'vivante')
            c.execute("INSERT INTO entry_changes(entry_id,action,before_json,after_json,changed_at) VALUES(?,?,?,?,?)",
                      (self.eid('vivante'), 'delete', '{}', None, '2026-01-01T00:00:00'))
            self.assertTrue(any('réutilisé' in p for p in schema_checks.rc19_problems(c)))
        finally: c.close()


class Hardening(RC19):
    def test_deleted_entry_history_stays_readable(self):
        e = self.billed_world(); self.delete(e, reason='doublon du 10', confirm_billed='1')
        r = self.c.get(f'/entry/{e}/edit'); self.assertEqual(r.status_code, 302); self.assertIn(f'/entry/{e}/historique', r.headers['Location'])
        page = text(self.c.get(f'/entry/{e}/historique'))
        for needle in ('Saisie supprimée', 'motif : doublon du 10', 'facturée par', '5,00 h', 'atelier 5 h'): self.assertIn(needle, page)
        self.assertIn(f'/entry/{e}/historique', self.c.get(f'/invoice/{self.iid}/ecart').get_data(as_text=True))
        self.assertEqual(self.c.get('/entry/999999/historique').status_code, 404)

    def test_stale_pages_double_submit_and_billing_changed_meanwhile(self):
        self.entry(self.pid, '2026-09-10', 5, 'onglets'); e = self.eid('onglets')
        rev = re.search(r'name="rev" value="([0-9a-f]+)"', self.c.get(f'/entry/{e}/edit').get_data(as_text=True)).group(1)
        r, fl = self.edit(e, manual_hours='4', rev=rev); self.assertIn('modifiée', fl)
        r, fl = self.edit(e, manual_hours='4', rev=rev); self.assertIn('déjà enregistrée', fl)                  # double submit
        r, fl = self.delete(e, rev=rev); self.assertIn('modifiée depuis l\'ouverture', fl); self.assertEqual(self.row(e)['hours'], 4)
        # the page was opened before the invoice was issued: its confirmation does not cover the new invoice
        page = self.c.get(f'/entry/{e}/edit').get_data(as_text=True); rev = re.search(r'name="rev" value="([0-9a-f]+)"', page).group(1)
        self.assertIn('name="billed_ids" value=""', page)
        iid = self.issued(self.pid, '2026-09-01', '2026-09-30', 0.5)
        r, fl = self.edit(e, manual_hours='3', reason='r', confirm_billed='1', rev=rev, billed_ids=''); self.assertIn('la facturation de cette saisie a changé', fl)
        r, fl = self.edit(e, manual_hours='3', reason='r', confirm_billed='1', rev=rev, billed_ids=str(iid)); self.assertIn('modifiée', fl)

    def test_reason_is_one_plain_line_and_audit_details_are_json(self):
        e = self.billed_world()
        for bad in ('ligne 1\nligne 2', 'x‮y', 'a\x00b'):
            r, fl = self.edit(e, manual_hours='4.5', reason=bad, confirm_billed='1'); self.assertIn('caractères de contrôle', fl)
        reason = 'x;invoices=-;by=autre <script>alert(1)</script>'
        r, fl = self.edit(e, manual_hours='4.5', reason=reason, confirm_billed='1'); self.assertIn('modifiée', fl)
        d = json.loads(self.sql("SELECT detail FROM audit WHERE event='time_entry_updated' ORDER BY id DESC LIMIT 1")[0][0])
        self.assertEqual((d['reason'], d['by'], d['id']), (reason, m.SEC['user'], e))
        page = self.c.get(f'/entry/{e}/edit').get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', page); self.assertIn('&lt;script&gt;', page)

    def test_suggestion_never_bills_a_reclassified_entry_twice_and_issuance_warns(self):
        e = self.billed_world()
        self.edit(e, work_date='2026-10-02', reason='date', confirm_billed='1')                   # billed by September, now dated October
        self.entry(self.pid, '2026-10-05', 3, 'octobre')
        st, js = self.suggest(self.pid, '2026-10-01', '2026-10-31')
        self.assertEqual((js['hours'], js['already_billed_hours'], js['raw_days']), (8, 5, 0.375))
        iid, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 0.375)
        page = text(self.c.get(f'/issue/{iid}')); self.assertIn('Saisies déjà facturées corrigées depuis leur facture', page)
        self.assertIn('reprendra ces saisies avec leur valeur actuelle', page)

    def test_forged_backups_are_refused_and_a_newer_backup_with_traced_corrections_restores(self):
        from app import restore_service as rs
        e = self.billed_world(); self.edit(e, manual_hours='4.5', reason='durée', confirm_billed='1')
        good = json.loads(self.c.get('/backup').data)
        con = m.db()
        try:
            self.assertEqual(rs.preview(con, rs.validate(con, json.dumps(good).encode()))['blocking'], [])
            d = json.loads(json.dumps(good))                                                    # untraced change of a billed entry
            for r in d['tables']['entries']:
                if r['id'] == e: r['hours'] = 3
            self.assertTrue([x for x in rs.preview(con, rs.validate(con, json.dumps(d).encode()))['blocking'] if 'sans correction tracée' in x])
        finally: con.close()
        self.delete(e, reason='doublon', confirm_billed='1')
        later = json.loads(self.c.get('/backup').data)
        d = json.loads(json.dumps(later))                                                       # resurrected deleted billed entry
        d['tables']['entries'].append(next(r for r in good['tables']['entries'] if r['id'] == e))
        con = m.db()
        try: self.assertTrue([x for x in rs.preview(con, rs.validate(con, json.dumps(d).encode()))['blocking'] if 'supprimée selon l\'historique' in x])
        finally: con.close()


class ReviewFixes(RC19):
    """Findings of the final adversarial code review of rc19 (2026-10-05), each confirmed by reading + replay before being fixed."""

    def test_suggestion_counts_an_entry_moved_here_from_another_mandates_invoice(self):
        e = self.billed_world()                                                                 # 5 h billed by the invoice of the FIRST mandate
        self.edit(e, project_id=str(self.pid2), reason='mauvais mandat', confirm_billed='1')
        v = self.variance(self.iid); self.assertEqual((v['variance_hours'], v['changed'][0]['status']), (-5, 'autre mandat'))
        st, js = self.suggest(self.pid2, '2026-09-01', '2026-09-30')                           # not billed on the second mandate: proposed there
        self.assertEqual((st, js['hours'], js['already_billed_hours'], js['raw_days']), (200, 5, 0, 0.625))
        e2 = self.eid('atelier 5 h')                                                            # same mandate, date reclassified: still never twice
        self.edit(e2, project_id=str(self.pid), reason='retour', confirm_billed='1')
        self.edit(e2, work_date='2026-10-02', reason='date', confirm_billed='1')
        st, js = self.suggest(self.pid, '2026-10-01', '2026-10-31'); self.assertEqual((js['hours'], js['already_billed_hours']), (5, 5))

    def test_a_credit_note_decision_is_void_once_that_note_is_cancelled(self):
        e = self.billed_world()
        self.edit(e, manual_hours='4.5', reason='durée', confirm_billed='1')
        self.c.post(f'/invoice/{self.iid}/credit', data={'reason': 'écart', 'amount': '50', 'treatment': 'remboursement'})
        n = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{n}/issue')
        self.assertEqual(self.scalar('SELECT status FROM credit_notes WHERE id=?', (n,)), 'issued', self.flashes())
        v = self.variance(self.iid)
        self.flashes(); self.c.post(f'/invoice/{self.iid}/ecart/decision', data={'fingerprint': v['fingerprint'], 'decision': 'avoir', 'credit_note_id': str(n)})
        self.assertFalse(self.variance(self.iid)['needs_decision'], self.flashes())
        self.assertNotIn('variancesAlert', self.c.get('/').get_data(as_text=True))
        self.flashes(); self.c.post(f'/credit/{n}/cancel', data={'reason': 'montant erroné'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_cancellations WHERE credit_note_id=?', (n,)), 1, self.flashes())
        v = self.variance(self.iid)                                                             # the alert is back: nothing treats the variance any more
        self.assertTrue(v['needs_decision']); self.assertIsNone(v['decision'])
        self.assertIn('variancesAlert', self.c.get('/').get_data(as_text=True))
        self.assertIn('décision caduque', text(self.c.get(f'/invoice/{self.iid}/ecart')))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_variance_decisions WHERE invoice_id=?', (self.iid,)), 1)   # append-only: the row stays
        self.c.post(f'/invoice/{self.iid}/ecart/decision', data={'fingerprint': v['fingerprint'], 'decision': 'aucune', 'reason': 'écart accepté'})
        self.assertFalse(self.variance(self.iid)['needs_decision'])                             # a new decision covers it again

    def test_hour_unit_credit_proposal_is_exactly_the_billed_hours(self):
        c = sqlite3.connect(self.db); c.execute('UPDATE projects SET day_hours=6.5 WHERE id=?', (self.pid,)); c.commit(); c.close()
        self.entry(self.pid, '2026-09-10', 3.7, 'heures décimales')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 3.7, unit='hour')
        if self.scalar('SELECT unit FROM invoices WHERE id=?', (iid,)) != 'hour': self.skipTest('hour unit not offered by the draft form')
        self.flashes(); self.issue(iid)
        self.delete(self.eid('heures décimales'), reason='saisie erronée', confirm_billed='1')
        self.assertIn('créer une note de crédit de 3,7 h', text(self.c.get(f'/invoice/{iid}/ecart')))     # was 3,700002 h (hours → days → hours)
        self.assertIn('value="3.7"', self.c.get(f'/invoice/{iid}/credit?ecart=1').get_data(as_text=True))
        v = self.variance(iid); self.assertEqual((v['variance_hours'], v['remaining_units']), (-3.7, -3.7))
        self.flashes(); self.c.post(f'/invoice/{iid}/credit', data={'reason': 'ajustement', 'qty': '3.7', 'treatment': 'remboursement'})
        self.assertIn('Brouillon de note de crédit créé', ' '.join(self.flashes()))
