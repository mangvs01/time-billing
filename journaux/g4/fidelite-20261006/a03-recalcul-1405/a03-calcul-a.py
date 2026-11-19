"""A-03: h.mm vs decimal reading of the clock cells of imported entries.
Read-only: DB opened with mode=ro on a scratch copy; workbooks are scratch copies parsed with the stdlib.
Usage: python3 -I a03.py <db> <orig.xlsx> <r1.xlsx> <out.json>"""
import json
import math
import re
import sqlite3
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from fractions import Fraction

sys.path.insert(0, '/tmp/tb-g4-1405/a03-a')
from xlsx_cells import read_cells, col_index  # noqa: E402

SHA_ORIG = 'c93c610cdffe66d150fbb05d64513054d297f6170158effef99eb461eddac438'
SHA_R1 = 'a6f6b7efd5938f7713806836afce721f113e2d09f74c042622219a2b42e45bba'
NUM_RE = re.compile(r'^-?\d+(\.\d+)?$')
DATE_FMT_IDS = set(range(14, 23)) | {45, 46, 47}


def is_date_fmt(fid, code):
    if fid in DATE_FMT_IDS: return True
    if not code: return False
    c = re.sub(r'\[[^\]]*\]|"[^"]*"|\\.', '', code).lower()
    return any(ch in c for ch in 'dmyhs') and '0.0' not in c


def norm(v):
    import unicodedata
    s = '' if v is None else str(v)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', s).strip().lower()


def openpyxl_like(cell):
    """str() of the value openpyxl would return (the importer's _raw)."""
    if cell is None: return '', None
    t, txt, fid, code, isf = cell
    if txt is None: return '', None
    if t == 'n':
        if is_date_fmt(fid, code):
            n = float(txt)  # openpyxl from_excel: serials < 60 use base 1899-12-31 (Excel's fictitious 1900-02-29)
            d = (datetime(1899, 12, 31) if n < 60 else datetime(1899, 12, 30)) + timedelta(days=n)
            return d.isoformat(), 'date'
        v = float(txt) if ('.' in txt or 'E' in txt or 'e' in txt) else int(txt)
        return str(v), 'number'
    if t in ('s', 'str', 'inlineStr'): return txt, 'text'
    return txt, t


def sheet_columns(rows):
    for rn in range(1, 31):
        cells = rows.get(rn, {})
        normd = {norm(v[1]): col for col, v in cells.items() if v[1] is not None}
        if ('date(s)' in normd or 'date' in normd) and 'projet' in normd and 'heures de travail' in normd:
            pick = lambda *ns: next((normd[n] for n in ns if n in normd), None)
            return {'start': pick('heure debut', 'debut'), 'end': pick('heure fin', 'fin'), 'hours': pick('heures de travail')}
    return None


def wb_index(path):
    cells = read_cells(path)
    idx = {}
    for sname, rows in cells.items():
        cols = sheet_columns(rows)
        if not cols: continue
        for rn, row in rows.items():
            idx[(sname, rn)] = {k: row.get(c) for k, c in cols.items()}
    return idx


def frac2(x):
    """frac = round((x - floor(x))*100), two decimals as typed (Python round = half-even); also tells if a tie happened."""
    fl = x.to_integral_value(rounding='ROUND_FLOOR')
    raw = (x - fl) * 100
    f = int(raw.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    return int(fl), f, raw


def q4(fr):
    return float(Decimal(fr.numerator) / Decimal(fr.denominator)).__round__(4)


def main():
    DB, ORIG, R1, OUT = sys.argv[1:5]
    orig = wb_index(ORIG); r1 = wb_index(R1)
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    q = """SELECT r.batch_id, b.file_sha256, b.source_filename, r.source_sheet, r.source_row, r.raw_json, r.decision, r.issues,
                  e.id, e.work_date, e.start_time, e.end_time, e.hours, p.id, p.name, p.active
           FROM import_batch_rows r JOIN import_batches b ON b.id = r.batch_id
           JOIN entries e ON e.id = r.entry_id JOIN projects p ON p.id = e.project_id
           WHERE b.status = 'COMMITTED' AND r.entry_id IS NOT NULL ORDER BY e.id"""
    rows = con.execute(q).fetchall()
    n_entries = con.execute('SELECT COUNT(*) FROM entries').fetchone()[0]
    n_changes = con.execute('SELECT COUNT(*) FROM entry_changes').fetchone()[0]
    quirks = Counter(); qex = defaultdict(list)

    def note(k, ex):
        quirks[k] += 1
        if len(qex[k]) < 12: qex[k].append(ex)

    P = []
    for (bid, sha, fname, sheet, srow, rawj, dec, issues, eid, wdate, st, et, hrs, pid, pname, pact) in rows:
        raw = json.loads(rawj)
        cell = f'{sheet}!{srow}'
        src = 'R1' if sha == SHA_R1 else ('orig' if sha == SHA_ORIG else 'other')
        if src == 'other': note('unknown_source_sha', cell)
        wb = (r1 if src == 'R1' else orig).get((sheet, srow))
        types = {}
        for k in ('start', 'end', 'hours'):
            s_wb, ty = openpyxl_like(wb.get(k) if wb else None)
            types[k] = ty
            if s_wb != raw[k]: note(f'raw_json_vs_{src}_workbook_{k}', (cell, raw[k], s_wb))
            if ty == 'text' and k != 'hours': note('clock_cell_is_text', (cell, k, raw[k]))
            if ty == 'date' and k != 'hours': note('clock_cell_date_formatted', (cell, k, raw[k], wb[k][1]))
            if wb and wb.get(k) and wb[k][4]: note(f'{k}_is_formula', cell)
        if src == 'R1':
            o = orig.get((sheet, srow))
            ov = {k: openpyxl_like(o.get(k) if o else None)[0] for k in ('start', 'end', 'hours')}
            if any(ov[k] != raw[k] for k in ('start', 'end', 'hours')):
                note('R1_differs_from_orig_same_cell', (cell, {k: raw[k] for k in ('start', 'end', 'hours')}, ov))
        # stored hours vs declared
        if raw['hours'] and NUM_RE.match(raw['hours']):
            if abs(Decimal(raw['hours']) - Decimal(repr(hrs))) > Decimal('1e-9'):
                note('stored_hours_ne_declared', (cell, eid, raw['hours'], hrs))
        if raw['hours'] and NUM_RE.match(raw['hours']) and len(raw['hours'].split('.')[-1]) > 4:
            note('declared_hours_float_noise', (cell, raw['hours'], hrs))
        s, e = raw['start'], raw['end']
        if not (NUM_RE.match(s or '') and NUM_RE.match(e or '')): continue
        xs, xe = Decimal(s), Decimal(e)
        if (xs * 4) % 1 == 0 and (xe * 4) % 1 == 0: continue
        fs_i, fs, fs_raw = frac2(xs); fe_i, fe, fe_raw = frac2(xe)
        for x, rawf, k in ((xs, fs_raw, 'start'), (xe, fe_raw, 'end')):
            if rawf != rawf.to_integral_value(): note('more_than_2_decimals', (cell, k, str(x), str(rawf)))
        imp_s, imp_e = fs >= 60, fe >= 60
        stored = Fraction(Decimal(repr(hrs)))
        dec_clock = Fraction(xe - xs)
        if dec_clock <= 0: note('decimal_clock_nonpositive', (cell, s, e))
        # importer-stored clocks = decimal reading
        exp_st = '%02d:%02d' % divmod(int((xs * 60).quantize(Decimal(1), rounding=ROUND_HALF_UP)), 60)
        exp_et = '%02d:%02d' % divmod(int((xe * 60).quantize(Decimal(1), rounding=ROUND_HALF_UP)), 60)
        if (st, et) != (exp_st, exp_et): note('stored_clock_ne_decimal_reading', (cell, eid, s, e, st, et))
        rec = dict(cell=cell, entry_id=eid, mandate=pname, project_id=pid, active=pact, raw_start=s, raw_end=e,
                   stored_hours=hrs, declared=raw['hours'], start_time=st, end_time=et, source=src, batch=bid,
                   cell_types=(types['start'], types['end']), issues=issues,
                   decimal_clock=float(dec_clock), declared_vs_decimal_clock=float(stored - dec_clock),
                   frac=(fs, fe), cls='D' if (imp_s or imp_e) else 'H')
        if rec['cls'] == 'H':
            hs = Fraction(fs_i) + Fraction(fs, 60); he = Fraction(fe_i) + Fraction(fe, 60)
            dur = he - hs
            crossed = dur <= 0
            if crossed: dur += 24; note('midnight_crossing_H', (cell, s, e))
            rec['duration_hmm_exact'] = dur; rec['delta_exact'] = dur - stored
        else:
            rec['delta_exact'] = Fraction(0)
        if abs(stored - dec_clock) > Fraction(1, 10**6): note(f'declared_ne_decimal_clock_material_{rec["cls"]}', (cell, eid, s, e, raw['hours'], hrs))
        if stored != dec_clock: note(f'declared_ne_decimal_clock_{rec["cls"]}', (cell, eid, s, e, raw['hours'], hrs, round(float(dec_clock), 4)))
        P.append(rec)

    D = [r for r in P if r['cls'] == 'D']; H = [r for r in P if r['cls'] == 'H']
    Hnz = [r for r in H if r['delta_exact'] != 0]
    Hnz_tiny = [r for r in Hnz if abs(r['delta_exact']) < Fraction(1, 20000)]
    tot = sum((r['delta_exact'] for r in P), Fraction(0))
    act = [r for r in P if r['active'] == 1]
    tot_act = sum((r['delta_exact'] for r in act), Fraction(0))
    pm = {}
    for r in P:
        m = pm.setdefault(r['project_id'], dict(name=r['mandate'], active=bool(r['active']), n=0, n_D=0, n_H=0, n_H_nonzero=0, s=Fraction(0)))
        m['n'] += 1; m['n_' + r['cls']] += 1; m['s'] += r['delta_exact']
        if r['cls'] == 'H' and r['delta_exact'] != 0: m['n_H_nonzero'] += 1
    f4 = lambda fr: round(float(fr), 4)
    out = dict(
        n_entries=n_entries, n_linked_rows=len(rows), n_entry_changes=n_changes,
        P=len(P), D=len(D), H=len(H), H_nonzero=len(Hnz), H_nonzero_below_0_00005=len(Hnz_tiny),
        sum_delta=f4(tot), sum_delta_exact=str(tot), sum_delta_of_rounded_rows=round(sum(f4(r['delta_exact']) for r in P), 4),
        active_sum_delta=f4(tot_act), active_n=len(act), active_H=sum(1 for r in act if r['cls'] == 'H'),
        active_H_nonzero=sum(1 for r in act if r['cls'] == 'H' and r['delta_exact'] != 0),
        P_by_source=Counter(r['source'] for r in P), H_by_source=Counter(r['source'] for r in H),
        Hnz_by_source=Counter(r['source'] for r in Hnz),
        sum_negative=f4(sum((r['delta_exact'] for r in Hnz if r['delta_exact'] < 0), Fraction(0))),
        sum_positive=f4(sum((r['delta_exact'] for r in Hnz if r['delta_exact'] > 0), Fraction(0))),
        per_mandate=[dict(name=m['name'], active=m['active'], n=m['n'], n_D=m['n_D'], n_H=m['n_H'], n_H_nonzero=m['n_H_nonzero'], sum_delta=f4(m['s']))
                     for _, m in sorted(pm.items())],
        rows=[dict(cell=r['cell'], entry_id=r['entry_id'], mandate=r['mandate'], active=r['active'], raw_start=r['raw_start'], raw_end=r['raw_end'],
                   stored_hours=r['stored_hours'], declared=r['declared'], duration_hmm=f4(r['duration_hmm_exact']), delta=f4(r['delta_exact']),
                   decimal_clock=round(r['decimal_clock'], 4), stored_clock=f"{r['start_time']}-{r['end_time']}", source=r['source'], cell_types=r['cell_types'])
              for r in sorted(Hnz, key=lambda r: r['entry_id'])],
        D_rows=[dict(cell=r['cell'], entry_id=r['entry_id'], raw_start=r['raw_start'], raw_end=r['raw_end'], frac=r['frac'], stored_hours=r['stored_hours'],
                     decimal_clock=round(r['decimal_clock'], 4)) for r in D],
        H_zero_rows=[dict(cell=r['cell'], entry_id=r['entry_id'], raw_start=r['raw_start'], raw_end=r['raw_end'], stored_hours=r['stored_hours'])
                     for r in H if r['delta_exact'] == 0],
        P_cell_types=Counter(str(r['cell_types']) for r in P),
        quirks={k: dict(n=v, examples=qex[k]) for k, v in sorted(quirks.items())},
    )
    with open(OUT, 'w') as f: json.dump(out, f, indent=1, ensure_ascii=False, default=str)
    print(json.dumps({k: v for k, v in out.items() if k not in ('rows', 'D_rows', 'H_zero_rows', 'quirks', 'per_mandate')}, default=str, ensure_ascii=False, indent=1))
    for m in out['per_mandate']: print(m)
    print('rows (H, delta != 0):')
    for r in out['rows']: print(r)
    print('quirks:')
    for k, v in out['quirks'].items(): print(k, v['n'], v['examples'])


if __name__ == '__main__':
    main()
