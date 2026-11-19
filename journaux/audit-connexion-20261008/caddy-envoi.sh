#!/bin/bash
# Un envoi légitime volumineux (sauvegarde JSON → /restore, aperçu seulement, rien n'est restauré) passe-t-il à travers le Caddy JETABLE avec
# les options du bloc ? Conteneur jetable sur une COPIE de base. Usage : caddy-envoi.sh IMAGE BASE_SOURCE.db "<options reverse_proxy>"
set -u
IMG=${1:?image}; SRC=${2:?base}; OPT=${3-}; NAME=tb-mesure-envoi; PORT=8474
T=$(mktemp -d /tmp/tb-caddy-envoi.XXXXXX); mkdir -p $T/data; chmod 777 $T/data; cp "$SRC" $T/data/timebilling.db; chmod 666 $T/data/timebilling.db
PW=$(head -c 18 /dev/urandom | base64 | tr -dc A-Za-z0-9)
docker run -d --name $NAME -p 127.0.0.1:$PORT:8000 -v $T/data:/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=0 \
  -e DB_PATH=/data/timebilling.db -e APP_PASSWORD="$PW" "$IMG" >/dev/null || exit 2
for i in $(seq 60); do curl -fs http://127.0.0.1:$PORT/health >/dev/null 2>&1 && break; sleep 1; done
printf '{\n\tadmin off\n\tauto_https off\n}\nhttp://127.0.0.1:8475 {\n\tencode zstd gzip\n\theader -Server\n\treverse_proxy 127.0.0.1:%s {\n\t\t%s\n\t}\n}\n' $PORT "$OPT" > $T/Caddyfile
XDG_DATA_HOME=$T XDG_CONFIG_HOME=$T HOME=$T caddy run --adapter caddyfile --config $T/Caddyfile > $T/caddy.log 2>&1 &
CP=$!; sleep 2
echo "options reverse_proxy : ${OPT:-(aucune)}"
python3 -I - "$PW" <<'PY'
import sys, re, uuid, hashlib, http.cookiejar, urllib.request, urllib.parse
pw = sys.argv[1]
for label, port in (("direct", 8474), ("via Caddy", 8475)):
    j = http.cookiejar.CookieJar(); o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
    o.open(f"http://127.0.0.1:{port}/login", data=urllib.parse.urlencode({"username": "admin", "password": pw}).encode())
    raw = o.open(f"http://127.0.0.1:{port}/backup").read()
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"backup\"; filename=\"s.json\"\r\nContent-Type: application/json\r\n\r\n").encode() + raw + f"\r\n--{b}--\r\n".encode()
    r = o.open(urllib.request.Request(f"http://127.0.0.1:{port}/restore", data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"}))
    page = r.read().decode(); sha = hashlib.sha256(raw).hexdigest()
    print(f"{label} : sauvegarde {len(raw)/1e6:.2f} Mo, envoi → {r.status} {r.url.split(':',2)[2]} ; empreinte reçue = envoyée : {sha[:16] in page}")
PY
kill $CP; wait $CP 2>/dev/null; docker rm -f $NAME >/dev/null; rm -rf $T
