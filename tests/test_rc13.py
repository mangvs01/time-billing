"""V9.2-rc13: remaining points of the rc10 QA (synthetic data only, on a COPY of the staging database; see test_import.py).

QA-22 annex: the Motif column wraps instead of being cut with "…"; pagination follows the real row heights
"""
from reportlab.pdfbase import pdfmetrics

from app import pdf_layout
from tests.test_rc6 import Rc6

LONG = "Préparation de l'atelier de cadrage avec l'équipe projet puis revue du budget détaillé et rédaction du compte rendu pour le comité de pilotage"


def entry(day, desc, hours=1.0):
    return {"work_date": f"2026-09-{day:02d}", "description": desc, "hours": hours, "start_time": "08:00", "end_time": "09:00"}


class Annex(Rc6):
    def render(self, rows):
        h, _ = self.header(self.draft(self.pid, '2026-09-01', '2026-09-30', 2)[0], issued=True)
        printed = []
        orig = pdf_layout.Doc.text
        def text(d, x, top, s, *a, **kw):
            if s and d.c._pagesize[0] > 600: printed.append((x, top, s))
            return orig(d, x, top, s, *a, **kw)
        pdf_layout.Doc.text = text
        try: data = pdf_layout.render_invoice(h, rows, issued=True)[0]
        finally: pdf_layout.Doc.text = orig
        return data, printed

    def test_motif_wraps_without_ellipsis(self):
        data, printed = self.render([entry(1, LONG)])
        motif = " ".join(s for x, _, s in printed if abs(x - 204.0) < .01)
        self.assertNotIn("…", motif)
        self.assertEqual(motif.replace("- ", ""), LONG)
        self.assertGreater(len([1 for x, _, _ in printed if abs(x - 204.0) < .01]), 1)

    def test_line_breaks_and_spaces_collapse(self):
        rows = pdf_layout.motif_lines(entry(1, "équipe\nsuite   de ligne\t!"))
        self.assertEqual(rows, ["équipe suite de ligne !"])

    def test_every_motif_line_fits_its_column(self):
        for line in pdf_layout.motif_lines(entry(1, LONG * 3 + " " + "x" * 80)):
            self.assertLessEqual(pdfmetrics.stringWidth(line, pdf_layout.SHEET, 9), pdf_layout.MOTIF_WIDTH + .01)

    def test_pagination_follows_row_heights(self):
        rows = [entry(1 + i % 28, LONG) for i in range(30)]
        plan = pdf_layout.annex_plan(rows)
        self.assertGreater(len(plan), 1)
        budget = pdf_layout.ROWS_PER_PAGE * pdf_layout.ROW_PITCH
        for ym, chunk, last, total, k, *_ in plan:
            self.assertLessEqual(sum(pdf_layout.row_height(e) for e in chunk), budget + .01)
        self.assertEqual(sum(len(c) for _, c, *_ in plan), 30)

    def test_single_line_rows_keep_21_per_page(self):
        plan = pdf_layout.annex_plan([entry(1 + i % 28, "Réunion") for i in range(22)])
        self.assertEqual([len(c) for _, c, *_ in plan], [21, 1])

    def test_enormous_motif_is_the_only_cut(self):
        rows = pdf_layout.motif_lines(entry(1, "mot " * 1000))
        self.assertEqual(len(rows), pdf_layout.MOTIF_MAX_LINES); self.assertTrue(rows[-1].endswith("…"))
        self.assertLessEqual(pdf_layout.row_height(entry(1, "mot " * 1000)), pdf_layout.ROWS_PER_PAGE * pdf_layout.ROW_PITCH)

    def test_rows_stay_above_the_page_number(self):
        _, printed = self.render([entry(1 + i % 28, LONG) for i in range(18)])
        self.assertTrue(printed)
        self.assertLessEqual(max(t for _, t, s in printed if not s.startswith("Page ")), 560)


from tests.test_credit_settlement import Settlement
import sqlite3


class SqlHardening(Settlement):
    """QA-S3: rules that hold even for a direct SQL write (the application is not the only line of defence)."""
    def raw(self, sql, args=()):
        c = sqlite3.connect(self.db)
        try: c.execute(sql, args); c.commit()
        finally: c.close()

    def test_audit_log_is_append_only(self):
        self.assertGreater(self.scalar('SELECT COUNT(*) FROM audit'), 0)
        for sql in ("UPDATE audit SET detail='x'", "DELETE FROM audit"):
            with self.assertRaises(sqlite3.DatabaseError) as cm: self.raw(sql)
            self.assertIn('append-only', str(cm.exception))

    def test_refund_cannot_exceed_the_credit_note(self):
        cid = self.issued_cn(amount='100', treatment='remboursement')
        ttc = float(self.pos(cid)['ttc'])
        ins = "INSERT INTO credit_operations(credit_note_id,kind,amount,executed_on,created_at) VALUES(?,?,?,?,?)"
        with self.assertRaises(sqlite3.DatabaseError) as cm: self.raw(ins, (cid, 'refund', 1e9, '2026-10-01', 'x'))
        self.assertIn('cannot exceed', str(cm.exception))
        with self.assertRaises(sqlite3.DatabaseError): self.raw(ins, (cid, 'refund', ttc + 1, '2026-10-01', 'x'))
        self.raw(ins, (cid, 'refund', ttc, '2026-10-01', 'x'))                     # the exact amount is accepted
        with self.assertRaises(sqlite3.DatabaseError): self.raw(ins, (cid, 'refund', 1, '2026-10-01', 'x'))   # nothing left

    def test_application_refunds_still_work(self):
        cid = self.issued_cn(amount='100', treatment='remboursement')
        ttc = self.pos(cid)['ttc']
        self.assertIn('', self.refund(cid, '40')); op = self.last_op()
        self.reverse(cid, op); self.refund(cid, str(ttc))                           # reversal frees the amount again
        self.assertEqual(self.pos(cid)['balance'], 0)


class LegalIdentityLock(Settlement):
    """QA-S2: the legal client of a draft that receives a reserved offset cannot be changed through the mandate."""
    def edit(self, **over):
        row = self.sql('SELECT * FROM projects WHERE id=?', (self.pid,))[0]
        form = {k: ('' if row[k] is None else str(row[k])) for k in row.keys() if k not in ('id', 'active', 'closed_at', 'closed_reason')}
        form['short_name'] = form.get('short_name', ''); form.update(over)
        self.flashes(); r = self.c.post(f'/project/{self.pid}/edit', data=form); return ' '.join(self.page_msgs(r))

    def test_locked_while_an_offset_is_reserved(self):
        cid = self.issued_cn(qty='0.5', treatment='compensation')
        self.entry(self.pid, '2026-10-05', 8)
        target, fl = self.draft(self.pid, '2026-10-01', '2026-10-31', 1)
        self.assertIn('Imputation enregistrée', self.offset(cid, target, '100'))
        before = self.sql('SELECT client_legal_id FROM projects WHERE id=?', (self.pid,))[0][0]
        self.assertIn('identité juridique', self.edit(client_legal_id='CHE-111.222.333'))
        self.assertEqual(self.sql('SELECT client_legal_id FROM projects WHERE id=?', (self.pid,))[0][0], before)
        self.assertNotIn('identité juridique', self.edit(client='Autre libellé'))          # unrelated fields stay editable
        op = self.last_op(); self.reverse(cid, op)
        self.assertNotIn('identité juridique', self.edit(client_legal_id='CHE-111.222.333'))   # free again once the offset is reversed
