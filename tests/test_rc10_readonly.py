"""V9.2-rc10: consulting, recomputing or re-rendering never rewrites history.

Synthetic data only, on a COPY of the staging database (see test_import.py for the run command).

Rules under test
R1  every read-only page, export and PDF leaves the whole database byte-for-byte identical (login/session tables excluded)
R2  frozen documents (PDF, annex, archive) stay identical when time passes, when the calendar day changes and when the mandate is edited afterwards
R3  the suggestion endpoint (recalculation of days/amounts) writes nothing
R4  the same holds with imported rows, issued invoices, refunds, offsets and cancellations in the database
"""
import hashlib, io, re, sqlite3
from datetime import date, datetime, time

import app.app as m
from app import billing_rules as rules
from tests.test_import import workbook
from tests.test_v92 import V92
from tests.test_functional import pdf_text

EXCLUDED = {'web_sessions', 'login_failures', 'audit', 'auth_credentials'}  # authentication state; the audit log is append-only (exports are traced), checked apart


def audit_rows(db):
    c = sqlite3.connect(db)
    try: return [tuple(r) for r in c.execute('SELECT * FROM audit ORDER BY rowid')]
    finally: c.close()


def dump(db):
    """Canonical content of every table (rows sorted), hashed per table."""
    c = sqlite3.connect(db); out = {}
    try:
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            if t in EXCLUDED: continue
            rows = sorted(repr(r) for r in c.execute(f'SELECT * FROM "{t}"'))
            out[t] = hashlib.sha256('\n'.join(rows).encode()).hexdigest() + f':{len(rows)}'
    finally: c.close()
    return out


class ReadOnly(V92):
    def build_world(self):
        pid = self.mandate(name='Mandat Lecture', rate='650', vat='8.1', ordered='20')
        self.entry(pid, '2026-08-10', 16, 'août A'); self.entry(pid, '2026-09-10', 12, 'sept A')
        self.c.post('/entry', data={'work_date': '2026-09-11', 'project_id': pid, 'entry_mode': 'clock', 'start_time': '09:00', 'end_time': '11:45'})
        self.pid = pid
        self.f1 = self.issued(pid, '2026-08-01', '2026-08-31', 2)
        self.f2 = self.issued(pid, '2026-09-01', '2026-09-30', 1.75, derogate=(12,))   # rc41: 1.75 j for 1.84375 j worked: gap of check 12, written reason
        # refund note, then an offset note applied on a later invoice, then a cancelled note
        self.flashes(); self.c.post(f'/invoice/{self.f1}/credit', data={'reason': 'r1', 'mode': 'amounts', 'treatment': 'remboursement', 'qty': '0.5', 'unit_rate': '650'})
        self.nc_refund = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{self.nc_refund}/issue')
        self.c.post(f'/credit/{self.nc_refund}/refund', data={'amount': '100', 'executed_on': rules.local_today().isoformat()})
        self.flashes(); self.c.post(f'/invoice/{self.f1}/credit', data={'reason': 'r2', 'qty': '0.25', 'unit_rate': '650', 'treatment': 'compensation'})
        self.nc_off = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{self.nc_off}/issue')
        self.entry(pid, '2026-10-02', 8, 'oct A')
        self.f3, _ = self.draft(pid, '2026-10-01', '2026-10-31', 1)
        self.c.post(f'/credit/{self.nc_off}/offset', data={'target_invoice_id': str(self.f3), 'amount': '100'})
        self.flashes(); self.c.post(f'/invoice/{self.f2}/credit', data={'reason': 'r3', 'qty': '0.25', 'unit_rate': '650', 'treatment': 'remboursement'})
        self.nc_cancel = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{self.nc_cancel}/issue')
        self.c.post(f'/credit/{self.nc_cancel}/cancel', data={'reason': 'erreur'})
        # imported batch (synthetic workbook)
        d = workbook({'SEPT': [(datetime(2026, 9, 15), 'importé', 'Alpha', None, None, 2)]})
        t = self.upload(d); form = self.save(t, {'Alpha': self.p1}); self.commit(t, form)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM import_batches WHERE status='COMMITTED'"), 1)

    def urls(self):
        u = ['/', '/?tab=time', '/?tab=mandates', '/?tab=billing', '/?tab=archive', '/?tab=migration', '/?tab=settings', '/entries', '/entries?q=a&page=1',
             '/entries.csv', '/archive.zip', f'/project/{self.pid}/edit', f'/invoice/{self.f3}/edit', f'/issue/{self.f3}', f'/issue/{self.f1}',
             f'/invoice/{self.f1}/credit', f'/invoice/{self.f2}/credit', f'/entry/{self.scalar("SELECT MIN(id) FROM entries")}/edit']
        for i in (self.f1, self.f2, self.f3): u.append(f'/invoice/{i}.pdf')
        for n in (self.nc_refund, self.nc_off, self.nc_cancel): u += [f'/credit/{n}', f'/credit/{n}.pdf']
        u += [f'/invoice/{self.f1}/ecart', f'/invoice/{self.f2}/ecart']    # rc19: post-invoicing variance pages are read-only too
        u.append(f'/credit/{self.nc_cancel}/cancellation.pdf')
        return u

    def get_all(self):
        bad = []
        for u in self.urls():
            r = self.c.get(u, follow_redirects=False)
            if r.status_code >= 500: bad.append((u, r.status_code))
        self.assertEqual(bad, [])

    def test_r1_r4_consultation_changes_nothing(self):
        self.build_world()
        before = dump(self.db); a0 = audit_rows(self.db)
        for u in self.urls():
            self.c.get(u); now = dump(self.db)
            self.assertEqual(audit_rows(self.db)[:len(a0)], a0, f'{u} a réécrit le journal')
            self.assertEqual({k: v for k, v in now.items() if v != before.get(k)}, {}, f'{u} a modifié la base')
        self.get_all()
        for p in (self.pid,):
            for mode in ('exact', 'down', 'up', 'nearest'):
                self.suggest(p, '2026-08-01', '2026-10-31', mode, '0.25')
        self.assertEqual(dump(self.db), before)

    def test_r2_frozen_documents_survive_time_and_mandate_edits(self):
        self.build_world()
        pdfs = {u: self.c.get(u).data for u in [f'/invoice/{i}.pdf' for i in (self.f1, self.f2)] +
                [f'/credit/{n}.pdf' for n in (self.nc_refund, self.nc_off)] + [f'/credit/{self.nc_cancel}/cancellation.pdf']}
        zip_before = self.c.get('/archive.zip').data
        # the calendar moves on a year, and the mandate is edited (rate, name, address, ordered days)
        real = rules.local_today
        try:
            rules.local_today = lambda: date(2027, 11, 15); m.rules.local_today = rules.local_today
            self.c.post(f'/project/{self.pid}/edit', data={'name': 'Mandat Lecture RENOMMÉ', 'client': 'Autre Client', 'po': 'PO-NEW', 'rate': '999', 'ordered_days': '50',
                                                            'vat': '7.7', 'day_hours': '7', 'billing_address': 'Nouvelle adresse\n1000 Ailleurs'})
            for u, data in pdfs.items(): self.assertEqual(self.c.get(u).data, data, u)
            self.get_all()
            for u, data in pdfs.items(): self.assertEqual(self.c.get(u).data, data, u)
        finally:
            rules.local_today = real; m.rules.local_today = real
        # archive = same documents (the index may show current mandate names, the PDFs and sums must not move)
        import zipfile
        za = zipfile.ZipFile(io.BytesIO(zip_before)); zb = zipfile.ZipFile(io.BytesIO(self.c.get('/archive.zip').data))
        pa = {n: za.read(n) for n in za.namelist() if n.lower().endswith('.pdf')}; pb = {n: zb.read(n) for n in zb.namelist() if n.lower().endswith('.pdf')}
        self.assertEqual(pa, pb)
        self.assertTrue(pa)

    def test_issued_rows_never_change_by_recalculation_of_hours(self):
        """rc19: a billed entry can be corrected or deleted (reason + confirmation), but the frozen annex, the issued invoices and their PDF
        never move; the change only shows as a post-invoicing variance."""
        self.build_world()
        snap = [tuple(r) for r in self.sql('SELECT * FROM invoice_annex_entries ORDER BY rowid')]
        inv = [tuple(r) for r in self.sql("SELECT * FROM invoices WHERE status='issued' ORDER BY id")]
        frozen = [tuple(r) for r in self.sql('SELECT * FROM invoice_snapshots ORDER BY invoice_id')]
        pdf = self.c.get(f'/invoice/{self.f1}.pdf').data
        eid = self.scalar("SELECT id FROM entries WHERE description='août A'")
        self.flashes(); self.c.post(f'/entry/{eid}/delete', data={}); self.assertIn('motif', ' '.join(self.flashes()))   # no reason: refused
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries WHERE id=?', (eid,)), 1)
        self.c.post(f'/entry/{eid}/delete', data={'reason': 'doublon', 'confirm_billed': '1'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries WHERE id=?', (eid,)), 0)
        self.assertEqual([tuple(r) for r in self.sql('SELECT * FROM invoice_annex_entries ORDER BY rowid')], snap)
        self.assertEqual([tuple(r) for r in self.sql("SELECT * FROM invoices WHERE status='issued' ORDER BY id")], inv)
        self.assertEqual([tuple(r) for r in self.sql('SELECT * FROM invoice_snapshots ORDER BY invoice_id')], frozen)
        self.assertEqual(self.c.get(f'/invoice/{self.f1}.pdf').data, pdf)
        self.assertIn('−16,00 h', self.c.get(f'/invoice/{self.f1}/ecart').get_data(as_text=True))
