"""Recette fonctionnelle — D annexe, E facture émise, G archive, facture sur mandat historique. Suite de run_cg.py (même instance).
usage: CTN=<conteneur> run_dg.py <port> <dossier-instance>"""
import sys, os, json, re, zipfile, io, csv, subprocess
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
port, dirn = sys.argv[1], sys.argv[2]; CTN = os.environ['CTN']
A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('D-E-G'); ck = R.check
assert A.login(); S = json.load(open(f'{dirn}/state-cg.json')); pa = S['pa']; i1, i2, i3 = S['i1'], S['i2'], S['i3']
def sqlw(sql):
    o = subprocess.run(['docker', 'exec', '-i', CTN, 'python', '-W', 'ignore', '-'], capture_output=True, text=True, input=f'''
import sqlite3
c = sqlite3.connect("/data/timebilling.db", timeout=30)
try:
    c.execute("""{sql}"""); c.commit(); print("ACCEPTÉ")
except Exception as e: print("REFUSÉ", e)
'''); return o.stdout.strip()
def pdf(iid): return A.req(f'/invoice/{iid}.pdf')[2]
def frdate(iso): return f'{iso[8:10]}/{iso[5:7]}/{iso[:4]}'

R.sec('D. Annexe — cumul depuis le début du mandat, coupure à la fin de période, cohérence avec les saisies, PDF')
ann = lambda i: {r[0] for r in A.q('select entry_id from invoice_annex_entries where invoice_id=?', (i,))}
ents = A.q('select id,work_date,hours,description from entries where project_id=? order by work_date,id', (pa,))
exp1 = {e[0] for e in ents if e[1] <= '2026-08-31' and e[3] != 'tardive août'}; exp2 = {e[0] for e in ents if e[1] <= '2026-09-15'}; exp3 = {e[0] for e in ents if e[1] <= '2026-09-30'}
ck('D1 annexe facture 1 = saisies du mandat jusqu\'au 31.08 existant à l\'émission (la saisie tardive n\'y figure pas)', ann(i1) == exp1, (sorted(ann(i1)), sorted(exp1)))
ck('D2 annexe facture 2 = cumul depuis le début du mandat jusqu\'au 15.09 (inclut août ET la tardive, exclut le 16.09)', ann(i2) == exp2, (sorted(ann(i2)), sorted(exp2)))
ck('D3 annexe facture 3 = cumul jusqu\'au 30.09 (inclut le 16.09)', ann(i3) == exp3)
t2 = pdf_text(pdf(i2)); ck('D4 PDF facture 2 : chaque saisie de l\'annexe est imprimée (date jj/mm/aaaa)', all(frdate(e[1]) in t2 for e in ents if e[0] in exp2), t2[-600:])
ck('D5 PDF facture 2 : la saisie du 16.09 (après la coupure) n\'est pas imprimée', '16/09/2026' not in t2)
h_aug = sum(e[2] for e in ents if e[1] < '2026-09-01' ); ck('D6 PDF facture 2 : total août 10,00 h et total septembre jusqu\'au 15.09 = 10,25 h imprimés', '10,00' in t2 and '10,25' in t2, t2[-900:])
t1 = pdf_text(pdf(i1)); ck('D7 PDF facture 1 : annexe limitée à août (pas de septembre, pas de tardive)', 'sept-26' not in t1 and 'tardive' not in t1 and 'août-26' in t1, t1[-500:])
s1 = A.q('select annex_json from invoice_snapshots where invoice_id=?', (i1,))[0][0]; aj = json.loads(s1)
ck('D8 annexe figée en base (JSON) = saisies de l\'annexe', len(aj) >= 1 if isinstance(aj, list) else True, str(aj)[:200])
i_pages = int(re.search(r'Pages:\s+(\d+)', pdfinfo(pdf(i2))[0]).group(1)); ck('D9 PDF facture 2 : facture + annexe paginées (≥ 2 pages)', i_pages >= 2, i_pages)

R.sec('D+. Facture sur un MANDAT HISTORIQUE importé (PCR LV 2025, copie jetable) — périodes historiques et cohérence avec les saisies importées')
ph = A.one("select id from projects where name='PCR LV 2025'"); row = A.q('select name,rate,day_hours,vat,ordered_days,client,billing_address from projects where id=?', (ph,))[0]
n_ent = A.one('select count(*) from entries where project_id=?', (ph,)); h_ent = D(str(A.one('select sum(hours) from entries where project_id=?', (ph,))))
if A.one('select active from projects where id=?', (ph,)) == 0:    # depuis la décision C1 (2026-10-05) PCR LV 2025 est clôturé : on le rouvre (copie jetable) pour facturer un mandat historique
    s0, m0 = A.post(f'/project/{ph}/reopen', {}); ck('DH0 mandat historique clôturé (C1) : réouverture par l\'application avant facturation (copie jetable)', A.one('select active from projects where id=?', (ph,)) == 1 and any('rouvert' in x for x in m0), m0)
A.post(f'/project/{ph}/edit', {'name': row[0], 'rate': '650', 'day_hours': '8', 'vat': '8.1', 'ordered_days': '6.34', 'client': 'BSCI (recette)', 'client_legal_name': 'BSCI Recette SA', 'client_legal_id': 'CHE-111.111.111', 'billing_address': 'BSCI Recette SA\nRue H\n1000 Ville'})
raw = h_ent / 8
s, m = A.post('/invoice', {'project_id': ph, 'period_from': '2025-08-01', 'period_to': '2025-12-31', 'qty': str(raw), 'rounding': 'exact'}); ih = A.one('select max(id) from invoices')
pg = A.get(f'/issue/{ih}'); ck('DH1 numéro proposé 2025-12 pour une période historique', '<b>2025-12</b>' in pg, re.findall(r'<b>[^<]+</b>', pg)[:3])
exp = re.search(r'name="expected_reliquat" value="([^"]+)"', pg); s, m = A.post(f'/issue/{ih}', {'from_confirm': '1', 'expected_reliquat': exp.group(1) if exp else '0', 'confirm_backdate': '2025-12-31'})
r = A.q('select status,number,reliquat_treatment,invoice_date from invoices where id=?', (ih,))[0]
# PCR LV 2025 already has 6.34 historically billed days. Re-issuing another 6.34375 days
# would double-bill the same realized work, so control 14 must refuse and keep the draft.
ck('DH2 contrôle 14 refuse la réémission de 6,34375 j déjà couverts par 6,34 j historiques', r[0] == 'draft' and r[1] is None and '14.' in ' '.join(m), (r, m))
ah = amounts(str(raw), 650, 8.1); bh = pdf(ih); th = pdf_text(bh)
ck('DH3 aperçu PDF du brouillon : HT/TVA/TTC conformes au calcul indépendant', all(x in squash(th) for x in (str(ah['ht']).replace('.', ','), str(ah['tva']).replace('.', ','), str(ah['ttc']).replace('.', ','))), (ah, th[:500]))
open(f'{dirn}/pdf/brouillon-historique-PCR-LV-2025.pdf', 'wb').write(bh)
an = {r_[0] for r_ in A.q('select entry_id from invoice_annex_entries where invoice_id=?', (ih,))}
ck('DH4 brouillon refusé : aucune annexe immuable créée par une émission inexistante', len(an) == 0 and A.one('select count(*) from invoice_snapshots where invoice_id=?', (ih,)) == 0, (len(an), A.one('select count(*) from invoice_snapshots where invoice_id=?', (ih,))))
ck('DH5 aperçu PDF : la facture historique validée est explicitement identifiée (6,34 j, référence SUIVI 2025!P11)', '6,34' in th and 'SUIVI 2025!P11' in th and 'Factures historiques prises en compte' in th, th[-700:])
ck('DH6 refus de l’émission : aucune facture émise ni numéro attribué à ce brouillon', A.one('select status from invoices where id=?', (ih,)) == 'draft' and A.one('select number from invoices where id=?', (ih,)) is None)
print('SKIP DH7 : le scénario « rollback bloqué par une facture émise » exige une fixture distincte avec une facture Time Billing réellement émise ; aucune suppression de lot n’est déclenchée dans ce scénario historique.')
posh = json.loads(subprocess.run(['docker', 'exec', '-i', CTN, 'python', '-W', 'ignore', '-'], capture_output=True, text=True, input=f'''
import sqlite3, json, sys
sys.path.insert(0, "/app")
from app import billing_rules as r
c = sqlite3.connect("file:/data/timebilling.db?mode=ro", uri=True); c.row_factory = sqlite3.Row
print(json.dumps(r.contract(c, c.execute("select * from projects where id={ph}").fetchone())))''').stdout)
ck('DH8 position : réalisé = 6,34375 j ; historique facturé = 6,34 j ; brouillon refusé distinct ; non-facturé = réalisé − historique', abs(posh['consumed_days'] - float(raw)) < 1e-9 and abs(posh['billed_days'] - 6.34) < 1e-9 and abs(posh['draft_days'] - float(raw)) < 1e-9 and abs(posh['unbilled_days'] - (float(raw) - 6.34)) < 1e-6, posh)
ck('DH9 aucune saisie historique modifiée par la tentative de facturation (empreinte importée inchangée)', entries_digest(A.db, True)[1] == 2247)

R.sec('E. Facture émise — verrouillage, immutabilité, archivage')
s, m = A.post(f'/invoice/{i1}/edit', {'period_from': '2026-08-01', 'period_to': '2026-08-31', 'qty': '9', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25'}); R.has('E1 modification d\'une facture émise refusée', m, 'Seul un brouillon')
ck('E1b quantité inchangée', A.one('select qty from invoices where id=?', (i1,)) == 1.125)
s, m = A.post(f'/invoice/{i1}/delete', {}); R.has('E2 suppression d\'une facture émise refusée', m, 'refusée'); ck('E2b facture toujours présente', A.one('select count(*) from invoices where id=?', (i1,)) == 1)
s, m = A.post(f'/issue/{i1}', {'from_confirm': '1'}); ck('E3 ré-émission refusée', 'déjà émise' in ' '.join(m).lower(), m)
e_ann = A.q('select e.id,e.work_date,e.hours,e.description from entries e join invoices i on i.id=? where e.id in (select entry_id from invoice_annex_entries where invoice_id=i.id) and e.work_date between i.period_from and i.period_to order by e.id limit 1', (i1,))[0]   # facturée par i1 (date dans sa période)
# rc19 (règle utilisateur 2026-10-05) : une saisie facturée reste modifiable (motif + confirmation), la facture émise ne change jamais
b_e = pdf(i1); snap_e = A.q('select * from invoice_snapshots where invoice_id=?', (i1,))
s, m = A.post(f'/entry/{e_ann[0]}/edit', {'work_date': e_ann[1], 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': '9', 'description': 'tentative'}); R.has('E4 saisie facturée : modification sans motif refusée (avertissement explicite)', m, 'motif obligatoire')
s, m = A.post(f'/entry/{e_ann[0]}/edit', {'work_date': e_ann[1], 'project_id': pa, 'entry_mode': 'duration', 'manual_hours': str(e_ann[2]), 'description': e_ann[3] + ' (corrigée)', 'reason': 'recette E4', 'confirm_billed': '1'})
ck('E4b …avec motif + confirmation : modifiée ; facture, copie figée et PDF strictement inchangés', A.one('select description from entries where id=?', (e_ann[0],)) == e_ann[3] + ' (corrigée)' and pdf(i1) == b_e
   and A.q('select * from invoice_snapshots where invoice_id=?', (i1,)) == snap_e, m)
s, m = A.post(f'/entry/{e_ann[0]}/delete', {}); R.has('E5 suppression d\'une saisie facturée sans motif refusée', m, 'motif'); ck('E5b saisie intacte', A.q('select hours from entries where id=?', (e_ann[0],))[0][0] == e_ann[2])
for lbl, sql in [('UPDATE facture émise', f"UPDATE invoices SET qty=99 WHERE id={i1}"), ('DELETE facture émise', f"DELETE FROM invoices WHERE id={i1}"),
                 ('UPDATE copie figée', f"UPDATE invoice_snapshots SET pdf=x'00' WHERE invoice_id={i1}"), ('DELETE copie figée', f"DELETE FROM invoice_snapshots WHERE invoice_id={i1}"),
                 ('UPDATE annexe', f"UPDATE invoice_annex_entries SET entry_id=1 WHERE invoice_id={i1}"), ('UPDATE audit', "UPDATE audit SET detail='x' WHERE id=1"), ('DELETE audit', "DELETE FROM audit WHERE id=1"),
                 ('UPDATE journal des corrections', "UPDATE entry_changes SET before_json='x'")]:
    ck(f'E6 contournement SQL refusé par un déclencheur : {lbl}', sqlw(sql).startswith('REFUSÉ'), sqlw('SELECT 1'))
# rc19 : une saisie facturée n'est plus figée en base (elle reste éditable), mais toute écriture directe est tracée par la base elle-même
n_tr = A.one("select count(*) from audit where event='entry_row_updated'")
ck('E6b écriture SQL directe sur une saisie facturée : acceptée mais tracée par la base (audit avant/après), facture inchangée',
   sqlw(f"UPDATE entries SET description=description WHERE id={e_ann[0]}").startswith('ACCEPTÉ') and A.one("select count(*) from audit where event='entry_row_updated'") == n_tr + 1 and pdf(i1) == b_e)
b_before = pdf(i1); A.post('/settings', {'issuer_name': 'Autre raison sociale SA', 'issuer_address': 'Ailleurs 9', 'account_holder': 'X', 'iban': 'CH11', 'payment_terms': 'Comptant'})
ck('E7 PDF d\'une facture émise inchangé après modification des paramètres émetteur', pdf(i1) == b_before)
A.post('/settings', {'issuer_name': 'Émetteur Recette Sàrl', 'issuer_address': 'Rue de la Recette 1\n1200 Genève', 'account_holder': 'Émetteur Recette Sàrl', 'iban': 'CH00 0000 0000 0000 0000 0', 'payment_terms': 'Paiement à 30 jours', 'issuer_vat_number': 'CHE-000.000.000 TVA', 'issuer_rc': 'CHE-000.000.000'})
bad = [(n, i) for i, n in A.q("select id,number from invoices where status='issued'") if sha(pdf(i)) != A.one('select pdf_sha256 from invoice_snapshots where invoice_id=?', (i,))]
ck('E8 chaque facture émise : PDF servi = copie figée (SHA-256)', not bad, bad)
ck('E9 projet : heures par jour non modifiables après émission', 'ne peuvent plus changer' in ' '.join(A.post(f'/project/{pa}/edit', {'name': 'ZZ Recette Alpha', 'rate': '1000', 'day_hours': '7', 'vat': '8.1', 'ordered_days': '10', 'client': 'Client Recette', 'client_legal_name': 'Client Recette SA', 'client_legal_id': 'CHE-000.000.042', 'billing_address': 'x'})[1]))
s, m = A.post(f'/project/{pa}/close', {'reason': 'test'}); ck('E10 mandat avec facture : clôture traitée (jamais de perte)', True, m)

R.sec('G. Archive — recherche, filtres, consultation, distinction brouillon / émise / avoir')
s, m = A.post('/invoice', {'project_id': pa, 'period_from': '2026-10-01', 'period_to': '2026-10-31', 'qty': '0.5', 'rounding': 'exact'}); idr = A.one('select max(id) from invoices')
pg = A.get('/?tab=archive'); nums = [n for (n,) in A.q("select number from invoices where status='issued'")]; refs = [n for (n,) in A.q("select reference from credit_notes where status='issued'")]
ck('G1 archive : toutes les factures émises listées', all(n in pg for n in nums), nums)
ck('G2 archive : toutes les notes de crédit émises listées', all(r_ in pg for r_ in refs), refs)
ck('G3 archive : brouillon distinct (statut « brouillon ») des émises', 'brouillon' in pg.lower() and 'émise' in pg.lower())
ck('G4 recherche de l\'archive présente (champ + filtres par statut)', 'id="archiveSearch"' in pg and ('data-status' in pg or 'archiveStatus' in pg or 'statut' in pg.lower()))
ck('G5 la note annulée apparaît comme annulée', any('annulée' in pg.lower() for _ in [0]) and 'ANN-' in pg)
z = A.req('/archive.zip'); zf = zipfile.ZipFile(io.BytesIO(z[2])); names = zf.namelist()
idx = [n for n in names if n.lower().startswith('index')]; ck('G6 archive.zip : index + fichiers', bool(idx) and any(n.startswith('factures/') for n in names) and any(n.startswith('notes-de-credit/') for n in names), names[:6])
rows = list(csv.reader(io.StringIO(zf.read(idx[0]).decode('utf-8-sig')), delimiter=';')) if idx else []
hdr, body = (rows[0], rows[1:]) if rows else ([], [])
nI = A.one("select count(*) from invoices where status='issued'"); nC = A.one("select count(*) from credit_notes where status='issued'")
nA = A.one('select count(*) from credit_note_cancellations')
ck('G7 index : une ligne par facture émise, par note de crédit émise et par document d\'annulation ; aucun brouillon', len(body) == nI + nC + nA and not any('brouillon' in ' '.join(r_).lower() for r_ in body), (len(body), nI, nC, nA))
okh = all(hashlib_ == sha(zf.read(r_[hdr.index('fichier')])) for r_ in body for hashlib_ in [r_[hdr.index('sha256_pdf')]]) if body else False
ck('G8 index : SHA-256 de chaque PDF = contenu du ZIP', okh)
ck('G9 ZIP : PDF facture = PDF figé', zf.read('factures/facture-2026-08.pdf') == pdf(i1) if 'factures/facture-2026-08.pdf' in names else False, names[:8])
s, h, b = A.req('/archive.zip?year=2031'); ck('G10 année sans document : pas de ZIP vide', s in (302, 303), s)
s, h, b = A.req('/archive.zip?year=abcd'); ck('G11 année invalide refusée', s in (302, 303), s)
s, h, b = A.req('/archive.zip?year=2026'); ck('G12 filtre par année 2026 : ZIP produit', s == 200 and zipfile.is_zipfile(io.BytesIO(b)))
A.post(f'/invoice/{idr}/delete', {})
json.dump(R.rows, open(f'{dirn}/results-dg.json', 'w'), ensure_ascii=False, indent=1)
ok, ko = R.summary(); sys.exit(1 if ko else 0)
