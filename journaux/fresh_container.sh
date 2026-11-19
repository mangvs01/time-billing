#!/bin/bash
# Usage: fresh_container.sh <name> <port> <dir>  — conteneur jetable RC10 sur COPIE vide de la base staging (données fictives uniquement)
W=/root/time-billing-v9-rc10-20261004; N=$1; P=$2; D=$3; IMG=${IMG:-time-billing-v9-rc10-test:latest}
docker rm -f $N >/dev/null 2>&1; rm -rf $D/data; mkdir -p $D/data; chmod 777 $D/data
cp ${BASE_DB:-$W/recette/base/data/base.db} $D/data/timebilling.db; chmod 666 $D/data/timebilling.db
PW="Rc10-$(head -c9 /dev/urandom | xxd -p)"; echo $PW > $D/pw.txt; chmod 600 $D/pw.txt
docker run -d --name $N -p 127.0.0.1:$P:8000 -v $W/app:/app/app:ro -v $W/tests:/app/tests:ro -v $D/data:/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=0 -e INVOICE_CHECK_WORDS= -e DB_PATH=/data/timebilling.db -e APP_PASSWORD=$PW $IMG >/dev/null
for i in $(seq 1 20); do curl -sf http://127.0.0.1:$P/health >/dev/null && break; sleep 1; done; curl -s http://127.0.0.1:$P/health; echo
