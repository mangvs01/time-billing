#!/bin/bash
# Migration à blanc d'un bac à sable (A = copie exacte de la base de prod, B = copie + données fictives V9.0).
# Variante F (2026-10-07) : identique à dry-run.sh sauf le contrôle « code = code V9.0 », fait contre la copie $S/ref-v90 (aucune lecture de /opt).
# Joue les scripts de la procédure RC11 tels quels, avec la configuration du bac à sable. Aucun secret affiché.
set -uo pipefail
SC=$1; MB=$(cd "$(dirname "$0")" && pwd); S=$MB/$SC; P=$MB/../procedure; CONF=$S/sandbox.conf; . $CONF
TAG=$(sed -n 's/^VERSION="9.2-\(.*\)"/\1/p' "$SOURCE_APP/app.py")   # 2026-10-07 : étiquette du code DÉPLOYÉ (copie de publication possible), pas de l'arbre
J=$S/pdf; mkdir -p $J; chmod 700 $J
step() { echo; echo "=== $*"; }
login_pdfs() { # $1 = fichier mot de passe, $2 = suffixe ; télécharge les PDF des factures 1..3 (si présentes)
  local jar; jar=$(mktemp); curl -s -c $jar -b $jar -o /dev/null --data-urlencode username=admin --data-urlencode "password@$1" "$URL/login"
  for i in 1 2 3; do code=$(curl -s -b $jar -o $J/facture-$i-$2.pdf -w %{http_code} "$URL/invoice/$i.pdf"); [ "$code" = 200 ] && echo "PDF facture $i ($2) : 200, sha $(sha256sum < $J/facture-$i-$2.pdf | cut -c1-12)" || rm -f $J/facture-$i-$2.pdf; done; rm -f $jar; }
pw_v90() { local f; f=$(mktemp); chmod 600 $f; sed -n 's/^SANDBOX_PASSWORD=//p' $S/opt/time-billing-v9/.env.v90 | tr -d '\n' > $f; echo $f; }

step "0. version d'origine (V9.0, image construite depuis l'arborescence de prod copiée)"
(cd $ROOT && docker compose -p $PROJECT up -d --build --quiet-pull 2>&1 | tail -1)
for _ in $(seq 1 60); do curl -sf $URL/health >/dev/null && break; sleep 1; done; echo "santé V9.0 : $(curl -s $URL/health)"
F=$(pw_v90); login_pdfs $F v90; rm -f $F

step "1. 10-preflight";   bash $P/10-preflight.sh $CONF || exit 1
step "2. 20-backup";      bash $P/20-backup.sh $CONF || exit 1
step "3. 30-rehearse";    bash $P/30-rehearse.sh $CONF || exit 1
step "4. rotate-secrets (mot de passe de test aléatoire, non interactif)"
NPW=$S/.new-password; ( umask 077; openssl rand -base64 18 | tr -d '\n' > $NPW )
NEW_PASSWORD_FILE=$NPW COOKIE_SECURE=0 TRUST_PROXY=0 bash $P/rotate-secrets.sh $CONF || exit 1
grep -q "APP_PASSWORD_HASH='scrypt:" $ROOT/.env.$TAG && ! grep -qF "$(cat $NPW)" $ROOT/.env.$TAG && echo "OK .env.$TAG : hachage seulement, mot de passe en clair absent, mode $(stat -c %a $ROOT/.env.$TAG)"
step "5. 40-deploy";      bash $P/40-deploy.sh $CONF || exit 1
step "6. 50-verify (dont redémarrage)"; bash $P/50-verify.sh $CONF || exit 1
step "7. contrôles complémentaires $TAG"
! grep -qE '^ *[A-Z_]*(PASSWORD|SECRET_KEY)[A-Z_]*: *[^$ ]' $ROOT/docker-compose.yml && echo "OK compose : secrets uniquement par variables \${…}, aucune valeur"
[ "$(docker exec $CONTAINER sh -c 'printf %s "$APP_PASSWORD_HASH"' | sha256sum)" = "$(sed -n "s/^APP_PASSWORD_HASH='\(.*\)'$/\1/p" $ROOT/.env | tr -d '\n' | sha256sum)" ] && echo "OK hachage transmis intact au conteneur (comparaison d'empreintes, caractères \$ préservés)"
echo "ancien mot de passe refusé : $(F=$(pw_v90); curl -s -o /dev/null -w %{http_code} --data-urlencode username=admin --data-urlencode "password@$F" $URL/login; rm -f $F) (200 = formulaire réaffiché)"
login_pdfs $NPW $TAG
for i in 1 2 3; do [ -f $J/facture-$i-v90.pdf ] || continue
  if [ -f $J/facture-$i-$TAG.pdf ]; then
    diff -q <(pdftotext -layout $J/facture-$i-v90.pdf -) <(pdftotext -layout $J/facture-$i-$TAG.pdf -) >/dev/null && echo "OK facture $i : texte du PDF servi après migration = texte du PDF V9.0" || echo "ÉCART facture $i (texte)"; fi; done
docker exec -i $CONTAINER python - <<'PY'
import sqlite3,json; c=sqlite3.connect('/data/timebilling.db'); c.row_factory=sqlite3.Row
for r in c.execute("SELECT id,number,status,issued_at,invoice_date FROM invoices ORDER BY id"): print('facture', dict(r))
for r in c.execute("SELECT invoice_id,number,frozen_by,pdf_sha256 FROM invoice_snapshots ORDER BY invoice_id"): print('copie figée', r['invoice_id'], r['number'], r['frozen_by'], r['pdf_sha256'][:12])
for r in c.execute("SELECT id,reference,status,treatment,amount FROM credit_notes"): print('note (héritée V9.0)', dict(r))
print('audit migration', c.execute("SELECT detail FROM audit WHERE event='legacy_invoices_frozen'").fetchall())
PY
for i in 1 2; do [ -f $J/facture-$i-$TAG.pdf ] && [ "$(docker exec $CONTAINER python -c "import sqlite3,hashlib;print(hashlib.sha256(sqlite3.connect('/data/timebilling.db').execute('SELECT pdf FROM invoice_snapshots WHERE invoice_id=$i').fetchone()[0]).hexdigest())")" = "$(sha256sum < $J/facture-$i-$TAG.pdf | cut -d' ' -f1)" ] && echo "OK facture $i : PDF servi = copie figée (octet pour octet)"; done
step "8. 90-rollback";    bash $P/90-rollback.sh $CONF || exit 1
step "9. contrôle du retour arrière"
TS=$(cat $BACKUP_BASE/last-backup); echo "santé : $(curl -s $URL/health)"
[ "$(sha256sum < $ROOT/data/timebilling.db)" = "$(sha256sum < $BACKUP_BASE/pre-$TAG-$TS/timebilling.db)" ] && echo "OK base = sauvegarde (SHA-256 identique)"
diff -rq --exclude __pycache__ $ROOT/app $S/ref-v90/time-billing-v9/app >/dev/null && echo "OK code = code V9.0 de production (identique)"
F=$(pw_v90); login_pdfs $F retour; rm -f $F
for i in 1 2 3; do [ -f $J/facture-$i-v90.pdf ] && { diff -q <(pdftotext -layout $J/facture-$i-v90.pdf -) <(pdftotext -layout $J/facture-$i-retour.pdf -) >/dev/null && echo "OK facture $i : identique à l'origine après retour arrière" || echo "ÉCART facture $i après retour"; }; done
docker restart $CONTAINER >/dev/null; for _ in $(seq 1 60); do curl -sf $URL/health >/dev/null && break; sleep 1; done; echo "redémarrage V9.0 après retour : $(curl -s $URL/health)"
step "10. nettoyage du bac à sable"
(cd $ROOT && docker compose -p $PROJECT down 2>&1 | tail -1); docker image ls --format '{{.Repository}}:{{.Tag}}' | grep "^$IMAGE" | xargs -r docker rmi >/dev/null && echo "images du bac à sable supprimées"
rm -f $NPW; echo "FIN $SC"
