#!/bin/bash
# Recette finale RC10 (navigateur Chromium + HTTP + concurrence) sur l'IMAGE DÉPLOYÉE EN STAGING, dans des conteneurs jetables
# sur une COPIE de la base staging, données exclusivement fictives. Aucune écriture dans le staging ni la production.
set -uo pipefail
W=/root/time-billing-v9-rc10-20261004; RUN=${RUN:-final}; PFX=${PFX:-tb-rc10f}; PB=${PB:-8194}; O=$W/recette/$RUN; J=$W/journaux/$RUN
IMG=$(docker image inspect ${IMG_REF:-time-billing-v9-staging-time-billing-v9-staging:latest} --format '{{.Id}}')   # IMG_REF=…:rc11 pour la recette d'une version non déployée
mkdir -p $O/ecrans $O/pdf $O/dl $O/journaux $O/work $J; chmod 700 $O
cp $W/tests/browser/*.js $O/journaux/; cp $W/recette/metier/journaux/logo-fictif.png $O/journaux/
STG0=$(sha256sum /opt/time-billing-v9-staging/data/timebilling.db | cut -d' ' -f1)
launch() { # nom port dossier
  docker rm -f $1 >/dev/null 2>&1; rm -rf $3; mkdir -p $3/data; chmod 777 $3/data; cp ${SRC_DB:-/opt/time-billing-v9-staging/data/timebilling.db} $3/data/timebilling.db; chmod 666 $3/data/timebilling.db
  head -c12 /dev/urandom | xxd -p > $3/pw.txt; chmod 600 $3/pw.txt
  docker run -d --name $1 -p 127.0.0.1:$2:8000 -v $3/data:/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=0 -e INVOICE_CHECK_WORDS= -e DB_PATH=/data/timebilling.db -e ENV_LABEL=RECETTE -e APP_PASSWORD=$(cat $3/pw.txt) $IMG >/dev/null
  for i in $(seq 1 30); do curl -sf http://127.0.0.1:$2/health >/dev/null && break; sleep 1; done; }
rc=0; export EXPECT_VERSION=$(sed -n 's/^VERSION="\(.*\)"/\1/p' $W/app/app.py)
# 1. parcours métier complet : phase 1, redémarrage, phase 2
launch ${PFX}-metier $((PB+0)) $O/work/metier
(cd $O/journaux && PW_FILE=$O/work/metier/pw.txt BASE_URL=http://127.0.0.1:$((PB+0)) node recette-metier.js phase1 > recette-metier-phase1.log 2>&1) || rc=1
docker restart ${PFX}-metier >/dev/null; sleep 5
(cd $O/journaux && PW_FILE=$O/work/metier/pw.txt BASE_URL=http://127.0.0.1:$((PB+0)) node recette-metier.js phase2 > recette-metier-phase2.log 2>&1) || rc=1
docker rm -f ${PFX}-metier >/dev/null; mv $O/work/metier/data $O/work/metier-data-apres 2>/dev/null
# 2. gestion des saisies
launch ${PFX}-sais $((PB+1)) $O/work/sais
(cd $O/journaux && PW_FILE=$O/work/sais/pw.txt BASE_URL=http://127.0.0.1:$((PB+1)) DB_FILE=$O/work/sais/data/timebilling.db node recette-saisies.js phase1 > recette-saisies-phase1.log 2>&1) || rc=1
docker restart ${PFX}-sais >/dev/null; sleep 5
(cd $O/journaux && PW_FILE=$O/work/sais/pw.txt BASE_URL=http://127.0.0.1:$((PB+1)) DB_FILE=$O/work/sais/data/timebilling.db node recette-saisies.js phase2 > recette-saisies-phase2.log 2>&1) || rc=1
docker rm -f ${PFX}-sais >/dev/null
# 3. HTTP bout en bout (2 phases, redémarrage) + concurrence (gthread)
launch ${PFX}-e2e $((PB+2)) $O/work/e2e; docker cp $W/tests/e2e_http.py ${PFX}-e2e:/app/e2e_http.py; docker cp $W/tests/concurrency_http.py ${PFX}-e2e:/app/concurrency_http.py
docker exec -e APP_PASSWORD=$(cat $O/work/e2e/pw.txt) ${PFX}-e2e python -W ignore /app/e2e_http.py phase1 > $O/journaux/e2e_phase1.log 2>&1 || rc=1
docker restart ${PFX}-e2e >/dev/null; sleep 5
docker exec -e APP_PASSWORD=$(cat $O/work/e2e/pw.txt) ${PFX}-e2e python -W ignore /app/e2e_http.py phase2 > $O/journaux/e2e_phase2.log 2>&1 || rc=1
docker rm -f ${PFX}-e2e >/dev/null
# concurrence : conteneur FRAIS (le test suppose une base vide : 28 saisies, 2 brouillons) — jamais dans le conteneur e2e déjà peuplé
launch ${PFX}-conc $((PB+5)) $O/work/conc; docker cp $W/tests/concurrency_http.py ${PFX}-conc:/app/concurrency_http.py
docker exec ${PFX}-conc python -W ignore /app/concurrency_http.py > $O/journaux/concurrence.log 2>&1 || rc=1
docker rm -f ${PFX}-conc >/dev/null
# 4. affichage adaptatif (téléphone / tablette / bureau) sur données fictives
launch ${PFX}-ux $((PB+3)) $O/work/ux
cp $W/tests/browser/seed-ux.js $O/work/ux/seed-ux.js; cp $O/work/ux/pw.txt $O/work/ux/pw.txt.bak
(cd $O/work/ux && BASE_URL=http://127.0.0.1:$((PB+3)) node seed-ux.js > $O/journaux/seed-ux.log 2>&1) || rc=1
mkdir -p $O/ecrans-responsive
(cd $O/journaux && PW_FILE=$O/work/ux/pw.txt BASE_URL=http://127.0.0.1:$((PB+3)) DB_FILE=$O/work/ux/data/timebilling.db OUT=$O/ecrans-responsive node recette-responsive.js > recette-responsive.log 2>&1) || rc=1
docker rm -f ${PFX}-ux >/dev/null
# 4b. RC12 : saisie conservée après refus, deux onglets, PDF à adresses longues, archive vide
launch ${PFX}-rc12 $((PB+4)) $O/work/rc12; mkdir -p $O/ecrans-rc12
(cd $O/journaux && PW_FILE=$O/work/rc12/pw.txt BASE_URL=http://127.0.0.1:$((PB+4)) OUT=$O/ecrans-rc12 node recette-rc12.js > recette-rc12.log 2>&1) || rc=1
docker rm -f ${PFX}-rc12 >/dev/null
# 4c. RC13 : motif d'annexe imprimé en entier (pdftotext), déclencheurs SQL actifs dans l'application en marche
launch ${PFX}-rc13 $((PB+6)) $O/work/rc13; docker cp $W/tests/e2e_http.py ${PFX}-rc13:/app/tests_e2e_http.py; docker cp $W/tests/e2e_rc13.py ${PFX}-rc13:/app/e2e_rc13.py
docker exec -e APP_PASSWORD=$(cat $O/work/rc13/pw.txt) -w /app ${PFX}-rc13 python -W ignore /app/e2e_rc13.py > $O/journaux/e2e_rc13.log 2>&1 || rc=1
PDFT=$(pdftotext -layout $O/work/rc13/data/rc13-annex.pdf - 2>/dev/null | tr -s ' \n' ' ')
for w in "Préparation de l'atelier de cadrage" "budget détaillé" "comité de pilotage"; do case "$PDFT" in *"$w"*) echo "annexe : « $w » imprimé" >> $O/journaux/e2e_rc13.log;; *) echo "ÉCHEC annexe : « $w » absent du PDF" >> $O/journaux/e2e_rc13.log; rc=1;; esac; done
case "$PDFT" in *"…"*) echo "ÉCHEC annexe : troncature « … » dans le PDF" >> $O/journaux/e2e_rc13.log; rc=1;; esac
docker rm -f ${PFX}-rc13 >/dev/null
# 4d. RC14 : design « Liquid Glass » (navigation, cartes, recherche d'archive, parcours existants, responsive, console)
launch ${PFX}-rc14 $((PB+7)) $O/work/rc14; mkdir -p $O/ecrans-rc14
(cd $O/journaux && PW_FILE=$O/work/rc14/pw.txt BASE_URL=http://127.0.0.1:$((PB+7)) OUT=$O/ecrans-rc14 node recette-rc14.js > recette-rc14.log 2>&1) || rc=1
docker rm -f ${PFX}-rc14 >/dev/null
# 4e. Nuit RC14 : filtres d'archive, position des mandats, aperçu d'import dans la coque, rendu téléphone
launch ${PFX}-nuit $((PB+8)) $O/work/nuit; mkdir -p $O/ecrans-nuit; cp $W/tests/browser/releve-fictif-nuit.xlsx $O/journaux/
(cd $O/journaux && PW_FILE=$O/work/nuit/pw.txt BASE_URL=http://127.0.0.1:$((PB+8)) OUT=$O/ecrans-nuit node recette-nuit.js > recette-nuit.log 2>&1) || rc=1
docker rm -f ${PFX}-nuit >/dev/null
# 4f. RC17/18 : saisie passant minuit (décision C5) dans le navigateur, bureau + téléphone, erreurs console
launch ${PFX}-minuit $((PB+9)) $O/work/minuit; mkdir -p $O/ecrans-minuit
(cd $O/journaux && PW_FILE=$O/work/minuit/pw.txt BASE_URL=http://127.0.0.1:$((PB+9)) OUT_DIR=$O/ecrans-minuit node recette-minuit.js > recette-minuit.log 2>&1) || rc=1
docker rm -f ${PFX}-minuit >/dev/null
# 4g. RC19 : saisies toujours éditables, facture émise immuable, écart post-facturation et décision ; sur une COPIE de la base staging
# (saisies historiques réelles, mandats clôturés : indépendant de SRC_DB), bureau + téléphone ; captures hors dépôt
mkdir -p $O/ecrans-rc19; IMG_REF=${IMG_REF:-time-billing-v9-staging-time-billing-v9-staging:latest} $W/journaux/fonc/launch_fonc.sh ${PFX}-rc19 $((PB+10)) $O/work/rc19 >/dev/null || rc=1
(cd $O/journaux && PW_FILE=$O/work/rc19/pw.txt BASE_URL=http://127.0.0.1:$((PB+10)) DB_FILE=$O/work/rc19/data/timebilling.db OUT_DIR=$O/ecrans-rc19 node recette-rc19.js > recette-rc19.log 2>&1) || rc=1
docker rm -f ${PFX}-rc19 >/dev/null
# 5. contrôles de fin
[ "$(sha256sum /opt/time-billing-v9-staging/data/timebilling.db | cut -d' ' -f1)" = "$STG0" ] && echo "base staging inchangée" || { echo "ÉCHEC : base staging modifiée"; rc=1; }
for f in $O/journaux/recette-metier-phase1.log $O/journaux/recette-metier-phase2.log $O/journaux/recette-saisies-phase1.log $O/journaux/recette-saisies-phase2.log $O/journaux/recette-responsive.log $O/journaux/recette-rc12.log $O/journaux/recette-rc14.log $O/journaux/recette-nuit.log $O/journaux/recette-minuit.log $O/journaux/recette-rc19.log $O/journaux/e2e_rc13.log $O/journaux/e2e_phase1.log $O/journaux/e2e_phase2.log $O/journaux/concurrence.log; do n=$(grep -c '^FAIL' $f); echo "$(basename $f): $(grep -E '^RESULT|passed|résultat|RÉSULTAT|^RC1[24] navigateur|^NUIT navigateur' $f | tail -1)  FAIL=$n"; { [ -s $f ] && [ "$n" = 0 ]; } || { echo "ÉCHEC : $(basename $f) vide ou en échec"; rc=1; }; done
echo "rc=$rc"; exit $rc
