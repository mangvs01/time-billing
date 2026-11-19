#!/bin/bash
# Tests de mutation RC10 : chaque mutation casse volontairement une règle sur une COPIE du code ; la suite DOIT échouer.
W=/root/time-billing-v9-rc10-20261004; M=${MUT_DIR:-$W/recette/mut}; rm -rf $M; mkdir -p $M
n=0; killed=0
mut() { # nom | fichier | python-expression de remplacement (old, new) | modules de test
  local name=$1 file=$2 old=$3 new=$4 mods=$5
  if [ -n "${ONLY:-}" ] && ! [[ "$name" =~ $ONLY ]]; then return; fi
  n=$((n+1)); rm -rf $M/app; cp -r $W/app $M/app
  python3 - "$M/app/$file" "$old" "$new" <<'PY' || { echo "MUTATION $name : motif introuvable (mutation invalide)"; return; }
import sys
p,old,new=sys.argv[1:4]; s=open(p,encoding='utf8').read()
if old not in s: raise SystemExit(1)
open(p,'w',encoding='utf8').write(s.replace(old,new,1))
PY
  out=$(APP_DIR=$M/app IMG=time-billing-v9-rc10-test:latest $W/journaux/run_unit.sh $mods 2>&1 | tail -3)
  if echo "$out" | grep -q "^FAILED"; then killed=$((killed+1)); echo "TUÉE      $name"; else echo "SURVIVANTE $name"; fi
}
mut "M1 verrou annexe ignoré"            app.py 'if e["annex_number"]: return' 'if False: return' tests.test_rc10
mut "M2 verrou import ignoré"            app.py 'if e["import_batch_id"] or (e["source"] or "manual")!="manual": return' 'if False: return' tests.test_rc10
mut "M3 verrou mandat clôturé ignoré"    app.py 'if not e["project_active"]: return' 'if False: return' tests.test_rc10
mut "M4 historique de correction omis"   app.py 'c.execute("INSERT INTO entry_changes(entry_id,action,before_json,after_json,changed_at) VALUES(?,?,?,?,?)",(eid,"update",before,after,rules.utc_now_iso()))' 'pass' tests.test_rc10
mut "M5 copie de suppression omise"      app.py 'c.execute("INSERT INTO entry_changes(entry_id,action,before_json,after_json,changed_at) VALUES(?,?,?,?,?)",(eid,"delete",entry_json(e),None,rules.utc_now_iso()))' 'pass' tests.test_rc10
mut "M6 NaN accepté"                     app.py 'if not math.isfinite(h): raise ValueError("durée invalide (nombre d'"'"'heures attendu, ex. 4,25 pour 4 h 15)")' 'pass' tests.test_rc10
mut "M7 plafond 24 h supprimé"           app.py 'if h>24: raise ValueError("durée supérieure à 24 h pour une seule prestation")' 'pass' tests.test_rc10
mut "M8 redirection ouverte (return_to)" app.py 'ok=(v.startswith("/entries") or v.startswith("/?tab="))' 'ok=True or (v.startswith("/entries") or v.startswith("/?tab="))' tests.test_rc10 tests.test_rc10_security
mut "M9 échappement LIKE supprimé"       app.py 'like="%"+q.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"' 'like="%"+q+"%"' tests.test_rc10
mut "M10 neutralisation CSV retirée"     app.py 'return "'"'"'"+v if v[:1] in ("=","+","-","@","\t","\r") else v' 'return v' tests.test_rc10
mut "M11 restauration : comparaison complète retirée" restore_service.py 'blocking += immutable_diffs(conn, data)' 'pass' tests.test_rc10_security
mut "M12 session non révocable"          app.py 'if not r: return False' 'pass' tests.test_rc10_security
mut "M13 durée absolue de session retirée" app.py 'if r["created_at"]<(rules.utc_now()-timedelta(hours=SESSION_MAX_HOURS)).isoformat(timespec="seconds"):' 'if False:' tests.test_rc10_security
mut "M14 limitation par /64 retirée"     security.py 'if a.version == 6:' 'if False:' tests.test_rc10_security
mut "M15 contrôle Origin supprimé"       security.py 'return origin == "null" or origin.rstrip("/") != request.host_url.rstrip("/")' 'return False' tests.test_rc10_security
mut "M16 HSTS toujours absent"           security.py 'if secure: response.headers.setdefault("Strict-Transport-Security"' 'if False: response.headers.setdefault("Strict-Transport-Security"' tests.test_rc10_security
mut "M17 bornes mandat retirées"         app.py 'if not (v["rate"]<=1e6' 'if False and (v["rate"]<=1e6' tests.test_rc10_security
mut "M24 quantité de brouillon non bornée" app.py 'qty=num_field(form.get("qty"),"quantité",0.0,MAX_DAYS*(24 if unit=="hour" else 1),lo_open=True)' 'qty=float(form.get("qty") or 0)' tests.test_rc10_numbers
mut "M25 TVA de brouillon non bornée"     app.py 'v["vat"]=num_field(request.form.get("vat"),"taux de TVA",0.0,100.0,default=float(i["vat"]))' 'v["vat"]=float(request.form.get("vat") or i["vat"])' tests.test_rc10_numbers
mut "M26 montant crédit non borné"        app.py ' if abs(d)>Decimal(str(MAX_MONEY)): raise ValueError(f"{label} hors limites (1 000 000 000 au maximum)")' ' pass' tests.test_rc10_numbers
mut "M18 contrôle de pixels du logo retiré" app.py 'or im.width*im.height>4_000_000: raise ValueError' ': pass' tests.test_rc10_security
mut "M19 |int retiré sur le compteur de lot" templates/index.html 'inserted_rows|int' 'inserted_rows' tests.test_rc10_security
mut "M20 archive : contrôle d empreinte retiré" invoice_service.py 'if hashlib.sha256(s["pdf"]).hexdigest() != s["pdf_sha256"]: raise RuntimeError("empreinte du PDF figé invalide")' 'pass' tests.test_rc10
mut "M21 archive : brouillons inclus" app.py "WHERE i.status='issued' ORDER BY i.issued_at,i.id" "ORDER BY i.issued_at,i.id" tests.test_rc10
mut "M22 limite de lignes du classeur retirée" historical_import.py 'if len(rows) > MAX_SHEET_ROWS: raise WorkbookRefused(' 'if False: raise WorkbookRefused(' tests.test_rc10_security
mut "M23 gestionnaire d erreur affiche le détail" app.py 'return ("Erreur interne : l'"'"'opération n'"'"'a pas abouti (le détail technique est dans le journal du service). Revenir à l'"'"'accueil et vérifier l'"'"'état avant de recommencer.",500)' 'return (str(e),500)' tests.test_rc10_security
echo "RÉSULTAT : $killed/$n mutations détectées"; rm -rf $M
