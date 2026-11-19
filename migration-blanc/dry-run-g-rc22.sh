#!/bin/bash
# Répétition G (rc22, 2026-10-08) : la séquence prévue pour un éventuel déploiement de 9.2-rc22 sur le staging (décision de l'utilisateur, non prise),
# sur un faux staging jetable dans l'état du staging réel après le déploiement rc21 du 2026-10-07 13:09 UTC. Aucune lecture de /opt : base =
# sauvegarde pre-rc21-20261007T130853Z (SHA vérifié ; celle que 40 a migrée en rc21 à 13:09), code rc21 = copie de publication figée
# /root/time-billing-releases/9.2-rc21-51b7c1b (celle de staging.conf), code rc22 = copie figée 9.2-rc22-2282419.
#   0. faux staging rc21 (secrets de test)        1. 10 → 20 → 30 → 40 → 50 (rc22)
#   2. contrôles rc22 : données métier identiques (outils/empreinte_metier.py + pages), brouillon n°1, export .xlsx, correctifs rc22
#   3. retour arrière (rien d'écrit) : accepté → rc21, base = sauvegarde      4. redéploiement 10 → 50
#   5. parcours utilisateur : validation des 24 historiques, export      6. retour arrière après validation : doit être refusé
# Jamais le staging réel ni la production. Usage : [PORT=<port>] migration-blanc/dry-run-g-rc22.sh   (port 8436 par défaut, bac à sable migration-blanc/G-RC22, recréé)
set -uo pipefail
MB=$(cd "$(dirname "$0")" && pwd); W=$(cd $MB/.. && pwd); S=$MB/G-RC22; P=$W/procedure; PORT=${PORT:-8436}
ROOT=$S/opt/time-billing-v9-staging; DBF=$ROOT/data/timebilling.db
REL21=/root/time-billing-releases/9.2-rc21-51b7c1b; REL22=/root/time-billing-releases/9.2-rc22-2282419
RC21_IMAGE=tb-g4-cand:51b7c1b; RC22_IMAGE=tb-g4-cand:2282419
PRE=/root/backups/time-billing-v9-staging/pre-rc21-20261007T130853Z
LIB=$W/tests/recette_fonctionnelle
step() { echo; echo "=== $*"; }
ok() { echo "OK    $*"; }; ko() { echo "ÉCHEC $*"; FAIL=1; }; FAIL=0
for R in $REL21 $REL22; do (cd $R && sha256sum -c --quiet SHA256SUMS) && ok "copie de publication $(basename $R) intacte" || { ko "copie $R altérée"; exit 1; }; done
grep -q '^VERSION="9.2-rc22"' $REL22/app/app.py || { echo "copie rc22 : VERSION inattendue"; exit 1; }
docker rm -f tbmb-grc22 >/dev/null 2>&1; [ -d "$S" ] && { (cd $ROOT 2>/dev/null && docker compose -p tbmb-grc22 down >/dev/null 2>&1); chmod -R u+w "$S" 2>/dev/null; rm -rf "$S"; }
mkdir -p $S/opt $S/backups $S/journal $ROOT/data; chmod 700 $S $S/backups

step "0. faux staging rc21 : code = copie figée 9.2-rc21-51b7c1b, base = $(basename $PRE) (SHA vérifié), secrets de test"
(cd $PRE && sha256sum -c --quiet SHA256SUMS) && ok "sauvegarde pre-rc21 intacte" || { ko "sauvegarde pre-rc21 altérée"; exit 1; }
cp -r $REL21/app $REL21/requirements.txt $REL21/requirements.lock $REL21/Dockerfile $REL21/.dockerignore $ROOT/; chmod -R u+w $ROOT
install -m 644 $P/docker-compose.staging.yml $ROOT/docker-compose.yml
cp $PRE/timebilling.db $DBF
PW=$(openssl rand -hex 12); echo -n "$PW" > $S/pw.txt; chmod 600 $S/pw.txt
HASH=$(docker run --rm --network none $RC21_IMAGE python -c "import sys;from werkzeug.security import generate_password_hash as g;print(g(sys.argv[1]))" "$PW")
( umask 077; printf "APP_USER=admin\nAPP_PASSWORD_HASH='%s'\nSECRET_KEY='%s'\nCOOKIE_SECURE=0\nTB_PORT=%s\nTB_CONTAINER=tbmb-grc22\nENV_LABEL=RECETTE\n" "$HASH" "$(openssl rand -hex 32)" $PORT > $ROOT/.env )
cat > $S/sandbox.conf <<EOF
ROOT=$ROOT
PROJECT=tbmb-grc22
CONTAINER=tbmb-grc22
IMAGE=tbmb-grc22-time-billing-v9-staging
URL=http://127.0.0.1:$PORT
BACKUP_BASE=$S/backups
SOURCE_APP=$REL22/app
SOURCE_REQ=$REL22/requirements.txt
RC_IMAGE=$RC22_IMAGE
COMPOSE_TEMPLATE=$P/docker-compose.staging.yml
EOF
chown -R 10001:10001 $ROOT/data; chmod 700 $ROOT/data; chmod 600 $DBF
(cd $ROOT && docker compose -p tbmb-grc22 up -d --build --quiet-pull 2>&1 | tail -1)
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:$PORT/health >/dev/null && break; sleep 1; done
V0=$(curl -s http://127.0.0.1:$PORT/health); echo "santé : $V0"; grep -q '9.2-rc21' <<<"$V0" && ok "faux staging en rc21" || { ko "version d'origine ($V0)"; exit 1; }
HTTP() { python3 - "$PORT" "$S" "$DBF" "$@" || FAIL=1; }
# copie cohérente de la base du bac à sable (API de sauvegarde SQLite, service en marche) : comparée par outils/empreinte_metier.py
COPY() { python3 -c "import sqlite3,sys;s=sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True);d=sqlite3.connect(sys.argv[2]);s.backup(d)" $DBF $1; }
METIER() { python3 -I $W/outils/empreinte_metier.py comparer "$1" "$2" > $S/cmp.txt; local r=$?; [ $r = 0 ] && ok "$3 — $(head -1 $S/cmp.txt)" || { ko "$3"; cat $S/cmp.txt; }; }
SNAP() { python3 - "$PORT" "$S" "$DBF" "$1" "$LIB" <<'PY'
import sys, re, html, json, hashlib
port, S, db, out, lib = sys.argv[1:6]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
snap = {'n_saisies': A.one('select count(*) from entries'), 'heures': A.one('select round(sum(hours),4) from entries'),
        'historiques_par_statut': A.q('select status,count(*) from historical_invoices group by status')}
pg = html.unescape(A.get('/issue/1')); snap['controles_brouillon_1'] = sorted(re.findall(r'data-check="(\d+)" data-status="(\w+)"', pg), key=lambda x: int(x[0]))
pos = html.unescape(A.get('/'))
snap['accueil_chiffres'] = hashlib.sha256(re.sub(r'\s+', ' ', ' '.join(re.findall(r'CHF[^<]{0,40}|\d[\d\s’\']*,\d\d', pos))).encode()).hexdigest()
json.dump(snap, open(out, 'w'), indent=1, default=str)
print(f"INFO  état : {snap['n_saisies']} saisies / {snap['heures']} h ; historiques {snap['historiques_par_statut']} ; brouillon n°1 en échec : {[k for k, v in snap['controles_brouillon_1'] if v == 'fail']}")
PY
}
SAME() { python3 - "$1" "$2" "$3" <<'PY'
import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])); diff = [k for k in a if a[k] != b.get(k)]
print(('OK    ' if not diff else 'ÉCHEC ') + sys.argv[3] + ('' if not diff else ' — différences : ' + ', '.join(diff))); sys.exit(1 if diff else 0)
PY
[ $? = 0 ] || FAIL=1; }
EXPORT() { python3 - "$PORT" "$S" "$DBF" "$1" "$LIB" <<'PY'
import sys
port, S, db, out, lib = sys.argv[1:6]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
s, h, b = A.req('/export/classeur.xlsx'); open(out, 'wb').write(b)
print(('OK    ' if s == 200 and b[:2] == b'PK' else 'ÉCHEC ') + f'export .xlsx téléchargé ({s}, {len(b)} octets)'); sys.exit(0 if s == 200 and b[:2] == b'PK' else 1)
PY
[ $? = 0 ] || FAIL=1; }
SHEETS() { docker run --rm --network none -v "$1:/x.xlsx:ro" $RC22_IMAGE python -c "
import openpyxl; wb = openpyxl.load_workbook('/x.xlsx'); print(' | '.join(wb.sheetnames))"; }
COPY $S/base-rc21.db; SNAP $S/etat-rc21.json
EXPORT $S/export-rc21.xlsx; SHEETS $S/export-rc21.xlsx > $S/onglets-rc21.txt

step "1. déploiement rc22 : 10 → 20 → 30 → 40 → 50 (comme le staging : .env conservé)"
deploy() {
  bash $P/10-preflight.sh $S/sandbox.conf || ko "10-preflight"
  bash $P/20-backup.sh $S/sandbox.conf || { ko "20-backup"; return 1; }
  bash $P/30-rehearse.sh $S/sandbox.conf || ko "30-rehearse"
  cp -p $ROOT/.env $ROOT/.env.rc22
  bash $P/40-deploy.sh $S/sandbox.conf || { ko "40-deploy"; return 1; }
  bash $P/50-verify.sh $S/sandbox.conf || ko "50-verify"
}
deploy || exit 1
grep -q "$(cd $REL22/app && find . -type f ! -path '*/__pycache__/*' ! -name '*.before-*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64)" $S/backups/pre-rc22-$(cat $S/backups/last-backup)/source-app.sha256 \
  && ok "empreinte du code noté par 20 = copie figée rc22" || ko "empreinte du code déployé"

step "2. contrôles rc22 : mêmes données métier que rc21, brouillon n°1, export, correctifs de la revue rc19"
COPY $S/base-rc22.db; METIER $S/base-rc21.db $S/base-rc22.db "rc22 : toutes les tables métier identiques à rc21 (outils/empreinte_metier.py)"
SNAP $S/etat-rc22.json; SAME $S/etat-rc21.json $S/etat-rc22.json "rc22 : saisies, heures, historiques, contrôles du brouillon n°1 et chiffres de l'accueil identiques à rc21"
EXPORT $S/export-rc22.xlsx; SHEETS $S/export-rc22.xlsx > $S/onglets-rc22.txt
cmp -s $S/onglets-rc21.txt $S/onglets-rc22.txt && ok "export .xlsx : mêmes onglets qu'en rc21 ($(cat $S/onglets-rc22.txt | tr '|' '\n' | wc -l) onglets)" || ko "onglets de l'export différents : $(cat $S/onglets-rc21.txt) ≠ $(cat $S/onglets-rc22.txt)"
HTTP "$LIB" <<'PY'
import sys
port, S, db, lib = sys.argv[1:5]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
s, _, _ = A.req('/entries?project=%C2%B2'); print(('OK    ' if s == 200 else 'ÉCHEC ') + f'/entries?project=² : {s} (rc21 : erreur 500)')
pg = A.get('/entry/1/edit'); c = 'sauf rattachement à un mandat clôturé' in pg
print(('OK    ' if c else 'ÉCHEC ') + 'libellé « Motif (facultatif, sauf rattachement à un mandat clôturé) »')
sys.exit(0 if s == 200 and c else 1)
PY

step "3. retour arrière (aucune donnée métier écrite depuis la sauvegarde) : accepté → rc21"
TS=$(cat $S/backups/last-backup)
bash $P/90-rollback.sh $S/sandbox.conf 2>&1 | tee $S/retour-1.log; [ ${PIPESTATUS[0]} = 0 ] && ok "90-rollback accepté" || ko "90-rollback"
grep -q "base = sauvegarde $TS (SHA-256 identique)" $S/retour-1.log && ok "base restaurée = sauvegarde d'avant déploiement (SHA-256 vérifié par 90-rollback)" || ko "SHA de la base restaurée non confirmé"
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc21' <<<"$H" && ok "version rc21 de retour" || ko "version après retour : $H"
COPY $S/base-retour.db; METIER $S/base-rc21.db $S/base-retour.db "après retour : toutes les tables métier identiques à rc21"
SNAP $S/etat-retour.json; SAME $S/etat-rc21.json $S/etat-retour.json "après retour : état rc21 identique (pages)"

step "4. redéploiement rc22 : 10 → 50"
deploy || exit 1
COPY $S/base-rc22-bis.db; METIER $S/base-rc21.db $S/base-rc22-bis.db "après redéploiement : tables métier identiques à rc21"

step "5. parcours utilisateur sur rc22 : validation des 24 historiques, puis export"
HTTP "$LIB" <<'PY'
import sys
port, S, db, lib = sys.argv[1:5]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
for (pid,) in A.q("select distinct project_id from historical_invoices where status='proposed'"): A.post(f'/historique/mandat/{pid}/valider', {})
r = A.q('select status,count(*) from historical_invoices group by status'); c = r == [('validated', 24)]
print(('OK    ' if c else 'ÉCHEC ') + f'24 historiques validées par la page : {r}'); sys.exit(0 if c else 1)
PY
EXPORT $S/export-rc22-apres-validation.xlsx
python3 - "$PORT" "$S" "$DBF" "$LIB" <<'PY' || FAIL=1
import sys, json
port, S, db, lib = sys.argv[1:5]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db)
d = json.loads(A.q("select detail from audit where event='gsheet_export_downloaded' order by id desc limit 1")[0][0]); s = d.get('suivi', {})
norm = lambda v: str(v).replace("'", '').replace(' ', '').replace(' ', '').replace('\xa0', '').replace(',', '.')
c = norm(s.get('2025')) in ('67236.00', '67236', '67236.0') and norm(s.get('2026')) in ('70973.50', '70973.5')
print(('OK    ' if c else 'ÉCHEC ') + f"CA des onglets SUIVI = « Facturé » de Billing (2025 67 236,00 ; 2026 70 973,50, comme la répétition E en rc21) : {s}")
sys.exit(0 if c else 1)
PY

step "6. retour arrière après validation des historiques : doit être REFUSÉ"
COPY $S/avant-tentative.db
if bash $P/90-rollback.sh $S/sandbox.conf > $S/retour-2.log 2>&1; then cat $S/retour-2.log; ko "retour arrière ACCEPTÉ alors que 24 validations ont été écrites depuis la sauvegarde"
else tail -3 $S/retour-2.log; ok "retour arrière refusé (validations écrites depuis la sauvegarde)"; fi
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc22' <<<"$H" && ok "service rc22 toujours en marche" || ko "service après la tentative : $H"
COPY $S/apres-tentative.db; METIER $S/avant-tentative.db $S/apres-tentative.db "base inchangée par la tentative"
grep -q "historical_invoices : 24 ligne(s) modifiée(s)" $S/retour-2.log && ok "motif du refus : historical_invoices : 24 ligne(s) modifiée(s)" || ko "motif du refus inattendu : $(grep ARRÊT $S/retour-2.log)"

step "7. nettoyage"
(cd $ROOT && docker compose -p tbmb-grc22 down >/dev/null 2>&1); docker image ls --format '{{.Repository}}:{{.Tag}}' | grep '^tbmb-grc22-time-billing-v9-staging' | xargs -r docker rmi >/dev/null 2>&1 && echo "images du bac à sable supprimées"
rm -f $S/*.db; rm -rf $S/opt/time-billing-v9-staging/data/backups
[ $FAIL = 0 ] && echo "RÉPÉTITION G : GO" || echo "RÉPÉTITION G : NO-GO"; exit $FAIL
