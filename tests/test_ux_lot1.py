"""UX lot 1 (2026-10-20): display and ergonomics only — lot 1 of the UX proposals and the owner decisions B-1 to B-8.

No billing, check, issuance, VAT, stored rounding or numbering rule changes. Several tests below also prove that what is STORED or LOGGED
stays exactly what it was (audit trail of a derogation, hours of a night entry, the entry table after a page view).
Synthetic data only (see test_import.py for the run command; tests/browser/recette-ux-lot1.js covers the mobile rendering in a real browser).
"""
import html as H, json, re
from datetime import timedelta

import app.app as m
from app import pdf_layout
from app.billing_rules import local_today
from tests.test_functional import Cycle

NN = ' '   # thin no-break space: the screen's thousands separator


def text(r): return H.unescape(r.get_data(as_text=True))


def section(page, start, end='</section>'):
    i = page.index(start); return page[i:page.index(end, i)]


class SwissFormat(Cycle):
    """B-1: numbers of the check details in the screen format, on screen only; the audit log keeps the original text."""

    def test_filter_reformats_numbers_and_keeps_every_digit(self):
        f = m.fr_detail
        self.assertEqual(f('13.0 × 1200.0 = 15600.00 CHF HT'), f'13 × 1{NN}200 = 15{NN}600,00 CHF HT')
        self.assertEqual(f('taux 0.0 %, TVA 0.00 CHF'), 'taux 0 %, TVA 0,00 CHF')
        self.assertEqual(f('3 saisie(s), 110.5 h dans la période'), '3 saisie(s), 110,5 h dans la période')
        self.assertEqual(f('réalisé : 15.9375 j ; solde -4.15625 j'), 'réalisé : 15,9375 j ; solde −4,15625 j')     # no rounding, ever
        self.assertEqual(f('du 01.09.2026 au 30.09.2026'), 'du 01.09.2026 au 30.09.2026')                     # dates untouched
        self.assertEqual(f('description : « Lot 2.5 v1.2 » (test)'), 'description : « Lot 2.5 v1.2 » (test)')   # quoted user text untouched
        self.assertEqual(f('facture 2026-08 émise'), 'facture 2026-08 émise')
        self.assertEqual(f(None), '')

    def underbilled_draft(self):
        pid = self.mandate(name='Mandat format suisse')
        self.entry(pid, '2026-09-02', 8); self.entry(pid, '2026-09-03', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        return pid, iid

    def test_check_details_on_screen_audit_log_unchanged(self):
        pid, iid = self.underbilled_draft()
        page = text(self.c.get(f'/issue/{iid}'))
        self.assertIn('1 × 650 = 650,00 CHF HT', page)                       # check 3
        self.assertNotIn('650.0', page); self.assertNotIn('1.0 ×', page)
        self.assertIn("quantité facturée 1 j pour 2 j réalisé(s) dans la période (tolérance de sous-facturation : 0 j)", page)   # check 12, table and reason label
        with m.db() as conn: raw = next(c['detail'] for c in m.invoice_checks.run_checks(conn, iid) if c['n'] == 12)
        self.assertIn('1.0 j pour 2.0 j', raw)                                # the check itself still produces the same text
        r = self.issue(iid, derogate=(12,))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        logged = json.loads(self.scalar("SELECT detail FROM audit WHERE event='invoice_check_derogation' ORDER BY id DESC LIMIT 1"))
        self.assertEqual(logged['check'], 12); self.assertEqual(logged['anomaly'], raw)   # B-1: the audit keeps the original anomaly text, byte for byte

    def test_credit_note_rate_shown_in_swiss_format_value_unchanged(self):
        pid = self.mandate(name='Mandat tarif NC', rate='1200')
        self.entry(pid, '2026-09-02', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        page = text(self.c.get(f'/invoice/{iid}/credit'))
        self.assertIn(f'Tarif de la facture : 1{NN}200,00 CHF/j', page)
        self.assertRegex(page, r'name="unit_rate" type="number" min="0" step="any" value="1200\.0"')   # the posted value is exactly the stored one


class Precision(Cycle):
    """B-2: management days with 2 decimals (exact value in a tooltip), invoiced quantity with the printed precision, « aucun solde » without a PO."""

    def test_management_days_two_decimals_with_exact_tooltip(self):
        pid = self.mandate(name='Mandat précision')
        for d, h in (('2026-09-01', 8), ('2026-09-02', 8), ('2026-09-03', 7.5)): self.entry(pid, d, h)   # 23.5 h = 2.9375 j
        page = self.c.get('/').get_data(as_text=True)
        synth = section(page, 'Situation synthétique des mandats'); detail = section(page, '<h2>Détail des mandats</h2>')
        for s in (synth, detail):
            self.assertIn('<span class="exact" title="valeur exacte : 2,9375">2,94</span>', s)
            self.assertNotIn('>2,9375<', s); self.assertNotIn('2,938', s)
        self.assertIn('12,00', detail); self.assertNotIn('title="valeur exacte : 12"', detail)   # no tooltip when nothing is hidden

    def test_quantity_with_printed_precision(self):
        for v in (1, 8, 0.5, 4.15625, 1234.5, 2.123456789, 12.3, 0.000001):
            self.assertEqual(m.fr_exact(v).replace(NN, ' '), pdf_layout.qty_label(v), v)     # same digits as the PDF, screen separators
        pid = self.mandate(name='Mandat quantité')
        for d in ('2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04', '2026-09-07'): self.entry(pid, d, 7)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 4.15625, invoice_date='2026-09-30')
        archive = section(self.c.get('/').get_data(as_text=True), 'id="archiveTable"', '</table>')
        self.assertIn('<td data-label="Quantité">4,15625 j</td>', archive)
        page = text(self.c.get(f'/issue/{iid}'))
        self.assertIn('<tr><th>Quantité facturée</th><td>4,15625 j', page)
        iid2, _ = self.draft(pid, '2026-08-01', '2026-08-31', 2, invoice_date='2026-08-31')
        self.assertIn('<tr><th>Quantité facturée</th><td>2,00 j', text(self.c.get(f'/issue/{iid2}')))      # printed « 2,00 », never « 2 »
        self.assertEqual(self.scalar('SELECT qty FROM invoices WHERE id=?', (iid,)), 4.15625)            # stored value untouched

    def test_draft_without_po_says_no_balance(self):
        pid = self.mandate(name='Mandat sans PO', ordered='')
        self.entry(pid, '2026-09-02', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        page = text(self.c.get(f'/issue/{iid}'))
        row = section(page, '<tr><th>Solde contractuel</th>', '</tr>')
        self.assertIn('Sans bon de commande : aucun solde', row); self.assertNotIn('solde après émission', row); self.assertNotIn('−', row)
        detail = section(self.c.get('/').get_data(as_text=True), '<h2>Détail des mandats</h2>')
        mrow = section(detail, 'Mandat sans PO', '</tr>')
        self.assertIn('sans PO : aucun solde', mrow); self.assertNotIn('Dépassement à examiner', mrow)


class EntryForm(Cycle):
    """B-3 (last mandate preselected, visible indicator), n° 5 (date of the day, date kept), B-4 (night entry label + swap link)."""

    def form(self, url='/?tab=time'):
        return section(self.c.get(url).get_data(as_text=True), 'id="entryForm"', '</form>')

    def test_date_of_the_day_by_default(self):
        self.assertIn(f'name="work_date" value="{local_today().isoformat()}" required', self.form())

    def test_last_mandate_preselected_with_indicator_and_date_kept(self):
        a = self.mandate(name='Mandat A', start='2026-01-01'); b = self.mandate(name='Mandat B', start='2025-01-01')
        f = self.form()
        self.assertNotIn('lastProjectNote', f); self.assertNotIn(' selected>', f)   # no entry yet: no preselection, nothing claimed
        self.entry(b, '2026-08-12', 2)
        f = self.form()                                                    # page right after the save
        self.assertIn(f'<option value="{b}" selected>Mandat B</option>', f)
        self.assertIn('class="preset"', f); self.assertIn('Enregistré sur <b>Mandat B</b> ; saisie suivante sur le même mandat.', f)
        self.assertIn('name="work_date" value="2026-08-12" required', f)   # date kept after the save
        f = self.form()                                                    # later visit: same mandate, indicator says why, date of the day again
        self.assertIn(f'<option value="{b}" selected>Mandat B</option>', f)
        self.assertIn('Mandat de la dernière saisie : <b>Mandat B</b>.', f)          # UX lot 2 (n° 4): shorter wording, same indicator
        self.assertIn(f'name="work_date" value="{local_today().isoformat()}" required', f)
        self.entry(a, '2026-08-13', 1)
        self.assertIn(f'<option value="{a}" selected>Mandat A</option>', self.form())

    def test_refused_entry_does_not_move_the_preselection(self):
        b = self.mandate(name='Mandat B')
        self.entry(b, '2026-08-12', 2); self.form()
        self.c.post('/entry', data={'work_date': 'hier', 'project_id': self.p1, 'entry_mode': 'duration', 'manual_hours': '1'})
        self.assertIn(f'<option value="{b}" selected>Mandat B</option>', self.form())

    def test_night_entry_label_and_swap_link_rule_unchanged(self):
        page = self.c.get('/?tab=time').get_data(as_text=True)
        self.assertIn('<button id="entrySubmit">Enregistrer le temps</button>', page)
        self.assertIn('<button type="button" class="linkbtn" id="swapTimes" hidden>Inverser début et fin</button>', page)
        self.assertIn("(fin le lendemain)", page); self.assertIn('mins>720', page); self.assertIn("classList.toggle('warnbtn',special)", page)
        # the rule stays: a night entry is accepted as before (one entry, 16 h), nothing is blocked server-side
        pid = self.mandate(name='Mandat nuit')
        self.c.post('/entry', data={'work_date': '2026-08-12', 'project_id': pid, 'entry_mode': 'clock', 'start_time': '17:00', 'end_time': '09:00', 'description': 'nuit'})
        self.assertEqual([tuple(r) for r in self.sql('SELECT start_time,end_time,hours FROM entries WHERE project_id=?', (pid,))], [('17:00', '09:00', 16.0)])

    def test_page_view_writes_nothing(self):
        pid = self.mandate(name='Mandat lecture'); self.entry(pid, '2026-08-12', 2)
        before = [tuple(r) for r in self.sql('SELECT * FROM entries ORDER BY id')], self.scalar('SELECT COUNT(*) FROM audit')
        for url in ('/', '/?tab=time', '/?tab=time&focus=start', '/?tab=billing'): self.c.get(url)
        self.assertEqual(([tuple(r) for r in self.sql('SELECT * FROM entries ORDER BY id')], self.scalar('SELECT COUNT(*) FROM audit')), before)


class Dashboard(Cycle):
    """B-5 (recent entries: Modifier kept, no Supprimer) and n° 8 (realised beyond ordered)."""

    def test_recent_entries_keep_edit_without_delete(self):
        pid = self.mandate(name='Mandat récent')
        for d in ('2026-08-10', '2026-08-11', '2026-08-12'): self.entry(pid, d, 2)
        for tab in ('dashboard', 'time'):
            recent = section(self.c.get(f'/?tab={tab}').get_data(as_text=True), '<h2>Dernières saisies</h2>')
            self.assertEqual(recent.count('>Modifier</a>'), 3, tab)
            self.assertNotIn('Supprimer', recent, tab)
            self.assertNotIn('/delete', recent, tab)
            self.assertIn('href="/entries"', recent)
        eid = self.scalar('SELECT MIN(id) FROM entries')
        self.assertIn('Supprimer', text(self.c.get('/entries'))); self.assertIn('id="entryDeleteForm"', text(self.c.get(f'/entry/{eid}/edit')))  # deletion still reachable
        self.c.post(f'/entry/{eid}/delete', data={'return_to': '/entries'})
        self.assertEqual(self.sql('SELECT id FROM entries WHERE id=?', (eid,)), [])                          # and works as before

    def test_realised_beyond_ordered_is_flagged(self):
        over = self.mandate(name='Mandat dépassé', ordered='1'); ok = self.mandate(name='Mandat normal', ordered='10')
        self.entry(over, '2026-08-10', 8); self.entry(over, '2026-08-11', 8); self.entry(ok, '2026-08-10', 8)
        page = self.c.get('/').get_data(as_text=True)
        self.assertEqual(page.count('Réalisé &gt; commandé (+1,00 j)'), 2)            # ring card + position bar
        self.assertEqual(page.count('<div class="ringcard over">'), 1)
        self.assertEqual(page.count('<div class="bal-bar over"'), 1)
        self.assertIn('.ringcard.over .ring.real{stroke:#e09400}', page)


class Shell(Cycle):
    """B-6 (floating « Saisir » on mobile, 44 px targets), B-7 (version), B-8 (tab name), n° 1 (mobile cards on detail pages), n° 10 (headings)."""

    def test_version_absent_from_login_present_on_health(self):
        anon = m.APP.test_client()
        page = anon.get('/login').get_data(as_text=True)
        self.assertNotIn(m.VERSION, page); self.assertNotIn('class="ver"', page)
        self.assertIn('<main class="loginwrap" id="contenu">', page)
        self.assertIn('<label for="loginUser">Utilisateur</label><input id="loginUser" name="username"', page)
        self.assertIn('<label for="loginPassword">Mot de passe</label><input id="loginPassword" type="password" name="password"', page)
        self.assertEqual(anon.get('/health').get_json(), {'status': 'ok', 'version': m.VERSION})
        self.assertIn(f'Version {m.VERSION}.', self.c.get('/?tab=settings').get_data(as_text=True))       # still shown once signed in

    def test_archive_tab_renamed(self):
        page = self.c.get('/').get_data(as_text=True)
        self.assertIn('<button type="button" data-tab="archive" title="Factures et brouillons">Factures et brouillons</button>', page)
        pid = self.mandate(name='Mandat onglet'); self.entry(pid, '2026-09-02', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        detail = self.c.get(f'/issue/{iid}').get_data(as_text=True)
        self.assertIn('<a href="/?tab=archive" title="Factures et brouillons" class="active" aria-current="page">Factures et brouillons</a>', detail)
        for p in (page, detail): self.assertNotIn('Factures émises', section(p, '<aside class="sidebar">', '</aside>'))

    def test_floating_entry_button_on_mobile(self):
        page = self.c.get('/').get_data(as_text=True)
        self.assertIn('<button type="button" class="fab" id="fabSaisir" aria-label="Saisir des heures">Saisir</button>', page)
        self.assertNotRegex(page, r'id="fabSaisir"[^>]*data-tab')                       # not a tab: the navigation keeps its 7 entries
        self.assertIn("showTab('time',true);focusEntry()", page)
        css = page[page.index('/* B-6'):page.index('@media print{.fab{display:none}}')]
        self.assertIn('.fab{display:none}', css)                                         # hidden on desktop
        mobile = css[css.index('@media (max-width:760px){'):]
        self.assertIn('.fab{display:inline-flex', mobile); self.assertIn('position:fixed', mobile); self.assertIn('min-height:56px', mobile)
        self.assertIn('.main{padding-bottom:104px}', mobile)                              # it never hides the end of a page
        self.assertIn('body[data-tab=time] .fab{display:none}', mobile)
        for sel in ('.sidebar .tabs button,.sidebar .tabs a,.sidebar .tabs .subtab{min-height:44px}', 'button.secondary,.actions button', '.radio label,.modebox label{min-height:44px'):
            self.assertIn(sel, mobile)
        pid = self.mandate(name='Mandat fab'); self.entry(pid, '2026-09-02', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        for url in (f'/issue/{iid}', '/entries', f'/project/{pid}/edit'):
            self.assertIn('<a class="fab" id="fabSaisir" href="/?tab=time&amp;focus=start" aria-label="Saisir des heures">Saisir</a>', self.c.get(url).get_data(as_text=True), url)
        self.assertIn("if(document.body.dataset.tab==='time')focusEntry();", self.c.get('/?tab=time&focus=start').get_data(as_text=True))
        self.assertNotIn("if(document.body.dataset.tab==='time')focusEntry();", self.c.get('/?tab=time').get_data(as_text=True))

    def test_one_h1_per_page_and_it_names_the_screen(self):
        page = self.c.get('/?tab=billing').get_data(as_text=True)
        self.assertEqual(re.findall(r'<h1[^>]*>([^<]*)</h1>', page), ['Édition des factures'])
        self.assertIn('<p class="brandname">Time Billing V9.2</p>', page)
        self.assertIn("history.replaceState", page)
        self.assertIn('<th><span class="vh">Actions</span></th>', section(page, '<h2>Dernières saisies</h2>'))
        pid = self.mandate(name='Mandat titre'); self.entry(pid, '2026-09-02', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        self.assertEqual(re.findall(r'<h1[^>]*>([^<]*)</h1>', self.c.get(f'/issue/{iid}').get_data(as_text=True)), ['Émettre la facture — Mandat titre'])

    def test_mobile_card_rules_reach_detail_pages(self):
        pid = self.mandate(name='Mandat cartes'); self.entry(pid, '2026-09-02', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        for url in (f'/issue/{iid}', '/historique', '/'):
            page = self.c.get(url).get_data(as_text=True)
            self.assertIn('table.cards td::before{content:attr(data-label)', page, url)
            self.assertIn('table.cards tr:first-child{display:none}', page, url)
            self.assertIn("c.dataset.label=h[i]||''", page, url)                        # labels filled from the header on every page


class Issuance(Cycle):
    """n° 2 (failures summarised on top, 14 rows kept in order), n° 7 (PDF preview link), n° 6 (two buttons after the draft), n° 4 (check 13 announced)."""

    def test_failed_checks_summary_rows_in_order_and_pdf_preview(self):
        pid = self.mandate(name='Mandat contrôles')
        self.entry(pid, '2026-09-02', 8); self.entry(pid, '2026-09-03', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        page = self.c.get(f'/issue/{iid}').get_data(as_text=True)
        summary = section(page, 'id="checkSummary"', '</div>')
        self.assertIn('1 contrôle en échec :</b> <a href="#chk12">n° 12</a>', summary)
        self.assertEqual(re.findall(r'<tr id="chk(\d+)" class="chkrow-(\w+)"', page), [(str(n), 'fail' if n == 12 else 'ok') for n in range(1, 15)])
        self.assertIn('<b class="chk chk-fail">ANOMALIE</b>', page); self.assertIn('<b class="chk chk-ok">conforme</b>', page)
        self.assertIn('id="derogationNeeded"', page)                                      # the existing banner stays
        btn = page.index('Émettre définitivement la facture')
        self.assertIn(f'<a class="btn" id="draftPdfPreview" href="/invoice/{iid}.pdf">Aperçu PDF (brouillon)</a>', page[btn:])
        self.assertIn('<label for="reliquatNote"', page); self.assertIn('<input id="reliquatNote" name="reliquat_note">', page)
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').status_code, 200)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')    # the preview issues nothing

    def test_draft_created_offers_two_buttons_without_redirection(self):
        pid = self.mandate(name='Mandat brouillon')
        today = local_today()
        r = self.c.post('/invoice', data={'project_id': pid, 'period_from': today.isoformat(), 'period_to': (today + timedelta(days=10)).isoformat(), 'qty': '1'})
        self.assertEqual(r.status_code, 302); self.assertTrue(r.headers['Location'].endswith('/?tab=billing'))   # same destination as before
        iid = self.scalar('SELECT MAX(id) FROM invoices')
        page = text(self.c.get('/?tab=billing'))
        box = section(page, 'id="draftCreated"', '</div></div>')
        self.assertIn(f'<a class="btnlink" href="/invoice/{iid}/edit">Ouvrir le brouillon</a>', box)
        self.assertIn(f'<a class="btnlink" href="/issue/{iid}">Contrôler avant émission</a>', box)
        self.assertIn("La période finit après aujourd'hui : l'émission demandera une dérogation écrite (contrôle 13).", box)
        self.assertNotIn('id="draftCreated"', self.c.get('/?tab=billing').get_data(as_text=True))   # shown once
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')

    def test_period_after_today_announced_in_the_form(self):
        page = self.c.get('/?tab=billing').get_data(as_text=True)
        self.assertIn(f'id="periodAfterToday" data-today="{local_today().isoformat()}" role="status" hidden>', page)   # Zurich business day, as check 13
        self.assertIn('const today=w.dataset.today;', page)
