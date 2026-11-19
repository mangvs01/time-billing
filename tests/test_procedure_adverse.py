"""rc25 — dernière revue adverse de la garde (aucune activation, rien hors du dossier temporaire).

1. fonctions shell exportées (dont `builtin`, `.`, `exit`) et BASH_ENV : quels points d'entrée les bloquent, lesquels exigent `env -i … bash -p` ;
2. points d'entrée : rien d'exécutable avant le chargement de la garde ; une configuration hostile n'exécute rien ;
3. installateur d'empreintes : liens symboliques, dossiers parents, cible qui est un dossier, PATH piégé, nettoyage ;
4. intégrité de la garde : protections démontrées (empreintes, propriétaire, droits) et limite connue (auto-attestation) en `expectedFailure`.

Faux `docker` journalisé, aucune base, aucun /etc /opt /root réel. Exécutés en root seulement (la garde contrôle la propriété root).
"""
import os, re, shutil, stat, subprocess, unittest

from tests.test_procedure_guard import Base, PROC, NAMES, DEFAULT_APPROVALS, today

ENTRY = ('10-preflight.sh', '20-backup.sh', '30-rehearse.sh', '40-deploy.sh', '50-verify.sh', '60-donnees-d1-d2-a01.sh', '70-promouvoir-base-staging.sh',
         '90-rollback.sh', 'mot-de-passe-production.sh', 'rotate-secrets.sh', 'backup-quotidien.sh', 'verifier-sauvegarde.sh')
ALL_ENTRY = ENTRY + ('00-prerequis-bascule.sh',)
ENV_BLOCK_LINE = re.compile(r'^\[\[ \$- == \*p\* \]\] \|\| \{ \{ \[\[ -r /proc/self/environ \]\] && _e=\$\(< /proc/self/environ\); \} 2>/dev/null && '
                            r'\[\[ \$_e != \*BASH_FUNC_\* && \$_e != \*BASH_ENV=\* && \$_e != \*SHELLOPTS=\* \]\] \|\| : "\$\{BASH_SOURCE\[999\]:\?')

# fonction piégée : si elle est APPELÉE, elle crée le témoin ; « effet » = ce qu'elle ferait pour tromper la garde
TRAPS = {
    'builtin (muette)': ('builtin', 'builtin() { touch "$MARKER"; }'),
    'readlink': ('readlink', 'readlink() { touch "$MARKER"; echo "${@: -1}"; }'),
    'date': ('date', 'date() { touch "$MARKER"; echo 20991231; }'),
    'dirname': ('dirname', 'dirname() { touch "$MARKER"; echo /nonexistent; }'),
    'stat': ('stat', 'stat() { touch "$MARKER"; echo 0; }'),
    'sha256sum': ('sha256sum', 'sha256sum() { touch "$MARKER"; echo 0000  x; }'),
    'awk': ('awk', 'awk() { touch "$MARKER"; }'),
    'cut': ('cut', 'cut() { touch "$MARKER"; }'),
    'exit (muette)': ('exit', 'exit() { touch "$MARKER"; return 0; }'),
    '. (point)': ('.', '.() { touch "$MARKER"; }'),
    'source': ('source', 'source() { touch "$MARKER"; }'),
}


@unittest.skipUnless(os.geteuid() == 0, 'la garde exige des fichiers appartenant à root : tests exécutés en root seulement')
class Adverse(Base):
    def marker(self): return os.path.join(self.td, 'MARKER')

    def run_with_functions(self, script, conf, names, privileged, extra_args=(), env=None):
        """Lance `script` depuis un bash père qui définit et EXPORTE les fonctions piégées."""
        defs = '; '.join(TRAPS[n][1] for n in names); exp = ' '.join(TRAPS[n][0] for n in names)
        flag = '-p ' if privileged else ''
        e = dict(os.environ, PATH=self.bin + ':' + os.environ['PATH'], FAKE_DOCKER_LOG=self.log, MARKER=self.marker()); e.pop('CONFIRM_PROD', None); e.update(env or {})
        return subprocess.run(['bash', '-c', f'{defs}; export -f {exp}; exec bash {flag}"$0" "$@"', os.path.join(self.proc, script), conf, *extra_args],
                              capture_output=True, text=True, env=e, cwd=self.td)

    # ---- 1. fonctions exportées ----------------------------------------------------------------------------------------------------------------------
    def test_no_exported_function_is_ever_called_and_every_entry_point_refuses_without_dash_p(self):
        sneaky = self.conf('sneaky.conf', root=os.path.join(self.td, 'lnk'), project='x', container='x', image='x', url='http://127.0.0.1:9')
        for script in ENTRY:
            for label in TRAPS:
                with self.subTest(f'{script} / {label}'):
                    if os.path.exists(self.marker()): os.remove(self.marker())
                    self.reset_calls()
                    r = self.run_with_functions(script, sneaky, [label], privileged=False, extra_args=(os.path.join(self.td, 'x.db'),))
                    self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertFalse(os.path.exists(self.marker()), f'la fonction exportée « {label} » a été APPELÉE : {r.stdout}{r.stderr}')
                    self.assertEqual(self.calls(), [], 'aucun appel docker')
                    self.assertIn('environnement non sûr', r.stdout + r.stderr)

    def test_combined_traps_that_defeated_the_previous_detection_are_refused(self):
        """Avant correction : `builtin` muette + `readlink` faisaient passer un ROOT symbolique (détection par « builtin declare -F » contournée) ; `dirname` + `exit`
        muets laissaient le script continuer SANS garde (docker exécuté)."""
        prod_like = os.path.join(self.td, 'fakeprod'); os.makedirs(prod_like); link = os.path.join(self.td, 'lnk'); os.symlink(prod_like, link)
        adv = os.path.join(self.td, 'adv'); shutil.copytree(self.proc, adv)
        for n in os.listdir(adv):
            p = os.path.join(adv, n)
            with open(p) as f: t = f.read()
            with open(p, 'w') as f: f.write(t.replace('PROD_ROOT=/opt/time-billing-v9', f'PROD_ROOT={prod_like}'))
            os.chmod(p, 0o755)
        sneaky = self.conf('sneaky2.conf', root=link, project='x', container='x', image='x', url='http://127.0.0.1:9')
        for names in (['builtin (muette)', 'readlink'], ['dirname', 'exit (muette)'], ['. (point)', 'exit (muette)'], ['source', 'dirname']):
            with self.subTest(names):
                if os.path.exists(self.marker()): os.remove(self.marker())
                self.reset_calls()
                defs = '; '.join(TRAPS[n][1] for n in names); exp = ' '.join(TRAPS[n][0] for n in names)
                e = dict(os.environ, PATH=self.bin + ':' + os.environ['PATH'], FAKE_DOCKER_LOG=self.log, MARKER=self.marker())
                r = subprocess.run(['bash', '-c', f'{defs}; export -f {exp}; exec bash "$0" "$1"', os.path.join(adv, '20-backup.sh'), sneaky], capture_output=True, text=True, env=e, cwd=self.td)
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(self.calls(), [], 'la garde a été contournée : docker appelé'); self.assertFalse(os.path.exists(self.marker()))

    def test_with_dash_p_inherited_functions_are_ignored_and_the_guard_still_decides(self):
        for label in TRAPS:
            with self.subTest(label):
                if os.path.exists(self.marker()): os.remove(self.marker())
                self.reset_calls()
                r = self.run_with_functions('20-backup.sh', self.prod, [label], privileged=True)                       # production, pas de CONFIRM_PROD
                self.assertNotEqual(r.returncode, 0); self.assertIn('PRODUCTION', r.stdout + r.stderr); self.assertEqual(self.calls(), [])
                self.assertFalse(os.path.exists(self.marker()), f'« {label} » appelée malgré -p')
                self.reset_calls()
                r = self.run_with_functions('backup-quotidien.sh', self.prod, [label], privileged=True, env={'CONFIRM_PROD': f'OUI-{today()}'})   # confirmation valide : s'exécute
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertTrue(self.calls())      # (le témoin n'est pas contrôlé ici : le faux docker, un bash non -p, importe les fonctions)

    def test_BASH_ENV_payload_runs_before_any_script_text_unless_dash_p(self):
        """LIMITE NON CORRIGEABLE DANS LE SCRIPT : bash exécute $BASH_ENV avant la première ligne. Le script refuse ensuite, mais la charge a déjà tourné ; seul `bash -p` (ou env -i) l'évite."""
        payload = os.path.join(self.td, 'benv.sh')
        with open(payload, 'w') as f: f.write(f'touch "{self.marker()}"\n')
        e = dict(os.environ, PATH=self.bin + ':' + os.environ['PATH'], FAKE_DOCKER_LOG=self.log, BASH_ENV=payload)
        r = subprocess.run(['bash', os.path.join(self.proc, '20-backup.sh'), self.prod], capture_output=True, text=True, env=e, cwd=self.td)
        self.assertNotEqual(r.returncode, 0); self.assertEqual(self.calls(), [])
        self.assertTrue(os.path.exists(self.marker()), 'la charge BASH_ENV aurait dû s\'exécuter avant le refus (limite documentée)')
        os.remove(self.marker())
        r = subprocess.run(['bash', '-p', os.path.join(self.proc, '20-backup.sh'), self.prod], capture_output=True, text=True, env=e, cwd=self.td)
        self.assertNotEqual(r.returncode, 0); self.assertIn('PRODUCTION', r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.marker()), 'avec -p, BASH_ENV est ignoré')
        r = subprocess.run(['/usr/bin/env', '-i', 'PATH=/usr/sbin:/usr/bin:/sbin:/bin', 'bash', os.path.join(self.proc, '20-backup.sh'), self.prod], capture_output=True, text=True, cwd=self.td)
        self.assertIn('PRODUCTION', r.stdout + r.stderr)                                                                   # env -i seul (sans -p) fonctionne aussi

    # ---- 2. points d'entrée -------------------------------------------------------------------------------------------------------------------------------
    def test_nothing_but_comments_and_the_environment_check_precedes_the_guard_in_every_entry_script(self):
        for script in ALL_ENTRY:
            with self.subTest(script):
                with open(os.path.join(PROC, script)) as f: lines = f.read().splitlines()
                code = [(i + 1, l) for i, l in enumerate(lines) if l.strip() and not l.lstrip().startswith('#')]
                self.assertTrue(code[0][1].startswith('#!') or True)
                first = [l for _, l in code if not l.startswith('#!')]
                if script == '00-prerequis-bascule.sh': self.assertEqual(first[0], 'set -uo pipefail'); first = first[1:]
                self.assertRegex(first[0], ENV_BLOCK_LINE); self.assertEqual(first[1], '_d=.; [[ $0 == */* ]] && _d=${0%/*}')
                self.assertRegex(first[2], r'^\. "\$_d/(tb-common|lire-conf)\.sh" \|\| : "\$\{BASH_SOURCE\[999\]:\?')
        with open(os.path.join(PROC, 'lire-conf.sh')) as f: lc = f.read()
        self.assertTrue(any(ENV_BLOCK_LINE.match(l) for l in lc.splitlines()), 'lire-conf.sh répète le contrôle d\'environnement')

    def test_every_entry_script_loads_the_guard_through_the_same_path(self):
        for script in ENTRY:
            with self.subTest(script):
                with open(os.path.join(PROC, script)) as f: t = f.read()
                self.assertEqual(t.count('tb-common.sh'), len(re.findall(r'tb-common\.sh', t)))
                self.assertIn('. "$_d/tb-common.sh"', t); self.assertNotIn('$(dirname "$0")/tb-common.sh', t)

    def test_a_hostile_conf_runs_nothing_in_any_entry_script(self):
        trap = os.path.join(self.td, 'trap.conf')
        for label, line in {'commande': f'touch {self.marker()}', 'substitution': f'ROOT=$(touch {self.marker()})', 'BASH_ENV': f'BASH_ENV={self.marker()}.sh'}.items():
            with open(self.prod) as f: base = f.read()
            with open(trap, 'w') as f: f.write(base + line + '\n')
            for script in ENTRY:
                with self.subTest(f'{script} / {label}'):
                    if os.path.exists(self.marker()): os.remove(self.marker())
                    self.reset_calls(); r = self.run_script(script, trap, os.path.join(self.td, 'x.db'), env={'CONFIRM_PROD': f'OUI-{today()}'})
                    self.assertNotEqual(r.returncode, 0); self.assertFalse(os.path.exists(self.marker())); self.assertEqual(self.calls(), [])

    def test_conf_given_as_pipe_device_or_odd_filename_is_not_executed(self):
        with open(self.prod) as f: base = f.read()
        evil = os.path.join(self.td, 'x$(touch MARKER).conf')            # relatif : le script travaille dans le dossier temporaire
        with open(evil, 'w') as f: f.write(base)
        self.reset_calls(); self.run_script('20-backup.sh', evil, env={'CONFIRM_PROD': f'OUI-{today()}'})
        self.assertFalse(os.path.exists(self.marker()), 'nom de fichier piégé exécuté')
        fifo = os.path.join(self.td, 'fifo'); os.mkfifo(fifo)
        p = subprocess.Popen(['bash', '-p', os.path.join(self.proc, '20-backup.sh'), fifo], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.td,
                             env=dict(os.environ, PATH=self.bin + ':' + os.environ['PATH'], FAKE_DOCKER_LOG=self.log, CONFIRM_PROD=f'OUI-{today()}'))
        try: out, err = p.communicate(timeout=20)
        except subprocess.TimeoutExpired: p.kill(); self.fail('un tube nommé a bloqué le lecteur de configuration')
        self.assertNotEqual(p.returncode, 0); self.assertIn('illisible', out + err)

    # ---- 3. installateur d'empreintes ------------------------------------------------------------------------------------------------------------
    def installer_copy(self, target, parent_mode=None):
        """Copie du dossier de scripts dont l'installateur vise `target` (seule différence avec le dépôt)."""
        d = os.path.join(self.td, 'instproc'); shutil.rmtree(d, ignore_errors=True); shutil.copytree(self.proc, d)
        for n in os.listdir(d):
            p = os.path.join(d, n); os.chmod(p, 0o755)
            with open(p) as f: t = f.read()
            with open(p, 'w') as f: f.write(t.replace(self.approvals, target))
        return d

    def run_installer(self, d, *args, privileged=True, env=None):
        e = dict(os.environ, CONFIRM_SAUVEGARDE=f'OUI-{today()}'); e.update(env or {})
        return subprocess.run(['bash', *(['-p'] if privileged else []), os.path.join(d, 'approuver-sauvegarde.sh'), *args], capture_output=True, text=True, env=e, cwd=self.td)

    def test_installer_refuses_when_the_target_is_a_directory_and_leaves_no_temporary_file(self):
        etc = os.path.join(self.td, 'etc2'); os.makedirs(etc, mode=0o755); os.chmod(etc, 0o755); target = os.path.join(etc, 'approved-scripts.sha256'); os.makedirs(target)
        r = self.run_installer(self.installer_copy(target), '--ecrire')
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr); self.assertNotIn('Approbation enregistrée', r.stdout)
        self.assertEqual(os.listdir(target), [], 'rien ne doit être déposé DANS le dossier cible'); self.assertEqual([f for f in os.listdir(etc) if f.startswith('.approved')], [])

    def test_installer_refuses_a_symlink_target_and_never_writes_through_it(self):
        etc = os.path.join(self.td, 'etc3'); os.makedirs(etc, mode=0o755); os.chmod(etc, 0o755); target = os.path.join(etc, 'approved-scripts.sha256')
        victim = os.path.join(self.td, 'victim'); open(victim, 'w').write('intact\n'); os.symlink(victim, target)
        r = self.run_installer(self.installer_copy(target), '--ecrire'); self.assertNotEqual(r.returncode, 0)
        self.assertEqual(open(victim).read(), 'intact\n'); self.assertEqual([f for f in os.listdir(etc) if f.startswith('.approved')], [])

    def test_installer_refuses_a_target_directory_whose_ancestor_is_writable_by_others_and_does_not_create_it(self):
        parent = os.path.join(self.td, 'open-parent'); os.makedirs(parent); os.chmod(parent, 0o777)
        target = os.path.join(parent, 'time-billing', 'approved-scripts.sha256')              # dossier « time-billing » à créer sous un parent modifiable par tous
        r = self.run_installer(self.installer_copy(target), '--ecrire'); self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.dirname(target)), 'le dossier cible ne doit pas être créé sous un parent non fiable')
        os.makedirs(os.path.join(parent, 'existing'), mode=0o755); os.chmod(os.path.join(parent, 'existing'), 0o755)
        target = os.path.join(parent, 'existing', 'approved-scripts.sha256')                    # dossier cible root-only mais parent modifiable : la garde le refuserait
        r = self.run_installer(self.installer_copy(target), '--ecrire'); self.assertNotEqual(r.returncode, 0); self.assertFalse(os.path.exists(target))

    def test_installer_creates_the_target_directory_root_only_and_writes_atomically_complete_content(self):
        parent = os.path.join(self.td, 'good-parent'); os.makedirs(parent, mode=0o755); os.chmod(parent, 0o755)
        target = os.path.join(parent, 'time-billing', 'approved-scripts.sha256')
        d = self.installer_copy(target); r = self.run_installer(d, '--ecrire'); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = os.stat(os.path.dirname(target)); self.assertEqual((st.st_uid, stat.S_IMODE(st.st_mode)), (0, 0o755))
        st = os.stat(target); self.assertEqual((st.st_uid, stat.S_IMODE(st.st_mode)), (0, 0o644))
        lines = open(target).read().splitlines(); self.assertEqual(sorted(l.split()[1] for l in lines), sorted(NAMES)); self.assertTrue(open(target).read().endswith('\n'))
        self.assertEqual([f for f in os.listdir(os.path.dirname(target)) if f.startswith('.approved')], [])
        for l in lines:
            h, n = l.split(); self.assertEqual(subprocess.run(['sha256sum', os.path.join(d, n)], capture_output=True, text=True).stdout.split()[0], h)

    def test_installer_ignores_a_poisoned_path_and_requires_dash_p(self):
        etc = os.path.join(self.td, 'etc4'); os.makedirs(etc, mode=0o755); os.chmod(etc, 0o755); target = os.path.join(etc, 'approved-scripts.sha256')
        fake = os.path.join(self.bin, 'sha256sum'); open(fake, 'w').write('#!/bin/bash\nfor a in "$@"; do case "$a" in -*) ;; *) echo "%s  $a";; esac; done\n' % ('0' * 64)); os.chmod(fake, 0o755)
        d = self.installer_copy(target)
        r = self.run_installer(d, '--ecrire', env={'PATH': self.bin + ':' + os.environ['PATH']})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('0' * 64, open(target).read(), 'un sha256sum factice du PATH a fixé les empreintes approuvées')
        os.remove(target)
        r = self.run_installer(d, '--ecrire', privileged=False, env={'BASH_FUNC_stat%%': '() { echo 0; }'}); self.assertNotEqual(r.returncode, 0); self.assertFalse(os.path.exists(target))

    def test_installer_is_a_simulation_by_default_even_as_root_and_writes_nothing(self):
        etc = os.path.join(self.td, 'etc5'); target = os.path.join(etc, 'approved-scripts.sha256')
        r = self.run_installer(self.installer_copy(target)); self.assertEqual(r.returncode, 0); self.assertFalse(os.path.exists(etc)); self.assertIn('Simulation', r.stdout)

    # ---- 4. intégrité de la garde -------------------------------------------------------------------------------------------------------------------
    def test_protection_a_changed_guard_or_reader_loses_the_exception(self):
        for name in ('tb-common.sh', 'lire-conf.sh'):
            with self.subTest(name):
                self.approve(); path = os.path.join(self.proc, name)
                with open(path) as f: original = f.read()
                with open(path, 'a') as f: f.write('\n# modification\n')
                self.reset_calls(); self.blocked(self.run_script('backup-quotidien.sh', self.prod))
                with open(path, 'w') as f: f.write(original)

    def test_protection_files_not_owned_by_root_or_writable_lose_the_exception(self):
        for name in ('tb-common.sh', 'lire-conf.sh', 'backup-quotidien.sh', 'verifier-sauvegarde.sh'):
            for label, prep, undo in (('modifiable par les autres', lambda p: os.chmod(p, 0o757), lambda p: os.chmod(p, 0o755)),
                                      ('modifiable par le groupe', lambda p: os.chmod(p, 0o775), lambda p: os.chmod(p, 0o755)),
                                      ('propriétaire non root', lambda p: os.chown(p, 12345, 12345), lambda p: os.chown(p, 0, 0))):
                with self.subTest(f'{name} {label}'):
                    self.approve(); path = os.path.join(self.proc, name); prep(path); self.reset_calls()
                    self.blocked(self.run_script('backup-quotidien.sh' if name != 'verifier-sauvegarde.sh' else 'verifier-sauvegarde.sh', self.prod, *( [os.path.join(self.td, 'x.db')] if name == 'verifier-sauvegarde.sh' else [] )))
                    undo(path)

    @unittest.expectedFailure
    def test_KNOWN_LIMIT_a_rewritten_guard_can_switch_its_own_checks_off(self):
        """LIMITE (auto-attestation) : les empreintes sont vérifiées PAR le code de tb-common.sh. Un tb-common.sh réécrit pour ne plus rien contrôler (et donc ses
        empreintes aussi) n'est pas arrêté par ses propres contrôles ; seule la propriété root + les droits de ses dossiers l'en protègent (hypothèse, pas démonstration).
        Ce test décrit le comportement SOUHAITÉ ; il échoue aujourd'hui, ce qu'`expectedFailure` consigne. Le corriger exige un vérificateur HORS du jeu de fichiers
        approuvés (choix d'architecture : décision du propriétaire)."""
        self.approve()
        path = os.path.join(self.proc, 'tb-common.sh')
        with open(path) as f: t = f.read()
        with open(path, 'w') as f: f.write(t.replace('is_production() {', 'is_production() { return 1;', 1))       # la garde se déclare « pas production »
        self.blocked(self.run_script('backup-quotidien.sh', self.prod))

    @unittest.expectedFailure
    def test_KNOWN_LIMIT_a_modified_reader_runs_its_top_level_code_before_any_hash_is_checked(self):
        """LIMITE : lire-conf.sh est « sourcé » avant la vérification des empreintes ; si on le modifie, son code s'exécute puis l'exception est refusée.
        Comportement SOUHAITÉ : aucun code d'un fichier non approuvé ne s'exécute. Même remède que ci-dessus (vérificateur extérieur)."""
        self.approve()
        with open(os.path.join(self.proc, 'lire-conf.sh'), 'a') as f: f.write(f'\ntouch "{self.marker()}"\n')
        self.run_script('backup-quotidien.sh', self.prod)
        self.assertFalse(os.path.exists(self.marker()))


if __name__ == '__main__':
    unittest.main()
