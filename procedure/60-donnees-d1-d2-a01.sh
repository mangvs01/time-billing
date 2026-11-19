#!/bin/bash
# 7. Données du Decision Center sur le STAGING uniquement (2026-10-07) :
#    - D1 (billing-d1-load-go = GO_STAGING) + D2 (billing-d2 = IMPORT_4550) : 24 factures historiques chargées « à valider » (outils/charger_factures_historiques.py) ;
#    - A-01 (billing-a01-l01 … l15 = OUI) : note de la colonne I reportée dans la description de 15 saisies (outils/reporter_notes_a01.py).
#    Service arrêté pendant l'écriture ; sauvegarde vérifiée ; les deux outils sont d'abord simulés sur la copie arrêtée ; au moindre échec
#    de l'application, la base sauvegardée est remise en place avant le redémarrage. Code utilisé = image DÉPLOYÉE ($IMAGE:latest).
# Usage : procedure/60-donnees-d1-d2-a01.sh procedure/staging.conf
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
case "$ROOT" in /opt/time-billing-v9) die "cible = PRODUCTION : refusé";; */time-billing-v9-staging) ;; *) die "cible $ROOT : ce script ne vise que le staging (ou sa répétition)";; esac
REPO=$(cd "$PROC_DIR/.." && pwd); CLASSEUR=${CLASSEUR:-/root/Time sheet CP.xlsx}
WB_SHA=c93c610cdffe66d150fbb05d64513054d297f6170158effef99eb461eddac438
[ "$(sha256sum < "$CLASSEUR" | cut -d' ' -f1)" = "$WB_SHA" ] || die "classeur inattendu ($CLASSEUR)"
curl -sf -m 5 "$URL/health" >/dev/null || die "staging non disponible avant l'opération : rien n'est fait"
DB="$ROOT/data/timebilling.db"; OWNER=$(stat -c %u:%g "$DB"); MODE=$(stat -c %a "$DB")
TS=$(date -u +%Y%m%dT%H%M%SZ); B="$BACKUP_BASE/pre-donnees-d1d2a01-$TS"; J="$REPO/journaux/donnees-staging-$TS"
mkdir -p "$B" "$J"; chmod 700 "$B"
W=$(mktemp -d /tmp/tb-donnees-XXXX); cp "$CLASSEUR" "$W/classeur.xlsx"; mkdir -p "$W/simu" "$W/out"; chmod -R 777 "$W"
tool() { local base=$1 out=$2 user=$3; shift 3
  docker run --rm --network none --user "$user" -v "$REPO/outils:/app/outils:ro" -v "$W/classeur.xlsx:/src/classeur.xlsx:ro" -v "$base:/data" -v "$out:/out" \
    -w /app -e PYTHONPATH=/app "$IMAGE:latest" python -W ignore "$@" --classeur /src/classeur.xlsx --base /data/timebilling.db --sortie /out; }

log "arrêt du staging (écritures D1/D2/A-01)"; compose stop
# quoi qu'il arrive, le staging est relancé en sortie et le dossier temporaire supprimé ; 2026-10-07 (relecture adverse) : interruption (Ctrl-C,
# coupure SSH) pendant l'application = base remise à l'état sauvegardé avant le redémarrage (sinon état mixte : chargeur écrit, A-01 non)
APPLYING=0
trap '[ "$APPLYING" = 1 ] && restore; compose start >/dev/null 2>&1 || true; rm -rf "$W"' EXIT
cp -p "$DB" "$B/timebilling.db"; (cd "$B" && sha256sum timebilling.db > SHA256SUMS); chmod 600 "$B"/*
[ "$(sha256sum < "$DB")" = "$(sha256sum < "$B/timebilling.db")" ] || { compose start; die "copie de la base différente de l'original : rien n'est fait"; }
log "sauvegarde $B (sha $(cut -c1-12 "$B/SHA256SUMS"))"

# simulation sur une copie de la base arrêtée (la copie est jetée) : arrêt sans écriture si l'un des outils refuse
mkdir -p "$W/copie"; cp "$B/timebilling.db" "$W/copie/timebilling.db"; chmod -R 777 "$W/copie"
if ! tool "$W/copie" "$W/simu" 0:0 outils/charger_factures_historiques.py > "$J/simulation-chargeur.txt" 2>&1 \
   || ! tool "$W/copie" "$W/simu" 0:0 outils/reporter_notes_a01.py > "$J/simulation-a01.txt" 2>&1; then
  compose start; wait_health || true; die "simulation refusée (voir $J) : rien n'est écrit, staging redémarré"
fi
log "simulations conformes"

restore() { log "ÉCHEC : remise en place de la base sauvegardée"; cp "$B/timebilling.db" "$DB"; chown "$OWNER" "$DB"; chmod "$MODE" "$DB"; rm -f "$DB-wal" "$DB-shm" "$DB-journal"; APPLYING=0
  [ "$(sha256sum < "$DB")" = "$(sha256sum < "$B/timebilling.db")" ] && log "base restaurée (identique à la sauvegarde)" \
    || { trap - EXIT; die "base restaurée DIFFÉRENTE de la sauvegarde : staging laissé ARRÊTÉ ; remettre $B/timebilling.db à la main"; }; }
APPLYING=1
if tool "$ROOT/data" "$W/out" "$OWNER" outils/charger_factures_historiques.py --appliquer --confirmer CHARGER-24-A-VALIDER > "$J/application-chargeur.txt" 2>&1 \
   && tool "$ROOT/data" "$W/out" "$OWNER" outils/reporter_notes_a01.py --appliquer --confirmer REPORTER-15-NOTES-A01 > "$J/application-a01.txt" 2>&1; then
  APPLYING=0; log "application conforme"; OK=1
else restore; OK=0; fi
cp "$W"/out/* "$J/" 2>/dev/null || true
compose start; wait_health || die "staging ne répond pas après redémarrage (voir docker logs $CONTAINER)"
log "staging redémarré : $(health | head -c 200)"
rm -rf "$W"
[ "$OK" = 1 ] || die "application refusée (voir $J) : base remise à l'état sauvegardé, staging redémarré"
log "TERMINÉ : $(tail -1 "$J/application-chargeur.txt")"
log "A-01 : $(python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(len(r["corrigees"]), "description(s) corrigée(s),", len(r["deja_faites"]), "déjà faite(s) ; chiffres inchangés :", r["chiffres_inchanges"])' "$J/a01-resume.json"). Journal : $J"
