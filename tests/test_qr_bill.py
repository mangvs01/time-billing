"""BQR1: Swiss QR-bill module (app/qr_bill.py). Synthetic data only (« Test SA », « Client Exemple »).

Unit part: valid cases, refusals in plain French (wrong IBAN, unstructured address, QR-IBAN without QRR, zero amount), EUR.
Insertion part: flag off = the PDF is the same as before (golden fingerprint untouched, same pages); flag on = one extra portrait page after page 1.
"""
import os, re, sys, unittest

from reportlab import rl_config
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from app import invoice_checks, pdf_layout, qr_bill
from app.qr_bill import QrBillError

IBAN = "CH9300762011623852957"                    # classic IBAN (documentation example)
QR_IBAN = "CH4431999123000889012"                 # QR-IBAN (institution identifier 31999)
CRED = {"name": "Test SA", "street": "Rue du Lac", "house_num": "1", "pcode": "1800", "city": "Vevey", "country": "CH"}
DEBT = {"name": "Client Exemple", "street": "Avenue de la Gare", "house_num": "12", "pcode": "1003", "city": "Lausanne", "country": "CH"}
QRR = "210000000003139471430009017"               # 27 digits, modulo-10 check digit valid


def pages(pdf): return len(re.findall(rb"/Type /Page\b(?!s)", pdf))


class Unit(unittest.TestCase):
    def build(self, **kw):
        args = dict(creditor=CRED, iban=IBAN, amount="1234.50", currency="CHF", debtor=DEBT, reference=None, message="Facture 2026-09")
        args.update(kw); return qr_bill.build_bill(**args)

    def refused(self, fragment, **kw):
        with self.assertRaises(QrBillError) as cm: self.build(**kw)
        self.assertIn(fragment, str(cm.exception)); return str(cm.exception)

    def test_valid_without_reference_is_NON(self):
        b = self.build()
        self.assertEqual((b.ref_type, b.currency, str(b.amount)), ("NON", "CHF", "1234.50"))
        self.assertIn("Test SA", qr_bill.bill_svg(b))

    def test_valid_with_scor_reference(self):
        ref = qr_bill.scor_reference("2026-09")
        self.assertEqual(ref, "RF" + ref[2:4] + "202609")
        b = self.build(reference=ref)
        self.assertEqual(b.ref_type, "SCOR")

    def test_scor_known_value(self):
        self.assertEqual(qr_bill.scor_reference("539007547034"), "RF18539007547034")      # ISO 11649 example

    def test_valid_qr_iban_with_qrr(self):
        self.assertEqual(self.build(iban=QR_IBAN, reference=QRR).ref_type, "QRR")

    def test_eur(self):
        b = self.build(currency="EUR", amount="10")
        self.assertEqual((b.currency, str(b.amount)), ("EUR", "10.00"))

    def test_other_currency_refused(self):
        self.refused("CHF et EUR", currency="USD")

    def test_wrong_iban(self):
        self.refused("IBAN du créancier invalide", iban="CH9300762011623852958")
        self.refused("obligatoire", iban="")
        self.refused("suisse (CH) ou liechtensteinois", iban="FR1420041010050500013M02606")

    def test_qr_iban_needs_qrr(self):
        self.refused("exige une référence QRR", iban=QR_IBAN)
        self.refused("exige une référence QRR", iban=QR_IBAN, reference=qr_bill.scor_reference("2026-09"))

    def test_qrr_needs_qr_iban(self):
        self.refused("n'est admise qu'avec un QR-IBAN", reference=QRR)

    def test_bad_reference_check_digits(self):
        self.refused("Référence invalide", reference="RF99202609")

    def test_unstructured_address_refused(self):
        msg = self.refused("non structurée", debtor={"name": "Client Exemple", "billing_address": "Client Exemple\nAvenue de la Gare 12\n1003 Lausanne"})
        self.assertIn("champs séparés", msg)
        self.refused("non structurée", creditor={"name": "Test SA", "line1": "Rue du Lac 1", "line2": "1800 Vevey"})
        self.refused("champs séparés", debtor="Avenue de la Gare 12, 1003 Lausanne")

    def test_incomplete_structured_address_refused(self):
        self.refused("code postal : champ obligatoire", debtor=dict(DEBT, pcode=""))
        self.refused("localité : champ obligatoire", creditor=dict(CRED, city=" "))
        self.refused("pays", debtor=dict(DEBT, country="Suisse"))
        self.refused("numéro est collé", debtor=dict(DEBT, street="Rue du Lac 1", house_num=""))

    def test_debtor_is_optional(self):
        self.assertIsNone(self.build(debtor=None).debtor)

    def test_zero_or_negative_amount_refused(self):
        self.refused("Montant nul ou négatif", amount="0")
        self.refused("Montant nul ou négatif", amount="0.00")
        self.refused("Montant nul ou négatif", amount="-5")
        self.refused("Montant nul ou négatif", amount="0.004")
        self.refused("Montant illisible", amount="abc")

    def test_rounding_and_swiss_separators(self):
        self.assertEqual(str(self.build(amount="1'234,505").amount), "1234.51")

    def test_forbidden_characters_and_length(self):
        self.refused("caractère(s) non admis", message="Facture \u0627")
        self.refused("140 au maximum", message="x" * 141)
        self.refused("caractère(s) non admis", debtor=dict(DEBT, name="Client‮Exemple"))

    def test_accents_and_line_breaks_accepted(self):
        b = self.build(message="Facture de septembre\n2026 - Mandat Évolution")
        self.assertTrue(qr_bill.bill_svg(b))

    def test_drawing_has_the_slip_size(self):
        d = qr_bill.bill_drawing(self.build())
        self.assertAlmostEqual(d.width, 595.28, 1); self.assertAlmostEqual(d.height, 300.47, 1)

    def test_draw_on_canvas_makes_a_pdf(self):
        import io
        buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4)
        qr_bill.payment_page(c, self.build(), "Section paiement"); c.save()
        self.assertTrue(buf.getvalue().startswith(b"%PDF")); self.assertEqual(pages(buf.getvalue()), 1)

    def test_flag(self):
        old = os.environ.pop("QR_BILL_ENABLED", None)
        try:
            self.assertFalse(qr_bill.enabled())
            for v, want in (("1", True), ("true", True), ("OUI", True), ("0", False), ("", False), ("non", False)):
                os.environ["QR_BILL_ENABLED"] = v; self.assertEqual(qr_bill.enabled(), want, v)
        finally:
            os.environ.pop("QR_BILL_ENABLED", None)
            if old is not None: os.environ["QR_BILL_ENABLED"] = old

    def test_library_is_appended_after_the_regular_packages(self):
        self.assertIn(qr_bill.VENDOR_DIR, sys.path)
        self.assertGreater(sys.path.index(qr_bill.VENDOR_DIR), 0)


def fake_header(**over):
    """Header built by hand for the insertion tests (no database): enough for render_invoice."""
    from decimal import Decimal
    h = {"id": 1, "number": "2026-09", "status": "issued", "issued_at": "2026-09-30", "invoice_date": "2026-09-30", "project_id": 1, "project": "Mandat Exemple",
         "client": "Client Exemple", "po": "PO-1", "period_from": "2026-09-01", "period_to": "2026-09-30", "qty": 2, "unit": "day", "unit_rate": 650, "vat": 8.1,
         "note": "", "rounding": "exact", "rounding_step": 0.25, "day_hours": 8, "project_number": "NP-1", "billing_contact": "Service comptabilité",
         "billing_address": "Avenue de la Gare 12\n1003 Lausanne", "dates_label": "Sept 2026", "ordered_days": 12, "description": "Prestations de septembre",
         "other_amount": 0, "other_label": "", "reliquat_days": 0, "reliquat_treatment": "", "reliquat_note": "", "client_legal_name": "Client Exemple SA",
         "client_legal_id": "", "client_legal_id_display": "", "project_short": "Exemple", "other_vat_mode": "hors_tva", "invoice_date_history": [], "consumed_days": 2,
         "position": {"ordered": 12, "realized": 2, "historical": 0, "previous": 0, "current": 2, "credited": 0, "balance": 10, "later": 0}, "period_hours": 16,
         "amounts": {"ht": Decimal("1300.00"), "vat": Decimal("8.1"), "tva": Decimal("105.30"), "other": Decimal("0"), "ttc": Decimal("1405.30")},
         "offsets": [], "net_due": "1405.30",
         "issuer": {"issuer_name": "Test SA", "issuer_address": "Rue du Lac 1\n1800 Vevey", "account_holder": "Test SA", "iban": IBAN, "bic": "", "payment_terms": "30 jours net",
                    "thanks_text": "", "issuer_rc": "", "issuer_vat_number": "", "issuer_street": "Rue du Lac", "issuer_house_num": "1", "issuer_pcode": "1800",
                    "issuer_city": "Vevey", "issuer_country": "CH"},
         "client_street": "Avenue de la Gare", "client_house_num": "12", "client_pcode": "1003", "client_city": "Lausanne", "client_country": "CH",
         "client_addr_verified": 1, "qr_bill": 1}       # BQR3: the box « Ajouter la QR-facture » is ticked by default in these fixtures; fake_header(qr_bill=0) is the invoice without the option
    h.update(over); return h


class Insertion(unittest.TestCase):
    def setUp(self):
        self._inv = rl_config.invariant; rl_config.invariant = 1       # no timestamp: two renderings of the same data are byte-identical
        self._flag = os.environ.pop("QR_BILL_ENABLED", None)

    def tearDown(self):
        rl_config.invariant = self._inv; os.environ.pop("QR_BILL_ENABLED", None)
        if self._flag is not None: os.environ["QR_BILL_ENABLED"] = self._flag

    def render(self, h, issued=True): return pdf_layout.render_invoice(h, [], issued=issued)[0]

    def test_golden_layout_fingerprint_unchanged(self):
        self.assertEqual(invoice_checks._golden(), invoice_checks.layout_fingerprint())

    def test_flag_off_or_zero_is_the_same_pdf(self):
        a = self.render(fake_header())
        os.environ["QR_BILL_ENABLED"] = "0"
        self.assertEqual(a, self.render(fake_header()))

    def test_flag_on_adds_exactly_one_portrait_page_after_page_1(self):
        off = self.render(fake_header()); os.environ["QR_BILL_ENABLED"] = "1"; on = self.render(fake_header())
        self.assertEqual(pages(on), pages(off) + 1)
        self.assertNotEqual(on, off)

    def test_invoice_without_structured_address_gets_no_slip_and_a_reason(self):
        os.environ["QR_BILL_ENABLED"] = "1"
        off = pages(self.render(fake_header(client_street="", client_pcode="", client_city="", client_house_num="")))   # (flag on, slip omitted)
        h = fake_header(client_street="", client_pcode="", client_city="", client_house_num="")
        pdf = self.render(h, issued=True)
        self.assertEqual(pages(pdf), off)
        os.environ.pop("QR_BILL_ENABLED")
        self.assertEqual(pdf, self.render(h, issued=True))               # omitted slip = exactly the invoice without the flag
        os.environ["QR_BILL_ENABLED"] = "1"
        w = qr_bill.blocking_problem(h)
        self.assertIn("code postal", w)                                   # BQR3: this reason now BLOCKS issuance (check 15), see TestBlocking

    def test_unstructured_free_text_gives_a_clear_reason(self):
        os.environ["QR_BILL_ENABLED"] = "1"
        h = fake_header(); [h.pop(k) for k in ("client_street", "client_house_num", "client_pcode", "client_city", "client_country")]
        self.assertIn("non structurée", qr_bill.blocking_problem(h))

    def test_draft_without_data_renders_without_slip(self):
        os.environ["QR_BILL_ENABLED"] = "1"
        h = fake_header(number=None, status="draft", client_pcode="", client_city="")
        pdf = self.render(h, issued=False)
        self.assertTrue(pdf.startswith(b"%PDF"))
        os.environ.pop("QR_BILL_ENABLED"); self.assertEqual(pdf, self.render(h, issued=False))

    def test_no_reason_when_flag_off_or_all_is_valid(self):
        self.assertIsNone(qr_bill.blocking_problem(fake_header(client_pcode="")))     # flag off: nothing
        os.environ["QR_BILL_ENABLED"] = "1"
        self.assertIsNone(qr_bill.blocking_problem(fake_header()))

    def test_invalid_iban_gives_a_reason_and_no_slip(self):
        os.environ["QR_BILL_ENABLED"] = "1"
        for iban in ("CH0000000000000000000", "", "CH93 0076 2011 6238 5295 8"):
            h = fake_header(); h["issuer"] = dict(h["issuer"], iban=iban)
            self.assertIn("IBAN", qr_bill.blocking_problem(h), iban); self.assertEqual(pages(self.render(h)), pages(self.render(fake_header())) - 1)

    def test_foreign_iban_is_left_out_without_any_message(self):
        os.environ["QR_BILL_ENABLED"] = "1"
        for iban in ("FR1420041010050500013M02606", "DE89370400440532013000", "GB82WEST12345698765432"):
            h = fake_header(); h["issuer"] = dict(h["issuer"], iban=iban, issuer_country="FR")
            self.assertEqual(qr_bill.assess(h), (None, None), iban)
            self.assertIsNone(qr_bill.blocking_problem(h))
            self.assertEqual(pages(self.render(h)), pages(self.render(fake_header())) - 1)

    def test_payload_matches_the_invoice(self):
        """The QR content (Swiss Payment Standards 2.0 payload) compared field by field with the invoice."""
        os.environ["QR_BILL_ENABLED"] = "1"
        bill, w = qr_bill.assess(fake_header()); self.assertIsNone(w)
        f = bill.qr_data().split("\r\n" if "\r\n" in bill.qr_data() else "\n")
        self.assertEqual(f[:4], ["SPC", "0200", "1", IBAN])
        self.assertEqual(f[4:11], ["S", "Test SA", "Rue du Lac", "1", "1800", "Vevey", "CH"])
        self.assertEqual(f[11:18], [""] * 7)                                       # no final creditor
        self.assertEqual(f[18:20], ["1405.30", "CHF"])
        self.assertEqual(f[20:27], ["S", "Client Exemple SA", "Avenue de la Gare", "12", "1003", "Lausanne", "CH"])
        self.assertEqual(f[27:29], ["SCOR", qr_bill.scor_reference("2026-09")])
        self.assertEqual(f[29:31], ["Facture 2026-09", "EPD"])

    def test_eur_invoice(self):
        os.environ["QR_BILL_ENABLED"] = "1"
        bill, w = qr_bill.assess(fake_header(currency="EUR")); self.assertIsNone(w)
        self.assertIn("EUR", bill.qr_data()); self.assertEqual(bill.currency, "EUR")
        self.assertEqual(pages(self.render(fake_header(currency="EUR"))), pages(self.render(fake_header())))
        self.assertIn("CHF et EUR", qr_bill.blocking_problem(fake_header(currency="USD")))

    def test_credit_offset_amount_and_zero_net(self):
        os.environ["QR_BILL_ENABLED"] = "1"
        h = fake_header(offsets=[{"reference": "NC-1", "amount": "1405.30"}], net_due="0.00")
        self.assertIn("Montant nul", qr_bill.blocking_problem(h))

    def test_inputs_from_header_uses_net_due_and_the_invoice_number(self):
        h = fake_header(offsets=[{"reference": "NC-1", "amount": "100.00"}], net_due="1305.30")
        k = qr_bill.inputs_from_header(h)
        self.assertEqual((str(k["amount"]), k["currency"], k["message"]), ("1305.30", "CHF", "Facture 2026-09"))
        self.assertTrue(k["reference"].startswith("RF"))
        self.assertEqual(qr_bill.build_bill(**k).ref_type, "SCOR")


if __name__ == "__main__":
    unittest.main()
