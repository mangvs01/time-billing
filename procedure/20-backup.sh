#!/bin/bash
# 2. Sauvegarde : arrêt (plus aucune écriture), image de retour, copie de la base arrêtée, arborescence, empreintes.
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
TS=$(date -u +%Y%m%dT%H%M%SZ); B="$BACKUP_BASE/pre-${RC_TAG}-$TS"; mkdir -p "$B"; chmod 700 "$BACKUP_BASE" "$B"
[[ "$(health)" == *"\"$VERSION\""* ]] && die "$VERSION est déjà en marche : une sauvegarde maintenant remplacerait celle d'avant déploiement (retour arrière vers $VERSION)"
# rc25 (TB-06) : image réellement exécutée par le conteneur (pas « latest », qu'une construction non déployée aurait pu remplacer)
RUN_IMG=$(docker inspect "$CONTAINER" --format '{{.Image}}' 2>/dev/null || true)
compose stop
on_fail restart_old     # rc25 (TB-06) : un échec de la sauvegarde ne laisse plus le service arrêté (rien n'a été modifié ; aucun déploiement ne suivra)
# 2026-10-07 (relecture adverse) : base en journal « rollback » ; un journal restant après l'arrêt = transaction interrompue : la copie serait incohérente
[ -e "$ROOT/data/timebilling.db-journal" ] && { die "journal de transaction présent après l'arrêt (timebilling.db-journal) : rien n'est sauvegardé, service relancé ; analyser avant de recommencer"; }
docker tag "${RUN_IMG:-$IMAGE:latest}" "$IMAGE:pre-${RC_TAG}-$TS"
# rc25 (TB-06) : copie durable de l'image de retour dans la sauvegarde ; un « docker image prune -a » ou « system prune -a » supprime l'étiquette
# pre-… (image non utilisée par un conteneur) : 90 la recharge depuis cette copie (rollback_image)
docker save "$IMAGE:pre-${RC_TAG}-$TS" | gzip -1 > "$B/image.tar.gz"
cp -p "$ROOT/data/timebilling.db" "$B/timebilling.db"
tar -C "$(dirname "$ROOT")" -czf "$B/tree.tar.gz" "$(basename "$ROOT")"      # code, compose, Dockerfile, data (+ .env s'il existe)
chmod 600 "$B"/*
app_digest > "$B/source-app.sha256"
docker image inspect "$IMAGE:pre-${RC_TAG}-$TS" --format '{{.Id}}' > "$B/image-id.txt"
R=$(mktemp -d); cleanup 'rm -rf "$R"'; cp "$B/timebilling.db" "$R/"; py_on_copy "$R" "$RC_IMAGE" "$COUNT_PY" > "$B/counts-before.json"
(cd "$B" && sha256sum timebilling.db tree.tar.gz image-id.txt image.tar.gz counts-before.json source-app.sha256 > SHA256SUMS && sha256sum -c --quiet SHA256SUMS)
[ "$(sha256sum < "$ROOT/data/timebilling.db")" = "$(sha256sum < "$B/timebilling.db")" ] || die "copie de la base différente de l'original"
echo "$TS" > "$STATE"; chmod 600 "$STATE"
on_fail ""              # sauvegarde conforme : le service reste arrêté jusqu'à 40 (ou relance manuelle de l'ancienne version)
log "sauvegarde $B conforme (service arrêté ; relancer l'ancienne version : docker compose -p $PROJECT start)"
