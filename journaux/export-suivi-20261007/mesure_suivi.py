"""Mesure de l'export .xlsx option B (onglets SUIVI) sur une COPIE jetable de la base du staging (copie locale 958c76ed du 06.10) :
chargement des 24 lignes D1/D2 par le chargeur, validation simulée de toutes, export, puis comparaison de chaque cellule chargée avec la cellule
reconstruite dans l'onglet SUIVI de l'export. Rien n'est écrit ailleurs que dans la copie temporaire. Usage : voir LISEZMOI.txt."""
import io, json, os, shutil, sqlite3, sys, tempfile
from datetime import date

classeur, base, sortie = sys.argv[1:4]
from outils import charger_factures_historiques as ch
tmp = tempfile.mkdtemp(prefix="mesure-suivi-")
try:
    work = os.path.join(tmp, "copie.db")
    src = sqlite3.connect(f"file:{base}?mode=ro", uri=True); dst = sqlite3.connect(work); src.backup(dst); dst.close(); src.close()
    os.environ["DB_PATH"] = work
    for k, v in (("SECRET_KEY", os.urandom(32).hex()), ("APP_PASSWORD", os.urandom(12).hex())): os.environ.setdefault(k, v)
    import app.app as m
    import openpyxl
    from app import billing_rules as rules, forecast, gsheet_export as gx, historical_billing
    c = m.db()
    recs = ch.read_cells(classeur)
    ids = {r["name"]: r["id"] for r in c.execute("SELECT id,name FROM projects")}
    added, same = ch.insert(c, recs, ids, ch.sha256(classeur), historical_billing); c.commit()
    today = date(2026, 10, 7)
    _, before = gx.build(c, today=today)
    for hid in added: historical_billing.set_status(c, hid, "validated", "simulation")
    c.commit()
    data, summ = gx.build(c, today=today)
    fc = {y["year"]: str(y["actual"]) for y in forecast.build(c, today)["years"]}
    issued = c.execute("SELECT COUNT(*) FROM invoices WHERE status='issued'").fetchone()[0]
    c.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
wb = openpyxl.load_workbook(io.BytesIO(data))
lignes, ecarts = [], []
for r in recs:
    ws = wb[r["source_sheet"]]
    label = "Facture " + r["invoice_date"][8:10] + "/" + r["invoice_date"][5:7]
    cols = {ws.cell(2, k).value: k for k in range(1, ws.max_column + 1)}
    rows = {ws.cell(x, 1).value: x for x in range(3, ws.max_row + 1) if ws.cell(x, 1).value}
    got = ws.cell(rows[r["mandate"]], cols[label]).value if r["mandate"] in rows and label in cols else None
    ok = got is not None and abs(got - r["amount_ht"]) < 0.005
    lignes.append({"cellule": f"{r['source_sheet']}!{r['source_cell']}", "mandat": r["mandate"], "valeur_classeur": r["raw"], "montant_ht": r["amount_ht"],
                   "export": f"{r['source_sheet']}!{label}", "valeur_export": got, "identique": ok})
    if not ok: ecarts.append(lignes[-1])
res = {"onglets": summ["sheets"], "factures_tb_emises_dans_la_copie": issued, "suivi_avant_validation": before["suivi"], "suivi_apres_validation": summ["suivi"],
       "facture_billing_previsions": {y: fc.get(y) for y in summ["suivi"]}, "ca_identique_a_billing": all(summ["suivi"][y] == fc.get(y) for y in summ["suivi"]),
       "cellules_comparees": len(lignes), "ecarts": ecarts,
       "lignes_par_onglet": {n: wb[n].max_row - 3 for n in summ["sheets"] if n.startswith("SUIVI ")}}
os.makedirs(sortie, exist_ok=True)
json.dump({"resume": res, "lignes": lignes}, open(os.path.join(sortie, "mesure-suivi.json"), "w"), ensure_ascii=False, indent=1)
open(os.path.join(sortie, "export-copie-apres-validation.xlsx"), "wb").write(data)
print(json.dumps(res, ensure_ascii=False, indent=1))
