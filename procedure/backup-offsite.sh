#!/usr/bin/env bash
# Envoi hors serveur d'une sauvegarde locale déjà créée et vérifiée.
# Remote rclone + restic (chiffrement de bout en bout ; plus de variante S3) ; notification e-mail uniquement en cas d'échec.
# Usage: backup-offsite.sh /root/backups/time-billing-v9-prod/quotidiennes/timebilling-YYYYMMDDTHHMMSSZ.db
set -Eeuo pipefail
umask 077
# Environnement d'exécution durci comme lire-conf.sh / les scripts d'entrée (0d2f3ce) : AVANT tout le reste, uniquement des mots-clés bash. Hors « bash -p », refus si
# l'environnement porte une fonction exportée (BASH_FUNC_…), BASH_ENV, ENV ou SHELLOPTS ; ${…:?} termine le shell sans appeler « exit ». Invocation attendue (cron) :
#   /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p /chemin/procedure/backup-offsite.sh <sauvegarde.db>
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
[[ $- == *p* || ( -z ${ENV+x} && -z ${BASH_ENV+x} ) ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (ENV ou BASH_ENV défini) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"

CONFIG=${TB_BACKUP_CONFIG:-/etc/time-billing-backup.env}

# Lecture SÛRE de la configuration : le fichier n'est JAMAIS exécuté (ni « source », ni « . »), il est lu comme des DONNÉES (même principe que lire-conf.sh, correctif 0d2f3ce).
# Format : lignes vides, commentaires (« # … » en début de ligne), et CLÉ=valeur ou CLÉ="valeur" ; CLÉ dans la liste fermée ci-dessous, une seule fois ;
# la valeur est validée selon sa clé (remote rclone, chemin absolu sans « .. », entier, hôte, adresse e-mail…). Toute ligne invalide = refus de TOUT le fichier (fail-closed) ;
# les variables ne sont affectées qu'après validation complète, et rien n'est hérité de l'environnement pour ces clés.
BACKUP_CONF_KEYS=" RESTIC_REPOSITORY RCLONE_CONFIG RESTIC_PASSWORD_FILE RESTIC_READ_DATA_SUBSET KEEP_DAILY KEEP_MONTHLY TB_SMTP_HOST TB_SMTP_PORT TB_SMTP_TLS TB_SMTP_FROM TB_ALERT_TO TB_SMTP_USER TB_SMTP_PASSWORD "

conf_value_ok() { # $1 = clé, $2 = valeur ; retour 0 si valide
  local k=$1 v=$2
  local re_abs='^/[A-Za-z0-9_./-]*$' re_host='^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$' re_mail='^[A-Za-z0-9._%+-]+@[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$'
  local re_rclone='^rclone:[A-Za-z0-9_][A-Za-z0-9_.-]*:[A-Za-z0-9_./-]+$'
  local re_subset1='^[0-9]{1,3}/[0-9]{1,3}$' re_subset2='^[0-9]{1,3}(\.[0-9]{1,3})?%$'
  case $k in
    RESTIC_REPOSITORY) [[ $v != *..* ]] && [[ $v =~ $re_rclone ]] ;;
    RCLONE_CONFIG|RESTIC_PASSWORD_FILE) [[ $v =~ $re_abs && $v != *..* && $v != *//* && $v != */ ]] ;;
    RESTIC_READ_DATA_SUBSET) [[ $v =~ $re_subset1 || $v =~ $re_subset2 ]] ;;
    KEEP_DAILY|KEEP_MONTHLY) [[ $v =~ ^[0-9]{1,4}$ ]] ;;
    TB_SMTP_HOST) [[ $v =~ $re_host ]] ;;
    TB_SMTP_PORT) [[ $v =~ ^[0-9]{1,5}$ ]] ;;
    TB_SMTP_TLS) [[ $v == starttls || $v == ssl || $v == none ]] ;;
    TB_SMTP_FROM|TB_ALERT_TO|TB_SMTP_USER) [[ $v =~ $re_mail ]] ;;
    TB_SMTP_PASSWORD) [[ $v =~ ^[A-Za-z0-9_.:@%+,/=-]{1,256}$ ]] ;;
    *) return 1 ;;
  esac
}

lire_conf_sauvegarde() { # $1 = fichier ; retour 0 = tout le fichier est valide et affecté ; 2 = refus (message sur stderr)
  local file=${1-} content line k v n=0 seen=" " keys=() vals=() i
  local re_quoted='^([A-Z][A-Z0-9_]*)="([^"]*)"$' re_plain="^([A-Z][A-Z0-9_]*)=([^\"']*)\$"
  if [[ ! -f $file || ! -r $file ]]; then echo "ARRÊT : configuration illisible : ${file:-<vide>}" >&2; return 2; fi
  content=$(< "$file") || { echo "ARRÊT : configuration illisible : $file" >&2; return 2; }   # une seule lecture : ce qui est validé est ce qui est affecté
  while IFS= read -r line || [[ -n $line ]]; do
    n=$((n + 1))
    [[ $line =~ ^[[:space:]]*(#.*)?$ ]] && continue
    if [[ $line =~ $re_quoted || $line =~ $re_plain ]]; then k=${BASH_REMATCH[1]}; v=${BASH_REMATCH[2]}
    else echo "ARRÊT : $file ligne $n refusée (format CLÉ=valeur attendu ; la configuration est lue comme des données, jamais exécutée)" >&2; return 2; fi
    if [[ $k == AWS_* || ( $k == RESTIC_REPOSITORY && $v == s3:* ) ]]; then echo "ARRÊT : $file ligne $n : la variante S3 (s3:, AWS_*) n'est plus prise en charge ; seul un remote rclone (rclone:Remote:chemin) est autorisé" >&2; return 2; fi
    if [[ $BACKUP_CONF_KEYS != *" $k "* ]]; then echo "ARRÊT : $file ligne $n : clé « $k » inconnue (clés admises :$BACKUP_CONF_KEYS)" >&2; return 2; fi
    if [[ $seen == *" $k "* ]]; then echo "ARRÊT : $file ligne $n : clé « $k » définie deux fois" >&2; return 2; fi
    conf_value_ok "$k" "$v" || { echo "ARRÊT : $file ligne $n : valeur refusée pour $k (remote rclone, chemin absolu sans « .. », sans substitution ni caractère spécial attendus)" >&2; return 2; }
    seen+="$k "; keys+=("$k"); vals+=("$v")
  done <<<"$content"
  for k in $BACKUP_CONF_KEYS; do unset -v "$k"; done                                           # rien n'est hérité de l'environnement
  for i in "${!keys[@]}"; do printf -v "${keys[$i]}" '%s' "${vals[$i]}"; done
}

# Contrôle de syntaxe seul, sans sauvegarde, sans rclone/restic, sans e-mail : backup-offsite.sh --check-config <fichier>
if [[ ${1-} == --check-config ]]; then
  [[ $# -eq 2 ]] || { echo "Usage: backup-offsite.sh --check-config <fichier>" >&2; exit 2; }
  lire_conf_sauvegarde "$2" || exit 2
  echo "Configuration valide : $2"
  exit 0
fi

CURRENT_STEP="initialisation"
ALERT_SENT=0
HOST_LABEL=$(hostname -f 2>/dev/null || hostname)

send_failure_email() {
  local rc="$1"
  [[ "$ALERT_SENT" = 0 ]] || return 0
  ALERT_SENT=1
  export TB_SMTP_HOST TB_SMTP_PORT TB_SMTP_TLS TB_SMTP_FROM TB_ALERT_TO TB_SMTP_USER TB_SMTP_PASSWORD
  [[ -n "${TB_SMTP_HOST:-}" && -n "${TB_SMTP_FROM:-}" && -n "${TB_ALERT_TO:-}" ]] || {
    printf 'ALERTE NON ENVOYÉE : configuration SMTP incomplète (code %s, étape %s).\n' "$rc" "$CURRENT_STEP" >&2
    return 1
  }
  TB_ALERT_SUBJECT="[Time Billing] ÉCHEC sauvegarde distante — ${HOST_LABEL}"
  TB_ALERT_BODY=$(printf "Échec de la sauvegarde distante Time Billing.\n\nHôte : %s\nÉtape : %s\nCode retour : %s\nHorodatage UTC : %s\n\nAucune bascule de production n'a été lancée par ce script. Consulter le journal cron/systemd local.\n" "$HOST_LABEL" "$CURRENT_STEP" "$rc" "$(date -u +%FT%TZ)")
  export TB_ALERT_SUBJECT TB_ALERT_BODY
  python3 - <<'PY'
import os, smtplib, ssl, sys
from email.message import EmailMessage
msg = EmailMessage()
msg["Subject"] = os.environ["TB_ALERT_SUBJECT"]
msg["From"] = os.environ["TB_SMTP_FROM"]
msg["To"] = os.environ["TB_ALERT_TO"]
msg.set_content(os.environ["TB_ALERT_BODY"])
host = os.environ["TB_SMTP_HOST"]
port = int(os.environ.get("TB_SMTP_PORT", "587"))
mode = os.environ.get("TB_SMTP_TLS", "starttls").lower()
user = os.environ.get("TB_SMTP_USER", "")
password = os.environ.get("TB_SMTP_PASSWORD", "")
try:
    if mode == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as s:
            if user: s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            if mode == "starttls":
                s.starttls(context=ssl.create_default_context()); s.ehlo()
            elif mode != "none":
                raise ValueError("TB_SMTP_TLS must be ssl, starttls or none")
            if user: s.login(user, password)
            s.send_message(msg)
except Exception as e:
    print("Échec de l'envoi de l'alerte e-mail (" + type(e).__name__ + ").", file=sys.stderr)
    sys.exit(1)
print("Alerte e-mail envoyée.")
PY
}

on_exit() {
  local rc=$?
  trap - EXIT
  if [[ "$rc" -ne 0 ]]; then
    send_failure_email "$rc" || true
  fi
  exit "$rc"
}
trap on_exit EXIT

CURRENT_STEP="vérification de la configuration"
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || { echo "Configuration absente ou lien symbolique : $CONFIG" >&2; exit 2; }
read -r CONFIG_UID CONFIG_MODE < <(stat -c '%u %a' "$CONFIG")
[[ "$CONFIG_UID" = 0 && "$((8#$CONFIG_MODE & 077))" -eq 0 ]] || { echo "La configuration doit appartenir à root et être inaccessible au groupe/autres (chmod 600)." >&2; exit 2; }
lire_conf_sauvegarde "$CONFIG" || exit 2
for v in RESTIC_REPOSITORY RESTIC_PASSWORD_FILE TB_SMTP_HOST TB_SMTP_PORT TB_SMTP_TLS TB_SMTP_FROM TB_ALERT_TO KEEP_DAILY KEEP_MONTHLY; do
  [[ -n "${!v:-}" ]] || { echo "Variable requise absente : $v" >&2; exit 2; }
done
if [[ "$RESTIC_REPOSITORY" == rclone:* ]]; then
  RCLONE_CONFIG=${RCLONE_CONFIG:-/etc/time-billing-backup/rclone.conf}
  [[ -f "$RCLONE_CONFIG" && ! -L "$RCLONE_CONFIG" ]] || { echo "Configuration rclone absente ou lien symbolique." >&2; exit 2; }
  read -r RCLONE_UID RCLONE_MODE < <(stat -c '%u %a' "$RCLONE_CONFIG")
  [[ "$RCLONE_UID" = 0 && "$((8#$RCLONE_MODE & 077))" -eq 0 ]] || { echo "La configuration rclone doit appartenir à root et être inaccessible au groupe/autres (chmod 600)." >&2; exit 2; }
  export RCLONE_CONFIG
  command -v rclone >/dev/null || { echo "Dépendance absente : rclone." >&2; exit 127; }
else
  echo "RESTIC_REPOSITORY doit utiliser un remote rclone (rclone:Remote:chemin)." >&2; exit 2
fi
[[ -f "$RESTIC_PASSWORD_FILE" && ! -L "$RESTIC_PASSWORD_FILE" ]] || { echo "Fichier de mot de passe restic absent ou lien symbolique." >&2; exit 2; }
read -r PASS_UID PASS_MODE < <(stat -c '%u %a' "$RESTIC_PASSWORD_FILE")
[[ "$PASS_UID" = 0 && "$((8#$PASS_MODE & 077))" -eq 0 ]] || { echo "Le fichier de mot de passe restic doit appartenir à root et être inaccessible au groupe/autres." >&2; exit 2; }
command -v restic >/dev/null || { echo "Dépendance absente : restic." >&2; exit 127; }

CURRENT_STEP="validation du fichier de sauvegarde local"
SRC=${1:?Usage: backup-offsite.sh /root/backups/time-billing-v9-prod/quotidiennes/timebilling-*.db}
EXPECTED_DIR=/root/backups/time-billing-v9-prod/quotidiennes
[[ -f "$SRC" && ! -L "$SRC" ]] || { echo "La sauvegarde source doit être un fichier régulier, non symbolique." >&2; exit 2; }
SRC_REAL=$(realpath "$SRC")
[[ "$(dirname "$SRC_REAL")" = "$EXPECTED_DIR" ]] || { echo "La source doit provenir du répertoire quotidien de sauvegarde de production." >&2; exit 2; }
BASE=$(basename "$SRC_REAL")
[[ "$BASE" =~ ^timebilling-[0-9]{8}T[0-9]{6}Z\.db$ ]] || { echo "Nom de sauvegarde inattendu." >&2; exit 2; }
(
  cd "$EXPECTED_DIR"
  grep -F "  $BASE" SHA256SUMS | tail -n 1 | sha256sum -c --status -
) || { echo "Empreinte de la sauvegarde locale absente ou invalide." >&2; exit 3; }
python3 - "$SRC_REAL" <<'PY'
import sqlite3, sys
p = sys.argv[1]
c = sqlite3.connect("file:" + p + "?mode=ro", uri=True)
try:
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integrity_check"
    assert c.execute("PRAGMA foreign_key_check").fetchall() == [], "foreign_key_check"
finally:
    c.close()
PY

CURRENT_STEP="vérification de l'accès au dépôt objet"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE
restic cat config >/dev/null

CURRENT_STEP="transfert chiffré vers le dépôt objet"
restic backup --tag time-billing-prod --host "$HOST_LABEL" "$SRC_REAL"

CURRENT_STEP="contrôle du dépôt distant"
restic check --read-data-subset="${RESTIC_READ_DATA_SUBSET:-1/10}"

CURRENT_STEP="rétention distante"
restic forget --keep-daily "$KEEP_DAILY" --keep-monthly "$KEEP_MONTHLY" --prune

CURRENT_STEP="validation finale du dépôt distant"
restic check

CURRENT_STEP="terminé"
printf 'Sauvegarde distante validée : %s ; dépôt chiffré restic vérifié ; horodatage UTC %s\n' "$BASE" "$(date -u +%FT%TZ)"
