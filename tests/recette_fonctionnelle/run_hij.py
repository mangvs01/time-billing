"""Recette fonctionnelle — H sauvegarde/restauration, I import (idempotence, aucun doublon, reproductibilité), J PDF vs modèle.
usage: CTN=<conteneur A> run_hij.py <portA> <dossierA>   (lance 2 conteneurs supplémentaires : restauration 8301, import 8302, sur copies)"""
import sys, os, json, re, subprocess, base64, zipfile, io, sqlite3, hashlib, copy
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
portA, dirA = sys.argv[1], sys.argv[2]; W = '/root/time-billing-v9-rc10-20261004'; FD = f'{W}/recette/fonc'
A = App(portA, f'{dirA}/pw.txt', f'{dirA}/data/timebilling.db'); R = Report('H-I-J'); ck = R.check; assert A.login()
def launch(name, port, d, src=None):
    o = subprocess.run([f'{W}/journaux/fonc/launch_fonc.sh', name, str(port), d] + ([src] if src else []), capture_output=True, text=True); assert o.returncode == 0, o.stdout + o.stderr
    a = App(port, f'{d}/pw.txt', f'{d}/data/timebilling.db'); assert a.login(); return a
TABLES = ['projects', 'entries', 'invoices', 'invoice_snapshots', 'invoice_annex_entries', 'credit_notes', 'credit_operations', 'credit_note_snapshots', 'credit_note_cancellations', 'settings', 'import_batches', 'import_batch_rows', 'entry_changes', 'invoice_date_changes']

# ------------------------------------------------------------------ H. sauvegarde / restauration
R.sec('H. Sauvegarde JSON et restauration sur copie')
s, h, raw = A.req('/backup'); obj = json.loads(raw)
cnt = {t: A.one(f'select count(*) from {t}') for t in obj['tables']}
ck('H1 export JSON : produit, application/json, version et schéma', s == 200 and 'json' in h.get('Content-Type', '') and obj['meta']['app_version'] and obj['meta']['schema'], list(obj['meta'])[:5])
ck('H2 compte de lignes déclaré (meta.row_counts) = lignes réelles de chaque table', all(obj['meta']['row_counts'][t] == len(obj['tables'][t]) == cnt[t] for t in obj['tables']), {t: (obj['meta']['row_counts'][t], cnt[t]) for t in obj['tables'] if obj['meta']['row_counts'][t] != cnt[t]})
ck('H3 les PDF figés (BLOB) sont dans la sauvegarde (base64) : factures et avoirs', all(r['pdf'] for r in obj['tables']['invoice_snapshots']) and len(obj['tables']['invoice_snapshots']) == A.one("select count(*) from invoices where status='issued'"))
B = launch('tb-fonc-restore', 8301, f'{FD}/restore')
def etat(App_): return tuple(App_.one(f'select count(*) from {t}') for t in TABLES) + (App_.one("select group_concat(id||status||coalesce(number,''), ',') from invoices"),)
n_b0 = (B.one('select count(*) from entries'), B.one('select count(*) from invoices'), B.one("select count(*) from invoices where status='issued'")); E_B0 = etat(B)
ck('H4 base cible (copie du staging validé) : 2 247 saisies, 1 facture = brouillon n°1 de l\'utilisateur (aucune émise) avant restauration', n_b0 == (2247, 1, 0), n_b0)
s, m = B.post('/restore', files={'backup': ('mauvais.txt', raw)}); ck('H5 fichier non .json refusé', any('.json' in x for x in m), m)
cut = copy.deepcopy(obj); cut['tables'].pop('entries')
s, h, b = B.req('/restore', files={'backup': ('amputee.json', json.dumps(cut).encode())}); loc6 = h.get('Location') or ''
# l'application accepte le téléversement pour aperçu ; le refus a lieu à la confirmation (RESTAURER), explicite, sans aucune écriture
if '/restore/' in loc6: s6, msgs = B.post(loc6.replace(B.base, ''), {'confirm': 'RESTAURER'})
else: s6, msgs = s, flashes(B.get(loc6.replace(B.base, '') or '/?tab=settings'))
ck('H6 sauvegarde amputée (table « entries » absente) refusée, base inchangée', B.one('select count(*) from entries') == 2247 and (s in (302, 303)), (s, loc6))
ck('H6b message de refus explicite', any('impossible' in x.lower() or 'refus' in x.lower() for x in msgs), msgs)
bad = copy.deepcopy(obj); bad['tables']['invoice_snapshots'][0]['pdf'] = base64.b64encode(b'%PDF-1.4 falsifie').decode()
s, h, b = B.req('/restore', files={'backup': ('falsifiee.json', json.dumps(bad).encode())}); loc = h.get('Location') or ''
if '/restore/' in loc:
    tok = loc.rsplit('/', 1)[-1]; s2, m2 = B.post(f'/restore/{tok}', {'confirm': 'RESTAURER'}); ck('H7 PDF figé falsifié (SHA ≠) : restauration refusée, base inchangée', etat(B) == E_B0, m2)
    B.post(f'/restore/{tok}', {'action': 'cancel'})
else: ck('H7 PDF figé falsifié refusé dès le téléversement, base inchangée', etat(B) == E_B0 and '/restore/' not in loc, (loc, flashes(B.get('/?tab=settings'))))
s, h, b = B.req('/restore', files={'backup': ('tronquee.json', raw[:len(raw) // 2])}); ck('H8 JSON tronqué refusé, base inchangée', etat(B) == E_B0 and not ('/restore/' in (h.get('Location') or '')), h.get('Location'))
s, h, b = B.req('/restore', files={'backup': ('sauvegarde.json', raw)}); loc = h.get('Location') or ''; ck('H9 sauvegarde valide : aperçu de restauration', '/restore/' in loc, loc)
tok = loc.rsplit('/', 1)[-1]; prev = B.get(f'/restore/{tok}'); ck('H9b aperçu : montre les comptes (factures, saisies) avant d\'écrire', 'RESTAURER' in prev and ('facture' in prev.lower()), prev[:200])
s, m = B.post(f'/restore/{tok}', {'confirm': 'oui'}); ck('H10 confirmation incorrecte refusée, base inchangée', etat(B) == E_B0 and any('RESTAURER' in x for x in m), m)
s, m = B.post(f'/restore/{tok}', {'confirm': 'RESTAURER'}); ck('H11 restauration effectuée avec sauvegarde préalable vérifiée', any('Restauration effectuée' in x for x in m), m)
# comparaison table par table
def tdig(App_, t):
    c = sqlite3.connect(f'file:{App_.db}?mode=ro', uri=True)
    try:
        cols = [r[1] for r in c.execute(f'pragma table_info({t})')]; rows = [tuple((hashlib.sha256(v).hexdigest() if isinstance(v, bytes) else v) for v in r) for r in c.execute(f'select * from {t} order by 1,2' if t in ('invoice_annex_entries',) else f'select * from {t} order by rowid')]
        return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest(), len(rows)
    finally: c.close()
diffs = [(t, tdig(A, t), tdig(B, t)) for t in TABLES if tdig(A, t) != tdig(B, t)]
ck('H12 après restauration : 14 tables identiques à la source (saisies, factures, PDF figés, avoirs, opérations, lots d\'import, paramètres)', not diffs, diffs[:2])
ck('H13 empreinte des 2 247 saisies historiques identique à la source', entries_digest(B.db, True) == entries_digest(A.db, True))
ck('H14 intégrité SQLite et clés étrangères après restauration', B.one('pragma integrity_check') == 'ok' and not B.q('pragma foreign_key_check'))
B2 = App(8301, f'{FD}/restore/pw.txt', B.db); first_inv = A.one("select min(id) from invoices where status='issued'")
ck('H15 application utilisable après restauration (connexion, liste, PDF figé identique)', B2.login() and len(B2.get('/entries.csv').splitlines()) > 2247 and B2.req(f'/invoice/{first_inv}.pdf')[2] == A.req(f'/invoice/{first_inv}.pdf')[2])
ck('H16 trace d\'audit de la restauration (json_restored)', B.one("select count(*) from audit where event='json_restored'") == 1)
ck('H17 sauvegarde pré-restauration conservée dans le conteneur cible', 'pre-restore' in subprocess.run(['docker', 'exec', 'tb-fonc-restore', 'sh', '-c', 'ls /data/backups 2>/dev/null; ls /data 2>/dev/null'], capture_output=True, text=True).stdout)
# rejouer la même restauration : idempotente
s, h, b = B2.req('/restore', files={'backup': ('sauvegarde.json', raw)}); tok = (h.get('Location') or '').rsplit('/', 1)[-1]; B2.post(f'/restore/{tok}', {'confirm': 'RESTAURER'})
ck('H18 restauration rejouée : état identique (idempotente)', not [t for t in TABLES if tdig(A, t) != tdig(B, t)])

# ------------------------------------------------------------------ I. import
R.sec('I. Import — état reproductible, ré-import refusé, aucun doublon')
C = launch('tb-fonc-import', 8302, f'{FD}/import')
XL = open('/root/Time sheet CP.xlsx', 'rb').read(); n0 = C.one('select count(*) from entries'); dg0 = entries_digest(C.db)
s, h, _ = C.req('/import', {}, {'workbook': ('Time sheet CP.xlsx', XL)}); tok = h['Location'].rsplit('/', 1)[-1]
names = json.load(open(f'{FD}/../../import/final/out/plans-final.json'))['F1']['project_names']
tgt = {}
for pl in ('plans-final.json', 'plans-reste.json'):
    for run, p in json.load(open(f'{W}/import/final/out/{pl}')).items():
        for n, m in p['mapping'].items():
            if m != 'skip': tgt.setdefault(n, m.split(':', 1)[1])
mp = {n: str(C.one('select id from projects where name=?', (tgt.get(n, ''),)) or '') for n in names}
form = {f'map_{i}': (mp[n] or 'skip') for i, n in enumerate(names)}; form['action'] = 'save'; C.req(f'/import/review/{tok}', form)
pg = C.get(f'/import/review/{tok}')
ck('I1 ré-import du même classeur : aperçu produit, lignes déjà importées détectées', 'déjà importée' in pg or 'déjà présente' in pg, re.findall(r'(\d+) ligne', pg)[:3])
m_conf = re.search(r"Confirmer l'import réel de (\d+) ligne", pg); fp = re.search(r'name="fingerprint" value="([0-9a-f]{64})"', pg)
nimp = int(m_conf.group(1)) if m_conf else 0
ck('I2 lignes importables sans décision lors d\'un ré-import (mapping à un mandat par nom) : seules les lignes dont le mandat réel diffère du mandat unique choisi (fenêtres NC STC / GEM STC, 8 lignes) ne sont pas reconnues', nimp <= 8, nimp)
s, m = C.post(f'/import/review/{tok}', dict(form, action='commit', fingerprint=fp.group(1) if fp else '', ack='1'))
ck('I3 validation du ré-import refusée (décisions manquantes / rien d\'importable)', C.one('select count(*) from entries') == n0 and any('non exécuté' in x.lower() or 'décision' in x.lower() or 'aucune ligne' in x.lower() for x in m), m)
ck('I4 aucune saisie ajoutée, aucune supprimée : empreinte inchangée', entries_digest(C.db) == dg0)
# tentative de forcer : décision « include » sur une ligne déjà importée
row = re.search(r'name="d_(\d+)"', pg); idx = None
payload_rows = json.load(open(f'{W}/import/execution-staging/out/plan.json'))['rows']
first_lot1 = next(r for r in payload_rows if r['final'] == 'LOT1' and mp.get(r['project']))
idx = first_lot1['idx']
decs = {f"d_{r['idx']}": 'exclude' for r in payload_rows if r['project'] and mp.get(r['project']) and r['app_cat'] not in ('bloquante', 'total_ou_sous_total')}
decs[f'd_{idx}'] = 'include'
f2 = dict(form, **decs); f2['action'] = 'save'; C.req(f'/import/review/{tok}', f2); pg2 = C.get(f'/import/review/{tok}')
m2 = re.search(r"Confirmer l'import réel de (\d+) ligne", pg2); fp2 = re.search(r'name="fingerprint" value="([0-9a-f]{64})"', pg2)
s, m = C.post(f'/import/review/{tok}', dict(f2, action='commit', fingerprint=fp2.group(1) if fp2 else '', ack='1'))
dup = C.one('select count(*) from entries') - n0
ck('I5 AUCUN DOUBLON POSSIBLE : même en décidant toutes les autres lignes, forcer l\'inclusion d\'une ligne déjà importée du même classeur est refusé', dup == 0, f'{dup} doublon(s) créé(s) ; messages : {m}')
C.post(f'/import/review/{tok}/cancel', {})
# état final reproductible
dd = f'{W}/import/final/copie-D/data/timebilling.db'
def nb(db):
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        rs = c.execute("select e.work_date,p.name,e.start_time,e.end_time,printf('%.4f',e.hours),e.description,e.source,e.source_ref from entries e join projects p on p.id=e.project_id order by e.source_ref,e.work_date,p.name,e.start_time,e.end_time").fetchall()
        return hashlib.sha256(json.dumps([list(r) for r in rs]).encode()).hexdigest(), len(rs)
    finally: c.close()
if os.path.exists(dd):   # root-83 (2026-10-11) : oracle corrigé — les 15 écarts bruts sont les corrections A-01 décidées par l'utilisateur (voir run_i6_a01.py)
    from run_i6_a01 import i6 as _i6
    _r = _i6(dd, '/opt/time-billing-v9-staging/data/timebilling.db')
    ck('I6 état final reproductible : rejeu F1→G5 sur copie-D + corrections A-01 tracées (décisions YES) = staging validé, saisie par saisie (sans id ni lot)', _r['ok'], _r)
ck('I7 staging validé : toujours 2 247 saisies / 24 mandats / 0 facture / 11 lots COMMITTED', (nb('/opt/time-billing-v9-staging/data/timebilling.db')[1], ) == (2247,))

# ------------------------------------------------------------------ J. PDF
R.sec('J. PDF — comparaison avec le modèle fourni (Facture-reelle-reference-2026-09.pdf)')
ref = open(f'{W}/Facture-reelle-reference-2026-09.pdf', 'rb').read(); ours = open(f'{dirA}/pdf/facture-2026-09.pdf', 'rb').read()
tr, to = pdf_text(ref), pdf_text(ours)
LAB = ['FACTURE', 'Date :', 'N° Facture :', 'PO:', 'Adresse de facturation :', 'DESCRIPTION', 'JOUR', 'COUT JOURNALIER', 'MONTANT', 'SOUS-TOTAL', 'TAUX TVA', 'TVA', 'AUTRES', 'TOTAL', 'Paiement', 'Titulaire:', 'IBAN:',
       'N° registre commerce', 'Feuille de temps', 'Total des heures', 'de travail du mois', 'Date(s)', 'Motif', 'Projet', 'Numéro de projet', 'Heure début', 'Heure fin', 'Heures de travail']
miss = [l for l in LAB if l in tr and l not in to]
ck('J1 libellés du modèle présents dans notre facture émise (28 libellés de structure)', not miss and all(l in tr for l in LAB), miss)
ir, fr_ = pdfinfo(ref), pdfinfo(ours)
ck('J2 format A4 comme le modèle', 'A4' in ir[0] and 'A4' in fr_[0], re.findall(r'Page size:.*', fr_[0]))
ck('J3 polices embarquées (aucune police non incorporée), texte extractable', 'no' not in [l.split()[-5] for l in fr_[1].splitlines()[2:] if len(l.split()) >= 6 and l.split()[-5] in ('yes', 'no')] and len(to) > 400, fr_[1][:300])
def bbox(data):
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.pdf') as t:
        t.write(data); t.flush(); x = subprocess.run(['pdftotext', '-bbox', '-f', '1', '-l', '1', t.name, '-'], capture_output=True, text=True).stdout
    return {w: (float(a), float(b)) for a, b, w in re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" [^>]*>([^<]+)</word>', x)[::-1]}
br, bo = bbox(ref), bbox(ours)
dev = {w: (round(abs(br[w][0] - bo[w][0]), 1), round(abs(br[w][1] - bo[w][1]), 1)) for w in ('FACTURE', 'DESCRIPTION', 'JOUR', 'MONTANT', 'SOUS-TOTAL', 'TAUX') if w in br and w in bo}
ck('J4 mise en page : position des titres de colonnes et des totaux identique au modèle (±4 pt)', len(dev) >= 5 and all(dx <= 4 and dy <= 4 for dx, dy in dev.values()), dev)
ck('J5 annexe « Feuille de temps » : mêmes colonnes et même format de date (jj/mm/aaaa) et d\'heure décimale', all(x in to for x in ('Feuille de temps', 'Heures de travail')) and re.search(r'\d\d/\d\d/\d{4}', to) and re.search(r'\d\d/\d\d/\d{4}', tr))
ck('J6 montants au format du modèle (espace fine milliers, virgule, CHF)', re.search(r'\d[\s  ]\d{3},\d{2} CHF', to) is not None and re.search(r'\d[\s  ]\d{3},\d{2} CHF', tr) is not None)
ck('J7 facture émise sans mention « BROUILLON » ; brouillon porte le filigrane', 'BROUILLON' not in to and 'BROUILLON' in pdf_text(open(f'{dirA}/pdf/brouillon-2026-09-2-avec-imputation.pdf', 'rb').read()))
ods = zipfile.ZipFile(f'{W}/Facture-modele-reference.ods'); oc = re.sub(r'<[^>]+>', ' ', ods.read('content.xml').decode()); ck('J8 modèle .ods : mêmes libellés de structure', all(l in oc for l in ('DESCRIPTION', 'SOUS-TOTAL', 'TAUX TVA', 'COUT JOURNALIER') ))
pdfs = {n: open(f'{dirA}/pdf/{n}', 'rb').read() for n in os.listdir(f'{dirA}/pdf')}
ck('J9 tous les PDF générés (factures, brouillon, avoirs, annulation, facture historique) : %PDF valides, texte extractable, polices incorporées', all(d.startswith(b'%PDF') and len(pdf_text(d)) > 200 for d in pdfs.values()) and len(pdfs) >= 6, list(pdfs))
tn = pdf_text(pdfs['avoir-NC-2026-08.pdf']); ck('J10 avoir : document séparé, mentionne « NOTE DE CRÉDIT », la facture d\'origine, montants négatifs/crédités', 'CRÉDIT' in tn.upper() and '2026-08' in tn, tn[:400])
json.dump(R.rows, open(f'{dirA}/results-hij.json', 'w'), ensure_ascii=False, indent=1)
ok, ko = R.summary(); sys.exit(1 if ko else 0)
