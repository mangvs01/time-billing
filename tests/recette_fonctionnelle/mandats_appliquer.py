"""Applique import/MANDATS-A-COMPLETER.csv à une instance (par les formulaires de l'application : validations et audit habituels, jamais de SQL).
Simulation par défaut : n'écrit rien sans --apply.
  --level certain : ne remplit que des champs VIDES en base avec une valeur déduite sans ambiguïté (SUIVI / tables mensuelles / facture de référence) ;
                    les mandats marqués application_auto = non (conflit entre sources ou donnée de certitude moyenne) sont ignorés.
  --level all     : applique toutes les valeurs non vides du CSV (à utiliser après décisions de l'utilisateur / édition du CSV).
  --close-termine : clôture (avec motif, réversible) les mandats dont action_proposee commence par « clôturer ».
usage: mandats_appliquer.py --port P --pwfile F --db BASE.db [--csv import/MANDATS-A-COMPLETER.csv] [--level certain|all] [--close-termine] [--apply]"""
import sys, os, csv, argparse, sqlite3
sys.path.insert(0, os.path.dirname(__file__))
from lib import App

ap = argparse.ArgumentParser(); ap.add_argument('--port', required=True); ap.add_argument('--pwfile', required=True); ap.add_argument('--db', required=True)
ap.add_argument('--csv', default='/root/time-billing-v9-rc10-20261004/import/MANDATS-A-COMPLETER.csv'); ap.add_argument('--level', default='certain', choices=['certain', 'all'])
ap.add_argument('--close-termine', action='store_true'); ap.add_argument('--apply', action='store_true'); a = ap.parse_args()
REF_MANDAT = 'CIRSE 2026'
A = App(a.port, a.pwfile, a.db)
if a.apply: assert A.login(), 'connexion impossible'
ro = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True); ro.row_factory = sqlite3.Row
def entries_fp(): return ro.execute("select count(*), round(sum(hours),4), group_concat(id) from (select id,hours from entries order by id)").fetchone()
fp0 = tuple(entries_fp()); print('saisies avant :', fp0[0], 'saisies /', fp0[1], 'h')
TEXT = ('short_name', 'client', 'po', 'project_number', 'billing_contact', 'billing_address', 'dates_label', 'client_legal_name', 'client_legal_id')
changes = closes = 0
for r in csv.DictReader(open(a.csv, encoding='utf-8-sig'), delimiter=';'):
    p = ro.execute('select * from projects where name=?', (r['mandat'],)).fetchone()
    if not p: print('! mandat absent de la base :', r['mandat']); continue
    form = {'name': p['name'], 'rate': p['rate'] or 0, 'day_hours': p['day_hours'] or 8, 'vat': p['vat'] or 0, 'ordered_days': p['ordered_days'] or 0, 'start_date': p['start_date'] or '', 'duration_months': p['duration_months'] or 12}
    for k in TEXT: form[k] = p[k] or ''
    csvmap = {'project_number': r['n_projet'], 'po': r['po'], 'dates_label': r['dates_label'], 'client': r['client_nom_court'], 'billing_contact': r['contact_facturation'],
              'billing_address': r['adresse_facturation'].replace(' / ', '\n'), 'client_legal_name': r['raison_sociale'], 'client_legal_id': r['id_legal'],
              'vat': r['tva_pct'], 'rate': r['tarif_jour_chf'], 'ordered_days': r['jours_commandes'], 'start_date': r['debut'], 'duration_months': r['duree_mois']}
    decs = set(filter(None, r['decisions_requises'].split(',')))
    diff = {}
    for k, v in csvmap.items():
        if v in ('', None) or str(v) == str(form[k]): continue
        if a.level == 'certain':
            if r['mandat'] == REF_MANDAT and k in ('vat', 'billing_contact', 'billing_address', 'client_legal_name') and not (form[k] or 0): diff[k] = v     # facture de référence
            elif k in ('project_number', 'po', 'dates_label') and not form[k] and r.get('application_auto') == 'oui' and (k == 'dates_label' or (r['n_projet_source'] if k == 'project_number' else r['po_source']).startswith(('SUIVI', 'feuilles mensuelles (table'))): diff[k] = v
        else: diff[k] = v
    if diff:
        print(f"~ {r['mandat']:24}", {k: (form[k], v) for k, v in diff.items()}); changes += 1
        if a.apply:
            form.update(diff); s, m = A.post(f'/project/{p["id"]}/edit', {k: str(v) for k, v in form.items()})
            assert any('Mandat mis à jour' in x for x in m), (r['mandat'], m)
    if a.close_termine and r['action_proposee'].startswith('clôturer') and p['active']:
        print(f"x {r['mandat']:24} clôture"); closes += 1
        if a.apply:
            s, m = A.post(f'/project/{p["id"]}/close', {'reason': 'Terminé selon le SUIVI 2025/2026 ; facturé hors application (historique importé)'}); assert any('Mandat clôturé' in x for x in m), (r['mandat'], m)
ro.close(); ro = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True); ro.row_factory = sqlite3.Row
fp1 = tuple(entries_fp()); print('saisies après :', fp1[0], 'saisies /', fp1[1], 'h')
assert fp0 == fp1, 'LES SAISIES ONT CHANGÉ'
print(f"{'APPLIQUÉ' if a.apply else 'SIMULATION'} : {changes} mandat(s) modifié(s), {closes} clôture(s) ; saisies identiques (ids, heures)")
