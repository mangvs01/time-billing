"""V9.2 credit notes: refund or offset chosen per document, settlement ledger, balances, history.

Synthetic data only (fictitious mandates, client and issuer), on a COPY of the staging database
(see test_import.py for the run command).

Reference invoice for every case: 2 days × 650 CHF, VAT 8.1 % → HT 1300.00, VAT 105.30, TTC 1405.30.
"""
import hashlib, html, json, sqlite3
from datetime import date, timedelta
from decimal import Decimal

from app.billing_rules import local_today, local_date  # RC8: business day in Europe/Zurich
import app.app as m
from tests.test_functional import pdf_text
import tests.test_v92 as v92
from tests.test_v92 import V92

D = Decimal
TODAY = local_today().isoformat()


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N (year of the invoice date = today's year, then the sequence of the year)


class Settlement(V92):
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat NC2', rate='650', vat='8.1', ordered='12')
        self.entry(self.pid, '2026-09-10', 16)
        self.iid = self.issued(self.pid, '2026-09-01', '2026-09-30', 2)
        self.inv_pdf = self.c.get(f'/invoice/{self.iid}.pdf').data
        self.inv_row = tuple(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0])
        self.inv_snap = tuple(self.sql('SELECT * FROM invoice_snapshots WHERE invoice_id=?', (self.iid,))[0])

    # helpers ----------------------------------------------------------------------------------
    def page_msgs(self, r):
        return self.flashes() + ([html.unescape(r.get_data(as_text=True))] if r.status_code == 200 else [])

    def credit(self, iid=None, **form):
        form.setdefault('reason', 'motif fictif')
        self.flashes(); r = self.c.post(f'/invoice/{iid or self.iid}/credit', data=form)
        return self.scalar('SELECT MAX(id) FROM credit_notes'), ' '.join(self.page_msgs(r))

    def issue_cn(self, cid):
        self.flashes(); self.c.post(f'/credit/{cid}/issue'); fl = ' '.join(self.flashes())
        return self.scalar('SELECT status FROM credit_notes WHERE id=?', (cid,)), fl

    def issued_cn(self, **form):
        cid, fl = self.credit(**form)
        self.assertIn('Brouillon de note de crédit créé', fl)
        st, fl = self.issue_cn(cid); self.assertEqual(st, 'issued', fl)
        return cid

    def op(self, url, **form):
        self.flashes(); self.c.post(url, data=form); return ' '.join(self.flashes())

    def refund(self, cid, amount, executed_on=TODAY, **kw):
        return self.op(f'/credit/{cid}/refund', amount=str(amount), executed_on=executed_on, **kw)

    def offset(self, cid, target, amount, **kw):
        return self.op(f'/credit/{cid}/offset', target_invoice_id=str(target), amount=str(amount), **kw)

    def reverse(self, cid, op_id, note='erreur de saisie (test)'):
        return self.op(f'/credit/{cid}/reverse/{op_id}', note=note)

    def pos(self, cid):
        c = m.db()
        try: return m.credits.position(c, c.execute('SELECT * FROM credit_notes WHERE id=?', (cid,)).fetchone())
        finally: c.close()

    def last_op(self):
        return self.scalar('SELECT MAX(id) FROM credit_operations')

    def assert_original_untouched(self):
        self.assertEqual(tuple(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0]), self.inv_row)
        self.assertEqual(tuple(self.sql('SELECT * FROM invoice_snapshots WHERE invoice_id=?', (self.iid,))[0]), self.inv_snap)
        self.assertEqual(self.c.get(f'/invoice/{self.iid}.pdf').data, self.inv_pdf)


class PartialAndTotal(Settlement):
    def test_partial_credit_refund_cycle(self):
        cid = self.issued_cn(qty='0.5', treatment='remboursement')
        cn = self.sql('SELECT * FROM credit_notes WHERE id=?', (cid,))[0]
        self.assertEqual((cn['reference'], cn['amount'], cn['qty'], cn['treatment']), (f'NC-{YEAR}-1', 325.0, 0.5, 'remboursement'))
        t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        for needle in ('NOTE DE CRÉDIT', f'NC-{YEAR}-1', "Facture d'origine :", f'{YEAR}-1 du', '325,00 CHF', '26,33 CHF', '351,33 CHF',
                       'Mode de traitement : remboursement', "facture d'origine inchangée"):
            self.assertIn(needle, t)
        self.assertNotIn('Paiement à 30 jours', t)
        p = self.pos(cid)
        self.assertEqual((p['ttc'], p['refunded'], p['balance'], p['status']), (D('351.33'), D('0'), D('351.33'), 'à rembourser'))
        # partial refund: credited amount stays distinct from what was actually paid back
        self.assertIn('Remboursement enregistré', self.refund(cid, '200', external_ref='VIR-TEST-1'))
        p = self.pos(cid)
        self.assertEqual((p['ttc'], p['refunded'], p['balance'], p['status']), (D('351.33'), D('200.00'), D('151.33'), 'partiellement remboursée'))
        self.assertIn('dépasse le solde restant à rembourser', self.refund(cid, '151.34'))
        self.assertIn('date future refusée', self.refund(cid, '1', (local_today() + timedelta(days=1)).isoformat()))
        self.assertIn('date d\'exécution', self.refund(cid, '1', 'demain'))
        self.assertIn('positif', self.refund(cid, '0'))
        self.refund(cid, '151.33')
        p = self.pos(cid)
        self.assertEqual((p['refunded'], p['balance'], p['status']), (D('351.33'), D('0.00'), 'remboursée'))
        self.assertIn('dépasse', self.refund(cid, '0.01'))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_operations'), 2)
        page = self.c.get(f'/credit/{cid}').get_data(as_text=True)
        self.assertIn('Reste à rembourser', page); self.assertIn('VIR-TEST-1', page); self.assertNotIn('Enregistrer le remboursement', page)
        k = self.c.get(f'/invoice/{self.iid}/credit').get_data(as_text=True)
        self.assertIn('975,00\xa0CHF', k)  # creditable balance left on the invoice
        self.assert_original_untouched()

    def test_total_credit_in_days(self):
        cid, fl = self.credit(scope='total', treatment='remboursement', qty='9', amount='9')  # partial fields ignored
        cn = self.sql('SELECT * FROM credit_notes WHERE id=?', (cid,))[0]
        self.assertEqual((cn['qty'], cn['unit_rate'], cn['amount']), (2.0, 650.0, 1300.0))
        self.issue_cn(cid)
        self.assertEqual(self.pos(cid)['ttc'], D('1405.30'))
        pos = self.suggest(self.pid, '2026-10-01', '2026-10-31')[1]
        self.assertEqual((pos['billed_days_before'], pos['po_balance_days']), (0.0, 12.0))  # all invoiced days reversed
        _, fl = self.credit(amount='0.01', treatment='remboursement'); self.assertIn('dépasserait le montant créditable', fl)
        _, fl = self.credit(scope='total', treatment='compensation'); self.assertIn('déjà entièrement créditée', fl)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 1)
        self.assertIn('créditée totalement', self.c.get('/?tab=archive').get_data(as_text=True))
        self.assert_original_untouched()

    def test_total_after_partial_credits_remaining(self):
        self.issued_cn(qty='0.5', treatment='remboursement')
        cid, _ = self.credit(scope='total', treatment='compensation')
        cn = self.sql('SELECT * FROM credit_notes WHERE id=?', (cid,))[0]
        self.assertEqual((cn['qty'], cn['amount']), (1.5, 975.0))
        self.issue_cn(cid)
        # 26.33 + 78.98 would credit 1405.31 for a 1405.30 invoice: the closing note carries the VAT balance 78.97
        p = self.pos(cid); self.assertEqual((p['ht'], p['tva'], p['ttc']), (D('975.00'), D('78.97'), D('1053.97')))
        self.assertEqual(self.pos(cid - 1)['ttc'] + p['ttc'], D('1405.30'))
        t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data); self.assertIn('78,97 CHF', t); self.assertIn('1 053,97 CHF', t)
        self.assertEqual(self.sql('SELECT reference FROM credit_notes WHERE id=?', (cid,))[0][0], f'NC-{YEAR}-1.2')
        page = self.c.get('/?tab=archive').get_data(as_text=True)
        self.assertIn('créditée totalement', page)

    def test_total_after_amount_credit_uses_amount(self):
        self.issued_cn(amount='100', treatment='remboursement')
        cid, _ = self.credit(scope='total', treatment='remboursement')
        cn = self.sql('SELECT * FROM credit_notes WHERE id=?', (cid,))[0]
        self.assertEqual((cn['qty'], cn['amount']), (None, 1200.0))

    def test_mode_is_mandatory(self):
        _, fl = self.credit(qty='0.5')
        self.assertIn('choisir le mode de traitement', fl)
        _, fl = self.credit(qty='0.5', treatment='virement')
        self.assertIn('choisir le mode de traitement', fl)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 0)
        # a draft without mode (created outside the form) cannot be issued — app and DB both refuse
        c = sqlite3.connect(self.db); c.execute("INSERT INTO credit_notes(invoice_id,amount,reason,vat) VALUES(?,10,'sans mode',8.1)", (self.iid,)); c.commit()
        cid = c.execute('SELECT MAX(id) FROM credit_notes').fetchone()[0]
        with self.assertRaises(sqlite3.DatabaseError): c.execute("UPDATE credit_notes SET status='issued',reference='NC-X' WHERE id=?", (cid,))
        with self.assertRaises(sqlite3.DatabaseError): c.execute("INSERT INTO credit_notes(invoice_id,amount,reason,treatment) VALUES(?,1,'x','autre')", (self.iid,))
        c.close()
        st, fl = self.issue_cn(cid); self.assertEqual(st, 'draft'); self.assertIn('mode de traitement', fl)


class Offsets(Settlement):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    DEROGATE = (12, 13)   # rc25: fixtures of this class bill days without matching recorded work (or a period past today): these checks are overridden, explicitly
    def later_draft(self, f, t, qty, pid=None):
        iid, fl = self.draft(pid or self.pid, f, t, qty); self.assertIn('Brouillon créé.', fl); return iid

    def test_compensation_full_on_later_invoice(self):
        cid = self.issued_cn(qty='0.5', treatment='compensation')
        t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        self.assertIn('Mode de traitement : compensation', t); self.assertIn('imputé sur une prochaine facture', t)
        self.assertEqual(self.pos(cid)['status'], 'disponible')
        self.entry(self.pid, '2026-10-05', 8)
        target = self.later_draft('2026-10-01', '2026-10-31', 1)  # 650 + 52.65 = 702.65 TTC
        self.assertIn('Imputation enregistrée', self.offset(cid, target, '351.33'))
        p = self.pos(cid)
        self.assertEqual((p['reserved'], p['applied'], p['balance']), (D('351.33'), D('0'), D('0.00')))
        self.assertEqual(p['status'], "entièrement affectée (imputation en attente d'émission)")
        t = pdf_text(self.c.get(f'/invoice/{target}.pdf').data)
        for needle in ('TOTAL FACTURE', '702,65 CHF', f'Imputation note de crédit NC-{YEAR}-1', '- 351,33 CHF', 'NET À PAYER', '351,32 CHF'):
            self.assertIn(needle, t)
        self.assertIn('net à payer 351,32\xa0CHF', self.c.get('/?tab=archive').get_data(as_text=True))
        self.issue(target, derogate=(13,))
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (target,)), f'{YEAR}-2')
        p = self.pos(cid)
        self.assertEqual((p['reserved'], p['applied'], p['balance'], p['status']), (D('0'), D('351.33'), D('0.00'), 'compensée'))
        frozen = pdf_text(self.c.get(f'/invoice/{target}.pdf').data)
        self.assertIn('NET À PAYER', frozen); self.assertIn('351,32 CHF', frozen)
        header = json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (target,)))
        self.assertEqual(header['offsets'], [{'op_id': self.last_op(), 'reference': f'NC-{YEAR}-1', 'amount': '351.33'}])
        self.assertIn('figée sur la facture émise', self.reverse(cid, self.last_op()))
        self.assertEqual(self.pos(cid)['status'], 'compensée')
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='credit_offset_applied'"), 1)
        events = [e['event'] for e in m.credits.history(m.db(), self.sql('SELECT * FROM credit_notes WHERE id=?', (cid,))[0])]
        self.assertEqual(events[0], 'Émission'); self.assertIn('Imputation sur facture', events[1]); self.assertIn('appliquée', events[2])
        self.assert_original_untouched()

    def test_partial_compensation_over_two_invoices_and_release(self):
        cid = self.issued_cn(amount='500', treatment='compensation')  # TTC 540.50
        self.assertEqual(self.pos(cid)['ttc'], D('540.50'))
        a = self.later_draft('2026-10-01', '2026-10-31', 0.25)  # 162.50 + 13.16 = 175.66
        self.assertIn('dépasse le montant restant dû sur la facture cible (175,66\xa0CHF)', self.offset(cid, a, '300'))
        self.offset(cid, a, '175.66')
        p = self.pos(cid); self.assertEqual((p['balance'], p['status']), (D('364.84'), 'partiellement compensée'))
        b = self.later_draft('2026-11-01', '2026-11-30', 1)  # 702.65
        self.assertIn('dépasse le solde disponible de la note de crédit (364,84\xa0CHF', self.offset(cid, b, '400'))
        self.offset(cid, b, '200'); op_b = self.last_op()
        p = self.pos(cid); self.assertEqual((p['reserved'], p['balance']), (D('375.66'), D('164.84')))
        # a draft that carries an imputation cannot drop below it
        self.flashes(); r = self.c.post(f'/invoice/{b}/edit', data={'period_from': '2026-11-01', 'period_to': '2026-11-30', 'qty': '0.25', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25'})
        self.assertIn('annuler d\'abord une imputation', ' '.join(self.page_msgs(r)))
        self.assertEqual(self.scalar('SELECT qty FROM invoices WHERE id=?', (b,)), 1.0)
        # deleting draft A releases its reservation through a visible reversal row
        self.flashes(); self.c.post(f'/invoice/{a}/delete'); self.assertIn('1 imputation(s)', ' '.join(self.flashes()))
        rev = self.sql("SELECT * FROM credit_operations WHERE kind='offset_reversal'")[0]
        self.assertEqual((rev['amount'], rev['target_invoice_id'], rev['note']), (175.66, a, 'brouillon de facture supprimé : imputation libérée'))
        self.assertIn('brouillon de facture n°', rev['target_label'])
        self.assertEqual(self.pos(cid)['balance'], D('340.50'))
        # manual reversal on a draft target
        self.assertIn('Opération annulée', self.reverse(cid, op_b))
        p = self.pos(cid); self.assertEqual((p['balance'], p['status']), (D('540.50'), 'disponible'))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_operations'), 4)  # nothing deleted
        self.offset(cid, b, '540.50')
        self.issue(b, derogate=(13,))
        p = self.pos(cid); self.assertEqual((p['applied'], p['balance'], p['status']), (D('540.50'), D('0.00'), 'compensée'))
        self.assertIn('162,15 CHF', pdf_text(self.c.get(f'/invoice/{b}.pdf').data))  # 702.65 − 540.50
        self.assert_original_untouched()

    def test_offset_targets_restricted(self):
        cid = self.issued_cn(qty='1', treatment='compensation')  # 702.65 TTC
        other = self.mandate(name='Autre client', rate='650', vat='8.1')
        cc = sqlite3.connect(self.db); cc.execute("UPDATE projects SET client='Autre Client Fictif',client_legal_id='CHE-999.999.999' WHERE id=?", (other,)); cc.commit(); cc.close()
        foreign = self.later_draft('2026-10-01', '2026-10-31', 1, pid=other)
        self.assertIn('non admissible', self.offset(cid, foreign, '10'))
        self.assertIn('non admissible', self.offset(cid, self.iid, '10'))  # never the original invoice
        # an invoice issued after the credit note may receive an imputation; its frozen PDF is not altered
        later = self.issued(self.pid, '2026-10-01', '2026-10-31', 1)
        pdf_before = self.c.get(f'/invoice/{later}.pdf').data
        self.offset(cid, later, '100'); op = self.last_op()
        p = self.pos(cid); self.assertEqual((p['applied'], p['reserved'], p['balance']), (D('100.00'), D('0'), D('602.65')))
        self.assertEqual(self.c.get(f'/invoice/{later}.pdf').data, pdf_before)
        self.assertIn('Opération annulée', self.reverse(cid, op))  # not printed on the PDF: may still be corrected
        self.assertEqual(self.pos(cid)['balance'], D('702.65'))

    def test_mode_enforced_on_operations(self):
        comp = self.issued_cn(qty='0.5', treatment='compensation')
        refd = self.issued_cn(amount='100', treatment='remboursement')
        self.assertIn('traitée par compensation', self.refund(comp, '10'))
        target = self.later_draft('2026-10-01', '2026-10-31', 1)
        self.assertIn('traitée par remboursement', self.offset(refd, target, '10'))
        draft, _ = self.credit(amount='5', treatment='remboursement')
        self.assertIn('seule une note de crédit émise', self.refund(draft, '1'))
        c = sqlite3.connect(self.db); c.execute('PRAGMA foreign_keys=ON')
        bad = [f"INSERT INTO credit_operations(credit_note_id,kind,amount,executed_on,created_at) VALUES({comp},'refund',1,'2026-10-01','x')",
               f"INSERT INTO credit_operations(credit_note_id,kind,amount,target_invoice_id,created_at) VALUES({refd},'offset',1,{target},'x')",
               f"INSERT INTO credit_operations(credit_note_id,kind,amount,executed_on,created_at) VALUES({draft},'refund',1,'2026-10-01','x')",
               f"INSERT INTO credit_operations(credit_note_id,kind,amount,executed_on,created_at) VALUES({refd},'refund',-5,'2026-10-01','x')"]
        for q in bad:
            with self.assertRaises(sqlite3.DatabaseError, msg=q): c.execute(q)
        c.close()
        self.refund(refd, '10'); op = self.last_op()
        c = sqlite3.connect(self.db)
        for q in (f'UPDATE credit_operations SET amount=1 WHERE id={op}', f'DELETE FROM credit_operations WHERE id={op}',
                  f"UPDATE credit_notes SET treatment='compensation' WHERE id={refd}",
                  f"INSERT INTO credit_operations(credit_note_id,kind,amount,reverses_id,created_at) VALUES({refd},'refund_reversal',3,{op},'x')"):
            with self.assertRaises(sqlite3.DatabaseError, msg=q): c.execute(q)
        c.close()


class Overflow(Settlement):
    DEROGATE = (13,)   # rc25: fixtures of this class bill days without matching recorded work (or a period past today): these checks are overridden, explicitly
    def test_cumulative_overflow_refused(self):
        _, fl = self.credit(amount='1300.01', treatment='remboursement'); self.assertIn('dépasserait le montant créditable', fl)
        self.credit(amount='1000', treatment='remboursement')  # draft counts against the creditable amount
        _, fl = self.credit(amount='300.01', treatment='compensation'); self.assertIn('solde créditable 300,00\xa0CHF HT', fl)
        _, fl = self.credit(qty='2.5', unit_rate='1', treatment='remboursement')  # tiny rate cannot hide a day overflow (rc11: a rate other than the invoice's is refused outright)
        self.assertIn('tarif de la note de crédit', fl.replace('&#39;', "'"))
        _, fl = self.credit(qty='2.5', treatment='remboursement')                 # same rate: the amount ceiling refuses it (1 625 > 300 left)
        self.assertIn('solde créditable', fl)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 1)
        _, fl = self.credit(amount='300', treatment='compensation'); self.assertIn('Brouillon de note de crédit créé', fl)
        _, fl = self.credit(amount='0.01', treatment='compensation'); self.assertIn('dépasserait', fl)

    def test_issuance_rechecks_overflow(self):
        cid, _ = self.credit(amount='1000', treatment='remboursement')
        c = sqlite3.connect(self.db)  # second draft inserted outside the form, bypassing the creation check
        c.execute("INSERT INTO credit_notes(invoice_id,amount,reason,vat,treatment) VALUES(?,400,'contournement',8.1,'remboursement')", (self.iid,)); c.commit()
        other = c.execute('SELECT MAX(id) FROM credit_notes').fetchone()[0]; c.close()
        self.assertEqual(self.issue_cn(cid)[0], 'draft')  # 1000 + 400 drafts > 1300: refused
        self.c.post(f'/credit/{other}/delete')
        self.assertEqual(self.issue_cn(cid)[0], 'issued')

    def test_invoice_receiving_offsets_cannot_be_overcredited(self):
        cid = self.issued_cn(scope='total', treatment='compensation')  # 1405.30 available
        self.entry(self.pid, '2026-10-05', 8)
        later = self.issued(self.pid, '2026-10-01', '2026-10-31', 1)  # 702.65 TTC, issued after the credit note
        self.offset(cid, later, '702.65')
        self.assertIn('dépasse le montant restant dû', self.offset(cid, later, '0.01'))
        _, fl = self.credit(iid=later, amount='10', treatment='remboursement')
        self.assertIn('augmenté des imputations reçues', fl)


class History(Settlement):
    def test_refund_reversal_and_full_history(self):
        cid = self.issued_cn(qty='0.5', treatment='remboursement')
        self.refund(cid, '100', external_ref='VIR-1'); op = self.last_op()
        self.assertIn('motif d\'annulation obligatoire', self.reverse(cid, op, note=''))
        self.assertIn('Opération annulée', self.reverse(cid, op, note='virement rejeté par la banque (test)'))
        rev = self.last_op()
        self.assertIn('déjà annulée', self.reverse(cid, op))
        self.assertIn('ne peut pas être annulée', self.reverse(cid, rev))
        p = self.pos(cid); self.assertEqual((p['refunded'], p['balance'], p['status']), (D('0'), D('351.33'), 'à rembourser'))
        self.refund(cid, '351.33', external_ref='VIR-2')
        h = m.credits.history(m.db(), self.sql('SELECT * FROM credit_notes WHERE id=?', (cid,))[0])
        self.assertEqual([(e['amount']) for e in h], [None, D('100.00'), D('-100.00'), D('351.33')])
        self.assertIn('VIR-1', h[1]['detail']); self.assertIn('annule l\'opération', h[2]['detail']); self.assertIn('virement rejeté', h[2]['detail'])
        page = html.unescape(self.c.get(f'/credit/{cid}').get_data(as_text=True))
        for needle in ('Historique complet', 'Annulation de remboursement', 'VIR-2', 'remboursée'):
            self.assertIn(needle, page)
        events = [r[0] for r in self.sql("SELECT event FROM audit WHERE event LIKE 'credit_%' ORDER BY id")]
        self.assertEqual(events, ['credit_draft_created', 'credit_note_issued', 'credit_refund_recorded', 'credit_operation_reversed', 'credit_refund_recorded'])
        self.assert_original_untouched()

    def test_original_invoice_cannot_be_modified(self):
        self.issued_cn(qty='0.5', treatment='remboursement')
        c = sqlite3.connect(self.db); c.execute('PRAGMA foreign_keys=ON')
        for q in (f'UPDATE invoices SET qty=1 WHERE id={self.iid}', f'DELETE FROM invoices WHERE id={self.iid}',
                  f'UPDATE invoice_snapshots SET pdf_sha256=\'x\' WHERE invoice_id={self.iid}'):
            with self.assertRaises(sqlite3.DatabaseError, msg=q): c.execute(q)
        c.close()
        self.flashes(); self.c.get(f'/invoice/{self.iid}/edit'); self.assertIn('note de crédit', ' '.join(self.flashes()))
        self.flashes(); self.c.post(f'/invoice/{self.iid}/delete'); self.assertIn('Suppression refusée', ' '.join(self.flashes()))
        self.assert_original_untouched()


class LedgerRestore(V92):
    dump, upload, state = v92.Restore.dump, v92.Restore.upload, v92.Restore.state

    def test_restore_keeps_ledger_and_blocks_its_loss(self):
        pid = self.mandate(name='Mandat restauré', vat='8.1'); self.entry(pid, '2026-09-10', 8)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'r', 'amount': '50', 'treatment': 'remboursement'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.c.post(f'/credit/{cid}/refund', data={'amount': '20', 'executed_on': TODAY})
        raw = self.dump(); saved = self.state()
        self.assertEqual(len(json.loads(raw)['tables']['credit_operations']), 1)
        token = self.upload(raw); self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        self.assertIn('Restauration effectuée', ' '.join(self.flashes()))
        self.assertEqual(self.state(), saved)
        c = sqlite3.connect(self.db)
        with self.assertRaises(sqlite3.DatabaseError): c.execute('DELETE FROM credit_operations')  # triggers rebuilt
        c.close()
        data = json.loads(raw); data['tables']['credit_operations'] = []
        token = self.upload(json.dumps(data).encode())
        page = html.unescape(self.c.get(f'/restore/{token}').get_data(as_text=True))
        self.assertIn('Restauration bloquée', page); self.assertIn(f'NC-{YEAR}-1', page)
