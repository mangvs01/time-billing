"""V9.2-rc11: regression tests for the defects found by the independent functional QA of rc10 (QA-01 … QA-20, QA-S1).
Synthetic data only, on a COPY of the staging database (see test_import.py for the run command).
"""
import io, json, re, sqlite3

import app.app as m
from app import pdf_layout
from tests.test_functional import pdf_text
from tests.test_v92 import V92


class Billing(V92):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def pid(self, **kw):
        return self.mandate(**kw)

    def test_qa01_same_period_cannot_be_issued_twice(self):
        pid = self.pid(name='QA01', ordered='10'); self.entry(pid, '2026-01-12', 8)
        a, _ = self.draft(pid, '2026-01-01', '2026-01-31', 1)
        b, fl = self.draft(pid, '2026-01-01', '2026-01-31', 1)              # a second identical draft is still accepted, with a warning
        self.assertTrue(any('autre(s) brouillon(s)' in f for f in fl), fl)
        self.flashes(); self.issue(a); self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (a,)), 'issued')
        self.flashes(); self.issue(b)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (b,)), 'draft')
        self.assertTrue(any('chevauche' in f for f in self.flashes()))

    def test_qa02_editing_a_draft_keeps_its_rate(self):
        pid = self.pid(name='QA02', rate='1000'); self.entry(pid, '2026-02-10', 8)
        iid, _ = self.draft(pid, '2026-02-01', '2026-02-28', 1)
        self.c.post(f'/project/{pid}/edit', data={'name': 'QA02', 'client': 'C', 'po': 'P', 'rate': '1200', 'ordered_days': '12', 'vat': '0', 'day_hours': '8',
                                                   'start_date': '2025-11-01', 'duration_months': '11'})
        self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-02-01', 'period_to': '2026-02-28', 'qty': '1', 'note': 'seule la note change'})
        self.assertEqual(self.scalar('SELECT unit_rate FROM invoices WHERE id=?', (iid,)), 1000)

    def test_qa04_printed_quantity_matches_the_amount(self):
        pid = self.pid(name='QA04', rate='1234.56', ordered='50'); self.entry(pid, '2026-03-10', 8)
        iid = self.issued(pid, '2026-03-01', '2026-03-31', 4.123457)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn('4,123457', t); self.assertIn('5 090,66', t)             # 4,123457 x 1 234,56 = 5 090,6583…

    def test_qa04_label_helpers(self):
        self.assertEqual(pdf_layout.qty_label(4), '4,00'); self.assertEqual(pdf_layout.qty_label(0.5), '0,50')
        self.assertEqual(pdf_layout.qty_label(4.123457), '4,123457'); self.assertEqual(pdf_layout.qty_label(1234.5), '1 234,50')
        self.assertEqual(pdf_layout.rate_money(650), '650,00 CHF'); self.assertEqual(pdf_layout.rate_money(85.526315789), '85,5263 CHF')

    def test_qa05_ids_of_deleted_objects_are_never_reused(self):
        pid = self.pid(name='QA05'); self.entry(pid, '2026-04-10', 2)
        a, _ = self.draft(pid, '2026-04-01', '2026-04-30', 0.25)
        self.c.post(f'/invoice/{a}/edit', data={'period_from': '2026-04-01', 'period_to': '2026-04-30', 'qty': '0.25', 'invoice_date': '2026-04-29'})   # leaves a date trace
        self.c.post(f'/invoice/{a}/delete')
        b, _ = self.draft(pid, '2026-04-01', '2026-04-30', 0.25)
        self.assertGreater(b, a)
        e1 = self.scalar('SELECT MAX(id) FROM entries'); self.c.post(f'/entry/{e1}/delete', data={'reason': 'test'})
        self.entry(pid, '2026-04-11', 1)
        self.assertGreater(self.scalar('SELECT MAX(id) FROM entries'), e1)

    def test_qa06_description_that_would_be_cut_is_refused(self):
        pid = self.pid(name='QA06'); self.entry(pid, '2026-05-10', 8)
        self.flashes(); self.c.post('/invoice', data={'project_id': pid, 'period_from': '2026-05-01', 'period_to': '2026-05-31', 'qty': '1', 'description': 'mot ' * 120})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM invoices WHERE project_id=?", (pid,)), 0)
        self.assertTrue(any('description trop longue' in f for f in self.flashes()))
        self.c.post('/invoice', data={'project_id': pid, 'period_from': '2026-05-01', 'period_to': '2026-05-31', 'qty': '1', 'description': 'Production PM/DM - Projet - 2600137BE'})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM invoices WHERE project_id=?", (pid,)), 1)

    def test_qa07_08_entry_warnings_are_not_blocking(self):
        pid = self.pid(name='QA07'); self.flashes()
        self.c.post('/entry', data={'work_date': '2026-06-10', 'project_id': pid, 'entry_mode': 'clock', 'start_time': '09:00', 'end_time': '12:00'}); self.flashes()
        self.c.post('/entry', data={'work_date': '2026-06-10', 'project_id': pid, 'entry_mode': 'clock', 'start_time': '10:00', 'end_time': '13:00'})
        fl = self.flashes(); self.assertTrue(any('chevauche' in f for f in fl), fl); self.assertTrue(any('Temps enregistré' in f for f in fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries WHERE project_id=?', (pid,)), 2)
        self.entry(pid, '2030-01-10', 1); self.assertTrue(any('futur' in f for f in self.flashes()))
        self.entry(pid, '1999-01-10', 1); self.assertTrue(any('hors de la période' in f for f in self.flashes()))
        self.draft(pid, '2026-06-01', '2026-06-30', 0.25)
        self.entry(pid, '2026-06-12', 1); self.assertTrue(any('brouillon' in f for f in self.flashes()))

    def test_qa12_zero_rate_and_negative_other_are_refused(self):
        pid = self.pid(name='QA12', rate='0'); self.entry(pid, '2026-07-10', 8)
        iid, _ = self.draft(pid, '2026-07-01', '2026-07-31', 1)
        self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft'); self.assertTrue(any('Tarif journalier' in f for f in self.flashes()))
        pid2 = self.pid(name='QA12b'); self.entry(pid2, '2026-07-10', 8); self.flashes()
        self.c.post('/invoice', data={'project_id': pid2, 'period_from': '2026-07-01', 'period_to': '2026-07-31', 'qty': '1', 'other_amount': '-5000'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices WHERE project_id=?', (pid2,)), 0)

    def test_qa13_15_issue_page_warns_on_po_overrun_and_order(self):
        pid = self.pid(name='QA13', ordered='1'); self.entry(pid, '2026-08-10', 8)
        self.issued(pid, '2026-08-01', '2026-08-31', 1)
        iid, _ = self.draft(pid, '2026-07-01', '2026-07-31', 1)
        page = self.c.get(f'/issue/{iid}').get_data(as_text=True)
        self.assertIn('Dépassement du bon de commande', page); self.assertIn('hors ordre chronologique', page)

    def test_qa17_day_hours_locked_once_invoiced(self):
        pid = self.pid(name='QA17'); self.entry(pid, '2026-09-10', 8); self.issued(pid, '2026-09-01', '2026-09-30', 1)
        self.flashes()
        r = self.c.post(f'/project/{pid}/edit', data={'name': 'QA17', 'client': 'C', 'po': 'P', 'rate': '650', 'ordered_days': '12', 'vat': '0', 'day_hours': '7.5',
                                                       'start_date': '2025-11-01', 'duration_months': '11'})
        self.assertEqual(self.scalar('SELECT day_hours FROM projects WHERE id=?', (pid,)), 8)
        self.assertIn('heures par jour ne peuvent plus changer', r.get_data(as_text=True))

    def test_qa18_messages_and_validation(self):
        self.pid(name='QA18'); self.flashes()
        self.c.post('/project', data={'name': 'QA18', 'rate': '1', 'day_hours': '8', 'vat': '0'})
        fl = self.flashes(); self.assertTrue(any('porte déjà ce nom' in f for f in fl), fl); self.assertFalse(any('UNIQUE' in f for f in fl))
        self.c.post('/project', data={'name': 'QA18b', 'rate': '1', 'day_hours': '8', 'vat': '0', 'duration_months': '0', 'start_date': '2026-01-01'})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM projects WHERE name='QA18b'"), 0)
        self.c.post('/issue/999999', data={}); self.assertTrue(any("n'existe plus" in f for f in self.flashes()))

    def test_qa18_reopen_clears_closed_reason(self):
        pid = self.pid(name='QA18c'); self.c.post(f'/project/{pid}/close', data={'reason': 'terminé'})
        self.assertEqual(self.scalar('SELECT closed_reason FROM projects WHERE id=?', (pid,)), 'terminé')
        self.c.post(f'/project/{pid}/reopen'); self.assertEqual(self.scalar('SELECT closed_reason FROM projects WHERE id=?', (pid,)), '')


class Credits(V92):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    DEROGATE = (13,)   # rc25: periods past the real date of the day (check 13), explicitly
    def issued_invoice(self):
        pid = self.mandate(name='QA19', rate='1000', ordered='20'); self.entry(pid, '2026-10-02', 40)
        return self.issued(pid, '2026-10-01', '2026-10-31', 5)

    def test_qa19_credit_rate_must_match_and_label_follows_unit(self):
        iid = self.issued_invoice(); self.flashes()
        r = self.c.post(f'/invoice/{iid}/credit', data={'scope': 'partial', 'qty': '1', 'unit_rate': '2000', 'reason': 'x', 'treatment': 'remboursement'})
        self.assertIn('tarif de la note de crédit', r.get_data(as_text=True).replace('&#39;', "'"))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes WHERE invoice_id=?', (iid,)), 0)
        self.c.post(f'/invoice/{iid}/credit', data={'scope': 'partial', 'qty': '1', 'unit_rate': '1000', 'reason': 'x', 'treatment': 'remboursement'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes WHERE invoice_id=?', (iid,)), 1)

    def test_qa19_refund_cannot_precede_the_credit_note(self):
        iid = self.issued_invoice()
        self.c.post(f'/invoice/{iid}/credit', data={'scope': 'partial', 'qty': '1', 'reason': 'x', 'treatment': 'remboursement'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue'); self.flashes()
        self.c.post(f'/credit/{cid}/refund', data={'amount': '10', 'executed_on': '2020-01-01'})
        self.assertTrue(any('précéder' in f for f in self.flashes()))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_operations WHERE credit_note_id=?', (cid,)), 0)


class Restore(V92):
    def dump(self): return self.c.get('/backup').data

    def test_qa03_large_backup_is_accepted(self):
        pid = self.mandate(name='QA03'); self.entry(pid, '2026-01-10', 8); self.issued(pid, '2026-01-01', '2026-01-31', 1)
        obj = json.loads(self.dump()); obj['meta']['padding'] = 'x' * (17 * 1024 * 1024)       # > 15 MB, like a backup of ~100 invoices
        r = self.c.post('/restore', data={'backup': (io.BytesIO(json.dumps(obj).encode()), 'grosse.json')}, content_type='multipart/form-data')
        self.assertNotEqual(r.status_code, 413); self.assertIn('/restore/', r.headers.get('Location', ''))

    def test_qa11_backup_has_no_session_and_restore_keeps_the_login(self):
        pid = self.mandate(name='QA11'); self.entry(pid, '2026-01-10', 1)
        raw = self.dump(); obj = json.loads(raw)
        self.assertNotIn('web_sessions', obj['tables']); self.assertNotIn('login_failures', obj['tables'])
        r = self.c.post('/restore', data={'backup': (io.BytesIO(raw), 'b.json')}, content_type='multipart/form-data')
        token = r.headers['Location'].rsplit('/', 1)[-1]
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        self.assertEqual(self.c.get('/').status_code, 200)                    # still signed in
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM web_sessions'), 1)

    def test_qa_s1_restore_cannot_add_entries_to_a_frozen_annex(self):
        pid = self.mandate(name='QAS1'); self.entry(pid, '2026-01-10', 8); self.entry(pid, '2026-01-20', 8); self.issued(pid, '2026-01-01', '2026-01-31', 2)
        self.entry(pid, '2026-01-25', 1)                                       # later entry, not in the annex
        obj = json.loads(self.dump()); late = self.scalar('SELECT MAX(id) FROM entries')
        obj['tables']['invoice_annex_entries'].append({'invoice_id': obj['tables']['invoices'][0]['id'], 'entry_id': late})
        r = self.c.post('/restore', data={'backup': (io.BytesIO(json.dumps(obj).encode()), 'f.json')}, content_type='multipart/form-data')
        token = r.headers['Location'].rsplit('/', 1)[-1]
        page = self.c.get(f'/restore/{token}').get_data(as_text=True)
        self.assertIn('ne correspondent pas à son annexe figée', page)
