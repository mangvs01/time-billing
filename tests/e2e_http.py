"""End-to-end HTTP cycle against a running gunicorn (synthetic data, DB copy only).
Usage: python e2e_http.py phase1|phase2   (state handed over in /data/e2e_state.json)
"""
import hashlib, http.cookiejar, io, json, os, re, sqlite3, sys, urllib.parse, urllib.request, uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo   # jour ouvré de Zurich, comme l'application (billing_rules.local_today) : entre 22:00 et 24:00 UTC, la date UTC est la veille
from openpyxl import Workbook

BASE = 'http://127.0.0.1:8000'; DB = os.environ['DB_PATH']; STATE = '/data/e2e_state.json'
jar = http.cookiejar.CookieJar()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)
results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond))); print(('PASS ' if cond else 'FAIL ') + name + (f' — {detail}' if detail and not cond else ''))


def req(path, data=None, files=None):
    headers = {}
    if files:
        b = uuid.uuid4().hex; body = b''
        for k, v in (data or {}).items(): body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, (fn, content) in files.items():
            body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b'\r\n'
        body += f'--{b}--\r\n'.encode(); headers['Content-Type'] = f'multipart/form-data; boundary={b}'
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
    else: body = None
    try:
        r = op.open(urllib.request.Request(BASE + path, data=body, headers=headers)); return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e: return e.code, e.headers, e.read()


def page(path='/'):
    return req(path)[2].decode()


def q(sql, a=()):
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    try: return c.execute(sql, a).fetchall()
    finally: c.close()


def login():
    s, h, _ = req('/login', {'username': 'admin', 'password': os.environ['APP_PASSWORD']})
    check('login', s == 302 and '/login' not in h.get('Location', ''))


def wb(rows):
    w = Workbook(); ws = w.active; ws.title = {3: 'MAR', 4: 'AVR', 5: 'MAI'}[rows[0][0].month]; ws.append(['Relevé mars']); ws.append(['Date(s)', 'Motif', 'Projet', 'Heure début', 'Heure fin', 'Heures de travail'])
    for r in rows: ws.append(list(r))
    b = io.BytesIO(); w.save(b); return b.getvalue()


def do_import(rows, name):
    s, h, _ = req('/import', {}, {'workbook': (name, wb(rows))})
    token = h['Location'].rsplit('/', 1)[-1]
    check(f'aperçu {name} créé', s == 302 and '/import/review/' in h['Location'])
    html = page(f'/import/review/{token}')
    pid = str(q("SELECT id FROM projects WHERE name='E2E Alpha'")[0][0])
    form = {'map_0': pid, 'action': 'save'}
    req(f'/import/review/{token}', form)
    html = page(f'/import/review/{token}')
    fp = re.search(r'name="fingerprint" value="([0-9a-f]+)"', html).group(1)
    s, h, _ = req(f'/import/review/{token}', dict(form, action='commit', fingerprint=fp, ack='1'))
    check(f'validation {name}', s == 302 and h['Location'].endswith('/?tab=migration'))
    return q('SELECT id FROM import_batches WHERE status=\'COMMITTED\' ORDER BY rowid DESC LIMIT 1')[0][0]


def phase1():
    login()
    req('/settings', {'issuer_name': 'Émetteur E2E Sàrl', 'issuer_address': 'Rue E2E 1\n1200 Genève', 'account_holder': 'Émetteur E2E Sàrl',
                      'iban': 'CH00 0000 0000 0000 0000 0', 'payment_terms': 'Paiement à 30 jours', 'issuer_vat_number': 'CHE-123.456.789 TVA'})
    req('/project', {'name': 'E2E Alpha', 'rate': '1200', 'day_hours': '8', 'vat': '8.1', 'ordered_days': '10', 'client': 'Client E2E', 'client_legal_name': 'Client E2E SA', 'client_legal_id': 'CHE-000.000.042',
                     'billing_address': 'Client E2E SA\nRue 2\n1000 Ville'})
    same = (datetime(2025, 3, 3), 'réunion', 'E2E Alpha', time(9, 0), time(9, 15), 0.25)
    b1 = do_import([same, same, (datetime(2025, 3, 4), 'analyse', 'E2E Alpha', None, None, 0.5)], 'lot1.xlsx')
    check('lot 1 : 3 lignes distinctes (répétition conservée)', q('SELECT COUNT(*) FROM entries WHERE import_batch_id=?', (b1,))[0][0] == 3)
    check('durées 15/30 min conservées', sorted(r[0] for r in q('SELECT hours FROM entries WHERE import_batch_id=?', (b1,))) == [0.25, 0.25, 0.5])
    pid = q("SELECT id FROM projects WHERE name='E2E Alpha'")[0][0]
    req('/invoice', {'project_id': pid, 'period_from': '2025-03-01', 'period_to': '2025-03-31', 'qty': '0.125'})
    iid = q('SELECT MAX(id) FROM invoices')[0][0]
    check('brouillon créé via la route', iid is not None)
    s, h, draft = req(f'/invoice/{iid}.pdf'); check('PDF brouillon', s == 200 and draft.startswith(b'%PDF'))
    page = req(f'/issue/{iid}')[2].decode()
    check('page de confirmation avec numéro', '<b>2025-03</b>' in page)
    exp = re.search(r'name="expected_reliquat" value="([^"]+)"', page).group(1)
    expected_date = re.search(r'name="expected_invoice_date" value="([^"]+)"', page).group(1)
    # No reliquat exists here, so the confirmation form intentionally has no treatment radio; do not submit a spurious 'reporte'.
    req(f'/issue/{iid}', {'expected_reliquat': exp, 'expected_invoice_date': expected_date, 'from_confirm': '1'})
    check('facture émise (2025-03)', q('SELECT status, number, reliquat_treatment FROM invoices WHERE id=?', (iid,))[0] == ('issued', '2025-03', 'aucun'))  # 1 h = 0.125 j billed exactly: no reliquat
    s, h, pdf1 = req(f'/invoice/{iid}.pdf'); stored = q('SELECT pdf_sha256 FROM invoice_snapshots WHERE invoice_id=?', (iid,))[0][0]
    check('PDF émis = PDF figé', s == 200 and hashlib.sha256(pdf1).hexdigest() == stored)
    req('/entry', {'work_date': '2025-03-28', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '2', 'description': 'tardive'})
    check('PDF émis inchangé après nouvelle saisie dans la période', req(f'/invoice/{iid}.pdf')[2] == pdf1)
    req(f'/imports/rollback/{b1}', {})
    check('rollback refusé (lot couvert par facture émise)', q('SELECT status FROM import_batches WHERE id=?', (b1,))[0][0] == 'COMMITTED'
          and q('SELECT COUNT(*) FROM entries WHERE import_batch_id=?', (b1,))[0][0] == 3)
    b2 = do_import([(datetime(2025, 4, 2), 'avril', 'E2E Alpha', None, None, 1)], 'lot2.xlsx')
    req(f'/imports/rollback/{b2}', {})
    check('rollback lot 2 accepté', q('SELECT status FROM import_batches WHERE id=?', (b2,))[0][0] == 'ROLLED_BACK'
          and q('SELECT COUNT(*) FROM entries WHERE import_batch_id=?', (b2,))[0][0] == 0)
    b3 = do_import([(datetime(2025, 5, 5), 'mai', 'E2E Alpha', None, None, 1.5)], 'lot3.xlsx')
    # V9.2: draft edit/delete, credit note, closure refusal with pending draft
    req('/invoice', {'project_id': pid, 'period_from': '2025-04-01', 'period_to': '2025-04-30', 'qty': '1'})
    d2 = q('SELECT MAX(id) FROM invoices')[0][0]
    req(f'/invoice/{d2}/edit', {'period_from': '2025-04-01', 'period_to': '2025-04-30', 'qty': '0.5', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25', 'description': 'modifié'})
    check('brouillon modifié', q('SELECT qty, description FROM invoices WHERE id=?', (d2,))[0] == (0.5, 'modifié'))
    req(f'/project/{pid}/close', {'reason': 'test'})
    check('clôture refusée avec brouillon en cours', q('SELECT active FROM projects WHERE id=?', (pid,))[0][0] == 1)
    req(f'/invoice/{d2}/delete', {})
    check('brouillon supprimé', not q('SELECT 1 FROM invoices WHERE id=?', (d2,)))
    req(f'/invoice/{iid}/credit', {'reason': 'E2E', 'qty': '0.0625', 'treatment': 'remboursement'})
    cid = q('SELECT MAX(id) FROM credit_notes')[0][0]
    req(f'/credit/{cid}/issue', {})
    check('note de crédit émise NC-2025-03', q('SELECT status, reference FROM credit_notes WHERE id=?', (cid,))[0] == ('issued', 'NC-2025-03'))
    check('facture d\'origine inchangée après NC', req(f'/invoice/{iid}.pdf')[2] == pdf1)
    s_, h_, cpdf = req(f'/credit/{cid}.pdf'); check('PDF note de crédit', s_ == 200 and cpdf.startswith(b'%PDF'))
    # V9.2 settlement: partial refund on the refund-mode note, total credit of the rest by offset on a later draft
    req(f'/credit/{cid}/refund', {'amount': '30', 'executed_on': datetime.now(ZoneInfo('Europe/Zurich')).date().isoformat(), 'external_ref': 'VIR-E2E'})
    check('remboursement partiel enregistré', q("SELECT kind, amount FROM credit_operations WHERE credit_note_id=?", (cid,)) == [('refund', 30.0)])
    check('suivi : partiellement remboursée', 'partiellement remboursée' in req(f'/credit/{cid}')[2].decode())
    req(f'/invoice/{iid}/credit', {'reason': 'E2E total', 'scope': 'total', 'treatment': 'compensation'})
    cid2 = q('SELECT MAX(id) FROM credit_notes')[0][0]; req(f'/credit/{cid2}/issue', {})
    check('crédit total du solde émis NC-2025-03.2', q('SELECT status, reference, qty, tva_amount FROM credit_notes WHERE id=?', (cid2,))[0] == ('issued', 'NC-2025-03.2', 0.0625, 6.07))
    req(f'/invoice/{iid}/credit', {'reason': 'E2E dépassement', 'amount': '0.01', 'treatment': 'remboursement'})
    check('dépassement refusé', q('SELECT COUNT(*) FROM credit_notes')[0][0] == 2)
    req('/invoice', {'project_id': pid, 'period_from': '2025-04-01', 'period_to': '2025-04-30', 'qty': '0.5'})
    d3 = q('SELECT MAX(id) FROM invoices')[0][0]
    req(f'/credit/{cid2}/offset', {'target_invoice_id': d3, 'amount': '50'})
    check('compensation partielle réservée sur brouillon', q("SELECT kind, amount, target_invoice_id FROM credit_operations WHERE credit_note_id=?", (cid2,)) == [('offset', 50.0, d3)])
    check('brouillon cible : PDF avec imputation', req(f'/invoice/{d3}.pdf')[0] == 200 and 'net à payer 598,60\xa0CHF' in req('/?tab=archive')[2].decode())
    json.dump({'cid2': cid2, 'd3': d3, 'iid': iid, 'cid': cid, 'cpdf_sha': hashlib.sha256(cpdf).hexdigest(), 'pdf_sha': hashlib.sha256(pdf1).hexdigest(), 'b1': b1, 'b2': b2, 'b3': b3,
               'counts': q('SELECT (SELECT COUNT(*) FROM entries),(SELECT COUNT(*) FROM import_batches),(SELECT COUNT(*) FROM audit)')[0]}, open(STATE, 'w'))


def phase2():
    st = json.load(open(STATE))
    login()
    check('santé après redémarrage', req('/health')[0] == 200)
    check('données persistées après redémarrage', list(q('SELECT (SELECT COUNT(*) FROM entries),(SELECT COUNT(*) FROM import_batches),(SELECT COUNT(*) FROM audit)')[0])[:2] == st['counts'][:2])
    check('PDF émis identique après redémarrage', hashlib.sha256(req(f"/invoice/{st['iid']}.pdf")[2]).hexdigest() == st['pdf_sha'])
    check('statuts des lots persistés', [q('SELECT status FROM import_batches WHERE id=?', (st[k],))[0][0] for k in ('b1', 'b2', 'b3')] == ['COMMITTED', 'ROLLED_BACK', 'COMMITTED'])
    req(f"/imports/rollback/{st['b3']}", {})
    check('rollback après redémarrage', q('SELECT status FROM import_batches WHERE id=?', (st['b3'],))[0][0] == 'ROLLED_BACK')
    check("page d'accueil : onglet Édition des factures", 'Édition des factures</button>' in page('/'))
    check('opérations de crédit persistées après redémarrage', q('SELECT kind, amount FROM credit_operations ORDER BY id') == [('refund', 30.0), ('offset', 50.0)])
    check('PDF note de crédit identique après redémarrage', hashlib.sha256(req(f"/credit/{st['cid']}.pdf")[2]).hexdigest() == st['cpdf_sha'])
    # restore under live gunicorn workers: backup, extra work, restore, data back to the backup
    s_, h_, raw = req('/backup'); check('sauvegarde JSON téléchargée', s_ == 200)
    before = q('SELECT COUNT(*) FROM entries')[0][0]
    pid = q("SELECT id FROM projects WHERE name='E2E Alpha'")[0][0]
    req('/entry', {'work_date': '2025-06-02', 'project_id': pid, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'après sauvegarde'})
    check('saisie ajoutée après sauvegarde', q('SELECT COUNT(*) FROM entries')[0][0] == before + 1)
    s_, h_, _ = req('/restore', {}, {'backup': ('sauvegarde.json', raw)})
    token = h_['Location'].rsplit('/', 1)[-1]
    check('prévisualisation de restauration', 'Restauration bloquée' not in page(f'/restore/{token}'))
    req(f'/restore/{token}', {'action': 'restore', 'confirm': 'RESTAURER'})
    for _ in range(4): req('/health')  # hit both workers after the swap
    check('restauration effectuée (saisie ultérieure retirée)', q('SELECT COUNT(*) FROM entries')[0][0] == before)
    check('PDF émis identique après restauration', hashlib.sha256(req(f"/invoice/{st['iid']}.pdf")[2]).hexdigest() == st['pdf_sha'])
    check('opérations de crédit conservées après restauration', q('SELECT COUNT(*) FROM credit_operations')[0][0] == 2)
    check('suivi compensation après restauration', 'Réservé sur brouillons' in page(f"/credit/{st['cid2']}") and '31,07\xa0CHF' in page(f"/credit/{st['cid2']}"))
    check('sauvegarde pré-restauration présente', any(n.startswith('pre-restore-') for n in os.listdir('/data/backups')))


if __name__ == '__main__':
    {'phase1': phase1, 'phase2': phase2}[sys.argv[1]]()
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    check('intégrité SQLite', c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not c.execute('PRAGMA foreign_key_check').fetchall())
    print(f"RESULT {sys.argv[1]}: {sum(ok for _, ok in results)}/{len(results)} passed")
    sys.exit(0 if all(ok for _, ok in results) else 1)
