"""Remplit les paramètres émetteur VIDES d'une instance avec les valeurs de la facture de référence (Facture-reelle-reference-2026-09.pdf) : jamais d'écrasement.
usage: appliquer_emetteur.py --port P --pwfile F --db BASE.db [--apply]   (simulation par défaut)"""
import sys, os, argparse, sqlite3
sys.path.insert(0, os.path.dirname(__file__))
from lib import App
ap = argparse.ArgumentParser(); ap.add_argument('--port', required=True); ap.add_argument('--pwfile', required=True); ap.add_argument('--db', required=True); ap.add_argument('--apply', action='store_true'); a = ap.parse_args()
REF = {'issuer_name': 'Huddl Sàrl', 'issuer_address': 'Bvd de la Tour 2\n1205 Genève', 'issuer_rc': 'CH-660-4711023-3', 'account_holder': 'Huddl Sàrl',
       'iban': 'CH42 0024 0240 5471 1401 Y', 'bic': 'UBSWCHZH80A', 'payment_terms': 'Paiement à 30 jours sur le compte:', 'thanks_text': 'Je vous remercie de votre confiance.'}
ro = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True)
cur = dict(ro.execute('select key, value from settings').fetchall())
todo = {k: v for k, v in REF.items() if not (cur.get(k) or '').strip()}; kept = [k for k in REF if k not in todo]
print('déjà renseignés (conservés) :', kept or 'aucun'); print('à renseigner :', list(todo) or 'aucun')
if a.apply and todo:
    A = App(a.port, a.pwfile, a.db); assert A.login()
    form = {k: (cur.get(k) or '') for k in REF}; form.update(todo)      # le formulaire enregistre TOUS les champs émetteur : on renvoie l'existant tel quel
    for k in ('refund_delay_days', 'other_vat_default'):
        if cur.get(k): form[k] = cur[k]
    s, m = A.post('/settings', form); print(m)
    ro = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True); new = dict(ro.execute('select key, value from settings').fetchall())
    assert all(new.get(k) == v for k, v in {**{k: cur.get(k) for k in kept}, **todo}.items() if v), 'écart après enregistrement'
    print('APPLIQUÉ', len(todo), 'champ(s)')
