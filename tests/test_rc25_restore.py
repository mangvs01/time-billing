"""RC25 phase 2 (TB-05): restore safety. Synthetic data only, on a throw-away copy of the base DB (see tests/test_import.py).

An amputated backup (missing business table), a backup whose rows do not match meta.row_counts, and a restore that fails at the
rebuild stage are refused WITHOUT changing anything; a successful restore never replaces the current append-only audit log.
"""
import io, json, os, sqlite3

import app.app as m
from app import restore_service as rs
from tests.test_v92 import V92


class RestoreSafety(V92):
    def dump(self):
        r = self.c.get('/backup'); self.assertEqual(r.status_code, 200); return json.loads(r.data)

    def upload(self, data):
        r = self.c.post('/restore', data={'backup': (io.BytesIO(json.dumps(data).encode()), 'sauvegarde.json')}, content_type='multipart/form-data')
        loc = r.headers.get('Location', '')
        return loc.rsplit('/', 1)[-1] if '/restore/' in loc else None

    def everything(self):
        """Every row of every table, audit included (the comparison proves a refusal wrote nothing at all)."""
        tables = [t[0] for t in self.sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: [tuple(r) for r in self.sql(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}

    def audit(self):
        return [tuple(r) for r in self.sql('SELECT id,event,detail,created_at FROM audit ORDER BY id')]

    def world(self):
        """Three plain entries (no issued invoice: nothing else protects them) plus one issued invoice."""
        pid = self.mandate(name='Mandat restauration')
        for d in ('2026-08-03', '2026-08-04', '2026-08-05'): self.entry(pid, d, 8, f'saisie {d}')
        self.entry(pid, '2026-09-10', 8, 'saisie facturée')
        self.issued(pid, '2026-09-01', '2026-09-30', 1)
        return pid

    def refused_without_change(self, data, needle):
        """Upload → the preview is blocked with `needle` → a confirmed commit is refused → the database is identical, row for row."""
        token = self.upload(data); self.assertIsNotNone(token, self.flashes())
        page = self.c.get(f'/restore/{token}').get_data(as_text=True)
        self.assertIn('Restauration bloquée', page); self.assertIn(needle, page)
        before = self.everything(); self.flashes()
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        self.assertTrue(any('base inchangée' in f and needle in f for f in self.flashes()))
        self.assertEqual(self.everything(), before)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 4)
        self.c.post(f'/restore/{token}', data={'action': 'cancel'})

    def test_backup_without_a_business_table_is_refused_and_destroys_nothing(self):
        self.world(); good = self.dump()
        for t in ('entries', 'projects', 'audit', 'settings'):
            d = json.loads(json.dumps(good)); d['tables'].pop(t)                       # cut out, still declared in meta.row_counts
            self.refused_without_change(d, f'table {t} déclarée')
            d['meta']['row_counts'].pop(t)                                             # cut out of the declaration as well
            self.refused_without_change(d, f'table métier {t} absente')

    def test_row_count_mismatch_is_refused_and_destroys_nothing(self):
        self.world(); good = self.dump()
        self.assertEqual(good['meta']['row_counts']['entries'], 4)
        d = json.loads(json.dumps(good)); d['tables']['entries'] = [r for r in d['tables']['entries'] if r['description'] != 'saisie 2026-08-04']
        self.refused_without_change(d, 'entries : 3 ligne(s) pour 4 déclarée(s)')
        d = json.loads(json.dumps(good)); d['meta']['row_counts']['entries'] = 5
        self.refused_without_change(d, 'entries : 4 ligne(s) pour 5 déclarée(s)')
        d = json.loads(json.dumps(good)); d['meta']['row_counts'].pop('entries')
        self.refused_without_change(d, 'entries : nombre de lignes non déclaré')
        for bad in (None, [], {'entries': '4'}, {'entries': True}, {'entries': -1}):
            d = json.loads(json.dumps(good)); d['meta']['row_counts'] = bad if not isinstance(bad, dict) else dict(good['meta']['row_counts'], **bad)
            if bad is None: d['meta'].pop('row_counts')
            self.refused_without_change(d, 'meta.row_counts')

    def test_backup_older_than_a_table_is_accepted_only_while_that_table_is_empty(self):
        self.world(); good = self.dump()
        d = json.loads(json.dumps(good))                                               # a faithful pre-rc19 file: no table, no count, no CREATE
        d['tables'].pop('invoice_variance_decisions'); d['meta']['row_counts'].pop('invoice_variance_decisions')
        d['meta']['schema'] = [s for s in d['meta']['schema'] if 'invoice_variance_decisions' not in s]
        con = m.db()
        try: self.assertEqual(rs.preview(con, rs.validate(con, json.dumps(d).encode()))['blocking'], [])
        finally: con.close()
        no_schema = json.loads(json.dumps(d)); no_schema['meta'].pop('schema')       # the file's own schema is unknown: no exemption
        con = m.db()
        try: self.assertTrue([b for b in rs.preview(con, rs.validate(con, json.dumps(no_schema).encode()))['blocking'] if 'table métier invoice_variance_decisions absente' in b])
        finally: con.close()
        iid = self.scalar("SELECT id FROM invoices WHERE status='issued'")             # the current table now holds a decision
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO invoice_variance_decisions(invoice_id,decision,variance_hours,fingerprint,reason,decided_at) VALUES(?,?,?,?,?,?)",
                  (iid, 'aucune', 0, 'test', 'écart accepté (test)', '2026-10-01T10:00:00')); c.commit(); c.close()
        token = self.upload(d); page = self.c.get(f'/restore/{token}').get_data(as_text=True)
        self.assertIn('invoice_variance_decisions absente', page); self.assertIn('Restauration bloquée', page)

    def test_restore_keeps_the_current_audit_log_verbatim(self):
        self.world(); good = self.dump()
        m.log('evenement_apres_sauvegarde', 'doit survivre à la restauration')         # audit written after the backup was taken
        self.c.get('/backup')
        current = self.audit()
        forged = json.loads(json.dumps(good))
        forged['tables']['audit'][0]['detail'] = 'réécrit par le fichier'               # same id, different content: must not replace the current row
        forged['tables']['audit'].append({'id': 999999, 'event': 'ligne_du_fichier', 'detail': 'absente de la base', 'created_at': '2026-01-01 00:00:00'})
        forged['meta']['row_counts']['audit'] = len(forged['tables']['audit'])
        token = self.upload(forged); self.flashes()
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        self.assertIn('Restauration effectuée', ' '.join(self.flashes()))
        after = self.audit()
        self.assertEqual(after[:len(current)], current)                               # every current row, same id, same content
        tail = [(e, d) for _, e, d, _ in after[len(current):]]
        self.assertIn(('ligne_du_fichier', 'absente de la base'), tail)               # the file's own rows are appended, never substituted
        self.assertIn('réécrit par le fichier', [d for _, _, d, _ in after[len(current):]])
        self.assertNotIn(999999, [x[0] for x in after])
        self.assertEqual(after[-1][1], 'json_restored'); self.assertIn('audit_kept=', after[-1][2])
        c = sqlite3.connect(self.db)
        with self.assertRaises(sqlite3.DatabaseError): c.execute('DELETE FROM audit')   # still append-only after the rebuild
        c.close()

    def test_identical_backup_restores_without_duplicating_the_audit(self):
        self.world(); good = self.dump(); current = self.audit()
        token = self.upload(good); self.flashes()
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        self.assertIn('Restauration effectuée', ' '.join(self.flashes()))
        after = self.audit()
        self.assertEqual(after[:len(current)], current)
        self.assertEqual([e for _, e, _, _ in after[len(current):]], ['restore_previewed', 'json_restored'])
        self.assertIn('audit_appended=0', after[-1][2])

    def test_failure_at_rebuild_stage_is_non_destructive(self):
        self.world(); good = self.dump()
        d = json.loads(json.dumps(good))                                                # plain entry of an unknown mandate: only the rebuilt FK check sees it
        orphan = dict(next(r for r in d['tables']['entries'] if r['description'] == 'saisie 2026-08-03'), id=987654, project_id=424242)
        d['tables']['entries'].append(orphan); d['meta']['row_counts']['entries'] += 1
        token = self.upload(d); page = self.c.get(f'/restore/{token}').get_data(as_text=True)
        self.assertNotIn('Restauration bloquée', page)
        before = self.everything(); self.flashes()
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        fl = ' '.join(self.flashes()); self.assertIn('base inchangée', fl); self.assertIn('clé étrangère', fl)
        after = self.everything()
        self.assertEqual({t: v for t, v in after.items() if t != 'audit'}, {t: v for t, v in before.items() if t != 'audit'})
        self.assertEqual(after['audit'], before['audit'])
        self.assertFalse([f for f in os.listdir(self.tmp) if '.restore-' in f])        # no rebuilt file left behind
        self.integrity()

    def test_rebuild_itself_refuses_a_count_that_contradicts_meta(self):
        self.world(); good = self.dump(); good['meta']['row_counts']['entries'] = 9
        tmp = rs.temp_path(self.db)
        try:
            with self.assertRaises(rs.RestoreRefused): rs.rebuild(tmp, good, m.init, keep_from=self.db)
        finally:
            if os.path.exists(tmp): os.remove(tmp)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 4)
