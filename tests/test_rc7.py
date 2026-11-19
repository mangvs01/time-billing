"""V9.2-rc7: acceptance reserves A1, A2, A3, A4, A6 and the confirmed offset rule (synthetic data only, on a COPY
of the staging database; see test_import.py for the run command).

A1 summary page: the client name is printed in full, wrapped at the normal size in a widened column; never truncated
A2 cancellation document: recalls the mode of the cancelled note (refund / offset)
A3 dates on screen: JJ.MM.AAAA à HH:MM:SS (plain dates JJ.MM.AAAA); stored and audited values stay technical ISO
A4 "NB J" renamed "Jours réalisés cumulés"; realised / invoiced / cancelled by credit notes / contract balance kept apart
A6 invoice date: no 30/90-day limit, never before the billed period, backdating needs an explicit confirmation,
   draft-only, immutable real issuance timestamp, number from the billed period
Offsets: an invoice whose credit note was offset elsewhere stays creditable up to its remaining balance; a consumed
   offset is never cancelled implicitly; no double recovery.
"""
import html, json, re, sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from app.billing_rules import local_today, local_date  # RC8: business day in Europe/Zurich
from app import billing_rules as rules, invoice_service, pdf_layout
from tests.test_credit_settlement import Settlement
from tests.test_functional import pdf_text
from tests.test_rc6 import LONG_CLIENT, Rc6

TODAY = local_today()


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N (year of the invoice date = today's year, then the sequence of the year)


def conn(db):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row; return c


def visible(page):
    """Text a user sees: tags removed (input values and attributes excluded), entities decoded."""
    return html.unescape(re.sub(r'<[^>]+>', ' ', page))


class A1ClientName(Rc6):
    def test_long_client_in_full_at_normal_size_inside_its_column(self):
        self.set_client(LONG_CLIENT)
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2); self.issue(iid)
        h, rows = self.header(iid)
        drawn = []; orig = pdf_layout.Doc.text
        def spy(self_, x, top, s_, size=8, font=pdf_layout.BODY, color=None, align="left", label=None, **kw):
            if s_:
                w = self_.c.stringWidth(s_, font, size)
                drawn.append((self_.c.getPageNumber(), x - w if align == "right" else x, s_, size, w))   # left edge (G4/D6: a right-aligned line on the summary page)
            return orig(self_, x, top, s_, size=size, font=font, **({"color": color} if color is not None else {}), align=align, label=label)
        pdf_layout.Doc.text = spy
        try: pdf_layout.render_invoice(h, rows, issued=True)
        finally: pdf_layout.Doc.text = orig
        last = max(p for p, *_ in drawn)
        x0, x1 = pdf_layout.SUMMARY_COLS[2], pdf_layout.SUMMARY_COLS[3]
        client = [(s, size, w) for p, x, s, size, w in drawn if p == last and x == x0 and s not in ('Client',)]
        self.assertEqual(' '.join(s for s, _, _ in client[:len(client)]).split()[:len(LONG_CLIENT.split())], LONG_CLIENT.split())
        self.assertTrue(all(size == 10.3 for _, size, _ in client), 'no size reduction')
        self.assertTrue(all(x0 + w <= x1 - 6 + 0.01 for _, _, w in client), 'every line stays inside the Client column')
        # nothing on the summary page runs past the frame
        self.assertTrue(all(x + w <= pdf_layout.SUMMARY_RIGHT for p, x, s, size, w in drawn if p == last))
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertNotIn('…', t)

    def test_reference_client_short_name_on_one_line(self):
        self.set_client('Client Recette — Direction des Infrastructures')
        d = pdf_layout.Doc(); w = pdf_layout.SUMMARY_COLS[3] - pdf_layout.SUMMARY_COLS[2] - 6
        size, lines = d.fit_cell('Client Recette', w, 10.3, pdf_layout.SHEET)
        self.assertEqual((size, lines), (10.3, ['Client Recette']))
        size, lines = d.fit_cell('Client Recette — Direction des Infrastructures', w, 10.3, pdf_layout.SHEET)
        self.assertEqual(size, 10.3); self.assertEqual(' '.join(lines), 'Client Recette — Direction des Infrastructures')


class A2CancellationMode(Rc6):
    def test_both_modes_recalled_on_the_frozen_cancellation(self):
        self.set_client('CLI')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2); self.issue(iid)
        for treatment, mode in (('remboursement', 'remboursement (aucun remboursement en vigueur)'),
                                ('compensation', 'compensation sur facture ultérieure (aucune imputation en vigueur)')):
            self.c.post(f'/invoice/{iid}/credit', data={'reason': 'r', 'qty': '0.25', 'treatment': treatment})
            cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
            self.c.post(f'/credit/{cid}/cancel', data={'reason': 'mode erroné (test)'})
            t = ' '.join(pdf_text(self.c.get(f'/credit/{cid}/cancellation.pdf').data).split())
            self.assertIn(f'Mode de traitement de la note annulée : {mode}.', t)


class A3Dates(Rc6):
    def test_rule(self):
        for raw, shown in {'2026-10-03T13:13:26': '03.10.2026 à 15:13:26', '2026-10-03 07:05:00': '03.10.2026 à 09:05:00',
                           '2026-10-03 07:05': '03.10.2026 à 09:05:00', '2026-10-03T13:13:26.5': '03.10.2026 à 15:13:26',
                           '2026-10-03': '03.10.2026', '': '', None: '', 'n/a': 'n/a'}.items():
            self.assertEqual(rules.fr_ts(raw), shown, raw)
        self.assertEqual(rules.fr_periods_in('brouillon (M, 2026-07-01 → 2026-07-31) facture 2026-07-12'), 'brouillon (M, 01.07.2026 → 31.07.2026) facture 2026-07-12')

    def test_no_iso_date_visible_and_technical_values_kept(self):
        self.set_client('CLI')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, invoice_date='2026-09-30')
        for url in (f'/invoice/{iid}/edit', f'/issue/{iid}'):
            page = self.c.get(url).get_data(as_text=True)
            self.assertNotRegex(visible(page), r'\b\d{4}-\d{2}-\d{2}\b', url)
            self.assertRegex(visible(page), r'\d{2}\.\d{2}\.\d{4} à \d{2}:\d{2}:\d{2}', url)
        self.issue(iid)
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'r', 'qty': '0.5', 'treatment': 'remboursement', 'refund_delay_days': '10'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.c.post(f'/credit/{cid}/refund', data={'amount': '10', 'executed_on': TODAY.isoformat()})
        for url in (f'/credit/{cid}', '/?tab=archive', '/?tab=mandates', '/?tab=dashboard', f'/invoice/{iid}/credit'):
            page = self.c.get(url).get_data(as_text=True)
            body = page.split('<body>', 1)[-1]
            self.assertNotRegex(visible(body), r'\b\d{4}-\d{2}-\d{2}\b', url)
        page = self.c.get(f'/credit/{cid}').get_data(as_text=True)
        self.assertIn(f'exécuté le {TODAY.strftime("%d.%m.%Y")}', visible(page))
        issued_at = self.scalar('SELECT issued_at FROM invoices WHERE id=?', (iid,))
        archive = self.c.get('/?tab=archive').get_data(as_text=True)
        self.assertIn(f'<time datetime="{issued_at}Z" title="UTC {issued_at}">{rules.fr_ts(issued_at)}</time>', archive)
        # stored and audited values: technical ISO, untouched
        self.assertRegex(issued_at, r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')
        self.assertEqual(self.scalar('SELECT invoice_date FROM invoices WHERE id=?', (iid,)), '2026-09-30')
        self.assertEqual(self.scalar("SELECT executed_on FROM credit_operations WHERE kind='refund'"), TODAY.isoformat())
        self.assertIn(f'invoice_date=2026-09-30;issued_at={issued_at}', self.scalar("SELECT detail FROM audit WHERE event='invoice_issued'"))
        self.assertIn('"invoice_date": "2026-09-30"', self.scalar('SELECT header_json FROM invoice_snapshots WHERE invoice_id=?', (iid,)))

    def test_flash_dates_in_french(self):
        self.set_client('CLI')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2); self.issue(iid); self.flashes()
        self.c.post('/entry', data={'work_date': '2026-09-15', 'project_id': self.pid, 'entry_mode': 'duration', 'manual_hours': '1'})
        self.assertIn("facture émise jusqu'au 30.09.2026", ' '.join(self.flashes()))
        _, fl = self.draft(self.pid, '2026-09-15', '2026-10-15', 1)
        self.assertIn('(01.09.2026 → 30.09.2026)', ' '.join(fl))


class A4Days(Settlement):
    """setUp: mandate 12 days ordered, 2 days realised (16 h) and invoiced (2026-09, 2 × 650, VAT 8.1 %)."""

    def summary(self, data):
        t = pdf_text(data); return t[t.rindex('PROJET'):]

    def test_renamed_and_kept_apart_on_the_pdf(self):
        self.entry(self.pid, '2026-10-05', 12)                      # 1.5 days realised in October
        cid = self.issued_cn(qty='0.5', treatment='remboursement')  # 0.5 day cancelled on 2026-09
        iid, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1.5)
        s = self.summary(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn('Jours réalisés', s); self.assertIn('cumulés', s); self.assertNotRegex(s, r'(?m)^NB J$')
        self.assertIn('NB J PO', s)  # ordered days column of the reference kept
        one = ' '.join(s.split())
        # G4: the invoiced days are SEVEN-way separated: historical (outside Time Billing), earlier Time Billing invoices, this invoice, credit notes
        for label in (f"Position contractuelle en jours au {local_today().strftime('%d.%m.%Y')}", 'Jours commandés (PO)',   # D9: the date of the invoice (today for an undated draft) 'Jours facturés historiques (hors Time Billing)',
                      'Jours facturés Time Billing antérieurs', 'Jours facturés par cette facture', 'Jours annulés par notes de crédit', 'Solde contractuel'):
            self.assertIn(label, one)
        # ordered 12 · realised 3,50 · historical 0 · earlier Time Billing 2 · this draft 1,50 · cancelled 0,50 · balance 12 − (0 + 2 + 1,50 − 0,50) = 9
        figures = re.findall(r'(?m)^(\d+(?:,\d+)?)$', s)
        self.assertEqual(figures[-7:], ['12', '3,50', '0', '2', '1,50', '0,50', '9'])
        self.issue(iid, derogate=(13,))
        h = invoice_service.frozen_header(conn(self.db), iid)
        self.assertEqual({k: h['position'][k] for k in ('ordered', 'realized', 'historical', 'previous', 'current', 'invoiced', 'credited', 'balance')},
                         {'ordered': 12.0, 'realized': 3.5, 'historical': 0, 'previous': 2.0, 'current': 1.5, 'invoiced': 3.5, 'credited': 0.5, 'balance': 9.0})
        self.assertEqual(h['position']['historical_items'], [])

    def test_screens_kept_apart(self):
        self.issued_cn(qty='0.5', treatment='remboursement')
        for tab in ('dashboard', 'mandates'):
            t = visible(self.c.get(f'/?tab={tab}').get_data(as_text=True))
            for label in ('Jours réalisés cumulés', 'Jours facturés', 'Jours annulés par notes de crédit', 'Solde contractuel (j)'):
                self.assertIn(label, t, tab)
        c = conn(self.db); k = rules.contract(c, c.execute('SELECT * FROM projects WHERE id=?', (self.pid,)).fetchone()); c.close()
        self.assertEqual((k['gross_billed_days'], k['credited_days'], k['billed_days'], k['po_balance_days']), (2.0, 0.5, 1.5, 10.5))

    def test_history_not_modified(self):
        tables = ('entries', 'invoices', 'invoice_snapshots', 'invoice_annex_entries', 'credit_notes', 'credit_note_snapshots', 'credit_operations')
        before = {t: self.sql(f'SELECT * FROM {t} ORDER BY rowid') for t in tables}
        pdf = self.c.get(f'/invoice/{self.iid}.pdf').data
        for url in ('/?tab=dashboard', '/?tab=mandates', '/?tab=archive', f'/invoice/{self.iid}/credit'): self.c.get(url)
        self.assertEqual({t: self.sql(f'SELECT * FROM {t} ORDER BY rowid') for t in tables}, before)
        self.assertEqual(pdf, self.inv_pdf)  # an invoice issued earlier keeps its frozen PDF, byte for byte


class A6InvoiceDate(Settlement):
    def draft_dated(self, d, f='2026-03-01', t='2026-03-31'):
        self.entry(self.pid, f[:8] + '10', 8)
        iid, fl = self.draft(self.pid, f, t, 1, invoice_date=d); return iid, fl

    def test_no_day_limit_backdating_with_explicit_confirmation(self):
        far = (TODAY - timedelta(days=200)).isoformat()   # beyond any 30 / 90-day window
        f = min(far[:8] + '01', '2026-03-01'); t = (date.fromisoformat(f) + timedelta(days=27)).isoformat()
        iid, fl = self.draft_dated(far, f, t); self.assertIn('Brouillon créé.', fl)
        page = visible(self.c.get(f'/issue/{iid}').get_data(as_text=True))
        self.assertIn('Facture antidatée', page); self.assertIn('Je confirme émettre cette facture', page)
        self.flashes(); self.issue(iid, confirm_backdate=False, derogate=(13,))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        self.assertIn("antérieure à la date réelle d'émission", ' '.join(self.flashes()))
        # a confirmation given for another date does not count
        self.c.post(f'/issue/{iid}', data={'reliquat_treatment': 'reporte', 'confirm_backdate': TODAY.isoformat()})
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)   # issued_at is stored as naive UTC, whatever the host's TZ
        before = utcnow()
        self.flashes(); self.issue(iid, derogate=(13,))
        after = utcnow()
        row = self.sql('SELECT number,invoice_date,issued_at,status FROM invoices WHERE id=?', (iid,))[0]
        self.assertEqual(row['status'], 'issued', self.flashes())
        self.assertRegex(row['number'], rf'{far[:4]}-\d+')           # rc37: the YEAR of the printed date, then the sequence (not the billed period)
        self.assertEqual(row['invoice_date'], far)                   # printed date as chosen
        self.assertTrue(before <= datetime.fromisoformat(row['issued_at']) <= after, (row['issued_at'], before, after))  # real issuance timestamp
        self.assertIn('backdated=confirmed', self.scalar("SELECT detail FROM audit WHERE event='invoice_issued' ORDER BY id DESC LIMIT 1"))
        self.assertIn(f'Date :\n{pdf_layout.dmy(far)}', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))
        self.assertIn('(antidatée)', visible(self.c.get('/?tab=archive').get_data(as_text=True)))

    def test_issue_day_needs_no_confirmation(self):
        self.entry(self.pid, '2026-10-05', 8)
        iid, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1, invoice_date=TODAY.isoformat()) if TODAY.isoformat() >= '2026-10-01' else (None, '')
        if iid is None: self.skipTest('date du jour antérieure à la période de test')
        self.issue(iid, confirm_backdate=False, derogate=(13,))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued')

    def test_never_before_period_start(self):
        _, fl = self.draft_dated('2026-02-28')
        self.assertIn('ne peut pas précéder le début de la période facturée', ' '.join(fl))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM invoices WHERE period_from='2026-03-01'"), 0)

    def test_future_date_still_refused_at_issuance(self):
        self.entry(self.pid, '2026-10-05', 8)
        iid, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1, invoice_date=(TODAY + timedelta(days=3)).isoformat())
        self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')

    def test_date_and_issuance_timestamp_immutable_after_issuance(self):
        iid, _ = self.draft_dated('2026-03-15'); self.issue(iid, derogate=(13,))
        row = tuple(self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0])
        self.flashes(); self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-03-01', 'period_to': '2026-03-31', 'qty': '1', 'unit': 'day',
                                                                   'rounding': 'exact', 'rounding_step': '0.25', 'invoice_date': '2026-03-20'})
        self.assertIn('Seul un brouillon peut être modifié', ' '.join(self.flashes()))
        c = sqlite3.connect(self.db)
        for sql in ("UPDATE invoices SET issued_at='2026-03-15T09:00:00' WHERE id=?", "UPDATE invoices SET invoice_date='2026-03-20' WHERE id=?"):
            with self.assertRaises(sqlite3.IntegrityError): c.execute(sql, (iid,))
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("INSERT INTO invoice_date_changes(invoice_id,old_date,new_date,changed_at) VALUES(?,?,?,?)", (iid, '2026-03-15', '2026-03-20', 'x'))
        c.close()
        self.assertEqual(tuple(self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]), row)

    def test_issued_at_written_only_by_issuance(self):
        iid, _ = self.draft_dated('2026-03-15')
        c = sqlite3.connect(self.db)
        with self.assertRaises(sqlite3.IntegrityError): c.execute("UPDATE invoices SET issued_at='2026-03-15T09:00:00' WHERE id=?", (iid,))
        with self.assertRaises(sqlite3.IntegrityError): c.execute("UPDATE invoices SET status='issued',number='X' WHERE id=?", (iid,))
        c.close()
        self.assertIsNone(self.scalar('SELECT issued_at FROM invoices WHERE id=?', (iid,)))


class ConfirmedOffsetRule(Settlement):
    """Reference invoice A (setUp): 2026-09, 2 days × 650, VAT 8.1 % → TTC 1405.30. Its note NC-2026-09 (100 HT,
    108.10 TTC, offset mode) is imputed on invoice B (2026-10, 1 day → TTC 702.65)."""
    DEROGATE = (13,)   # rc25: fixtures of this class bill days without matching recorded work (or a period past today): these checks are overridden, explicitly

    def setup_offset(self, frozen=True):
        cid = self.issued_cn(amount='100', treatment='compensation')
        self.entry(self.pid, '2026-10-05', 8)
        if frozen:
            b, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1); self.offset(cid, b, '108.10'); self.issue(b)
        else:
            b = self.issued(self.pid, '2026-10-01', '2026-10-31', 1); self.offset(cid, b, '108.10')
        return cid, b

    def credited_ttc(self, iid):
        return sum((self.pos(r[0])['ttc'] for r in self.sql("""SELECT id FROM credit_notes WHERE invoice_id=? AND status='issued'
                    AND id NOT IN (SELECT credit_note_id FROM credit_note_cancellations)""", (iid,))), D('0'))

    def test_origin_invoice_stays_creditable_up_to_its_balance(self):
        cid, b = self.setup_offset()
        page = visible(self.c.get(f'/invoice/{self.iid}/credit').get_data(as_text=True))
        self.assertNotIn('Crédit total indisponible', page)
        # more than the balance is refused
        _, fl = self.credit(amount='1200.01', treatment='remboursement'); self.assertIn('dépasserait', fl)
        tcid, fl = self.credit(scope='total', treatment='remboursement'); self.assertIn('Brouillon de note de crédit créé', fl)
        self.assertEqual(self.issue_cn(tcid)[0], 'issued')
        self.assertEqual(self.pos(tcid)['ttc'], D('1297.20'))                  # 1405.30 − 108.10 still available
        self.assertEqual(self.credited_ttc(self.iid), D('1405.30'))            # never more than invoice A
        _, fl = self.credit(amount='1', treatment='remboursement'); self.assertIn('entièrement créditée', fl) if 'entièrement' in fl else self.assertIn('dépasserait', fl)
        # the offset consumed on B is untouched
        self.assertEqual(self.pos(cid)['applied'], D('108.10'))

    def test_consumed_offset_never_cancelled_implicitly(self):
        cid, b = self.setup_offset()
        op = self.sql("SELECT id FROM credit_operations WHERE kind='offset'")[0][0]
        self.assertIn('figée sur la facture émise', self.reverse(cid, op))
        self.flashes(); self.c.post(f'/credit/{cid}/cancel', data={'reason': 'essai'})
        self.assertEqual(self.sql('SELECT reference FROM credit_note_cancellations WHERE credit_note_id=?', (cid,)), [])
        _, fl = self.credit(iid=b, scope='total', treatment='remboursement'); self.assertIn('crédit total refusé', fl)
        # B credited within its net amount only: B net due 594.55
        _, fl = self.credit(iid=b, amount='600', treatment='remboursement'); self.assertIn('dépasserait', fl)
        pcid, fl = self.credit(iid=b, amount='500', treatment='remboursement'); self.assertIn('créé', fl)
        self.assertEqual(self.issue_cn(pcid)[0], 'issued')
        self.assertLessEqual(self.credited_ttc(b) + D('108.10'), D('702.65'))    # no double recovery on B
        self.assertEqual([r[0] for r in self.sql('SELECT kind FROM credit_operations WHERE credit_note_id=? ORDER BY id', (cid,))], ['offset'])

    def test_reversible_offset_needs_an_explicit_traceable_reversal(self):
        cid, b = self.setup_offset(frozen=False)
        _, fl = self.credit(iid=b, scope='total', treatment='remboursement'); self.assertIn('crédit total impossible tant que des imputations sont actives', fl)
        op = self.last_op(); self.assertIn('Opération annulée', self.reverse(cid, op, 'correction tracée'))
        tcid, fl = self.credit(iid=b, scope='total', treatment='remboursement'); self.assertIn('créé', fl)
        self.assertEqual(self.issue_cn(tcid)[0], 'issued')
        self.assertEqual(self.pos(cid)['balance'], D('108.10'))                  # the note is available again…
        self.assertEqual(self.credited_ttc(b), D('702.65'))                      # …and B is credited once, in full
        self.assertEqual([r[0] for r in self.sql('SELECT kind FROM credit_operations WHERE credit_note_id=? ORDER BY id', (cid,))], ['offset', 'offset_reversal'])


class Integrity(Settlement):
    def test_integrity_after_rc7_flows(self):
        ConfirmedOffsetRule.setup_offset(self)
        c = sqlite3.connect(self.db)
        self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
        for iid, pdf, sha in c.execute('SELECT invoice_id,pdf,pdf_sha256 FROM invoice_snapshots'):
            import hashlib; self.assertEqual(hashlib.sha256(pdf).hexdigest(), sha)
        c.close()
