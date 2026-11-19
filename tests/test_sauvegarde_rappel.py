"""BSAV1: the permanent « Sauvegarde conseillée » line is gone from « À traiter »; a pop-up at login, at most once per calendar month, replaces it
(only when issued documents exist and the last JSON backup is missing or older than 30 days). Same mechanism as the QR-bill reminder (BQR7).
Synthetic data, throw-away database (see tests.test_qr_bill_option.Option). Run:  python -m unittest tests.test_sauvegarde_rappel
"""
import os, unittest
from datetime import datetime, timedelta, timezone

from app import sauvegarde_rappel as sv
from tests.test_qr_bill_option import Option, m

NOW = datetime(2026, 11, 19, 9, 0, 0)


class Helpers(unittest.TestCase):
    def test_stale_when_never_downloaded_or_unreadable(self):
        for v in (None, "", "pas une date", 12): self.assertTrue(sv.backup_stale(v, NOW), v)

    def test_thirty_days_is_the_threshold(self):
        self.assertFalse(sv.backup_stale((NOW - timedelta(days=29, hours=23)).isoformat(), NOW))
        self.assertTrue(sv.backup_stale((NOW - timedelta(days=30)).isoformat(), NOW))
        self.assertFalse(sv.backup_stale("2026-11-10 08:00:00", NOW))            # audit format (space separator)

    def test_due_once_per_calendar_month(self):
        self.assertTrue(sv.reminder_due(None, NOW)); self.assertTrue(sv.reminder_due("nope", NOW))
        self.assertFalse(sv.reminder_due("2026-11-01T00:00:00", NOW)); self.assertFalse(sv.reminder_due("2026-11-18T23:59:59", NOW))
        self.assertTrue(sv.reminder_due("2026-10-31T23:59:59", NOW))              # the month changed, even one second later
        self.assertTrue(sv.reminder_due("2025-11-19T09:00:00", NOW))              # same month number, other year
        self.assertTrue(sv.reminder_due("2027-03-01T00:00:00", NOW))              # future value (clock set back) cannot silence it

    def test_timezone_aware_value_is_read_as_utc(self):
        self.assertFalse(sv.reminder_due(datetime(2026, 11, 2, tzinfo=timezone.utc).isoformat(), NOW))


class Popup(Option):
    ID = 'id="sv-rappel"'

    DOCS = True

    def setUp(self):
        super().setUp()
        if self.DOCS: self.sqlw("INSERT INTO invoices(number,project_id,period_from,period_to,qty,unit,unit_rate,status,issued_at) VALUES('2026-001',?,'2026-09-01','2026-09-30',1,'day',650,'issued','2026-10-01T10:00:00')", (self.pid,))
        self.sqlw("DELETE FROM settings WHERE key=?", (sv.REMINDER_KEY,))

    def relogin(self):
        self.c.post("/logout"); self.assertEqual(self.c.post("/login", data={"username": m.SEC["user"], "password": os.environ["APP_PASSWORD"]}).status_code, 302)
    def last(self):
        r = self.sql("SELECT value FROM settings WHERE key=?", (sv.REMINDER_KEY,)); return r[0][0] if r else None
    def audits(self): return self.scalar("SELECT COUNT(*) FROM audit WHERE event='sauvegarde_rappel_affiche'")
    def backed_up(self, days):
        when = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)).isoformat(sep=" ", timespec="seconds")
        self.sqlw("INSERT INTO audit(event,detail,created_at) VALUES('json_backup_exported','x',?)", (when,))

    def test_shown_when_no_backup_ever_with_the_texts_and_two_buttons(self):
        self.relogin(); page = self.page("/")
        self.assertIn(self.ID, page)
        self.assertIn("Vous n'avez pas encore téléchargé de sauvegarde", page)
        self.assertIn("copie de toutes vos factures, de vos clients et de vos PDF", page); self.assertIn("clé USB", page)
        self.assertIn("Télécharger la sauvegarde maintenant", page); self.assertIn("Plus tard", page)
        self.assertIn('href="/?tab=settings#sauvegarde"', page[page.index(self.ID):])
        self.assertEqual(self.audits(), 1); self.assertTrue(self.last())

    def test_shown_when_last_backup_is_older_than_thirty_days(self):
        self.backed_up(45); self.relogin(); page = self.page("/")
        self.assertIn(self.ID, page); self.assertIn("plus de 30 jours", page)

    def test_not_shown_when_the_backup_is_recent_and_nothing_is_written(self):
        self.backed_up(5); self.relogin()
        self.assertNotIn(self.ID, self.page("/")); self.assertIsNone(self.last()); self.assertEqual(self.audits(), 0)

    def test_only_once_per_login_and_not_again_the_same_month(self):
        self.relogin()
        self.assertIn(self.ID, self.page("/")); self.assertNotIn(self.ID, self.page("/")); self.assertNotIn(self.ID, self.page("/?tab=settings"))
        stamp = self.last(); self.relogin()                              # « Plus tard » is remembered: a new login the same month stays quiet
        self.assertNotIn(self.ID, self.page("/")); self.assertEqual(self.last(), stamp); self.assertEqual(self.audits(), 1)

    def test_comes_back_the_next_month_and_the_date_moves_forward(self):
        self.relogin(); self.page("/")
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=40)).isoformat(timespec="seconds")
        self.sqlw("UPDATE settings SET value=? WHERE key=?", (old, sv.REMINDER_KEY)); self.relogin()
        self.assertIn(self.ID, self.page("/")); self.assertGreater(self.last(), old); self.assertEqual(self.audits(), 2)

    def test_stops_once_a_backup_is_downloaded(self):
        self.relogin(); self.assertIn(self.ID, self.page("/"))
        self.c.get("/backup")
        self.sqlw("UPDATE settings SET value='2000-01-01T00:00:00' WHERE key=?", (sv.REMINDER_KEY,)); self.relogin()
        self.assertNotIn(self.ID, self.page("/"))

    def test_the_qr_popup_goes_first_and_this_one_waits_for_the_next_login(self):
        self.sqlw("DELETE FROM settings WHERE key='qr_rappel_dernier'"); self.relogin()
        page = self.page("/"); self.assertIn('id="qr-rappel"', page); self.assertNotIn(self.ID, page); self.assertIsNone(self.last())
        self.relogin(); self.assertIn(self.ID, self.page("/"))

    def test_dashboard_todo_no_longer_has_the_advice_line(self):
        self.relogin(); page = self.page("/")
        self.assertNotIn("Sauvegarde conseillée", page); self.assertNotIn('data-todo="backup"', page)
        self.assertNotIn("aucune sauvegarde JSON n'a été téléchargée", page)
        self.page("/"); self.assertNotIn("Sauvegarde conseillée", self.page("/"))

    def test_markup_is_accessible_and_csp_friendly(self):
        self.relogin(); page = self.page("/")
        self.assertRegex(page, r'<dialog id="sv-rappel"[^>]*aria-labelledby="sv-rappel-t"[^>]*aria-describedby="sv-rappel-d"')
        block = page[page.index('<dialog id="sv-rappel"'):]; block = block[:block.index("</script>") + 9]
        self.assertRegex(block, r'<script nonce="[^"]+">'); self.assertNotRegex(block, r"\son(click|load|error)=")

    def test_viewing_the_dashboard_writes_nothing_and_wrong_password_never_arms_it(self):
        self.relogin(); self.page("/")
        before = (self.sql("SELECT key,value FROM settings ORDER BY key"), self.scalar("SELECT COUNT(*) FROM audit"))
        for u in ("/", "/?tab=settings", "/?tab=archive"): self.page(u)
        self.assertEqual(([tuple(r) for r in before[0]], before[1]), ([tuple(r) for r in self.sql("SELECT key,value FROM settings ORDER BY key")], self.scalar("SELECT COUNT(*) FROM audit")))
        self.c.post("/logout"); self.sqlw("DELETE FROM settings WHERE key=?", (sv.REMINDER_KEY,))
        self.c.post("/login", data={"username": m.SEC["user"], "password": "mauvais"})
        self.assertNotIn(self.ID, self.page("/login"))


class NoDocuments(Popup):
    DOCS = False

    def test_not_shown_without_issued_documents(self):
        self.relogin(); self.assertNotIn(self.ID, self.page("/")); self.assertIsNone(self.last()); self.assertEqual(self.audits(), 0)

    # nothing to save: none of the inherited scenarios applies
    for _n in [n for n in dir(Popup) if n.startswith("test_") and n != "test_not_shown_without_issued_documents"]: locals()[_n] = None
    del _n


if __name__ == "__main__":
    unittest.main()
