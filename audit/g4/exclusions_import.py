#!/usr/bin/env python3
"""G4-1 (complément) — heures du classeur NON importées (doublons exacts A1 + exceptions), par mandat. LECTURE SEULE.
Usage (conteneur jetable, PYTHONPATH=/app avec le code de l'application) :
    python exclusions_import.py <classeur.xlsx> <copie-base.db> <dossier-sortie>
Une ligne source est « exclue » si elle n'est ni un total ni une saisie de la base (entries.source_ref = FEUILLE!ligne)."""
import collections, datetime, json, sqlite3, sys

from app import historical_import as hi

SRC, DB, OUT = sys.argv[1:4]
res = hi.parse_workbook(open(SRC, "rb").read(), today=datetime.date(2026, 10, 5))
rows = res["rows"]
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
imp = {r[0]: r[1] for r in c.execute("SELECT e.source_ref,p.name FROM entries e JOIN projects p ON p.id=e.project_id")}
name2m = collections.defaultdict(collections.Counter)
for r in rows:
    ref = f"{r['source_sheet']}!{r['source_row']}"
    if ref in imp: name2m[hi._norm(r["project_name"])][imp[ref]] += 1
by = collections.defaultdict(lambda: {"lignes": 0, "heures": 0.0, "refs": []})
for r in rows:
    ref = f"{r['source_sheet']}!{r['source_row']}"
    if ref in imp or "total_row" in r["issues"]: continue
    cand = name2m.get(hi._norm(r["project_name"]))
    if cand and len(cand) == 1: m = next(iter(cand))
    elif cand and r["work_date"] and "NC STC" in (r["project_name"] or "").upper(): m = "NC STC June" if r["work_date"] <= "2025-06-04" else "NC STC Sept"   # coupure retenue à l'import
    elif cand: m = "? " + "/".join(cand)
    else: m = "(nom source sans mandat) " + str(r["project_name"])
    by[m]["lignes"] += 1; by[m]["heures"] = round(by[m]["heures"] + float(r["hours"] or 0), 4); by[m]["refs"].append(ref)
json.dump(by, open(f"{OUT}/exclusions-par-mandat.json", "w"), ensure_ascii=False, indent=1)
print({m: (v["lignes"], v["heures"]) for m, v in sorted(by.items())})
