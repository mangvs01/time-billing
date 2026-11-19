#!/bin/bash
# Usage: test_https_proxy.sh  — RC13: l'application derrière un reverse proxy HTTPS JETABLE (Caddy local, certificat interne, ports 8231/8443,
# admin off, stockage dans un dossier temporaire). N'touche NI au Caddy du serveur NI au staging NI à la production. Données fictives.
set -u
W=/root/time-billing-v9-rc10-20261004; T=$(mktemp -d /tmp/claude-0/-root/bc1e5850-4039-4def-b7dc-79de6ca9fdb6/scratchpad/https.XXXX); N=tb-rc13-https; AP=8231; SP=8443; F=0
ok(){ echo "OK    $1"; }; ko(){ echo "ÉCHEC $1"; F=$((F+1)); }
IMG=time-billing-v9-rc10-test:latest bash $W/journaux/fresh_container.sh $N $AP $T >/dev/null
docker rm -f $N >/dev/null 2>&1; PW=$(cat $T/pw.txt)
docker run -d --name $N -p 127.0.0.1:$AP:8000 -v $W/app:/app/app:ro -v $T/data:/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=1 -e TRUST_PROXY=1 -e DB_PATH=/data/timebilling.db -e APP_PASSWORD=$PW time-billing-v9-rc10-test:latest >/dev/null
for i in $(seq 1 20); do curl -sf http://127.0.0.1:$AP/health >/dev/null && break; sleep 1; done
cat > $T/Caddyfile <<CF
{
	admin off
	auto_https disable_redirects
	local_certs
	storage file_system $T/caddy-data
}
https://localhost:$SP {
	tls internal
	encode gzip
	header {
		Strict-Transport-Security "max-age=31536000"
		-Server
	}
	reverse_proxy 127.0.0.1:$AP
}
CF
caddy validate --config $T/Caddyfile >/dev/null 2>&1 && ok "Caddyfile valide" || ko "Caddyfile invalide"
XDG_DATA_HOME=$T/xdg XDG_CONFIG_HOME=$T/xdgc caddy run --config $T/Caddyfile >$T/caddy.log 2>&1 &
CP=$!; sleep 4
U=https://localhost:$SP; J=$T/jar; B="curl -sk --resolve localhost:$SP:127.0.0.1 -b $J -c $J"
H=$($B -D - -o /dev/null $U/login); echo "$H" | grep -qi "^HTTP/.* 200" && ok "login servi en HTTPS" || ko "login HTTPS"
R=$($B -D - -o /dev/null -e $U/login -H "Origin: $U" -d "username=admin&password=$PW" $U/login)
echo "$R" | grep -i "^set-cookie" | grep -qi "secure" && ok "cookie de session Secure" || ko "cookie sans Secure: $(echo "$R"|grep -i set-cookie|sed 's/=.*//')"
echo "$R" | grep -i "^set-cookie" | grep -qi "httponly" && ok "cookie HttpOnly" || ko "cookie sans HttpOnly"
echo "$R" | grep -qi "^strict-transport-security" && ok "HSTS présent" || ko "HSTS absent"
C=$($B -o /dev/null -w "%{http_code}" $U/); [ "$C" = 200 ] && ok "page protégée accessible avec la session (HTTPS)" || ko "page protégée: $C"
# l'origine du navigateur (https://localhost:8443) doit être acceptée derrière le proxy ; une origine étrangère refusée
C=$($B -o /dev/null -w "%{http_code}" -H "Origin: $U" -d "reason=x" $U/logout); [ "$C" != 403 ] && [ "$C" != 000 ] && ok "POST même origine accepté derrière le proxy ($C)" || ko "POST même origine refusé ou injoignable ($C)"
C=$($B -o /dev/null -w "%{http_code}" -H "Origin: https://evil.example" -d "reason=x" $U/project); [ "$C" = 403 ] && ok "POST origine étrangère refusé (403)" || ko "POST origine étrangère: $C"
C=$($B -o /dev/null -w "%{http_code}" $U/health); [ "$C" = 200 ] && ok "/health via le proxy" || ko "/health: $C"
kill $CP 2>/dev/null; wait $CP 2>/dev/null; docker rm -f $N >/dev/null 2>&1
echo "échecs: $F"; exit $F
