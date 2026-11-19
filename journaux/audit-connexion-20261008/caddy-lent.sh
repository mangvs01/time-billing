#!/bin/bash
# Mesure à travers un Caddy JETABLE (binaire de l'hôte, processus séparé, port local, http, admin désactivée, données dans /tmp ;
# le service Caddy partagé et /etc/caddy ne sont jamais touchés). Usage : caddy-lent.sh IMAGE "<options reverse_proxy>" [N] [CHEMIN] [CL]
set -u
IMG=${1:?image}; OPT=${2-}; N=${3:-24}; CH=${4:-/login}; CL=${5:-100000}; D=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d /tmp/tb-caddy-lent.XXXXXX)
cat > $T/Caddyfile <<CF
{
	admin off
	auto_https off
}
http://127.0.0.1:8473 {
	encode zstd gzip
	header -Server
	reverse_proxy 127.0.0.1:8472 {
		$OPT
	}
}
CF
XDG_DATA_HOME=$T XDG_CONFIG_HOME=$T HOME=$T caddy run --adapter caddyfile --config $T/Caddyfile > $T/caddy.log 2>&1 &
CP=$!; sleep 2; kill -0 $CP 2>/dev/null || { cat $T/caddy.log; exit 2; }
echo "options reverse_proxy : ${OPT:-(aucune : bloc actuel de 80-site-caddy.sh)}"
BURST=${BURST:-1} CHEMIN=$CH CL=$CL CIBLE=8473 $D/lent.sh "$IMG" $N 8472
kill $CP; wait $CP 2>/dev/null; rm -rf $T
