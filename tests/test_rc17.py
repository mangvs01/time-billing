"""V9.2-rc17 (shipped as rc18 after a JS syntax fix in the time form): a time entry may run past midnight (decision C5, 2026-10-05): ONE entry, duration computed across midnight
(22:00 -> 02:00 = 4 h), kept on its start day, never split. Synthetic data only, on a COPY of the staging database."""
import html, re

import app.app as m
from tests._app_facts import declared_version
from tests.test_functional import pdf_text
from tests.test_rc10 import EntryCase


def clock(c, pid, d, s, e, desc='nuit'): return c.post('/entry', data={'work_date': d, 'project_id': str(pid), 'entry_mode': 'clock', 'start_time': s, 'end_time': e, 'description': desc})


class MidnightEntry(EntryCase):
    def row(self, desc): return self.sql('SELECT * FROM entries WHERE description=?', (desc,))

    def test_22_to_02_is_one_entry_of_4_hours_on_the_start_day(self):
        self.flashes(); r = clock(self.c, self.pid, '2026-08-12', '22:00', '02:00')
        self.assertEqual(r.status_code, 302)
        rows = self.row('nuit'); self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['work_date'], rows[0]['start_time'], rows[0]['end_time'], rows[0]['hours']), ('2026-08-12', '22:00', '02:00', 4.0))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE work_date='2026-08-13'"), 0, 'no second row on the next day')
        fl = ' '.join(self.flashes())
        self.assertIn('passant minuit', fl); self.assertIn('4 h', fl); self.assertIn('Temps enregistré', fl)
        self.assertNotIn('Saisie refusée', fl)

    def test_durations_across_midnight(self):
        for i, (s, e, h) in enumerate([('23:00', '01:00', 2.0), ('22:00', '00:00', 2.0), ('23:59', '00:00', 1 / 60), ('18:30', '06:15', 11.75), ('12:00', '11:59', 23 + 59 / 60), ('00:01', '00:00', 23 + 59 / 60)]):
            clock(self.c, self.pid, f'2026-08-{10 + i:02d}', s, e, desc=f'n{i}')
            r = self.row(f'n{i}'); self.assertEqual(len(r), 1, (s, e)); self.assertAlmostEqual(r[0]['hours'], h, 9, (s, e)); self.assertEqual(r[0]['work_date'], f'2026-08-{10 + i:02d}')

    def test_same_day_entries_are_unchanged(self):
        clock(self.c, self.pid, '2026-08-12', '08:30', '12:15', 'jour')
        r = self.row('jour')[0]; self.assertEqual((r['start_time'], r['end_time'], r['hours']), ('08:30', '12:15', 3.75))
        self.assertNotIn('passant minuit', ' '.join(self.flashes()))

    def test_end_equal_to_start_is_still_refused(self):
        self.flashes(); n = self.scalar('SELECT COUNT(*) FROM entries')
        clock(self.c, self.pid, '2026-08-12', '10:00', '10:00', 'zero')
        self.assertIn('identique', ' '.join(self.flashes())); self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), n)

    def test_bad_formats_still_refused(self):
        n = self.scalar('SELECT COUNT(*) FROM entries')
        for s, e in (('24:00', '02:00'), ('22:00', '25:00'), ('22:7', '02:00'), ('', '02:00'), ('22:00', '')):
            clock(self.c, self.pid, '2026-08-12', s, e, 'bad')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries'), n)

    def test_month_end_night_stays_in_the_start_month(self):
        clock(self.c, self.pid, '2026-09-30', '22:00', '02:00')
        self.assertEqual(self.scalar("SELECT ROUND(SUM(hours),2) FROM entries WHERE work_date BETWEEN '2026-09-01' AND '2026-09-30'"), 4.0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE work_date BETWEEN '2026-10-01' AND '2026-10-31'"), 0)
        s, js = self.suggest(self.pid, '2026-09-01', '2026-09-30'); self.assertEqual(s, 200)
        self.assertIn('4', html.unescape(str(js)))
        s2, js2 = self.suggest(self.pid, '2026-10-01', '2026-10-31')
        self.assertNotIn("'hours': 4", str(js2))

    def test_invoice_annex_prints_the_single_row(self):
        clock(self.c, self.pid, '2026-09-30', '22:00', '02:00', 'annexe')
        iid, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 0.5)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM invoices WHERE id=?', (iid,)), 1, fl)
        t = pdf_text(self.c.get(f'/invoice/{iid}.pdf').data)
        for needle in ('22,00', '2,00', '4,00'): self.assertIn(needle, t)

    def test_overlap_across_midnight_is_flagged(self):
        clock(self.c, self.pid, '2026-08-12', '22:00', '02:00', 'veille'); self.flashes()
        clock(self.c, self.pid, '2026-08-13', '01:00', '03:00', 'matin')                       # 01:00-02:00 shared with the previous night
        self.assertIn('chevauche', ' '.join(self.flashes()))
        clock(self.c, self.pid, '2026-08-15', '22:00', '02:00', 'veille2'); self.flashes()
        clock(self.c, self.pid, '2026-08-16', '02:00', '03:00', 'apres')                       # starts exactly when the night ends
        self.assertNotIn('chevauche', ' '.join(self.flashes()))
        clock(self.c, self.pid2, '2026-08-11', '23:00', '23:59', 'avant'); self.assertNotIn('chevauche', ' '.join(self.flashes()))
        clock(self.c, self.pid, '2026-08-11', '23:30', '00:30', 'nuit2')                       # 23:30 -> 00:30 vs 'avant' 23:00-23:59 : overlap
        self.assertIn('chevauche', ' '.join(self.flashes()))
        clock(self.c, self.pid, '2026-08-20', '21:00', '23:00', 'a'); self.flashes()
        clock(self.c, self.pid, '2026-08-20', '22:00', '01:00', 'b')                           # same-day overlap with a night entry
        self.assertIn('chevauche', ' '.join(self.flashes()))

    def test_daily_total_is_attributed_to_the_start_day(self):
        self.entry(self.pid, '2026-08-12', 6); self.flashes()
        clock(self.c, self.pid, '2026-08-12', '20:00', '04:00', 'longue')                       # 8 h -> 14 h on the 12th
        fl = ' '.join(self.flashes()); self.assertIn('plus de 12 h', fl); self.assertIn('12.08.2026', fl)
        self.assertEqual(self.scalar("SELECT COALESCE(SUM(hours),0) FROM entries WHERE work_date='2026-08-13'"), 0)

    def test_dst_night_keeps_wall_clock_but_warns(self):
        clock(self.c, self.pid, '2026-10-24', '22:00', '04:00', 'automne')                      # clocks go back on 25.10.2026 at 03:00
        r = self.row('automne')[0]; self.assertEqual(r['hours'], 6.0)
        fl = ' '.join(self.flashes()); self.assertIn('changement d\'heure', fl); self.assertIn('7 h', fl)
        clock(self.c, self.pid, '2026-03-28', '23:00', '04:00', 'printemps')                    # clocks go forward on 29.03.2026 at 02:00
        self.assertEqual(self.row('printemps')[0]['hours'], 5.0); self.assertIn('changement d\'heure', ' '.join(self.flashes()))
        clock(self.c, self.pid, '2026-08-12', '22:00', '02:00', 'ete'); self.assertNotIn('changement d\'heure', ' '.join(self.flashes()))

    def test_correction_to_a_midnight_entry_keeps_history_and_one_row(self):
        clock(self.c, self.pid, '2026-08-12', '20:00', '22:00', 'corr'); e = self.eid('corr')
        r, fl = self.edit(e, entry_mode='clock', start_time='22:00', end_time='02:00')
        row = self.sql('SELECT * FROM entries WHERE id=?', (e,))[0]
        self.assertEqual((row['start_time'], row['end_time'], row['hours'], row['work_date']), ('22:00', '02:00', 4.0, '2026-08-12'), fl)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM entries WHERE description=?', ('corr',)), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entry_changes WHERE entry_id=? AND action='update'", (e,)), 1)
        self.assertIn('passant minuit', ' '.join(fl) if isinstance(fl, list) else str(fl))

    def test_list_marks_the_next_day_end_and_csv_keeps_the_times(self):
        clock(self.c, self.pid, '2026-08-12', '22:00', '02:00', 'listee')
        page = html.unescape(self.c.get('/entries?q=listee').get_data(as_text=True))
        self.assertIn('22:00 – 02:00', page); self.assertIn('(+1 j)', page)
        r = self.c.get('/entries.csv'); self.assertEqual(r.status_code, 200)
        line = [l for l in r.get_data(as_text=True).splitlines() if 'listee' in l]
        self.assertEqual(len(line), 1); self.assertIn('22:00', line[0]); self.assertIn('02:00', line[0]); self.assertIn('4', line[0])

    def test_forms_compute_the_duration_across_midnight(self):
        for url in ('/', f'/entry/{(clock(self.c, self.pid, "2026-08-12", "20:00", "21:00", "js"), self.eid("js"))[1]}/edit'):
            t = self.c.get(url).get_data(as_text=True)
            self.assertIn('+=1440', t); self.assertIn('minuit', t)

    def test_totals_and_mandate_hours_use_the_computed_duration(self):
        clock(self.c, self.pid, '2026-08-12', '22:00', '02:00')
        self.assertEqual(self.scalar('SELECT SUM(hours) FROM entries WHERE project_id=?', (self.pid,)), 4.0)
        p = html.unescape(re.sub(r'<[^>]+>', ' ', self.c.get('/?tab=mandates').get_data(as_text=True)))
        self.assertIn('4,00', p)

    def test_version(self):
        self.assertEqual(m.VERSION, declared_version())
