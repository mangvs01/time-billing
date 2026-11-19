#!/bin/bash
# Prépare un bac à sable : arborescence de prod copiée (sans data ni compose), base = extraction en lecture seule,
# compose de prod reproduit mais assaini (nom, écoute locale, secrets de test aléatoires dans .env).
set -euo pipefail
sc=$1; port=$2; SRC=${3:?base source (copie)}; MB=$(cd "$(dirname "$0")" && pwd); P=$MB/../procedure; S=$MB/$sc; l=$(echo $sc | tr A-Z a-z)
[ -e "$S" ] && { echo "$S existe déjà"; exit 1; }
mkdir -p $S/opt $S/backups; chmod 700 $S $S/backups
rsync -a --exclude data --exclude docker-compose.yml --exclude '__pycache__' /opt/time-billing-v9/ $S/opt/time-billing-v9/
mkdir -p $S/opt/time-billing-v9/data; cp "$SRC" $S/opt/time-billing-v9/data/timebilling.db; chmod 700 $S/opt/time-billing-v9/data; chmod 600 $S/opt/time-billing-v9/data/timebilling.db
sed -e "s/container_name: time-billing-v9/container_name: tbmb-$l/" -e "s/\"8091:8000\"/\"127.0.0.1:$port:8000\"/" \
    -e 's/APP_PASSWORD: ".*"/APP_PASSWORD: ${SANDBOX_PASSWORD}/' -e 's/SECRET_KEY: ".*"/SECRET_KEY: ${SANDBOX_KEY}/' /opt/time-billing-v9/docker-compose.yml > $S/opt/time-billing-v9/docker-compose.yml
grep -q 'SANDBOX_PASSWORD' $S/opt/time-billing-v9/docker-compose.yml && grep -q 'SANDBOX_KEY' $S/opt/time-billing-v9/docker-compose.yml || { echo "assainissement du compose incomplet"; exit 1; }
( umask 077; { echo "SANDBOX_PASSWORD=$(openssl rand -hex 12)"; echo "SANDBOX_KEY=$(openssl rand -hex 32)"; } > $S/opt/time-billing-v9/.env.v90 ); cp -p $S/opt/time-billing-v9/.env.v90 $S/opt/time-billing-v9/.env
cat > $S/sandbox.conf <<EOF
ROOT=$S/opt/time-billing-v9
PROJECT=tbmb-$l
CONTAINER=tbmb-$l
IMAGE=tbmb-$l-time-billing-v9
URL=http://127.0.0.1:$port
BACKUP_BASE=$S/backups
SOURCE_APP=$MB/../app
SOURCE_REQ=$MB/../requirements.txt
RC_IMAGE=time-billing-v9-staging-time-billing-v9-staging:$(sed -n 's/^VERSION="9.2-\(.*\)"/\1/p' $MB/../app/app.py)
COMPOSE_TEMPLATE=$P/docker-compose.prod.yml
TB_PORT=$port
EOF
echo "bac à sable $sc prêt"
