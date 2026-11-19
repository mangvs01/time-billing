#!/bin/bash
# (Re)lance l'instance jetable tb-nuit-dev (:8300) : code du dépôt monté en lecture seule, copie des données de démo.
docker rm -f tb-nuit-dev >/dev/null 2>&1
docker run -d --name tb-nuit-dev -p 127.0.0.1:8300:8000 --user 10001:10001 \
  -e SECRET_KEY="$(head -c 32 /dev/urandom | base64)" -e COOKIE_SECURE=0 -e INVOICE_CHECK_WORDS= -e DB_PATH=/data/timebilling.db -e ENV_LABEL=NUIT \
  -e APP_PASSWORD="$(cat /root/demo-time-billing/mot-de-passe.txt)" \
  -v /tmp/nuit/dev-data:/data -v /root/time-billing-v9-rc10-20261004/app:/app/app:ro \
  time-billing-v9-staging-time-billing-v9-staging:latest \
  gunicorn -w 2 --worker-class gthread --threads 8 --worker-tmp-dir /dev/shm --timeout 60 -b 0.0.0.0:8000 app.app:APP >/dev/null
for i in $(seq 1 30); do c=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8300/login); [ "$c" = 200 ] && { echo "tb-nuit-dev prêt"; exit 0; }; sleep 0.5; done; echo "tb-nuit-dev KO"; docker logs --tail 20 tb-nuit-dev; exit 1
