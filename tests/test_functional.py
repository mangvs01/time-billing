"""Functional review: mandate → time → invoice → issue → frozen PDF → cumulative annex.

Synthetic data only, on a COPY of the staging database (see test_import.py for the run command).
The reference scenario mirrors the shape of the real invoice 2026-09 (12-day PO, 650 CHF/day,
65.2 h recorded = 8.15 days, 8.00 days invoiced) with fictitious names.
"""
import base64, hashlib, json, os, re, sqlite3, zlib
from datetime import date

from app.billing_rules import local_today, local_date  # RC8: business day in Europe/Zurich
import app.app as m
from tests.test_import import Base, FAKE_ISSUER


from app.billing_rules import local_today as _local_today
YEAR = _local_today().year      # rc37: invoice numbers are AAAA-N (year of the invoice date = today's year, then the sequence of the year)


def _pdf_objects(data):
    objs = {}
    for m in re.finditer(rb'(\d+) 0 obj(.*?)endobj', data, re.S): objs[int(m.group(1))] = m.group(2)
    return objs


def _stream(body):
    m = re.search(rb'stream\r?\n(.*?)\r?\n?endstream', body, re.S)
    if not m: return b''
    raw = m.group(1)
    for decode in (lambda b: zlib.decompress(base64.a85decode(b.strip(), adobe=True)), zlib.decompress):
        try: return decode(raw)
        except Exception: continue
    return raw


def _unescape(t):
    return re.sub(rb'\\([0-7]{1,3}|.)', lambda m: bytes([int(m.group(1), 8)]) if m.group(1)[:1].isdigit() else
                  {b'n': b'\n', b'r': b'\r', b't': b'\t', b'b': b'\b', b'f': b'\f'}.get(m.group(1), m.group(1)), t, flags=re.S)


def _font_maps(objs):
    """Resource name (/F1, /F2+0 …) → byte → text, from each embedded font's ToUnicode CMap (TrueType subsets)."""
    maps = {}
    for body in objs.values():
        for name, ref in re.findall(rb'/([A-Za-z0-9_.+-]+)\s+(\d+) 0 R', body):
            font = objs.get(int(ref), b'')
            if b'/Type /Font' not in font and b'/Type/Font' not in font: continue
            tu = re.search(rb'/ToUnicode\s+(\d+) 0 R', font)
            if not tu: maps.setdefault(name, None); continue
            cmap = {}; cm = _stream(objs[int(tu.group(1))])
            for block in re.findall(rb'beginbfchar(.*?)endbfchar', cm, re.S):
                for src, dst in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', block):
                    cmap[int(src, 16)] = bytes.fromhex(dst.decode()).decode('utf-16-be')
            for block in re.findall(rb'beginbfrange(.*?)endbfrange', cm, re.S):
                for a, b, dst in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', block):
                    base = int(dst, 16)
                    for k in range(int(a, 16), int(b, 16) + 1): cmap[k] = chr(base + k - int(a, 16))
            maps[name] = cmap
    return maps


def pdf_text(data):
    """Text-show operands of reportlab content streams, one per line, in drawing order. Standard fonts are
    decoded as cp1252; embedded TrueType subsets (rc4 typography) through their ToUnicode CMap."""
    objs = _pdf_objects(data); maps = _font_maps(objs); out = []
    for body in objs.values():
        if b'/Length' not in body or b'stream' not in body: continue
        s = _stream(body)
        if b' Tf' not in s: continue
        font = None
        for tok in re.finditer(rb'/([A-Za-z0-9_.+-]+)\s+[\d.]+\s+Tf|\((.*?)(?<!\\)\)\s*Tj', s, re.S):
            if tok.group(1) is not None: font = tok.group(1); continue
            raw = _unescape(tok.group(2)); cmap = maps.get(font)
            out.append(''.join(cmap.get(b, '\ufffd') for b in raw) if cmap else raw.decode('cp1252', 'replace'))
    return '\n'.join(out)


# 65.2 h over 11 months, quarter-hour granularity like the reference annex (fictitious descriptions)
REF_HOURS = {'2025-11-28': [1.0], '2025-12-01': [0.25, 0.25, 0.25, 0.25], '2026-01-07': [0.5, 0.25, 0.5, 0.5, 0.5, 0.25, 0.25],
             '2026-02-19': [0.5], '2026-03-27': [0.25], '2026-04-09': [0.5, 0.25, 0.75, 0.25, 0.25, 0.5, 0.25],
             '2026-05-07': [0.25, 0.5, 1.25, 0.25, 0.25, 0.75, 0.25, 0.25, 0.5], '2026-06-04': [11.45], '2026-07-02': [7.0],
             '2026-08-20': [23.75], '2026-09-22': [10.5]}


# D8 (2026-10-06) + rc25: checks 12, 13 and 14 may be overridden at issuance, each by a written reason GIVEN FOR THAT CHECK. rc25 (decision 6): the helper below
# gives NO reason by default any more; a test that needs an exception names the checks it overrides (derogate=(12, 13), ...), so a fixture that
# over-bills or bills ahead of the work is visible in the test itself and no check is silently bypassed.
def derogations(*numbers):
    return {f'derogation_{n}': f'jeu de données de test : exception voulue du contrôle {n}' for n in numbers}


class Cycle(Base):
    DEROGATE = ()     # classes whose fixtures bill without matching recorded work name here the checks they override (never a global default)

    def issue(self, iid, treatment='reporte', confirm_backdate=True, derogate=None):
        """rc7 (A6): a draft dated before today needs the explicit confirmation the user ticks on the issue page;
        the helper ticks it unless confirm_backdate=False (tests of the refusal). derogate: the numbers of the checks (12, 13, 14) a written reason is
        given for, none by default (a reason for one check never covers another); None = the class's DEROGATE (empty unless the class opts in)."""
        data = dict({'reliquat_treatment': treatment}, **derogations(*(self.DEROGATE if derogate is None else derogate)))
        d = self.scalar('SELECT invoice_date FROM invoices WHERE id=?', (iid,))
        if confirm_backdate and d and d < local_today().isoformat(): data['confirm_backdate'] = d
        return self.c.post(f'/issue/{iid}', data=data)

    def mandate(self, name='Mandat Test PM', rate='650', ordered='12', vat='0', start='2025-11-01', months='11', legal_id='CHE-000.000.001'):
        self.c.post('/project', data={'name': name, 'client': 'Client Fictif SA', 'po': 'PO-TEST-001', 'rate': rate, 'day_hours': '8', 'project_number': 'NP-TEST',
                                      'client_legal_name': 'Client Fictif SA', 'client_legal_id': legal_id,
                                      'billing_address': 'Client Fictif SA\nRue Imaginaire 1\n9999 Nulle-Part', 'dates_label': '01-05 Sept 2026',
                                      'vat': vat, 'ordered_days': ordered, 'start_date': start, 'duration_months': months})
        return self.scalar('SELECT id FROM projects WHERE name=?', (name,))

    def entry(self, pid, d, hours, desc='prestation fictive'):
        return self.c.post('/entry', data={'work_date': d, 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': str(hours), 'description': desc})

    def suggest(self, pid, f, t, mode='exact', step='0.25'):
        r = self.c.post('/suggest', data={'project_id': pid, 'period_from': f, 'period_to': t, 'rounding': mode, 'rounding_step': step})
        return r.status_code, (r.get_json() if r.is_json else None)

    def draft(self, pid, f, t, qty, **kw):
        if self.RECORD_WORK: self.record_work(pid, f, t, qty, kw.get('unit', 'day'))
        self.flashes()
        self.c.post('/invoice', data=dict({'project_id': pid, 'period_from': f, 'period_to': t, 'qty': str(qty)}, **kw))
        return self.scalar('SELECT MAX(id) FROM invoices'), self.flashes()

    def load_reference(self):
        pid = self.mandate()
        for d, hs in REF_HOURS.items():
            for h in hs: self.entry(pid, d, h)
        return pid


class ReferenceCycle(Cycle):
    def test_reference_quantities_and_amounts(self):
        pid = self.load_reference()
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 34)
        self.assertAlmostEqual(self.scalar('SELECT SUM(hours) FROM entries'), 65.2, places=9)
        st, s = self.suggest(pid, '2025-11-01', '2026-09-30', 'down', '0.25')
        self.assertEqual(st, 200)
        self.assertEqual((s['hours'], s['raw_days'], s['suggested_qty'], s['suggested_amount']), (65.2, 8.15, 8.0, 5200.0))
        iid, fl = self.draft(pid, '2025-11-01', '2026-09-30', s['suggested_qty'], rounding='down', rounding_step='0.25')
        self.assertIn('Brouillon créé.', fl)
        self.issue(iid, derogate=(12,))   # rc41: the reference bills 8 j (rounded down) for 8.15 j worked: a gap of check 12 now, overridden with a written reason
        inv = self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]
        self.assertEqual((inv['status'], inv['qty'], inv['unit_rate'], inv['vat']), ('issued', 8.0, 650.0, 0.0))
        self.assertEqual(inv['number'], f'{YEAR}-1')  # rc37: year then the sequence of the year (was: year-month of the period end)
        text = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        for needle in ('FACTURE', 'N° Facture :', f'{YEAR}-1', 'PO-TEST-001', 'SOUS-TOTAL', '5 200,00 CHF', 'TAUX TVA', '0,00%', 'AUTRES', 'TOTAL', '8,00', '650,00 CHF'):
            self.assertIn(needle, text)
        self.assertEqual(len(re.findall(r'^\d{2}/\d{2}/\d{4}$', text, re.M)), 34)  # cumulative annex: every entry
        for month in ('nov-25', 'déc-25', 'janv-26', 'févr-26', 'mars-26', 'avr-26', 'mai-26', 'juin-26', 'juil-26', 'août-26', 'sept-26'):
            self.assertIn(month, text)
        self.assertIn('8,15', text); self.assertIn('NB J PO', text)  # summary page: 8.15 days consumed, 12 ordered

    def test_issued_pdf_shows_invoice_date_and_vat_amount(self):
        pid = self.mandate(name='Mandat TVA', rate='1000', vat='8.1')
        self.entry(pid, '2026-09-10', 16)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 2)
        self.issue(iid)
        text = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn('2 000,00 CHF', text); self.assertIn('8,10%', text); self.assertIn('162,00 CHF', text); self.assertIn('2 162,00 CHF', text)
        self.assertIn(local_today().strftime('%d.%m.%Y'), text)

    def test_vat_rounding_to_cent(self):
        pid = self.mandate(name='Mandat TVA cents', rate='333.33', vat='8.1')
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1.25)
        text = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        # 1.25 × 333.33 = 416.6625 → 416.66 ; VAT 8.1 % of 416.66 = 33.749 → 33.75 ; total 450.41
        self.assertIn('416,66 CHF', text); self.assertIn('33,75 CHF', text); self.assertIn('450,41 CHF', text)


class Rounding(Cycle):
    def test_rounding_matrix(self):
        pid = self.mandate(name='Mandat arrondis', rate='1000')
        for _ in range(8): self.entry(pid, '2026-09-01', 8.15)   # 65.2 h = 8.15 days (max 24 h per entry)
        self.entry(pid, '2026-09-02', 0.8)    # → 8.25 days on the 2-day window
        cases = {('exact', '0.25'): 8.15, ('nearest', '0.25'): 8.25, ('up', '0.25'): 8.25, ('down', '0.25'): 8.0,
                 ('nearest', '0.5'): 8.0, ('up', '0.5'): 8.5, ('down', '1'): 8.0, ('up', '1'): 9.0}
        for (mode, step), want in cases.items():
            self.assertEqual(self.suggest(pid, '2026-09-01', '2026-09-01', mode, step)[1]['suggested_qty'], want, (mode, step))
        self.assertEqual(self.suggest(pid, '2026-09-01', '2026-09-02', 'nearest', '0.25')[1]['suggested_qty'], 8.25)
        # 7 × 8.15 + 7.95 = 65.0 h = 8.125 days exactly; float summation must not turn half-up into down
        c = sqlite3.connect(self.db); c.execute("UPDATE entries SET hours=7.95 WHERE id=(SELECT MIN(id) FROM entries)"); c.commit(); c.close()
        self.assertEqual(self.suggest(pid, '2026-09-01', '2026-09-01', 'exact')[1]['raw_days'], 8.125)
        self.assertEqual(self.suggest(pid, '2026-09-01', '2026-09-01', 'nearest', '0.25')[1]['suggested_qty'], 8.25)

    def test_float_sum_does_not_flip_half_up(self):
        # 79 + 131 + 19 + 11 min = 240 min = 0.5 day exactly; the float sum gives 0.49999999999999994
        pid = self.mandate(name='Mandat minutes', rate='1000')
        for a, b in (('09:00', '10:19'), ('10:30', '12:41'), ('13:00', '13:19'), ('14:00', '14:11')):
            self.c.post('/entry', data={'work_date': '2026-09-03', 'project_id': pid, 'entry_mode': 'clock', 'start_time': a, 'end_time': b})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 4)
        st, s = self.suggest(pid, '2026-09-03', '2026-09-03', 'nearest', '1')
        self.assertEqual((s['raw_days'], s['suggested_qty']), (0.5, 1.0))

    def test_invalid_rounding_inputs_refused(self):
        pid = self.mandate(name='Mandat arrondis 2')
        _, fl = self.draft(pid, '2026-09-01', '2026-09-30', 1, rounding='sideways')
        self.assertFalse(any('Brouillon créé' in f for f in fl))
        _, fl = self.draft(pid, '2026-09-01', '2026-09-30', 1, rounding_step='0')
        self.assertFalse(any('Brouillon créé' in f for f in fl))


class ContractBalance(Cycle):
    def test_po_balance_and_carry_over_after_partial_billing(self):
        pid = self.load_reference()
        iid, _ = self.draft(pid, '2025-11-01', '2026-09-30', 8.0, rounding='down')
        self.issue(iid, derogate=(12,))   # rc41: 8 j billed for 8.15 j worked (reliquat 0.15): check 12 overridden with a written reason
        self.entry(pid, '2026-10-05', 4)  # 0.5 day in the next period
        st, s = self.suggest(pid, '2026-10-01', '2026-10-31', 'exact')
        self.assertEqual(s['raw_days'], 0.5)                       # period only
        self.assertEqual(s['billed_days_before'], 8.0)
        self.assertEqual(s['unbilled_days_to_date'], 0.65)         # 8.65 consumed − 8.00 billed: the 0.15 carry-over is visible
        self.assertEqual(s['po_balance_days'], 4.0)                # 12 ordered − 8 billed
        html = self.c.get('/?tab=mandates').get_data(as_text=True)
        row = re.search(r'<td>Mandat Test PM<br>.*?</tr>', html.split('Détail des mandats', 1)[1], re.S).group(0)
        for v in ('12,00', '8,00', '4,00', '0,65'): self.assertIn(f'<td>{v}</td>', row)   # ordered, billed, PO balance, unbilled

    def test_draft_beyond_po_balance_warns(self):
        pid = self.mandate(name='Mandat petit PO', ordered='2')
        _, fl = self.draft(pid, '2026-09-01', '2026-09-30', 3)
        self.assertIn('Brouillon créé.', fl)
        self.assertTrue(any('dépassent le solde' in f for f in fl), fl)


class Validation(Cycle):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def test_entry_requires_valid_date_and_project(self):
        pid = self.mandate(name='Mandat validation')
        for d in ('', '2026-02-30', 'hier'):
            self.flashes(); self.entry(pid, d, 1)
            self.assertTrue(any('Saisie refusée' in f for f in self.flashes()), d)
        self.c.post('/entry', data={'work_date': '2026-09-01', 'project_id': 999, 'entry_mode': 'duration', 'manual_hours': '1'})
        self.entry(pid, '2026-09-01', 25)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 0)

    def test_invoice_period_must_be_valid(self):
        pid = self.mandate(name='Mandat période')
        for f, t in (('2026-09-30', '2026-09-01'), ('', '2026-09-30'), ('2026-13-01', '2026-12-31')):
            _, fl = self.draft(pid, f, t, 1)
            self.assertFalse(any('Brouillon créé' in x for x in fl), (f, t))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'), 0)

    def test_overlapping_issued_period_refused(self):
        pid = self.mandate(name='Mandat chevauchement')
        iid, _ = self.draft(pid, '2026-08-01', '2026-08-31', 1); self.issue(iid)
        _, fl = self.draft(pid, '2026-08-15', '2026-09-15', 1)
        self.assertTrue(any('chevauche' in f for f in fl), fl)
        _, fl = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        self.assertIn('Brouillon créé.', fl)

    def test_entry_in_already_issued_period_warns(self):
        pid = self.mandate(name='Mandat tardif')
        iid, _ = self.draft(pid, '2026-08-01', '2026-08-31', 1); self.issue(iid)
        self.flashes(); self.entry(pid, '2026-08-20', 1)
        fl = self.flashes()
        self.assertTrue(any('Temps enregistré' in f for f in fl))
        self.assertTrue(any('déjà facturée' in f for f in fl), fl)

    def test_suggest_unknown_project(self):
        self.assertEqual(self.suggest(999, '2026-09-01', '2026-09-30')[0], 400)


class ArchiveAndBackup(Cycle):
    def test_archive_lists_all_invoices(self):
        pid = self.mandate(name='Mandat archive')
        for i in range(35):
            self.draft(pid, '2026-09-01', '2026-09-30', 1)
        html = self.c.get('/?tab=archive').get_data(as_text=True)
        self.assertEqual(len(re.findall(r'href="/invoice/\d+\.pdf"', html)), 35)

    def test_json_backup_is_complete_and_verifiable(self):
        pid = self.mandate(name='Mandat sauvegarde', vat='8.1')
        self.entry(pid, '2026-09-10', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1); self.issue(iid)
        r = self.c.get('/backup')
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.headers['Content-Disposition'], r'time-billing-v9-backup-\d{8}T\d{6}Z\.json')
        data = json.loads(r.data)
        tables = {t[0] for t in self.sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")} - {'web_sessions', 'login_failures', 'kept_forms', 'auth_credentials'}  # rc11/rc12 / BMDP1: operational state is not backed up
        self.assertEqual(set(data['tables']), tables)
        for t in tables: self.assertEqual(len(data['tables'][t]), self.scalar(f'SELECT COUNT(*) FROM {t}'), t)
        snap = data['tables']['invoice_snapshots'][0]
        self.assertEqual(hashlib.sha256(base64.b64decode(snap['pdf'])).hexdigest(), snap['pdf_sha256'])
        self.assertIn('generated_at', data['meta'])


class Ergonomics(Cycle):
    def test_navigation_labels(self):
        html = self.c.get('/').get_data(as_text=True)
        tabs = re.findall(r'data-tab="(\w+)"[^>]*>([^<]+)<', html)
        self.assertEqual([t[1] for t in tabs], ['Tableau de bord', 'Saisie des heures', 'Mandats & prévisionnel', 'Édition des factures', 'Factures et brouillons', 'Import historique', 'Paramètres & sauvegardes'])  # B-8 (2026-10-20)

    def test_actions_return_to_their_tab(self):
        pid = self.mandate(name='Mandat onglets')
        cases = [('/project', {'name': 'Autre'}, 'mandates'), ('/entry', {'work_date': '2026-09-01', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '1'}, 'time'),
                 ('/invoice', {'project_id': pid, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1'}, 'billing')]
        for url, data, tab in cases:
            self.assertTrue(self.c.post(url, data=data).headers['Location'].endswith(f'tab={tab}'), url)
        iid = self.scalar('SELECT MAX(id) FROM invoices')
        self.assertTrue(self.issue(iid).headers['Location'].endswith('tab=archive'))
        html = self.c.get('/?tab=billing').get_data(as_text=True)
        self.assertIn("showTab('billing')", html)

    def test_issue_requires_confirmation(self):
        pid = self.mandate(name='Mandat confirmation')
        self.draft(pid, '2026-09-01', '2026-09-30', 1)
        html = self.c.get('/?tab=archive').get_data(as_text=True)
        iid = self.scalar('SELECT MAX(id) FROM invoices')
        self.assertIn(f'href="/issue/{iid}"', html)  # issuing goes through a confirmation page
        page = self.c.get(f'/issue/{iid}').get_data(as_text=True)
        self.assertIn('Émettre définitivement la facture', page); self.assertIn('Numéro de facture', page)

    def test_login_next_is_not_an_open_redirect(self):
        anon = m.APP.test_client()
        r = anon.post('/login?next=https://evil.example/', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
        self.assertEqual(r.headers['Location'], '/')
        r = anon.post('/login?next=//evil.example/', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
        self.assertEqual(r.headers['Location'], '/')
