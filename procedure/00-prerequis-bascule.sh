#!/bin/bash
# G5 (Decision Center billing-g5-bascule-production = PLAN_OK, 2026-10-08) : contrôle automatique des prérequis de la bascule de la production,
# à lancer avant la fenêtre et au début de la fenêtre. LECTURE SEULE : n'arrête rien, n'écrit rien (hors /tmp), ne lit RIEN de la production
# (ni base, ni dossier, ni /health : production vide et version vérifiées par 10 et 70 dans la fenêtre, avec CONFIRM_PROD).
# Bloquants : nom DNS (A = IP du serveur sur deux résolveurs publics, aucun AAAA vers un autre serveur) ; copie de publication intacte, désignée
# par les deux configurations avec la même image ; staging en marche dans cette version ; site Caddy candidat valide (caddy validate) ;
# décisions billing-g5-bascule-production et billing-g4-correction-historiques résolues ; place disque pour les sauvegardes.
# Informatif : état des factures historiques et des brouillons d'après la dernière sauvegarde du staging (pas de lecture de la base vivante).
# Usage : procedure/00-prerequis-bascule.sh procedure/prod.conf procedure/staging.conf
#   variables : NOM (billing.hudd-l.com), IP_ATTENDUE (147.93.55.171), CADDYFILE (/etc/caddy/Caddyfile), DECISIONS (/srv/decision-center/decisions.json)
# Code retour 0 = prérequis remplis (la date et l'heure restent celles écrites par l'utilisateur).
set -uo pipefail
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/lire-conf.sh" || : "${BASH_SOURCE[999]:?ARRÊT : lire-conf.sh introuvable ou en erreur}"      # rc25 : configurations lues comme des DONNÉES (jamais exécutées)
P_CONF=${1:?usage: $0 <configuration production> <configuration staging>}; S_CONF=${2:?usage: $0 <configuration production> <configuration staging>}
NOM=${NOM:-billing.hudd-l.com}; IP_ATTENDUE=${IP_ATTENDUE:-147.93.55.171}
CADDYFILE=${CADDYFILE:-/etc/caddy/Caddyfile}; DECISIONS=${DECISIONS:-/srv/decision-center/decisions.json}
PROC_DIR=$(cd "$(dirname "$0")" && pwd)
log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*"; }
FAIL=0; ok() { log "OK    $*"; }; ko() { log "MANQUE $*"; FAIL=1; }; info() { log "INFO  $*"; }
# configurations lues sans héritage l'une de l'autre, comme des données (lire-conf.sh : jamais exécutées ; sans le garde-fou CONFIRM_PROD de tb-common : rien n'est touché ici)
lire_conf "$P_CONF" P_ || : "${BASH_SOURCE[999]:?ARRÊT : configuration production refusée}"; lire_conf "$S_CONF" S_ || : "${BASH_SOURCE[999]:?ARRÊT : configuration staging refusée}"
P_BACKUP=${P_BACKUP_BASE-}; P_APP=${P_SOURCE_APP-}; P_IMAGE=${P_RC_IMAGE-}; S_BACKUP=${S_BACKUP_BASE-}; S_APP=${S_SOURCE_APP-}; S_IMAGE=${S_RC_IMAGE-}
[ -n "${P_ROOT-}" ] && [ -n "${S_ROOT-}" ] || { log "ARRÊT : configuration illisible"; exit 2; }

# 1. nom d'accès
for R in 1.1.1.1 8.8.8.8; do
  A=$(dig +short +time=3 +tries=2 @$R "$NOM" A | grep -E '^[0-9.]+$' | sort | tr '\n' ' '); A=${A% }
  [ "$A" = "$IP_ATTENDUE" ] && ok "DNS $NOM A = $A (résolveur $R)" || ko "DNS $NOM A = « ${A:-absent} » (résolveur $R), attendu $IP_ATTENDUE : enregistrement A à créer chez le registraire"
done
AAAA=$(dig +short +time=3 +tries=2 @1.1.1.1 "$NOM" AAAA | grep ':' | tr '\n' ' ')
[ -z "$AAAA" ] && ok "DNS $NOM : aucun AAAA (certificat obtenu en IPv4)" || ko "DNS $NOM AAAA = $AAAA : le serveur n'est pas configuré en IPv6 ici, retirer l'AAAA ou le vérifier"

# 2. code et images
[ "$P_APP" = "$S_APP" ] && ok "prod.conf et staging.conf désignent la même copie ($P_APP)" || ko "copies différentes : production $P_APP, staging $S_APP"
[ "$P_IMAGE" = "$S_IMAGE" ] && ok "même image de répétition ($P_IMAGE)" || ko "images différentes : production $P_IMAGE, staging $S_IMAGE"
REL=$(dirname "$P_APP")
(cd "$REL" && sha256sum -c --quiet SHA256SUMS >/dev/null 2>&1) && ok "copie de publication $(basename "$REL") intacte (SHA256SUMS)" || ko "copie de publication $REL altérée ou sans SHA256SUMS"
VERSION=$(sed -n 's/^VERSION="\(.*\)"/\1/p' "$P_APP/app.py" 2>/dev/null)
docker image inspect "$P_IMAGE" >/dev/null 2>&1 && ok "image $P_IMAGE présente" || ko "image $P_IMAGE absente (10-preflight la construirait depuis la copie)"
VS=$(curl -s -m 5 "$S_URL/health" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null)
[ -n "$VERSION" ] && [ "$VS" = "$VERSION" ] && ok "staging en marche en $VS = version de la copie" || ko "staging en « ${VS:-indisponible} », copie en « $VERSION » : déployer d'abord cette version sur le staging"

# 3. site Caddy candidat (le Caddyfile réel n'est pas modifié ici)
T=$(mktemp -d /tmp/tb-prerequis-XXXX); trap 'rm -rf "$T"' EXIT
if grep -qE "^[[:space:]]*$NOM[[:space:]]*\{" "$CADDYFILE" 2>/dev/null; then info "site $NOM déjà présent dans $CADDYFILE"; cp "$CADDYFILE" "$T/Caddyfile"
else cp "$CADDYFILE" "$T/Caddyfile" 2>/dev/null && NOM="$NOM" bash "$PROC_DIR/80-site-caddy.sh" bloc >> "$T/Caddyfile"; fi
(cd "$(dirname "$CADDYFILE")" && caddy validate --adapter caddyfile --config "$T/Caddyfile" >"$T/validate.log" 2>&1) \
  && ok "Caddyfile candidat (site $NOM → 127.0.0.1:8091) valide" || { ko "Caddyfile candidat invalide :"; tail -3 "$T/validate.log"; }

# 4. décisions de l'utilisateur (Decision Center, lecture seule)
python3 -I - "$DECISIONS" > "$T/dec.txt" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); items = d if isinstance(d, list) else d.get('decisions', d)
items = list(items.values()) if isinstance(items, dict) else items
by = {x.get('id'): x for x in items if isinstance(x, dict)}
for i, need in (('billing-g5-bascule-production', 'PLAN_OK'), ('billing-g4-correction-historiques', None)):
    x = by.get(i, {}); st, dec = x.get('status'), x.get('decision')
    good = st == 'resolved' and (need is None or dec == need)
    print(('OK' if good else 'KO') + f'|{i} : statut {st}, décision {dec}')
PY
while IFS='|' read -r r m; do [ "$r" = OK ] && ok "$m" || ko "$m"; done < "$T/dec.txt"
[ -s "$T/dec.txt" ] || ko "Decision Center illisible ($DECISIONS)"

# 5. place disque (sauvegardes de la production et copie promue)
for D in "$P_BACKUP" "$S_BACKUP"; do E=$D; while [ ! -d "$E" ]; do E=$(dirname "$E"); done; L=$(df -Pm "$E" | awk 'NR==2{print $4}')
  [ "${L:-0}" -ge 2048 ] && ok "place libre $D : ${L} Mo" || ko "place libre $D : ${L:-?} Mo (< 2 Go)"; done

# 6. informatif : recette du staging d'après sa DERNIÈRE sauvegarde (la base vivante n'est pas lue)
LAST=$(ls -td "$S_BACKUP"/pre-*/ "$S_BACKUP"/quotidiennes/ 2>/dev/null | head -1)
DB=$( [ -n "$LAST" ] && ls -t "$LAST"*.db 2>/dev/null | head -1 )
if [ -n "$DB" ]; then python3 -I - "$DB" <<'PY' | while read -r l; do info "$l"; done
import sqlite3, sys, os, datetime
c = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True)
t = datetime.datetime.fromtimestamp(os.path.getmtime(sys.argv[1]), datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
h = dict(c.execute('select status, count(*) from historical_invoices group by status').fetchall())
b = c.execute("select count(*) from invoices where status='draft'").fetchone()[0]
print(f'dernière sauvegarde du staging ({os.path.basename(os.path.dirname(sys.argv[1]))} ; base modifiée pour la dernière fois le {t}) : factures historiques {h} ; brouillons {b}')
if h.get('proposed'): print(f"recette : {h['proposed']} facture(s) historique(s) encore « à valider » à cette date")
PY
else info "aucune sauvegarde du staging lisible dans $S_BACKUP"; fi

[ $FAIL = 0 ] && { log "PRÉREQUIS REMPLIS — bascule possible à la date et l'heure écrites par l'utilisateur (G5)"; exit 0; }
log "PRÉREQUIS NON REMPLIS — aucune bascule"; exit 1
