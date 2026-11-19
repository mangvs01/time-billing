#!/bin/bash
# 4. Déploiement RC10 : code, requirements, Dockerfile, compose RC10 (écoute locale, secrets dans .env 600), construction, démarrage.
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
# rc25 (TB-06) : A = contrôles, rien n'est modifié ; un échec relance l'ancienne version (arrêtée par 20). B = installation ; un échec lance
# 90-rollback.sh, qui refuse lui-même d'écarter des données écrites depuis la sauvegarde (le service reste alors arrêté, message explicite).
on_fail restart_old
last_backup; same_tag; same_app "$B"
(cd "$B" && sha256sum -c --quiet SHA256SUMS) || die "sauvegarde $B altérée"
[ -f "$B/rehearsal-GO" ] || die "aucun marqueur GO de 30-rehearse pour la sauvegarde $TS : exécuter 30-rehearse.sh (GO exigé)"
[ "$(cat "$B/rehearsal-GO")" = "$(go_marker)" ] || die "marqueur GO de 30 périmé (sauvegarde, base, code ou image de répétition changés depuis la répétition) : relancer 30-rehearse.sh"
[ "$(docker inspect "$CONTAINER" --format '{{.State.Running}}' 2>/dev/null || echo false)" = false ] || die "le service $CONTAINER est en marche : des écritures postérieures à la sauvegarde $TS seraient perdues au retour arrière ; relancer 20 puis 30"
[ "$(sha256sum < "$ROOT/data/timebilling.db")" = "$(sha256sum < "$B/timebilling.db")" ] || die "la base vivante a changé depuis la sauvegarde $TS : relancer 20 puis 30"
rollback_image                                                          # image de retour disponible AVANT toute modification
[ -f "$ROOT/.env.${RC_TAG}" ] || die ".env.${RC_TAG} absent : exécuter rotate-secrets.sh (nouveau mot de passe + secret de session)"
[ "$(stat -c %a "$ROOT/.env.${RC_TAG}")" = 600 ] || die ".env.${RC_TAG} doit être en mode 600"
# rc25 (TB-06) : port publié = port de URL (seule la ligne TB_PORT est lue ; sinon défaut du gabarit compose)
PORT_ENV=$(sed -nE "s/^TB_PORT=['\"]?([0-9]+)['\"]?$/\1/p" "$ROOT/.env.${RC_TAG}" | tail -n 1)
PORT_ENV=${PORT_ENV:-$(sed -nE 's/.*\$\{TB_PORT:-([0-9]+)\}.*/\1/p' "$COMPOSE_TEMPLATE" | head -n 1)}
[ "$PORT_ENV" = "$(url_port)" ] || die "port publié ${PORT_ENV:-inconnu} (.env.${RC_TAG} / gabarit compose) ≠ port de URL $(url_port) : corriger TB_PORT dans .env.${RC_TAG}"
on_fail 'log "ÉCHEC pendant l'"'"'installation : retour arrière automatique (90-rollback.sh)"; env -u ABANDONNER_CORRECTIONS bash "$PROC_DIR/90-rollback.sh" "$CONF" || log "ATTENTION : retour arrière automatique refusé ou en échec (voir ci-dessus) ; service possiblement arrêté"'
echo "$TS" > "$BACKUP_BASE/deployed"; chmod 600 "$BACKUP_BASE/deployed"   # cible de 90 : la sauvegarde de CE déploiement (relecture adverse)
rsync -a --delete --exclude '__pycache__' --exclude '*.before-*' "$SOURCE_APP/" "$ROOT/app/"
cp "$SOURCE_REQ" "$ROOT/requirements.txt"; cp "$(dirname "$SOURCE_REQ")/requirements.lock" "$ROOT/requirements.lock"
install -m 644 "$(dirname "$SOURCE_APP")/.dockerignore" "$ROOT/.dockerignore"
install -m 644 "$(dirname "$SOURCE_APP")/Dockerfile" "$ROOT/Dockerfile"            # RC10 : serveur gthread (le CMD est dans le Dockerfile)
install -m 644 "$COMPOSE_TEMPLATE" "$ROOT/docker-compose.yml"       # plus aucun secret dans ce fichier
mv "$ROOT/.env.${RC_TAG}" "$ROOT/.env"
chown -R 10001:10001 "$ROOT/data"; chmod 700 "$ROOT/data"; chmod 600 "$ROOT/data/timebilling.db"   # RC11 : service non privilégié
compose config --quiet || die "compose invalide (variable manquante dans .env ?)"
compose build --quiet
compose up -d
wait_health || die "le service ne répond pas"
on_fail ""
log "déployé — santé : $(health)"
