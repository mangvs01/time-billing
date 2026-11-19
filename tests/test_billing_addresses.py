"""rc37 (P2) — selectable billing address: reusable addresses per client (legal identity), copy (instantané) in the draft, seed script, PDF.
Synthetic data only."""
import io, json, os, re, sqlite3, sys, unittest

import app.app as m
from app import address_service, billing_rules as rules
from tests import test_g4
from tests.test_functional import pdf_text
from tests.test_g4 import text
from tests.test_invoice_lines import draw_calls, page_one

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import seed_adresses_egg as seed          # noqa: E402

LEGAL = 'CHE-000.000.001'        # the legal identity of the default synthetic mandate (Cycle.mandate)
OWNER_TEXT = os.path.join(ROOT, 'docs', 'commentaire-pdf-adresses.txt')


def owner_addresses():
    """The addresses of the owner's comment, parsed from the verbatim text file: {label: [printed lines]}."""
    raw = open(OWNER_TEXT, encoding='utf-8').read().splitlines()
    blocks, cur = [], []
    for l in raw + ['']:
        if l.strip(): cur.append(l.strip())
        elif cur: blocks.append(cur); cur = []
    head = next(b for b in blocks if b[0].startswith('Créer une liste'))
    labels = head[1:]; out = {}
    for b in blocks[1:]:
        key = {'EGG BE SPRL': 'EGG BE', 'EGG CH SA': 'EGG CH', 'EGG MEA': 'EGG MEA', 'EGG FR': 'EGG FR'}[b[0]]
        out[key] = b
    assert labels == ['EGG FR', 'EGG BE', 'EGG CH', 'EGG MEA'], labels
    return labels, out


class Addresses(test_g4.G4):
    checks = test_g4.Checks.checks
    RECORD_WORK = True

    def seeded(self, **kw):
        out = io.StringIO(); old = sys.stdout; sys.stdout = out
        try: rc = seed.main(['--base', self.db, '--client-legal-id', LEGAL, '--appliquer', '--confirmer', seed.CONFIRM] + [f'--{k}' for k in kw])
        finally: sys.stdout = old
        self.assertEqual(rc, 0); return out.getvalue()

    def draft_id(self):
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 2); self.assertIn('Brouillon créé.', fl); return iid

    def rev(self, iid): return str(self.scalar('SELECT revision FROM invoices WHERE id=?', (iid,)))

    def edit(self, iid, **over):
        d = dict(period_from='2026-09-01', period_to='2026-09-30', qty='2', unit='day', rounding='exact', rounding_step='0.25', vat='0', description='Prestation', other_amount='0',
                 other_label='', other_vat_mode='hors_tva', invoice_date='', note='', revision=self.rev(iid)); d.update(over)
        self.flashes(); r = self.c.post(f'/invoice/{iid}/edit', data=d)
        return r, ' '.join(self.flashes()) + (' ' + text(r) if r.status_code == 200 else '')

    def addr_id(self, label): return self.scalar('SELECT id FROM billing_addresses WHERE label=?', (label,))

    def pdf_lines(self, iid):
        return [c[2] for c in page_one(draw_calls(lambda: self.c.get(f'/invoice/{iid}.pdf'))) if c[0] == 390.7 and 180 < c[1] < 290]

    # --- the owner's text, verbatim ------------------------------------------------------------------------------
    def test_the_data_file_holds_the_four_addresses_of_the_owner_exactly(self):
        labels, want = owner_addresses()
        data = json.load(open(os.path.join(ROOT, 'app', 'donnees_adresses', 'egg.json'), encoding='utf-8'))
        self.assertEqual([a['label'] for a in sorted(data['addresses'], key=lambda a: a['sort_order'])], labels)
        for a in data['addresses']: self.assertEqual(a['lines'], want[a['label']], a['label'])
        self.assertEqual(want['EGG FR'][-1], 'FR74 433 639 523'); self.assertEqual(want['EGG BE'][2], 'Etienne Demunter 5, boîte 10')

    # --- rc40 : the list is offered on EVERY mandate (owner's annotated PDF, 27.10.2026) --------------------------------------------------
    def test_the_global_list_is_offered_to_a_mandate_without_any_client_and_can_be_chosen(self):
        c = m.db()
        try:
            now = '2026-10-27 00:00:00'
            for n, lab in enumerate(['EGG FR', 'EGG BE', 'EGG CH', 'EGG MEA']):
                c.execute("INSERT INTO billing_addresses(client_key,label,contact,address,active,sort_order,created_at) VALUES('*',?,?,?,1,?,?)", (lab, 'Contact ' + lab, 'Rue ' + lab, n, now))
            c.commit()
            opts = [a['label'] for a in address_service.listing(c, '')]            # no client at all
            self.assertEqual(opts, ['EGG FR', 'EGG BE', 'EGG CH', 'EGG MEA'])
            self.assertEqual([a['label'] for a in address_service.listing(c, 'NOM:autre')], opts)      # another client: same list
            pid = c.execute('SELECT id FROM projects LIMIT 1').fetchone()['id']
            p = c.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
            inv = {'billing_address_id': None}
            got = address_service.choose(c, inv, p, str(opts and c.execute("SELECT id FROM billing_addresses WHERE label='EGG CH'").fetchone()['id']))
            self.assertEqual(got['bill_label'], 'EGG CH')
        finally: c.close()

    def test_the_four_seeded_addresses_of_rc37_become_global_once_and_nothing_else_moves(self):
        c = m.db()
        try:
            now = '2026-10-27 00:00:00'
            for n, lab in enumerate(['EGG FR', 'EGG BE', 'EGG CH', 'EGG MEA', 'Autre adresse']):
                c.execute("INSERT INTO billing_addresses(client_key,label,contact,address,active,sort_order,created_at) VALUES('NOM:bsci',?,?,?,1,?,?)", (lab, 'C', 'A ' + lab, n, now))
            c.commit()
            address_service.make_global(c); address_service.make_global(c); c.commit()                   # idempotent
            rows = {r['label']: r['client_key'] for r in c.execute('SELECT label,client_key FROM billing_addresses')}
            self.assertEqual({k: v for k, v in rows.items() if k.startswith('EGG')}, {'EGG FR': '*', 'EGG BE': '*', 'EGG CH': '*', 'EGG MEA': '*'})
            self.assertEqual(rows['Autre adresse'], 'NOM:bsci')
        finally: c.close()

    # --- seed script ----------------------------------------------------------------------------------------------
    def test_seed_is_a_dry_run_by_default_and_idempotent_when_applied(self):
        out = io.StringIO(); old = sys.stdout; sys.stdout = out
        try: rc = seed.main(['--base', self.db, '--client-legal-id', LEGAL])
        finally: sys.stdout = old
        self.assertEqual(rc, 0); self.assertIn('SIMULATION : 4 écriture(s)', out.getvalue()); self.assertEqual(self.scalar('SELECT COUNT(*) FROM billing_addresses'), 0)
        self.assertIn('APPLIQUÉ : 4', self.seeded()); rows = [tuple(r) for r in self.sql('SELECT * FROM billing_addresses ORDER BY id')]
        self.assertEqual([r['label'] for r in self.sql('SELECT label FROM billing_addresses ORDER BY sort_order')], ['EGG FR', 'EGG BE', 'EGG CH', 'EGG MEA'])
        self.assertIn('APPLIQUÉ : 0', self.seeded()); self.assertEqual([tuple(r) for r in self.sql('SELECT * FROM billing_addresses ORDER BY id')], rows)    # replay: nothing changes
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='billing_addresses_seeded'"), 1)                                           # one audit row, none for the replay
        self.assertEqual(self.scalar('SELECT client_key FROM billing_addresses LIMIT 1'), rules.legal_key(LEGAL))

    def test_seed_refuses_without_confirmation_unknown_client_and_never_overwrites_silently(self):
        with self.assertRaises(SystemExit) as e: seed.main(['--base', self.db, '--client-legal-id', LEGAL, '--appliquer'])
        self.assertIn('--confirmer', str(e.exception)); self.assertEqual(self.scalar('SELECT COUNT(*) FROM billing_addresses'), 0)
        with self.assertRaises(SystemExit) as e: seed.main(['--base', self.db, '--client-legal-id', 'CHE-999.999.999'])
        self.assertIn('aucun mandat', str(e.exception))
        self.seeded(); c = sqlite3.connect(self.db); c.execute("UPDATE billing_addresses SET address='Adresse modifiée à la main' WHERE label='EGG CH'"); c.commit(); c.close()
        out = self.seeded(); self.assertIn('DIFFÉRENT', out); self.assertEqual(self.scalar("SELECT address FROM billing_addresses WHERE label='EGG CH'"), 'Adresse modifiée à la main')
        out = io.StringIO(); old = sys.stdout; sys.stdout = out
        try: seed.main(['--base', self.db, '--client-legal-id', LEGAL, '--appliquer', '--confirmer', seed.CONFIRM, '--mettre-a-jour'])
        finally: sys.stdout = old
        self.assertEqual(self.scalar("SELECT address FROM billing_addresses WHERE label='EGG CH'"), 'Route de Saint Julien 63\n1212 Lancy\nSwitzerland')


    def test_seed_by_client_name_for_mandates_without_a_legal_identity(self):
        """The owner's draft prints no « N° d'identification »: the EGG mandate probably has no legal identity, so its key is the short client name."""
        self.c.post('/project', data={'name': 'GEM STC 2026 - 2600140AE', 'client': ' EGG ', 'rate': '600', 'day_hours': '8', 'billing_address': ''})
        out = io.StringIO(); old = sys.stdout; sys.stdout = out
        try: rc = seed.main(['--base', self.db, '--client-name', 'egg', '--appliquer', '--confirmer', seed.CONFIRM])
        finally: sys.stdout = old
        self.assertEqual(rc, 0); self.assertIn('NOM:egg', out.getvalue()); self.assertIn('GEM STC 2026 - 2600140AE', out.getvalue())
        pid = self.scalar('SELECT id FROM projects WHERE name=?', ('GEM STC 2026 - 2600140AE',)); self.entry(pid, '2026-09-10', 16)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 2)
        html = self.c.get(f'/invoice/{iid}/edit').get_data(as_text=True); self.assertEqual(re.findall(r'<option value="\d+" data-text="[^"]*"\s*>([^<]+)</option>', html), ['EGG FR', 'EGG BE', 'EGG CH', 'EGG MEA'])
        with self.assertRaises(SystemExit): seed.main(['--base', self.db, '--client-name', 'Inconnu'])
        with self.assertRaises(SystemExit): seed.main(['--base', self.db, '--client-name', 'egg', '--client-legal-id', 'x'])       # one or the other

    def test_seed_finds_the_mandates_by_the_short_name_EGG_without_any_option(self):
        """rc38 (owner decision Q4, 26.10): without --client-name / --client-legal-id the mandates are found by the short client name « EGG » (dry run here)."""
        with self.assertRaises(SystemExit): seed.main(['--base', self.db])                       # no mandate called EGG yet: refused, nothing done
        self.c.post('/project', data={'name': 'GEM STC 2026 - 2600140AE', 'client': 'EGG', 'rate': '600', 'day_hours': '8', 'billing_address': ''})
        out = io.StringIO(); old = sys.stdout; sys.stdout = out
        try: rc = seed.main(['--base', self.db])
        finally: sys.stdout = old
        self.assertEqual(rc, 0); self.assertIn('NOM:egg', out.getvalue()); self.assertIn('SIMULATION : 4 écriture(s)', out.getvalue())
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM billing_addresses WHERE client_key=?', ('NOM:egg',)), 0)       # a dry run writes nothing

    def test_seed_creates_the_table_on_a_base_that_does_not_have_it_yet(self):
        c = sqlite3.connect(self.db); c.execute('DROP TABLE billing_addresses'); c.commit(); c.close()
        self.assertIn('APPLIQUÉ : 4', self.seeded()); self.assertEqual(self.scalar('SELECT COUNT(*) FROM billing_addresses'), 4)

    # --- the editor menu and the PDF ------------------------------------------------------------------------------
    def test_the_menu_lists_the_four_labels_in_order_and_the_pdf_prints_the_choice_line_by_line(self):
        self.seeded(); iid = self.draft_id(); labels, want = owner_addresses()
        html = self.c.get(f'/invoice/{iid}/edit').get_data(as_text=True)
        self.assertEqual(re.findall(r'<option value="(\d+)" data-text="[^"]*" >?\s*([^<]+)</option>', html.replace(' selected', ''))[:0], [])
        opts = re.findall(r'<option value="\d+" data-text="[^"]*"\s*>([^<]+)</option>', html); self.assertEqual(opts, labels)
        self.assertEqual(re.search(r'<select name="billing_address_id".*?</select>', html, re.S).group(0).count('<option'), 5)      # + « adresse de la fiche du mandat »
        for label in labels:
            r, fl = self.edit(iid, billing_address_id=str(self.addr_id(label))); self.assertEqual(r.status_code, 302, fl); self.assertIn(f'Adresse de facturation : {label}.', fl)
            got = self.pdf_lines(iid)
            for line in want[label]: self.assertIn(line, got, (label, line))
            self.assertEqual([l for l in got if l in want[label]], want[label], label)                  # same lines, same order, one per line (no merged text)
            self.assertEqual(self.scalar('SELECT bill_label FROM invoices WHERE id=?', (iid,)), label)

    def test_the_alert_label_stays_while_no_address_is_chosen_and_the_mandate_has_none(self):
        self.c.post('/project', data={'name': 'Mandat sans adresse', 'client': 'Client Fictif', 'rate': '650', 'day_hours': '8', 'client_legal_name': 'Client Fictif SA', 'client_legal_id': LEGAL})
        pid = self.scalar('SELECT id FROM projects WHERE name=?', ('Mandat sans adresse',)); self.entry(pid, '2026-09-10', 16)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 2); self.seeded()
        self.assertIn('[À COMPLÉTER : Adresse de facturation]', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))
        r, fl = self.edit(iid, billing_address_id=str(self.addr_id('EGG BE')), qty='2')
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data); self.assertNotIn('[À COMPLÉTER : Adresse de facturation]', t); self.assertIn('1090 JETTE', t)

    def test_a_draft_keeps_the_mandate_address_until_an_explicit_choice_then_a_copy(self):
        self.seeded(); iid = self.draft_id()
        self.assertIn('Rue Imaginaire 1', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))                      # the mandate's own address (decision D8)
        self.c.post(f'/project/{self.pid}/edit', data=self.project_form(billing_address='Client Fictif SA\nRue Nouvelle 2\n8888 Ailleurs'))
        self.assertIn('Rue Nouvelle 2', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))                        # still live while no choice was made
        self.assertIsNone(self.scalar('SELECT billing_address_id FROM invoices WHERE id=?', (iid,)))
        self.edit(iid, billing_address_id=str(self.addr_id('EGG CH')))
        self.c.post(f'/project/{self.pid}/edit', data=self.project_form(billing_address='Client Fictif SA\nRue Encore Autre 3\n7777 Là-bas'))
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data); self.assertIn('Route de Saint Julien 63', t); self.assertNotIn('Rue Encore Autre 3', t)    # the copy no longer follows the mandate
        self.edit(iid, billing_address_id='')                                                                      # back to the mandate's address, explicit
        self.assertIn('Rue Encore Autre 3', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)); self.assertIsNone(self.scalar('SELECT bill_address FROM invoices WHERE id=?', (iid,)))

    def project_form(self, **over):
        p = self.sql('SELECT * FROM projects WHERE id=?', (self.pid,))[0]
        d = {k: ('' if p[k] is None else str(p[k])) for k in ('name', 'short_name', 'client', 'po', 'project_number', 'rate', 'ordered_days', 'day_hours', 'vat', 'start_date', 'duration_months',
                                                                 'dates_label', 'billing_contact', 'billing_address', 'client_legal_name', 'client_legal_id')}
        d.update(over); return d

    def test_editing_or_deactivating_an_address_does_not_move_the_drafts_that_copied_it_until_refresh(self):
        self.seeded(); iid = self.draft_id(); aid = self.addr_id('EGG MEA'); self.edit(iid, billing_address_id=str(aid))
        self.flashes(); self.c.post(f'/adresses/{aid}', data={'label': 'EGG MEA', 'contact': 'EGG MEA FZ-LLC', 'address': 'Office 30 - Floor 23\nThe One Tower - TECOM\nDubai\nUnites Arab Emirates'})
        self.assertIn('enregistrée', ' '.join(self.flashes()))
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data); self.assertIn('Office 28 - Floor 23', t); self.assertNotIn('EGG MEA FZ-LLC', t)         # the draft's copy
        self.c.post(f'/adresses/{aid}', data={'act': 'desactiver'}); self.assertIn('Office 28 - Floor 23', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))
        html = self.c.get(f'/invoice/{iid}/edit').get_data(as_text=True); self.assertIn('EGG MEA (désactivée)', html)                               # still shown: the draft carries it
        r, fl = self.edit(iid, billing_address_id=str(aid), refresh_address='1'); self.assertEqual(r.status_code, 302, fl)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data); self.assertIn('Office 30 - Floor 23', t); self.assertIn('EGG MEA FZ-LLC', t)            # explicit refresh
        iid2 = self.draft(self.pid, '2026-10-01', '2026-10-31', 1)[0]
        r, fl = self.edit(iid2, billing_address_id=str(aid), period_from='2026-10-01', period_to='2026-10-31', qty='1'); self.assertEqual(r.status_code, 200); self.assertIn('désactivée', fl)   # never newly chosen

    def test_an_unchanged_choice_is_not_silently_refreshed(self):
        self.seeded(); iid = self.draft_id(); aid = self.addr_id('EGG BE'); self.edit(iid, billing_address_id=str(aid))
        c = sqlite3.connect(self.db); c.execute("UPDATE billing_addresses SET address='Ligne changée' WHERE id=?", (aid,)); c.commit(); c.close()
        self.edit(iid, billing_address_id=str(aid)); self.assertIn('Avenue du Bourgmestre', self.scalar('SELECT bill_address FROM invoices WHERE id=?', (iid,)))
        self.edit(iid)                                                                                              # a form without the field (old script): the choice stays
        self.assertEqual(self.scalar('SELECT billing_address_id FROM invoices WHERE id=?', (iid,)), aid)

    def test_refusals_foreign_unknown_and_malformed_choices(self):
        self.seeded(); iid = self.draft_id()
        pid2 = self.mandate(name='Autre client', legal_id='CHE-000.000.002'); self.c.post('/adresses/ajouter', data={'client_key': rules.legal_key('CHE-000.000.002'), 'label': 'Autre', 'contact': 'Autre SA', 'address': 'Rue 1\n1000 Lausanne'})
        for bad, msg in ((str(self.addr_id('Autre')), "n'appartient pas au client"), ('99999', "n'appartient pas au client"), ('abc', 'adresse de facturation inconnue'), ('1; DROP TABLE invoices', 'adresse de facturation inconnue')):
            r, fl = self.edit(iid, billing_address_id=bad); self.assertEqual(r.status_code, 200, bad); self.assertIn(msg, fl)
            self.assertIsNone(self.scalar('SELECT billing_address_id FROM invoices WHERE id=?', (iid,)))

    def test_an_address_too_long_for_the_billing_block_is_refused(self):
        self.seeded(); iid = self.draft_id(); aid = self.addr_id('EGG CH')
        c = sqlite3.connect(self.db); c.execute("UPDATE billing_addresses SET address=? WHERE id=?", ('\n'.join(f'Une ligne d\'adresse numéro {k} assez longue pour passer à la ligne suivante' for k in range(7)), aid)); c.commit(); c.close()
        r, fl = self.edit(iid, billing_address_id=str(aid)); self.assertEqual(r.status_code, 200); self.assertIn('adresse trop longue pour le bloc de facturation', fl)

    # --- issuance, credit notes, snapshots --------------------------------------------------------------------------
    def test_issued_invoice_freezes_the_chosen_address_and_credit_note_prints_it(self):
        self.seeded(); iid = self.draft_id(); aid = self.addr_id('EGG CH'); self.edit(iid, billing_address_id=str(aid)); self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))
        hdr = json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,)))
        self.assertEqual((hdr['billing_label'], hdr['billing_source'], hdr['billing_address_id'], hdr['billing_contact']), ('EGG CH', 'choix', aid, 'EGG CH SA'))
        pdf = self.c.get(f'/invoice/{iid}.pdf').data; self.assertIn('Route de Saint Julien 63', pdf_text(pdf))
        self.c.post(f'/adresses/{aid}', data={'label': 'EGG CH', 'contact': 'Autre nom', 'address': 'Autre rue 1'}); self.c.post(f'/adresses/{aid}', data={'act': 'desactiver'})
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').data, pdf)                                               # an issued invoice never follows (decision D7 / immutability)
        c = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError): c.execute("UPDATE invoices SET bill_address='x' WHERE id=?", (iid,))
        finally: c.close()
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'erreur', 'treatment': 'remboursement', 'scope': 'total'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data); self.assertIn('Route de Saint Julien 63', t); self.assertIn('EGG CH SA', t)

    def test_a_mandate_without_address_becomes_issuable_with_a_chosen_address(self):
        self.c.post('/project', data={'name': 'Mandat sans adresse', 'client': 'Client Fictif', 'rate': '650', 'day_hours': '8', 'client_legal_name': 'Client Fictif SA', 'client_legal_id': LEGAL})
        pid = self.scalar('SELECT id FROM projects WHERE name=?', ('Mandat sans adresse',)); self.entry(pid, '2026-09-10', 16); self.seeded()
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 2)
        self.flashes(); self.issue(iid); self.assertIn('Adresse de facturation', ' '.join(self.flashes())); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        self.edit(iid, billing_address_id=str(self.addr_id('EGG FR'))); self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))
        self.assertIn('FR74 433 639 523', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))

    def test_invoices_without_a_choice_are_unchanged_and_existing_columns_stay_null(self):
        iid = self.draft_id(); self.flashes(); self.issue(iid)
        row = self.sql('SELECT billing_address_id,bill_label,bill_contact,bill_address FROM invoices WHERE id=?', (iid,))[0]; self.assertEqual(tuple(row), (None, None, None, None))
        hdr = json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,))); self.assertEqual(hdr['billing_source'], 'mandat'); self.assertIn('Rue Imaginaire 1', hdr['billing_address'])

    # --- management page --------------------------------------------------------------------------------------------
    def test_management_page_add_edit_duplicate_and_escaping(self):
        self.seeded(); key = rules.legal_key(LEGAL)
        html = text(self.c.get('/adresses')); self.assertIn('EGG FR', html); self.assertIn('Identité juridique', html)
        self.flashes(); self.c.post('/adresses/ajouter', data={'client_key': key, 'label': '<script>alert(1)</script>', 'contact': 'X <b>', 'address': 'Rue <i>1</i>\n1000 Lausanne'})
        page = self.c.get('/adresses').get_data(as_text=True); self.assertNotIn('<script>alert(1)</script>', page); self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
        iid = self.draft_id(); ed = self.c.get(f'/invoice/{iid}/edit').get_data(as_text=True); self.assertNotIn('<script>alert(1)</script>', ed); self.assertNotIn('Rue <i>1</i>', ed)     # menu and preview are escaped too
        self.assertIn('Rue &lt;i&gt;1&lt;/i&gt;', ed)
        self.assertIn('existe déjà', self.post_flash('/adresses/ajouter', {'client_key': key, 'label': 'EGG FR', 'contact': 'x', 'address': 'y'}))
        self.assertIn('client inconnu', self.post_flash('/adresses/ajouter', {'client_key': 'INCONNU', 'label': 'Z', 'contact': '', 'address': 'y'}))
        self.assertIn('adresse trop longue', self.post_flash('/adresses/ajouter', {'client_key': key, 'label': 'Longue', 'contact': 'c', 'address': '\n'.join(str(k) for k in range(8))}))
        self.assertIn('libellé obligatoire', self.post_flash('/adresses/ajouter', {'client_key': key, 'label': ' ', 'contact': '', 'address': 'y'}))
        self.assertEqual(self.c.post('/adresses/999999', data={'label': 'a', 'address': 'b'}).status_code, 404)

    def post_flash(self, url, data):
        self.flashes(); self.c.post(url, data=data); return ' '.join(self.flashes())

    # --- backup / restore and schema --------------------------------------------------------------------------------
    def test_addresses_and_the_choice_survive_a_backup_and_restore(self):
        self.seeded(); iid = self.draft_id(); self.edit(iid, billing_address_id=str(self.addr_id('EGG BE')))
        before_a = [tuple(r) for r in self.sql('SELECT * FROM billing_addresses ORDER BY id')]; before_i = tuple(self.sql('SELECT billing_address_id,bill_label,bill_contact,bill_address FROM invoices WHERE id=?', (iid,))[0])
        raw = self.c.get('/backup').data; self.c.post(f'/adresses/{self.addr_id("EGG FR")}', data={'act': 'desactiver'})
        r = self.c.post('/restore', data={'backup': (io.BytesIO(raw), 'sauvegarde.json')}, content_type='multipart/form-data'); token = r.headers['Location'].rsplit('/', 1)[-1]; self.flashes()
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'}); self.assertIn('Restauration effectuée', ' '.join(self.flashes()))
        self.assertEqual([tuple(r) for r in self.sql('SELECT * FROM billing_addresses ORDER BY id')], before_a)
        self.assertEqual(tuple(self.sql('SELECT billing_address_id,bill_label,bill_contact,bill_address FROM invoices WHERE id=?', (iid,))[0]), before_i)

    def test_migration_is_additive_and_idempotent(self):
        cols = {r['name'] for r in self.sql('PRAGMA table_info(invoices)')}; self.assertTrue({'billing_address_id', 'bill_label', 'bill_contact', 'bill_address'} <= cols)
        m.init(); m.init(); self.assertEqual(self.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name='billing_addresses'"), 1)
        from app import restore_service
        self.assertLess(restore_service.ORDER.index('projects'), restore_service.ORDER.index('billing_addresses'))

    def test_client_key_groups_by_legal_identity_with_the_short_name_as_fallback(self):
        K = address_service.client_key
        self.assertEqual(K({'client_legal_id': 'che-123.456.789 TVA', 'client': 'A'}), K({'client_legal_id': 'CHE123456789', 'client': 'B'}))
        self.assertEqual(K({'client_legal_id': '', 'client': '  EGG  Group '}), 'NOM:egg group'); self.assertEqual(K({'client_legal_id': '', 'client': ''}), '')
        self.assertNotEqual(K({'client_legal_id': '', 'client': 'CHE123456789'}), K({'client_legal_id': 'CHE123456789', 'client': ''}))


if __name__ == '__main__':
    unittest.main()
