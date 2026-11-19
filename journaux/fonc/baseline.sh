#!/bin/bash
cd /root/time-billing-v9-rc10-20261004
ALL=$(ls tests/test_*.py | sed 's#tests/#tests.#;s#\.py$##' | tr '\n' ' ')
echo "== unitaires ($ALL)" > journaux/fonc/unit-complet.log
IMG=time-billing-v9-rc10-test:latest journaux/run_unit.sh $ALL >> journaux/fonc/unit-complet.log 2>&1
echo "UNIT_DONE rc=$?" >> journaux/fonc/unit-complet.log
RUN=fonc1 PFX=tb-fonc1 PB=8230 journaux/recette_navigateur_final.sh > journaux/fonc/recette-navigateur.out 2>&1
echo "RECETTE_DONE rc=$?" >> journaux/fonc/recette-navigateur.out
