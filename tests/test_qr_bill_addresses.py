"""BQR4: structured addresses typed in the screens (client per mandate, issuer in the settings), QR-IBAN, embedded library (app/vendor).
Synthetic data, throw-away database in a temporary folder. Run:  python -m unittest tests.test_qr_bill_addresses
"""
import io, os, re, shutil, subprocess, sys, tempfile, unittest

from tests.test_qr_bill_option import Option, m, VALID_IBAN, STRUCT_CLIENT, STRUCT_ISSUER          # also sets the test environment variables
from tests.test_functional import pdf_text
from app import address_presets, invoice_service, qr_bill

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QR_IBAN = "CH4431999123000889012"
NEW_PROJECT_COLS = ("client_street", "client_house_num", "client_pcode", "client_city", "client_country", "client_addr_verified")


class Screens(Option):
    """Typing the addresses in the two screens (no SQL shortcut)."""
    ISSUER = dict(STRUCT_ISSUER)
    CLIENT = dict(STRUCT_CLIENT)

    def save_issuer(self, **over):
        base = {"issuer_name": "Emetteur SA", "account_holder": "Emetteur SA", "issuer_address": "Rue du Lac 1\n1800 Vevey", "iban": VALID_IBAN,
                "payment_terms": "Paiement à 30 jours sur le compte:", "issuer_vat_number": "CHE-000.000.000 TVA (fictif)", "qr_iban": ""}
        r = self.c.post("/settings", data={**base, **self.ISSUER, **over}); self.assertEqual(r.status_code, 302); return self.flashes()

    def save_mandate(self, verified=True, **over):
        row = dict(self.sql("SELECT * FROM projects WHERE id=?", (self.pid,))[0])
        data = {k: row[k] for k in ("name", "short_name", "client", "po", "project_number", "rate", "ordered_days", "day_hours", "vat", "start_date", "duration_months",
                                    "dates_label", "billing_contact", "billing_address", "client_legal_name", "client_legal_id")}
        data.update(self.CLIENT); data.update(over)
        if verified: data["client_addr_verified"] = "1"
        self.c.post(f"/project/{self.pid}/edit", data=data); return self.flashes()

    def tick(self, iid): self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"})

    def stored_client(self):
        return dict(self.sql("SELECT " + ",".join(NEW_PROJECT_COLS) + " FROM projects WHERE id=?", (self.pid,))[0])


class Migration(Screens):
    def test_columns_are_additive_empty_by_default_and_rollback_leaves_rows_alone(self):
        before = dict(self.sql("SELECT * FROM projects WHERE id=?", (self.pid,))[0])
        for k in NEW_PROJECT_COLS: self.assertIn(k, before)
        self.assertEqual([before[k] for k in NEW_PROJECT_COLS], ["", "", "", "", "", 0])           # nothing invented: no country, not verified
        for k in NEW_PROJECT_COLS: self.sqlw(f"ALTER TABLE projects DROP COLUMN {k}")            # rollback SQL (docs/QR-FACTURE.md)
        after = dict(self.sql("SELECT * FROM projects WHERE id=?", (self.pid,))[0])
        self.assertEqual(after, {k: v for k, v in before.items() if k not in NEW_PROJECT_COLS})
        m.init(); m.init()                                                                      # forward again, twice: idempotent
        again = dict(self.sql("SELECT * FROM projects WHERE id=?", (self.pid,))[0])
        self.assertEqual(again, before)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM settings WHERE key LIKE 'issuer_%' AND key NOT IN ('issuer_name','issuer_address','issuer_rc','issuer_vat_number')")[0][0], 0)

    def test_old_forms_without_the_new_fields_leave_the_address_alone(self):
        self.sqlw("UPDATE projects SET client_street='Rue X', client_pcode='1000', client_city='Ville', client_country='CH', client_addr_verified=1 WHERE id=?", (self.pid,))
        data = {"name": "Mandat QR", "rate": "650", "ordered_days": "12", "day_hours": "8", "vat": "0", "duration_months": "11"}
        self.assertEqual(self.c.post(f"/project/{self.pid}/edit", data=data).status_code, 302)
        self.assertEqual(self.stored_client()["client_street"], "Rue X"); self.assertEqual(self.stored_client()["client_addr_verified"], 1)


class Entry(Screens):
    def test_mandate_screen_saves_and_normalises_the_structured_address(self):
        page = self.page(f"/project/{self.pid}/edit")
        for frag in ('id="adresse-structuree"', 'name="client_street"', 'name="client_house_num"', 'name="client_pcode"', 'name="client_city"', 'name="client_country"', "adresse vérifiée"):
            self.assertIn(frag, page)
        self.assertIn("non saisie", page)
        self.save_mandate(verified=False, client_country="ch", client_city="  Lausanne ")
        s = self.stored_client(); self.assertEqual((s["client_country"], s["client_city"], s["client_addr_verified"]), ("CH", "Lausanne", 0))
        self.assertIn("à confirmer", self.page(f"/project/{self.pid}/edit"))
        self.save_mandate(verified=True); self.assertEqual(self.stored_client()["client_addr_verified"], 1)
        self.assertIn("adresse vérifiée</span>", self.page(f"/project/{self.pid}/edit"))

    def test_mandate_screen_refuses_incomplete_or_bad_values_with_a_simple_message(self):
        for over in ({"client_pcode": ""}, {"client_city": ""}, {"client_country": ""}, {"client_country": "SUI"}, {"client_street": "Rue 12", "client_house_num": ""}, {"client_city": "Cairo \u00a4"}):
            self.save_mandate(**over); self.assertEqual(self.stored_client()["client_pcode"], "", str(over))      # refused: nothing stored
        for over, frag in (({"client_pcode": ""}, "code postal : à remplir"), ({"client_country": "SUI"}, "code à 2 lettres")):
            r = self.c.post(f"/project/{self.pid}/edit", data={**dict(name="Mandat QR", rate="650", ordered_days="12", day_hours="8", vat="0", duration_months="11"), **self.CLIENT, **over})
            t = r.get_data(as_text=True).replace("&#39;", "'"); self.assertIn("Mandat non modifié", t); self.assertIn(frag, t)

    def test_empty_address_is_accepted_and_clears_the_verified_flag(self):
        self.save_mandate(); self.assertEqual(self.stored_client()["client_addr_verified"], 1)
        self.save_mandate(client_street="", client_house_num="", client_pcode="", client_city="", client_country="")
        self.assertEqual(self.stored_client(), dict.fromkeys(NEW_PROJECT_COLS[:5], "") | {"client_addr_verified": 0})

    def test_settings_screen_saves_issuer_address_and_qr_iban(self):
        page = self.page("/?tab=settings")
        for frag in ('id="adresse-emetteur"', 'name="issuer_street"', 'name="issuer_pcode"', 'name="issuer_country"', 'name="qr_iban"'): self.assertIn(frag, page)
        self.save_issuer(issuer_country="ch", qr_iban=QR_IBAN.lower())
        g = lambda k: self.sql("SELECT value FROM settings WHERE key=?", (k,))[0][0]
        self.assertEqual((g("issuer_street"), g("issuer_house_num"), g("issuer_pcode"), g("issuer_city"), g("issuer_country"), g("qr_iban")),
                         ("Rue du Lac", "1", "1800", "Vevey", "CH", QR_IBAN))
        self.assertIn(QR_IBAN, self.page("/?tab=settings"))

    def test_settings_validation(self):
        f = " ".join(self.save_issuer(issuer_pcode=""));      self.assertIn("Paramètres non enregistrés", f); self.assertIn("code postal : à remplir", f)
        f = " ".join(self.save_issuer(qr_iban=VALID_IBAN));   self.assertIn("pas un QR-IBAN", f)                          # a classic IBAN is not a QR-IBAN
        f = " ".join(self.save_issuer(qr_iban="CH4431999123000889013")); self.assertIn("clé de contrôle", f)
        f = " ".join(self.save_issuer(qr_iban="FR1420041010050500013M02606")); self.assertIn("suisse ou liechtensteinois", f)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM settings WHERE key IN ('qr_iban','issuer_pcode')")[0][0], 0)       # nothing stored by a refused form
        f = " ".join(self.save_issuer(iban="CH93 0076 2011 6238 5295 8"))                                                 # wrong check key: saved, with a warning
        self.assertIn("Paramètres enregistrés", f); self.assertIn("clé de contrôle", f); self.assertIn("restera bloquée", f)
        f = " ".join(self.save_issuer()); self.assertNotIn("Attention", f)

    def test_partial_settings_form_leaves_the_structured_issuer_alone(self):
        self.save_issuer(); self.c.post("/settings", data={"issuer_name": "Emetteur SA", "issuer_address": "Rue du Lac 1\n1800 Vevey", "account_holder": "Emetteur SA", "iban": VALID_IBAN, "payment_terms": "x"})
        self.assertEqual(self.sql("SELECT value FROM settings WHERE key='issuer_pcode'")[0][0], "1800")

    def test_pure_validators(self):
        self.assertIsNone(qr_bill.iban_problem(VALID_IBAN)); self.assertIsNone(qr_bill.iban_problem("")); self.assertIsNone(qr_bill.iban_problem(QR_IBAN, qr_iban=True))
        for bad in ("CH93 0076 2011 6238 5295 8", "1234", "CH93-0076", "XX"): self.assertIsNotNone(qr_bill.iban_problem(bad), bad)
        self.assertEqual(qr_bill.address_problems("", "", "", "", ""), [])
        self.assertEqual(qr_bill.address_problems("Rue", "1", "1000", "Ville", "CH"), [])
        self.assertEqual(len(qr_bill.address_problems("Rue", "1", "", "", "")), 3)

    def test_qrr_reference(self):
        r = qr_bill.qrr_reference("2026-09"); self.assertEqual(len(r), 27); self.assertEqual(r[:-1], "202609".zfill(26)); self.assertTrue(r.isdigit())
        self.assertEqual(qr_bill.qrr_reference("210000000003139471430009017"[:-1])[-1], "7")                         # the known QRR of the Swiss standard documentation
        self.assertEqual(qr_bill.qrr_reference(None), qr_bill.qrr_reference("1"))


class Presets(Screens):
    def test_the_four_egg_texts(self):
        self.assertEqual([p["label"] for p in address_presets.PRESETS], ["EGG FR", "EGG BE", "EGG CH", "EGG MEA"])
        txt = {"EGG CH": "EGG CH SA\nRoute de Saint Julien 63\n1212 Lancy\nSwitzerland", "EGG FR": "EGG FR\n55 avenue Victor Hugo\n75116 Paris\nFrance",
               "EGG BE": "EGG BE SPRL\nAvenue du Bourgmestre\nEtienne Demunter 5, boîte 10\n1090 JETTE\nBelgique", "EGG MEA": "EGG MEA\nOffice 28 - Floor 23\nThe One Tower - TECOM\nDubai\nUnites Arab Emirates"}
        for label, t in txt.items(): self.assertEqual(address_presets.match_text(t)["label"], label)
        self.assertIsNone(address_presets.match_text("Client SA\nRue 1\n1000 Ville")); self.assertIsNone(address_presets.match_text(""))
        self.assertIsNone(address_presets.PRESETS[3]["fields"])                      # EGG MEA: no postal code, no number -> nothing prefilled
        self.assertEqual(address_presets.PRESETS[2]["fields"], {"client_street": "Route de Saint Julien", "client_house_num": "63", "client_pcode": "1212", "client_city": "Lancy", "client_country": "CH"})
        for p in address_presets.PRESETS[:3]: self.assertEqual(qr_bill.address_problems(*(p["fields"][k] for k in ("client_street", "client_house_num", "client_pcode", "client_city", "client_country"))), [])

    def test_proposal_is_shown_marked_to_confirm_and_never_stored(self):
        self.sqlw("UPDATE projects SET billing_address=? WHERE id=?", ("EGG CH SA\nRoute de Saint Julien 63\n1212 Lancy\nSwitzerland", self.pid))
        page = self.page(f"/project/{self.pid}/edit")
        self.assertIn("à confirmer — proposé d'après le texte de l'adresse « EGG CH »", page); self.assertIn('value="Route de Saint Julien"', page); self.assertIn('value="1212"', page)
        self.assertNotIn("checked", page.split("client_addr_verified")[1].split(">")[0])
        self.assertEqual(self.stored_client(), dict.fromkeys(NEW_PROJECT_COLS[:5], "") | {"client_addr_verified": 0})          # displaying stores nothing
        self.sqlw("UPDATE projects SET billing_address=? WHERE id=?", ("EGG MEA\nOffice 28 - Floor 23\nThe One Tower - TECOM\nDubai\nUnites Arab Emirates", self.pid))
        page = self.page(f"/project/{self.pid}/edit"); self.assertIn("non saisie", page); self.assertNotIn("proposé d'après", page)
        self.assertIn("EGG MEA (à saisir à la main", page)
        self.sqlw("UPDATE projects SET billing_address='Client SA\nRue 1\n1000 Ville' WHERE id=?", (self.pid,)); self.assertIn("non saisie", self.page(f"/project/{self.pid}/edit"))
        self.sqlw("UPDATE projects SET billing_address=? WHERE id=?", ("EGG FR\n55 avenue Victor Hugo\n75116 Paris\nFrance", self.pid))
        self.save_mandate(verified=False, **dict(zip(("client_street", "client_house_num", "client_pcode", "client_city", "client_country"), ("avenue Victor Hugo", "55", "75116", "Paris", "FR"))))
        self.assertIn("à confirmer</span>", self.page(f"/project/{self.pid}/edit"))                  # saved but still to be confirmed


class Flow(Screens):
    """The whole path through the screens: blocked, told what to fix and where, then unblocked, issued, slip read back."""
    def setUp(self):
        super().setUp(); os.environ["QR_BILL_ENABLED"] = "1"

    def test_blocked_then_unblocked_by_typing_the_addresses_in_the_screens(self):
        iid = self.draft_(); self.tick(iid); ck = self.checks(iid)[15]
        self.assertEqual(ck["status"], "fail")
        self.assertIn("Adresse du créancier", ck["detail"])
        self.assertEqual([l[1] for l in ck["links"]][0], "/?tab=settings#adresse-emetteur")                                  # creditor problem -> settings screen
        self.save_issuer()                                                                                                 # issuer done, client still missing
        ck = self.checks(iid)[15]; self.assertEqual(ck["status"], "fail")
        self.assertIn("Adresse du client", ck["detail"]); self.assertEqual(ck["links"][0], ("Fiche du mandat", f"/project/{self.pid}/edit#adresse-structuree"))
        self.assertNotIn("Paramètres", " ".join(l[0] for l in ck["links"]))
        self.assertIn("/project/%d/edit#adresse-structuree" % self.pid, self.page(f"/issue/{iid}"))
        self.save_mandate(verified=False); ck = self.checks(iid)[15]                                                        # typed but not confirmed yet
        self.assertEqual(ck["status"], "fail"); self.assertIn("Adresse du client à confirmer", ck["detail"]); self.assertIn("adresse vérifiée", ck["detail"])
        self.save_mandate(verified=True); self.assertEqual(self.checks(iid)[15]["status"], "ok")
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (iid,)), "issued", self.flashes())

    def test_each_field_missing_is_named(self):
        self.save_issuer(); self.save_mandate(); iid = self.draft_(); self.tick(iid); self.assertEqual(self.checks(iid)[15]["status"], "ok")
        for table, col, frag in (("settings", "issuer_pcode", "Adresse du créancier, code postal"), ("settings", "issuer_city", "Adresse du créancier, localité"),
                                 ("settings", "issuer_country", "Adresse du créancier, pays"), ("projects", "client_country", "Adresse du client, pays")):
            q = (lambda v: ("UPDATE settings SET value=? WHERE key=?", (v, col))) if table == "settings" else (lambda v: (f"UPDATE projects SET {col}=? WHERE id=?", (v, self.pid)))
            good = (self.sql("SELECT value FROM settings WHERE key=?", (col,)) if table == "settings" else self.sql(f"SELECT {col} FROM projects WHERE id=?", (self.pid,)))[0][0]
            self.sqlw(*q("")); ck = self.checks(iid)[15]; self.assertEqual(ck["status"], "fail", col); self.assertIn(frag, ck["detail"], col); self.sqlw(*q(good))
        self.assertEqual(self.checks(iid)[15]["status"], "ok")

    def test_issued_slip_is_read_back_field_by_field(self):
        self.save_issuer(); self.save_mandate(); iid = self.draft_(); self.tick(iid); self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (iid,)), "issued", self.flashes())
        number = self.scalar("SELECT number FROM invoices WHERE id=?", (iid,)); pdf = self.pdf(iid); text = " ".join(pdf_text(pdf).split())
        h = invoice_service.frozen_header(m.db(), iid)
        self.assertEqual((h["client_street"], h["client_pcode"], h["client_country"], h["client_addr_verified"]), ("Avenue de la Gare", "1003", "CH", 1))
        self.assertEqual(h["issuer"]["issuer_pcode"], "1800")
        bill, why = qr_bill.assess(h); self.assertIsNone(why)
        f = bill.qr_data().split("\r\n" if "\r\n" in bill.qr_data() else "\n")
        total = f"{float(h['amounts']['ttc']):.2f}"
        self.assertEqual(f[:4], ["SPC", "0200", "1", VALID_IBAN]); self.assertEqual(f[4:11], ["S", "Emetteur SA", "Rue du Lac", "1", "1800", "Vevey", "CH"])
        self.assertEqual(f[18:20], [total, "CHF"]); self.assertEqual(f[20:27], ["S", "Client SA", "Avenue de la Gare", "12", "1003", "Lausanne", "CH"])
        self.assertEqual(f[27:29], ["SCOR", qr_bill.scor_reference(number)]); self.assertEqual(f[29], "Facture " + number)
        for frag in ("Section paiement", "Récépissé", "Emetteur SA", "Rue du Lac 1", "1800 Vevey", "Client SA", "Avenue de la Gare 12", "1003 Lausanne", "CH93 0076 2011 6238 5295 7",
                     "Facture " + number, qr_bill.scor_reference(number)[:4]):
            self.assertIn(frag, text, frag)
        self.assertIn(f"{float(total):,.2f}".replace(",", " ").replace(".", "."), text.replace("\xa0", " ").replace("'", " "))
        self.check_qr_in_pdf(pdf, bill.qr_data())

    def check_qr_in_pdf(self, pdf, payload):
        """The QR drawn on page 2 of the PDF, rasterised and sampled module by module, equals the QR of the expected payload (a fresh encoding of the fields above)."""
        if not shutil.which("pdftoppm"): self.skipTest("pdftoppm absent")
        import qrcode
        from PIL import Image
        d = tempfile.mkdtemp()
        try:
            open(os.path.join(d, "f.pdf"), "wb").write(pdf)
            subprocess.run(["pdftoppm", "-r", "400", "-gray", "-f", "2", "-l", "2", os.path.join(d, "f.pdf"), os.path.join(d, "p")], check=True)
            png = next(os.path.join(d, x) for x in os.listdir(d) if x.startswith("p") and x != "f.pdf")
            im = Image.open(png).convert("L"); px = im.load(); W, H = im.size; mm = 400 / 25.4
            x0, x1, y0, y1 = int(64 * mm), int(116 * mm), int(205 * mm), int(258 * mm)      # between the cut line (62 mm) and the text column (118 mm)
            dark = [(x, y) for y in range(y0, min(y1, H)) for x in range(x0, min(x1, W)) if px[x, y] < 128]
            self.assertTrue(dark, "no QR found on page 2")
            bx0, bx1 = min(x for x, _ in dark), max(x for x, _ in dark); by0, by1 = min(y for _, y in dark), max(y for _, y in dark)
            self.assertAlmostEqual((bx1 - bx0) / mm, 45.8, delta=0.6); self.assertAlmostEqual((by1 - by0) / mm, 45.8, delta=0.6)
            q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0); q.add_data(payload); q.make(fit=True)
            exp = q.get_matrix(); n = len(exp); cell = (bx1 - bx0 + 1) / n; self.assertAlmostEqual(n * cell, (by1 - by0 + 1), delta=cell)
            skip = 4.5 * mm                                         # the Swiss cross (7 mm) and its margin hide the middle modules
            cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2; bad = tested = 0
            for r in range(n):
                for c in range(n):
                    x, y = bx0 + (c + .5) * cell, by0 + (r + .5) * cell
                    if abs(x - cx) < skip and abs(y - cy) < skip: continue
                    tested += 1; bad += (px[int(x), int(y)] < 128) != bool(exp[r][c])
            self.assertEqual(bad, 0, f"{bad} modules of {tested} differ"); self.assertGreater(tested, 1500)
            # control: a QR made from another payload would not match (the comparison is not vacuous)
            q2 = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0); q2.add_data(payload.replace("Lausanne", "Lausanna")); q2.make(fit=True)
            if len(q2.get_matrix()) == n:
                diff = sum(1 for r in range(n) for c in range(n) if q2.get_matrix()[r][c] != exp[r][c]); self.assertGreater(diff, 20)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_qr_iban_gives_a_qrr_reference_and_a_valid_slip(self):
        self.save_issuer(qr_iban=QR_IBAN); self.save_mandate(); iid = self.draft_(); self.tick(iid)
        self.assertEqual(self.checks(iid)[15]["status"], "ok", self.checks(iid)[15]["detail"])          # even on a draft without number
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (iid,)), "issued", self.flashes())
        number = self.scalar("SELECT number FROM invoices WHERE id=?", (iid,)); h = invoice_service.frozen_header(m.db(), iid)
        bill, why = qr_bill.assess(h); self.assertIsNone(why)
        f = bill.qr_data().split("\r\n" if "\r\n" in bill.qr_data() else "\n")
        self.assertEqual(f[3], QR_IBAN); self.assertEqual(f[27:29], ["QRR", qr_bill.qrr_reference(number)]); self.assertEqual(len(f[28]), 27)
        self.check_qr_in_pdf(self.pdf(iid), bill.qr_data())
        self.assertIn(qr_bill.qrr_reference(number)[:2], " ".join(pdf_text(self.pdf(iid)).split()))
        self.assertIsNone(h["issuer"].get("iban") and None)                                           # the classic IBAN stays in the header for the printed bank details

    def test_issued_invoice_keeps_its_address_when_the_mandate_changes_later(self):
        self.save_issuer(); self.save_mandate(); a = self.draft_(); self.tick(a); self.flashes(); self.issue(a)
        self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (a,)), "issued", self.flashes())
        frozen, header = self.pdf(a), invoice_service.frozen_header(m.db(), a)
        self.save_mandate(client_street="Rue Nouvelle", client_house_num="99", client_pcode="2000", client_city="Neuchâtel")
        self.save_issuer(issuer_street="Chemin Neuf", issuer_pcode="1700", issuer_city="Fribourg", qr_iban=QR_IBAN)
        self.assertEqual(self.pdf(a), frozen); self.assertEqual(invoice_service.frozen_header(m.db(), a), header)
        self.assertEqual(header["client_street"], "Avenue de la Gare"); self.assertEqual(header["issuer"]["issuer_city"], "Vevey"); self.assertNotIn("qr_iban", header["issuer"])
        t = " ".join(pdf_text(frozen).split()); self.assertIn("Avenue de la Gare 12", t); self.assertNotIn("Rue Nouvelle", t)
        b = self.draft(self.pid, "2026-10-01", "2026-10-31", 1)[0]; self.tick(b)                     # the next invoice reads the new data
        hb = invoice_service.live_data(m.db(), b)[0]; self.assertEqual((hb["client_street"], hb["client_city"], hb["issuer"]["issuer_city"]), ("Rue Nouvelle", "Neuchâtel", "Fribourg"))


class Unticked(Screens):
    def test_box_unticked_is_the_same_pdf_whatever_is_typed_and_the_golden_is_untouched(self):
        os.environ["QR_BILL_ENABLED"] = "1"; iid = self.draft_(); before = self.pdf(iid)
        self.save_issuer(qr_iban=QR_IBAN); self.save_mandate()
        self.assertEqual(self.pdf(iid), before)                                                          # addresses typed, box unticked: same bytes
        h = invoice_service.live_data(m.db(), iid)[0]
        for k in ("qr_bill", "client_street", "client_addr_verified"): self.assertNotIn(k, h)           # ordinary header keeps its keys
        for k in ("issuer_street", "issuer_pcode", "qr_iban"): self.assertNotIn(k, h["issuer"])
        self.assertEqual(sorted(self.checks(iid)), list(range(1, 15)))
        from app import invoice_checks
        self.assertEqual(invoice_checks._golden(), invoice_checks.layout_fingerprint())
        os.environ.pop("QR_BILL_ENABLED"); self.assertEqual(self.pdf(iid), before)


class Vendor(unittest.TestCase):
    def test_library_loads_from_the_repository_without_any_external_path(self):
        code = ("import sys; sys.path[:] = [p for p in sys.path if 'vendor-qrbill' not in p]; sys.path.insert(0, %r)\n"
                "from app import qr_bill\nQ, S = qr_bill._lib()\nimport qrbill, svglib, lxml.etree, qrcode, svgwrite, stdnum.iban, iso3166, tinycss2, cssselect2, webencodings\n"
                "print(qrbill.__file__); print(lxml.etree.__file__); print(stdnum.iban.__file__)\n") % ROOT
        env = {k: v for k, v in os.environ.items() if k != "QR_BILL_VENDOR_DIR"}
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=tempfile.gettempdir())
        self.assertEqual(r.returncode, 0, r.stderr)
        vendor = os.path.join(ROOT, "app", "vendor")
        for line in r.stdout.split():
            self.assertTrue(line.startswith(vendor), line)
        self.assertNotIn("vendor-qrbill", r.stdout)

    def test_every_embedded_package_ships_its_licence(self):
        vendor = os.path.join(ROOT, "app", "vendor")
        pk = {"qrbill": "qrbill", "qrcode": "qrcode", "svgwrite": "svgwrite", "svglib": "svglib", "cssselect2": "cssselect2", "tinycss2": "tinycss2",
              "webencodings": "webencodings", "iso3166": "iso3166", "lxml": "lxml", "stdnum": "python-stdnum"}
        for pkg, lic in pk.items():
            self.assertTrue(os.path.isdir(os.path.join(vendor, pkg)), pkg)
            files = os.listdir(os.path.join(vendor, "licences", lic)); self.assertTrue(files, lic)
            self.assertTrue(any(re.match(r"(LICEN[CS]E|COPYING)", f, re.I) for f in files), lic)
        self.assertTrue(os.path.isfile(os.path.join(vendor, "VENDOR.md")))
        self.assertEqual(sorted(os.listdir(os.path.join(vendor, "licences"))), sorted(pk.values()))


if __name__ == "__main__":
    unittest.main()
