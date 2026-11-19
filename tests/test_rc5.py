"""V9.2-rc5: decisions of 2026-10-03 (synthetic data only, on a COPY of the staging database; see test_import.py
for the run command).

4 legal identifier printed in a normalised form, stored value unchanged (leading zeros kept, original retrievable)
5 back-dated invoice date: distinct from the real issuance timestamp, every change on the draft traced (append-only),
  number from the billed period, nothing changes after issuance
6 total credit of an invoice that received an offset: refused when the offset was consumed at issuance; an offset
  still reversible (on a draft, or recorded after issuance) must first be cancelled by a traceable reversal
"""
import html, json, re, sqlite3
from datetime import date, timedelta
from decimal import Decimal

from app.billing_rules import local_today, local_date  # RC8: business day in Europe/Zurich
import app.app as m
from app import billing_rules as rules
from tests.test_functional import pdf_text
import tests.test_v92 as v92
from tests.test_credit_settlement import Settlement
from tests.test_v92 import V92

D = Decimal
TODAY = local_today()


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N (year of the invoice date = today's year, then the sequence of the year)


def text(r):
    return html.unescape(re.sub(r'<[^>]+>', '', r.get_data(as_text=True)))


class LegalDisplay(V92):
    def test_rule(self):
        cases = {'che000000777': 'CHE-000.000.777', 'CHE-123.456.789': 'CHE-123.456.789', ' che 012 345 678 tva ': 'CHE-012.345.678 TVA',
                 'CHE-012.345.678 MWST': 'CHE-012.345.678 MWST', 'CHE.000.000.001': 'CHE-000.000.001',
                 'HRB 0012345': 'HRB 0012345', 'CHE-12.345': 'CHE-12.345', '': '', None: ''}
        for raw, shown in cases.items(): self.assertEqual(rules.legal_display(raw), shown, raw)
        # same legal client for offsets as before
        self.assertEqual(rules.legal_key('che000000777'), rules.legal_key('CHE-000.000.777'))

    def test_stored_value_unchanged_display_frozen_and_printed(self):
        pid = self.mandate(name='Mandat IDE', legal_id='che000000777')
        self.assertEqual(self.scalar('SELECT client_legal_id FROM projects WHERE id=?', (pid,)), 'che000000777')
        page = text(self.c.get(f'/project/{pid}/edit'))
        self.assertIn('Imprimé : CHE-000.000.777', page); self.assertIn('valeur saisie conservée telle quelle : che000000777', page)
        self.entry(pid, '2026-09-10', 8)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        h = json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,)))
        self.assertEqual((h['client_legal_id'], h['client_legal_id_display']), ('che000000777', 'CHE-000.000.777'))
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn("N° d'identification : CHE-000.000.777", t); self.assertNotIn('che000000777', t)
        # credit note and cancellation document print the same normalised identifier
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'r', 'amount': '10', 'treatment': 'remboursement'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.assertIn("N° d'identification : CHE-000.000.777", pdf_text(self.c.get(f'/credit/{cid}.pdf').data))
        self.c.post(f'/credit/{cid}/cancel', data={'reason': 'test'})
        self.assertIn("N° d'identification : CHE-000.000.777", pdf_text(self.c.get(f'/credit/{cid}/cancellation.pdf').data))

    def test_unknown_format_printed_as_entered(self):
        pid = self.mandate(name='Mandat étranger', legal_id='HRB 0012345')
        self.entry(pid, '2026-09-10', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        self.assertIn("N° d'identification : HRB 0012345", pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))


class InvoiceDateTrace(V92):
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat date'); self.entry(self.pid, '2026-09-10', 8)

    def edit(self, iid, **kw):
        form = {'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25'}
        form.update(kw); self.flashes(); self.c.post(f'/invoice/{iid}/edit', data=form); return ' '.join(self.flashes())

    def hist(self, iid):
        return [tuple(r) for r in self.sql('SELECT old_date,new_date,context FROM invoice_date_changes WHERE invoice_id=? ORDER BY id', (iid,))]

    def test_every_change_traced_then_frozen(self):
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        self.assertIn('Brouillon créé.', fl)
        self.assertIn('Brouillon modifié', self.edit(iid, invoice_date='2026-09-29'))
        self.edit(iid, invoice_date='2026-09-29')  # unchanged: no new trace
        self.edit(iid, invoice_date='')            # back to the real issuance day
        self.edit(iid, invoice_date='2026-10-01')
        self.assertEqual(self.hist(iid), [(None, '2026-09-30', 'création du brouillon'), ('2026-09-30', '2026-09-29', 'modification du brouillon'),
                                          ('2026-09-29', None, 'modification du brouillon'), (None, '2026-10-01', 'modification du brouillon')])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='draft_invoice_date_changed'"), 4)
        page = text(self.c.get(f'/issue/{iid}'))
        self.assertIn('Historique de la date de facture', page); self.assertIn("29.09.2026 → date d'émission", page)  # rc7 (A3)
        self.assertIn('date modifiée 4 fois (tracé)', html.unescape(self.c.get('/?tab=archive').get_data(as_text=True)))
        self.issue(iid)
        inv = self.sql('SELECT number,invoice_date,issued_at FROM invoices WHERE id=?', (iid,))[0]
        # number = the sequence of the year (rc37), printed date as set, real timestamp stored apart
        self.assertEqual((inv['number'], inv['invoice_date']), (f'{YEAR}-1', '2026-10-01'))
        self.assertEqual(local_date(inv['issued_at']), TODAY.isoformat())
        h = json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,)))
        self.assertEqual([(x['old_date'], x['new_date']) for x in h['invoice_date_history']],
                         [(None, '2026-09-30'), ('2026-09-30', '2026-09-29'), ('2026-09-29', None), (None, '2026-10-01')])
        self.assertIn('01.10.2026', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))
        c = sqlite3.connect(self.db)
        try:
            for sql in ("UPDATE invoices SET invoice_date='2026-09-15' WHERE id=?", "UPDATE invoices SET issued_at='2026-09-30T10:00:00' WHERE id=?",
                        "INSERT INTO invoice_date_changes(invoice_id,old_date,new_date,changed_at) VALUES(?,'2026-10-01','2026-09-15','x')",
                        "UPDATE invoice_date_changes SET new_date='2026-09-15' WHERE invoice_id=?", "DELETE FROM invoice_date_changes WHERE invoice_id=?"):
                with self.assertRaises(sqlite3.DatabaseError, msg=sql): c.execute(sql, (iid,))
        finally: c.close()
        self.assertIn('Seul un brouillon peut être modifié', self.edit(iid, invoice_date='2026-09-15'))
        self.assertEqual(len(self.hist(iid)), 4)

    def test_deleted_draft_keeps_its_trace(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        self.c.post(f'/invoice/{iid}/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices WHERE id=?', (iid,)), 0)
        self.assertEqual(len(self.hist(iid)), 1)

    def test_restore_keeps_and_protects_history(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        self.issue(iid)
        raw = v92.Restore.dump(self)
        token = v92.Restore.upload(self, raw); self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        self.assertIn('Restauration effectuée', ' '.join(self.flashes()))
        self.assertEqual(len(self.hist(iid)), 1)
        data = json.loads(raw); data['tables']['invoice_date_changes'] = []
        token = v92.Restore.upload(self, json.dumps(data).encode())
        page = html.unescape(self.c.get(f'/restore/{token}').get_data(as_text=True))
        self.assertIn('Restauration bloquée', page); self.assertIn('modification de date', page)


class TotalCreditAfterOffset(Settlement):
    """Reference invoice (setUp): 2026-09, 2 days × 650, VAT 8.1 % → TTC 1405.30."""
    DEROGATE = (13,)   # rc25: fixtures of this class bill days without matching recorded work (or a period past today): these checks are overridden, explicitly

    def offset_note(self, amount='100'):
        return self.issued_cn(amount=amount, treatment='compensation')  # 100 HT → 108.10 TTC

    def later_draft(self, f='2026-10-01', t='2026-10-31', qty=1):
        self.entry(self.pid, f[:8] + '05', 8 * qty)
        iid, fl = self.draft(self.pid, f, t, qty); self.assertIn('Brouillon créé.', fl); return iid

    def test_draft_offset_cancelled_then_total_credit_allowed(self):
        cid = self.offset_note(); target = self.later_draft()
        self.offset(cid, target, '108.10'); op = self.last_op()
        page = html.unescape(self.c.get(f'/issue/{target}').get_data(as_text=True))
        self.assertIn('Compensations imputées', page); self.assertIn('Encore annulables', page)
        self.assertIn('Opération annulée', self.reverse(cid, op, 'compensation retirée avant émission'))
        self.issue(target, derogate=(13,))
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (target,)), f'{YEAR}-2')
        h = json.loads(self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (target,)))
        self.assertEqual(h['offsets'], [])
        tcid, fl = self.credit(iid=target, scope='total', treatment='remboursement')
        self.assertIn('Brouillon de note de crédit créé', fl)
        self.assertEqual(self.issue_cn(tcid)[0], 'issued')
        self.assertEqual(self.pos(tcid)['ttc'], D('702.65'))
        kinds = [r[0] for r in self.sql('SELECT kind FROM credit_operations WHERE credit_note_id=? ORDER BY id', (cid,))]
        self.assertEqual(kinds, ['offset', 'offset_reversal'])  # traceable: both rows kept
        self.assertEqual(self.pos(cid)['balance'], D('108.10'))   # the note's amount is available again

    def test_consumed_offset_blocks_total_credit_for_good(self):
        cid = self.offset_note(); target = self.later_draft()
        self.offset(cid, target, '108.10'); self.issue(target, derogate=(13,))
        row = tuple(self.sql('SELECT * FROM invoices WHERE id=?', (target,))[0]); pdf = self.c.get(f'/invoice/{target}.pdf').data
        page = html.unescape(self.c.get(f'/invoice/{target}/credit').get_data(as_text=True))
        self.assertIn('Crédit total indisponible', page); self.assertIn('définitivement consommée', page)
        n = self.scalar('SELECT COUNT(*) FROM credit_notes')
        _, fl = self.credit(iid=target, scope='total', treatment='remboursement')
        self.assertIn('crédit total refusé', fl); self.assertIn(f'NC-{YEAR}-1 108,10\xa0CHF', fl)
        # a partial note reaching the full invoice amount is the same total credit
        _, fl = self.credit(iid=target, qty='1', treatment='remboursement')
        self.assertIn('crédit total refusé', fl)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), n)
        # partial credit within the net amount stays possible
        pcid, fl = self.credit(iid=target, amount='100', treatment='remboursement'); self.assertIn('Brouillon de note de crédit créé', fl)
        self.assertEqual(self.issue_cn(pcid)[0], 'issued')
        # the offset itself cannot be taken back, the issued invoice is unchanged
        self.assertIn('figée sur la facture émise', self.reverse(cid, self.sql("SELECT id FROM credit_operations WHERE kind='offset'")[0][0]))
        self.assertEqual(tuple(self.sql('SELECT * FROM invoices WHERE id=?', (target,))[0]), row)
        self.assertEqual(self.c.get(f'/invoice/{target}.pdf').data, pdf)
        self.assertIn('crédit total indisponible (compensation définitive)', html.unescape(self.c.get('/?tab=archive').get_data(as_text=True)))

    def test_offset_recorded_after_issuance_must_be_reversed_first(self):
        cid = self.offset_note(); self.entry(self.pid, '2026-10-05', 8)
        target = self.issued(self.pid, '2026-10-01', '2026-10-31', 1)
        self.offset(cid, target, '50'); op = self.last_op()
        _, fl = self.credit(iid=target, scope='total', treatment='remboursement')
        self.assertIn('crédit total impossible tant que des imputations sont actives', fl)
        self.assertIn('Opération annulée', self.reverse(cid, op))
        tcid, fl = self.credit(iid=target, scope='total', treatment='remboursement')
        self.assertIn('Brouillon de note de crédit créé', fl); self.assertEqual(self.issue_cn(tcid)[0], 'issued')

    def test_total_draft_note_rechecked_at_issuance(self):
        cid = self.offset_note(); self.entry(self.pid, '2026-10-05', 8)
        target = self.issued(self.pid, '2026-10-01', '2026-10-31', 1)
        tcid, fl = self.credit(iid=target, scope='total', treatment='remboursement'); self.assertIn('créé', fl)
        self.offset(cid, target, '50')  # imputed after the total draft note was prepared
        st, fl = self.issue_cn(tcid)
        self.assertEqual(st, 'draft'); self.assertIn('crédit total impossible', fl)
