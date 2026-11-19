"""Recette fonctionnelle — M. Clôture / réouverture des mandats terminés (après mandats_appliquer.py --close-termine), sur COPIE jetable.
Vérifie que clôturer ne perd rien (saisies, historique), refuse de nouvelles saisies, est réversible, et que la prévision recalculée correspond.
usage: run_mandats.py <port> <dossier-instance>"""
import sys, os, re, html
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
port, dirn = sys.argv[1], sys.argv[2]; A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('M'); ck = R.check; assert A.login()
R.sec('M. Mandats terminés : clôture, historique conservé, réversibilité, prévision')
ev = dict(A.q("select event, count(*) from audit where event like 'project_%' group by 1"))
ck('M1 19 clôtures tracées dans l\'audit, avec la position à la clôture', ev.get('project_closed') == 19 and A.one("select count(*) from audit where event='project_closed' and detail like '%unbilled_days=%' and detail like '%po_balance_days=%'") == 19, ev)
ck('M2 saisies historiques toutes présentes (2 247 / 1 934,4987 h) malgré les clôtures', A.q('select count(*), round(sum(hours),4) from entries')[0] == (2247, 1934.4987), A.q('select count(*), round(sum(hours),4) from entries')[0])
cl = A.q("select id, name from projects where active=0 order by name")
pid, nm = cl[0]; n_e = A.one('select count(*) from entries where project_id=?', (pid,))
pg = html.unescape(A.get(f'/entries?project={pid}')); shown = len(re.findall(r'<tr', pg))
ck(f'M3 l\'historique d\'un mandat clôturé reste consultable ({nm} : {n_e} saisies)', shown >= min(n_e, 20), (shown, n_e))
s, m = A.post('/entry', {'work_date': '2026-09-29', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'test sur mandat clôturé'})
ck('M4 nouvelle saisie sur un mandat clôturé refusée, rien créé', A.one('select count(*) from entries where project_id=?', (pid,)) == n_e and m, m)
s, m = A.post(f'/project/{pid}/reopen', {}); ck('M5 réouverture possible (réversible)', any('rouvert' in x for x in m) and A.one('select active from projects where id=?', (pid,)) == 1, m)
s, m = A.post('/entry', {'work_date': '2026-09-29', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'saisie après réouverture'})
ck('M6 après réouverture, saisie acceptée (puis supprimée : copie jetable)', A.one('select count(*) from entries where project_id=?', (pid,)) == n_e + 1, m)
eid = A.one("select id from entries where description='saisie après réouverture'"); A.post(f'/entry/{eid}/delete', {})
s, m = A.post(f'/project/{pid}/close', {'reason': 'recette M : re-clôture'}); ck('M7 re-clôture, motif obligatoire respecté', any('Mandat clôturé' in x for x in m) and A.one('select active from projects where id=?', (pid,)) == 0, m)
s, m = A.post(f'/project/{pid}/close', {'reason': ''}); ck('M7b clôture sans motif refusée', any('motif' in x.lower() for x in m) and A.one('select active from projects where id=?', (pid,)) == 0, m)  # déjà clôturé par M7 : le refus doit rester explicite
# prévision : seuls les mandats actifs comptent, recalcul indépendant
pgd = A.get('/'); got = sum((D(re.sub(r'[^\d,]', '', html.unescape(a)).replace(',', '.')) for _, a in re.findall(r'<title>(\d{4}-\d{2}) : ([^<]*)</title>', pgd)), D(0))
exp = sum(((D(str(r[0])) * D(str(r[1]))).quantize(CENT, ROUND_HALF_UP) for r in A.q('select ordered_days, rate from projects where active=1 and ordered_days>0 and rate>0')), D(0))
ck('M8 prévision affichée = Σ (jours commandés × tarif) des seuls mandats actifs (aucune facture émise)', got == exp, (got, exp))
act = [r[0] for r in A.q('select name from projects where active=1 order by name')]
ck('M9 mandats actifs après clôtures = NHAF 2026, PCR LV 2026, STC GEM Oct - DM job, EUROPCR 2027, MSD', sorted(act) == sorted(['NHAF 2026', 'PCR LV 2026', 'STC GEM Oct - DM job', 'EUROPCR 2027', 'MSD']), act)
ok = sum(1 for r in R.rows if r['ok']); ko = [r for r in R.rows if not r['ok']]
print(f"\nRÉSULTAT M : {ok}/{len(R.rows)} OK, {len(ko)} KO")
for r in ko: print('  KO', r['test'], '|', r['detail'])
sys.exit(1 if ko else 0)
