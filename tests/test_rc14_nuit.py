"""V9.2-rc14, night session: presentation refinements of the « Liquid Glass » design (synthetic data only, on a COPY of the staging database).
Each test pins a visible behaviour added during the night; none of them changes a figure, a label or a route."""
import re
from datetime import datetime, timedelta

from tests.test_credit_settlement import Settlement
import app.app as m


class DetailPagesShell(Settlement):
    def page(self, url): return self.c.get(url).get_data(as_text=True)

    def test_environment_tag_on_every_authenticated_screen(self):
        cid = self.issued_cn(amount='100', treatment='remboursement')
        old = m.ENV_LABEL; m.ENV_LABEL = 'ESSAI'
        try:
            for url in ('/', '/entries', f'/credit/{cid}', f'/invoice/{self.iid}/credit', f'/project/{self.pid}/edit'):
                self.assertIn('<span class="envtag">ESSAI</span>', self.page(url), url)
        finally:
            m.ENV_LABEL = old

    def test_sidebar_marks_the_section_of_a_detail_page(self):
        cid = self.issued_cn(amount='100', treatment='remboursement')
        active = lambda t: re.findall(r'<a href="/\?tab=(\w+)"[^>]*class="active" aria-current="page"', t)
        self.assertEqual(active(self.page(f'/credit/{cid}')), ['archive'])
        self.assertEqual(active(self.page(f'/invoice/{self.iid}/credit')), ['archive'])
        self.assertEqual(active(self.page(f'/project/{self.pid}/edit')), ['mandates'])
        self.assertEqual(active(self.page('/entries')), ['time'])


class DashboardHierarchy(Settlement):
    def page(self, url): return self.c.get(url).get_data(as_text=True)

    def test_primary_card_meter_matches_the_forecast_table(self):
        from app import billing_rules as rules
        today = rules.local_today()
        self.mandate(name='Mandat prévisionnel nuit', rate='500', ordered='30', start=today.replace(day=1).isoformat(), months='6', legal_id='CHE-000.000.078')
        t = self.page('/')
        total = re.search(r'Total estimé (\d{4}) : <b>([^<]+)</b>', t)
        self.assertIsNotNone(total)
        year, shown = total.groups()
        self.assertEqual(year, str(today.year))
        table = re.search(r'Total estimé %s</b></td><td><b>([^<]+)</b>' % year, t).group(1)
        self.assertEqual(shown, table)                                     # same figure as the forecast table, no recomputation
        a, b = (int(x) for x in re.search(r'Facturé (\d+) %</span><span><i class="lg plan"></i>Prévision restante (\d+) %', t).groups())
        self.assertIn(a + b, (99, 100, 101))                               # rounding only
        self.assertEqual(len(re.findall(r'class="kpi(?: primary)?"', t)), 5)                         # still five cards

    def test_ring_card_shows_contract_balance_on_its_own_line(self):
        t = self.page('/')
        self.assertRegex(t, r'<small class="rest">Solde contractuel : <b>[−\-0-9 ,]+ j</b></small>')


class MandateBalances(Settlement):
    def page(self, url): return self.c.get(url).get_data(as_text=True)

    def panel(self, t): return t[t.index('class="panel p-balances"'):][:t[t.index('class="panel p-balances"'):].index('</section>')]

    def test_one_bar_per_active_mandate_with_application_figures(self):
        closed = self.mandate(name='Mandat clos nuit', rate='500', ordered='10', legal_id='CHE-000.000.079')
        self.c.post(f'/project/{closed}/close', data={'reason': 'fin'})
        t = self.page('/?tab=mandates'); p = self.panel(t)
        active = [str(r[0]) for r in self.sql('SELECT id FROM projects WHERE active=1 ORDER BY id')]
        self.assertEqual(p.count('<div class="bal" '), len(active))                                   # one bar block per active mandate, nothing else
        self.assertEqual(sorted(re.findall(r'<div class="bal" id="mandat-(\d+)" data-pid="\1">', p), key=int), active)   # exactly the active ones (anchor = id)
        self.assertNotIn('Mandat clos nuit', p)
        # the balance written under the bar is the one of the « Détail des mandats » table (same source, no recomputation)
        for bal in re.findall(r'Solde contractuel <b>([^<]+) j</b>', p):
            self.assertIn('<td>%s</td>' % bal, t[t.index('Détail des mandats'):])

    def test_panel_respects_the_recette_invariants(self):
        t = self.page('/')
        self.assertLess(t.index('Détail des mandats'), t.index('class="panel p-balances"'))       # forecast-chart section boundaries unchanged
        p = self.panel(t)
        self.assertNotRegex(p, r'href="/invoice/\d+\.pdf"'); self.assertNotIn('/issue/', p)       # PDF-link count and first « Émettre » link untouched
        self.assertIn('data-panel="mandates billing time"', t)

    def test_credit_follow_up_summary_repeats_existing_figures(self):
        cid = self.issued_cn(amount='100', treatment='remboursement')
        t = self.page(f'/credit/{cid}')
        summary = t[t.index('class="cn-sum"'):t.index('<table>', t.index('class="cn-sum"'))]
        rest = re.search(r'Reste à rembourser</span><strong>([^<]+)</strong>', summary).group(1)
        self.assertIn('<tr><th>Reste à rembourser</th><td><b>%s</b></td></tr>' % rest, t)
        self.assertIn('role="img"', summary)


class ArchiveFilters(Settlement):
    def test_status_chips_and_row_markers(self):
        self.issued_cn(amount='100', treatment='remboursement')
        t = self.c.get('/?tab=archive').get_data(as_text=True)
        self.assertIn('id="archiveFilters"', t)
        for k in ('all', 'draft', 'issued', 'credit'): self.assertIn('data-af="%s"' % k, t)
        table = t[t.index('id="archiveTable"'):t.index('</table>', t.index('id="archiveTable"'))]
        invoices = self.sql('SELECT COUNT(*) FROM invoices')[0][0]
        self.assertEqual(len(re.findall(r'<tr data-st="(?:draft|issued)" data-cn="\d+">', table)), invoices)   # one marker per invoice
        self.assertRegex(table, r'data-cn="[1-9]')                                                          # the credited invoice is flagged
        self.assertIn('class="cards tcards"', t[t.index('id="archiveTable"') - 40:t.index('id="archiveTable"') + 40])
        self.assertEqual(len(re.findall(r'href="/invoice/\d+\.pdf"', t)), invoices)                       # PDF links unchanged


from tests.test_import import Base as ImportBase, workbook


class ImportReviewShell(ImportBase):
    def test_review_page_has_the_application_shell(self):
        rows = [(datetime(2025, 3, 1) + timedelta(days=i), f'l{i}', 'Alpha', None, None, 1) for i in range(3)]
        html = self.review(self.upload(workbook({'MAR': rows})))
        self.assertIn('<aside class="sidebar">', html); self.assertIn('<main class="main wrap imp" id="contenu">', html)
        self.assertRegex(html, r'<a class="subtab active" href="/\?tab=migration"')
        self.assertEqual(html.count('data-status='), 3)                                                   # rows unchanged
        self.assertIn("Valider l'import", html)


class Accessibility(Settlement):
    def test_refusal_and_confirmation_messages_look_different(self):
        r = self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': '-3'}, follow_redirects=True)
        t = r.get_data(as_text=True)
        self.assertRegex(t, r'<div class="msg err" role="alert">Saisie refusée')
        r = self.c.post('/entry', data={'work_date': '2026-09-11', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': '2'}, follow_redirects=True)
        t = r.get_data(as_text=True)
        self.assertRegex(t, r'<div class="msg" role="status">Temps enregistré')

    def test_skip_link_and_landmark(self):
        for url in ('/', '/entries', f'/project/{self.pid}/edit'):
            t = self.c.get(url).get_data(as_text=True)
            self.assertIn('<a class="skip" href="#contenu">', t, url); self.assertRegex(t, r'<main class="main[^"]*" id="contenu">')

    def test_secondary_text_contrast_token(self):
        css = open(m.APP.root_path + '/templates/_ds.html', encoding='utf8').read()
        self.assertIn('--ink-3:#5b6577;', css)                                     # 4.6:1 on the glass surface (WCAG AA)
