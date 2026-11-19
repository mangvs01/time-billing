#!/bin/bash
# Rotation : nouveau mot de passe (saisi sans écho, jamais stocké en clair : seul son hachage scrypt est écrit) et
# nouveau secret de session aléatoire (64 caractères hexadécimaux, distinct du mot de passe). Écrit $ROOT/.env.${RC_TAG} (600).
# Mode non interactif : NEW_PASSWORD_FILE=<fichier 600> (bacs à sable ; production : par mot-de-passe-production.sh, G5).
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
umask 077
# rc25 (TB-06) : port publié = port de URL de la configuration (staging 8092, production 8091) ; avant, 8091 par défaut partout (staging compris)
PORT=$(url_port); [ -z "${TB_PORT:-}" ] || [ "$TB_PORT" = "$PORT" ] || die "TB_PORT=$TB_PORT ≠ port de URL ($PORT) dans $CONF"
if [ -n "${NEW_PASSWORD_FILE:-}" ]; then PW=$(cat "$NEW_PASSWORD_FILE"); else
  read -rsp "Nouveau mot de passe (6 caractères minimum) : " PW; echo; read -rsp "Confirmer : " PW2; echo
  [ "$PW" = "$PW2" ] || die "les deux saisies diffèrent"; unset PW2; fi
# 2026-10-14 : minimum abaissé de 16 à 6 caractères (décision du propriétaire). La connexion reste limitée
# à 5 échecs par IP sur 15 minutes (app/security.py, MAX_FAILURES/WINDOW_MIN).
[ ${#PW} -ge 6 ] || die "mot de passe trop court (6 caractères minimum)"
HASH=$(printf '%s' "$PW" | docker run -i --rm --network none "$RC_IMAGE" python -c "import sys;from werkzeug.security import generate_password_hash as g;print(g(sys.stdin.read()))"); unset PW
KEY=$(openssl rand -hex 32)
{ echo "# Généré le $(date -u +%FT%TZ) par rotate-secrets.sh — ne jamais copier ni afficher ce fichier"
  echo "APP_USER=admin"; echo "APP_PASSWORD_HASH='$HASH'"; echo "SECRET_KEY='$KEY'"
  echo "COOKIE_SECURE=${COOKIE_SECURE:-1}"; echo "TRUST_PROXY=${TRUST_PROXY:-1}"; echo "SESSION_HOURS=8"
  echo "TB_CONTAINER=$CONTAINER"; echo "TB_PORT=$PORT"; } > "$ROOT/.env.${RC_TAG}"
unset HASH KEY; chmod 600 "$ROOT/.env.${RC_TAG}"
log ".env.${RC_TAG} écrit (mode 600) : hachage scrypt du mot de passe + secret de session de 64 caractères"
