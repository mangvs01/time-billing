#!/bin/bash
# Suites HTTP de la recette fonctionnelle sur une instance JETABLE (copie du staging avec historique), image IMG_REF. usage: run_http_suites.sh <tag-sortie> [IMG_REF]
cd /root/time-billing-v9-rc10-20261004; T=$1; export IMG_REF=${2:-time-billing-v9-staging-time-billing-v9-staging:latest}; export CTN=tb-fonc-$T; D=$PWD/recette/fonc/$T; L=journaux/fonc/$T; mkdir -p $L
S0=$(sha256sum /opt/time-billing-v9-staging/data/timebilling.db | cut -d' ' -f1)
docker rm -f tb-fonc-restore tb-fonc-import >/dev/null 2>&1
journaux/fonc/launch_fonc.sh $CTN 8310 $D > $L/launch.log 2>&1 || exit 9
rc=0; for s in ab cg dg extra hij; do python3 tests/recette_fonctionnelle/run_$s.py 8310 $D > $L/run_$s.log 2>&1; r=$?; echo "$s rc=$r $(grep '^RÉSULTAT' $L/run_$s.log)"; rc=$((rc|r)); done
# K (prévision) : copie FRAÎCHE — son recalcul indépendant suppose qu'aucune facture n'a été émise sur la copie
docker rm -f tb-fonc-k >/dev/null 2>&1; journaux/fonc/launch_fonc.sh tb-fonc-k 8312 $PWD/recette/fonc/k-$T > $L/launch-k.log 2>&1 || exit 9
python3 tests/recette_fonctionnelle/run_forecast.py 8312 $PWD/recette/fonc/k-$T > $L/run_forecast.log 2>&1; r=$?; echo "forecast rc=$r $(grep '^RÉSULTAT' $L/run_forecast.log)"; rc=$((rc|r)); docker rm -f tb-fonc-k >/dev/null 2>&1
# Q (entités vides C2, ECIO C3) : copie FRAÎCHE — crée puis supprime des brouillons (ne doit pas décaler les numéros des autres lots)
docker rm -f tb-fonc-q >/dev/null 2>&1; journaux/fonc/launch_fonc.sh tb-fonc-q 8313 $PWD/recette/fonc/q-$T > $L/launch-q.log 2>&1 || exit 9
python3 tests/recette_fonctionnelle/run_entites_vides.py 8313 $PWD/recette/fonc/q-$T > $L/run_entites_vides.log 2>&1; r=$?; echo "entites_vides rc=$r $(grep '^RÉSULTAT' $L/run_entites_vides.log)"; rc=$((rc|r)); docker rm -f tb-fonc-q >/dev/null 2>&1
echo "version testée: $(curl -s http://127.0.0.1:8310/health)"
[ "$(sha256sum /opt/time-billing-v9-staging/data/timebilling.db | cut -d' ' -f1)" = "$S0" ] && echo "base staging réelle inchangée" || { echo "ÉCHEC: base staging modifiée"; rc=1; }
docker rm -f $CTN tb-fonc-restore tb-fonc-import >/dev/null 2>&1; echo "rc=$rc"
