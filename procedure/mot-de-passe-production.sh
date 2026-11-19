#!/bin/bash
# G5 (Decision Center billing-g5-bascule-production = PLAN_OK) : mot de passe de la PRODUCTION généré aléatoirement (24 caractères sans
# caractère ambigu), écrit dans un fichier lisible par root seulement, puis rotate-secrets.sh (hachage scrypt + nouveau secret de session dans
# $ROOT/.env.<rc>). L'utilisateur lit le fichier, range le mot de passe dans son gestionnaire, puis supprime le fichier. Jamais affiché ici.
# Usage : procedure/mot-de-passe-production.sh <configuration>   (production : CONFIRM_PROD=OUI-<AAAAMMJJ>, comme rotate-secrets.sh)
#   variable : MDP_FICHIER (/root/time-billing-v9-mot-de-passe.txt) — refus s'il existe déjà (jamais écrasé).
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
MDP_FICHIER=${MDP_FICHIER:-/root/time-billing-v9-mot-de-passe.txt}
[ -e "$MDP_FICHIER" ] && die "$MDP_FICHIER existe déjà : le lire / le supprimer d'abord (jamais écrasé)"
umask 077
python3 -I -c "import secrets,sys; a='abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'; sys.stdout.write(''.join(secrets.choice(a) for _ in range(24)))" > "$MDP_FICHIER"
chmod 600 "$MDP_FICHIER"
[ "$(wc -c < "$MDP_FICHIER")" = 24 ] || { rm -f "$MDP_FICHIER"; die "génération du mot de passe impossible"; }
if ! NEW_PASSWORD_FILE="$MDP_FICHIER" bash "$PROC_DIR/rotate-secrets.sh" "$CONF"; then rm -f "$MDP_FICHIER"; die "rotate-secrets en échec : fichier du mot de passe supprimé, rien n'est changé"; fi
log "mot de passe de $(basename "$ROOT") : $MDP_FICHIER (600, 24 caractères) — le ranger dans le gestionnaire de mots de passe puis supprimer le fichier"
