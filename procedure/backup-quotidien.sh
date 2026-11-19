#!/bin/bash
# Sauvegarde quotidienne À CHAUD (sans arrêt) : copie cohérente par l'API de sauvegarde SQLite exécutée DANS le conteneur,
# contrôle d'intégrité, empreinte SHA-256, rétention (30 quotidiennes + 12 mensuelles). Aucun secret manipulé.
# Ce que le script écrit réellement (il n'est donc PAS « en lecture seule ») :
#   - dans le volume de PRODUCTION : un fichier temporaire /data/.backup-auto.db, supprimé à la sortie, y compris en cas d'échec (trap) ;
#   - dans BACKUP_BASE : la nouvelle sauvegarde, SHA256SUMS, et la suppression des sauvegardes au-delà de la rétention.
# Il exécute du code (python) dans le conteneur de production : seule la version approuvée (empreintes, voir tb-common.sh) peut tourner sans CONFIRM_PROD.
# Usage : backup-quotidien.sh <fichier de configuration>   (cron : procedure/cron-sauvegarde.example, non installé)
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
umask 077
D="$BACKUP_BASE/quotidiennes"; M="$BACKUP_BASE/mensuelles"; mkdir -p "$D" "$M"; chmod 700 "$BACKUP_BASE" "$D" "$M"
TS=$(date -u +%Y%m%dT%H%M%SZ); F="$D/timebilling-$TS.db"
OK=0
# nettoyage à toute sortie : fichier temporaire du volume de production, et copie incomplète ou non vérifiée (jamais une sauvegarde déjà vérifiée : OK=1 plus bas)
cleanup() { docker exec "$CONTAINER" rm -f /data/.backup-auto.db >/dev/null 2>&1 || true; [ "$OK" = 1 ] || rm -f -- "$F"; }
trap cleanup EXIT
docker exec -i "$CONTAINER" python - <<'PY' || die "sauvegarde en ligne impossible"
import sqlite3, os
src = sqlite3.connect('/data/timebilling.db', timeout=30); dst = sqlite3.connect('/data/.backup-auto.db')
src.backup(dst); dst.close(); src.close()
chk = sqlite3.connect('file:/data/.backup-auto.db?mode=ro', uri=True)
assert chk.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'integrité'
assert chk.execute('PRAGMA foreign_key_check').fetchall() == [], 'clés étrangères'
PY
docker cp "$CONTAINER:/data/.backup-auto.db" "$F" >/dev/null; docker exec "$CONTAINER" rm -f /data/.backup-auto.db
chmod 600 "$F"; ( cd "$D" && sha256sum "$(basename "$F")" >> SHA256SUMS && chmod 600 SHA256SUMS )
[ "$(sha256sum < "$F" | cut -c1-64)" = "$(tail -1 "$D/SHA256SUMS" | cut -c1-64)" ] || die "empreinte incohérente"
OK=1     # la sauvegarde du jour est vérifiée : la suite (rétention, contrôle de l'ensemble) ne doit jamais l'effacer
log "sauvegarde $F ($(stat -c %s "$F") octets) — intégrité ok — sha256 $(sha256sum < "$F" | cut -c1-16)…"
[ "$(date -u +%d)" = 01 ] && cp -p "$F" "$M/timebilling-$(date -u +%Y%m).db" && log "copie mensuelle conservée"
# rétention : 30 dernières quotidiennes, 12 dernières mensuelles ; SHA256SUMS : lignes d'origine conservées pour les fichiers restants
# (2026-10-07 : il était recalculé chaque jour, ce qui « validait » une sauvegarde altérée après coup)
ls -1t "$D"/timebilling-*.db 2>/dev/null | tail -n +31 | xargs -r rm -f || true
ls -1t "$M"/timebilling-*.db 2>/dev/null | tail -n +13 | xargs -r rm -f || true
( cd "$D" && while read -r h f; do [ -e "$f" ] && echo "$h  $f"; done < SHA256SUMS > SHA256SUMS.new; mv SHA256SUMS.new SHA256SUMS; chmod 600 SHA256SUMS )
( cd "$D" && sha256sum -c --quiet SHA256SUMS ) || die "une sauvegarde quotidienne ne correspond plus à son empreinte d'origine"
