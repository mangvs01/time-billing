"""DH7 — fixture dédiée (root-83, 2026-10-11) : l'annulation d'un lot d'import couvert par une facture Time Billing ÉMISE est refusée et ne retire aucune saisie.
Remplace le SKIP DH7 de run_dg.py (dans la recette réconciliée, la facture du mandat historique est bloquée par le contrôle 14 : plus de facture émise à protéger).
Contrôle positif d'abord (un lot non facturé s'annule), pour prouver que le refus vient bien de la facture émise. Copie jetable du golden UNIQUEMENT."""
import sys, re
from lib import App, Report
port, dirn = sys.argv[1], sys.argv[2]
A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('DH7'); ck = R.check; assert A.login()
B_FREE, B_BILLED, PID = 'c5799f02abd67c6ad56057d09342f9c3', '0aec89c3878f2874508e40b1b0634d4e', 23

R.sec('DH7-0 préconditions (copie jetable)')
ck('DH7-0a aucune facture émise dans la copie', A.one("select count(*) from invoices where status='issued'") == 0)
ck('DH7-0b les deux lots sont COMMITTED', [A.one('select status from import_batches where id=?', (b,)) for b in (B_FREE, B_BILLED)] == ['COMMITTED', 'COMMITTED'])
ck('DH7-0c mandat 23 actif, sans facture historique validée', A.one('select active from projects where id=?', (PID,)) == 1 and A.one("select count(*) from historical_invoices where project_id=? and status='validated'", (PID,)) == 0)

R.sec('DH7-1 contrôle positif : un lot que rien ne facture s\'annule')
n0 = A.one('select count(*) from entries'); k = A.one('select count(*) from entries where import_batch_id=?', (B_FREE,))
s, m = A.post(f'/imports/rollback/{B_FREE}', {})
ck('DH7-1 lot non facturé annulé : statut ROLLED_BACK, ses saisies retirées', A.one('select status from import_batches where id=?', (B_FREE,)) == 'ROLLED_BACK' and A.one('select count(*) from entries') == n0 - k and k > 0, (m, n0, k))

R.sec('DH7-2 facture Time Billing émise sur des saisies du lot, puis tentative d\'annulation')
row = A.q('select name from projects where id=?', (PID,))[0]
A.post(f'/project/{PID}/edit', {'name': row[0], 'rate': '650', 'day_hours': '8', 'vat': '0', 'ordered_days': '20', 'client': 'Client recette DH7', 'client_legal_name': 'Client Recette DH7 SA',
                                'client_legal_id': 'CHE-222.222.222', 'billing_address': 'Client Recette DH7 SA\nRue DH7 1\n1000 Ville'})
d0, d1 = '2026-09-01', '2026-09-30'
hrs = A.one('select round(sum(hours),6) from entries where project_id=? and work_date between ? and ?', (PID, d0, d1)); qty = hrs / 8
s, m = A.post('/invoice', {'project_id': PID, 'period_from': d0, 'period_to': d1, 'qty': str(qty), 'unit': 'day', 'rounding': 'exact'})
iid = A.one('select max(id) from invoices'); pg = A.get(f'/issue/{iid}'); exp = re.search(r'name="expected_reliquat" value="([^"]+)"', pg)
s, m = A.post(f'/issue/{iid}', {'from_confirm': '1', 'expected_reliquat': exp.group(1) if exp else '0', 'confirm_backdate': d1})
st = A.q('select status, number from invoices where id=?', (iid,))[0]
ck('DH7-2a facture émise sur la période qui contient les saisies du lot (quantité = heures ÷ 8, sans dérogation)', st[0] == 'issued', (st, m))
cov = A.one('select count(*) from invoice_annex_entries x join entries e on e.id=x.entry_id where x.invoice_id=? and e.import_batch_id=?', (iid, B_BILLED))
ck('DH7-2b l\'annexe figée de la facture liste des saisies du lot', cov and cov > 0, cov)
n1 = A.one('select count(*) from entries'); kb = A.one('select count(*) from entries where import_batch_id=?', (B_BILLED,))
s, m = A.post(f'/imports/rollback/{B_BILLED}', {})
ck('DH7-3 annulation du lot couvert par une facture émise REFUSÉE (message explicite)', any(x.startswith('Rollback refusé') for x in m), m)
ck('DH7-4 aucune saisie retirée ; lot toujours COMMITTED', A.one('select count(*) from entries') == n1 and A.one('select count(*) from entries where import_batch_id=?', (B_BILLED,)) == kb
   and A.one('select status from import_batches where id=?', (B_BILLED,)) == 'COMMITTED', (n1, kb))
ck('DH7-5 facture toujours émise, annexe figée intacte', A.one('select status from invoices where id=?', (iid,)) == 'issued'
   and A.one('select count(*) from invoice_annex_entries x join entries e on e.id=x.entry_id where x.invoice_id=? and e.import_batch_id=?', (iid, B_BILLED)) == cov)
ok, ko = R.summary(); sys.exit(1 if ko else 0)
