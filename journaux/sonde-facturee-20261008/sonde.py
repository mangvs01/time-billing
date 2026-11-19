"""Sonde (lecture du comportement, base jetable) : rôle « facturée » purement par date + annexe cumulative.
Lancement : voir run.sh (PYTHONPATH=dépôt, aucune écriture dans le dépôt)."""
import html as H, os, re, shutil, sqlite3, tempfile, unittest

import app.app as m
from app import post_billing, invoice_checks
from tests.test_import import FAKE_ISSUER
from tests.test_v92 import V92

PROBE = os.path.dirname(os.path.abspath(__file__))


def P(*a): print(*a, flush=True)


class Sonde(V92):
    def setUp(self):  # = Base.setUp, mais base jetable sous le dossier de la sonde (pas /data)
        self.tmp = tempfile.mkdtemp(dir=os.path.join(PROBE, 'data'))
        self.db = os.path.join(self.tmp, 'timebilling.db')
        m.DB = self.db; m.init()
        m.APP.config['TESTING'] = True
        self.c = m.APP.test_client()
        r = self.c.post('/login', data={'username': m.SEC['user'], 'password': os.environ['APP_PASSWORD']})
        assert r.status_code == 302
        self.c.post('/settings', data=FAKE_ISSUER)
        self.pid = self.mandate(name='Mandat M', rate='800', vat='0', ordered='20', start='2026-01-01', months='12')

    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ----------------------------------------------------------------------------------
    def eid(self, desc): return self.scalar('SELECT id FROM entries WHERE description=?', (desc,))
    def inv(self, iid): return self.sql('SELECT * FROM invoices WHERE id=?', (iid,))[0]

    def edit(self, eid, **kw):
        r0 = self.sql('SELECT * FROM entries WHERE id=?', (eid,))[0]
        data = {'work_date': r0['work_date'], 'project_id': str(r0['project_id']), 'entry_mode': 'duration', 'manual_hours': str(r0['hours']),
                'description': r0['description']}
        g = self.c.get(f'/entry/{eid}/edit').get_data(as_text=True)
        for k in ('rev', 'billed_ids'):
            mm = re.search(rf'name="{k}" value="([^"]*)"', g)
            if mm: data[k] = mm.group(1)
        data.update(kw)
        self.flashes(); r = self.c.post(f'/entry/{eid}/edit', data=data)
        return r.status_code, self.flashes()

    def variance(self, iid):
        c = m.db()
        try: return post_billing.invoice_variance(c, c.execute('SELECT * FROM invoices WHERE id=?', (iid,)).fetchone())
        finally: c.close()

    def roles(self, eid):
        c = m.db()
        try:
            ei = post_billing.entries_invoices(c, [eid]).get(eid, [])
            row = m.annotate_entries(c, [dict(c.execute(m.ENTRY_SQL + ' WHERE e.id=?', (eid,)).fetchone())])[0]
        finally: c.close()
        return [(x['number'], x['role'], (x['frozen'] or {}).get('work_date')) for x in ei], row['billed_by'], row['billed_changed'], row['annex_of']

    def checks(self, iid):
        c = m.db()
        try: return invoice_checks.run_checks(c, iid)
        finally: c.close()

    def show_checks(self, iid):
        for ch in self.checks(iid):
            if ch['n'] in (1, 6, 8, 12) or ch['status'] != 'ok':
                P(f"   contrôle {ch['n']:>2} [{ch['status']}{' dérogeable' if ch['derogable'] else ''}] {ch['detail'][:170]}")

    def issue_page(self, iid):
        t = H.unescape(self.c.get(f'/issue/{iid}').get_data(as_text=True))
        t = re.sub(r'<[^>]+>', ' ', t); t = re.sub(r'\s+', ' ', t)
        out = []
        for pat in (r'Saisies déjà facturées corrigées[^.]*\.[^.]*\.', r'Reliquat après cette facture [^A-Z]{0,80}', r'Traitement du reliquat[^—]*', r'double facturation[^.]{0,80}'):
            for mm in re.finditer(pat, t): out.append(mm.group(0)[:260])
        return out

    def show_var(self, iid):
        v = self.variance(iid)
        P(f"   écart {v['number']}: frozen={v['frozen_hours']} h current={v['current_hours']} h variance={v['variance_hours']} h "
          f"needs_decision={v['needs_decision']} remaining_units={v['remaining_units']}")
        P(f"     changed={[(x['id'], x['status'], x['where']) for x in v['changed']]} late={[e['id'] for e in v['late']]} "
          f"reclassified={[(e['id'], e['billed_by']) for e in v['reclassified']]} earlier_changed={[x['id'] for x in v['earlier_changed']]}")
        page = H.unescape(self.c.get(f'/invoice/{iid}/ecart').get_data(as_text=True))
        mm = re.search(r'créer une note de crédit de [^<]*', page)
        P(f"     page /invoice/{iid}/ecart : {mm.group(0) if mm else 'aucune note de crédit proposée'}")
        return v

    def suggest_sept(self):
        st, js = self.suggest(self.pid, '2026-09-01', '2026-09-30')
        P(f"   /suggest sept : hours={js['hours']} already_billed_hours={js['already_billed_hours']} suggested_qty={js['suggested_qty']} j "
          f"unbilled_days_to_date={js['unbilled_days_to_date']}")
        return js

    def issue_try(self, iid, label):
        self.flashes(); self.issue(iid, derogate=False)
        st = self.inv(iid)['status']; fl = self.flashes()
        P(f"   émission {label} SANS dérogation -> statut={st} ; flash={[f[:230] for f in fl]}")
        if st != 'issued':
            self.flashes(); self.issue(iid, derogate=True); st = self.inv(iid)['status']
            P(f"   émission {label} AVEC motifs de dérogation 12/13 -> statut={st} ; flash={[f[:160] for f in self.flashes()]}")
        return st

    # -- scénario commun : F08 (août) facture S ; S déplacée en septembre --------------------------
    def base_f08_then_move(self):
        self.entry(self.pid, '2026-08-20', 8, 'S travail août')
        self.entry(self.pid, '2026-09-10', 4, 'T travail septembre')
        S = self.eid('S travail août'); T = self.eid('T travail septembre')
        f08 = self.issued(self.pid, '2026-08-01', '2026-08-31', 1)
        P(f"F08 émise : {self.inv(f08)['number']} qty={self.inv(f08)['qty']} j ; annexe S : {self.roles(S)}")
        st, fl = self.edit(S, work_date='2026-09-15', reason='date corrigée : travail fait en septembre')
        P(f"Édition S sans confirmation -> HTTP {st} ; flash={[f[:200] for f in fl]} ; date={self.scalar('SELECT work_date FROM entries WHERE id=?', (S,))}")
        st, fl = self.edit(S, work_date='2026-09-15', reason='date corrigée : travail fait en septembre', confirm_billed='1')
        P(f"Édition S avec confirmation -> HTTP {st} ; date={self.scalar('SELECT work_date FROM entries WHERE id=?', (S,))}")
        for f in fl: P(f"   flash: {f[:330]}")
        P(f"   rôles S après déplacement : {self.roles(S)}")
        return S, T, f08

    def test_q1_q2_suggested_quantity(self):
        P("\n===== Q1/Q2 variante A : F09 à la quantité SUGGÉRÉE =====")
        S, T, f08 = self.base_f08_then_move()
        js = self.suggest_sept()
        f09, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', js['suggested_qty'])
        P(f"Brouillon F09 qty={self.inv(f09)['qty']} ; flash={fl}")
        self.show_checks(f09)
        for x in self.issue_page(f09): P(f"   page d'émission : {x}")
        self.issue_try(f09, 'F09')
        self.after_f09(S, f08, f09)

    def test_q1_q2_full_quantity(self):
        P("\n===== Q1/Q2 variante B : F09 = toutes les heures de septembre (1,5 j, S comprise) =====")
        S, T, f08 = self.base_f08_then_move()
        f09, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 1.5)
        P(f"Brouillon F09 qty={self.inv(f09)['qty']} ; flash={fl}")
        self.show_checks(f09)
        for x in self.issue_page(f09): P(f"   page d'émission : {x}")
        self.issue_try(f09, 'F09')
        self.after_f09(S, f08, f09)

    def after_f09(self, S, f08, f09):
        P(f"F09 = {self.inv(f09)['number']} qty={self.inv(f09)['qty']} j ; montant F08+F09 = {(self.inv(f08)['qty'] + self.inv(f09)['qty']) * 800} CHF HT pour 12 h = 1,5 j réalisés (1200 CHF)")
        P(f"   rôles S (entries_invoices / annotate billed_by, billed_changed, annex_of) : {self.roles(S)}")
        ent = H.unescape(self.c.get('/entries').get_data(as_text=True))
        mm = re.search(r'S travail août.{0,0}', ent)
        snippet = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', ent))
        i = snippet.find('S travail août'); P(f"   /entries (ligne S) : …{snippet[max(0, i - 200):i + 40]}…")
        self.show_var(f08); self.show_var(f09)
        st, fl = self.edit(S, manual_hours='6', reason='durée réelle 6 h', confirm_billed='1')
        P(f"Ensuite S 8 h -> 6 h (HTTP {st}) ; flash :")
        for f in fl: P(f"   flash: {f[:260]}")
        self.show_var(f08); self.show_var(f09)

    # -- Q3 : saisie listée dans l'annexe cumulative d'une facture ultérieure ---------------------
    def test_q3_cumulative_annex(self):
        P("\n===== Q3 : saisie tardive d'août reprise à la main dans F09 =====")
        self.entry(self.pid, '2026-08-20', 8, 'S travail août')
        self.entry(self.pid, '2026-09-10', 4, 'T travail septembre')
        f08 = self.issued(self.pid, '2026-08-01', '2026-08-31', 1)
        self.flashes(); self.entry(self.pid, '2026-08-25', 4, 'L tardive août'); L = self.eid('L tardive août')
        P(f"L (4 h, 25.08) saisie après F08 ; flash={[f[:160] for f in self.flashes()]}")
        js = self.suggest_sept()
        f09, fl = self.draft(self.pid, '2026-09-01', '2026-09-30', 1)   # l'utilisateur reprend L à la main : 4 h T + 4 h L = 1 j
        P(f"Brouillon F09 qty=1 j (T 4 h + L 4 h reprise à la main)")
        self.show_checks(f09)
        for x in self.issue_page(f09): P(f"   page d'émission : {x}")
        self.issue_try(f09, 'F09')
        P(f"   rôles L : {self.roles(L)}")
        self.show_var(f08); self.show_var(f09)
        st, fl = self.edit(L, manual_hours='2', reason='L : 2 h seulement')
        P(f"Ensuite L 4 h -> 2 h (HTTP {st}) ; flash :")
        for f in fl: P(f"   flash: {f[:260]}")
        self.show_var(f08); self.show_var(f09)
        c = m.db()
        try: pos = m.contract(c, c.execute('SELECT * FROM projects WHERE id=?', (self.pid,)).fetchone())
        finally: c.close()
        P(f"   position mandat : consumed={pos['consumed_days']} j billed={pos['billed_days']} j unbilled={pos['unbilled_days']} j")


if __name__ == '__main__':
    unittest.main(verbosity=1)
