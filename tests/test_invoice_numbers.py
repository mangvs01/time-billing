"""rc37 (P3) — invoice numbers: AAAA-N proposed from the draft, reserved by the draft, editable, globally unique (case and spaces ignored), never silently replaced.
Synthetic data only."""
import io, json, os, re, sqlite3, threading, unittest, unittest.mock as mock

import app.app as m
from app import billing_rules as rules, pdf_layout, schema_checks, restore_service
from tests import test_g4
from tests.test_functional import pdf_text
from tests.test_g4 import text
from tests.test_invoice_lines import draw_calls, page_one

YEAR = rules.local_today().year


class Unit(unittest.TestCase):
    def test_format_rules(self):
        ok = ['2026-11', 'A', 'a1', '2026-1', 'EXT/5', 'X-1/B', '1' * 20]
        for v in ok: self.assertEqual(rules.check_invoice_number(v), v)
        self.assertEqual(rules.check_invoice_number('  2026-11  '), '2026-11')
        bad = {'': 'vide', '   ': 'vide', '1' * 21: 'trop long', '2026.11': 'invalide', '2026_11': 'invalide', '20%26': 'invalide', 'NC-2026-1': 'réservé', 'nc-1': 'réservé',
               '2026 11': 'invalide', '-2026': 'invalide', '/x': 'invalide', '2026-1\n2': 'invalide', 'é-1': 'invalide', '２０２６-1': 'invalide', "2026-1';--": 'invalide', '<b>': 'invalide'}
        for v, why in bad.items():
            with self.assertRaises(ValueError, msg=repr(v)) as e: rules.check_invoice_number(v)
            self.assertIn(why, str(e.exception), repr(v))

    def test_parse_number_reads_both_formats(self):
        P = rules.parse_number
        self.assertEqual(P('2026-11'), (2026, 11)); self.assertEqual(P('2026-09'), (2026, 9)); self.assertEqual(P('2026-09-3'), (2026, 9)); self.assertEqual(P('2026-001'), (2026, 1))
        for v in ('EXT/5', '2026', '2026-', 'x2026-1', '2026-1-2-3', None, ''): self.assertIsNone(P(v), v)

    def test_number_key_ignores_case_and_surrounding_spaces(self):
        self.assertEqual(rules.number_key(' a-1 '), rules.number_key('A-1'))


class Numbers(test_g4.G4):
    checks = test_g4.Checks.checks
    RECORD_WORK = True

    def number(self, iid): return self.scalar('SELECT number FROM invoices WHERE id=?', (iid,))

    def new(self, f='2026-09-01', t='2026-09-30', qty=2, **kw):
        iid, fl = self.draft(self.pid, f, t, qty, **kw); self.assertIn('Brouillon créé.', fl); return iid

    def rev(self, iid): return str(self.scalar('SELECT revision FROM invoices WHERE id=?', (iid,)))

    def edit(self, iid, **over):
        d = dict(period_from='2026-09-01', period_to='2026-09-30', qty='2', unit='day', rounding='exact', rounding_step='0.25', vat='0', description='Prestation', other_amount='0',
                 other_label='', other_vat_mode='hors_tva', invoice_date='', note='', revision=self.rev(iid)); d.update(over)
        self.flashes(); r = self.c.post(f'/invoice/{iid}/edit', data=d)
        return r, ' '.join(self.flashes()) + (' ' + text(r) if r.status_code == 200 else '')

    def sqlw(self, q, a=()):
        c = sqlite3.connect(self.db)
        try: c.execute(q, a); c.commit()
        finally: c.close()

    def legacy_issued(self, number, project=None):
        pid = project or self.pid
        self.sqlw("INSERT INTO invoices(number,project_id,period_from,period_to,qty,unit,unit_rate,status,issued_at) VALUES(?,?,'2025-01-01','2025-01-31',1,'day',650,'issued','2025-02-01T10:00:00')", (number, pid))

    # --- proposal and reservation ----------------------------------------------------------------------------------
    def test_the_draft_gets_the_next_number_of_the_year_at_once_and_a_deleted_one_is_free_again(self):
        a, b = self.new(), self.new('2026-09-01', '2026-09-30', 1)
        self.assertEqual((self.number(a), self.number(b)), (f'{YEAR}-1', f'{YEAR}-2'))
        self.assertEqual(self.scalar('SELECT number_manual FROM invoices WHERE id=?', (a,)), 0)
        self.c.post(f'/invoice/{a}/delete')
        self.assertIn(f'number_released={YEAR}-1', self.scalar("SELECT detail FROM audit WHERE event='draft_deleted' ORDER BY id DESC LIMIT 1"))
        c = self.new('2026-09-01', '2026-09-30', 1); self.assertEqual(self.number(c), f'{YEAR}-1')                # the first free one is proposed (decision D5 b)

    def test_the_creation_message_names_the_reserved_number(self):
        self.flashes(); self.c.post('/invoice', data={'project_id': self.pid, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2'})
        self.assertIn(f'Numéro de facture proposé et réservé : {YEAR}-1', ' '.join(self.flashes()))

    def test_each_year_has_its_own_sequence_the_year_is_the_one_of_the_invoice_date(self):
        iid = self.new('2025-12-01', '2025-12-31', 1, invoice_date='2025-12-31')
        self.assertEqual(self.number(iid), '2025-1')
        j = self.new(); self.assertEqual(self.number(j), f'{YEAR}-1')
        self.edit(j, invoice_date='2026-09-30')                                                          # automatic number follows the year of the date
        self.assertEqual(self.number(j), '2026-1')
        r, fl = self.edit(j, invoice_date='')                                                              # back to « date of issuance » = today's year
        self.assertEqual(self.number(j), f'{YEAR}-1')

    def test_numbers_of_earlier_releases_and_external_ones_count_as_taken(self):
        Y = YEAR
        self.legacy_issued(f'{Y}-10')                                                                     # the owner's example: last invoice 2026-10 → next 2026-11
        self.assertEqual(self.number(self.new()), f'{Y}-11')
        self.legacy_issued(f'{Y}-09-3', self.mandate(name='Autre mandat', legal_id='CHE-000.000.002'))    # AAAA-MM-N: its month is the sequence
        self.assertEqual(self.number(self.new('2026-09-01', '2026-09-30', 1)), f'{Y}-12')
        with mock.patch.dict(os.environ, {'EXTERNAL_INVOICE_NUMBERS': f'{Y}-20, {Y}-14'}):
            self.assertEqual(self.number(self.new('2026-09-01', '2026-09-30', 1)), f'{Y}-21')
        pid = self.mandate(name='Mandat historique', legal_id='CHE-000.000.003')
        self.hist(pid=pid, date='2026-10-01', days=1.0, amount=650.0, cell='Q12', invoice_ref=f'{Y}-30')       # any status of historical invoice counts
        self.assertEqual(self.number(self.new('2026-09-01', '2026-09-30', 1)), f'{Y}-31')

    def test_a_draft_number_higher_than_the_issued_ones_does_not_move_the_next_proposal_past_gaps(self):
        a = self.new(); b = self.new('2026-09-01', '2026-09-30', 1)
        self.edit(b, number=f'{YEAR}-9')                                                                   # manual, leaves 2..8 free
        c = self.new('2026-09-01', '2026-09-30', 1); self.assertEqual(self.number(c), f'{YEAR}-2')

    # --- editing: validation and conflicts -----------------------------------------------------------------------------
    def test_a_typed_number_is_saved_flagged_manual_and_traced(self):
        iid = self.new(); r, fl = self.edit(iid, number='EXT/2026-77')
        self.assertEqual(r.status_code, 302, fl); self.assertIn('Numéro de facture saisi : EXT/2026-77', fl)
        self.assertEqual((self.number(iid), self.scalar('SELECT number_manual FROM invoices WHERE id=?', (iid,))), ('EXT/2026-77', 1))
        row = self.sql('SELECT old_number,new_number,manual,context FROM invoice_number_changes WHERE invoice_id=? ORDER BY id', (iid,))
        self.assertEqual([tuple(r) for r in row], [(None, f'{YEAR}-1', 0, 'création du brouillon'), (f'{YEAR}-1', 'EXT/2026-77', 1, 'modification du brouillon')])
        self.assertIn('from=%s-1;to=EXT/2026-77;manual=1' % YEAR, self.scalar("SELECT detail FROM audit WHERE event='draft_number_changed' ORDER BY id DESC LIMIT 1"))
        html = text(self.c.get(f'/invoice/{iid}/edit')); self.assertIn('value="EXT/2026-77"', html); self.assertIn('saisi à la main', html); self.assertIn('Historique du numéro', html)

    def test_invalid_numbers_are_refused_with_the_reason_and_nothing_changes(self):
        iid = self.new(); before = self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]
        for bad, why in (('2026.11', 'numéro invalide'), ('2026_11', 'numéro invalide'), ('20%26', 'numéro invalide'), ('NC-2026-1', 'réservé aux notes de crédit'), ('x' * 21, 'trop long'),
                         ('2026 11', 'numéro invalide'), ('é1', 'numéro invalide')):
            r, fl = self.edit(iid, number=bad); self.assertEqual(r.status_code, 200, bad); self.assertIn(why, fl, bad)
            self.assertEqual(tuple(self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]), tuple(before), bad)

    def test_conflicts_are_explained_per_holder_and_a_free_number_is_only_proposed(self):
        other = self.mandate(name='Mandat voisin', legal_id='CHE-000.000.004'); self.entry(other, '2026-09-10', 16)
        a = self.new(); self.legacy_issued('ISS-1'); self.sqlw("INSERT INTO invoice_number_changes(invoice_id,context,changed_at) VALUES(0,'x','')")
        b, _ = self.draft(other, '2026-09-01', '2026-09-30', 1)
        pid_h = self.mandate(name='Mandat historique', legal_id='CHE-000.000.005'); self.hist(pid=pid_h, date='2026-09-30', days=1.0, amount=650.0, cell='Q13', invoice_ref='HIST-9')
        keep = self.number(b)
        with mock.patch.dict(os.environ, {'EXTERNAL_INVOICE_NUMBERS': 'EXTN-3'}):
            cases = ((f'{YEAR}-1', 'le brouillon n°'), ('iss-1', 'la facture émise ISS-1'), (' hist-9 ', 'une facture historique (hors application) n° HIST-9'), ('extn-3', 'un numéro de facture externe réservé (EXTN-3)'))
            for typed, who in cases:
                r, fl = self.edit(b, number=typed, period_from='2026-09-01', qty='1'); self.assertEqual(r.status_code, 200, typed)
                self.assertIn('est déjà utilisé par ' + who, fl, typed); self.assertIn('numéro libre proposé :', fl); self.assertIn("aucun numéro n'est jamais remplacé automatiquement", fl)
                self.assertEqual(self.number(b), keep, typed)                                              # nothing was replaced
        r, fl = self.edit(b, number=f'{YEAR}-2', period_from='2026-09-01', qty='1'); self.assertEqual(r.status_code, 302, fl)    # the proposed one is free

    def test_the_proposed_number_in_a_conflict_message_is_really_free(self):
        a = self.new(); b = self.new('2026-09-01', '2026-09-30', 1)
        r, fl = self.edit(b, number=self.number(a), qty='1'); proposed = re.search(r'numéro libre proposé : (\S+?)\.', fl).group(1)
        self.assertIsNone(rules.number_conflict(m.db(), proposed, exclude_id=b))        # free for this draft (here: its own reserved number)

    def test_blank_number_goes_back_to_the_automatic_proposal(self):
        iid = self.new(); self.edit(iid, number='ZZ-1'); self.assertEqual(self.scalar('SELECT number_manual FROM invoices WHERE id=?', (iid,)), 1)
        r, fl = self.edit(iid, number=''); self.assertEqual(r.status_code, 302, fl)
        self.assertEqual((self.number(iid), self.scalar('SELECT number_manual FROM invoices WHERE id=?', (iid,))), (f'{YEAR}-1', 0))

    def test_saving_without_touching_the_number_keeps_it_and_old_forms_without_the_field_too(self):
        iid = self.new(); n = self.number(iid)
        self.edit(iid, number=n); self.assertEqual((self.number(iid), self.scalar('SELECT number_manual FROM invoices WHERE id=?', (iid,))), (n, 0))
        r = self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25', 'vat': '0'})
        self.assertEqual(r.status_code, 302); self.assertEqual(self.number(iid), n)

    def test_case_and_space_variants_are_the_same_number(self):
        a = self.new(); self.edit(a, number='Ab-1'); b = self.new('2026-09-01', '2026-09-30', 1)
        for v in ('ab-1', 'AB-1', ' Ab-1 '):
            r, fl = self.edit(b, number=v, qty='1'); self.assertEqual(r.status_code, 200, v); self.assertIn('est déjà utilisé', fl, v)
        c = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError): c.execute('UPDATE invoices SET number=? WHERE id=?', ('aB-1', b))                  # the database says it too (NOCASE index)
        finally: c.close()

    def test_database_triggers_refuse_a_historical_number_on_a_draft(self):
        pid = self.mandate(name='Mandat historique', legal_id='CHE-000.000.006'); self.hist(pid=pid, date='2026-09-30', days=1.0, amount=650.0, cell='Q14', invoice_ref='REAL-5')
        iid = self.new(); c = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError) as e: c.execute('UPDATE invoices SET number=? WHERE id=?', (' real-5', iid))
            self.assertIn('historical', str(e.exception))
        finally: c.close()

    # --- PDF and screens ------------------------------------------------------------------------------------------------
    def test_the_draft_pdf_prints_the_proposed_number_and_the_old_wording_is_gone(self):
        iid = self.new(); t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn(f'{YEAR}-1 (proposé)', t); self.assertNotIn("(attribué à l'émission)", t)
        self.edit(iid, number='NEW-7'); self.assertIn('NEW-7 (proposé)', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))

    def test_the_planned_date_and_the_number_do_not_overlap_on_page_one_of_the_draft_pdf(self):
        iid = self.new(invoice_date='2026-09-30')
        calls = page_one(draw_calls(lambda: self.c.get(f'/invoice/{iid}.pdf')))
        date = next(c for c in calls if c[2].endswith('(prévue)')); num = next(c for c in calls if c[2].endswith('(proposé)'))
        self.assertEqual(date[0], num[0]); self.assertEqual(round(num[1] - date[1], 2), pdf_layout.DRAFT_REF_ROW_PITCH)       # same column, 14 pt apart: the 10.9 pt line boxes of 8 pt type leave 3 pt (11.1 pt left them touching)
        self.flashes(); issued = page_one(draw_calls(lambda: self.issue(iid)))                                      # the ISSUED document keeps the reference pitch (11.1 pt)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))
        d2 = next(c for c in issued if c[2] == '30.09.2026'); n2 = next(c for c in issued if c[2] == f'{YEAR}-1'); self.assertEqual(round(n2[1] - d2[1], 2), 11.1)
        from reportlab.pdfbase import pdfmetrics
        self.assertLess(pdfmetrics.stringWidth(num[2], pdf_layout.BODY, 8), 555 - num[0])                   # and it stays on the page
        self.assertLess(max(c[1] for c in calls if c[1] < 120) , 125)

    def test_the_archive_list_shows_the_reserved_number_of_a_draft(self):
        iid = self.new(); html = text(self.c.get('/?tab=archive')); self.assertIn(f'{YEAR}-1', html); self.assertIn('réservé (brouillon)', html)

    # --- issuance --------------------------------------------------------------------------------------------------------
    def test_issuance_keeps_the_reserved_number_and_it_is_the_same_everywhere(self):
        import zipfile
        iid = self.new(); self.edit(iid, number='EXT/42'); self.flashes(); shown = text(self.c.get(f'/issue/{iid}'))
        self.assertIn('<b>EXT/42</b>', shown); self.assertIn('name="expected_number" value="EXT/42"', self.c.get(f'/issue/{iid}').get_data(as_text=True))
        self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))
        self.assertEqual(self.number(iid), 'EXT/42'); self.assertEqual(self.scalar('SELECT number FROM invoice_snapshots WHERE invoice_id=?', (iid,)), 'EXT/42')
        self.assertEqual(json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,)))['number'], 'EXT/42')
        pdf = self.c.get(f'/invoice/{iid}.pdf'); self.assertIn('EXT/42', pdf_text(pdf.data)); self.assertNotIn('(proposé)', pdf_text(pdf.data))
        z = zipfile.ZipFile(io.BytesIO(self.c.get('/archive.zip').data)); self.assertTrue(any(n.startswith('factures/facture-EXT_42') for n in z.namelist()), z.namelist())
        self.assertIn('EXT/42', z.read('index.csv').decode('utf-8-sig'))
        self.assertIn('EXT/42', self.scalar("SELECT detail FROM audit WHERE event='invoice_issued' ORDER BY id DESC LIMIT 1"))
        self.assertEqual(self.sql('SELECT new_number,context FROM invoice_number_changes WHERE invoice_id=? ORDER BY id DESC', (iid,))[0][1], 'modification du brouillon')   # issuance kept it: no new change
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'erreur', 'treatment': 'remboursement', 'scope': 'total'}); cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.assertEqual(self.scalar('SELECT reference FROM credit_notes WHERE id=?', (cid,)), 'NC-EXT/42')                          # NC-<n°>; the « . » suffix is for the 2nd note (no « . » in numbers)
        self.assertIn('NC-EXT/42', pdf_text(self.c.get(f'/credit/{cid}.pdf').data))

    def test_numbering_of_credit_notes_with_the_new_format(self):
        iid = self.new(); self.flashes(); self.issue(iid)
        for k in range(2): self.c.post(f'/invoice/{iid}/credit', data={'reason': 'r', 'amount': '100', 'treatment': 'remboursement'}); self.c.post(f'/credit/{self.scalar("SELECT MAX(id) FROM credit_notes")}/issue')
        self.assertEqual([r[0] for r in self.sql('SELECT reference FROM credit_notes ORDER BY id')], [f'NC-{YEAR}-1', f'NC-{YEAR}-1.2'])

    def test_legacy_draft_without_number_shows_a_proposal_reserves_it_on_save_and_is_issued_with_it(self):
        iid = self.new(); self.sqlw('UPDATE invoices SET number=NULL WHERE id=?', (iid,))
        html = self.c.get(f'/invoice/{iid}/edit').get_data(as_text=True); self.assertIn(f'value="{YEAR}-1"', html); self.assertIn('name="number_proposed"', html); self.assertIn('pas encore réservé', text(self.c.get(f'/invoice/{iid}/edit')))
        self.assertIn(f'{YEAR}-1 (proposé)', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))
        self.assertIsNone(self.number(iid))                                                              # a GET writes nothing
        self.edit(iid, number=f'{YEAR}-1', number_proposed=f'{YEAR}-1')
        self.assertEqual((self.number(iid), self.scalar('SELECT number_manual FROM invoices WHERE id=?', (iid,))), (f'{YEAR}-1', 0))
        j = self.new('2026-08-01', '2026-08-31', 1); self.sqlw('UPDATE invoices SET number=NULL WHERE id=?', (j,)); self.flashes(); self.issue(j)      # issued without having been saved: takes the first free number
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (j,)), 'issued', ' '.join(self.flashes())); self.assertEqual(self.number(j), f'{YEAR}-2')

    def test_an_automatic_number_follows_the_year_of_the_printed_date_at_issuance(self):
        iid = self.new(); self.sqlw("UPDATE invoices SET number='2025-77' WHERE id=?", (iid,))               # proposed last year, issued today (no date set)
        self.assertIn(f'<b>{YEAR}-1</b>', text(self.c.get(f'/issue/{iid}')))
        self.flashes(); self.issue(iid); self.assertEqual(self.number(iid), f'{YEAR}-1')
        self.assertEqual(self.sql('SELECT old_number,new_number,context FROM invoice_number_changes WHERE invoice_id=? ORDER BY id DESC', (iid,))[0][2], 'émission')
        k = self.new('2026-08-01', '2026-08-31', 1); self.edit(k, number='2025-99', qty='1', period_from='2026-08-01', period_to='2026-08-31'); self.flashes(); self.issue(k)           # a number typed by hand is kept as typed
        self.assertEqual(self.number(k), '2025-99')

    def test_the_issue_form_refuses_a_number_that_changed_since_the_page_was_shown(self):
        iid = self.new(); self.flashes()
        self.c.post(f'/issue/{iid}', data={'reliquat_treatment': 'reporte', 'expected_number': 'AUTRE-1', 'confirm_backdate': '2026-09-30'})
        self.assertIn('le numéro de facture a changé depuis l\'affichage', ' '.join(self.flashes())); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')

    def test_a_conflict_that_appears_after_the_reservation_stops_the_issuance_explicitly(self):
        iid = self.new(); n = self.number(iid)
        pid = self.mandate(name='Mandat historique', legal_id='CHE-000.000.007'); self.hist(pid=pid, date='2026-09-30', days=1.0, amount=650.0, cell='Q15', invoice_ref=n.lower())   # a real invoice printed with it
        self.flashes(); self.issue(iid); fl = ' '.join(self.flashes())
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft'); self.assertIn('Émission refusée', fl); self.assertIn('une facture historique (hors application)', fl)
        self.assertIn("modifier le numéro du brouillon avant d'émettre", fl); self.assertEqual(self.number(iid), n)                       # nothing replaced
        self.edit(iid, number=f'{YEAR}-50'); self.flashes(); self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued')

    def test_an_issued_invoice_is_never_renumbered(self):
        iid = self.new(); self.flashes(); self.issue(iid); n = self.number(iid)
        r = self.c.post(f'/invoice/{iid}/edit', data=dict(period_from='2026-09-01', period_to='2026-09-30', qty='2', unit='day', vat='0', number='HACK-1'))
        self.assertIn('Seul un brouillon peut être modifié', ' '.join(self.flashes())); self.assertEqual(self.number(iid), n)
        c = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError): c.execute("UPDATE invoices SET number='HACK-2' WHERE id=?", (iid,))
            with self.assertRaises(sqlite3.DatabaseError): c.execute("UPDATE invoice_number_changes SET new_number='x'")
            with self.assertRaises(sqlite3.DatabaseError): c.execute('DELETE FROM invoice_number_changes')
        finally: c.close()

    def test_an_invoice_cannot_be_issued_without_a_number_at_database_level(self):
        iid = self.new(); self.sqlw('UPDATE invoices SET number=NULL WHERE id=?', (iid,))
        c = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError) as e: c.execute("UPDATE invoices SET status='issued',issued_at='2026-10-01T00:00:00',invoice_date='2026-10-01' WHERE id=?", (iid,))
            self.assertIn('needs a number', str(e.exception))
        finally: c.close()

    # --- concurrency ---------------------------------------------------------------------------------------------------------
    def test_concurrent_creations_never_share_a_number(self):
        out = []; barrier = threading.Barrier(6)
        def worker(k):
            c = m.APP.test_client(); c.post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']}); barrier.wait()
            c.post('/invoice', data={'project_id': self.pid, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1'}); out.append(k)
        ts = [threading.Thread(target=worker, args=(k,)) for k in range(6)]; [t.start() for t in ts]; [t.join() for t in ts]
        nums = [r[0] for r in self.sql('SELECT number FROM invoices ORDER BY id')]
        self.assertEqual(len(nums), 6); self.assertEqual(len(set(nums)), 6); self.assertEqual(sorted(nums), [f'{YEAR}-{k}' for k in range(1, 7)])

    def test_concurrent_edits_to_the_same_number_only_one_wins_the_other_gets_the_explanation(self):
        a, b = self.new(), self.new('2026-09-01', '2026-09-30', 1); res = {}; barrier = threading.Barrier(2)
        def worker(k, iid, qty):
            c = m.APP.test_client(); c.post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']}); barrier.wait()
            r = c.post(f'/invoice/{iid}/edit', data=dict(period_from='2026-09-01', period_to='2026-09-30', qty=qty, unit='day', vat='0', number='RACE-1', revision='0'))
            res[k] = (r.status_code, r.get_data(as_text=True))
        ts = [threading.Thread(target=worker, args=('a', a, '2')), threading.Thread(target=worker, args=('b', b, '1'))]; [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(sorted(v[0] for v in res.values()), [200, 302]); loser = next(v for v in res.values() if v[0] == 200)[1]
        import html
        self.assertIn('RACE-1 est déjà utilisé par', html.unescape(loser)); self.assertIn('numéro libre proposé :', html.unescape(loser))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM invoices WHERE number='RACE-1'"), 1)

    def test_after_one_draft_is_issued_under_a_number_no_other_row_can_take_it_even_by_case(self):
        a = self.new(); b = self.new('2026-08-01', '2026-08-31', 1)
        self.edit(a, number='RACE-2'); self.flashes(); self.issue(a); self.assertEqual(self.number(a), 'RACE-2')
        r, fl = self.edit(b, number='race-2', qty='1', period_from='2026-08-01', period_to='2026-08-31'); self.assertEqual(r.status_code, 200); self.assertIn('est déjà utilisé par la facture émise RACE-2', fl)
        c = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError): c.execute('UPDATE invoices SET number=? WHERE id=?', ('Race-2', b))
        finally: c.close()

    # --- migration, schema checks, backup --------------------------------------------------------------------------------
    def test_migration_creates_the_normalised_index_and_is_idempotent(self):
        c = sqlite3.connect(self.db)
        try:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='idx_invoices_number_norm'").fetchone()[0], 1)
            m.init(); m.init(); self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='idx_invoices_number_norm'").fetchone()[0], 1)
            self.assertEqual(schema_checks.rc19_problems(c), [])
        finally: c.close()

    def test_migration_skips_the_index_when_the_data_already_holds_a_case_duplicate_and_says_so(self):
        c = sqlite3.connect(self.db); c.execute('DROP INDEX idx_invoices_number_norm')
        c.execute("INSERT INTO invoices(number,project_id,period_from,period_to,qty,unit,unit_rate,status,issued_at) VALUES('dup-1',?,'2025-01-01','2025-01-31',1,'day',1,'issued','2025-02-01T10:00:00')", (self.pid,))
        c.execute("INSERT INTO invoices(number,project_id,period_from,period_to,qty,unit,unit_rate,status,issued_at) VALUES('DUP-1',?,'2025-02-01','2025-02-28',1,'day',1,'issued','2025-03-01T10:00:00')", (self.pid,)); c.commit(); c.close()
        m.init()                                                                                          # must not stop the start-up
        c = sqlite3.connect(self.db)
        try:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='idx_invoices_number_norm'").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE event='invoice_number_index_skipped'").fetchone()[0], 1)
            m.init(); self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE event='invoice_number_index_skipped'").fetchone()[0], 1)     # said once
            pb = schema_checks.rc19_problems(c); self.assertTrue(any('index d\'unicité normalisée' in p and 'DUP-1' in p for p in pb), pb)
        finally: c.close()

    def test_the_history_and_the_flag_survive_a_backup_and_restore(self):
        iid = self.new(); self.edit(iid, number='KEEP/1'); before = [tuple(r) for r in self.sql('SELECT * FROM invoice_number_changes ORDER BY id')]
        raw = self.c.get('/backup').data; self.edit(iid, number='OTHER-2')
        r = self.c.post('/restore', data={'backup': (io.BytesIO(raw), 'sauvegarde.json')}, content_type='multipart/form-data'); token = r.headers['Location'].rsplit('/', 1)[-1]; self.flashes()
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'}); self.assertIn('Restauration effectuée', ' '.join(self.flashes()))
        self.assertEqual((self.number(iid), self.scalar('SELECT number_manual FROM invoices WHERE id=?', (iid,))), ('KEEP/1', 1))
        self.assertEqual([tuple(r) for r in self.sql('SELECT * FROM invoice_number_changes ORDER BY id')], before)
        self.assertLess(restore_service.ORDER.index('invoice_number_changes'), restore_service.ORDER.index('invoices'))

    # --- historical validation --------------------------------------------------------------------------------------------
    def test_a_draft_only_reserves_a_number_a_historical_row_with_it_is_not_refused_as_a_time_billing_number(self):
        iid = self.new(); n = self.number(iid)
        pid = self.mandate(name='Mandat historique', legal_id='CHE-000.000.008'); hid = self.hist(pid=pid, date='2026-09-30', days=1.0, amount=650.0, cell='Q16', invoice_ref=n)
        r, fl = self.set_status(hid, 'validated')
        self.assertEqual(self.sql('SELECT status FROM historical_invoices WHERE id=?', (hid,))[0][0], 'validated', fl)                    # the real invoice exists: the fact wins ...
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')         # ... and the draft must change its number


class MigrationFromRc36(test_g4.G4):
    """The additive migration on a database that has the rc36 shape (new tables, columns, triggers and index removed) and rc36-style data: nothing existing changes."""
    RECORD_WORK = True

    def test_additive_migration_keeps_every_existing_row_and_creates_the_new_objects(self):
        i1, _ = self.draft(self.pid, '2026-08-01', '2026-08-31', 1); self.flashes(); self.issue(i1)
        i2, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)                                       # a draft
        c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
        self.assertEqual(c.execute('SELECT status FROM invoices WHERE id=?', (i1,)).fetchone()[0], 'issued')
        c.execute('UPDATE invoices SET number=NULL WHERE id=?', (i2,))                                      # rc36: a draft has no number
        for t in ('invoice_lines_no_insert_frozen', 'invoice_lines_no_update_issued', 'invoice_lines_no_delete_issued', 'invoice_number_changes_no_update', 'invoice_number_changes_no_delete',
                  'invoice_number_not_historical_ins', 'invoice_number_not_historical_upd', 'invoice_issue_needs_number'): c.execute(f'DROP TRIGGER {t}')
        c.execute('DROP INDEX idx_invoices_number_norm'); c.execute('DROP INDEX idx_number_changes_invoice')
        c.execute('DROP TRIGGER credit_lines_totals_match'); c.execute('DROP TABLE credit_note_lines')             # rc38 objects that point to invoice_lines: removed first (an rc36 base has neither)
        for t in ('invoice_lines', 'billing_addresses', 'invoice_number_changes'): c.execute(f'DROP TABLE {t}')
        for col in ('revision', 'billing_address_id', 'bill_label', 'bill_contact', 'bill_address', 'number_manual'): c.execute(f'ALTER TABLE invoices DROP COLUMN {col}')
        c.commit()
        old_cols = [r[1] for r in c.execute('PRAGMA table_info(invoices)')]
        before = {t: [tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in ('invoices', 'invoice_snapshots', 'invoice_annex_entries', 'projects', 'entries', 'settings', 'audit')}
        self.assertEqual(len(schema_checks.rc19_problems(c)) > 0, True)                                      # the rc37 checks do see the rc36 shape
        c.close()
        m.init(); m.init()                                                                                  # restart twice
        c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
        try:
            now = {t: [tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in ('invoices', 'invoice_snapshots', 'invoice_annex_entries', 'projects', 'entries', 'settings')}
            for t in ('invoice_snapshots', 'invoice_annex_entries', 'projects', 'entries', 'settings'): self.assertEqual(now[t], before[t], t)
            width = len(old_cols)
            self.assertEqual([r[:width] for r in now['invoices']], before['invoices'])                         # every old column of every invoice is untouched
            self.assertEqual([r[width:] for r in now['invoices']], [(0, None, None, None, None, 0)] * 2)       # new columns: revision 0, no address, number_manual 0
            self.assertEqual(c.execute('SELECT number FROM invoices WHERE id=?', (i2,)).fetchone()[0], None)    # a draft created before rc37 stays without number until saved or issued
            self.assertEqual(schema_checks.rc19_problems(c), [])
            self.assertEqual([r[0] for r in c.execute("SELECT event FROM audit WHERE id>?", (before['audit'][-1][0],))], [])    # the migration writes nothing to the audit log
        finally: c.close()
        j = self.sql('SELECT status FROM invoices WHERE id=?', (i2,))[0][0]; self.assertEqual(j, 'draft')
        self.flashes(); self.issue(i2); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (i2,)), 'issued', ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (i2,)), f'{YEAR}-1' if self.scalar('SELECT number FROM invoices WHERE id=?', (i1,)) != f'{YEAR}-1' else f'{YEAR}-2')


if __name__ == '__main__':
    unittest.main()
