#!/usr/bin/env python3
"""G4-1 — rapprochement des factures historiques du classeur (SUIVI 2025 / SUIVI 2026) avec les mandats de l'application.

LECTURE SEULE : le classeur et la copie de la base sont ouverts en lecture seule ; rien n'est écrit dans la base ni dans le classeur.
Usage (dans un conteneur jetable sans réseau, image de test qui fournit openpyxl) :
    python rapprochement_suivi.py <classeur.xlsx> <copie-base.db> <dossier-sortie>

Sorties : rapprochement-suivi.csv (une ligne par mandat / ligne SUIVI), rapprochement-suivi-factures.csv (une ligne par cellule de facture),
rapprochement-suivi.json (tout, pour les contrôles) et un résumé sur la sortie standard.
Aucune donnée n'est corrigée ni inventée : une valeur ambiguë est signalée, jamais tranchée.
"""
import csv, json, re, sqlite3, sys, warnings
from datetime import date

import openpyxl

warnings.filterwarnings("ignore")
SRC, DB, OUT = sys.argv[1:4]
TOL = 0.05   # tolérance (jours) pour parler d'écart

# ligne du SUIVI -> mandat de l'application (None = pas de mandat : aucune saisie importée)
MAP = {
    ("SUIVI 2025", "AL Jan-Mar"): None,
    ("SUIVI 2025", "Endovascular Summit"): "Endovascular Summit",
    ("SUIVI 2025", "EUROPCR 2025"): "EUROPCR 2025",
    ("SUIVI 2025", "ECIO 2025"): "ECIO 2025",
    ("SUIVI 2025", "NC STC June"): "NC STC June",
    ("SUIVI 2025", "CIRSE 2025"): "CIRSE 2025",
    ("SUIVI 2025", "ERA 2025"): "ERA 2025",
    ("SUIVI 2025", "Rising stars Q3"): "Rising stars Q3",
    ("SUIVI 2025", "PCR LV 2025"): "PCR LV 2025",
    ("SUIVI 2025", "SMART Y90"): "SMART Y90",
    ("SUIVI 2025", "EAHAD"): "EAHAD",
    ("SUIVI 2025", "NC STC Sept"): "NC STC Sept",
    ("SUIVI 2026", "ASN 2025"): "ASN 2025",
    ("SUIVI 2026", "ERA 2025 (cloture)"): "ERA 2025",
    ("SUIVI 2026", "SMM 2026"): "SMM 2026",
    ("SUIVI 2026", "EHRA 2026"): "EHRA 2026",
    ("SUIVI 2026", "EAU 2026"): "EAU 2026",
    ("SUIVI 2026", "STC GEM Avril"): "STC GEM Avril",
    ("SUIVI 2026", "EUROPCR 2026"): "EUROPCR 2026",
    ("SUIVI 2026", "EULAR 2026"): "EULAR 2026",
    ("SUIVI 2026", "ERA 2026"): None,
    ("SUIVI 2026", "CIRSE 2026"): "CIRSE 2026",
    ("SUIVI 2026", "PCR LV 2026"): "PCR LV 2026",
    ("SUIVI 2026", "NHAF 2026"): "NHAF 2026",
    ("SUIVI 2026", "STC GEM Oct - DM job"): "STC GEM Oct - DM job",
}
INV_RE = re.compile(r"^Facture\s+(\d{1,2})[./](\d{1,2})\s*$")


def num(v):
    return float(v) if isinstance(v, (int, float)) else None


def read_suivi(wbv, wbf, name):
    """Lignes du tableau SUIVI : valeurs calculées + formules, colonnes de facture repérées par leur en-tête « Facture jj.mm »."""
    ws, wf = wbv[name], wbf[name]
    year = int(ws.cell(1, 1).value)
    heads = {ws.cell(2, c).value: c for c in range(1, ws.max_column + 1) if ws.cell(2, c).value}
    inv_cols = []
    for h, c in heads.items():
        m = INV_RE.match(str(h))
        if m: inv_cols.append((c, h, date(year, int(m.group(2)), int(m.group(1)))))
    rows = []
    for r in range(3, ws.max_row + 1):
        proj = ws.cell(r, heads["PROJET"]).value
        if proj in (None, ""): continue
        if not any(ws.cell(r, heads[k]).value not in (None, "") for k in ("Client", "TARIF", "TOTAL") if k in heads): continue
        g = lambda k: ws.cell(r, heads[k]).value if k in heads else None
        total_f = wf.cell(r, heads["TOTAL"]).value
        invs = []
        for c, h, d in inv_cols:
            v = ws.cell(r, c).value
            if v in (None, "", 0): continue
            invs.append({"colonne": h, "cellule": f"{name}!{openpyxl.utils.get_column_letter(c)}{r}", "date": d.isoformat(), "brut": v,
                         "formule": wf.cell(r, c).value if isinstance(wf.cell(r, c).value, str) and str(wf.cell(r, c).value).startswith("=") else ""})
        rows.append({"feuille": name, "ligne": r, "projet": str(proj).strip(), "client": g("Client"), "num_projet": g("Num projet"), "dates": g("Dates"),
                     "po": g("PO"), "nb_j_po": num(g("NB J PO")), "nb_j": num(g("NB J")), "tarif": num(g("TARIF")), "total": num(g("TOTAL")),
                     "total_formule": total_f if isinstance(total_f, str) else "", "statut": (g("Statut") or "").strip(), "factures": invs,
                     "unite_factures": "jours" if name == "SUIVI 2025" else "CHF"})
    return rows


SIDE_MAP = {   # nom du tableau latéral mensuel -> mandats de l'application (regroupés quand le classeur ne distingue pas)
    'Endovascular Summit': ['Endovascular Summit'], 'PCR LV 2025': ['PCR LV 2025'], 'ECIO 2025': ['ECIO 2025'], 'NC STC': ['NC STC June', 'NC STC Sept'],
    'EUROPCR 2025': ['EUROPCR 2025'], 'CIRSE 2025': ['CIRSE 2025'], 'ERA 2025': ['ERA 2025'], 'Rising stars Q3': ['Rising stars Q3'], 'SMART Y90': ['SMART Y90'],
    'EAHAD': ['EAHAD'], 'ASN 2025': ['ASN 2025'], 'EUROPCR 2026': ['EUROPCR 2026'], 'SMM': ['SMM 2026'], 'PI SMM': ['SMM 2026'], 'EAU 2026': ['EAU 2026'],
    'EAU': ['EAU 2026'], 'EULAR 2026': ['EULAR 2026'], 'Back up Claudia (GEM STC)': ['STC GEM Avril', 'STC GEM Oct - DM job'], 'EHRA 2026': ['EHRA 2026'],
    'CIRSE 2026': ['CIRSE 2026'], 'GEM STC': ['STC GEM Avril', 'STC GEM Oct - DM job'], 'PCR LV 2026': ['PCR LV 2026'], 'NHAF 2026': ['NHAF 2026'],
    'EUROPCR 2027': ['EUROPCR 2027'], 'MSD': ['MSD']}


def read_side_tables(wbv, wbf):
    """Σ « TOTAL H » des tableaux récapitulatifs de chaque feuille mensuelle, par groupe de mandats (le classeur lui-même, doublons inclus)."""
    from openpyxl.utils import range_boundaries
    tot = {}
    for ws in wbv.worksheets:
        if ws.title.startswith("SUIVI"): continue
        for t in wbf[ws.title].tables.values():
            if t.name.startswith("FeuilleDeTemps"): continue
            c1, r1, c2, r2 = range_boundaries(t.ref)
            heads = [ws.cell(r1, c).value for c in range(c1, c2 + 1)]
            ih = heads.index("TOTAL H") if "TOTAL H" in heads else None
            for r in range(r1 + 1, r2 + 1):
                nm = str(ws.cell(r, c1).value or "").strip()
                if nm in ("", "Heures", "Total H", "Total J") or nm not in SIDE_MAP or ih is None: continue
                h = ws.cell(r, c1 + ih).value
                if isinstance(h, (int, float)): tot[nm] = tot.get(nm, 0.0) + float(h)
    groups = {}
    for nm, h in tot.items():
        groups.setdefault(tuple(SIDE_MAP[nm]), []).append((nm, h))
    return tot


def main():
    wbv = openpyxl.load_workbook(SRC, data_only=True)
    wbf = openpyxl.load_workbook(SRC, data_only=False)
    src = read_suivi(wbv, wbf, "SUIVI 2025") + read_suivi(wbv, wbf, "SUIVI 2026")
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); db.row_factory = sqlite3.Row
    mandates = {r["name"]: dict(r) for r in db.execute("SELECT * FROM projects")}
    billed_in_app = {r[0]: r[1] for r in db.execute("SELECT project_id, COALESCE(SUM(qty),0) FROM invoices WHERE status='issued' GROUP BY project_id")}
    entries = {}
    for r in db.execute("SELECT project_id, work_date, hours FROM entries ORDER BY work_date"):
        entries.setdefault(r["project_id"], []).append((r["work_date"], r["hours"]))

    side = read_side_tables(wbv, wbf)
    try: excluded = json.load(open(f"{OUT}/exclusions-par-mandat.json"))
    except Exception: excluded = {}
    # 1) une ligne par cellule de facture : jours et montant dérivés, sans rien inventer
    invoices_out = []
    for s in src:
        rate = s["tarif"]
        for i in s["factures"]:
            if s["unite_factures"] == "jours":
                days, amount = float(i["brut"]), (float(i["brut"]) * rate if rate else None)
                basis = "jours lus dans la cellule ; montant = jours × tarif de la ligne"
            else:
                amount, days = float(i["brut"]), (float(i["brut"]) / rate if rate else None)
                basis = "montant CHF lu dans la cellule ; jours = montant ÷ tarif de la ligne"
            invoices_out.append(dict(i, feuille=s["feuille"], projet=s["projet"], jours=round(days, 5) if days is not None else None,
                                     montant_chf=round(amount, 2) if amount is not None else None, tarif=rate, base=basis))

    for s in src:   # montant TOTAL d'une ligne sans colonne de facture ni quantité (ex. « AL Jan-Mar » = 6900+12500) : repris tel quel, sans quantité
        if not s["factures"] and s["total"] and not s["nb_j_po"] and not s["nb_j"]:
            invoices_out.append({"feuille": s["feuille"], "projet": s["projet"], "colonne": "(TOTAL de la ligne, sans colonne de facture)", "cellule": f"{s['feuille']}!ligne {s['ligne']}",
                                 "date": "", "brut": s["total"], "formule": s["total_formule"], "jours": None, "montant_chf": round(s["total"], 2), "tarif": s["tarif"],
                                 "base": "montant seul : aucune quantité, aucun tarif, aucune date de facture dans le classeur"})
    for s in src:   # contrôle de cohérence ligne par ligne : somme des factures lues = TOTAL de la ligne ?
        mine = [i for i in invoices_out if i["feuille"] == s["feuille"] and i["projet"] == s["projet"] and i["colonne"].startswith("Facture")]
        if not mine or s["total"] is None: s["controle"] = ""; continue
        tot = sum(i["montant_chf"] or 0 for i in mine)
        s["controle"] = "somme des factures = TOTAL de la ligne" if abs(tot - s["total"]) < 0.01 else f"somme des factures {tot:.2f} ≠ TOTAL de la ligne {s['total']:.2f}"
    # 2) une ligne par mandat (ou ligne SUIVI sans mandat)
    groups = {}
    for s in src:
        groups.setdefault(MAP[(s["feuille"], s["projet"])] or f"(aucun mandat) {s['projet']}", []).append(s)
    out = []
    for app_name in sorted(set(list(groups) + list(mandates)), key=str.lower):
        rows = groups.get(app_name, [])
        m = mandates.get(app_name)
        dh = (m["day_hours"] or 8) if m else 8
        invs = [i for i in invoices_out if (MAP[(i["feuille"], i["projet"])] or f"(aucun mandat) {i['projet']}") == app_name]
        inv_days = round(sum(i["jours"] or 0 for i in invs), 5); inv_amt = round(sum(i["montant_chf"] or 0 for i in invs), 2)
        ents = entries.get(m["id"], []) if m else []
        hours = round(sum(h for _, h in ents), 4); realized = round(hours / dh, 5)
        last_inv = max((i["date"] for i in invs), default=None)
        after = round(sum(h for d, h in ents if last_inv and d > last_inv), 4)
        cutoffs = []
        run = 0.0
        for i in sorted(invs, key=lambda x: x["date"]):
            run += i["jours"] or 0
            real_to = round(sum(h for d, h in ents if d <= i["date"]) / dh, 5)
            cutoffs.append({"facture": i["colonne"], "date": i["date"], "jours": i["jours"], "cumul_facture": round(run, 5), "realise_a_cette_date": real_to,
                            "ecart": round(run - real_to, 5)})
        # heures du classeur (tableaux mensuels, doublons inclus) pour ce mandat ; regroupé quand un même tableau couvre plusieurs mandats
        mine_side = [(nm, h) for nm, h in side.items() if app_name in SIDE_MAP[nm]]
        grouped = any(len(SIDE_MAP[nm]) > 1 for nm, _ in mine_side)
        side_hours = None if (not mine_side or grouped) else round(sum(h for _, h in mine_side), 4)
        side_group = None
        if mine_side and grouped:
            members = sorted({x for nm, _ in mine_side for x in SIDE_MAP[nm]})
            side_group = {"mandats": members, "heures": round(sum(h for nm, h in side.items() if set(SIDE_MAP[nm]) & set(members)), 4)}
        exc = excluded.get(app_name, {})
        status = ", ".join(sorted({s["statut"] for s in rows if s["statut"]})) or ""
        first = rows[0] if rows else {}
        # texte d'amorce de la ligne source avec montant sans quantité
        amount_only = [s for s in rows if not s["factures"] and s["total"] and not s["nb_j_po"] and not s["nb_j"]]
        flags = []
        if m is None and rows:
            flags.append("F")                      # pas de mandat / montant sans quantité ni saisie
        if inv_days > TOL or inv_amt > 0:
            if (billed_in_app.get(m["id"], 0) if m else 0) == 0: flags.append("A")
        if status == "TERMINE" and m and not m["active"] and (inv_days > TOL) and realized - 0 > TOL: flags.append("B")
        if inv_days > TOL and realized - inv_days > TOL: flags.append("C")
        if len(invs) > 1 or len(rows) > 1: flags.append("D")
        out.append({
            "projet_source": " + ".join(s["projet"] for s in rows) or "(absent du SUIVI)", "feuilles": " + ".join(s["feuille"] for s in rows),
            "client_source": first.get("client") or "", "statut_source": status, "nb_j_po_source": first.get("nb_j_po"),
            "nb_j_source": ", ".join(str(s["nb_j"]) for s in rows if s["nb_j"] is not None), "tarif_source": first.get("tarif"),
            "jours_factures_source": inv_days, "montant_facture_source_chf": inv_amt,
            "reference_date_facture": " ; ".join(f"{i['colonne']} ({i['cellule']}: {i['brut']}{' j' if i['feuille']=='SUIVI 2025' and not i['colonne'].startswith('(TOTAL') else ' CHF'})" for i in invs),
            "mandat_application": app_name if m else "", "mandat_actif": (None if not m else bool(m["active"])),
            "po_jours_application": (m["ordered_days"] if m else None), "tarif_application": (m["rate"] if m else None),
            "heures_application": hours, "jours_realises_application": realized, "saisies": len(ents),
            "premiere_saisie": ents[0][0] if ents else "", "derniere_saisie": ents[-1][0] if ents else "",
            "jours_factures_application": round(billed_in_app.get(m["id"], 0), 5) if m else 0, "notes_de_credit": 0,
            "realise_non_facture_application": realized - round(billed_in_app.get(m["id"], 0), 5) if m else None,
            "ecart_facture_moins_realise_jours": round(inv_days - realized, 5) if m else None,
            "realise_non_facture_si_historique_compte": round(realized - inv_days, 5) if m else None,
            "heures_apres_derniere_facture": after if last_inv else None, "date_derniere_facture": last_inv or "",
            "heures_classeur_tableaux_mensuels": side_hours, "jours_realises_classeur": (round(side_hours / dh, 5) if side_hours is not None else None),
            "groupe_classeur": side_group, "heures_exclues_import": exc.get("heures", 0.0), "lignes_exclues_import": ", ".join(exc.get("refs", [])),
            "solde_po_application": (round((m["ordered_days"] or 0) - billed_in_app.get(m["id"], 0), 5) if m else None),
            "solde_po_si_historique_compte": (round((m["ordered_days"] or 0) - inv_days, 5) if m and (m["ordered_days"] or 0) > 0 else None),
            "controle_total_ligne": " ; ".join(f"{x['projet']}: {x['controle']}" for x in rows if x.get("controle")),
            "controle_aux_dates_de_facture": cutoffs, "categories": "".join(sorted(set(flags))) or "-",
        })
    json.dump({"lignes_suivi": src, "factures": invoices_out, "rapprochement": out}, open(f"{OUT}/rapprochement-suivi.json", "w"), ensure_ascii=False, indent=1, default=str)
    cols = ["projet_source", "client_source", "statut_source", "nb_j_po_source", "jours_factures_source", "montant_facture_source_chf", "reference_date_facture",
            "mandat_application", "jours_realises_application", "jours_factures_application", "notes_de_credit", "realise_non_facture_application",
            "ecart_facture_moins_realise_jours", "realise_non_facture_si_historique_compte", "jours_realises_classeur", "heures_exclues_import", "solde_po_application", "solde_po_si_historique_compte", "heures_apres_derniere_facture", "controle_total_ligne", "categories"]
    with open(f"{OUT}/rapprochement-suivi.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(out)
    with open(f"{OUT}/rapprochement-suivi-factures.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["feuille", "projet", "colonne", "cellule", "date", "brut", "formule", "jours", "montant_chf", "tarif", "base"], extrasaction="ignore")
        w.writeheader(); w.writerows(invoices_out)
    print(json.dumps({"mandats_lignes": len(out), "cellules_facture": len(invoices_out),
                      "total_jours": round(sum(i["jours"] or 0 for i in invoices_out), 5), "total_chf": round(sum(i["montant_chf"] or 0 for i in invoices_out), 2)}))


main()
