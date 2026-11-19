#!/bin/bash
# Automatisation de RUNBOOK-CLONE-ISOLE-RC25.md §2-§5 pour le clone isolé « billing-rc25-isolated » (127.0.0.1:8093).
#
#   run_clone_recette.sh check     LECTURE SEULE : isolement (montages, privilèges, liens, fichier vu par le conteneur), version, empreinte du code, préconditions de données.
#   run_clone_recette.sh prepare   ÉCRIT dans le CLONE seulement : sauvegarde « golden », mot de passe de test propre au clone (pw.txt, jamais affiché), recréation du conteneur du clone.
#   run_clone_recette.sh run       ÉCRIT dans le CLONE seulement : exécute UNIQUEMENT les recettes dont les préconditions sont satisfaites, chacune après restauration du golden ;
#                                  les autres sont BLOCKED (jamais « adaptées » pour obtenir un PASS). Jamais : import, --apply, base vide, document absent.
#                                  Option réservée au propriétaire : TB_RUN_MISMATCHED="run_ab" lance cette recette malgré l'écart de précondition (FAIL consigné tel quel).
#   run_clone_recette.sh restore   remet le clone dans l'état du golden.
#
# Garde-fous : cible figée (conteneur, dossier, port) ; toute cible contenant « time-billing-v9 » (staging, production) est refusée ; l'isolement est vérifié avant toute écriture ;
# aucun mot de passe n'est lu, affiché ni journalisé ; le staging n'est jamais ouvert (seulement stat, pour comparer les inodes). Les preuves vont dans $C/preuves/<horodatage> (0700).
set -euo pipefail
CMD=${1:-}; [ -n "$CMD" ] || { sed -n 2,12p "$0"; exit 2; }
C=${C:-/opt/time-billing-rc25-isolated}; N=${N:-billing-rc25-isolated}; P=${P:-8093}
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd -P)}
STG=${STG:-/opt/time-billing-v9-staging/data/timebilling.db}
fail() { echo "STOP : $*" >&2; exit 1; }
case "$C$N" in *time-billing-v9*) fail "cible interdite (staging ou production) : $C / $N";; esac
if [ -z "${TB_SIM:-}" ]; then [ "$C" = /opt/time-billing-rc25-isolated ] && [ "$N" = billing-rc25-isolated ] && [ "$P" = 8093 ] || fail "cible différente du clone isolé (réservé aux essais du dépôt : TB_SIM=1)"; fi
E=${E:-$C/preuves/$(date -u +%Y%m%dT%H%M%SZ)}; mkdir -p "$E"; chmod 700 "$C/preuves" "$E" 2>/dev/null || true
log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$E/journal.txt"; }
DB="$C/data/timebilling.db"

isolement() {
  docker ps --filter "name=^/${N}\$" --format '{{.Names}}  {{.Ports}}' > "$E/ps.txt"; cat "$E/ps.txt"
  [ -s "$E/ps.txt" ] || fail "conteneur $N introuvable"
  docker inspect -f '{{range .Mounts}}{{.Source}}:{{.Destination}}{{"\n"}}{{end}}' "$N" | sed '/^$/d' > "$E/mounts.txt"; cat "$E/mounts.txt"
  docker inspect -f '{{.HostConfig.Privileged}} {{.HostConfig.NetworkMode}} {{.HostConfig.PidMode}}' "$N" > "$E/hostconfig.txt"; cat "$E/hostconfig.txt"
  [ "$(cat "$E/mounts.txt")" = "$C/data:/data" ] || fail "montages différents du seul montage attendu $C/data:/data (staging, production, docker.sock ou dossier parent visibles ?)"
  case "$(cat "$E/hostconfig.txt")" in "false bridge "|"false default ") ;; *) fail "conteneur privilégié, réseau hôte ou PID hôte";; esac
  [ "$(readlink -f "$C/data")" = "$C/data" ] || fail "$C/data est un lien symbolique ou passe par un lien"
  [ "$(stat -c %h "$DB")" = 1 ] || fail "la base du clone a plusieurs liens physiques"
  if [ -e "$STG" ]; then [ "$(stat -c %d:%i "$DB")" != "$(stat -c %d:%i "$STG")" ] || fail "la base du clone EST la base du staging (même inode)"; fi
  [ "$(docker exec "$N" printenv DB_PATH)" = /data/timebilling.db ] || fail "DB_PATH inattendu dans le conteneur"
  local h1 h2
  h1=$(docker exec "$N" python -c "import hashlib;print(hashlib.sha256(open('/data/timebilling.db','rb').read()).hexdigest())"); h2=$(sha256sum "$DB" | cut -d' ' -f1)
  [ "$h1" = "$h2" ] || fail "le fichier /data/timebilling.db du conteneur diffère du fichier du clone"
  log "ISOLEMENT OK (montage unique $C/data:/data, non privilégié, base du clone = fichier vu par le conteneur)"
}

identite() {
  local d='cd %s && find . -type f ! -path "*/__pycache__/*" ! -name "*.before-*" -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64'
  local a b v
  a=$(bash -c "$(printf "$d" "$REPO/app")"); b=$(docker exec "$N" sh -c "$(printf "$d" /app/app)")
  v=$(curl -s -m 5 "http://127.0.0.1:$P/health" || true); echo "$v" > "$E/health.txt"
  log "empreinte du code : dépôt=$a conteneur=$b ; health=$v"
  [ "$a" = "$b" ] || fail "l'image ne contient pas le code du dépôt testé ($REPO)"
  case "$v" in *'"version":"9.2-rc25"'*|*'"version": "9.2-rc25"'*) ;; *) fail "version applicative différente de 9.2-rc25";; esac
  log "CODE CONFORME (version 9.2-rc25)"
}

preflight() { python3 -I "$REPO/tests/recette_fonctionnelle/preflight_clone.py" "$DB" --url "http://127.0.0.1:$P" | tee "$E/preflight.txt"; }

attendre() { for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$P/health" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
restore_golden() {
  [ -s "$E/golden.db" ] || [ -n "${GOLDEN:-}" ] || fail "pas de golden (lancer « prepare » d'abord, ou GOLDEN=<fichier>)"
  local g=${GOLDEN:-$E/golden.db}
  [ -s "$g" ] || fail "golden introuvable ou vide : $g (rien n'a été arrêté ni modifié)"
  docker stop "$N" >/dev/null; rm -f "$DB-wal" "$DB-shm"; cp "$g" "$DB"; chown 10001:10001 "$DB" 2>/dev/null || true; chmod 600 "$DB"; docker start "$N" >/dev/null
  attendre || fail "le clone ne redémarre pas"
}

case "$CMD" in
check)
  isolement; identite; preflight
  log "check terminé : lecture seule, aucune écriture. Preuves : $E" ;;
prepare)
  isolement; identite
  docker stop "$N" >/dev/null
  python3 -I - "$DB" "$E/golden.db" <<'PY'
import sqlite3, sys
s = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
PY
  chmod 600 "$E/golden.db"; sha256sum "$E/golden.db" | tee "$E/golden.sha256"
  [ "$(python3 -I -c "import sqlite3,sys; print(sqlite3.connect('file:$E/golden.db?mode=ro',uri=True).execute('PRAGMA integrity_check').fetchone()[0])")" = ok ] || fail "golden : integrity_check différent de ok"
  [ -e "$C/pw.txt" ] || { umask 077; openssl rand -hex 12 > "$C/pw.txt"; }; chmod 600 "$C/pw.txt"
  IMG=$(docker inspect -f '{{.Image}}' "$N"); docker inspect "$N" > "$E/inspect-avant.json"; chmod 600 "$E/inspect-avant.json"   # contient des secrets : ne pas diffuser
  docker rm -f "$N" >/dev/null
  docker run -d --name "$N" -p "127.0.0.1:$P:8000" -v "$C/data:/data" -e SECRET_KEY="$(openssl rand -hex 32)" -e COOKIE_SECURE=0 -e INVOICE_CHECK_WORDS= \
    -e DB_PATH=/data/timebilling.db -e ENV_LABEL=RECETTE -e APP_PASSWORD="$(cat "$C/pw.txt")" "$IMG" >/dev/null
  attendre || fail "le clone ne démarre pas après recréation"
  log "PREPARE OK : golden $(cut -c1-16 "$E/golden.sha256"), conteneur recréé (même image), mot de passe de test dans $C/pw.txt (non affiché)" ;;
restore) restore_golden; log "clone restauré depuis le golden" ;;
run)
  isolement; identite
  [ -s "$E/golden.db" ] || [ -n "${GOLDEN:-}" ] || fail "pas de golden : lancer « prepare » (même dossier E=...)"
  restore_golden; preflight > /dev/null
  : > "$E/resultats.txt"
  verdict() { grep -q "PRÉCONDITIONS OK .*$1" "$E/preflight.txt"; }
  # TB_RUN_MISMATCHED="run_ab" : choix EXPLICITE du propriétaire de lancer une recette malgré un écart de précondition (son FAIL sera consigné tel quel, jamais masqué)
  permis() { verdict "$1" || case " ${TB_RUN_MISMATCHED:-} " in *" $1 "*) true;; *) false;; esac; }
  statut() { # nom  rc  logfile
    local ligne; ligne=$(grep -a '^RÉSULTAT' "$3" | tail -1 || true)
    if [ "$2" = 0 ] && [ -n "$ligne" ] && printf '%s' "$ligne" | grep -q ' 0 KO'; then echo "PASS|$1|rc=$2|$ligne"; else echo "FAIL|$1|rc=$2|${ligne:-sans ligne RÉSULTAT}"; fi; }
  lancer() { local n=$1; shift; ( cd "$REPO" && env "$@" timeout 900 python3 -W ignore "tests/recette_fonctionnelle/$n.py" "$P" "$C" ) > "$E/$n.log" 2>&1 && rc=0 || rc=$?
    statut "$n" "$rc" "$E/$n.log" | tee -a "$E/resultats.txt"; }
  bloque() { echo "BLOCKED|$1|-|$2" | tee -a "$E/resultats.txt"; }
  if verdict 'run_pages'; then restore_golden; lancer run_pages CTN="$N"; else bloque run_pages "préconditions non satisfaites"; fi
  # run_cg, run_dg et run_extra lisent l'état écrit par run_ab (state-ab.json puis state-cg.json) : chaîne ab -> cg -> dg -> extra sur UNE instance, sans restauration entre
  if permis 'run_ab'; then
    restore_golden; lancer run_ab CTN="$N"; lancer run_cg CTN="$N"; lancer run_dg CTN="$N"; lancer run_extra CTN="$N"
  else
    bloque run_ab "précondition de données (1 brouillon n°1 attendu) non satisfaite"
    bloque "run_cg/run_dg/run_extra" "dépendent de l'état écrit par run_ab (state-ab.json) : chaîne non exécutable sans run_ab"
  fi
  if verdict 'run_forecast'; then restore_golden; lancer run_forecast; else bloque run_forecast "préconditions non satisfaites"; fi
  if verdict 'run_entites_vides'; then restore_golden; lancer run_entites_vides; else bloque run_entites_vides "mandats attendus absents ou valeurs différentes"; fi
  if verdict 'run_rc19'; then restore_golden; lancer run_rc19 TB_EXPECT_VERSION=9.2-rc25; else bloque run_rc19 "précondition de données (19 clôturés, 1 brouillon) non satisfaite"; fi
  bloque run_mandats "exige mandats_appliquer.py --apply (interdit)"
  bloque run_premiere_facture "exige --apply (interdit) et Facture-reelle-reference-2026-09.pdf (absent)"
  bloque run_hij "exige Time sheet CP.xlsx, journaux/fonc/launch_fonc.sh et 2 conteneurs supplémentaires (import/restauration)"
  bloque concurrency_http "exige une base vide"
  bloque "recettes navigateur / e2e_http" "voir RUNBOOK §5.2-5.3 (Node/Playwright et docker cp) : non automatisées ici"
  restore_golden
  # contrôle de fin : le clone (au repos) est LOGIQUEMENT identique au golden ; on ne compare pas les octets (le démarrage de l'application peut réécrire le fichier)
  docker stop "$N" >/dev/null
  if python3 -I "$REPO/outils/empreinte_metier.py" comparer "${GOLDEN:-$E/golden.db}" "$DB" > "$E/comparaison-finale.txt" 2>&1; then log "clone restauré : tables métier IDENTIQUES au golden"; else log "ÉCART après restauration : voir $E/comparaison-finale.txt"; fi
  docker start "$N" >/dev/null; attendre || fail "le clone ne redémarre pas"
  sha256sum "$E"/*.log "$E/resultats.txt" "$E/preflight.txt" > "$E/SHA256SUMS-preuves" 2>/dev/null || true
  log "RUN terminé ; clone restauré. Tableau :"; column -t -s'|' "$E/resultats.txt" 2>/dev/null || cat "$E/resultats.txt"
  grep -q '^FAIL' "$E/resultats.txt" && log "au moins un FAIL : lire les journaux $E/*.log" || log "aucun FAIL parmi les recettes exécutées (les BLOCKED restent à lever)" ;;
*) fail "commande inconnue : $CMD" ;;
esac
