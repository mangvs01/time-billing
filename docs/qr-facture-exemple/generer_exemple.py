"""Génère l'exemple de facture avec bulletin QR (données fictives : « Test SA », « Client Exemple »).
Usage, depuis la racine du dépôt :  /root/venvs/rc25-test-venv/bin/python docs/qr-facture-exemple/generer_exemple.py
Écrit exemple-facture-qr.pdf (facture émise, case « Ajouter la QR-facture » cochée : bulletin) et exemple-facture-sans-qr.pdf (même facture, case décochée) à côté de ce script.
BQR3 : le bulletin est une option par facture (en-tête fictif : clé qr_bill = 1 cochée, 0 décochée) ; QR_BILL_ENABLED n'est que le garde-fou global.
Le drapeau est positionné ici pour la durée du script seulement ; rien n'est écrit ailleurs."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from tests.test_qr_bill import fake_header          # en-tête fictif construit à la main, sans base de données
from app import pdf_layout, invoice_checks

ROWS = [{"id": i, "work_date": f"2026-09-{d:02d}", "start_time": "08:30", "end_time": "17:30", "hours": 8, "description": "Prestations de conseil"} for i, d in ((1, 10), (2, 11))]
os.environ["QR_BILL_ENABLED"] = "1"
open(os.path.join(HERE, "exemple-facture-sans-qr.pdf"), "wb").write(pdf_layout.render_invoice(fake_header(qr_bill=0), ROWS, issued=True)[0])      # case décochée
open(os.path.join(HERE, "exemple-facture-qr.pdf"), "wb").write(pdf_layout.render_invoice(fake_header(), ROWS, issued=True)[0])
print("ok")

# --- BQR2 : les trois exemples demandés (données fictives) -------------------------------------------------------------------
from app import qr_bill
from reportlab import rl_config; rl_config.invariant = 1      # sans horodatage : deux rendus des mêmes données sont identiques
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
os.environ["QR_BILL_ENABLED"] = "1"
open(os.path.join(HERE, "exemple-1-chf-avec-reference-SCOR.pdf"), "wb").write(pdf_layout.render_invoice(fake_header(), ROWS, issued=True)[0])
# 2. CHF sans référence (« NON ») : bulletin seul, construit directement par le module
from tests.test_qr_bill import CRED, DEBT, IBAN
bill = qr_bill.build_bill(CRED, IBAN, "1405.30", "CHF", DEBT, reference=None, message="Facture 2026-09")
c = canvas.Canvas(os.path.join(HERE, "exemple-2-chf-sans-reference.pdf"), pagesize=A4); qr_bill.payment_page(c, bill, "Section paiement — sans référence (NON)"); c.save()
# 3. case cochée mais adresse du client non structurée : l'émission est BLOQUÉE (contrôle n° 15) ; la sortie est de décocher la case = facture sans bulletin
bad = fake_header(client_street="", client_house_num="", client_pcode="", client_city="")
reason = qr_bill.blocking_problem(bad)
assert reason
unticked = pdf_layout.render_invoice(fake_header(qr_bill=0, client_pcode="", client_city=""), ROWS, issued=True)[0]
os.environ.pop("QR_BILL_ENABLED"); assert unticked == pdf_layout.render_invoice(fake_header(qr_bill=0, client_pcode="", client_city=""), ROWS, issued=True)[0]      # identique à la facture sans QR-facture
c = canvas.Canvas(os.path.join(HERE, "exemple-3-adresse-non-structuree-refusee.pdf"), pagesize=A4)
c.setFont("Helvetica-Bold", 12); c.drawString(50, 780, "Écran d'émission, contrôle n° 15 : ÉMISSION IMPOSSIBLE (case « Ajouter la QR-facture » cochée)")
c.setFont("Helvetica", 10)
import textwrap
for n, line in enumerate(textwrap.wrap(reason + " — à corriger : " + invoice_checks._qr_where(reason) + " ; ou décocher « Ajouter la QR-facture ».", 95)): c.drawString(50, 750 - 15 * n, line)
c.save(); open(os.path.join(HERE, "exemple-3-facture-emise-sans-bulletin.pdf"), "wb").write(unticked)     # case décochée : la facture part, sans bulletin
print("ok 3 exemples")
