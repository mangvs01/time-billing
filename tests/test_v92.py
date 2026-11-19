"""V9.2 milestone: reference PDF layout, credit notes, YYYY-MM numbering, reliquat decision,
draft edit/delete, mandate closure, calendar-year forecast, safe JSON restore.
Synthetic data only, on a COPY of the staging database (see test_import.py for the run command).
"""
import base64, hashlib, html, io, json, os, re, sqlite3
from datetime import date

from app.billing_rules import local_today, local_date  # RC8: business day in Europe/Zurich
import app.app as m
from tests.test_functional import Cycle, derogations, pdf_text
from tests.test_import import FAKE_ISSUER


YEAR = local_today().year      # rc37: the first invoice of a test database is « AAAA-1 » (year of the invoice date = today's year), the second « AAAA-2 »…


def ym_add(d, k):
    i = d.year * 12 + d.month - 1 + k
    return f'{i // 12:04d}-{i % 12 + 1:02d}'


class V92(Cycle):
    def issued(self, pid, f, t, qty, treatment='reporte', derogate=None):
        iid, fl = self.draft(pid, f, t, qty)
        self.assertIn('Brouillon créé.', fl)
        self.flashes(); self.issue(iid, treatment, derogate=derogate)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        return iid


class PdfLayout(V92):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def test_page_one_follows_reference_blocks(self):
        pid = self.mandate(name='Mandat PDF', vat='0')
        self.c.post(f'/project/{pid}/edit', data={'name': 'Mandat PDF', 'client': 'CLI', 'po': 'PO-X-1', 'rate': '650', 'ordered_days': '12', 'vat': '0', 'day_hours': '8',
                                                   'project_number': 'NP-1', 'billing_contact': 'Contact Fictif', 'billing_address': 'Entité Fictive\nRue 1\n1000 Ville\nPays',
                                                   'dates_label': 'Dates fictives', 'start_date': '2025-11-01', 'duration_months': '11'})
        self.entry(pid, '2026-09-10', 8)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        for needle in ('FACTURE', 'Date :', 'N° Facture :', 'PO:', 'PO-X-1', 'Adresse de facturation :', 'Contact Fictif', 'Entité Fictive', 'Pays',
                       'DESCRIPTION', 'JOUR', 'COUT JOURNALIER', 'MONTANT', 'SOUS-TOTAL', 'TAUX TVA', 'TVA', 'AUTRES', 'TOTAL', '- CHF',
                       FAKE_ISSUER['issuer_name'], 'Rue de Test 2', 'Paiement à 30 jours sur le compte:', 'Titulaire: ' + FAKE_ISSUER['account_holder'],
                       'IBAN: ' + FAKE_ISSUER['iban'], 'Feuille de temps', 'sept-26', 'Total des heures', 'de travail du mois', 'Numéro de projet', 'NP-1',
                       'Heure début', 'Heure fin', 'Heures de travail', 'NB J PO', 'Dates fictives', 'CLI'):
            self.assertIn(needle, t)
        self.assertNotIn('À COMPLÉTER', t)
        self.assertNotIn('BROUILLON', t)

    def test_clock_times_printed_as_decimal_hours_like_reference(self):
        pid = self.mandate(name='Mandat horaires')
        self.c.post('/entry', data={'work_date': '2026-09-03', 'project_id': pid, 'entry_mode': 'clock', 'start_time': '19:45', 'end_time': '21:30'})
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 0.25)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn('19,75', t); self.assertIn('21,50', t); self.assertIn('1,75', t)

    def test_missing_fields_are_flagged_never_invented(self):
        c = sqlite3.connect(self.db); c.execute('DELETE FROM settings'); c.commit(); c.close()
        pid = self.mandate(name='Mandat incomplet')
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        for label in ('Raison sociale', 'Adresse émetteur', 'Conditions de paiement', 'Titulaire du compte', 'IBAN', 'BIC'):
            self.assertIn(f'[À COMPLÉTER : {label}]', t)
        self.assertIn('BROUILLON', t)
        self.assertNotRegex(t, r'IBAN: \S')  # nothing made up
        self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        self.assertTrue(any('champs à compléter' in f for f in self.flashes()))

    def test_vat_invoice_requires_issuer_vat_number(self):
        c = sqlite3.connect(self.db); c.execute("UPDATE settings SET value='' WHERE key='issuer_vat_number'"); c.commit(); c.close()
        pid = self.mandate(name='Mandat TVA', vat='8.1')
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        self.flashes(); self.issue(iid)
        self.assertTrue(any('N° TVA' in f for f in self.flashes()))
        pid0 = self.mandate(name='Mandat sans TVA', vat='0')
        self.issued(pid0, '2026-09-01', '2026-09-30', 1)  # 0 % VAT: no VAT number needed

    def test_project_billing_address_required(self):
        pid = self.mandate(name='Mandat sans adresse')
        c = sqlite3.connect(self.db); c.execute("UPDATE projects SET billing_address='' WHERE id=?", (pid,)); c.commit(); c.close()
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        self.flashes(); self.issue(iid)
        self.assertTrue(any('Adresse de facturation' in f for f in self.flashes()))

    def test_logo_upload_validated(self):
        r = self.c.post('/settings', data=dict(FAKE_ISSUER, logo=(io.BytesIO(b'not an image'), 'logo.png')), content_type='multipart/form-data')
        self.assertTrue(any('logo illisible' in f for f in self.flashes()))
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
        self.c.post('/settings', data=dict(FAKE_ISSUER, logo=(io.BytesIO(png), 'logo.png')), content_type='multipart/form-data')
        self.assertEqual(self.scalar("SELECT value FROM settings WHERE key='logo_png_b64'"), base64.b64encode(png).decode())
        pid = self.mandate(name='Mandat logo')
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        data = self.c.get(f'/invoice/{iid}.pdf').data
        self.assertIn(b'/Subtype /Image', data); self.assertNotIn('Logo à fournir', pdf_text(data))

    def test_settings_change_does_not_alter_issued_pdf(self):
        pid = self.mandate(name='Mandat figé')
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        before = self.c.get(f'/invoice/{iid}.pdf').data
        self.c.post('/settings', data=dict(FAKE_ISSUER, iban='CH99 9999 9999 9999 9999 9'))
        self.c.post(f'/project/{pid}/edit', data={'name': 'Mandat figé renommé', 'billing_address': 'Autre adresse', 'client': 'X', 'rate': '1', 'ordered_days': '1'})
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').data, before)


class Numbering(V92):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    DEROGATE = (13,)   # rc25: periods past the real date of the day (check 13), explicitly
    def test_year_then_sequence_of_the_year_whatever_the_period_or_the_mandate(self):
        """rc37 (owner decision 26.10.2026): AAAA-N, N follows the invoices of the year (no leading zero), not the month of the period end."""
        Y = local_today().year
        a = self.mandate(name='Mandat A'); b = self.mandate(name='Mandat B')
        i1 = self.issued(a, '2026-09-01', '2026-09-30', 1)
        i2 = self.issued(b, '2026-09-01', '2026-09-30', 1)
        i3 = self.issued(a, '2026-10-01', '2026-10-15', 1)
        i4 = self.issued(b, '2026-10-01', '2026-10-31', 1)
        i5 = self.issued(a, '2026-10-16', '2026-10-31', 1)
        nums = [self.scalar('SELECT number FROM invoices WHERE id=?', (i,)) for i in (i1, i2, i3, i4, i5)]
        self.assertEqual(nums, [f'{Y}-1', f'{Y}-2', f'{Y}-3', f'{Y}-4', f'{Y}-5'])

    def test_number_shown_before_issuing(self):
        pid = self.mandate(name='Mandat aperçu numéro')
        iid, _ = self.draft(pid, '2026-08-01', '2026-08-31', 1)
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (iid,)), f'{local_today().year}-1')          # reserved from the draft
        self.assertIn(f'<b>{local_today().year}-1</b>', self.c.get(f'/issue/{iid}').get_data(as_text=True))

    def test_legacy_numbers_untouched(self):
        Y = local_today().year
        pid = self.mandate(name='Mandat ancien')
        self.entry(pid, '2026-01-10', 8)                  # the work the V9.0 invoice billed (check 14: no invoice beyond the work recorded)
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO invoices(number,project_id,period_from,period_to,qty,unit,unit_rate,status,issued_at) VALUES(?,?,'2026-01-01','2026-01-31',1,'day',650,'issued','2026-02-01T10:00:00')", (f'{Y}-001', pid))
        c.commit(); c.close(); m.init()
        self.assertEqual(self.sql("SELECT frozen_by FROM invoice_snapshots")[0][0], 'migration-v9.2 (rendu V9.0)')
        self.assertIn('FACTURE / BROUILLON', pdf_text(self.c.get('/invoice/1.pdf').data))  # exact V9.0 rendering kept
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=1'), f'{Y}-001')
        iid = self.issued(pid, '2026-02-01', '2026-02-28', 1)
        self.assertEqual(self.scalar('SELECT number FROM invoices WHERE id=?', (iid,)), f'{Y}-2')        # a number of an earlier release counts as taken: its month / sequence is read as the sequence


class Reliquat(V92):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat reliquat', ordered='12')
        for d in ('2026-09-01', '2026-09-02'): self.entry(self.pid, d, 8.6)  # 17.2 h = 2.15 days

    def test_decision_required_and_recorded(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)
        page = self.c.get(f'/issue/{iid}').get_data(as_text=True)
        self.assertIn('<b>0,15 j</b>', page)
        # rc41: no tolerance below the work (2 j invoiced for 2.15 j worked is a gap of check 12): the written reason is given, the reliquat question follows
        self.flashes(); self.c.post(f'/issue/{iid}', data=derogations(12))
        self.assertTrue(any('choisir le traitement du reliquat' in f for f in self.flashes()))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        self.c.post(f'/issue/{iid}', data=dict({'reliquat_treatment': 'autre'}, **derogations(12)))
        self.assertTrue(any('préciser' in f for f in self.flashes()))
        self.c.post(f'/issue/{iid}', data=dict({'reliquat_treatment': 'offert', 'expected_reliquat': '0.15'}, **derogations(12)))
        r = self.sql('SELECT status,reliquat_days,reliquat_treatment FROM invoices WHERE id=?', (iid,))[0]
        self.assertEqual(tuple(r), ('issued', 0.15, 'offert'))
        self.assertIn('Dont 0,15 jour(s) réalisé(s) offert(s), non facturé(s).', pdf_text(self.c.get(f'/invoice/{iid}.pdf').data))

    def test_offered_vs_carried_over_next_position(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2); self.issue(iid, 'offert', derogate=(12,))
        self.entry(self.pid, '2026-10-05', 4)
        s = self.suggest(self.pid, '2026-10-01', '2026-10-31')[1]
        self.assertEqual((s['unbilled_days_to_date'], s['offered_days']), (0.5, 0.15))   # offered reliquat is settled
        pid2 = self.mandate(name='Mandat report', ordered='12')
        for d in ('2026-09-01', '2026-09-02'): self.entry(pid2, d, 8.6)
        iid2, _ = self.draft(pid2, '2026-09-01', '2026-09-30', 2); self.issue(iid2, 'reporte', derogate=(12,))
        self.entry(pid2, '2026-10-05', 4)
        self.assertEqual(self.suggest(pid2, '2026-10-01', '2026-10-31')[1]['unbilled_days_to_date'], 0.65)  # carried over
        self.assertNotIn('offert', pdf_text(self.c.get(f'/invoice/{iid2}.pdf').data))

    def test_negative_reliquat_cannot_be_offered(self):
        # rc25: check 14 (never derogable) refuses any invoice beyond the work recorded, so a negative reliquat is only reachable through days already
        # OFFERED: 2.15 j worked in September, 1 j invoiced, 1.15 j offered; October: 1 j worked, 2 j invoiced (explicit exception of check 12) -> -1 j
        self.RECORD_WORK = False
        a, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 1); self.flashes(); self.issue(a, 'offert', derogate=(12,))
        self.assertEqual(self.scalar('SELECT reliquat_days FROM invoices WHERE id=?', (a,)), 1.15)
        self.entry(self.pid, '2026-10-05', 8)
        iid, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 2)
        self.flashes(); self.issue(iid, 'offert', derogate=(12, 13))
        self.assertTrue(any('ne peut pas être offert' in f for f in self.flashes()))
        self.issue(iid, 'reporte', derogate=(12, 13))
        self.assertEqual(self.scalar('SELECT reliquat_days FROM invoices WHERE id=?', (iid,)), -1.0)

    def test_stale_confirmation_refused(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)
        self.entry(self.pid, '2026-09-03', 2)  # position changes after the page was displayed
        self.flashes(); self.c.post(f'/issue/{iid}', data=dict({'reliquat_treatment': 'offert', 'expected_reliquat': '0.15'}, **derogations(12)))
        self.assertTrue(any('a changé' in f for f in self.flashes()))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')

    def test_no_reliquat_no_question(self):
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2.15)
        self.c.post(f'/issue/{iid}', data={})
        self.assertEqual(tuple(self.sql('SELECT status,reliquat_treatment FROM invoices WHERE id=?', (iid,))[0]), ('issued', 'aucun'))


class CreditNotes(V92):
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat NC', rate='650', vat='8.1', ordered='12')
        self.entry(self.pid, '2026-09-10', 16)
        self.iid = self.issued(self.pid, '2026-09-01', '2026-09-30', 2)  # 1300 HT, 105.30 VAT
        self.inv_pdf = self.c.get(f'/invoice/{self.iid}.pdf').data
        self.inv_row = tuple(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0])

    def credit(self, **form):
        # success redirects (message in session); refusal re-renders the form (message in the page)
        form.setdefault('treatment', 'remboursement')
        self.flashes(); r = self.c.post(f'/invoice/{self.iid}/credit', data=form)
        return self.scalar('SELECT MAX(id) FROM credit_notes'), self.flashes() + ([html.unescape(r.get_data(as_text=True))] if r.status_code == 200 else [])

    def test_credit_note_lifecycle(self):
        cid, fl = self.credit(reason='Journée non due (test)', qty='0.5')
        self.assertIn('Brouillon de note de crédit créé', ' '.join(fl))
        self.assertTrue(pdf_text(self.c.get(f'/credit/{cid}.pdf').data).count('BROUILLON'))
        self.c.post(f'/credit/{cid}/issue')
        cn = self.sql('SELECT * FROM credit_notes WHERE id=?', (cid,))[0]
        self.assertEqual((cn['status'], cn['reference'], cn['amount']), ('issued', f'NC-{YEAR}-1', 325.0))
        t = pdf_text(self.c.get(f'/credit/{cid}.pdf').data)
        for needle in ('NOTE DE CRÉDIT', f'NC-{YEAR}-1', "Facture d'origine :", f'{YEAR}-1 du', '325,00 CHF', '8,10%', '26,33 CHF', '351,33 CHF', 'Journée non due (test)'):
            self.assertIn(needle, t)
        self.assertNotIn('Paiement à 30 jours', t)  # no payment request on a document in the client's favour
        snap = self.sql('SELECT pdf_sha256 FROM credit_note_snapshots WHERE credit_note_id=?', (cid,))[0][0]
        self.assertEqual(hashlib.sha256(self.c.get(f'/credit/{cid}.pdf').data).hexdigest(), snap)
        # the original invoice is untouched
        self.assertEqual(self.c.get(f'/invoice/{self.iid}.pdf').data, self.inv_pdf)
        self.assertEqual(tuple(self.sql('SELECT * FROM invoices WHERE id=?', (self.iid,))[0]), self.inv_row)
        # contract position: credited days are no longer billed
        pos = self.suggest(self.pid, '2026-10-01', '2026-10-31')[1]
        self.assertEqual((pos['billed_days_before'], pos['po_balance_days']), (1.5, 10.5))

    def test_credit_note_immutable_once_issued(self):
        cid, _ = self.credit(reason='test', amount='100')
        self.c.post(f'/credit/{cid}/issue')
        c = sqlite3.connect(self.db); c.execute('PRAGMA foreign_keys=ON')
        for q in (f"UPDATE credit_notes SET amount=1 WHERE id={cid}", f"DELETE FROM credit_notes WHERE id={cid}",
                  "UPDATE credit_note_snapshots SET pdf_sha256='x'", "DELETE FROM credit_note_snapshots"):
            with self.assertRaises(sqlite3.DatabaseError, msg=q): c.execute(q)
        c.close()
        self.flashes(); self.c.post(f'/credit/{cid}/delete')
        self.assertTrue(any('Suppression refusée' in f for f in self.flashes()))

    def test_cannot_credit_more_than_invoiced(self):
        self.credit(reason='a', amount='1000')
        cid, fl = self.credit(reason='b', amount='300.01')
        self.assertIn('dépasserait', ' '.join(fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 1)
        cid, fl = self.credit(reason='c', qty='1', amount='5')
        self.assertIn("l'un des deux", ' '.join(fl))

    def test_second_credit_note_numbering_and_only_on_issued(self):
        for r in ('x', 'y'):
            cid, _ = self.credit(reason=r, amount='10'); self.c.post(f'/credit/{cid}/issue')
        self.assertEqual([r[0] for r in self.sql('SELECT reference FROM credit_notes ORDER BY id')], [f'NC-{YEAR}-1', f'NC-{YEAR}-1.2'])
        draft, _ = self.draft(self.pid, '2026-10-01', '2026-10-31', 1)
        self.flashes(); self.c.post(f'/invoice/{draft}/credit', data={'reason': 'z', 'amount': '1', 'treatment': 'remboursement'})
        self.assertTrue(any('uniquement à une facture émise' in f for f in self.flashes()))
        c = sqlite3.connect(self.db)
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("INSERT INTO credit_notes(invoice_id,amount,reason) VALUES(?,1,'direct')", (draft,))
        c.close()

    def test_credit_draft_deletable(self):
        cid, _ = self.credit(reason='brouillon', amount='10')
        self.c.post(f'/credit/{cid}/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM credit_notes'), 0)


class Drafts(V92):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def test_edit_and_delete_draft_only(self):
        pid = self.mandate(name='Mandat brouillon')
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        self.assertEqual(self.c.get(f'/invoice/{iid}/edit').status_code, 200)
        self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-01', 'period_to': '2026-09-15', 'qty': '1.25', 'unit': 'day', 'rounding': 'up',
                                                   'rounding_step': '0.25', 'vat': '0', 'description': 'Ligne modifiée', 'other_amount': '12.5', 'other_label': 'frais'})
        r = self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]
        self.assertEqual((r['period_to'], r['qty'], r['description'], r['other_amount'], r['rounding']), ('2026-09-15', 1.25, 'Ligne modifiée', 12.5, 'up'))
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertIn('AUTRES — frais', t); self.assertIn('12,50 CHF', t); self.assertIn('825,00 CHF', t)  # 812.50 + 12.50
        self.c.post(f'/invoice/{iid}/delete')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices'), 0)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        self.flashes(); self.c.post(f'/invoice/{iid}/edit', data={'qty': '9', 'period_from': '2026-09-01', 'period_to': '2026-09-30'})
        self.assertTrue(any('note de crédit' in f for f in self.flashes()))
        self.c.post(f'/invoice/{iid}/delete')
        self.assertEqual((self.scalar('SELECT qty FROM invoices WHERE id=?', (iid,)), self.scalar('SELECT COUNT(*) FROM invoices')), (1.0, 1))

    def test_edit_keeps_validations(self):
        pid = self.mandate(name='Mandat brouillon 2')
        self.issued(pid, '2026-08-01', '2026-08-31', 1)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        page = self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-08-15', 'period_to': '2026-09-30', 'qty': '1'}).get_data(as_text=True)
        self.assertIn('chevauche', page)
        self.c.post(f'/invoice/{iid}/edit', data={'period_from': '2026-09-30', 'period_to': '2026-09-01', 'qty': '1'})
        self.assertEqual(self.scalar('SELECT period_from FROM invoices WHERE id=?', (iid,)), '2026-09-01')


class Closure(V92):
    def test_close_keeps_history_and_blocks_new_activity(self):
        pid = self.mandate(name='Mandat à clôturer', ordered='12')
        self.entry(pid, '2026-09-10', 8)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        draft, _ = self.draft(pid, '2026-10-01', '2026-10-31', 1)
        self.flashes(); self.c.post(f'/project/{pid}/close', data={'reason': 'Fin de mission'})
        self.assertTrue(any('brouillon(s)' in f for f in self.flashes()))
        self.c.post(f'/invoice/{draft}/delete')
        self.c.post(f'/project/{pid}/close', data={'reason': ''})
        self.assertEqual(self.scalar('SELECT active FROM projects WHERE id=?', (pid,)), 1)  # reason required
        self.c.post(f'/project/{pid}/close', data={'reason': 'Fin de mission'})
        p = self.sql('SELECT active,closed_at,closed_reason FROM projects WHERE id=?', (pid,))[0]
        self.assertEqual((p['active'], p['closed_reason']), (0, 'Fin de mission')); self.assertTrue(p['closed_at'])
        self.flashes(); self.entry(pid, '2026-10-02', 1)
        self.assertTrue(any('clôturé' in f for f in self.flashes()))
        _, fl = self.draft(pid, '2026-10-01', '2026-10-31', 1)
        self.assertTrue(any('clôturé' in f for f in fl))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries WHERE project_id=?', (pid,)), 1)
        html = self.c.get('/?tab=mandates').get_data(as_text=True)
        self.assertIn('Fin de mission', html); self.assertIn(f'/project/{pid}/reopen', html)
        time_select = html.split('name="project_id" required>')[1].split('</select>')[0]
        self.assertNotIn('Mandat à clôturer', time_select)
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').status_code, 200)  # history readable
        self.c.post(f'/project/{pid}/reopen')
        self.assertEqual(self.scalar('SELECT active FROM projects WHERE id=?', (pid,)), 1)
        self.assertEqual([r[0] for r in self.sql("SELECT event FROM audit WHERE event LIKE 'project_%' ORDER BY id")][-2:], ['project_closed', 'project_reopened'])


def fr2en(v):
    return v.replace('\u202f', '').replace(',', '.').replace('−', '-')


class CalendarForecast(V92):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def years(self):
        html = self.c.get('/?tab=mandates').get_data(as_text=True)
        out = {}
        for y, body in re.findall(r'<div class="year"><h3>(\d{4})</h3>(.*?)</table></div>', html, re.S):
            # rc4: amounts are displayed in French format (7 800,00 CHF); normalised back to 7800.00 for comparison
            out[y] = {'months': {k: fr2en(v) for k, v in re.findall(r'<tr><td>(\d{4}-\d{2})</td><td>([0-9\u202f,]+)\xa0CHF</td>', body)},
                      # G4 (D-06): the « Facturé » row also counts validated historical invoices, and says so
                      'actual': fr2en(re.search(r'Facturé \d{4} \(émis et historique validé\)</td><td>([−0-9\u202f,]+)\xa0CHF', body).group(1)),
                      'total': fr2en(re.search(r'Total estimé \d{4}</b></td><td><b>([−0-9\u202f,]+)\xa0CHF', body).group(1))}
        return out, html

    def test_spread_of_real_po_balance_over_remaining_months(self):
        today = local_today()
        pid = self.mandate(name='Mandat prévision', rate='1000', ordered='24', start=f'{today.year:04d}-{today.month:02d}-01', months='12')
        y, _ = self.years()
        months = {k: v for d in y.values() for k, v in d['months'].items()}
        self.assertEqual(len(months), 12); self.assertTrue(all(v == '2000.00' for v in months.values()))
        # bill 4 days: the remaining 20 days × 1000 are spread, total exact to the cent
        self.entry(pid, today.isoformat(), 8)
        self.issued(pid, today.replace(day=1).isoformat(), today.isoformat(), 4)
        y, _ = self.years()
        months = {k: v for d in y.values() for k, v in d['months'].items()}
        self.assertAlmostEqual(sum(float(v) for v in months.values()), 20000.00, places=2)
        self.assertEqual(months[ym_add(today, 0)], '1666.67'); self.assertEqual(months[ym_add(today, 11)], '1666.63')
        self.assertEqual(y[str(today.year)]['actual'], '4000.00')
        per_year = {k: sum(float(v) for v in d['months'].values()) for k, d in y.items()}
        self.assertEqual(set(per_year), {str(today.year), str(today.year + 1)} if today.month > 1 else {str(today.year)})

    def test_closed_expired_and_undated_mandates(self):
        today = local_today()
        a = self.mandate(name='Mandat clos', rate='1000', ordered='10', start=f'{today.year:04d}-{today.month:02d}-01', months='5')
        self.c.post(f'/project/{a}/close', data={'reason': 'test'})
        self.mandate(name='Mandat échu', rate='1000', ordered='3', start='2024-01-01', months='6')
        self.mandate(name='Mandat sans date', rate='1000', ordered='3', start='', months='3')
        y, html = self.years()
        months = {k: v for d in y.values() for k, v in d['months'].items()}
        self.assertEqual(sum(float(v) for v in months.values()), 3000.0)  # only the undated one, spread from now
        self.assertIn('Mandat échu (fin 2024-06, 3\u202f000,00\xa0CHF)', html)
        self.assertIn('Mandats sans date de début', html); self.assertNotIn('Mandat clos :', html)

    def test_actuals_net_of_credit_notes(self):
        today = local_today()
        pid = self.mandate(name='Mandat net', rate='1000', ordered='10', start=f'{today.year:04d}-{today.month:02d}-01', months='2')
        iid = self.issued(pid, today.replace(day=1).isoformat(), today.isoformat(), 2)
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'test', 'qty': '0.5', 'treatment': 'compensation'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        y, _ = self.years()
        self.assertEqual(y[str(today.year)]['actual'], '1500.00')
        months = {k: v for d in y.values() for k, v in d['months'].items()}
        self.assertEqual(sum(float(v) for v in months.values()), 8500.0)  # 10 − (2 − 0.5) days


class Restore(V92):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def dump(self):
        r = self.c.get('/backup'); self.assertEqual(r.status_code, 200); return r.data

    def upload(self, raw):
        r = self.c.post('/restore', data={'backup': (io.BytesIO(raw), 'sauvegarde.json')}, content_type='multipart/form-data')
        loc = r.headers.get('Location', '')
        return loc.rsplit('/', 1)[-1] if '/restore/' in loc else None

    def state(self):
        tables = [t[0] for t in self.sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'audit' ORDER BY name")]
        return {t: [tuple(r) for r in self.sql(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}

    def test_refuses_invalid_files(self):
        self.assertIsNone(self.upload(b'{not json'))
        self.assertIsNone(self.upload(json.dumps({'tables': {}}).encode()))
        self.assertIsNone(self.upload(json.dumps({'meta': {'app_version': '5.0'}, 'tables': {}}).encode()))
        self.assertIsNone(self.upload(json.dumps({'meta': {'app_version': '9.2-rc'}, 'tables': {'hack': []}}).encode()))
        pid = self.mandate(name='Mandat altéré'); self.issued(pid, '2026-09-01', '2026-09-30', 1)
        data = json.loads(self.dump()); data['tables']['invoice_snapshots'][0]['pdf'] = base64.b64encode(b'%PDF-falsifie').decode()
        self.assertIsNone(self.upload(json.dumps(data).encode()))
        self.assertTrue(any('empreinte du PDF figé invalide' in f for f in self.flashes()))

    def test_roundtrip_with_preview_confirmation_and_prior_backup(self):
        pid = self.mandate(name='Mandat sauvegardé', vat='8.1'); self.entry(pid, '2026-09-10', 8)
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'r', 'amount': '50', 'treatment': 'remboursement'}); self.c.post(f'/credit/{self.scalar("SELECT MAX(id) FROM credit_notes")}/issue')
        raw = self.dump(); saved = self.state(); pdf = self.c.get(f'/invoice/{iid}.pdf').data
        # later work that the restore will discard (no issued document involved)
        self.entry(pid, '2026-10-01', 3); self.mandate(name='Mandat ultérieur')
        token = self.upload(raw); self.assertIsNotNone(token)
        page = self.c.get(f'/restore/{token}').get_data(as_text=True)
        self.assertIn('<td>entries</td><td>2</td><td>1</td>', page); self.assertNotIn('Restauration bloquée', page)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 2)  # preview changes nothing
        self.flashes(); self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'oui'})
        self.assertTrue(any('RESTAURER' in f for f in self.flashes())); self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), 2)
        self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        fl = ' '.join(self.flashes()); self.assertIn('Restauration effectuée', fl)
        self.assertEqual(self.state(), saved)
        self.assertEqual(self.c.get(f'/invoice/{iid}.pdf').data, pdf)
        bk = re.search(r'(pre-restore-[\w-]+\.db)', fl).group(1)
        b = sqlite3.connect(os.path.join(m.backup_dir(), bk))
        self.assertEqual(b.execute('SELECT COUNT(*) FROM entries').fetchone()[0], 2); b.close()  # state just before restore
        self.assertEqual(self.sql("SELECT event FROM audit ORDER BY id DESC LIMIT 1")[0][0], 'json_restored')
        self.integrity()
        c = sqlite3.connect(self.db); c.execute('PRAGMA foreign_keys=ON')  # triggers still active after rebuild
        with self.assertRaises(sqlite3.DatabaseError): c.execute(f'DELETE FROM invoices WHERE id={iid}')
        c.close()

    def test_blocked_when_issued_documents_would_be_lost(self):
        pid = self.mandate(name='Mandat perte')
        raw = self.dump()
        iid = self.issued(pid, '2026-09-01', '2026-09-30', 1)  # issued after the backup
        token = self.upload(raw)
        page = self.c.get(f'/restore/{token}').get_data(as_text=True)
        self.assertIn('Restauration bloquée', page); self.assertIn(f'{YEAR}-1', page)
        self.flashes(); self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        self.assertTrue(any('base inchangée' in f for f in self.flashes()))
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued')

    def test_cancel_removes_staged_file(self):
        token = self.upload(self.dump())
        self.c.post(f'/restore/{token}', data={'action': 'cancel'})
        self.assertEqual(self.c.get(f'/restore/{token}').status_code, 404)
