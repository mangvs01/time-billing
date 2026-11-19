"""V9.2-rc14: integration of the « Liquid Glass » design (synthetic data only, on a COPY of the staging database).
The design must add presentation only: every existing screen keeps working, the new cards show figures that come from the application logic,
the stylesheet stays CSP-safe (no external resource) and no business wording is changed."""
import html as htmllib, re

from tests.test_credit_settlement import Settlement
from tests.test_v92 import V92
import app.app as m

TEMPLATES = m.APP.root_path + '/templates'


def read(name): return open(f'{TEMPLATES}/{name}', encoding='utf8').read()


class Shell(Settlement):
    def page(self, url): return self.c.get(url).get_data(as_text=True)

    def test_sidebar_on_every_authenticated_screen(self):
        cid = self.issued_cn(amount='100', treatment='remboursement')
        for url in ('/', '/entries', f'/entry/{self.scalar("SELECT MIN(id) FROM entries")}/edit', f'/credit/{cid}', f'/invoice/{self.iid}/credit', f'/project/{self.pid}/edit'):
            t = self.page(url)
            self.assertIn('<aside class="sidebar">', t, url); self.assertIn('Time Billing V9.2', t, url)
            self.assertIn('Déconnexion', t, url); self.assertIn('<main class="main', t, url)
            for label in ('Tableau de bord', 'Saisie des heures', 'Factures et brouillons', 'Import historique'): self.assertIn(label, t, (url, label))  # B-8 (2026-10-20)

    def test_wording_of_navigation_unchanged(self):
        t = self.page('/')
        labels = re.findall(r'data-tab="(\w+)"[^>]*>([^<]+)<', t)
        self.assertEqual([k for k, _ in labels], ['dashboard', 'time', 'mandates', 'billing', 'archive', 'migration', 'settings'])
        self.assertEqual([htmllib.unescape(v) for _, v in labels], ['Tableau de bord', 'Saisie des heures', 'Mandats & prévisionnel', 'Édition des factures', 'Factures et brouillons', 'Import historique', 'Paramètres & sauvegardes'])  # B-8 (2026-10-20)

    def test_login_page_is_styled_and_complete(self):
        c = m.APP.test_client(); t = c.get('/login').get_data(as_text=True)
        self.assertIn('class="loginbox"', t); self.assertIn('name="username"', t); self.assertIn('name="password"', t)
        self.assertNotIn(m.VERSION, t); self.assertEqual(c.get('/health').get_json()['version'], m.VERSION)   # B-7 (2026-10-20): no exact version on the public page, kept on /health

    def test_dashboard_cards_come_from_application_figures(self):
        t = self.page('/')
        self.assertIn('class="kpis"', t)
        k = self.sql('SELECT COUNT(*) FROM invoices WHERE status=?', ('draft',))[0][0]
        self.assertRegex(t, r'Brouillons en attente</span><span class="k-value">%d<' % k)
        self.assertIn('class="ringcard"', t); self.assertIn('Réalisé', t)
        # the invoiced amount of the year shown on the card is the forecast figure (same source as the forecast table)
        fig = re.search(r'Facturé \d{4}</span><span class="k-value">([^<]+)<', t).group(1)
        norm = lambda x: re.sub(r'\s', '', x)
        self.assertIn(norm(fig), norm(htmllib.unescape(t[t.index('Prévisions par année civile'):])))

    def test_ring_is_bounded_and_absent_without_progress(self):
        pid = self.mandate(name='Mandat sans saisie', rate='500', vat='0', ordered='10')
        t = self.page('/')
        card = re.search(r'<div class="ringcard">(?:(?!</div>\s*</div>).)*Mandat sans saisie.*?</div>', t, re.S).group(0)
        self.assertIn('0%', card); self.assertNotIn('class="ring real"', card); self.assertNotIn('class="ring bill"', card)
        for v in re.findall(r'stroke-dasharray="([\d.]+) 400"', t): self.assertLessEqual(float(v), 296)

    def test_archive_badges_and_search_box(self):
        self.issued_cn(amount='100', treatment='remboursement')
        t = self.page('/')
        self.assertIn('badge b-issued', t); self.assertIn('id="archiveSearch"', t); self.assertIn('id="archiveTable"', t)
        self.assertIn('class="subrow"', t)

    def test_forecast_chart_is_drawn_from_forecast_months(self):
        from app import billing_rules as rules
        today = rules.local_today()
        self.mandate(name='Mandat prévisionnel', rate='500', ordered='30', start=today.replace(day=1).isoformat(), months='6', legal_id='CHE-000.000.077')
        t = self.page('/'); t = t[t.index('Prévisions par année civile'):t.index('Détail des mandats')]
        months = len(re.findall(r'<td>\d{4}-\d{2}</td>', t))
        self.assertGreater(months, 0)
        self.assertEqual(len(re.findall(r'<rect class="bar"', t)), months)              # one bar per forecast month, none invented
        self.assertGreaterEqual(len(re.findall(r'<svg class="fchart"', t)), 1)


class Stylesheet(V92):
    def test_design_system_is_csp_safe(self):
        css = read('_ds.html')
        self.assertNotIn('@import', css)
        urls = re.findall(r'url\(\s*["\']?([^"\')]+)', css)
        for u in urls: self.assertTrue(u.startswith('data:') or u.startswith('#'), u)       # only data: URIs and local gradients
        self.assertNotIn('http://fonts', css); self.assertNotIn('https://', css)
        self.assertNotIn('<script', css)

    def test_accessibility_fallbacks_present(self):
        css = read('_ds.html')
        for needle in ('prefers-reduced-motion', 'prefers-reduced-transparency', '@supports not', ':focus-visible'): self.assertIn(needle, css)

    def test_breakpoints_for_tablet_and_phone(self):
        css = read('_ds.html')
        self.assertIn('max-width:1100px', css); self.assertIn('max-width:760px', css)

    def test_every_template_loads_the_design_system(self):
        for name in ('index.html', 'entries.html', 'entry_edit.html', '_page.html', 'login.html', 'import_review.html'):
            self.assertIn('_ds.html', read(name), name)
