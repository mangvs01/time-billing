#!/bin/bash
# Répétition E (rc21, 2026-10-07) : la séquence EXACTE prévue pour D11 (billing-d11-deploy-rc20), sur un faux staging jetable dans l'état du staging
# réel après procedure/60 (rc19 + 24 factures historiques « à valider » + 15 descriptions A-01). Aucune lecture de /opt : base = sauvegarde
# pre-donnees-d1d2a01 (rc19, juste avant procedure/60, SHA vérifié), code rc19 = git archive 8afd867, puis procedure/60 rejouée sur le bac à sable.
#   0. faux staging rc19 (secrets de test)        1. procedure/60 (D1/D2/A-01) sur le bac à sable
#   2. 10 → 20 → 30 → 40 → 50 (rc21)               3. contrôles rc21 par HTTP (données identiques, brouillon n°1, bouton et export .xlsx)
#   4. retour arrière (rien d'écrit) : accepté → rc19, base = sauvegarde      5. redéploiement 10 → 50
#   6. parcours utilisateur : validation des 24 historiques, export (onglets SUIVI, CA = « Facturé »)
#   7. retour arrière après validation : doit être refusé (les validations seraient écartées)
# Jamais le staging réel ni la production. Usage : [PORT=<port>] migration-blanc/dry-run-e-rc21.sh   (port 8435 par défaut, bac à sable migration-blanc/E-RC21, recréé)
set -uo pipefail
MB=$(cd "$(dirname "$0")" && pwd); W=$(cd $MB/.. && pwd); S=$MB/E-RC21; P=$W/procedure; PORT=${PORT:-8435}
ROOT=$S/opt/time-billing-v9-staging; DBF=$ROOT/data/timebilling.db
RC19_COMMIT=8afd867; RC21_IMAGE=tb-g4-cand:51b7c1b; RC19_IMAGE=tb-g4-decisions-cand:8afd867
PRE=/root/backups/time-billing-v9-staging/pre-donnees-d1d2a01-20261007T072306Z
TAG=$(sed -n 's/^VERSION="9.2-\(.*\)"/\1/p' $W/app/app.py)
step() { echo; echo "=== $*"; }
ok() { echo "OK    $*"; }; ko() { echo "ÉCHEC $*"; FAIL=1; }; FAIL=0
[ "$TAG" = rc21 ] || { echo "code du dépôt = $TAG, rc21 attendu"; exit 1; }
[ -z "$(git -C $W status --porcelain -- app requirements.txt requirements.lock Dockerfile .dockerignore)" ] || { echo "app/ modifié par rapport au commit : arrêt"; exit 1; }
docker rm -f tbmb-erc21 >/dev/null 2>&1; [ -d "$S" ] && { (cd $ROOT 2>/dev/null && docker compose -p tbmb-erc21 down >/dev/null 2>&1); rm -rf "$S"; }
mkdir -p $S/opt $S/backups $S/src19 $S/journal $ROOT/data; chmod 700 $S $S/backups

step "0. faux staging rc19 : code $RC19_COMMIT, base = $(basename $PRE) (SHA vérifié), secrets de test"
(cd $PRE && sha256sum -c --quiet SHA256SUMS) && ok "sauvegarde pre-donnees intacte" || { ko "sauvegarde pre-donnees altérée"; exit 1; }
git -C $W archive $RC19_COMMIT app requirements.txt requirements.lock Dockerfile .dockerignore | tar -x -C $S/src19
cp -a $S/src19/. $ROOT/; install -m 644 $P/docker-compose.staging.yml $ROOT/docker-compose.yml
cp $PRE/timebilling.db $DBF; SHA0=$(sha256sum < $DBF)
PW=$(openssl rand -hex 12); echo -n "$PW" > $S/pw.txt; chmod 600 $S/pw.txt
HASH=$(docker run --rm --network none $RC19_IMAGE python -c "import sys;from werkzeug.security import generate_password_hash as g;print(g(sys.argv[1]))" "$PW")
( umask 077; printf "APP_USER=admin\nAPP_PASSWORD_HASH='%s'\nSECRET_KEY='%s'\nCOOKIE_SECURE=0\nTB_PORT=%s\nTB_CONTAINER=tbmb-erc21\nENV_LABEL=RECETTE\n" "$HASH" "$(openssl rand -hex 32)" $PORT > $ROOT/.env )
cat > $S/sandbox.conf <<EOF
ROOT=$ROOT
PROJECT=tbmb-erc21
CONTAINER=tbmb-erc21
IMAGE=tbmb-erc21-time-billing-v9-staging
URL=http://127.0.0.1:$PORT
BACKUP_BASE=$S/backups
SOURCE_APP=$W/app
SOURCE_REQ=$W/requirements.txt
RC_IMAGE=$RC21_IMAGE
COMPOSE_TEMPLATE=$P/docker-compose.staging.yml
EOF
chown -R 10001:10001 $ROOT/data; chmod 700 $ROOT/data; chmod 600 $DBF
(cd $ROOT && docker compose -p tbmb-erc21 up -d --build --quiet-pull 2>&1 | tail -1)
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:$PORT/health >/dev/null && break; sleep 1; done
V0=$(curl -s http://127.0.0.1:$PORT/health); echo "santé : $V0"; grep -q '9.2-rc19' <<<"$V0" && ok "faux staging en rc19" || { ko "version d'origine ($V0)"; exit 1; }
HTTP() { python3 - "$PORT" "$S" "$DBF" "$@" || FAIL=1; }
# état de référence (lecture de la base du bac à sable + pages) : comparé après chaque déploiement / retour
SNAP() { python3 - "$PORT" "$S" "$DBF" "$1" <<'PY'
import sys, re, html, json, hashlib
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db, out = sys.argv[1:5]; A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
d = lambda sql: hashlib.sha256(json.dumps(A.q(sql), default=str).encode()).hexdigest()
snap = {'saisies': d('select * from entries order by id'), 'historiques': d('select * from historical_invoices order by id'),
        'factures': d('select * from invoices order by id'), 'mandats': d('select * from projects order by id'), 'parametres': d('select * from settings order by key'),
        'corrections': d('select * from entry_changes order by id'), 'n_saisies': A.one('select count(*) from entries'),
        'historiques_par_statut': A.q('select status,count(*) from historical_invoices group by status')}
pg = html.unescape(A.get('/issue/1')); snap['controles_brouillon_1'] = sorted(re.findall(r'data-check="(\d+)" data-status="(\w+)"', pg), key=lambda x: int(x[0]))
json.dump(snap, open(out, 'w'), indent=1, default=str)
print(f"INFO  état : {snap['n_saisies']} saisies ; historiques {snap['historiques_par_statut']} ; brouillon n°1 en échec : {[k for k, v in snap['controles_brouillon_1'] if v == 'fail']}")
PY
}
SAME() { python3 - "$1" "$2" "$3" <<'PY'
import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])); diff = [k for k in a if a[k] != b.get(k)]
print(('OK    ' if not diff else 'ÉCHEC ') + sys.argv[3] + ('' if not diff else ' — différences : ' + ', '.join(diff))); sys.exit(1 if diff else 0)
PY
[ $? = 0 ] || FAIL=1; }

SAMEDB() { python3 - "$DBF" "$1" "$2" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); c.execute("ATTACH ? AS o", (f"file:{sys.argv[2]}?mode=ro",)); diff = []
for (t,) in c.execute("select name from main.sqlite_master where type='table' and name not in ('audit','web_sessions')").fetchall():
    n = c.execute(f"select (select count(*) from (select * from main.{t} except select * from o.{t})) + (select count(*) from (select * from o.{t} except select * from main.{t}))").fetchone()[0]
    if n: diff.append(f"{t} ({n})")
print(('OK    ' if not diff else 'ÉCHEC ') + sys.argv[3] + ('' if not diff else ' — ' + ', '.join(diff))); sys.exit(1 if diff else 0)
PY
[ $? = 0 ] || FAIL=1; }

step "1. procedure/60-donnees-d1-d2-a01.sh sur le faux staging (D1 + D2 : 24 « à valider » ; A-01 : 15 descriptions)"
ls -d $W/journaux/donnees-staging-* > $S/j-avant.txt 2>/dev/null
bash $P/60-donnees-d1-d2-a01.sh $S/sandbox.conf && ok "procedure/60 conforme" || { ko "procedure/60"; exit 1; }
for j in $(ls -d $W/journaux/donnees-staging-* 2>/dev/null); do grep -qx "$j" $S/j-avant.txt || mv "$j" $S/journal/; done   # journal du bac à sable, pas celui du staging
HTTP <<'PY'
import sys
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db = sys.argv[1:4]; A = App(port, f'{S}/pw.txt', db)
r = A.q('select status,count(*),round(sum(amount_ht),2) from historical_invoices group by status'); c = A.one("select count(*) from entry_changes where reason like '%A-01%' or actor='outil-a01'")
print(('OK    ' if r == [('proposed', 24, 138209.5)] else 'ÉCHEC ') + f'24 factures historiques « à valider » (133 659,50 + 4 550 CHF) : {r}')
print(f'INFO  corrections A-01 tracées : {c}'); sys.exit(0 if r == [('proposed', 24, 138209.5)] else 1)
PY
SNAP $S/etat-rc19.json

step "2. déploiement rc21 : 10 → 20 → 30 → 40 → 50 (comme le staging : .env conservé)"
deploy() {
  bash $P/10-preflight.sh $S/sandbox.conf || ko "10-preflight"
  bash $P/20-backup.sh $S/sandbox.conf || { ko "20-backup"; return 1; }
  bash $P/30-rehearse.sh $S/sandbox.conf || ko "30-rehearse"
  cp -p $ROOT/.env $ROOT/.env.$TAG
  bash $P/40-deploy.sh $S/sandbox.conf || { ko "40-deploy"; return 1; }
  bash $P/50-verify.sh $S/sandbox.conf || ko "50-verify"
}
deploy || exit 1

step "3. contrôles rc21 (HTTP) : mêmes données que rc19, brouillon n°1, bouton et export .xlsx"
SNAP $S/etat-rc21.json; SAME $S/etat-rc19.json $S/etat-rc21.json "rc21 : saisies, corrections, historiques, factures/brouillons, mandats, paramètres et contrôles du brouillon n°1 identiques à rc19"
EXPORT() { python3 - "$PORT" "$S" "$DBF" "$1" <<'PY'
import sys, html, json
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db, out = sys.argv[1:5]; A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
s, h, b = A.req('/export/classeur.xlsx'); open(out, 'wb').write(b)
ct = dict((k.lower(), v) for k, v in h.items()).get('content-type', '') if hasattr(h, 'items') else str(h)
print(('OK    ' if s == 200 and b[:2] == b'PK' and 'spreadsheetml' in ct else 'ÉCHEC ') + f'export .xlsx téléchargé ({s}, {len(b)} octets)')
ev = A.q("select detail from audit where event='gsheet_export_downloaded' order by id desc limit 1")
print('INFO  journal : ' + (ev[0][0] if ev else '—'))
sys.exit(0 if s == 200 and b[:2] == b'PK' else 1)
PY
[ $? = 0 ] || FAIL=1; }
SHEETS() { docker run --rm --network none -v "$1:/x.xlsx:ro" $RC21_IMAGE python -c "
import openpyxl, json; wb = openpyxl.load_workbook('/x.xlsx')
out = {'onglets': wb.sheetnames}
for n in wb.sheetnames:
    if n.startswith('SUIVI'):
        ws = wb[n]; out[n] = {'lignes': [ws.cell(r, 1).value for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value],
                              'entete': [c.value for c in ws[1]]}
print(json.dumps(out, ensure_ascii=False))"; }
HTTP <<'PY'
import sys, html
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db = sys.argv[1:4]; A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
pg = html.unescape(A.get('/')); c = 'href="/export/classeur.xlsx" download>Télécharger le classeur (.xlsx)' in pg
print(('OK    ' if c else 'ÉCHEC ') + 'onglet Migration (page d accueil) : bouton « Télécharger le classeur (.xlsx) »'); sys.exit(0 if c else 1)
PY
EXPORT $S/export-rc21-avant-validation.xlsx
SHEETS $S/export-rc21-avant-validation.xlsx > $S/onglets-avant-validation.json && python3 - $S/onglets-avant-validation.json <<'PY' || FAIL=1
import json, sys
o = json.load(open(sys.argv[1])); n = o['onglets']; s = [x for x in n if x.startswith('SUIVI')]
print(f"INFO  {len(n)} onglets : {', '.join(n)}")
c = s == ['SUIVI 2026']; print(('OK    ' if c else 'ÉCHEC ') + f"avant validation : seul SUIVI 2026 (mandats ouverts, aucun document) — {s}")
sys.exit(0 if c else 1)
PY

step "4. retour arrière (aucune donnée métier écrite depuis la sauvegarde ; le téléchargement n'écrit que l'audit) : accepté → rc19"
TS=$(cat $S/backups/last-backup)
bash $P/90-rollback.sh $S/sandbox.conf 2>&1 | tee $S/retour-1.log; [ ${PIPESTATUS[0]} = 0 ] && ok "90-rollback accepté" || ko "90-rollback"
grep -q "base = sauvegarde $TS (SHA-256 identique)" $S/retour-1.log && ok "base restaurée = sauvegarde d'avant déploiement (SHA-256 vérifié par 90-rollback, service arrêté)" || ko "SHA de la base restaurée non confirmé"
SAMEDB $S/backups/pre-$TAG-$TS/timebilling.db "après redémarrage rc19 : contenu de toutes les tables = sauvegarde (le fichier peut différer : écritures de démarrage sans effet sur les données)"
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc19' <<<"$H" && ok "version rc19 de retour" || ko "version après retour : $H"
SNAP $S/etat-retour.json; SAME $S/etat-rc19.json $S/etat-retour.json "après retour : état rc19 identique (dont brouillon n°1 et 24 historiques)"

step "5. redéploiement rc21 : 10 → 50"
deploy || exit 1
SNAP $S/etat-rc21-bis.json; SAME $S/etat-rc19.json $S/etat-rc21-bis.json "après redéploiement : données identiques à rc19"

step "6. parcours utilisateur sur rc21 : validation des 24 historiques (page Factures historiques), puis export"
HTTP <<'PY'
import sys
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db = sys.argv[1:4]; A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
for (pid,) in A.q("select distinct project_id from historical_invoices where status='proposed'"): A.post(f'/historique/mandat/{pid}/valider', {})
r = A.q('select status,count(*) from historical_invoices group by status'); c = r == [('validated', 24)]
print(('OK    ' if c else 'ÉCHEC ') + f'24 historiques validées par la page : {r}')
n = A.one("select count(*) from audit where event='historical_invoice_validated'"); print(f'INFO  validations tracées : {n}'); sys.exit(0 if c else 1)
PY
EXPORT $S/export-rc21-apres-validation.xlsx
SHEETS $S/export-rc21-apres-validation.xlsx > $S/onglets-apres-validation.json && python3 - $S/onglets-apres-validation.json <<'PY' || FAIL=1
import json, sys
o = json.load(open(sys.argv[1])); n = o['onglets']
want = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEPT', 'OCT', 'NOV', 'DEC', 'SUIVI 2025', 'JAN 26', 'FEB 26', 'MAR 26', 'APR 26', 'MAY 26', 'JUN 26', 'JUL 26', 'AUG 26', 'SEPT 26', 'SUIVI 2026']
print(f"INFO  {len(n)} onglets : {', '.join(n)}")
c1 = len(n) == 23 and [x for x in n if x.startswith('SUIVI')] == ['SUIVI 2025', 'SUIVI 2026'] and n.index('SUIVI 2025') == 12 and n[-1] == 'SUIVI 2026'
print(('OK    ' if c1 else 'ÉCHEC ') + "23 onglets, SUIVI 2025 après DEC, SUIVI 2026 en dernier (ordre du classeur)")
l25, l26 = len(o.get('SUIVI 2025', {}).get('lignes', [])), len(o.get('SUIVI 2026', {}).get('lignes', []))
print(f'INFO  lignes SUIVI 2025 : {l25} ; SUIVI 2026 : {l26} (mesure du 07.10 : 10 + 14, lignes TOTAL comprises si présentes)')
sys.exit(0 if c1 else 1)
PY
python3 - "$PORT" "$S" "$DBF" <<'PY' || FAIL=1
import sys, json
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db = sys.argv[1:4]; A = App(port, f'{S}/pw.txt', db)
d = json.loads(A.q("select detail from audit where event='gsheet_export_downloaded' order by id desc limit 1")[0][0]); s = d.get('suivi', {})
norm = lambda v: str(v).replace("'", '').replace(' ', '').replace(' ', '').replace('\xa0', '').replace(',', '.')
c = norm(s.get('2025')) in ('67236.00', '67236', '67236.0') and norm(s.get('2026')) in ('70973.50', '70973.5')
print(('OK    ' if c else 'ÉCHEC ') + f"CA des onglets SUIVI = « Facturé » de Billing (2025 67 236,00 ; 2026 70 973,50) : {s} ; saisies {d.get('entries')} / {d.get('hours')} h")
sys.exit(0 if c else 1)
PY

step "7. retour arrière après validation des historiques : doit être REFUSÉ (les 24 validations seraient écartées sans avertissement)"
python3 -c "import sqlite3,sys;s=sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True);d=sqlite3.connect(sys.argv[2]);s.backup(d)" $DBF $S/avant-tentative.db
if bash $P/90-rollback.sh $S/sandbox.conf > $S/retour-2.log 2>&1; then cat $S/retour-2.log; ko "retour arrière ACCEPTÉ alors que 24 validations ont été écrites depuis la sauvegarde"
else cat $S/retour-2.log; ok "retour arrière refusé (validations écrites depuis la sauvegarde)"; fi
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc21' <<<"$H" && ok "service rc21 toujours en marche" || ko "service après la tentative : $H"
SAMEDB $S/avant-tentative.db "base inchangée par la tentative (contenu de toutes les tables hors audit/sessions)"
grep -q "historical_invoices : 24 ligne(s) modifiée(s)" $S/retour-2.log && ok "motif du refus : historical_invoices : 24 ligne(s) modifiée(s)" || ko "motif du refus inattendu : $(grep ARRÊT $S/retour-2.log)"

step "8. nettoyage"
(cd $ROOT && docker compose -p tbmb-erc21 down >/dev/null 2>&1); docker image ls --format '{{.Repository}}:{{.Tag}}' | grep '^tbmb-erc21-time-billing-v9-staging' | xargs -r docker rmi >/dev/null 2>&1 && echo "images du bac à sable supprimées"
rm -rf $S/src19 $S/opt/time-billing-v9-staging/data/backups
[ $FAIL = 0 ] && echo "RÉPÉTITION E : GO" || echo "RÉPÉTITION E : NO-GO"; exit $FAIL
