#!/bin/bash
# Lance outils/aller_retour_formulaires.py contre un conteneur JETABLE sur une COPIE de base (jamais le staging réel, aucune lecture sous /opt).
# Usage : outils/lancer_aller_retour.sh IMAGE BASE_SOURCE.db JOURNAL.json [NOM_CONTENEUR] [PORT]
# La base source n'est jamais ouverte en écriture : elle est copiée dans un dossier temporaire supprimé à la fin (conteneur retiré aussi).
set -u
W=/root/time-billing-v9-rc10-20261004
IMG=${1:?image}; SRC=${2:?base source}; OUT=${3:?journal json}; NAME=${4:-tb-allerretour}; PORT=${5:-8460}
T=$(mktemp -d /tmp/tb-allerretour.XXXXXX); mkdir -p "$T/data"; chmod 777 "$T/data"
cp "$SRC" "$T/data/timebilling.db"; chmod 666 "$T/data/timebilling.db"
SHA0=$(sha256sum "$SRC" | cut -d' ' -f1)
head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' > "$T/pw.txt"
docker run -d --name "$NAME" -p 127.0.0.1:$PORT:8000 -v "$T/data":/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=0 \
  -e INVOICE_CHECK_WORDS= -e DB_PATH=/data/timebilling.db -e ENV_LABEL=RECETTE -e APP_PASSWORD="$(cat "$T/pw.txt")" "$IMG" >/dev/null || { rm -rf "$T"; exit 2; }
for i in $(seq 60); do curl -fs http://127.0.0.1:$PORT/health >/dev/null 2>&1 && break; sleep 1; done
echo "image $(docker image inspect "$IMG" --format '{{.Id}}') ; version $(curl -fs http://127.0.0.1:$PORT/health) ; source $SRC ($SHA0)"
# copie cohérente de la base MIGRÉE par l'image avant les envois (API de sauvegarde sqlite), pour comparer ensuite toutes les tables métier
snap() { python3 -I -c 'import sqlite3,sys; s=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' "$T/data/timebilling.db" "$1"; }
snap "$T/avant.db"
python3 -I $W/outils/aller_retour_formulaires.py http://127.0.0.1:$PORT "$T/pw.txt" "$T/data/timebilling.db" "$OUT"; rc=$?
snap "$T/apres.db"
echo "empreinte_metier (16 tables métier de 90-rollback, toutes colonnes, horodatages compris) :"
python3 -I $W/outils/empreinte_metier.py comparer "$T/avant.db" "$T/apres.db" || rc=1
docker rm -f "$NAME" >/dev/null; rm -rf "$T"
[ "$(sha256sum "$SRC" | cut -d' ' -f1)" = "$SHA0" ] && echo "base source inchangée" || { echo "ÉCHEC : base source modifiée"; rc=3; }
exit $rc
