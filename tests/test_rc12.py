"""V9.2-rc12: open points of the rc10 QA (synthetic data only, on a COPY of the staging database; see test_import.py).

QA-21 first page of the PDF: long addresses / legal name / payment terms / thanks / footer wrap or shrink, nothing leaves the page
      (checked on every drawn string: its width is measured with the real font)
"""
from reportlab.pdfbase import pdfmetrics

from app import pdf_layout
from tests.test_rc6 import Rc6

LONG_LINE = 'Direction générale des infrastructures et de la mobilité numérique du canton, bureau des grands projets transversaux'
LEFT, RIGHT = 30.0, 565.0          # A4 is 595 pt wide: nothing may be drawn outside these margins


class Recorder:
    """Wrap Doc.text to record the horizontal extent of every drawn string."""
    def __enter__(self):
        self.items, self.orig = [], pdf_layout.Doc.text
        rec = self
        def text(d, x, top, s, size=8, font=pdf_layout.BODY, color=None, align="left", label=None):
            if s and d.c._pagesize[0] < 600:   # portrait pages only (annex pages are landscape)
                w = pdfmetrics.stringWidth(s, font, size)
                x0 = {"left": x, "right": x - w, "center": x - w / 2}[align]
                rec.items.append((x0, x0 + w, top, s))
            kw = {} if color is None else {"color": color}
            return rec.orig(d, x, top, s, size=size, font=font, align=align, label=label, **kw)
        pdf_layout.Doc.text = text; return self
    def __exit__(self, *a): pdf_layout.Doc.text = self.orig


class LongTexts(Rc6):
    def long_header(self, **extra):
        h, rows = self.header(self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0], issued=True)
        iss = dict(h["issuer"], issuer_name=LONG_LINE, issuer_address=f'{LONG_LINE}\nRue de la Très Longue Avenue du Général-Guisan-Dufour 123bis\n1000 Lausanne',
                   payment_terms='Paiement à 30 jours net dès réception de la facture, sans escompte, par virement bancaire exclusivement, en francs suisses ' * 2,
                   thanks_text='Merci de votre confiance et au plaisir de poursuivre cette collaboration dans la durée ' * 2, issuer_rc='CHE-123.456.789 RC Vaud', issuer_vat_number='CHE-123.456.789 TVA ' * 3)
        return dict(h, issuer=iss, billing_contact='Madame Prénom Nom-Très-Long-De-Famille, cheffe de projet', billing_address=f'{LONG_LINE}\nAvenue de la Gare 1\n1003 Lausanne',
                    client_legal_name='Département Fictif des Infrastructures et de la Mobilité de la République et canton', **extra), rows

    def test_nothing_leaves_the_page(self):
        h, rows = self.long_header()
        with Recorder() as r: data = pdf_layout.render_invoice(h, rows, issued=True)[0]
        self.assertTrue(r.items)
        bad = [(round(a), round(b), s[:40]) for a, b, _, s in r.items if a < LEFT or b > RIGHT]
        self.assertEqual(bad, [], 'strings outside the margins')
        self.assertTrue(data.startswith(b'%PDF'))

    def test_blocks_stay_above_the_table(self):
        h, rows = self.long_header()
        with Recorder() as r: pdf_layout.render_invoice(h, rows, issued=True)
        header_rows = [t for a, b, t, s in r.items if 185 <= t < 295 and (a < 210 or a >= 390)]
        self.assertTrue(header_rows); self.assertLessEqual(max(header_rows), pdf_layout.BLOCK_BOTTOM + 1)

    def test_no_text_lost(self):
        h, rows = self.long_header()
        with Recorder() as r: pdf_layout.render_invoice(h, rows, issued=True)
        printed = ' '.join(s for *_, s in r.items).replace('- ', '').replace('-', '')
        for w in ('Guisan', 'Lausanne', 'Prénom', 'Département', 'confiance', 'escompte'): self.assertIn(w, printed.replace('Guisan-Dufour', 'GuisanDufour').replace('Guisan', 'Guisan'))

    def test_block_fits_refuses_the_impossible(self):
        h, _ = self.long_header()
        self.assertTrue(pdf_layout.block_fits(h))
        absurd = dict(h, billing_address='\n'.join(f'ligne {i} de l’adresse' for i in range(30)))
        self.assertFalse(pdf_layout.block_fits(absurd))

    def test_short_texts_unchanged(self):
        h, rows = self.header(self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0], issued=True)
        self.assertTrue(pdf_layout.block_fits(h))


import html as _html, re, json as _json

from tests.test_v92 import V92


def page_text(r): return _html.unescape(re.sub(r'<[^>]+>', ' ', r.data.decode()))


class KeptForm(V92):
    """QA-09: a refused form is shown again with what was typed (no secret, no hidden field, one use, 2 minutes)."""
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat rc12', rate='650', vat='0')

    def kept_json(self, r):
        m = re.search(r'<script[^>]*id="tb-kept">(.*?)</script>', r.data.decode(), re.S)
        return _json.loads(_html.unescape(m.group(1))) if m else None

    def test_refused_entry_comes_back_filled(self):
        r = self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': '99', 'description': 'réunion importante du lundi'})
        self.assertEqual(r.status_code, 302)
        page = self.c.get('/?tab=time')
        self.assertIn('Saisie refusée', page_text(page))
        k = self.kept_json(page)
        self.assertEqual(k['path'], '/entry'); self.assertEqual(k['data']['description'], 'réunion importante du lundi'); self.assertEqual(k['data']['manual_hours'], '99')
        self.assertIsNone(self.kept_json(self.c.get('/?tab=time')), 'consumed once')

    def test_kept_text_is_inert_in_the_page(self):
        evil = '</script><script>alert(1)</script>'
        self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': '99', 'description': evil})
        raw = self.c.get('/?tab=time').data.decode()
        self.assertNotIn(evil, raw); self.assertNotIn('<script>alert(1)', raw)

    def test_successful_entry_keeps_nothing(self):
        self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': '2', 'description': 'ok'})
        self.assertIsNone(self.kept_json(self.c.get('/?tab=time')))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM kept_forms'), 0)

    def test_refused_project_edit_rerenders_with_typed_values(self):
        r = self.c.post(f'/project/{self.pid}/edit', data={'name': 'Mandat rc12', 'rate': '-5', 'ordered_days': '12', 'vat': '0', 'day_hours': '8', 'billing_address': 'Adresse tapée à garder'})
        self.assertEqual(r.status_code, 200)
        k = self.kept_json(r)
        self.assertEqual(k['path'], f'/project/{self.pid}/edit'); self.assertEqual(k['data']['billing_address'], 'Adresse tapée à garder')

    def test_refused_credit_note_keeps_reason(self):
        iid = self.issued(self.pid, '2026-09-01', '2026-09-30', 1)
        r = self.c.post(f'/invoice/{iid}/credit', data={'reason': 'motif long tapé', 'qty': '50', 'treatment': 'remboursement'})
        k = self.kept_json(r) if r.status_code == 200 else self.kept_json(self.c.get('/?tab=archive'))
        self.assertTrue(k and k['data']['reason'] == 'motif long tapé', r.status_code)

    def test_not_carried_across_sessions_or_backups(self):
        self.c.post('/entry', data={'work_date': '2026-09-10', 'project_id': str(self.pid), 'entry_mode': 'duration', 'manual_hours': '99', 'description': 'MARQUEUR-KEPT-7731'})
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM kept_forms'), 1)
        b = self.c.get('/backup'); self.assertEqual(b.status_code, 200)
        self.assertNotIn(b'MARQUEUR-KEPT-7731', b.data)
        j = _json.loads(b.data); self.assertNotIn('kept_forms', j['tables']); self.assertNotIn('kept_forms', j['meta']['row_counts'])
        from app import restore_service
        self.assertIn('kept_forms', restore_service.TRANSIENT)


class EntryRevision(V92):
    """QA-25: two tabs on the same entry: the second save is refused, typed values kept, history unchanged."""
    def test_second_tab_is_refused(self):
        pid = self.mandate(name='Mandat rev', rate='650')
        self.entry(pid, '2026-09-10', 2)
        eid = self.scalar('SELECT MAX(id) FROM entries')
        form = lambda h: {'work_date': '2026-09-10', 'project_id': str(pid), 'entry_mode': 'duration', 'manual_hours': h, 'description': 'x'}
        rev = lambda: re.search(r'name="rev" value="([0-9a-f]+)"', self.c.get(f'/entry/{eid}/edit').data.decode()).group(1)
        a, b = rev(), rev()
        self.assertEqual(a, b)
        r = self.c.post(f'/entry/{eid}/edit', data=dict(form('3'), rev=a)); self.assertEqual(r.status_code, 302)
        self.assertEqual(self.scalar('SELECT hours FROM entries WHERE id=?', (eid,)), 3)
        r = self.c.post(f'/entry/{eid}/edit', data=dict(form('5'), rev=b))
        self.assertEqual(r.status_code, 200); self.assertIn('modifiée depuis l', page_text(r))
        self.assertEqual(self.scalar('SELECT hours FROM entries WHERE id=?', (eid,)), 3)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entry_changes WHERE entry_id=?', (eid,)), 1)
        # the re-rendered form carries the new token: a deliberate second save goes through
        r = self.c.post(f'/entry/{eid}/edit', data=dict(form('5'), rev=re.search(r'name="rev" value="([0-9a-f]+)"', r.data.decode()).group(1)))
        self.assertEqual(r.status_code, 302); self.assertEqual(self.scalar('SELECT hours FROM entries WHERE id=?', (eid,)), 5)


class Misc(V92):
    def test_empty_year_archive_is_refused_not_empty_zip(self):
        r = self.c.get('/archive.zip?year=1999')
        self.assertEqual(r.status_code, 302); self.assertIn('Aucun document émis en 1999', ' '.join(self.flashes()))

    def test_draft_created_points_to_the_archive(self):
        pid = self.mandate(name='Mandat msg'); self.entry(pid, '2026-09-10', 8)
        _, fl = self.draft(pid, '2026-09-01', '2026-09-30', 1)
        self.assertTrue(any('Factures et brouillons' in f for f in fl), fl)   # B-8 (2026-10-20): tab renamed
