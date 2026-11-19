"""UX lot 2 (2026-10-23, owner decision « tout le lot 2 », recommendations R-1 to R-7 of docs/UX-LOT2-PROPOSITIONS.md): display and ergonomics only.

No billing, check, issuance, VAT, rounding or numbering rule changes. Several tests below prove it: the draft form's check-12 preview gives the verdict
the check itself gives once the draft exists (R-1, one implementation), the default rounding stays « Sans arrondi » (R-2), no date is prefilled (R-5),
the issue form posts the same fields (derogation reasons tied to it by form="issueForm"), page views write nothing.
Synthetic data only (see test_import.py for the run command; tests/browser/recette-ux-lot2.js covers the rendering in a real browser).
"""
import html as H, json, re
from datetime import date, timedelta

import app.app as m
from app import invoice_checks
from app.billing_rules import local_today
from tests.test_functional import Cycle

NN = ' '   # thin no-break space: the screen's thousands separator


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N (year of the invoice date = today's year, then the sequence of the year)


def text(r): return H.unescape(r.get_data(as_text=True))


def section(page, start, end='</section>'):
    i = page.index(start); return page[i:page.index(end, i)]


class Base2(Cycle):
    def issued(self, name='Mandat lot 2', hours=8, qty=1, **kw):
        pid = self.mandate(name=name, **kw)
        self.entry(pid, '2026-09-02', hours)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', qty, invoice_date='2026-09-30')
        self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        return pid, iid

    def writes(self):
        return (self.scalar('SELECT COUNT(*) FROM audit'), [tuple(r) for r in self.sql('SELECT * FROM invoices ORDER BY id')],
                [tuple(r) for r in self.sql('SELECT * FROM entries ORDER BY id')])


class Dashboard(Base2):
    """n° 1 (« À traiter », R-4) and n° 11 (lighter dashboard)."""

    def todo(self): return section(self.c.get('/?tab=dashboard').get_data(as_text=True), 'id="todoPanel"')

    def test_nothing_to_do(self):
        t = self.todo()
        self.assertIn('id="todoEmpty"', t); self.assertNotIn('<li', t)

    def test_draft_line_links_to_the_issue_page_with_the_checks_of_the_issue_page(self):
        pid = self.mandate(name='Mandat brouillon')
        self.entry(pid, '2026-09-02', 8); self.entry(pid, '2026-09-03', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')   # under-billed: check 12 fails
        t = self.todo()
        self.assertIn(f'<a class="btn primary" href="/issue/{iid}">Contrôler et émettre</a>', t)
        with m.db() as c: failed = [k['n'] for k in invoice_checks.failures(invoice_checks.run_checks(c, iid))]
        self.assertEqual(failed, [12])
        self.assertIn('1 contrôle en échec (n° 12)', t)

    def test_many_drafts_only_say_to_check(self):
        pid = self.mandate(name='Mandat nombreux brouillons', ordered='')
        for k in range(m.DASH_CHECKS_MAX + 1):
            self.draft(pid, f'2026-0{k + 1}-01', f'2026-0{k + 1}-28', 1, invoice_date=f'2026-0{k + 1}-28')
        t = self.todo()
        self.assertEqual(t.count('data-todo="draft"'), m.DASH_CHECKS_MAX + 1)
        self.assertEqual(t.count('à contrôler'), m.DASH_CHECKS_MAX + 1); self.assertNotIn('en échec', t)   # R-4: the checks are not run beyond the limit

    def test_variance_credit_note_backup_most_urgent_first(self):
        pid, iid = self.issued(name='Mandat écart', rate='800', ordered='10')
        eid = self.scalar('SELECT id FROM entries WHERE project_id=?', (pid,))
        self.c.post(f'/entry/{eid}/edit', data={'work_date': '2026-09-02', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '7.5', 'description': 'x',
                                               'reason': 'durée réelle corrigée', 'confirm_billed': '1'})
        self.c.post(f'/invoice/{iid}/credit', data={'treatment': 'remboursement', 'scope': 'partial', 'qty': '0.5', 'amount': '', 'other_amount': '', 'reason': 'Geste fictif',
                                                   'description': '', 'refund_delay_days': '30'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.assertEqual(self.scalar('SELECT status FROM credit_notes WHERE id=?', (cid,)), 'issued', self.flashes())
        t = self.todo()
        kinds = re.findall(r'data-todo="(\w+)"', t)
        self.assertEqual(kinds, ['variance', 'credit'])                                            # decision required, to do (BSAV1: no backup advice line any more)
        self.assertIn('id="variancesAlert"', t)                                                    # the id the rc19 suites read stays on the variance line
        self.assertIn(f'href="/invoice/{iid}/ecart">Décider</a>', t)                               # straight to the decision page
        self.assertIn(f'href="/credit/{cid}">Suivi</a>', t); self.assertIn('À rembourser', t)
        self.assertNotIn('Sauvegarde conseillée', t)                                               # BSAV1: monthly pop-up at login instead
        self.assertNotIn('/backup"', t)                                                            # nothing is executed from the dashboard (not even a download)
        page = self.c.get('/').get_data(as_text=True)
        self.assertNotIn('class="panel wide warnbox" data-panel="dashboard"', page)               # the two red banners are gone

    def test_figures_are_links_and_dashboard_writes_nothing(self):
        pid = self.mandate(name='Mandat liens'); self.entry(pid, '2026-09-02', 8)
        self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        before = self.writes()
        page = self.c.get('/').get_data(as_text=True)
        self.assertEqual(self.writes(), before)                                                    # R-4: running the checks on the dashboard writes nothing
        for href in ('/?tab=mandates', '/?tab=billing', '/?tab=archive&amp;af=draft', '/?tab=archive#notes-credit'):
            self.assertIn(f'<a class="kpi" href="{href}"', page)
        self.assertIn('Brouillons en attente</span><span class="k-value">1<', page)
        self.assertIn('id="notes-credit"', page); self.assertIn("searchParams.get('af')", page)

    def test_lighter_dashboard(self):
        pid = self.mandate(name='Mandat récent')
        for d in range(1, 9): self.entry(pid, f'2026-08-{d:02d}', 1)
        page = self.c.get('/').get_data(as_text=True)
        self.assertEqual(section(page, '<h2>Dernières saisies</h2>').count('>Modifier</a>'), 8)   # same rows; the dashboard shows the first 5 (CSS)
        self.assertIn('body[data-tab=dashboard] .recent-table tr:nth-child(n+7):not(.month-total){display:none}', page)
        self.assertIn('<details class="fold" id="synthFold" open><summary><h2>Situation synthétique des mandats</h2>', page)
        nopo = self.mandate(name='Mandat sans PO lot 2', ordered=''); self.entry(nopo, '2026-08-03', 4)
        self.assertIn('<div class="ringinfo nopo"><b>Mandat sans PO lot 2</b>', self.c.get('/').get_data(as_text=True))


class EntryForm(Base2):
    """n° 4 (mobile entry) and n° 10 (« Reprendre »)."""

    def test_date_shortcuts_segmented_mode_and_duration_in_button(self):
        page = self.c.get('/?tab=time').get_data(as_text=True)
        today = local_today()
        self.assertIn(f'data-setdate="{today.isoformat()}">Aujourd\'hui</button>', page)
        self.assertIn(f'data-setdate="{(today - timedelta(days=1)).isoformat()}">Hier</button>', page)
        self.assertIn('<input type="radio" name="entry_mode" value="clock" checked> Début / fin</label>', page)
        self.assertIn('<input type="radio" name="entry_mode" value="duration"> Durée</label>', page)
        self.assertIn('`${submitDefault} — ${hm}`', page)                                         # « Enregistrer le temps — 3 h 45 »
        self.assertIn('body[data-tab=time] .entry-submit{position:sticky', page)

    def test_reprendre_prefills_only(self):
        pid = self.mandate(name='Mandat reprise')
        self.c.post('/entry', data={'work_date': '2026-08-12', 'project_id': pid, 'entry_mode': 'clock', 'start_time': '08:30', 'end_time': '12:15', 'description': 'Atelier « client »'})
        before = self.writes()
        page = self.c.get('/?tab=time').get_data(as_text=True)
        recent = section(page, '<h2>Dernières saisies</h2>')
        self.assertIn(f'data-pid="{pid}" data-start="08:30" data-end="12:15" data-hours="3.75" data-desc="Atelier « client »"', H.unescape(recent))
        self.assertIn('>Reprendre</button>', recent); self.assertNotIn('/delete', recent)
        self.assertEqual(self.writes(), before)


class DraftForm(Base2):
    """n° 3 (R-1, R-2, R-5)."""

    def test_period_story_is_the_check_12_rule(self):
        s = invoice_checks.period_story
        self.assertEqual(s(1, 1, True, '2026-09-01', '2026-09-30'), [])
        self.assertEqual(s(1, 0.5, True, '2026-09-01', '2026-09-30'), ['sur-facturation : quantité facturée 1 j pour 0.5 j réalisé(s) dans la période (tolérance de sur-facturation : 0 j)'])
        self.assertEqual(s(1, 1.5, True, '2026-09-01', '2026-09-30'), ['quantité facturée 1 j pour 1.5 j réalisé(s) dans la période (tolérance de sous-facturation : 0 j)'])   # rc41: no under-billing tolerance any more
        self.assertEqual(s(1, 1 + 1e-6, True, '2026-09-01', '2026-09-30'), [])                  # float noise below EPS is not a gap
        self.assertEqual(len(s(1, 1.51, True, '2026-09-01', '2026-09-30')), 1)
        self.assertIn('aucune saisie datée de la période', s(1, 0, False, '2026-09-01', '2026-09-30')[0])

    def test_preview_gives_the_verdict_of_the_check_itself(self):
        """R-1: for each rounding rule, the verdict announced before the draft exists is the one check 12 gives on the draft created with that quantity."""
        pid = self.mandate(name='Mandat aperçu', rate='900', ordered='40')
        for d, h in (('2026-09-01', 7.75), ('2026-09-02', 8), ('2026-09-03', 8), ('2026-09-04', 8), ('2026-09-07', 8), ('2026-09-08', 8), ('2026-09-09', 8)):
            self.entry(pid, d, h)                                                                  # 55.75 h = 6.96875 j
        st, s = self.suggest(pid, '2026-09-01', '2026-09-30', 'nearest', '0.25')
        self.assertEqual(st, 200); self.assertEqual((s['raw_days'], s['suggested_qty']), (6.96875, 7.0))   # existing fields unchanged
        self.assertEqual(set(s['options']), {'exact', 'nearest', 'up', 'down'})
        self.assertEqual({k: v['qty'] for k, v in s['options'].items()}, {'exact': 6.96875, 'nearest': 7.0, 'up': 7.0, 'down': 6.75})
        self.assertEqual(s['entries_in_period'], 7)
        for mode, o in s['options'].items():
            iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', o['qty'], rounding=mode, rounding_step='0.25', invoice_date='2026-09-30')
            with m.db() as c: c12 = next(k for k in invoice_checks.run_checks(c, iid) if k['n'] == 12)
            self.assertEqual(o['check12_ok'], c12['status'] == 'ok', (mode, o, c12))
            if not o['check12_ok']: self.assertEqual(o['check12'], [m.fr_detail(c12['detail'])])
            self.c.post(f'/invoice/{iid}/delete')
        self.assertFalse(s['options']['nearest']['check12_ok']); self.assertFalse(s['options']['down']['check12_ok'])   # 0 j tolerance both ways (rc41): 7 j is 0.03 j over, 6.75 j is 0.22 j under
        self.assertTrue(s['options']['exact']['check12_ok'])

    def test_typed_quantity_overlap_clash_and_po(self):
        pid = self.mandate(name='Mandat alertes', ordered='2')
        self.entry(pid, '2026-08-03', 8); self.entry(pid, '2026-09-02', 8)
        i1, _ = self.draft(pid, '2026-08-01', '2026-08-31', 1, invoice_date='2026-08-31'); self.issue(i1)
        d1, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        r = self.c.post('/suggest', data={'project_id': pid, 'period_from': '2026-08-15', 'period_to': '2026-09-15', 'rounding': 'exact', 'rounding_step': '0.25', 'qty': '3'}).get_json()
        self.assertEqual([d['id'] for d in r['overlapping_drafts']], [d1])
        self.assertEqual(r['issued_clash']['number'], self.scalar('SELECT number FROM invoices WHERE id=?', (i1,)))
        self.assertEqual(r['typed']['qty'], 3.0); self.assertFalse(r['typed']['check12_ok']); self.assertTrue(r['typed']['po_over'])
        before = self.writes()
        for q in ('', 'abc', '-1', 'inf'):
            r = self.c.post('/suggest', data={'project_id': pid, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'rounding': 'exact', 'rounding_step': '0.25', 'qty': q})
            self.assertEqual(r.status_code, 200, q); self.assertIsNone(r.get_json()['typed'], q)
        self.assertEqual(self.writes(), before)                                                    # /suggest stays read-only

    def test_default_rounding_unchanged_no_date_prefilled_shortcut_data(self):
        pid, iid = self.issued(name='Mandat raccourcis')
        form = section(self.c.get('/?tab=billing').get_data(as_text=True), 'id="invoiceForm"', '</form>')
        self.assertIn('<select name="rounding" id="rounding"><option value="exact">Sans arrondi</option>', form)   # R-2: the default rule is unchanged
        self.assertNotRegex(form, r'<option value="(?:nearest|up|down)"[^>]*selected')
        self.assertIn('<input type="date" name="period_from" id="periodFrom" required>', form)                 # R-5: nothing prefilled
        self.assertIn('<input type="date" name="period_to" id="periodTo" required>', form)
        self.assertIn(f'data-last="2026-09-30">Mandat raccourcis</option>', form)                               # end of the last issued period
        for k in ('since', 'lastmonth', 'thismonth'): self.assertIn(f'data-period="{k}"', form)
        self.assertEqual(form.count('<button class="wide" id="draftSubmit">Créer le brouillon</button>'), 1)    # one submit button; the others are type=button
        self.assertEqual(len(re.findall(r'<button(?![^>]*type="button")', form)), 1)
        self.assertIn('<details class="wide draft-options" id="draftOptions">', form)
        for name in ('description', 'other_amount', 'other_label', 'other_vat_mode', 'invoice_date', 'note'): self.assertIn(f'name="{name}"', form)


class Issuance(Base2):
    """n° 2 (R-3)."""

    def page(self, iid): return self.c.get(f'/issue/{iid}').get_data(as_text=True)

    def test_three_steps_reasons_in_their_rows_same_posted_fields(self):
        pid = self.mandate(name='Mandat trois temps')
        self.entry(pid, '2026-09-02', 8); self.entry(pid, '2026-09-03', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        page = self.page(iid)
        row = section(page, '<tr id="chk12"', '</tr>')
        self.assertIn('<textarea form="issueForm" id="derog12" name="derogation_12" required minlength="10"', row)   # in the row of its anomaly
        self.assertIn(f'<a class="btn" href="/invoice/{iid}/edit">Corriger le brouillon</a>', row)
        self.assertIn('<form method="post" class="panel" id="issueForm">', page)
        self.assertIn(f'name="expected_reliquat" value="', page)
        for h in ('1. Contrôles avant émission', '2. Décisions', '3. Émission'): self.assertIn(h, page)
        recap = section(page, 'id="issueRecap"', '</aside>')
        self.assertIn(f'<b>{YEAR}-1</b>', recap); self.assertIn('Avant d\'émettre :</b> 1 dérogation à motiver (n° 12) ; traitement du reliquat à choisir', H.unescape(recap))
        self.assertIn(f'Émettre définitivement la facture {YEAR}-1 — 650,00 CHF</button>', page)
        self.assertRegex(page, r'<details class="pos" id="issuePosition"><summary>')               # R-3: folded without alert
        self.issue(iid, derogate=(12,))                                                             # the same fields as before issue it
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())

    def test_position_opens_on_alert_and_blocking_failure_has_no_reason_field(self):
        pid = self.mandate(name='Mandat PO petit', ordered='1')
        for d in ('2026-09-01', '2026-09-02'): self.entry(pid, d, 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 2, invoice_date='2026-09-30')
        page = self.page(iid)
        self.assertIn('<details class="pos" id="issuePosition" open>', page)                       # PO exceeded: unfolded
        self.assertIn('Dépassement du bon de commande', page)
        c = __import__('sqlite3').connect(m.DB); c.execute('UPDATE invoices SET unit_rate=1 WHERE id=?', (iid,)); c.commit(); c.close()   # check 3 fails: not derogable
        page = self.page(iid)
        self.assertNotIn('name="derogation_', page); self.assertIn('Émission impossible', page)
        self.assertRegex(page, r'<button disabled>Émettre définitivement')


class Archive(Base2):
    """n° 6."""

    def test_drafts_first_one_main_action_same_markers(self):
        pid, iid = self.issued(name='Mandat archive')
        self.entry(pid, '2026-10-02', 8)
        did, _ = self.draft(pid, '2026-10-01', '2026-10-31', 1)
        t = self.c.get('/?tab=archive').get_data(as_text=True)
        table = section(t, 'id="archiveTable"', '</table>')
        self.assertLess(table.index('Brouillons à émettre'), table.index(f'href="/issue/{did}"'))
        self.assertLess(table.index(f'href="/issue/{did}"'), table.index('Documents émis'))
        self.assertLess(table.index('Documents émis'), table.index(f'href="/invoice/{iid}.pdf"'))
        self.assertIn(f'<a class="btn primary" href="/issue/{did}">Contrôler et émettre</a><details class="more">', table)
        self.assertIn(f'<form method="post" action="/invoice/{did}/delete" data-confirm="Supprimer définitivement ce brouillon ?"><button class="secondary">Supprimer</button></form>', table)
        self.assertEqual(len(re.findall(r'<tr data-st="(?:draft|issued)" data-cn="\d+">', table)), 2)
        self.assertEqual(len(re.findall(r'href="/invoice/\d+\.pdf"', table)), 2)      # in the TABLE (the to-do list of payments to follow, added after this test, also links the issued PDF)
        self.assertIn("grs.forEach(r=>r.hidden=!!(v||af!=='all'))", t)                             # group titles leave the filtered counts as they were
        self.assertIn('#archiveTable tr.grouprow[hidden]{display:none}', t)                         # and stay hidden on phones (found by the browser recette)


class Navigation(Base2):
    """n° 5: bottom tab bar on phones; « Saisie » takes over the role of the floating button B-6."""

    def test_bar_and_more_menu_on_every_page(self):
        pid = self.mandate(name='Mandat nav'); self.entry(pid, '2026-09-02', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        for url in ('/', f'/issue/{iid}', '/entries', f'/project/{pid}/edit'):
            page = self.c.get(url).get_data(as_text=True)
            self.assertIn('<button type="button" class="navmore" id="navMore" aria-expanded="false" aria-controls="navMoreMenu" title="Plus">Plus</button>', page, url)
            menu = section(page, '<div class="navmenu" id="navMoreMenu" hidden>', '</div>')
            for lab in ('Édition des factures', 'Import historique', 'Paramètres'): self.assertIn(lab, menu, url)
            self.assertIn('<form method="post" action="/logout" class="inline"><button type="submit" class="linkbtn navlogout">Déconnexion</button></form>', menu, url)
            self.assertIn('.navmore,.navmenu,.sidebar .tabs .navmore{display:none}', page, url)
            self.assertIn('.fab{display:none!important}', page, url)
        self.assertIn("matchMedia('(max-width:760px)').matches)focusEntry()", self.c.get('/').get_data(as_text=True))

    def test_stylesheet_has_no_jinja_comment_opener(self):
        with open(m.os.path.join(m.os.path.dirname(m.__file__), 'templates', '_ds.html'), encoding='utf-8') as f: css = f.read()
        self.assertNotRegex(css, r'\{#')        # _ds.html is included as a template: « {#id » would open a Jinja comment


class Numbers(Base2):
    """n° 8 (R-6): 2 decimals + exact tooltip for management figures; exact values in checks, variance and credit notes."""

    def test_two_decimals_with_tooltip_outside_decision_pages(self):
        pid = self.mandate(name='Mandat nombres')
        self.entry(pid, '2026-09-02', 5.75)                                                        # 0.71875 j
        page = self.c.get('/entries').get_data(as_text=True)
        self.assertIn('<span class="exact" title="valeur exacte : 0,71875">0,72</span>', page)
        self.assertNotIn('0,7188', page)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 0.5, invoice_date='2026-09-30')
        self.issue(iid, derogate=(12,))                                                             # reliquat 0.21875 j reported (rc41: 0.5 j for 0.71875 j worked is a gap of check 12: written reason)
        arch = section(self.c.get('/?tab=archive').get_data(as_text=True), 'id="archiveTable"', '</table>')
        self.assertIn('<span class="exact" title="valeur exacte : 0,21875">0,22</span> j — Reporté', arch)
        self.assertEqual(self.scalar('SELECT reliquat_days FROM invoices WHERE id=?', (iid,)), 0.21875)   # stored value untouched

    def test_variance_page_keeps_exact_values_without_padding(self):
        pid, iid = self.issued(name='Mandat écart exact', rate='800', ordered='10')
        eid = self.scalar('SELECT id FROM entries WHERE project_id=?', (pid,))
        self.c.post(f'/entry/{eid}/edit', data={'work_date': '2026-09-02', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '7.5', 'description': 'x',
                                               'reason': 'durée réelle corrigée', 'confirm_billed': '1'})
        page = text(self.c.get(f'/invoice/{iid}/ecart'))
        self.assertIn('−0,0625 j', page); self.assertNotIn(',0000 j', page)


class Entries(Base2):
    """n° 7."""

    def test_quick_periods_and_totals_over_the_whole_selection(self):
        pid = self.mandate(name='Mandat liste')
        for k in range(52): self.entry(pid, '2026-09-08' if k < 30 else '2026-09-09', 1)          # 52 entries, 2 pages, one ISO week
        page = text(self.c.get('/entries'))
        self.assertEqual(page.count('data-entry='), 50)                                            # subtotal rows are not entries
        self.assertIn('Semaine 37 (07.09.2026 → 13.09.2026) : <b>52,00 h</b>', page)               # the week total counts both pages
        self.assertIn('Total du 09.09.2026 : <b>22,00 h</b> <small>(22 saisies, toutes pages)</small>', page)
        today = local_today(); mon = today - timedelta(days=today.weekday())
        self.assertIn(f'href="/entries?date_from={mon.isoformat()}&amp;date_to={today.isoformat()}">Cette semaine</a>', self.c.get('/entries').get_data(as_text=True))
        p2 = self.c.get(f'/entries?project={pid}&date_from=2026-09-01&date_to=2026-09-30').get_data(as_text=True)
        self.assertIn(f'href="/entries?project={pid}&amp;date_from=', p2)                          # the other filters are kept
        self.assertIn("f.requestSubmit", p2)


class Mandates(Base2):
    """n° 9 (R-7)."""

    def test_close_moved_to_the_mandate_page_same_route(self):
        pid = self.mandate(name='Mandat à clore', ordered='')
        page = self.c.get('/?tab=mandates').get_data(as_text=True)
        self.assertNotIn(f'action="/project/{pid}/close"', page); self.assertNotIn('Motif de clôture', section(page, '<h2>Détail des mandats</h2>'))
        self.assertIn('<td><small>sans PO</small></td>', section(page, '<h2>Détail des mandats</h2>'))   # ordered value « sans PO », no 0,00 CHF
        edit = self.c.get(f'/project/{pid}/edit').get_data(as_text=True)
        self.assertIn(f'<form class="closeform" method="post" action="/project/{pid}/close" data-confirm="Clôturer ce mandat ?', edit)
        self.c.post(f'/project/{pid}/close', data={'reason': ''})
        self.assertEqual(self.scalar('SELECT active FROM projects WHERE id=?', (pid,)), 1)          # reason still required
        self.c.post(f'/project/{pid}/close', data={'reason': 'mission terminée'})
        self.assertEqual(self.scalar('SELECT active FROM projects WHERE id=?', (pid,)), 0)
        self.assertNotIn('id="cloture"', self.c.get(f'/project/{pid}/edit').get_data(as_text=True))
        self.assertIn(f'/project/{pid}/reopen', self.c.get('/?tab=mandates').get_data(as_text=True))

    def test_creation_form_in_sections_same_fields(self):
        form = section(self.c.get('/?tab=mandates').get_data(as_text=True), 'id="nouveau-mandat"')
        for h in ('1. Identification', '2. Conditions contractuelles', '3. Facturation', '4. Identité juridique du client'): self.assertIn(h, form)
        names = re.findall(r'name="(\w+)"', form)
        self.assertEqual(sorted(names), sorted(['name', 'short_name', 'client', 'po', 'rate', 'ordered_days', 'start_date', 'duration_months', 'day_hours', 'vat',
                                                'project_number', 'dates_label', 'billing_contact', 'billing_address', 'client_legal_name', 'client_legal_id']))
        self.assertEqual(form.count('requis avant émission</span>'), 3)                             # the fields rules.missing_for_issue asks for
        self.assertEqual(sorted(m.rules.PROJECT_REQUIRED), ['billing_address', 'client'])


class Version(Base2):
    def test_version_candidate(self):
        self.assertGreaterEqual(int(m.VERSION.rsplit('rc', 1)[1]), 34)                              # lot 2 is in rc34 and later (rc35: tests/test_theme.py pins the version)
        self.assertEqual(self.c.get('/health').get_json()['version'], m.VERSION)
