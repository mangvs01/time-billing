"""RC13 end-to-end (synthetic data, DB copy only): long annex reason printed in full, SQL triggers active in the running app.
Usage: python e2e_rc13.py   (writes /data/rc13-annex.pdf for the caller's pdftotext check)"""
import sys, sqlite3
sys.argv = [sys.argv[0], 'none']
import tests_e2e_http as e  # noqa  (e2e_http.py copied next to this file in the container)

LONG = "Préparation de l'atelier de cadrage avec l'équipe projet puis revue du budget détaillé et rédaction du compte rendu pour le comité de pilotage"
e.login()
e.req('/settings', {'issuer_name': 'Émetteur RC13 Sàrl', 'issuer_address': 'Rue 1\n1200 Genève', 'account_holder': 'Émetteur RC13 Sàrl', 'iban': 'CH00 0000 0000 0000 0000 0',
                    'payment_terms': 'Paiement à 30 jours', 'issuer_vat_number': 'CHE-000.000.000 TVA (fictif)'})
e.req('/project', {'name': 'RC13 Alpha', 'rate': '1200', 'day_hours': '8', 'vat': '8.1', 'ordered_days': '10', 'client': 'Client RC13', 'client_legal_name': 'Client RC13 SA',
                   'client_legal_id': 'CHE-000.000.043', 'billing_address': 'Client RC13 SA\nRue 2\n1000 Ville'})
pid = e.q("SELECT id FROM projects WHERE name='RC13 Alpha'")[0][0]
e.req('/entry', {'work_date': '2026-09-10', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '8', 'description': LONG})
e.req('/invoice', {'project_id': pid, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1'})
iid = e.q('SELECT MAX(id) FROM invoices')[0][0]
page = e.req(f'/issue/{iid}')[2].decode()
import re
exp = re.search(r'name="expected_reliquat" value="([^"]+)"', page).group(1)
e.req(f'/issue/{iid}', {'reliquat_treatment': 'reporte', 'expected_reliquat': exp, 'from_confirm': '1'})
e.check('facture RC13 émise', e.q('SELECT status FROM invoices WHERE id=?', (iid,))[0][0] == 'issued')
s, h, pdf = e.req(f'/invoice/{iid}.pdf'); e.check('PDF émis', s == 200 and pdf.startswith(b'%PDF'))
open('/data/rc13-annex.pdf', 'wb').write(pdf)
c = sqlite3.connect(e.DB)
for sql in ("UPDATE audit SET detail='x'", "DELETE FROM audit"):
    try: c.execute(sql); e.check('audit en ajout seul: ' + sql, False)
    except sqlite3.DatabaseError as ex: e.check('audit en ajout seul: ' + sql, 'append-only' in str(ex))
c.close()
print(f"RESULT rc13: {sum(ok for _, ok in e.results)}/{len(e.results)} passed")
sys.exit(0 if all(ok for _, ok in e.results) else 1)
