"""rc25 — garde de production des scripts de procédure (procedure/tb-common.sh) : blocage par défaut, reconnaissance de la production par tous ses identifiants,
exception « sauvegarde » liée à l'empreinte SHA-256 des scripts approuvés, fichier d'approbation de confiance, nettoyage des fichiers temporaires.

Tout se passe dans un dossier temporaire avec un FAUX `docker` (il journalise ses appels et ne touche à rien) : aucun conteneur, aucun /opt, aucun /etc réel.
La propriété « root » des fichiers est contrôlée par la garde : ces tests ne s'exécutent donc qu'en root (ils sont ignorés, explicitement, sinon).
"""
import os, re, shutil, sqlite3, stat, subprocess, tempfile, unittest
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(REPO, 'procedure')
NAMES = ('backup-quotidien.sh', 'verifier-sauvegarde.sh', 'tb-common.sh', 'lire-conf.sh')
DEFAULT_APPROVALS = '/etc/time-billing/approved-scripts.sha256'      # constante du code ; les copies de test la remplacent par un fichier du dossier temporaire
COPIED = NAMES + ('approuver-sauvegarde.sh', '00-prerequis-bascule.sh', '10-preflight.sh', '20-backup.sh', '30-rehearse.sh', '40-deploy.sh', '50-verify.sh', '60-donnees-d1-d2-a01.sh',
                    '70-promouvoir-base-staging.sh', '80-site-caddy.sh', '90-rollback.sh', 'mot-de-passe-production.sh', 'rotate-secrets.sh')

FAKE_DOCKER = r'''#!/bin/bash
echo "docker $*" >> "$FAKE_DOCKER_LOG"
case "$1" in
  exec) shift
    case "$*" in
      *" rm -f "*) exit 0 ;;
      *python*) cat >/dev/null; [ "${FAKE_DOCKER_FAIL:-}" = python ] && exit 1; exit 0 ;;
    esac ;;
  cp) python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('create table if not exists t(x)'); c.commit()" "$3"; exit 0 ;;
esac
exit 0
'''


def today(): return datetime.now(timezone.utc).strftime('%Y%m%d')


@unittest.skipUnless(os.geteuid() == 0, 'la garde exige des fichiers appartenant à root : tests exécutés en root seulement')
class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix='tbguard-')
        t = self.td
        self.etc = os.path.join(t, 'etc'); os.makedirs(self.etc, mode=0o755); os.chmod(self.etc, 0o755)
        self.approvals = os.path.join(self.etc, 'approved-scripts.sha256')
        self.proc = os.path.join(t, 'proc'); os.makedirs(self.proc, mode=0o755)
        for n in COPIED: shutil.copy(os.path.join(PROC, n), self.proc); os.chmod(os.path.join(self.proc, n), 0o755)
        for n in ('tb-common.sh', 'approuver-sauvegarde.sh'):                    # SEULE différence avec le dépôt : le chemin constant du fichier d'approbation
            path = os.path.join(self.proc, n)
            with open(path) as f: text = f.read()
            with open(path, 'w') as f: f.write(text.replace(DEFAULT_APPROVALS, self.approvals))
        os.chmod(self.proc, 0o755)
        self.bin = os.path.join(t, 'bin'); os.makedirs(self.bin)
        with open(os.path.join(self.bin, 'docker'), 'w') as f: f.write(FAKE_DOCKER)
        os.chmod(os.path.join(self.bin, 'docker'), 0o755)
        self.log = os.path.join(t, 'docker.log'); open(self.log, 'w').close()
        self.app = os.path.join(t, 'app'); os.makedirs(self.app)
        with open(os.path.join(self.app, 'app.py'), 'w') as f: f.write('VERSION="9.2-rc25"\n')
        open(os.path.join(self.app, 'requirements.txt'), 'w').close()
        self.backups = os.path.join(t, 'backups')
        self.prod = self.conf('prod.conf', root='/opt/time-billing-v9')

    def tearDown(self): shutil.rmtree(self.td, ignore_errors=True)

    def conf(self, name, root, project='time-billing-v9', container='time-billing-v9', image='time-billing-v9-time-billing-v9', url='http://127.0.0.1:8091'):
        p = os.path.join(self.td, name)
        with open(p, 'w') as f:
            f.write(f'ROOT={root}\nPROJECT={project}\nCONTAINER={container}\nIMAGE={image}\nURL={url}\nBACKUP_BASE={self.backups}\n'
                    f'SOURCE_APP={self.app}\nSOURCE_REQ={self.app}/requirements.txt\nRC_IMAGE=x\nCOMPOSE_TEMPLATE=x\n')
        return p

    def sha(self, name): return subprocess.run(['sha256sum', os.path.join(self.proc, name)], capture_output=True, text=True).stdout.split()[0]

    def approve(self, names=NAMES, mode=0o644):
        with open(self.approvals, 'w') as f:
            for n in names: f.write(f'{self.sha(n)}  {n}\n')
        os.chmod(self.approvals, mode)

    def run_script(self, script, conf, *args, env=None, proc=None, privileged=True):
        e = dict(os.environ, PATH=self.bin + ':' + os.environ['PATH'], FAKE_DOCKER_LOG=self.log)
        e.pop('CONFIRM_PROD', None); e.update(env or {})
        return subprocess.run(['bash', *(['-p'] if privileged else []), os.path.join(proc or self.proc, script), conf, *args], capture_output=True, text=True, env=e, cwd=self.td)

    def calls(self): return open(self.log).read().splitlines()

    def reset_calls(self): open(self.log, 'w').close()

    def blocked(self, r):
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('PRODUCTION', r.stdout + r.stderr)
        self.assertEqual(self.calls(), [], 'aucun appel docker avant le refus')

    def ran(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any(c.startswith('docker exec') for c in self.calls()))



@unittest.skipUnless(os.geteuid() == 0, 'la garde exige des fichiers appartenant à root : tests exécutés en root seulement')
class Guard(Base):
    # --- blocage par défaut ---------------------------------------------------------------------------------------------------------------------
    def test_default_blocks_the_backup_scripts_without_any_approval(self):
        self.blocked(self.run_script('backup-quotidien.sh', self.prod))
        self.blocked(self.run_script('verifier-sauvegarde.sh', self.prod, os.path.join(self.td, 'x.db')))

    def test_other_scripts_stay_blocked_even_with_a_valid_approval(self):
        self.approve()
        for s in ('20-backup.sh', '40-deploy.sh', '90-rollback.sh'): self.blocked(self.run_script(s, self.prod))

    def test_confirm_prod_still_works_and_only_with_todays_date(self):
        self.ran(self.run_script('backup-quotidien.sh', self.prod, env={'CONFIRM_PROD': f'OUI-{today()}'}))
        self.reset_calls()
        self.blocked(self.run_script('backup-quotidien.sh', self.prod, env={'CONFIRM_PROD': 'OUI-20200101'}))

    # --- la production est reconnue par tous ses identifiants -------------------------------------------------------------------------------------
    def test_every_spelling_or_identifier_of_production_is_guarded(self):
        link = os.path.join(self.td, 'link-to-prod'); os.symlink('/opt/time-billing-v9', link)
        cases = {'trailing slash': self.conf('a.conf', '/opt/time-billing-v9/'), 'symlink': self.conf('b.conf', link),
                 'dotted': self.conf('c.conf', '/opt/./time-billing-v9'),
                 'container only': self.conf('d.conf', '/tmp/not-production', project='x', container='time-billing-v9', image='x', url='http://127.0.0.1:1'),
                 'project only': self.conf('e.conf', '/tmp/not-production', project='time-billing-v9', container='x', image='x', url='http://127.0.0.1:1'),
                 'image only': self.conf('f.conf', '/tmp/not-production', project='x', container='x', url='http://127.0.0.1:1'),
                 'port only': self.conf('g.conf', '/tmp/not-production', project='x', container='x', image='x', url='http://127.0.0.1:8091/')}
        for label, c in cases.items():
            with self.subTest(label): self.blocked(self.run_script('backup-quotidien.sh', c))

    def test_staging_is_not_production_and_is_unaffected(self):
        st = os.path.join(self.td, 'staging.conf'); repl = {'BACKUP_BASE': self.backups, 'SOURCE_APP': self.app, 'SOURCE_REQ': f'{self.app}/requirements.txt'}
        with open(os.path.join(PROC, 'staging.conf')) as f: lines = f.read().splitlines()
        with open(st, 'w') as f: f.write('\n'.join(f'{l.split("=")[0]}={repl[l.split("=")[0]]}' if l.split('=')[0] in repl else l for l in lines) + '\n')   # server paths replaced (a key defined twice is refused)
        self.ran(self.run_script('backup-quotidien.sh', st))
        self.ran(self.run_script('backup-quotidien.sh', self.conf('s2.conf', '/opt/time-billing-v9-staging', project='time-billing-v9-staging',
                                                                container='time-billing-v9-staging', image='time-billing-v9-staging-time-billing-v9-staging', url='http://127.0.0.1:8092')))

    # --- exception liée aux empreintes -------------------------------------------------------------------------------------------------------------
    def test_approved_scripts_run_without_confirm_prod_and_say_so(self):
        self.approve()
        r = self.run_script('backup-quotidien.sh', self.prod); self.ran(r)
        self.assertIn('exception « sauvegarde »', r.stdout + r.stderr)
        db = os.path.join(self.backups, 'quotidiennes'); files = [f for f in os.listdir(db) if f.startswith('timebilling-') and f.endswith('.db')]
        self.assertEqual(len(files), 1); self.assertEqual(stat.S_IMODE(os.stat(os.path.join(db, files[0])).st_mode), 0o600)
        self.assertTrue(os.path.isfile(os.path.join(db, 'SHA256SUMS')))
        sample = os.path.join(self.td, 'sample.db'); sqlite3.connect(sample).close()
        self.ran(self.run_script('verifier-sauvegarde.sh', self.prod, sample))

    def test_the_exception_is_independent_of_the_directory_where_the_approved_copy_lives(self):
        self.approve()
        other = os.path.join(self.td, 'opt-proc'); shutil.copytree(self.proc, other)                         # the documented cron path was a different directory
        self.ran(self.run_script('backup-quotidien.sh', self.prod, proc=other))

    def test_a_modified_script_loses_the_exception(self):
        self.approve()
        marker = os.path.join(self.td, 'MARKER')
        with open(os.path.join(self.proc, 'backup-quotidien.sh'), 'a') as f: f.write(f'\ntouch {marker}\n')
        self.blocked(self.run_script('backup-quotidien.sh', self.prod)); self.assertFalse(os.path.exists(marker))

    def test_a_replaced_script_with_the_approved_name_is_refused(self):
        self.approve()
        with open(os.path.join(self.proc, 'backup-quotidien.sh'), 'w') as f:
            f.write('#!/bin/bash\n. "$(dirname "$0")/tb-common.sh"\necho PWNED\n')
        r = self.run_script('backup-quotidien.sh', self.prod); self.blocked(r); self.assertNotIn('PWNED', r.stdout)

    def test_a_modified_guard_loses_the_exception_too(self):
        self.approve()
        with open(os.path.join(self.proc, 'tb-common.sh'), 'a') as f: f.write('\n# modification non approuvée\n')
        self.blocked(self.run_script('backup-quotidien.sh', self.prod))

    def test_the_approved_name_is_not_enough_without_the_matching_hash(self):
        self.approve()
        with open(self.approvals) as f: lines = f.read().splitlines()
        for variant, content in {'wrong hash': [re.sub(r'^[0-9a-f]{64}', '0' * 64, l) if 'backup-quotidien' in l else l for l in lines],
                                 'missing script': [l for l in lines if 'backup-quotidien' not in l], 'missing guard': [l for l in lines if 'tb-common' not in l],
                                 'duplicate line': lines + [lines[0]], 'uppercase hash': [l.upper() if 'backup-quotidien' in l else l for l in lines],
                                 'empty file': []}.items():
            with self.subTest(variant):
                with open(self.approvals, 'w') as f: f.write('\n'.join(content) + '\n')
                os.chmod(self.approvals, 0o644); self.blocked(self.run_script('backup-quotidien.sh', self.prod))

    def test_the_other_script_name_does_not_inherit_the_approval(self):
        self.approve(); alt = os.path.join(self.proc, 'copie.sh'); shutil.copy(os.path.join(self.proc, 'backup-quotidien.sh'), alt)
        self.blocked(self.run_script('copie.sh', self.prod))

    # --- fichier d'approbation de confiance ---------------------------------------------------------------------------------------------------------
    def test_untrusted_approvals_file_is_ignored(self):
        for label, prep in {'group writable file': lambda: os.chmod(self.approvals, 0o664), 'world writable file': lambda: os.chmod(self.approvals, 0o666),
                            'world writable directory': lambda: os.chmod(self.etc, 0o777), 'group writable directory': lambda: os.chmod(self.etc, 0o775),
                            'file owned by another user': lambda: os.chown(self.approvals, 12345, 12345),
                            'directory owned by another user': lambda: os.chown(self.etc, 12345, 12345),
                            'file is a symlink': self._symlink_approvals}.items():
            with self.subTest(label):
                os.chmod(self.etc, 0o755); os.chown(self.etc, 0, 0)
                if os.path.lexists(self.approvals): os.remove(self.approvals)
                self.approve(); prep()
                self.blocked(self.run_script('backup-quotidien.sh', self.prod))

    def _symlink_approvals(self):
        real = os.path.join(self.td, 'real-approvals'); os.replace(self.approvals, real); os.symlink(real, self.approvals)


    # --- voies de contournement (revue adverse, mission de validation technique) -------------------------------------------------------------------
    def test_a_poisoned_path_cannot_fake_the_hash_or_ownership_checks(self):
        """Un `sha256sum` / `stat` placé en tête du PATH ne doit pas pouvoir faire passer un script modifié."""
        self.approve()
        with open(os.path.join(self.proc, 'backup-quotidien.sh'), 'a') as f: f.write('\n# modifié après approbation\n')
        want = {l.split()[1]: l.split()[0] for l in open(self.approvals).read().splitlines()}
        fake = os.path.join(self.bin, 'sha256sum')
        with open(fake, 'w') as f: f.write('#!/bin/bash\nfor a in "$@"; do case "$a" in *backup-quotidien.sh) echo "%s  $a"; exit 0;; esac; done\nexec /usr/bin/sha256sum "$@"\n' % want['backup-quotidien.sh'])
        os.chmod(fake, 0o755)
        self.blocked(self.run_script('backup-quotidien.sh', self.prod))

    def test_a_writable_ancestor_directory_loses_the_exception(self):
        """Le dossier des scripts est root-only mais un ancêtre modifiable par d'autres permettrait de le remplacer : exception refusée."""
        self.approve(); parent = os.path.join(self.td, 'parent'); os.makedirs(parent, mode=0o755)
        moved = os.path.join(parent, 'proc'); shutil.copytree(self.proc, moved)
        for n in os.listdir(moved): os.chmod(os.path.join(moved, n), 0o755)
        os.chmod(parent, 0o777)
        self.blocked(self.run_script('backup-quotidien.sh', self.prod, proc=moved))
        os.chmod(parent, 0o755); self.reset_calls()
        self.ran(self.run_script('backup-quotidien.sh', self.prod, proc=moved))                                 # contrôle positif : même copie, ancêtre sain

    def test_scripts_writable_by_others_lose_the_exception(self):
        self.approve(); path = os.path.join(self.proc, 'backup-quotidien.sh')
        os.chmod(path, 0o757); self.blocked(self.run_script('backup-quotidien.sh', self.prod))
        os.chmod(path, 0o755); os.chmod(self.proc, 0o777); self.blocked(self.run_script('backup-quotidien.sh', self.prod))
        os.chmod(self.proc, 0o755); os.chown(path, 12345, 12345); self.blocked(self.run_script('backup-quotidien.sh', self.prod))

    # --- nettoyage -----------------------------------------------------------------------------------------------------------------------------------
    def test_failure_cleans_the_temporary_file_and_leaves_no_backup(self):
        self.approve()
        r = self.run_script('backup-quotidien.sh', self.prod, env={'FAKE_DOCKER_FAIL': 'python'})
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(any('rm -f /data/.backup-auto.db' in c for c in self.calls()), self.calls())       # temp file of the production volume removed on failure
        db = os.path.join(self.backups, 'quotidiennes')
        self.assertEqual([f for f in os.listdir(db) if f.endswith('.db')], [])

    def test_success_removes_the_temporary_file_and_keeps_the_verified_backup(self):
        self.approve(); self.ran(self.run_script('backup-quotidien.sh', self.prod))
        self.assertTrue(any('rm -f /data/.backup-auto.db' in c for c in self.calls()))
        self.assertEqual(len([f for f in os.listdir(os.path.join(self.backups, 'quotidiennes')) if f.endswith('.db')]), 1)

    # --- outil d'approbation ----------------------------------------------------------------------------------------------------------------------
    def installer(self, *args, env=None):
        e = dict(os.environ); e.pop('CONFIRM_SAUVEGARDE', None); e.update(env or {})
        return subprocess.run(['bash', os.path.join(self.proc, 'approuver-sauvegarde.sh'), *args], capture_output=True, text=True, env=e, cwd=self.td), self.approvals

    def test_installer_is_a_simulation_by_default_and_needs_the_dated_confirmation(self):
        r, target = self.installer(); self.assertEqual(r.returncode, 0, r.stderr); self.assertFalse(os.path.exists(target)); self.assertIn('Simulation', r.stdout)
        for env in ({}, {'CONFIRM_SAUVEGARDE': 'OUI-20200101'}, {'CONFIRM_SAUVEGARDE': 'OUI'}):
            r, target = self.installer('--ecrire', env=env); self.assertNotEqual(r.returncode, 0); self.assertFalse(os.path.exists(target))

    def test_installer_writes_a_trusted_file_that_activates_exactly_the_approved_content(self):
        r, target = self.installer('--ecrire', env={'CONFIRM_SAUVEGARDE': f'OUI-{today()}'}); self.assertEqual(r.returncode, 0, r.stderr)
        st = os.stat(target); self.assertEqual((st.st_uid, stat.S_IMODE(st.st_mode)), (0, 0o644)); self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(target)).st_mode), 0o755)
        with open(target) as f: self.assertEqual(sorted(l.split()[1] for l in f.read().splitlines()), sorted(NAMES))
        self.approvals = target
        self.ran(self.run_script('backup-quotidien.sh', self.prod))                                         # end to end: the guard accepts what the installer wrote
        with open(os.path.join(self.proc, 'verifier-sauvegarde.sh'), 'a') as f: f.write('\n# changed after approval\n')
        self.reset_calls()
        self.blocked(self.run_script('verifier-sauvegarde.sh', self.prod, os.path.join(self.td, 'x.db')))

    def test_installer_refuses_a_writable_ancestor_of_the_scripts_directory(self):
        parent = os.path.join(self.td, 'p2'); os.makedirs(parent, mode=0o755); moved = os.path.join(parent, 'proc'); shutil.copytree(self.proc, moved); os.chmod(parent, 0o777)
        e = dict(os.environ, CONFIRM_SAUVEGARDE=f'OUI-{today()}')
        r = subprocess.run(['bash', os.path.join(moved, 'approuver-sauvegarde.sh'), '--ecrire'], capture_output=True, text=True, env=e, cwd=self.td)
        self.assertNotEqual(r.returncode, 0); self.assertFalse(os.path.exists(self.approvals))

    def test_installer_refuses_untrustworthy_inputs(self):
        env = {'CONFIRM_SAUVEGARDE': f'OUI-{today()}'}
        os.chmod(os.path.join(self.proc, 'backup-quotidien.sh'), 0o775)
        r, target = self.installer('--ecrire', env=env); self.assertNotEqual(r.returncode, 0); self.assertFalse(os.path.exists(target))
        os.chmod(os.path.join(self.proc, 'backup-quotidien.sh'), 0o755)
        os.chmod(self.etc, 0o777)
        r, target = self.installer('--ecrire', env=env); self.assertNotEqual(r.returncode, 0); self.assertFalse(os.path.exists(target))

    # --- non-régression -----------------------------------------------------------------------------------------------------------------------------
    def test_every_procedure_script_still_parses(self):
        for n in sorted(f for f in os.listdir(PROC) if f.endswith('.sh')):
            with self.subTest(n): self.assertEqual(subprocess.run(['bash', '-n', os.path.join(PROC, n)], capture_output=True).returncode, 0)

    def test_the_documented_cron_example_uses_existing_script_names_and_a_real_directory(self):
        with open(os.path.join(PROC, 'cron-sauvegarde.example')) as f: lines = [l for l in f.read().splitlines() if l and not l.startswith('#') and not l.startswith('PATH')]
        self.assertEqual(len(lines), 2)
        for l in lines:
            self.assertNotIn('/opt/time-billing-v9/procedure', l)
            script = re.search(r'/procedure/([a-z-]+\.sh)', l).group(1); self.assertTrue(os.path.isfile(os.path.join(PROC, script)), script)
            self.assertIn(script, ('backup-quotidien.sh', 'verifier-sauvegarde.sh'))


if __name__ == '__main__':
    unittest.main()
