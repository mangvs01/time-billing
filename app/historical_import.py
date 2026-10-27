"""Historical Excel timesheet import: parsing and validation.

No database writes occur here. Every source row stays individual: nothing is
merged, deduplicated or corrected. Raw cell values are kept next to the parsed
ones so the preview and the batch ledger show exactly what the workbook held.
"""
import hashlib, io, json, re, unicodedata
from itertools import islice
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONTHS = {'JAN': 1, 'JANV': 1, 'FEV': 2, 'FEB': 2, 'FEVR': 2, 'MAR': 3, 'MARS': 3, 'AVR': 4, 'APR': 4,
          'MAI': 5, 'MAY': 5, 'JUN': 6, 'JUIN': 6, 'JUL': 7, 'JULY': 7, 'JUIL': 7, 'AUG': 8, 'AOU': 8,
          'AOUT': 8, 'SEP': 9, 'SEPT': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
SHEET_RE = re.compile(r'^([A-Z]+)[\s._-]*(\d{2}|\d{4})?$')
CLOCK_RE = re.compile(r'^([0-9]{1,2})\s*[:hH]\s*([0-9]{2})$')   # ASCII digits (\d takes any script)
HEADER_SCAN_ROWS = 30
CLOCK_TOLERANCE_H = Decimal('0.01')  # 36 s: absorbs 0.33 h for 20 min, flags real gaps

# Severity: 'error' rows are never imported; 'warning' rows need an explicit
# include/exclude decision; 'info' is shown but needs nothing.
ISSUES = {
    'date_missing': ('error', 'Date absente'),
    'date_unparseable': ('error', 'Date illisible'),
    'project_missing': ('error', 'Projet absent'),
    'hours_missing': ('error', 'Durée déclarée absente'),
    'hours_unparseable': ('error', 'Durée déclarée illisible'),
    'hours_nonpositive': ('error', 'Durée nulle ou négative'),
    'formula_without_value': ('error', 'Formule sans valeur calculée dans le fichier'),
    'total_row': ('error', 'Ligne de total probable'),
    'project_unmapped': ('error', 'Projet source non associé'),
    'project_closed': ('error', 'Mandat clôturé : rouvrir le mandat ou choisir un autre projet'),
    'before_issued_invoice': ('error', 'Antérieure ou égale à une facture émise du projet'),
    'incomplete_time_pair': ('warning', 'Horaires incomplets (début ou fin manquant)'),
    'clock_unreadable': ('warning', 'Heure de début/fin illisible'),
    'clock_ambiguous': ('warning', 'Heure ambiguë (valeur < 1)'),
    'time_order_ambiguous': ('warning', 'Heure de fin ≤ heure de début'),
    'declared_vs_clock_mismatch': ('warning', 'Écart durée déclarée / durée calculée'),
    'date_outside_sheet_month': ('warning', "Date hors du mois de l'onglet"),
    'date_suspect': ('warning', 'Date suspecte (future ou hors plage)'),
    'hours_suspect': ('warning', 'Durée supérieure à 24 h'),
    'possible_existing_entry': ('warning', 'Prestation identique déjà présente en base'),
    'already_imported': ('error', 'Ligne déjà importée (lot non annulé), depuis ce fichier ou une copie du classeur : aucun doublon possible'),   # rc16 : bloquant, une décision « importer » ne peut pas créer de doublon
    # Decision Center billing-import-overwrite-scope = OVERWRITE_MATCHING (2026-10-07): a line matching an existing entry (same sheet and row, one living entry
    # imported from it, at least 4 of its 6 values unchanged) may overwrite that entry, by an explicit per-line « écraser » choice; never imported a second time
    'source_row_changed': ('warning', "Ligne déjà importée, modifiée depuis dans le classeur, et sa saisie existe : « écraser » remplace la saisie par la nouvelle valeur (correction tracée) ; sinon la saisie est conservée"),
    'entry_corrected_since_import': ('warning', "Ligne inchangée dans le classeur, mais sa saisie a été corrigée dans Billing depuis l'import : « écraser » rétablit la valeur du classeur (correction tracée) ; sinon la correction est conservée"),
    'overwrite_billed_entry': ('warning', "La saisie à écraser est facturée par une facture émise : la facture ne change pas ; un écart post-facturation sera affiché"),
    'source_row_ambiguous': ('error', "Plusieurs saisies existantes ont été importées depuis cette ligne : correspondance non déterministe, rien n'est écrasé ni importé"),
    'source_row_changed_entry_deleted': ('warning', 'Ligne déjà importée avec un autre contenu ; la saisie créée alors a été supprimée depuis'),
    'possible_already_imported': ('warning', 'Ligne identique déjà importée depuis une autre ligne du classeur (ligne insérée ou supprimée au-dessus ?)'),
    'previously_excluded': ('warning', "Ligne écartée volontairement lors d'un import précédent"),
    'year_differs_from_sheet': ('warning', "Année différente de celle de l'onglet (non corrigée)"),
    'duplicate_other_sheet': ('warning', "Copie exacte d'une saisie d'un autre onglet (jamais supprimée automatiquement)"),
    'time_overlap': ('warning', 'Plage horaire chevauchant une autre saisie du même jour'),
    'repeated_in_file': ('info', 'Ligne répétée dans le fichier (conservée)'),
    'clock_from_date_format': ('info', 'Heure stockée au format date Excel, relue comme heure décimale (valeur brute conservée)'),
    'manual_duration': ('info', 'Durée saisie sans horaires'),
    'hours_from_time_format': ('info', 'Durée lue depuis un format horaire'),
    'clock_rounded': ('info', 'Heure décimale arrondie à la minute'),
}


def severity(code):
    return ISSUES[code][0]


def _norm(v):
    s = '' if v is None else str(v)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', s).strip().lower()


def _text(v):
    return '' if v is None else str(v).strip()


def _raw(v):
    if v is None: return ''
    if isinstance(v, (datetime, date, time)): return v.isoformat()
    if isinstance(v, timedelta): return f'timedelta:{v.total_seconds()}'
    return str(v)


def sheet_period(title):
    m = SHEET_RE.match(_norm(title).upper())
    if not m or m.group(1) not in MONTHS: return None
    year = m.group(2)
    if year and len(year) == 2: year = '20' + year
    return MONTHS[m.group(1)], int(year) if year else None


def read_date(v):
    if v is None or _text(v) == '': return '', 'date_missing'
    if isinstance(v, datetime): return v.date().isoformat(), None
    if isinstance(v, date): return v.isoformat(), None
    if isinstance(v, str):
        for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y'):
            try: return datetime.strptime(v.strip(), fmt).date().isoformat(), None
            except ValueError: pass
    return '', 'date_unparseable'  # includes bare numbers: an Excel serial is never guessed


def _fmt_minutes(mins):
    return f'{mins // 60:02d}:{mins % 60:02d}'


def read_clock(v):
    """Return (HH:MM or '', issue or None, info or None)."""
    if v is None or _text(v) == '': return '', None, None
    if isinstance(v, datetime):
        if date(1900, 1, 2) <= v.date() < date(1900, 3, 1):
            # Excel serial n (1900 system) = decimal hour n typed into a date-formatted cell: 13.5 -> 1900-01-13 12:00.
            n = Decimal(int((v - datetime(1899, 12, 31)).total_seconds())) / Decimal(86400)
            if not 1 <= n < 24: return '', 'clock_unreadable', None
            mins = int((n * 60).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            return _fmt_minutes(mins), None, 'clock_from_date_format'
        if v.date() not in (date(1899, 12, 30), date(1899, 12, 31), date(1900, 1, 1)): return '', 'clock_unreadable', None
        v = v.time()
    if isinstance(v, time):
        s = _fmt_minutes(v.hour * 60 + v.minute)
        return (s + f':{v.second:02d}' if v.second else s), None, None
    if isinstance(v, str):
        m = CLOCK_RE.match(v.strip())
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            return f'{int(m.group(1)):02d}:{m.group(2)}', None, None
        return '', 'clock_unreadable', None
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        n = Decimal(str(v))
        if 0 <= n < 1: return '', 'clock_ambiguous', None  # Excel day fraction or decimal hour: not guessed
        if not 1 <= n < 24: return '', 'clock_unreadable', None
        exact = n * 60
        mins = int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return _fmt_minutes(mins), None, (None if exact == mins else 'clock_rounded')
    return '', 'clock_unreadable', None


def read_hours(v):
    """Return (Decimal or None, issue or None, info or None)."""
    if v is None or _text(v) == '': return None, 'hours_missing', None
    if isinstance(v, timedelta): return Decimal(str(v.total_seconds())) / 3600, None, 'hours_from_time_format'
    if isinstance(v, time): return Decimal(v.hour * 3600 + v.minute * 60 + v.second) / 3600, None, 'hours_from_time_format'
    if isinstance(v, str):
        m = CLOCK_RE.match(v.strip())
        if m: return Decimal(int(m.group(1)) * 60 + int(m.group(2))) / 60, None, 'hours_from_time_format'
        v = v.strip().replace(',', '.')
    if isinstance(v, bool): return None, 'hours_unparseable', None
    try: return Decimal(str(v)), None, None
    except (InvalidOperation, ValueError): return None, 'hours_unparseable', None


def _minutes(clock):
    p = [int(x) for x in clock.split(':')]
    return p[0] * 60 + p[1] + (p[2] / 60 if len(p) > 2 else 0)


def _header_year(rows):
    """Year of the first date found above the column header (cell B2 of the monthly sheets), or None."""
    for row in rows:
        for c in row:
            if isinstance(c, (datetime, date)) and not isinstance(c, time): return c.year
    return None


def _find_header(rows):
    for ri, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        norm = [_norm(x) for x in row]
        if ('date(s)' in norm or 'date' in norm) and 'projet' in norm and 'heures de travail' in norm:
            return ri, norm
    return None, None


def _flag_other_sheet_duplicates(rows, periods):
    """An identical entry present in two sheets: the copy outside its month's sheet is flagged for an explicit decision.
    Nothing is removed or merged; the original keeps its normal status."""
    groups = {}
    for r in rows:
        if r['work_date'] and 'total_row' not in r['issues']:
            groups.setdefault((r['work_date'], _norm(r['project_name']), r['start_time'], r['end_time'], r['hours'], _norm(r['description'])), []).append(r)
    for grp in groups.values():
        if len({r['source_sheet'] for r in grp}) < 2: continue
        def in_month(r):
            per = periods.get(r['source_sheet']); d = date.fromisoformat(r['work_date'])
            return bool(per) and d.month == per[0] and (not per[1] or d.year == per[1])
        keeper = next((r for r in grp if in_month(r)), grp[0])
        for r in grp:
            if r['source_sheet'] != keeper['source_sheet']:
                r['issues'].append('duplicate_other_sheet'); r['duplicate_of'] = f"{keeper['source_sheet']}!{keeper['source_row']}"


def _flag_overlaps(rows):
    """Two different entries of the same day whose time ranges intersect (all projects). Exact copies are not overlaps."""
    days = {}
    for r in rows:
        if r['work_date'] and r['start_time'] and r['end_time'] and 'total_row' not in r['issues']:
            days.setdefault(r['work_date'], []).append(r)
    ident = lambda r: (r['project_name'], r['start_time'], r['end_time'], r['hours'], r['description'])
    for lst in days.values():
        for i, a in enumerate(lst):
            for b in lst[i + 1:]:
                if ident(a) == ident(b): continue
                if _minutes(a['start_time']) < _minutes(b['end_time']) and _minutes(b['start_time']) < _minutes(a['end_time']):
                    for x in (a, b):
                        if 'time_overlap' not in x['issues']: x['issues'].append('time_overlap')


class WorkbookRefused(ValueError):
    """A workbook refused for a reason worth showing as is (never an internal error)."""


MAX_SHEET_ROWS = 20000  # a real month sheet has a few hundred rows; a bound protects the service from a hostile or accidental huge file


def parse_workbook(data, today=None):
    """Parse workbook bytes. Raises on unreadable files; never touches the DB."""
    from openpyxl import load_workbook
    today = today or datetime.now(ZoneInfo("Europe/Zurich")).date()
    values = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    formulas = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    rows_out, skipped, ignored_blank, periods = [], [], {}, {}
    for ws in values.worksheets:
        period = sheet_period(ws.title)
        if period is None:
            skipped.append({'sheet': ws.title, 'reason': 'onglet non mensuel'}); continue
        ws.reset_dimensions(); fws = formulas[ws.title]; fws.reset_dimensions()
        rows = list(islice(ws.iter_rows(values_only=True), MAX_SHEET_ROWS + 1)); frows = list(islice(fws.iter_rows(values_only=True), MAX_SHEET_ROWS + 1))
        if len(rows) > MAX_SHEET_ROWS: raise WorkbookRefused(f"onglet {ws.title!r} : plus de {MAX_SHEET_ROWS} lignes (classeur refusé, aucun import préparé)")
        hi, headers = _find_header(rows)
        if hi is not None and period[1] is None:
            period = (period[0], _header_year(rows[:hi]))  # sheets titled « JAN » carry the year in their header date
        periods[ws.title] = period
        if hi is None:
            skipped.append({'sheet': ws.title, 'reason': 'en-tête Date(s) / Projet / Heures de travail introuvable'}); continue
        def col(*names):
            return next((headers.index(n) for n in names if n in headers), None)
        cols = {'date': col('date(s)', 'date'), 'description': col('motif', 'description'), 'project': col('projet'),
                'start': col('heure debut', 'debut'), 'end': col('heure fin', 'fin'), 'hours': col('heures de travail')}
        for offset, row in enumerate(rows[hi + 1:], start=hi + 1):
            frow = frows[offset] if offset < len(frows) else ()
            def val(k, src=row):
                i = cols[k]
                return src[i] if i is not None and i < len(src) else None
            cells = {k: val(k) for k in cols}
            if all(c is None or _text(c) == '' for c in cells.values()): continue
            if all(_text(cells[k]) == '' for k in ('date', 'description', 'project', 'start', 'end')) and _text(cells['hours']) in ('', '0', '0.0'):
                ignored_blank[ws.title] = ignored_blank.get(ws.title, 0) + 1  # empty template row (duration formula = 0), counted not hidden
                continue
            issues, infos = [], []
            work_date, di = read_date(cells['date'])
            if di: issues.append(di)
            project = _text(cells['project'])
            if not project: issues.append('project_missing')
            hours, hi_issue, hi_info = read_hours(cells['hours'])
            if hi_issue: issues.append(hi_issue)
            if hi_info: infos.append(hi_info)
            if hours is not None and hours <= 0: issues.append('hours_nonpositive')
            if hours is not None and hours > 24: issues.append('hours_suspect')
            for k in ('hours', 'date'):
                fv = val(k, frow)
                if cells[k] is None and isinstance(fv, str) and fv.startswith('='): issues.append('formula_without_value')
            if any('total' in _norm(cells[k]) for k in ('date', 'description', 'project')) and not work_date:
                issues.append('total_row')
            # Unlabelled subtotal inside the table (> 24 h, no project, no motive, no clock): a total, not an entry.
            if (hours is not None and hours > 24 and not project and not _text(cells['description'])
                    and not _text(cells['start']) and not _text(cells['end']) and 'total_row' not in issues):
                issues.append('total_row')
            if 'total_row' in issues:
                issues = ['total_row']  # the other findings (no date, no project...) only restate that this is not an entry
            start, si, sinfo = read_clock(cells['start']); end, ei, einfo = read_clock(cells['end'])
            for x in (si, ei):
                if x and x not in issues: issues.append(x)
            for x in (sinfo, einfo):
                if x and x not in infos: infos.append(x)
            has_start = _text(cells['start']) != ''; has_end = _text(cells['end']) != ''
            if has_start != has_end: issues.append('incomplete_time_pair')
            if not has_start and not has_end: infos.append('manual_duration')
            clock_hours = ''
            if start and end:
                elapsed = Decimal(str(_minutes(end) - _minutes(start))) / 60
                if elapsed <= 0: issues.append('time_order_ambiguous')
                else:
                    clock_hours = str(elapsed.quantize(Decimal('0.0001')))
                    if hours is not None and abs(elapsed - hours) > CLOCK_TOLERANCE_H: issues.append('declared_vs_clock_mismatch')
            if work_date:
                d = date.fromisoformat(work_date)
                month, year = period
                if year and d.year != year: issues.append('year_differs_from_sheet')  # reported, never corrected (2015 stays 2015)
                elif d.month != month: issues.append('date_outside_sheet_month')
                if d > today or d.year < 2000: issues.append('date_suspect')
            rows_out.append({
                'idx': len(rows_out), 'source_sheet': ws.title, 'source_row': offset + 1,
                'raw': {k: _raw(v) for k, v in cells.items()},
                'work_date': work_date, 'project_name': project, 'description': _text(cells['description']),
                'start_time': start, 'end_time': end,
                'hours': (format(hours.normalize(), 'f') if hours is not None else ''),
                'clock_hours': clock_hours, 'issues': issues + infos,
            })
    keys = {}
    for r in rows_out:
        if 'total_row' in r['issues']: continue  # a total/subtotal cell is not an entry: two identical subtotals are not a repeated entry
        k = (r['work_date'], r['project_name'], r['start_time'], r['end_time'], r['hours'], r['description'])
        keys.setdefault(k, []).append(r)
    for group in keys.values():
        if len(group) > 1:
            for r in group: r['issues'].append('repeated_in_file')
            seen = {}
            for r in group:  # later occurrence of an exact repeat inside ONE sheet: candidate for a proposal only, nothing is excluded here
                if r['source_sheet'] in seen: r['repeat_of'] = seen[r['source_sheet']]
                else: seen[r['source_sheet']] = f"{r['source_sheet']}!{r['source_row']}"
    _flag_other_sheet_duplicates(rows_out, periods)
    _flag_overlaps(rows_out)
    return {'sheets': values.sheetnames, 'rows': rows_out, 'skipped_sheets': skipped, 'ignored_blank_rows': ignored_blank}


def _line_key(raw):
    """Identity of a source line by its cell values (stored raw_json of the batch ledger, or the raw of a parsed row): a re-saved or
    extended copy of the workbook yields the same key, whatever its sha256."""
    if isinstance(raw, str): raw = json.loads(raw or '{}')
    def num(v):       # 0.8000000000000007 (17 digits, Excel) and 0.800000000000001 (15 digits, LibreOffice) are the same cell; '2' and '2.0' too
        if re.fullmatch(r'-?[0-9]+(\.[0-9]+)?([eE]-?[0-9]+)?', v or ''):
            try: return format(Decimal(v).quantize(Decimal('0.000001')).normalize(), 'f')
            except InvalidOperation: return v
        return v
    day = raw.get('date', '')
    if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T00:00:00', day or ''): day = day[:10]      # a date cell read as date or as datetime
    return (day, _norm(raw.get('project', '')), num(raw.get('start', '')), num(raw.get('end', '')), num(raw.get('hours', '')), _norm(raw.get('description', '')))


def _imported_lines(conn):
    """Lines of the COMMITTED batches (a rolled-back batch no longer counts): imported ones by position and by content (and the positions whose entry
    still exists), explicitly excluded ones by position and by content. OVERWRITE_MATCHING: for each position, its living entries with the key of the
    LAST line written into them (import, then each overwrite, in batch-row order)."""
    by_pos, by_content, excluded, excluded_content, alive, living, content_pos = {}, set(), {}, set(), set(), {}, {}
    for x in conn.execute("""SELECT ir.source_sheet,ir.source_row,ir.raw_json,ir.decision,ir.entry_id,e.id,e.source_ref FROM import_batch_rows ir
                             JOIN import_batches b ON b.id=ir.batch_id LEFT JOIN entries e ON e.id=ir.entry_id WHERE b.status='COMMITTED' ORDER BY ir.id"""):
        k = _line_key(x[2])
        if x[4] is not None:
            by_pos.setdefault((x[0], x[1]), set()).add(k); by_content.add(k); content_pos.setdefault(k, set()).add((x[0], x[1]))
            if x[5] is not None:
                alive.add((x[0], x[1]))
                # an entry counts for the overwrite only while it still carries the provenance of this line (an id reused before rc19 does not)
                if x[6] == f"{x[0]}!{x[1]}": living.setdefault((x[0], x[1]), {})[x[5]] = k
        elif x[3] == 'exclude':
            excluded.setdefault((x[0], x[1]), set()).add(k); excluded_content.add(k)
    return by_pos, by_content, excluded, excluded_content, alive, living, content_pos


def _same_line_edited(key, mkey):
    """The same workbook line edited: of its 4 elements — date, project, times and duration (together), description — at most one differs, and
    the ones kept are not empty on both sides (two blank cells prove nothing)."""
    parts = lambda k: (k[0], k[1], (k[2], k[3], k[4]), k[5])
    a, b = parts(key), parts(mkey)
    kept = [x for x, y in zip(a, b) if x == y and x not in ('', ('', '', ''))]
    return sum(x != y for x, y in zip(a, b)) <= 1 and len(kept) >= 2


OVERWRITE_ISSUES = ('source_row_changed', 'entry_corrected_since_import')


def entry_state(e):
    """Values of an entry that an overwrite replaces (and the version token of the preview: an entry edited since changes the fingerprint)."""
    return [e['work_date'], e['project_id'], e['start_time'] or '', e['end_time'] or '', e['hours'], e['description'] or '']


def _corrected_since_import(conn, e, r, pid):
    """The living entry of an unchanged line no longer holds the line's values: one of its 5 values differs, or it sits on another mandate than the
    one the line is mapped to AND a correction was recorded (a mere other mapping of the re-imported file is not a correction made in Billing)."""
    if (e['work_date'], e['start_time'] or '', e['end_time'] or '', e['description'] or '') != (r['work_date'], r['start_time'] or '', r['end_time'] or '', r['description'] or '') \
            or abs(float(e['hours']) - float(r['hours'] or 0)) >= 1e-9:
        return True
    return e['project_id'] != pid and conn.execute("SELECT 1 FROM entry_changes WHERE entry_id=? AND action='update' LIMIT 1", (e['id'],)).fetchone() is not None


def validate(conn, payload, mapping, decisions):
    """Combine static issues with DB-dependent checks. Pure read; returns rows + summary.

    mapping: {project_name: '' | 'skip' | '<project id>'}; decisions: {idx(str): 'include'|'exclude'}.
    """
    projects = {str(r['id']): r['name'] for r in conn.execute('SELECT id,name FROM projects')}
    closed = {r['id'] for r in conn.execute('SELECT id FROM projects WHERE active=0')}
    issued = {r['project_id']: r['last'] for r in conn.execute(
        "SELECT project_id, MAX(period_to) last FROM invoices WHERE status='issued' GROUP BY project_id")}
    out, counts = [], {}
    imported_pos, imported_content, excluded_pos, excluded_content, alive_pos, living, content_pos = _imported_lines(conn)
    file_pos = {}                                          # where each line content sits in THIS file (detects rows inserted / removed above)
    for x in payload['rows']: file_pos.setdefault(_line_key(x['raw']), set()).add((x['source_sheet'], x['source_row']))
    for r in payload['rows']:
        issues = list(r['issues'])
        target = mapping.get(r['project_name'], '') if r['project_name'] else ''
        pid = int(target) if target in projects else None
        if r['project_name'] and target != 'skip' and pid is None: issues.append('project_unmapped')
        if pid in closed: issues.append('project_closed')
        # OVERWRITE_MATCHING: the entry this line matches, if any. Deterministic: same sheet and row, exactly one living entry imported from it, and either
        # the same values or the same line edited (_same_line_edited) with no sign of a shift: this content was not imported from another row, and the
        # entry's current line does not sit at another row of this file (a row inserted or removed above never overwrites its neighbour's entry).
        pos, key = (r['source_sheet'], r['source_row']), _line_key(r['raw'])
        here = living.get(pos, {}); match = None
        if len(here) == 1:
            mid, mkey = next(iter(here.items()))
            shifted = any(p != pos for p in content_pos.get(key, ())) or any(p != pos for p in file_pos.get(mkey, ()))
            if key == mkey or (not shifted and _same_line_edited(key, mkey)): match = (mid, mkey)
        if pid is not None and r['work_date'] and pid in issued and r['work_date'] <= issued[pid]: issues.append('before_issued_invoice')
        # rc16 + G4: a line already imported is recognised by its source line (sheet, row, cell values), not only by the sha256 of the file: a re-saved or
        # completed copy of the workbook cannot import it again, and a line corrected in the application since its import does not come back with its old value.
        match_entry = None
        if 'total_row' not in issues and len(here) > 1 and any(key == k or _same_line_edited(key, k) for k in here.values()):
            issues.append('source_row_ambiguous')
        elif 'total_row' not in issues and match and key == match[1]:
            e = conn.execute('SELECT * FROM entries WHERE id=?', (match[0],)).fetchone()
            if pid is not None and _corrected_since_import(conn, e, r, pid): issues.append('entry_corrected_since_import'); match_entry = e
            else: issues.append('already_imported')
        elif 'total_row' not in issues and match:
            e = conn.execute('SELECT * FROM entries WHERE id=?', (match[0],)).fetchone()
            if pid is not None and (e['project_id'] != pid or _corrected_since_import(conn, e, r, e['project_id'])):
                issues.append('source_row_changed'); match_entry = e      # the same line edited in the workbook since, its entry still there
            else: issues.append('already_imported')                       # other cell text, same values read: nothing to overwrite
        elif 'total_row' not in issues:
            if (key in imported_pos.get(pos, ()) or (key in imported_content and r['start_time'] and r['end_time'])
                    or conn.execute("""SELECT 1 FROM import_batch_rows ir JOIN import_batches b ON b.id=ir.batch_id
                                       WHERE b.status='COMMITTED' AND b.file_sha256=? AND ir.source_sheet=? AND ir.source_row=? AND ir.entry_id IS NOT NULL LIMIT 1""",
                                    (payload['file_sha256'], r['source_sheet'], r['source_row'])).fetchone()):
                issues.append('already_imported')
            elif pos in imported_pos and pos not in alive_pos:
                issues.append('source_row_changed_entry_deleted')   # the way to import a corrected line again: delete its entry first (traced)
            elif key in imported_content:
                issues.append('possible_already_imported')          # an unclocked line already imported from another row (row inserted or removed above)
            elif key in excluded_pos.get(pos, ()) or (key in excluded_content and r['start_time'] and r['end_time']):
                issues.append('previously_excluded')
        if pid is not None and r['work_date'] and r['hours']:
            # same date, clock and duration: on the chosen mandate, or on ANY mandate when the line has a clock (one person cannot work twice in the same
            # slot); the entry this line would overwrite is not a duplicate of it
            clocked = bool(r['start_time'] and r['end_time'])
            if conn.execute('SELECT 1 FROM entries WHERE work_date=? AND ABS(hours-?)<1e-9 AND start_time=? AND end_time=? AND id IS NOT ?' + ('' if clocked else ' AND project_id=?') + ' LIMIT 1',
                            (r['work_date'], float(r['hours']), r['start_time'], r['end_time'], match_entry['id'] if match_entry is not None else None) + (() if clocked else (pid,))).fetchone():
                issues.append('possible_existing_entry')
        if match_entry is not None and any(i in OVERWRITE_ISSUES for i in issues):
            from app import post_billing
            if any(x['role'] == 'billed' for x in post_billing.entry_invoices(conn, match_entry['id'])): issues.append('overwrite_billed_entry')
            r = dict(r, match_entry_id=match_entry['id'], match_state=entry_state(match_entry), match_project=projects.get(str(match_entry['project_id']), ''))
        sev = {severity(i) for i in issues}
        decision = decisions.get(str(r['idx']), '')
        if target == 'skip': status = 'excluded_project'
        elif 'error' in sev: status = 'error'
        elif any(i in OVERWRITE_ISSUES for i in issues): status = 'overwrite' if decision == 'overwrite' else 'keep'   # never by default
        elif 'warning' in sev: status = decision if decision in ('include', 'exclude') else 'needs_decision'
        elif decision == 'exclude': status = 'exclude'  # a valid row the user explicitly chose not to import (e.g. one occurrence of an exact pair)
        else: status = 'ok'
        for i in issues: counts[i] = counts.get(i, 0) + 1
        proposal = ''
        if r.get('duplicate_of') and 'duplicate_other_sheet' in issues: proposal = f"ne pas importer : copie de {r['duplicate_of']} (arbitrage 1)"
        elif r.get('repeat_of'): proposal = f"ne pas importer cette occurrence : répétition exacte de {r['repeat_of']} (une par paire, à valider)"
        out.append(dict(r, issues=issues, status=status, project_id=pid, anomaly=any(severity(i) != 'info' for i in issues),
                        project_label=projects.get(str(pid), '') if pid else '', proposal=proposal, decision=decision))
    by_status = {}
    for r in out: by_status[r['status']] = by_status.get(r['status'], 0) + 1
    importable = [r for r in out if r['status'] in ('ok', 'include')]
    def _fmt(d):  # display of sums: rounded to the hundredth, so Excel float noise (0.8000000000000007) never shows; row values stay untouched
        return format(d.quantize(Decimal('0.01')).normalize(), 'f')
    names = payload['project_names']
    summary = {
        'total': len(out), 'importable': len(importable), 'by_status': by_status,
        'issue_counts': dict(sorted(counts.items(), key=lambda kv: (['error', 'warning', 'info'].index(severity(kv[0])), kv[0]))),
        'anomalies': sum(1 for r in out if r['anomaly']),
        'unmapped_projects': [n for n in names if mapping.get(n, '') not in projects and mapping.get(n, '') != 'skip'],
        'hours_importable': _fmt(sum((Decimal(r['hours']) for r in importable), Decimal(0))),
    }
    def _hours(rs): return sum((Decimal(r['hours']) for r in rs if r['hours']), Decimal(0))
    summary['hours_by_status'] = {k: _fmt(_hours([r for r in out if r['status'] == k])) for k in by_status}
    summary['hours_importable_by_year'] = {}
    summary['hours_importable_by_project'] = {}
    yh, ph = {}, {}
    for r in importable:
        y = r['work_date'][:4] if r['work_date'] else '—'
        yh[y] = yh.get(y, Decimal(0)) + Decimal(r['hours']); summary['hours_importable_by_year'][y] = _fmt(yh[y])
        ph[r['project_name']] = ph.get(r['project_name'], Decimal(0)) + Decimal(r['hours']); summary['hours_importable_by_project'][r['project_name']] = _fmt(ph[r['project_name']])
    summary['overwrites'] = sum(1 for r in out if r['status'] == 'overwrite')
    summary['fingerprint'] = hashlib.sha256(json.dumps(
        [[r['idx'], r['status'], sorted(r['issues']), r['project_id']] + ([r['match_entry_id'], r['match_state']] if r.get('match_entry_id') else []) for r in out],
        sort_keys=True).encode()).hexdigest()
    return out, summary


CATEGORY_ORDER = [('source_row_changed', 'A13 Ligne modifiée dans le classeur : saisie existante (écraser / conserver)'),
                  ('entry_corrected_since_import', "A14 Saisie corrigée dans Billing depuis l'import (écraser / conserver)"),
                  ('possible_already_imported', 'A12 Ligne identique déjà importée depuis une autre ligne'),
                  ('source_row_changed_entry_deleted', 'A10 Ligne déjà importée, modifiée depuis dans le classeur (saisie supprimée)'), ('previously_excluded', "A11 Écartée lors d'un import précédent"),
                  ('year_differs_from_sheet', "A1 Année différente de l'onglet"), ('date_suspect', 'A2 Date future ou hors plage'),
                  ('duplicate_other_sheet', "A3 Copie d'une saisie d'un autre onglet"), ('declared_vs_clock_mismatch', 'A4 Durée déclarée ≠ calculée'),
                  ('clock_unreadable', 'A5 Heure illisible'), ('date_outside_sheet_month', "A6 Date hors du mois de l'onglet"),
                  ('time_overlap', 'A7 Chevauchement horaire'), ('time_order_ambiguous', 'A8 Fin ≤ début'), ('incomplete_time_pair', 'A9 Horaires incomplets')]


def classify(r):
    """(category, subcategory) of a validated row: total_ou_sous_total | bloquante | a_arbitrer | valide | exclue_projet."""
    if 'total_row' in r['issues']: return 'total_ou_sous_total', ''
    if r['status'] == 'excluded_project': return 'exclue_projet', ''
    errors = [i for i in r['issues'] if severity(i) == 'error' and i != 'project_unmapped']  # unmapped is a mapping step, not a data defect
    if errors: return 'bloquante', ', '.join(errors)
    if any(severity(i) == 'warning' for i in r['issues']):
        for code, label in CATEGORY_ORDER:
            if code in r['issues']: return 'a_arbitrer', label
        return 'a_arbitrer', 'A0 Autre'
    return 'valide', ''


def fmt_hours(d):
    return format(Decimal(d).quantize(Decimal('0.01')).normalize(), 'f')


def suggest_mapping(source_names, projects):
    """Proposals only: source name -> existing projects whose normalised name is equal, or one is a whole-word prefix of the other.
    Nothing is selected for the user; every association stays an explicit, editable choice until the batch is committed."""
    out = {}
    for n in source_names:
        a = _norm(n)
        out[n] = [p['name'] for p in projects if (b := _norm(p['name'])) and (a == b or a.startswith(b + ' ') or b.startswith(a + ' '))]
    return out
