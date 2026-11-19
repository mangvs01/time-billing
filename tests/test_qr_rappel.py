"""BQR7: pop-up at login, at most once a week, asking the owner to complete what the QR-bill needs (IBAN, structured address, clients' addresses).
Synthetic data, throw-away database (see tests.test_qr_bill_option.Option). Run:  python -m unittest tests.test_qr_rappel
"""
import os, re, unittest
from datetime import datetime, timedelta, timezone

from app import qr_bill
from tests.test_qr_bill_option import Option, VALID_IBAN, m

NOW = datetime(2026, 11, 6, 9, 0, 0)


def P(pid=1, active=1, verified=0, client="Client SA", name="Mandat"):
    return {"id": pid, "active": active, "client_addr_verified": verified, "client": client, "name": name}


FULL = {"iban": VALID_IBAN, "issuer_pcode": "1800", "issuer_city": "Vevey", "issuer_country": "CH", "issuer_street": "Rue du Lac", "issuer_house_num": "1"}


class ReminderDue(unittest.TestCase):
    def test_never_shown_or_unreadable_is_due(self):
        for v in (None, "", "pas une date", 12):
            self.assertTrue(qr_bill.reminder_due(v, NOW), v)

    def test_seven_days_is_the_threshold(self):
        self.assertFalse(qr_bill.reminder_due((NOW - timedelta(days=6, hours=23)).isoformat(), NOW))
        self.assertTrue(qr_bill.reminder_due((NOW - timedelta(days=7)).isoformat(), NOW))
        self.assertTrue(qr_bill.reminder_due((NOW - timedelta(days=30)).isoformat(), NOW))

    def test_future_value_is_due_so_a_set_back_clock_cannot_silence_it(self):
        self.assertTrue(qr_bill.reminder_due((NOW + timedelta(days=40)).isoformat(), NOW))

    def test_timezone_aware_value_is_read_as_utc(self):
        self.assertFalse(qr_bill.reminder_due(datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc).isoformat(), NOW))
        self.assertTrue(qr_bill.reminder_due(datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc).isoformat(), NOW))


class Gaps(unittest.TestCase):
    def texts(self, settings, projects=()): return [g["texte"] for g in qr_bill.setup_gaps(settings, list(projects))]

    def test_everything_in_place_means_no_gap(self):
        self.assertEqual(qr_bill.setup_gaps(FULL, [P(verified=1), P(2, active=0)]), [])

    def test_missing_iban_says_an_ordinary_swiss_iban_is_enough(self):
        g = qr_bill.setup_gaps(dict(FULL, iban=""), [])
        self.assertEqual(len(g), 1); self.assertIn("ordinaire", g[0]["texte"]); self.assertNotIn("QR-IBAN obligatoire", g[0]["texte"])

    def test_invalid_iban_gives_the_plain_message(self):
        g = qr_bill.setup_gaps(dict(FULL, iban="CH9300762011623852958"), [])
        self.assertEqual(len(g), 1); self.assertIn("clé de contrôle", g[0]["texte"])

    def test_foreign_iban_is_a_gap_unless_a_qr_iban_is_given(self):
        de = "DE89370400440532013000"
        self.assertEqual(len(qr_bill.setup_gaps(dict(FULL, iban=de), [])), 1)
        self.assertIn("DE", self.texts(dict(FULL, iban=de))[0])
        self.assertEqual(qr_bill.setup_gaps(dict(FULL, iban=de, qr_iban="CH4431999123000889012"), []), [])

    def test_a_wrong_qr_iban_is_reported_but_an_empty_one_is_not(self):
        self.assertEqual(qr_bill.setup_gaps(dict(FULL, qr_iban=""), []), [])
        g = qr_bill.setup_gaps(dict(FULL, qr_iban=VALID_IBAN), [])      # a classic IBAN typed in the QR-IBAN field
        self.assertEqual(len(g), 1); self.assertIn("QR-IBAN", g[0]["texte"])

    def test_empty_structured_address_is_one_gap_with_a_link_to_the_issuer_block(self):
        g = qr_bill.setup_gaps({"iban": VALID_IBAN}, [])
        self.assertEqual(len(g), 1); self.assertIn("champs séparés", g[0]["texte"]); self.assertIn("adresse-emetteur", g[0]["lien"])

    def test_partial_address_names_what_is_missing(self):
        g = qr_bill.setup_gaps(dict(FULL, issuer_city="", issuer_country=""), [])
        self.assertEqual(len(g), 1); self.assertIn("localité", g[0]["texte"]); self.assertIn("pays", g[0]["texte"])

    def test_only_active_unconfirmed_clients_are_listed_with_their_link(self):
        g = qr_bill.setup_gaps(FULL, [P(1, client="Alpha"), P(2, verified=1, client="Bravo"), P(3, active=0, client="Charlie"), P(4, client="", name="Delta")])
        self.assertEqual([x["lien"] for x in g], ["/project/1/edit", "/project/4/edit"])
        self.assertIn("Alpha", g[0]["texte"]); self.assertIn("Delta", g[1]["texte"])

    def test_many_clients_are_counted_not_listed_one_by_one(self):
        g = qr_bill.setup_gaps(FULL, [P(i, client=f"C{i}") for i in range(1, 8)])
        self.assertEqual(len(g), qr_bill.GAPS_MAX_CLIENTS + 1)
        self.assertIn("3 autre(s)", g[-1]["texte"])

    def test_every_gap_has_text_link_and_action(self):
        for g in qr_bill.setup_gaps({}, [P()]):
            self.assertTrue(g["texte"] and g["lien"].startswith("/") and g["action"])


class Popup(Option):
    """Through the real login and the dashboard (QR option left OFF, as in production)."""

    def relogin(self):
        self.c.post("/logout"); self.assertEqual(self.c.post("/login", data={"username": m.SEC["user"], "password": os.environ["APP_PASSWORD"]}).status_code, 302)

    def last(self):
        r = self.sql("SELECT value FROM settings WHERE key=?", (qr_bill.REMINDER_KEY,))
        return r[0][0] if r else None
    def audits(self): return self.scalar("SELECT COUNT(*) FROM audit WHERE event='qr_rappel_affiche'")

    def test_shown_on_the_first_dashboard_after_login_even_with_the_option_off(self):
        self.assertFalse(qr_bill.enabled())
        page = self.page("/")
        self.assertIn('id="qr-rappel"', page)
        self.assertIn("champs séparés", page)               # the issuer address is only a free-text block in this fixture
        self.assertIn("Client SA", page)                    # the mandate's address is not confirmed
        self.assertIn("Plus tard", page); self.assertIn("Compléter maintenant", page)
        self.assertEqual(self.audits(), 1)
        self.assertTrue(self.last())

    def test_markup_is_accessible_and_csp_friendly(self):
        page = self.page("/")
        self.assertRegex(page, r'<dialog id="qr-rappel"[^>]*aria-labelledby="qr-rappel-t"[^>]*aria-describedby="qr-rappel-d"')
        self.assertIn('id="qr-rappel-t"', page); self.assertIn('id="qr-rappel-d"', page)
        block = page[page.index('<dialog id="qr-rappel"'):]
        block = block[:block.index("</script>") + 9]
        self.assertRegex(block, r'<script nonce="[^"]+">')
        self.assertNotRegex(block, r"\son(click|load|error)=")

    def test_not_shown_again_on_the_same_login(self):
        self.assertIn('id="qr-rappel"', self.page("/"))
        self.assertNotIn('id="qr-rappel"', self.page("/"))
        self.assertNotIn('id="qr-rappel"', self.page("/?tab=settings"))
        self.assertEqual(self.audits(), 1)

    def test_not_shown_again_within_a_week_even_after_a_new_login(self):
        self.page("/")
        stamp = self.last()
        self.relogin()
        self.assertNotIn('id="qr-rappel"', self.page("/"))
        self.assertEqual(self.last(), stamp); self.assertEqual(self.audits(), 1)

    def test_shown_again_after_eight_days_and_the_date_moves_forward(self):
        self.page("/")
        old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)).isoformat(timespec="seconds")
        self.sqlw("UPDATE settings SET value=? WHERE key=?", (old, qr_bill.REMINDER_KEY))
        self.relogin()
        self.assertIn('id="qr-rappel"', self.page("/"))
        self.assertGreater(self.last(), old); self.assertEqual(self.audits(), 2)

    def test_login_on_another_page_keeps_the_reminder_for_the_next_dashboard(self):
        self.c.post("/logout")
        self.sqlw("DELETE FROM settings WHERE key=?", (qr_bill.REMINDER_KEY,))      # the login of setUp already used this week's reminder
        r = self.c.post("/login?next=/calendrier", data={"username": m.SEC["user"], "password": os.environ["APP_PASSWORD"]})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('id="qr-rappel"', self.page("/calendrier"))
        self.assertIn('id="qr-rappel"', self.page("/"))

    def test_silent_and_nothing_written_when_everything_is_in_place(self):
        self.structure()                                    # issuer + client structured addresses, client confirmed
        self.sqlw("DELETE FROM settings WHERE key=?", (qr_bill.REMINDER_KEY,))
        before = self.audits()                              # the login of setUp (before structure()) may already have logged one
        self.relogin()
        self.assertNotIn('id="qr-rappel"', self.page("/"))
        self.assertIsNone(self.last()); self.assertEqual(self.audits(), before)

    def test_comes_back_after_a_week_when_something_is_still_missing_but_not_once_complete(self):
        self.page("/")
        self.sqlw("UPDATE settings SET value='2000-01-01T00:00:00' WHERE key=?", (qr_bill.REMINDER_KEY,))
        self.structure()
        self.relogin()
        self.assertNotIn('id="qr-rappel"', self.page("/"))
        self.assertEqual(self.last(), "2000-01-01T00:00:00")  # untouched: the reminder was not shown

    def test_viewing_the_dashboard_writes_nothing(self):
        self.page("/")                                      # consumes the pop-up flag set at login
        before = (self.sql("SELECT key,value,updated_at FROM settings ORDER BY key"), self.audits(), self.scalar("SELECT COUNT(*) FROM audit"))
        for url in ("/", "/?tab=settings", "/?tab=archive"): self.page(url)
        after = (self.sql("SELECT key,value,updated_at FROM settings ORDER BY key"), self.audits(), self.scalar("SELECT COUNT(*) FROM audit"))
        self.assertEqual([tuple(r) for r in before[0]], [tuple(r) for r in after[0]]); self.assertEqual(before[1:], after[1:])

    # --- BQR8 : guide pas à pas, joignable depuis le rappel ---------------------------------------------------------------------------------------------------
    GUIDE = "/aide/qr-facture"

    def test_popup_and_settings_link_to_the_guide(self):
        page = self.page("/")
        block = page[page.index('<dialog id="qr-rappel"'):page.index("</dialog>")]
        self.assertIn(f'href="{self.GUIDE}"', block); self.assertIn("Guide pas à pas", block)
        self.assertIn(f'href="{self.GUIDE}"', self.page("/?tab=settings"))

    def test_guide_needs_a_login(self):
        r = m.APP.test_client().get(self.GUIDE)
        self.assertEqual(r.status_code, 302); self.assertIn("/login", r.headers["Location"])

    def test_guide_page_renders_and_names_the_three_steps(self):
        r = self.c.get(self.GUIDE); self.assertEqual(r.status_code, 200)
        t = r.get_data(as_text=True)
        for key in ('id="etape-iban"', 'id="etape-adresse"', 'id="etape-clients"', "IBAN suisse ordinaire", "QR-IBAN (facultatif)", "avant le 20 novembre 2026"):
            self.assertIn(key, t, key)

    def test_guide_uses_the_exact_names_of_the_real_screens(self):
        """The guide quotes menu entries, headings, fields and buttons: each must exist on the real page, so a renamed screen breaks this test instead of misleading the owner."""
        guide = self.c.get(self.GUIDE).get_data(as_text=True).replace("&amp;", "&")
        home = self.page("/").replace("&amp;", "&"); settings = self.page("/?tab=settings").replace("&amp;", "&")
        mandate = self.page(f"/project/{self.pid}/edit").replace("&amp;", "&")
        for menu in ("Paramètres & sauvegardes", "Mandats & prévisionnel"):
            self.assertIn(menu, guide); self.assertIn(menu, home, menu)
        for label in ("Paramètres de l'émetteur", "Adresse de l'émetteur en champs séparés et compte QR", "Enregistrer les paramètres", "QR-IBAN (facultatif)", "Titulaire du compte"):
            self.assertIn(label, guide, label); self.assertIn(label, settings, label)
        for label in ("adresse vérifiée (je l'ai relue : elle peut figurer sur une QR-facture)", "Code postal", "Localité"):
            self.assertIn(label, guide if label.startswith("adresse") or label in ("Code postal", "Localité") else "", label); self.assertIn(label, mandate, label)
        self.assertIn("Modifier", guide); self.assertIn('href="/project/', home)

    def test_viewing_the_guide_writes_nothing(self):
        self.page("/")
        before = ([tuple(r) for r in self.sql("SELECT key,value FROM settings ORDER BY key")], self.scalar("SELECT COUNT(*) FROM audit"))
        self.c.get(self.GUIDE); self.c.get(self.GUIDE)
        after = ([tuple(r) for r in self.sql("SELECT key,value FROM settings ORDER BY key")], self.scalar("SELECT COUNT(*) FROM audit"))
        self.assertEqual(before, after)

    def test_wrong_password_never_arms_the_reminder(self):
        self.c.post("/logout")
        self.c.post("/login", data={"username": m.SEC["user"], "password": "mauvais"})
        self.assertNotIn('id="qr-rappel"', self.page("/login"))


if __name__ == "__main__":
    unittest.main()
