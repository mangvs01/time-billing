"""rc37 (P1) — manual lines of a draft invoice: amounts, form, persistence, PDF, freezing at issuance, credit notes on these lines: tests/test_credit_lines.py (rc38).
Synthetic data only. Run with the isolated runner (see docs/FACTURES-IMPLEMENTATION.md)."""
import json, os, re, sqlite3, threading, unittest
from decimal import Decimal

import app.app as m
from app import billing_rules as rules, invoice_service, pdf_layout
from tests import test_g4
from tests.test_functional import Cycle, pdf_text
from tests.test_g4 import text

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


LONG_SERVICE = 'GEM STC 2026 - 2600140AE - Delegate management'      # 2 printed lines + the period line = the tallest service row


def m_issuer(case):
    from tests.test_import import FAKE_ISSUER
    return dict(FAKE_ISSUER)


def line(desc='Frais de déplacement', qty='1', rate='100', unit='flat', vat_mode='soumis', id='', uid=None):
    return dict(id=id, uid=uid if uid is not None else 'u' + re.sub(r'[^A-Za-z0-9]', '', desc)[:20] + re.sub(r'[^0-9]', '', qty + rate), description=desc, qty=qty, unit=unit, rate=rate, vat_mode=vat_mode)


def draw_calls(fn):
    """Every Doc.text call (x, top, text, size, align) made while fn() runs: the drawing instructions of the PDF."""
    calls = []; orig = pdf_layout.Doc.text
    def rec(self, x, top, s, size=8, font=pdf_layout.BODY, color=None, align='left', label=None):
        calls.append([round(x, 2), round(top, 2), s or ('<' + (label or '') + '>'), size, align])
        kw = dict(size=size, font=font, align=align, label=label)
        if color is not None: kw['color'] = color
        return orig(self, x, top, s, **kw)
    pdf_layout.Doc.text = rec
    try: fn()
    finally: pdf_layout.Doc.text = orig
    return calls


def page_one(calls):
    i = next((n for n, c in enumerate(calls) if c[2] == 'Feuille de temps'), len(calls))
    return calls[:i]


class LiftedBlock:
    """rc38: issuing an invoice with manual lines is blocked by default (billing_rules.MANUAL_LINES_ISSUANCE_BLOCKED); the tests of this module are about what happens to such an
    invoice once issued (freezing, immutability, exports), so they run with the block lifted. The block itself is tested in tests/test_credit_lines.py."""
    def setUp(self):
        super().setUp()
        old = rules.MANUAL_LINES_ISSUANCE_BLOCKED; rules.MANUAL_LINES_ISSUANCE_BLOCKED = False
        self.addCleanup(setattr, rules, 'MANUAL_LINES_ISSUANCE_BLOCKED', old)


class Amounts(unittest.TestCase):
    def test_without_lines_the_result_is_the_one_of_rc36(self):
        a = rules.amounts(2, 650, 8.1, 120.5, 'soumis')
        self.assertEqual((a['ht'], a['tva'], a['other'], a['ttc']), (Decimal('1300.00'), Decimal('115.06'), Decimal('120.50'), Decimal('1535.56')))
        self.assertEqual((a['lines_ht'], a['subtotal']), (Decimal(0), Decimal('1300.00')))

    def test_lines_round_half_up_to_the_cent_each(self):
        ls = [dict(qty=3, unit_rate=0.335, vat_mode='soumis'), dict(qty=1.5, unit_rate=33.333, vat_mode='soumis'), dict(qty=1, unit_rate=0.005, vat_mode='hors_tva')]
        a = rules.amounts(0.000001, 0, 0, 0, 'hors_tva', ls)
        self.assertEqual(rules.line_amount(3, 0.335), Decimal('1.01'))       # 1.005 → 1.01 (half up, Decimal: no float surprise)
        self.assertEqual(rules.line_amount(1.5, 33.333), Decimal('50.00'))   # 49.9995 → 50.00
        self.assertEqual(rules.line_amount(1, 0.005), Decimal('0.01'))
        self.assertEqual(a['lines_ht'], Decimal('51.02')); self.assertEqual(a['ttc'], Decimal('51.02'))

    def test_vat_base_holds_the_taxed_lines_and_the_hors_tva_ones_are_added_after(self):
        ls = [dict(qty=1, unit_rate=100, vat_mode='soumis'), dict(qty=2, unit_rate=25, vat_mode='hors_tva')]
        a = rules.amounts(2, 500, 8.1, 10, 'soumis', ls)
        # base = 1000 + 100 + 10 = 1110 → VAT 89.91 ; total = 1000 + 150 + 89.91 + 10
        self.assertEqual((a['tva'], a['ttc'], a['subtotal'], a['lines_taxed'], a['lines_untaxed']), (Decimal('89.91'), Decimal('1249.91'), Decimal(1150), Decimal(100), Decimal(50)))
        b = rules.amounts(2, 500, 8.1, 10, 'hors_tva', ls)
        self.assertEqual((b['tva'], b['ttc']), (Decimal('89.10'), Decimal('1249.10')))     # base 1100


class Editor(LiftedBlock, test_g4.G4):
    checks = test_g4.Checks.checks
    RECORD_WORK = True

    def new_draft(self, **kw):
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, **kw)
        self.assertIn('Brouillon créé.', fl); return iid

    def rev(self, iid): return str(self.scalar('SELECT revision FROM invoices WHERE id=?', (iid,)))

    def form(self, iid, lines=(), revision=None, **over):
        d = dict(period_from='2026-09-01', period_to='2026-09-30', qty='2', unit='day', rounding='exact', rounding_step='0.25', vat='0', description='Prestation', other_amount='0',
                 other_label='', other_vat_mode='hors_tva', invoice_date='', note='', revision=self.rev(iid) if revision is None else revision)
        d.update(over)
        d.update({'line_id': [l['id'] for l in lines], 'line_uid': [l['uid'] for l in lines], 'line_description': [l['description'] for l in lines], 'line_qty': [l['qty'] for l in lines],
                  'line_unit': [l['unit'] for l in lines], 'line_rate': [l['rate'] for l in lines], 'line_vat_mode': [l['vat_mode'] for l in lines]})
        return d

    def save(self, iid, lines=(), **kw):
        self.flashes(); r = self.c.post(f'/invoice/{iid}/edit', data=self.form(iid, lines, **kw), follow_redirects=False)
        # a refused save shows the editor again in the same response (the messages are rendered there, not stored for a redirect)
        return r, ' '.join(self.flashes()) + (' ' + text(r) if r.status_code == 200 else '')

    def rows(self, iid): return self.sql('SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY position', (iid,))

    # --- persistence: no duplicate, no loss -------------------------------------------------------------------
    def test_add_edit_remove_and_persist_after_reload(self):
        iid = self.new_draft()
        r, fl = self.save(iid, [line('Frais de déplacement', '1', '120.50'), line('Hébergement', '2', '95', unit='piece', vat_mode='hors_tva')])
        self.assertEqual(r.status_code, 302); self.assertIn('Brouillon modifié.', fl); self.assertIn('2 ligne(s) manuelle(s) enregistrée(s).', fl)
        rows = self.rows(iid)
        self.assertEqual([(x['position'], x['description'], x['qty'], x['unit'], x['unit_rate'], x['vat_mode']) for x in rows],
                         [(1, 'Frais de déplacement', 1.0, 'flat', 120.5, 'soumis'), (2, 'Hébergement', 2.0, 'piece', 95.0, 'hors_tva')])
        html = text(self.c.get(f'/invoice/{iid}/edit'))                      # reload: both lines are in the form, with their amounts in the recap
        self.assertIn('value="Frais de déplacement"', html); self.assertIn('value="Hébergement"', html); self.assertIn('1 300,00', html.replace(' ', ' '))
        # edit the first, remove the second, keep ids: no duplicate
        ids = [x['id'] for x in rows]
        r, fl = self.save(iid, [line('Frais de déplacement Genève', '1', '130', id=str(ids[0]), uid=rows[0]['client_uid'])])
        again = self.rows(iid)
        self.assertEqual([(x['id'], x['description'], x['unit_rate']) for x in again], [(ids[0], 'Frais de déplacement Genève', 130.0)])
        self.assertIn('manual_lines=1;lines_added=0;lines_changed=1;lines_removed=1', self.scalar("SELECT detail FROM audit WHERE event='draft_updated' ORDER BY id DESC LIMIT 1"))

    def test_two_successive_saves_of_the_same_page_keep_exactly_the_same_lines(self):
        iid = self.new_draft(); ls = [line('A', '1', '10', uid='ua'), line('B', '2', '20', uid='ub')]
        self.save(iid, ls); first = self.rows(iid)
        self.save(iid, ls)                                                    # the browser re-posts the page (new lines still carry no id): idempotent by uid
        second = self.rows(iid)
        self.assertEqual([(x['id'], x['position'], x['description']) for x in first], [(x['id'], x['position'], x['description']) for x in second])
        self.assertEqual(len(second), 2)

    def test_double_submission_of_the_same_form_creates_nothing_twice(self):
        iid = self.new_draft(); rev = self.rev(iid); ls = [line('A', '1', '10', uid='ua')]
        self.save(iid, ls, revision=rev)
        r, fl = self.save(iid, ls, revision=rev)                              # same revision again: the second click of a double click
        self.assertIn('modifié depuis l\'ouverture', fl); self.assertEqual(len(self.rows(iid)), 1)

    def test_a_stale_tab_cannot_overwrite_a_newer_save(self):
        iid = self.new_draft(); stale = self.rev(iid)
        self.save(iid, [line('Nouvelle', '1', '50', uid='un')])
        r, fl = self.save(iid, [line('Ancienne', '1', '1', uid='uo')], revision=stale)
        self.assertEqual(r.status_code, 200); self.assertIn('Brouillon non modifié : ce brouillon a été modifié depuis l\'ouverture', fl)
        self.assertEqual([x['description'] for x in self.rows(iid)], ['Nouvelle'])
        self.assertIn(f'name="revision" value="{stale}"', r.get_data(as_text=True))     # the page shown again keeps the stale token: it cannot be re-posted blindly

    def test_a_refused_save_writes_nothing_and_shows_the_typed_lines_again(self):
        iid = self.new_draft(); self.save(iid, [line('Gardée', '1', '10', uid='ug')])
        before = [dict(x) for x in self.rows(iid)]; qty_before = self.scalar('SELECT qty FROM invoices WHERE id=?', (iid,)); rev_before = self.rev(iid)
        r, fl = self.save(iid, [line('Gardée', '1', '10', id=str(before[0]['id']), uid='ug'), line('', '1', '5', uid='ux')], qty='7')     # line 2 has no description
        self.assertEqual(r.status_code, 200); self.assertIn('ligne 2 : description obligatoire', fl)
        self.assertEqual([dict(x) for x in self.rows(iid)], before); self.assertEqual(self.scalar('SELECT qty FROM invoices WHERE id=?', (iid,)), qty_before); self.assertEqual(self.rev(iid), rev_before)
        self.assertIn('value="Gardée"', r.get_data(as_text=True)); self.assertIn('name="qty" type="number" min="0.001" step="0.000001" value="7"', r.get_data(as_text=True))

    def test_failure_in_the_lines_rolls_back_the_draft_update_too(self):
        iid = self.new_draft(); self.save(iid, [line('A', '1', '10', uid='ua')]); rev = self.rev(iid)
        r, fl = self.save(iid, [line('Fantôme', '1', '1', id='999999', uid='uf')], qty='9')    # unknown line id: refused after the draft row would have been updated
        self.assertIn('n\'existe plus', fl); self.assertEqual(self.scalar('SELECT qty FROM invoices WHERE id=?', (iid,)), 2.0); self.assertEqual(self.rev(iid), rev)

    def test_server_side_add_and_remove_buttons_work_without_javascript_and_write_nothing(self):
        iid = self.new_draft(); self.save(iid, [line('A', '1', '10', uid='ua')]); rev = self.rev(iid)
        d = self.form(iid, [line('A', '1', '10', id=str(self.rows(iid)[0]['id']), uid='ua')]); d['add_line'] = '1'
        r = self.c.post(f'/invoice/{iid}/edit', data=d)
        html = r.get_data(as_text=True); self.assertEqual(html.count('name="line_description"'), 2 + 1)        # 2 rows + the template of the JS clone
        self.assertEqual(len(self.rows(iid)), 1); self.assertEqual(self.rev(iid), rev)
        d = self.form(iid, [line('A', '1', '10', id=str(self.rows(iid)[0]['id']), uid='ua')]); d['remove_line'] = str(self.rows(iid)[0]['id'])
        html = self.c.post(f'/invoice/{iid}/edit', data=d).get_data(as_text=True)
        self.assertEqual(html.count('name="line_description"'), 0 + 1); self.assertEqual(len(self.rows(iid)), 1)    # removal is only a form state until « Enregistrer »
        self.save(iid, []); self.assertEqual(len(self.rows(iid)), 0)

    def test_the_hidden_default_button_of_the_form_is_the_save_button(self):
        iid = self.new_draft(); html = self.c.get(f'/invoice/{iid}/edit').get_data(as_text=True)
        form = html[html.index('id="tb-edit"'):]; first = re.search(r'<button[^>]*>', form).group(0)
        self.assertIn('name="act" value="save"', first)             # Enter in a field never triggers « Supprimer » of the first line

    def test_concurrent_saves_of_the_same_revision_only_one_wins(self):
        iid = self.new_draft(); rev = self.rev(iid); out = {}
        barrier = threading.Barrier(2)
        def worker(k):
            c = m.APP.test_client(); c.post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
            barrier.wait()
            r = c.post(f'/invoice/{iid}/edit', data=self.form(iid, [line('Ligne ' + k, '1', '10', uid='u' + k)], revision=rev))
            out[k] = r.status_code
        ts = [threading.Thread(target=worker, args=(k,)) for k in 'AB']
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(sorted(out.values()), [200, 302]); self.assertEqual(len(self.rows(iid)), 1)
        self.assertEqual(self.scalar('SELECT revision FROM invoices WHERE id=?', (iid,)), int(rev) + 1)

    # --- validation --------------------------------------------------------------------------------------------
    def test_validation_refusals(self):
        iid = self.new_draft()
        for bad, msg in [(line('X', '0', '10'), 'ligne 1 : quantité invalide'), (line('X', '-1', '10'), 'quantité invalide'), (line('X', '1', '-5'), 'prix unitaire (CHF) invalide'),
                         (line('X', '1', 'abc'), 'prix unitaire (CHF) invalide'), (line('X', '1e3', '10'), 'quantité invalide'), (line('X', '1', '10', unit='mètre'), 'unité inconnue'),
                         (line('X', '1', '10', vat_mode='demi'), 'régime de TVA inconnu'), (line('X' * 250, '1', '10'), 'description trop longue'),
                         (line('un mot ' + 'W' * 60, '1', '10'), 'un mot de la description est trop long'),
                         (line('Une description beaucoup trop longue pour deux lignes imprimées dans la colonne de la facture, vraiment', '1', '10'), 'description trop longue (2 lignes imprimées'),
                         (line('X', '123456.789012', '10', unit='piece'), 'quantité trop longue pour la colonne')]:
            r, fl = self.save(iid, [bad]); self.assertEqual(r.status_code, 200, msg); self.assertIn(msg, fl); self.assertEqual(len(self.rows(iid)), 0)
        r, fl = self.save(iid, [line('X', '1', '0')]); self.assertEqual(r.status_code, 302)                  # a free line (price 0) is valid; negative is refused above
        r, fl = self.save(iid, [line('Y', '1', '1', uid='y1'), line('Z', '1', '1', uid='y1')]); self.assertIn('en double', fl)

    def test_a_row_with_an_id_cannot_be_silently_emptied(self):
        iid = self.new_draft(); self.save(iid, [line('A', '1', '10', uid='ua')]); lid = str(self.rows(iid)[0]['id'])
        r, fl = self.save(iid, [dict(line('', '', ''), id=lid, uid='ua')]); self.assertIn('description obligatoire', fl); self.assertEqual(len(self.rows(iid)), 1)

    def test_at_most_eight_manual_lines_then_an_explicit_refusal(self):
        iid = self.new_draft()
        eight = [line(f'Ligne {k}', '1', '10', uid=f'u{k}') for k in range(8)]
        r, fl = self.save(iid, eight); self.assertEqual(r.status_code, 302, fl); self.assertEqual(len(self.rows(iid)), 8)
        r, fl = self.save(iid, eight + [line('Neuvième', '1', '10', uid='u9')]); self.assertEqual(r.status_code, 200)
        self.assertIn('9 lignes manuelles : 8 au maximum', fl); self.assertEqual(len(self.rows(iid)), 8)
        d = self.form(iid, eight); d['add_line'] = '1'; r = self.c.post(f'/invoice/{iid}/edit', data=d)
        self.assertIn('8 lignes manuelles au maximum', text(r)); self.assertEqual(text(r).count('name="line_description"'), 8 + 1)      # nothing added, the 8 rows are shown again

    def test_the_total_of_the_rows_must_fit_the_reserved_height(self):
        iid = self.new_draft(); two = 'Description sur deux lignes imprimées pour la hauteur de la rangée ok'
        self.assertEqual(pdf_layout.description_line_count(two), 2)
        r, fl = self.save(iid, [line(two + str(k % 3), '1', '1', uid=f'u{k}') for k in range(7)])
        self.assertEqual(r.status_code, 200); self.assertIn('occupent plus de place', fl)

    def test_nothing_is_stored_for_a_draft_without_lines_and_the_draft_form_still_posts_like_before(self):
        iid = self.new_draft()
        r = self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25', 'vat': '0'})
        self.assertEqual(r.status_code, 302); self.assertEqual(len(self.rows(iid)), 0)              # scripts / old forms without the new fields keep working

    # --- totals, PDF ------------------------------------------------------------------------------------------
    def test_preview_endpoint_computes_the_totals_on_the_server_and_writes_nothing(self):
        iid = self.new_draft(); rev = self.rev(iid)
        r = self.c.post(f'/invoice/{iid}/preview', data=self.form(iid, [line('A', '2', '25', uid='ua'), line('B', '1', '100.005', uid='ub', vat_mode='hors_tva')], vat='8.1'))
        j = r.get_json(); self.assertTrue(j['ok'])
        self.assertEqual((j['subtotal'], j['lines']), (rules.fr_chf(Decimal('1450.01')), [rules.fr_chf(Decimal('50.00')), rules.fr_chf(Decimal('100.01'))]))
        self.assertEqual(j['vat'], rules.fr_chf(Decimal('109.35')))     # base = 1300 + 50 (taxed line)
        self.assertEqual(len(self.rows(iid)), 0); self.assertEqual(self.rev(iid), rev)
        bad = self.c.post(f'/invoice/{iid}/preview', data=self.form(iid, [line('', '2', '25')])).get_json(); self.assertFalse(bad['ok'])

    def test_manual_lines_are_printed_in_the_draft_pdf_and_counted_in_the_sub_total(self):
        iid = self.new_draft(); self.save(iid, [line('Frais de déplacement', '1', '120.50', uid='ua'), line('Hébergement deux nuits', '2', '95', unit='piece', vat_mode='hors_tva', uid='ub')],
                                         vat='8.1', description='Prestation PM')
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        for needle in ('Frais de déplacement', '120,50 CHF', 'Hébergement deux nuits', '2,00 pièce', '95,00 CHF', '190,00 CHF', 'Prestation PM'):
            self.assertIn(needle, t)
        # service 1300.00 + 120.50 + 190.00 = 1610.50 ; VAT 8.1 % of (1300 + 120.50) = 115.06 (115.0605) ; total 1610.50 + 115.06
        self.assertIn('1 610,50 CHF', t); self.assertIn('115,06 CHF', t); self.assertIn('1 725,56 CHF', t)

    def test_pdf_rows_follow_the_service_line_and_move_the_totals_down_by_their_height(self):
        iid = self.new_draft(); base = page_one(draw_calls(lambda: self.c.get(f'/invoice/{iid}.pdf')))
        self.save(iid, [line('A', '1', '10', uid='ua'), line('Description sur deux lignes imprimées pour la hauteur de la rangée ok', '1', '10', uid='ub')])
        calls = page_one(draw_calls(lambda: self.c.get(f'/invoice/{iid}.pdf')))
        top = lambda cs, s: next(c[1] for c in cs if c[2] == s)
        self.assertEqual(top(base, 'SOUS-TOTAL'), 350.5)
        # rows start under the service line (317.9 + 26.6 = 344.5), heights 16.3 and 26.6 → totals at 350.5 + 42.9
        self.assertEqual(top(calls, 'A'), 344.5); self.assertAlmostEqual(top(calls, 'SOUS-TOTAL'), 350.5 + 16.3 + 26.6, places=2)

    def set_terms(self, value):
        c = sqlite3.connect(self.db); c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('payment_terms',?)", (value,)); c.commit(); c.close()

    def worst_cases(self):
        two = 'Description sur deux lignes imprimées pour la hauteur de la rangée ok'
        return [[line(f'Ligne {i}', '1', '10', uid=f'a{i}') for i in range(8)],
                [line(two + str(i), '1', '10', uid=f'b{i}') for i in range(6)],
                [line(two + str(i), '1', '10', uid=f'c{i}') for i in range(3)] + [line(f'Une ligne {i}', '1', '10', uid=f'd{i}') for i in range(5)]]


    def test_a_three_line_service_row_does_not_overlap_the_first_manual_row(self):
        """Found by the visual check of the generated PDF: description on 2 lines + period = 3 printed lines, the manual rows start under all of them."""
        iid = self.new_draft(); self.save(iid, [line('Frais de déplacement', '1', '10', uid='ua')], description=LONG_SERVICE)
        calls = page_one(draw_calls(lambda: self.c.get(f'/invoice/{iid}.pdf')))
        period = next(c for c in calls if c[2].startswith('Période :')); first = next(c for c in calls if c[2] == 'Frais de déplacement')
        self.assertGreaterEqual(first[1] - period[1], 10.3 - 1e-9); self.assertEqual(period[1], 338.5)

    def test_the_page_is_not_cut_with_the_worst_cases_the_form_admits(self):
        """8 one-line rows / the tallest rows the budget admits / a mix, plus two credit imputations, a one-line note, a thanks line and 2-line payment terms:
        the lowest text of page 1 (BIC row) stays above the footer (limit 807 pt, the footer baseline is 816.4)."""
        for k, rows in enumerate(self.worst_cases()):
            iid = self.new_draft() if k == 0 else self.draft(self.pid, f'2026-0{k + 1}-01', f'2026-0{k + 1}-28', 1)[0]
            r, fl = self.save(iid, rows, period_from='2026-09-01' if k == 0 else f'2026-0{k + 1}-01', period_to='2026-09-30' if k == 0 else f'2026-0{k + 1}-28', qty='2' if k == 0 else '1',
                              description=LONG_SERVICE)       # the service row at its tallest: 2 lines of description + the period
            self.assertEqual(r.status_code, 302, fl)
            with m.db() as c: h, annex = invoice_service.live_data(c, iid)
            h['offsets'] = [{'op_id': 1, 'reference': 'NC-2026-09', 'amount': '10.00'}, {'op_id': 2, 'reference': 'NC-2026-09.2', 'amount': '5.00'}]; h['net_due'] = '1.00'
            h['note'] = 'Une note libre sur une seule ligne'
            h['issuer'] = dict(h['issuer'], thanks_text='Je vous remercie de votre confiance.', payment_terms='Paiement à 30 jours net sur le compte indiqué ci-dessous, ' * 2, bic='UBSWCHZH80A')
            calls = page_one(draw_calls(lambda: pdf_layout.render_invoice(h, annex, issued=False)))
            last = max(c[1] for c in calls if c[1] < 814 and not c[2].startswith('BROUILLON')); self.assertLess(last, pdf_layout.PAGE_ONE_LIMIT, (k, last))
            self.assertAlmostEqual(pdf_layout.first_page_bottom(h), last, places=2)       # the dry measurement used by check 11 is the real one
            self.assertEqual(len([c for c in calls if c[2].startswith('BIC')]), 1)

    def test_check_11_refuses_a_page_one_that_would_run_into_the_footer(self):
        iid = self.new_draft(); self.save(iid, self.worst_cases()[0], description=LONG_SERVICE)
        self.assertEqual(self.checks(iid)[11]['status'], 'ok')
        self.set_terms('Paiement à 30 jours net sur le compte indiqué ci-dessous, ' * 40)      # 40 × the sentence: about twenty printed lines
        ck = self.checks(iid)[11]; self.assertEqual(ck['status'], 'fail'); self.assertIn('la page 1 déborderait sur le pied de page', ck['detail'])
        self.save(iid, [])           # without manual line the check keeps its previous behaviour (no new refusal)
        self.assertEqual(self.checks(iid)[11]['status'], 'ok')

    def test_page_one_of_an_invoice_without_manual_line_is_unchanged_since_rc36(self):
        """Regression oracle: the drawing calls below the header block of rc36 (fixture captured on the rc36 code, same data)."""
        want = json.load(open(os.path.join(FIXTURES, 'page1_rc36_below_header.json')))
        pid = self.mandate(name='Mandat Capture', rate='650', vat='8.1')
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 2, description='Prestation de capture', note='Note courte')
        got = [c for c in page_one(draw_calls(lambda: self.c.get(f'/invoice/{iid}.pdf'))) if c[1] >= 290]
        self.assertEqual(got, want['draft_plain'])
        self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '2', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25', 'vat': '8.1',
                    'description': 'Prestation de capture', 'other_amount': '120.50', 'other_label': 'Frais divers', 'other_vat_mode': 'soumis', 'invoice_date': '', 'note': 'Note courte'})
        got = [c for c in page_one(draw_calls(lambda: self.c.get(f'/invoice/{iid}.pdf'))) if c[1] >= 290]
        self.assertEqual(got, want['draft_other'])

    # --- bug B1-B4 (editor feedback) -------------------------------------------------------------------------
    def test_editor_warns_when_a_label_would_not_be_printed_and_when_the_description_is_replaced(self):
        iid = self.new_draft()
        r, fl = self.save(iid, [], description='', other_label='Frais divers', other_amount='0')
        self.assertIn('Le libellé « AUTRES » n\'est imprimé que si un montant est saisi', fl); self.assertIn('Description vide : le nom du mandat', fl)

    def test_the_editor_shows_the_service_line_read_only_with_its_rate_and_the_totals(self):
        iid = self.new_draft(); html = text(self.c.get(f'/invoice/{iid}/edit'))
        self.assertIn('Prestations (heures)', html); self.assertIn('tarif du mandat', html); self.assertIn('SOUS-TOTAL', html); self.assertIn('TOTAL TTC', html)
        self.assertNotIn('name="unit_rate"', html)

    # --- issuance: freezing, immutability, checks ---------------------------------------------------------------
    def test_issuance_freezes_the_lines_in_the_snapshot_and_the_table_becomes_immutable(self):
        iid = self.new_draft(); self.save(iid, [line('Frais de déplacement', '1', '120.50', uid='ua'), line('Hébergement', '2', '95', unit='piece', vat_mode='hors_tva', uid='ub')], vat='0', description='Prestation PM')
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', ' '.join(self.flashes()))
        hdr = json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,)))
        self.assertEqual([(l['position'], l['description'], l['qty'], l['unit'], l['unit_rate'], l['vat_mode']) for l in hdr['lines']],
                         [(1, 'Frais de déplacement', 1.0, 'flat', 120.5, 'soumis'), (2, 'Hébergement', 2.0, 'piece', 95.0, 'hors_tva')])
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data); self.assertIn('Frais de déplacement', t); self.assertIn('1 610,50 CHF', t)       # the frozen PDF
        before = self.scalar('SELECT pdf_sha256 FROM invoice_snapshots WHERE invoice_id=?', (iid,))
        c = sqlite3.connect(self.db)
        try:
            for q in ('UPDATE invoice_lines SET unit_rate=1 WHERE invoice_id=%d' % iid, 'DELETE FROM invoice_lines WHERE invoice_id=%d' % iid,
                      "INSERT INTO invoice_lines(invoice_id,position,description,qty,unit,unit_rate,vat_mode,created_at) VALUES(%d,9,'x',1,'flat',1,'soumis','')" % iid):
                with self.assertRaises(sqlite3.DatabaseError, msg=q): c.execute(q)
        finally: c.close()
        r = self.c.post(f'/invoice/{iid}/edit', data=self.form(iid, [line('Pirate', '1', '1')]))      # the editor refuses an issued invoice
        self.assertIn('Seul un brouillon peut être modifié', ' '.join(self.flashes())); self.assertEqual(self.scalar('SELECT pdf_sha256 FROM invoice_snapshots WHERE invoice_id=?', (iid,)), before)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?', (iid,)), 2)

    def test_the_issued_pdf_does_not_depend_on_the_table_any_more(self):
        iid = self.new_draft(); self.save(iid, [line('Ligne figée', '1', '10', uid='ua')])
        self.flashes(); self.issue(iid)
        a = self.c.get(f'/invoice/{iid}.pdf').data
        c = sqlite3.connect(self.db); c.execute('DROP TRIGGER invoice_lines_no_update_issued'); c.execute('UPDATE invoice_lines SET description=\'Modifiée hors application\' WHERE invoice_id=?', (iid,)); c.commit(); c.close()
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').data, a)

    def test_the_draft_delete_removes_its_lines(self):
        iid = self.new_draft(); self.save(iid, [line('A', '1', '10', uid='ua')])
        self.c.post(f'/invoice/{iid}/delete'); self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices WHERE id=?', (iid,)), 0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?', (iid,)), 0)
        self.assertIn('manual_lines_deleted=1', self.scalar("SELECT detail FROM audit WHERE event='draft_deleted' ORDER BY id DESC LIMIT 1"))

    def test_checks_see_the_lines_vat_text_and_layout(self):
        iid = self.new_draft(); self.save(iid, [line('Frais de déplacement', '1', '100', uid='ua')], vat='0')
        ck = self.checks(iid); self.assertEqual(ck[4]['status'], 'ok', ck[4]); self.assertIn('1 ligne(s) manuelle(s)', ck[4]['detail']); self.assertEqual(ck[3]['status'], 'ok')
        self.assertEqual(ck[11]['status'], 'ok', ck[11])
        self.save(iid, [line('Démo de test', '1', '100', uid='ua')], vat='0')               # check 10: a test word in a manual line is refused like in the description
        self.assertEqual(self.checks(iid)[10]['status'], 'fail') if m.invoice_checks.forbidden_words() else None
        c = sqlite3.connect(self.db); c.execute("UPDATE invoice_lines SET description=? WHERE invoice_id=?", ('Mot ' + 'W' * 70, iid)); c.commit(); c.close()    # saved outside the rules
        self.assertEqual(self.checks(iid)[11]['status'], 'fail'); self.assertIn('un mot de la description est trop long', self.checks(iid)[11]['detail'])

    def test_total_zero_or_negative_is_still_refused_at_issuance_with_lines(self):
        iid = self.new_draft(); self.save(iid, [line('Gratuit', '1', '0', uid='ua')]); self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued')     # the service line carries the total here

    # --- credit notes: the credit of manual lines is tested in tests/test_credit_lines.py (rc38) ----------------------------------------------
    def test_an_invoice_without_manual_lines_is_credited_as_before(self):
        iid = self.new_draft(); self.flashes(); self.issue(iid)
        self.flashes(); self.c.post(f'/invoice/{iid}/credit', data={'reason': 'erreur de saisie', 'treatment': 'remboursement', 'scope': 'total'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 1)

    # --- exports -------------------------------------------------------------------------------------------------
    def test_the_turnover_counts_the_manual_lines_but_not_the_days(self):
        from app import gsheet_export
        iid = self.new_draft(); self.save(iid, [line('A', '2', '50', uid='ua')]); self.flashes(); self.issue(iid)
        with m.db() as c: docs = [d for d in gsheet_export.documents(c) if d['kind'] == 'invoice']
        self.assertEqual(docs[0]['ht'], Decimal('1400.00')); self.assertEqual(docs[0]['days'], 2.0)           # 2 × 650 + 100 ; days = the service line only
        with m.db() as c: h, _ = invoice_service.live_data(c, iid)
        self.assertEqual(h['position']['current'], 2.0)

    def test_listing_and_archive_zip_show_the_printed_total(self):
        import zipfile, io
        iid = self.new_draft(); self.save(iid, [line('A', '2', '50', uid='ua')], vat='0'); self.flashes(); self.issue(iid)
        html = text(self.c.get('/?tab=archive')); self.assertIn('1 400,00', html.replace(' ', ' ').replace('\xa0', ' '))
        z = zipfile.ZipFile(io.BytesIO(self.c.get('/archive.zip').data)); idx = [n for n in z.namelist() if n.endswith('.csv')][0]
        rows = z.read(idx).decode('utf-8-sig').splitlines(); self.assertIn('1400.00', rows[1])


class LinesRestore(LiftedBlock, Cycle):
    RECORD_WORK = True

    def test_manual_lines_survive_a_json_backup_and_restore(self):
        import io, base64
        pid = self.mandate(name='Mandat sauvegardé', vat='8.1'); self.entry(pid, '2026-09-10', 8)
        d1, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        data = {'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25', 'vat': '8.1', 'description': 'Prestation',
                'line_id': ['', ''], 'line_uid': ['ra', 'rb'], 'line_description': ['Frais', 'Hébergement'], 'line_qty': ['1', '2'], 'line_unit': ['flat', 'piece'],
                'line_rate': ['40', '55.5'], 'line_vat_mode': ['soumis', 'hors_tva'], 'revision': '0'}
        self.c.post(f'/invoice/{d1}/edit', data=data); self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoice_lines'), 2)
        self.flashes(); self.issue(d1); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (d1,)), 'issued', ' '.join(self.flashes()))
        d2, _ = self.draft(pid, '2026-10-01', '2026-10-31', 1)
        self.c.post(f'/invoice/{d2}/edit', data=dict(data, period_from='2026-10-01', period_to='2026-10-31', line_id=['', ''], line_uid=['rc', 'rd'], revision=str(self.scalar('SELECT revision FROM invoices WHERE id=?', (d2,)))))
        before = [tuple(r) for r in self.sql('SELECT * FROM invoice_lines ORDER BY id')]; self.assertEqual(len(before), 4)
        raw = self.c.get('/backup').data; pdf = self.c.get(f'/invoice/{d1}.pdf').data
        self.c.post(f'/invoice/{d2}/delete')                                              # later work, lines included
        r = self.c.post('/restore', data={'backup': (io.BytesIO(raw), 'sauvegarde.json')}, content_type='multipart/form-data')
        token = r.headers['Location'].rsplit('/', 1)[-1]; self.flashes()
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'}); self.assertIn('Restauration effectuée', ' '.join(self.flashes()))
        self.assertEqual([tuple(r) for r in self.sql('SELECT * FROM invoice_lines ORDER BY id')], before)       # both the frozen invoice's lines and the draft's
        self.assertEqual(self.c.get(f'/invoice/{d1}.pdf').data, pdf)
        self.assertIn('value="Hébergement"', self.c.get(f'/invoice/{d2}/edit').get_data(as_text=True))
        c = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.DatabaseError): c.execute(f'DELETE FROM invoice_lines WHERE invoice_id={d1}')   # the triggers are back after the rebuild
        finally: c.close()


class Schema(Cycle):
    def test_migration_is_additive_and_idempotent(self):
        c = sqlite3.connect(self.db)
        try:
            self.assertEqual([r[1] for r in c.execute('PRAGMA table_info(invoice_lines)')][:3], ['id', 'invoice_id', 'position'])
            cols = {r[1] for r in c.execute('PRAGMA table_info(invoices)')}; self.assertIn('revision', cols)
            m.init(); m.init()                                    # replayed at every start
            self.assertEqual(c.execute('SELECT COUNT(*) FROM sqlite_master WHERE name=\'invoice_lines\'').fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'invoice_lines_%'").fetchone()[0], 3)
        finally: c.close()

    def test_restore_order_holds_the_new_table_before_the_snapshots(self):
        from app import restore_service
        self.assertLess(restore_service.ORDER.index('invoices'), restore_service.ORDER.index('invoice_lines')); self.assertLess(restore_service.ORDER.index('invoice_lines'), restore_service.ORDER.index('invoice_snapshots'))


if __name__ == '__main__':
    unittest.main()
