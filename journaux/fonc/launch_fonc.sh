#!/bin/bash
# usage: launch_fonc.sh <nom> <port> <dossier> [base-source]  — conteneur JETABLE (image déployée en staging) sur une COPIE de la base staging (historique inclus). Jamais le staging réel.
set -euo pipefail
N=$1; PORT=$2; DIR=$3; SRC=${4:-/opt/time-billing-v9-staging/data/timebilling.db}
IMG=$(docker image inspect ${IMG_REF:-time-billing-v9-staging-time-billing-v9-staging:latest} --format "{{.Id}}")
docker rm -f $N >/dev/null 2>&1 || true; rm -rf $DIR; mkdir -p $DIR/data; chmod 700 $DIR; chmod 777 $DIR/data
python3 - "$SRC" "$DIR/data/timebilling.db" <<'PY'
import sqlite3,sys
s=sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
PY
chmod 666 $DIR/data/timebilling.db; head -c12 /dev/urandom | xxd -p > $DIR/pw.txt; chmod 600 $DIR/pw.txt
docker run -d --name $N -p 127.0.0.1:$PORT:8000 -v $DIR/data:/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=0 -e INVOICE_CHECK_WORDS= -e DB_PATH=/data/timebilling.db -e ENV_LABEL=RECETTE -e APP_PASSWORD=$(cat $DIR/pw.txt) $IMG >/dev/null
for i in $(seq 1 40); do curl -sf http://127.0.0.1:$PORT/health >/dev/null && { echo "prêt $N :$PORT"; exit 0; }; sleep 1; done; echo "échec démarrage $N"; docker logs $N | tail -5; exit 1
