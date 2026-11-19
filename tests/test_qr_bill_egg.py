"""BQR5: the QR-bill on the production base (rc42): the structured address follows the choice of the EGG list (FR / BE / CH / MEA) and is COPIED into the invoice.
Synthetic data, throw-away database. Run:  python -m unittest tests.test_qr_bill_egg
"""
import io, os, sys, unittest

from tests.test_qr_bill_option import Option, m, STRUCT_ISSUER, STRUCT_CLIENT           # also sets the test environment variables
from tests.test_functional import pdf_text
from app import address_service, invoice_checks, invoice_service, qr_bill

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import seed_adresses_egg as seed          # noqa: E402

LEGAL = "CHE-000.000.001"        # the legal identity of the synthetic mandate (Cycle.mandate)
STRUCT = ("addr_street", "addr_house_num", "addr_pcode", "addr_city", "addr_country", "addr_verified")
BILL = ("bill_street", "bill_house_num", "bill_pcode", "bill_city", "bill_country", "bill_addr_verified")


class Egg(Option):
    def setUp(self):
        super().setUp()
        out = io.StringIO(); old = sys.stdout; sys.stdout = out
        try: self.assertEqual(seed.main(["--base", self.db, "--client-legal-id", LEGAL, "--appliquer", "--confirmer", seed.CONFIRM]), 0)
        finally: sys.stdout = old
        m.init()          # the application starts again: additive migration + structured split of the seeded list
        self.structure(issuer=True, client=False)

    def aid(self, label): return self.scalar("SELECT id FROM billing_addresses WHERE label=?", (label,))
    def row(self, label): return dict(self.sql("SELECT * FROM billing_addresses WHERE label=?", (label,))[0])
    def verify(self, label): self.sqlw("UPDATE billing_addresses SET addr_verified=1 WHERE label=?", (label,))
    def choose(self, iid, label):
        r = self.c.post(f"/invoice/{iid}/edit", data={"period_from": "2026-09-01", "period_to": "2026-09-30", "qty": "2", "unit": "day", "billing_address_id": str(self.aid(label)),
                                                      "revision": str(self.scalar("SELECT revision FROM invoices WHERE id=?", (iid,)))})
        self.assertEqual(r.status_code, 302); self.flashes()


class Migration(Egg):
    def test_split_of_the_three_unambiguous_addresses_and_none_for_mea_nothing_verified(self):
        fr, be, ch, mea = (self.row(x) for x in ("EGG FR", "EGG BE", "EGG CH", "EGG MEA"))
        self.assertEqual([fr[k] for k in STRUCT], ["avenue Victor Hugo", "55", "75116", "Paris", "FR", 0])
        self.assertEqual([be[k] for k in STRUCT], ["Avenue du Bourgmestre Etienne Demunter", "5, boîte 10", "1090", "JETTE", "BE", 0])
        self.assertEqual([ch[k] for k in STRUCT], ["Route de Saint Julien", "63", "1212", "Lancy", "CH", 0])
        self.assertEqual([mea[k] for k in STRUCT], ["", "", "", "", "", 0])           # nothing invented

    def test_additive_idempotent_never_overwrites_and_rollback_leaves_texts_alone(self):
        before = {r["label"]: dict(r) for r in self.sql("SELECT * FROM billing_addresses")}
        self.sqlw("UPDATE billing_addresses SET addr_street='Autre rue', addr_verified=1 WHERE label='EGG CH'")
        m.init(); m.init()
        self.assertEqual(self.row("EGG CH")["addr_street"], "Autre rue")            # a filled / verified address is never rewritten
        self.sqlw("UPDATE billing_addresses SET addr_street='Route de Saint Julien', addr_verified=0 WHERE label='EGG CH'")
        c = m.db()
        try: address_service.unmigrate(c); c.commit()
        finally: c.close()
        cols = [r[1] for r in self.sql("PRAGMA table_info(billing_addresses)")]
        for k in STRUCT: self.assertNotIn(k, cols)
        after = {r["label"]: dict(r) for r in self.sql("SELECT * FROM billing_addresses")}
        for lab, row in before.items(): self.assertEqual(after[lab], {k: v for k, v in row.items() if k not in STRUCT})      # texts, order, activity untouched
        m.init(); self.assertIn("addr_verified", [r[1] for r in self.sql("PRAGMA table_info(billing_addresses)")])           # and forward again
        self.assertEqual(self.row("EGG CH")["addr_city"], "Lancy")

    def test_invoice_snapshot_columns_are_additive_and_empty_by_default(self):
        iid = self.draft_(); row = dict(self.sql("SELECT * FROM invoices WHERE id=?", (iid,))[0])
        for k in BILL: self.assertIsNone(row[k])
        for k in BILL: self.sqlw(f"ALTER TABLE invoices DROP COLUMN {k}")
        after = dict(self.sql("SELECT * FROM invoices WHERE id=?", (iid,))[0])
        self.assertEqual(after, {k: v for k, v in row.items() if k not in BILL})
        m.init(); self.assertIn("bill_street", [r[1] for r in self.sql("PRAGMA table_info(invoices)")])


class Snapshot(Egg):
    def setUp(self):
        super().setUp(); os.environ["QR_BILL_ENABLED"] = "1"

    def test_choosing_an_address_copies_the_structured_fields_and_the_header_reads_the_copy(self):
        iid = self.draft_(); self.choose(iid, "EGG CH")
        self.assertEqual([self.sql(f"SELECT {k} FROM invoices WHERE id=?", (iid,))[0][0] for k in BILL], ["Route de Saint Julien", "63", "1212", "Lancy", "CH", 0])
        self.sqlw("UPDATE invoices SET qr_bill=1 WHERE id=?", (iid,))
        h = invoice_service.live_data(m.db(), iid)[0]
        self.assertEqual((h["client_street"], h["client_pcode"], h["client_country"], h["client_addr_verified"]), ("Route de Saint Julien", "1212", "CH", 0))
        self.sqlw("UPDATE billing_addresses SET addr_street='Rue changée', addr_verified=1 WHERE label='EGG CH'")      # editing the list does not move the copy
        h = invoice_service.live_data(m.db(), iid)[0]; self.assertEqual((h["client_street"], h["client_addr_verified"]), ("Route de Saint Julien", 0))

    def test_unverified_blocks_check_15_then_verified_and_actualised_passes_and_prints_the_slip(self):
        iid = self.draft_(); self.choose(iid, "EGG CH"); self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"})
        ck = self.checks(iid); self.assertEqual(ck[15]["status"], "fail"); self.assertIn("à confirmer", ck[15]["detail"])
        self.verify("EGG CH")
        self.assertEqual(self.checks(iid)[15]["status"], "fail")                  # the copy in the draft is unchanged until « Actualiser »
        self.c.post(f"/invoice/{iid}/edit", data={"period_from": "2026-09-01", "period_to": "2026-09-30", "qty": "2", "unit": "day", "qr_bill_present": "1", "qr_bill": "1",
                                                   "billing_address_id": str(self.aid("EGG CH")), "refresh_address": "1", "revision": str(self.scalar("SELECT revision FROM invoices WHERE id=?", (iid,)))})
        self.assertEqual(self.checks(iid)[15]["status"], "ok")
        self.assertIn("Route de Saint Julien", pdf_text(self.pdf(iid)))
        self.assertEqual(self.pages(self.pdf(iid)), self.pages(self.pdf(self.draft_())) + 1)      # one extra page for the slip

    def test_mea_has_no_structure_so_the_slip_is_refused_and_names_the_field(self):
        iid = self.draft_(); self.choose(iid, "EGG MEA"); self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"})
        ck = self.checks(iid)[15]; self.assertEqual(ck["status"], "fail"); self.assertTrue(ck["links"])
        self.assertIn("Adresses de facturation (liste)", [l for l, _ in ck["links"]])

    def test_without_choice_the_mandate_columns_are_used_as_before(self):
        iid = self.draft_(); self.structure(issuer=False, client=True); self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"})
        self.assertEqual(self.checks(iid)[15]["status"], "ok")
        h = invoice_service.live_data(m.db(), iid)[0]; self.assertEqual(h["client_street"], STRUCT_CLIENT["client_street"])

    def test_back_to_the_mandate_address_clears_the_copy(self):
        iid = self.draft_(); self.choose(iid, "EGG BE")
        self.c.post(f"/invoice/{iid}/edit", data={"period_from": "2026-09-01", "period_to": "2026-09-30", "qty": "2", "unit": "day", "billing_address_id": "",
                                                   "revision": str(self.scalar("SELECT revision FROM invoices WHERE id=?", (iid,)))})
        self.assertEqual([self.sql(f"SELECT {k} FROM invoices WHERE id=?", (iid,))[0][0] for k in BILL], [None] * 6)

    def test_issued_invoice_freezes_the_copy_and_the_slip(self):
        self.verify("EGG CH"); iid = self.draft_(); self.choose(iid, "EGG CH"); self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"})
        self.assertEqual(self.checks(iid)[15]["status"], "ok")
        self.issue(iid)
        self.sqlw("UPDATE billing_addresses SET addr_street='Rue changée' WHERE label='EGG CH'")
        self.assertIn("Route de Saint Julien", pdf_text(self.pdf(iid)))


class Admin(Egg):
    def test_list_page_edits_the_structure_and_refuses_a_bad_one(self):
        aid = self.aid("EGG CH")
        base = {"label": "EGG CH", "contact": "EGG CH SA", "address": "Route de Saint Julien 63\n1212 Lancy\nSwitzerland"}
        r = self.c.post(f"/adresses/{aid}", data={**base, "addr_street": "Route de Saint-Julien", "addr_house_num": "63", "addr_pcode": "1212", "addr_city": "Lancy", "addr_country": "ch", "addr_verified": "1"})
        self.assertEqual(r.status_code, 302); self.flashes()
        row = self.row("EGG CH"); self.assertEqual((row["addr_street"], row["addr_country"], row["addr_verified"]), ("Route de Saint-Julien", "CH", 1))
        r = self.c.post(f"/adresses/{aid}", data={**base, "addr_street": "Rue", "addr_pcode": "12 12", "addr_city": "Lancy", "addr_country": "Suisse", "addr_verified": "1"}); self.flashes()
        self.assertEqual(self.row("EGG CH")["addr_street"], "Route de Saint-Julien")      # refused, nothing saved
        r = self.c.post(f"/adresses/{aid}", data=base); self.assertEqual(r.status_code, 302)      # an older form without the fields leaves the structure alone
        self.assertEqual(self.row("EGG CH")["addr_verified"], 1)
        self.assertIn("Forme structurée", self.page("/adresses"))


class Untouched(Egg):
    def test_ordinary_invoice_has_fourteen_checks_same_keys_and_same_number(self):
        iid = self.draft_(); self.choose(iid, "EGG CH")
        self.assertEqual(sorted(self.checks(iid)), list(range(1, 15)))
        h = invoice_service.live_data(m.db(), iid)[0]
        for k in ("qr_bill", "client_street", "client_addr_verified"): self.assertNotIn(k, h)
        os.environ["QR_BILL_ENABLED"] = "1"
        try: self.assertEqual(sorted(self.checks(iid)), list(range(1, 15)))
        finally: os.environ.pop("QR_BILL_ENABLED", None)
        self.issue(iid); self.assertRegex(self.scalar("SELECT number FROM invoices WHERE id=?", (iid,)), r"^\d{4}-\d+$")


if __name__ == "__main__":
    unittest.main()
