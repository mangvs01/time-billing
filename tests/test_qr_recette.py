"""BILL-QR-PRET (20/11/2026): recette de bout en bout de la QR-facture, QR_BILL_ENABLED=1 posé DANS LE PROCESSUS DE TEST seulement (jamais dans un fichier de configuration).

Données fictives uniquement : IBAN de documentation suisse CH93 0076 2011 6238 5295 7 (clé de contrôle valide, compte inexistant), QR-IBAN fictif CH44 3199 9123 0008 8901 2,
« Emetteur SA » à Vevey, « Client SA » à Lausanne. Base jetable créée par init() dans un dossier temporaire ; aucune base réelle, aucun accès réseau.

Ce que la recette vérifie, sur le PDF d'une facture ÉMISE (pas sur un objet de test) :
  - la page du bulletin (A4 portrait, après la page 1) : textes de la norme (Récépissé, Section paiement, Compte / Payable à, Référence, Informations supplémentaires, Payable par,
    Monnaie, Montant, Point de dépôt), montant lisible identique à celui de la charge utile ;
  - la ligne de découpe (pointillé horizontal en haut du bulletin et pointillé vertical à 62 mm) et la croix suisse au centre du code QR, par analyse de l'image du PDF ;
  - le code QR : image du PDF comparée module par module à un code QR encodé à neuf depuis la charge utile (aucun décodeur de code QR n'est installé ici : voir le rapport) ;
  - la charge utile elle-même, relue par un vérificateur écrit à part (`payload_problems`, d'après la norme « Swiss Implementation Guidelines QR-bill 2.2 ») et non par la bibliothèque :
    structure, longueurs, IBAN, clé de contrôle des références (SCOR mod 97, QRR mod 10), cohérence QR-IBAN / QRR, montant, devise, adresses structurées, EPD.
Cas : facture avec référence SCOR, facture avec QR-IBAN et référence QRR, facture avec avoir imputé (montant = net à payer), avoir qui couvre toute la facture (émission bloquée puis
sortie par la case), note de crédit (jamais de bulletin), références de paiement distinctes, PDF émis figé, valeurs du drapeau, transmission du drapeau au conteneur, liste d'allumage.
Lancer :  python -m unittest tests.test_qr_recette   (ou outils/run_tests_parallel.py tests.test_qr_recette)
Pour garder les PDF et les images du bulletin à regarder : RECETTE_QR_DIR=/chemin/dossier (hors dépôt).
"""
import os, re, shutil, subprocess, tempfile, unittest

import tests.test_qr_bill_addresses as A
from tests.test_qr_bill_option import m, VALID_IBAN                    # also sets the test environment variables
from tests.test_functional import pdf_text
from app import invoice_service, qr_bill

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QR_IBAN = A.QR_IBAN
KEEP = os.environ.get("RECETTE_QR_DIR")
LATIN = set(chr(c) for c in range(0x20, 0x7F)) | set("àáâãäåæçèéêëìíîïñòóôõöøùúûüýÿœšžÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝŸŒŠŽßÐðÞþ€£§°")
MM300 = 300 / 25.4


def lu(path):
    with open(path, encoding="utf-8") as fh: return fh.read()


# --- independent reader of the QR payload (Swiss Implementation Guidelines QR-bill 2.2, §4) -------------------------------------------------
def _mod97(s):
    return int("".join(str(int(ch, 36)) for ch in s)) % 97


def iban_ok(iban):
    return len(iban) == 21 and iban[:2] in ("CH", "LI") and iban[2:4].isdigit() and iban[4:].isalnum() and _mod97(iban[4:] + iban[:4]) == 1


def qrr_ok(ref):
    """27 digits, the last one is the recursive modulo-10 check digit (table of the Swiss payment standard)."""
    if not (len(ref) == 27 and ref.isdigit()): return False
    carry = 0
    for ch in ref[:-1]: carry = (0, 9, 4, 6, 8, 2, 7, 1, 3, 5)[(carry + int(ch)) % 10]
    return (10 - carry) % 10 == int(ref[-1])


def scor_ok(ref):
    """ISO 11649: « RF », 2 check digits, 1 to 21 letters or digits; rearranged (tail + « RF » + check) the number is 1 modulo 97."""
    return bool(re.fullmatch(r"RF\d{2}[0-9A-Z]{1,21}", ref)) and _mod97(ref[4:] + ref[:4]) == 1


def payload_problems(payload):
    """List of problems of a QR payload (text with the standard's lines); [] = conforming. Written from the standard, independent of the qrbill library."""
    bad = []
    f = payload.replace("\r\n", "\n").split("\n")
    if len(f) < 31: return [f"{len(f)} lignes au lieu de 31 au moins"]
    if f[:3] != ["SPC", "0200", "1"]: bad.append(f"en-tête {f[:3]} au lieu de SPC / 0200 / 1")
    if not iban_ok(f[3]): bad.append(f"IBAN {f[3]!r} invalide, ni CH ni LI ou clé fausse")

    def address(label, a, required):
        t, name, street, num, pcode, city, country = a
        if not any(a):
            if required: bad.append(f"{label} : adresse vide")
            return
        if t != "S": bad.append(f"{label} : type d'adresse {t!r} (seul S, structurée, est admis)")
        for key, v, mx, need in (("nom", name, 70, True), ("rue", street, 70, False), ("numéro", num, 16, False), ("code postal", pcode, 16, True), ("localité", city, 35, True)):
            if need and not v: bad.append(f"{label} : {key} vide")
            if len(v) > mx: bad.append(f"{label} : {key} de {len(v)} caractères (maximum {mx})")
        if not re.fullmatch(r"[A-Z]{2}", country): bad.append(f"{label} : pays {country!r} (2 lettres majuscules)")

    address("créancier", f[4:11], True)
    if any(f[11:18]): bad.append("créancier final renseigné (réservé, doit rester vide)")
    if f[18] and not re.fullmatch(r"\d{1,9}\.\d{2}", f[18]): bad.append(f"montant {f[18]!r} (format 0.00, 12 caractères au plus)")
    if re.fullmatch(r"\d+\.\d+", f[18]) and float(f[18]) <= 0: bad.append("montant nul ou négatif")
    if f[19] not in ("CHF", "EUR"): bad.append(f"monnaie {f[19]!r}")
    address("débiteur", f[20:27], False)
    kind, ref, info, trailer = f[27], f[28], f[29], f[30]
    is_qr_iban = 30000 <= int(f[3][4:9]) <= 31999 if f[3][4:9].isdigit() else False
    if kind == "QRR":
        if not is_qr_iban: bad.append("référence QRR avec un IBAN ordinaire (réservée au QR-IBAN)")
        if not qrr_ok(ref): bad.append(f"référence QRR {ref!r} : 27 chiffres et chiffre de contrôle modulo 10 attendus")
    elif kind == "SCOR":
        if is_qr_iban: bad.append("référence SCOR avec un QR-IBAN (il exige une QRR)")
        if not scor_ok(ref): bad.append(f"référence SCOR {ref!r} : clé de contrôle ISO 11649 fausse")
    elif kind == "NON":
        if is_qr_iban: bad.append("pas de référence avec un QR-IBAN (il exige une QRR)")
        if ref: bad.append("type NON mais une référence est donnée")
    else: bad.append(f"type de référence {kind!r}")
    if len(info) > 140: bad.append("message de plus de 140 caractères")
    if trailer != "EPD": bad.append(f"fin de bloc {trailer!r} au lieu de EPD")
    if len(f) > 31 + 3 or any(f[31:]) and len(f) > 34: bad.append("trop de lignes après EPD")
    odd = sorted({ch for ch in payload.replace("\r", "").replace("\n", "") if ch not in LATIN})
    if odd: bad.append("caractères hors jeu latin de la norme : " + " ".join(odd))
    return bad


# --- reading the printed page ------------------------------------------------------------------------------------------------------------------
def raster(pdf, page, dpi=300, name="p"):
    """Grey image (PIL) of one page of `pdf` (bytes). With RECETTE_QR_DIR the PDF and the PNG are kept there."""
    from PIL import Image
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "f.pdf"), "wb") as fh: fh.write(pdf)
        subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-f", str(page), "-l", str(page), "-png", os.path.join(d, "f.pdf"), os.path.join(d, "p")], check=True)
        png = next(os.path.join(d, x) for x in sorted(os.listdir(d)) if x.startswith("p") and x.endswith(".png"))
        im = Image.open(png).convert("L"); im.load()
        if KEEP:
            os.makedirs(KEEP, exist_ok=True)
            with open(os.path.join(KEEP, name + ".pdf"), "wb") as fh: fh.write(pdf)
            im.save(os.path.join(KEEP, name + f"-page{page}.png"))
        return im
    finally:
        shutil.rmtree(d, ignore_errors=True)


def dashes(px, points, dark=128):
    """(share of dark pixels, number of dark/light transitions) along the list of (x, y) pixels: a dotted line alternates, plain text or a full rule does not."""
    v = [px[x, y] < dark for x, y in points]
    return sum(v) / len(v), sum(1 for a, b in zip(v, v[1:]) if a != b)


def page_text(pdf, page):
    out = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-layout", "-", "-"], input=pdf, capture_output=True, check=True)
    return out.stdout.decode("utf-8")


class Recette(A.Screens):
    """The whole path through the screens, then the issued PDF is read back (see the module docstring)."""
    RECORD_WORK = True

    def setUp(self):
        super().setUp(); os.environ["QR_BILL_ENABLED"] = "1"
        if not shutil.which("pdftoppm") or not shutil.which("pdftotext"): self.skipTest("poppler (pdftoppm, pdftotext) absent")
        self.save_issuer(); self.save_mandate(); self.flashes()

    # -- helpers
    def issue_ticked(self, iid, tick=True):
        if tick: self.tick(iid)
        self.flashes(); self.issue(iid)
        self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (iid,)), "issued", " ".join(self.flashes()))
        number = self.scalar("SELECT number FROM invoices WHERE id=?", (iid,))
        return number, self.pdf(iid), invoice_service.frozen_header(m.db(), iid)

    def fields(self, h):
        bill, why = qr_bill.assess(h); self.assertIsNone(why); self.assertIsNotNone(bill)
        payload = bill.qr_data(); return payload, payload.replace("\r\n", "\n").split("\n")

    def credit_note(self, iid, qty, treatment):
        self.flashes(); self.c.post(f"/invoice/{iid}/credit", data={"qty": str(qty), "treatment": treatment, "reason": "motif fictif de recette"})
        cid = self.scalar("SELECT MAX(id) FROM credit_notes")
        self.assertIn("Brouillon de note de crédit créé", " ".join(self.flashes())); self.flashes()
        self.c.post(f"/credit/{cid}/issue"); self.assertEqual(self.scalar("SELECT status FROM credit_notes WHERE id=?", (cid,)), "issued", " ".join(self.flashes()))
        return cid

    def second_draft(self):
        iid, fl = self.draft(self.pid, "2026-10-01", "2026-10-31", 1); self.assertIn("Brouillon créé", " ".join(fl)); return iid

    def read_slip(self, pdf, payload, amount_text, name, kind):
        """Everything printed on page 2 against the payload (`kind` = SCOR / QRR) — see the module docstring."""
        f = payload.replace("\r\n", "\n").split("\n")
        self.assertEqual(payload_problems(payload), [], payload)
        # page geometry: page 2 is a portrait A4 (page 3, the annex, is landscape)
        im = raster(pdf, 2, name=name); W, H = im.size; px = im.load()
        self.assertAlmostEqual(W / MM300, 210, delta=1); self.assertAlmostEqual(H / MM300, 297, delta=1)
        # printed texts
        t = " ".join(page_text(pdf, 2).split())
        iban_printed = " ".join(f[3][i:i + 4] for i in range(0, 21, 4))                                               # CH93 0076 2011 6238 5295 7
        ref = f[28]                                                                                                   # QRR: 2 digits then groups of 5 · SCOR: groups of 4
        ref_printed = " ".join([ref[:2]] + [ref[i:i + 5] for i in range(2, 27, 5)]) if kind == "QRR" else " ".join(ref[i:i + 4] for i in range(0, len(ref), 4))
        for frag in ("Récépissé", "Section paiement", "Compte / Payable à", "Référence", "Informations supplémentaires", "Payable par", "Monnaie", "Montant", "Point de dépôt",
                     iban_printed, ref_printed, f[5], f[6] + " " + f[7], "CH-" + f[8] + " " + f[9], f[21], f[22] + " " + f[23], "CH-" + f[24] + " " + f[25], f[29], f[19] + " " + amount_text):
            self.assertIn(frag, t.replace("\xa0", " "), frag)
        self.assertEqual(f[18], amount_text.replace(" ", ""), "montant imprimé = montant de la charge utile")
        # cut lines: dotted horizontal rule at the top of the slip (bill = the 106 last millimetres), dotted vertical rule at 62 mm
        top = H - round(106 * MM300)
        rows = [(y, dashes(px, [(x, y) for x in range(round(75 * MM300), round(200 * MM300))])) for y in range(top, top + round(4 * MM300))]
        y, (share, flips) = max(rows, key=lambda r: r[1][1])
        self.assertGreater(flips, 60, "ligne de découpe horizontale pointillée introuvable"); self.assertTrue(0.25 < share < 0.75, share)
        self.assertAlmostEqual((y - top) / MM300, 1.14, delta=0.7)
        cols = [(x, dashes(px, [(x, yy) for yy in range(top + round(8 * MM300), H - round(3 * MM300))])) for x in range(round(60 * MM300), round(64 * MM300))]
        x, (share, flips) = max(cols, key=lambda r: r[1][1])
        self.assertGreater(flips, 60, "ligne de découpe verticale pointillée introuvable"); self.assertTrue(0.25 < share < 0.75, share)
        self.assertAlmostEqual(x / MM300, 62, delta=0.5)
        # swiss cross at the centre of the QR code: white cross on a black square (centre white, diagonal corner black), and the QR itself equals a fresh encoding of the payload
        dark = [(xx, yy) for yy in range(round(205 * MM300), min(round(258 * MM300), H)) for xx in range(round(64 * MM300), round(116 * MM300)) if px[xx, yy] < 128]
        bx0, bx1 = min(xx for xx, _ in dark), max(xx for xx, _ in dark); by0, by1 = min(yy for _, yy in dark), max(yy for _, yy in dark)
        cx, cy = (bx0 + bx1) // 2, (by0 + by1) // 2
        self.assertGreater(px[cx, cy], 200, "le centre de la croix doit être blanc"); self.assertLess(px[cx + round(2.4 * MM300), cy + round(2.4 * MM300)], 80, "coin de la croix noir")
        self.assertAlmostEqual(bx0 / MM300, 67, delta=1.0)                                            # 5 mm after the receipt / payment separator
        A.Flow.check_qr_in_pdf(self, pdf, payload)

    # -- A. classic IBAN, SCOR reference
    def test_A_facture_scor_de_bout_en_bout(self):
        iid = self.draft_(); self.assertEqual(self.checks(iid).get(15), None)                          # box not ticked: no check 15, 14 checks as before
        number, pdf, h = self.issue_ticked(iid)
        self.assertEqual(self.pages(pdf), self.pages(self.pdf(iid)))
        payload, f = self.fields(h)
        self.assertEqual((f[3], f[27], f[28], f[29]), (VALID_IBAN, "SCOR", qr_bill.scor_reference(number), "Facture " + number))
        self.assertEqual(f[4:11], ["S", "Emetteur SA", "Rue du Lac", "1", "1800", "Vevey", "CH"]); self.assertEqual(f[20:27], ["S", "Client SA", "Avenue de la Gare", "12", "1003", "Lausanne", "CH"])
        self.assertEqual(f[18:20], [f"{float(h['amounts']['ttc']):.2f}", "CHF"]); self.assertEqual(f[18], "1300.00")
        self.read_slip(pdf, payload, "1 300.00", "A-facture-SCOR", "SCOR")

    # -- B. QR-IBAN, QRR reference
    def test_B_facture_qr_iban_reference_qrr(self):
        self.save_issuer(qr_iban=QR_IBAN); self.flashes()
        number, pdf, h = self.issue_ticked(self.draft_())
        payload, f = self.fields(h)
        self.assertEqual((f[3], f[27], f[28]), (QR_IBAN, "QRR", qr_bill.qrr_reference(number))); self.assertEqual(len(f[28]), 27)
        self.read_slip(pdf, payload, "1 300.00", "B-facture-QRR", "QRR")

    # -- C. avoir imputé : le bulletin demande le NET À PAYER, pas le total
    def test_C_avoir_impute_le_montant_du_bulletin_est_le_net_a_payer(self):
        n1, pdf1, h1 = self.issue_ticked(self.draft_())
        cid = self.credit_note(self.scalar("SELECT MAX(id) FROM invoices"), "0.5", "compensation")              # 0,5 jour x 650 = 325,00 (sans TVA)
        d2 = self.second_draft(); self.flashes(); self.c.post(f"/credit/{cid}/offset", data={"target_invoice_id": str(d2), "amount": "325"})
        self.assertIn("Imputation enregistrée", " ".join(self.flashes()))
        draft_pdf = self.pdf(d2); self.assertIn("NET À PAYER", pdf_text(draft_pdf))
        n2, pdf2, h2 = self.issue_ticked(d2)
        self.assertEqual((float(h2["amounts"]["ttc"]), h2["net_due"]), (650.0, "325.00"))
        payload, f = self.fields(h2)
        self.assertEqual(f[18:20], ["325.00", "CHF"]); self.assertEqual(f[29], "Facture " + n2)
        self.read_slip(pdf2, payload, "325.00", "C-facture-avec-avoir", "SCOR")
        t = pdf_text(pdf2); self.assertIn("TOTAL FACTURE", t); self.assertIn("NET À PAYER", t)
        self.assertNotEqual(f[28], qr_bill.scor_reference(n1)); self.assertEqual(f[28], qr_bill.scor_reference(n2))                  # a reference per invoice
        self.assertEqual(self.fields(h1)[1][18], "1300.00")                                                                          # the first invoice still asks 1300.00

    # -- D. l'avoir couvre toute la facture : rien à payer, pas de bulletin possible
    def test_D_avoir_total_bloque_le_bulletin_la_sortie_est_de_decocher_la_case(self):
        self.issue_ticked(self.draft_())
        cid = self.credit_note(self.scalar("SELECT MAX(id) FROM invoices"), "1", "compensation")                         # 650,00
        d2 = self.second_draft(); self.c.post(f"/credit/{cid}/offset", data={"target_invoice_id": str(d2), "amount": "650"}); self.flashes()
        self.tick(d2); ck = self.checks(d2)[15]
        self.assertEqual(ck["status"], "fail"); self.assertIn("Montant nul", ck["detail"])
        self.flashes(); self.issue(d2); self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (d2,)), "draft")        # blocked
        self.c.post(f"/invoice/{d2}/qr-bill", data={"qr_bill": "0"}); self.assertNotIn(15, self.checks(d2))
        self.flashes(); self.issue(d2); self.assertEqual(self.scalar("SELECT status FROM invoices WHERE id=?", (d2,)), "issued", " ".join(self.flashes()))
        self.assertNotIn("Section paiement", pdf_text(self.pdf(d2)))

    # -- E. une note de crédit n'a jamais de bulletin, même si la facture d'origine en a un
    def test_E_note_de_credit_sans_bulletin(self):
        number, pdf, h = self.issue_ticked(self.draft_()); iid = self.scalar("SELECT MAX(id) FROM invoices")
        cid = self.credit_note(iid, "0.5", "remboursement")
        cpdf = self.c.get(f"/credit/{cid}.pdf").data; txt = pdf_text(cpdf)
        self.assertIn("NOTE DE CRÉDIT", txt)
        for frag in ("Section paiement", "Récépissé", "Point de dépôt", "Compte / Payable à"): self.assertNotIn(frag, txt)
        self.assertEqual(self.c.get(f"/invoice/{iid}.pdf").data, pdf)                                                     # the original invoice is untouched

    # -- F. le PDF émis ne bouge plus
    def test_F_le_pdf_emis_est_fige(self):
        number, pdf, h = self.issue_ticked(self.draft_()); iid = self.scalar("SELECT MAX(id) FROM invoices")
        self.save_issuer(iban="CH5604835012345678009", issuer_city="Genève", issuer_pcode="1201", qr_iban=QR_IBAN)         # the owner changes the account afterwards
        self.sqlw("UPDATE projects SET client_city='Fribourg' WHERE id=?", (self.pid,))
        self.assertEqual(self.pdf(iid), pdf); self.assertEqual(self.fields(invoice_service.frozen_header(m.db(), iid))[1][3], VALID_IBAN)
        os.environ.pop("QR_BILL_ENABLED"); self.assertEqual(self.pdf(iid), pdf)                                            # and without the safeguard: same bytes

    # -- G. case décochée : la facture sort comme avant, drapeau allumé ou non
    def test_G_case_decochee_aucun_bulletin(self):
        number, pdf, h = self.issue_ticked(self.draft_(), tick=False); self.assertNotIn("qr_bill", h)
        self.assertNotIn("Section paiement", pdf_text(pdf)); self.assertEqual(len(payload_problems("SPC\n")), 1)

    # -- H. références de paiement : deux factures, deux références
    def test_H_references_distinctes_entre_factures(self):
        n1, _, h1 = self.issue_ticked(self.draft_()); n2, _, h2 = self.issue_ticked(self.second_draft())
        r1, r2 = self.fields(h1)[1][28], self.fields(h2)[1][28]
        self.assertNotEqual(n1, n2); self.assertNotEqual(r1, r2); self.assertTrue(scor_ok(r1) and scor_ok(r2))


class Verificateur(unittest.TestCase):
    """The independent reader of the payload and the reference rules (pure Python: no database, no PDF)."""
    GOOD = "\n".join(["SPC", "0200", "1", VALID_IBAN, "S", "Emetteur SA", "Rue du Lac", "1", "1800", "Vevey", "CH"] + [""] * 7 +
                      ["1300.00", "CHF", "S", "Client SA", "Avenue de la Gare", "12", "1003", "Lausanne", "CH", "SCOR", "RF37" + "20261", "Facture 2026-1", "EPD"])

    def test_official_vectors_and_the_checker_is_not_vacuous(self):
        self.assertTrue(qrr_ok("210000000003139471430009017"))                                                           # example of the standard
        self.assertFalse(qrr_ok("210000000003139471430009018")); self.assertFalse(qrr_ok("21000000000313947143000901"))
        self.assertTrue(scor_ok("RF18539007547034")); self.assertFalse(scor_ok("RF19539007547034"))                         # ISO 11649 example
        self.assertTrue(iban_ok(VALID_IBAN)); self.assertFalse(iban_ok("CH9300762011623852958")); self.assertFalse(iban_ok("FR1420041010050500013M02606"))
        self.assertEqual(payload_problems(self.GOOD), [])
        for old, new, frag in (("1300.00", "0.00", "nul"), ("1300.00", "1300,00", "montant"), ("CHF", "USD", "monnaie"), ("\nS\nClient SA", "\nK\nClient SA", "type d'adresse"),
                               ("\nCH\nSCOR", "\nCHE\nSCOR", "pays"), ("RF37", "RF38", "SCOR"), ("EPD", "XXX", "EPD"), ("Rue du Lac", "Rue du Lac —", "hors jeu latin")):
            self.assertTrue(any(frag in p for p in payload_problems(self.GOOD.replace(old, new, 1))), (old, new))
        self.assertTrue(any("SCOR avec un QR-IBAN" in p for p in payload_problems(self.GOOD.replace(VALID_IBAN, QR_IBAN))))
        self.assertTrue(any("QRR avec un IBAN ordinaire" in p for p in payload_problems(self.GOOD.replace("SCOR", "QRR"))))

    def test_every_number_of_a_year_gives_its_own_valid_reference_in_both_modes(self):
        numbers = [f"2026-{n}" for n in range(1, 1500)] + [f"2027-{n}" for n in range(1, 50)]
        for qr_iban, valid in ((None, scor_ok), (QR_IBAN, qrr_ok)):
            refs = {n: qr_bill.payment_reference(n, qr_iban) for n in numbers}
            self.assertEqual(len(set(refs.values())), len(numbers), "deux numéros donnent la même référence")
            self.assertTrue(all(valid(r) for r in refs.values()))
            self.assertIsNone(qr_bill.reference_clash("2026-12", [n for n in numbers if n != "2026-12"], qr_iban))
        self.assertEqual(qr_bill.reference_clash("2026-1-1", ["2026-11"], None), "2026-11")                               # the known risky mix (BQR9) stays caught


class Drapeau(unittest.TestCase):
    """QR_BILL_ENABLED: the value written by the person who switches it on must mean the same thing everywhere (screens, PDF, checks) and reach the container."""
    def setUp(self):
        self._flag = os.environ.pop("QR_BILL_ENABLED", None)

    def tearDown(self):
        os.environ.pop("QR_BILL_ENABLED", None)
        if self._flag is not None: os.environ["QR_BILL_ENABLED"] = self._flag

    def test_absent_or_empty_is_off(self):
        self.assertFalse(qr_bill.enabled()); os.environ["QR_BILL_ENABLED"] = ""; self.assertFalse(qr_bill.enabled())

    def test_the_documented_values_switch_it_on_and_the_others_do_not(self):
        for v in ("1", "true", "TRUE", "oui", "yes", "on", " 1 "):
            os.environ["QR_BILL_ENABLED"] = v; self.assertTrue(qr_bill.enabled(), v)
        for v in ("0", "false", "non", "no", "off", "2", "x"):
            os.environ["QR_BILL_ENABLED"] = v; self.assertFalse(qr_bill.enabled(), v)

    def test_the_container_receives_the_variable_and_its_default_is_off(self):
        """procedure/docker-compose.*.yml lists the variables given to the container one by one: a line QR_BILL_ENABLED in .env alone would never reach the application."""
        for name in ("docker-compose.prod.yml", "docker-compose.staging.yml"):
            text = lu(os.path.join(ROOT, "procedure", name))
            lines = [l.strip() for l in text.splitlines() if l.strip().startswith("QR_BILL_ENABLED:")]
            self.assertEqual(len(lines), 1, name)
            self.assertRegex(lines[0], r"^QR_BILL_ENABLED: \$\{QR_BILL_ENABLED:-\}", name)                                  # empty default = off


class ValeursDuDrapeauDansLesEcrans(A.Screens):
    """A value that is not one of the documented ones (« 0 », « non ») must show NO box and add NO page, exactly like an absent variable."""
    def test_zero_or_non_shows_no_box_and_no_check_15_and_no_slip(self):
        self.save_issuer(); self.save_mandate(); iid = self.draft_(); off = self.pdf(iid)
        for v in ("0", "non", "false"):
            os.environ["QR_BILL_ENABLED"] = v
            try:
                self.assertNotIn("qrBillField", self.page(f"/invoice/{iid}/edit"), v); self.assertNotIn("qrBillOption", self.page(f"/issue/{iid}"), v)
                self.sqlw("UPDATE invoices SET qr_bill=1 WHERE id=?", (iid,))
                self.assertEqual(self.pdf(iid), off, v); self.assertNotIn(15, self.checks(iid), v)
                self.sqlw("UPDATE invoices SET qr_bill=0 WHERE id=?", (iid,))
            finally:
                os.environ.pop("QR_BILL_ENABLED", None)


class ListeAllumage(unittest.TestCase):
    """docs/QR-ALLUMAGE.md: six steps at most, plain French, and every screen it names exists in the application."""
    PATH = os.path.join(ROOT, "docs", "QR-ALLUMAGE.md")

    def text(self):
        if not os.path.exists(self.PATH): self.fail("docs/QR-ALLUMAGE.md manque")
        return lu(self.PATH)

    def test_six_numbered_steps_at_most(self):
        steps = re.findall(r"^## Étape (\d+)", self.text(), re.M)
        self.assertTrue(1 <= len(steps) <= 6, steps); self.assertEqual(steps, [str(i) for i in range(1, len(steps) + 1)])

    def test_names_of_the_screens_exist_in_the_application(self):
        """Every « name » of the checklist is the name of a screen, a button or a box of the application (the guillemets are used for nothing else in that file)."""
        import html
        tpl = os.path.join(ROOT, "app", "templates")
        shown = html.unescape("".join(lu(os.path.join(tpl, f)) for f in sorted(os.listdir(tpl)))).replace("\xa0", " ")
        names = re.findall(r"«\s*([^»]+?)\s*»", self.text())
        self.assertGreaterEqual(len(names), 6)
        for name in names: self.assertIn(name, shown, f"écran, bouton ou case inconnu de l'application : « {name} »")

    def test_no_jargon_without_explanation_and_no_real_data(self):
        t = self.text()
        self.assertNotRegex(t, r"CH\d{2}[ ]?\d{4}[ ]?\d{4}[ ]?\d{4}[ ]?\d{4}[ ]?\d", "aucun IBAN dans la liste")
        self.assertIn("QR_BILL_ENABLED", t)                                                                                 # the technical step names the variable once, for the operator


if __name__ == "__main__":
    unittest.main()
