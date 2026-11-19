"""Minimal stdlib reader of an .xlsx: returns, per sheet, {row_number: {col_letter: (type, raw_text, numfmt)}}.
type: 'n' number, 's' shared string, 'str' formula string, 'inlineStr', 'b' bool, 'e' error.
Never writes anything. Usage as module: read_cells(path)."""
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'pr': 'http://schemas.openxmlformats.org/package/2006/relationships'}


def _col(ref):
    return re.match(r'([A-Z]+)', ref).group(1)


def col_index(letters):
    n = 0
    for ch in letters: n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_cells(path):
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    rid2t = {r.get('Id'): r.get('Target') for r in rels.findall('pr:Relationship', NS)}
    ss = []
    if 'xl/sharedStrings.xml' in z.namelist():
        for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS):
            ss.append(''.join(t.text or '' for t in si.iter('{%s}t' % NS['m'])))
    fmts = []
    custom = {}
    if 'xl/styles.xml' in z.namelist():
        st = ET.fromstring(z.read('xl/styles.xml'))
        nf = st.find('m:numFmts', NS)
        if nf is not None:
            for f in nf.findall('m:numFmt', NS): custom[int(f.get('numFmtId'))] = f.get('formatCode')
        xfs = st.find('m:cellXfs', NS)
        if xfs is not None:
            for xf in xfs.findall('m:xf', NS): fmts.append(int(xf.get('numFmtId', 0)))
    out = {}
    for s in wb.find('m:sheets', NS).findall('m:sheet', NS):
        name = s.get('name'); rid = s.get('{%s}id' % NS['r'])
        target = rid2t[rid]
        target = target.lstrip('/')
        if not target.startswith('xl/'): target = 'xl/' + target
        root = ET.fromstring(z.read(target))
        rows = {}
        for row in root.iter('{%s}row' % NS['m']):
            rn = int(row.get('r'))
            cells = {}
            for c in row.findall('m:c', NS):
                t = c.get('t', 'n'); sidx = int(c.get('s', 0))
                v = c.find('m:v', NS)
                f = c.find('m:f', NS)
                if t == 'inlineStr':
                    txt = ''.join(x.text or '' for x in c.iter('{%s}t' % NS['m']))
                elif v is None:
                    txt = None
                elif t == 's':
                    txt = ss[int(v.text)]
                else:
                    txt = v.text
                fid = fmts[sidx] if sidx < len(fmts) else 0
                cells[_col(c.get('r'))] = (t, txt, fid, custom.get(fid), f is not None)
            rows[rn] = cells
        out[name] = rows
    return out
