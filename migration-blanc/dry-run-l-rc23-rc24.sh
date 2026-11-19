#!/bin/bash
# Répétition L (rc23 → rc24, 2026-10-08) : la séquence prévue pour un déploiement de 9.2-rc24 sur le staging (correctifs techniques seulement :
# verrou partiel des saisies importées, adresses en \n, paramètres et mandats enregistrés sans changement non réécrits, audit de connexion borné ;
# déploiement soumis à un go de l'utilisateur), sur un faux staging jetable dans l'état du staging réel en rc23 le 2026-10-08 09:11 UTC.
# Aucune lecture de /opt : base = sauvegarde pre-rc23-20261008T091053Z (SHA vérifié ; celle que 40 a migrée en rc23 à 09:11), code rc23 =
# copie figée 9.2-rc23-50492d4 (staging.conf), code rc24 = copie figée REL24.
#   0. faux staging rc23 (secrets de test)        1. 10 → 20 → 30 → 40 → 50 (rc24)
#   2. contrôles rc24 : données métier identiques (outils/empreinte_metier.py + pages), brouillon n°1, export .xlsx, pages « Corriger » / « Ajouter »
#   3. retour arrière (rien d'écrit) : accepté → rc23, base = sauvegarde      4. redéploiement 10 → 50
#   5. parcours utilisateur : validation des 24 historiques, correction d'une ligne, ajout d'une ligne, export (CA = « Facturé »)
#   6. retour arrière après ces écritures : doit être refusé
# Jamais le staging réel ni la production. Dérivé de dry-run-j-rc24.sh (rc22 → rc23, même séquence).
# Usage : REL24=<copie figée rc24> RC24_IMAGE=<image> [PORT=<port>] migration-blanc/dry-run-l-rc23-rc24.sh   (port 8448, bac à sable migration-blanc/L-RC24, recréé)
set -uo pipefail
MB=$(cd "$(dirname "$0")" && pwd); W=$(cd $MB/.. && pwd); S=$MB/L-RC24; P=$W/procedure; PORT=${PORT:-8448}
ROOT=$S/opt/time-billing-v9-staging; DBF=$ROOT/data/timebilling.db
REL23=/root/time-billing-releases/9.2-rc23-50492d4; REL24=${REL24:?copie figée rc24}
RC23_IMAGE=tb-g4-cand:50492d4; RC24_IMAGE=${RC24_IMAGE:?image rc24}
PRE=/root/backups/time-billing-v9-staging/pre-rc23-20261008T091053Z
LIB=$W/tests/recette_fonctionnelle
step() { echo; echo "=== $*"; }
ok() { echo "OK    $*"; }; ko() { echo "ÉCHEC $*"; FAIL=1; }; FAIL=0
for R in $REL23 $REL24; do (cd $R && sha256sum -c --quiet SHA256SUMS) && ok "copie de publication $(basename $R) intacte" || { ko "copie $R altérée"; exit 1; }; done
grep -q '^VERSION="9.2-rc24"' $REL24/app/app.py || { echo "copie rc24 : VERSION inattendue"; exit 1; }
docker rm -f tbmb-lrc24 >/dev/null 2>&1; [ -d "$S" ] && { (cd $ROOT 2>/dev/null && docker compose -p tbmb-lrc24 down >/dev/null 2>&1); chmod -R u+w "${S:?}" 2>/dev/null; rm -rf "${S:?}"; }
mkdir -p $S/opt $S/backups $S/journal $ROOT/data; chmod 700 $S $S/backups

step "0. faux staging rc23 : code = copie figée 9.2-rc23-50492d4, base = $(basename $PRE) (SHA vérifié), secrets de test"
(cd $PRE && sha256sum -c --quiet SHA256SUMS) && ok "sauvegarde pre-rc23 intacte" || { ko "sauvegarde pre-rc23 altérée"; exit 1; }
cp -r $REL23/app $REL23/requirements.txt $REL23/requirements.lock $REL23/Dockerfile $REL23/.dockerignore $ROOT/; chmod -R u+w $ROOT
install -m 644 $P/docker-compose.staging.yml $ROOT/docker-compose.yml
cp $PRE/timebilling.db $DBF
PW=$(openssl rand -hex 12); echo -n "$PW" > $S/pw.txt; chmod 600 $S/pw.txt
HASH=$(docker run --rm --network none $RC23_IMAGE python -c "import sys;from werkzeug.security import generate_password_hash as g;print(g(sys.argv[1]))" "$PW")
( umask 077; printf "APP_USER=admin\nAPP_PASSWORD_HASH='%s'\nSECRET_KEY='%s'\nCOOKIE_SECURE=0\nTB_PORT=%s\nTB_CONTAINER=tbmb-lrc24\nENV_LABEL=RECETTE\n" "$HASH" "$(openssl rand -hex 32)" $PORT > $ROOT/.env )
cat > $S/sandbox.conf <<EOF
ROOT=$ROOT
PROJECT=tbmb-lrc24
CONTAINER=tbmb-lrc24
IMAGE=tbmb-lrc24-time-billing-v9-staging
URL=http://127.0.0.1:$PORT
BACKUP_BASE=$S/backups
SOURCE_APP=$REL24/app
SOURCE_REQ=$REL24/requirements.txt
RC_IMAGE=$RC24_IMAGE
COMPOSE_TEMPLATE=$P/docker-compose.staging.yml
EOF
chown -R 10001:10001 $ROOT/data; chmod 700 $ROOT/data; chmod 600 $DBF
(cd $ROOT && docker compose -p tbmb-lrc24 up -d --build --quiet-pull 2>&1 | tail -1)
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:$PORT/health >/dev/null && break; sleep 1; done
V0=$(curl -s http://127.0.0.1:$PORT/health); echo "santé : $V0"; grep -q '9.2-rc23' <<<"$V0" && ok "faux staging en rc23" || { ko "version d'origine ($V0)"; exit 1; }
HTTP() { python3 - "$PORT" "$S" "$DBF" "$@" || FAIL=1; }
# copie cohérente de la base du bac à sable (API de sauvegarde SQLite, service en marche) : comparée par outils/empreinte_metier.py
COPY() { python3 -c "import sqlite3,sys;s=sqlite3.connect(f'file:{sys.argv[1]}?mode=ro',uri=True);d=sqlite3.connect(sys.argv[2]);s.backup(d)" $DBF $1; }
METIER() { python3 -I $W/outils/empreinte_metier.py comparer "$1" "$2" > $S/cmp.txt; local r=$?; [ $r = 0 ] && ok "$3 — $(head -1 $S/cmp.txt)" || { ko "$3"; cat $S/cmp.txt; }; }
SNAP() { python3 - "$PORT" "$S" "$DBF" "$1" "$LIB" <<'PY'
import sys, re, html, json, hashlib
port, S, db, out, lib = sys.argv[1:6]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
snap = {'n_saisies': A.one('select count(*) from entries'), 'heures': A.one('select round(sum(hours),4) from entries'),
        'historiques_par_statut': A.q('select status,count(*) from historical_invoices group by status')}
pg = html.unescape(A.get('/issue/1')); snap['controles_brouillon_1'] = sorted(re.findall(r'data-check="(\d+)" data-status="(\w+)"', pg), key=lambda x: int(x[0]))
pos = html.unescape(A.get('/'))
snap['accueil_chiffres'] = hashlib.sha256(re.sub(r'\s+', ' ', ' '.join(re.findall(r'CHF[^<]{0,40}|\d[\d\s’\']*,\d\d', pos))).encode()).hexdigest()
json.dump(snap, open(out, 'w'), indent=1, default=str)
print(f"INFO  état : {snap['n_saisies']} saisies / {snap['heures']} h ; historiques {snap['historiques_par_statut']} ; brouillon n°1 en échec : {[k for k, v in snap['controles_brouillon_1'] if v == 'fail']}")
PY
}
SAME() { python3 - "$1" "$2" "$3" <<'PY'
import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])); diff = [k for k in a if a[k] != b.get(k)]
print(('OK    ' if not diff else 'ÉCHEC ') + sys.argv[3] + ('' if not diff else ' — différences : ' + ', '.join(diff))); sys.exit(1 if diff else 0)
PY
[ $? = 0 ] || FAIL=1; }
EXPORT() { python3 - "$PORT" "$S" "$DBF" "$1" "$LIB" <<'PY'
import sys
port, S, db, out, lib = sys.argv[1:6]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
s, h, b = A.req('/export/classeur.xlsx'); open(out, 'wb').write(b)
print(('OK    ' if s == 200 and b[:2] == b'PK' else 'ÉCHEC ') + f'export .xlsx téléchargé ({s}, {len(b)} octets)'); sys.exit(0 if s == 200 and b[:2] == b'PK' else 1)
PY
[ $? = 0 ] || FAIL=1; }
SHEETS() { docker run --rm --network none -v "$1:/x.xlsx:ro" $RC24_IMAGE python -c "
import openpyxl; wb = openpyxl.load_workbook('/x.xlsx'); print(' | '.join(wb.sheetnames))"; }
COPY $S/base-rc23.db; SNAP $S/etat-rc23.json
EXPORT $S/export-rc23.xlsx; SHEETS $S/export-rc23.xlsx > $S/onglets-rc23.txt

step "1. déploiement rc24 : 10 → 20 → 30 → 40 → 50 (comme le staging : .env conservé)"
deploy() {
  bash $P/10-preflight.sh $S/sandbox.conf || ko "10-preflight"
  bash $P/20-backup.sh $S/sandbox.conf || { ko "20-backup"; return 1; }
  bash $P/30-rehearse.sh $S/sandbox.conf || ko "30-rehearse"
  cp -p $ROOT/.env $ROOT/.env.rc24
  bash $P/40-deploy.sh $S/sandbox.conf || { ko "40-deploy"; return 1; }
  bash $P/50-verify.sh $S/sandbox.conf || ko "50-verify"
}
deploy || exit 1
grep -q "$(cd $REL24/app && find . -type f ! -path '*/__pycache__/*' ! -name '*.before-*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64)" $S/backups/pre-rc24-$(cat $S/backups/last-backup)/source-app.sha256 \
  && ok "empreinte du code noté par 20 = copie figée rc24" || ko "empreinte du code déployé"

step "2. contrôles rc24 : mêmes données métier que rc23, brouillon n°1, export, pages Corriger / Ajouter"
COPY $S/base-rc24.db; METIER $S/base-rc23.db $S/base-rc24.db "rc24 : toutes les tables métier identiques à rc23 (outils/empreinte_metier.py)"
SNAP $S/etat-rc24.json; SAME $S/etat-rc23.json $S/etat-rc24.json "rc24 : saisies, heures, historiques, contrôles du brouillon n°1 et chiffres de l'accueil identiques à rc23"
EXPORT $S/export-rc24.xlsx; SHEETS $S/export-rc24.xlsx > $S/onglets-rc24.txt
cmp -s $S/onglets-rc23.txt $S/onglets-rc24.txt && ok "export .xlsx : mêmes onglets qu'en rc23 ($(cat $S/onglets-rc24.txt | tr '|' '\n' | wc -l) onglets)" || ko "onglets de l'export différents"
HTTP "$LIB" <<'PY'
import sys
port, S, db, lib = sys.argv[1:5]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
hid = A.q("select min(id) from historical_invoices")[0][0]
s1, _, _ = A.req(f'/historique/{hid}/corriger'); s2, _, _ = A.req('/historique/ajouter'); pg = A.get('/historique')
c = s1 == 200 and s2 == 200 and 'Ajouter une facture historique manquante' in pg and f'/historique/{hid}/corriger' in pg
print(('OK    ' if c else 'ÉCHEC ') + f'pages « Corriger » ({s1}) et « Ajouter » ({s2}), liens sur le registre'); sys.exit(0 if c else 1)
PY

step "3. retour arrière (aucune donnée métier écrite depuis la sauvegarde) : accepté → rc23"
TS=$(cat $S/backups/last-backup)
bash $P/90-rollback.sh $S/sandbox.conf 2>&1 | tee $S/retour-1.log; [ ${PIPESTATUS[0]} = 0 ] && ok "90-rollback accepté" || ko "90-rollback"
grep -q "base = sauvegarde $TS (SHA-256 identique)" $S/retour-1.log && ok "base restaurée = sauvegarde d'avant déploiement (SHA-256 vérifié par 90-rollback)" || ko "SHA de la base restaurée non confirmé"
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc23' <<<"$H" && ok "version rc23 de retour" || ko "version après retour : $H"
COPY $S/base-retour.db; METIER $S/base-rc23.db $S/base-retour.db "après retour : toutes les tables métier identiques à rc23"
SNAP $S/etat-retour.json; SAME $S/etat-rc23.json $S/etat-retour.json "après retour : état rc23 identique (pages)"

step "4. redéploiement rc24 : 10 → 50"
deploy || exit 1
COPY $S/base-rc24-bis.db; METIER $S/base-rc23.db $S/base-rc24-bis.db "après redéploiement : tables métier identiques à rc23"

step "5. parcours utilisateur sur rc24 : validation des 24 historiques, correction d'une ligne, ajout d'une ligne, export"
HTTP "$LIB" <<'PY'
import sys
port, S, db, lib = sys.argv[1:5]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
ok = True
def say(c, m):
    global ok; ok = ok and bool(c); print(('OK    ' if c else 'ÉCHEC ') + m)
for (pid,) in A.q("select distinct project_id from historical_invoices where status='proposed'"): A.post(f'/historique/mandat/{pid}/valider', {})
r = A.q('select status,count(*) from historical_invoices group by status'); say(r == [('validated', 24)], f'24 historiques validées par la page : {r}')
# correction FICTIVE (bac à sable) : la ligne D2 SUIVI 2026!M15 (4 550 CHF) passe à 4 600 CHF ; ajout FICTIF de 100 CHF daté du 15.01.2026
h = A.q("select id,project_id,invoice_date,qty_days,amount_ht,invoice_ref from historical_invoices where source_sheet='SUIVI 2026' and source_cell='M15'")
say(len(h) == 1, f'ligne D2 SUIVI 2026!M15 trouvée : {h}')
hid, pid, d, q, a, ref = h[0]
A.post(f'/historique/{hid}/corriger', {'invoice_date': d, 'qty_days': repr(q), 'amount_ht': '4600', 'invoice_ref': ref or '', 'motif': 'répétition I : correction fictive'})
n = A.q("select status from historical_invoices where id=?", (hid,))[0][0]
c = A.q("select status,amount_ht,qty_days,source_file,source_cell from historical_invoices where id>? and source_cell='M15 (correction 1)'", (hid,))
say(n == 'rejected' and c == [('validated', 4600.0, q, 'saisie dans Time Billing', 'M15 (correction 1)')], f'correction : origine {n}, ligne corrigée {c}')
A.post('/historique/ajouter', {'project_id': str(pid), 'invoice_date': '2026-01-15', 'qty_days': '', 'amount_ht': '100', 'invoice_ref': '', 'motif': 'répétition I : ajout fictif'})
c = A.q("select status,amount_ht,source_sheet,source_cell from historical_invoices where source_sheet='ajout manuel'")
say(c == [('validated', 100.0, 'ajout manuel', 'n° 1')], f'ajout : {c}')
ev = [e for (e,) in A.q("select event from audit where event in ('historical_invoice_corrected','historical_invoice_added') order by id")]
say(ev == ['historical_invoice_corrected', 'historical_invoice_added'], f'journal : {ev}')
say(A.q("select count(*) from historical_invoices where status='validated'")[0][0] == 25, '25 lignes validées (24 − 1 remplacée + 1 corrigée + 1 ajoutée)')
sys.exit(0 if ok else 1)
PY
EXPORT $S/export-rc24-apres-parcours.xlsx
python3 - "$PORT" "$S" "$DBF" "$LIB" <<'PY' || FAIL=1
import sys, json
port, S, db, lib = sys.argv[1:5]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db)
d = json.loads(A.q("select detail from audit where event='gsheet_export_downloaded' order by id desc limit 1")[0][0]); s = d.get('suivi', {})
norm = lambda v: str(v).replace("'", '').replace(' ', '').replace(' ', '').replace('\xa0', '').replace(',', '.')
c = norm(s.get('2025')) in ('67236.00', '67236', '67236.0') and norm(s.get('2026')) in ('71123.50', '71123.5')
print(('OK    ' if c else 'ÉCHEC ') + f"CA des onglets SUIVI : 2025 67 236,00 inchangé ; 2026 70 973,50 + 50 (correction) + 100 (ajout) = 71 123,50 : {s}")
sys.exit(0 if c else 1)
PY

step "6. retour arrière après le parcours : doit être REFUSÉ"
COPY $S/avant-tentative.db
if bash $P/90-rollback.sh $S/sandbox.conf > $S/retour-2.log 2>&1; then cat $S/retour-2.log; ko "retour arrière ACCEPTÉ alors que des validations / corrections ont été écrites depuis la sauvegarde"
else tail -3 $S/retour-2.log; ok "retour arrière refusé (écritures depuis la sauvegarde)"; fi
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc24' <<<"$H" && ok "service rc24 toujours en marche" || ko "service après la tentative : $H"
COPY $S/apres-tentative.db; METIER $S/avant-tentative.db $S/apres-tentative.db "base inchangée par la tentative"
grep -q "historical_invoices" $S/retour-2.log && ok "motif du refus cite historical_invoices" || ko "motif du refus inattendu : $(grep ARRÊT $S/retour-2.log)"

step "7. nettoyage"
(cd $ROOT && docker compose -p tbmb-lrc24 down >/dev/null 2>&1); docker image ls --format '{{.Repository}}:{{.Tag}}' | grep '^tbmb-lrc24-time-billing-v9-staging' | xargs -r docker rmi >/dev/null 2>&1 && echo "images du bac à sable supprimées"
rm -f "${S:?}"/*.db; rm -rf "${S:?}"/opt/time-billing-v9-staging/data/backups
[ $FAIL = 0 ] && echo "RÉPÉTITION L : GO" || echo "RÉPÉTITION L : NO-GO"; exit $FAIL
