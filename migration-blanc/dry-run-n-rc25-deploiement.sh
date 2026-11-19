#!/bin/bash
# Répétition N (RC25 phase 2, TB-06) : chaîne de déploiement / retour arrière fail-closed, sur un bac à sable JETABLE (/tmp), base SYNTHÉTIQUE.
# Jamais le staging, la production, /opt ni un vrai .env : projet docker « tbsbx25 », service renommé, port local dédié, secrets de test aléatoires.
#   ancienne version = copie figée 9.2-rc24-3f49b60 (lecture seule) ; nouvelle = app/ de cet arbre, VERSION « 9.2-rc25p2 » (copie dans /tmp)
#   A. 40 sans marqueur GO de 30 : refusé, ancienne version relancée, base inchangée
#   B. 30 en échec (image de répétition absente) : aucun marqueur GO, ancienne version relancée
#   C. port de .env.<rc> ≠ port de URL : 40 refusé avant toute modification
#   D. marqueur GO puis écriture dans la base vivante (service relancé) : 40 refusé (service en marche, puis base changée)
#   E. 20 → 30 GO → 40 → 50 : déployé, vérifications conformes
#   F. donnée écrite après le déploiement dans une table INCONNUE de 90 : retour refusé ; « OUI » non lié au déploiement : refusé
#   G. image de retour supprimée (prune) puis retour confirmé OUI-<TS> : image rechargée depuis la sauvegarde, base = sauvegarde, donnée dans la copie
#   H. échec pendant l'installation (40, phase B : .env.<rc> sans SECRET_KEY) : retour arrière automatique, ancienne version, base = sauvegarde
# Usage : migration-blanc/dry-run-n-rc25-deploiement.sh  (PORT=18493 par défaut ; bac à sable /tmp/rc25p2/N recréé)
set -uo pipefail
MB=$(cd "$(dirname "$0")" && pwd); W=$(cd "$MB/.." && pwd); P=${PROC:-$W/procedure}   # PROC=<autre dossier procedure> : rejouer sur une version de référence
S=${S:-/tmp/rc25p2/N}; PORT=${PORT:-18493}; PJ=tbsbx25; ROOT=$S/opt/tbsbx; DBF=$ROOT/data/timebilling.db
REL24=/root/time-billing-releases/9.2-rc24-3f49b60; RC_IMAGE=${RC_IMAGE:-tb-g4-cand:3f49b60}; NEW=rc25p2
step() { echo; echo "=== $*"; }
ok() { echo "OK    $*"; }; ko() { echo "ÉCHEC $*"; FAIL=1; }; FAIL=0
health() { curl -s -m 5 "http://127.0.0.1:$PORT/health" || true; }
version_is() { for _ in $(seq 1 30); do [[ "$(health)" == *"\"$1\""* ]] && return 0; sleep 1; done; return 1; }
running() { [ "$(docker inspect $PJ --format '{{.State.Running}}' 2>/dev/null)" = true ]; }
# contenu logique (toutes les lignes de toutes les tables hors audit / sessions) : l'ancienne version relancée écrit dans le fichier à son démarrage
# (transactions d'init), le SHA-256 du fichier ne peut donc être comparé qu'avant tout redémarrage (90 le fait lui-même : « SHA-256 identique »)
logical() { python3 - "${1:-$DBF}" <<'PY'
import sqlite3, sys, hashlib, json
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
t = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN ('audit','web_sessions','login_failures','kept_forms') ORDER BY name")]
print(hashlib.sha256(json.dumps({x: [list(r) for r in c.execute(f'SELECT * FROM [{x}] ORDER BY rowid')] for x in t}, default=str).encode()).hexdigest())
PY
}
last() { cat "$S/backups/last-backup"; }
# run <journal> <code attendu 0|1> <motif attendu (grep -E) ou ""> <commande…>
run() { local j=$1 want=$2 pat=$3; shift 3; "$@" > "$S/journal/$j.log" 2>&1; local rc=$?
  if { [ "$want" = 0 ] && [ $rc = 0 ]; } || { [ "$want" = 1 ] && [ $rc != 0 ]; }; then
    if [ -z "$pat" ] || grep -qE "$pat" "$S/journal/$j.log"; then ok "$j : code $rc${pat:+, « $pat »}"; return 0; fi
    ko "$j : motif « $pat » absent"; else ko "$j : code $rc (attendu $( [ "$want" = 0 ] && echo 0 || echo '≠ 0'))"; fi
  tail -n 8 "$S/journal/$j.log" | sed 's/^/      /'; return 1; }

(cd $REL24 && sha256sum -c --quiet SHA256SUMS) || { echo "copie figée rc24 altérée"; exit 1; }
docker image inspect "$RC_IMAGE" >/dev/null 2>&1 || { echo "image de répétition $RC_IMAGE absente"; exit 1; }
[ -d "$S" ] && { (cd "$ROOT" 2>/dev/null && docker compose -p $PJ down >/dev/null 2>&1); docker rm -f $PJ >/dev/null 2>&1; rm -rf "${S:?}"; }
docker images --format '{{.Repository}}:{{.Tag}}' | grep "^$PJ-tbsbx:" | xargs -r docker rmi -f >/dev/null 2>&1
mkdir -p $S/opt $S/backups $S/journal $S/rel25 $ROOT/data; chmod 700 $S $S/backups

step "0. bac à sable : ancienne version rc24 (copie figée), base synthétique, secrets de test"
cp -r $REL24/app $REL24/requirements.txt $REL24/requirements.lock $REL24/Dockerfile $REL24/.dockerignore $ROOT/; chmod -R u+w $ROOT
cp -r $W/app $W/requirements.txt $W/requirements.lock $W/Dockerfile $W/.dockerignore $S/rel25/; find $S/rel25 -name __pycache__ -prune -exec rm -rf {} +
sed -i "s/^VERSION=\"9\\.2-rc[^\"]*\"$/VERSION=\"9.2-$NEW\"/" $S/rel25/app/app.py; grep -q "^VERSION=\"9.2-$NEW\"" $S/rel25/app/app.py || { echo "VERSION non remplacée"; exit 1; }
sed -e 's/^  time-billing-v9-staging:/  tbsbx:/' -e 's/TB_CONTAINER:-time-billing-v9-staging/TB_CONTAINER:-tbsbx25/' -e "s/TB_PORT:-8092/TB_PORT:-$PORT/" \
    $P/docker-compose.staging.yml > $S/compose-template.yml
install -m 644 $S/compose-template.yml $ROOT/docker-compose.yml
HASH=$(docker run --rm --network none "$RC_IMAGE" python -c "import sys;from werkzeug.security import generate_password_hash as g;print(g(sys.argv[1]))" "$(openssl rand -hex 12)")
envfile() { printf "APP_USER=admin\nAPP_PASSWORD_HASH='%s'\nSECRET_KEY='%s'\nCOOKIE_SECURE=0\nTB_PORT=%s\nTB_CONTAINER=%s\nENV_LABEL=RECETTE\n" "$HASH" "$(openssl rand -hex 32)" "$1" $PJ; }
( umask 077; envfile $PORT > $ROOT/.env )
cat > $S/sandbox.conf <<EOF
ROOT=$ROOT
PROJECT=$PJ
CONTAINER=$PJ
IMAGE=$PJ-tbsbx
URL=http://127.0.0.1:$PORT
BACKUP_BASE=$S/backups
SOURCE_APP=$S/rel25/app
SOURCE_REQ=$S/rel25/requirements.txt
RC_IMAGE=$RC_IMAGE
COMPOSE_TEMPLATE=$S/compose-template.yml
EOF
sed "s#^RC_IMAGE=.*#RC_IMAGE=tbsbx25-absente:inexistante#" $S/sandbox.conf > $S/sandbox-sans-image.conf
C=$S/sandbox.conf
chown -R 10001:10001 $ROOT/data; chmod 700 $ROOT/data
(cd $ROOT && docker compose -p $PJ up -d --build --quiet-pull 2>&1 | tail -n 2)
version_is 9.2-rc24 && ok "ancienne version rc24 en marche (base créée par l'application)" || { ko "démarrage rc24 : $(health)"; exit 1; }
(cd $ROOT && docker compose -p $PJ stop >/dev/null 2>&1)
python3 - "$DBF" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute("INSERT INTO projects(name,client,rate,day_hours,vat,billing_address) VALUES('Mandat fictif N','Client Fictif SA',650,8,0,'Client Fictif SA\nRue Imaginaire 1\n9999 Nulle-Part')")
pid = c.execute("SELECT id FROM projects WHERE name='Mandat fictif N'").fetchone()[0]
for d in ('2026-09-01', '2026-09-02', '2026-09-03'): c.execute("INSERT INTO entries(work_date,project_id,hours,description) VALUES(?,?,?,?)", (d, pid, 8, 'saisie fictive'))
c.commit(); print('base synthétique :', c.execute('SELECT COUNT(*) FROM entries').fetchone()[0], 'saisies')
PY
(cd $ROOT && docker compose -p $PJ start >/dev/null 2>&1); version_is 9.2-rc24 || { ko "redémarrage rc24"; exit 1; }
cp -p $ROOT/.env $ROOT/.env.$NEW

step "A. 40 sans marqueur GO de 30"
run 10-preflight 0 "préparation conforme" bash $P/10-preflight.sh $C
run A-20-backup 0 "conforme" bash $P/20-backup.sh $C; TSA=$(last)
[ -f $S/backups/pre-$NEW-$TSA/image.tar.gz ] && grep -q image.tar.gz $S/backups/pre-$NEW-$TSA/SHA256SUMS && ok "copie de l'image de retour dans la sauvegarde (SHA256SUMS)" || ko "image.tar.gz absente"
L0=$(logical)
run A-40-sans-GO 1 "aucun marqueur GO" bash $P/40-deploy.sh $C
version_is 9.2-rc24 && ok "ancienne version relancée par le piège" || ko "service non relancé : $(health)"
[ "$(logical)" = "$L0" ] && ok "contenu de la base inchangé" || ko "contenu de la base modifié"
[ ! -f $S/backups/deployed ] && ok "aucun déploiement enregistré" || ko "« deployed » écrit"

step "B. 30 en échec : pas de marqueur GO, ancienne version relancée"
run B-20-backup 0 "conforme" bash $P/20-backup.sh $C; TSB=$(last)
running && ko "service en marche après 20" || ok "service arrêté par 20"
run B-30-echec 1 "" bash $P/30-rehearse.sh $S/sandbox-sans-image.conf
grep -q "reprise" $S/journal/B-30-echec.log && ok "reprise exécutée par le piège" || ko "reprise absente"
[ ! -e $S/backups/pre-$NEW-$TSB/rehearsal-GO ] && ok "aucun marqueur GO" || ko "marqueur GO présent après échec"
version_is 9.2-rc24 && ok "ancienne version relancée" || ko "service non relancé : $(health)"
run B-40-apres-echec 1 "aucun marqueur GO" bash $P/40-deploy.sh $C

step "C. port de .env.$NEW ≠ port de URL"
run C-20-backup 0 "conforme" bash $P/20-backup.sh $C
run C-30-GO 0 "marqueur GO écrit" bash $P/30-rehearse.sh $C
( umask 077; envfile 8091 > $ROOT/.env.$NEW )
run C-40-port 1 "port publié 8091" bash $P/40-deploy.sh $C
version_is 9.2-rc24 && [ ! -f $S/backups/deployed ] && ok "ancienne version relancée, rien déployé" || ko "état après refus du port"
( umask 077; envfile $PORT > $ROOT/.env.$NEW )

step "D. marqueur GO périmé par une écriture dans la base vivante"
run D-20-backup 0 "conforme" bash $P/20-backup.sh $C
run D-30-GO 0 "marqueur GO écrit" bash $P/30-rehearse.sh $C
(cd $ROOT && docker compose -p $PJ start >/dev/null 2>&1); version_is 9.2-rc24
python3 -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute(\"INSERT INTO entries(work_date,project_id,hours,description) SELECT '2026-09-04',id,4,'écrite après la sauvegarde' FROM projects LIMIT 1\");c.commit()" "$DBF"
run D-40-en-marche 1 "est en marche" bash $P/40-deploy.sh $C
(cd $ROOT && docker compose -p $PJ stop >/dev/null 2>&1)
run D-40-base-changee 1 "base vivante a changé" bash $P/40-deploy.sh $C
version_is 9.2-rc24 && ok "ancienne version relancée" || ko "service non relancé"

step "E. chaîne complète 10 → 20 → 30 (GO) → 40 → 50"
run E-10 0 "" bash $P/10-preflight.sh $C
run E-20 0 "conforme" bash $P/20-backup.sh $C; TSE=$(last); BE=$S/backups/pre-$NEW-$TSE
run E-30 0 "marqueur GO écrit" bash $P/30-rehearse.sh $C
grep -q "^GO ts=$TSE tag=$NEW " $BE/rehearsal-GO && ok "marqueur GO lié à la sauvegarde $TSE" || ko "contenu du marqueur"
run E-40 0 "déployé" bash $P/40-deploy.sh $C
version_is 9.2-$NEW && ok "nouvelle version en marche" || ko "version : $(health)"
run E-50 0 "VÉRIFICATIONS CONFORMES" bash $P/50-verify.sh $C

step "F. donnée postérieure au déploiement dans une table inconnue : retour refusé"
python3 -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute('CREATE TABLE zz_future(id INTEGER PRIMARY KEY, v TEXT)');c.execute(\"INSERT INTO zz_future(v) VALUES('donnée postérieure')\");c.commit()" "$DBF"
run F-90-refus 1 "zz_future : 1 ligne" bash $P/90-rollback.sh $C
version_is 9.2-$NEW && ok "service inchangé (nouvelle version en marche)" || ko "service après refus : $(health)"
run F-90-OUI-non-lie 1 "attendue est OUI-$TSE" env ABANDONNER_CORRECTIONS=OUI bash $P/90-rollback.sh $C
version_is 9.2-$NEW && ok "service inchangé" || ko "service après refus OUI"

step "G. image de retour supprimée (prune), retour confirmé OUI-$TSE"
# toutes les étiquettes pre-* du bac à sable (A à E les posent sur la même image) : l'ancienne image n'est plus référencée, comme après « image prune -a »
docker images --format '{{.Repository}}:{{.Tag}}' | grep "^$PJ-tbsbx:pre-" | xargs -r docker rmi >/dev/null 2>&1
docker image inspect "$PJ-tbsbx:pre-$NEW-$TSE" >/dev/null 2>&1 && ko "étiquette encore présente" || ok "étiquettes pre-* supprimées"
docker image inspect "$(cat $BE/image-id.txt)" >/dev/null 2>&1 && echo "      (NB : image encore présente sous un autre nom ; seule l'étiquette a disparu)" || ok "ancienne image supprimée du moteur docker"
run G-90 0 "rechargée depuis la copie" env ABANDONNER_CORRECTIONS=OUI-$TSE bash $P/90-rollback.sh $C
grep -qE "données écartées par le retour arrière : .*zz_future" $S/journal/G-90.log && ok "écart annoncé (non silencieux)" || ko "écart non annoncé"
grep -q "journal d'audit" $S/journal/G-90.log && ok "lignes d'audit mises de côté comptées" || echo "      (aucune ligne d'audit postérieure)"
version_is 9.2-rc24 && ok "ancienne version rc24 en marche" || ko "version après retour : $(health)"
grep -q "base = sauvegarde $TSE (SHA-256 identique)" $S/journal/G-90.log && ok "90 : base restaurée = sauvegarde $TSE (SHA-256, avant redémarrage)" || ko "SHA de la base restaurée"
[ "$(logical)" = "$(logical $BE/timebilling.db)" ] && ok "contenu de la base = sauvegarde $TSE (après redémarrage)" || ko "contenu différent de la sauvegarde"
K=$(ls -d $S/backups/ecarte-$TSE-retour-* | tail -n 1)/timebilling-avant-retour.db
[ "$(python3 -c "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute('SELECT v FROM zz_future').fetchone()[0])" "$K")" = "donnée postérieure" ] && ok "donnée postérieure conservée dans la copie $K" || ko "copie de la base vivante"

step "H. échec pendant l'installation : retour arrière automatique"
run H-20 0 "conforme" bash $P/20-backup.sh $C; TSH=$(last); BH=$S/backups/pre-$NEW-$TSH
run H-30 0 "marqueur GO écrit" bash $P/30-rehearse.sh $C
( umask 077; envfile $PORT | grep -v '^SECRET_KEY=' > $ROOT/.env.$NEW )
run H-40 1 "retour arrière automatique" bash $P/40-deploy.sh $C
grep -q "retour arrière effectué" $S/journal/H-40.log && ok "90 exécuté par le piège de 40" || ko "90 non exécuté"
version_is 9.2-rc24 && ok "ancienne version rc24 en marche" || ko "version : $(health)"
grep -q "base = sauvegarde $TSH (SHA-256 identique)" $S/journal/H-40.log && ok "90 : base restaurée = sauvegarde $TSH (SHA-256)" || ko "SHA de la base restaurée"
[ "$(logical)" = "$(logical $BH/timebilling.db)" ] && ok "contenu de la base = sauvegarde $TSH" || ko "contenu différent de la sauvegarde"

step "nettoyage"
(cd $ROOT && docker compose -p $PJ down >/dev/null 2>&1); docker images --format '{{.Repository}}:{{.Tag}}' | grep "^$PJ-tbsbx:" | xargs -r docker rmi -f >/dev/null 2>&1
echo; [ $FAIL = 0 ] && echo "RÉPÉTITION N : TOUT CONFORME" || echo "RÉPÉTITION N : ÉCHECS (voir ci-dessus, journaux $S/journal)"; exit $FAIL
