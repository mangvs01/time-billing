"""Prépare une COPIE de base (jamais le staging réel) pour recette-verrou-import.js : saisies « NAV … » telles que l'import peut les écrire.
Usage : python3 -I tests/browser/preparer-copie-verrou-import.py COPIE_DB"""
import sqlite3, sys
NEXT = """(SELECT MAX(COALESCE((SELECT MAX(id) FROM entries),0),COALESCE((SELECT MAX(entry_id) FROM entry_changes),0),
 COALESCE((SELECT MAX(entry_id) FROM invoice_annex_entries),0),COALESCE((SELECT MAX(entry_id) FROM import_batch_rows),0))+1)"""
c = sqlite3.connect(sys.argv[1])
pid = c.execute("SELECT id FROM projects WHERE active=1 ORDER BY id LIMIT 1").fetchone()[0]
for s, e, h, d in [('', '', 25.0, 'NAV gt24'), ('', '', 0.005, 'NAV lt001'), ('07:05:30', '09:10:15', 2.08, 'NAV secondes'), ('08:00', '08:00', 3.0, 'NAV debut=fin'),
                   ('08:00', '', 2.0, 'NAV horaire seul'), ('', '', 2.0, 'NAV multi l1\nl2'), ('', '', 2.0, 'NAV long ' + 'L' * 1100),
                   ('07:05:30', '09:10:15', 2.08, 'NAV sec2'), ('08:00:30', '08:00', 0.5, 'NAV minute'), ('', '', 5e-05, 'NAV minuscule')]:
    c.execute(f"INSERT INTO entries(id,work_date,project_id,start_time,end_time,hours,description,source,source_ref) VALUES({NEXT},'2026-09-02',?,?,?,?,?,'import','SEPT 26!999')",
              (pid, s, e, h, d))
c.commit(); print('mandat', pid)
