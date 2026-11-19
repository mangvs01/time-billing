"""Recette fonctionnelle — K. Prévision (tableau de bord) : recalcul indépendant en Decimal d'après la règle documentée, comparé au rendu HTTP.
usage: run_forecast.py <port> <dossier>   (instance JETABLE sur COPIE de la base staging ; des paramètres de mandats y sont modifiés en SQL pour couvrir les cas limites)"""
import sys, os, re, html, sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))
from lib import *
port, dirA = sys.argv[1], sys.argv[2]
A = App(port, f'{dirA}/pw.txt', f'{dirA}/data/timebilling.db'); R = Report('K'); ck = R.check; assert A.login()
today = datetime.now(ZoneInfo('Europe/Zurich')).date(); cur = today.year * 12 + today.month - 1
# La base de cette recette contient des factures historiques validées, mais aucun document
# Time Billing émis : sinon les quantités de ces documents doivent aussi être modélisées par l'oracle.
assert A.one("select count(*) from invoices where status='issued'") == 0, "précondition K : aucune facture Time Billing émise"
assert A.one("select count(*) from credit_notes where status='issued' and id not in (select credit_note_id from credit_note_cancellations)") == 0, "précondition K : aucune note de crédit active émise"
idx = lambda ym: int(ym[:4]) * 12 + int(ym[5:7]) - 1
ym = lambda i: f'{i // 12:04d}-{i % 12 + 1:02d}'

def expected():
    """Règle : solde PO (jours commandés − facturés nets) × tarif, réparti à parts égales du mois courant (ou début si postérieur) à la fin du mandat ; le dernier mois absorbe l'arrondi."""
    months, expired, undated = {}, [], []
    for p in A.q("select id, name, rate, ordered_days, start_date, duration_months from projects where active=1 order by name"):
        pid, name, rate, od, sd, dur = p
        # Oracle indépendant : les 23 factures historiques validées de la copie consomment
        # le PO en jours ; les lignes proposées/rejetées ne comptent pas. Cette recette
        # n'accepte aucune facture Time Billing ni note de crédit sur sa base de départ.
        hist_days = D(str(A.one("select coalesce(sum(qty_days),0) from historical_invoices where project_id=? and status='validated'", (pid,))))
        bal = (max(D(str(od or 0)) - hist_days, D(0)) * D(str(rate or 0))).quantize(CENT, ROUND_HALF_UP)
        if bal <= 0: continue
        if sd: start = idx(sd)
        else: start = cur; undated.append(name)
        end = start + max(1, int(dur or 12)) - 1; first = max(cur, start)
        if end < first: expired.append((name, ym(end), bal)); continue
        n = end - first + 1; share = (bal / n).quantize(CENT, ROUND_HALF_UP)
        for k in range(n):
            months[ym(first + k)] = months.get(ym(first + k), D(0)) + (share if k < n - 1 else bal - share * (n - 1))
    return months, expired, undated

def rendered():
    pg = A.get('/?tab=mandates')
    out = {}
    for m, amt in re.findall(r'<title>(\d{4}-\d{2}) : ([^<]*)</title>', pg):
        out[m] = D(re.sub(r'[^\d,]', '', html.unescape(amt)).replace(',', '.'))
    return pg, out

def compare(label):
    pg, got = rendered(); exp, expired, undated = expected()
    ck(f'K {label} : {len(exp)} mois de prévision affichés = recalcul indépendant (mêmes mois)', set(got) == set(exp), (sorted(set(got) ^ set(exp))[:6]))
    bad = {m: (str(got.get(m)), str(exp.get(m))) for m in exp if got.get(m) != exp[m]}
    ck(f'K {label} : montant de chaque mois identique au centime', not bad, dict(list(bad.items())[:4]))
    allbal = D(0)
    for pid, od, rate in A.q("select id, ordered_days, rate from projects where active=1 and ordered_days>0 and rate>0"):
        hist_days = D(str(A.one("select coalesce(sum(qty_days),0) from historical_invoices where project_id=? and status='validated'", (pid,))))
        allbal += (max(D(str(od or 0)) - hist_days, D(0)) * D(str(rate or 0))).quantize(CENT, ROUND_HALF_UP)
    tot = sum(exp.values(), D(0)); ck(f'K {label} : total réparti + échu = solde PO total des mandats actifs (rien perdu, rien créé)', tot + sum((e[2] for e in expired), D(0)) == allbal, (tot, allbal))
    cy = sum((v for m, v in exp.items() if m[:4] == str(today.year)), D(0))
    kp = re.search(r'Prévision restante \d{4}</span><span class="k-value">([^<]*)<', pg)
    ck(f'K {label} : indicateur « Prévision restante {today.year} » = somme des mois de l\'année', kp and D(re.sub(r'[^\d,]', '', html.unescape(kp.group(1))).replace(',', '.')) == cy, (kp.group(1) if kp else None, cy))
    ck(f'K {label} : mandats échus signalés à part ({len(expired)}) et non répartis', all(e[0] in pg for e in expired), [e[0] for e in expired][:3])
    return exp, expired, undated

R.sec('K. Prévision — recalcul indépendant (règle documentée)')
# --- état réel du staging après la décision C1 (19 mandats TERMINE clôturés) : la prévision ne compte que les 5 mandats actifs ---
nact, nclos = A.one('select count(*) from projects where active=1'), A.one('select count(*) from projects where active=0')
ck('K-C1 état réel : 19 mandats clôturés, 5 actifs', (nact, nclos) == (5, 19), (nact, nclos))
exp_c1, ex_c1, un_c1 = compare('état réel après C1 (19 mandats clôturés)')
tot_c1 = sum(exp_c1.values(), D(0)) + sum((e[2] for e in ex_c1), D(0))
ck('K-C1 prévision totale = 27 050 CHF (PCR LV 2026 5 850 + NHAF 2026 10 400 + STC GEM Oct 10 800), contre 134 521 CHF avant clôture', tot_c1 == D('27050.00'), tot_c1)
# --- la copie jetable est ensuite remise dans l'état « tous mandats actifs » (SQL sur la COPIE seulement) pour les cas limites ci-dessous ---
cc = sqlite3.connect(A.db); cc.execute('pragma busy_timeout=5000'); cc.execute("update projects set active=1, closed_at=NULL, closed_reason='' where active=0"); cc.commit(); cc.close()
exp0, ex0, un0 = compare('base historique (24 mandats rouverts sur la copie, sans date de début)')
ck('K0 mandats sans date de début : traités comme commençant le mois courant (12 mois)', len(un0) > 0 and min(exp0) == ym(cur) and max(exp0) == ym(cur + 11), (min(exp0), max(exp0), len(un0)))

# --- cas limites sur la COPIE jetable (SQL direct, jamais sur le staging réel) ---
c = sqlite3.connect(A.db); c.execute('pragma busy_timeout=5000')
names = [r[0] for r in c.execute("select name from projects where active=1 and ordered_days>0 and rate>0 order by name limit 5")]
past = ym(cur - 14) + '-01'; fut = ym(cur + 3) + '-15'; mid = ym(cur - 2) + '-01'
c.execute("update projects set start_date=?, duration_months=6 where name=?", (past, names[0]))          # échu
c.execute("update projects set start_date=?, duration_months=5 where name=?", (fut, names[1]))           # début futur
c.execute("update projects set start_date=?, duration_months=4 where name=?", (mid, names[2]))           # en cours, 2 mois restants
c.execute("update projects set start_date=?, duration_months=1 where name=?", (ym(cur) + '-01', names[3]))  # un seul mois
c.execute("update projects set active=0, closed_at='2026-01-01T00:00:00', closed_reason='recette K' where name=?", (names[4],))  # clôturé : exclu
c.commit(); c.close()
exp1, ex1, un1 = compare('cas limites (échu, début futur, en cours, 1 mois, clôturé)')
ck('K1 mise en place : un mandat échu, un clôturé, un début futur, un sur un seul mois', any(e[0] == names[0] for e in ex1) and len(ex1) >= 1, [e[0] for e in ex1])
bal4 = D(str(A.one("select ordered_days from projects where name=?", (names[4],)))) * D(str(A.one("select rate from projects where name=?", (names[4],))))
ck('K2 le mandat clôturé avait un solde > 0 mais n\'est compté nulle part (exclu par la règle)', bal4 > 0 and not any(names[4] == e[0] for e in ex1), bal4)
fm = ym(idx(fut[:7])); ck('K3 aucun mois de prévision du mandat à début futur avant son début (le mois de début existe)', fm in exp1, fm)
ok = sum(1 for r in R.rows if r['ok']); ko = [r for r in R.rows if not r['ok']]
print(f"\nRÉSULTAT K : {ok}/{len(R.rows)} OK, {len(ko)} KO")
for r in ko: print('  KO', r['section'], '|', r['test'], '|', r['detail'])
sys.exit(1 if ko else 0)
