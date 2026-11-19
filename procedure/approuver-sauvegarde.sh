#!/bin/bash
# Enregistre les empreintes SHA-256 des deux scripts de sauvegarde approuvés ET de la garde (tb-common.sh) et du lecteur de configuration (lire-conf.sh) dans le fichier d'approbation de root :
# c'est ce fichier qui active, pour ces seuls scripts et pour leur contenu exact, l'exception à CONFIRM_PROD (voir tb-common.sh).
# À EXÉCUTER PAR ROOT, À LA MAIN, UNIQUEMENT après la décision écrite du propriétaire (Decision Center billing-g5-sauvegarde-quotidienne = A) et après
# relecture du contenu des trois fichiers. Rien dans le dépôt ne l'appelle. Rejouer ce script après TOUTE modification d'un des trois fichiers
# (sinon l'exception cesse de s'appliquer : c'est voulu). Par défaut : simulation, rien n'est écrit.
# Usage : /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p approuver-sauvegarde.sh               -> affiche les empreintes qui seraient enregistrées
#         /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin CONFIRM_SAUVEGARDE=OUI-<AAAAMMJJ> /bin/bash -p approuver-sauvegarde.sh --ecrire
#         (sans -p le script refuse dès qu'une fonction exportée ou BASH_ENV est présent dans l'environnement)
# Fichier cible : /etc/time-billing/approved-scripts.sha256 (constante ; aucune variable d'environnement ne le change).
# rc25 (revue adverse) : même contrôle d'environnement que les scripts d'entrée (mots-clés bash seulement) puis PATH fixe ; démarrer par « /usr/bin/env -i PATH=… /bin/bash -p ».
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
PATH=/usr/sbin:/usr/bin:/sbin:/bin
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd -P)
TARGET=/etc/time-billing/approved-scripts.sha256      # constante, comme dans tb-common.sh (les tests travaillent sur une copie modifiée de cette ligne)
FILES=(backup-quotidien.sh verifier-sauvegarde.sh tb-common.sh lire-conf.sh)
die() { echo "ARRÊT : $*" >&2; exit 1; }
root_only() { [ -e "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %u -- "$1")" = 0 ] && [ $(( 8#$(stat -c %a -- "$1") & 8#022 )) = 0 ]; }
ancestors_ok() { local d; d=$(dirname -- "$1"); while :; do [ -d "$d" ] && [ ! -L "$d" ] && [ "$(stat -c %u -- "$d")" = 0 ] || return 1
  { [ $(( 8#$(stat -c %a -- "$d") & 8#022 )) = 0 ] || [ $(( 8#$(stat -c %a -- "$d") & 8#1000 )) != 0 ]; } || return 1; [ "$d" = / ] && return 0; d=$(dirname -- "$d"); done; }
[ "$(id -u)" = 0 ] || die "à exécuter par root"
for f in "${FILES[@]}"; do [ -f "$DIR/$f" ] || die "$DIR/$f introuvable"; done
hashes() { (cd "$DIR" && sha256sum -- "${FILES[@]}"); }
LINES=$(hashes)
printf '%s\n' "$LINES"
if [ "${1:-}" != "--ecrire" ]; then
  echo "Simulation : rien n'est écrit. Pour enregistrer (après décision écrite du propriétaire) : CONFIRM_SAUVEGARDE=OUI-$(date -u +%Y%m%d) $0 --ecrire"; exit 0; fi
[ "${CONFIRM_SAUVEGARDE:-}" = "OUI-$(date -u +%Y%m%d)" ] || die "confirmation manquante ou périmée : CONFIRM_SAUVEGARDE=OUI-$(date -u +%Y%m%d)"
# on n'approuve que des fichiers eux-mêmes dignes de confiance : à root, ni liens symboliques, ni écriture par le groupe ou les autres
for f in "${FILES[@]}"; do root_only "$DIR/$f" || die "$DIR/$f n'appartient pas à root, est un lien symbolique ou est modifiable par le groupe / les autres"; done
ancestors_ok "$DIR/x" || die "un dossier parent de $DIR n'appartient pas à root ou est modifiable par d'autres (la garde refuserait l'exception)"
root_only "$DIR" || die "le dossier $DIR n'appartient pas à root ou est modifiable par le groupe / les autres"
TDIR=$(dirname -- "$TARGET")
ancestors_ok "$TDIR" || die "un dossier parent de $TDIR n'appartient pas à root ou est modifiable par d'autres : $TDIR n'est pas créé / utilisé (la garde refuserait l'exception)"
if [ -e "$TDIR" ]; then root_only "$TDIR" || die "$TDIR n'appartient pas à root, est un lien symbolique ou est modifiable par le groupe / les autres"
else mkdir -m 0755 -- "$TDIR"; chown root:root -- "$TDIR"; fi
{ [ ! -e "$TARGET" ] && [ ! -L "$TARGET" ]; } || { [ -f "$TARGET" ] && [ ! -L "$TARGET" ]; } || die "$TARGET existe mais n'est pas un fichier ordinaire (lien symbolique ou dossier) : refus"
LINES=$(hashes)                                                       # empreintes recalculées APRÈS les contrôles de confiance, puis vérifiées une dernière fois avant l'écriture
TMP=$(mktemp "$TDIR/.approved.XXXXXX"); trap 'rm -f -- "$TMP"' EXIT
printf '%s\n' "$LINES" > "$TMP"; chown root:root -- "$TMP"; chmod 0644 -- "$TMP"
[ "$(hashes)" = "$LINES" ] || die "un des fichiers a changé pendant l'approbation : rien n'est enregistré (relancer)"
mv -fT -- "$TMP" "$TARGET"; trap - EXIT                                  # rename atomique ; -T : jamais « dans » un dossier
echo "Approbation enregistrée dans $TARGET (root:root, 0644)."
command -v logger >/dev/null 2>&1 && logger -t time-billing "empreintes des scripts de sauvegarde approuvées dans $TARGET" || true
