"""Replay: what would the import review say for the real workbook (original, corrected copy R1, re-saved copy) on a COPY of the staging DB."""
import sys, io, json, hashlib, sqlite3, collections
sys.path.insert(0, '/app')
from app import historical_import as hi
from openpyxl import load_workbook
db = sqlite3.connect('file:/w/copy.db?mode=ro', uri=True); db.row_factory = sqlite3.Row
# mapping used for the historical import: source label -> most frequent mandate of the entries imported from that label
lab = collections.defaultdict(collections.Counter)
for r in db.execute("SELECT ir.raw_json, e.project_id FROM import_batch_rows ir JOIN entries e ON e.id=ir.entry_id"):
    lab[json.loads(r[0]).get('project', '').strip()][str(r[1])] += 1
active = [str(r[0]) for r in db.execute("SELECT id FROM projects WHERE active=1 ORDER BY id")]
def resave(b):
    """Same sheets byte for byte (cached formula values kept), only docProps/core.xml changes: what a new « Save » changes."""
    import zipfile
    zi = zipfile.ZipFile(io.BytesIO(b)); o = io.BytesIO(); zo = zipfile.ZipFile(o, 'w', zipfile.ZIP_DEFLATED)
    for it in zi.infolist():
        d = zi.read(it.filename)
        if it.filename == 'docProps/core.xml': d = d.replace(b'</cp:coreProperties>', b'<dc:description>reenregistre</dc:description></cp:coreProperties>')
        zo.writestr(it, d)
    zo.close(); return o.getvalue()
files = {'original': open('/w/orig.xlsx', 'rb').read(), 'R1': open('/w/r1.xlsx', 'rb').read()}
files['original réenregistré'] = resave(files['original'])
out = {}
for name, data in files.items():
    p = hi.parse_workbook(data, today=__import__('datetime').date(2026, 10, 6))
    p['file_sha256'] = hashlib.sha256(data).hexdigest(); p['project_names'] = sorted({r['project_name'] for r in p['rows'] if r['project_name']})
    for variant in ('mapping historique', 'tout vers un mandat actif'):
        mapping = {n: (lab[n].most_common(1)[0][0] if lab.get(n) else 'skip') for n in p['project_names']} if variant == 'mapping historique' else {n: active[-1] for n in p['project_names']}
        decisions = {}
        rows, s = hi.validate(db, p, mapping, decisions)
        # worst case: the user answers « import » to every warning
        rows2, s2 = hi.validate(db, p, mapping, {str(r['idx']): 'include' for r in rows if r['status'] == 'needs_decision'})
        st = collections.Counter(r['status'] for r in rows)
        imp = [r for r in rows2 if r['status'] in ('ok', 'include')]
        out[f'{name} / {variant}'] = {'sha': p['file_sha256'][:8], 'statuts': dict(st), 'importables_sans_decision': s['importable'],
                                      'importables_si_tout_importer': len(imp), 'already_imported': s['issue_counts'].get('already_imported', 0),
                                      'source_row_changed': s['issue_counts'].get('source_row_changed', 0), 'previously_excluded': s['issue_counts'].get('previously_excluded', 0),
                                      'exemples_importables': [f"{r['source_sheet']}!{r['source_row']} {r['work_date']} {r['hours']} h {r['issues']}" for r in imp[:8]]}
print(json.dumps(out, ensure_ascii=False, indent=1))
