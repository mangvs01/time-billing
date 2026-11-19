"""rc25 D6 — procedure/backup-offsite.sh : la configuration n'est JAMAIS exécutée, elle est lue comme des données (liste blanche, valeurs validées, fail-closed).
Seule l'option --check-config est lancée : ni sauvegarde, ni rclone, ni restic, ni réseau, ni e-mail."""
import os, shutil, subprocess, tempfile, types, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'procedure', 'backup-offsite.sh')

VALID = '''# commentaire
RESTIC_REPOSITORY="rclone:Onedrive:TimeBilling/production"
RCLONE_CONFIG="/etc/time-billing-backup/rclone.conf"
RESTIC_PASSWORD_FILE=/etc/time-billing-backup/restic-password
RESTIC_READ_DATA_SUBSET="1/10"
KEEP_DAILY="30"
KEEP_MONTHLY="12"
TB_SMTP_HOST="smtp.gmail.com"
TB_SMTP_PORT="587"
TB_SMTP_TLS="starttls"
TB_SMTP_FROM="a@example.org"
TB_ALERT_TO="a@example.org"
TB_SMTP_USER="a@example.org"
TB_SMTP_PASSWORD="abcdEFGHijklMNOP"
'''


class BackupOffsiteConf(unittest.TestCase):
    def setUp(self):
        # mkdtemp() sans argument positionnel : le runner isolé (run_tests_isolated.py) remplace
        # tempfile.mkdtemp par un wrapper qui impose dir= ; TemporaryDirectory() (Python 3.12)
        # lui passe dir en positionnel et provoque « got multiple values for argument 'dir' ».
        self.td = types.SimpleNamespace(name=tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.td.name, True)
        self.marker = os.path.join(self.td.name, 'MARKER')

    def check(self, text):
        p = os.path.join(self.td.name, 'backup.env')
        with open(p, 'w', newline='') as f: f.write(text)
        return subprocess.run(['bash', SCRIPT, '--check-config', p], capture_output=True, text=True, timeout=30,
                              env={'PATH': '/usr/bin:/bin', 'HOME': self.td.name})

    def assertRefused(self, text, what):
        r = self.check(text)
        self.assertFalse(os.path.exists(self.marker), f'{what} : la configuration a été EXÉCUTÉE')
        self.assertNotEqual(r.returncode, 0, f'{what} : {r.stdout}{r.stderr}')
        self.assertIn('ARRÊT', r.stderr, what)
        return r

    def test_valid_conf_is_accepted(self):
        r = self.check(VALID)
        self.assertEqual((r.returncode, r.stderr), (0, ''), r.stdout)

    def test_s3_repository_is_refused_with_code_2(self):
        text = VALID.replace('RESTIC_REPOSITORY="rclone:Onedrive:TimeBilling/production"', 'RESTIC_REPOSITORY="s3:https://s3.example.org/bucket/prefix"')
        r = self.assertRefused(text, 's3:')
        self.assertEqual(r.returncode, 2)
        self.assertIn('S3', r.stderr)

    def test_aws_keys_are_refused_with_code_2(self):
        for k, v in (('AWS_ACCESS_KEY_ID', 'AKIA0123'), ('AWS_SECRET_ACCESS_KEY', 'ab/cd+ef=='), ('AWS_DEFAULT_REGION', 'eu-west-1')):
            with self.subTest(k):
                r = self.assertRefused(VALID + f'{k}="{v}"\n', k)
                self.assertEqual(r.returncode, 2)
                self.assertIn('AWS_*', r.stderr)

    def check_env(self, extra, flags=()):
        p = os.path.join(self.td.name, 'backup.env')
        with open(p, 'w') as f: f.write(VALID)
        env = {'PATH': '/usr/bin:/bin', 'HOME': self.td.name, **extra}
        return subprocess.run(['bash', *flags, SCRIPT, '--check-config', p], capture_output=True, text=True, timeout=30, env=env)

    def assertEnvRefused(self, extra, what):
        r = self.check_env(extra)
        self.assertNotEqual(r.returncode, 0, what)
        self.assertIn('environnement non sûr', r.stderr, what)
        self.assertNotIn('Configuration valide', r.stdout, what)

    def test_bash_env_is_refused(self):
        benv = os.path.join(self.td.name, 'benv.sh')
        with open(benv, 'w') as f: f.write(f'touch {self.marker}\n')
        self.assertEnvRefused({'BASH_ENV': benv}, 'BASH_ENV')

    def test_env_is_refused(self):
        self.assertEnvRefused({'ENV': os.path.join(self.td.name, 'env.sh')}, 'ENV')

    def test_exported_function_is_refused(self):
        self.assertEnvRefused({'BASH_FUNC_hostname%%': '() { echo piege; }'}, 'fonction exportée')

    def test_valid_rclone_conf_is_accepted_under_hardened_invocation(self):
        r = self.check_env({}, flags=('-p',))
        self.assertEqual((r.returncode, r.stderr), (0, ''), r.stdout)

    def test_hostile_or_invalid_lines_are_refused(self):
        m = self.marker
        cases = {
            'clé inconnue': 'FOO=bar',
            'clé dangereuse PATH': 'PATH=/tmp/evil',
            'clé dangereuse BASH_ENV': 'BASH_ENV=/tmp/x',
            'clé en minuscules': 'keep_daily=3',
            'substitution $()': f'RESTIC_REPOSITORY="rclone:R:$(touch {m})"',
            'substitution $() sans guillemets': f'KEEP_DAILY=$(touch {m})',
            'backquotes': f'TB_SMTP_HOST=`touch {m}`',
            'backquotes entre guillemets': f'TB_SMTP_HOST="`touch {m}`"',
            'point-virgule': f'KEEP_DAILY=3; touch {m}',
            'point-virgule entre guillemets': 'RCLONE_CONFIG="/etc/a;b"',
            'esperluette': f'KEEP_DAILY=3 & touch {m}',
            'expansion ${}': 'RCLONE_CONFIG="${HOME}/x"',
            'commande nue': f'touch {m}',
            'export': 'export KEEP_DAILY=3',
            'source': f'. {m}',
            'chemin relatif': 'RESTIC_PASSWORD_FILE="restic-password"',
            'chemin relatif ./': 'RCLONE_CONFIG="./rclone.conf"',
            'chemin avec ..': 'RESTIC_PASSWORD_FILE="/etc/time-billing-backup/../shadow"',
            'remote rclone avec ..': 'RESTIC_REPOSITORY="rclone:Onedrive:../autre"',
            'dépôt s3 (variante supprimée)': 'RESTIC_REPOSITORY="s3:https://s3.example.org/b/p"',
            'dépôt ni s3 ni rclone': 'RESTIC_REPOSITORY="/tmp/depot-local"',
            'ligne sans =': 'RESTIC_PASSWORD_FILE',
            'entier invalide': 'KEEP_DAILY="3x"',
            'TLS hors liste': 'TB_SMTP_TLS="oui"',
            'retour chariot (CRLF)': 'KEEP_DAILY="3"\r',
            'commentaire en fin de ligne': 'TB_SMTP_TLS="starttls"   # starttls | ssl | none',
            'doublon': 'KEEP_DAILY="31"',
        }
        for label, line in cases.items():
            with self.subTest(label):
                if os.path.exists(m): os.remove(m)
                self.assertRefused(VALID + line + '\n', label)

    def test_message_names_line_and_reason(self):
        r = self.assertRefused('KEEP_DAILY=3\nFOO=bar\n', 'clé inconnue')
        self.assertIn('ligne 2', r.stderr)
        self.assertIn('FOO', r.stderr)
        r = self.assertRefused('RCLONE_CONFIG=/etc/../x\n', 'chemin ..')
        self.assertIn('valeur refusée', r.stderr)

    def test_one_bad_line_refuses_the_whole_file(self):
        self.assertRefused(VALID + 'garbage\n', 'ligne sans =')

    def test_missing_file_and_usage(self):
        r = subprocess.run(['bash', SCRIPT, '--check-config', os.path.join(self.td.name, 'absent')], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('illisible', r.stderr)
        r = subprocess.run(['bash', SCRIPT, '--check-config'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)

    def test_script_does_not_source_its_config(self):
        src = open(SCRIPT).read()
        for l in src.splitlines():
            self.assertNotRegex(l, r'^\s*(\.|source)\s+"?\$CONFIG', l)


if __name__ == '__main__':
    unittest.main()
