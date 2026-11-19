"""Restes techniques de REVUE-CODE-RC19.md (« Constatés, NON corrigés », points techniques seulement ; les points métier
du modèle facture / annexe restent hors de ce lot). Données fictives, sur COPIE de la base (journaux/run_unit.sh).

T1  /entries?project=² (chiffre non ASCII) : 500 → filtre ignoré, comme toute valeur de filtre mal formée
T2  correction d'une saisie au 31.12.9999 : l'écriture était validée puis « Saisie non modifiée » s'affichait (erreur après validation)
T3  libellé du motif : « (facultatif) » alors que le rattachement à un mandat clôturé l'exige côté serveur
"""
from tests.test_rc19 import RC19, text


class RevueRC19Restes(RC19):
    RECORD_WORK = True   # rc25: the fixtures of this class record the work they bill (Cycle.draft): check 14 is not derogable, so a fixture may not bill days that were never worked
    def test_t1_filtre_mandat_chiffre_non_ascii(self):
        self.clock(self.pid, '2026-03-02', '08:00', '09:00', 'T1 a')
        for v in ('²', '٣', '1²', '¹²'):
            r = self.c.get('/entries', query_string={'project': v})
            self.assertEqual(r.status_code, 200, v)
            self.assertIn('T1 a', text(r), v)                       # filtre ignoré : la saisie reste listée
            self.assertEqual(self.c.get('/entries.csv', query_string={'project': v}).status_code, 200, v)
        r = self.c.get('/entries', query_string={'project': str(self.pid2)})
        self.assertNotIn('T1 a', text(r))                           # un identifiant ASCII filtre toujours

    def test_t2_date_extreme_message_juste(self):
        self.clock(self.pid, '2026-03-02', '08:00', '09:00', 'T2 a')
        eid = self.eid('T2 a')
        r, msg = self.edit(eid, work_date='9999-12-31')
        self.assertEqual(self.row(eid)['work_date'], '9999-12-31')
        self.assertNotIn('non modifiée', msg)
        self.assertIn('modifiée', msg)
        self.assertEqual(len(self.changes(eid)), 1)
        # retour à une date normale : possible, tracé
        r, msg = self.edit(eid, work_date='2026-03-03')
        self.assertEqual(self.row(eid)['work_date'], '2026-03-03')
        self.assertNotIn('non modifiée', msg)
        # date minimale : même comportement
        r, msg = self.edit(eid, work_date='0001-01-01')
        self.assertEqual(self.row(eid)['work_date'], '0001-01-01')
        self.assertNotIn('non modifiée', msg)

    def test_t2_nouvelle_saisie_date_extreme(self):
        for d in ('9999-12-31', '0001-01-01'):
            self.flashes(); r = self.clock(self.pid, d, '23:00', '01:00', f'T2 {d}')
            msg = ' '.join(self.flashes())
            n = self.scalar('SELECT COUNT(*) FROM entries WHERE description=?', (f'T2 {d}',))
            # message cohérent avec la base : enregistrée => « Temps enregistré », sinon « Saisie refusée »
            self.assertIn('Temps enregistré' if n else 'Saisie refusée', msg, d)
            self.assertNotIn('out of range', msg, d)

    def test_t3_libelle_motif_mandat_cloture(self):
        self.clock(self.pid, '2026-03-02', '08:00', '09:00', 'T3 a')
        page = text(self.c.get(f'/entry/{self.eid("T3 a")}/edit'))
        self.assertNotIn('Motif de la correction (facultatif)', page)
        self.assertIn('mandat clôturé', page.split('Motif de la correction', 1)[1][:200])

    def test_t2_dates_extremes_aucune_page_en_erreur(self):
        """Une saisie au 31.12.9999 / 01.01.0001 (mode durée : toujours acceptée) ne doit faire échouer aucune page ni l'export."""
        iid = self.issued(self.pid, '2026-03-01', '2026-03-31', '1')
        for d in ('9999-12-31', '0001-01-01'):
            self.entry(self.pid, d, 2, f'X {d}')
            self.entry(self.pid2, d, 1, f'Y {d}')
        self.clock(self.pid, '9999-12-31', '22:00', '02:00', 'X nuit')
        self.assertTrue(self.eid('X 9999-12-31') and self.eid('X 0001-01-01') and self.eid('X nuit'))
        pages = ['/', '/entries', '/entries.csv', '/historique', '/export/classeur.xlsx', '/archive.zip', '/backup', f'/invoice/{iid}.pdf', f'/invoice/{iid}/ecart',
                 f'/project/{self.pid}/edit', f'/entry/{self.eid("X 9999-12-31")}/edit', f'/entry/{self.eid("X nuit")}/historique']
        pages += [f'/?tab={t}' for t in ('dashboard', 'time', 'mandates', 'billing', 'archive', 'migration', 'settings')]
        pages += ['/entries?date_from=9999-12-31', '/entries?date_to=0001-01-01']
        for u in pages:
            self.assertEqual(self.c.get(u).status_code, 200, u)
        st, s = self.suggest(self.pid, '9999-12-01', '9999-12-31')
        self.assertEqual(st, 200, s)
        _, fl = self.draft(self.pid, '9999-12-01', '9999-12-31', '0.25')
        self.assertNotIn('out of range', ' '.join(fl))

    def test_t4_mandat_cloture_avertissements(self):
        """Suppression ou changement d'heures d'une saisie d'un mandat clôturé : même avertissement que le déplacement (position de clôture modifiée)."""
        self.clock(self.pid2, '2026-03-02', '08:00', '09:00', 'T4 a')
        self.clock(self.pid2, '2026-03-03', '08:00', '09:00', 'T4 b')
        self.c.post(f'/project/{self.pid2}/close', data={'reason': 'mandat terminé'})
        self.assertEqual(self.scalar('SELECT active FROM projects WHERE id=?', (self.pid2,)), 0)
        a, b = self.eid('T4 a'), self.eid('T4 b')
        r, msg = self.edit(a, description='T4 a corrigée')                   # description seule : position inchangée, pas d'avertissement
        self.assertIn('modifiée', msg); self.assertNotIn('position enregistrée', msg)
        r, msg = self.edit(a, end_time='10:00')
        self.assertEqual(self.row(a)['hours'], 2)
        self.assertIn('position enregistrée à la clôture est modifiée', msg)
        r, msg = self.delete(b, reason='doublon')
        self.assertFalse(self.sql('SELECT 1 FROM entries WHERE id=?', (b,)))
        self.assertIn('supprimée', msg); self.assertIn('position enregistrée à la clôture est modifiée', msg)
        # mandat actif : aucun avertissement de clôture
        self.clock(self.pid, '2026-03-04', '08:00', '09:00', 'T4 c')
        r, msg = self.delete(self.eid('T4 c'))
        self.assertIn('supprimée', msg); self.assertNotIn('clôturé', msg)

    def test_t5_erreur_apres_validation_message_juste(self):
        """Une erreur pendant le calcul des avertissements, APRÈS l'écriture, ne doit dire ni « non modifiée » ni « refusée »."""
        import app.app as m
        self.clock(self.pid, '2026-03-02', '08:00', '09:00', 'T5 a')
        self.clock(self.pid, '2026-03-03', '08:00', '09:00', 'T5 b')
        a, b = self.eid('T5 a'), self.eid('T5 b')
        orig = m.draft_warning
        def boom(*a_, **k): raise RuntimeError('panne simulée')
        m.draft_warning = boom
        try:
            r, msg = self.edit(a, end_time='11:00')
            self.assertEqual(self.row(a)['hours'], 3); self.assertEqual(r.status_code, 302)
            self.assertNotIn('non modifiée', msg); self.assertIn('Avertissements non calculés', msg)
            r, msg = self.delete(b)
            self.assertFalse(self.sql('SELECT 1 FROM entries WHERE id=?', (b,)))
            self.assertNotIn('refusée', msg); self.assertIn('Avertissements non calculés', msg)
        finally:
            m.draft_warning = orig
