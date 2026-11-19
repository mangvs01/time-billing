#!/bin/bash
# Scénarios du retour arrière 90 pour la bascule PRODUCTION (V9.0 → rc courante), sur un bac à sable V9.0 préparé par setup-sandbox-copie.sh.
# Pour chaque scénario : 20 → 30 → rotate-secrets → 40 (code du dépôt), une écriture dans la base déployée (bac à sable uniquement), puis 90 :
# accepté (aucune donnée nouvelle) ou refusé avec le motif attendu ; après un refus, retour forcé (ABANDONNER_CORRECTIONS=OUI) pour repartir de V9.0.
# Aucune lecture de /opt. Usage : test-90-f.sh <bac à sable>
set -uo pipefail
SC=$1; MB=$(cd "$(dirname "$0")" && pwd); S=$MB/$SC; P=$MB/../procedure; CONF=$S/sandbox.conf; . $CONF
NPW=$S/.new-password; ( umask 077; openssl rand -base64 18 | tr -d '\n' > $NPW )
OK=0; KO=0; ok() { echo "OK    $*"; OK=$((OK+1)); }; ko() { echo "ÉCHEC $*"; KO=$((KO+1)); }
v90() { curl -s $URL/health | grep -q '"9.0-rc1"'; }
deploy() { bash $P/20-backup.sh $CONF >/dev/null && bash $P/30-rehearse.sh $CONF >/dev/null && NEW_PASSWORD_FILE=$NPW COOKIE_SECURE=0 TRUST_PROXY=0 bash $P/rotate-secrets.sh $CONF >/dev/null \
  && bash $P/40-deploy.sh $CONF >/dev/null 2>&1; }
ecrire() { docker exec -i $CONTAINER python - <<<"import sqlite3; c=sqlite3.connect('/data/timebilling.db'); c.executescript('''$1'''); c.commit()"; }
scenario() { # $1 nom, $2 SQL (vide = aucune écriture), $3 motif attendu dans le refus (vide = retour accepté), $4 conf (défaut : $CONF)
  local conf=${4:-$CONF} log; echo; echo "=== $1"
  v90 || { ko "$1 : le bac à sable n'est pas en V9.0 au départ"; return; }
  deploy || { ko "$1 : déploiement"; return; }
  [ -n "$2" ] && { ecrire "$2" || { ko "$1 : écriture"; ABANDONNER_CORRECTIONS=OUI bash $P/90-rollback.sh $conf >/dev/null 2>&1; return; }; }
  log=$(bash $P/90-rollback.sh $conf 2>&1); local rc=$?; grep -E "ARRÊT|recalculées|NB :|impossible" <<<"$log" | sed 's/^/      /'
  if [ -z "$3" ]; then
    [ $rc = 0 ] && v90 && grep -q "SHA-256 identique" <<<"$log" && ok "$1 : retour accepté, V9.0 et base = sauvegarde" || ko "$1 : retour attendu accepté (rc=$rc)"
  else
    [ $rc != 0 ] && grep -qF "$3" <<<"$log" && curl -s $URL/health | grep -q 9.2- && ok "$1 : retour refusé (« $3 »), service rc toujours en marche" || ko "$1 : refus attendu « $3 » (rc=$rc)"
    sleep 1; ABANDONNER_CORRECTIONS=OUI bash $P/90-rollback.sh $conf >/dev/null 2>&1 && v90 && ok "$1 : retour forcé après export (ABANDONNER_CORRECTIONS=OUI) → V9.0" || ko "$1 : retour forcé"
  fi; }

v90 || { (cd $ROOT && docker compose -p $PROJECT up -d --build --quiet-pull >/dev/null 2>&1); for _ in $(seq 1 60); do v90 && break; sleep 1; done; }   # bac à sable nettoyé par dry-run-f.sh
scenario "S0 juste après le déploiement (connexions seulement)" "" ""
scenario "S1 colonne ajoutée, mandat existant (adresse de facturation)" "UPDATE projects SET billing_address='Rue X 1' WHERE id=1;" "projects : 1 ligne(s) modifiée(s) (colonnes ajoutées par la migration)"
scenario "S2 colonne ajoutée, brouillon existant (date de facture)" "UPDATE invoices SET invoice_date='2026-10-07' WHERE id=3;" "invoices : 1 ligne(s) modifiée(s) (colonnes ajoutées par la migration)"
scenario "S3 colonne ajoutée, note de crédit existante (description)" "UPDATE credit_notes SET description='motif' WHERE id=1;" "credit_notes : 1 ligne(s) modifiée(s) (colonnes ajoutées par la migration)"
scenario "S4 table ajoutée sans id (paramètre émetteur)" "INSERT INTO settings(key,value) VALUES('issuer_name','Test');" "settings : 1 ligne(s) ajoutée(s) ou modifiée(s) (par rapport à la sauvegarde migrée)"
scenario "S5 table ajoutée avec id (facture historique)" "INSERT INTO historical_invoices(project_id,source_file,source_sheet,source_cell,invoice_date,amount_ht,basis,created_at) VALUES(1,'test.xlsx','SUIVI 2026','B2','2026-01-31',100,'amount_only','2026-10-07T13:20:00');" "historical_invoices : 1 ligne(s) ajoutée(s)"
scenario "S6 table ajoutée avec id (historique des corrections)" "INSERT INTO entry_changes(entry_id,action,before_json,after_json,changed_at,reason,actor) VALUES(1,'update','{}','{}','2026-10-07T13:20:00','test','admin');" "entry_changes : 1 ligne(s) ajoutée(s)"
scenario "S7 colonne d'origine (description d'une saisie)" "UPDATE entries SET description='corrigée' WHERE id=(SELECT MIN(id) FROM entries);" "entries : 1 ligne(s) modifiée(s)"
# S8 : VERSION du dépôt changée après le déploiement (copie de app/ avec une autre VERSION) — le retour vise le déploiement réellement fait
ALT=$S/app-version-changee; rm -rf $ALT; cp -r $SOURCE_APP $ALT; sed -i 's/^VERSION="9.2-[a-z0-9]*"/VERSION="9.2-rc99"/' $ALT/app.py
sed "s#^SOURCE_APP=.*#SOURCE_APP=$ALT#" $CONF > $S/conf-version-changee
scenario "S8 VERSION du dépôt changée depuis le déploiement" "" "" $S/conf-version-changee
# S9 : copie migrée impossible (conteneur introuvable → image inconnue) : comportement d'avant, refus prudent
sed "s#^CONTAINER=.*#CONTAINER=tbmb-inexistant#" $CONF > $S/conf-sans-image
scenario "S9 copie migrée impossible (refus prudent)" "" "copie migrée indisponible" $S/conf-sans-image
# S10 : 20 relancé pour une autre version (rc99) SANS 40 après le déploiement : le retour vise toujours la sauvegarde du déploiement réel
echo; echo "=== S10 20 relancé pour une autre version sans 40"
if v90 && deploy; then D=$(cat $BACKUP_BASE/deployed); bash $P/20-backup.sh $S/conf-version-changee >/dev/null 2>&1; (cd $ROOT && docker compose -p $PROJECT start >/dev/null 2>&1)
  log=$(bash $P/90-rollback.sh $CONF 2>&1); rc=$?; grep -E "ARRÊT|retour arrière effectué" <<<"$log" | sed 's/^/      /'
  [ $rc = 0 ] && v90 && grep -q "base = sauvegarde $D (SHA-256 identique)" <<<"$log" && ok "S10 : retour vers la sauvegarde du déploiement ($D), pas celle du 20 relancé ($(cat $BACKUP_BASE/last-backup)) → V9.0" || ko "S10 (rc=$rc)"
else ko "S10 : départ/déploiement"; fi
rm -rf $ALT $S/conf-version-changee $S/conf-sans-image $NPW
echo; echo "BILAN : $OK OK, $KO échec(s)"; [ $KO = 0 ]
