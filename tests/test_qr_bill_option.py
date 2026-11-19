"""BQR3: the QR-bill is an OPTION chosen invoice by invoice (invoices.qr_bill, default 0) and BLOCKS issuance (check 15) when a piece of information is missing.
Synthetic data, on a throw-away database created by init() in a temporary folder (no staging copy needed). Run:  python -m unittest tests.test_qr_bill_option
"""
import os, shutil, sqlite3, tempfile, unittest, unittest.mock

os.environ.setdefault("APP_PASSWORD", "mot-de-passe-de-test-123"); os.environ.setdefault("SECRET_KEY", "k" * 40); os.environ.setdefault("COOKIE_SECURE", "0")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "bqr3-boot.db"))
import app.app as m
from app import invoice_checks, invoice_service, qr_bill
from reportlab import rl_config
from tests.test_functional import Cycle, pdf_text
from tests.test_import import FAKE_ISSUER

VALID_IBAN = "CH9300762011623852957"
STRUCT_ISSUER = {"issuer_street": "Rue du Lac", "issuer_house_num": "1", "issuer_pcode": "1800", "issuer_city": "Vevey", "issuer_country": "CH"}
STRUCT_CLIENT = {"client_street": "Avenue de la Gare", "client_house_num": "12", "client_pcode": "1003", "client_city": "Lausanne", "client_country": "CH"}
CLIENT_COLS = tuple(STRUCT_CLIENT)


class Option(Cycle):
    RECORD_WORK = True

    def setUp(self):       # same as Base.setUp, but on a fresh database in a temporary folder
        self._inv = rl_config.invariant; rl_config.invariant = 1
        self._flag = os.environ.pop("QR_BILL_ENABLED", None)
        self._words = os.environ.get("INVOICE_CHECK_WORDS"); os.environ["INVOICE_CHECK_WORDS"] = ""      # as the throw-away test containers (the fixtures say « Fictif »)
        self.tmp = tempfile.mkdtemp(); self.db = os.path.join(self.tmp, "timebilling.db")
        m.DB = self.db; m.init(); m.APP.config["TESTING"] = True
        self.c = m.APP.test_client()
        self.assertEqual(self.c.post("/login", data={"username": m.SEC["user"], "password": os.environ["APP_PASSWORD"]}).status_code, 302)
        self.c.post("/settings", data=dict(FAKE_ISSUER, iban=VALID_IBAN, issuer_name="Emetteur SA", account_holder="Emetteur SA", issuer_address="Rue du Lac 1\n1800 Vevey"))
        self.pid = self.mandate(name="Mandat QR", vat="0")
        self.sqlw("UPDATE projects SET client='Client SA', client_legal_name='Client SA', po='PO-0001', project_number='NP-0001', billing_contact='Contact', billing_address='Client SA\nRue 1\n1000 Ville' WHERE id=?", (self.pid,))

    def tearDown(self):
        rl_config.invariant = self._inv; os.environ.pop("QR_BILL_ENABLED", None)
        if self._flag is not None: os.environ["QR_BILL_ENABLED"] = self._flag
        os.environ.pop("INVOICE_CHECK_WORDS", None)
        if self._words is not None: os.environ["INVOICE_CHECK_WORDS"] = self._words
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sqlw(self, q, a=()):
        c = sqlite3.connect(self.db); c.execute(q, a); c.commit(); c.close()

    def structure(self, issuer=True, client=True):
        if issuer:
            for k, v in STRUCT_ISSUER.items(): self.sqlw("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        if client:      # BQR4: the columns exist (additive migration of init()); « adresse vérifiée » is part of what the owner confirms
            self.sqlw("UPDATE projects SET " + ",".join(f"{k}=?" for k in CLIENT_COLS) + ",client_addr_verified=1 WHERE id=?", (*STRUCT_CLIENT.values(), self.pid))

    def draft_(self, **kw): return self.draft(self.pid, "2026-09-01", "2026-09-30", 2, **kw)[0]
    def pdf(self, iid): return self.c.get(f"/invoice/{iid}.pdf").data
    def pages(self, pdf):
        import re; return len(re.findall(rb"/Type /Page\b(?!s)", pdf))
    def checks(self, iid):
        c = m.db()
        try: return {x["n"]: x for x in invoice_checks.run_checks(c, iid)}
        finally: c.close()
    def edit(self, iid, **extra):
        return self.c.post(f"/invoice/{iid}/edit", data=dict({"period_from": "2026-09-01", "period_to": "2026-09-30", "qty": "2", "unit": "day"}, **extra))
    def stored(self, iid): return self.scalar("SELECT qr_bill FROM invoices WHERE id=?", (iid,))
    def page(self, url): return self.c.get(url).get_data(as_text=True)


class Migration(Option):
    def test_column_is_additive_default_zero_and_rollback_leaves_rows_alone(self):
        iid = self.draft_()
        self.assertEqual(self.stored(iid), 0)
        before = dict(self.sql("SELECT * FROM invoices WHERE id=?", (iid,))[0])
        # emulate a database that predates the column: drop it, start the application again (init) -> the column comes back with 0 on the existing row
        self.sqlw("ALTER TABLE invoices DROP COLUMN qr_bill")
        self.assertNotIn("qr_bill", [r[1] for r in self.sql("PRAGMA table_info(invoices)")])
        m.init()
        self.assertEqual(self.stored(iid), 0)
        self.assertEqual(dict(self.sql("SELECT * FROM invoices WHERE id=?", (iid,))[0]), before)      # nothing else of the row changed
        m.init(); self.assertEqual(self.stored(iid), 0)                                                # idempotent
        # rollback SQL (documented in docs/QR-FACTURE.md): drops the column only
        self.sqlw("ALTER TABLE invoices DROP COLUMN qr_bill")
        after = dict(self.sql("SELECT * FROM invoices WHERE id=?", (iid,))[0])
        self.assertEqual(after, {k: v for k, v in before.items() if k != "qr_bill"})
        m.init()          # and forward again, so that the application works after the rollback test
        self.assertIn("qr_bill", [r[1] for r in self.sql("PRAGMA table_info(invoices)")])


class Unticked(Option):
    def test_box_unticked_is_the_same_pdf_flag_on_or_off_and_no_check_15(self):
        iid = self.draft_()
        off = self.pdf(iid); ck = self.checks(iid)
        self.assertEqual(sorted(ck), list(range(1, 15)))
        os.environ["QR_BILL_ENABLED"] = "1"
        self.assertEqual(self.pdf(iid), off)                                  # flag on, box unticked: byte-identical to today's invoice
        self.assertEqual(sorted(self.checks(iid)), list(range(1, 15)))
        h = invoice_service.live_data(m.db(), iid)[0]; self.assertNotIn("qr_bill", h)       # the header of an ordinary invoice keeps its keys

    def test_flag_off_shows_no_box_and_ignores_a_stored_choice(self):
        iid = self.draft_()
        self.assertNotIn("qrBillField", self.page(f"/invoice/{iid}/edit")); self.assertNotIn("qrBillOption", self.page(f"/issue/{iid}"))
        self.sqlw("UPDATE invoices SET qr_bill=1 WHERE id=?", (iid,))
        off = self.pdf(iid)
        self.assertEqual(sorted(self.checks(iid)), list(range(1, 15)))        # safeguard off: behaviour of today, whatever is stored
        self.sqlw("UPDATE invoices SET qr_bill=0 WHERE id=?", (iid,))
        self.assertEqual(self.pdf(iid), off)
        r = self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"}); self.assertEqual(r.status_code, 302); self.assertEqual(self.stored(iid), 0)


class Ticked(Option):
    def setUp(self):
        super().setUp(); os.environ["QR_BILL_ENABLED"] = "1"

    def test_box_is_shown_unticked_by_default_in_both_screens_and_saved_with_the_draft(self):
        iid = self.draft_()
        e, i = self.page(f"/invoice/{iid}/edit"), self.page(f"/issue/{iid}")
        self.assertIn("Ajouter la QR-facture", e); self.assertIn("Ajouter la QR-facture", i)
        self.assertNotIn("checked", e.split("qrBillField")[1].split("</label>")[0]); self.assertNotIn("checked", i.split("qrBillBox")[1].split(">")[0])
        self.edit(iid, qr_bill_present="1", qr_bill="1"); self.assertEqual(self.stored(iid), 1)
        self.assertIn("checked", self.page(f"/invoice/{iid}/edit").split("qrBillField")[1].split("</label>")[0])
        self.assertIn("checked", self.page(f"/issue/{iid}").split("qrBillBox")[1].split(">")[0])        # same value on the issue screen
        self.edit(iid, qr_bill_present="1"); self.assertEqual(self.stored(iid), 0)                    # unticked in the editor
        self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"}); self.assertEqual(self.stored(iid), 1)    # ticked on the issue screen
        self.edit(iid); self.assertEqual(self.stored(iid), 1)                                        # an editor form without the box leaves the choice alone

    def test_ticked_with_missing_information_blocks_the_issuance_and_unticking_releases_it(self):
        iid = self.draft_(); self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"})
        ck = self.checks(iid)
        self.assertEqual(sorted(ck), list(range(1, 16))); self.assertEqual(ck[15]["status"], "fail"); self.assertFalse(ck[15]["derogable"])
        self.assertIn("Adresse du créancier", ck[15]["detail"]); self.assertIn("décocher", ck[15]["detail"])
        page = self.page(f"/issue/{iid}")
        self.assertIn('id="chk15"', page); self.assertIn("Émission impossible", page); self.assertIn("/project/%d/edit" % self.pid, page)
        self.flashes(); self.issue(iid, derogate=(15,))                      # no written reason can override it
        self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (iid,)), "draft"); self.assertIn("15.", " ".join(self.flashes()))
        self.c.post(f"/invoice/{iid}/qr-bill", data={})                       # the way out: untick
        self.assertEqual(sorted(self.checks(iid)), list(range(1, 15)))
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (iid,)), "issued", self.flashes())

    def test_each_missing_piece_blocks_with_its_own_message(self):
        self.structure(); iid = self.draft_(); self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"})
        self.assertEqual(self.checks(iid)[15]["status"], "ok")
        for table, col, bad, frag in (("settings", "iban", "CH0000000000000000000", "IBAN du créancier invalide"), ("settings", "issuer_pcode", "", "Adresse du créancier, code postal"),
                                      ("projects", "client_city", "", "Adresse du client, localité"), ("projects", "client_pcode", "", "Adresse du client, code postal")):
            good = self.sql("SELECT value FROM settings WHERE key=?", (col,))[0][0] if table == "settings" else self.sql(f"SELECT {col} FROM projects WHERE id=?", (self.pid,))[0][0]
            q = ("UPDATE settings SET value=? WHERE key=?", (bad, col)) if table == "settings" else (f"UPDATE projects SET {col}=? WHERE id=?", (bad, self.pid))
            self.sqlw(*q); ck = self.checks(iid)[15]
            self.assertEqual(ck["status"], "fail", col); self.assertIn(frag, ck["detail"], col)
            self.sqlw(*(("UPDATE settings SET value=? WHERE key=?", (good, col)) if table == "settings" else (f"UPDATE projects SET {col}=? WHERE id=?", (good, self.pid))))
        self.assertEqual(self.checks(iid)[15]["status"], "ok")

    def test_complete_information_unblocks_and_the_pdf_gets_the_slip_page_with_BROUILLON(self):
        iid = self.draft_(); plain = self.pdf(iid); n0 = self.pages(plain)
        self.structure(); self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"})
        self.assertEqual(self.checks(iid)[15]["status"], "ok")
        d = self.pdf(iid); self.assertEqual(self.pages(d), n0 + 1)
        t = " ".join(pdf_text(d).split()); self.assertIn("BROUILLON — bulletin non valable", t); self.assertIn("Section paiement", t)
        self.flashes(); self.issue(iid); self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (iid,)), "issued", self.flashes())
        issued = self.pdf(iid); self.assertEqual(self.pages(issued), n0 + 1); self.assertNotIn("bulletin non valable", " ".join(pdf_text(issued).split()))
        self.assertIn("Facture " + self.scalar("SELECT number FROM invoices WHERE id=?", (iid,)), " ".join(pdf_text(issued).split()))

    def test_issued_invoice_never_changes(self):
        self.structure(); a = self.draft_(); self.c.post(f"/invoice/{a}/qr-bill", data={"qr_bill": "1"}); self.flashes(); self.issue(a)
        self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (a,)), "issued", self.flashes())
        frozen = self.pdf(a); h = invoice_service.frozen_header(m.db(), a); self.assertEqual(h["qr_bill"], 1)
        self.c.post(f"/invoice/{a}/qr-bill", data={})                                   # refused: not a draft
        self.assertEqual(self.stored(a), 1)
        self.sqlw("UPDATE settings SET value='CH0000000000000000000' WHERE key='iban'"); os.environ.pop("QR_BILL_ENABLED")
        self.assertEqual(self.pdf(a), frozen)                                           # frozen bytes, whatever the data or the flag become
        # an invoice issued WITHOUT the option stays without it when the option is later used on another one
        self.sqlw("UPDATE settings SET value=? WHERE key='iban'", (VALID_IBAN,)); os.environ["QR_BILL_ENABLED"] = "1"
        b = self.draft(self.pid, "2026-10-01", "2026-10-31", 1)[0]; self.flashes(); self.issue(b)
        self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (b,)), "issued", self.flashes())
        self.assertEqual(self.stored(b), 0); self.assertNotIn("Section paiement", " ".join(pdf_text(self.pdf(b)).split())); self.assertIn("Section paiement", " ".join(pdf_text(self.pdf(a)).split()))

    def test_foreign_account_greys_the_box_without_any_error(self):
        self.sqlw("UPDATE settings SET value='FR1420041010050500013M02606' WHERE key='iban'")
        iid = self.draft_(); i = self.page(f"/issue/{iid}")
        self.assertIn("qrBillUnsupported", i); self.assertIn("Pas de bulletin pour ce compte", i); self.assertIn("disabled", i.split("qrBillOption")[1][:600])
        self.assertIn("Pas de bulletin pour ce compte", self.page(f"/invoice/{iid}/edit"))
        self.flashes(); r = self.c.post(f"/invoice/{iid}/qr-bill", data={"qr_bill": "1"}); self.assertEqual(self.stored(iid), 0)      # cannot be ticked
        self.assertEqual(sorted(self.checks(iid)), list(range(1, 15)))
        self.sqlw("UPDATE invoices SET qr_bill=1 WHERE id=?", (iid,))                     # even if forced: no error, no check, no page
        self.assertEqual(self.checks(iid)[15]["status"], "ok"); self.assertEqual(self.pages(self.pdf(iid)), self.pages(self.pdf(self.draft_())))


if __name__ == "__main__":
    unittest.main()
