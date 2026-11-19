"""Aller-retour des formulaires de modification (condition G4 : toute donnée reste corrigeable après la bascule).

Pour chaque saisie, chaque mandat, chaque brouillon de facture et les paramètres de l'émetteur : ouvre le formulaire de modification et le renvoie
INCHANGÉ, comme un navigateur (champs désactivés par la page exclus, retours à la ligne retirés des champs d'une ligne, cases non cochées
absentes). Attendu : aucun refus, et aucune valeur métier modifiée (comparaison de la base avant / après, hors horodatages techniques).
À lancer UNIQUEMENT contre un conteneur jetable sur une COPIE de base (les envois écrivent dans la base) — jamais le staging réel.

Usage : python3 -I outils/aller_retour_formulaires.py BASE_URL FICHIER_MOT_DE_PASSE COPIE_DB [JOURNAL]
"""
import html.parser, http.cookiejar, json, re, sqlite3, sys, urllib.parse, urllib.request

BASE, PWFILE, DB = sys.argv[1].rstrip('/'), sys.argv[2], sys.argv[3]
LOG = open(sys.argv[4], 'w', encoding='utf-8') if len(sys.argv) > 4 else sys.stdout
ONE_LINE = {'text', 'search', 'tel', 'url', 'password', 'email', ''}


class Form(html.parser.HTMLParser):
    """Champs envoyés par un navigateur pour le formulaire n° `index` (ou d'id `fid`) de la page."""
    def __init__(self, fid=None, action=None, here=None):
        super().__init__(convert_charrefs=True); self.fid, self.action, self.here = fid, action, here
        self.depth = 0; self.fields = []; self.found = False; self.sel = None; self.ta = None; self.opts = []

    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == 'form' and not self.found and ((self.fid and a.get('id') == self.fid) or (self.action and a.get('action') == self.action)
                                                 or (self.here and (a.get('method') or '').lower() == 'post' and a.get('action') in (None, '', self.here))):
            self.found = True; self.depth = 1; return
        if not self.depth: return
        if tag == 'form': self.depth += 1
        if 'disabled' in a: return
        if tag == 'input' and a.get('name'):
            t = (a.get('type') or 'text').lower(); v = a.get('value') or ''
            if t in ('checkbox', 'radio'):
                if 'checked' in a: self.fields.append((a['name'], v or 'on'))
            elif t == 'file': pass
            elif t in ONE_LINE: self.fields.append((a['name'], re.sub(r'[\r\n]', '', v)))
            else: self.fields.append((a['name'], v))
        elif tag == 'select' and a.get('name'): self.sel = a['name']; self.opts = []
        elif tag == 'option' and self.sel: self.opts.append((a.get('value', ''), 'selected' in a))
        elif tag == 'textarea' and a.get('name'): self.ta = [a['name'], '']

    def handle_data(self, d):
        if self.ta: self.ta[1] += d

    def handle_endtag(self, tag):
        if not self.depth: return
        if tag == 'select' and self.sel:
            chosen = [v for v, s in self.opts if s] or [v for v, _ in self.opts[:1]]
            if chosen: self.fields.append((self.sel, chosen[0]))
            self.sel = None
        elif tag == 'textarea' and self.ta:
            v = self.ta[1][1:] if self.ta[1].startswith('\n') else self.ta[1]
            self.fields.append((self.ta[0], v.replace('\r\n', '\n').replace('\n', '\r\n'))); self.ta = None
        elif tag == 'form': self.depth -= 1


jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a): return None


op_nr = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)


def get(path): return op.open(BASE + path).read().decode()


def post(path, fields):
    data = urllib.parse.urlencode(fields).encode()
    try:
        r = op_nr.open(urllib.request.Request(BASE + path, data=data)); return r.status, r.read().decode(), ''
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers.get('Location', '')


def flashes(page): return [re.sub(r'<[^>]+>', '', m).strip() for m in re.findall(r'class="msg[^"]*"[^>]*>(.*?)</', page, re.S)]


def form(page, **k):
    f = Form(**k); f.feed(page); return f.fields if f.found else None


def snapshot(stamps=False):
    """stamps=True : horodatages compris (procedure/90-rollback compare toutes les colonnes : une ligne réécrite à l'identique y compte « modifiée »)"""
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True); c.row_factory = sqlite3.Row
    try:
        out = {}
        for t in ('entries', 'projects', 'invoices', 'invoice_lines', 'settings', 'historical_invoices'):
            try: rows = c.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall()
            except sqlite3.OperationalError: continue
            out[t] = [{k: r[k] for k in r.keys() if stamps or not re.search(r'(_at|updated|modified)$', k)} for r in rows]
        out['entry_changes'] = c.execute('SELECT COUNT(*) FROM entry_changes').fetchone()[0]
        return out
    finally: c.close()


def ids(q):
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    try: return [r[0] for r in c.execute(q)]
    finally: c.close()


pw = open(PWFILE).read().strip()
login = get('/login')
lf = Form(); lf.found = True; lf.depth = 1; lf.feed(login)
fields = dict(lf.fields); fields.update(username='admin', password=pw)
post('/login', fields)
before = snapshot(); before_st = snapshot(True); problems = []; n = {}


def roundtrip(kind, path, fid=None, action=None, ok_codes=(302, 303)):
    page = get(path); f = form(page, fid=fid, action=action, here=None if (fid or action) else path)
    if f is None: problems.append((kind, path, 'formulaire introuvable')); return
    fd = dict(f)
    if kind == 'saisie':   # comme le script de la page : un seul mode envoyé
        f = [(k, v) for k, v in f if not (k == 'manual_hours' and fd.get('entry_mode') == 'clock') and not (k in ('start_time', 'end_time') and fd.get('entry_mode') == 'duration')]
    st, body, loc = post(action or path, f)
    msgs = flashes(get(path)) if st in (302, 303) else flashes(body)   # message affiché sur la page suivante (même formulaire, page légère)
    bad = st not in ok_codes or any(re.search(r'refus|non modifi|non enregistr|invalide|obligatoire|erreur|non calculés', m, re.I) for m in msgs)
    n[kind] = n.get(kind, 0) + 1
    if bad: problems.append((kind, path, st, msgs[:3]))


for eid in ids('SELECT id FROM entries ORDER BY id'): roundtrip('saisie', f'/entry/{eid}/edit', fid='entryEditForm')
for pid in ids('SELECT id FROM projects ORDER BY id'): roundtrip('mandat', f'/project/{pid}/edit')
for iid in ids("SELECT id FROM invoices WHERE status='draft' ORDER BY id"): roundtrip('brouillon', f'/invoice/{iid}/edit')
roundtrip('paramètres', '/?tab=settings', action='/settings')   # émetteur (adresse multiligne) et options de facturation ; logo : champ fichier vide, conservé
after = snapshot(); after_st = snapshot(True)
def _rows(snap, t): return {json.dumps(r, sort_keys=True, default=str) for r in snap[t]}
# lignes dont seul un horodatage diffère (valeurs métier identiques), toutes tables, y compris celles où d'autres lignes ont changé
stamps_only = {t: k for t in before_st if isinstance(before_st[t], list)
               if (k := len(_rows(before_st, t) - _rows(after_st, t)) - len(_rows(before, t) - _rows(after, t)))}
diff = {}
for t in before:
    if before[t] != after[t]:
        if isinstance(before[t], list):
            b = {json.dumps(r, sort_keys=True, default=str) for r in before[t]}; a = {json.dumps(r, sort_keys=True, default=str) for r in after[t]}
            diff[t] = {'avant': sorted(b - a)[:5], 'après': sorted(a - b)[:5], 'n': len(b ^ a)}
        else: diff[t] = (before[t], after[t])
print(json.dumps({'formulaires': n, 'refus': problems[:50], 'n_refus': len(problems), 'valeurs_modifiees': diff, 'horodatages_seuls_modifies': stamps_only}, ensure_ascii=False, indent=1, default=str), file=LOG)
print(f"formulaires {n} ; refus {len(problems)} ; tables modifiées {sorted(diff)} ; lignes réécrites à l'identique (horodatage seul, vues « modifiées » par 90-rollback) {stamps_only}")
sys.exit(1 if problems or diff or stamps_only else 0)
