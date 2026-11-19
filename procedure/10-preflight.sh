#!/bin/bash
# 1. Préparation, sans interruption : santé, empreinte, fichiers WAL, place disque, sources présentes.
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
log "cible $ROOT (projet $PROJECT, conteneur $CONTAINER) — santé : $(health)"
[ -d "$SOURCE_APP" ] || die "code source absent : $SOURCE_APP"
docker image inspect "$RC_IMAGE" >/dev/null 2>&1 || { log "construction de l'image de répétition $RC_IMAGE"; docker build -q -t "$RC_IMAGE" "$(dirname "$SOURCE_APP")" >/dev/null || die "construction impossible"; }
L=$(ls "$ROOT/data"); grep -qE 'timebilling.db-(wal|shm|journal)$' <<<"$L" && die "fichiers WAL/SHM/journal présents : à inclure explicitement dans la sauvegarde"
[ "$(df --output=avail -k "$BACKUP_BASE" 2>/dev/null | tail -1 || df --output=avail -k / | tail -1)" -gt 512000 ] || die "moins de 500 Mo libres"
[ -f "$ROOT/.env" ] && [ "$(stat -c %a "$ROOT/.env")" != 600 ] && die ".env existant mais pas en mode 600"
log "Dockerfile identique : $(diff -q "$ROOT/Dockerfile" "$(dirname "$SOURCE_APP")/Dockerfile" >/dev/null && echo oui || echo NON)"
log "requirements identiques : $(diff -q "$ROOT/requirements.txt" "$SOURCE_REQ" >/dev/null && echo oui || echo 'non (copiés au déploiement)')"
log "propriétaire du dossier de données : $(stat -c %u "$ROOT/data") (le service RC11 s'exécute en uid 10001 : changé au déploiement)"
# 2026-10-08 : 40 exige $ROOT/.env.<rc> (600) ; absent, 40 s'arrête alors que 20 a déjà arrêté le service (staging rc23, 06:11 UTC) : signalé ici
if [ -f "$ROOT/.env.${RC_TAG}" ]; then log "secrets de $RC_TAG : .env.${RC_TAG} présent (mode $(stat -c %a "$ROOT/.env.${RC_TAG}"))"
else log "ATTENTION : .env.${RC_TAG} absent — 40 s'arrêtera ; le créer AVANT 20 (staging : cp -p $ROOT/.env $ROOT/.env.${RC_TAG} ; production : rotate-secrets.sh / mot-de-passe-production.sh entre 30 et 40)"; fi
log "préparation conforme"
