"""A-01 (Decision Center billing-a01-l01 … l15, 2026-10-07): the tool outils/reporter_notes_a01.py copies the column-I note of the workbook into the
empty description of an imported entry through the application's own correction route. Synthetic entries only, on a COPY of the staging database."""
import unittest.mock

import app.app as m
from app import post_billing
from outils import reporter_notes_a01 as tool
from tests.test_g4 import G4


class A01Tool(G4):
    def imported(self, d, start, end, hours, ref, desc=''):
        c = m.db()
        try:
            cur = c.execute("INSERT INTO entries(work_date,project_id,start_time,end_time,hours,description,source,source_ref) VALUES(?,?,?,?,?,?,?,?)",
                            (d, self.pid, start, end, hours, desc, 'historical_excel', ref)); c.commit(); return cur.lastrowid
        finally: c.close()

    def plan(self, cards):
        c = m.db()
        try:
            with unittest.mock.patch.object(tool, 'A01', cards): return tool.plan(c, post_billing)
        finally: c.close()

    def test_the_note_goes_into_the_description_through_the_traced_correction_and_nothing_else_changes(self):
        e1 = self.imported('2026-09-30', '14:09', '15:15', 1.0999999999999996, 'SEPT 26!127')      # declared hours kept, not recomputed from the clock
        e2 = self.imported('2026-07-31', '', '', 0.25, 'JUL 26!51')
        cards = [('billing-a01-l15', 'SEPT 26', 127, 'session management', e1), ('billing-a01-l05', 'JUL 26', 51, 'DM', e2)]
        todo = self.plan(cards); self.assertEqual([x[3] for x in todo], [True, True])
        before, sessions = self.position(), self.scalar('SELECT COUNT(*) FROM web_sessions')
        self.assertEqual(tool.apply(m, todo), [e1, e2])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM web_sessions'), sessions)                 # the tool's session is revoked
        self.assertEqual(self.sql('SELECT description,hours,start_time,end_time FROM entries WHERE id=?', (e1,))[0][:], ('session management', 1.0999999999999996, '14:09', '15:15'))
        self.assertEqual(self.sql('SELECT description,hours FROM entries WHERE id=?', (e2,))[0][:], ('DM', 0.25))
        self.assertEqual(self.sql("SELECT reason FROM entry_changes WHERE entry_id=? AND action='update'", (e1,))[0][0], 'note colonne I du classeur (Decision Center billing-a01-l15)')
        self.assertEqual(self.position(), before)
        self.assertEqual([x[3] for x in self.plan(cards)], [False, False])                          # second run: nothing left to do

    def test_any_mismatch_stops_before_the_first_write(self):
        e1 = self.imported('2026-09-22', '13:30', '15:30', 2.0, 'SEPT 26!88')
        e2 = self.imported('2026-09-22', '17:30', '18:30', 1.0, 'SEPT 26!90', desc='déjà décrite')
        with self.assertRaises(SystemExit) as e:
            self.plan([('billing-a01-l06', 'SEPT 26', 88, 'session management', e1), ('billing-a01-l07', 'SEPT 26', 90, 'session management', e2)])
        self.assertIn('a déjà la description', str(e.exception))
        with self.assertRaises(SystemExit) as e: self.plan([('billing-a01-l06', 'SEPT 26', 89, 'session management', e1)])
        self.assertIn('provient de', str(e.exception))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entry_changes WHERE entry_id IN (?,?)", (e1, e2)), 0)

    def test_the_tool_lists_the_fifteen_cards_of_the_decision_center(self):
        self.assertEqual([x[0] for x in tool.A01], [f'billing-a01-l{i:02d}' for i in range(1, 16)])
        self.assertEqual(len({x[4] for x in tool.A01}), 15)
