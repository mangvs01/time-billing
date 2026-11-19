"""Concurrency checks against a running gunicorn (gthread workers), synthetic data on a DB copy only.
Usage (inside the container): python tests/concurrency_http.py
Verifies that simultaneous requests cannot produce duplicate numbers, double issuance, or credit over-run."""
import http.cookiejar, json, os, re, sqlite3, sys, threading, urllib.parse, urllib.request
from datetime import date

BASE = 'http://127.0.0.1:8000'; DB = os.environ['DB_PATH']; PW = os.environ['APP_PASSWORD']
jar = http.cookiejar.CookieJar()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)
results = []


def check(name, cond, detail=''):
    results.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + (f' — {detail}' if detail and not cond else ''))


def post(path, data):
    try:
        r = op.open(urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data, doseq=True).encode())); return r.status, r.headers.get('Location', '')
    except urllib.error.HTTPError as e: return e.code, e.headers.get('Location', '')


def sql(q, a=()):
    c = sqlite3.connect(DB, timeout=15)
    try: return c.execute(q, a).fetchall()
    finally: c.close()


def burst(calls):
    out = [None] * len(calls); gate = threading.Barrier(len(calls))
    def run(i, f):
        gate.wait(); out[i] = f()
    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(calls)]
    [t.start() for t in ts]; [t.join() for t in ts]; return out


print(post('/login', {'username': 'admin', 'password': PW}))
post('/settings', {'issuer_name': 'Émetteur Concurrence Sàrl', 'issuer_address': 'Rue 1\n1000 Lieu', 'account_holder': 'Émetteur Concurrence Sàrl', 'iban': 'CH00 0000 0000 0000 0000 0',
                   'payment_terms': 'Paiement à 30 jours', 'issuer_vat_number': 'CHE-123.456.789 TVA'})
post('/project', {'name': 'Concurrence', 'rate': '800', 'day_hours': '8', 'vat': '8.1', 'ordered_days': '40', 'client': 'Client', 'billing_address': 'Client SA\nRue 2\n1000 Lieu',
                  'client_legal_id': 'CHE-000.000.009', 'client_legal_name': 'Client SA'})
pid = sql("SELECT id FROM projects WHERE name='Concurrence'")[0][0]
for d in range(1, 29): post('/entry', {'work_date': f'2026-09-{d:02d}', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '8', 'description': 'prestation'})
check('28 saisies créées', sql('SELECT COUNT(*) FROM entries')[0][0] == 28)

# 1. two drafts of the same billed month issued at the same instant: two distinct numbers, no gap in the sequence
for f, t in (('2026-09-01', '2026-09-14'), ('2026-09-15', '2026-09-30')):
    post('/invoice', {'project_id': pid, 'period_from': f, 'period_to': t, 'qty': '10' if f.endswith('01') else '8', 'rounding': 'exact', 'rounding_step': '0.25'})
d1, d2 = [r[0] for r in sql("SELECT id FROM invoices ORDER BY id")]
D8 = {f'derogation_{n}': 'Recette fictive : dérogation motivée pour préparer les données' for n in (12, 13, 14)}   # G4/D8 + rc25 : contrôles 12, 13 et 14 dérogeables, un motif écrit pour chacun
res = burst([lambda: post(f'/issue/{d1}', {'reliquat_treatment': 'reporte', **D8}), lambda: post(f'/issue/{d2}', {'reliquat_treatment': 'reporte', **D8})])
nums = sorted(r[0] for r in sql("SELECT number FROM invoices WHERE status='issued'"))
check('deux émissions simultanées : numéros distincts AAAA-N (réservés par les brouillons, rc37)', len(nums) == 2 and len(set(nums)) == 2 and all(re.fullmatch(r'\d{4}-\d+', n) for n in nums), nums)
check('chaque facture émise a sa copie figée et son annexe', sql("SELECT COUNT(*) FROM invoices i JOIN invoice_snapshots s ON s.invoice_id=i.id WHERE i.status='issued'")[0][0] == len(nums))

# 1b. rc37 (P3): six drafts created at the same instant reserve six distinct numbers; the editor refuses a second draft taking a number another one just took
y = date.today().year
before_n = {r[0] for r in sql('SELECT number FROM invoices')}
burst([lambda: post('/invoice', {'project_id': pid, 'period_from': '2026-12-01', 'period_to': '2026-12-31', 'qty': '1', 'rounding': 'exact', 'rounding_step': '0.25'}) for _ in range(6)])
new_n = [r[0] for r in sql('SELECT number FROM invoices') if r[0] not in before_n]
check('6 créations simultanées de brouillons : 6 numéros distincts réservés', len(new_n) == 6 and len(set(new_n)) == 6 and all(re.fullmatch(rf'{y}-\d+', n) for n in new_n), new_n)
drafts = [r[0] for r in sql("SELECT id FROM invoices WHERE status='draft' ORDER BY id")]
edit = lambda i: post(f'/invoice/{i}/edit', {'period_from': '2026-12-01', 'period_to': '2026-12-31', 'qty': '1', 'unit': 'day', 'vat': '8.1', 'number': 'RACE/1'})
burst([lambda i=i: edit(i) for i in drafts[:4]])
check('4 brouillons qui saisissent le même numéro : un seul gagne', sql("SELECT COUNT(*) FROM invoices WHERE number='RACE/1'")[0][0] == 1)
post(f'/invoice/{drafts[0]}/edit', {'period_from': '2026-12-01', 'period_to': '2026-12-31', 'qty': '1', 'unit': 'day', 'vat': '8.1', 'number': ''})   # blank = automatic again
for i in drafts: post(f'/invoice/{i}/delete', {})
check('brouillons supprimés : leurs numéros sont libérés', sql("SELECT COUNT(*) FROM invoices WHERE status='draft' AND number IS NOT NULL")[0][0] == 0)

# 1c. rc37 (P1): the same editor page saved twice at once keeps ONE set of manual lines (idempotent by line uid, stale revision refused)
post('/invoice', {'project_id': pid, 'period_from': '2026-12-01', 'period_to': '2026-12-31', 'qty': '1', 'rounding': 'exact', 'rounding_step': '0.25'})
dl = sql('SELECT MAX(id) FROM invoices')[0][0]
form = {'period_from': '2026-12-01', 'period_to': '2026-12-31', 'qty': '1', 'unit': 'day', 'vat': '8.1', 'revision': '0'}
def save_lines(): return post(f'/invoice/{dl}/edit', {**form, 'line_id': ['', ''], 'line_uid': ['ca', 'cb'], 'line_description': ['Frais A', 'Frais B'], 'line_qty': ['1', '2'], 'line_unit': ['flat', 'flat'], 'line_rate': ['10', '20'], 'line_vat_mode': ['soumis', 'hors_tva']})
burst([save_lines for _ in range(6)])
check('6 enregistrements simultanés du même formulaire : 2 lignes, pas de doublon, pas de perte', sql('SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?', (dl,))[0][0] == 2 and sql('SELECT revision FROM invoices WHERE id=?', (dl,))[0][0] == 1)
post(f'/invoice/{dl}/delete', {})

# 2. the same draft issued by 8 simultaneous requests: exactly one issuance
post('/entry', {'work_date': '2026-10-01', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '8', 'description': 'octobre'})
post('/invoice', {'project_id': pid, 'period_from': '2026-10-01', 'period_to': '2026-10-31', 'qty': '1', 'rounding': 'exact', 'rounding_step': '0.25'})
d3 = sql('SELECT MAX(id) FROM invoices')[0][0]
before = sql("SELECT COUNT(*) FROM audit WHERE event='invoice_issued'")[0][0]
burst([lambda: post(f'/issue/{d3}', {'reliquat_treatment': 'reporte', **D8}) for _ in range(8)])
check('8 émissions simultanées de la même facture : une seule émission', sql("SELECT COUNT(*) FROM audit WHERE event='invoice_issued'")[0][0] - before == 1 and sql('SELECT status FROM invoices WHERE id=?', (d3,))[0][0] == 'issued')
check('un seul PDF figé pour cette facture', sql('SELECT COUNT(*) FROM invoice_snapshots WHERE invoice_id=?', (d3,))[0][0] == 1)

# 3. concurrent total credit notes on the same invoice: the cumulative credit never exceeds the invoice
inv = d1
burst([lambda: post(f'/invoice/{inv}/credit', {'scope': 'total', 'reason': 'test', 'treatment': 'remboursement'}) for _ in range(6)])
n = sql("SELECT COUNT(*) FROM credit_notes WHERE invoice_id=?", (inv,))[0][0]
check('6 notes de crédit totales simultanées : un seul brouillon', n == 1, n)
burst([lambda: post(f'/invoice/{inv}/credit', {'scope': 'partial', 'qty': '4', 'reason': 'test', 'treatment': 'remboursement'}) for _ in range(6)])
tot = sql("SELECT COALESCE(SUM(qty),0) FROM credit_notes WHERE invoice_id=? AND qty IS NOT NULL", (inv,))[0][0]
check('crédits partiels simultanés : jamais plus que la quantité facturée (10 j)', tot <= 10 + 1e-9, tot)

# 4. concurrent entry creation while an invoice is being drafted: every entry kept, none duplicated
c0 = sql('SELECT COUNT(*) FROM entries')[0][0]
burst([lambda i=i: post('/entry', {'work_date': '2026-11-01', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '1', 'description': f'parallèle {i}'}) for i in range(20)])
check('20 saisies simultanées : toutes enregistrées une fois', sql('SELECT COUNT(*) FROM entries')[0][0] - c0 == 20 and sql("SELECT COUNT(DISTINCT description) FROM entries WHERE description LIKE 'parallèle %'")[0][0] == 20)

# 5. concurrent edit/delete of the same entry: one outcome, a coherent history
post('/entry', {'work_date': '2026-11-02', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '2', 'description': 'cible'})
e = sql("SELECT id FROM entries WHERE description='cible'")[0][0]
burst([lambda: post(f'/entry/{e}/delete', {}), lambda: post(f'/entry/{e}/delete', {}), lambda: post(f'/entry/{e}/edit', {'work_date': '2026-11-02', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '3', 'description': 'cible'})])
gone = sql('SELECT COUNT(*) FROM entries WHERE id=?', (e,))[0][0] == 0
dels = sql("SELECT COUNT(*) FROM entry_changes WHERE entry_id=? AND action='delete'", (e,))[0][0]
check('suppressions/correction simultanées : au plus une suppression tracée, état cohérent', dels <= 1 and (gone == (dels == 1)), (gone, dels))

check('intégrité SQLite', sql('PRAGMA integrity_check')[0][0] == 'ok')
check('clés étrangères', sql('PRAGMA foreign_key_check') == [])
print(f'RESULT: {sum(results)}/{len(results)}'); sys.exit(0 if all(results) else 1)
