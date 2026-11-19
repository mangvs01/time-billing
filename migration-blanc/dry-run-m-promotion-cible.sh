#!/bin/bash
# Répétition M (2026-10-08) : la répétition H (promotion de la base du staging vers la production, G4 = PROMOTE_STAGING_DB) rejouée avec la
# VERSION CIBLE ACTUELLE de la bascule G5 et les données du staging du 08.10 09:10 UTC, sur deux bacs à sable, sans aucune lecture de /opt :
#   - fausse PRODUCTION = arborescence V9.0 de l'archive A19 (base A = copie exacte de la base de production du 05.10 : vide), déployée dans la
#     version cible par la procédure (10 → 20 → 30 → rotate-secrets → 40 → 50) depuis la copie de publication figée, comme le prévoit prod.conf ;
#   - faux STAGING = version cible sur la sauvegarde du staging pre-rc23-20261008T091053Z (tes données), recette simulée : 24 historiques validées.
# Contrôles identiques à H (refus versions différentes / sans PROMOUVOIR=OUI / production non vide ; échec simulé → base d'origine remise ;
# production = staging ; mot de passe de la production ; donnée corrigeable après promotion ; retour 90 refusé puis accepté → V9.0, SHA-256).
# Usage : [REL=<copie figée> IMG=<image>] migration-blanc/dry-run-m-promotion-cible.sh   (défaut : rc23 = 9.2-rc23-50492d4 / tb-g4-cand:50492d4 ;
#         ports PP=8457 production, PS=8458 staging ; bacs à sable migration-blanc/M-PROD et M-STG, recréés). Dérivé de dry-run-h-promotion.sh.
set -uo pipefail
MB=$(cd "$(dirname "$0")" && pwd); W=$(cd $MB/.. && pwd); P=$W/procedure; LIB=$W/tests/recette_fonctionnelle; EMP=$W/outils/empreinte_metier.py
PP=${PP:-8457}; PS=${PS:-8458}; SP=$MB/M-PROD; SS=$MB/M-STG
REL21=${REL:-/root/time-billing-releases/9.2-rc23-50492d4}; RC21_IMAGE=${IMG:-tb-g4-cand:50492d4}; VER=$(sed -n 's/^VERSION="\(.*\)"$/\1/p' $REL21/app/app.py); TAG=${VER#9.2-}
TREE=$MB/A19/backups/pre-rc19-20261005T132712Z/tree.tar.gz
PRE=/root/backups/time-billing-v9-staging/pre-rc23-20261008T091053Z
step() { echo; echo "=== $*"; }
ok() { echo "OK    $*"; }; ko() { echo "ÉCHEC $*"; FAIL=1; }; FAIL=0
emp() { python3 -I $EMP "$@"; }
COPY() { python3 -c "import sqlite3,sys;s=sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True);d=sqlite3.connect(sys.argv[2]);s.backup(d)" "$1" "$2"; }
health() { curl -s -m 5 http://127.0.0.1:$1/health; }
(cd $REL21 && sha256sum -c --quiet SHA256SUMS) && ok "copie de publication $TAG intacte" || { ko "copie $TAG altérée"; exit 1; }
(cd $PRE && sha256sum -c --quiet SHA256SUMS) && ok "sauvegarde du staging $(basename $PRE) intacte" || { ko "sauvegarde altérée"; exit 1; }
for s in $SP $SS; do [ -d "$s" ] && { for r in $s/opt/*; do [ -f $r/docker-compose.yml ] && (cd $r && docker compose -p tbmb-$(basename $s | tr A-Z a-z) down >/dev/null 2>&1); done; chmod -R u+w $s; rm -rf $s; }; done

step "0a. fausse production V9.0 (archive A19, base A vide), conf = prod.conf du bac à sable (copie de publication $TAG)"
RC_IMAGE=$RC21_IMAGE bash $MB/setup-sandbox-copie.sh M-PROD $PP $TREE A19 || exit 1
sed -i -e "s#^SOURCE_APP=.*#SOURCE_APP=$REL21/app#" -e "s#^SOURCE_REQ=.*#SOURCE_REQ=$REL21/requirements.txt#" $SP/sandbox.conf
TROOT=$SP/opt/time-billing-v9; TDB=$TROOT/data/timebilling.db; SHA_V90=$(sha256sum < $TDB)
(cd $TROOT && docker compose -p tbmb-m-prod up -d --build --quiet-pull 2>&1 | tail -1)
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:$PP/health >/dev/null && break; sleep 1; done
grep -q '9.0-rc1' <<<"$(health $PP)" && ok "fausse production en V9.0 : $(health $PP)" || { ko "production V9.0 : $(health $PP)"; exit 1; }

step "0b. faux staging $TAG ($(basename $PRE) = tes données), recette simulée : 24 historiques validées"
SROOT=$SS/opt/time-billing-v9-staging; SDB=$SROOT/data/timebilling.db
mkdir -p $SS/backups $SROOT/data; chmod 700 $SS $SS/backups
cp -r $REL21/app $REL21/requirements.txt $REL21/requirements.lock $REL21/Dockerfile $REL21/.dockerignore $SROOT/; chmod -R u+w $SROOT
install -m 644 $P/docker-compose.staging.yml $SROOT/docker-compose.yml; cp $PRE/timebilling.db $SDB
SPW=$SS/pw.txt; ( umask 077; openssl rand -hex 12 | tr -d '\n' > $SPW )
HASH=$(docker run --rm --network none $RC21_IMAGE python -c "import sys;from werkzeug.security import generate_password_hash as g;print(g(sys.argv[1]))" "$(cat $SPW)")
( umask 077; printf "APP_USER=admin\nAPP_PASSWORD_HASH='%s'\nSECRET_KEY='%s'\nCOOKIE_SECURE=0\nTB_PORT=%s\nTB_CONTAINER=tbmb-m-stg\nENV_LABEL=STAGING\n" "$HASH" "$(openssl rand -hex 32)" $PS > $SROOT/.env )
cat > $SS/sandbox.conf <<EOF
ROOT=$SROOT
PROJECT=tbmb-m-stg
CONTAINER=tbmb-m-stg
IMAGE=tbmb-m-stg-time-billing-v9-staging
URL=http://127.0.0.1:$PS
BACKUP_BASE=$SS/backups
SOURCE_APP=$REL21/app
SOURCE_REQ=$REL21/requirements.txt
RC_IMAGE=$RC21_IMAGE
COMPOSE_TEMPLATE=$P/docker-compose.staging.yml
EOF
chown -R 10001:10001 $SROOT/data; chmod 700 $SROOT/data; chmod 600 $SDB
(cd $SROOT && docker compose -p tbmb-m-stg up -d --build --quiet-pull 2>&1 | tail -1)
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:$PS/health >/dev/null && break; sleep 1; done
grep -q "$VER" <<<"$(health $PS)" && ok "faux staging en $TAG" || { ko "staging : $(health $PS)"; exit 1; }
python3 - $PS $SPW $SDB $LIB <<'PY' || FAIL=1
import sys
port, pw, db, lib = sys.argv[1:5]; sys.path.insert(0, lib); from lib import App
A = App(port, pw, db); assert A.login(), 'connexion staging'
for (pid,) in A.q("select distinct project_id from historical_invoices where status='proposed'"): A.post(f'/historique/mandat/{pid}/valider', {})
r = A.q('select status,count(*) from historical_invoices group by status'); c = r == [('validated', 24)]
print(('OK    ' if c else 'ÉCHEC ') + f'recette simulée sur le staging : 24 historiques validées {r}'); sys.exit(0 if c else 1)
PY
# journaux de 70 (journaux/promotion-<TS> du dépôt) déplacés dans le bac à sable : ce ne sont pas ceux d'une vraie promotion
PROMO() { local avant; avant=$(ls -d $W/journaux/promotion-* 2>/dev/null); CONFIRM_PROD= bash $P/70-promouvoir-base-staging.sh $SP/sandbox.conf $SS/sandbox.conf; local r=$?
  mkdir -p $SP/journal; for j in $(ls -d $W/journaux/promotion-* 2>/dev/null); do grep -qx "$j" <<<"$avant" || mv "$j" $SP/journal/; done; return $r; }

step "1. promotion AVANT le déploiement de la production (V9.0 ≠ $TAG) : doit être refusée, rien d'arrêté"
COPY $SDB $SS/s-ref.db
PROMOUVOIR=OUI PROMO > $SP/h1.log 2>&1 && { cat $SP/h1.log; ko "promotion acceptée avec des versions différentes"; } || { grep ARRÊT $SP/h1.log; grep -q "versions différentes" $SP/h1.log && ok "refus : versions différentes" || ko "motif inattendu"; }
grep -q 9.0-rc1 <<<"$(health $PP)" && grep -q "$VER" <<<"$(health $PS)" && ok "production et staging toujours en marche" || ko "services après refus"

step "2. déploiement de la fausse production en $TAG : 10 → 20 → 30 → rotate-secrets → 40 → 50 (copie de publication)"
bash $P/10-preflight.sh $SP/sandbox.conf >/dev/null || ko "10"
bash $P/20-backup.sh $SP/sandbox.conf > $SP/d20.log 2>&1 || { cat $SP/d20.log; ko "20"; exit 1; }
bash $P/30-rehearse.sh $SP/sandbox.conf > $SP/d30.log 2>&1 || { tail $SP/d30.log; ko "30"; exit 1; }
TPW=$SP/.new-password; ( umask 077; openssl rand -base64 18 | tr -d '\n' > $TPW )
NEW_PASSWORD_FILE=$TPW COOKIE_SECURE=0 TRUST_PROXY=0 bash $P/rotate-secrets.sh $SP/sandbox.conf >/dev/null || { ko "rotate-secrets"; exit 1; }
bash $P/40-deploy.sh $SP/sandbox.conf > $SP/d40.log 2>&1 || { tail $SP/d40.log; ko "40"; exit 1; }
bash $P/50-verify.sh $SP/sandbox.conf > $SP/d50.log 2>&1 && ok "production déployée en $TAG, 50-verify conforme" || { tail $SP/d50.log; ko "50"; }
COPY $TDB $SP/t-vide.db; emp vide $SP/t-vide.db >/dev/null && ok "production $TAG sans donnée métier ($(emp vide $SP/t-vide.db))" || ko "production non vide après déploiement : $(emp vide $SP/t-vide.db)"
TSHA=$(sha256sum < $TDB)

step "3. sans PROMOUVOIR=OUI : refus"
PROMO > $SP/h3.log 2>&1 && ko "promotion sans confirmation acceptée" || { grep -q "PROMOUVOIR=OUI" $SP/h3.log && ok "refus : confirmation PROMOUVOIR=OUI exigée" || { cat $SP/h3.log; ko "motif inattendu"; }; }

grep -v '^PROJECT=' $SS/sandbox.conf > $SS/sans-projet.conf
PROMOUVOIR=OUI CONFIRM_PROD= bash $P/70-promouvoir-base-staging.sh $SP/sandbox.conf $SS/sans-projet.conf > $SP/h3b.log 2>&1 && ko "configuration du staging sans PROJECT acceptée" \
  || { grep -q "configuration du staging incomplète" $SP/h3b.log && ok "refus : configuration du staging incomplète (aucun héritage de la production)" || { cat $SP/h3b.log; ko "motif inattendu"; }; }
rm -f $SS/sans-projet.conf

step "4. échec simulé après l'installation : la base de production d'origine doit être remise, les deux services relancés"
TB_TEST_ECHEC=apres-installation PROMOUVOIR=OUI PROMO > $SP/h4.log 2>&1 && ko "échec simulé non détecté" || { grep -E "ARRÊT|ÉCHEC|restaurée" $SP/h4.log; }
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:$PP/health >/dev/null && curl -sf http://127.0.0.1:$PS/health >/dev/null && break; sleep 1; done
grep -q "$VER" <<<"$(health $PP)" && grep -q "$VER" <<<"$(health $PS)" && ok "production et staging relancés après l'échec" || ko "services après échec : $(health $PP) / $(health $PS)"
COPY $TDB $SP/t-apres-echec.db; emp vide $SP/t-apres-echec.db >/dev/null && emp comparer $SP/t-vide.db $SP/t-apres-echec.db >/dev/null && ok "production : base d'origine (vide) remise" || ko "production après échec différente de l'origine"
ls $SP/backups/promotion-*/production-echec.db >/dev/null 2>&1 && ok "base installée avant l'échec conservée (production-echec.db)" || ko "production-echec.db absente"
COPY $SDB $SS/s-apres-echec.db; emp comparer $SS/s-ref.db $SS/s-apres-echec.db >/dev/null && ok "staging intact après l'échec" || ko "staging modifié par l'échec"

step "5. promotion"
PROMOUVOIR=OUI PROMO 2>&1 | tee $SP/h5.log; [ ${PIPESTATUS[0]} = 0 ] && ok "70-promouvoir-base-staging : TERMINÉ" || { ko "promotion"; }
grep -q "$VER" <<<"$(health $PP)" && ok "production en marche : $(health $PP)" || ko "production : $(health $PP)"
[ -z "$(health $PS)" ] && ok "staging laissé ARRÊTÉ (gel)" || ko "staging encore en marche : $(health $PS)"
COPY $TDB $SP/t-promue.db; emp comparer $SS/s-ref.db $SP/t-promue.db && ok "production = staging (toutes les tables métier)" || ko "production ≠ staging"
emp comparer $SS/s-ref.db $SDB >/dev/null && ok "base du staging intacte (tables métier)" || ko "base du staging modifiée"
python3 - $PP $TPW $SPW $TDB $LIB <<'PY' || FAIL=1
import sys, re, html, json
port, tpw, spw, db, lib = sys.argv[1:6]; sys.path.insert(0, lib); from lib import App
bad = App(port, spw, db); c0 = not bad.login(); print(('OK    ' if c0 else 'ÉCHEC ') + 'mot de passe du STAGING refusé par la production')
A = App(port, tpw, db); c1 = A.login(); print(('OK    ' if c1 else 'ÉCHEC ') + 'connexion à la production avec SON mot de passe (secrets de la production conservés)')
ev = A.q("select detail from audit where event='database_promoted_from_staging'"); c2 = len(ev) == 1
print(('OK    ' if c2 else 'ÉCHEC ') + f"événement d'audit de la promotion : {ev[0][0][:160] if ev else '—'}")
s = A.q("select count(*) from web_sessions")[0][0]; c3 = s == 1; print(('OK    ' if c3 else 'ÉCHEC ') + f'sessions web du staging purgées (1 session = cette connexion) : {s}')
r = A.q('select status,count(*) from historical_invoices group by status'); c4 = r == [('validated', 24)]; print(('OK    ' if c4 else 'ÉCHEC ') + f'24 historiques validées en production : {r}')
# condition de l'utilisateur : les données restent corrigeables après la bascule — correction tracée d'une saisie importée, par la page
eid = A.one("select id from entries where source='historical_excel' and start_time<>'' order by id limit 1"); pg = html.unescape(A.get(f'/entry/{eid}/edit'))
form = dict(re.findall(r'<input[^>]*name="(\w+)"[^>]*value="([^"]*)"', pg)); form['entry_mode'] = re.search(r'name="entry_mode" value="(\w+)" checked', pg).group(1)
form['project_id'] = re.search(r'<option value="(\d+)"[^>]*selected', pg).group(1); before = A.one('select description from entries where id=?', (eid,))
form['description'] = (before or '') + ' (corrigé après bascule)'; form['reason'] = 'répétition H : donnée corrigeable après promotion'
st, msgs = A.post(f'/entry/{eid}/edit', form); after = A.one('select description from entries where id=?', (eid,))
n = A.one("select count(*) from entry_changes where entry_id=? and reason like 'répétition H%'", (eid,)); c5 = after == form['description'] and n == 1
print(('OK    ' if c5 else 'ÉCHEC ') + f'saisie {eid} corrigée en production après promotion, correction tracée ({n}) — {msgs[:1]}')
sys.exit(0 if all((c0, c1, c2, c3, c4, c5)) else 1)
PY

step "6. seconde promotion (staging relancé) : refusée, la production contient des données"
(cd $SROOT && docker compose -p tbmb-m-stg start >/dev/null 2>&1); for _ in $(seq 1 60); do curl -sf http://127.0.0.1:$PS/health >/dev/null && break; sleep 1; done
COPY $TDB $SP/t-avant-2.db
PROMOUVOIR=OUI PROMO > $SP/h6.log 2>&1 && ko "seconde promotion acceptée" || { grep ARRÊT $SP/h6.log; grep -q "contient déjà des données" $SP/h6.log && ok "refus : production non vide" || ko "motif inattendu"; }
COPY $TDB $SP/t-apres-2.db; emp comparer $SP/t-avant-2.db $SP/t-apres-2.db >/dev/null && ok "production inchangée par la tentative" || ko "production modifiée par la tentative"
grep -q "$VER" <<<"$(health $PS)" && ok "staging toujours en marche (refus avant tout arrêt)" || ko "staging : $(health $PS)"
(cd $SROOT && docker compose -p tbmb-m-stg stop >/dev/null 2>&1)

step "7. retour arrière de la production : refusé sans ABANDONNER_CORRECTIONS, puis accepté → V9.0, base d'origine"
bash $P/90-rollback.sh $SP/sandbox.conf > $SP/r1.log 2>&1 && ko "retour arrière accepté sans ABANDONNER_CORRECTIONS" || { grep ARRÊT $SP/r1.log | cut -c1-300; ok "retour refusé (données promues et correction écrites depuis la sauvegarde)"; }
ABANDONNER_CORRECTIONS=OUI bash $P/90-rollback.sh $SP/sandbox.conf > $SP/r2.log 2>&1 && ok "retour arrière accepté avec ABANDONNER_CORRECTIONS=OUI" || { tail -5 $SP/r2.log; ko "retour arrière"; }
grep -q 9.0-rc1 <<<"$(health $PP)" && ok "production de retour en V9.0" || ko "version après retour : $(health $PP)"
TS=$(cat $SP/backups/last-backup); [ "$(sha256sum < $TDB)" = "$(sha256sum < $SP/backups/pre-$TAG-$TS/timebilling.db)" ] && ok "base de production = sauvegarde d'avant déploiement (SHA-256)" || ko "base après retour"
[ "$(sha256sum < $SP/backups/pre-$TAG-$TS/timebilling.db)" = "$SHA_V90" ] && ok "… = base V9.0 d'origine (SHA-256 de la copie A)" || ko "sauvegarde ≠ base A d'origine"
emp comparer $SS/s-ref.db $SDB >/dev/null && ok "données promues intactes sur le staging après le retour arrière" || ko "staging modifié"
ls $SP/backups/promotion-*/production-avant.db $SP/backups/promotion-*/staging.db >/dev/null 2>&1 && (cd $(ls -d $SP/backups/promotion-* | tail -1) && sha256sum -c --quiet SHA256SUMS) && ok "sauvegarde promotion-<TS> présente et vérifiée (SHA256SUMS)" || ko "sauvegarde de promotion"

step "8. nettoyage"
for r in $TROOT $SROOT; do (cd $r && docker compose -p $([ $r = $TROOT ] && echo tbmb-m-prod || echo tbmb-m-stg) down >/dev/null 2>&1); done
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -E '^tbmb-m-(prod|stg)-' | xargs -r docker rmi >/dev/null 2>&1 && echo "images des bacs à sable supprimées"
rm -f $SP/*.db $SS/*.db $TPW
[ $FAIL = 0 ] && echo "RÉPÉTITION M : GO" || echo "RÉPÉTITION M : NO-GO"; exit $FAIL
