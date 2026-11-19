#!/bin/bash
# G4 (Decision Center billing-g4-donnees-production = PROMOTE_STAGING_DB, 2026-10-08) : la base du STAGING, recettée par l'utilisateur, devient la
# base de la PRODUCTION lors de la bascule (G5 : autorisation écrite séparée). Condition de l'utilisateur : toutes les données restent
# modifiables / corrigeables après la bascule — la base est copiée telle quelle (mêmes saisies, historiques, mandats, journaux de corrections).
# À lancer APRÈS le déploiement de la production (10 → 50) dans la MÊME version que le staging, et après la recette du staging.
# Usage : PROMOUVOIR=OUI procedure/70-promouvoir-base-staging.sh procedure/prod.conf procedure/staging.conf
#         (production : CONFIRM_PROD=OUI-<AAAAMMJJ> exigé en plus, comme pour toute la procédure)
# Déroulé : contrôles (deux services sains, même version, même code déployé, production SANS aucune donnée métier) → arrêt du staging (gel :
# plus aucune écriture) → copie cohérente de sa base → arrêt de la production → sauvegarde de sa base → copie préparée (sessions web,
# formulaires gardés et échecs de connexion du staging purgés ; événement d'audit « base promue depuis le staging ») → contrôle copie = staging
# (outils/empreinte_metier.py, toutes les tables métier) → installation → démarrage → contrôle production = staging.
# Échec après l'arrêt de la production : base d'origine remise (SHA-256 vérifié), production et staging relancés.
# Succès : le staging reste ARRÊTÉ (aucune saisie réelle ne doit plus y être faite) ; relance pour des essais : docker compose -p <projet> start.
# Retour arrière : 90-rollback.sh <conf production> avec ABANDONNER_CORRECTIONS=OUI (base V9.0 d'origine) — les données promues restent
# intactes dans la base du staging et dans la sauvegarde promotion-<TS>.
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
SRC_CONF=${2:?usage: $0 <configuration production> <configuration staging>}
[ "${PROMOUVOIR:-}" = OUI ] || die "promotion non confirmée : exporter PROMOUVOIR=OUI (après la recette du staging et l'autorisation de bascule)"
# 2026-10-08 (relecture adverse) : lue SANS hériter de ROOT/PROJECT/URL de la production (ligne absente = valeur de la production auparavant)
lire_conf "$SRC_CONF" S_ || : "${BASH_SOURCE[999]:?ARRÊT : configuration du staging refusée}"                    # rc25 : lue comme des données (jamais exécutée), sans hériter de ROOT/PROJECT/URL de la production
[ -n "${S_ROOT-}" ] && [ -n "${S_PROJECT-}" ] && [ -n "${S_URL-}" ] || die "configuration du staging incomplète ($SRC_CONF)"
[ "$S_PROJECT" != "$PROJECT" ] && [ "$S_URL" != "$URL" ] && [ "$S_ROOT" != "$ROOT" ] || die "configurations de la production et du staging confondues"
[ "$(basename "$ROOT")" = time-billing-v9 ] || die "cible $ROOT : la cible doit être la production (…/time-billing-v9)"
[ "$(basename "$S_ROOT")" = time-billing-v9-staging ] || die "source $S_ROOT : la source doit être le staging (…/time-billing-v9-staging)"
REPO=$(cd "$PROC_DIR/.." && pwd); EMP="$REPO/outils/empreinte_metier.py"
TDB="$ROOT/data/timebilling.db"; SDB="$S_ROOT/data/timebilling.db"
scompose() { (cd "$S_ROOT" && docker compose -p "$S_PROJECT" "$@"); }
version() { curl -s -m 5 "$1/health" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true; }
code_digest() { (cd "$1/app" && find . -type f ! -path '*/__pycache__/*' ! -name '*.before-*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64); }
copie() { python3 - "$1" "$2" <<'PY'
import sqlite3, sys   # copie cohérente (API de sauvegarde SQLite), source ouverte en lecture seule
s = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d)
assert d.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "intégrité"; d.close(); s.close()
PY
}
emp() { python3 -I "$EMP" "$@"; }

# 1. contrôles sans interruption
VT=$(version "$URL"); VS=$(version "$S_URL")
[ -n "$VT" ] || die "production indisponible ($URL) : rien n'est fait"
[ -n "$VS" ] || die "staging indisponible ($S_URL) : rien n'est fait"
[ "$VT" = "$VS" ] || die "versions différentes (production $VT, staging $VS) : déployer d'abord la version du staging en production (10 → 50)"
DT=$(code_digest "$ROOT"); DS=$(code_digest "$S_ROOT")
[ -n "$DT" ] && [ -n "$DS" ] || die "code déployé illisible ($ROOT/app ou $S_ROOT/app) : rien n'est fait"
[ "$DT" = "$DS" ] || die "code déployé différent entre production et staging (même étiquette $VT) : rien n'est fait"
S_STOPPED=0; T_STOPPED=0; APPLYING=0; DONE=0
W=$(mktemp -d /tmp/tb-promotion-XXXX); chmod 700 "$W"
# quoi qu'il arrive (erreur, interruption) : base d'origine remise si l'installation a commencé, production et staging relancés sauf succès
# 2026-10-08 (relecture adverse) : sans « set +e » le piège s'arrêtait au premier échec (ex. journal vers un terminal coupé) et laissait la base
# partielle et les services arrêtés ; les signaux sont ignorés pendant la remise en place. Lancer ce script dans tmux/screen.
trap 'set +e; trap "" INT HUP PIPE TERM; [ "$APPLYING" = 1 ] && restore; [ "$T_STOPPED" = 1 ] && { compose start >/dev/null 2>&1; }
      [ "$S_STOPPED" = 1 ] && [ "$DONE" = 0 ] && { scompose start >/dev/null 2>&1; }; rm -rf "$W"' EXIT
copie "$TDB" "$W/production-en-marche.db" || die "lecture de la base de production impossible"
NV=$(emp vide "$W/production-en-marche.db") || die "la production contient déjà des données ($NV) : promotion refusée, rien n'est fait (nouvelle décision nécessaire)"
log "contrôles : production et staging en $VT, même code ($(code_digest "$ROOT" | cut -c1-12)), production sans donnée métier"

TS=$(date -u +%Y%m%dT%H%M%SZ); B="$BACKUP_BASE/promotion-$TS"; J="$REPO/journaux/promotion-$TS"
mkdir -p "$B" "$J"; chmod 700 "$B" "$J"
OWNER=$(stat -c %u:%g "$TDB"); MODE=$(stat -c %a "$TDB")
running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
restore() { log "ÉCHEC : remise en place de la base de production d'origine" || true; T_STOPPED=1; compose stop >/dev/null 2>&1   # relancée par le piège de sortie
  if running "$CONTAINER"; then T_STOPPED=0; APPLYING=0
    log "production ENCORE EN MARCHE : base non remise ; arrêter le service puis remettre $B/production-avant.db à la main" || true; return 0; fi
  [ -f "$TDB" ] && cp -p "$TDB" "$B/production-echec.db"   # ce qui a pu être écrit après le démarrage n'est jamais écrasé sans copie
  cp "$B/production-avant.db" "$TDB"; chown "$OWNER" "$TDB"; chmod "$MODE" "$TDB"; rm -f "$TDB-wal" "$TDB-shm" "$TDB-journal"; APPLYING=0
  [ "$(sha256sum < "$TDB")" = "$(sha256sum < "$B/production-avant.db")" ] && { log "base de production restaurée (identique à la sauvegarde)" || true; } \
    || { T_STOPPED=0; log "base restaurée DIFFÉRENTE de la sauvegarde : production laissée ARRÊTÉE ; remettre $B/production-avant.db à la main"; }; }

# 2. gel du staging et copie de sa base
log "arrêt du staging (gel : plus aucune écriture)"; S_STOPPED=1; scompose stop
running "$(scompose ps -a -q 2>/dev/null | head -1)" && die "staging toujours en marche après l'arrêt : promotion refusée"
[ -z "$(version "$S_URL")" ] || die "le staging répond encore ($S_URL) après l'arrêt : gel non garanti, promotion refusée"
[ ! -e "$SDB-journal" ] || die "transaction interrompue dans la base du staging ($SDB-journal) : promotion refusée, staging relancé"
copie "$SDB" "$B/staging.db" || die "copie de la base du staging impossible : staging relancé, rien n'est fait"
emp comparer "$SDB" "$B/staging.db" > "$J/copie-staging.txt" || die "copie du staging différente de l'original (voir $J) : staging relancé, rien n'est fait"
log "base du staging copiée (sha $(sha256sum < "$B/staging.db" | cut -c1-12))"
( umask 077; emp empreinte "$B/staging.db" > "$B/staging-empreinte.json" )
log "contenu promu : $(python3 -c 'import json,sys; c=json.load(open(sys.argv[1]))["chiffres"]; print("factures", c.get("factures_par_statut"), "; notes de crédit", c.get("notes_de_credit_par_statut"), "; historiques", {k: v["nombre"] for k, v in c.get("historiques_par_statut", {}).items()}, "; saisies", c.get("saisies"))' "$B/staging-empreinte.json") — toute facture ou note ÉMISE devient une pièce réelle et immuable en production"

# 3. arrêt de la production et sauvegarde de sa base
log "arrêt de la production"; T_STOPPED=1; compose stop
{ ! running "$CONTAINER" && [ -z "$(version "$URL")" ]; } || die "production toujours en marche après l'arrêt : rien n'est fait"
[ ! -e "$TDB-journal" ] || die "transaction interrompue dans la base de production ($TDB-journal) : rien n'est fait, services relancés"
cp -p "$TDB" "$B/production-avant.db"
[ "$(sha256sum < "$TDB")" = "$(sha256sum < "$B/production-avant.db")" ] || die "copie de la base de production différente de l'original : rien n'est fait"
NV=$(emp vide "$B/production-avant.db") || die "la production contient des données ($NV) : promotion refusée, rien n'est fait, services relancés"
log "sauvegarde de la production : $B/production-avant.db (sha $(sha256sum < "$B/production-avant.db" | cut -c1-12)) — aucune donnée métier"

# 4. copie préparée : rien de métier ne change ; sessions et traces transitoires du staging retirées ; événement d'audit
cp "$B/staging.db" "$W/promue.db"
python3 - "$W/promue.db" "$(sha256sum < "$B/staging.db" | cut -d' ' -f1)" "$VS" "$TS" <<'PY' || die "préparation de la copie impossible : rien n'est installé, services relancés"
import json, sqlite3, sys
c = sqlite3.connect(sys.argv[1]); t = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
purge = {x: c.execute(f"DELETE FROM {x}").rowcount for x in ("web_sessions", "kept_forms", "login_failures", "auth_credentials") if x in t}   # BMDP1 : le mot de passe du staging ne passe jamais en production
n = lambda q: c.execute(q).fetchone()[0]
detail = {"source": "staging", "source_sha256": sys.argv[2], "version": sys.argv[3], "promotion": sys.argv[4], "purge": purge,
          "entries": n("SELECT COUNT(*) FROM entries"), "projects": n("SELECT COUNT(*) FROM projects"), "invoices": n("SELECT COUNT(*) FROM invoices"),
          "historical_invoices": n("SELECT COUNT(*) FROM historical_invoices") if "historical_invoices" in t else 0}
c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("database_promoted_from_staging", json.dumps(detail, ensure_ascii=False)))
c.commit(); assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; c.close()
print(json.dumps(detail, ensure_ascii=False))
PY
emp comparer "$B/staging.db" "$W/promue.db" > "$J/copie-promue.txt" || die "copie préparée différente du staging (voir $J) : rien n'est installé, services relancés"
cp -p "$W/promue.db" "$B/promue.db"

# 5. installation et démarrage
APPLYING=1
cp "$W/promue.db" "$TDB"; chown "$OWNER" "$TDB"; chmod "$MODE" "$TDB"; rm -f "$TDB-wal" "$TDB-shm" "$TDB-journal"
# répétition seulement (jamais sous /opt) : échec simulé après l'installation, pour vérifier la remise en place de la base d'origine
case "$ROOT" in /opt/*) ;; *) [ "${TB_TEST_ECHEC:-}" = apres-installation ] && die "échec simulé (répétition) après l'installation";; esac
compose start; T_STOPPED=0
wait_health || die "production ne répond pas après l'installation (voir docker logs $CONTAINER)"
[ "$(version "$URL")" = "$VT" ] || die "version de la production après installation : $(version "$URL") (attendu $VT)"

# 6. contrôle : production = staging (toutes les tables métier), base intègre, page de connexion servie
copie "$TDB" "$W/production-apres.db" || die "lecture de la production après installation impossible"
emp comparer "$B/staging.db" "$W/production-apres.db" > "$J/production-apres.txt" || die "production différente du staging après installation (voir $J)"
[ "$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$URL/login")" = 200 ] || die "page de connexion de la production non servie"
APPLYING=0; DONE=1
(cd "$B" && sha256sum staging.db production-avant.db promue.db > SHA256SUMS); chmod 600 "$B"/*
( umask 077; emp empreinte "$W/production-apres.db" > "$B/production-empreinte.json" )   # chiffres financiers : dans la sauvegarde (600), pas dans le dépôt
log "TERMINÉ : production $VT = base du staging ($(head -1 "$J/production-apres.txt")). Chiffres : $B/production-empreinte.json"
log "sauvegarde : $B (production-avant.db = base d'origine, staging.db, promue.db ; SHA256SUMS). Le staging reste ARRÊTÉ."
log "retour arrière si nécessaire : $PROC_DIR/90-rollback.sh $CONF (base V9.0 d'origine) — il refusera, liste à l'appui, tant que les données promues sont là ;"
log "  ABANDONNER_CORRECTIONS=OUI seulement après export de ce qui a été saisi EN PRODUCTION depuis (les données promues restent dans $B/staging.db)"
