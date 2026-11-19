#!/bin/bash
# Usage: run_unit.sh [module ...]  — tests unitaires dans un conteneur jetable SANS réseau, sur copie de la base staging.
W=/root/time-billing-v9-rc10-20261004; S=$W/recette/base
IMG=${IMG:-time-billing-v9-rc10-test:latest}
MODS=${@:-tests.test_functional tests.test_import tests.test_rc3 tests.test_rc4 tests.test_rc5 tests.test_rc6 tests.test_rc7 tests.test_rc8 tests.test_rc9_import tests.test_v92 tests.test_credit_settlement}
rm -rf $S/work; mkdir -p $S/work; cp $S/data/base.db $S/work/base.db; chmod -R 777 $S/work
docker run --rm --network none -v ${APP_DIR:-$W/app}:/app/app:ro -v $W/tests:/app/tests:ro -v $W/outils:/app/outils:ro -v $S/work:/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=0 -e INVOICE_CHECK_WORDS= -e BASE_DB=/data/base.db -e DB_PATH=/data/boot.db -e APP_PASSWORD=t$(head -c8 /dev/urandom | xxd -p) -w /app $IMG python -W ignore -m unittest $MODS 2>&1
