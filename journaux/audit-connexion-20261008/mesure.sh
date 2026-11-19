#!/bin/bash
# Mesure (conteneur JETABLE, base vide neuve, jamais le staging ni la production) : croissance de la table audit quand un robot
# insiste sur /login après le verrouillage (5 échecs / 15 min par IP). Usage : mesure.sh IMAGE [NOM] [PORT] [SECONDES]
set -u
IMG=${1:?image}; NAME=${2:-tb-mesure-login}; PORT=${3:-8471}; DUR=${4:-20}
T=$(mktemp -d /tmp/tb-mesure-login.XXXXXX); mkdir -p "$T/data"; chmod 777 "$T/data"
docker run -d --name "$NAME" -p 127.0.0.1:$PORT:8000 -v "$T/data":/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=0 \
  -e DB_PATH=/data/timebilling.db -e ENV_LABEL=RECETTE -e APP_PASSWORD="$(head -c 18 /dev/urandom | base64 | tr -dc A-Za-z0-9)" "$IMG" >/dev/null || { rm -rf "$T"; exit 2; }
for i in $(seq 60); do curl -fs http://127.0.0.1:$PORT/health >/dev/null 2>&1 && break; sleep 1; done
echo "image $IMG ; version $(curl -fs http://127.0.0.1:$PORT/health)"
python3 -I - "$PORT" "$DUR" <<'PY'
import sys, time, threading, urllib.request, urllib.parse, collections
port, dur = int(sys.argv[1]), float(sys.argv[2])
body = urllib.parse.urlencode({"username": "admin", "password": "mauvais-mot-de-passe"}).encode()
codes = collections.Counter(); lock = threading.Lock(); end = time.time() + dur
def w():
    while time.time() < end:
        try: r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/login", data=body), timeout=10); c = r.status
        except urllib.error.HTTPError as e: c = e.code
        except Exception as e: c = type(e).__name__
        with lock: codes[c] += 1
ts = [threading.Thread(target=w) for _ in range(16)]; [t.start() for t in ts]; [t.join() for t in ts]
n = sum(codes.values()); print(f"{n} requêtes en {dur:.0f} s ({n/dur:.0f}/s) : {dict(codes)}")
PY
sleep 1
python3 -I - "$T/data/timebilling.db" "$DUR" <<'PY'
import sqlite3, sys, os
p, dur = sys.argv[1], float(sys.argv[2]); c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
ev = c.execute("select event,count(*) from audit group by event order by 2 desc").fetchall(); print("audit :", ev)
n = sum(x for _, x in ev if _.startswith("login")); size = os.path.getsize(p) + (os.path.getsize(p + "-wal") if os.path.exists(p + "-wal") else 0)
print(f"base + wal : {size/1e6:.2f} Mo ; lignes login/s : {n/dur:.0f} ; extrapolation 24 h : {n/dur*86400/1e6:.1f} M lignes")
PY
docker rm -f "$NAME" >/dev/null; rm -rf "$T"
