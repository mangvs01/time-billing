#!/bin/bash
# Time Billing V9 — common helpers for the RC deployment / rollback scripts (tag derived from VERSION) / rollback scripts. Usage: <script> <config file>
# Never prints a secret: only variable names, lengths, hashes of files and HTTP status codes are shown.
set -euo pipefail
. "${BASH_SOURCE[0]%/*}/lire-conf.sh" || : "${BASH_SOURCE[999]:?ARRÊT : lire-conf.sh introuvable ou en erreur}"      # rc25 : la configuration est lue comme des DONNÉES (jamais exécutée)
CONF=${1:?usage: $0 <fichier de configuration>}; lire_conf "$CONF" || : "${BASH_SOURCE[999]:?ARRÊT : configuration refusée}"
: "${ROOT:?}" "${PROJECT:?}" "${CONTAINER:?}" "${IMAGE:?}" "${URL:?}" "${BACKUP_BASE:?}" "${SOURCE_APP:?}" "${SOURCE_REQ:?}" "${RC_IMAGE:?}" "${COMPOSE_TEMPLATE:?}"
VERSION=$(sed -n 's/^VERSION="\(.*\)"/\1/p' "$SOURCE_APP/app.py"); [ -n "$VERSION" ] || { echo "ARRÊT : VERSION introuvable dans $SOURCE_APP/app.py" >&2; exit 1; }
RC_TAG=${VERSION#9.2-}            # rc11, rc12… : tout est dérivé du code à déployer
PROC_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STATE="$BACKUP_BASE/last-backup"
log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "ARRÊT : $*"; exit 1; }
# rc25 (TB-06) : un seul piège EXIT par script. cleanup <cmd> = nettoyage toujours exécuté ; on_fail <cmd> = reprise exécutée seulement en cas
# d'échec (code ≠ 0, die, interruption), par ex. relancer l'ancienne version que le script a arrêtée. Un « trap … EXIT » posé ensuite écraserait
# ces reprises : les scripts n'en posent plus. INT / TERM / HUP passent par EXIT (sans cela, une interruption sautait la reprise).
CLEANUPS=(); ON_FAIL=""
cleanup() { CLEANUPS+=("$1"); }
on_fail() { ON_FAIL=$1; }
_on_exit() { local rc=$?; trap - EXIT INT TERM HUP; set +e
  if [ "$rc" != 0 ] && [ -n "$ON_FAIL" ]; then log "échec (code $rc) : reprise — $ON_FAIL"; eval "$ON_FAIL"; fi
  local c; for c in "${CLEANUPS[@]}"; do eval "$c"; done; exit "$rc"; }
trap _on_exit EXIT; trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP
restart_old() { compose start >/dev/null 2>&1 && log "ancienne version relancée (rien n'a été modifié)" || log "ATTENTION : relance de l'ancienne version impossible : docker compose -p $PROJECT start"; }
# --- production guard (rc25) -----------------------------------------------------------------------------------------------------------------------
# Every script that sources this file refuses to act on PRODUCTION without CONFIRM_PROD=OUI-<today's date, UTC>.
# "Production" is recognised by ANY of its identifiers (canonical ROOT, PROJECT, CONTAINER, IMAGE, port 8091), not by one spelling of ROOT: a configuration
# that writes the path differently ("/opt/time-billing-v9/", a symlink) or that only names the production container is still production.
PROD_ROOT=/opt/time-billing-v9
is_production() {
  local r; r=$(PATH=/usr/sbin:/usr/bin:/sbin:/bin readlink -f -- "$ROOT" 2>/dev/null || printf '%s' "$ROOT")
  [ "$ROOT" = "$PROD_ROOT" ] || [ "$r" = "$PROD_ROOT" ] || [ "$PROJECT" = time-billing-v9 ] || [ "$CONTAINER" = time-billing-v9 ] \
    || [ "$IMAGE" = time-billing-v9-time-billing-v9 ] || [[ "$URL" == *:8091 || "$URL" == *:8091/* ]]
}
# Narrow exception for the two nightly backup jobs (owner decision billing-g5-sauvegarde-quotidienne). INACTIVE by default: it applies only when a root-owned
# approvals file lists the SHA-256 of the calling script AND of this guard, and every file involved is root-owned, a regular file (no symlink) and not
# writable by group or others. The exception is bound to the CONTENT of the scripts, not to a path or a name alone. Any doubt = the strict guard above.
# What this does and does not protect: a script edited by anyone without root, or edited and not re-approved, loses the exception (fail-closed). It cannot
# protect against root itself, which can also rewrite the approvals file.
APPROVALS_FILE=/etc/time-billing/approved-scripts.sha256      # constante : aucune variable d'environnement ne peut désigner un autre fichier (les tests travaillent sur une copie modifiée de cette ligne)
root_only() { # $1 = path: exists, not a symlink, owned by root, no write bit for group or others
  [ -e "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %u -- "$1")" = 0 ] && [ $(( 8#$(stat -c %a -- "$1") & 8#022 )) = 0 ]
}
ancestors_ok() { # $1 = real path: every directory above it is a root-owned directory that others cannot rename entries in (write bit only allowed with the sticky bit, e.g. /tmp)
  local d; d=$(dirname -- "$1")
  while :; do
    [ -d "$d" ] && [ ! -L "$d" ] && [ "$(stat -c %u -- "$d")" = 0 ] || return 1
    { [ $(( 8#$(stat -c %a -- "$d") & 8#022 )) = 0 ] || [ $(( 8#$(stat -c %a -- "$d") & 8#1000 )) != 0 ]; } || return 1
    [ "$d" = / ] && return 0; d=$(dirname -- "$d")
  done
}
backup_exception_ok() { # $1 = real path of the calling script
  local real=$1 guard dir f want have
  local PATH=/usr/sbin:/usr/bin:/sbin:/bin                           # the checks below must not run a look-alike stat / sha256sum / awk found first in the caller's PATH
  guard=$(readlink -f -- "${BASH_SOURCE[0]}"); dir=$(dirname -- "$real")
  [[ $- == *p* ]] || return 1                                            # démarré par « bash -p » (ou shebang -p) : aucune fonction ni BASH_ENV hérités de l'environnement
  case "$(basename -- "$real")" in backup-quotidien.sh|verifier-sauvegarde.sh) ;; *) return 1 ;; esac
  [ "$(dirname -- "$guard")" = "$dir" ] || return 1                    # the guard that is running sits next to the script it protects
  root_only "$APPROVALS_FILE" && root_only "$(dirname -- "$APPROVALS_FILE")" && ancestors_ok "$(readlink -f -- "$APPROVALS_FILE")" || return 1
  for f in "$real" "$guard" "$dir/lire-conf.sh"; do
    root_only "$f" && root_only "$(dirname -- "$f")" && ancestors_ok "$f" || return 1
    want=$(awk -v n="$(basename -- "$f")" 'NF==2 && $2==n {print $1}' "$APPROVALS_FILE")   # exactly one line per name: a duplicate gives two lines, which never match
    have=$(sha256sum -- "$f" | cut -d' ' -f1)
    { [[ "$want" =~ ^[0-9a-f]{64}$ ]] && [ "$want" = "$have" ]; } || return 1
  done
}
# les trois commandes qui décident (readlink, date, et celles de backup_exception_ok) sont cherchées dans un PATH FIXE, jamais dans celui de l'appelant
SCRIPT_REAL=$(PATH=/usr/sbin:/usr/bin:/sbin:/bin readlink -f -- "${BASH_SOURCE[1]:-$0}")
TODAY_UTC=$(PATH=/usr/sbin:/usr/bin:/sbin:/bin date -u +%Y%m%d)
if is_production && [ "${CONFIRM_PROD:-}" != "OUI-$TODAY_UTC" ]; then
  if backup_exception_ok "$SCRIPT_REAL"; then
    log "garde production : exception « sauvegarde » ($(basename -- "$SCRIPT_REAL") et tb-common.sh conformes aux empreintes SHA-256 de $APPROVALS_FILE)"
  else
    die "cible = PRODUCTION. Exporter CONFIRM_PROD=OUI-$TODAY_UTC uniquement après accord explicite."
  fi
fi
# 2026-10-07 (relecture adverse) : empreinte du code à déployer, notée par 20 et contrôlée par 30 et 40 (un changement de l'arbre de travail
# entre la répétition et le déploiement déploierait du code non répété)
app_digest() { (cd "$SOURCE_APP" && find . -type f ! -path '*/__pycache__/*' ! -name '*.before-*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64); }
same_app() { [ "$(app_digest)" = "$(cat "$1/source-app.sha256")" ] || die "le code de $SOURCE_APP a changé depuis la sauvegarde (20) : relancer 20-backup puis 30"; }
compose() { (cd "$ROOT" && docker compose -p "$PROJECT" "$@"); }
# 2026-10-07 (répétition production F) : la sauvegarde du déploiement est retrouvée par son horodatage (last-backup), BTAG = version qu'elle précède.
# 30/40/50 exigent BTAG = RC_TAG (VERSION changée dans le dépôt depuis 20 = code non répété) ; 90 revient du déploiement réellement fait,
# quelle que soit la VERSION du dépôt au moment du retour (avant : « sauvegarde altérée » et retour impossible).
last_backup() { local f=${1:-$STATE}; [ -f "$f" ] || die "aucune sauvegarde enregistrée : exécuter 20-backup.sh"; TS=$(cat "$f")
  local d=( "$BACKUP_BASE"/pre-*-"$TS" ); { [ ${#d[@]} = 1 ] && [ -d "${d[0]}" ]; } || die "sauvegarde pre-*-$TS introuvable ou ambiguë dans $BACKUP_BASE"
  B=${d[0]}; BTAG=${B##*/pre-}; BTAG=${BTAG%-"$TS"}; }
same_tag() { [ "$BTAG" = "$RC_TAG" ] || die "la sauvegarde $TS précède $BTAG mais le code de $SOURCE_APP est maintenant $VERSION : relancer 20-backup puis 30"; }
health() { curl -s -m 5 "$URL/health" || true; }
# rc25 (TB-06) : le port publié est celui de URL (fichier de configuration de l'environnement), jamais un défaut commun aux environnements
url_port() { local p; p=$(sed -nE 's#^http://127\.0\.0\.1:([0-9]{1,5})/?$#\1#p' <<<"$URL")
  [ -n "$p" ] || { log "ARRÊT : URL=$URL : écoute locale http://127.0.0.1:<port> attendue" >&2; return 1; }; echo "$p"; }
# rc25 (TB-06) : marqueur GO de la répétition (30), lié à la sauvegarde, à sa base, au code et à l'image de répétition ; exigé par 40
go_marker() { printf 'GO ts=%s tag=%s db=%s app=%s image=%s\n' "$TS" "$RC_TAG" "$(sha256sum < "$B/timebilling.db" | cut -c1-64)" "$(app_digest)" \
  "$(docker image inspect "$RC_IMAGE" --format '{{.Id}}')"; }
# rc25 (TB-06) : image de retour = étiquette pre-<tag>-<TS> ; si un « prune » l'a supprimée (ou si elle a été réétiquetée), elle est rechargée depuis
# la copie image.tar.gz de la sauvegarde (contrôlée par SHA256SUMS). Identifiant final = image-id.txt, sinon arrêt (à appeler AVANT tout arrêt du service).
rollback_image() { local tag="$IMAGE:pre-${BTAG}-$TS" want have; want=$(cat "$B/image-id.txt")
  have=$(docker image inspect "$tag" --format '{{.Id}}' 2>/dev/null || true)
  if [ "$have" != "$want" ]; then
    [ -f "$B/image.tar.gz" ] || die "image de retour $tag absente ou différente de image-id.txt, et aucune copie image.tar.gz dans $B : retour arrière impossible (service inchangé)"
    gunzip -c "$B/image.tar.gz" | docker load -q >/dev/null || die "rechargement de $B/image.tar.gz impossible (service inchangé)"
    have=$(docker image inspect "$tag" --format '{{.Id}}' 2>/dev/null || true)
    [ "$have" = "$want" ] || die "image rechargée $tag différente de image-id.txt (service inchangé)"
    log "image de retour $tag rechargée depuis la copie de la sauvegarde"
  fi; }
wait_health() { for _ in $(seq 1 60); do curl -sf -m 2 "$URL/health" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
# throwaway, network-less container on a DB copy; ephemeral random secrets (the app refuses to start without them)
py_on_copy() { local dir=$1 image=$2; shift 2
  docker run --rm --user 0:0 --network none -v "$SOURCE_APP:/app/app:ro" -v "$dir:/data" -e DB_PATH=/data/timebilling.db \
    -e SECRET_KEY="$(openssl rand -hex 32)" -e APP_PASSWORD="$(openssl rand -hex 16)" -e COOKIE_SECURE=0 -w /app "$image" python -c "$@"; }
# effectifs par table + empreintes ligne à ligne des saisies, factures / brouillons, mandats et paramètres (G4 : 50-verify les compare après le déploiement)
# 2026-10-07 (répétition production F, base V9.0) : empreintes limitées aux tables et colonnes PRÉSENTES à la sauvegarde, liste des colonnes
# enregistrée (clé « …_cols ») et réutilisée par 50 — une table absente de V9.0 (settings) faisait échouer 20, et « SELECT * » après une migration
# qui ajoute des colonnes aurait signalé à tort un contenu différent. Sauvegarde plus ancienne sans « …_cols » : toutes les colonnes, comme avant.
DIGEST_PY="
import hashlib,json
def table_cols(c,t): return [r[1] for r in c.execute('PRAGMA table_info('+t+')')]
def digest(c,t,cols,order): return hashlib.sha256(json.dumps([list(r) for r in c.execute('SELECT '+','.join('['+x+']' for x in cols)+' FROM '+t+' ORDER BY ['+order+']')],default=str).encode()).hexdigest()
DIGESTS={'_entries_sha256':('entries',['id','work_date','project_id','start_time','end_time','hours','description'],'id'),
         '_invoices_sha256':('invoices',None,'id'),'_projects_sha256':('projects',None,'id'),'_settings_sha256':('settings',None,'key')}"
COUNT_PY="
import sqlite3,json,sys
$DIGEST_PY
c=sqlite3.connect('/data/timebilling.db'); t=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\")]
out={x:c.execute(f'SELECT COUNT(*) FROM \"{x}\"').fetchone()[0] for x in t}
for k,(x,cols,o) in DIGESTS.items():
    if x not in t: continue
    cols=[y for y in (cols or table_cols(c,x)) if y in table_cols(c,x)]; out[k]=digest(c,x,cols,o); out[k+'_cols']=cols
print(json.dumps(out, sort_keys=True))"
