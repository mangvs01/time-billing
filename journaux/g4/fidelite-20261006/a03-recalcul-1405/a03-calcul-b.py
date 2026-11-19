#!/usr/bin/env python3
"""A-03 : ecart si les heures debut/fin numeriques non multiples de 0,25 etaient en notation h.mm.

Lecture seule. Usage : python3 -I a03_hmm.py [scratch_dir]
Entrees (copies dans scratch_dir) : orig.xlsx (sha c93c610c...), corr.xlsx (R1, sha a6f6b7ef...), staging.db.
Sorties : scratch_dir/out/a03_rows.csv, a03_result.json, a03_checks.txt
"""
import sys, os, json, math, hashlib, sqlite3, zipfile, re, csv, datetime as dt
from fractions import Fraction
from decimal import Decimal
import xml.etree.ElementTree as ET

D = sys.argv[1] if len(sys.argv) > 1 else '/tmp/tb-g4-1405/a03-b'
sys.path.insert(0, os.path.join(D, 'lib'))
import warnings; warnings.filterwarnings('ignore')
import openpyxl
from openpyxl.utils import get_column_letter

OUT = os.path.join(D, 'out'); os.makedirs(OUT, exist_ok=True)
checks = []
def note(*a):
    s = ' '.join(str(x) for x in a); checks.append(s); print(s)

def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()

BOOKS = {}
for tag, fn in (('orig', 'orig.xlsx'), ('corr', 'corr.xlsx')):
    p = os.path.join(D, fn); h = sha(p)
    BOOKS[h] = tag
    note(f'{tag}: {fn} sha256={h}')

# ---------- 1. Workbook cells (openpyxl values + formulas) and raw XML <v> strings ----------
def norm(s):
    import unicodedata
    s = '' if s is None else str(s)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', s).strip().lower()

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
def raw_xml_cells(path):
    """sheet title -> {coord: (t attr, <v> text, has <f>)} straight from the XML."""
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    rmap = {r.get('Id'): r.get('Target') for r in rels}
    out = {}
    for s in wb.find('m:sheets', NS):
        rid = s.get('{%s}id' % NS['r']); tgt = rmap[rid]
        tgt = tgt.lstrip('/') if tgt.startswith('/') else 'xl/' + tgt
        root = ET.fromstring(z.read(tgt)); cells = {}
        for c in root.iter('{%s}c' % NS['m']):
            v = c.find('m:v', NS); f = c.find('m:f', NS)
            cells[c.get('r')] = (c.get('t', 'n'), None if v is None else v.text, f is not None)
        out[s.get('name')] = cells
    return out

WB = {}
for h, tag in BOOKS.items():
    p = os.path.join(D, tag + '.xlsx')
    wv = openpyxl.load_workbook(p, data_only=True)
    wf = openpyxl.load_workbook(p, data_only=False)
    WB[tag] = (wv, wf, raw_xml_cells(p))

def header(ws):
    for r in range(1, 31):
        vals = [norm(ws.cell(r, c).value) for c in range(1, ws.max_column + 1)]
        if ('date(s)' in vals or 'date' in vals) and 'projet' in vals and 'heures de travail' in vals:
            def col(*names):
                return next((vals.index(n) + 1 for n in names if n in vals), None)
            return r, {'start': col('heure debut', 'debut'), 'end': col('heure fin', 'fin'),
                       'hours': col('heures de travail'), 'project': col('projet'), 'date': col('date(s)', 'date')}
    return None, None

def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

def importer_raw(v):  # same as app/historical_import._raw
    if v is None: return ''
    if isinstance(v, (dt.datetime, dt.date, dt.time)): return v.isoformat()
    if isinstance(v, dt.timedelta): return f'timedelta:{v.total_seconds()}'
    return str(v)

# ---------- 2. DB provenance ----------
db = sqlite3.connect('file:' + os.path.join(D, 'staging.db') + '?mode=ro', uri=True)
db.row_factory = sqlite3.Row
note('entries:', db.execute('select count(*) from entries').fetchone()[0],
     '| entry_changes:', db.execute('select count(*) from entry_changes').fetchone()[0],
     '| audit entry_* events:', db.execute("select count(*) from audit where event like 'entry%'").fetchone()[0])
rows = db.execute("""
  SELECT r.batch_id, r.source_sheet, r.source_row, r.raw_json, r.decision, r.issues, r.entry_id,
         b.file_sha256, b.committed_at, e.hours, e.start_time, e.end_time, e.work_date, e.source_ref,
         p.id AS pid, p.name AS mandate, p.active
  FROM import_batch_rows r
  JOIN import_batches b ON b.id = r.batch_id AND b.status = 'COMMITTED'
  JOIN entries e ON e.id = r.entry_id
  JOIN projects p ON p.id = e.project_id
  ORDER BY r.entry_id""").fetchall()
note('current entries with a committed source line:', len(rows))

def fr(x):  # exact rational of the typed decimal (via shortest repr == what Excel/openpyxl expose)
    return Fraction(Decimal(repr(float(x))))

def frac2(x):  # frac = round((x - floor(x))*100), as specified (Python round = half-even)
    return round((x - math.floor(x)) * 100)

result_rows, P, Dcls, H = [], [], [], []
quirk = {'raw_json_vs_cell': [], 'text_cells': [], 'formula_cells': [], 'date_cells': [], 'empty': [],
         'orig_vs_corr_differs': [], 'more_than_2_decimals': [], 'half_rounding': [],
         'stored_vs_raw_hours': [], 'stored_clock_vs_decimal': [], 'declared_vs_decimal_clock': [],
         'declared_vs_hmm_clock_in_P': [], 'xml_v_not_short': [], 'midnight': []}
for r in rows:
    tag = BOOKS.get(r['file_sha256'])
    if tag is None:
        note('UNKNOWN workbook sha for batch', r['batch_id']); continue
    wv, wf, xml = WB[tag]
    ws, wsf = wv[r['source_sheet']], wf[r['source_sheet']]
    hr, cols = header(ws)
    raw = json.loads(r['raw_json'])
    cell = {}
    for k in ('start', 'end', 'hours'):
        coord = f"{get_column_letter(cols[k])}{r['source_row']}"
        v = ws[coord].value; f = wsf[coord].value
        t, vtxt, hasf = xml[r['source_sheet']].get(coord, (None, None, False))
        cell[k] = dict(coord=coord, v=v, f=f, xml_t=t, xml_v=vtxt, has_f=hasf, fmt=ws[coord].number_format)
        if importer_raw(v) != raw[k]:
            quirk['raw_json_vs_cell'].append((r['source_sheet'], r['source_row'], k, raw[k], importer_raw(v), tag))
        if k in ('start', 'end'):
            if isinstance(v, str) and v.strip(): quirk['text_cells'].append((r['source_sheet'], coord, v, r['entry_id']))
            if hasf: quirk['formula_cells'].append((r['source_sheet'], coord, f, v, r['entry_id']))
            if isinstance(v, (dt.datetime, dt.time)): quirk['date_cells'].append((r['source_sheet'], coord, v, cell[k]['fmt'], r['entry_id']))
            if v is None or (isinstance(v, str) and not v.strip()): quirk['empty'].append((r['source_sheet'], coord, r['entry_id']))
            if is_number(v) and vtxt is not None and repr(float(vtxt)) != vtxt and str(float(vtxt)) != vtxt and not re.fullmatch(r'\d+', vtxt):
                quirk['xml_v_not_short'].append((r['source_sheet'], coord, vtxt, repr(float(vtxt)), r['entry_id']))
    # other workbook (R1 vs original) for the same cells
    other = 'corr' if tag == 'orig' else 'orig'
    wo = WB[other][0][r['source_sheet']]
    for k in ('start', 'end', 'hours'):
        vo = wo[cell[k]['coord']].value
        if importer_raw(vo) != importer_raw(cell[k]['v']):
            quirk['orig_vs_corr_differs'].append((r['source_sheet'], cell[k]['coord'], k, tag, importer_raw(cell[k]['v']), other, importer_raw(vo), r['entry_id']))

    s, e = cell['start']['v'], cell['end']['v']
    stored = r['hours']
    # declared hours (cell) vs stored
    hv = cell['hours']['v']
    if is_number(hv) and abs(float(hv) - stored) > 1e-12:
        quirk['stored_vs_raw_hours'].append((r['source_sheet'], r['source_row'], hv, stored, r['entry_id']))
    if is_number(s) and is_number(e):
        # stored clock = decimal reading?
        def hhmm(x):
            m = int((Decimal(str(x)) * 60).to_integral_value(rounding='ROUND_HALF_UP')); return f'{m // 60:02d}:{m % 60:02d}'
        if (r['start_time'], r['end_time']) != (hhmm(s), hhmm(e)):
            quirk['stored_clock_vs_decimal'].append((r['source_sheet'], r['source_row'], s, e, r['start_time'], r['end_time'], r['entry_id']))
        dec_dur = float(e) - float(s)
        if abs(dec_dur - stored) > 0.01:
            quirk['declared_vs_decimal_clock'].append((r['source_sheet'], r['source_row'], s, e, stored, round(dec_dur, 4), r['entry_id']))
        in_P = any(fr(x) * 4 != int(fr(x) * 4) for x in (s, e))
        if not in_P: continue
        rec = dict(cell=f"{r['source_sheet']}!{r['source_row']}", entry_id=r['entry_id'], mandate=r['mandate'],
                   active=bool(r['active']), workbook=tag, raw_start=raw['start'], raw_end=raw['end'],
                   stored_hours=stored, start_coord=cell['start']['coord'], end_coord=cell['end']['coord'])
        for x in (s, e):
            q = fr(x)
            if (q * 100).denominator != 1: quirk['more_than_2_decimals'].append((rec['cell'], x, r['entry_id']))
            y = (x - math.floor(x)) * 100
            if abs(y - math.floor(y) - 0.5) < 1e-6: quirk['half_rounding'].append((rec['cell'], x, r['entry_id']))
        fs, fe = frac2(s), frac2(e)
        rec.update(frac_start=fs, frac_end=fe)
        P.append(rec)
        if fs >= 60 or fe >= 60:
            rec.update(cls='D', duration_hmm=None, delta=0.0, delta_exact=Fraction(0)); Dcls.append(rec)
        else:
            hs = Fraction(math.floor(s)) + Fraction(fs, 60); he = Fraction(math.floor(e)) + Fraction(fe, 60)
            dur = he - hs
            if dur <= 0: dur += 24; quirk['midnight'].append(rec['cell'])
            dx = dur - fr(stored)
            rec.update(cls='H', duration_hmm=float(dur), delta=float(dx), delta_exact=dx)
            if abs(float(fr(stored)) - dec_dur) > 0.01:
                quirk['declared_vs_hmm_clock_in_P'].append((rec['cell'], s, e, stored, round(dec_dur, 4)))
            H.append(rec)

EPS = Fraction(1, 10**9)
Hnz = [x for x in H if abs(x['delta_exact']) > EPS]
Hnoise = [x for x in H if 0 < abs(x['delta_exact']) <= EPS]
tot = sum((x['delta_exact'] for x in H), Fraction(0))
act = [x for x in P if x['active']]
tot_act = sum((x['delta_exact'] for x in act), Fraction(0))
per = {}
for x in P:
    k = (x['mandate'], x['active']); per.setdefault(k, [0, Fraction(0), 0, 0, 0])
    per[k][0] += 1; per[k][1] += x['delta_exact']; per[k][2] += x['cls'] == 'D'; per[k][3] += x['cls'] == 'H'
    per[k][4] += x in Hnz

note('\n|P| =', len(P), ' |D| =', len(Dcls), ' |H| =', len(H), ' H with delta!=0 =', len(Hnz), ' (float-noise-only deltas:', len(Hnoise), ')')
note('SUM(delta) =', f'{float(tot):.4f}', f'(exact {tot})')
note('ACTIVE mandates: n =', len(act), ' SUM(delta) =', f'{float(tot_act):.4f}', ' (H nonzero among active:', sum(1 for x in Hnz if x['active']), ')')
note('per mandate (name, active, n_P, n_D, n_H, n_H_nonzero, sum_delta):')
for (m, a), (n, sd, nd, nh, nz) in sorted(per.items(), key=lambda kv: (not kv[0][1], kv[0][0])):
    note(f'  {m:28s} active={int(a)} n={n:3d} D={nd:3d} H={nh:3d} H!=0={nz:3d} sum={float(sd):+.4f}')
note('by workbook:', {t: sum(1 for x in P if x['workbook'] == t) for t in ('orig', 'corr')})

note('\nH rows with delta != 0:')
for x in sorted(Hnz, key=lambda x: x['entry_id']):
    note(f"  {x['cell']:10s} id={x['entry_id']:5d} {x['mandate']:22s} act={int(x['active'])} start={x['raw_start']:>6s} end={x['raw_end']:>6s} "
         f"stored={x['stored_hours']!r:>20s} hmm={x['duration_hmm']:.4f} delta={x['delta']:+.4f} [{x['workbook']}]")
note('\nD rows:')
for x in sorted(Dcls, key=lambda x: x['entry_id']):
    note(f"  {x['cell']:10s} id={x['entry_id']:5d} {x['mandate']:22s} start={x['raw_start']:>6s} end={x['raw_end']:>6s} frac=({x['frac_start']},{x['frac_end']}) stored={x['stored_hours']}")
note('\nH rows with delta == 0:')
for x in sorted([x for x in H if x not in Hnz], key=lambda x: x['entry_id']):
    note(f"  {x['cell']:10s} id={x['entry_id']:5d} {x['mandate']:22s} start={x['raw_start']:>6s} end={x['raw_end']:>6s} stored={x['stored_hours']!r}")

note('\nQUIRKS:')
for k, v in quirk.items():
    note(f'  {k}: {len(v)}')
    for i in v[:40]: note('     ', i)

with open(os.path.join(OUT, 'a03_rows.csv'), 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['cell', 'entry_id', 'mandate', 'active', 'workbook', 'class', 'raw_start', 'raw_end', 'frac_start', 'frac_end',
                'stored_hours', 'duration_hmm', 'delta'])
    for x in sorted(P, key=lambda x: x['entry_id']):
        w.writerow([x['cell'], x['entry_id'], x['mandate'], int(x['active']), x['workbook'], x['cls'], x['raw_start'], x['raw_end'],
                    x['frac_start'], x['frac_end'], repr(x['stored_hours']),
                    '' if x['duration_hmm'] is None else f"{x['duration_hmm']:.6f}", f"{x['delta']:.6f}"])
json.dump({'P': len(P), 'D': len(Dcls), 'H': len(H), 'H_nonzero': len(Hnz), 'sum_delta': round(float(tot), 4),
           'active_n': len(act), 'active_sum_delta': round(float(tot_act), 4),
           'per_mandate': [{'name': m, 'active': a, 'n': n, 'sum_delta': round(float(sd), 4)} for (m, a), (n, sd, *_ ) in sorted(per.items())],
           'rows': [{'cell': x['cell'], 'entry_id': x['entry_id'], 'mandate': x['mandate'], 'raw_start': x['raw_start'],
                     'raw_end': x['raw_end'], 'stored_hours': x['stored_hours'], 'duration_hmm': round(x['duration_hmm'], 4),
                     'delta': round(x['delta'], 4)} for x in sorted(Hnz, key=lambda x: x['entry_id'])]},
          open(os.path.join(OUT, 'a03_result.json'), 'w'), ensure_ascii=False, indent=1)
open(os.path.join(OUT, 'a03_checks.txt'), 'w').write('\n'.join(checks) + '\n')
