"""rc35 (BILLING-THÈME, owner feedback 24.10: « je ne vois pas le petit bouton qui permet de changer de thème ; par défaut on avait opté pour le thème sombre ! »).

Display only: the dark « graphite » theme is the default on every page (sign-in page included), a small switch (sidebar header on a computer, « Plus » menu
on a phone, sign-in page) flips to light; the choice is kept in the browser (localStorage « tb-theme ») and applied in <head> before any stylesheet, by a
script signed with the response's CSP nonce. No billing, VAT, rounding, check or numbering rule is touched; PDFs are drawn by reportlab and do not use
these templates. Synthetic data only (see test_import.py); tests/browser/recette-theme.js covers the rendering (contrasts, no light first paint).
"""
import glob, os, re

import app.app as m
from tests.test_ux_lot2 import Base2

TEMPLATES = os.path.join(os.path.dirname(m.__file__), 'templates')
DARK_MARK = '/* ---------- rc35 : thème sombre « graphite »'
W = ':where([data-theme=dark]) '


def read(name):
    with open(os.path.join(TEMPLATES, name), encoding='utf-8') as f: return f.read()


def rules(css):
    """(selector list, declarations) of every style rule, at-rule blocks (@media, @supports) unwrapped; comments removed."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S); out, stack, start = [], [], 0
    for i, ch in enumerate(css):
        if ch == '{': stack.append(css[start:i].strip()); start = i + 1
        elif ch == '}':
            head = stack.pop() if stack else ''
            if not head.startswith('@'): out.append(([s.strip() for s in head.split(',')], css[start:i]))
            start = i + 1
    return out


class DefaultDark(Base2):
    def pages(self):
        pid, iid = self.issued(name='Mandat thème')
        self.entry(pid, '2026-10-01', 4)
        did, _ = self.draft(pid, '2026-10-01', '2026-10-31', 0.5, invoice_date='2026-10-31')
        eid = self.scalar('SELECT MAX(id) FROM entries')
        return ['/', '/calendrier', '/?tab=time', '/?tab=archive', '/?tab=settings', '/entries', f'/entry/{eid}/edit', f'/project/{pid}/edit', f'/issue/{did}', f'/invoice/{iid}/credit', f'/invoice/{did}/edit']

    def test_every_page_opens_dark_and_applies_the_saved_choice_before_the_stylesheets(self):
        anon = m.APP.test_client()
        for client, url in [(anon, '/login')] + [(self.c, u) for u in self.pages()]:
            r = client.get(url); t = r.get_data(as_text=True)
            self.assertEqual(r.status_code, 200, url)
            self.assertTrue(t.startswith('<!doctype html><html lang="fr" data-theme="dark"><head>'), url)            # dark without any script
            head = t[:t.index('</head>')]
            js = head.index("var d=document.documentElement,K='tb-theme'")
            self.assertLess(js, head.index('<style>'), url)                                                       # before the first rule is parsed
            nonce = re.search(r"'nonce-([^']+)'", r.headers['Content-Security-Policy']).group(1)
            tag = head[head.rindex('<script', 0, js):js]
            self.assertEqual(tag, f'<script nonce="{nonce}">(function(){{', url)

    def test_every_html_template_carries_the_default_and_the_head_script(self):
        heads = [f for f in glob.glob(f'{TEMPLATES}/*.html') if '<!doctype' in read(os.path.basename(f))]
        self.assertEqual(sorted(os.path.basename(f) for f in heads), ['_page.html', 'calendrier.html', 'entries.html', 'entry_edit.html', 'import_review.html', 'index.html', 'login.html'])
        for f in heads:
            s = read(os.path.basename(f))
            self.assertIn('<html lang="fr" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{% include "_theme_head.html" %}', s, f)
            self.assertLess(s.index('_theme_head.html'), s.index('<style>'), f)

    def test_saved_choice_rules(self):
        js = read('_theme_head.html')
        self.assertIn("function apply(t){d.setAttribute('data-theme',t==='light'?'light':'dark')}", js)          # only an explicit « light » leaves the default
        self.assertIn("try{apply(localStorage.getItem(K))}catch(e){apply(null)}", js)                             # storage blocked: dark, no script error
        self.assertIn("try{localStorage.setItem(K,t)}catch(x){}", js)
        self.assertNotRegex(js, r'\bon[a-z]+=')                                                                   # delegated listener, no inline handler


class Switch(Base2):
    def test_header_switch_on_a_computer_and_in_the_more_menu_on_a_phone(self):
        for url in ('/', '/entries', f'/project/{self.mandate(name="Mandat bascule")}/edit'):
            page = self.c.get(url).get_data(as_text=True)
            brand = page[page.index('<div class="brand">'):page.index('<nav class="tabs"')]
            self.assertIn('<button type="button" class="themetoggle" data-theme-toggle aria-pressed="true" title="Passer au thème clair"><span class="vh">Thème sombre</span></button>', brand, url)
            menu = page[page.index('<div class="navmenu" id="navMoreMenu" hidden>'):]; menu = menu[:menu.index('</div>')]
            self.assertIn('<button type="button" class="themetoggle-m" data-theme-toggle aria-pressed="true" title="Passer au thème clair">Thème sombre</button><form method="post" action="/logout"', menu, url)
        css = read('_ds.html')
        self.assertIn('@media (max-width:760px){.sidebar .brand button.themetoggle{display:none}', css)          # phone: the switch lives in « Plus »
        self.assertIn('.navmore,.navmenu,.sidebar .tabs .navmore{display:none}', css)                            # computer: no « Plus » menu

    def test_sign_in_page_switch_comes_after_the_form(self):
        t = m.APP.test_client().get('/login').get_data(as_text=True)
        self.assertEqual(re.findall(r'<button[^>]*>', t)[0], '<button>')                                         # the first button is still « Connexion »
        self.assertIn('</form><button type="button" class="themetoggle login-theme" data-theme-toggle aria-pressed="true" title="Passer au thème clair"><span class="vh">Thème sombre</span></button></main>', t)


class Stylesheet(Base2):
    def test_dark_theme_lives_in_the_design_system_loaded_by_every_page(self):
        css = read('_ds.html'); dark = css[css.index(DARK_MARK):]
        self.assertIn('@media screen{\nhtml[data-theme=dark]{color-scheme:dark;', dark)                            # printing an HTML page stays light
        self.assertNotIn('html[data-theme=dark] ', read('_style.html'))                                           # one dark theme only (_page.html never loaded _style.html)
        self.assertNotRegex(css, r'\{#')

    def test_every_colour_token_has_a_dark_value(self):
        css = read('_ds.html')
        light = set(re.findall(r'(--[\w-]+):', css[css.index(':root{'):css.index('}', css.index(':root{'))]))
        block = css[css.index('html[data-theme=dark]{'):]; dark = set(re.findall(r'(--[\w-]+):', block[:block.index('}')]))
        missing = light - dark - {'--r-panel', '--r-ctl', '--ease', '--t', '--f'}                                   # shapes, motion and fonts are shared
        self.assertEqual(missing, set())

    def test_every_hard_coded_light_rule_has_its_dark_mirror(self):
        """A light rule with a literal white surface or a literal dark text colour would stay light in the dark theme: each one needs
        « :where([data-theme=dark]) <same selector> » (same specificity, later in the sheet)."""
        css = read('_ds.html'); i = css.index(DARK_MARK)
        dark = {s for sel, _ in rules(css[i:]) for s in sel}
        light_surface = re.compile(r'background(-color)?:[^;]*(#fff\b|rgba\(255,255,255,\.[4-9]|rgba\(250,251,253)')
        dark_text = re.compile(r'(^|;)\s*color:\s*(#7a1d17|#5f3a00|#0b5a3d|#a3281f|#1d2a35)')
        exempt = {'.brand .logo', '.fab', 'a.btn.primary', 'a.btn.primary:hover', 'a.btn.danger', 'a.btn.danger:hover', 'button'}   # coloured action surfaces, mirrored by colour
        missing = []
        for sel, body in rules(css[:i]):
            if light_surface.search(body) or dark_text.search(body):
                missing += [s for s in sel if s not in exempt and W + s not in dark]
        self.assertEqual(missing, [])
        for s in exempt - {'.brand .logo'}: self.assertIn(W + s, dark, s)

    def test_action_colour_meets_aa_with_white_text(self):
        def lum(h):
            c = [int(h[k:k + 2], 16) / 255 for k in (1, 3, 5)]
            c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        css = read('_ds.html'); tok = dict(re.findall(r'(--[\w-]+):(#[0-9a-f]{6})', css[css.index('html[data-theme=dark]{'):]))
        ratio = lambda a, b: (max(lum(a), lum(b)) + .05) / (min(lum(a), lum(b)) + .05)
        self.assertGreaterEqual(ratio(tok['--accent'], '#ffffff'), 4.5)
        for t in ('--ink', '--ink-2', '--ink-3', '--blue', '--ok', '--warn', '--err'):
            self.assertGreaterEqual(ratio(tok[t], tok['--glass']), 4.5, t)                                       # on the panel surface
            self.assertGreaterEqual(ratio(tok[t], tok['--raised']), 4.5, t)                                      # on cards, inputs' neighbours


class Version(Base2):
    def test_version_candidate(self):
        self.assertGreaterEqual(int(m.VERSION.rsplit('rc', 1)[1]), 35)   # theme is in rc35 and later (rc36: calendar)
        self.assertEqual(self.c.get('/health').get_json()['version'], m.VERSION)
