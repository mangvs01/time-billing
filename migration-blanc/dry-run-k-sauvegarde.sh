#!/bin/bash
# Répétition K (2026-10-08) : sauvegarde quotidienne à chaud (procedure/backup-quotidien.sh) et vérification de restaurabilité
# (procedure/verifier-sauvegarde.sh) sur une production FICTIVE en 9.2-rc23 (copie figée 9.2-rc23-50492d4, image tb-g4-cand:50492d4) portant
# une copie des données réelles du staging (sauvegarde pre-rc23-20261008T061057Z). Aucune lecture de /opt ; ROOT de bac à sable (le garde-fou
# production de tb-common.sh ne s'applique pas ici : voir la fiche Decision Center sur la planification de la sauvegarde en production).
#   1. production fictive (conteneur jetable)   2. deux sauvegardes à chaud, service en marche, écriture entre les deux
#   3. vérification de restaurabilité de la dernière   4. sauvegarde altérée après coup : la sauvegarde suivante doit s'arrêter
# Usage : migration-blanc/dry-run-k-sauvegarde.sh [PORT]   (port 8439 ; bac à sable migration-blanc/K-SAUV, recréé)
set -uo pipefail
MB=$(cd "$(dirname "$0")" && pwd); W=$(cd $MB/.. && pwd); S=$MB/K-SAUV; P=$W/procedure; PORT=${1:-8439}
REL=/root/time-billing-releases/9.2-rc23-50492d4; IMG=tb-g4-cand:50492d4; NAME=tb-k-sauv
PRE=/root/backups/time-billing-v9-staging/pre-rc23-20261008T061057Z
ok() { echo "OK    $*"; }; ko() { echo "KO    $*"; FAIL=1; }; step() { echo; echo "=== $*"; }; FAIL=0
step "0. bac à sable"
docker rm -f $NAME >/dev/null 2>&1; rm -rf "$S"; mkdir -p "$S/data" "$S/root"; chmod 700 "$S"; chmod 777 "$S/data"
(cd "$PRE" && sha256sum -c --quiet SHA256SUMS) && ok "sauvegarde source intacte" || { ko "sauvegarde source altérée"; exit 1; }
cp "$PRE/timebilling.db" "$S/data/timebilling.db"; chmod 666 "$S/data/timebilling.db"
cat > "$S/sandbox.conf" <<EOF
ROOT=$S/root
PROJECT=tb-k-sauv
CONTAINER=$NAME
IMAGE=$IMG
URL=http://127.0.0.1:$PORT
BACKUP_BASE=$S/backups
SOURCE_APP=$REL/app
SOURCE_REQ=$REL/requirements.txt
RC_IMAGE=$IMG
COMPOSE_TEMPLATE=$P/docker-compose.prod.yml
EOF
docker run -d --name $NAME -p 127.0.0.1:$PORT:8000 -v "$S/data":/data -e SECRET_KEY=$(openssl rand -hex 32) -e APP_PASSWORD=$(openssl rand -hex 12) \
  -e COOKIE_SECURE=0 -e DB_PATH=/data/timebilling.db -e ENV_LABEL=RECETTE $IMG >/dev/null
for _ in $(seq 60); do curl -sf -m 2 http://127.0.0.1:$PORT/health >/dev/null && break; sleep 1; done
curl -s http://127.0.0.1:$PORT/health | grep -q '"9.2-rc23"' && ok "production fictive en 9.2-rc23" || ko "version"

step "1. première sauvegarde à chaud (service en marche)"
$P/backup-quotidien.sh "$S/sandbox.conf" && ok "sauvegarde 1" || ko "sauvegarde 1"
F1=$(ls -1t "$S"/backups/quotidiennes/timebilling-*.db | head -1)
n1=$(python3 -I -c "import sqlite3,sys; print(sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True).execute('SELECT COUNT(*) FROM entries').fetchone()[0])" "$F1")
[ "$n1" = 2247 ] && ok "sauvegarde 1 : 2 247 saisies" || ko "sauvegarde 1 : $n1 saisies"
docker exec $NAME test -e /data/.backup-auto.db && ko "fichier temporaire resté dans /data" || ok "fichier temporaire retiré de /data"
[ "$(stat -c %a "$F1")" = 600 ] && [ "$(stat -c %a "$S/backups/quotidiennes")" = 700 ] && ok "droits 600 / 700" || ko "droits"

step "2. écriture entre deux sauvegardes, puis seconde sauvegarde"
sleep 1
docker exec $NAME python -c "import sqlite3; c=sqlite3.connect('/data/timebilling.db'); c.execute(\"INSERT INTO settings(key,value) VALUES('k_repetition','1') ON CONFLICT(key) DO UPDATE SET value='2'\"); c.commit()"
$P/backup-quotidien.sh "$S/sandbox.conf" && ok "sauvegarde 2" || ko "sauvegarde 2"
F2=$(ls -1t "$S"/backups/quotidiennes/timebilling-*.db | head -1)
[ "$F2" != "$F1" ] && python3 -I -c "import sqlite3,sys; assert sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True).execute(\"SELECT value FROM settings WHERE key='k_repetition'\").fetchone()" "$F2" \
  && ok "sauvegarde 2 contient l'écriture faite après la 1" || ko "sauvegarde 2 sans l'écriture"
[ "$(wc -l < "$S/backups/quotidiennes/SHA256SUMS")" = 2 ] && ok "SHA256SUMS : 2 lignes d'origine" || ko "SHA256SUMS"

step "3. vérification de restaurabilité (conteneur jetable sans réseau)"
$P/verifier-sauvegarde.sh "$S/sandbox.conf" "$F2" && ok "sauvegarde 2 restaurable" || ko "vérification"

step "4. sauvegarde 1 altérée après coup : la sauvegarde suivante doit s'arrêter en le signalant"
chmod 600 "$F1"; printf 'x' | dd of="$F1" bs=1 seek=200 conv=notrunc 2>/dev/null
sleep 1
out=$($P/backup-quotidien.sh "$S/sandbox.conf" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "ne correspond plus" <<<"$out" && ok "altération détectée (code $rc)" || ko "altération non détectée : $out"

step "5. nettoyage"
docker rm -f $NAME >/dev/null; ok "conteneur retiré (bac à sable conservé : $S)"
[ $FAIL = 0 ] && echo "RÉPÉTITION K : GO" || echo "RÉPÉTITION K : NO-GO"
exit $FAIL
