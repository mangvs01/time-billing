"""BILL-RC48-FIX : correctifs retenus de la revue indépendante de 9.2-rc48 (docs/revues-rc48/synthese.md). Données synthétiques uniquement.

A  une adresse qui a un « jumeau » à la casse près (créé avant l'index, ou variante Unicode « Zürich » / « ZÜRICH ») reste modifiable tant que son libellé ne change pas ;
   le refus d'un vrai conflit est en français clair.
F  le contrôle de schéma (schema_checks.rc19_problems) vérifie aussi les 5 déclencheurs de rc48 et le texte du plafond d'avoir (formule d'arrondi), pas seulement l'index d'adresse.
G  plus de texte anglais brut à l'écran quand la BASE refuse une écriture : restauration d'une sauvegarde et création d'une note de crédit.
N-1..N-3 (2e revue, BILL-RC48-FIX2) : l'outil de retour n'ouvre ni ne migre JAMAIS la base visée par DB_PATH, refuse les chemins de production sans confirmation explicite, signale les avoirs au-dessus du plafond de rc47 ;
   un libellé d'adresse à espaces multiples reste modifiable (contact seul).
C/D l'outil outils/retour_rc47.py (base et JSON) : voir aussi outils/repeter_migration_rc48.py, qui le fait tourner contre le VRAI code rc47."""
import json, os, re, sqlite3, subprocess, sys, tempfile, unittest
from unittest import mock

import app.app as m
from app import address_service, credit_lines, db_messages, line_guards, restore_service, schema_checks
from tests import test_credit_lines as tcl
from tests.test_bill_fa1ft import Base
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'outils'))
import retour_rc47                                                                                       # noqa: E402  (import sans effet : ne charge pas app.app)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAP_EN = 'The credits of an invoice line cannot exceed its amount'


# ===================================================================================================================================================
class A_twin_addresses(Base):
    IDX = address_service.LABEL_INDEX

    def setUp(self):
        super().setUp(); self.mandate(name='Mandat jumeau', legal_id='CHE-000.000.078')

    def twins(self, a, b):
        """Two addresses of one client whose labels differ only by case, as rc47 allowed (the unique index of rc48 is dropped to build the state)."""
        self.sqlw(f"DROP INDEX IF EXISTS {self.IDX}")
        self.sqlw(f"INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','{a}','Rue 1','2026-10-27T10:00:00')",
                  f"INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','{b}','Rue 2','2026-10-27T10:00:00')")
        return [r['id'] for r in self.sql("SELECT id FROM billing_addresses WHERE label IN (?,?) ORDER BY id", (a, b))]

    def post(self, aid, label, contact='', address='Rue modifiée'):
        self.flashes(); self.c.post(f'/adresses/{aid}', data={'label': label, 'contact': contact, 'address': address}); return ' '.join(self.flashes())

    def test_an_address_with_an_ascii_twin_stays_editable_when_its_label_does_not_change(self):
        a, b = self.twins('Basel', 'BASEL')
        fl = self.post(a, 'Basel', contact='Mme Fictive'); self.assertIn('enregistrée', fl); self.assertNotIn('non modifiée', fl)
        self.assertEqual(self.sql('SELECT label,contact,address FROM billing_addresses WHERE id=?', (a,))[0][:], ('Basel', 'Mme Fictive', 'Rue modifiée'))
        fl = self.post(b, 'BASEL', contact='M. Fictif'); self.assertIn('enregistrée', fl)                       # the twin as well
        self.assertEqual(self.scalar('SELECT contact FROM billing_addresses WHERE id=?', (b,)), 'M. Fictif')

    def test_an_address_with_a_unicode_twin_stays_editable_the_index_does_not_see_it(self):
        a, b = self.twins('Zürich', 'ZÜRICH'); self.sqlw(f"CREATE UNIQUE INDEX {self.IDX} ON billing_addresses(client_key, label COLLATE NOCASE)")      # NOCASE does not fold ü/Ü: the index can exist
        fl = self.post(a, 'Zürich', contact='Mme Fictive'); self.assertIn('enregistrée', fl, fl)
        self.assertEqual(self.scalar('SELECT contact FROM billing_addresses WHERE id=?', (a,)), 'Mme Fictive')

    def test_a_stored_label_with_repeated_spaces_stays_editable_for_its_contact_N2(self):
        self.sqlw(f"DROP INDEX IF EXISTS {self.IDX}")
        self.sqlw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','Egg  BE','Rue 1','2026-10-27T10:00:00')", "INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','egg be','Rue 2','2026-10-27T10:00:00')")
        self.sqlw(f"CREATE UNIQUE INDEX {self.IDX} ON billing_addresses(client_key, label COLLATE NOCASE)")                      # « Egg  BE » / « egg be » differ by spacing: the index accepts both
        a = self.scalar("SELECT id FROM billing_addresses WHERE label='Egg  BE'")
        fl = self.post(a, 'Egg  BE', contact='Mme Fictive'); self.assertIn('enregistrée', fl, fl); self.assertNotIn('non modifiée', fl)
        self.assertEqual(self.sql('SELECT label,contact FROM billing_addresses WHERE id=?', (a,))[0][:], ('Egg  BE', 'Mme Fictive'))             # stored label left as it was
        self.sqlw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','Zed','Rue 3','2026-10-27T10:00:00')")
        z = self.scalar("SELECT id FROM billing_addresses WHERE label='Zed'"); fl = self.post(z, 'EGG BE'); self.assertIn('existe déjà', fl)             # a real rename onto a twin of « egg be » is still refused

    def test_the_same_edit_stays_possible_without_any_twin_and_the_structured_fields_too(self):
        self.sqlw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','Genève','Rue 1','2026-10-27T10:00:00')")
        aid = self.scalar("SELECT id FROM billing_addresses WHERE label='Genève'")
        self.flashes(); self.c.post(f'/adresses/{aid}', data={'label': 'Genève', 'contact': 'X', 'address': 'Rue 9', 'addr_street': 'Rue', 'addr_house_num': '9', 'addr_pcode': '1200', 'addr_city': 'Genève', 'addr_country': 'CH'})
        self.assertIn('enregistrée', ' '.join(self.flashes())); self.assertEqual(self.scalar('SELECT addr_pcode FROM billing_addresses WHERE id=?', (aid,)), '1200')

    def test_renaming_onto_a_twin_is_still_refused_with_a_clear_french_message(self):
        a, b = self.twins('Basel', 'BASEL'); self.sqlw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','Berne','Rue 3','2026-10-27T10:00:00')")
        berne = self.scalar("SELECT id FROM billing_addresses WHERE label='Berne'")
        fl = self.post(berne, 'basel'); self.assertIn('non modifiée', fl)
        self.assertIn('« Basel »', fl); self.assertIn('majuscules et les minuscules', fl); self.assertIn('Choisir un autre nom', fl)
        self.assertNotIn('à la casse près', fl)                                                                  # jargon removed
        self.assertEqual(self.scalar('SELECT label FROM billing_addresses WHERE id=?', (berne,)), 'Berne')
        fl = self.post(a, 'BASEL'); self.assertIn('non modifiée', fl)                                           # a twin cannot take its twin's label either (it would be a change of label)
        self.assertEqual(self.scalar('SELECT label FROM billing_addresses WHERE id=?', (a,)), 'Basel')

    def test_the_messages_of_an_addition(self):
        self.sqlw("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES('*','Lugano','Rue 1','2026-10-27T10:00:00')")
        for lab, needle in (('lugano', 'majuscules et les minuscules'), ('Lugano', 'choisir un autre nom')):
            self.flashes(); self.c.post('/adresses/ajouter', data={'client_key': '*', 'label': lab, 'contact': '', 'address': 'Rue 2'}); fl = ' '.join(self.flashes())
            self.assertIn('non ajoutée', fl); self.assertIn('« Lugano »', fl); self.assertIn(needle, fl, fl); self.assertNotIn('à la casse près', fl)
        self.assertEqual(self.count_label('lugano'), 1)

    def count_label(self, lab): return self.scalar('SELECT COUNT(*) FROM billing_addresses WHERE label=? COLLATE NOCASE', (lab,))

    def test_rename_conflict_unit(self):
        a, b = self.twins('Basel', 'BASEL'); c = sqlite3.connect(self.db); c.row_factory = sqlite3.Row
        try:
            row = dict(c.execute('SELECT * FROM billing_addresses WHERE id=?', (a,)).fetchone())
            self.assertIsNone(address_service.rename_conflict(c, row, 'Basel'))                                  # unchanged label: never checked
            self.assertIn('BASEL', address_service.rename_conflict(c, row, 'basel'))                            # changed label that meets the twin
            self.assertIsNone(address_service.rename_conflict(c, row, 'Autre'))
            self.assertEqual(address_service.label_twin(c, '*', 'basel', a), 'BASEL')
            self.assertTrue(address_service.label_taken(c, '*', 'Basel', b)); self.assertFalse(address_service.label_taken(c, '*', 'Inconnue'))
        finally: c.close()


# ===================================================================================================================================================
class F_schema_check(Base):
    TRIGGERS = ("credit_line_upd_no_move_frozen", "credit_line_upd_same_invoice", "credit_line_upd_same_vat_mode", "credit_line_upd_within_line", "invoice_line_no_move_to_issued")

    def problems(self):
        c = sqlite3.connect(self.db)
        try: return schema_checks.rc19_problems(c)
        finally: c.close()

    def test_a_fresh_database_has_no_problem(self):
        self.assertEqual(self.problems(), [])

    def test_each_of_the_five_triggers_is_checked(self):
        for name in self.TRIGGERS:
            self.sqlw(f"DROP TRIGGER {name}"); p = self.problems()
            self.assertTrue(any(name in x and 'absent' in x for x in p), (name, p)); m.init(); self.assertEqual(self.problems(), [], name)         # the next start re-creates it

    def test_the_former_rounding_formula_of_the_line_cap_is_reported(self):
        self.sqlw("DROP TRIGGER credit_lines_within_line", credit_lines.LEGACY_WITHIN_LINE_TRIGGER)
        p = self.problems(); self.assertTrue(any('credit_lines_within_line' in x and "ancienne formule d'arrondi" in x for x in p), p)
        m.init(); self.assertEqual(self.problems(), [])

    def test_a_trigger_whose_text_differs_is_reported_even_if_name_and_table_match(self):
        self.sqlw("DROP TRIGGER credit_line_upd_within_line",
                  "CREATE TRIGGER credit_line_upd_within_line BEFORE UPDATE OF invoice_line_id, amount ON credit_note_lines WHEN NEW.amount>1e12 BEGIN SELECT RAISE(ABORT,'x'); END")
        p = self.problems(); self.assertTrue(any('credit_line_upd_within_line' in x and 'différent' in x for x in p), p)
        self.sqlw("DROP TRIGGER invoice_line_no_move_to_issued"); self.assertTrue(any('invoice_line_no_move_to_issued' in x for x in self.problems()))

    def test_a_partial_return_to_rc47_is_reported(self):
        c = sqlite3.connect(self.db); credit_lines.rollback_update_guards(c); line_guards.rollback(c); c.commit(); c.close()                      # what a half-done rollback leaves
        p = self.problems(); self.assertEqual(len([x for x in p if 'déclencheur' in x]), 5, p)

    def test_the_expected_texts_match_what_the_migration_stores(self):
        c = sqlite3.connect(self.db)
        try:
            stored = {r[0]: credit_lines.norm_sql(r[1]) for r in c.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")}
            for n, t in credit_lines.expected_triggers().items(): self.assertEqual(stored[n], t, n)
            self.assertEqual(stored[line_guards.NAME], credit_lines.norm_sql(line_guards.TRIGGER))
        finally: c.close()


# ===================================================================================================================================================
class G_french_messages(tcl.Base):
    ENGLISH = re.compile(r"\b(cannot|exceed|immutable|must|belongs|credited line|constraint|failed|append-only|issued|trigger)\b", re.I)

    def setUp(self):
        super().setUp(); self.iid = self.issued_with()

    def test_every_guard_text_of_the_application_has_a_french_translation(self):
        sources = []
        for f in os.listdir(os.path.join(ROOT, 'app')):
            if f.endswith('.py'):
                with open(os.path.join(ROOT, 'app', f), encoding='utf-8') as fh: sources.append(fh.read())
        used = {t for s in sources for t in re.findall(r"RAISE\((?:ABORT|FAIL),'([^']*)'\)", s)}
        self.assertTrue(used); missing = sorted(t for t in used if t not in db_messages.GUARDS); self.assertEqual(missing, [], 'garde SQL sans traduction française')
        for en, fr in db_messages.GUARDS.items(): self.assertFalse(self.ENGLISH.search(fr), (en, fr))

    def test_french_translates_guards_constraints_and_never_shows_unknown_text(self):
        f = db_messages.french
        self.assertIn('avoirs', f(sqlite3.IntegrityError(CAP_EN))); self.assertNotIn('cannot', f(sqlite3.IntegrityError(CAP_EN)))
        self.assertIn('adresses', f(sqlite3.IntegrityError('UNIQUE constraint failed: billing_addresses.client_key, billing_addresses.label')))
        self.assertIn('doublon', f(sqlite3.IntegrityError('UNIQUE constraint failed: invoices.number')))
        self.assertEqual(f(sqlite3.OperationalError('quelque chose d\'inconnu en anglais near "x"')), db_messages.GENERIC)
        for e in (sqlite3.IntegrityError('FOREIGN KEY constraint failed'), sqlite3.IntegrityError('CHECK constraint failed: amount>0'), sqlite3.OperationalError('database is locked')):
            self.assertFalse(self.ENGLISH.search(f(e)), f(e))

    def test_restore_refusal_text(self):
        t = m.restore_refusal_text
        self.assertEqual(t(restore_service.RestoreRefused("saisir RESTAURER pour confirmer")), "saisir RESTAURER pour confirmer")
        s = t(sqlite3.IntegrityError(CAP_EN)); self.assertIn('avoirs', s); self.assertIn('administrateur', s); self.assertFalse(self.ENGLISH.search(s), s)
        s = t(sqlite3.IntegrityError('UNIQUE constraint failed: billing_addresses.client_key, billing_addresses.label')); self.assertIn('adresses', s); self.assertFalse(self.ENGLISH.search(s), s)
        s = t(KeyError('pdf')); self.assertIn('erreur inattendue', s); self.assertNotIn('pdf', s)

    def test_a_restore_stopped_by_the_database_shows_french_and_changes_nothing(self):
        data = json.loads(self.c.get('/backup').data)
        r = self.c.post('/restore', data={'backup': (__import__('io').BytesIO(json.dumps(data).encode()), 'sauvegarde.json')}, content_type='multipart/form-data')
        token = r.headers['Location'].rsplit('/', 1)[-1]; before = self.fingerprint_all(); self.flashes()
        with mock.patch.object(m.restore_service, 'rebuild', side_effect=sqlite3.IntegrityError(CAP_EN)):
            self.c.post(f'/restore/{token}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        fl = ' '.join(self.flashes()); self.assertIn('Restauration refusée, base inchangée', fl); self.assertIn('avoirs', fl)
        self.assertNotIn('cannot exceed', fl); self.assertFalse(self.ENGLISH.search(fl), fl); self.assertEqual(self.fingerprint_all(), before)

    def fingerprint_all(self):
        return [tuple(r) for t in ('invoices', 'invoice_lines', 'credit_notes', 'credit_note_lines') for r in self.sql(f'SELECT * FROM {t} ORDER BY 1')]

    def test_a_credit_note_refused_by_the_database_shows_french(self):
        with mock.patch.object(m, 'credit_note_lines_save', side_effect=sqlite3.IntegrityError(CAP_EN)):
            l1 = self.line_ids(self.iid)[0]; cid, fl = self.credit(self.iid, scope='partial', **{f'cl_{l1}': '40'})
        self.assertIsNone(cid); self.assertIn('Note de crédit non créée', fl); self.assertIn('avoirs', fl)
        self.assertNotIn('cannot exceed', fl); self.assertNotIn('credits of an invoice line', fl)

    def test_a_credit_note_refused_by_the_application_keeps_its_own_french_message(self):
        l1 = self.line_ids(self.iid)[0]; cid, fl = self.credit(self.iid, scope='partial', **{f'cl_{l1}': '1000'})
        self.assertIsNone(cid); self.assertIn('Note de crédit non créée', fl); self.assertFalse(self.ENGLISH.search(fl.split('Note de crédit non créée')[1][:200]), fl)


# ===================================================================================================================================================
class CD_return_tool(Base):
    TOOL = os.path.join(ROOT, 'outils', 'retour_rc47.py')

    def tool(self, *args):
        r = subprocess.run([sys.executable, '-I', self.TOOL, *args], capture_output=True, text=True, cwd='/'); return r.returncode, r.stdout + r.stderr

    def copy_db(self):
        d = tempfile.mkdtemp(dir=self.tmp); out = os.path.join(d, 'copie.db'); s = sqlite3.connect(self.db); t = sqlite3.connect(out); s.backup(t); t.close(); s.close(); return out

    def objs(self, path):
        c = sqlite3.connect(path)
        try: return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('index','trigger')")}
        finally: c.close()

    def test_base_dry_run_changes_nothing_then_the_return_removes_exactly_the_six_objects(self):
        path = self.copy_db(); before = self.objs(path); self.assertTrue({address_service.LABEL_INDEX, *credit_lines.UPDATE_GUARD_NAMES, line_guards.NAME} <= before)
        rc, out = self.tool('base', path); self.assertEqual(rc, 0, out); self.assertIn('Simulation', out); self.assertEqual(self.objs(path), before)
        rc, out = self.tool('base', path, '--oui'); self.assertEqual(rc, 0, out); self.assertIn('Retour arrière effectué', out)
        after = self.objs(path); self.assertEqual(before - after, {address_service.LABEL_INDEX, *credit_lines.UPDATE_GUARD_NAMES, line_guards.NAME}); self.assertEqual(after - before, set())
        c = sqlite3.connect(path)
        try:
            self.assertEqual(credit_lines.norm_sql(c.execute("SELECT sql FROM sqlite_master WHERE name='credit_lines_within_line'").fetchone()[0]), credit_lines.norm_sql(credit_lines.LEGACY_WITHIN_LINE_TRIGGER))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM audit WHERE event='rollback_rc47_schema'").fetchone()[0], 1)
        finally: c.close()
        self.assertEqual(len([f for f in os.listdir(os.path.dirname(path)) if '.avant-retour-rc47-' in f]), 1)
        rc, out = self.tool('base', path, '--oui'); self.assertEqual(rc, 0); self.assertIn('déjà au schéma rc47', out)
        rc, out = self.tool('base', path + '.absent'); self.assertEqual(rc, 1)
        rc, out = self.tool(); self.assertEqual(rc, 2)

    def test_json_mode_builds_an_rc47_schema_file_with_the_data_of_the_backup(self):
        pid = self.mandate(name='Mandat retour', legal_id='CHE-000.000.079'); self.entry(pid, '2026-09-10', 16)
        raw = self.c.get('/backup').data; d = tempfile.mkdtemp(dir=self.tmp); js = os.path.join(d, 'sauvegarde.json'); out = os.path.join(d, 'pour-rc47.db'); open(js, 'wb').write(raw)
        rc, txt = self.tool('json', js, out); self.assertEqual(rc, 0, txt); self.assertTrue(os.path.isfile(out))
        names = self.objs(out); self.assertFalse(names & {address_service.LABEL_INDEX, *credit_lines.UPDATE_GUARD_NAMES, line_guards.NAME}); self.assertIn('credit_lines_within_line', names)
        c = sqlite3.connect(out)
        try:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM projects WHERE name='Mandat retour'").fetchone()[0], 1); self.assertEqual(c.execute("SELECT COUNT(*) FROM entries").fetchone()[0], self.scalar('SELECT COUNT(*) FROM entries'))
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], 'ok')
        finally: c.close()
        rc, txt = self.tool('json', js, out); self.assertEqual(rc, 1); self.assertIn("refus d'écraser", txt)
        bad = os.path.join(d, 'x.json'); open(bad, 'w').write('{pas json'); rc, txt = self.tool('json', bad, os.path.join(d, 'y.db')); self.assertEqual(rc, 1); self.assertFalse(os.path.exists(os.path.join(d, 'y.db')))
        self.assertEqual(sorted(os.listdir(d)), ['pour-rc47.db', 'sauvegarde.json', 'x.json'])            # no scratch file left behind

    # ---- BILL-RC48-FIX2 (N-1) : l'outil ne doit jamais toucher la base visée par DB_PATH, ni la production sans confirmation explicite
    def tool_env(self, env_db, *args):
        env = {k: v for k, v in os.environ.items() if k not in ('DB_PATH',)}; env['DB_PATH'] = env_db
        r = subprocess.run([sys.executable, '-I', self.TOOL, *args], capture_output=True, text=True, cwd='/', env=env); return r.returncode, r.stdout + r.stderr

    def test_json_mode_never_opens_nor_migrates_the_database_pointed_by_DB_PATH(self):
        pid = self.mandate(name='Mandat N1', legal_id='CHE-000.000.080'); self.entry(pid, '2026-09-10', 16)
        raw = self.c.get('/backup').data; d = tempfile.mkdtemp(dir=self.tmp); js = os.path.join(d, 'sauvegarde.json'); open(js, 'wb').write(raw)
        bad = os.path.join(d, 'illisible.json'); open(bad, 'w').write('{pas json')
        target = self.copy_db(); rc, out = self.tool('base', target, '--oui'); self.assertEqual(rc, 0, out)            # a base brought back to the rc47 schema: the state the revue showed being re-migrated
        for f in os.listdir(os.path.dirname(target)):
            if '.avant-retour-rc47-' in f: os.remove(os.path.join(os.path.dirname(target), f))
        with open(target, 'rb') as f: h0 = f.read()
        before = sorted(os.listdir(os.path.dirname(target)))
        for jf, o in ((js, os.path.join(d, 'ok.db')), (bad, os.path.join(d, 'refuse.db'))):
            rc, out = self.tool_env(target, 'json', jf, o); self.assertEqual(rc, 0 if jf == js else 1, out)
            with open(target, 'rb') as f: self.assertEqual(f.read(), h0, 'la base visée par DB_PATH a été modifiée (migration rc48 ?)')
            self.assertEqual(sorted(os.listdir(os.path.dirname(target))), before)                                         # not even a -journal / -wal / staging directory
        self.assertEqual(self.objs(target) & {address_service.LABEL_INDEX, *credit_lines.UPDATE_GUARD_NAMES, line_guards.NAME}, set())
        self.assertEqual([x for x in os.listdir(tempfile.gettempdir()) if x.startswith('retour-rc47-env-') and os.path.getmtime(os.path.join(tempfile.gettempdir(), x)) > __import__('time').time() - 60], [])

    def test_the_tool_refuses_production_paths_and_the_default_database_unless_explicitly_confirmed(self):
        prod = '/opt/time-billing-v9/chemin-de-test-inexistant/x.db'          # never an existing file: the refusal and the confirmed case must not even look at the real production
        for args in (('base', prod), ('base', prod, '--oui'), ('json', prod + '.json', '/tmp/ne-sera-pas-cree.db'), ('json', '/tmp/x.json', '/opt/time-billing-v9/sortie.db')):
            rc, out = self.tool(*args); self.assertEqual(rc, 1, out); self.assertIn('REFUS', out); self.assertIn('--confirmer-chemin-production', out)
        self.assertFalse(os.path.exists('/tmp/ne-sera-pas-cree.db'))
        rc, out = self.tool('base', prod, '--confirmer-chemin-production'); self.assertEqual(rc, 1); self.assertIn('Fichier introuvable', out); self.assertNotIn('REFUS', out)        # confirmed: goes on (here: no such file, nothing written)
        target = self.copy_db(); rc, out = self.tool_env(target, 'base', target); self.assertEqual(rc, 1); self.assertIn('REFUS', out)                              # the default database (DB_PATH) counts as production
        rc, out = self.tool_env(target, 'base', target, '--confirmer-chemin-production'); self.assertEqual(rc, 0, out)
        link = os.path.join(os.path.dirname(target), 'lien.db'); os.symlink('/opt/time-billing-v9/x.db', link); rc, out = self.tool('base', link); self.assertEqual(rc, 1); self.assertIn('REFUS', out)

    def test_the_base_mode_does_not_import_the_application_so_init_never_runs(self):
        code = ("import runpy,sys\nsys.argv=['t','base','/tmp/inexistant-retour-rc47.db']\n"
                "try: runpy.run_path(%r, run_name='__main__')\nexcept SystemExit: pass\nprint('IMPORTED' if 'app.app' in sys.modules else 'NOT_IMPORTED')" % self.TOOL)
        r = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, cwd=ROOT, env={**os.environ, 'DB_PATH': os.path.join(self.tmp, 'ne-doit-pas-exister.db')})
        self.assertIn('NOT_IMPORTED', r.stdout + r.stderr); self.assertFalse(os.path.exists(os.path.join(self.tmp, 'ne-doit-pas-exister.db')))

    # ---- N-3 : avoirs au-dessus du plafond de rc47
    def test_credits_above_the_rc47_ceiling_are_counted_and_announced_by_the_base_mode(self):
        d = tempfile.mkdtemp(dir=self.tmp); path = os.path.join(d, 'mini.db'); c = sqlite3.connect(path)
        c.executescript("CREATE TABLE invoice_lines(id INTEGER PRIMARY KEY, qty REAL, unit_rate REAL); CREATE TABLE credit_note_lines(id INTEGER PRIMARY KEY, credit_note_id INTEGER, invoice_line_id INTEGER, amount REAL);"
                        "CREATE TABLE credit_note_cancellations(credit_note_id INTEGER);"
                        "INSERT INTO invoice_lines VALUES(1,1.5,0.15),(2,1,100),(3,1.5,0.15);"
                        "INSERT INTO credit_note_lines VALUES(1,1,1,0.23),(2,2,2,100),(3,3,3,0.23);INSERT INTO credit_note_cancellations VALUES(3);")
        c.commit()
        self.assertEqual(retour_rc47.over_rc47_cap(c), [1]); c.close()                                       # the cancelled credit (note 3) does not count, the exact credit (line 2) neither
        rc, out = self.tool('base', path); self.assertEqual(rc, 0, out); self.assertIn('ATTENTION : 1 ligne', out); self.assertIn('FICHIER SQLite', out)


# ===================================================================================================================================================
class B_control_tool(Base):
    TOOL = os.path.join(ROOT, 'outils', 'controle_copie_rc48.py')

    def run_tool(self, path):
        r = subprocess.run([sys.executable, '-I', self.TOOL, path], capture_output=True, text=True, cwd='/'); return r.returncode, r.stdout + r.stderr

    def copy_db(self):
        d = tempfile.mkdtemp(dir=self.tmp); out = os.path.join(d, 'copie.db'); s = sqlite3.connect(self.db); t = sqlite3.connect(out); s.backup(t); t.close(); s.close(); return out

    def test_clean_base_nothing_to_report_and_the_file_is_never_written(self):
        path = self.copy_db()
        with open(path, 'rb') as f: h0 = f.read()
        rc, out = self.run_tool(path)
        self.assertEqual(rc, 0, out); self.assertIn('RIEN À SIGNALER', out); self.assertEqual(rc, self.run_tool(path)[0])
        with open(path, 'rb') as f: self.assertEqual(f.read(), h0)
        self.assertEqual(sorted(os.listdir(os.path.dirname(path))), ['copie.db'])                    # no -journal / -wal file either

    def test_each_point_is_detected(self):
        path = self.copy_db(); c = sqlite3.connect(path)
        c.execute(f"DROP INDEX {address_service.LABEL_INDEX}")
        for k, l in (('*', 'Basel'), ('*', 'BASEL'), ('NOM:bsci', 'Zürich'), ('NOM:bsci', 'ZÜRICH'), ('NOM:bsci', 'egg fr'), ('*', 'EGG FR'), ('*', ' Lac  Léman ')):
            c.execute("INSERT INTO billing_addresses(client_key,label,address,created_at) VALUES(?,?,'x','2026-10-27T10:00:00')", (k, l))
        c.commit(); c.close()
        rc, out = self.run_tool(path); self.assertEqual(rc, 1, out)
        for needle in ('[À TRAITER] 1.', '[À TRAITER] 2.', '[À TRAITER] 3.', '[À TRAITER] 4.', '2:BASEL | 1:Basel', 'ZÜRICH', "(6, 'EGG FR', 5, 'egg fr')"): self.assertIn(needle, out, needle)
        self.assertLess(out.index('] 1.'), out.index('] 2.')); self.assertLess(out.index('] 2.'), out.index('] 3.'))
        rc, out = self.run_tool(path + '.absent'); self.assertEqual(rc, 2)
        self.assertEqual(subprocess.run([sys.executable, '-I', self.TOOL], capture_output=True, cwd='/').returncode, 2)


if __name__ == '__main__':
    unittest.main()
