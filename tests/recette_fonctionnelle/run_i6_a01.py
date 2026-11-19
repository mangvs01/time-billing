"""I6 — état final reproductible, oracle corrigé (root-83, 2026-10-11). LECTURE SEULE (sqlite mode=ro&immutable=1).
Attendu : rejeu F1→G5 sur copie indépendante (copie-D) + corrections A-01 tracées = base cible, saisie par saisie (sans id ni lot).
Les 15 écarts de description du rejeu brut viennent de la décision A-01 (Decision Center billing-a01-l01…l15, réponse YES de l'utilisateur, 2026-10-07),
appliquée par outils/reporter_notes_a01.py (acteur « outil-a01 », correction tracée dans entry_changes). Le contrôle est STRICT :
  - chaque correction appliquée doit être une mise à jour de la description SEULE, avant = rejeu copie-D, après = base cible ;
  - son motif doit citer une décision billing-a01-lNN résolue YES par l'utilisateur ;
  - après application, les deux empreintes doivent être égales (aucun autre écart toléré).
Usage : run_i6_a01.py <copie-D.db> <base cible.db> [decisions.json]   (code 0 = PASS)"""
import hashlib, json, re, sqlite3, sys
Q = ("select e.work_date,p.name,e.start_time,e.end_time,printf('%.4f',e.hours),e.description,e.source,e.source_ref from entries e "
     "join projects p on p.id=e.project_id order by e.source_ref,e.work_date,p.name,e.start_time,e.end_time")
ro = lambda db: sqlite3.connect(f'file:{db}?mode=ro&immutable=1', uri=True)
digest = lambda rows: hashlib.sha256(json.dumps([list(r) for r in rows]).encode()).hexdigest()

def i6(copie_d, target, decisions='/srv/decision-center/decisions.json'):
    d, t = ro(copie_d), ro(target)
    try:
        rd, rt = [list(r) for r in d.execute(Q)], [list(r) for r in t.execute(Q)]
        yes = {x['id'] for x in json.load(open(decisions)) if isinstance(x, dict) and str(x.get('id', '')).startswith('billing-a01-l')
               and x.get('status') == 'resolved' and str(x.get('decision')).upper() == 'YES' and x.get('resolved_by') == 'user'}
        by_ref = {r[7]: r for r in rd}; problems, applied = [], []
        for eid, ref, act, b, a, reason in t.execute("""select c.entry_id,e.source_ref,c.action,c.before_json,c.after_json,c.reason from entry_changes c
                                                       join entries e on e.id=c.entry_id where c.actor='outil-a01' order by c.id"""):
            b, a = json.loads(b), json.loads(a or 'null') or {}
            changed = sorted(k for k in set(b) | set(a) if b.get(k) != a.get(k))
            m = re.search(r'billing-a01-l\d\d', reason or '')
            row = by_ref.get(ref)
            if act != 'update' or changed != ['description'] or not m or m.group(0) not in yes or row is None or (row[5] or '') != (b.get('description') or ''):
                problems.append((ref, act, changed, m.group(0) if m else None)); continue
            row[5] = a.get('description'); applied.append(m.group(0))
        rd.sort(key=lambda r: (r[7] or '', r[0] or '', r[1] or '', r[2] or '', r[3] or ''))
        raw, exp, got = digest([list(r) for r in d.execute(Q)]), digest(rd), digest(rt)
        return {'ok': not problems and exp == got and len(applied) == len(set(applied)) == 15, 'rows': (len(rd), len(rt)), 'applied': len(applied),
                'decisions_yes': len(yes), 'problems': problems, 'raw_copieD': raw, 'expected': exp, 'target': got}
    finally: d.close(); t.close()

if __name__ == '__main__':
    r = i6(*sys.argv[1:4])
    print(json.dumps(r, ensure_ascii=False, indent=1))
    print(('PASS' if r['ok'] else 'FAIL') + f" I6 rejeu copie-D + {r['applied']} corrections A-01 tracées (décisions YES : {r['decisions_yes']}) = base cible ({r['rows'][1]} saisies)")
    print(f"RÉSULTAT I6 : {1 if r['ok'] else 0}/1 OK, {0 if r['ok'] else 1} KO"); sys.exit(0 if r['ok'] else 1)
