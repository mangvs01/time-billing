#!/bin/bash
# Répétition D (rc19 + G4, 2026-10-06) : la séquence EXACTE prévue pour le staging, sur une COPIE du staging (rc18, 2 247 saisies, brouillon n°1),
# secrets de test (aucun secret du staging copié ; .env conservé tel quel au déploiement, comme le sera celui du staging : mot de passe inchangé).
#   1. 10 → 20 → 30 → 40 → 50 (sauvegarde, répétition, déploiement, vérifications : empreintes saisies / factures / mandats / paramètres)
#   2. contrôles G4 par HTTP : registre vide, page Factures historiques, 13 contrôles sur le brouillon n°1 (émission impossible), dashboard inchangé
#   3. retour arrière (aucune donnée écrite depuis la sauvegarde : accepté) → base = sauvegarde (SHA), rc18
#   4. redéploiement 20 → 50
#   5. répétition du chargement D1 : simulation, puis écriture des 23 lignes « à valider » (sans effet), validation d'un mandat, retour arrière refusé
# Jamais le staging réel ni la production. Usage : [RC_IMAGE=<image>] [PORT=<port>] migration-blanc/dry-run-d-g4.sh   (port 8433 par défaut — 8421 est le Decision Center depuis le 2026-10-07 —, bac à sable migration-blanc/D-G4, recréé)
set -uo pipefail
MB=$(cd "$(dirname "$0")" && pwd); W=$MB/..; S=$MB/D-G4; P=$W/procedure; PORT=${PORT:-8433}; TAG=$(sed -n 's/^VERSION="9.2-\(.*\)"/\1/p' $W/app/app.py)
RC_IMAGE=${RC_IMAGE:-time-billing-v9-staging-time-billing-v9-staging:rc19}   # image candidate construite depuis le commit à déployer
step() { echo; echo "=== $*"; }
ok() { echo "OK    $*"; }; ko() { echo "ÉCHEC $*"; FAIL=1; }; FAIL=0
[ "$TAG" = rc19 ] || { echo "code du dépôt = $TAG, rc19 attendu"; exit 1; }
docker rm -f tbmb-dg4 >/dev/null 2>&1; [ -d "$S" ] && { (cd $S/opt/tb 2>/dev/null && docker compose -p tbmb-dg4 down >/dev/null 2>&1); rm -rf "$S"; }
mkdir -p $S/opt $S/backups $S/simu; chmod 700 $S $S/backups; chmod 777 $S/simu
step "0. bac à sable : arborescence staging rc18 (sans données ni secrets), base = copie cohérente du staging, secrets de test"
rsync -a --exclude data --exclude '.env*' --exclude '__pycache__' /opt/time-billing-v9-staging/ $S/opt/tb/
mkdir -p $S/opt/tb/data
python3 - /opt/time-billing-v9-staging/data/timebilling.db $S/opt/tb/data/timebilling.db <<'PY'
import sqlite3, sys
s = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
PY
PW=$(openssl rand -hex 12); echo -n "$PW" > $S/pw.txt; chmod 600 $S/pw.txt
HASH=$(docker run --rm --network none $RC_IMAGE python -c "import sys;from werkzeug.security import generate_password_hash as g;print(g(sys.argv[1]))" "$PW")
( umask 077; printf "APP_USER=admin\nAPP_PASSWORD_HASH='%s'\nSECRET_KEY='%s'\nCOOKIE_SECURE=0\nTB_PORT=%s\nTB_CONTAINER=tbmb-dg4\nENV_LABEL=RECETTE\n" "$HASH" "$(openssl rand -hex 32)" $PORT > $S/opt/tb/.env )
cat > $S/sandbox.conf <<EOF
ROOT=$S/opt/tb
PROJECT=tbmb-dg4
CONTAINER=tbmb-dg4
IMAGE=tbmb-dg4-time-billing-v9-staging
URL=http://127.0.0.1:$PORT
BACKUP_BASE=$S/backups
SOURCE_APP=$W/app
SOURCE_REQ=$W/requirements.txt
RC_IMAGE=$RC_IMAGE
COMPOSE_TEMPLATE=$P/docker-compose.staging.yml
EOF
chown -R 10001:10001 $S/opt/tb/data; chmod 700 $S/opt/tb/data
(cd $S/opt/tb && docker compose -p tbmb-dg4 up -d --build --quiet-pull 2>&1 | tail -1)
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:$PORT/health >/dev/null && break; sleep 1; done
V0=$(curl -s http://127.0.0.1:$PORT/health); echo "santé avant : $V0"; grep -q '9.2-rc18' <<<"$V0" && ok "version d'origine rc18" || ko "version d'origine ($V0)"
DBF=$S/opt/tb/data/timebilling.db
HTTP() { python3 - "$PORT" "$S" "$DBF" "$@" || FAIL=1; }
SHA0=$(sha256sum < $DBF)
deploy() {
  bash $P/10-preflight.sh $S/sandbox.conf || ko "10-preflight"
  bash $P/20-backup.sh $S/sandbox.conf || { ko "20-backup"; return 1; }
  bash $P/30-rehearse.sh $S/sandbox.conf || ko "30-rehearse"
  cp -p $S/opt/tb/.env $S/opt/tb/.env.$TAG          # mot de passe et secret de session conservés (comme sur le staging)
  bash $P/40-deploy.sh $S/sandbox.conf || { ko "40-deploy"; return 1; }
  bash $P/50-verify.sh $S/sandbox.conf || ko "50-verify"
}
step "1. déploiement rc19 + G4 : 10 → 20 → 30 → 40 → 50"
deploy || exit 1
step "2. contrôles G4 (HTTP, lecture seule de la base)"
HTTP <<'PY'
import sys, re, html
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db = sys.argv[1:4]; A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
bad = []
def ok(n, c, d=''):
    print(('OK    ' if c else 'ÉCHEC ') + n + ('' if c else f' — {d}'))
    if not c: bad.append(n)
ok('version rc19', '9.2-rc19' in A.get('/health'))
ok('registre des factures historiques présent et vide', A.one('select count(*) from historical_invoices') == 0)
pg = html.unescape(A.get('/historique')); ok('page Factures historiques servie', 'Factures historiques' in pg, pg[:200])
ok('2 247 saisies', A.one('select count(*) from entries') == 2247)
iid = A.one("select id from invoices where status='draft' order by id limit 1"); ok('brouillon n°1 conservé', iid == 1, iid)
pg = html.unescape(A.get(f'/issue/{iid}'))
rows = dict(re.findall(r'data-check="(\d+)" data-status="(\w+)"', pg))
ok('13 contrôles affichés sur le brouillon n°1', sorted(map(int, rows)) == list(range(1, 14)), rows)
ok('brouillon n°1 : contrôles 3 (tarif 0, R-CHK-2), 10 (données de test), 12 (0 h dans la période) et 13 (fin de période après la date) en échec', [k for k, v in sorted(rows.items(), key=lambda x: int(x[0])) if v == 'fail'] == ['3', '10', '12', '13'], rows)
ok('brouillon n°1 : tarif 0 refusé à l émission (champs à compléter)', 'Émission impossible.' in pg and 'tarif' in pg.split('Émission impossible.')[1][:300].lower(), pg[:400])
ok('brouillon n°1 : émission impossible (bouton désactivé)', 'disabled' in pg.split('Émettre définitivement')[0][-200:])
s, h, b = A.req(f'/invoice/{iid}.pdf'); t = b
ok('PDF du brouillon n°1 rendu', s == 200 and t[:4] == b'%PDF', s)
dash = html.unescape(A.get('/')); ok('tableau de bord servi', 'Réalisé non facturé' in dash)
sys.exit(1 if bad else 0)
PY
step "3. retour arrière (aucune donnée écrite depuis la sauvegarde) : accepté, base = sauvegarde, rc18"
TS=$(cat $S/backups/last-backup)
bash $P/90-rollback.sh $S/sandbox.conf && ok "90-rollback accepté" || ko "90-rollback"
[ "$(sha256sum < $DBF)" = "$(sha256sum < $S/backups/pre-$TAG-$TS/timebilling.db)" ] && ok "base = sauvegarde d'avant déploiement (SHA-256 identique)" || ko "base différente de la sauvegarde"
[ "$(sha256sum < $DBF)" = "$SHA0" ] && ok "base = copie d'origine du staging (SHA-256 identique)" || ko "base différente de la copie d'origine"
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc18' <<<"$H" && ok "version rc18 de retour" || ko "version après retour : $H"
step "4. redéploiement rc19 + G4 : 10 → 50"
deploy || exit 1
step "5. répétition du chargement D1 (copie ; le classeur est lu en lecture seule)"
mkdir -p $S/src && cp "/root/Time sheet CP.xlsx" $S/src/classeur.xlsx && chmod 755 $S/src && chmod 444 $S/src/classeur.xlsx
LOAD() { docker run --rm --network none --user 0:0 -v $W/app:/app/app:ro -v $W/outils:/app/outils:ro -v $S/src:/src:ro -v $S/opt/tb/data:/data -v $S/simu:/out \
  -e PYTHONPATH=/app -e DB_PATH=/data/timebilling.db -e SECRET_KEY=$(openssl rand -hex 32) -e APP_PASSWORD=$(openssl rand -hex 16) -e COOKIE_SECURE=0 -w /app $RC_IMAGE \
  python -W ignore outils/charger_factures_historiques.py --classeur /src/classeur.xlsx --base /data/timebilling.db --sortie /out "$@"; }
B1=$(sha256sum < $DBF)
LOAD > $S/simu/simulation.log 2>&1 && grep -q '"lignes": 23' $S/simu/simulation.log && grep -q '"aucun_effet_tant_que_a_valider": true' $S/simu/simulation.log \
  && ok "simulation : 23 lignes, aucun effet tant qu'à valider" || ko "simulation ($(tail -3 $S/simu/simulation.log))"
[ "$(sha256sum < $DBF)" = "$B1" ] && ok "simulation : base inchangée (SHA-256)" || ko "la simulation a modifié la base"
LOAD --appliquer > $S/simu/refus.log 2>&1 && ko "écriture acceptée sans confirmation" || ok "écriture refusée sans --confirmer"
LOAD --appliquer --confirmer CHARGER-23-A-VALIDER > $S/simu/chargement.log 2>&1 && ok "écriture : $(tail -1 $S/simu/chargement.log)" || ko "écriture ($(tail -3 $S/simu/chargement.log))"
LOAD --appliquer --confirmer CHARGER-23-A-VALIDER > $S/simu/rejeu.log 2>&1 && grep -q "0 ligne(s)" $S/simu/rejeu.log && ok "rejeu idempotent : $(tail -1 $S/simu/rejeu.log)" || ko "rejeu ($(tail -2 $S/simu/rejeu.log))"
HTTP <<'PY'
import sys, re, html
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db = sys.argv[1:4]; A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
bad = []
def ok(n, c, d=''):
    print(('OK    ' if c else 'ÉCHEC ') + n + ('' if c else f' — {d}'))
    if not c: bad.append(n)
ok('23 lignes « à valider », aucune validée', A.q("select status,count(*) from historical_invoices group by status") == [('proposed', 23)], A.q("select status,count(*) from historical_invoices group by status"))
ok('total 205,63 j / 133 659,50 CHF', A.q('select round(sum(qty_days),2),round(sum(amount_ht),2) from historical_invoices')[0] == (205.63, 133659.5))
ok('M15 (D2) et AL (D3) absentes', A.one("select count(*) from historical_invoices where source_cell in ('M15','H3')") == 0)
ok('5 notes de provenance D4', A.one("select count(*) from historical_invoices where note like 'Provenance (D4)%'") == 5)
ok('CIRSE 2026 : n° 2026-09 repris de la facture réelle', A.one("select invoice_ref from historical_invoices where source_sheet='SUIVI 2026' and source_cell='Q12'") == '2026-09')
pg = html.unescape(A.get('/historique')); ok('page : 23 lignes à valider affichées', pg.count('à valider') >= 23 or 'SUIVI 2026!Q12' in pg, pg[:300])
pid = A.one("select id from projects where name='CIRSE 2026'")
s, m = A.post(f'/historique/mandat/{pid}/valider', {}); ok('validation du mandat CIRSE 2026 par la page', A.one("select status from historical_invoices where project_id=?", (pid,)) == 'validated', m)
ok('validation tracée (auteur, date)', A.one("select count(*) from audit where event='historical_invoice_validated'") == 1)
sys.exit(1 if bad else 0)
PY
step "6. retour arrière après chargement : refusé (données écrites depuis la sauvegarde)"
if bash $P/90-rollback.sh $S/sandbox.conf; then ko "retour arrière accepté alors que le registre a été chargé"; else ok "retour arrière refusé (registre chargé depuis la sauvegarde : à exporter d'abord)"; fi
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc19' <<<"$H" && ok "service rc19 toujours en marche après le refus" || ko "service après refus : $H"
step "7. nettoyage"
(cd $S/opt/tb && docker compose -p tbmb-dg4 down >/dev/null 2>&1); docker image ls --format '{{.Repository}}:{{.Tag}}' | grep '^tbmb-dg4-time-billing-v9-staging' | xargs -r docker rmi >/dev/null 2>&1 && echo "images du bac à sable supprimées"
rm -rf $S/src
[ $FAIL = 0 ] && echo "RÉPÉTITION D : GO" || echo "RÉPÉTITION D : NO-GO"; exit $FAIL
