"""Pré-contrôle LECTURE SEULE d'un clone isolé : les données correspondent-elles aux hypothèses de chaque recette ?

usage: python3 preflight_clone.py <timebilling.db> [--url http://127.0.0.1:8093]
  - ouvre la base en `mode=ro` + `PRAGMA query_only=1` (aucune écriture possible, même par erreur) ; compare le SHA-256 du fichier avant/après et l'affiche ;
  - n'affiche AUCUNE valeur de paramètre (émetteur, IBAN…) : seulement leur présence ;
  - `--url` : un seul GET /health (version) ; aucun login, aucun mot de passe lu ;
  - code de sortie 0 si la base est saine (integrity_check ok), 2 sinon ; les « écarts de précondition » ne changent pas le code (ils se lisent dans le tableau).
Ne remplace pas les recettes : il dit lesquelles ont des préconditions satisfaites AVANT de les lancer.
"""
import hashlib, json, sqlite3, sys, urllib.request

path = sys.argv[1]
url = sys.argv[sys.argv.index('--url') + 1] if '--url' in sys.argv else None
sha = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()
before = sha(path)
c = sqlite3.connect(f'file:{path}?mode=ro', uri=True); c.execute('PRAGMA query_only=1')
q = lambda s, a=(): c.execute(s, a).fetchall()
one = lambda s, a=(): (q(s, a) or [[None]])[0][0]
tables = {r[0] for r in q("select name from sqlite_master where type='table'")}
has = lambda t: t in tables

integrity = one('PRAGMA integrity_check'); fk = q('PRAGMA foreign_key_check')
entries = q('select count(*), round(coalesce(sum(hours),0),4) from entries')[0] if has('entries') else (None, None)
projects = one('select count(*) from projects') if has('projects') else None
closed = one('select count(*) from projects where active=0') if has('projects') else None
inv = q("select count(*), coalesce(sum(status='issued'),0), coalesce(sum(status='draft'),0), coalesce(sum(number is not null),0) from invoices")[0] if has('invoices') else (None,) * 4
credit = one('select count(*) from credit_notes') if has('credit_notes') else None
names = ('PCR LV 2026', 'STC GEM Oct - DM job', 'MSD', 'NHAF 2026', 'EUROPCR 2027', 'ECIO 2025')
present = {n: (q('select id, active, rate, ordered_days, billing_address, billing_contact, client_legal_name, vat from projects where name=?', (n,)) or [None])[0] for n in names} if has('projects') else {}
settings_keys = {r[0]: bool((r[1] or '').strip()) for r in q('select key, value from settings')} if has('settings') else {}
issuer_keys = [k for k in settings_keys if k.startswith('issuer_') or k in ('iban', 'bic', 'account_holder', 'payment_terms', 'thanks_text')]
rc25_tables = ('credit_operations', 'credit_notes', 'invoice_snapshots', 'invoice_annex_entries', 'invoice_variance_decisions', 'invoice_date_changes', 'entry_changes')
version = None
if url:
    try: version = json.load(urllib.request.urlopen(url.rstrip('/') + '/health', timeout=5)).get('version')
    except Exception as e: version = f'illisible ({type(e).__name__})'

rows = []
def row(label, actual, expected_by, ok):
    rows.append((label, actual, expected_by, 'OK' if ok else 'ÉCART'))

row('integrity_check', integrity, 'toutes', integrity == 'ok'); row('foreign_key_check (lignes en erreur)', len(fk), 'toutes', not fk)
row('tables RC25 présentes', [t for t in rc25_tables if not has(t)] or 'toutes', 'toutes (pas de migration RC25)', all(has(t) for t in rc25_tables))
row('saisies (nombre, heures)', entries, 'rc19 R*, dg DH9, mandats M2, entites_vides Q9, premiere_facture L16, ab A25', tuple(entries) == (2247, 1934.4987))
row('mandats', projects, 'ab, rc19, hij', projects == 24)
row('mandats clôturés (active=0)', closed, 'rc19 R0a, mandats M1 (19 : état APRÈS mandats_appliquer --close-termine)', closed == 19)
row('factures (total, émises, brouillons, numérotées)', tuple(inv), 'ab/rc19/hij attendent (1,0,1,0) = un brouillon n°1 ; le clone annoncé a 0 facture', tuple(inv)[:1] == (1,) and inv[1] == 0 and inv[3] == 0)
row('notes de crédit', credit, 'informatif', True)
for n in names:
    p = present.get(n)
    if n in ('PCR LV 2026', 'STC GEM Oct - DM job'): row(f'mandat « {n} »', 'absent' if p is None else f'actif={p[1]} adresse/contact/raison vides={p[4] == "" and p[5] == "" and p[6] == ""}', 'entites_vides Q1 (vides, actif)', p is not None and p[1] == 1 and p[4] == '' and p[5] == '' and p[6] == '')
    elif n == 'MSD': row('mandat « MSD »', 'absent' if p is None else f'tarif={p[2]} jours={p[3]} adresse vide={p[4] == ""}', 'entites_vides Q6 (0, 0, vide)', p is not None and p[2:4] == (0.0, 0.0) and p[4] == '')
    elif n in ('NHAF 2026', 'EUROPCR 2027'): row(f'mandat « {n} »', 'absent' if p is None else f'contact={p[5] == "Claudia Ntampaka"} raison={p[6] == "EGG BE"} tva={p[7]}', 'entites_vides Q8 / premiere_facture (adresse C2)', p is not None and p[5] == 'Claudia Ntampaka' and p[6] == 'EGG BE' and p[7] == 0)
    else: row(f'mandat « {n} »', 'absent' if p is None else f'actif={p[1]} tarif={p[2]} jours={p[3]}', 'entites_vides Q10 (clôturé, tarif 0)', p is not None and p[1] == 0 and p[2] == 0)
row('paramètres émetteur renseignés (présence seulement)', f'{sum(settings_keys[k] for k in issuer_keys)}/{len(issuer_keys)}', 'informatif : run_premiere_facture les réécrit', True)
if url: row('version applicative (/health)', version, 'TB_EXPECT_VERSION (9.2-rc25)', version == '9.2-rc25')

print(f'base : {path}\nSHA-256 avant lecture : {before}')
w = max(len(r[0]) for r in rows)
for label, actual, by, st in rows: print(f'{st:6} {label:<{w}}  {actual}   ← {by}')

def applicable(ok_labels): return all(dict((r[0], r[3]) for r in rows).get(l) == 'OK' for l in ok_labels)
lab = lambda s: [r[0] for r in rows if r[0].startswith(s)]
base_ok = ['integrity_check', 'tables RC25 présentes']
verdicts = {
    'run_pages.py': (applicable(base_ok), 'lecture seule (3 GET)'),
    'run_cg.py / run_dg.py / run_extra.py': (applicable(base_ok), 'créent leurs propres factures/avoirs ; dg DH5/DH9 exigent 2 247 saisies' + ('' if applicable(['saisies (nombre, heures)']) else ' → ÉCART attendu sur ces 2 contrôles')),
    'run_ab.py': (applicable(base_ok + ['mandats', 'saisies (nombre, heures)', 'factures (total, émises, brouillons, numérotées)']), 'contrôle de précondition « 1 brouillon n°1 »'),
    'run_forecast.py': (applicable(base_ok + ['mandats']), 'modifie des paramètres de mandats en SQL : copie FRAÎCHE requise'),
    'run_mandats.py': (applicable(base_ok + ['mandats clôturés (active=0)']), 'exige 19 clôtures : produites par mandats_appliquer --apply (INTERDIT ici) → BLOQUÉ si non clôturés'),
    'run_entites_vides.py': (applicable(base_ok + lab('mandat «')), 'copie FRAÎCHE (crée/supprime des brouillons)'),
    'run_rc19.py': (applicable(base_ok + ['saisies (nombre, heures)', 'mandats', 'mandats clôturés (active=0)', 'factures (total, émises, brouillons, numérotées)']), 'précondition R0a (19 clôturés, 1 brouillon)'),
    'run_hij.py': (False, 'exige /root/Time sheet CP.xlsx, journaux/fonc/launch_fonc.sh et 2 conteneurs supplémentaires : BLOQUÉ sur le clone seul'),
    'run_premiere_facture.py': (False, 'exige mandats_appliquer.py --level certain déjà appliqué (INTERDIT) et Facture-reelle-reference-2026-09.pdf : BLOQUÉ'),
}
print('\nApplicabilité (préconditions de données uniquement ; ne dit rien sur les dépendances de fichiers/conteneurs listées):')
for k, (ok, why) in verdicts.items(): print(f'  {"PRÉCONDITIONS OK " if ok else "ÉCART / BLOQUÉ  "} {k:<40} {why}')
after = sha(path)
print(f'\nSHA-256 après lecture : {after}  ({"identique : aucune écriture" if after == before else "DIFFÉRENT !"})')
sys.exit(0 if integrity == 'ok' and after == before else 2)
