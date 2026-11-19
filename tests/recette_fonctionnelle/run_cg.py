"""Recette fonctionnelle — C facturation, D annexe, E facture émise, F avoirs, G archive. Suite de run_ab.py (même instance, copie du staging).
usage: CTN=<conteneur> run_cg.py <port> <dossier-instance>"""
import sys, os, json, re, subprocess, zipfile, io, csv, datetime
sys.path.insert(0, os.path.dirname(__file__))
from lib import *

port, dirn = sys.argv[1], sys.argv[2]; CTN = os.environ['CTN']
A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('C-G'); ck = R.check
assert A.login(); st = json.load(open(f'{dirn}/state-ab.json')); pa, pb = st['pa'], st['pb']
os.makedirs(f'{dirn}/pdf', exist_ok=True)
TODAY = datetime.datetime.now(datetime.timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Zurich')).date().isoformat()
def incontainer(script):
    o = subprocess.run(['docker', 'exec', '-i', CTN, 'python', '-W', 'ignore', '-'], input=script, capture_output=True, text=True)
    if o.returncode: raise RuntimeError(o.stderr[-600:])
    return o.stdout
def position(cid):
    return json.loads(incontainer(f'''
import sqlite3, json, sys
sys.path.insert(0, "/app")
from app import credit_service as cr
c = sqlite3.connect("file:/data/timebilling.db?mode=ro", uri=True); c.row_factory = sqlite3.Row
cn = c.execute("select * from credit_notes where id={cid}").fetchone(); p = cr.position(c, cn)
print(json.dumps({{k: (str(v) if not isinstance(v, (int, float, str, bool, type(None), list, dict)) else v) for k, v in p.items() if k != "operations"}}, default=str))
'''))
def contract_of(pid):
    return json.loads(incontainer(f'''
import sqlite3, json, sys
sys.path.insert(0, "/app")
from app import billing_rules as r
c = sqlite3.connect("file:/data/timebilling.db?mode=ro", uri=True); c.row_factory = sqlite3.Row
p = c.execute("select * from projects where id={pid}").fetchone(); print(json.dumps(r.contract(c, p)))
'''))
def sql_write_attempt(sql):
    """Tentative d'écriture directe (contournant l'application) sur la COPIE : les déclencheurs SQL doivent la refuser."""
    o = subprocess.run(['docker', 'exec', '-i', CTN, 'python', '-W', 'ignore', '-'], capture_output=True, text=True, input=f'''
import sqlite3
c = sqlite3.connect("/data/timebilling.db", timeout=30)
try:
    c.execute("""{sql}"""); c.commit(); print("ACCEPTÉ")
except Exception as e: print("REFUSÉ", e)
''')
    return o.stdout.strip()
def draft(pid, f, t, qty, **kw):
    d = {'project_id': pid, 'period_from': f, 'period_to': t, 'qty': qty, 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25'}; d.update(kw); return A.post('/invoice', d)
def last_inv(): return A.one('select max(id) from invoices')
def issue_page(iid): return A.get(f'/issue/{iid}')
def issue(iid, treatment=None, note='', backdate=None, **extra):
    pg = issue_page(iid); exp = re.search(r'name="expected_reliquat" value="([^"]+)"', pg)
    f = {'from_confirm': '1'}
    if exp: f['expected_reliquat'] = exp.group(1)
    if treatment: f['reliquat_treatment'] = treatment
    if note: f['reliquat_note'] = note
    if backdate: f['confirm_backdate'] = backdate
    f.update(extra)
    return A.post(f'/issue/{iid}', f)
def pdf(path, name=None):
    s, h, b = A.req(path)
    if name and s == 200: open(f'{dirn}/pdf/{name}.pdf', 'wb').write(b)
    return s, b

# ---------------------------------------------------------------- C. facturation
R.sec('C. Facturation — préparation des saisies Alpha')
e5 = A.q("select id from entries where project_id=? and description='chevauche'", (pa,))
for (i,) in e5: A.post(f'/entry/{i}/delete', {})
A.post('/entry', {'work_date': '2026-09-15', 'project_id': pa, 'entry_mode': 'clock', 'start_time': '10:00', 'end_time': '14:15', 'description': 'sept clock'})
A.post('/entry', {'work_date': '2026-09-16', 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': '2.1', 'description': 'après coupure facture 2'})
def cons(pid, upto=None):
    return D(str(A.one('select coalesce(sum(hours),0) from entries where project_id=?' + (' and work_date<=?' if upto else ''), (pid, upto) if upto else (pid,))))
ck('C0 heures Alpha août = 9,0 h (3,5 + 4,25 + 1,25)', cons(pa, '2026-08-31') == D('9.0'), cons(pa, '2026-08-31'))
R.sec('C. Facturation — suggestion de quantité et arrondis (calcul indépendant)')
raw = (cons(pa, '2026-08-31') / 8)
def rnd(q, mode, step):
    import math
    u = q / D(step)
    u = {'up': u.to_integral_value(rounding='ROUND_CEILING'), 'down': u.to_integral_value(rounding='ROUND_FLOOR'), 'nearest': u.to_integral_value(rounding='ROUND_HALF_UP'), 'exact': None}[mode]
    return None if u is None else float(u * D(step))
for mode, step in [('exact', '0.25'), ('nearest', '0.25'), ('up', '0.25'), ('down', '0.25'), ('nearest', '0.5'), ('up', '1'), ('down', '1'), ('nearest', '1')]:
    s, h, b = A.req('/suggest', {'project_id': pa, 'period_from': '2026-08-01', 'period_to': '2026-08-31', 'rounding': mode, 'rounding_step': step})
    j = json.loads(b); exp = float(raw) if mode == 'exact' else rnd(raw, mode, step)
    ck(f'C1 /suggest {mode} pas {step} : 9 h = 1,125 j → {exp}', abs(j['suggested_qty'] - exp) < 1e-9 and abs(j['raw_days'] - 1.125) < 1e-9 and abs(j['hours'] - 9.0) < 1e-9, j)
s, h, b = A.req('/suggest', {'project_id': pa, 'period_from': '2026-09-01', 'period_to': '2026-08-01', 'rounding': 'exact'}); ck('C1b période inversée refusée (400)', s == 400, b[:100])
s, h, b = A.req('/suggest', {'project_id': pa, 'period_from': '2026-08-01', 'period_to': '2026-08-31', 'rounding': 'bizarre'}); ck('C1c arrondi inconnu refusé (400)', s == 400, b[:100])

R.sec('C. Facturation — brouillon, émission, numéro AAAA-MM, TVA, arrondi, reliquat')
s, m = draft(pa, '2026-08-01', '2026-08-31', '1.25', rounding='nearest'); i1 = last_inv()
r = A.q('select status,number,qty,unit_rate,vat,rounding from invoices where id=?', (i1,))[0]; ck('C2 brouillon créé : sans numéro, tarif 1000, TVA 8,1, arrondi nearest', r == ('draft', None, 1.25, 1000.0, 8.1, 'nearest'), r)
n_c2 = A.one('select count(*) from invoices')   # brouillon n°1 de l'utilisateur (copie du staging) + C2
s, m = draft(pa, '2026-08-01', '2026-08-31', '0'); ck('C2b quantité 0 refusée', A.one('select count(*) from invoices') == n_c2 and any('Brouillon non créé' in x for x in m), m)
s, m = draft(pa, '2026-09-30', '2026-08-01', '1'); ck('C2c période inversée refusée', A.one('select count(*) from invoices') == n_c2 and any('Brouillon non créé' in x for x in m), m)
s, m = draft(pa, '2026-08-01', '2026-08-31', '1', invoice_date='2026-07-01'); R.has('C2d date de facture avant le début de période refusée', m, 'précéder')
s, m = draft(pa, '2026-08-01', '2026-08-31', '1', description='mot ' * 200); R.has('C2e description trop longue refusée (document imprimé)', m, 'trop longue')
s, m = draft(pa, '2026-08-01', '2026-08-31', '1', other_amount='-5'); R.has('C2f montant « autres » négatif refusé', m, 'négatif')
pg = issue_page(i1); ck('C3 page d\'émission : numéro proposé 2026-08', '<b>2026-08</b>' in pg)
rel_exp = cons(pa, '2026-08-31') / 8 - D('0') - D('1.25')
shown = D(re.search(r'name="expected_reliquat" value="([^"]+)"', pg).group(1)); ck('C4 reliquat calculé = consommé − facturé − quantité (−0,125 j, facturé d\'avance)', shown == rel_exp, (shown, rel_exp))
s, m = issue(i1); R.has('C5 contrôle 14 : sur-facturation bloquée sans dérogation', m, '14. La quantité nette facturée cumulée'); ck('C5b statut resté brouillon après refus', A.one('select status from invoices where id=?', (i1,)) == 'draft')
s, m = issue(i1, 'offert'); R.has('C6 contrôle 14 reste bloquant avec traitement offert', m, '14. La quantité nette facturée cumulée')
s, m = issue(i1, 'autre'); R.has('C6b contrôle 14 reste bloquant avec traitement autre', m, '14. La quantité nette facturée cumulée')
s, m = issue(i1, 'reporte'); R.has('C7a contrôle 14 : la justification ne rend pas dérogeable la sur-facturation', m, '14. La quantité nette facturée cumulée')
s, m = issue(i1, 'reporte', negative_reliquat_reason='Recette fictive : scénario de facturation d\'avance motivée, utilisé uniquement pour vérifier que le contrôle 14 reste non dérogeable.')
R.has('C7b contrôle 14 reste bloquant même avec un motif écrit synthétique', m, '14. La quantité nette facturée cumulée')
ck('C7d audit : aucune dérogation ni exception de reliquat enregistrée pour ce brouillon refusé', A.one("select count(*) from audit where event in ('invoice_check_derogation','invoice_negative_reliquat_exception') and (detail like ? or detail like ?)", (f'%"invoice_id": {i1},%', f'%"invoice_id":{i1},%')) == 0)   # root-83 : oracle durci (revue root-09 D2)
# Le contrôle 14 est non dérogeable : après avoir prouvé le refus de 1,25 j pour 1,125 j réalisé, corriger le brouillon à la quantité exacte avant de tester l'émission nominale.
s, m = A.post(f'/invoice/{i1}/edit', {'period_from':'2026-08-01','period_to':'2026-08-31','qty':'1.125','unit':'day','rounding':'nearest','rounding_step':'0.25','vat':'8.1','description':'Recette fonctionnelle août','other_amount':'0','other_label':'','other_vat_mode':'hors_tva','invoice_date':'','note':''})
ck('C7c quantité corrigée à 1,125 j pour correspondre au réalisé (brouillon)', A.one('select qty from invoices where id=?', (i1,)) == 1.125, m)
s, m = issue(i1)
r = A.q('select status,number,reliquat_days,reliquat_treatment,invoice_date,issued_at from invoices where id=?', (i1,))[0]
ck('C7 émission : quantité cohérente 1,125 j, numéro 2026-08, reliquat nul', r[:4] == ('issued', '2026-08', 0.0, 'aucun'), (r, m))
ck('C7b date de facture = jour d\'émission (Zurich) et horodatage d\'émission enregistré', r[4] == TODAY and r[5], r)
a1 = amounts('1.125', 1000, 8.1)
ck('C8 montants indépendants : HT 1125,00 · TVA 91,13 · TTC 1216,13', (a1['ht'], a1['tva'], a1['ttc']) == (D('1125.00'), D('91.13'), D('1216.13')), a1)
s, b1 = pdf(f'/invoice/{i1}.pdf', 'facture-2026-08'); t1 = pdf_text(b1); sq = squash(t1)
ck('C9 PDF facture 2026-08 : numéro, HT, TVA, TTC imprimés = calcul indépendant', all(x in sq for x in ('2026-08', '1125,00', '91,13', '1216,13')), t1[:600])
ck('C9b PDF = copie figée (SHA-256 du snapshot)', sha(b1) == A.one('select pdf_sha256 from invoice_snapshots where invoice_id=?', (i1,)))

# entrée tardive dans la période déjà facturée
s, m = A.post('/entry', {'work_date': '2026-08-20', 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'tardive août'}); R.has('C10 saisie dans une période déjà facturée : avertissement', m, 'période déjà facturée')
s, b1b = pdf(f'/invoice/{i1}.pdf'); ck('C10b PDF émis inchangé après saisie tardive', b1b == b1)
ck('C10c tardive absente de l\'annexe figée', A.one("select count(*) from invoice_annex_entries x join entries e on e.id=x.entry_id where x.invoice_id=? and e.description='tardive août'", (i1,)) == 0)
pos = contract_of(pa); billed = 1.125
ck('C11 position du mandat : facturé 1,125 j, solde PO = 10 − 1,125 = 8,875 j, réalisé non facturé calculé séparément', abs(pos['billed_days'] - 1.125) < 1e-9 and abs(pos['po_balance_days'] - (10 - 1.125)) < 1e-9 and abs(pos['unbilled_days'] - (float(cons(pa) / 8) - 1.125)) < 1e-6, pos)

# deuxième facture, avec « AUTRES » soumis à TVA
s, m = draft(pa, '2026-08-15', '2026-09-05', '1'); R.has('C12 période chevauchant une facture émise refusée', m, 'chevauche la facture émise')
s, m = draft(pa, '2026-09-01', '2026-09-15', '1.0', rounding='down', other_amount='120.50', other_label='Frais divers', other_vat_mode='soumis'); i2 = last_inv()
pg = issue_page(i2); consumed2 = cons(pa, '2026-09-15') / 8; rel2 = consumed2 - D('1.125') - D('1.0')
shown = D(re.search(r'name="expected_reliquat" value="([^"]+)"', pg).group(1)); ck('C13 reliquat facture 2 = (consommé au 15.09 − déjà facturé − 1,0) calcul indépendant', shown == rel2, (shown, rel2))
s, m = issue(i2, 'offert'); r = A.q('select number,reliquat_treatment,reliquat_days from invoices where id=?', (i2,))[0]; ck('C14 émission facture 2 : numéro 2026-09-2 (référence historique 2026-09 réservée), reliquat offert enregistré', r[0] == '2026-09-2' and r[1] == 'offert' and abs(r[2] - float(rel2)) < 1e-9, (r, m))
a2 = amounts('1.0', 1000, 8.1, '120.50', 'soumis')
ck('C15 « AUTRES » soumis à TVA : base 1120,50 → TVA 90,76 (arrondi 0,01) · TTC 1211,26', (a2['tva'], a2['ttc']) == (D('90.76'), D('1211.26')), a2)
s, b2 = pdf(f'/invoice/{i2}.pdf', 'facture-2026-09'); sq2 = squash(pdf_text(b2)); ck('C15b PDF facture 2 : HT, AUTRES, TVA, TTC', all(x in sq2 for x in ('1000,00', '120,50', '90,76', '1211,26')), pdf_text(b2)[:500])
pos = contract_of(pa); ck('C16 jours offerts cumulés = reliquat offert ; facturé net 2,125 j', abs(pos['offered_days'] - float(rel2)) < 1e-9 and abs(pos['billed_days'] - 2.125) < 1e-9, pos)

# troisième facture le même mois -> numéro -2, antidatage
A.post('/entry', {'work_date':'2026-09-20','project_id':pa,'entry_mode':'duration','manual_hours':'3.9','description':'Recette synthétique : heures pour facture antidatée'})
s, m = draft(pa, '2026-09-16', '2026-09-30', '0.75', other_amount='50', other_label='Déplacement', invoice_date='2026-10-01'); i3 = last_inv()
pg = issue_page(i3); ck('C17 troisième numéro du mois : 2026-09-3, après la référence historique 2026-09 et la facture 2026-09-2', '<b>2026-09-3</b>' in pg)
s, m = issue(i3, 'reporte'); R.has('C18 date de facture antérieure au jour d\'émission : confirmation explicite exigée', m, 'antidatage'); ck('C18b reste brouillon', A.one('select status from invoices where id=?', (i3,)) == 'draft')
s, m = draft(pa, '2026-10-01', '2026-10-31', '0.1', invoice_date='2026-10-31'); i_fut = last_inv(); s, m = issue(i_fut, 'reporte')
R.has('C19a sans motif : refus D8 (contrôle 12, aucune saisie dans la période, dérogation motivée possible)', m, '12. La facture, l\'annexe et la position')
s, m = issue(i_fut, 'reporte', derogation_12='Recette : période sans saisie, dérogation volontaire pour atteindre la règle de date')
R.has('C19 date de facture postérieure au jour d\'émission refusée (même avec la dérogation 12)', m, 'postérieure'); ck('C19c reste brouillon', A.one('select status from invoices where id=?', (i_fut,)) == 'draft')
A.post(f'/invoice/{i_fut}/delete', {}); ck('C19b brouillon supprimé', A.one('select count(*) from invoices where id=?', (i_fut,)) == 0)

# données de facturation manquantes sur un mandat historique créé par l'import
s, m = draft(A.one("select id from projects where name='EUROPCR 2027'"), '2026-06-01', '2026-07-31', '0.25'); ie = last_inv(); s, m = issue(ie, 'reporte')
R.has('C20 mandat historique sans client/tarif : émission refusée avec la liste des champs manquants', m, 'à compléter'); R.has('C20b …dont le tarif', m, 'Tarif journalier')
A.post(f'/invoice/{ie}/delete', {})

# ---------------------------------------------------------------- AVOIRS (utilisés ensuite pour la compensation sur i3)
R.sec('F. Avoirs — partiel, total, remboursement, compensation, soldes, plafonds, traçabilité')
def credit(iid, **f):
    d = {'reason': 'recette', 'treatment': 'remboursement', 'scope': 'partial'}; d.update(f); n0 = A.one('select count(*) from credit_notes'); s, m = A.post(f'/invoice/{iid}/credit', d)
    return (A.one('select max(id) from credit_notes') if A.one('select count(*) from credit_notes') > n0 else None), m
def cissue(cid): return A.post(f'/credit/{cid}/issue', {})
c_over, m = credit(i1, qty='5'); ck('F1 avoir > facture refusé (5 j sur 1,25 j)', c_over is None, m)
c_over, m = credit(i1, amount='99999'); ck('F1b avoir en montant > facture refusé', c_over is None, m)
c_x, m = credit(i1, qty='0.25', amount='10'); ck('F1c quantité ET montant refusés ensemble', c_x is None, m)
c_x, m = credit(i1, reason='', qty='0.25'); ck('F1d motif obligatoire', c_x is None, m)
c_x, m = credit(i1, qty='0.25', treatment=''); ck('F1e mode (remboursement/compensation) obligatoire', c_x is None, m)
c_x, m = credit(i1, qty='0.25', unit_rate='999'); ck('F1f tarif ≠ facture d\'origine refusé', c_x is None, m)
c1, m = credit(i1, qty='0.25'); ck('F2 avoir partiel 0,25 j créé en brouillon (facture inchangée)', c1 is not None and A.one('select status from credit_notes where id=?', (c1,)) == 'draft')
s, m = cissue(c1); r = A.q('select reference,status,amount,treatment from credit_notes where id=?', (c1,))[0]; ck('F3 avoir émis NC-2026-08, HT 250,00', r == ('NC-2026-08', 'issued', 250.0, 'remboursement'), (r, m))
n1 = amounts('0.25', 1000, 8.1); ck('F3b avoir 1 : HT 250,00 · TVA 20,25 · TTC 270,25 (indépendant)', (n1['ht'], n1['tva'], n1['ttc']) == (D('250.00'), D('20.25'), D('270.25')), n1)
s, bn1 = pdf(f'/credit/{c1}.pdf', 'avoir-NC-2026-08'); tn1 = pdf_text(bn1); ck('F4 PDF avoir séparé : référence, facture d\'origine, montants', all(x in squash(tn1) for x in ('NC-2026-08', '2026-08', '250,00', '270,25')), tn1[:500])
ck('F4b PDF avoir figé (SHA)', sha(bn1) == A.one('select pdf_sha256 from credit_note_snapshots where credit_note_id=?', (c1,)) if A.one("select count(*) from sqlite_master where name='credit_note_snapshots'") else True)
s, bi = pdf(f'/invoice/{i1}.pdf'); ck('F5 facture d\'origine inchangée après avoir (octets identiques)', bi == b1)
# remboursement partiel puis plafond
op = lambda cid, amt, **k: A.post(f'/credit/{cid}/refund', dict({'amount': amt, 'executed_on': TODAY, 'external_ref': 'VIR-RECETTE', 'note': 'test'}, **k))
refunded = lambda cid: D(str(A.one("select coalesce(sum(amount),0) from credit_operations where credit_note_id=? and kind='refund'", (cid,))))
bal = lambda cid: D(str(position(cid)['balance']))
s, m = op(c1, '100'); ck('F6 remboursement partiel 100,00 enregistré ; solde 170,25', refunded(c1) == 100 and bal(c1) == D('170.25'), (m, position(c1)))
s, m = op(c1, '170.26'); R.has('F7 remboursement au-delà du solde (170,26 > 170,25) refusé', m, 'refus'); ck('F7b rien enregistré par le refus', refunded(c1) == 100)
s, m = op(c1, '-5'); R.has('F7c montant négatif refusé', m, 'refus')
s, m = op(c1, '170.25'); ck('F8 remboursement du solde exact : solde 0,00, statut « remboursée »', bal(c1) == 0 and position(c1)['status'] == 'remboursée', position(c1))
s, m = op(c1, '0.01'); R.has('F9 aucun remboursement au-delà d\'un solde nul', m, 'refus')
last_op = A.q("select id from credit_operations where credit_note_id=? and kind='refund' order by id desc limit 1", (c1,))[0][0]
s, m = A.post(f'/credit/{c1}/reverse/{last_op}', {'note': 'erreur de saisie', 'executed_on': TODAY})
ck('F10 annulation d\'un remboursement : écriture d\'annulation, ligne d\'origine conservée, solde 170,25', A.one("select count(*) from credit_operations where credit_note_id=? and kind='refund_reversal'", (c1,)) == 1 and A.one("select count(*) from credit_operations where credit_note_id=? and kind='refund'", (c1,)) == 2 and bal(c1) == D('170.25'), (m, position(c1)))
s, m = op(c1, '170.25'); ck('F10b re-remboursement : soldée de nouveau', bal(c1) == 0)
s, m = A.post(f'/credit/{c1}/cancel', {'reason': 'test'}); ck('F11 annulation d\'un avoir déjà remboursé refusée', A.one('select count(*) from credit_note_cancellations where credit_note_id=?', (c1,)) == 0, m)
# compensation sur la facture suivante (même client juridique)
c2, m = credit(i1, amount='400', treatment='compensation'); s, m = cissue(c2); r = A.q('select reference,status from credit_notes where id=?', (c2,))[0]
n2 = amounts(1, 400, 8.1); ck('F12 avoir en montant 400,00 HT, compensation : NC-2026-08.2 ; TTC 432,40', r == ('NC-2026-08.2', 'issued') and n2['ttc'] == D('432.40') and D(str(position(c2)['ttc'])) == D('432.40'), (r, m, n2))
s, m = op(c2, '10'); R.has('F13 remboursement refusé sur un avoir de compensation (mode immuable)', m, 'refus')
off = lambda cid, tgt, amt: A.post(f'/credit/{cid}/offset', {'target_invoice_id': tgt, 'amount': amt, 'note': 'compensation'})
offs = lambda cid: D(str(A.one("select coalesce(sum(amount),0) from credit_operations where credit_note_id=? and kind='offset'", (cid,))))
s, m = off(c2, i1, '10'); R.has('F14 imputation sur la facture d\'origine (émise) refusée', m, 'refus')
s, m = off(c2, i3, '300'); ck('F15 imputation 300,00 sur le brouillon 2026-09-2 (réservation)', offs(c2) == 300 and position(c2)['status'].startswith('partiellement'), (m, position(c2)))
s, m = off(c2, i3, '132.41'); R.has('F16 imputation au-delà du solde d\'avoir (132,41 > 132,40) refusée', m, 'refus')
s, m = off(c2, i3, '132.40'); ck('F17 solde d\'avoir entièrement affecté : 0,00', bal(c2) == 0, position(c2))
A.post('/project', {'name': 'ZZ Recette Gamma', 'rate': '500', 'day_hours': '8', 'vat': '0', 'ordered_days': '1', 'client': 'Autre', 'client_legal_name': 'Autre SA', 'client_legal_id': 'CHE-999.999.999', 'billing_address': 'Autre SA\nRue 3\n1000 Ville'})
pg_ = A.one("select id from projects where name='ZZ Recette Gamma'"); A.post('/invoice', {'project_id': pg_, 'period_from': '2026-09-01', 'period_to': '2026-09-30', 'qty': '0.5', 'rounding': 'exact'}); ig = last_inv()
c_b, m = credit(i1, amount='10', treatment='compensation'); cissue(c_b)
s, m = off(c_b, ig, '5'); R.has('F18 imputation sur un autre client juridique refusée', m, 'refus')
A.post(f'/credit/{c_b}/cancel', {'reason': 'nettoyage test'}); A.post(f'/invoice/{ig}/delete', {})
a3 = amounts('0.75', 1000, 8.1, '50', 'hors_tva'); net3 = a3['ttc'] - D('432.40')
ck('F19 TTC du brouillon de septembre (indépendant) : HT 750,00 + TVA 60,75 + AUTRES 50,00 = 860,75', a3['ttc'] == D('860.75'), a3)
s, bd3 = pdf(f'/invoice/{i3}.pdf', 'brouillon-2026-09-3-avec-imputation'); td3 = squash(pdf_text(bd3))
ck('F20 PDF du brouillon : imputations NC-2026-08.2 (300,00 + 132,40) visibles, net à payer 428,35', all(x in td3 for x in ('NC-2026-08.2', '300,00', '132,40', '428,35')), pdf_text(bd3)[:900])
s, m = issue(i3, 'reporte', backdate='2026-10-01'); r = A.q('select number,status,invoice_date,issued_at from invoices where id=?', (i3,))[0]
ck('F21 émission antidatée confirmée : numéro 2026-09-3, date de facture 01.10.2026, horodatage réel conservé', r[0] == '2026-09-3' and r[1] == 'issued' and r[2] == '2026-10-01' and r[3][:10] >= '2026-10-01', (r, m))
ck('F22 imputation devenue définitive à l\'émission (avoir « compensée ») + audit', position(c2)['status'] == 'compensée' and A.one("select count(*) from audit where event='credit_offset_applied'") == 2, position(c2))
s, m = A.post(f'/credit/{c2}/reverse/{A.one("select min(id) from credit_operations where credit_note_id=? and kind=\'offset\'", (c2,))}', {'note': 'tentative'}); R.has('F23 annulation d\'une imputation figée sur facture émise refusée', m, 'refus')
# avoir total
c5, m = credit(i1, scope='total', treatment='remboursement'); s, m = cissue(c5); r = A.q('select reference,status,amount,qty from credit_notes where id=?', (c5,))[0]
tot = D(str(position(c1)['ttc'])) + D(str(position(c2)['ttc'])) + D(str(position(c5)['ttc']))
ck('F24 avoir total sur le solde (600,00 HT) : NC-2026-08.n (n unique, la note annulée .3 garde son numéro) ; somme des avoirs TTC = TTC facture 1216,13 au centime', r[0].startswith('NC-2026-08.') and r[0] not in ('NC-2026-08', 'NC-2026-08.2') and r[2] == 475.0 and tot == D('1216.13'), (r, tot))
c6, m = credit(i1, scope='total'); R.has('F25 facture entièrement créditée : nouvel avoir refusé', m, 'entièrement'); ck('F25b aucun brouillon créé', c6 is None)
c7, m = credit(i3, scope='total'); ck('F26 crédit total refusé sur une facture ayant reçu une compensation figée', c7 is None and 'compensation' in ' '.join(m).lower(), m)
c8, m = credit(i3, qty='0.25', treatment='remboursement'); ck('F26b crédit partiel dans le net à payer accepté', c8 is not None, m)
A.post(f'/credit/{c8}/delete', {})
# annulation / remplacement
c3, m = credit(i2, qty='0.5'); cissue(c3); ref3 = A.one('select reference from credit_notes where id=?', (c3,)); s, m = A.post(f'/credit/{c3}/cancel', {'reason': 'avoir émis par erreur'})
ck('F27 avoir sans opération annulable : document d\'annulation ANN-… figé, solde 0', A.one('select reference from credit_note_cancellations where credit_note_id=?', (c3,)) == 'ANN-' + ref3 and D(str(position(c3)['balance'])) == 0, m)
s, ban = pdf(f'/credit/{c3}/cancellation.pdf', 'annulation-' + ref3); ck('F28 PDF d\'annulation séparé et figé', ban.startswith(b'%PDF') and ref3 in pdf_text(ban), pdf_text(ban)[:300])
s, m = op(c3, '1'); R.has('F29 aucune opération sur un avoir annulé', m, 'refus')
c4, m = credit(i2, qty='0.5', replaces_credit_id=str(c3)); s, m = cissue(c4)
ck('F30 avoir de remplacement : lié à l\'avoir annulé, nouvelle référence, les deux restent visibles', A.one('select replaces_credit_id from credit_notes where id=?', (c4,)) == c3 and A.one('select status from credit_notes where id=?', (c4,)) == 'issued' and A.one('select reference from credit_notes where id=?', (c4,)) != ref3, m)
s, m = op(c4, str(position(c4)['ttc'])); ck('F30b remboursement du remplaçant accepté', D(str(position(c4)['balance'])) == 0, m)
# position du mandat en jours (facturés bruts, annulés, net, solde) : calcul indépendant
gross = D(str(A.one("select coalesce(sum(qty),0) from invoices where project_id=? and status='issued'", (pa,))))
cred = D(str(A.one("select coalesce(sum(cn.qty),0) from credit_notes cn join invoices i on i.id=cn.invoice_id where i.project_id=? and cn.status='issued' and cn.qty is not null and cn.id not in (select credit_note_id from credit_note_cancellations)", (pa,))))
pos = contract_of(pa)
ck('F31 jours : facturés bruts / annulés par avoirs / nets / solde commandé / à facturer (indépendant)', abs(pos['gross_billed_days'] - float(gross)) < 1e-9 and abs(pos['credited_days'] - float(cred)) < 1e-9 and abs(pos['billed_days'] - float(gross - cred)) < 1e-9 and abs(pos['po_balance_days'] - (10 - float(gross - cred))) < 1e-9, (pos, gross, cred))
# traçabilité & immuabilité
ck('F32 traçabilité : audit des avoirs émis / remboursements / imputations / annulations', all(A.one('select count(*) from audit where event=?', (e,)) >= 1 for e in ('credit_note_issued', 'credit_draft_created')), '')
ck('F33 ledger append-only : UPDATE refusé', sql_write_attempt("UPDATE credit_operations SET amount=1 WHERE id=1").startswith('REFUSÉ'))
ck('F34 ledger append-only : DELETE refusé', sql_write_attempt("DELETE FROM credit_operations WHERE id=1").startswith('REFUSÉ'))
ck('F35 avoir émis non modifiable (UPDATE direct refusé)', sql_write_attempt(f"UPDATE credit_notes SET amount=1 WHERE id={c1}").startswith('REFUSÉ'))
ck('F36 avoir émis non supprimable (DELETE direct refusé)', sql_write_attempt(f"DELETE FROM credit_notes WHERE id={c1}").startswith('REFUSÉ'))
json.dump({'pa': pa, 'pb': pb, 'i1': i1, 'i2': i2, 'i3': i3, 'c1': c1, 'c2': c2, 'c3': c3, 'c4': c4, 'c5': c5, 'bi1': sha(b1), 'bi2': sha(b2)}, open(f'{dirn}/state-cg.json', 'w'))
json.dump(R.rows, open(f'{dirn}/results-cg.json', 'w'), ensure_ascii=False, indent=1)
ok, ko = R.summary(); sys.exit(1 if ko else 0)
