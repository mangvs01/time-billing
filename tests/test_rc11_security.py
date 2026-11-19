"""V9.2-rc11: content-security-policy without 'unsafe-inline' for scripts, POST-only logout, no inline event handler left.
Synthetic data only, on a COPY of the staging database (see test_import.py for the run command).
"""
import glob, os, re

import app.app as m
from tests.test_v92 import V92

TEMPLATES = os.path.join(os.path.dirname(m.__file__), 'templates')


def text(r): return r.get_data(as_text=True)


class Csp(V92):
    def csp(self, path='/'):
        r = self.c.get(path); return r.headers['Content-Security-Policy'], text(r)

    def test_script_src_has_no_unsafe_inline_but_a_nonce(self):
        h, _ = self.csp()
        script = [d for d in h.split(';') if d.strip().startswith('script-src')][0]
        self.assertNotIn('unsafe-inline', script); self.assertRegex(script, r"'nonce-[A-Za-z0-9_-]{16,}'")

    def test_every_inline_script_carries_the_nonce_of_this_response(self):
        for path in ('/', '/entries', '/?tab=migration'):
            h, body = self.csp(path); nonce = re.search(r"'nonce-([^']+)'", h).group(1)
            tags = re.findall(r'<script\b[^>]*>', body)
            self.assertTrue(tags, path)
            for t in tags: self.assertIn(f'nonce="{nonce}"', t, (path, t))

    def test_nonce_changes_on_every_request(self):
        self.assertNotEqual(self.csp()[0], self.csp()[0])

    def test_login_page_and_errors_also_carry_the_policy(self):
        anon = m.APP.test_client()
        for path in ('/login', '/inexistant'):
            self.assertIn("script-src 'self' 'nonce-", anon.get(path).headers['Content-Security-Policy'])

    def test_no_template_has_an_inline_event_handler_or_javascript_url(self):
        for f in glob.glob(f'{TEMPLATES}/*.html'):
            s = open(f, encoding='utf-8').read()
            self.assertIsNone(re.search(r'\son[a-z]+\s*=\s*["\']', s), f)
            self.assertNotIn('javascript:', s.lower(), f)

    def test_confirmation_prompts_moved_to_data_attributes(self):
        body = text(self.c.get('/'))
        self.assertNotIn('onsubmit', body)
        pid = self.scalar('SELECT MIN(id) FROM projects WHERE active=1')                          # UX lot 2 (R-7): the close prompt lives on the mandate page
        edit = text(self.c.get(f'/project/{pid}/edit'))
        self.assertIn('data-confirm="', edit); self.assertNotIn('onsubmit', edit)

    def test_injected_text_in_a_confirmation_cannot_break_out_of_the_attribute(self):
        # the old sink: a value placed inside onsubmit="return confirm('…{{value}}…')" ; now plain attribute text, never evaluated
        hostile = "'+alert(1)+'\"><script>alert(2)</script>"
        from jinja2 import Environment
        out = Environment(autoescape=True).from_string('<form data-confirm="Annuler {{v}} ?"></form>').render(v=hostile)
        self.assertNotIn('<script>', out); self.assertIn('&#34;&gt;&lt;script&gt;', out)   # quote and angle brackets escaped: the attribute cannot be closed


class Logout(V92):
    def test_get_logout_does_not_sign_out(self):
        r = self.c.get('/logout'); self.assertEqual(r.status_code, 302); self.assertEqual(r.headers['Location'], '/')
        self.assertEqual(self.c.get('/').status_code, 200)

    def test_post_logout_signs_out_and_a_cross_site_post_is_refused(self):
        r = self.c.post('/logout', headers={'Origin': 'https://evil.example'}); self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.get('/').status_code, 200)
        r = self.c.post('/logout'); self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])
        self.assertEqual(self.c.get('/').status_code, 302)

    def test_navbar_offers_a_post_form_not_a_link(self):
        body = text(self.c.get('/'))
        self.assertIn('action="/logout"', body); self.assertNotIn('href="/logout"', body)
