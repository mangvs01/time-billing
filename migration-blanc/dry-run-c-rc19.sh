#!/bin/bash
# Répétition C (rc19) : COPIE du staging au schéma rc18 (2 247 saisies historiques réelles) sur laquelle de VRAIES factures sont émises sous
# rc18 (le staging réel n'en a aucune : sa reconstruction de l'annexe porte sur 0 ligne). Passage en rc19 par la procédure officielle
# (10 → 50 ; gunicorn à 2 processus : migration lancée deux fois en parallèle), contrôles, correction d'une saisie facturée, puis retour
# arrière : refusé tant que des corrections rc19 existent, effectué avec ABANDONNER_CORRECTIONS=OUI (base = sauvegarde, SHA identique ;
# PDF figés identiques). Secrets de test générés (aucun secret du staging copié). Jamais le staging réel ni la production.
# Usage : migration-blanc/dry-run-c-rc19.sh   (port 8419, bac à sable migration-blanc/C19, supprimé puis recréé)
set -uo pipefail
MB=$(cd "$(dirname "$0")" && pwd); W=$MB/..; S=$MB/C19; P=$W/procedure; PORT=8419; TAG=$(sed -n 's/^VERSION="9.2-\(.*\)"/\1/p' $W/app/app.py)
step() { echo; echo "=== $*"; }
ok() { echo "OK    $*"; }; ko() { echo "ÉCHEC $*"; FAIL=1; }; FAIL=0
[ "$TAG" = rc19 ] || { echo "code du dépôt = $TAG, rc19 attendu"; exit 1; }
docker rm -f tbmb-c19 >/dev/null 2>&1; [ -d "$S" ] && { (cd $S/opt/tb 2>/dev/null && docker compose -p tbmb-c19 down >/dev/null 2>&1); rm -rf "$S"; }
mkdir -p $S/opt $S/backups $S/pdf; chmod 700 $S $S/backups
step "0. bac à sable : arborescence staging rc18 (sans données ni secrets), base = copie du staging, secrets de test"
rsync -a --exclude data --exclude '.env*' --exclude '__pycache__' /opt/time-billing-v9-staging/ $S/opt/tb/
mkdir -p $S/opt/tb/data
python3 - /opt/time-billing-v9-staging/data/timebilling.db $S/opt/tb/data/timebilling.db <<'PY'
import sqlite3, sys
s = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
PY
PW=$(openssl rand -hex 12); echo -n "$PW" > $S/pw.txt; chmod 600 $S/pw.txt
HASH=$(docker run --rm --network none time-billing-v9-staging-time-billing-v9-staging:rc19 python -c "import sys;from werkzeug.security import generate_password_hash as g;print(g(sys.argv[1]))" "$PW")
( umask 077; printf "APP_USER=admin\nAPP_PASSWORD_HASH='%s'\nSECRET_KEY='%s'\nCOOKIE_SECURE=0\nTB_PORT=%s\nTB_CONTAINER=tbmb-c19\nENV_LABEL=RECETTE\n" "$HASH" "$(openssl rand -hex 32)" $PORT > $S/opt/tb/.env )
cat > $S/sandbox.conf <<EOF
ROOT=$S/opt/tb
PROJECT=tbmb-c19
CONTAINER=tbmb-c19
IMAGE=tbmb-c19-time-billing-v9-staging
URL=http://127.0.0.1:$PORT
BACKUP_BASE=$S/backups
SOURCE_APP=$W/app
SOURCE_REQ=$W/requirements.txt
RC_IMAGE=time-billing-v9-staging-time-billing-v9-staging:rc19
COMPOSE_TEMPLATE=$P/docker-compose.staging.yml
EOF
chown -R 10001:10001 $S/opt/tb/data; chmod 700 $S/opt/tb/data
(cd $S/opt/tb && docker compose -p tbmb-c19 up -d --build --quiet-pull 2>&1 | tail -1)
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:$PORT/health >/dev/null && break; sleep 1; done
V0=$(curl -s http://127.0.0.1:$PORT/health); echo "santé avant : $V0"; grep -q '9.2-rc18' <<<"$V0" && ok "version d'origine rc18" || ko "version d'origine ($V0)"
DBF=$S/opt/tb/data/timebilling.db
HTTP() { python3 - "$PORT" "$S" "$DBF" "$@" || FAIL=1; }
step "1. sous rc18 : deux factures émises sur NHAF 2026 (annexes cumulatives), une saisie manuelle corrigée (historique rc18)"
HTTP <<'PY'
import sys, re, json, hashlib
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db = sys.argv[1:4]; A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
pid = A.one("select id from projects where name='NHAF 2026'"); out = {}
for (f, t) in (('2025-01-01', '2026-06-30'), ('2026-07-01', '2026-09-30')):
    h = A.one('select coalesce(sum(hours),0) from entries where project_id=? and work_date between ? and ?', (pid, f, t)) or 0
    s, m = A.post('/invoice', {'project_id': pid, 'period_from': f, 'period_to': t, 'qty': str(round(max(h, 1) / 8, 6)), 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25'})
    iid = A.one('select max(id) from invoices'); pg = A.get(f'/issue/{iid}'); fm = {'from_confirm': '1', 'reliquat_treatment': 'reporte'}
    for k in ('expected_reliquat', 'expected_invoice_date', 'confirm_backdate'):
        x = re.search(rf'name="{k}"[^>]*value="([^"]+)"', pg)
        if x: fm[k] = x.group(1)
    s, m = A.post(f'/issue/{iid}', fm); st = A.q('select status,number from invoices where id=?', (iid,))[0]
    print(f'facture {st[1]} ({f} → {t}, {round(h, 4)} h) : {st[0]}', m[-1:] if st[0] != 'issued' else '')
    out[iid] = hashlib.sha256(A.req(f'/invoice/{iid}.pdf')[2]).hexdigest()
s, m = A.post('/entry', {'work_date': '2026-10-01', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '2', 'description': 'saisie manuelle C19'})
e = A.one("select id from entries where description='saisie manuelle C19'")
s, m = A.post(f'/entry/{e}/edit', {'work_date': '2026-10-01', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '2.5', 'description': 'saisie manuelle C19'})
print('correction rc18 :', A.one('select count(*) from entry_changes'), 'ligne(s) d historique')
print('liens d annexe :', A.one('select count(*) from invoice_annex_entries'), '; factures émises :', A.one("select count(*) from invoices where status='issued'"))
json.dump(out, open(f'{S}/pdf/sha-avant.json', 'w'))
PY
ANNEX0=$(python3 -c "import sqlite3;print(sqlite3.connect('file:$DBF?mode=ro',uri=True).execute('select count(*) from invoice_annex_entries').fetchone()[0])")
FK0=$(python3 -c "import sqlite3;print(len([r for r in sqlite3.connect('file:$DBF?mode=ro',uri=True).execute('pragma foreign_key_list(invoice_annex_entries)') if r[2]=='entries']))")
[ "$ANNEX0" -gt 100 ] && [ "$FK0" = 1 ] && ok "$ANNEX0 liens d'annexe sous rc18 (annexes cumulatives des 2 factures), clé étrangère vers les saisies présente" || ko "liens d'annexe sous rc18 : $ANNEX0, clé : $FK0"
step "2. procédure officielle rc19 : 10 → 20 → 30 → 40 → 50"
bash $P/10-preflight.sh $S/sandbox.conf || ko "10-preflight"
bash $P/20-backup.sh $S/sandbox.conf || { ko "20-backup"; exit 1; }
bash $P/30-rehearse.sh $S/sandbox.conf || ko "30-rehearse"
cp -p $S/opt/tb/.env $S/opt/tb/.env.$TAG
bash $P/40-deploy.sh $S/sandbox.conf || { ko "40-deploy"; exit 1; }
bash $P/50-verify.sh $S/sandbox.conf || ko "50-verify"
step "3. après migration : liens identiques, migration unique malgré 2 processus, PDF figés identiques, correction d'une saisie facturée"
HTTP <<'PY'
import sys, re, json, hashlib, sqlite3
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db = sys.argv[1:4]; A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
bad = []
def ok(n, c, d=''):
    print(('OK    ' if c else 'ÉCHEC ') + n + ('' if c else f' — {d}'))
    if not c: bad.append(n)
sha0 = json.load(open(f'{S}/pdf/sha-avant.json'))
ok('version rc19', '9.2-rc19' in A.get('/health'))
ok('reconstruction de l annexe journalisée UNE fois (2 processus au démarrage)', A.one("select count(*) from audit where event='schema_rc19_annex_rebuilt'") == 1, A.q("select detail from audit where event='schema_rc19_annex_rebuilt'"))
ok('clé étrangère annexe -> saisies retirée', not [r for r in A.q('pragma foreign_key_list(invoice_annex_entries)') if r[2] == 'entries'])
ok('PDF des factures émises servis identiques octet pour octet', all(hashlib.sha256(A.req(f'/invoice/{i}.pdf')[2]).hexdigest() == h for i, h in sha0.items()), sha0)
iid = max(int(i) for i in sha0); pid = A.one('select project_id from invoices where id=?', (iid,))
e = A.one("select e.id from entries e join invoices i on i.id=? where e.project_id=i.project_id and e.work_date between i.period_from and i.period_to order by e.id limit 1", (iid,))
r = A.q('select work_date,hours,description,start_time,end_time from entries where id=?', (e,))[0]
pg = A.get(f'/entry/{e}/edit'); rev = re.search(r'name="rev" value="([0-9a-f]+)"', pg).group(1); bid = re.search(r'name="billed_ids" value="([^"]*)"', pg).group(1)
ok('page de correction : saisie facturée, avertissement explicite', 'Saisie déjà facturée' in pg)
f = {'work_date': r[0], 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': str(round(r[1] + 0.5, 4)), 'description': r[2], 'reason': 'répétition C', 'confirm_billed': '1', 'rev': rev, 'billed_ids': bid}
s, m = A.post(f'/entry/{e}/edit', f); ok('saisie facturée corrigée (+0,5 h) avec motif et confirmation', any('modifiée' in x for x in m), m)
ok('écart post-facturation +0,50 h visible', '+0,50 h' in A.get(f'/invoice/{iid}/ecart') or '0,50 h' in A.get(f'/invoice/{iid}/ecart'))
ok('PDF toujours identiques après la correction', all(hashlib.sha256(A.req(f'/invoice/{i}.pdf')[2]).hexdigest() == h for i, h in sha0.items()))
sys.exit(1 if bad else 0)
PY
step "4. retour arrière : refusé tant qu'une correction rc19 existe (service toujours en marche)"
if bash $P/90-rollback.sh $S/sandbox.conf; then ko "retour arrière accepté alors qu'une correction rc19 existe"; else ok "retour arrière refusé (correction rc19 à préserver)"; fi
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc19' <<<"$H" && ok "service rc19 toujours en marche après le refus" || ko "service après refus : $H"
step "5. retour arrière forcé (ABANDONNER_CORRECTIONS=OUI) : base = sauvegarde d'avant déploiement, rc18, PDF identiques"
sleep 1   # le dossier de copie est horodaté à la seconde : 90-rollback refuse de réutiliser celui du refus précédent
ABANDONNER_CORRECTIONS=OUI bash $P/90-rollback.sh $S/sandbox.conf || ko "90-rollback forcé"
TS=$(cat $S/backups/last-backup)
[ "$(sha256sum < $DBF)" = "$(sha256sum < $S/backups/pre-$TAG-$TS/timebilling.db)" ] && ok "base = sauvegarde d'avant déploiement (SHA-256 identique)" || ko "base différente de la sauvegarde"
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc18' <<<"$H" && ok "version rc18 de retour" || ko "version après retour : $H"
KEEP=$(ls -d $S/backups/ecarte-$TS-retour-*/timebilling-avant-retour.db 2>/dev/null | tail -1)
python3 - "$KEEP" <<'PY' && ok "copie de la base rc19 conservée avant retour, correction rc19 incluse" || ko "copie avant retour"
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
assert c.execute("select count(*) from entry_changes where reason='répétition C'").fetchone()[0] == 1
PY
HTTP <<'PY'
import sys, json, hashlib
sys.path.insert(0, '/root/time-billing-v9-rc10-20261004/tests/recette_fonctionnelle'); from lib import App
port, S, db = sys.argv[1:4]; A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
sha0 = json.load(open(f'{S}/pdf/sha-avant.json'))
good = all(hashlib.sha256(A.req(f'/invoice/{i}.pdf')[2]).hexdigest() == h for i, h in sha0.items())
trig = A.one("select count(*) from sqlite_master where name='annexed_entry_no_update'") == 1
print(('OK    ' if good else 'ÉCHEC ') + 'PDF des factures émises identiques après retour rc18')
print(('OK    ' if trig else 'ÉCHEC ') + 'déclencheurs rc18 de retour')
sys.exit(0 if good and trig else 1)
PY
step "6. nettoyage"
(cd $S/opt/tb && docker compose -p tbmb-c19 down >/dev/null 2>&1); docker image ls --format '{{.Repository}}:{{.Tag}}' | grep '^tbmb-c19-time-billing-v9-staging' | xargs -r docker rmi >/dev/null 2>&1 && echo "images du bac à sable supprimées"
[ $FAIL = 0 ] && echo "RÉPÉTITION C : GO" || echo "RÉPÉTITION C : NO-GO"; exit $FAIL
