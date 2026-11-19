"""V9.2-rc6: anomalies A1-A3 of the final business test (synthetic data only, on a COPY of the staging database;
see test_import.py for the run command).

A1 summary page: a value wider than its column wraps onto further lines instead of being truncated
A2 cancellation document: recalls the mode (refund / offset) of the cancelled credit note
A3 timestamps on screen in a readable French format; the technical value stays available (datetime / title)
Non-regression: rc6 pages that A1/A2 do not touch are drawn exactly as by the rc5 layout (tests/_layout_rc5.py).
"""
import html, re, sqlite3
import unittest.mock as mock

from app import billing_rules as rules, invoice_service, pdf_layout
from tests import _layout_rc5
from tests.test_functional import _pdf_objects, _stream, pdf_text
from tests.test_v92 import V92

LONG_CLIENT = 'Département Fictif des Infrastructures et de la Mobilité'


def page_streams(data):
    """Decompressed drawing streams of every page (font programs excluded)."""
    out = []
    for body in _pdf_objects(data).values():
        if b'/Length' not in body or b'/Length1' in body or b'/Subtype' in body: continue
        s = _stream(body)
        if b'BT' in s or b' re' in s: out.append(s)
    return out


def text_positions(stream):
    """(x, y, size) of every BT … ET text object of a page stream, as a multiset (the string bytes are left out: adding a glyph to the embedded
    font subset renumbers the codes of the others)."""
    from collections import Counter
    return Counter((float(x), float(y), float(z)) for x, y, z in re.findall(rb'BT 1 0 0 1 ([\d.]+) ([\d.]+) Tm /\S+ ([\d.]+) Tf', stream))


def only_the_period_moved(test, old, new):
    """D6 (a), 2026-10-06: page 1 is the rc5 one except the invoiced period, no longer printed under the totals (x = 210) but as the last line
    of the DESCRIPTION cell (x = 50.3); a one-line description thus makes a two-line cell, so quantity, rate and amount are centred on it
    (5.1 pt lower, as on the reference invoice whose description has two lines). Everything else, rules and bands included, stays in place."""
    o, n = text_positions(old), text_positions(new)
    gone, came = sorted((o - n).elements()), sorted((n - o).elements())
    per_old = [g for g in gone if g[0] == 210 and g[2] == 7.5]; per_new = [c for c in came if c[0] == 50.3 and c[2] == 8]
    test.assertEqual((len(per_old), len(per_new)), (1, 1), (gone, came))
    moved = [g for g in gone if g not in per_old]
    test.assertEqual(sorted((x, round(y - 5.1, 4), z) for x, y, z in moved), sorted(c for c in came if c not in per_new), (gone, came))
    test.assertTrue(len(moved) in (0, 3))
    shapes = lambda st: sorted(l for l in re.sub(rb'BT .*? ET', b'', st, flags=re.S).splitlines() if not l.endswith((b' rg', b' RG')))   # rules, bands (fill colours set around texts aside)
    test.assertEqual(shapes(old), shapes(new))


class Rc6(V92):
    def setUp(self):
        super().setUp()
        self.pid = self.mandate(name='Mandat rc6', rate='650', vat='8.1')
        self.entry(self.pid, '2026-09-10', 16)

    def header(self, iid, issued=False):
        c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
        try: h, rows = invoice_service.live_data(c, iid)
        finally: c.close()
        if issued: h = dict(h, number='2026-09', status='issued', invoice_date='2026-09-30')
        return h, rows

    def set_client(self, client):
        self.c.post(f'/project/{self.pid}/edit', data={'name': 'Mandat rc6', 'client': client, 'po': 'PO-RC6', 'rate': '650', 'ordered_days': '12', 'vat': '8.1',
                                                       'day_hours': '8', 'project_number': 'NP-RC6', 'billing_address': 'Entité Fictive\nRue 1\n1000 Ville',
                                                       'dates_label': 'Sept 2026', 'start_date': '2025-11-01', 'duration_months': '11',
                                                       'client_legal_name': 'Entité Fictive SA', 'client_legal_id': 'CHE-000.000.777'})


class SummaryWrap(Rc6):
    def test_long_client_printed_in_full(self):
        self.set_client(LONG_CLIENT)
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)
        self.issue(iid)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        self.assertNotIn('…', t)
        for word in LONG_CLIENT.split(): self.assertIn(word, t.split())
        # every other summary value still printed
        for v in ('NP-RC6', 'PO-RC6', 'Sept 2026'): self.assertIn(v, t)

    def test_wrap_rule(self):
        # rc7 (A1): wrap at the normal size, never shrink; Client column now 150 pt wide (144 pt of text)
        d = pdf_layout.Doc(); w = pdf_layout.SUMMARY_COLS[3] - pdf_layout.SUMMARY_COLS[2] - 6
        size, lines = d.fit_cell(LONG_CLIENT, w, 10.3, pdf_layout.SHEET)
        self.assertGreater(len(lines), 1); self.assertEqual(size, 10.3)
        self.assertEqual(' '.join(lines), LONG_CLIENT, 'words are never cut when they fit the column')
        self.assertTrue(all(d.c.stringWidth(l, pdf_layout.SHEET, size) <= w for l in lines))
        self.assertEqual(d.fit_cell('CLI', w, 10.3, pdf_layout.SHEET), (10.3, ['CLI']))
        size, long_word = d.fit_cell('X' * 40, 51, 10.3, pdf_layout.SHEET)  # last resort: hyphenated, nothing lost
        self.assertEqual(size, 10.3); self.assertEqual(''.join(l.rstrip('-') for l in long_word), 'X' * 40)
        self.assertEqual(d.wrap('', 51, 10.3), [''])

    def test_short_values_drawn_exactly_as_rc5(self):
        self.set_client('CLI')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)
        for issued in (False, True):
            h, rows = self.header(iid, issued)
            if not issued: h = dict(h, number=None)       # rc37: a draft prints its reserved number and spreads the date / number / PO rows (tests/test_invoice_numbers.py); the rc5 wording is the fallback compared here
            old = page_streams(_layout_rc5.render_invoice(h, rows, issued=issued)[0])
            with mock.patch.object(pdf_layout, 'DRAFT_REF_ROW_PITCH', pdf_layout.REF_ROW_PITCH):
                new = page_streams(pdf_layout.render_invoice(h, rows, issued=issued)[0])
            self.assertEqual(len(old), len(new)); self.assertTrue(old)
            # rc7 (A1/A4): the summary page is redrawn (columns, renamed heading, position block, see test_rc7);
            # every annex page stays exactly as in rc5; page 1 too, except the period line (D6)
            self.assertEqual(old[1:-1], new[1:-1], 'annex keeps the rc5 / reference geometry')
            only_the_period_moved(self, old[0], new[0])

    def test_long_value_only_changes_summary_page(self):
        self.set_client(LONG_CLIENT)
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2)
        h, rows = self.header(iid, True)
        old = page_streams(_layout_rc5.render_invoice(h, rows, issued=True)[0])
        new = page_streams(pdf_layout.render_invoice(h, rows, issued=True)[0])
        self.assertEqual(old[1:-1], new[1:-1]); only_the_period_moved(self, old[0], new[0])  # annex pages unchanged, page 1 but the period (D6)
        self.assertNotEqual(old[-1], new[-1])


class CancellationMode(Rc6):
    def cancel_doc(self, treatment):
        self.set_client('CLI')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2); self.issue(iid)
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'r', 'qty': '0.5', 'treatment': treatment})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.c.post(f'/credit/{cid}/cancel', data={'reason': 'mode erroné (test)'})
        return cid, pdf_text(self.c.get(f'/credit/{cid}/cancellation.pdf').data)

    def test_refund_mode_recalled(self):
        _, t = self.cancel_doc('remboursement')
        self.assertIn('Mode de traitement de la note annulée : remboursement (aucun remboursement en vigueur).', ' '.join(t.split()))

    def test_offset_mode_recalled(self):
        _, t = self.cancel_doc('compensation')
        self.assertIn('Mode de traitement de la note annulée : compensation sur facture ultérieure (aucune imputation en vigueur).', ' '.join(t.split()))

    def test_only_the_mode_line_is_new(self):
        cid, _ = self.cancel_doc('compensation')
        c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
        import json
        h = json.loads(c.execute('SELECT header_json FROM credit_note_cancellations WHERE credit_note_id=?', (cid,)).fetchone()[0]); c.close()
        old = pdf_text(_layout_rc5.render_cancellation(h)[0]); new = pdf_text(pdf_layout.render_cancellation(h)[0])
        # RC8: the rc5 renderer printed the UTC day of issuance timestamps, rc8 prints the Zurich day: date-only lines excluded
        dated = lambda l: re.search(r'\d{2}\.\d{2}\.\d{4}', l)
        old = '\n'.join(l for l in old.splitlines() if not dated(l)); new = '\n'.join(l for l in new.splitlines() if not dated(l))
        added = ' '.join(l for l in new.splitlines() if l not in old.splitlines())
        self.assertTrue(added.startswith('Mode de traitement de la note annulée') and added.endswith('(aucune imputation en vigueur).'), added)
        self.assertTrue(all(l in new.splitlines() for l in old.splitlines()), 'nothing printed by rc5 is lost')


class MentionsWrap(Rc6):
    def test_long_mentions_stay_inside_the_page(self):
        """Every text drawn on a credit note / cancellation with long mentions ends left of the right margin."""
        import json
        self.set_client('CLI')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2); self.issue(iid)
        long_reason = 'Motif volontairement très long pour vérifier le retour à la ligne des mentions imprimées sous le bloc des totaux (fictif)'
        self.c.post(f'/invoice/{iid}/credit', data={'reason': long_reason, 'qty': '0.5', 'treatment': 'compensation'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.c.post(f'/credit/{cid}/cancel', data={'reason': long_reason})
        c = sqlite3.connect(self.db)
        note = json.loads(c.execute('SELECT header_json FROM credit_note_snapshots WHERE credit_note_id=?', (cid,)).fetchone()[0])
        ann = json.loads(c.execute('SELECT header_json FROM credit_note_cancellations WHERE credit_note_id=?', (cid,)).fetchone()[0]); c.close()
        from decimal import Decimal
        note['amounts'] = {k: Decimal(v) for k, v in note['amounts'].items()}
        for name, render in (('note', lambda: pdf_layout.render_credit_note(note, issued=True)), ('annulation', lambda: pdf_layout.render_cancellation(ann))):
            drawn = []; orig = pdf_layout.Doc.text
            def spy(self_, x, top, s_, size=8, font=pdf_layout.BODY, color=None, align="left", label=None, **kw):
                if s_ and self_.c.getPageNumber() == 1:
                    w = self_.c.stringWidth(s_, font, size)
                    drawn.append((s_, {"left": x + w, "right": x, "center": x + w / 2}[align]))
                return orig(self_, x, top, s_, size=size, font=font, **({"color": color} if color is not None else {}), align=align, label=label)
            pdf_layout.Doc.text = spy
            try: render()
            finally: pdf_layout.Doc.text = orig
            worst = max(drawn, key=lambda t: t[1])
            self.assertLessEqual(worst[1], 557.5, (name, worst))
            self.assertIn('Mode de traitement de la note annulée', ' '.join(t[0] for t in drawn)) if name == 'annulation' else None
            self.assertEqual(' '.join(w for t in drawn for w in t[0].split() if w in long_reason.split()).count('volontairement'), 1)


class Timestamps(Rc6):
    def test_rule(self):
        # rc7 (A3): JJ.MM.AAAA à HH:MM:SS
        # rc7 (A3) format; RC8: stored UTC shown in Europe/Zurich (CEST = UTC+2 in October)
        for raw, shown in {'2026-10-03T13:13:26': '03.10.2026 à 15:13:26', '2026-10-03 07:05:00': '03.10.2026 à 09:05:00', '2026-10-03': '03.10.2026',
                           '2026-10-03T13:13:26.123456': '03.10.2026 à 15:13:26', '': '', None: '', 'n/a': 'n/a'}.items():
            self.assertEqual(rules.fr_ts(raw), shown, raw)

    def test_screens_show_french_and_keep_technical_value(self):
        self.set_client('CLI')
        iid, _ = self.draft(self.pid, '2026-09-01', '2026-09-30', 2, invoice_date='2026-09-30')
        page = self.c.get(f'/invoice/{iid}/edit').get_data(as_text=True)
        raw = self.scalar('SELECT changed_at FROM invoice_date_changes WHERE invoice_id=?', (iid,))
        self.assertIn(f'<time datetime="{raw}Z" title="UTC {raw}">{rules.fr_ts(raw)}</time>', page)  # RC8: UTC marked
        self.assertNotRegex(re.sub(r'<[^>]+>', '', page), r'\d{4}-\d{2}-\d{2}T\d{2}:')
        self.issue(iid)
        self.c.post(f'/invoice/{iid}/credit', data={'reason': 'r', 'qty': '0.5', 'treatment': 'remboursement'})
        cid = self.scalar('SELECT MAX(id) FROM credit_notes'); self.c.post(f'/credit/{cid}/issue')
        self.c.post(f'/credit/{cid}/refund', data={'amount': '10', 'executed_on': rules.local_today().isoformat()})
        page = self.c.get(f'/credit/{cid}').get_data(as_text=True)
        visible = html.unescape(re.sub(r'<[^>]+>', '', page))
        self.assertNotRegex(visible, r'\d{4}-\d{2}-\d{2}T\d{2}:', 'no raw ISO timestamp left in the history')
        op_raw = self.scalar('SELECT created_at FROM credit_operations WHERE credit_note_id=?', (cid,))
        self.assertIn(f'datetime="{op_raw}Z"', page)
        # stored values untouched (technical format, ordering, audit)
        self.assertRegex(op_raw, r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')
        archive = html.unescape(self.c.get('/?tab=archive').get_data(as_text=True))
        self.assertRegex(archive, r'title="\d{2}\.\d{2}\.\d{4} à \d{2}:\d{2}:\d{2} : émission → 30\.09\.2026')  # rc7 (A3)
