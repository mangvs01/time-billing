"""V9.2-rc11: management of time entries (list, filters, export, correction, deletion, locks, history) and the
display fixes. Synthetic data only, on a COPY of the staging database (see test_import.py for the run command).

Rules under test
E1  a manual entry can be listed, corrected and deleted; each correction / deletion keeps the previous value in an append-only history
E2  (rc19) no entry is locked: invoiced, imported or of a closed mandate, it stays editable; the issued invoice never changes
E3  refused input is never guessed or corrected (NaN, bad times, > 24 h, tiny durations, long text, unknown or closed mandate)
E4  list: filters, escaping, pagination, totals, CSV export without formula injection
E5  open redirect and cross-site requests are refused; anonymous access redirects to the login
"""
import csv, html, io, json, re, sqlite3
from datetime import date

import app.app as m
from app import billing_rules as rules
from tests.test_v92 import V92
from tests._app_facts import declared_version


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N (year of the invoice date = today's year, then the sequence of the year)


def text(r): return r.get_data(as_text=True)


class EntryCase(V92):
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat Saisies', rate='800', vat='8.1', ordered='20')
        self.pid2 = self.mandate(name='Second Mandat', rate='500', vat='0', ordered='5', legal_id='CHE-000.000.002')

    def eid(self, desc):
        return self.scalar('SELECT id FROM entries WHERE description=?', (desc,))

    def edit(self, eid, **kw):
        row = self.sql('SELECT * FROM entries WHERE id=?', (eid,))[0]
        data = {'work_date': row['work_date'], 'project_id': str(row['project_id']), 'entry_mode': 'duration', 'manual_hours': str(row['hours']),
                'description': row['description']}
        data.update(kw)
        self.flashes(); r = self.c.post(f'/entry/{eid}/edit', data=data)
        return r, self.msgs(r)

    def delete(self, eid, **kw):
        self.flashes(); r = self.c.post(f'/entry/{eid}/delete', data=kw)
        return r, self.msgs(r)

    def msgs(self, r):
        # a refused edit re-renders the form (the messages are consumed by the page); an accepted one redirects
        return ' '.join(self.flashes()) + (' ' + html.unescape(r.get_data(as_text=True)) if r.status_code == 200 else '')

    def changes(self, eid=None):
        return self.sql('SELECT * FROM entry_changes' + (' WHERE entry_id=?' if eid else '') + ' ORDER BY id', (eid,) if eid else ())


class CorrectAndDelete(EntryCase):
    def test_correct_a_manual_entry_keeps_history(self):
        self.entry(self.pid, '2026-09-10', 3.5, 'avant')
        e = self.eid('avant')
        r, fl = self.edit(e, work_date='2026-09-11', manual_hours='4.25', description='après', project_id=str(self.pid2))
        self.assertEqual(r.status_code, 302); self.assertIn('modifiée', fl)
        row = self.sql('SELECT * FROM entries WHERE id=?', (e,))[0]
        self.assertEqual((row['work_date'], row['project_id'], row['hours'], row['description'], row['start_time']), ('2026-09-11', self.pid2, 4.25, 'après', ''))
        ch = self.changes(e); self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0]['action'], 'update')
        before, after = json.loads(ch[0]['before_json']), json.loads(ch[0]['after_json'])
        self.assertEqual((before['work_date'], before['hours'], before['description'], before['project']), ('2026-09-10', 3.5, 'avant', 'Mandat Saisies'))
        self.assertEqual((after['work_date'], after['hours'], after['description'], after['project']), ('2026-09-11', 4.25, 'après', 'Second Mandat'))
        self.assertIn('time_entry_updated', [a['event'] for a in self.sql('SELECT event FROM audit')])
        # the position follows the correction (3.5 h left the first mandate, 4.25 h joined the second)
        c = m.db()
        try:
            self.assertEqual(m.contract(c, c.execute('SELECT * FROM projects WHERE id=?', (self.pid,)).fetchone())['consumed_hours'], 0)
            self.assertEqual(m.contract(c, c.execute('SELECT * FROM projects WHERE id=?', (self.pid2,)).fetchone())['consumed_hours'], 4.25)
        finally: c.close()

    def test_switch_between_clock_and_duration_modes(self):
        self.entry(self.pid, '2026-09-10', 2, 'x')
        e = self.eid('x')
        r, fl = self.edit(e, entry_mode='clock', start_time='08:30', end_time='12:15', manual_hours='')
        row = self.sql('SELECT * FROM entries WHERE id=?', (e,))[0]
        self.assertEqual((row['start_time'], row['end_time'], row['hours']), ('08:30', '12:15', 3.75))
        r, fl = self.edit(e, entry_mode='duration', manual_hours='1,5', start_time='', end_time='')
        row = self.sql('SELECT * FROM entries WHERE id=?', (e,))[0]
        self.assertEqual((row['start_time'], row['end_time'], row['hours']), ('', '', 1.5))
        self.assertEqual(len(self.changes(e)), 2)

    def test_identical_save_writes_nothing(self):
        self.entry(self.pid, '2026-09-10', 2, 'x'); e = self.eid('x')
        r, fl = self.edit(e)
        self.assertIn('Aucune modification', fl); self.assertEqual(self.changes(), [])

    def test_refused_input_changes_nothing(self):
        self.entry(self.pid, '2026-09-10', 2, 'x'); e = self.eid('x')
        snap = tuple(self.sql('SELECT * FROM entries WHERE id=?', (e,))[0])
        bad = [dict(manual_hours='nan'), dict(manual_hours='inf'), dict(manual_hours='-1'), dict(manual_hours='0'), dict(manual_hours='0.001'),
               dict(manual_hours='24.01'), dict(manual_hours='abc'), dict(manual_hours=''), dict(work_date='2026-13-40'), dict(work_date=''),
               dict(entry_mode='clock', start_time='12:00', end_time='12:00'),
               dict(entry_mode='clock', start_time='8:3', end_time='9:00'), dict(entry_mode='clock', start_time='25:00', end_time='26:00'),
               dict(entry_mode='clock', start_time='', end_time='09:00'), dict(entry_mode='clock', start_time='08:00', end_time=''),
               dict(entry_mode='other'), dict(description='x' * 1001), dict(project_id='99999'), dict(project_id='abc')]
        for kw in bad:
            r, fl = self.edit(e, **kw)
            self.assertIn('non modifiée', fl, kw)
            if kw.get('manual_hours') in ('nan', 'inf'): self.assertIn('durée invalide', fl, kw)     # refused by the rule itself, not by a database constraint
            self.assertEqual(tuple(self.sql('SELECT * FROM entries WHERE id=?', (e,))[0]), snap, kw)
        self.assertEqual(self.changes(), [])

    def test_creation_validations_share_the_same_rules(self):
        for kw in (dict(manual_hours='nan'), dict(manual_hours='0.001'), dict(manual_hours='abc'), dict(description='y' * 1001)):
            self.flashes()
            self.c.post('/entry', data=dict({'work_date': '2026-09-10', 'project_id': self.pid, 'entry_mode': 'duration', 'manual_hours': '2', 'description': 'z'}, **kw))
            self.assertIn('Saisie refusée', ' '.join(self.flashes()), kw)
        self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': self.pid, 'entry_mode': 'clock', 'start_time': '9:5', 'end_time': '10:00'})
        self.assertIn('format HH:MM', ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)

    def test_duration_mode_needs_no_start_end_and_clock_mode_needs_both(self):
        self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': self.pid, 'entry_mode': 'duration', 'manual_hours': '1.25', 'start_time': '', 'end_time': ''})
        self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': self.pid, 'entry_mode': 'clock', 'start_time': '10:00', 'end_time': '10:20'})
        self.assertEqual([(r['start_time'], r['end_time'], round(r['hours'], 9)) for r in self.sql('SELECT * FROM entries ORDER BY id')],
                         [('', '', 1.25), ('10:00', '10:20', round(1 / 3, 9))])

    def test_correction_to_a_closed_mandate_is_refused(self):
        self.entry(self.pid, '2026-09-10', 2, 'x'); e = self.eid('x')
        self.c.post(f'/project/{self.pid2}/close', data={'reason': 'test'})
        r, fl = self.edit(e, project_id=str(self.pid2))
        self.assertIn('clôturé', fl); self.assertEqual(self.scalar('SELECT project_id FROM entries WHERE id=?', (e,)), self.pid)

    def test_delete_keeps_a_full_copy(self):
        self.entry(self.pid, '2026-09-10', 2.5, 'à supprimer'); e = self.eid('à supprimer')
        r, fl = self.delete(e)
        self.assertEqual(r.status_code, 302); self.assertIn('supprimée', fl)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)
        ch = self.changes(e); self.assertEqual((len(ch), ch[0]['action'], ch[0]['after_json']), (1, 'delete', None))
        b = json.loads(ch[0]['before_json'])
        self.assertEqual((b['work_date'], b['hours'], b['description'], b['project']), ('2026-09-10', 2.5, 'à supprimer', 'Mandat Saisies'))
        self.assertIn('time_entry_deleted', [a['event'] for a in self.sql('SELECT event FROM audit')])
        r, fl = self.delete(e); self.assertIn('déjà supprimée', fl)            # second deletion: nothing to delete, nothing traced (rc19: says so)
        self.assertEqual(len(self.changes()), 1)

    def test_delete_and_edit_need_post(self):
        self.entry(self.pid, '2026-09-10', 2, 'x'); e = self.eid('x')
        self.assertEqual(self.c.get(f'/entry/{e}/delete').status_code, 405)
        self.assertEqual(self.c.get('/entry/99999/edit').status_code, 404)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM entries')[0][0], 1)

    def test_history_is_append_only_in_the_database(self):
        self.entry(self.pid, '2026-09-10', 2, 'x'); e = self.eid('x'); self.edit(e, manual_hours='3')
        c = sqlite3.connect(self.db)
        try:
            for q in ("UPDATE entry_changes SET action='delete'", "DELETE FROM entry_changes"):
                with self.assertRaises(sqlite3.DatabaseError): c.execute(q)
        finally: c.close()

    def test_draft_covering_the_date_is_flagged(self):
        self.entry(self.pid, '2026-09-10', 8, 'x'); e = self.eid('x')
        self.draft(self.pid, '2026-09-01', '2026-09-30', 1)
        r, fl = self.edit(e, manual_hours='6')
        self.assertIn('brouillon(s) de facture couvre', fl)
        r, fl = self.delete(e); self.assertIn('brouillon(s) de facture couvre', fl)


class Locks(EntryCase):
    """rc19 (user rule 2026-10-05): no entry is ever locked because it is old, imported, of a closed mandate or invoiced.
    The issued invoice stays immutable; a billed entry needs a reason and an explicit confirmation."""
    def setUp(self):
        super().setUp()
        self.entry(self.pid, '2026-09-10', 16, 'dans la facture')
        self.iid = self.issued(self.pid, '2026-09-01', '2026-09-30', 2)
        self.entry(self.pid, '2026-09-20', 4, 'ajout tardif')          # same period, added after issuance: not in the annex

    def test_entry_in_a_frozen_annex_is_editable_and_the_invoice_never_changes(self):
        e = self.eid('dans la facture')
        inv = tuple(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0])
        snap = tuple(self.sql('SELECT * FROM invoice_snapshots WHERE invoice_id=?', (self.iid,))[0])
        pdf = self.c.get(f'/invoice/{self.iid}.pdf').data
        r, fl = self.edit(e, manual_hours='15'); self.assertIn('motif obligatoire', fl)                 # reason required
        r, fl = self.edit(e, manual_hours='15', reason='durée réelle'); self.assertIn('cocher la confirmation', fl)
        self.assertEqual(self.scalar('SELECT hours FROM entries WHERE id=?', (e,)), 16); self.assertEqual(self.changes(), [])
        r, fl = self.edit(e, manual_hours='15', reason='durée réelle', confirm_billed='1')
        self.assertEqual(r.status_code, 302); self.assertIn('modifiée', fl); self.assertIn('Écart post-facturation', fl); self.assertIn('−1,00 h', fl)
        self.assertEqual(self.scalar('SELECT hours FROM entries WHERE id=?', (e,)), 15)
        self.assertEqual(tuple(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0]), inv)
        self.assertEqual(tuple(self.sql('SELECT * FROM invoice_snapshots WHERE invoice_id=?', (self.iid,))[0]), snap)
        self.assertEqual(self.c.get(f'/invoice/{self.iid}.pdf').data, pdf)
        ch = self.changes(e); self.assertEqual(len(ch), 1); self.assertEqual(ch[0]['reason'], 'durée réelle')
        self.assertEqual([x['role'] for x in json.loads(ch[0]['invoices_json'])], ['billed'])

    def test_late_entry_in_an_invoiced_period_stays_editable_with_a_warning(self):
        e = self.eid('ajout tardif')
        r, fl = self.edit(e, manual_hours='5'); self.assertIn('modifiée', fl); self.assertIn('période déjà facturée', fl)
        self.assertEqual(self.scalar('SELECT hours FROM entries WHERE id=?', (e,)), 5)
        r, fl = self.delete(e); self.assertIn('supprimée', fl)

    def test_imported_entry_is_editable_and_keeps_its_provenance(self):
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO import_batches(id,source_filename,status) VALUES('b1','x.xlsx','COMMITTED')")
        c.execute("INSERT INTO entries(work_date,project_id,hours,description,source,source_ref,import_batch_id) VALUES('2026-08-01',?,1,'importée','historical_excel','JAN!5','b1')", (self.pid,))
        c.commit(); c.close()
        e = self.eid('importée')
        r, fl = self.edit(e, manual_hours='2'); self.assertIn('modifiée', fl)
        row = self.sql('SELECT hours,source,source_ref,import_batch_id FROM entries WHERE id=?', (e,))[0]
        self.assertEqual(tuple(row), (2, 'historical_excel', 'JAN!5', 'b1'))
        r, fl = self.delete(e); self.assertIn('supprimée', fl)
        self.assertEqual([x['action'] for x in self.changes(e)], ['update', 'delete'])

    def test_closed_mandate_keeps_its_entries_editable(self):
        self.entry(self.pid2, '2026-09-10', 2, 'chez le second'); e = self.eid('chez le second')
        self.c.post(f'/project/{self.pid2}/close', data={'reason': 'fin'})
        r, fl = self.edit(e, manual_hours='3'); self.assertIn('modifiée', fl)
        self.assertEqual(self.scalar('SELECT hours FROM entries WHERE id=?', (e,)), 3)
        self.flashes(); self.c.post('/entry', data={'work_date': '2026-09-11', 'project_id': self.pid2, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'nouvelle'})
        self.assertIn('clôturé', ' '.join(self.flashes())); self.assertEqual(self.sql("SELECT id FROM entries WHERE description='nouvelle'"), [])
        r, fl = self.delete(e); self.assertIn('supprimée', fl)

    def test_edit_page_shows_no_lock(self):
        e = self.eid('dans la facture')
        page = text(self.c.get(f'/entry/{e}/edit'))
        self.assertNotIn('ne peut pas être modifiée', page); self.assertIn('Saisie déjà facturée', page)
        self.assertNotRegex(page, r'<(input|select|button)[^>]*\bdisabled\b')
        lst = text(self.c.get('/entries'))
        self.assertNotIn('verrouillée', lst); self.assertIn('facturée ', lst)


class ListAndExport(EntryCase):
    def setUp(self):
        super().setUp()
        for i in range(120):
            self.entry(self.pid if i % 2 else self.pid2, f'2026-0{1 + i % 9}-{1 + i % 27:02d}', 1 + (i % 4) * 0.25, f'saisie {i:03d}')
        self.entry(self.pid, '2026-05-05', 2, '100% sûr_ et "quoted"'); self.entry(self.pid, '2026-05-06', 2, '=HYPERLINK("http://x","y")')

    def test_pagination_and_totals(self):
        p1 = text(self.c.get('/entries')); self.assertIn('122</strong> saisie(s)', p1)
        self.assertIn('Page 1 / 3', p1); self.assertEqual(p1.count('data-entry='), 50)
        self.assertEqual(text(self.c.get('/entries?page=3')).count('data-entry='), 22)
        self.assertEqual(text(self.c.get('/entries?page=99')).count('data-entry='), 22)       # clamped
        self.assertEqual(text(self.c.get('/entries?page=abc')).count('data-entry='), 50)
        total = self.scalar('SELECT SUM(hours) FROM entries')
        self.assertIn(rules.fr_num(total) + ' h', p1.replace(' ', ' '))

    def test_filters(self):
        def n(q):
            return int(re.search(r'<strong>(\d+)</strong> saisie', text(self.c.get('/entries?' + q))).group(1))
        self.assertEqual(n(f'project={self.pid}'), 60 + 2)
        self.assertEqual(n(f'project={self.pid2}'), 60)
        self.assertEqual(n('date_from=2026-05-05&date_to=2026-05-06&project=' + str(self.pid)), self.scalar("SELECT COUNT(*) FROM entries WHERE project_id=? AND work_date BETWEEN '2026-05-05' AND '2026-05-06'", (self.pid,)))
        self.assertEqual(n('q=saisie 005'), 1)
        self.assertEqual(n('origin=import'), 0)
        self.assertEqual(n('origin=manual'), 122)
        self.assertEqual(n('project=abc&date_from=not-a-date&origin=zzz'), 122)               # malformed filters ignored, never guessed
        self.assertEqual(n('date_from=2026-02-30'), 122)

    def test_like_wildcards_are_literal(self):
        n = lambda q: text(self.c.get('/entries', query_string={'q': q})).count('data-entry=')
        self.assertEqual(n('100%'), 1); self.assertEqual(n('%'), 1); self.assertEqual(n('_'), 1); self.assertEqual(n('sûr_'), 1)
        self.assertEqual(n('saisie _05'), 0)

    def test_csv_export_matches_the_filter_and_neutralises_formulas(self):
        r = self.c.get(f'/entries.csv?project={self.pid}&q=HYPERLINK')
        self.assertEqual(r.status_code, 200); self.assertTrue(r.headers['Content-Type'].startswith('text/csv'))
        raw = r.get_data(as_text=True); self.assertTrue(raw.startswith('﻿'))
        rows = list(csv.reader(io.StringIO(raw.lstrip('﻿')), delimiter=';'))
        self.assertEqual(rows[0][:6], ['id', 'date', 'projet', 'debut', 'fin', 'heures']); self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][7], '\'=HYPERLINK("http://x","y")')
        full = list(csv.reader(io.StringIO(self.c.get('/entries.csv').get_data(as_text=True).lstrip('﻿')), delimiter=';'))
        self.assertEqual(len(full) - 1, 122)
        for row in full[1:]:
            for cell in row: self.assertFalse(cell[:1] in ('=', '+', '@', '\t', '\r'), cell)

    def test_list_html_escapes_descriptions(self):
        self.entry(self.pid, '2026-06-06', 1, '<script>alert(1)</script>')
        page = text(self.c.get('/entries?q=script'))
        self.assertNotIn('<script>alert(1)</script>', page); self.assertIn('&lt;script&gt;', page)

    def test_dashboard_and_time_tabs_offer_the_same_actions(self):
        for tab in ('dashboard', 'time'):
            page = text(self.c.get(f'/?tab={tab}'))
            self.assertIn('Dernières saisies', page); self.assertIn('/entry/', page); self.assertIn('Voir, filtrer, corriger', page)


class Safety(EntryCase):
    def test_anonymous_is_redirected(self):
        self.entry(self.pid, '2026-09-10', 2, 'x'); e = self.eid('x')
        anon = m.APP.test_client()
        for method, url in (('get', '/entries'), ('get', '/entries.csv'), ('get', f'/entry/{e}/edit'), ('post', f'/entry/{e}/edit'), ('post', f'/entry/{e}/delete')):
            r = getattr(anon, method)(url); self.assertEqual(r.status_code, 302, url); self.assertIn('/login', r.headers['Location'])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM entries')[0][0], 1)

    def test_return_to_cannot_leave_the_site(self):
        self.entry(self.pid, '2026-09-10', 2, 'x'); e = self.eid('x')
        for target in ('https://evil.example/', '//evil.example', '/\\evil', 'javascript:alert(1)', '/login'):
            r = self.c.post(f'/entry/{e}/edit', data={'work_date': '2026-09-10', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': '3',
                                                      'description': 'x', 'return_to': target})
            self.assertEqual(r.status_code, 302)
            loc = r.headers['Location']; self.assertTrue(loc.startswith('/entries') or loc.startswith('/?tab='), (target, loc))
            self.edit(e, manual_hours='2')

    def test_cross_site_post_is_refused(self):
        self.entry(self.pid, '2026-09-10', 2, 'x'); e = self.eid('x')
        r = self.c.post(f'/entry/{e}/delete', headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(r.status_code, 403); self.assertEqual(self.sql('SELECT COUNT(*) FROM entries')[0][0], 1)

    def test_sql_injection_in_filters_is_inert(self):
        self.entry(self.pid, '2026-09-10', 2, 'x')
        for q in ("' OR 1=1 --", "x'; DROP TABLE entries; --", '"; DELETE FROM entries; --'):
            self.assertEqual(self.c.get('/entries', query_string={'q': q, 'project': "1 OR 1=1", 'date_from': "2026-01-01'--"}).status_code, 200)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM entries')[0][0], 1)


class BackupRestore(EntryCase):
    def test_history_survives_backup_and_restore_and_cannot_be_dropped(self):
        self.entry(self.pid, '2026-09-10', 2, 'x'); e = self.eid('x'); self.edit(e, manual_hours='3'); self.delete(e)
        self.assertEqual(len(self.changes()), 2)
        raw = self.c.get('/backup').data
        data = json.loads(raw); self.assertEqual(len(data['tables']['entry_changes']), 2)
        # a backup that lacks the existing history is refused (append-only)
        data['tables']['entry_changes'] = data['tables']['entry_changes'][:1]
        c = m.db()
        try:
            import app.restore_service as rs
            pv = rs.preview(c, rs.validate(c, json.dumps(data).encode()))
        finally: c.close()
        self.assertTrue([b for b in pv['blocking'] if 'correction de saisie' in b], pv['blocking'])
        # an old backup without the table at all is refused too while history exists
        del data['tables']['entry_changes']
        c = m.db()
        try: pv = rs.preview(c, rs.validate(c, json.dumps(data).encode()))
        finally: c.close()
        self.assertTrue([b for b in pv['blocking'] if 'correction de saisie' in b])
        # the full backup restores to identical history
        good = json.loads(raw)
        c = m.db()
        try: self.assertEqual(rs.preview(c, rs.validate(c, raw))['blocking'], [])
        finally: c.close()
        self.assertEqual(good['tables']['entry_changes'][0]['action'], 'update')


class Display(V92):
    def test_hours_minutes_filter(self):
        f = rules.fr_hm
        self.assertEqual([f(3.5), f(0.7666666666666667), f(0.8000000000000007), f(0.0166667), f(8), f(0.25), f(24), f(None)],
                         ['3 h 30 min', '46 min', '48 min', '1 min', '8 h 00 min', '15 min', '24 h 00 min', ''])

    def test_no_mid_word_wrapping_rules_in_any_stylesheet(self):
        import os
        base = os.path.join(os.path.dirname(m.__file__), 'templates')
        for name in os.listdir(base):
            self.assertNotIn('overflow-wrap:anywhere', open(os.path.join(base, name), encoding='utf8').read(), name)

    def test_environment_label(self):
        page = text(self.c.get('/'))
        self.assertNotIn('envtag', page.split('<body>')[1].split('</header>')[0])
        old = m.ENV_LABEL
        try:
            m.ENV_LABEL = 'STAGING'
            self.assertIn('<span class="envtag">STAGING</span>', text(self.c.get('/')))
            self.assertIn('<span class="envtag">STAGING</span>', text(self.c.get('/entries')))
        finally: m.ENV_LABEL = old
        self.assertNotIn('RC staging', text(self.c.get('/')))

    def test_version_is_rc12(self):
        v = declared_version()                       # the version written in app/app.py (format 9.2-rcN checked there)
        self.assertEqual(m.VERSION, v); self.assertEqual(self.c.get('/health').get_json(), {'status': 'ok', 'version': v})


class Archive(V92):
    """Archive export: the frozen PDF of every issued document, an index and SHA-256 sums."""
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat Archive', rate='800', vat='8.1', ordered='20')
        self.entry(self.pid, '2026-08-10', 16); self.entry(self.pid, '2026-09-10', 8)
        self.i1 = self.issued(self.pid, '2026-08-01', '2026-08-31', 2)
        self.i2 = self.issued(self.pid, '2026-09-01', '2026-09-30', 1)
        self.draft(self.pid, '2026-10-01', '2026-10-31', 1)                       # a draft: never exported
        self.flashes()
        self.c.post(f'/invoice/{self.i1}/credit', data={'reason': 'test', 'qty': '0.5', 'treatment': 'remboursement'})
        self.cn = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{self.cn}/issue')
        self.c.post(f'/credit/{self.cn}/cancel', data={'reason': 'erreur'})

    def zip(self, qs=''):
        import zipfile
        r = self.c.get('/archive.zip' + qs); self.assertEqual(r.status_code, 200); self.assertEqual(r.mimetype, 'application/zip')
        return zipfile.ZipFile(io.BytesIO(r.data))

    def test_contents_are_the_frozen_bytes(self):
        import hashlib
        z = self.zip(); names = set(z.namelist())
        self.assertEqual(names, {f'factures/facture-{YEAR}-1.pdf', f'factures/facture-{YEAR}-2.pdf', f'notes-de-credit/note-de-credit-NC-{YEAR}-1.pdf',
                                 f'annulations/annulation-ANN-NC-{YEAR}-1.pdf', 'index.csv', 'SHA256SUMS', 'LISEZMOI.txt'})
        self.assertEqual(z.read(f'factures/facture-{YEAR}-1.pdf'), self.c.get(f'/invoice/{self.i1}.pdf').data)
        self.assertEqual(z.read(f'notes-de-credit/note-de-credit-NC-{YEAR}-1.pdf'), self.c.get(f'/credit/{self.cn}.pdf').data)
        self.assertEqual(z.read(f'annulations/annulation-ANN-NC-{YEAR}-1.pdf'), self.c.get(f'/credit/{self.cn}/cancellation.pdf').data)
        for line in z.read('SHA256SUMS').decode().strip().splitlines():
            digest, name = line.split('  '); self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), digest, name)
        self.assertNotIn('brouillon', ' '.join(names).lower())

    def test_index_lists_amounts_and_status(self):
        z = self.zip(); rows = list(csv.reader(io.StringIO(z.read('index.csv').decode().lstrip('﻿')), delimiter=';'))
        self.assertEqual(rows[0][:5], ['type', 'numero', 'date_document', 'emission_reelle_zurich', 'mandat'])
        by = {r[1]: r for r in rows[1:]}
        self.assertEqual(len(rows) - 1, 4)
        self.assertEqual((by[f'{YEAR}-1'][7], by[f'{YEAR}-1'][8], by[f'{YEAR}-1'][10]), ('1600.00', '129.60', '1729.60'))
        self.assertTrue(by[f'NC-{YEAR}-1'][11].startswith(f'annulée (ANN-NC-{YEAR}-1)')); self.assertEqual(by[f'NC-{YEAR}-1'][10], '-432.40')
        self.assertEqual(by[f'ANN-NC-{YEAR}-1'][0], 'annulation de note de crédit')

    def test_year_filter_and_invalid_year(self):
        today_year = str(rules.local_today().year)
        self.assertEqual(len([n for n in self.zip(f'?year={today_year}').namelist() if n.endswith('.pdf')]), 4)
        r = self.c.get('/archive.zip?year=1999'); self.assertEqual(r.status_code, 302)   # rc12 (QA-24): a year without document is refused with a message, no empty ZIP
        self.assertIn('Aucun document émis en 1999', ' '.join(self.flashes()))
        r = self.c.get('/archive.zip?year=20x6'); self.assertEqual(r.status_code, 302); self.assertIn('Année invalide', ' '.join(self.flashes()))

    def test_export_is_refused_when_a_stored_pdf_no_longer_matches_its_hash(self):
        c = sqlite3.connect(self.db)
        c.execute('DROP TRIGGER invoice_snapshot_no_update'); c.execute("UPDATE invoice_snapshots SET pdf=? WHERE invoice_id=?", (b'%PDF-forged', self.i1)); c.commit(); c.close()
        r = self.c.get('/archive.zip'); self.assertEqual(r.status_code, 302)
        self.assertIn('Archive non produite', ' '.join(self.flashes()))

    def test_anonymous_cannot_download(self):
        r = m.APP.test_client().get('/archive.zip'); self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])

    def test_link_on_the_archive_tab(self):
        self.assertIn('/archive.zip', text(self.c.get('/?tab=archive')))


class BackupReminder(V92):
    def test_settings_tab_states_the_last_backup_and_the_dashboard_no_longer_nags(self):
        # BSAV1: the permanent « Sauvegarde conseillée » line is gone from « À traiter » (monthly pop-up instead: tests.test_sauvegarde_rappel)
        self.assertNotIn('Sauvegarde conseillée', text(self.c.get('/')))
        pid = self.mandate(); self.entry(pid, '2026-09-10', 8); self.issued(pid, '2026-09-01', '2026-09-30', 1)
        page = text(self.c.get('/')); self.assertNotIn('Sauvegarde conseillée', page); self.assertNotIn('aucune sauvegarde JSON', page)
        self.assertIn('Aucune sauvegarde téléchargée à ce jour', page)
        self.c.get('/backup')
        page = text(self.c.get('/')); self.assertNotIn('Sauvegarde conseillée', page); self.assertIn('Dernière sauvegarde téléchargée', page)
        c = sqlite3.connect(self.db); c.execute("DROP TRIGGER audit_no_update"); c.execute("UPDATE audit SET created_at='2026-01-01 10:00:00' WHERE event='json_backup_exported'"); c.commit(); c.close()  # rc13: test-only back-dating
        self.assertNotIn('Sauvegarde conseillée', text(self.c.get('/')))                 # even stale: only the monthly pop-up at login speaks now
