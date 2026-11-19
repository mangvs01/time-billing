"""V9.2-rc4: document fidelity (R3-R12) and business rules R1/R2 (2026-10-03). Synthetic data only, on a COPY
of the staging database (see test_import.py for the run command).

R1 refund deadline optional, configurable, clearly displayed · R2 invoice date = real issuance day, editable on
the draft only, number still from the billed period · R3 reference typography · R4/R6 annex grid and frames,
bold totals · R5 "Page x of y" · R8 mandate information in the annex · R9 French number format on screen ·
R10 « AUTRES » visible on credit notes · R11 login title · R12 client legal identity printed.
Non-regression: every value printed by the rc3 layout is still printed, unchanged, by the rc4 layout.
"""
import html, re, sqlite3
from collections import Counter
from datetime import date, timedelta

from app.billing_rules import local_today, local_date  # RC8: business day in Europe/Zurich
import app.app as m
from app import billing_rules as rules, invoice_service, pdf_layout
from tests import _layout_rc3
from tests.test_functional import REF_HOURS, _font_maps, _pdf_objects, _stream, _unescape, pdf_text
from tests.test_credit_settlement import Settlement
from tests.test_v92 import V92
from tests.test_import import FAKE_ISSUER

TODAY = local_today()


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N (year of the invoice date = today's year, then the sequence of the year)


def pdf_runs(data):
    """[(page index, base font, text)] for every text-show operand."""
    objs = _pdf_objects(data); maps = _font_maps(objs)
    base = {}
    for body in objs.values():
        for name, ref in re.findall(rb'/([A-Za-z0-9_.+-]+)\s+(\d+) 0 R', body):
            b = re.search(rb'/BaseFont\s*/([^\s/>]+)', objs.get(int(ref), b''))
            if b: base[name] = b.group(1).decode()
    out = []; page = 0
    for body in objs.values():
        if b'/Length' not in body: continue
        s = _stream(body)
        if b' Tf' not in s: continue
        page += 1; font = None
        for tok in re.finditer(rb'/([A-Za-z0-9_.+-]+)\s+[\d.]+\s+Tf|\((.*?)(?<!\\)\)\s*Tj', s, re.S):
            if tok.group(1) is not None: font = tok.group(1); continue
            raw = _unescape(tok.group(2)); cmap = maps.get(font)
            out.append((page, base.get(font, ''), ''.join(cmap.get(b, '�') for b in raw) if cmap else raw.decode('cp1252', 'replace')))
    return out


def page_count(data):
    return len(re.findall(rb'/Type\s*/Page[^s]', data))


class Rc4(V92):
    def legal_mandate(self, name='Mandat rc4', short='CIRSE 2026', legal_name='Entité Juridique Fictive SA', **kw):
        pid = self.mandate(name=name, **kw)
        self.c.post(f'/project/{pid}/edit', data={'name': name, 'short_name': short, 'client': 'BSCI', 'po': 'PO-RC4-001', 'rate': kw.get('rate', '650'),
                                                   'ordered_days': '12', 'vat': kw.get('vat', '0'), 'day_hours': '8', 'project_number': 'NP-RC4',
                                                   'billing_contact': 'Contact Fictif', 'billing_address': 'Entité Fictive\nRue 1\n1000 Ville',
                                                   'dates_label': '05-09 Sept 2026', 'start_date': '2025-11-01', 'duration_months': '11',
                                                   'client_legal_name': legal_name, 'client_legal_id': 'CHE-000.000.777'})
        return pid


class Typography(Rc4):
    def test_reference_font_roles_embedded(self):
        pid = self.legal_mandate()
        self.entry(pid, '2026-09-10', 8)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        runs = pdf_runs(self.c.get(f'/invoice/{iid}.pdf').data)
        fonts_p1 = {f for p, f, t in runs if p == 1}; fonts_annex = {f for p, f, t in runs if p > 1}
        self.assertTrue(all('Helvetica' not in f for p, f, t in runs), 'no standard Helvetica left in rc4 documents')
        self.assertTrue(any('NunitoSans' in f or 'AvenirNext' in f for f in fonts_p1))       # Avenir Next Light role
        self.assertTrue(any('Carlito' in f or 'Calibri' in f for f in fonts_annex))          # Calibri role
        # reference: sub-total amount in Cambria (Caladea substitute), "Je vous remercie" in light italic
        self.assertTrue(any(('Caladea' in f or 'Cambria' in f) and t == '650,00 CHF' for p, f, t in runs if p == 1), [r for r in runs if r[0] == 1])
        self.c.post('/settings', data=dict(FAKE_ISSUER, thanks_text='Je vous remercie de votre confiance.'))
        d, _ = self.draft(pid, '2026-10-01', '2026-10-31', 1)
        thanks = [f for p, f, t in pdf_runs(self.c.get(f'/invoice/{d}.pdf').data) if t == 'Je vous remercie de votre confiance.']
        self.assertTrue(thanks and all('LightItalic' in f or 'LightIt' in f for f in thanks), thanks)
        self.assertEqual(set(pdf_layout.FONTS_USED), set(pdf_layout.FONT_ROLES))
        self.assertIn('Typographie des documents', self.c.get('/?tab=settings').get_data(as_text=True))


class AnnexLayout(Rc4):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def test_pagination_page_x_of_y(self):
        pid = self.load_reference()  # 11 months nov-25 → sept-26, 65.2 h
        iid = self.issued(pid, '2025-11-01', '2026-09-30', 8, derogate=(12,))   # rc41: 8 j for 8.15 j worked, check 12 overridden
        data = self.c.get(f'/invoice/{iid}.pdf').data
        self.assertEqual(page_count(data), 13)  # like the reference: 1 + 11 timesheets + summary
        runs = pdf_runs(data)
        marks = [(p, t) for p, f, t in runs if t.startswith('Page ')]
        self.assertEqual(marks, [(p, f'Page {p - 1} of 12') for p in range(2, 14)])
        self.assertFalse(any(t.startswith('Page ') for p, f, t in runs if p == 1))

    def test_long_month_continues_on_next_page_with_single_total(self):
        pid = self.legal_mandate()
        for k in range(30): self.entry(pid, f'2026-09-{k % 28 + 1:02d}', 0.5, desc=f'tâche {k}')
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1.875)      # 15 h worked = 1.875 j
        data = self.c.get(f'/invoice/{iid}.pdf').data
        runs = pdf_runs(data)
        self.assertEqual(page_count(data), 4)  # page 1 + 2 timesheet pages (21 + 9 rows) + summary
        self.assertEqual([t for p, f, t in runs if t.startswith('Page ')], ['Page 1 of 3', 'Page 2 of 3', 'Page 3 of 3'])
        self.assertIn('sept-26 (suite)', [t for p, f, t in runs if p == 3])
        self.assertEqual(len([1 for p, f, t in runs if p == 2 and re.fullmatch(r'\d\d/09/2026', t)]), 21)
        self.assertEqual(len([1 for p, f, t in runs if p == 3 and re.fullmatch(r'\d\d/09/2026', t)]), 9)
        totals = [(p, f) for p, f, t in runs if t == 'Total']
        self.assertEqual([p for p, f in totals], [3])  # the month total only once, after its last row

    def test_grid_frames_and_bold_total(self):
        pid = self.legal_mandate()
        for d in ('2026-09-01', '2026-09-02', '2026-09-03'): self.entry(pid, d, 2.5)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 0.9375)      # 7.5 h worked = 0.9375 j
        data = self.c.get(f'/invoice/{iid}.pdf').data
        runs = pdf_runs(data)
        total_value = [(f, t) for p, f, t in runs if p == 2 and t == '7,50']
        self.assertTrue(any('Bold' in f for f, t in total_value), total_value)       # monthly total value in bold
        self.assertTrue(any('Bold' not in f for f, t in total_value), total_value)   # the header figure stays light
        streams = [_stream(b) for b in _pdf_objects(data).values() if b'/Length' in b]
        annex = [s for s in streams if b'Tf' in s][1]
        grey_rules = len(re.findall(rb'\.682353 \.666667 \.666667 rg\s+n?\s*[\d. -]+ re f', annex))
        self.assertEqual(grey_rules, 3)                 # one thin grey rule under each of the 3 rows
        self.assertGreaterEqual(annex.count(b' re f'), 3 + 2 + 3 + 2)  # + band/blue rules, header, frame sides
        summary = [s for s in streams if b'Tf' in s][2]
        self.assertGreaterEqual(summary.count(b' re f'), 5)  # framed summary: 3 horizontal + 2 vertical rules
        self.assertTrue(any('Bold' in f for p, f, t in runs if p == 3 and t == 'PROJET'))

    def test_mandate_information_in_annex_and_summary(self):
        pid = self.legal_mandate()
        self.entry(pid, '2026-09-10', 8)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        runs = pdf_runs(self.c.get(f'/invoice/{iid}.pdf').data)
        annex = [t for p, f, t in runs if p == 2]; summary = [t for p, f, t in runs if p == 3]
        self.assertIn('CIRSE 2026', annex); self.assertIn('NP-RC4', annex); self.assertNotIn('Mandat rc4', annex)
        for v in ('CIRSE 2026', '05-09 Sept 2026', 'BSCI', 'NP-RC4', 'PO-RC4-001', '12', '1'): self.assertIn(v, summary)
        # without a short name the full mandate name is used
        self.c.post(f'/project/{pid}/edit', data={'name': 'Mandat rc4', 'short_name': '', 'rate': '650', 'day_hours': '8', 'client': 'BSCI',
                                                   'billing_address': 'Entité Fictive\nRue 1\n1000 Ville'})
        self.entry(pid, '2026-10-02', 8)
        d2, _ = self.draft(pid, '2026-10-01', '2026-10-31', 1)
        self.assertIn('Mandat rc4', [t for p, f, t in pdf_runs(self.c.get(f'/invoice/{d2}.pdf').data) if p == 3])

    def test_missing_summary_information_flagged_on_draft_only(self):
        pid = self.mandate(name='Mandat sans infos')
        self.c.post(f'/project/{pid}/edit', data={'name': 'Mandat sans infos', 'rate': '650', 'day_hours': '8', 'client': 'X', 'billing_address': 'X\nY'})
        self.entry(pid, '2026-09-10', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        for label in ('Dates', 'N° projet', 'PO'): self.assertIn(f'[À COMPLÉTER : {label}]', t)


class LegalIdentity(Settlement):
    DEROGATE = (13,)   # rc25: fixtures of this class bill days without matching recorded work (or a period past today): these checks are overridden, explicitly
    def setUp(self):
        super().setUp()
        self.c.post(f'/project/{self.pid}/edit', data={'name': 'Mandat NC2', 'rate': '650', 'day_hours': '8', 'vat': '8.1', 'ordered_days': '12', 'client': 'Client Fictif SA',
                                                        'billing_address': 'Client Fictif SA\nRue Imaginaire 1\n9999 Nulle-Part', 'client_legal_name': 'Holding Fictive SA',
                                                        'client_legal_id': 'CHE-000.000.001'})

    def test_identity_on_invoice_credit_note_and_cancellation(self):
        self.entry(self.pid, '2026-10-10', 8)
        iid = self.issued(self.pid, '2026-10-01', '2026-10-31', 1)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn('Holding Fictive SA', t); self.assertIn("N° d'identification : CHE-000.000.001", t)
        cid, _ = self.credit(iid=iid, qty='0.5', treatment='remboursement'); self.issue_cn(cid)
        self.assertIn("N° d'identification : CHE-000.000.001", pdf_text(self.c.get(f'/credit/{cid}.pdf').data))
        self.op(f'/credit/{cid}/cancel', reason='erreur de mode (test)')
        self.assertIn("N° d'identification : CHE-000.000.001", pdf_text(self.c.get(f'/credit/{cid}/cancellation.pdf').data))

    def test_legal_name_not_repeated_when_already_in_address(self):
        # setUp's first invoice froze legal name 'Client Fictif SA', already the first address line
        t = pdf_text(self.inv_pdf)
        # once in the address block on page 1, once in the summary Client column (rc7: printed in full, column widened)
        self.assertEqual(t.count('Client Fictif SA'), 2); self.assertIn("N° d'identification : CHE-000.000.001", t)


class OtherOnCreditNotes(Settlement):
    def test_autres_only_credit_is_visible(self):
        pid = self.mandate(name='Mandat autres', rate='1000', vat='8.1')
        self.entry(pid, '2026-09-10', 16)
        d, _ = self.draft(pid, '2026-09-01', '2026-09-30', 2, other_amount='120', other_label='Frais fictifs', other_vat_mode='hors_tva')
        self.issue(d); iid = d
        cid, fl = self.credit(iid=iid, other_amount='120', treatment='remboursement'); self.issue_cn(cid)
        t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        self.assertIn('AUTRES — Frais fictifs (hors TVA)', t); self.assertIn('120,00 CHF', t)
        self.assertNotIn('0,00 CHF', t.replace('120,00 CHF', ''))  # no 0,00 service line any more
        archive = self.c.get('/?tab=archive').get_data(as_text=True)
        self.assertIn('dont AUTRES − 120,00\xa0CHF', archive)
        self.assertIn('AUTRES 120,00\xa0CHF (hors TVA)', archive)


class InvoiceDate(Rc4):
    def setUp(self):
        super().setUp()
        self.pid = self.legal_mandate()
        self.entry(self.pid, '2026-09-10', 8)

    def test_default_is_real_issuance_day(self):
        iid = self.issued(self.pid, '2026-09-01', '2026-09-30', 1)
        self.assertEqual(self.scalar('SELECT invoice_date FROM invoices WHERE id=?', (iid,)), TODAY.isoformat())
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (iid,)), f'{YEAR}-1')

    def test_date_set_on_draft_is_printed_number_from_period(self):
        chosen = max(date(2026, 9, 1), TODAY - timedelta(days=2)).isoformat()
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 1, invoice_date=chosen)
        self.assertIn(f"{date.fromisoformat(chosen).strftime('%d.%m.%Y')} (prévue)", pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))
        page = self.c.get(f'/issue/{iid}').get_data(as_text=True)
        self.assertIn(f'<b>{rules.fr_date(chosen)}</b>', page)  # rc7 (A3); self.assertIn('date fixée sur le brouillon', page)
        self.issue(iid)
        row = self.sql('SELECT number,invoice_date,issued_at FROM invoices WHERE id=?', (iid,))[0]
        self.assertEqual((row['number'], row['invoice_date']), (f'{YEAR}-1', chosen))
        self.assertEqual(local_date(row['issued_at']), TODAY.isoformat())  # RC8: UTC timestamp, Zurich day  # the real issuance timestamp is kept too
        self.assertIn(date.fromisoformat(chosen).strftime('%d.%m.%Y'), pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))
        self.assertIn(f'invoice_date={chosen};issued_at={row["issued_at"]}', self.scalar("SELECT detail FROM audit WHERE event='invoice_issued'"))

    def test_date_editable_on_draft_only(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 1)
        form = {'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25', 'invoice_date': '2026-09-15'}
        self.c.post(f'/invoice/{iid}/edit', data=form)
        self.assertEqual(self.scalar('SELECT invoice_date FROM invoices WHERE id=?', (iid,)), '2026-09-15')
        self.issue(iid, derogate=(13,))
        frozen_pdf = self.c.get(f'/invoice/{iid}.pdf').data
        self.flashes(); self.c.post(f'/invoice/{iid}/edit', data=dict(form, invoice_date='2026-09-20'))
        self.assertIn('Seul un brouillon peut être modifié', ' '.join(self.flashes()))
        self.assertEqual(self.scalar('SELECT invoice_date FROM invoices WHERE id=?', (iid,)), '2026-09-15')
        c = sqlite3.connect(self.db)
        with self.assertRaises(sqlite3.IntegrityError): c.execute("UPDATE invoices SET invoice_date='2026-09-20' WHERE id=?", (iid,))
        c.close()
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').data, frozen_pdf)

    def test_invalid_dates_refused(self):
        _, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-08-31')
        self.assertIn('ne peut pas précéder le début de la période', ' '.join(fl))
        _, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 1, invoice_date='31.09.2026')
        self.assertIn('date de facture invalide', ' '.join(fl))
        future = (TODAY + timedelta(days=3)).isoformat()
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 1, invoice_date=future)
        self.assertIn('Brouillon créé.', fl)  # a planned date is allowed on a draft …
        page = self.c.get(f'/issue/{iid}').get_data(as_text=True)
        self.assertIn('postérieure au jour d', html.unescape(page)); self.assertIn('disabled', page)
        self.issue(iid)                         # … but the invoice cannot be issued before that day
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        self.assertIn('postérieure au jour d', ' '.join(self.flashes()))

    def test_changed_date_after_confirmation_page_refused(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 1)
        self.c.post(f'/issue/{iid}', data={'reliquat_treatment': 'reporte', 'expected_invoice_date': '2026-09-01', 'from_confirm': '1'})
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        self.assertIn('la date de facture a changé', ' '.join(self.flashes()))


class RefundDeadlineDisplay(Settlement):
    def test_deadline_or_its_absence_is_shown(self):
        none = self.issued_cn(qty='0.25', treatment='remboursement')
        with_delay = self.issued_cn(qty='0.25', treatment='remboursement', refund_delay_days='15')
        draft, _ = self.credit(qty='0.25', treatment='remboursement', refund_delay_days='20')
        archive = html.unescape(self.c.get('/?tab=archive').get_data(as_text=True))
        due = (TODAY + timedelta(days=15)).isoformat()
        self.assertIn('Remboursement — sans échéance', archive.replace('remboursement — sans', 'Remboursement — sans'))
        self.assertIn(f'échéance {rules.fr_date(due)}', archive)  # rc7 (A3); self.assertIn('délai 20 j après émission', archive)
        self.assertIn('aucune (aucun délai fixé)', html.unescape(self.c.get(f'/credit/{none}').get_data(as_text=True)))
        self.assertIn('20 jour(s) après émission', html.unescape(self.c.get(f'/credit/{draft}').get_data(as_text=True)))
        self.assertIn('sous 20 jour(s) après émission', pdf_text(self.c.get(f'/credit/{draft}.pdf').data))


class ScreenFormat(Rc4):
    def test_french_numbers_on_screen(self):
        pid = self.load_reference()
        iid = self.issued(pid, '2025-11-01', '2026-09-30', 8, derogate=(12,))   # rc41: 8 j for 8.15 j worked, check 12 overridden
        pages = ''.join(self.c.get(f'/?tab={t}').get_data(as_text=True) for t in ('dashboard', 'mandates', 'archive'))
        self.assertIn('5 200,00\xa0CHF', pages); self.assertIn('8,15', pages)
        self.assertNotRegex(pages, r'CHF \d'); self.assertNotIn('5200.00', pages); self.assertNotRegex(pages, r'>\d+\.\d+<')
        self.assertIn('8 ', m.fr_chf(8000)); self.assertEqual(m.fr_num(-0.004), '0,00'); self.assertEqual(m.fr_g(0.125), '0,125')
        self.assertEqual(m.fr_g(12), '12'); self.assertEqual(m.fr_num(1234567.891), '1 234 567,89'); self.assertEqual(m.fr_g(-2.5), '−2,5')

    def test_login_title(self):
        self.c.post('/logout')
        page = self.c.get('/login').get_data(as_text=True)
        self.assertIn('Time Billing V9.2', page); self.assertNotIn('V5', page)
        self.assertNotIn(m.VERSION, page)   # B-7 (2026-10-20): the exact version left the public login page; it stays on /health


class NonRegression(Rc4):
    """rc4 changes presentation only: every figure printed by the rc3 layout is printed identically by rc4."""
    FIG = re.compile(r'(?<![\w/])-?\d[\d ]*,\d{2}(?: CHF|%)?|- CHF')

    def figures(self, text):
        return Counter(x for x in self.FIG.findall(text))

    def compare(self, rc3_bytes, rc4_bytes):
        old, new = self.figures(pdf_text(rc3_bytes)), self.figures(pdf_text(rc4_bytes))
        self.assertTrue(old)
        self.assertEqual(old - new, Counter(), 'figures printed by rc3 missing or changed in rc4')
        return old, new

    def test_invoice_figures_unchanged(self):
        pid = self.load_reference()
        for kw in ({}, {'other_amount': '120', 'other_label': 'Frais', 'other_vat_mode': 'soumis'}):
            self.c.post(f'/project/{pid}/edit', data={'name': 'Mandat Test PM', 'rate': '650', 'day_hours': '8', 'vat': '8.1', 'client': 'C', 'billing_address': 'A\nB',
                                                       'ordered_days': '12', 'po': 'PO-1', 'project_number': 'NP-1', 'dates_label': 'x'})
            iid, _ = self.draft(pid, '2025-11-01', '2026-09-30', 8.15, **kw)
            c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
            h, rows = invoice_service.live_data(c, iid); c.close()
            old, new = self.compare(_layout_rc3.render_invoice(h, rows, issued=False)[0], pdf_layout.render_invoice(h, rows, issued=False)[0])
            # rc7 (A4): the only new figures are the contract-position block of the summary page (realised 8,15, invoiced 8,15 incl. this draft, balance 12 − 8,15)
            self.assertEqual(new - old, Counter({'8,15': 2, '3,85': 1}), 'no new figure on invoices besides the rc7 position block')
            self.c.post(f'/invoice/{iid}/delete')

    def test_credit_and_cancellation_figures_unchanged(self):
        pid = self.mandate(name='Mandat NR', rate='650', vat='8.1')
        self.entry(pid, '2026-09-10', 16)
        d, _ = self.draft(pid, '2026-09-01', '2026-09-30', 2, other_amount='120', other_label='Frais', other_vat_mode='soumis')
        self.issue(d)
        for form in ({'qty': '0.5'}, {'amount': '100', 'other_amount': '20'}):
            self.flashes(); self.c.post(f'/invoice/{d}/credit', data=dict(form, reason='nr', treatment='remboursement'))
            cid = self.scalar('SELECT MAX(id) FROM credit_notes')
            c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
            h = invoice_service.credit_data(c, cid); c.close()
            old, new = self.compare(_layout_rc3.render_credit_note(h, issued=False)[0], pdf_layout.render_credit_note(h, issued=False)[0])
            # rc4 adds the « AUTRES » amount as its own table line (R10): the only new figure allowed
            extra = new - old
            self.assertTrue(set(extra) <= {f"{pdf_layout.num(h['amounts']['other'])} CHF"}, extra)
