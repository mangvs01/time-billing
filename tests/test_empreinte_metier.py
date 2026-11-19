"""G4 (Decision Center billing-g4-donnees-production, en attente) : outils/empreinte_metier.py, contrôles communs aux deux méthodes — production
vide avant la bascule, données métier production = staging après. Bases synthétiques jetables ; l'outil n'ouvre les bases qu'en lecture."""
import hashlib, os, shutil, sqlite3, tempfile, unittest

from outils import empreinte_metier as tool

SCHEMA = """
CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT, closed_at TEXT);
CREATE TABLE entries(id INTEGER PRIMARY KEY, work_date TEXT, project_id INTEGER, hours REAL, description TEXT);
CREATE TABLE historical_invoices(id INTEGER PRIMARY KEY, project_id INTEGER, amount_ht REAL, status TEXT);
CREATE TABLE invoice_snapshots(invoice_id INTEGER, pdf BLOB);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE audit(id INTEGER PRIMARY KEY, action TEXT);
CREATE TABLE web_sessions(id TEXT PRIMARY KEY, data TEXT);
"""


class EmpreinteMetier(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.a = self.base('a.db', donnees=True)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def base(self, nom, donnees):
        p = os.path.join(self.d, nom)
        c = sqlite3.connect(p); c.executescript(SCHEMA)
        if donnees:
            c.execute("INSERT INTO projects VALUES(1,'EAU 2026',NULL),(2,'ASN 2025','2025-12-31')")
            c.executemany("INSERT INTO entries VALUES(?,?,?,?,?)", [(1, '2026-03-02', 1, 1.5, 'debrief'), (2, '2026-03-03', 2, 0.25, '')])
            c.execute("INSERT INTO historical_invoices VALUES(1,1,4550.0,'pending')")
            c.execute("INSERT INTO invoice_snapshots VALUES(1, ?)", (b'%PDF-1.4 fictif',))
            c.execute("INSERT INTO settings VALUES('issuer_iban','CH00 FICTIF')")
            c.execute("INSERT INTO audit VALUES(1,'login')"); c.execute("INSERT INTO web_sessions VALUES('s1','{}')")
        c.commit(); c.close()
        return p

    def copie(self, nom, sql=None):
        p = os.path.join(self.d, nom); shutil.copy(self.a, p)
        if sql:
            c = sqlite3.connect(p); c.executescript(sql); c.commit(); c.close()
        return p

    def sha(self, p):
        return hashlib.sha256(open(p, 'rb').read()).hexdigest()

    def test_une_base_sans_donnee_metier_est_vide_meme_avec_audit_et_sessions(self):
        v = self.base('v.db', donnees=False)
        c = sqlite3.connect(v); c.execute("INSERT INTO audit VALUES(1,'login')"); c.execute("INSERT INTO web_sessions VALUES('s','{}')"); c.commit(); c.close()
        self.assertEqual(tool.vide(v), [])
        self.assertEqual(tool.main(['x', 'vide', v]), 0)

    def test_la_moindre_ligne_metier_y_compris_un_parametre_rend_la_base_non_vide(self):
        v = self.base('v.db', donnees=False)
        c = sqlite3.connect(v); c.execute("INSERT INTO settings VALUES('issuer_name','X')"); c.commit(); c.close()
        self.assertEqual(tool.vide(v), [('settings', 1)])
        self.assertEqual(tool.main(['x', 'vide', v]), 1)
        self.assertEqual(dict(tool.vide(self.a)), {'projects': 2, 'entries': 2, 'historical_invoices': 1, 'invoice_snapshots': 1, 'settings': 1})

    def test_base_v90_sans_les_tables_ajoutees_par_les_migrations(self):
        p = os.path.join(self.d, 'v90.db'); c = sqlite3.connect(p)
        c.executescript("CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE entries(id INTEGER PRIMARY KEY, hours REAL);"
                        "CREATE TABLE audit(id INTEGER PRIMARY KEY)"); c.close()
        self.assertEqual(tool.vide(p), [])
        self.assertEqual(set(tool.empreinte(p)['tables_metier']), {'projects', 'entries'})

    def test_copie_identique_hors_sessions_et_audit(self):
        b = self.copie('b.db', "DELETE FROM web_sessions; INSERT INTO audit VALUES(2,'base promue depuis le staging');")
        self.assertEqual(tool.comparer(self.a, b), [])
        self.assertEqual(tool.main(['x', 'comparer', self.a, b]), 0)
        ea, eb = tool.empreinte(self.a), tool.empreinte(b)
        self.assertEqual(ea['tables_metier'], eb['tables_metier'])
        self.assertEqual((ea['hors_comparaison']['web_sessions'], eb['hors_comparaison']['web_sessions']), (1, 0))
        self.assertEqual(ea['chiffres']['saisies'], 2); self.assertEqual(ea['chiffres']['heures'], 1.75)
        self.assertEqual(ea['chiffres']['mandats_clotures'], 1)
        self.assertEqual(ea['chiffres']['historiques_par_statut'], {'pending': {'nombre': 1, 'montant_ht': 4550.0}})

    def test_ecarts_detectes_valeur_ligne_validation_parametre_et_pdf(self):
        cas = {"UPDATE entries SET description='debrief Anna' WHERE id=1": 'entries : 2 ligne(s) dans A, 2 dans B ; 1 ligne(s) seulement dans A, 1 seulement dans B',
               "UPDATE entries SET hours=1.5000001 WHERE id=1": 'entries :',
               "DELETE FROM entries WHERE id=2": 'entries : 2 ligne(s) dans A, 1 dans B ; 1 ligne(s) seulement dans A, 0 seulement dans B',
               "UPDATE historical_invoices SET status='validated'": 'historical_invoices :',
               "UPDATE settings SET value='CH99'": 'settings :',
               "UPDATE invoice_snapshots SET pdf=X'00'": 'invoice_snapshots :',
               "INSERT INTO invoice_snapshots VALUES(1, X'255044462D312E342066696374696966')": 'invoice_snapshots :'}
        for i, (sql, attendu) in enumerate(cas.items()):
            with self.subTest(sql=sql):
                b = self.copie(f'b{i}.db', sql)
                ec = tool.comparer(self.a, b)
                self.assertEqual(len(ec), 1, ec); self.assertTrue(ec[0].startswith(attendu), ec)
                self.assertEqual(tool.main(['x', 'comparer', self.a, b]), 1)
                self.assertNotEqual(tool.empreinte(self.a)['tables_metier'], tool.empreinte(b)['tables_metier'])

    def test_doublon_exact_detecte_malgre_except(self):
        c = sqlite3.connect(self.a); c.execute("CREATE TABLE credit_note_cancellations(credit_id INTEGER, reason TEXT)")
        c.execute("INSERT INTO credit_note_cancellations VALUES(1,'erreur')"); c.commit(); c.close()
        b = self.copie('b.db', "INSERT INTO credit_note_cancellations VALUES(1,'erreur')")
        self.assertEqual(tool.comparer(self.a, b), ['credit_note_cancellations : 1 ligne(s) dans A, 2 dans B ; 0 ligne(s) seulement dans A, 0 seulement dans B'])

    def test_schema_different_signale_sans_comparer_les_lignes(self):
        b = self.copie('b.db', "ALTER TABLE entries ADD COLUMN source_ref TEXT; DROP TABLE historical_invoices;")
        ec = tool.comparer(self.a, b)
        self.assertIn("entries : colonnes différentes (seulement A : - ; seulement B : ['source_ref'])", ec)
        self.assertIn('historical_invoices : table présente seulement dans A', ec)

    def test_empreinte_independante_de_l_ordre_physique_des_lignes(self):
        b = self.copie('b.db', "CREATE TABLE t AS SELECT * FROM entries ORDER BY id DESC; DELETE FROM entries; "
                               "INSERT INTO entries SELECT * FROM t; DROP TABLE t; VACUUM;")
        self.assertEqual(tool.empreinte(self.a)['tables_metier'], tool.empreinte(b)['tables_metier'])

    def test_lecture_seule_les_bases_ne_changent_pas(self):
        b = self.copie('b.db', "UPDATE entries SET hours=2 WHERE id=1")
        avant = (self.sha(self.a), self.sha(b))
        tool.vide(self.a); tool.empreinte(self.a); tool.comparer(self.a, b); tool.main(['x', 'comparer', b, self.a])
        self.assertEqual((self.sha(self.a), self.sha(b)), avant)
        self.assertFalse(os.path.exists(self.a + '-journal') or os.path.exists(self.a + '-wal'))

    def test_fichier_absent_erreur_sans_creer_de_base(self):
        p = os.path.join(self.d, 'absente.db')
        with self.assertRaises(sqlite3.OperationalError): tool.vide(p)
        self.assertFalse(os.path.exists(p))
        self.assertEqual(tool.main(['x']), 2)


if __name__ == '__main__':
    unittest.main()
