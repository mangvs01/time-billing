#!/bin/bash
# Copie jetable du staging (historique inclus) -> application des mandats « niveau certain » + clôture des mandats TERMINE -> recette L (première facture réelle).
# Jamais le staging réel. usage: run_mandats_premiere_facture.sh [IMG_REF]
cd /root/time-billing-v9-rc10-20261004; export IMG_REF=${1:-time-billing-v9-staging-time-billing-v9-staging:latest}; D=$PWD/recette/fonc/m
S0=$(sha256sum /opt/time-billing-v9-staging/data/timebilling.db | cut -d' ' -f1)
journaux/fonc/launch_fonc.sh tb-fonc-m 8320 $D || exit 9
python3 tests/recette_fonctionnelle/mandats_appliquer.py --port 8320 --pwfile $D/pw.txt --db $D/data/timebilling.db --level certain --close-termine --apply | tail -2 || exit 8
python3 tests/recette_fonctionnelle/run_mandats.py 8320 $D; rc=$?
python3 tests/recette_fonctionnelle/run_pages.py 8320 $D; rc=$((rc|$?))
python3 tests/recette_fonctionnelle/run_premiere_facture.py 8320 $D; rc=$((rc|$?))
docker rm -f tb-fonc-m >/dev/null 2>&1
[ "$(sha256sum /opt/time-billing-v9-staging/data/timebilling.db | cut -d' ' -f1)" = "$S0" ] && echo "base staging réelle inchangée" || { echo "ÉCHEC: base staging modifiée"; rc=1; }
exit $rc
