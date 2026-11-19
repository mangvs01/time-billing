"""Recette fonctionnelle — R. RC19 « saisies toujours éditables, facture émise immuable », sur une COPIE jetable du staging
(2 247 saisies historiques réelles, 24 mandats dont 19 clôturés, paramètres émetteur). Jamais le staging réel.
Recette demandée par l'utilisateur (2026-10-05) : R1 saisie historique importée, R2 début/fin, R3 durée, R4 description, R5 mandat clôturé,
R6 saisie déjà facturée, R7 facture émise strictement inchangée, R8 écart post-facturation visible, R9 audit avant/après, R10 un avoir
corrige ensuite la situation. En plus : les 2 247 saisies historiques ouvrent toutes un formulaire de correction actif, provenance conservée,
annexe cumulative, suppression d'une saisie facturée, annulation de lot refusée après correction.
usage: run_rc19.py <port> <dossier-instance>"""
import sys, os, re, json, html, hashlib, zipfile, io
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
port, dirn = sys.argv[1], sys.argv[2]; A = App(port, f'{dirn}/pw.txt', f'{dirn}/data/timebilling.db'); R = Report('R'); ck = R.check; assert A.login()
txt = lambda p: re.sub(r'\s+', ' ', html.unescape(re.sub(r'<script.*?</script>|<style.*?</style>', ' ', p, flags=re.S).replace('<', ' <')).replace('\xa0', ' '))
strip = lambda p: re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'<script.*?</script>|<style.*?</style>', ' ', p, flags=re.S)))).replace('\xa0', ' ')
DISABLED = re.compile(r'<(input|select|button|textarea)[^>]*\bdisabled\b')

def entry(eid): return A.q('select work_date,project_id,start_time,end_time,hours,description,source,source_ref,import_batch_id from entries where id=?', (eid,))[0]
def edit(eid, **kw):
    e = entry(eid)
    f = {'work_date': e[0], 'project_id': str(e[1]), 'entry_mode': 'clock' if (e[2] and e[3]) else 'duration', 'start_time': e[2], 'end_time': e[3],
         'manual_hours': '' if (e[2] and e[3]) else str(e[4]), 'description': e[5], 'return_to': '/entries'}
    pg = A.get(f'/entry/{eid}/edit'); rv = re.search(r'name="rev" value="([0-9a-f]+)"', pg); f['rev'] = rv.group(1) if rv else ''
    f.update(kw); return A.post(f'/entry/{eid}/edit', f)
def frozen(iid):
    return (A.q('select * from invoices where id=?', (iid,)), A.q('select invoice_id,number,frozen_at,frozen_by,header_json,annex_json,pdf_sha256,hex(pdf) from invoice_snapshots where invoice_id=?', (iid,)),
            A.q('select * from invoice_annex_entries where invoice_id=? order by entry_id', (iid,)), sha(A.req(f'/invoice/{iid}.pdf')[2]))
def zip_pdfs():
    z = zipfile.ZipFile(io.BytesIO(A.req('/archive.zip')[2])); return {n: sha(z.read(n)) for n in z.namelist() if n.lower().endswith('.pdf')}

SNAP0 = {r[0]: r[1:] for r in A.q('select id,work_date,project_id,start_time,end_time,hours,description,source,source_ref,import_batch_id from entries where import_batch_id is not null')}
n0, h0 = A.q('select count(*), round(sum(hours),4) from entries')[0]
R.sec('R0. État de départ (copie du staging)')
ck('R0a copie : 2 247 saisies historiques importées, 24 mandats dont 19 clôturés, 1 facture = brouillon n°1 de l\'utilisateur (aucune émise, aucun numéro)', (n0, A.one('select count(*) from projects'), A.one('select count(*) from projects where active=0'),
   A.q("select count(*), coalesce(sum(status='issued'),0), coalesce(sum(number is not null),0) from invoices")[0]) == (2247, 24, 19, (1, 0, 0)), (n0, h0))
# version attendue = TB_EXPECT_VERSION, sinon VERSION de l'arbre du dépôt (l'image candidate en est construite) ; avant : « rc23 » en dur
EXPECT = os.environ.get('TB_EXPECT_VERSION') or re.search(r'^VERSION="([^"]+)"', open('/root/time-billing-v9-rc10-20261004/app/app.py').read(), re.M).group(1)
ck(f'R0b version {EXPECT}', f'"version":"{EXPECT}"' in A.get('/health').replace(' ', ''), A.get('/health'))

R.sec('R0. Les 2 247 saisies historiques : aucun verrou')
ids = [r[0] for r in A.q('select id from entries where import_batch_id is not null order by id')]
bad = []
for i in ids:
    pg = A.get(f'/entry/{i}/edit')
    if 'Enregistrer la correction' not in pg or DISABLED.search(pg) or 'ne peut pas être modifiée' in pg or 'Provenance (import historique)' not in pg: bad.append(i)
ck(f'R0c les {len(ids)} saisies importées ouvrent un formulaire de correction actif avec leur provenance (aucun champ désactivé)', len(ids) == 2247 and not bad, bad[:10])
lst = strip(A.get('/entries')); ck('R0d liste des saisies : plus aucune mention « verrouillée », bouton Modifier sur chaque ligne', 'verrouillée' not in lst and A.get('/entries').count('>Modifier<') == 50, lst[:200])

R.sec('R1–R4. Saisie historique importée (mandat clôturé) : date, début/fin, durée, description, provenance conservée')
e1 = A.one("select e.id from entries e join projects p on p.id=e.project_id where e.import_batch_id is not null and p.active=0 and e.start_time<>'' and e.end_time<>'' order by e.id limit 1")
before1 = entry(e1); prov = A.q('select * from import_batch_rows where entry_id=?', (e1,)); batch = A.q('select * from import_batches where id=?', (before1[8],))
pg = strip(A.get(f'/entry/{e1}/edit')); raw = json.loads(prov[0][4])
ck('R1a page de correction : provenance affichée (fichier, onglet · ligne, lot, date d\'import, valeurs du classeur)', all(x in pg for x in ['Time sheet CP.xlsx', f'{prov[0][2]} · ligne {prov[0][3]}', before1[8], "Date d'import", 'Valeurs lues dans le classeur']), pg[:300])
s, m = edit(e1, work_date=before1[0][:8] + ('02' if before1[0][8:] != '02' else '03'))
ck('R1b date corrigée (saisie importée d\'un mandat clôturé)', entry(e1)[0] != before1[0] and any('modifiée' in x for x in m), m)
s, m = edit(e1, start_time='08:15', end_time='11:45'); ck('R2 début/fin corrigés : 08:15 → 11:45 = 3,5 h recalculées', entry(e1)[2:5] == ('08:15', '11:45', 3.5), (entry(e1), m))
s, m = edit(e1, entry_mode='duration', start_time='', end_time='', manual_hours='2.75'); ck('R3 durée corrigée (mode durée) : 2,75 h', entry(e1)[2:5] == ('', '', 2.75), (entry(e1), m))
s, m = edit(e1, description=before1[5] + ' — corrigée RC19'); ck('R4 description corrigée', entry(e1)[5].endswith('corrigée RC19'), m)
ck('R1c provenance inchangée : source, référence, lot, ligne du registre d\'import, lot d\'import', entry(e1)[6:9] == before1[6:9] and A.q('select * from import_batch_rows where entry_id=?', (e1,)) == prov
   and A.q('select * from import_batches where id=?', (before1[8],)) == batch)
ch = A.q('select action,before_json,after_json,changed_at,reason,actor,invoices_json from entry_changes where entry_id=? order by id', (e1,))
ck('R1d historique : 4 corrections, avant/après complets (provenance comprise), horodatage, utilisateur', len(ch) == 4 and json.loads(ch[0][1])['source_ref'] == before1[7]
   and json.loads(ch[0][1])['import_batch_id'] == before1[8] and all(c[5] == 'admin' and c[3] for c in ch), ch[:1])

R.sec('R5. Mandat clôturé : anciennes saisies modifiables, nouvelles refusées, réaffectation')
pc = entry(e1)[1]; pname = A.one('select name from projects where id=?', (pc,)); act = A.one("select id from projects where name='NHAF 2026'")
other_closed = A.one('select id from projects where active=0 and id<>? order by id limit 1', (pc,))
s, m = A.post('/entry', {'work_date': '2026-10-01', 'project_id': pc, 'entry_mode': 'duration', 'manual_hours': '1', 'description': 'nouvelle sur clôturé'})
ck('R5a nouvelle saisie sur un mandat clôturé : refusée', A.one("select count(*) from entries where description='nouvelle sur clôturé'") == 0 and any('clôturé' in x for x in m), m)
s, m = edit(e1, project_id=str(other_closed)); ck('R5b réaffectation vers un AUTRE mandat clôturé : refusée sans la case explicite', entry(e1)[1] == pc and any('Rattacher à un mandat clôturé' in x for x in m), m)
s, m = edit(e1, project_id=str(other_closed), allow_closed='1'); ck('R5c … et refusée avec la case mais sans motif', entry(e1)[1] == pc and any('motif obligatoire' in x for x in m), m)
s, m = edit(e1, project_id=str(other_closed), allow_closed='1', reason='affectation corrigée (recette)'); ck('R5c2 … acceptée avec la case « Rattacher à un mandat clôturé » et un motif, avertissement de facturation', entry(e1)[1] == other_closed and any('ne peuvent pas être facturées' in x for x in m), m)
s, m = edit(e1, project_id=str(pc), allow_closed='1', reason='retour au mandat d\'origine'); ck('R5d retour vers son mandat clôturé d\'origine : autre mandat clôturé, donc avec la case explicite et un motif', entry(e1)[1] == pc, m)
e5 = A.one('select id from entries where import_batch_id is not null and project_id=? and id<>? order by id limit 1', (pc, e1))
s, m = edit(e5, project_id=str(act)); ck('R5e réaffectation d\'une saisie historique vers un mandat actif : acceptée', entry(e5)[1] == act, m)
ck('R5f les mandats restent clôturés / actifs', A.one('select active from projects where id=?', (pc,)) == 0 and A.one('select active from projects where id=?', (other_closed,)) == 0)

R.sec('R6–R10. Saisie déjà facturée : exemple de l\'utilisateur (5 h facturées, corrigées à 4,5 h)')
s, m = A.post('/entry', {'work_date': '2026-10-01', 'project_id': act, 'entry_mode': 'duration', 'manual_hours': '5', 'description': 'Atelier RC19 facturé'})
eb = A.one("select id from entries where description='Atelier RC19 facturé'")
s, m = A.post('/invoice', {'project_id': act, 'period_from': '2026-10-01', 'period_to': '2026-10-04', 'qty': '0.625', 'unit': 'day', 'rounding': 'exact', 'rounding_step': '0.25'})
iid = A.one('select max(id) from invoices'); pg = A.get(f'/issue/{iid}'); fm = {'from_confirm': '1', 'reliquat_treatment': 'reporte'}
ex = re.search(r'name="expected_reliquat" value="([^"]+)"', pg)
if ex: fm['expected_reliquat'] = ex.group(1)
s, m = A.post(f'/issue/{iid}', fm); num = A.one('select number from invoices where id=?', (iid,))
ck('R6a facture émise : 0,625 j (5 h) sur NHAF 2026, période 01–04.10.2026', A.one('select status from invoices where id=?', (iid,)) == 'issued', m)
F0 = frozen(iid); Z0 = zip_pdfs(); hist_annexed = A.one('select count(*) from invoice_annex_entries x join entries e on e.id=x.entry_id where x.invoice_id=? and e.import_batch_id is not null', (iid,))
ck('R6b l\'annexe cumulative figée liste aussi les saisies historiques du mandat', hist_annexed > 0, hist_annexed)
pg = strip(A.get(f'/entry/{eb}/edit'))
ck('R6c page de correction : avertissement explicite, facture citée, motif et confirmation obligatoires', all(x in pg for x in ['Saisie déjà facturée', num, 'Motif de la correction (obligatoire', 'Je confirme']), pg[:400])
s, m = edit(eb, manual_hours='4.5'); ck('R6d sans motif : refusé, saisie inchangée', entry(eb)[4] == 5, m)
s, m = edit(eb, manual_hours='4.5', reason='durée réelle 4,5 h'); ck('R6e sans confirmation : refusé, saisie inchangée', entry(eb)[4] == 5, m)
s, m = edit(eb, manual_hours='4.5', reason='durée réelle 4,5 h', confirm_billed='1')
ck('R6f avec motif + confirmation : modifiée (4,5 h)', entry(eb)[4] == 4.5 and any('modifiée' in x for x in m), m)
ck('R7a facture émise strictement inchangée : ligne, copie figée (en-tête, annexe, PDF), liens d\'annexe, PDF servi', frozen(iid) == F0)
ck('R7b archive ZIP des documents émis identique', zip_pdfs() == Z0)
ck('R8a message après correction : écart post-facturation −0,50 h (−0,0625 j), facture inchangée, choix laissés', any('Écart post-facturation' in x and '−0,50 h' in x and '−0,0625 j' in x and 'inchangée' in x for x in m), m)
arch = strip(A.get('/?tab=archive')); ck('R8b historique des factures : ligne d\'écart sous la facture', 'Écart post-facturation : −0,50 h (−0,0625 j)' in arch, arch[arch.find(num):][:300])
dash = A.get('/'); ck('R8c tableau de bord : encadré « Écarts post-facturation »', 'variancesAlert' in dash and num in strip(dash[dash.find('variancesAlert'):][:1500]))
vp = strip(A.get(f'/invoice/{iid}/ecart'))
ck('R8d page d\'écart : 5,00 h facturées, 4,50 h actuelles, écart −0,50 h / −0,0625 j, valeur indicative −40,63 CHF', all(x in vp for x in ['5,00 h', '4,50 h', '−0,50 h', '−0,0625 j', '−40,63 CHF', 'modifiée']), vp[:600])
pos = re.search(r'NHAF 2026 : ([\d,−-]+) j facturés nets, ([\d,−-]+) j réalisés non facturés', html.unescape(dash))
ck('R8e indicateurs actuels recalculés depuis la saisie corrigée (facturé net 0,63 j inchangé)', pos and pos.group(1) in ('0,63', '0,625'), pos.groups() if pos else None)
c9 = A.q('select action,before_json,after_json,changed_at,reason,actor,invoices_json from entry_changes where entry_id=? order by id desc limit 1', (eb,))[0]
inv_j = json.loads(c9[6])
ck('R9a historique : avant 5 h / après 4,5 h, date-heure, utilisateur, motif, facture concernée (rôle facturée)', json.loads(c9[1])['hours'] == 5 and json.loads(c9[2])['hours'] == 4.5 and c9[3]
   and c9[4] == 'durée réelle 4,5 h' and c9[5] == 'admin' and inv_j == [{'id': iid, 'number': num, 'period_from': '2026-10-01', 'period_to': '2026-10-04', 'role': 'billed'}], c9)
au = A.q("select event,detail from audit where event in ('time_entry_updated','entry_row_updated') order by id desc limit 2")
ck('R9b journal d\'audit : évènement applicatif (facture, utilisateur, motif) + trace posée par la base elle-même', {a[0] for a in au} == {'time_entry_updated', 'entry_row_updated'}
   and any(a[0] == 'time_entry_updated' and json.loads(a[1])['invoices'] == [f'{num}:billed'] and json.loads(a[1])['reason'] == 'durée réelle 4,5 h' for a in au), au)
hp = strip(A.get(f'/entry/{eb}/edit')); ck('R9c historique visible sur la page de la saisie (motif, utilisateur, facture)', all(x in hp for x in ['motif : durée réelle 4,5 h', 'par admin', f'facturée par {num}']))
link = re.search(r'href="(/invoice/\d+/credit\?ecart=1)"', A.get(f'/invoice/{iid}/ecart'))
cf = A.get(html.unescape(link.group(1))) if link else ''
ck('R10a proposition de note de crédit calculée par le serveur : 0,0625 j, motif « Ajustement des heures facturées… » (rien n\'est émis automatiquement)', link and 'value="0.0625"' in cf and 'Ajustement des heures facturées' in html.unescape(cf)
   and A.one('select count(*) from credit_notes') == 0, link.group(1) if link else None)
s, m = A.post(f'/invoice/{iid}/credit', {'treatment': 'remboursement', 'scope': 'partial', 'reason': 'Écart post-facturation : durée corrigée à 4,5 h', 'qty': '0.0625', 'unit_rate': '650'})
cid = A.one('select max(id) from credit_notes'); s, m2 = A.post(f'/credit/{cid}/issue', {})
ck('R10b note de crédit de 0,0625 j émise (40,63 CHF)', A.q('select status,qty,amount from credit_notes where id=?', (cid,))[0] == ('issued', 0.0625, 40.63), (m, m2))
vp = strip(A.get(f'/invoice/{iid}/ecart')); ck('R10c écart restant après la note de crédit émise après la correction : 0', 'Écart restant après ces notes de crédit' in vp and '0,0000 j' in vp[vp.find('Écart restant'):][:200], vp[vp.find('Notes de crédit'):][:300])
dash = html.unescape(A.get('/')); ck('R10d tant que la décision n\'est pas enregistrée, l\'alerte reste (la note seule ne décide pas à la place de l\'utilisateur)', 'variancesAlert' in dash)
fp = re.search(r'name="fingerprint" value="([0-9a-f]+)"', A.get(f'/invoice/{iid}/ecart')).group(1)
s, m = A.post(f'/invoice/{iid}/ecart/decision', {'fingerprint': fp, 'decision': 'avoir', 'credit_note_id': str(cid), 'reason': 'avoir de l\'écart'})
dec = A.q('select decision,credit_note_id,variance_hours,actor from invoice_variance_decisions where invoice_id=?', (iid,))
ck('R10e décision « note de crédit » enregistrée (registre en ajout seul : décision, note, écart, utilisateur)', dec == [('avoir', cid, -0.5, 'admin')], (dec, m))
dash = html.unescape(A.get('/')); pos = re.search(r'NHAF 2026 : ([\d,−-]+) j facturés nets', dash)
ck('R10f tableau de bord : plus d\'alerte d\'écart, facturé net réduit de l\'avoir', 'variancesAlert' not in dash and pos and pos.group(1) in ('0,56', '0,5625'), pos.groups() if pos else None)
ck('R10g la facture d\'origine reste identique après l\'avoir et la décision', frozen(iid) == F0)

R.sec('R11. Annexe cumulative et suppression d\'une saisie facturée')
eh = A.one("select e.id from entries e join invoice_annex_entries x on x.entry_id=e.id where x.invoice_id=? and e.import_batch_id is not null order by e.id limit 1", (iid,))
pg = strip(A.get(f'/entry/{eh}/edit')); ck('R11a saisie historique listée par l\'annexe cumulative : modifiable sans motif obligatoire, information affichée', 'annexe cumulative figée' in pg and 'Saisie déjà facturée' not in pg)
s, m = edit(eh, description=entry(eh)[5] + ' (annexe)'); vp = strip(A.get(f'/invoice/{iid}/ecart'))
ck('R11b … corrigée, l\'écart de la facture ne bouge pas (hors période facturée : −0,50 h, restant 0)', entry(eh)[5].endswith('(annexe)') and '−0,50 h' in vp and '0,0000 j' in vp[vp.find('Écart restant'):][:200], m)
s, m = A.post(f'/entry/{eb}/delete', {'return_to': '/entries'}); ck('R11c suppression d\'une saisie facturée sans motif : refusée, renvoi vers sa page', A.one('select count(*) from entries where id=?', (eb,)) == 1, m)
s, m = A.post(f'/entry/{eb}/delete', {'return_to': '/entries', 'reason': 'test de suppression', 'confirm_billed': '1'})
ck('R11d … avec motif + confirmation : supprimée, facture inchangée, écart −5,00 h', A.one('select count(*) from entries where id=?', (eb,)) == 0 and frozen(iid) == F0 and '−5,00 h' in strip(A.get(f'/invoice/{iid}/ecart')), m)
ck('R11e intégrité SQLite et clés étrangères', A.one('pragma integrity_check') == 'ok' and A.q('pragma foreign_key_check') == [])

R.sec('R12. Lot d\'import : annulation refusée dès qu\'une de ses saisies a été corrigée')
b1 = entry(e1)[8]; s, m = A.post(f'/imports/rollback/{b1}', {})
ck('R12a annulation du lot de e1 refusée (lot couvert par la facture émise, et corrigé)', A.one('select status from import_batches where id=?', (b1,)) == 'COMMITTED' and any('Rollback refusé' in x for x in m), m)
bfree = A.one("""select b.id from import_batches b where b.status='COMMITTED' and b.id<>? and not exists(select 1 from entries e join invoices i on i.project_id=e.project_id
                 and i.status='issued' and e.work_date<=i.period_to where e.import_batch_id=b.id) order by b.inserted_rows, b.id limit 1""", (b1,))
ef = A.one('select id from entries where import_batch_id=? order by id limit 1', (bfree,)); nfree = A.one('select inserted_rows from import_batches where id=?', (bfree,))
s, m = edit(ef, description=entry(ef)[5] + ' (lot)'); s, m = A.post(f'/imports/rollback/{bfree}', {})
ck('R12b lot non facturé dont une saisie a été corrigée : annulation refusée (« corrigées »), toutes ses saisies conservées', A.one('select status from import_batches where id=?', (bfree,)) == 'COMMITTED'
   and any('corrigées' in x for x in m) and A.one('select count(*) from entries where import_batch_id=?', (bfree,)) == nfree, m)
now = {r[0]: r[1:] for r in A.q('select id,work_date,project_id,start_time,end_time,hours,description,source,source_ref,import_batch_id from entries where import_batch_id is not null')}
touched = {i for i in SNAP0 if now.get(i) != SNAP0[i]}
ck('R13 2 247 saisies historiques toujours présentes ; seules les saisies corrigées par cette recette diffèrent (e1, e5, annexe, lot), aucune réimportée', len(now) == 2247 and touched == {e1, e5, eh, ef}, (len(now), sorted(touched)[:10]))
R.summary(); ko = [r for r in R.rows if not r['ok']]; sys.exit(1 if ko else 0)
