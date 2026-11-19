#!/bin/bash
# Recette navigateur rapide de la nuit : RC14 + responsive sur une IMAGE locale (IMG, ex. tb-nuit:c1), conteneurs jetables tb-nuit-q-*,
# ports 8310-8312, copie de la base staging (vide). Aucune écriture dans le staging ni la production.
set -uo pipefail
W=/root/time-billing-v9-rc10-20261004; IMG=${IMG:?IMG}; O=/tmp/nuit/rapide-${IMG//[:\/]/-}; rm -rf $O; mkdir -p $O; chmod 700 $O
launch() { docker rm -f $1 >/dev/null 2>&1; mkdir -p $3/data; chmod 777 $3/data; cp /opt/time-billing-v9-staging/data/timebilling.db $3/data/timebilling.db; chmod 666 $3/data/timebilling.db
  head -c12 /dev/urandom | xxd -p > $3/pw.txt; chmod 600 $3/pw.txt
  docker run -d --name $1 -p 127.0.0.1:$2:8000 -v $3/data:/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=0 -e INVOICE_CHECK_WORDS= -e DB_PATH=/data/timebilling.db -e ENV_LABEL=RECETTE -e APP_PASSWORD=$(cat $3/pw.txt) $IMG >/dev/null
  for i in $(seq 1 30); do curl -sf http://127.0.0.1:$2/health >/dev/null && break; sleep 1; done; }
rc=0
launch tb-nuit-q-rc14 8310 $O/rc14; mkdir -p $O/ecrans-rc14
(cd $W/tests/browser && PW_FILE=$O/rc14/pw.txt BASE_URL=http://127.0.0.1:8310 OUT=$O/ecrans-rc14 node recette-rc14.js > $O/recette-rc14.log 2>&1) || rc=1
docker rm -f tb-nuit-q-rc14 >/dev/null
launch tb-nuit-q-nuit 8312 $O/nuit; mkdir -p $O/ecrans-nuit
(cd $W/tests/browser && PW_FILE=$O/nuit/pw.txt BASE_URL=http://127.0.0.1:8312 OUT=$O/ecrans-nuit node recette-nuit.js > $O/recette-nuit.log 2>&1) || rc=1
docker rm -f tb-nuit-q-nuit >/dev/null
launch tb-nuit-q-ux 8311 $O/ux; cp $W/tests/browser/seed-ux.js $O/ux/
(cd $O/ux && BASE_URL=http://127.0.0.1:8311 node seed-ux.js > $O/seed-ux.log 2>&1) || rc=1
mkdir -p $O/ecrans-responsive
(cd $W/tests/browser && PW_FILE=$O/ux/pw.txt BASE_URL=http://127.0.0.1:8311 DB_FILE=$O/ux/data/timebilling.db OUT=$O/ecrans-responsive node recette-responsive.js > $O/recette-responsive.log 2>&1) || rc=1
docker rm -f tb-nuit-q-ux >/dev/null
for f in $O/recette-rc14.log $O/recette-nuit.log $O/recette-responsive.log; do echo "$(basename $f): $(grep -E '^RESULT|^RC14 navigateur|^NUIT navigateur' $f | tail -1) FAIL=$(grep -c '^FAIL' $f)"; grep '^FAIL' $f | head -5; done
echo "journaux : $O ; rc=$rc"; exit $rc
