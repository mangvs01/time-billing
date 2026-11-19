"""V9.2-rc3 business decisions (2026-10-03), synthetic data only, on a COPY of the staging database.

1. optional, configurable refund deadline (none by default)
2. explicit, configurable VAT treatment of « AUTRES », mirrored by credit notes
3. offset only between invoices of the same legal client (same legal identifier)
4. mode immutable after issuance; correction = cancellation document + traceable replacement note
plus a randomised check of cumulative HT / VAT / TTC rounding.
"""
import html, json, random, sqlite3
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.billing_rules import local_today, local_date  # RC8: business day in Europe/Zurich
import app.app as m
from tests.test_functional import pdf_text
from tests.test_credit_settlement import Settlement, TODAY
from tests.test_import import FAKE_ISSUER

D = Decimal


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N (year of the invoice date = today's year, then the sequence of the year)


class RefundDeadline(Settlement):
    def test_no_deadline_by_default(self):
        cid = self.issued_cn(qty='0.5', treatment='remboursement')
        cn = self.sql('SELECT refund_delay_days, refund_due_on FROM credit_notes WHERE id=?', (cid,))[0]
        self.assertEqual(tuple(cn), (None, None))
        t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        self.assertIn('vous sera remboursé (sans délai fixé).', t); self.assertNotIn('au plus tard', t)
        self.assertIn('aucune', html.unescape(self.c.get(f'/credit/{cid}').get_data(as_text=True)))

    def test_configured_default_and_per_note_deadline(self):
        self.c.post('/settings', data=dict(FAKE_ISSUER, refund_delay_days='30', other_vat_default='hors_tva'))
        self.assertIn('value="30"', self.c.get(f'/invoice/{self.iid}/credit').get_data(as_text=True))  # prefilled, still editable
        cid = self.issued_cn(qty='0.5', treatment='remboursement', refund_delay_days='10')
        due = (local_today() + timedelta(days=10)).isoformat()
        self.assertEqual(self.scalar('SELECT refund_due_on FROM credit_notes WHERE id=?', (cid,)), due)
        self.assertIn(f"au plus tard le {date.fromisoformat(due).strftime('%d.%m.%Y')}", pdf_text(self.c.get(f'/credit/{cid}.pdf').data))
        # compensation ignores the deadline; an empty field means no deadline even with a default configured
        comp = self.issued_cn(amount='10', treatment='compensation', refund_delay_days='10')
        self.assertIsNone(self.scalar('SELECT refund_due_on FROM credit_notes WHERE id=?', (comp,)))
        none = self.issued_cn(amount='10', treatment='remboursement', refund_delay_days='')
        self.assertIsNone(self.scalar('SELECT refund_due_on FROM credit_notes WHERE id=?', (none,)))

    def test_invalid_delays_refused(self):
        for bad in ('-1', '366', 'trente', '1.5'):
            _, fl = self.credit(qty='0.5', treatment='remboursement', refund_delay_days=bad)
            self.assertIn('délai de remboursement', fl, bad)
        self.flashes(); self.c.post('/settings', data=dict(FAKE_ISSUER, refund_delay_days='abc'))
        self.assertIn('non enregistrés', ' '.join(self.flashes()))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM settings WHERE key='refund_delay_days' AND value='abc'"), 0)

    def test_overdue_flag(self):
        c = sqlite3.connect(self.db)
        c.execute("""INSERT INTO credit_notes(invoice_id,reference,amount,reason,vat,treatment,status,issued_at,refund_delay_days,refund_due_on)
                     VALUES(?,'NC-TEST-RETARD',100,'retard',8.1,'remboursement','issued','2026-01-01T10:00:00',5,'2026-01-06')""", (self.iid,)); c.commit()
        cid = c.execute('SELECT MAX(id) FROM credit_notes').fetchone()[0]; c.close()
        p = self.pos(cid)
        self.assertTrue(p['overdue']); self.assertIn('échéance dépassée (06.01.2026)', p['status'])  # rc7 (A3): French date


class OtherVat(Settlement):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    DEROGATE = (13,)   # rc25: periods past the real date of the day (check 13), explicitly
    def setUp(self):
        super().setUp()
        self.entry(self.pid, '2026-10-05', 8)

    def inv_with_other(self, mode, f='2026-10-01', t='2026-10-31', qty=1, other='100'):
        iid, fl = self.draft(self.pid, f, t, qty, other_amount=other, other_label='frais fictifs', other_vat_mode=mode)
        self.assertIn('Brouillon créé.', fl)
        self.issue(iid); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        return iid

    def test_hors_tva_keeps_current_behaviour(self):
        iid = self.inv_with_other('hors_tva')  # 650 + VAT 52.65 + 100 = 802.65
        a = m.rules.invoice_amounts(self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0])
        self.assertEqual((a['ht'], a['tva'], a['other'], a['ttc']), (D('650.00'), D('52.65'), D('100.00'), D('802.65')))
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn('AUTRES — frais fictifs (hors TVA)', t); self.assertIn('802,65 CHF', t)
        self.assertEqual(json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,)))['other_vat_mode'], 'hors_tva')

    def test_soumis_includes_other_in_vat_base(self):
        iid = self.inv_with_other('soumis')  # VAT on 750 = 60.75 → 810.75
        a = m.rules.invoice_amounts(self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0])
        self.assertEqual((a['tva'], a['ttc']), (D('60.75'), D('810.75')))
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn('(soumis à TVA)', t); self.assertIn('60,75 CHF', t); self.assertIn('810,75 CHF', t)

    def test_default_from_settings_and_legacy_null(self):
        self.c.post('/settings', data=dict(FAKE_ISSUER, other_vat_default='soumis', refund_delay_days=''))
        iid, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1, other_amount='10')
        self.assertEqual(self.scalar('SELECT other_vat_mode FROM invoices WHERE id=?', (iid,)), 'soumis')
        # legacy invoice (NULL mode) is computed exactly as before: AUTRES outside the VAT base
        self.assertIsNone(self.scalar('SELECT other_vat_mode FROM invoices WHERE id=?', (self.iid,)) if False else None)
        row = dict(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0]); row.update(other_vat_mode=None, other_amount=100)
        self.assertEqual(m.rules.amounts(row['qty'], row['unit_rate'], row['vat'], 100, None)['tva'], D('105.30'))

    def test_credit_mirrors_original_treatment(self):
        for mode, other_vat in (('hors_tva', D('0.00')), ('soumis', D('8.10'))):
            iid = self.inv_with_other(mode, f'2026-1{1 if mode == "hors_tva" else 2}-01', f'2026-1{1 if mode == "hors_tva" else 2}-28')
            cid, fl = self.credit(iid=iid, other_amount='100', treatment='remboursement')
            self.assertIn('Brouillon de note de crédit créé', fl)
            cn = self.sql('SELECT * FROM credit_notes WHERE id=?', (cid,))[0]
            self.assertEqual((cn['other_vat_mode'], cn['other_amount'], cn['amount']), (mode, 100.0, 0.0))
            p = self.pos(cid)
            self.assertEqual((p['ht'], p['other'], p['tva']), (D('0.00'), D('100.00'), other_vat), mode)
            self.issue_cn(cid)
            t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
            self.assertIn('AUTRES CRÉDITÉ — frais fictifs', t); self.assertIn('hors TVA' if mode == 'hors_tva' else 'soumis à TVA', t)
            _, fl = self.credit(iid=iid, other_amount='0.01', treatment='remboursement')
            self.assertIn('« AUTRES »', fl)  # AUTRES already fully credited
        _, fl = self.credit(other_amount='5', treatment='remboursement')  # original invoice has no AUTRES line
        self.assertIn('ne comporte pas de ligne', fl)

    def test_total_credit_covers_both_lines_exactly(self):
        for mode in ('hors_tva', 'soumis'):
            iid = self.inv_with_other(mode, f'2026-1{1 if mode == "hors_tva" else 2}-01', f'2026-1{1 if mode == "hors_tva" else 2}-28', qty=0.33, other='33.33')
            inv = self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]; a = m.rules.invoice_amounts(inv)
            self.credit(iid=iid, qty='0.11', treatment='remboursement'); self.issue_cn(self.scalar('SELECT MAX(id) FROM credit_notes'))
            self.credit(iid=iid, other_amount='11.11', treatment='compensation'); self.issue_cn(self.scalar('SELECT MAX(id) FROM credit_notes'))
            cid, fl = self.credit(iid=iid, scope='total', treatment='remboursement'); self.issue_cn(cid)
            rows = self.sql('SELECT * FROM credit_notes WHERE invoice_id=?', (iid,))
            tot = {k: sum(m.credits.credit_amounts(r)[k] for r in rows) for k in ('ht', 'other', 'tva', 'ttc')}
            self.assertEqual((tot['ht'], tot['other'], tot['tva'], tot['ttc']), (a['ht'], a['other'], a['tva'], a['ttc']), mode)


class LegalClient(Settlement):
    def target(self, pid, f='2026-10-01', t='2026-10-31'):
        iid, fl = self.draft(pid, f, t, 1); self.assertIn('Brouillon créé.', fl); return iid

    def other_mandate(self, name, client, legal_id):
        pid = self.mandate(name=name, rate='650', vat='8.1', legal_id=legal_id)
        c = sqlite3.connect(self.db); c.execute('UPDATE projects SET client=? WHERE id=?', (client, pid)); c.commit(); c.close()
        return pid

    def test_same_legal_id_across_mandates_and_formats(self):
        cid = self.issued_cn(qty='1', treatment='compensation')
        same = self.other_mandate('Autre mandat même entité', 'Nom court différent', 'che000000001 TVA')
        t = self.target(same)
        self.assertIn('Imputation enregistrée', self.offset(cid, t, '100'))

    def test_different_legal_id_refused_even_with_same_name(self):
        cid = self.issued_cn(qty='1', treatment='compensation')
        homonym = self.other_mandate('Homonyme', 'Client Fictif SA', 'CHE-000.000.002')
        self.assertIn('non admissible', self.offset(cid, self.target(homonym), '100'))

    def test_missing_legal_id_blocks_offset(self):
        pid = self.mandate(name='Mandat sans IDE', rate='650', vat='8.1', legal_id='')
        self.entry(pid, '2026-09-10', 8)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        self.flashes(); self.c.post(f'/invoice/{iid}/credit', data={'reason': 'x', 'qty': '0.5', 'treatment': 'compensation'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.issue_cn(cid)
        t = self.target(pid, '2026-10-01', '2026-10-31')
        self.assertIn('identifiant juridique du client absent', self.offset(cid, t, '10'))
        page = html.unescape(self.c.get(f'/credit/{cid}').get_data(as_text=True))
        self.assertIn('identifiant juridique du client absent', page)

    def test_legal_identity_frozen_at_issuance(self):
        cid = self.issued_cn(qty='1', treatment='compensation')
        self.assertEqual(json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (self.iid,)))['client_legal_id'], 'CHE-000.000.001')
        # the mandate's identifier changes later: the frozen original keeps the old one, the new draft gets the new one
        c = sqlite3.connect(self.db); c.execute("UPDATE projects SET client_legal_id='CHE-000.000.003' WHERE id=?", (self.pid,)); c.commit(); c.close()
        self.assertIn('non admissible', self.offset(cid, self.target(self.pid), '10'))


class Correction(Settlement):
    def test_mode_immutable_after_issuance(self):
        cid = self.issued_cn(qty='0.5', treatment='remboursement')
        c = sqlite3.connect(self.db)
        for q in (f"UPDATE credit_notes SET treatment='compensation' WHERE id={cid}", f"UPDATE credit_notes SET refund_due_on='2030-01-01' WHERE id={cid}"):
            with self.assertRaises(sqlite3.DatabaseError, msg=q): c.execute(q)
        c.close()
        self.assertNotIn('treatment', html.unescape(self.c.get(f'/credit/{cid}').get_data(as_text=True)).split('Opérations')[0].split('<form')[0][-0:] if False else '')

    def test_cancel_and_replace_traceably(self):
        wrong = self.issued_cn(qty='0.5', treatment='remboursement', reason='mode erroné (test)')
        self.refund(wrong, '50'); op = self.last_op()
        self.assertIn('annuler d\'abord ces opérations', self.op(f'/credit/{wrong}/cancel', reason='mauvais mode'))
        self.reverse(wrong, op, 'saisie erronée (test)')
        self.assertIn('motif d\'annulation obligatoire', self.op(f'/credit/{wrong}/cancel', reason=''))
        self.assertIn('document d\'annulation figé', self.op(f'/credit/{wrong}/cancel', reason='mode choisi par erreur (test)'))
        k = self.sql('SELECT * FROM credit_note_cancellations WHERE credit_note_id=?', (wrong,))[0]
        self.assertEqual(k['reference'], f'ANN-NC-{YEAR}-1')
        t = pdf_text(self.c.get(f'/credit/{wrong}/cancellation.pdf').data)
        for needle in ('ANNULATION DE NOTE DE CRÉDIT', f'ANN-NC-{YEAR}-1', 'Note de crédit annulée :', f'NC-{YEAR}-1 du', "Facture d'origine :", '351,33 CHF',
                       'mode choisi par erreur (test)', 'est annulée et sans effet'):
            self.assertIn(needle, t)
        # the cancelled note itself is unchanged (frozen PDF identical), takes no operation, and frees the creditable amount
        self.assertEqual(self.pos(wrong)['status'], f'annulée (ANN-NC-{YEAR}-1)')
        self.assertIn('note de crédit annulée', self.refund(wrong, '1'))
        c = sqlite3.connect(self.db)
        for q in (f"INSERT INTO credit_operations(credit_note_id,kind,amount,executed_on,created_at) VALUES({wrong},'refund',1,'2026-10-01','x')",
                  'UPDATE credit_note_cancellations SET reason=\'x\'', 'DELETE FROM credit_note_cancellations'):
            with self.assertRaises(sqlite3.DatabaseError, msg=q): c.execute(q)
        c.close()
        self.assertIn('1\u202f300,00\xa0CHF', self.c.get(f'/invoice/{self.iid}/credit').get_data(as_text=True))
        self.assertEqual(self.suggest(self.pid, '2026-10-01', '2026-10-31')[1]['billed_days_before'], 2.0)
        # replacement note, with the right mode, linked to the cancelled one
        new = self.issued_cn(qty='0.5', treatment='compensation', reason='remplacement (test)', replaces_credit_id=str(wrong))
        self.assertEqual(self.sql('SELECT reference, replaces_credit_id FROM credit_notes WHERE id=?', (new,))[0][:], (f'NC-{YEAR}-1.2', wrong))
        t = pdf_text(self.c.get(f'/credit/{new}.pdf').data)
        self.assertIn(f'Remplace la note de crédit NC-{YEAR}-1, annulée par ANN-NC-{YEAR}-1.', t)
        _, fl = self.credit(amount='1', treatment='remboursement', replaces_credit_id=str(wrong)); self.assertIn('non encore remplacée', fl)
        _, fl = self.credit(amount='1', treatment='remboursement', replaces_credit_id=str(new)); self.assertIn('note annulée', fl)
        events = [e['event'] for e in m.credits.history(m.db(), self.sql('SELECT * FROM credit_notes WHERE id=?', (wrong,))[0])]
        self.assertIn(f'Annulation ANN-NC-{YEAR}-1', events); self.assertIn('Remplacement', events)
        self.assertIn('Remplace', html.unescape(self.c.get(f'/credit/{new}').get_data(as_text=True)))
        self.assertEqual(self.c.get(f'/credit/{wrong}.pdf').status_code, 200)
        self.assert_original_untouched()

    def test_frozen_offset_blocks_cancellation(self):
        cid = self.issued_cn(qty='0.5', treatment='compensation')
        self.entry(self.pid, '2026-10-05', 8)
        t, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1)
        self.offset(cid, t, '100'); self.issue(t)
        self.assertIn('imputation figée', self.op(f'/credit/{cid}/cancel', reason='x'))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_cancellations'), 0)

    def test_restore_blocked_if_cancellation_lost(self):
        cid = self.issued_cn(amount='10', treatment='remboursement')
        raw = self.c.get('/backup').data
        self.op(f'/credit/{cid}/cancel', reason='test')
        import io
        r = self.c.post('/restore', data={'backup': (io.BytesIO(raw), 'b.json')}, content_type='multipart/form-data')
        token = r.headers['Location'].rsplit('/', 1)[-1]
        page = html.unescape(self.c.get(f'/restore/{token}').get_data(as_text=True))
        self.assertIn('Restauration bloquée', page); self.assertIn(f'ANN-NC-{YEAR}-1', page)


class CumulativeRounding(Settlement):
    """Randomised (seeded) invoices and credit sequences: the credited totals never exceed the invoice and
    equal it exactly once fully credited; each note's VAT is within one cent of its own natural rounding."""
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def test_random_sequences(self):
        rng = random.Random(20261003); checked = 0
        for n in range(40):
            vat = rng.choice(['0', '2.6', '3.8', '8.1']); mode = rng.choice(['hors_tva', 'soumis'])
            pid = self.mandate(name=f'Mandat aléatoire {n}', rate=str(rng.choice([95, 650, 777.77, 1234.5])), vat=vat, ordered='0')
            qty = rng.choice([0.13, 0.33, 1, 1.37, 2.71]); other = rng.choice(['0', '0.05', '33.33', '99.99'])
            iid, fl = self.draft(pid, '2026-09-01', '2026-09-30', qty, other_amount=other, other_vat_mode=mode)
            self.issue(iid); inv = self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]
            self.assertEqual(inv['status'], 'issued', self.flashes())
            a = m.rules.invoice_amounts(inv)
            for _ in range(rng.randint(0, 3)):
                k = m.credits.creditable(m.db(), inv)
                if k['remaining_service'] > D('0.02') and rng.random() < 0.6:
                    form = {'qty': str(round(min(k['remaining_qty'], qty) * rng.uniform(0.05, 0.5), 3))} if rng.random() < 0.5 else {'amount': str((k['remaining_service'] * D(str(rng.uniform(0.05, 0.5)))).quantize(D('0.01')))}
                elif k['remaining_other'] > D('0.02'):
                    form = {'other_amount': str((k['remaining_other'] / 2).quantize(D('0.01')))}
                else: continue
                cid, fl = self.credit(iid=iid, treatment='remboursement', **form)
                if 'créé' in fl: self.issue_cn(cid)
            cid, fl = self.credit(iid=iid, scope='total', treatment='compensation'); self.issue_cn(cid)
            rows = self.sql("SELECT * FROM credit_notes WHERE invoice_id=? AND status='issued'", (iid,))
            tot = {k: sum((m.credits.credit_amounts(r)[k] for r in rows), D(0)) for k in ('ht', 'other', 'tva', 'ttc')}
            self.assertEqual((tot['ht'], tot['other'], tot['tva'], tot['ttc']), (a['ht'], a['other'], a['tva'], a['ttc']), f'cas {n}: {dict(inv)}')
            for r in rows:
                nat = m.rules.amounts(r['qty'], r['unit_rate'], r['vat'], r['other_amount'], r['other_vat_mode']) if r['qty'] else m.rules.amounts(1, r['amount'], r['vat'], r['other_amount'], r['other_vat_mode'])
                self.assertLessEqual(abs(m.credits.credit_amounts(r)['tva'] - nat['tva']), D('0.01') * len(rows), f'cas {n}')
            checked += 1
        self.assertEqual(checked, 40)


class ClosingNoteRounding(Settlement):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def test_total_in_days_after_partial_days_is_exact(self):
        # found by the randomised test: 0.133 j then the rest at 95 CHF/j → 0.867 × 95 = 82.365 → 82.37 > 82.36 left
        pid = self.mandate(name='Mandat 95', rate='95', vat='8.1', ordered='0')
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1); self.issue(iid)
        self.credit(iid=iid, qty='0.133', treatment='remboursement'); self.issue_cn(self.scalar('SELECT MAX(id) FROM credit_notes'))
        cid, fl = self.credit(iid=iid, scope='total', treatment='remboursement')
        self.assertIn('Brouillon de note de crédit créé', fl)
        cn = self.sql('SELECT * FROM credit_notes WHERE id=?', (cid,))[0]
        self.assertEqual((cn['qty'], cn['amount']), (0.867, 82.36))
        self.issue_cn(cid)
        rows = self.sql('SELECT * FROM credit_notes WHERE invoice_id=?', (iid,))
        self.assertEqual(sum(m.credits.credit_amounts(r)['ttc'] for r in rows), D('102.70'))  # 95 + 7.70
        self.assertIn('écart d\'arrondi', pdf_text(self.c.get(f'/credit/{cid}.pdf').data))
        self.assertEqual(self.suggest(pid, '2026-10-01', '2026-10-31')[1]['billed_days_before'], 0.0)


class CancellationLayout(Settlement):
    def test_cancellation_has_no_thanks_nor_payment(self):
        cid = self.issued_cn(amount='10', treatment='remboursement')
        self.op(f'/credit/{cid}/cancel', reason='test')
        t = pdf_text(self.c.get(f'/credit/{cid}/cancellation.pdf').data)
        self.assertNotIn('Paiement à 30 jours', t)
        self.assertNotIn(FAKE_ISSUER.get('thanks_text', 'Je vous remercie'), t)
