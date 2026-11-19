#!/usr/bin/env python3
"""G4 / décision D1 (2026-10-06) — chargement des factures historiques du classeur dans le registre `historical_invoices`, en statut « à valider ».

SIMULATION PAR DÉFAUT. Sans --appliquer, la base n'est ouverte qu'en lecture : le travail se fait sur une copie temporaire (supprimée à la fin),
où les 23 lignes sont chargées puis, pour mesurer l'effet, validées toutes ; le rapport compare chaque mandat avant / après.
Avec --appliquer (staging seulement, après le go de l'utilisateur et une sauvegarde) : les 23 lignes sont écrites en « à valider » dans une seule
transaction. Elles ne comptent pour RIEN tant que l'utilisateur ne les a pas validées sur la page « Factures historiques ». L'outil ne valide jamais.

Lignes chargées : exactement les 23 cellules de la décision D1 et la cellule de la décision D2 (Decision Center billing-d2 = IMPORT_4550,
2026-10-07 : « cette facture a bien été émise »), chacune relue dans le classeur (valeur, en-tête « Facture jj.mm » → date) et comparée
à la valeur attendue ; le moindre écart arrête tout. D2 : SUIVI 2026!M15, STC GEM Oct – 4 550 CHF, jours = montant ÷ tarif du mandat (600 CHF/j,
vérifié dans la base) = 7,5833 j, comme annoncé dans la fiche D2 (« Si OUI »). Exclusions (jamais chargées) :
  SUIVI 2025!H3   AL Jan-Mar – 19 400 CHF : D3 = NON (aucun mandat ; écart documenté)
  ERA 2026        aucune facture, aucun mandat ; ECIO 2025 : jamais facturé (décision C3)
Note de provenance D4 (doublons A1 exclus du réalisé) sur SUIVI 2026!J3, SUIVI 2025!K7, M14, N10, N8. Aucune valeur source n'est corrigée.

Usage (conteneur jetable SANS réseau, image de l'application, -w /app -e PYTHONPATH=/app ; l'image ne contient pas outils/ : monter
-v <dépôt>/outils:/app/outils:ro ; le classeur et la base montés en lecture seule pour la simulation) :
  python outils/charger_factures_historiques.py --classeur "/src/Time sheet CP.xlsx" --base /data/timebilling.db --sortie /out
  python outils/charger_factures_historiques.py ... --appliquer --confirmer CHARGER-24-A-VALIDER
"""
import argparse, csv, hashlib, json, os, re, shutil, sqlite3, sys, tempfile
from datetime import date

WORKBOOK_SHA256 = "c93c610cdffe66d150fbb05d64513054d297f6170158effef99eb461eddac438"
SOURCE_FILE = "Time sheet CP.xlsx"
CONFIRM = "CHARGER-24-A-VALIDER"
RATE = 650.0
INV_RE = re.compile(r"^Facture\s+(\d{1,2})[./](\d{1,2})\s*$")

# (feuille, cellule) -> (mandat de l'application, valeur attendue dans la cellule). SUIVI 2025 : jours ; SUIVI 2026 : montants CHF.
D1 = {
    ("SUIVI 2025", "I4"): ("Endovascular Summit", 5.2), ("SUIVI 2025", "K4"): ("Endovascular Summit", 7.7),
    ("SUIVI 2025", "I5"): ("EUROPCR 2025", 6.6), ("SUIVI 2025", "J5"): ("EUROPCR 2025", 5.3), ("SUIVI 2025", "K5"): ("EUROPCR 2025", 7.5),
    ("SUIVI 2025", "K7"): ("NC STC June", 10.5), ("SUIVI 2025", "N8"): ("CIRSE 2025", 9.5),
    ("SUIVI 2025", "J9"): ("ERA 2025", 5.6), ("SUIVI 2025", "L9"): ("ERA 2025", 8.4), ("SUIVI 2025", "N10"): ("Rising stars Q3", 6.0),
    ("SUIVI 2025", "P11"): ("PCR LV 2025", 6.34), ("SUIVI 2025", "O12"): ("SMART Y90", 10.0), ("SUIVI 2025", "K13"): ("EAHAD", 1.0),
    ("SUIVI 2025", "M14"): ("NC STC Sept", 13.8),
    ("SUIVI 2026", "J3"): ("ASN 2025", 6389.5), ("SUIVI 2026", "J4"): ("ERA 2025", 364.0), ("SUIVI 2026", "L5"): ("SMM 2026", 9750.0),
    ("SUIVI 2026", "N6"): ("EHRA 2026", 11700.0), ("SUIVI 2026", "K7"): ("EAU 2026", 9100.0), ("SUIVI 2026", "M8"): ("STC GEM Avril", 4550.0),
    ("SUIVI 2026", "O9"): ("EUROPCR 2026", 11245.0), ("SUIVI 2026", "P10"): ("EULAR 2026", 8125.0), ("SUIVI 2026", "Q12"): ("CIRSE 2026", 5200.0),
}
# D2 (2026-10-07, IMPORT_4550) : facture émise selon l'utilisateur ; le tarif de la ligne est celui du mandat (vérifié dans la base avant d'écrire)
D2 = {("SUIVI 2026", "M15"): ("STC GEM Oct - DM job", 4550.0)}
RATES = {("SUIVI 2026", "M15"): 600.0}
EXCLUDED = {("SUIVI 2025", "H3"): "D3 = NON : AL Jan-Mar, 19 400 CHF sans mandat, non chargé, écart documenté"}
# D1 : le numéro imprimé sur la facture réelle 2026-09 (Facture-reelle-reference-2026-09.pdf) est repris tel quel ; aucun autre numéro n'est connu
REFS = {("SUIVI 2026", "Q12"): "2026-09"}
# D4 : provenance seulement (le réalisé de l'application reste sans les doublons A1)
D4 = "Provenance (D4) : quantité fixée dans le classeur d'après un cumul qui comptait des lignes en double exclues du réalisé (A1)"
NOTES = {
    ("SUIVI 2026", "J3"): D4 + " : 2,75 h (effet certain 0,344 j) ; s'y ajoutent 1,50 h de OCT!94 (exception C6, non importée).",
    ("SUIVI 2025", "K7"): D4 + " : NC STC (June + Sept, même tableau) 0,75 h (MAR!49) + 9,75 h (AUG) ; effet certain 1,2625 j sur K7 + M14.",
    ("SUIVI 2025", "M14"): D4 + " : NC STC (June + Sept, même tableau) 0,75 h (MAR!49) + 9,75 h (AUG) ; effet certain 1,2625 j sur K7 + M14.",
    ("SUIVI 2025", "N10"): D4 + " : 3,75 h ; effet possible 0,469 j (6 j = PO : cumul ou PO facturé, indécidable).",
    ("SUIVI 2025", "N8"): D4 + " : 1,75 h ; effet possible 0,169 j au plus.",
    ("SUIVI 2026", "M15"): "D2 (2026-10-07) : facture émise selon l'utilisateur ; aucune pièce n'indique les jours : jours = montant ÷ tarif du mandat (600 CHF/j).",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def read_cells(path):
    """Relit les 24 cellules (D1 + D2) (valeur calculée) et leur en-tête de colonne. Retourne les enregistrements du registre, ou lève une erreur au moindre écart."""
    import openpyxl
    from openpyxl.utils import column_index_from_string
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    out = []
    for (sheet, cell), (mandate, expected) in {**D1, **D2}.items():
        rate = RATES.get((sheet, cell), RATE)
        ws = wb[sheet]
        year = int(ws.cell(1, 1).value)
        col = column_index_from_string(re.match(r"[A-Z]+", cell).group(0))
        head = str(ws.cell(2, col).value or "").strip()
        m = INV_RE.match(head)
        if not m: raise SystemExit(f"ARRÊT : {sheet}!{cell} : l'en-tête « {head} » n'est pas une colonne « Facture jj.mm »")
        raw = ws[cell].value
        if not isinstance(raw, (int, float)) or abs(float(raw) - expected) > 1e-6:
            raise SystemExit(f"ARRÊT : {sheet}!{cell} contient {raw!r}, attendu {expected} (décision D1) : rien n'est chargé")
        d = date(year, int(m.group(2)), int(m.group(1))).isoformat()
        if sheet == "SUIVI 2025":       # jours lus ; montant = jours × tarif de la ligne
            qty, amount, basis, derived = round(float(raw), 6), round(float(raw) * rate, 2), "days", 0
        else:                           # montant lu ; jours = montant ÷ tarif de la ligne
            amount = round(float(raw), 2); qty, basis, derived = round(amount / rate, 6), "amount", 1
        out.append({"mandate": mandate, "source_file": SOURCE_FILE, "source_sheet": sheet, "source_cell": cell, "source_column": head, "invoice_date": d,
                    "invoice_ref": REFS.get((sheet, cell)), "qty_days": qty, "amount_ht": amount, "unit_rate": rate, "basis": basis, "qty_derived": derived,
                    "note": NOTES.get((sheet, cell), ""), "raw": raw})
    for (sheet, cell), why in EXCLUDED.items():
        if (sheet, cell) in D1 or (sheet, cell) in D2: raise SystemExit("ARRÊT : une cellule exclue figure dans D1/D2")
    return out


def positions(c, rules):
    out = {}
    for p in c.execute("SELECT * FROM projects ORDER BY name"):
        k = rules.contract(c, p)
        out[p["name"]] = {"actif": bool(p["active"]), "po": k["ordered_days"], "realise": k["consumed_days"], "facture": k["billed_days"],
                          "historique": k["historical_days"], "non_facture": k["unbilled_days"], "solde_po": k["po_balance_days"]}
    return out


def insert(c, recs, ids, sha, historical_billing):
    """Écrit les lignes en « à valider ». Une cellule déjà présente avec les mêmes valeurs est sautée ; avec d'autres valeurs : arrêt."""
    added, same = [], []
    for r in recs:
        old = c.execute("SELECT * FROM historical_invoices WHERE source_file=? AND source_sheet=? AND source_cell=?",
                        (r["source_file"], r["source_sheet"], r["source_cell"])).fetchone()
        rec = dict(r, project_id=ids[r["mandate"]], source_sha256=sha)
        if (r["source_sheet"], r["source_cell"]) in RATES:
            # D2: the days are derived with the rate of the mandate; a mandate whose rate changed since the decision stops everything
            rate = c.execute("SELECT rate FROM projects WHERE id=?", (rec["project_id"],)).fetchone()[0]
            if abs(float(rate or 0) - rec["unit_rate"]) > 1e-9:
                raise SystemExit(f"ARRÊT : {r['source_sheet']}!{r['source_cell']} : le tarif du mandat {r['mandate']} est {rate}, attendu {rec['unit_rate']} "
                                 "(fiche D2) : rien n'est chargé")
        if rec.get("invoice_ref") and c.execute("SELECT 1 FROM invoices WHERE number=?", (rec["invoice_ref"],)).fetchone():
            # N1 the other way round: a Time Billing invoice issued before this load already carries the number of the real invoice
            raise SystemExit(f"ARRÊT : {r['source_sheet']}!{r['source_cell']} porte le n° {rec['invoice_ref']}, déjà attribué à une facture Time Billing : "
                             "deux documents auraient le même numéro ; rien n'est chargé (décision utilisateur requise)")
        dup = rec.get("invoice_ref") and c.execute("""SELECT id,source_sheet,source_cell FROM historical_invoices WHERE invoice_ref=? AND status<>'rejected'
                                                      AND NOT (source_file=? AND source_sheet=? AND source_cell=?)""",
                                                   (rec["invoice_ref"], r["source_file"], r["source_sheet"], r["source_cell"])).fetchone()
        if dup:
            # rc23 (review 2026-10-08): the same real invoice already recorded on another row (e.g. added by hand in the application)
            raise SystemExit(f"ARRÊT : {r['source_sheet']}!{r['source_cell']} porte le n° {rec['invoice_ref']}, déjà enregistré sur la facture historique "
                             f"n° {dup['id']} ({dup['source_sheet']}!{dup['source_cell']}) : rien n'est chargé (la même facture serait comptée deux fois)")
        if old:
            if any(old[k] != rec[k] for k in ("project_id", "invoice_date", "qty_days", "amount_ht", "basis", "source_sha256")):
                raise SystemExit(f"ARRÊT : {r['source_sheet']}!{r['source_cell']} existe déjà dans le registre avec d'autres valeurs (id {old['id']}) : rien n'est chargé")
            same.append(old["id"]); continue
        added.append(historical_billing.add_proposed(c, rec))
    return added, same


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classeur", required=True); ap.add_argument("--base", required=True); ap.add_argument("--sortie", required=True)
    ap.add_argument("--appliquer", action="store_true"); ap.add_argument("--confirmer", default="")
    a = ap.parse_args()
    sha = sha256(a.classeur)
    if sha != WORKBOOK_SHA256: raise SystemExit(f"ARRÊT : classeur inattendu (sha256 {sha[:12]}…, attendu {WORKBOOK_SHA256[:12]}…)")
    recs = read_cells(a.classeur)
    os.makedirs(a.sortie, exist_ok=True)

    if a.appliquer:
        if a.confirmer != CONFIRM: raise SystemExit(f"ARRÊT : --appliquer exige --confirmer {CONFIRM}")
        os.environ["DB_PATH"] = a.base
        from app import historical_billing
        c = sqlite3.connect(a.base, timeout=30, isolation_level=None); c.row_factory = sqlite3.Row; c.execute("PRAGMA foreign_keys=ON")
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='historical_invoices'").fetchone():
            raise SystemExit("ARRÊT : la base n'a pas de registre historical_invoices (déployer G4 d'abord)")
        c.execute("BEGIN IMMEDIATE")
        try:
            ids = {r["name"]: r["id"] for r in c.execute("SELECT id,name FROM projects")}
            missing = sorted({r["mandate"] for r in recs} - set(ids))
            if missing: raise SystemExit(f"ARRÊT : mandat(s) absent(s) de la base : {', '.join(missing)}")
            entries_before = c.execute("SELECT COUNT(*),COALESCE(SUM(hours),0) FROM entries").fetchone()
            added, same = insert(c, recs, ids, sha, historical_billing)
            if c.execute("SELECT COUNT(*) FROM historical_invoices WHERE status<>'proposed' AND id IN (%s)" % ",".join(map(str, added or [0]))).fetchone()[0]:
                raise SystemExit("ARRÊT : une ligne chargée n'est pas « à valider »")
            if tuple(c.execute("SELECT COUNT(*),COALESCE(SUM(hours),0) FROM entries").fetchone()) != tuple(entries_before):
                raise SystemExit("ARRÊT : les saisies ont changé pendant le chargement")
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK"); raise
        finally: c.close()
        print(f"CHARGÉ : {len(added)} ligne(s) « à valider » (ids {added[:1]}…{added[-1:]}), {len(same)} déjà présente(s) à l'identique. Aucune validée.")
        return

    # SIMULATION : copie temporaire ; la base fournie n'est ouverte qu'en lecture
    tmp = tempfile.mkdtemp(prefix="simu-g4-")
    try:
        work = os.path.join(tmp, "copie.db")
        src = sqlite3.connect(f"file:{a.base}?mode=ro", uri=True); dst = sqlite3.connect(work); src.backup(dst); dst.close(); src.close()
        os.environ["DB_PATH"] = work
        for k, v in (("SECRET_KEY", os.urandom(32).hex()), ("APP_PASSWORD", os.urandom(12).hex())):
            os.environ.setdefault(k, v)          # app.app refuses to load without them; the simulation never serves a page (throw-away copy)
        import app.app as m                      # migre la COPIE au schéma courant (registre compris)
        from app import billing_rules as rules, historical_billing
        c = m.db()
        before = positions(c, rules)
        ids = {r["name"]: r["id"] for r in c.execute("SELECT id,name FROM projects")}
        missing = sorted({r["mandate"] for r in recs} - set(ids))
        if missing: raise SystemExit(f"ARRÊT : mandat(s) absent(s) de la base : {', '.join(missing)}")
        added, same = insert(c, recs, ids, sha, historical_billing); c.commit()
        proposed = positions(c, rules)
        unchanged_while_proposed = proposed == before
        for hid in added: historical_billing.set_status(c, hid, "validated", "simulation")
        c.commit()
        after = positions(c, rules)
        year = lambda y: float(historical_billing.amounts_by_year(c).get(y, 0))
        ca = {"2025": year("2025"), "2026": year("2026")}
        c.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    with open(os.path.join(a.sortie, "simulation-lignes.csv"), "w", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["cellule", "colonne", "mandat", "date", "valeur lue", "base", "jours", "montant HT CHF", "n° facture", "note"])
        for r in recs:
            w.writerow([f"{r['source_sheet']}!{r['source_cell']}", r["source_column"], r["mandate"], r["invoice_date"], r["raw"], r["basis"], r["qty_days"], r["amount_ht"],
                        r["invoice_ref"] or "", r["note"]])
    with open(os.path.join(a.sortie, "simulation-mandats.csv"), "w", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["mandat", "actif", "PO j", "réalisé j", "facturé avant", "facturé après", "non facturé avant", "non facturé après", "solde PO avant", "solde PO après"])
        for n in sorted(after):
            b, x = before[n], after[n]
            w.writerow([n, "oui" if x["actif"] else "non", x["po"], x["realise"], b["facture"], x["facture"], b["non_facture"], x["non_facture"], b["solde_po"], x["solde_po"]])
    closed = [n for n in after if not after[n]["actif"]]; active = [n for n in after if after[n]["actif"]]
    tot = lambda d, keys, k: round(sum(d[n][k] for n in keys), 5)
    summary = {
        "mode": "SIMULATION (copie temporaire supprimée ; base lue seulement)", "classeur_sha256": sha, "lignes": len(recs),
        "jours": round(sum(r["qty_days"] for r in recs), 5), "montant_ht_chf": round(sum(r["amount_ht"] for r in recs), 2),
        "par_annee_chf": {y: round(sum(r["amount_ht"] for r in recs if r["invoice_date"].startswith(y)), 2) for y in ("2025", "2026")},
        "exclues": {f"{s}!{cl}": why for (s, cl), why in EXCLUDED.items()},
        "notes_d4": sorted(f"{s}!{cl}" for (s, cl) in NOTES if (s, cl) not in D2), "d2": sorted(f"{s}!{cl}" for (s, cl) in D2),
        "aucun_effet_tant_que_a_valider": unchanged_while_proposed,
        "clotures": {"mandats": len(closed), "facture_avant": tot(before, closed, "facture"), "facture_apres": tot(after, closed, "facture"),
                     "non_facture_avant": tot(before, closed, "non_facture"), "non_facture_apres": tot(after, closed, "non_facture"),
                     "solde_po_avant": tot(before, closed, "solde_po"), "solde_po_apres": tot(after, closed, "solde_po")},
        "actifs": {"mandats": len(active), "non_facture_avant": tot(before, active, "non_facture"), "non_facture_apres": tot(after, active, "non_facture"),
                   "inchanges": all(before[n] == after[n] for n in active)},
        "ca_historique_valide_chf": ca,
        "negatifs_apres": {n: after[n]["non_facture"] for n in sorted(after) if after[n]["non_facture"] < -1e-9},
    }
    json.dump(summary, open(os.path.join(a.sortie, "simulation-resume.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
