"""Revue adverse indépendante rc37 → rc40 (lignes manuelles, avoirs sur lignes, adresses, numérotation AAAA-N, PDF, exports, restauration) — tests NÉGATIFS.
Voir docs/FACTURES-REVUE-RC40.md (gravités, preuves, décision). Données synthétiques uniquement ; aucun caractère arabe littéral (les caractères de direction sont écrits en séquences \\u).

Classes :
  Unit          fonctions pures (clé de numéro, validation des lignes, texte des adresses, arrondis, cohérence écran / PDF) — sans base
  Numbers       collisions de numéros (zéros de tête AAAA-MM / AAAA-N, casse, espaces)
  Concurrency   deux avoirs / deux émissions simultanés sur la même ligne
  Injection     champs libres des lignes dans les écrans et le PDF
  RestoreForged sauvegarde falsifiée (lignes manuelles / lignes créditées d'un document émis)
  OpenDefects   défauts CONFIRMÉS mais NON corrigés (@expectedFailure : « succès inattendu » = corrigé, retirer le décorateur)
Écrit sans être exécuté (le superviseur lance les tests, runner isolé)."""
import html as H, io, json, os, random, re, threading, unittest
from decimal import Decimal, ROUND_HALF_UP

import app.app as m
from app import address_service, billing_rules as rules, invoice_lines, pdf_layout, restore_service
from tests import test_credit_lines as tcl
from tests.test_functional import pdf_text
from tests.test_invoice_lines import line

D = Decimal
CENT = D('0.01')


def hu(r): return H.unescape(r.get_data(as_text=True))


def row(desc='Frais', qty='1', rate='10', vat='soumis'):
    return {'line_id': '', 'line_uid': '', 'line_description': desc, 'line_qty': qty, 'line_unit': 'flat', 'line_rate': rate, 'line_vat_mode': vat}


# ===================================================================================================================================================
class Unit(unittest.TestCase):
    def test_number_key_unifies_leading_zeros_of_the_numeric_formats(self):
        K = rules.number_key
        self.assertEqual(K('2026-09'), K('2026-9')); self.assertEqual(K('2026-009'), K(' 2026-9 ')); self.assertEqual(K('2026-09-2'), K('2026-9-2'))
        self.assertEqual(K('ab-1'), K('AB-1')); self.assertEqual(K(' a-1 '), K('A-1'))
        for a, b in (('2026-10', '2026-1'), ('2026-9', '2026-9-2'), ('2026-9', '2027-9'), ('EXT/5', 'EXT/05'), ('2026-09', '2026-90')):
            self.assertNotEqual(K(a), K(b), (a, b))

    def test_invoice_number_format_refuses_what_could_break_references_and_files(self):
        self.assertEqual(rules.check_invoice_number('2026-1 '), '2026-1')                                  # surrounding spaces are trimmed, nothing else
        for v in ('NC-5', 'nc-5', '2026\u202e-1', '2026\u200b-1', '20 26', '2026.1', '2026_1', '../x', 'a\\b', '2026-1;', '\u0663-1', '1' * 21, "'; DROP", '<b>1</b>', '%41'):
            with self.assertRaises(ValueError, msg=repr(v)): rules.check_invoice_number(v)

    def test_manual_line_description_refuses_invisible_control_and_direction_characters(self):
        for bad in ('A\u202eB', 'A\u200bB', 'A\u2066B', 'A\u2067B', 'A\u2069B', 'A\u061cB', 'A\u00adB', 'A\x00B', 'A\x1bB', 'A\x7fB', 'A\x90B', 'A\ufeffB'):
            with self.assertRaises(ValueError, msg=repr(bad)) as e: invoice_lines.validate([row(bad)])
            self.assertIn('description invalide', str(e.exception))
        self.assertEqual(invoice_lines.validate([row('Frais « déplacement » – à 100 % <ok> & =cmd')])[0]['description'], 'Frais « déplacement » – à 100 % <ok> & =cmd')   # visible text is kept

    def test_manual_line_quantity_that_rounds_to_zero_is_refused_before_the_table_does(self):
        with self.assertRaises(ValueError) as e: invoice_lines.validate([row(qty='0.0000004')])
        self.assertIn('quantité invalide', str(e.exception))
        self.assertEqual(invoice_lines.validate([row(qty='0.000001')])[0]['qty'], 0.000001)

    def test_manual_lines_stay_under_one_billion_per_line_and_in_total(self):
        self.assertEqual(invoice_lines.validate([row(qty='1', rate='1000000000')])[0]['unit_rate'], 1e9)
        with self.assertRaises(ValueError) as e: invoice_lines.validate([row(qty='2', rate='1000000000')])
        self.assertIn('au-dessus de la limite', str(e.exception))
        with self.assertRaises(ValueError) as e: invoice_lines.validate([row('a', '1', '600000000'), row('b', '1', '600000000')])
        self.assertIn('total des lignes manuelles', str(e.exception))

    def test_address_text_loses_direction_isolates_controls_and_soft_hyphens(self):
        label, contact, addr = address_service.validate('EGG\u2067 FR', 'M.\u202e X', 'Rue\u00ad 1\u2066\nBern\x90')
        self.assertEqual((label, contact, addr), ('EGG FR', 'M. X', 'Rue 1\nBern'))
        for v in (label, contact, addr): self.assertIsNone(re.search('[\u2066-\u2069\u202a-\u202e\u00ad\x80-\x84\x86-\x9f]', v))

    def test_printed_quantity_times_printed_price_is_the_printed_amount(self):
        """The reader multiplies what the PDF prints: quantity (≤ 6 decimals) × unit price (≤ 4 decimals) must give the amount of the line to the cent, half-up."""
        rnd = random.Random(40); parse = lambda s: D(s.replace(' CHF', '').replace(' ', '').replace(',', '.'))
        for _ in range(400):
            q = D(rnd.randint(1, 5_000_000)) / D(10 ** rnd.randint(0, 6)); r = D(rnd.randint(0, 900_000)) / D(10 ** rnd.randint(0, 4))
            q = q.quantize(D('0.000001'), ROUND_HALF_UP)
            if q <= 0: continue
            printed = (parse(pdf_layout.qty_label(float(q))) * parse(pdf_layout.rate_money(float(r)))).quantize(CENT, ROUND_HALF_UP)
            self.assertEqual(printed, rules.line_amount(float(q), float(r)), (q, r))

    def test_totals_are_the_sum_of_their_printed_parts_with_one_vat_rounding(self):
        rnd = random.Random(41)
        for _ in range(300):
            vat = rnd.choice(['0', '2.6', '3.8', '8.1', '7.7']); qty = D(rnd.randint(1, 4000)) / 100; rate = D(rnd.randint(0, 200000)) / 100
            other = D(rnd.randint(0, 100000)) / 100; mode = rnd.choice(['soumis', 'hors_tva'])
            ls = [{'qty': float(D(rnd.randint(1, 900)) / 100), 'unit_rate': float(D(rnd.randint(0, 99999)) / 100), 'vat_mode': rnd.choice(['soumis', 'hors_tva'])} for _ in range(rnd.randint(0, 8))]
            a = rules.amounts(float(qty), float(rate), vat, float(other), mode, ls)
            ht = (qty * rate).quantize(CENT, ROUND_HALF_UP); amts = [(rules.line_amount(l['qty'], l['unit_rate']), l['vat_mode']) for l in ls]
            taxed = sum((x for x, v in amts if v != 'hors_tva'), D(0)); untaxed = sum((x for x, v in amts if v == 'hors_tva'), D(0))
            base = ht + taxed + (other if mode == 'soumis' else 0); tva = (base * D(vat) / 100).quantize(CENT, ROUND_HALF_UP)
            self.assertEqual((a['ht'], a['lines_ht'], a['subtotal'], a['tva']), (ht, taxed + untaxed, ht + taxed + untaxed, tva))
            self.assertEqual(a['ttc'], ht + taxed + untaxed + tva + other.quantize(CENT, ROUND_HALF_UP))
            self.assertEqual(a['ttc'].as_tuple().exponent, -2)                                                   # cents, nothing else


# ===================================================================================================================================================
class Numbers(tcl.Base):
    def issued_number(self, number):
        iid = self.draft_with(lines=()); r, fl = self.save(iid, [], number=number); self.assertEqual(r.status_code, 302, fl)
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (iid,)), number); return iid

    def test_a_zero_padded_variant_of_an_issued_number_is_refused(self):
        self.issued_number('2026-09')
        b = self.draft_with(lines=(), period=('2026-08-01', '2026-08-31')); keep = self.scalar('SELECT number FROM invoices WHERE id=?', (b,))
        for typed in ('2026-9', '2026-009', ' 2026-09 ', '2026-09'):
            r, fl = self.save(b, [], number=typed, period_from='2026-08-01', period_to='2026-08-31')
            self.assertEqual(r.status_code, 200, typed); self.assertIn('est déjà utilisé par la facture émise 2026-09', fl, typed)
            self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (b,)), keep, typed)

    def test_the_three_part_legacy_format_keeps_its_own_identity(self):
        self.issued_number('2026-09')
        b = self.draft_with(lines=(), period=('2026-08-01', '2026-08-31'))
        r, fl = self.save(b, [], number='2026-09-2', period_from='2026-08-01', period_to='2026-08-31'); self.assertEqual(r.status_code, 302, fl)     # AAAA-MM-N is another number than AAAA-MM

    def test_the_proposal_never_hands_out_a_variant_of_a_taken_number(self):
        self.issued_number('2026-09')
        c = m.db()
        try: taken = {rules.number_key(r[0]) for r in c.execute('SELECT number FROM invoices WHERE number IS NOT NULL')}; got = rules.propose_invoice_number(c, 2026)
        finally: c.close()
        self.assertNotIn(rules.number_key(got), taken); self.assertEqual(got, '2026-10')

    def test_reserved_prefix_and_odd_characters_are_refused_by_the_editor_and_change_nothing(self):
        b = self.draft_with(lines=()); keep = self.scalar('SELECT number FROM invoices WHERE id=?', (b,))
        for typed in ('NC-7', 'nc-7', '2026/1\u202e', '2026 1', '../1', '2026-1\n2', 'x' * 21):
            r, fl = self.save(b, [], number=typed); self.assertEqual(r.status_code, 200, repr(typed)); self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (b,)), keep, repr(typed))


# ===================================================================================================================================================
class Concurrency(tcl.Base):
    def login(self):
        c = m.APP.test_client(); c.post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']}); return c

    def race(self, fn):
        barrier = threading.Barrier(2); out = {}
        def worker(k):
            c = self.login(); barrier.wait(); out[k] = fn(c, k)
        ts = [threading.Thread(target=worker, args=(k,)) for k in 'AB']; [t.start() for t in ts]; [t.join() for t in ts]
        return out

    def test_two_simultaneous_credits_of_the_same_line_create_only_one_note(self):
        iid = self.issued_with(); l1, l2 = self.line_ids(iid)
        self.race(lambda c, k: c.post(f'/invoice/{iid}/credit', data={'reason': 'motif ' + k, 'treatment': 'remboursement', 'scope': 'partial', f'cl_{l1}': '100'}).status_code)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 1); self.assertEqual(self.scalar('SELECT COALESCE(SUM(amount),0) FROM credit_note_lines WHERE invoice_line_id=?', (l1,)), 100)

    def test_two_simultaneous_total_credits_create_only_one_note(self):
        iid = self.issued_with()
        self.race(lambda c, k: c.post(f'/invoice/{iid}/credit', data={'reason': 'motif ' + k, 'treatment': 'remboursement', 'scope': 'total'}).status_code)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 1)

    def test_two_simultaneous_issuances_of_the_same_credit_draft_issue_it_once(self):
        iid = self.issued_with(); cid, fl = self.credit(iid, scope='partial', **{f'cl_{self.line_ids(iid)[0]}': '40'}); self.assertIsNotNone(cid, fl)
        self.race(lambda c, k: c.post(f'/credit/{cid}/issue').status_code)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM credit_notes WHERE status='issued'"), 1); self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_snapshots'), 1)
        self.assertEqual(self.scalar('SELECT reference FROM credit_notes WHERE id=?', (cid,)), 'NC-' + self.scalar('SELECT number FROM invoices WHERE id=?', (iid,)))

    def test_a_second_credit_after_an_exhausted_line_is_refused_whatever_the_page_said(self):
        iid = self.issued_with(); l1, l2 = self.line_ids(iid)
        self.issued_cn(iid, scope='partial', **{f'cl_{l1}': '100'})
        cid, fl = self.credit(iid, scope='partial', **{f'cl_{l1}': '0.01'}); self.assertIsNone(cid); self.assertIn('dépasserait son montant', fl)
        cid, fl = self.credit(iid, scope='total'); self.assertIsNotNone(cid, fl)                                  # the rest of the invoice is still creditable once, line 1 excluded
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_lines WHERE invoice_line_id=?', (l1,)), 1)


# ===================================================================================================================================================
class Injection(tcl.Base):
    EVIL = '<img src=x onerror=alert(1)> &'
    EVIL2 = '<font color="red">x</font> =SUM(1)'

    def test_free_text_of_a_line_is_escaped_on_every_screen_and_printed_literally_in_the_pdf(self):
        iid = self.draft_with(lines=((self.EVIL, '1', '100', 'flat', 'soumis'), (self.EVIL2, '1', '50', 'flat', 'hors_tva')))
        pages = {'editor': f'/invoice/{iid}/edit', 'issue': f'/issue/{iid}', 'archive': '/?tab=archive'}
        for name, url in pages.items():
            raw = self.c.get(url).get_data(as_text=True); self.assertNotIn('<img src=x', raw, name); self.assertNotIn('<font color', raw, name)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data); self.assertIn('<img', t); self.assertIn('<font color', t)
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))
        l1 = self.line_ids(iid)[0]; cid = self.issued_cn(iid, scope='partial', **{f'cl_{l1}': '10'})
        for url in (f'/invoice/{iid}/credit', f'/credit/{cid}', '/?tab=archive'):
            raw = self.c.get(url).get_data(as_text=True); self.assertNotIn('<img src=x', raw, url); self.assertNotIn('<font color', raw, url)
        self.assertIn('<img', pdf_text(self.c.get(f'/credit/{cid}.pdf').data))                                    # the credit note copies the description as typed

    def test_the_archive_index_never_carries_the_free_text_of_a_line(self):
        import zipfile
        iid = self.issued_with(lines=(('=SUM(1+1)', '1', '100', 'flat', 'soumis'),)); r = self.c.get('/archive.zip'); self.assertEqual(r.status_code, 200)
        z = zipfile.ZipFile(io.BytesIO(r.data)); idx = z.read('index.csv').decode('utf-8-sig')
        self.assertNotIn('SUM(1+1)', idx)
        for l in idx.splitlines()[1:]:
            for cell in l.split(';'): self.assertFalse(cell[:1] in ('=', '@', '\t', '\r'), cell)             # nothing in the index can start a formula

    def test_a_line_with_a_direction_character_is_refused_by_the_editor_and_nothing_is_stored(self):
        iid = self.draft_with(lines=())
        r, fl = self.save(iid, [line('Frais\u202e100', '1', '10', uid='ud')]); self.assertEqual(r.status_code, 200); self.assertIn('description invalide', fl)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?', (iid,)), 0)

    def test_download_names_of_documents_contain_no_path_separator(self):
        iid = self.draft_with(lines=()); self.save(iid, [], number='2026/7'); self.flashes(); self.issue(iid)
        cd = self.c.get(f'/invoice/{iid}.pdf').headers.get('Content-Disposition', ''); self.assertNotIn('\\', cd); self.assertNotRegex(cd, r'filename="?[^";]*/')


# ===================================================================================================================================================
class RestoreForged(tcl.Base):
    def setUp(self):
        super().setUp()
        self.iid = self.issued_with(); self.l1, self.l2 = self.line_ids(self.iid); self.cid = self.issued_cn(self.iid, scope='partial', **{f'cl_{self.l1}': '60'})
        self.raw_backup = self.c.get('/backup').data

    def blocking(self, mutate=None):
        data = json.loads(self.raw_backup)
        if mutate: mutate(data['tables'])
        c = m.db()
        try: data = restore_service.validate(c, json.dumps(data)); return restore_service.preview(c, data)['blocking']
        finally: c.close()

    def about_lines(self, blocking): return [b for b in blocking if 'invoice_lines' in b or 'credit_note_lines' in b or 'copie figée' in b]

    def test_the_untouched_backup_of_the_same_database_is_not_blocked_by_the_line_checks(self):
        self.assertEqual(self.about_lines(self.blocking()), [])

    def test_a_forged_unit_price_on_a_line_of_an_issued_invoice_is_blocked(self):
        def bump(t): next(r for r in t['invoice_lines'] if r['id'] == self.l1)['unit_rate'] += 1
        b = self.blocking(bump); self.assertTrue(any('invoice_lines' in x and 'modifiées' in x for x in b), b); self.assertTrue(any('ne correspondent pas à sa copie figée' in x for x in b), b)

    def test_a_forged_vat_regime_or_description_on_an_issued_line_is_blocked(self):
        for col, val in (('vat_mode', 'hors_tva'), ('description', 'Autre texte'), ('qty', 5.0)):
            def edit(t, col=col, val=val): next(r for r in t['invoice_lines'] if r['id'] == self.l1)[col] = val
            self.assertTrue(self.about_lines(self.blocking(edit)), col)

    def test_a_backup_without_the_lines_of_an_issued_invoice_is_blocked(self):
        def drop(t): t['invoice_lines'] = [r for r in t['invoice_lines'] if r['invoice_id'] != self.iid]
        self.assertTrue(self.about_lines(self.blocking(drop)))

    def test_a_forged_amount_or_target_of_a_credited_line_of_an_issued_note_is_blocked(self):
        for col, val in (('amount', 99.0), ('invoice_line_id', self.l2), ('description', 'Autre')):
            def edit(t, col=col, val=val): next(r for r in t['credit_note_lines'] if r['credit_note_id'] == self.cid)[col] = val
            self.assertTrue(self.about_lines(self.blocking(edit)), col)

    def test_credited_lines_added_to_an_issued_note_by_the_file_are_blocked(self):
        def add(t):
            base = dict(next(r for r in t['credit_note_lines'] if r['credit_note_id'] == self.cid)); base.update(id=max(r['id'] for r in t['credit_note_lines']) + 1, invoice_line_id=self.l2, position=2, amount=10.0, vat_mode='hors_tva')
            t['credit_note_lines'].append(base)
        self.assertTrue(self.about_lines(self.blocking(add)))


# ===================================================================================================================================================
class OpenDefects(tcl.Base):
    """Confirmés par lecture du code (voir le rapport), NON corrigés ici car ils touchent le schéma de production ou une règle métier : décision du propriétaire / du superviseur."""

    @unittest.expectedFailure
    def test_F_C1_a_line_whose_product_ends_on_a_half_cent_can_be_credited_in_full(self):
        """1,5 × 0,15 = 0,225 → 0,23 (demi-supérieur, comme la facture) mais le déclencheur SQL credit_lines_within_line arrondit en virgule flottante (ROUND(1.5*0.15,2) = 0,22, plafond 0,225) :
        l'avoir total de cette ligne est refusé par la base alors que l'application l'autorise."""
        iid = self.issued_with(lines=(('Demi-cent', '1.5', '0.15', 'flat', 'soumis'),)); (l1,) = self.line_ids(iid)
        self.assertEqual(rules.line_amount(1.5, 0.15), D('0.23'))
        cid, fl = self.credit(iid, scope='partial', **{f'cl_{l1}': '0.23'}); self.assertIsNotNone(cid, fl)

    @unittest.expectedFailure
    def test_F_T1_a_draft_line_cannot_be_moved_under_an_issued_invoice_by_sql(self):
        """BEFORE UPDATE de invoice_lines_no_update_issued ne regarde que OLD.invoice_id : un UPDATE invoice_id=<facture émise> sur une ligne de brouillon passe."""
        iid = self.issued_with(); d = self.draft_with(lines=(('Ligne mobile', '1', '5', 'flat', 'soumis'),), period=('2026-10-01', '2026-10-31')); (ld,) = self.line_ids(d)
        msg = self.raw("UPDATE invoice_lines SET invoice_id=%d, position=9 WHERE id=%d" % (iid, ld)); self.assertIsNotNone(msg); self.assertIn('immutable', msg)

    @unittest.expectedFailure
    def test_F_T2_a_credited_line_row_of_a_draft_note_cannot_be_redirected_by_sql(self):
        """Les gardes credit_lines_same_invoice / same_vat_mode / within_line sont des BEFORE INSERT : un UPDATE (invoice_line_id, amount) sur une ligne d'avoir brouillon les contourne
        (l'application rattrape à l'émission, pas la base)."""
        iid = self.issued_with(); l1, l2 = self.line_ids(iid); cid, fl = self.credit(iid, scope='partial', **{f'cl_{l2}': '10'}); self.assertIsNotNone(cid, fl)
        msg = self.raw("UPDATE credit_note_lines SET invoice_line_id=%d, amount=5000, vat_mode='soumis' WHERE credit_note_id=%d" % (l1, cid)); self.assertIsNotNone(msg)

    @unittest.expectedFailure
    def test_F_A1_two_global_addresses_differing_only_by_case_are_refused(self):
        self.mandate(name='Mandat adresse', legal_id='CHE-000.000.077')
        self.raw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','EGG FR','Rue 1','2026-10-27T10:00:00')")
        self.flashes(); self.c.post('/adresses/ajouter', data={'client_key': '*', 'label': 'egg fr', 'contact': '', 'address': 'Rue 2'})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM billing_addresses WHERE client_key='*'"), 1, ' '.join(self.flashes()))


if __name__ == '__main__':
    unittest.main()
