"""BQR9: two numbered invoices never share the same payment reference (QRR with a QR-IBAN, SCOR otherwise).
Run:  python -m unittest tests.test_qr_reference_unique
"""
import os, unittest
import tests.test_qr_bill_option as base
from app import billing_rules as rules, invoice_service, qr_bill
import app.app as m

QR_IBAN = "CH4431999123000889012"
MSG = "Ce numéro donnerait la même référence de paiement que la facture {} : choisissez un autre numéro"


class Pure(unittest.TestCase):
    def test_single_rule_both_modes(self):
        self.assertEqual(qr_bill.payment_reference("2026-09"), qr_bill.scor_reference("2026-09"))
        self.assertEqual(qr_bill.payment_reference("2026-09", QR_IBAN), qr_bill.qrr_reference("2026-09"))
        self.assertIsNone(qr_bill.payment_reference(None)); self.assertIsNone(qr_bill.payment_reference(""))
        self.assertEqual(qr_bill.payment_reference("", QR_IBAN), qr_bill.qrr_reference(""))       # draft in QRR mode: provisional, as before

    def test_non_regression_of_existing_references(self):
        self.assertEqual(qr_bill.payment_reference("2026-09"), "RF70202609")
        self.assertEqual(qr_bill.payment_reference("2026-09", QR_IBAN), "000000000000000000002026090")

    def test_clashes_both_modes(self):
        for qr in ("", QR_IBAN):
            self.assertEqual(qr_bill.reference_clash("2026-10-1", ["2026-101"], qr), "2026-101")
            self.assertEqual(qr_bill.reference_clash("2026-1-1", ["2026-11"], qr), "2026-11")
            self.assertEqual(qr_bill.reference_clash("2026-11", ["2026-1-1"], qr), "2026-1-1")

    def test_no_false_positive(self):
        for qr in ("", QR_IBAN):
            self.assertIsNone(qr_bill.reference_clash("2026-09", ["2026-9"], qr))      # same number: not a second one
            self.assertIsNone(qr_bill.reference_clash("2026-09", ["2026-09"], qr))
            self.assertIsNone(qr_bill.reference_clash("2026-09", [None, "", "2025-09"], qr))
            serie = [f"2026-{n:02d}" for n in range(1, 100)]
            for n in serie: self.assertIsNone(qr_bill.reference_clash(n, [o for o in serie if o != n], qr), n)
        refs = {qr_bill.payment_reference(f"2026-{n:02d}", QR_IBAN) for n in range(1, 100)}; self.assertEqual(len(refs), 99)

    def test_scor_keeps_letters(self):
        self.assertIsNone(qr_bill.reference_clash("2026-A1", ["2026-11"], ""))         # SCOR keeps the letters ...
        self.assertEqual(qr_bill.reference_clash("2026-A1", ["2026-11"], QR_IBAN), None)   # ... QRR keeps digits: A1 -> 1, 11 -> 11


class Db(base.Option):
    def issued(self, number, pid=None):
        self.sqlw("INSERT INTO invoices(number,project_id,period_from,period_to,qty,unit,unit_rate,status,issued_at) VALUES(?,?,'2025-01-01','2025-01-31',1,'day',650,'issued','2025-02-01T10:00:00')", (number, pid or self.pid))

    def number(self, iid): return self.scalar("SELECT number FROM invoices WHERE id=?", (iid,))

    def try_number(self, iid, number):
        rev = str(self.scalar("SELECT revision FROM invoices WHERE id=?", (iid,)))
        self.flashes() if hasattr(self, "flashes") else None
        r = self.c.post(f"/invoice/{iid}/edit", data=dict(period_from="2026-09-01", period_to="2026-09-30", qty="2", unit="day", rounding="exact", rounding_step="0.25", vat="0",
                        description="P", other_amount="0", other_label="", other_vat_mode="hors_tva", invoice_date="", note="", revision=rev, number=number))
        return r.get_data(as_text=True)

    def set_qr_iban(self, v):
        self.sqlw("INSERT INTO settings(key,value) VALUES('qr_iban',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (v,))

    CASES = (("2026-101", "2026-10-1"), ("2026-11", "2026-1-1"), ("2027-10-1", "2027-101"))

    def test_typed_number_refused_both_modes_and_nothing_written(self):
        for existing, _ in self.CASES: self.issued(existing)       # issued invoices cannot be deleted: all inserted once
        for qr in ("", QR_IBAN):
            self.set_qr_iban(qr)
            for existing, typed in self.CASES:
                iid = self.draft_(); self.sqlw("UPDATE invoices SET number=NULL WHERE id=?", (iid,))
                before = (self.number(iid), self.scalar("SELECT revision FROM invoices WHERE id=?", (iid,)), self.scalar("SELECT COUNT(*) FROM invoice_number_changes"))
                html = self.try_number(iid, typed)
                self.assertIn(MSG.format(existing), html.replace("&nbsp;", " ").replace("&#39;", "'"), (qr, existing, typed))
                self.assertEqual(before, (self.number(iid), self.scalar("SELECT revision FROM invoices WHERE id=?", (iid,)), self.scalar("SELECT COUNT(*) FROM invoice_number_changes")))
                self.sqlw("DELETE FROM invoices WHERE id=?", (iid,))

    def test_typed_number_accepted_without_clash(self):
        self.issued("2026-09"); iid = self.draft_()
        self.try_number(iid, "2026-15"); self.assertEqual(self.number(iid), "2026-15")
        self.try_number(iid, "2026-8"); self.assertEqual(self.number(iid), "2026-8")
        self.try_number(iid, "2027-1-1"); self.assertEqual(self.number(iid), "2027-1-1")

    def test_same_number_keeps_its_own_message(self):
        self.issued("2026-09"); iid = self.draft_()
        html = self.try_number(iid, "2026-9"); self.assertIn("déjà utilisé", html); self.assertNotIn("même référence", html)

    def test_automatic_number_never_clashes(self):
        for n in range(1, 11): self.issued(f"2026-{n}")
        self.issued("2026-1-1")                  # reference of 2026-11
        with m.db() as c:
            n = rules.propose_invoice_number(c, 2026)
            self.assertNotEqual(n, "2026-11")    # 2026-11 would repeat the reference of 2026-1-1
            self.assertEqual(n, "2026-12"); self.assertIsNone(rules.reference_conflict(c, n))

    def test_drafts_without_number_do_not_count_and_two_issuers_style_projects_unaffected(self):
        iid = self.draft_(); self.sqlw("UPDATE invoices SET number=NULL WHERE id=?", (iid,))
        with m.db() as c:
            self.assertIsNone(rules.reference_conflict(c, "2026-1-1", exclude_id=None))
            self.assertIsNone(rules.reference_conflict(c, "2026-11"))

    def test_other_draft_with_reserved_number_counts(self):
        a = self.draft_(); self.sqlw("UPDATE invoices SET number='2026-101' WHERE id=?", (a,))
        with m.db() as c: self.assertEqual(rules.reference_conflict(c, "2026-10-1")["number"], "2026-101")

    def test_slip_omitted_with_message_on_legacy_collision(self):
        os.environ["QR_BILL_ENABLED"] = "1"; self.structure()
        self.issued("2026-101"); iid = self.draft_()
        self.sqlw("UPDATE invoices SET number='2026-10-1', number_manual=1, qr_bill=1 WHERE id=?", (iid,))      # old data: written before the check existed
        with m.db() as c: h = invoice_service.live_data(c, iid)[0]
        self.assertEqual(h["reference_clash"], "2026-101")
        bill, why = qr_bill.assess(h)
        self.assertIsNone(bill); self.assertEqual(why, MSG.format("2026-101"))
        self.assertIn(MSG.format("2026-101"), self.checks(iid)[15]["detail"] if "detail" in self.checks(iid)[15] else str(self.checks(iid)[15]))
        for qr in (QR_IBAN,):
            self.set_qr_iban(qr)
            with m.db() as c: h = invoice_service.live_data(c, iid)[0]
            self.assertEqual(qr_bill.assess(h)[1], MSG.format("2026-101"))

    def test_slip_still_printed_without_clash_and_header_keys_unchanged(self):
        os.environ["QR_BILL_ENABLED"] = "1"; self.structure()
        self.issued("2026-09"); iid = self.draft_(); self.sqlw("UPDATE invoices SET qr_bill=1 WHERE id=?", (iid,))
        with m.db() as c: h = invoice_service.live_data(c, iid)[0]
        self.assertNotIn("reference_clash", h)
        bill, why = qr_bill.assess(h); self.assertIsNotNone(bill, why)
        self.assertEqual(bill.reference_number, qr_bill.payment_reference(h["number"]))

    def test_unticked_invoice_header_keeps_its_keys(self):
        self.issued("2026-101"); iid = self.draft_(); self.sqlw("UPDATE invoices SET number='2026-10-1' WHERE id=?", (iid,))
        with m.db() as c: h = invoice_service.live_data(c, iid)[0]
        self.assertNotIn("reference_clash", h); self.assertNotIn("qr_bill", h)


if __name__ == "__main__": unittest.main()
