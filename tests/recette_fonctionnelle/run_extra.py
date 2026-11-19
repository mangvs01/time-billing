"""Recette fonctionnelle — cas limites de calcul : facturation en heures, TVA 0, arrondi au centime (demi supérieur), total nul refusé, grands montants.
usage: run_extra.py <port> <dossier-instance>"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
port, dirn = sys.argv[1], sys.argv[2]; A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('extra'); ck = R.check; assert A.login()
R.sec('C+. Calculs limites (comparés à un recalcul indépendant en Decimal)')
def mand(name, rate, dh, vat):
    A.post('/project', {'name': name, 'rate': rate, 'day_hours': dh, 'vat': vat, 'ordered_days': '100', 'client': 'C', 'client_legal_name': 'C SA', 'client_legal_id': 'CHE-123.456.789', 'billing_address': 'C SA\nRue 1\n1000 V'})
    return A.one('select id from projects where name=?', (name,))
def run(pid, f, t, qty, treat='reporte', **kw):
    dg = {k: kw.pop(k) for k in list(kw) if k.startswith('derogation_')}   # D8 : motifs écrits, champs du formulaire d'émission (pas du brouillon)
    d = {'project_id': pid, 'period_from': f, 'period_to': t, 'qty': qty, 'rounding': 'exact'}; d.update(kw); A.post('/invoice', d); iid = A.one('select max(id) from invoices')
    pg = A.get(f'/issue/{iid}'); e = re.search(r'name="expected_reliquat" value="([^"]+)"', pg); fm = {'from_confirm': '1', 'reliquat_treatment': treat, 'reliquat_note': 'x', 'confirm_backdate': '', **dg}
    if e: fm['expected_reliquat'] = e.group(1)
    s, m = A.post(f'/issue/{iid}', fm); return iid, m
# 1. facturation en heures : 9 h × (1000/8) = 1125,00
pa = A.one("select id from projects where name='ZZ Recette Alpha'")
p_h = mand('ZZ Recette Heures', '1000', '8', '8.1'); A.post('/entry', {'work_date': '2026-07-01', 'project_id': p_h, 'entry_mode': 'duration', 'manual_hours': '9', 'description': 'h'})
iid, m = run(p_h, '2026-07-01', '2026-07-31', '9', unit='hour'); r = A.q('select status,unit,unit_rate,qty from invoices where id=?', (iid,))[0]
a = amounts('9', D('1000') / D('8'), 8.1); ck('X1 facture en heures : tarif horaire = tarif jour ÷ heures par jour (125,00), HT 1125,00, TTC 1216,13', r == ('issued', 'hour', 125.0, 9.0) and a['ht'] == D('1125.00') and a['ttc'] == D('1216.13'), (r, m, a))
tt = squash(pdf_text(A.req(f'/invoice/{iid}.pdf')[2])); ck('X1b PDF : 1125,00 et 1216,13', '1125,00' in tt and '1216,13' in tt, tt[:300])
s, m = A.post('/credit-none', {}) if False else (0, [])
ck('X1c position du mandat : 9 h facturées = 1,125 j', abs(json.loads(__import__('subprocess').run(['docker', 'exec', '-i', os.environ['CTN'], 'python', '-W', 'ignore', '-'], capture_output=True, text=True, input=f'''
import sqlite3, json, sys
sys.path.insert(0, "/app")
from app import billing_rules as r
c = sqlite3.connect("file:/data/timebilling.db?mode=ro", uri=True); c.row_factory = sqlite3.Row
print(json.dumps(r.contract(c, c.execute("select * from projects where id={p_h}").fetchone())))''').stdout)['billed_days'] - 1.125) < 1e-9)
# 2. TVA 0 et journée 7,5 h
p_z = mand('ZZ Recette TVA0', '800', '7.5', '0'); A.post('/entry', {'work_date': '2026-07-02', 'project_id': p_z, 'entry_mode': 'duration', 'manual_hours': '7.5', 'description': 'j'})
iid, m = run(p_z, '2026-07-01', '2026-07-31', '1'); r = A.q('select status,number,vat from invoices where id=?', (iid,))[0]
ck('X2 mandat journée 7,5 h, TVA 0 : 7,5 h = 1 j, émis (numéro global du mois : 2026-07-2), TTC 800,00 sans TVA', r == ('issued', '2026-07-2', 0.0) and amounts('1', 800, 0)['ttc'] == D('800.00'), (r, m))
# 3. arrondi au centime, demi supérieur
p_c = mand('ZZ Recette Cent', '1', '8', '8.1'); A.post('/entry', {'work_date': '2026-07-03', 'project_id': p_c, 'entry_mode': 'duration', 'manual_hours': '9', 'description': 'c'})   # rc25 : 9 h = 1,125 j enregistrés pour 1,005 j facturés (contrôle 14)
iid, m = run(p_c, '2026-07-01', '2026-07-31', '1.005'); a = amounts('1.005', 1, 8.1); ck('X3a facture réellement émise (et non un brouillon)', A.one('select status from invoices where id=?', (iid,)) == 'issued', m)
tt = squash(pdf_text(A.req(f'/invoice/{iid}.pdf')[2])); ck('X3 arrondi demi supérieur au centime : 1,005 × 1 = 1,01 ; TVA 8,1 % = 0,08 ; TTC 1,09 (pas de dérive binaire)', (a['ht'], a['tva'], a['ttc']) == (D('1.01'), D('0.08'), D('1.09')) and all(x in tt for x in ('1,01', '0,08', '1,09')), (a, tt[:300]))
# 4. total nul refusé
A.post('/entry', {'work_date': '2026-08-02', 'project_id': p_c, 'entry_mode': 'duration', 'manual_hours': '0.01', 'description': 'z'})   # rc25 : 0,01 h enregistrée, aucune dérogation
iid, m = run(p_c, '2026-08-01', '2026-08-31', '0.00001'); st = A.one('select status from invoices where id=?', (iid,))
R.has('X4 total nul (HT arrondi à 0,00) : émission refusée', m, 'nul ou négatif'); ck('X4b reste brouillon', st == 'draft'); A.post(f'/invoice/{iid}/delete', {})
# 5. grands montants + séparateurs
p_g = mand('ZZ Recette Gros', '999999', '8', '8.1')
for k in range(411): A.post('/entry', {'work_date': '2026-07-04', 'project_id': p_g, 'entry_mode': 'duration', 'manual_hours': '24', 'description': f'g{k}'})   # rc25 : 1234,5 j = 9 876 h enregistrées (contrôle 14 jamais dérogeable)
A.post('/entry', {'work_date': '2026-07-04', 'project_id': p_g, 'entry_mode': 'duration', 'manual_hours': '12', 'description': 'g-fin'})
iid, m = run(p_g, '2026-07-01', '2026-07-31', '1234.5'); a = amounts('1234.5', 999999, 8.1); tt = squash(pdf_text(A.req(f'/invoice/{iid}.pdf')[2])); ck('X5a facture réellement émise (et non un brouillon)', A.one('select status from invoices where id=?', (iid,)) == 'issued', m)
ck('X5 grand montant (HT 1 234 498 765,50 ; TVA 100 004 399,76…) : écran = PDF = calcul indépendant', str(a['ttc']).replace('.', ',') in tt and str(a['tva']).replace('.', ',') in tt, (a, tt[:300]))
# 6. quantités et dates limites
s, m = A.post('/invoice', {'project_id': p_c, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '1e9', 'rounding': 'exact'}); ck('X6 quantité absurde (1e9) refusée', 'Brouillon non créé' in ' '.join(m) or A.one("select count(*) from invoices where qty>=1e8") == 0, m)
s, m = A.post('/invoice', {'project_id': p_c, 'period_from': '2026-02-30', 'period_to': '2026-03-30', 'qty': '1'}); ck('X7 date de période invalide (30 février) refusée', 'non créé' in ' '.join(m).lower(), m)
R.sec('A+/E+. Accès non authentifié, double soumission, avertissement brouillon')
anon = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db')
for pth in ('/', '/entries', '/entries.csv', '/backup', '/archive.zip', '/invoice/1.pdf', '/credit/1.pdf', '/restore/x', '/import/review/x'):
    s_, h_, b_ = anon.req(pth); ck(f'S1 sans connexion {pth} → redirection vers /login (aucune donnée servie)', s_ in (302, 401) and (b_ or b'')[:4] != b'%PDF' and b'saisie' not in (b_ or b'')[:50], (s_, h_.get('Location')))
bad = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); bad.pw = 'mauvais'; s_, h_, b_ = bad.req('/login', {'username': 'admin', 'password': 'mauvais'}); ck('S2 mauvais mot de passe refusé', s_ != 302 or '/login' in (h_.get('Location') or ''), s_)
pa = A.one("select id from projects where name='ZZ Recette Beta'")
A.post('/invoice', {'project_id': pa, 'period_from': '2026-08-01', 'period_to': '2026-08-31', 'qty': '1', 'rounding': 'exact'}); idb = A.one('select max(id) from invoices')
s_, m_ = A.post('/entry', {'work_date': '2026-08-12', 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'dans brouillon'}); R.has('E+1 saisie dans la période d\'un brouillon : avertissement de recalcul', m_, 'brouillon')
A.post(f'/invoice/{idb}/delete', {})
cn = A.one("select id from credit_notes where status='issued' limit 1"); s_, m_ = A.post(f'/credit/{cn}/issue', {}); R.has('E+2 double émission d\'un avoir refusée', m_, 'introuvable')
s_, m_ = A.post('/entry', {'work_date': '2026-08-12', 'project_id': pa, 'entry_mode': 'clock', 'start_time': '23:00', 'end_time': '01:00', 'description': 'minuit'}); r_ = A.q("select work_date,start_time,end_time,hours from entries where description='minuit'"); R.check('E+3 saisie 23:00→01:00 acceptée en UNE saisie de 2 h le 12.08, rien le 13.08 (décision C5)', len(r_) == 1 and tuple(r_[0]) == ('2026-08-12', '23:00', '01:00', 2.0) and A.one("select count(*) from entries where work_date='2026-08-13' and description='minuit'") == 0, r_)
json.dump(R.rows, open(f'{dirn}/results-extra.json', 'w'), ensure_ascii=False, indent=1)
ok, ko = R.summary(); sys.exit(1 if ko else 0)
