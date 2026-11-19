"""V9.2-rc10: fixes from the independent security audit (SEC-01 … SEC-15). Synthetic data only, on a COPY of the
staging database (see test_import.py for the run command). Each test reproduces the audited scenario and checks the fix.
"""
import base64, io, json, os, sqlite3, stat, struct, zlib
from datetime import timedelta

import app.app as m
from app import restore_service as rs, security
from tests.test_credit_settlement import Settlement
from tests.test_import import workbook, HEADER
from tests.test_v92 import V92


def text(r): return r.get_data(as_text=True)


class RestoreImmutability(Settlement):
    """SEC-01: a restore may not alter an issued document, its frozen copy, its annex or the append-only histories."""

    def backup(self): return json.loads(self.c.get('/backup').data)

    def blocking(self, data):
        c = m.db()
        try: return rs.preview(c, rs.validate(c, json.dumps(data).encode()))['blocking']
        finally: c.close()

    def test_untouched_backup_is_accepted(self):
        self.assertEqual(self.blocking(self.backup()), [])

    def test_changed_quantity_of_an_issued_invoice_is_refused(self):
        d = self.backup()
        for r in d['tables']['invoices']:
            if r['status'] == 'issued': r['qty'] = 99; r['unit_rate'] = 1
        b = self.blocking(d); self.assertTrue([x for x in b if x.startswith('invoices ') and 'qty' in x], b)

    def test_changed_frozen_header_or_pdf_of_an_invoice_is_refused(self):
        d = self.backup(); d['tables']['invoice_snapshots'][0]['header_json'] = d['tables']['invoice_snapshots'][0]['header_json'].replace('Client', 'Pirate')
        b = self.blocking(d); self.assertTrue([x for x in b if x.startswith('invoice_snapshots ') and 'header_json' in x], b)
        d = self.backup(); fake = b'%PDF-1.4 fake'; r = d['tables']['invoice_snapshots'][0]
        r['pdf'] = base64.b64encode(fake).decode(); r['pdf_sha256'] = __import__('hashlib').sha256(fake).hexdigest()   # consistent fake: hash recomputed
        self.assertTrue(self.blocking(d))

    def test_forged_credit_note_pdf_with_recomputed_hash_is_refused(self):
        cid = self.issued_cn(qty='0.5', treatment='remboursement')
        d = self.backup(); fake = b'%PDF-1.4 forged'
        for r in d['tables']['credit_note_snapshots']:
            if r['credit_note_id'] == cid: r['pdf'] = base64.b64encode(fake).decode(); r['pdf_sha256'] = __import__('hashlib').sha256(fake).hexdigest()
        self.assertTrue([x for x in self.blocking(d) if x.startswith('credit_note_snapshots')])

    def test_emptied_annex_and_changed_entry_of_an_issued_invoice_are_refused(self):
        d = self.backup(); d['tables']['invoice_annex_entries'] = []
        self.assertTrue([x for x in self.blocking(d) if x.startswith('invoice_annex_entries')])
        d = self.backup()
        annexed = {r['entry_id'] for r in d['tables']['invoice_annex_entries']}
        for r in d['tables']['entries']:
            if r['id'] in annexed: r['hours'] = 1
        # rc19: an invoiced entry may be corrected, never without its history: the hand-edited file carries no correction row
        self.assertTrue([x for x in self.blocking(d) if 'sans correction tracée' in x], self.blocking(d))

    def test_ordinary_work_after_the_backup_is_not_blocked(self):
        d = self.backup()
        for r in d['tables']['projects']: r['client'] = 'Autre nom'                  # mandates and plain entries are editable data
        self.assertEqual(self.blocking(d), [])

    def test_malformed_backups_are_refused_cleanly(self):
        c = m.db()
        try:
            for payload in ({'meta': {'app_version': '9.2'}, 'tables': {'entries': ['x']}},
                            {'meta': {'app_version': '9.2'}, 'tables': {'entries': [{'id': {'a': 1}}]}},
                            {'meta': {'app_version': '9.2'}, 'tables': {'entries': [[1, 2]]}}):
                with self.assertRaises(rs.RestoreRefused): rs.validate(c, json.dumps(payload).encode())
            with self.assertRaises(rs.RestoreRefused): rs.validate(c, b'[' * 100000)           # deep nesting: RecursionError becomes a refusal
        finally: c.close()
        r = self.c.post('/restore', data={'backup': (io.BytesIO(b'{"meta":{"app_version":"9.2"},"tables":{"entries":["x"]}}'), 'b.json')}, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 302); self.assertIn('Restauration impossible', ' '.join(self.flashes()))


class Session(V92):
    def test_open_redirect_variants_after_login(self):
        for nxt in ('/\t/evil.example', '//evil.example', '/\\evil.example', 'https://evil.example', '/ok\r\nSet-Cookie: x=1', '/\x7f/x'):
            c = m.APP.test_client()
            r = c.post('/login?next=' + __import__('urllib.parse', fromlist=['quote']).quote(nxt, safe='/:'), data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
            self.assertEqual((r.status_code, r.headers['Location']), (302, '/'), nxt)
        c = m.APP.test_client()
        r = c.post('/login?next=/?tab=billing', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
        self.assertEqual(r.headers['Location'], '/?tab=billing')

    def test_logout_revokes_a_copied_cookie(self):
        cookie = self.c.get_cookie('tb_session').value
        self.assertEqual(self.c.get('/').status_code, 200)
        thief = m.APP.test_client(); thief.set_cookie('tb_session', cookie)
        self.assertEqual(thief.get('/').status_code, 200)                       # a valid copy works until logout
        self.c.post('/logout')
        r = thief.get('/'); self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM web_sessions')[0][0], 0)

    def test_session_has_an_absolute_lifetime(self):
        old = (m.rules.utc_now() - timedelta(hours=m.SESSION_MAX_HOURS + 1)).isoformat(timespec='seconds')
        c = sqlite3.connect(self.db); c.execute('UPDATE web_sessions SET created_at=?', (old,)); c.commit(); c.close()
        r = self.c.get('/'); self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])

    def test_forged_cookie_without_server_session_is_refused(self):
        c = sqlite3.connect(self.db); c.execute('DELETE FROM web_sessions'); c.commit(); c.close()
        self.assertEqual(self.c.get('/').status_code, 302)

    def test_two_logins_are_independent(self):
        other = m.APP.test_client(); other.post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
        self.c.post('/logout'); self.assertEqual(other.get('/').status_code, 200)


class Throttle(V92):
    def test_ipv6_addresses_of_one_network_share_a_counter(self):
        self.assertEqual(security.client_key('2001:db8:1:2:aaaa:bbbb:cccc:dddd'), security.client_key('2001:db8:1:2::1'))
        self.assertNotEqual(security.client_key('2001:db8:1:2::1'), security.client_key('2001:db8:1:3::1'))
        self.assertEqual(security.client_key('::ffff:203.0.113.9'), '203.0.113.9'); self.assertEqual(security.client_key('203.0.113.9'), '203.0.113.9')
        self.assertEqual(security.client_key('garbage'), 'garbage'); self.assertEqual(security.client_key(None), '?')

    def test_rotating_ipv6_inside_a_network_does_not_reset_the_limit(self):
        for i in range(security.MAX_FAILURES):
            anon = m.APP.test_client()
            anon.post('/login', data={'username': 'admin', 'password': 'faux'}, environ_overrides={'REMOTE_ADDR': f'2001:db8:9:9::{i + 1}'})
        r = m.APP.test_client().post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']}, environ_overrides={'REMOTE_ADDR': '2001:db8:9:9::ffff'})
        self.assertEqual(r.status_code, 429)
        r = m.APP.test_client().post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']}, environ_overrides={'REMOTE_ADDR': '2001:db8:9:a::1'})
        self.assertEqual(r.status_code, 302)                                      # another network is not affected

    def test_a_bot_hammering_a_locked_login_adds_one_audit_row_per_window(self):
        def throttled_rows(prefix):
            c = m.db()
            try: return c.execute("SELECT COUNT(*) FROM audit WHERE event='login_throttled' AND detail LIKE ?", (f'ip={prefix}%',)).fetchone()[0]
            finally: c.close()
        bad = {'username': 'admin', 'password': 'faux'}
        for ip in ('198.51.100.77', '2001:db8:77:1::1'):
            for _ in range(security.MAX_FAILURES): m.APP.test_client().post('/login', data=bad, environ_overrides={'REMOTE_ADDR': ip})
        codes = {m.APP.test_client().post('/login', data=bad, environ_overrides={'REMOTE_ADDR': ip}).status_code
                 for ip in ['198.51.100.77'] * 30 + [f'2001:db8:77:1::{i:x}' for i in range(2, 32)]}
        self.assertEqual(codes, {429})                                            # the lock itself is unchanged
        self.assertEqual(throttled_rows('198.51.100.77'), 1)
        self.assertEqual(throttled_rows('2001:db8:77:1:'), 1)                    # rotating inside the /64 counts as one client
        for _ in range(security.MAX_FAILURES): m.APP.test_client().post('/login', data=bad, environ_overrides={'REMOTE_ADDR': '198.51.100.78'})
        m.APP.test_client().post('/login', data=bad, environ_overrides={'REMOTE_ADDR': '198.51.100.78'})
        self.assertEqual(throttled_rows('198.51.100.78'), 1)                     # another client still gets its own row

    def test_login_body_is_small_and_refused_before_reading(self):
        # behind the proxy buffer (80-site-caddy.sh: request_buffers 64KB), a larger body announced to /login is refused on its
        # Content-Length alone: a client sending it drop by drop can no longer hold one of the 16 server threads
        env = {'REMOTE_ADDR': '198.51.100.90'}
        r = m.APP.test_client().post('/login', data={'username': 'admin', 'password': 'x' * (m.LOGIN_MAX_BODY + 1)}, environ_overrides=env)
        self.assertEqual(r.status_code, 413); self.assertIn('connexion', text(r))
        r = m.APP.test_client().post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD'], 'pad': 'x' * 8000}, environ_overrides=env)
        self.assertEqual(r.status_code, 302)                                      # an ordinary login form is far below the limit
        self.assertLess(m.LOGIN_MAX_BODY, 64 * 1024)


class Headers(V92):
    def test_hsts_only_over_https_and_permissions_policy(self):
        http = self.c.get('/health'); self.assertNotIn('Strict-Transport-Security', http.headers)
        https = self.c.get('/health', base_url='https://localhost'); self.assertIn('max-age=', https.headers['Strict-Transport-Security'])
        self.assertIn('camera=()', http.headers['Permissions-Policy'])

    def test_origin_null_and_foreign_origin_refused_on_state_changes(self):
        self.mandate()
        for hdr in ({'Origin': 'null'}, {'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            r = self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': '1', 'entry_mode': 'duration', 'manual_hours': '1'}, headers=hdr)
            self.assertEqual(r.status_code, 403, hdr)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM entries')[0][0], 0)
        r = self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': '1', 'entry_mode': 'duration', 'manual_hours': '1'}, headers={'Origin': 'http://localhost'})
        self.assertEqual(r.status_code, 302)                                      # same origin still works

    def test_backup_and_staging_files_are_private(self):
        self.mandate(); self.entry(1, '2026-09-10', 2)
        r = self.c.post('/import', data={'workbook': (io.BytesIO(workbook({'SEPT': [('10.09.2026', 'x', 'Projet Alpha', '09:00', '10:00', 1)]})), 'a.xlsx')}, content_type='multipart/form-data')
        token = r.headers['Location'].rsplit('/', 1)[-1]
        mode = stat.S_IMODE(os.stat(m.stage_path(token)).st_mode); self.assertEqual(mode & 0o077, 0, oct(mode))


class Inputs(V92):
    def mandate_raw(self, **kw):
        data = {'name': 'Mandat X', 'rate': '650', 'day_hours': '8', 'vat': '8.1', 'ordered_days': '10', 'duration_months': '12'}; data.update(kw)
        self.flashes(); self.c.post('/project', data=data); return ' '.join(self.flashes())

    def test_non_finite_and_absurd_mandate_values_are_refused(self):
        for kw in (dict(rate='nan'), dict(rate='inf'), dict(rate='1e308'), dict(vat='nan'), dict(vat='101'), dict(ordered_days='1e12'), dict(day_hours='25'),
                   dict(day_hours='0'), dict(duration_months='2000000'), dict(name='x' * 201), dict(rate='-1')):
            self.assertIn('non enregistré', self.mandate_raw(**kw), kw)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM projects WHERE name=?', ('Mandat X',))[0][0], 0)
        self.assertIn('enregistré', self.mandate_raw()); self.assertEqual(self.c.get('/').status_code, 200)

    def test_logo_decompression_bomb_is_refused_without_decoding(self):
        def png(w, h):
            raw = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
            return b'\x89PNG\r\n\x1a\n' + raw(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0)) + raw(b'IDAT', zlib.compress(b'\0' * (h * (w + 1)) if w * h < 10 ** 6 else b'\0')) + raw(b'IEND', b'')
        for w, h in ((13000, 13000), (3000, 3000)):
            self.flashes(); self.c.post('/settings', data={'issuer_name': 'x', 'logo': (io.BytesIO(png(w, h)), 'l.png')}, content_type='multipart/form-data')
            self.assertIn('logo illisible ou trop grand', ' '.join(self.flashes()), (w, h))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM settings WHERE key='logo_png_b64'")[0][0], 0)

    def test_workbook_row_limit(self):
        rows = [('01.09.2026', 'x', 'Projet Alpha', '09:00', '09:15', 0.25)] * 20001
        wb = workbook({'SEPT': rows})
        r = self.c.post('/import', data={'workbook': (io.BytesIO(wb), 'big.xlsx')}, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 302); self.assertIn('/?tab=migration', r.headers['Location'])
        self.assertIn('plus de 20000 lignes', ' '.join(self.flashes()))


class Errors(V92):
    def test_unexpected_error_never_shows_internal_details(self):
        original = m.forecast_mod.build
        def boom(*a, **k): raise RuntimeError('SELECT secret FROM hidden_table')
        m.forecast_mod.build = boom
        m.APP.config['PROPAGATE_EXCEPTIONS'] = False
        try:
            r = self.c.get('/'); self.assertEqual(r.status_code, 500)
            self.assertNotIn('hidden_table', text(r)); self.assertIn('Erreur interne', text(r))
        finally: m.forecast_mod.build = original
        self.assertEqual(self.c.get('/').status_code, 200)

    def test_huge_ids_and_control_characters_do_not_crash(self):
        for url in ('/entry/99999999999999999999/edit', '/credit/99999999999999999999', '/invoice/99999999999999999999.pdf'):
            self.assertEqual(self.c.get(url).status_code, 404, url)
        self.mandate(); self.entry(1, '2026-09-10', 2); e = self.sql('SELECT id FROM entries')[0][0]
        r = self.c.post(f'/entry/{e}/edit', data={'work_date': '2026-09-10', 'project_id': '1', 'entry_mode': 'duration', 'manual_hours': '3', 'description': 'x', 'return_to': '/entries\r\nX-Evil: 1'})
        self.assertEqual(r.status_code, 302); self.assertEqual(r.headers['Location'], '/entries')

    def test_entries_with_invalid_dates_do_not_crash(self):
        for q in ('date_from=2026-02-30', 'date_to=zzz', 'date_from=2026-13-01&date_to=x'):
            self.assertEqual(self.c.get('/entries?' + q).status_code, 200, q)

    def test_stored_batch_counter_cannot_inject_script(self):
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO import_batches(id,source_filename,status,inserted_rows) VALUES('b1','x.xlsx','COMMITTED',?)", ("1');alert(document.cookie);//",))
        c.commit(); c.close()
        page = text(self.c.get('/?tab=migration'))
        self.assertNotIn("1');alert", page)                                       # never raw inside the onsubmit JavaScript
        self.assertIn("retirer ses 0 prestation(s)", page)
