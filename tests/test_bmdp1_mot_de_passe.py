"""BMDP1: « Changer mon mot de passe » dans l'application. Données synthétiques seulement (base jetable, aucun secret réel).

Run:  /root/venvs/rc25-test-venv/bin/python -I outils/run_tests_isolated.py tests.test_bmdp1_mot_de_passe

Le mot de passe de l'environnement (APP_PASSWORD, synthétique) est le mot de passe de départ ; le nouveau hachage scrypt, enregistré dans la
table auth_credentials, PRIME sur lui ; une base sans ligne = comportement d'avant, inchangé.
"""
import contextlib, io, json, logging, os, sqlite3, unittest
from werkzeug.security import generate_password_hash

import app.app as m
from app import restore_service as rs, security, invoice_checks
from outils import empreinte_metier
from tests.test_credit_settlement import Settlement
from tests.test_functional import pdf_text

URL = '/compte/mot-de-passe'
OLD = os.environ['APP_PASSWORD']                      # mot de passe de l'environnement (synthétique)
NEW = 'Nouveau-mot-de-passe-fictif-2026'
IP = {'REMOTE_ADDR': '203.0.113.7'}


class Pw(Settlement):
    def change(self, current=OLD, new=NEW, confirm=None, client=None, **kw):
        self.flashes() if client is None else None
        return (client or self.c).post(URL, data={'current_password': current, 'new_password': new, 'confirm_password': new if confirm is None else confirm}, **kw)

    def stored(self): return self.sql('SELECT * FROM auth_credentials')

    def login(self, pw, ip='198.51.100.9'):
        anon = m.APP.test_client()
        r = anon.post('/login', data={'username': m.SEC['user'], 'password': pw}, environ_base={'REMOTE_ADDR': ip})
        return anon, r

    def assert_refused(self, r, needle):
        self.assertEqual(r.status_code, 200); self.assertIn(needle, r.get_data(as_text=True).replace('&#39;', "'")); self.assertEqual(self.stored(), [])


class Screen(Pw):
    def test_page_needs_login_and_post_does_nothing_when_anonymous(self):
        anon = m.APP.test_client()
        r = anon.get(URL); self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])
        r = anon.post(URL, data={'current_password': OLD, 'new_password': NEW, 'confirm_password': NEW}); self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])
        self.assertEqual(self.stored(), [])

    def test_page_content_and_links(self):
        r = self.c.get(URL); t = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200); self.assertEqual(r.headers['Cache-Control'], 'no-store')
        for needle in ('Changer mon mot de passe', 'Mot de passe actuel', 'Nouveau mot de passe', 'seconde fois', '10 caractères au moins', 'name="current_password"',
                       'name="new_password"', 'name="confirm_password"', 'autocomplete="current-password"', 'autocomplete="new-password"', 'type="password"'):
            self.assertIn(needle, t)
        self.assertNotIn('value=', t.split('<form')[1].split('</form>')[0].replace('type="password"', ''))   # aucun champ prérempli
        home = self.c.get('/?tab=settings').get_data(as_text=True)
        self.assertEqual(home.count('href="/compte/mot-de-passe"'), 2)       # panneau « Accès à l'application » + menu « Plus » du téléphone

    def test_cross_site_post_is_refused(self):
        for h in ({'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            r = self.c.post(URL, data={'current_password': OLD, 'new_password': NEW, 'confirm_password': NEW}, headers=h)
            self.assertEqual(r.status_code, 403)
        self.assertEqual(self.stored(), []); self.assertEqual(self.login(OLD)[1].status_code, 302)
        r = self.c.post(URL, data={'current_password': OLD, 'new_password': NEW, 'confirm_password': NEW}, headers={'Origin': 'http://localhost'})   # même site : accepté
        self.assertEqual(r.status_code, 302); self.assertEqual(len(self.stored()), 1)


class Change(Pw):
    def test_success(self):
        r = self.change()
        self.assertEqual(r.status_code, 302); self.assertTrue(r.headers['Location'].endswith(URL))
        row = self.stored(); self.assertEqual(len(row), 1)
        self.assertTrue(row[0]['pw_hash'].startswith('scrypt:')); self.assertEqual(row[0]['version'], 1); self.assertTrue(row[0]['changed_at'])
        page = self.c.get(URL).get_data(as_text=True); self.assertIn('Mot de passe changé', page)
        self.assertEqual(self.sql("SELECT detail FROM audit WHERE event='password_changed'")[0][0][:17], 'mot de passe chan')
        self.assertEqual(self.login(NEW)[1].status_code, 302)                 # le nouveau mot de passe ouvre une session

    def test_old_password_is_refused_afterwards_and_the_new_one_is_needed_next_time(self):
        self.change()
        anon, r = self.login(OLD); self.assertEqual(r.status_code, 200); self.assertIn('Identifiants incorrects', r.get_data(as_text=True))
        with anon.session_transaction() as s: self.assertFalse(s.get('auth'))
        r = self.change(current=OLD, new='Encore-un-autre-mot-de-passe-1')      # l'ancien n'est plus le mot de passe actuel
        self.assert_refused_unchanged(r)
        r = self.change(current=NEW, new='Encore-un-autre-mot-de-passe-1'); self.assertEqual(r.status_code, 302)
        self.assertEqual(self.stored()[0]['version'], 2); self.assertEqual(self.login('Encore-un-autre-mot-de-passe-1')[1].status_code, 302)
        self.assertEqual(self.login(NEW)[1].status_code, 200)

    def assert_refused_unchanged(self, r):
        self.assertEqual(r.status_code, 200); self.assertIn('Mot de passe actuel incorrect', r.get_data(as_text=True)); self.assertEqual(self.stored()[0]['version'], 1)

    def test_wrong_current_password(self):
        r = self.change(current='mauvais-mot-de-passe-actuel')
        self.assert_refused(r, 'Mot de passe actuel incorrect')
        self.assertEqual(self.login(OLD)[1].status_code, 302)                  # rien n'a changé
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='password_change_failed'"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='password_changed'"), 0)

    def test_confirmation_differs(self):
        self.assert_refused(self.change(confirm=NEW + 'x'), 'pas identiques')

    def test_too_short_and_the_limit_itself(self):
        self.assert_refused(self.change(new='Neuf-car9'), 'trop court')       # 9 caractères (minimum 10 depuis le 20/11)
        self.assert_refused(self.change(new=''), 'trop court')
        self.assertEqual(self.change(new='Dix-chars1').status_code, 302)    # 10 caractères : accepté
        self.assertEqual(len(self.stored()), 1)

    def test_other_refusals(self):
        self.assert_refused(self.change(new=OLD), 'différent de l\'actuel')
        self.assert_refused(self.change(new=' ' * 14), 'espaces')
        self.assert_refused(self.change(new='x' * 201), 'trop long')
        self.assert_refused(self.change(new=os.environ['SECRET_KEY']), 'trop courant ou interdit')     # clé de session = mot de passe interdit
        self.assert_refused(self.change(new='replace-with-long-random-secret'), 'trop courant ou interdit')
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM web_sessions"), 1)   # un refus ne touche pas aux sessions

    def test_new_equal_to_the_current_stored_password_is_refused(self):
        self.change(); r = self.change(current=NEW, new=NEW)
        self.assertEqual(r.status_code, 200); self.assertIn('différent de l\'actuel', r.get_data(as_text=True).replace('&#39;', "'")); self.assertEqual(self.stored()[0]['version'], 1)

    def test_unicode_password_roundtrip(self):
        pw = 'Mot de passe très élaboré — ç ñ 日本語 !'
        self.assertEqual(self.change(new=pw).status_code, 302); self.assertEqual(self.login(pw)[1].status_code, 302)

    def test_clear_text_cannot_be_stored(self):
        c = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError): c.execute("INSERT INTO auth_credentials(id,pw_hash,version,changed_at) VALUES(1,'mot de passe en clair',1,'x')")
            with self.assertRaises(sqlite3.IntegrityError): c.execute("INSERT INTO auth_credentials(id,pw_hash,version,changed_at) VALUES(2,'scrypt:x',1,'x')")   # une seule ligne
        finally: c.close()


class Throttle(Pw):
    def test_wrong_current_password_is_limited_like_the_login(self):
        for _ in range(security.MAX_FAILURES): self.assertEqual(self.change(current='faux', environ_base=IP).status_code, 200)
        r = self.change(current=OLD, environ_base=IP)                           # même le bon mot de passe est refusé maintenant
        self.assertEqual(r.status_code, 429); self.assertIn('Trop de tentatives', r.get_data(as_text=True)); self.assertEqual(self.stored(), [])
        self.change(current=OLD, environ_base=IP); self.change(current=OLD, environ_base=IP)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='password_change_throttled'"), 1)   # une ligne par client et par fenêtre
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='password_change_failed'"), security.MAX_FAILURES)
        self.assertEqual(self.change(current=OLD, environ_base={'REMOTE_ADDR': '198.51.100.20'}).status_code, 302)   # un autre client n'est pas touché
        audit = ' '.join(r[0] for r in self.sql("SELECT detail FROM audit WHERE event LIKE 'password_%'"))
        for secret in ('faux', OLD, NEW): self.assertNotIn(secret, audit)
        self.assertIn('ip=203.0.113.7', audit)

    def test_window_elapses(self):
        for _ in range(security.MAX_FAILURES): self.change(current='faux', environ_base=IP)
        c = sqlite3.connect(self.db); c.execute("UPDATE login_failures SET at='2000-01-01T00:00:00'"); c.commit(); c.close()
        self.assertEqual(self.change(current=OLD, environ_base=IP).status_code, 302)

    def test_the_counter_is_shared_with_the_login(self):
        anon = m.APP.test_client()
        for _ in range(security.MAX_FAILURES): anon.post('/login', data={'username': m.SEC['user'], 'password': 'faux'}, environ_base=IP)
        self.assertEqual(self.change(environ_base=IP).status_code, 429)         # une session déjà ouverte ne peut pas servir à deviner le mot de passe

    def test_success_clears_the_failures(self):
        for _ in range(2): self.change(current='faux', environ_base=IP)
        self.assertEqual(self.change(environ_base=IP).status_code, 302)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM login_failures WHERE ip='203.0.113.7'"), 0)


class Precedence(Pw):
    def test_empty_table_keeps_the_environment_behaviour(self):
        self.assertEqual(self.stored(), []); self.assertEqual(self.login(OLD)[1].status_code, 302); self.assertEqual(self.login(NEW)[1].status_code, 200)

    def test_database_wins_over_the_environment_hash(self):
        env_pw = 'Mot-de-passe-du-hachage-env-1'; old = dict(m.SEC)
        m.SEC.update(pw_hash=generate_password_hash(env_pw, method='scrypt'), pw=None); self.addCleanup(lambda: (m.SEC.clear(), m.SEC.update(old)))
        self.assertEqual(self.login(env_pw)[1].status_code, 302); self.assertEqual(self.login(OLD)[1].status_code, 200)
        self.assertEqual(self.change(current=env_pw).status_code, 302)
        self.assertEqual(self.login(NEW)[1].status_code, 302); self.assertEqual(self.login(env_pw)[1].status_code, 200)
        # secours : effacer la ligne rend la main au mot de passe de l'environnement (voir docs/MOT-DE-PASSE.md)
        c = sqlite3.connect(self.db); c.execute('DELETE FROM auth_credentials'); c.commit(); c.close()
        self.assertEqual(self.login(env_pw)[1].status_code, 302); self.assertEqual(self.login(NEW)[1].status_code, 200)

    def test_database_wins_over_the_environment_clear_password_and_recovery_works(self):
        self.change()
        self.assertEqual(self.login(OLD)[1].status_code, 200); self.assertEqual(self.login(NEW)[1].status_code, 302)
        c = sqlite3.connect(self.db); c.execute('DELETE FROM auth_credentials'); c.commit(); c.close()
        self.assertEqual(self.login(OLD)[1].status_code, 302); self.assertEqual(self.login(NEW)[1].status_code, 200)

    def test_user_name_is_still_checked(self):
        self.change(); anon = m.APP.test_client()
        r = anon.post('/login', data={'username': 'autre', 'password': NEW}); self.assertEqual(r.status_code, 200)

    def test_pure_function_without_connection_ignores_the_table(self):
        cfg = {'user': 'admin', 'pw_hash': None, 'pw': 'Une phrase de passe fictive', 'key': 'k' * 40}
        self.assertTrue(security.credentials_ok(cfg, 'admin', 'Une phrase de passe fictive')); self.assertFalse(security.credentials_ok(cfg, 'admin', 'autre'))


class Sessions(Pw):
    def test_current_session_stays_others_are_revoked(self):
        other, r = self.login(OLD, ip='198.51.100.30'); self.assertEqual(r.status_code, 302)
        third, r = self.login(OLD, ip='198.51.100.31'); self.assertEqual(r.status_code, 302)
        self.assertEqual(other.get('/?tab=dashboard').status_code, 200)
        with self.c.session_transaction() as s: sid_before = s['sid']
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM web_sessions'), 3)
        self.assertEqual(self.change().status_code, 302)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM web_sessions'), 1)
        with self.c.session_transaction() as s: self.assertNotEqual(s['sid'], sid_before)       # identifiant renouvelé
        self.assertEqual(self.c.get('/?tab=dashboard').status_code, 200)                       # cette session reste ouverte
        for c in (other, third):
            r = c.get('/?tab=dashboard'); self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])
        r = other.post('/entry', data={'work_date': '2026-09-10', 'project_id': self.pid, 'entry_mode': 'duration', 'manual_hours': '1'})
        self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])   # une écriture d'un autre appareil est refusée aussi
        self.assertEqual(self.sql("SELECT COUNT(*) FROM web_sessions WHERE sid=?", (self.c.get_cookie('tb_session') and self._sid(),))[0][0], 1)

    def _sid(self):
        with self.c.session_transaction() as s: return s['sid']

    def test_refused_change_revokes_nothing(self):
        other, _ = self.login(OLD, ip='198.51.100.30'); self.change(current='faux')
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM web_sessions'), 2); self.assertEqual(other.get('/?tab=dashboard').status_code, 200)

    def test_kept_forms_of_revoked_sessions_are_dropped(self):
        c = sqlite3.connect(self.db); c.execute("INSERT INTO kept_forms VALUES('autre','/x','{}','2026-01-01T00:00:00')"); c.commit(); c.close()
        self.change(); self.assertEqual(self.scalar('SELECT COUNT(*) FROM kept_forms'), 0)


class NoClearText(Pw):
    def test_no_password_in_database_audit_logs_or_kept_forms(self):
        wrong = 'Tentative-erronee-fictive-77'
        buf_out, buf_err = io.StringIO(), io.StringIO(); records = []

        class H(logging.Handler):
            def emit(self, rec): records.append(rec.getMessage())
        h = H(); root = logging.getLogger(); root.addHandler(h); old_level = root.level; root.setLevel(logging.DEBUG); m.APP.logger.addHandler(h)
        try:
            with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                self.change(current=wrong); self.change(new='court'); self.change(confirm='autre-chose-entierement')
                self.assertEqual(self.change().status_code, 302)
        finally: root.removeHandler(h); m.APP.logger.removeHandler(h); root.setLevel(old_level)
        seen = ' '.join(records) + buf_out.getvalue() + buf_err.getvalue()
        c = sqlite3.connect(self.db)
        try:
            dump = '\n'.join(repr(r) for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'") for r in c.execute(f'SELECT * FROM "{t}"'))
        finally: c.close()
        raw = b''
        for f in os.listdir(self.tmp):
            if f.startswith('timebilling.db'):
                with open(os.path.join(self.tmp, f), 'rb') as fh: raw += fh.read()
        for secret in (NEW, wrong, 'court', 'autre-chose-entierement'):
            self.assertNotIn(secret, seen, secret); self.assertNotIn(secret, dump, secret); self.assertNotIn(secret.encode(), raw, secret)
        self.assertNotIn(OLD, seen); self.assertNotIn(OLD, ' '.join(r[0] for r in self.sql('SELECT detail FROM audit')))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM kept_forms'), 0)
        self.assertEqual(len(self.stored()), 1); self.assertTrue(self.stored()[0]['pw_hash'].startswith('scrypt:'))

    def test_the_hash_is_not_in_the_json_backup_nor_the_pages(self):
        self.change(); h = self.stored()[0]['pw_hash']
        b = self.c.get('/backup').get_data(as_text=True)
        self.assertNotIn(h, b); self.assertNotIn(NEW, b)
        obj = json.loads(b); self.assertNotIn('auth_credentials', obj['tables']); self.assertNotIn('auth_credentials', obj['meta']['row_counts'])   # (la définition de la table figure dans meta.schema, comme celle de web_sessions : aucune donnée)
        for u in ('/?tab=settings', URL): self.assertNotIn(h, self.c.get(u).get_data(as_text=True))

    def test_response_pages_never_echo_the_passwords(self):
        r = self.change(current='faux-actuel-fictif', new='court', confirm='autre'); t = r.get_data(as_text=True)
        for s in ('faux-actuel-fictif', 'court', 'autre'): self.assertNotIn(f'value="{s}"', t)


class BackupRestore(Pw):
    def test_table_is_operational_state(self):
        self.assertIn('auth_credentials', rs.TRANSIENT)

    def test_a_restore_neither_brings_back_the_old_password_nor_loses_the_new_one(self):
        backup = self.c.get('/backup').data                                   # sauvegarde faite avec l'ancien mot de passe
        self.change()
        tok = self.c.post('/restore', data={'backup': (io.BytesIO(backup), 'sauvegarde.json')}, content_type='multipart/form-data').headers['Location'].rsplit('/', 1)[-1]
        self.c.post(f'/restore/{tok}', data={'action': 'restore', 'confirm': 'RESTAURER'})
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(self.login(NEW)[1].status_code, 302); self.assertEqual(self.login(OLD)[1].status_code, 200)

    def test_init_is_additive_and_idempotent(self):
        c = sqlite3.connect(self.db); c.execute('DROP TABLE auth_credentials'); c.commit(); c.close()
        m.init(); m.init()
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.sql("SELECT sql FROM sqlite_master WHERE name='auth_credentials'")[0][0].count('CREATE TABLE'), 1)
        self.assertEqual(self.login(OLD)[1].status_code, 302)                   # base sans table : comportement d'avant
        self.assertEqual(self.change().status_code, 302)                         # et le changement recrée / remplit la table


class BusinessFingerprint(Pw):
    """Un changement de mot de passe ne touche à aucune donnée métier : factures, PDF figés, contrôles, empreinte SHA-256 des tables métier."""

    def test_invoices_pdf_checks_and_fingerprints_are_identical(self):
        pid = self.mandate(name='Mandat empreinte', rate='650', vat='8.1', ordered='12')
        self.entry(pid, '2026-10-05', 16)
        draft, _ = self.draft(pid, '2026-10-01', '2026-10-31', 2)

        def snap():
            self.flashes()                    # le message « Mot de passe changé » (affiché une fois) n'est pas une donnée métier
            c = m.db()
            try: checks = repr([(k['n'], k['status'], k.get('detail')) for k in invoice_checks.run_checks(c, draft)])
            finally: c.close()
            # le PDF d'un brouillon porte l'horodatage de sa génération : on compare son texte ; le PDF figé d'une facture émise, octet pour octet
            return {'pdf_issued': self.c.get(f'/invoice/{self.iid}.pdf').data, 'pdf_draft_text': pdf_text(self.c.get(f'/invoice/{draft}.pdf').data), 'checks': checks,
                    'issue_page': self.strip_nonce(self.c.get(f'/issue/{draft}').get_data(as_text=True)), 'archive': self.strip_nonce(self.c.get('/?tab=archive').get_data(as_text=True)),
                    'invoices': [tuple(r) for r in self.sql('SELECT * FROM invoices ORDER BY id')], 'snapshots': [tuple(r) for r in self.sql('SELECT * FROM invoice_snapshots ORDER BY invoice_id')]}

        self.c.get('/?tab=archive')           # consomme l'indicateur « dernière saisie » (état de session propre à la saisie, sans lien avec le mot de passe)
        before, db_before = snap(), os.path.join(self.tmp, 'avant.db')
        src = sqlite3.connect(self.db); dst = sqlite3.connect(db_before); src.backup(dst); src.close(); dst.close()
        self.assertEqual(self.change().status_code, 302)
        after = snap()
        self.assertEqual(before, after)
        self.assertEqual(before['pdf_issued'], self.inv_pdf)
        self.assertEqual(empreinte_metier.comparer(db_before, self.db), [])                                   # toutes les tables métier identiques
        fa, fb = empreinte_metier.empreinte(db_before), empreinte_metier.empreinte(self.db)
        self.assertEqual(fa['tables_metier'], fb['tables_metier']); self.assertEqual(fa['chiffres'], fb['chiffres'])
        self.assertNotIn('auth_credentials', fb['tables_metier']); self.assertEqual(fb['hors_comparaison']['auth_credentials'], 1)
        self.assertEqual(empreinte_metier.vide(self.db) != [], True)                                          # (la base de test contient des données métier)

    @staticmethod
    def strip_nonce(t):
        import re
        return re.sub(r'nonce="[^"]*"', 'nonce=""', t)

    def test_an_empty_production_stays_empty_for_the_g4_promotion_check(self):
        """Une base sans donnée métier mais avec un mot de passe changé reste « vide » pour outils/empreinte_metier.py vide."""
        tmp = os.path.join(self.tmp, 'vide.db'); c = sqlite3.connect(tmp)
        c.executescript("CREATE TABLE entries(id INTEGER); CREATE TABLE auth_credentials(id INTEGER PRIMARY KEY, pw_hash TEXT, version INTEGER, changed_at TEXT); INSERT INTO auth_credentials VALUES(1,'scrypt:x',1,'t');")
        c.commit(); c.close(); self.assertEqual(empreinte_metier.vide(tmp), [])


class Recovery(Pw):
    """docs/MOT-DE-PASSE.md : le bloc Python de secours, tel qu'il est écrit dans la documentation, est exécuté sur une base jetable."""

    def test_documented_recovery_command_restores_the_environment_password(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'docs', 'MOT-DE-PASSE.md'), encoding='utf-8') as fh: doc = fh.read()
        blocks = doc.split('```python\n')[1:]; self.assertEqual(len(blocks), 1); code = blocks[0].split('```')[0]
        self.assertIn('/data/timebilling.db', code); code = code.replace('/data/timebilling.db', self.db)
        other, _ = self.login(OLD, ip='198.51.100.40')
        self.change(); self.assertEqual(self.login(OLD)[1].status_code, 200)
        out = io.StringIO()
        with contextlib.redirect_stdout(out): exec(compile(code, 'secours', 'exec'), {})
        self.assertIn('lignes effacées : 1', out.getvalue())
        self.assertEqual(self.stored(), []); self.assertEqual(self.scalar('SELECT COUNT(*) FROM web_sessions'), 0)
        self.assertEqual(self.login(OLD)[1].status_code, 302); self.assertEqual(self.login(NEW)[1].status_code, 200)
        self.assertEqual(self.c.get('/').status_code, 302)                                     # session révoquée par la commande
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit WHERE event='password_reset_to_environment'"), 1)
        for t in ('entries', 'invoices', 'invoice_snapshots', 'projects'): self.assertGreaterEqual(self.scalar(f'SELECT COUNT(*) FROM {t}'), 0)
        c2, _ = self.login(OLD); self.assertEqual(self.change(client=c2).status_code, 302); self.assertEqual(len(self.stored()), 1)   # et on peut à nouveau changer le mot de passe


class Scripts(unittest.TestCase):
    def test_procedure_scripts_treat_the_table_as_transient(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        def read(f):
            with open(os.path.join(root, f)) as fh: return fh.read()
        self.assertIn('"auth_credentials"', read('procedure/90-rollback.sh').split('TRANSITOIRES = ')[1].split('\n')[0])
        self.assertIn('"auth_credentials"', read('procedure/70-promouvoir-base-staging.sh').split('purge = ')[1].split('\n')[0])
        self.assertIn('auth_credentials', empreinte_metier.HORS_COMPARAISON)


if __name__ == '__main__':
    unittest.main()
