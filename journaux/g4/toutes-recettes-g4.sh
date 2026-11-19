#!/bin/bash
# G4 (rc19 + G4, 2026-10-06) : toutes les recettes sur copies jetables (jamais le staging réel), image candidate :rc19. Résumé dans journaux/g4/recettes-g4.txt
cd /root/time-billing-v9-rc10-20261004; IMG=time-billing-v9-staging-time-billing-v9-staging:rc19; J=journaux/g4; S=$J/recettes-g4.txt; : > $S
echo "== $(date -u +%FT%TZ) lot R (copie fraîche du staging)" >> $S
export IMG_REF=$IMG; D=$PWD/recette/fonc/r19-lotR; journaux/fonc/launch_fonc.sh tb-r19-lotr 8402 $D > $J/launch-lotR.log 2>&1
python3 tests/recette_fonctionnelle/run_rc19.py 8402 $D > $J/run_rc19-final.log 2>&1; echo "lot R rc=$? $(grep '^RÉSULTAT' $J/run_rc19-final.log)" >> $S; docker rm -f tb-r19-lotr >/dev/null 2>&1
echo "== $(date -u +%FT%TZ) lots A–K + prévision + Q" >> $S
journaux/fonc/run_http_suites.sh r19 $IMG > $J/run_http_suites.log 2>&1; echo "A–K/Q rc=$?" >> $S; grep -E "rc=|version|staging" $J/run_http_suites.log >> $S
echo "== $(date -u +%FT%TZ) lots M, N, L (mandats préparés, première facture)" >> $S
journaux/fonc/run_mandats_premiere_facture.sh $IMG > $J/run_mandats_premiere_facture.log 2>&1; echo "M/N/L rc=$?" >> $S; grep -E "^RÉSULTAT|staging" $J/run_mandats_premiere_facture.log >> $S
echo "== $(date -u +%FT%TZ) navigateur complet (base d'avant import) + lot rc19 (copie staging)" >> $S
RUN=r19 PFX=tb-r19b PB=8200 IMG_REF=$IMG SRC_DB=/root/backups/time-billing-v9-staging/pre-import-historique-20261005T014206Z.db journaux/recette_navigateur_final.sh > $J/recette_navigateur_final.log 2>&1
echo "navigateur rc=$?" >> $S; tail -20 $J/recette_navigateur_final.log >> $S
echo "== $(date -u +%FT%TZ) FIN" >> $S
