"""Verrou partiel (REVUE-CODE-RC19, « Constatés, NON corrigés ») : l'import accepte, avec un simple avertissement, des valeurs que le
formulaire de correction refuse (durée > 24 h ou < 0,01 h, horaires avec secondes, début = fin, horaire seul, description longue ou sur
plusieurs lignes). Avant : une telle saisie ne pouvait plus être corrigée, même pour son seul motif (ou perdait sans le dire son horaire seul
et ses retours à la ligne), contre la règle rc19 « toute saisie reste modifiable » et la condition G4. Après : une valeur que l'utilisateur
ne change pas est conservée telle quelle ; toute NOUVELLE valeur suit les règles habituelles. 0 saisie réelle concernée (copie
pre-rc23-20261008T061057Z : 2 247 contrôlées) ; risque ouvert par un réimport volontaire (écraser). Données fictives, sur COPIE de la base.
"""
import sqlite3

from app.post_billing import NEXT_ENTRY_ID
from tests.test_import import FAKE_ISSUER
from tests.test_rc19 import RC19, text


class VerrouImport(RC19):
    def imported(self, start, end, hours, desc, d='2026-03-02'):
        """Saisie telle que l'import peut l'écrire (avertissements seulement), sans passer par le formulaire."""
        c = sqlite3.connect(self.db)
        try:
            c.execute(f"INSERT INTO entries(id,work_date,project_id,start_time,end_time,hours,description,source,source_ref) "
                      f"VALUES({NEXT_ENTRY_ID},?,?,?,?,?,?,'import','MAR 26!12')", (d, self.pid, start, end, hours, desc))
            c.commit()
        finally: c.close()
        return self.eid(desc)

    def ok(self, eid, msg, **expected):
        self.assertIn(f'Saisie n° {eid} modifiée', msg)
        r = self.row(eid)
        for k, v in expected.items(): self.assertEqual(r[k], v, k)

    def test_v1_duree_superieure_a_24h(self):
        eid = self.imported('', '', 25.0, 'V1 a')
        r, msg = self.edit(eid, description='V1 b')                 # motif seul : la durée importée reste
        self.ok(eid, msg, description='V1 b', hours=25.0)
        self.assertIn('max="25.0"', text(self.c.get(f'/entry/{eid}/edit')))   # le navigateur laisse envoyer la valeur enregistrée
        self.assertIn('keptHours', text(self.c.get(f'/entry/{eid}/edit')))
        r, msg = self.edit(eid, manual_hours='26')                   # nouvelle valeur : règle habituelle
        self.assertIn('supérieure à 24 h', msg); self.assertEqual(self.row(eid)['hours'], 25.0)
        r, msg = self.edit(eid, manual_hours='8')
        self.ok(eid, msg, hours=8.0)

    def test_v2_duree_inferieure_a_001h(self):
        eid = self.imported('', '', 0.005, 'V2 a')
        r, msg = self.edit(eid, description='V2 b')
        self.ok(eid, msg, description='V2 b', hours=0.005)
        r, msg = self.edit(eid, manual_hours='0.004')
        self.assertIn('inférieure à 0,01 h', msg); self.assertEqual(self.row(eid)['hours'], 0.005)

    def test_v3_horaires_avec_secondes(self):
        eid = self.imported('07:05:30', '09:10:15', 2.08, 'V3 a')
        page = text(self.c.get(f'/entry/{eid}/edit'))
        self.assertIn('value="07:05:30" step="1"', page)            # pas de 60 s par défaut : formulaire non envoyable sinon
        r, msg = self.edit(eid, description='V3 b')
        self.ok(eid, msg, description='V3 b', start_time='07:05:30', end_time='09:10:15', hours=2.08)
        r, msg = self.edit(eid, end_time='10:00')                    # un horaire changé : les deux sont relus (HH:MM ; secondes refusées)
        self.assertIn('avec secondes', msg); self.assertEqual(self.row(eid)['end_time'], '09:10:15')
        r, msg = self.edit(eid, start_time='07:05', end_time='10:00')
        self.ok(eid, msg, start_time='07:05', end_time='10:00', hours=(175 / 60))

    def test_v4_debut_egal_fin(self):
        eid = self.imported('08:00', '08:00', 3.0, 'V4 a')
        r, msg = self.edit(eid, description='V4 b')
        self.ok(eid, msg, description='V4 b', start_time='08:00', end_time='08:00', hours=3.0)
        self.assertNotIn('Avertissements non calculés', msg)
        r, msg = self.edit(eid, start_time='09:00', end_time='09:00')  # nouvelle saisie identique début = fin : refusée
        self.assertIn('identique', msg); self.assertEqual(self.row(eid)['start_time'], '08:00')
        self.assertNotIn('Avertissements non calculés', msg)
        # une saisie voisine (même jour) : ses avertissements ne butent plus sur la plage vide de V4
        self.flashes(); self.clock(self.pid, '2026-03-02', '07:00', '09:00', 'V4 voisine')
        self.assertTrue(self.eid('V4 voisine'))
        r, msg = self.edit(self.eid('V4 voisine'), description='V4 voisine b')
        self.ok(self.eid('V4 voisine b'), msg); self.assertNotIn('Avertissements non calculés', msg)

    def test_v5_horaire_seul(self):
        eid = self.imported('08:00', '', 2.0, 'V5 a')
        page = text(self.c.get(f'/entry/{eid}/edit'))
        self.assertIn('loneTime', page); self.assertIn('début 08:00, sans fin', page)
        r, msg = self.edit(eid, description='V5 b')                  # le formulaire (mode durée) n'envoie pas l'horaire seul
        self.ok(eid, msg, description='V5 b', start_time='08:00', end_time='', hours=2.0)
        r, msg = self.edit(eid, manual_hours='3')                    # durée changée : saisie en durée, comme annoncé sur la page
        self.ok(eid, msg, start_time='', end_time='', hours=3.0)
        eid2 = self.imported('', '17:00', 1.5, 'V5 c')
        r, msg = self.edit(eid2, description='V5 d')
        self.ok(eid2, msg, start_time='', end_time='17:00', hours=1.5)

    def test_v6_description_longue(self):
        long = 'L' * 1200
        eid = self.imported('', '', 2.0, long)
        r, msg = self.edit(eid, manual_hours='3')                    # description inchangée : conservée
        self.ok(eid, msg, hours=3.0, description=long)
        r, msg = self.edit(eid, description='M' * 1200)              # nouvelle description longue : refusée
        self.assertIn('description trop longue', msg); self.assertEqual(self.row(eid)['description'], long)

    def test_v7_description_sur_plusieurs_lignes(self):
        desc = 'V7 ligne 1\nligne 2\r\nligne 3'
        eid = self.imported('', '', 2.0, desc)
        self.assertIn('multilineDesc', text(self.c.get(f'/entry/{eid}/edit')))
        # le champ d'une ligne envoie la valeur sans retours à la ligne : la description enregistrée ne change pas
        r, msg = self.edit(eid, manual_hours='3', description='V7 ligne 1ligne 2ligne 3')
        self.ok(eid, msg, hours=3.0, description=desc)
        r, msg = self.edit(eid, manual_hours='3', description='V7 ligne 1 ligne 2 ligne 3')   # vraie modification : enregistrée
        self.ok(eid, msg, description='V7 ligne 1 ligne 2 ligne 3')

    def test_v8_rien_change_aucune_correction(self):
        eid = self.imported('07:05:30', '09:10:15', 25.5, 'V8 a')
        r, msg = self.edit(eid)
        self.assertIn('Aucune modification', msg); self.assertEqual(self.changes(eid), [])

    def test_v9_nouvelle_saisie_regles_inchangees(self):
        for kw, err in ((dict(entry_mode='duration', manual_hours='25'), 'supérieure à 24 h'),
                        (dict(entry_mode='duration', manual_hours='0.005'), 'inférieure à 0,01 h'),
                        (dict(entry_mode='clock', start_time='07:05:30', end_time='09:00'), 'heure invalide'),
                        (dict(entry_mode='clock', start_time='08:00', end_time='08:00'), 'identique')):
            eid = self.imported('', '', 2.0, f'V9 {err}')
            r, msg = self.edit(eid, **kw)
            self.assertIn(err, msg, kw); self.assertEqual(self.row(eid)['hours'], 2.0, kw)
        self.entry(self.pid, '2026-03-03', 25, 'V9 création 25 h')                # création : jamais de valeur conservée
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM entries WHERE description='V9 création 25 h'"), 0)

    def test_v10_retours_a_la_ligne_crlf_du_navigateur(self):
        """Un navigateur envoie les retours à la ligne d'un champ multiligne en \\r\\n : enregistrer un mandat ou l'adresse de l'émetteur sans
        rien changer réécrivait la valeur (\\n -> \\r\\n), vue comme une ligne modifiée par 90-rollback et la promotion G4."""
        p0 = self.sql('SELECT * FROM projects WHERE id=?', (self.pid,))[0]
        data = {k: ('' if p0[k] is None else str(p0[k])) for k in p0.keys() if k not in ('id', 'active', 'closed_reason', 'created_at')}
        data['billing_address'] = p0['billing_address'].replace('\n', '\r\n')
        self.c.post(f'/project/{self.pid}/edit', data=data)
        self.assertEqual(self.sql('SELECT billing_address FROM projects WHERE id=?', (self.pid,))[0][0], 'Client Fictif SA\nRue Imaginaire 1\n9999 Nulle-Part')
        self.c.post('/settings', data=dict(FAKE_ISSUER, issuer_address='Rue de Test 2\r\n1200 Genève\r1201 Genève'))
        self.assertEqual(self.scalar("SELECT value FROM settings WHERE key='issuer_address'"), 'Rue de Test 2\n1200 Genève\n1201 Genève')

    def test_v12_parametres_enregistres_sans_changement(self):
        """Aller-retour des paramètres (copie réelle du staging) : enregistrer sans rien changer réécrivait l'horodatage des 9 champs de
        l'émetteur et ajoutait les options absentes (TVA « AUTRES » = hors_tva, délai vide) — « paramètres modifiés » pour 90-rollback."""
        self.c.post('/settings', data=dict(FAKE_ISSUER, issuer_address='Rue A\r\nVille'))
        c = sqlite3.connect(self.db)
        try:
            c.execute("DELETE FROM settings WHERE key IN ('other_vat_default','refund_delay_days')")
            c.execute("UPDATE settings SET updated_at='2000-01-01 00:00:00'"); c.commit()
        finally: c.close()
        rows = lambda: [tuple(r) for r in self.sql('SELECT key,value,updated_at FROM settings ORDER BY key')]
        before = rows()
        page = text(self.c.get('/?tab=settings'))
        self.assertIn('<option value="hors_tva" selected', page)                           # valeur par défaut affichée = celle renvoyée
        self.c.post('/settings', data=dict(FAKE_ISSUER, issuer_address='Rue A\r\nVille', other_vat_default='hors_tva', refund_delay_days=''))
        self.assertEqual(rows(), before)
        self.c.post('/settings', data=dict(FAKE_ISSUER, issuer_address='Rue B\r\nVille', other_vat_default='hors_tva', refund_delay_days='30'))
        after = {r[0]: (r[1], r[2]) for r in rows()}
        self.assertEqual(after['issuer_address'][0], 'Rue B\nVille'); self.assertNotEqual(after['issuer_address'][1], '2000-01-01 00:00:00')
        self.assertEqual(after['refund_delay_days'][0], '30'); self.assertNotIn('other_vat_default', after)
        self.assertEqual(after['issuer_name'], ({r[0]: r[1] for r in before}['issuer_name'], '2000-01-01 00:00:00'))

    def test_v11_relecture_adverse(self):
        """Constats de la relecture adverse : (1) champ heure à pas d'une seconde → le navigateur envoie « 10:00:00 » ; (2) début = fin à la
        minute près (08:00:30 → 08:00) : avertissements en erreur ; (3) durée minuscule préremplie « 5e-05 », refusée par la règle F-C2-1 ;
        (5) aide « durée enregistrée » absente pour des horaires avec secondes."""
        eid = self.imported('07:05:30', '09:10:15', 2.08, 'V11 a')
        self.assertIn('declaredHours', text(self.c.get(f'/entry/{eid}/edit')))                           # (5)
        r, msg = self.edit(eid, end_time='10:00:00')                                                       # début importé inchangé, avec secondes
        self.assertIn('avec secondes', msg); self.assertEqual(self.row(eid)['end_time'], '09:10:15')
        r, msg = self.edit(eid, start_time='07:05:00', end_time='10:00:00')                               # (1) minutes entières : lues
        self.ok(eid, msg, start_time='07:05', end_time='10:00', hours=(175 / 60))
        r, msg = self.edit(eid, start_time='07:05:01', end_time='10:00')
        self.assertIn('avec secondes', msg); self.assertEqual(self.row(eid)['start_time'], '07:05')
        eid2 = self.imported('08:00:30', '08:00', 0.5, 'V11 b')                                            # (2)
        r, msg = self.edit(eid2, description='V11 c')
        self.ok(eid2, msg, description='V11 c'); self.assertNotIn('Avertissements non calculés', msg)
        eid3 = self.imported('', '', 5e-05, 'V11 d')                                                       # (3)
        self.assertIn('value="0.00005"', text(self.c.get(f'/entry/{eid3}/edit')))
        r, msg = self.edit(eid3, manual_hours='0.00005', description='V11 e')
        self.ok(eid3, msg, description='V11 e', hours=5e-05)
