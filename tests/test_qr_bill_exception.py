"""BQR6 (owner decision 04/11): check 15 (QR-bill requested) BLOCKS the issuance even on an exception mandate (« STC GEM* »): the box was ticked on purpose,
the way out is to correct the missing piece or to untick. Checks 1 to 14 keep the rc41 behaviour (warning only). Synthetic data, throw-away database. Run:
python -I outils/run_tests_isolated.py tests.test_qr_bill_exception
"""
import os, unittest

from tests.test_qr_bill_option import Option, m
from tests.test_functional import pdf_text
from app import invoice_checks, invoice_service


class ExceptionMandate(Option):
    def setUp(self):
        super().setUp(); os.environ["QR_BILL_ENABLED"] = "1"
        self._exc = os.environ.pop("BILLING_EXCEPTION_MANDATES", None)       # the default setting: « STC GEM* »
        self.sqlw("UPDATE projects SET name='STC GEM Novembre' WHERE id=?", (self.pid,))

    def tearDown(self):
        os.environ.pop("BILLING_EXCEPTION_MANDATES", None)
        if self._exc is not None: os.environ["BILLING_EXCEPTION_MANDATES"] = self._exc
        super().tearDown()

    def tick(self, iid): self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"})
    def status(self, iid): return self.scalar("SELECT status FROM invoices WHERE id=?", (iid,))
    def over(self):        # 3 j billed, 2 j worked: checks 12 and 14 would fail on an ordinary mandate
        self.record_work(self.pid, "2026-09-01", "2026-09-30", 2, "day"); self.RECORD_WORK = False
        try: return self.draft(self.pid, "2026-09-01", "2026-09-30", 3)[0]
        finally: self.RECORD_WORK = True

    def test_ticked_with_the_client_address_not_verified_blocks_on_stc_gem(self):
        self.structure(issuer=True, client=False)
        iid = self.draft_(); self.tick(iid); ck = self.checks(iid)
        self.assertIsNotNone(m.rules.exception_mandate(self.sql("SELECT * FROM projects WHERE id=?", (self.pid,))[0]))
        self.assertEqual((ck[15]["status"], ck[15]["derogable"]), ("fail", False))
        self.assertNotIn("would_fail", ck[15]); self.assertNotIn("exception", ck[15])
        self.assertIn("Adresse du client", ck[15]["detail"]); self.assertIn("décocher", ck[15]["detail"]); self.assertTrue(ck[15]["links"])
        self.assertEqual([c["n"] for c in invoice_checks.blocking(invoice_checks.run_checks(m.db(), iid))], [15])
        page = self.page(f"/issue/{iid}")
        self.assertIn("Émission impossible", page); self.assertIn('id="chk15"', page); self.assertNotIn('name="derogation_', page)
        self.assertRegex(page, r"<button disabled>Émettre")
        self.flashes(); self.issue(iid); self.assertEqual(self.status(iid), "draft")
        self.assertIn("15.", " ".join(self.flashes()))
        self.issue(iid, derogate=(15,)); self.assertEqual(self.status(iid), "draft")                  # no reason overrides it
        self.tick(iid); self.c.post(f"/invoice/{iid}/qr-bill", data={})                             # the way out: untick
        self.flashes(); self.issue(iid); self.assertEqual(self.status(iid), "issued", self.flashes())

    def test_other_checks_stay_warnings_while_15_blocks(self):
        self.structure(issuer=True, client=False)
        iid = self.over(); self.tick(iid); ck = self.checks(iid)
        for n in (12, 14): self.assertEqual((ck[n]["status"], ck[n]["would_fail"]), ("warning", True), n)
        self.assertEqual(ck[15]["status"], "fail")
        page = self.page(f"/issue/{iid}"); self.assertIn("Émission impossible", page); self.assertIn('id="chk12"', page)
        self.assertIn("ÉCART · STC GEM* (non bloquant)", page)
        self.flashes(); self.issue(iid); self.assertEqual(self.status(iid), "draft")

    def test_unticked_keeps_every_rc41_warning_and_issues_without_reason(self):
        self.structure(issuer=True, client=False)
        iid = self.over(); ck = self.checks(iid)
        self.assertEqual(sorted(ck), list(range(1, 15)))
        self.assertEqual(sorted(n for n, x in ck.items() if x.get("would_fail")), [12, 14])
        self.assertEqual(invoice_checks.blocking(invoice_checks.run_checks(m.db(), iid)), [])
        self.assertRegex(self.page(f"/issue/{iid}"), r"<button\s*>Émettre")
        self.flashes(); self.issue(iid, derogate=()); self.assertEqual(self.status(iid), "issued", self.flashes())
        self.assertEqual(self.scalar("SELECT qr_bill FROM invoices WHERE id=?", (iid,)), 0)

    def test_ticked_and_complete_issues_with_the_slip_page(self):
        self.structure(); iid = self.draft_(); plain = self.pages(self.pdf(iid)); self.tick(iid)
        ck = self.checks(iid); self.assertEqual(ck[15]["status"], "ok"); self.assertEqual(invoice_checks.blocking(invoice_checks.run_checks(m.db(), iid)), [])
        self.flashes(); self.issue(iid); self.assertEqual(self.status(iid), "issued", self.flashes())
        issued = self.pdf(iid); self.assertIn("Section paiement", " ".join(pdf_text(issued).split())); self.assertEqual(self.pages(issued), plain + 1)

    def test_ordinary_mandate_keeps_its_behaviour(self):
        self.sqlw("UPDATE projects SET name='Mandat ordinaire' WHERE id=?", (self.pid,))
        self.structure(issuer=True, client=False)
        iid = self.over(); ck = self.checks(iid)
        self.assertEqual(sorted(n for n, x in ck.items() if x["status"] == "fail"), [12, 14])           # still failing, not warnings
        self.assertFalse(any(x.get("would_fail") for x in ck.values()))
        self.tick(iid); ck = self.checks(iid)
        self.assertEqual((ck[15]["status"], ck[15]["derogable"]), ("fail", False))
        self.flashes(); self.issue(iid); self.assertEqual(self.status(iid), "draft")

    def test_issued_invoice_is_unchanged(self):
        self.structure(); a = self.draft_(); self.tick(a); self.flashes(); self.issue(a)
        self.assertEqual(self.status(a), "issued", self.flashes())
        frozen = self.pdf(a); self.assertEqual(invoice_checks.run_checks(m.db(), a), [])
        self.sqlw("UPDATE projects SET client_addr_verified=0"); self.sqlw("UPDATE settings SET value='CH0000000000000000000' WHERE key='iban'")
        self.assertEqual(self.pdf(a), frozen); self.assertEqual(invoice_checks.run_checks(m.db(), a), [])
        self.assertEqual(invoice_service.frozen_header(m.db(), a)["qr_bill"], 1)


if __name__ == "__main__":
    unittest.main()
