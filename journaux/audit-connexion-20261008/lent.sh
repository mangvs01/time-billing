#!/bin/bash
# Mesure (conteneur JETABLE, base vide) : N connexions « lentes » (POST /login, corps envoyé 1 octet / 5 s) occupent-elles les fils de gunicorn ?
# Usage : [CHEMIN=/login] [CL=100000] [BURST=1] [CIBLE=<port déjà servi, sans conteneur>] lent.sh IMAGE [N] [PORT]
set -u
IMG=${1:?image}; N=${2:-24}; PORT=${3:-8472}; NAME=tb-mesure-lent; CHEMIN=${CHEMIN:-/login}; CL=${CL:-100000}; BURST=${BURST:-1}; CIBLE=${CIBLE:-$PORT}
T=$(mktemp -d /tmp/tb-mesure-lent.XXXXXX); mkdir -p "$T/data"; chmod 777 "$T/data"
docker run -d --name $NAME -p 127.0.0.1:$PORT:8000 -v "$T/data":/data -e SECRET_KEY=$(head -c32 /dev/urandom | xxd -p -c64) -e COOKIE_SECURE=0 \
  -e DB_PATH=/data/timebilling.db -e APP_PASSWORD="$(head -c 18 /dev/urandom | base64 | tr -dc A-Za-z0-9)" "$IMG" >/dev/null || exit 2
for i in $(seq 60); do curl -fs http://127.0.0.1:$PORT/health >/dev/null 2>&1 && break; sleep 1; done
python3 -I - $CIBLE $N "$CHEMIN" $CL $BURST <<'PY'
import socket, sys, time, threading, urllib.request
port, n, path, cl, burst = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
def health():
    t = time.time()
    try: urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=20).read(); return f"{(time.time()-t)*1000:.0f} ms"
    except Exception as e: return f"ÉCHEC après {time.time()-t:.1f} s ({type(e).__name__})"
print(f"cible :{port} {path} Content-Length {cl}, {burst} octet(s) d emblée puis 1 octet / 5 s") ; print("avant :", health())
socks = []
for _ in range(n):
    s = socket.create_connection(("127.0.0.1", port)); s.sendall(f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: {cl}\r\n\r\n".encode() + b"u" * burst); socks.append(s)
stop = False
def drip():
    while not stop:
        for s in socks:
            try: s.sendall(b"a")
            except OSError: pass
        time.sleep(5)
threading.Thread(target=drip, daemon=True).start()
time.sleep(3)
for k in range(3): print(f"pendant ({n} connexions lentes) :", health()); time.sleep(2)
stop = True; [s.close() for s in socks]; time.sleep(2); print("après :", health())
PY
docker rm -f $NAME >/dev/null; rm -rf "$T"
