#!/bin/bash
# Variante de setup-sandbox.sh SANS lecture de /opt (consigne du 2026-10-06) : l'arborescence V9.0 du bac à sable vient de l'archive
# tree.tar.gz d'une sauvegarde d'un bac à sable précédent (A19, B19 : arborescence de prod copiée le 2026-10-05, base A ou B, secrets de test).
# Usage : setup-sandbox-copie.sh <nouveau nom> <port> <tree.tar.gz source> <nom du bac à sable source>
set -euo pipefail
sc=$1; port=$2; TREE=${3:?archive tree.tar.gz}; old=${4:?nom du bac à sable source}; MB=$(cd "$(dirname "$0")" && pwd); P=$MB/../procedure; S=$MB/$sc
l=$(echo $sc | tr A-Z a-z); o=$(echo $old | tr A-Z a-z)
[ -e "$S" ] && { echo "$S existe déjà"; exit 1; }
mkdir -p $S/opt $S/backups; chmod 700 $S $S/backups
tar -C $S/opt -xzf "$TREE"
R=$S/opt/time-billing-v9
grep -q 'version="9.0-rc1"' $R/app/app.py || { echo "l'archive n'est pas l'arborescence V9.0"; exit 1; }
sed -i -e "s/container_name: tbmb-$o/container_name: tbmb-$l/" -e "s/127.0.0.1:[0-9]*:8000/127.0.0.1:$port:8000/" $R/docker-compose.yml
grep -q "tbmb-$l" $R/docker-compose.yml && grep -q "127.0.0.1:$port:8000" $R/docker-compose.yml && grep -q 'SANDBOX_PASSWORD' $R/docker-compose.yml || { echo "compose du bac à sable incomplet"; exit 1; }
( umask 077; { echo "SANDBOX_PASSWORD=$(openssl rand -hex 12)"; echo "SANDBOX_KEY=$(openssl rand -hex 32)"; } > $R/.env.v90 ); cp -p $R/.env.v90 $R/.env
chmod 700 $R/data; chmod 600 $R/data/timebilling.db
cat > $S/sandbox.conf <<EOF
ROOT=$R
PROJECT=tbmb-$l
CONTAINER=tbmb-$l
IMAGE=tbmb-$l-time-billing-v9
URL=http://127.0.0.1:$port
BACKUP_BASE=$S/backups
SOURCE_APP=$MB/../app
SOURCE_REQ=$MB/../requirements.txt
RC_IMAGE=${RC_IMAGE:?image candidate}
COMPOSE_TEMPLATE=$P/docker-compose.prod.yml
TB_PORT=$port
EOF
# copie de référence du code V9.0 pour le contrôle « code = code V9.0 » après retour (au lieu de /opt/time-billing-v9/app)
mkdir -p $S/ref-v90; tar -C $S/ref-v90 -xzf "$TREE" time-billing-v9/app
echo "bac à sable $sc prêt (base : $(sha256sum < $R/data/timebilling.db | cut -c1-12))"
