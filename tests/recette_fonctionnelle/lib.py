"""Bibliothèque de la recette fonctionnelle staging : client HTTP (cookies, redirections suivies à la main, messages flash), lecture SQLite seule, rapport de résultats.
S'exécute SUR L'HÔTE contre un conteneur jetable monté sur une COPIE de la base staging. Jamais contre le staging réel."""
import http.cookiejar, urllib.parse, urllib.request, uuid, re, html, sqlite3, json, os, sys, hashlib, subprocess, tempfile
from decimal import Decimal as D, ROUND_HALF_UP

CENT = D('0.01')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None

class App:
    def __init__(self, port, pwfile, db):
        self.base = f'http://127.0.0.1:{port}'; self.db = db; self.pw = open(pwfile).read().strip()
        self.jar = http.cookiejar.CookieJar(); self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)
    def req(self, path, data=None, files=None, method=None):
        headers = {}; body = None
        if files:
            b = uuid.uuid4().hex; body = b''
            for k, v in (data or {}).items(): body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, (fn, content) in files.items(): body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b'\r\n'
            body += f'--{b}--\r\n'.encode(); headers['Content-Type'] = f'multipart/form-data; boundary={b}'
        elif data is not None: body = urllib.parse.urlencode(data, doseq=True).encode()
        try:
            r = self.op.open(urllib.request.Request(self.base + path, data=body, headers=headers, method=method)); return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e: return e.code, e.headers, e.read()
    def get(self, path): return self.req(path)[2].decode('utf-8', 'replace')
    def login(self):
        s, h, _ = self.req('/login', {'username': 'admin', 'password': self.pw}); return s == 302 and '/login' not in (h.get('Location') or '')
    def post(self, path, data=None, files=None):
        """POST puis lecture de la page de redirection : renvoie (statut, [messages flash])."""
        s, h, b = self.req(path, data if data is not None else {}, files)
        loc = h.get('Location'); page = b.decode('utf-8', 'replace'); msgs = []
        for _ in range(4):                       # suit jusqu'à 4 redirections en cumulant les messages flash
            msgs += flashes(page)
            if not loc: break
            s2, h2, b2 = self.req(loc.replace(self.base, '')); page = b2.decode('utf-8', 'replace'); loc = h2.get('Location') if s2 in (301, 302, 303) else None
        msgs += flashes(page) if loc is None and page else []
        return s, list(dict.fromkeys(msgs))
    def q(self, sql, a=()):
        c = sqlite3.connect(f'file:{self.db}?mode=ro', uri=True)
        try: return c.execute(sql, a).fetchall()
        finally: c.close()
    def one(self, sql, a=()):
        r = self.q(sql, a); return r[0][0] if r else None

def flashes(page):
    return [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', m))).strip() for m in re.findall(r'<div class="msg[^"]*"[^>]*>(.*?)</div>', page, re.S)]

class Report:
    def __init__(self, name): self.name = name; self.rows = []; self.section = ''
    def sec(self, s): self.section = s; print(f'\n## {s}')
    def check(self, name, cond, detail=''):
        self.rows.append({'section': self.section, 'test': name, 'ok': bool(cond), 'detail': '' if cond else str(detail)[:600]})
        print(('PASS ' if cond else 'FAIL ') + name + (f' — {detail}' if (detail and not cond) else ''))
    def has(self, name, msgs, needle, extra=''):
        t = ' | '.join(msgs); self.check(name, needle.lower() in t.lower(), f'attendu « {needle} » dans {t[:400]} {extra}')
    def summary(self):
        ok = sum(r['ok'] for r in self.rows); ko = [r for r in self.rows if not r['ok']]
        print(f'\nRÉSULTAT {self.name} : {ok}/{len(self.rows)} OK, {len(ko)} KO')
        for r in ko: print('  KO', r['section'], '|', r['test'], '|', r['detail'][:200])
        return ok, ko

def money(x): return D(str(x)).quantize(CENT, ROUND_HALF_UP)
def amounts(qty, rate, vat, other=0, mode='hors_tva'):
    ht = money(D(str(qty)) * D(str(rate))); oth = money(other); base = ht + oth if mode == 'soumis' else ht
    tva = money(base * D(str(vat)) / 100); return {'ht': ht, 'tva': tva, 'other': oth, 'ttc': ht + tva + oth}
def fr(d, places=2):
    d = D(str(d)).quantize(D(1).scaleb(-places), ROUND_HALF_UP); return f'{abs(d):,.{places}f}'.replace(',', ' ').replace('.', ',')
def pdf_text(data):
    f = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False); f.write(data); f.close()
    try: return subprocess.run(['pdftotext', '-layout', f.name, '-'], capture_output=True, text=True).stdout
    finally: os.unlink(f.name)
def squash(t): return re.sub(r'[\s  ]+', '', t)
def pdfinfo(data):
    f = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False); f.write(data); f.close()
    try:
        i = subprocess.run(['pdfinfo', f.name], capture_output=True, text=True).stdout; fo = subprocess.run(['pdffonts', f.name], capture_output=True, text=True).stdout
        return i, fo
    finally: os.unlink(f.name)
def sha(b): return hashlib.sha256(b).hexdigest()
def entries_digest(db, only_import=False):
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        rs = c.execute("select e.work_date,p.name,e.start_time,e.end_time,printf('%.4f',e.hours),e.description,e.source,e.source_ref from entries e join projects p on p.id=e.project_id " +
                       ("where e.import_batch_id is not null " if only_import else "") + "order by e.source_ref,e.work_date,p.name,e.start_time,e.end_time,e.description").fetchall()
        return hashlib.sha256(json.dumps([list(r) for r in rs]).encode()).hexdigest(), len(rs), round(sum(float(r[4]) for r in rs), 4)
    finally: c.close()
