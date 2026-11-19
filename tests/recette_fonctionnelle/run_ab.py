"""Recette fonctionnelle — sections A (saisie des temps) et B (mandats), sur une COPIE de la base staging (historique inclus).
usage: run_ab.py <port> <dossier-instance>"""
import sys, os, json, re, sqlite3, tempfile
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app import billing_rules as billing_rules_test
from lib import *

port, dirn = sys.argv[1], sys.argv[2]
A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('A+B'); ck = R.check
assert A.login(), 'connexion impossible'
HIST0 = entries_digest(A.db, only_import=True); N0 = A.one('select count(*) from entries'); P0 = A.one('select count(*) from projects')
R.sec('Préalable : base de départ = copie cohérente du staging')
inv0 = A.q("select count(*), coalesce(sum(status='issued'),0), coalesce(sum(number is not null),0) from invoices")[0]
ck('copie : 2 247 saisies importées / 24 mandats / aucune facture Time Billing émise ou numérotée', (HIST0[1], P0, inv0[1], inv0[2]) == (2247, 24, 0, 0), (HIST0, P0, inv0))

# --- paramètres émetteur + mandats fictifs ----------------------------------------------------------
A.post('/settings', {'issuer_name': 'Émetteur Recette Sàrl', 'issuer_address': 'Rue de la Recette 1\n1200 Genève', 'account_holder': 'Émetteur Recette Sàrl', 'iban': 'CH00 0000 0000 0000 0000 0',
                     'payment_terms': 'Paiement à 30 jours', 'issuer_vat_number': 'CHE-000.000.000 TVA', 'issuer_rc': 'CHE-000.000.000'})
def mandat(name, rate, dh, vat, od, **kw):
    f = {'name': name, 'rate': rate, 'day_hours': dh, 'vat': vat, 'ordered_days': od, 'client': 'Client Recette', 'client_legal_name': 'Client Recette SA', 'client_legal_id': 'CHE-000.000.042',
         'billing_address': 'Client Recette SA\nRue 2\n1000 Ville'}; f.update(kw); return A.post('/project', f)
R.sec('B. Mandats — création / modification / validation')
s, m = mandat('ZZ Recette Alpha', '1000', '8', '8.1', '10')
ck('B1 création mandat Alpha', A.one("select count(*) from projects where name='ZZ Recette Alpha'") == 1, m)
pa = A.one("select id from projects where name='ZZ Recette Alpha'")
s, m = mandat('ZZ Recette Alpha', '1', '8', '0', '1'); R.has('B2 nom en double refusé', m, 'porte déjà ce nom')
s, m = mandat('ZZ Recette Neg', '-5', '8', '0', '1'); ck('B3 tarif négatif refusé', A.one("select count(*) from projects where name='ZZ Recette Neg'") == 0, m)
s, m = mandat('ZZ Recette Dh0', '10', '0', '0', '1'); ck('B4 heures par jour = 0 refusé', A.one("select count(*) from projects where name='ZZ Recette Dh0'") == 0, m)
s, m = mandat('ZZ Recette Vat', '10', '8', '120', '1'); ck('B5 TVA > 100 refusée', A.one("select count(*) from projects where name='ZZ Recette Vat'") == 0, m)
s, m = mandat('', '10', '8', '0', '1'); R.has('B6 nom vide refusé', m, 'nom du projet obligatoire')
mandat('ZZ Recette Beta', '800', '7.5', '0', '5', client_legal_id='CHE-000.000.043'); pb = A.one("select id from projects where name='ZZ Recette Beta'")
ck('B7 mandat Beta (journée 7,5 h, TVA 0) créé', pb is not None)
# modification tarif / jours commandés (aucune facture encore)
s, m = A.post(f'/project/{pa}/edit', {'name': 'ZZ Recette Alpha', 'rate': '1000', 'day_hours': '8', 'vat': '8.1', 'ordered_days': '12', 'client': 'Client Recette', 'client_legal_name': 'Client Recette SA',
                                       'client_legal_id': 'CHE-000.000.042', 'billing_address': 'Client Recette SA\nRue 2\n1000 Ville'})
ck('B8 modification jours commandés 10 → 12', A.one('select ordered_days from projects where id=?', (pa,)) == 12, m)
A.post(f'/project/{pa}/edit', {'name': 'ZZ Recette Alpha', 'rate': '1000', 'day_hours': '8', 'vat': '8.1', 'ordered_days': '10', 'client': 'Client Recette', 'client_legal_name': 'Client Recette SA',
                               'client_legal_id': 'CHE-000.000.042', 'billing_address': 'Client Recette SA\nRue 2\n1000 Ville'})

# --- A. SAISIE -----------------------------------------------------------------------------------
R.sec('A. Saisie des temps')
def ent(**f): return A.post('/entry', f)
ids = lambda: A.q('select id from entries order by id desc limit 1')[0][0]
s, m = ent(work_date='2026-08-03', project_id=pa, entry_mode='clock', start_time='09:00', end_time='12:30', description='clock 3h30')
e1 = ids(); r = A.q('select start_time,end_time,hours,description from entries where id=?', (e1,))[0]
ck('A1 saisie début/fin 09:00–12:30 → 3,5 h exactes', r == ('09:00', '12:30', 3.5, 'clock 3h30'), r)
s, m = ent(work_date='2026-08-04', project_id=pa, entry_mode='duration', manual_hours='4,25', description='durée manuelle'); e2 = ids()
r = A.q('select start_time,end_time,hours from entries where id=?', (e2,))[0]; ck('A2 durée manuelle « 4,25 » (virgule) → 4,25 h, sans horaires', r == ('', '', 4.25), r)
s, m = ent(work_date='2026-08-31', project_id=pa, entry_mode='clock', start_time='08:00', end_time='09:15', manual_hours='99', description='exclusivité'); e3 = ids()
r = A.q('select hours from entries where id=?', (e3,))[0][0]; ck('A3 mode début/fin : la durée manuelle fournie en plus est ignorée (1,25 h, pas 99)', r == 1.25, r)
s, m = ent(work_date='2026-09-01', project_id=pa, entry_mode='duration', start_time='08:00', end_time='10:00', manual_hours='6', description='exclusivité 2'); e4 = ids()
r = A.q('select start_time,end_time,hours from entries where id=?', (e4,))[0]; ck('A4 mode durée : horaires fournis en plus ignorés (6 h, pas de début/fin)', r == ('', '', 6.0), r)
n = A.one('select count(*) from entries')
for lbl, f, needle in [('fin = début', dict(entry_mode='clock', start_time='10:00', end_time='10:00'), 'identique'),
                       ('horaire manquant', dict(entry_mode='clock', start_time='10:00', end_time=''), 'renseigner'), ('format HH:MM invalide', dict(entry_mode='clock', start_time='25:00', end_time='26:00'), 'invalide'),
                       ('durée vide', dict(entry_mode='duration', manual_hours=''), 'renseigner la durée'), ('durée 0', dict(entry_mode='duration', manual_hours='0'), 'positive'),
                       ('durée négative', dict(entry_mode='duration', manual_hours='-1'), 'positive'), ('durée > 24 h', dict(entry_mode='duration', manual_hours='25'), '24 h'),
                       ('durée texte', dict(entry_mode='duration', manual_hours='abc'), 'invalide'), ('durée < 0,01', dict(entry_mode='duration', manual_hours='0.001'), '0,01'),
                       ('durée NaN', dict(entry_mode='duration', manual_hours='nan'), 'invalide'), ('mode inconnu', dict(entry_mode='x'), 'inconnu')]:
    s, m = ent(work_date='2026-08-05', project_id=pa, description='x', **f); R.has(f'A5 refusé : {lbl}', m, needle)
s, m = ent(work_date='2026-06-06', project_id=pb, entry_mode='clock', start_time='22:00', end_time='02:00', description='nuit A5b'); emn = ids()
r = A.q('select work_date,start_time,end_time,hours from entries where id=?', (emn,))[0]; ck('A5b saisie passant minuit 22:00→02:00 : UNE saisie de 4 h rattachée au jour de début (C5)', r == ('2026-06-06', '22:00', '02:00', 4.0), r)
ck('A5c aucune seconde ligne créée le lendemain', A.one("select count(*) from entries where work_date='2026-06-07' and description='nuit A5b'") == 0)
n = A.one('select count(*) from entries')
s, m = ent(work_date='2026-13-45', project_id=pa, entry_mode='duration', manual_hours='1'); ck('A6 date invalide refusée', A.one('select count(*) from entries') == n, m)
s, m = ent(work_date='2026-08-05', project_id=pa, entry_mode='duration', manual_hours='1', description='y' * 1001); R.has('A7 description > 1000 caractères refusée', m, 'trop longue')
s, m = ent(work_date='2026-08-05', project_id=99999, entry_mode='duration', manual_hours='1'); ck('A8 mandat inconnu refusé', A.one('select count(*) from entries') == n, m)
ck('A9 aucune saisie créée par les refus', A.one('select count(*) from entries') == n)
# avertissements non bloquants
s, m = ent(work_date='2026-08-03', project_id=pa, entry_mode='clock', start_time='10:00', end_time='11:00', description='chevauche'); R.has('A10 chevauchement : avertissement mais saisie conservée', m, 'chevauche'); e5 = ids()
ck('A10b saisie chevauchante bien enregistrée', A.one('select hours from entries where id=?', (e5,)) == 1.0)
s, m = ent(work_date='2026-12-01', project_id=pa, entry_mode='duration', manual_hours='1', description='future'); R.has('A11 date future : avertissement', m, 'futur'); e6 = ids()
# modification
s, m = A.post(f'/entry/{e2}/edit', {'work_date': '2026-08-04', 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': '4.5', 'description': 'durée corrigée'})
r = A.q('select hours,description from entries where id=?', (e2,))[0]; ck('A12 modification durée 4,25 → 4,5 + description', r == (4.5, 'durée corrigée'), (r, m))
ck('A13 ancienne valeur tracée (entry_changes update)', A.one("select count(*) from entry_changes where entry_id=? and action='update'", (e2,)) == 1)
s, m = A.post(f'/entry/{e2}/edit', {'work_date': '2026-08-04', 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': '4.25', 'description': 'durée manuelle'})
ck('A14 re-modification (retour à 4,25) tracée : 2 lignes d\'historique', A.one("select count(*) from entry_changes where entry_id=?", (e2,)) == 2)
s, m = A.post(f'/entry/{e1}/edit', {'work_date': '2026-08-03', 'project_id': pb, 'entry_mode': 'clock', 'start_time': '09:00', 'end_time': '12:30', 'description': 'déplacée'})
ck('A15 changement de mandat (Alpha → Beta) possible', A.one('select project_id from entries where id=?', (e1,)) == pb, m)
A.post(f'/entry/{e1}/edit', {'work_date': '2026-08-03', 'project_id': pa, 'entry_mode': 'clock', 'start_time': '09:00', 'end_time': '12:30', 'description': 'clock 3h30'})
s, m = A.post(f'/entry/{e2}/edit', {'work_date': '2026-08-04', 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': '0', 'description': 'x'}); R.has('A16 modification invalide refusée', m, 'non modifiée')
ck('A16b valeur inchangée après refus', A.one('select hours from entries where id=?', (e2,)) == 4.25)
s, m = A.post(f'/entry/{e2}/edit', {'work_date': '2026-08-04', 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': '4.5', 'description': 'durée manuelle', 'rev': 'périmé'}); R.has('A16c jeton de version périmé refusé (deux onglets)', m, 'modifiée depuis')
n_ch = A.one('select count(*) from entry_changes where entry_id=?', (e2,))
s, m = A.post(f'/entry/{e2}/edit', {'work_date': '2026-08-04', 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': '4.25', 'description': 'durée manuelle', 'rev': 'périmé'})
R.has('A16d rc19 : formulaire renvoyé avec les valeurs déjà enregistrées (double envoi) : reconnu, rien n\'est écrit', m, 'déjà enregistrée'); ck('A16e aucune ligne d\'historique ajoutée', A.one('select count(*) from entry_changes where entry_id=?', (e2,)) == n_ch)
# suppression
s, m = A.post(f'/entry/{e6}/delete', {}); ck('A17 suppression d\'une saisie manuelle', A.one('select count(*) from entries where id=?', (e6,)) == 0, m)
ck('A18 copie conservée dans l\'historique (delete)', A.one("select count(*) from entry_changes where entry_id=? and action='delete'", (e6,)) == 1)
ck('A18b audit append-only : événement time_entry_deleted', A.one("select count(*) from audit where event='time_entry_deleted'") >= 1)
# historique : rc19 (règle utilisateur 2026-10-05) — une saisie importée est une saisie normale, modifiable, provenance conservée.
# Corrigée puis remise à l'identique pour que A25 (empreinte des 2 247 saisies historiques) reste la preuve de non-altération.
imp = A.q("select id,work_date,project_id,hours,description,source,source_ref,import_batch_id from entries where import_batch_id is not null and start_time='' order by id limit 1")[0]
s, m = A.post(f'/entry/{imp[0]}/edit', {'work_date': imp[1], 'project_id': imp[2], 'entry_mode': 'duration', 'manual_hours': '9', 'description': 'correction recette'})
ck('A19 saisie importée (mandat clôturé) modifiable, provenance conservée (source, référence, lot)', A.q('select hours,description,source,source_ref,import_batch_id from entries where id=?', (imp[0],))[0] == (9, 'correction recette', imp[5], imp[6], imp[7]), m)
s, m = A.post(f'/entry/{imp[0]}/edit', {'work_date': imp[1], 'project_id': imp[2], 'entry_mode': 'duration', 'manual_hours': str(imp[3]), 'description': imp[4]})
ck('A20 …remise à sa valeur d\'origine, deux corrections tracées (avant/après, utilisateur)', A.q('select hours,description from entries where id=?', (imp[0],))[0] == (imp[3], imp[4])
   and A.q("select count(*), min(actor) from entry_changes where entry_id=? and action='update'", (imp[0],))[0] == (2, 'admin'), m)
# conversion en jours (indépendante) : heures / heures-par-jour du mandat
A.post('/entry', {'work_date': '2026-08-10', 'project_id': pb, 'entry_mode': 'duration', 'manual_hours': '7.5', 'description': 'journée Beta'})
page = A.get('/entries?project=%d' % pb)
ck('A21 conversion en jours : 7,5 h sur mandat journée 7,5 h = 1 j équivalent', '1,0000' in page or '1,00' in page, re.findall(r'<strong>[^<]*</strong> j', page))
tot = A.get(f'/entries?project={pa}'); hs = A.one('select sum(hours) from entries where project_id=?', (pa,))
ck('A22 liste filtrée par mandat : total heures = somme en base', fr(hs) in tot.replace(' ', ' ') or fr(hs, 2).replace(' ', ' ') in tot, (hs,))
# filtres de la liste
ck('A23 filtre dates + texte', 'clock 3h30' in A.get('/entries?date_from=2026-08-03&date_to=2026-08-03&q=clock') and 'durée manuelle' not in A.get('/entries?date_from=2026-08-03&date_to=2026-08-03'))
ck('A24 export CSV des saisies = nombre en base', len(A.get('/entries.csv').lstrip('﻿').strip().splitlines()) - 1 == A.one('select count(*) from entries'))
# historique inchangé
H1 = entries_digest(A.db, only_import=True)
ck('A25 conservation des données historiques : empreinte des 2 247 saisies importées inchangée', H1 == HIST0, (HIST0, H1))
# mise à jour du solde de saisies d'Alpha pour la suite
R.sec('B. Mandats — positions (jours consommés / facturés / solde) et cohérence avec l\'historique')
import subprocess
contract_script = r'''
import sqlite3, json, sys
sys.path.insert(0, "/app")
from app import billing_rules as r
c = sqlite3.connect("file:/data/timebilling.db?mode=ro", uri=True); c.row_factory = sqlite3.Row
out = {}
for p in c.execute("select * from projects"):
    pos = r.contract(c, p); out[p["name"]] = pos
print(json.dumps(out))
'''
def positions():
    o = subprocess.run(['docker', 'exec', '-i', os.environ['CTN'], 'python', '-W', 'ignore', '-'], input=contract_script, capture_output=True, text=True); return json.loads(o.stdout)
pos = positions()
bad = []
for pid, name, hrs, dh, od in A.q('select p.id,p.name,coalesce(sum(e.hours),0),coalesce(p.day_hours,8),p.ordered_days from projects p left join entries e on e.project_id=p.id group by p.id'):
    cd = float(D(str(hrs)) / D(str(dh)))
    hist = A.one("select coalesce(sum(qty_days),0) from historical_invoices where project_id=? and status='validated'", (pid,))
    hist = float(hist or 0)
    expected_balance = float(od or 0) - hist
    expected_unbilled = cd - hist
    if abs(pos[name]['consumed_days'] - cd) > 1e-4 or abs(pos[name]['consumed_hours'] - hrs) > 1e-4 or abs(pos[name]['billed_days'] - hist) > 1e-4 or abs(pos[name]['po_balance_days'] - expected_balance) > 1e-4 or abs(pos[name]['unbilled_days'] - expected_unbilled) > 1e-4:
        bad.append((name, pos[name], {'consumed_days': cd, 'historical_validated_days': hist, 'po_balance_days': expected_balance, 'unbilled_days': expected_unbilled}))
ck('B9 les 26 mandats : calcul indépendant des jours réalisés et des factures historiques validées imputables ; solde PO = commandé − historique validé, dépassement négatif conservé', not bad and len(pos) == 26, (len(pos), bad[:2]))
hist_names = [n for n, in A.q("select distinct p.name from projects p join entries e on e.project_id=p.id where e.import_batch_id is not null")]
ck('B10 24 mandats historiques portent des saisies importées', len(hist_names) == 24, len(hist_names))
page = A.get('/?tab=mandates'); ck('B11 page Mandats : les 26 mandats listés', all(n in page for n in hist_names + ['ZZ Recette Alpha', 'ZZ Recette Beta']))
ck('B12 mandat créé par l\'import sans paramètres visible (EUROPCR 2027, jours commandés vides = 0)', pos['EUROPCR 2027']['ordered_days'] == 0)
europcr_id = A.one("select id from projects where name='EUROPCR 2025'")
europcr_hist = float(A.one("select coalesce(sum(qty_days),0) from historical_invoices where project_id=? and status='validated'", (europcr_id,)) or 0)
europcr_consumed = float(A.one("select coalesce(sum(e.hours),0)/coalesce(max(p.day_hours),8) from projects p left join entries e on e.project_id=p.id where p.id=?", (europcr_id,)) or 0)
europcr_ordered = float(A.one("select ordered_days from projects where id=?", (europcr_id,)) or 0)
europcr_expected_balance = europcr_ordered - europcr_hist
europcr_expected_unbilled = europcr_consumed - europcr_hist
ck('B13 EUROPCR 2025 : solde PO = 10 j commandés − factures historiques validées imputables ; le dépassement négatif est conservé et les jours non facturés restent calculés séparément', abs(pos['EUROPCR 2025']['po_balance_days'] - europcr_expected_balance) < 1e-4 and abs(pos['EUROPCR 2025']['unbilled_days'] - europcr_expected_unbilled) < 1e-4 and (europcr_expected_balance < 0) == (pos['EUROPCR 2025']['po_balance_days'] < 0), {'position': pos['EUROPCR 2025'], 'historical_validated_days': europcr_hist, 'expected_po_balance': europcr_expected_balance, 'expected_unbilled_days': europcr_expected_unbilled})
# B14 : sur une copie SQLite jetable, des lignes proposées/rejetées ne doivent jamais modifier les positions.
fd, tmpdb = tempfile.mkstemp(prefix='billing-historical-status-', suffix='.db'); os.close(fd)
try:
    src = sqlite3.connect(f'file:{A.db}?mode=ro', uri=True); dst = sqlite3.connect(tmpdb)
    src.backup(dst); src.close(); dst.row_factory = sqlite3.Row
    test_project = dst.execute('select * from projects where id=?', (pa,)).fetchone()
    before_status_test = billing_rules_test.contract(dst, test_project)
    dst.executemany('''insert into historical_invoices(project_id,source_file,source_sheet,source_cell,basis,qty_days,status,note,created_at) values(?,?,?,?,?,?,?,?,?)''', [
        (pa, 'synthetic-status-check.xlsx', 'Status test', 'A1', 'days', 7.0, 'proposed', '', '2026-10-10T00:00:00Z'),
        (pa, 'synthetic-status-check.xlsx', 'Status test', 'A2', 'days', 8.0, 'rejected', 'rejet fictif de recette', '2026-10-10T00:00:00Z')])
    dst.commit(); after_status_test = billing_rules_test.contract(dst, test_project)
    same_position = all(abs(float(after_status_test[k]) - float(before_status_test[k])) < 1e-9 for k in ('billed_days','po_balance_days','historical_days','historical_count'))
    ck('B14 factures historiques proposées/rejetées : aucun effet sur jours facturés, solde PO ou compteurs historiques (copie jetable)', same_position, {'before': {k: before_status_test[k] for k in ('billed_days','po_balance_days','historical_days','historical_count')}, 'after': {k: after_status_test[k] for k in ('billed_days','po_balance_days','historical_days','historical_count')}})
    dst.close()
finally:
    try: os.unlink(tmpdb)
    except FileNotFoundError: pass
json.dump({'pa': pa, 'pb': pb, 'e1': e1, 'e2': e2, 'e3': e3, 'e4': e4}, open(f'{dirn}/state-ab.json', 'w'))
json.dump(R.rows, open(f'{dirn}/results-ab.json', 'w'), ensure_ascii=False, indent=1)
ok, ko = R.summary(); sys.exit(1 if ko else 0)
