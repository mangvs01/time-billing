"""V9.2-rc8: Europe/Zurich display with UTC storage, and security hardening (synthetic data only, on a COPY of the
staging database; see test_import.py for the run command). No secret value is ever printed by these tests.

Time  stored timestamps stay UTC; screens and documents show Europe/Zurich (CET/CEST switched automatically); the
      business day (invoice date, future/backdated rule, refund dates) is the Zurich day
Sec   fail-closed secret checks, session cookie flags, login throttling, cross-site refusal, response headers
"""
import json, os, re, sqlite3, subprocess, sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import app.app as m
from app import billing_rules as rules, security
from tests.test_credit_settlement import Settlement
from tests.test_functional import pdf_text
from tests._app_facts import APP_ROOT

STRONG = 'k' * 40


class FixedNow(datetime):
    """datetime whose now() is a fixed UTC instant (converted to the requested zone)."""
    instant = datetime(2026, 10, 3, 22, 30, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


class ZurichDisplay(Settlement):
    def test_dst_switches_and_midnight(self):
        cases = {
            '2026-01-15T12:00:00': '15.01.2026 à 13:00:00',   # winter, CET = UTC+1
            '2026-07-15T12:00:00': '15.07.2026 à 14:00:00',   # summer, CEST = UTC+2
            '2026-03-29T00:59:59': '29.03.2026 à 01:59:59',   # last second of winter time
            '2026-03-29T01:00:00': '29.03.2026 à 03:00:00',   # 02:00 local does not exist: jump to 03:00
            '2026-10-25T00:59:59': '25.10.2026 à 02:59:59',   # last second of summer time
            '2026-10-25T01:00:00': '25.10.2026 à 02:00:00',   # 02:00-03:00 local happens twice
            '2026-10-03T22:30:00': '04.10.2026 à 00:30:00',   # already the next day in Zurich
            '2026-12-31T23:30:00': '01.01.2027 à 00:30:00',   # and the next year
            '2026-10-03 22:30:00': '04.10.2026 à 00:30:00',   # SQLite CURRENT_TIMESTAMP form (UTC)
            '2026-10-03': '03.10.2026',                       # a calendar day is never shifted
        }
        for raw, shown in cases.items(): self.assertEqual(rules.fr_ts(raw), shown, raw)
        self.assertEqual(rules.local_date('2026-10-03T22:30:00'), '2026-10-04')
        self.assertEqual(rules.local_date('2026-10-03'), '2026-10-03')
        # the two 02:30 of 25.10.2026 stay distinguishable through their UTC value (title / datetime)
        a, b = m.ts_html('2026-10-25T00:30:00'), m.ts_html('2026-10-25T01:30:00')
        self.assertIn('>25.10.2026 à 02:30:00<', a); self.assertIn('>25.10.2026 à 02:30:00<', b)
        self.assertIn('datetime="2026-10-25T00:30:00Z"', a); self.assertIn('title="UTC 2026-10-25T01:30:00"', b)

    def test_storage_stays_utc_whatever_the_container_tz(self):
        old = os.environ.get('TZ')
        try:
            os.environ['TZ'] = 'America/New_York'; import time; time.tzset()
            got = datetime.fromisoformat(rules.utc_now_iso()); ref = datetime.now(timezone.utc).replace(tzinfo=None)
            self.assertLess(abs((ref - got).total_seconds()), 5)
        finally:
            if old is None: os.environ.pop('TZ', None)
            else: os.environ['TZ'] = old
            time.tzset()

    def frozen(self, instant):
        FixedNow.instant = instant; self._orig = rules.datetime; rules.datetime = FixedNow
        self.addCleanup(lambda: setattr(rules, 'datetime', self._orig))

    def test_business_day_is_zurich_day_around_midnight(self):
        """22:30 UTC on 03.10.2026 = 00:30 on 04.10.2026 in Zurich."""
        self.frozen(datetime(2026, 10, 3, 22, 30, tzinfo=timezone.utc))
        self.assertEqual(rules.local_today(), date(2026, 10, 4))
        self.entry(self.pid, '2026-10-02', 8)
        # default date = Zurich day; issued_at = UTC instant
        iid, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1); self.issue(iid, confirm_backdate=False, derogate=(13,))
        row = self.sql('SELECT status,invoice_date,issued_at FROM invoices WHERE id=?', (iid,))[0]
        self.assertEqual((row['status'], row['invoice_date'], row['issued_at']), ('issued', '2026-10-04', '2026-10-03T22:30:00'))
        archive = self.c.get('/?tab=archive').get_data(as_text=True)
        self.assertIn('émise le <time datetime="2026-10-03T22:30:00Z" title="UTC 2026-10-03T22:30:00">04.10.2026 à 00:30:00</time></small>', archive)
        self.assertNotIn('(antidatée)', archive.split('2026-1</td>')[1].split('</tr>')[0])

    def test_future_and_backdated_rules_on_zurich_day(self):
        self.frozen(datetime(2026, 10, 3, 22, 30, tzinfo=timezone.utc))
        self.entry(self.pid, '2026-10-02', 8)
        fut, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1, invoice_date='2026-10-05')
        self.flashes(); self.issue(fut, derogate=(13,))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (fut,)), 'draft')
        self.assertIn('postérieure au jour d\'émission (04.10.2026)', ' '.join(self.flashes()))
        self.c.post(f'/invoice/{fut}/delete')
        # 03.10 is the UTC day but already yesterday in Zurich: backdated, confirmation required
        back, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1, invoice_date='2026-10-03')
        self.issue(back, confirm_backdate=False, derogate=(13,))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (back,)), 'draft')
        self.issue(back, derogate=(13,))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (back,)), 'issued')
        self.assertIn('backdated=confirmed', self.scalar("SELECT detail FROM audit WHERE event='invoice_issued' ORDER BY id DESC LIMIT 1"))

    def test_refund_due_date_and_credit_pdf_from_zurich_day(self):
        self.frozen(datetime(2026, 10, 3, 22, 30, tzinfo=timezone.utc))
        cid, fl = self.credit(qty='0.5', treatment='remboursement', refund_delay_days='10'); self.issue_cn(cid)
        self.assertEqual(self.scalar('SELECT issued_at FROM credit_notes WHERE id=?', (cid,)), '2026-10-03T22:30:00')
        self.assertEqual(self.scalar('SELECT refund_due_on FROM credit_notes WHERE id=?', (cid,)), '2026-10-14')
        t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        self.assertIn('Date :\n04.10.2026', t); self.assertIn('au plus tard le 14.10.2026', ' '.join(t.split()))


class SecretsConfig(Settlement):
    def env(self, **kw):
        base = {'APP_PASSWORD': 'Mot-de-passe-test-solide', 'SECRET_KEY': STRONG}
        base.update(kw); return {k: v for k, v in base.items() if v is not None}

    def test_fail_closed_without_leaking_values(self):
        bad = [dict(SECRET_KEY=None), dict(SECRET_KEY='court'), dict(SECRET_KEY='replace-with-long-random-secret'),
               dict(APP_PASSWORD=None), dict(APP_PASSWORD='change-me-now'), dict(APP_PASSWORD='trop-court'),
               dict(APP_PASSWORD='X' * 40, SECRET_KEY='X' * 40), dict(APP_PASSWORD=None, APP_PASSWORD_HASH='md5$abc')]
        for kw in bad:
            e = self.env(**kw)
            with self.assertRaises(security.ConfigError) as cm: security.load(e)
            for v in e.values():
                if len(v) >= 8: self.assertNotIn(v, str(cm.exception), 'a secret value appears in the error')

    def test_hash_preferred_and_accepted(self):
        from werkzeug.security import generate_password_hash
        cfg = security.load({'APP_PASSWORD_HASH': generate_password_hash('Une phrase de passe fictive'), 'SECRET_KEY': STRONG})
        self.assertIsNone(cfg['pw'])
        self.assertTrue(security.credentials_ok(cfg, 'admin', 'Une phrase de passe fictive'))
        self.assertFalse(security.credentials_ok(cfg, 'admin', 'autre'))
        self.assertFalse(security.credentials_ok(cfg, 'root', 'Une phrase de passe fictive'))

    def test_process_refuses_to_start_with_weak_config(self):
        secret = 'valeur-secrete-qui-ne-doit-pas-fuir'
        env = dict(os.environ, SECRET_KEY=secret, APP_PASSWORD=secret, DB_PATH=os.path.join(self.tmp, 'x.db'))
        r = subprocess.run([sys.executable, '-c', 'import app.app'], cwd=APP_ROOT, env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('SECRET_KEY identique au mot de passe', r.stderr)
        self.assertNotIn(secret, r.stdout + r.stderr)

    def test_cookie_policy(self):
        cfg = security.cookie_config(security.load(self.env()))       # default: HTTPS-only cookie
        self.assertEqual((cfg['SESSION_COOKIE_HTTPONLY'], cfg['SESSION_COOKIE_SECURE'], cfg['SESSION_COOKIE_SAMESITE']), (True, True, 'Lax'))
        self.assertEqual(cfg['PERMANENT_SESSION_LIFETIME'], timedelta(hours=8))
        self.assertFalse(security.cookie_config(security.load(self.env(COOKIE_SECURE='0')))['SESSION_COOKIE_SECURE'])
        anon = m.APP.test_client()
        r = anon.post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
        cookie = r.headers['Set-Cookie']
        self.assertTrue(cookie.startswith('tb_session=')); self.assertIn('HttpOnly', cookie); self.assertIn('SameSite=Lax', cookie); self.assertIn('Expires=', cookie)

    def test_session_renewed_at_login(self):
        anon = m.APP.test_client()
        with anon.session_transaction() as s: s['planted'] = 'x'
        anon.post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
        with anon.session_transaction() as s: self.assertNotIn('planted', s); self.assertTrue(s.get('auth'))


class AccessControls(Settlement):
    def login_as(self, client, pw, ip='203.0.113.7'):
        return client.post('/login', data={'username': m.SEC['user'], 'password': pw}, environ_base={'REMOTE_ADDR': ip})

    def test_throttling_per_ip_without_recording_secrets(self):
        anon = m.APP.test_client(); wrong = 'mauvais-mot-de-passe-fictif'
        for _ in range(security.MAX_FAILURES): self.assertEqual(self.login_as(anon, wrong).status_code, 200)
        r = self.login_as(anon, os.environ['APP_PASSWORD'])                 # even the right password is refused now
        self.assertEqual(r.status_code, 429); self.assertIn('Trop de tentatives', r.get_data(as_text=True))
        self.assertEqual(self.login_as(anon, os.environ['APP_PASSWORD'], ip='198.51.100.9').status_code, 302)  # other client unaffected
        audit = ' '.join(r[0] for r in self.sql("SELECT detail FROM audit WHERE event LIKE 'login_%'"))
        self.assertNotIn(wrong, audit); self.assertNotIn(os.environ['APP_PASSWORD'], audit); self.assertIn('ip=203.0.113.7', audit)
        c = sqlite3.connect(self.db); c.execute("UPDATE login_failures SET at='2000-01-01T00:00:00'"); c.commit(); c.close()
        self.assertEqual(self.login_as(anon, os.environ['APP_PASSWORD']).status_code, 302)   # window elapsed
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM login_failures WHERE ip='203.0.113.7'"), 0)

    def test_cross_site_state_change_refused(self):
        n = self.scalar('SELECT COUNT(*) FROM projects')
        form = {'name': 'Mandat intrus', 'rate': '1', 'day_hours': '8'}
        self.assertEqual(self.c.post('/project', data=form, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.c.post('/project', data=form, headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM projects'), n)
        self.assertEqual(self.c.post('/project', data=form, headers={'Origin': 'http://localhost'}).status_code, 302)  # same origin
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM projects'), n + 1)

    def test_security_headers_and_no_cache(self):
        for url in ('/?tab=archive', f'/invoice/{self.iid}.pdf'):
            r = self.c.get(url)
            for h in ('Content-Security-Policy', 'X-Frame-Options', 'X-Content-Type-Options', 'Referrer-Policy'): self.assertIn(h, r.headers, url)
            self.assertIn("frame-ancestors 'none'", r.headers['Content-Security-Policy'])
            self.assertEqual(r.headers['Cache-Control'], 'no-store', url)
        r = m.APP.test_client().get('/login'); self.assertNotIn('no-store', r.headers.get('Cache-Control', ''))

    def test_secrets_absent_from_pages_and_backup(self):
        pw, key = os.environ['APP_PASSWORD'], os.environ['SECRET_KEY']
        for url in ('/?tab=settings', '/?tab=archive', '/health', '/backup'):
            body = self.c.get(url).get_data(as_text=True)
            self.assertNotIn(pw, body, url); self.assertNotIn(key, body, url)
