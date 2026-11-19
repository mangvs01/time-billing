"""Recette fonctionnelle — L. « Première facture réelle » sur une COPIE jetable du staging (historique + mandats préparés) :
paramètres émetteur issus de la facture de référence, mandat actif NHAF 2026 (TVA 0 %, client facturé en Belgique), émission, PDF comparé au modèle.
usage: run_premiere_facture.py <port> <dossier-instance>   (instance où mandats_appliquer.py --level certain a déjà été appliqué)"""
import sys, os, re, subprocess, html
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
port, dirn = sys.argv[1], sys.argv[2]; A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('L'); ck = R.check; assert A.login()
os.makedirs(f'{dirn}/pdf', exist_ok=True)
REF_TXT = subprocess.run(['pdftotext', '-layout', '/root/time-billing-v9-rc10-20261004/Facture-reelle-reference-2026-09.pdf', '-'], capture_output=True, text=True).stdout
ISSUER = {'issuer_name': 'Huddl Sàrl', 'issuer_address': 'Bvd de la Tour 2\n1205 Genève', 'issuer_rc': 'CH-660-4711023-3', 'account_holder': 'Huddl Sàrl',
          'iban': 'CH42 0024 0240 5471 1401 Y', 'bic': 'UBSWCHZH80A', 'payment_terms': 'Paiement à 30 jours sur le compte:', 'thanks_text': 'Je vous remercie de votre confiance.'}
text = lambda pdfb: subprocess.run(['pdftotext', '-layout', '-', '-'], input=pdfb, capture_output=True).stdout.decode()

R.sec('L. Première facture réelle (copie jetable) — du mandat préparé au PDF')
pid = A.one("select id from projects where name='NHAF 2026'")
row = A.q("select project_number, po, vat, rate, day_hours, client, billing_address, active from projects where id=?", (pid,))[0]
ck('L0 mandat NHAF 2026 actif, préparé : n° projet, PO, tarif, 8 h/jour, TVA 0 %', row[0] == '2600903BE' and row[1] == 'PO-2600903BE-17062026-001' and row[2] == 0 and row[3] == 650 and row[4] == 8 and row[7] == 1, row)
d0, d1, hrs = A.q("select min(work_date), max(work_date), round(sum(hours),4) from entries where project_id=?", (pid,))[0]
days_exact = D(str(hrs)) / D(8)
# --- état initial : émetteur non paramétré (la copie peut déjà l'être : on le vide, sur la copie seulement)
A.post('/settings', {k: '' for k in ISSUER})
# --- brouillon
q_exp = (days_exact / D('0.25')).quantize(D(1), ROUND_HALF_UP) * D('0.25')
s0, m0 = A.post('/invoice', {'project_id': pid, 'period_from': d0, 'period_to': d1, 'qty': str(q_exp), 'unit': 'day', 'rounding': 'nearest', 'rounding_step': '0.25'})
iid = A.one('select max(id) from invoices'); st = A.q('select status, qty, number from invoices where id=?', (iid,)) if iid else []
ck('L1 brouillon créé, quantité suggérée = heures ÷ 8 arrondies au quart de jour (recalcul indépendant)', st and st[0][0] == 'draft' and D(str(st[0][1])) == q_exp, (st, q_exp, days_exact, m0))
# --- émission refusée tant que l'émetteur n'est pas paramétré : liste précise des champs manquants
pg = A.get(f'/issue/{iid}'); miss_txt = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', pg)))
addr_missing = not (row[6] or '').strip()      # depuis la décision C2 (2026-10-05) NHAF 2026 porte déjà l'adresse de facturation belge
ck('L2 émission impossible sans paramètres émetteur : l\'écran liste ce qui manque (raison sociale, titulaire, IBAN, conditions' + (', adresse de facturation)' if addr_missing else ' ; adresse de facturation déjà renseignée, donc non listée)'),
   all(x in miss_txt for x in ['Raison sociale de l\'émetteur', 'IBAN', 'Titulaire du compte', 'Conditions de paiement']) and (('Adresse de facturation' in miss_txt[miss_txt.find('compléter'):][:400]) == addr_missing), miss_txt[miss_txt.find('compléter'):][:300])
s, m = A.post(f'/issue/{iid}', {'from_confirm': '1'}); ck('L2b émission refusée côté serveur (POST direct) : brouillon inchangé', A.one('select status from invoices where id=?', (iid,)) == 'draft', m)
# --- paramètres émetteur (valeurs de la facture de référence)
s, m = A.post('/settings', dict(ISSUER)); ck('L3 paramètres émetteur enregistrés (valeurs de la facture de référence)', all(A.one('select value from settings where key=?', (k,)) == v for k, v in ISSUER.items()), m)
pg = A.get(f'/issue/{iid}'); miss_txt = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', pg)))
tail = miss_txt[miss_txt.find('compléter'):][:200] if 'compléter' in miss_txt else ''
ck('L4 après les paramètres émetteur il ne manque plus que l\'adresse de facturation, si le mandat n\'en a pas (C2 : NHAF 2026 en a une → rien ne manque)', ('IBAN' not in tail) and (('Adresse de facturation' in tail) == addr_missing), tail)
# --- adresse de facturation (proposition C3 = entité belge de la facture de référence), via le formulaire du mandat
p = A.q('select name, rate, day_hours, vat, ordered_days, start_date, duration_months, short_name, client, po, project_number, billing_contact, billing_address, dates_label, client_legal_name, client_legal_id from projects where id=?', (pid,))[0]
f = dict(zip(['name', 'rate', 'day_hours', 'vat', 'ordered_days', 'start_date', 'duration_months', 'short_name', 'client', 'po', 'project_number', 'billing_contact', 'billing_address', 'dates_label', 'client_legal_name', 'client_legal_id'], [('' if v is None else str(v)) for v in p]))
f.update({'billing_contact': 'Claudia Ntampaka', 'billing_address': 'EGG BE\nAvenue du Bourgmestre Etienne Demunter 5, boîte 10\nJette, 1090\nBelgique', 'client_legal_name': 'EGG BE'})
s, m = A.post(f'/project/{pid}/edit', f); ck('L5 adresse de facturation enregistrée par le formulaire du mandat', any('Mandat mis à jour' in x for x in m), m)
# --- émission
pg = A.get(f'/issue/{iid}'); exp = re.search(r'name="expected_reliquat" value="([^"]+)"', pg); fm = {'from_confirm': '1'}
if exp: fm['expected_reliquat'] = exp.group(1); fm['reliquat_treatment'] = 'reporte'
bd = re.search(r'name="confirm_backdate"[^>]*value="([^"]+)"', pg)
if bd: fm['confirm_backdate'] = bd.group(1)
s, m = A.post(f'/issue/{iid}', fm); inv = A.q('select status, number, qty, unit_rate, vat, period_to, invoice_date, issued_at from invoices where id=?', (iid,))[0]
# Le numéro du mois peut déjà appartenir à une facture externe validée (ex. CIRSE 2026 : 2026-09).
# L'oracle indépendant réserve ces références et les numéros déjà émis, sans neutraliser l'historique.
used_numbers = {r[0] for r in A.q("select invoice_ref from historical_invoices where status='validated' and invoice_ref is not null")}
used_numbers.update(r[0] for r in A.q("select number from invoices where status='issued' and number is not null and id<>?", (iid,)))
expected_number = d1[:7]; suffix = 2
while expected_number in used_numbers:
    expected_number = f'{d1[:7]}-{suffix}'; suffix += 1
ck('L6 facture émise, numéro disponible du mois de fin de période (références historiques réservées)', inv[0] == 'issued' and inv[1] == expected_number, {'expected': expected_number, 'actual': inv, 'reserved_historical_numbers': sorted(used_numbers), 'messages': m})
ht = (D(str(inv[2])) * D(str(inv[3]))).quantize(CENT, ROUND_HALF_UP); fmt = lambda v: f'{v:,.2f}'.replace(',', ' ').replace('.', ',')
s, _h, b = A.req(f'/invoice/{iid}.pdf'); open(f'{dirn}/pdf/premiere-facture-nhaf.pdf', 'wb').write(b); t = text(b)
ck('L7 PDF servi : valide, texte extractible', s == 200 and b[:5] == b'%PDF-' and 'FACTURE' in t, s)
labels = [x for x in ['FACTURE', 'N° Facture', 'PO:', 'Adresse de facturation', 'DESCRIPTION', 'JOUR', 'COUT JOURNALIER', 'MONTANT', 'SOUS-TOTAL', 'TAUX TVA', 'AUTRES', 'TOTAL', 'Paiement à 30 jours sur le compte', 'Titulaire: Huddl Sàrl', 'IBAN: CH42 0024 0240 5471 1401 Y', 'BIC: UBSWCHZH80A', 'N° registre commerce: CH-660-4711023-3', 'Je vous remercie de votre confiance'] if x in REF_TXT]
ck(f'L8 les {len(labels)} libellés/mentions du modèle de référence sont présents dans notre PDF', all(x in t for x in labels), [x for x in labels if x not in t])
ck('L9 TVA : « 0,00% » et montant TVA nul affichés comme sur la facture de référence', re.search(r'TAUX TVA\s+0,00\s?%', t) and re.search(r'TVA\s+-\s*CHF', t), re.findall(r'TAUX TVA.*|TVA\s+.*', t)[:3])
ck('L10 montants : HT = jours × tarif (Decimal), total = HT (TVA 0), format « 5 200,00 CHF »', fmt(ht) + ' CHF' in t.replace('\xa0', ' ').replace(' ', ' '), (fmt(ht), re.findall(r'\d[\d  ]*,\d\d\s*CHF', t)[:6]))
ck('L11 PO et n° de projet imprimés', 'PO-2600903BE-17062026-001' in t and '2600903BE' in t, None)
ck('L12 adresse de facturation imprimée (contact, entité, rue, ville, pays)', all(x in t for x in ['Claudia Ntampaka', 'EGG BE', 'Jette', 'Belgique']), None)
ck('L13 aucune mention BROUILLON sur une facture émise', 'BROUILLON' not in t.upper(), None)
tot_annex = [D(x.replace(',', '.')) for x in re.findall(r'^Total\s+([\d,]+)\s*$', t, re.M)]
par_mois = [D(str(v)).quantize(CENT, ROUND_HALF_UP) for (m, v) in A.q("select substr(work_date,1,7), sum(hours) from entries where project_id=? and work_date between ? and ? group by 1 order by 1", (pid, d0, d1))]
ck('L14 annexe : un total par mois, égal à la somme des heures en base du mois (2 décimales), et somme = heures de la période', tot_annex == par_mois and abs(sum(tot_annex) - D(str(hrs))) < D('0.01') * len(par_mois), (tot_annex, par_mois, hrs))
pg = html.unescape(A.get('/'))
m = re.search(r'NHAF 2026 : ([\d,]+) j facturés nets, ([\d,]+) j réalisés non facturés, solde contractuel ([\d,]+) j sur ([\d,]+) j commandés', pg)
num = lambda x: D(x.replace(',', '.'))
ck('L15 position affichée par l\'application : facturé net = quantité émise, solde contractuel = 16 − facturé, réalisé non facturé = écart heures/jours (recalcul indépendant)',
   m and num(m[1]) == q_exp and num(m[3]) == D(16) - q_exp and num(m[4]) == 16 and abs(num(m[2]) - (days_exact - q_exp)) <= D('0.01'), (m.groups() if m else None, q_exp, days_exact - q_exp))
h0 = A.q('select count(*), round(sum(hours),4) from entries')[0]
ck('L16 les 2 247 saisies historiques sont inchangées après émission (nombre et heures)', h0 == (2247, 1934.4987), h0)
s, _h, b2 = A.req(f'/invoice/{iid}.pdf'); ck('L17 PDF figé : second téléchargement identique octet pour octet', b2 == b, None)
ok = sum(1 for r in R.rows if r['ok']); ko = [r for r in R.rows if not r['ok']]
print(f"\nRÉSULTAT L : {ok}/{len(R.rows)} OK, {len(ko)} KO")
for r in ko: print('  KO', r['test'], '|', r['detail'])
sys.exit(1 if ko else 0)
