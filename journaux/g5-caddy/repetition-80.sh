#!/bin/bash
# Répétition de procedure/80-site-caddy.sh sur un Caddyfile FICTIF (jamais /etc/caddy, aucun rechargement réel : CADDY_RELOAD=true, ATTENTE=0).
set -u
W=/root/time-billing-v9-rc10-20261004; T=$(mktemp -d /tmp/tb-rep80.XXXXXX); F=$T/Caddyfile; FAIL=0
ok() { echo "OK    $*"; }; ko() { echo "ÉCHEC $*"; FAIL=1; }
printf '{\n\temail admin@example.org\n}\n\nautre.example.org {\n\treverse_proxy 127.0.0.1:9999\n}\n' > $F; S0=$(sha256sum < $F)
run() { CADDYFILE=$F CADDY_RELOAD=true ATTENTE=0 XDG_DATA_HOME=$T XDG_CONFIG_HOME=$T $W/procedure/80-site-caddy.sh "$@" > $T/out 2>&1; }
run ajouter && grep -q "request_buffers 64KB" $F && ok "ajout : bloc présent avec request_buffers 64KB" || { cat $T/out; ko "ajout"; }
(cd $T && XDG_DATA_HOME=$T XDG_CONFIG_HOME=$T caddy validate --adapter caddyfile --config $F >/dev/null 2>&1) && ok "Caddyfile résultant valide" || ko "Caddyfile résultant invalide"
grep -q "autre.example.org" $F && ok "autre site conservé" || ko "autre site perdu"
run ajouter && ko "second ajout accepté" || ok "second ajout refusé"
run retirer && [ "$(sha256sum < $F)" = "$S0" ] && ok "retrait : Caddyfile d'origine à l'octet (SHA-256)" || { cat $T/out; ko "retrait"; }
CADDYFILE=$F CADDY_RELOAD=false ATTENTE=0 XDG_DATA_HOME=$T XDG_CONFIG_HOME=$T $W/procedure/80-site-caddy.sh ajouter > $T/out 2>&1 && ko "rechargement en échec accepté" || { [ "$(sha256sum < $F)" = "$S0" ] && ok "rechargement en échec : origine remise (SHA-256)" || ko "origine non remise"; }
rm -rf $T; [ $FAIL = 0 ] && echo "RÉPÉTITION 80 : GO" || echo "RÉPÉTITION 80 : NO-GO"; exit $FAIL
