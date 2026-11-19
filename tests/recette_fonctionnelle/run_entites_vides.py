"""Recette fonctionnelle — Q. Mandats actifs dont l'entité de facturation est VOLONTAIREMENT vide (décision C2 : PCR LV 2026, STC GEM Oct - DM job, MSD) :
l'application ne doit rien inventer ni émettre de facture sans adresse de facturation ; NHAF 2026 / EUROPCR 2027 (adresse C2) ne sont pas bloqués par l'adresse.
usage: run_entites_vides.py <port> <dossier-instance>   (copie jetable du staging post-C1/C2)"""
import sys, os, re, html
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
port, dirn = sys.argv[1], sys.argv[2]; A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('Q'); ck = R.check; assert A.login()
R.sec('Q. Entités de facturation laissées vides (C2) : rien d\'inventé, émission bloquée proprement')
txt = lambda pg: re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', pg)))
for name in ('PCR LV 2026', 'STC GEM Oct - DM job'):
    pid = A.one('select id from projects where name=?', (name,)); row = A.q('select billing_address, billing_contact, client_legal_name, active, rate from projects where id=?', (pid,))[0]
    ck(f'Q1 {name} : adresse / contact / raison sociale vides en base (rien d\'inventé), mandat actif', row[0] == '' and row[1] == '' and row[2] == '' and row[3] == 1, row)
    d0, d1 = A.q('select min(work_date), max(work_date) from entries where project_id=?', (pid,))[0]
    A.post('/invoice', {'project_id': pid, 'period_from': d0, 'period_to': d1, 'qty': '0.5', 'unit': 'day', 'rounding': 'exact'}); iid = A.one('select max(id) from invoices')
    ck(f'Q2 {name} : brouillon créé (la facturation n\'est pas bloquée avant l\'émission)', A.one('select status from invoices where id=?', (iid,)) == 'draft')
    pg = txt(A.get(f'/issue/{iid}')); tail = pg[pg.find('compléter'):][:300] if 'compléter' in pg else ''
    ck(f'Q3 {name} : l\'écran d\'émission signale « Adresse de facturation » à compléter', 'Adresse de facturation' in tail, tail or pg[:300])
    s, m = A.post(f'/issue/{iid}', {'from_confirm': '1'}); ck(f'Q4 {name} : émission refusée côté serveur (POST direct), brouillon inchangé', A.one('select status from invoices where id=?', (iid,)) == 'draft', m)
    t = pdf_text(A.req(f'/invoice/{iid}.pdf')[2]); ck(f'Q5 {name} : PDF de brouillon marqué BROUILLON, champ manquant signalé « À COMPLÉTER » (jamais une adresse inventée)', 'BROUILLON' in t.upper() and 'COMPLÉTER' in t.upper() and 'EGG BE' not in t, t[:300])
    A.post(f'/invoice/{iid}/delete', {})
pid = A.one("select id from projects where name='MSD'"); r = A.q('select rate, ordered_days, billing_address from projects where id=?', (pid,))[0]
ck('Q6 MSD : ni tarif, ni jours commandés, ni adresse (rien d\'inventé)', r == (0.0, 0.0, ''), r)
s, m = A.post('/invoice', {'project_id': pid, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '0.5', 'unit': 'day', 'rounding': 'exact'}); n = A.one("select count(*) from invoices where project_id=?", (pid,))
ck('Q7 MSD sans tarif : aucune facture émise (soit refus du brouillon, soit brouillon non émissible)', A.one("select count(*) from invoices where project_id=? and status='issued'", (pid,)) == 0, (n, m))
for name in ('NHAF 2026', 'EUROPCR 2027'):
    row = A.q('select billing_contact, client_legal_name, vat, billing_address from projects where name=?', (name,))[0]
    ck(f'Q8 {name} : entité C2 présente (EGG BE, Claudia Ntampaka, Jette), TVA 0 %', row[0] == 'Claudia Ntampaka' and row[1] == 'EGG BE' and row[2] == 0 and 'Jette' in row[3], row)
pid = A.one("select id from projects where name='ECIO 2025'"); r = A.q('select rate, ordered_days, po, active, closed_reason from projects where id=?', (pid,))[0]
ck('Q10 ECIO 2025 (C3) : clôturé, aucun tarif, aucun PO, aucun jour commandé enregistrés', r[0] == 0 and r[1] == 0 and r[2] == '' and r[3] == 0 and 'facturé hors application' in r[4], r)
n0 = A.one('select count(*) from invoices'); s, m = A.post('/invoice', {'project_id': pid, 'period_from': '2025-01-01', 'period_to': '2025-04-30', 'qty': '2.66', 'unit': 'day', 'rounding': 'exact'})
ck('Q11 ECIO 2025 : aucune facture créée pour ses 21,3 h (mandat clôturé, tarif 0)', A.one('select count(*) from invoices') == n0 and A.one('select count(*) from invoices where project_id=?', (pid,)) == 0, m)
pos = A.get('/'); ck('Q12 ECIO 2025 : aucune mention « offert » rattachée au mandat (jours offerts = 0 en base)', A.one('select count(*) from invoices where reliquat_treatment=\'offert\'') == 0 and A.one('select count(*) from entries where project_id=?', (pid,)) == 36, None)
e = A.q("select count(*), round(sum(hours),4) from entries")[0]; ck('Q9 saisies historiques inchangées (2 247 / 1 934,4987 h)', e == (2247, 1934.4987), e)
ok = sum(1 for r in R.rows if r['ok']); ko = [r for r in R.rows if not r['ok']]
print(f"\nRÉSULTAT Q : {ok}/{len(R.rows)} OK, {len(ko)} KO")
for r in ko: print('  KO', r['test'], '|', r['detail'])
sys.exit(1 if ko else 0)
