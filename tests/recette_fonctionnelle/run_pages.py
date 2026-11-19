"""Recette fonctionnelle — N. Parcours de toutes les pages sur la copie préparée (mandats clôturés, émetteur renseigné, historique) : aucune erreur serveur.
usage: run_pages.py <port> <dossier-instance>"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
port, dirn = sys.argv[1], sys.argv[2]; A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('N'); ck = R.check; assert A.login()
R.sec('N. Parcours des pages (aucune erreur 5xx, aucun texte d\'erreur interne)')
paths = ['/', '/?tab=mandates', '/?tab=time', '/?tab=billing', '/?tab=archive', '/?tab=settings', '/?tab=import', '/entries', '/entries?page=2', '/entries.csv', '/archive.zip?year=2026', '/archive.zip?year=2025', '/backup', '/health']
pids = [r[0] for r in A.q('select id from projects order by id')]
paths += [f'/project/{i}/edit' for i in pids] + [f'/entries?project={i}' for i in pids]
bad = []
for p in paths:
    s, h, b = A.req(p)
    t = b[:4000].decode('utf-8', 'replace')
    if s >= 500 or 'Traceback' in t or 'erreur interne' in t.lower(): bad.append((p, s))
    elif s not in (200, 302, 303, 404): bad.append((p, s))
ck(f'N1 {len(paths)} pages/exports parcourus : 200/redirection, aucune erreur serveur', not bad, bad[:6])
n404 = [p for p in paths if A.req(p)[0] == 404]
ck('N2 aucune page introuvable parmi les pages parcourues', not n404, n404)
pg = html = A.get('/?tab=mandates')
ck('N3 la page Mandats distingue les mandats clôturés des actifs', ('clôtur' in pg.lower()), None)
ok = sum(1 for r in R.rows if r['ok']); ko = [r for r in R.rows if not r['ok']]
print(f"\nRÉSULTAT N : {ok}/{len(R.rows)} OK, {len(ko)} KO")
for r in ko: print('  KO', r['test'], '|', r['detail'])
sys.exit(1 if ko else 0)
