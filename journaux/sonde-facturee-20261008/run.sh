#!/bin/bash
# Lance la sonde avec le même mécanisme que les tests du dépôt (python -m unittest), hors Docker, sans écrire dans le dépôt.
D=/tmp/sonde-facturee-20261008-061729
cd $D
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/root/time-billing-v9-rc10-20261004:$D
export SECRET_KEY=$(head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n') COOKIE_SECURE=0 APP_PASSWORD=sonde-$(head -c8 /dev/urandom | od -An -tx1 | tr -d ' \n')
export DB_PATH=$D/data/boot.db INVOICE_CHECK_WORDS=""
exec $D/venv/bin/python -m unittest -v sonde "$@"
