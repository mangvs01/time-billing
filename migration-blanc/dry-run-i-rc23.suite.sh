step "2. contrôles rc23 : mêmes données métier que rc22, brouillon n°1, export, pages Corriger / Ajouter"
COPY $S/base-rc23.db; METIER $S/base-rc22.db $S/base-rc23.db "rc23 : toutes les tables métier identiques à rc22 (outils/empreinte_metier.py)"
SNAP $S/etat-rc23.json; SAME $S/etat-rc22.json $S/etat-rc23.json "rc23 : saisies, heures, historiques, contrôles du brouillon n°1 et chiffres de l'accueil identiques à rc22"
EXPORT $S/export-rc23.xlsx; SHEETS $S/export-rc23.xlsx > $S/onglets-rc23.txt
cmp -s $S/onglets-rc22.txt $S/onglets-rc23.txt && ok "export .xlsx : mêmes onglets qu'en rc22 ($(cat $S/onglets-rc23.txt | tr '|' '\n' | wc -l) onglets)" || ko "onglets de l'export différents"
HTTP "$LIB" <<'PY'
import sys
port, S, db, lib = sys.argv[1:5]; sys.path.insert(0, lib); from lib import App
A = App(port, f'{S}/pw.txt', db); assert A.login(), 'connexion'
hid = A.q("select min(id) from historical_invoices")[0][0]
s1, _, _ = A.req(f'/historique/{hid}/corriger'); s2, _, _ = A.req('/historique/ajouter'); pg = A.get('/historique')
c = s1 == 200 and s2 == 200 and 'Ajouter une facture historique manquante' in pg and f'/historique/{hid}/corriger' in pg
print(('OK    ' if c else 'ÉCHEC ') + f'pages « Corriger » ({s1}) et « Ajouter » ({s2}), liens sur le registre'); sys.exit(0 if c else 1)
PY

step "3. retour arrière (aucune donnée métier écrite depuis la sauvegarde) : accepté → rc22"
TS=$(cat $S/backups/last-backup)
bash $P/90-rollback.sh $S/sandbox.conf 2>&1 | tee $S/retour-1.log; [ ${PIPESTATUS[0]} = 0 ] && ok "90-rollback accepté" || ko "90-rollback"
grep -q "base = sauvegarde $TS (SHA-256 identique)" $S/retour-1.log && ok "base restaurée = sauvegarde d'avant déploiement (SHA-256 vérifié par 90-rollback)" || ko "SHA de la base restaurée non confirmé"
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc22' <<<"$H" && ok "version rc22 de retour" || ko "version après retour : $H"
COPY $S/base-retour.db; METIER $S/base-rc22.db $S/base-retour.db "après retour : toutes les tables métier identiques à rc22"
SNAP $S/etat-retour.json; SAME $S/etat-rc22.json $S/etat-retour.json "après retour : état rc22 identique (pages)"

step "4. redéploiement rc23 : 10 → 50"
deploy || exit 1
COPY $S/base-rc23-bis.db; METIER $S/base-rc22.db $S/base-rc23-bis.db "après redéploiement : tables métier identiques à rc22"

step "5. parcours utilisateur sur rc23 : validation des 24 historiques, correction d'une ligne, ajout d'une ligne, export"
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
EXPORT $S/export-rc23-apres-parcours.xlsx
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
H=$(curl -s http://127.0.0.1:$PORT/health); grep -q '9.2-rc23' <<<"$H" && ok "service rc23 toujours en marche" || ko "service après la tentative : $H"
COPY $S/apres-tentative.db; METIER $S/avant-tentative.db $S/apres-tentative.db "base inchangée par la tentative"
grep -q "historical_invoices" $S/retour-2.log && ok "motif du refus cite historical_invoices" || ko "motif du refus inattendu : $(grep ARRÊT $S/retour-2.log)"

step "7. nettoyage"
(cd $ROOT && docker compose -p tbmb-irc23 down >/dev/null 2>&1); docker image ls --format '{{.Repository}}:{{.Tag}}' | grep '^tbmb-irc23-time-billing-v9-staging' | xargs -r docker rmi >/dev/null 2>&1 && echo "images du bac à sable supprimées"
rm -f "${S:?}"/*.db; rm -rf "${S:?}"/opt/time-billing-v9-staging/data/backups
[ $FAIL = 0 ] && echo "RÉPÉTITION I : GO" || echo "RÉPÉTITION I : NO-GO"; exit $FAIL
