#!/bin/bash
# G5 (Decision Center billing-g5-bascule-production = PLAN_OK, nom billing.hudd-l.com) : accès HTTPS à la production par Caddy.
# Le bloc est délimité par deux marqueurs : « retirer » enlève exactement ce qu'« ajouter » a mis (Caddyfile d'origine, SHA-256 identique).
# Usage : procedure/80-site-caddy.sh bloc|ajouter|retirer
#   bloc     : affiche le bloc (rien n'est modifié ; utilisé par 00-prerequis-bascule.sh)
#   ajouter  : sauvegarde du Caddyfile → ajout du bloc → caddy validate → rechargement (sans coupure des autres sites) → attente du certificat
#              et de la page de connexion en HTTPS. Validation ou rechargement en échec : Caddyfile d'origine remis et rechargé.
#   retirer  : retour arrière (après 90-rollback.sh ou si le site doit être fermé) : bloc retiré, validé, rechargé.
#   Caddyfile réel : CONFIRM_PROD=OUI-<AAAAMMJJ> exigé (comme pour toute la procédure de production).
#   variables : NOM (billing.hudd-l.com), CIBLE (127.0.0.1:8091), CADDYFILE (/etc/caddy/Caddyfile), CADDY_RELOAD (systemctl reload caddy),
#               ATTENTE (120 s ; 0 = ne pas attendre le HTTPS, bac à sable)
# request_buffers 64KB (2026-10-08) : Caddy lit jusqu'à 64 Ko du corps d'une requête AVANT de la transmettre. Sans lui, 16 connexions envoyant
#   un corps au compte-gouttes occupaient les 16 fils du serveur (2 × 8) : application indisponible (mesuré : journaux/audit-connexion-20261008/).
#   Les corps plus gros (imports, restauration) passent comme avant ; /login refuse dès l'en-tête tout corps > 16 Ko (application, rc24).
set -euo pipefail
ACTION=${1:?usage: $0 bloc|ajouter|retirer}
NOM=${NOM:-billing.hudd-l.com}; CIBLE=${CIBLE:-127.0.0.1:8091}; CADDYFILE=${CADDYFILE:-/etc/caddy/Caddyfile}
CADDY_RELOAD=${CADDY_RELOAD:-systemctl reload caddy}; ATTENTE=${ATTENTE:-120}
DEBUT="# >>> time-billing $NOM (procedure/80-site-caddy.sh) — retirer avec : 80-site-caddy.sh retirer"
FIN="# <<< time-billing $NOM"
log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "ARRÊT : $*"; exit 1; }
bloc() { cat <<EOF

$DEBUT
$NOM {
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000"
		-Server
	}
	reverse_proxy $CIBLE {
		request_buffers 64KB
	}
}
$FIN
EOF
}
[ "$ACTION" = bloc ] && { bloc; exit 0; }
[ "$ACTION" = ajouter ] || [ "$ACTION" = retirer ] || die "action inconnue : $ACTION"
[ -f "$CADDYFILE" ] || die "$CADDYFILE absent"
if [ "$CADDYFILE" = /etc/caddy/Caddyfile ] && [ "${CONFIRM_PROD:-}" != "OUI-$(date -u +%Y%m%d)" ]; then
  die "Caddyfile réel : exporter CONFIRM_PROD=OUI-$(date -u +%Y%m%d) uniquement après accord explicite (G5, date et heure de l'utilisateur)"; fi
present() { grep -qF "$DEBUT" "$CADDYFILE"; }
valide() { (cd "$(dirname "$CADDYFILE")" && caddy validate --adapter caddyfile --config "$1" >/dev/null 2>"$1.validate.log") || { tail -5 "$1.validate.log" >&2; return 1; }; }
TS=$(date -u +%Y%m%dT%H%M%SZ); SAUV="$CADDYFILE.bak-$TS-avant-80-$ACTION"
CAND=$(mktemp "$(dirname "$CADDYFILE")/.Caddyfile-80-XXXX"); trap 'rm -f "$CAND" "$CAND.validate.log"' EXIT
if [ "$ACTION" = ajouter ]; then
  present && die "le bloc $NOM est déjà présent dans $CADDYFILE : rien n'est fait"
  grep -qE "^[[:space:]]*$NOM[[:space:]]*\{" "$CADDYFILE" && die "un site $NOM non géré par ce script existe déjà dans $CADDYFILE : rien n'est fait"
  { cat "$CADDYFILE"; bloc; } > "$CAND"
else
  present || die "aucun bloc $NOM ajouté par ce script dans $CADDYFILE : rien n'est fait"
  # le bloc et la ligne vide qui le précède (ajoutée par « ajouter »)
  python3 -I - "$CADDYFILE" "$CAND" "$DEBUT" "$FIN" <<'PY'
import sys
src, dst, debut, fin = sys.argv[1:5]; lines = open(src).read().split('\n')
i = lines.index(debut); j = lines.index(fin, i)
if i > 0 and lines[i - 1] == '': i -= 1
open(dst, 'w').write('\n'.join(lines[:i] + lines[j + 1:]))
PY
fi
valide "$CAND" || die "Caddyfile candidat invalide : $CADDYFILE inchangé"
cp -p "$CADDYFILE" "$SAUV"; log "Caddyfile sauvegardé : $SAUV (sha $(sha256sum "$SAUV" | cut -c1-12))"
cat "$CAND" > "$CADDYFILE"     # même fichier (droits, propriétaire) : contenu remplacé
if ! sh -c "$CADDY_RELOAD"; then
  cat "$SAUV" > "$CADDYFILE"; sh -c "$CADDY_RELOAD" || true
  die "rechargement de Caddy en échec : Caddyfile d'origine remis (sha $(sha256sum "$CADDYFILE" | cut -c1-12)) et rechargé"
fi
log "Caddy rechargé : site $NOM $( [ "$ACTION" = ajouter ] && echo "ajouté (→ $CIBLE)" || echo retiré) ; Caddyfile sha $(sha256sum "$CADDYFILE" | cut -c1-12)"
[ "$ACTION" = ajouter ] && [ "$ATTENTE" -gt 0 ] || exit 0
for _ in $(seq 1 "$ATTENTE"); do
  C=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "https://$NOM/login" || true); [ "$C" = 200 ] && break; sleep 1; done
[ "$C" = 200 ] && log "https://$NOM/login : 200 (certificat valide)" \
  || { log "https://$NOM/login : « $C » après ${ATTENTE} s — vérifier le DNS et journalctl -u caddy (le site reste ajouté ; retour : $0 retirer)"; exit 1; }
