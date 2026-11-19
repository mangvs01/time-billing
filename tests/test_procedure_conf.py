"""rc25 — la configuration (prod.conf / staging.conf) n'est JAMAIS exécutée : elle est lue comme des données (procedure/lire-conf.sh), validée ligne à ligne,
avant toute garde. Tests adverses : conf piégée, clés inconnues, doublons, fonctions shell exportées, PATH piégé, variable d'environnement TB_APPROVALS_FILE.

Même principe que test_procedure_guard : dossier temporaire, FAUX docker, aucun /opt ni /etc réel ; exécutés en root seulement (la garde contrôle la propriété root).
"""
import os, shutil, subprocess, unittest

from tests.test_procedure_guard import Base, PROC, today

KEYS = ('ROOT', 'PROJECT', 'CONTAINER', 'IMAGE', 'URL', 'BACKUP_BASE', 'SOURCE_APP', 'SOURCE_REQ', 'RC_IMAGE', 'COMPOSE_TEMPLATE')

HOSTILE_LINES = {
    'commande': 'touch {m}',
    'substitution $()': 'ROOT=$(touch {m})',
    'substitution ``': 'PROJECT=`touch {m}`',
    'point-virgule': 'URL=http://127.0.0.1:8091; touch {m}',
    'et commercial': 'IMAGE=x & touch {m}',
    'pipe': 'CONTAINER=x | touch {m}',
    'expansion ${}': 'SOURCE_APP=${{x:=$(touch {m})}}',
    'guillemets': 'RC_IMAGE="$(touch {m})"',
    'apostrophes': "RC_IMAGE='x'",
    'export': 'export ROOT=/opt/time-billing-v9',
    'source': '. {m}.sh',
    'fonction': 'f() {{ touch {m}; }}; f',
    'espace dans la valeur': 'BACKUP_BASE=/a b',
    'glob': 'BACKUP_BASE=/tmp/*',
    'retour chariot (CRLF)': 'ROOT=/opt/time-billing-v9\r',
    'clé inconnue PATH': 'PATH=/tmp/evil',
    'clé inconnue BASH_ENV': 'BASH_ENV={m}.sh',
    'clé inconnue CONFIRM_PROD': 'CONFIRM_PROD=OUI-{d}',
    'clé inconnue TB_APPROVALS_FILE': 'TB_APPROVALS_FILE=/tmp/approved',
    'clé inconnue LD_PRELOAD': 'LD_PRELOAD=/tmp/x.so',
    'clé en minuscules': 'root=/opt/time-billing-v9',
    'doublon': 'ROOT=/opt/time-billing-v9-staging',
}


class ConfNeverExecuted(Base):
    def conf_text(self, extra=(), drop=()):
        lines = [l for l in open(self.prod).read().splitlines() if l.split('=')[0] not in drop]
        return '\n'.join(lines + list(extra)) + '\n'

    def write_conf(self, name, text):
        p = os.path.join(self.td, name)
        with open(p, 'w', newline='') as f: f.write(text)
        return p

    def marker(self): return os.path.join(self.td, 'MARKER')

    def not_executed(self, r, what):
        self.assertFalse(os.path.exists(self.marker()), f'{what} : la configuration a été EXÉCUTÉE ({r.stdout}{r.stderr})')
        self.assertNotEqual(r.returncode, 0, f'{what} : {r.stdout}{r.stderr}')
        self.assertEqual(self.calls(), [], f'{what} : aucun appel docker avant le refus')

    # --- 1. une configuration piégée n'est jamais exécutée, quelle que soit la forme du piège, avant ET après la garde ----------------------------------
    def test_a_hostile_conf_line_is_refused_and_never_run(self):
        self.approve()                                                             # même avec l'exception « sauvegarde » valide
        for label, tpl in HOSTILE_LINES.items():
            with self.subTest(label):
                if os.path.exists(self.marker()): os.remove(self.marker())
                with open(self.marker() + '.sh', 'w') as f: f.write(f'touch {self.marker()}\n')       # charge utile du cas « source » : ne doit pas s'exécuter non plus
                line = tpl.format(m=self.marker(), d=today())
                conf = self.write_conf('hostile.conf', self.conf_text(extra=[line]))
                for script in ('20-backup.sh', 'backup-quotidien.sh'):
                    self.not_executed(self.run_script(script, conf, env={'CONFIRM_PROD': f'OUI-{today()}'}), f'{script} + {label} (CONFIRM_PROD valide)')
                    self.not_executed(self.run_script(script, conf), f'{script} + {label}')

    def test_a_trapped_conf_that_would_have_run_before_the_guard_in_every_entry_script(self):
        conf = self.write_conf('trap.conf', self.conf_text(extra=[f'touch {self.marker()}']))
        for script in ('20-backup.sh', '40-deploy.sh', '90-rollback.sh', 'backup-quotidien.sh', 'verifier-sauvegarde.sh'):
            with self.subTest(script):
                r = self.run_script(script, conf, os.path.join(self.td, 'x.db')); self.not_executed(r, script)

    def test_missing_key_or_empty_file_is_refused(self):
        for label, text in {'fichier vide': '', 'seulement des commentaires': '# rien\n\n'}.items():
            with self.subTest(label): self.not_executed(self.run_script('20-backup.sh', self.write_conf('e.conf', text), env={'CONFIRM_PROD': f'OUI-{today()}'}), label)
        for k in KEYS:
            with self.subTest('sans ' + k):
                self.not_executed(self.run_script('20-backup.sh', self.write_conf('m.conf', self.conf_text(drop=(k,))), env={'CONFIRM_PROD': f'OUI-{today()}'}), 'sans ' + k)

    def test_variables_of_the_environment_cannot_replace_a_missing_conf_key(self):
        conf = self.write_conf('m.conf', self.conf_text(drop=('CONTAINER',)))
        self.not_executed(self.run_script('20-backup.sh', conf, env={'CONTAINER': 'time-billing-v9-staging', 'CONFIRM_PROD': f'OUI-{today()}'}), 'CONTAINER hérité')

    def test_a_conf_that_names_production_by_any_identifier_is_still_guarded(self):
        for k, v in (('PROJECT', 'time-billing-v9'), ('CONTAINER', 'time-billing-v9'), ('URL', 'http://127.0.0.1:8091')):
            with self.subTest(k):
                lines = [l for l in open(self.conf('s.conf', root='/opt/time-billing-v9-staging', project='time-billing-v9-staging', container='time-billing-v9-staging',
                                                   image='time-billing-v9-staging-x', url='http://127.0.0.1:8092')).read().splitlines() if not l.startswith(k + '=')]
                conf = self.write_conf('mixed.conf', '\n'.join(lines + [f'{k}={v}']) + '\n'); self.blocked(self.run_script('20-backup.sh', conf)); self.reset_calls()

    def test_comments_blank_lines_and_the_repository_confs_are_accepted(self):
        for name in ('prod.conf', 'staging.conf'):
            with self.subTest(name):
                got = subprocess.run(['bash', '-c', f'. "{PROC}/lire-conf.sh"; lire_conf "{PROC}/{name}" X_ && for k in {" ".join(KEYS)}; do v=X_$k; printf "%s=%s\\n" "$k" "${{!v}}"; done'],
                                     capture_output=True, text=True)
                self.assertEqual(got.returncode, 0, got.stderr)
                ref = subprocess.run(['bash', '-c', f'. "{PROC}/{name}"; for k in {" ".join(KEYS)}; do printf "%s=%s\\n" "$k" "${{!k}}"; done'], capture_output=True, text=True)
                self.assertEqual(got.stdout, ref.stdout)                          # la lecture « données » donne les mêmes valeurs que l'ancienne exécution de la conf
                self.assertIn('ROOT=/opt/', got.stdout)
        self.approve()
        ok = self.write_conf('ok.conf', '# commentaire avec $(rien) et `rien`\n\n  # indenté\n' + self.conf_text())
        self.ran(self.run_script('backup-quotidien.sh', ok))

    # --- 2. les deux autres lecteurs de conf (prérequis, promotion) --------------------------------------------------------------------------------
    def test_prerequisite_checker_does_not_execute_confs(self):
        trap = self.write_conf('trap.conf', self.conf_text(extra=[f'touch {self.marker()}']))
        good = self.conf('good.conf', root='/opt/time-billing-v9-staging', project='time-billing-v9-staging', container='time-billing-v9-staging', image='x', url='http://127.0.0.1:8092')
        for order in ((trap, good), (good, trap)):
            r = subprocess.run(['timeout', '60', 'bash', os.path.join(self.proc, '00-prerequis-bascule.sh'), *order], capture_output=True, text=True,
                               env=dict(os.environ, PATH=self.bin + ':' + os.environ['PATH']), cwd=self.td)
            self.assertFalse(os.path.exists(self.marker()), f'00-prerequis a exécuté la conf : {r.stdout}{r.stderr}'); self.assertNotEqual(r.returncode, 0)

    def test_promotion_script_does_not_execute_the_second_conf(self):
        trap = self.write_conf('trap.conf', self.conf_text(extra=[f'touch {self.marker()}']))
        target = self.conf('t.conf', root='/opt/time-billing-v9-test', project='tbtest', container='tbtest', image='tbtest-x', url='http://127.0.0.1:8099')
        r = self.run_script('70-promouvoir-base-staging.sh', target, trap, env={'PROMOUVOIR': 'OUI'})
        self.assertFalse(os.path.exists(self.marker()), f'70 a exécuté la conf : {r.stdout}{r.stderr}'); self.assertNotEqual(r.returncode, 0)

    # --- 3. fonctions shell exportées et PATH piégé ne peuvent pas fausser la garde ---------------------------------------------------------------
    def test_exported_shell_functions_are_refused(self):
        for fn in ('readlink', 'date', 'stat', 'sha256sum', 'awk', 'dirname', 'basename', 'cut', 'sed', 'printf', 'test'):
            with self.subTest(fn):
                r = subprocess.run(['bash', '-c', f'{fn}() {{ echo 20991231; }}; export -f {fn}; exec bash "$0" "$1"', os.path.join(self.proc, '20-backup.sh'), self.prod],
                                   capture_output=True, text=True, env=dict(os.environ, PATH=self.bin + ':' + os.environ['PATH'], FAKE_DOCKER_LOG=self.log), cwd=self.td)
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(self.calls(), [])
                if fn != 'dirname': self.assertIn('fonction', r.stdout + r.stderr)          # dirname masqué : le chargement de la garde échoue avant, et l'échec est lui aussi fatal

    def test_entry_scripts_stop_when_the_guard_cannot_be_loaded(self):
        """Avant correction, `. tb-common.sh` en échec laissait le script continuer SANS garde (docker appelé)."""
        entry = ('10-preflight.sh', '20-backup.sh', '30-rehearse.sh', '40-deploy.sh', '50-verify.sh', '60-donnees-d1-d2-a01.sh', '70-promouvoir-base-staging.sh',
                 '90-rollback.sh', 'mot-de-passe-production.sh', 'rotate-secrets.sh', 'backup-quotidien.sh', 'verifier-sauvegarde.sh')
        bare = os.path.join(self.td, 'bare'); os.makedirs(bare)
        for n in entry: shutil.copy(os.path.join(PROC, n), bare)                                  # dossier SANS tb-common.sh
        for n in entry:
            with self.subTest(n):
                self.reset_calls(); r = self.run_script(n, self.prod, os.path.join(self.td, 'x.db'), proc=bare, env={'CONFIRM_PROD': f'OUI-{today()}'})
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(self.calls(), [], n)

    def test_a_fake_readlink_or_date_in_the_path_cannot_open_the_guard(self):
        link = os.path.join(self.td, 'lnk'); os.symlink('/opt/time-billing-v9', link)
        sneaky = self.conf('sneaky.conf', root=link, project='x', container='x', image='x', url='http://127.0.0.1:9')       # production seulement via un lien symbolique
        for name, body in {'readlink': '#!/bin/bash\nfor a in "$@"; do last=$a; done; echo "$last"\n', 'date': '#!/bin/bash\necho 20991231\n'}.items():
            with self.subTest(name):
                fake = os.path.join(self.bin, name)
                with open(fake, 'w') as f: f.write(body)
                os.chmod(fake, 0o755)
                self.blocked(self.run_script('20-backup.sh', sneaky))
                self.reset_calls()
                if name == 'date': self.blocked(self.run_script('20-backup.sh', self.prod, env={'CONFIRM_PROD': 'OUI-20991231'}))
                os.remove(fake); self.reset_calls()

    # --- 4. le chemin du fichier d'approbation n'est pas pilotable par l'environnement ---------------------------------------------------------------
    def test_the_approvals_file_path_cannot_be_chosen_through_the_environment(self):
        # copie NON modifiée de la garde : le chemin /etc/time-billing/... y est une constante ; TB_APPROVALS_FILE ne doit avoir aucun effet
        raw = os.path.join(self.td, 'raw'); shutil.copytree(PROC, raw)
        for n in os.listdir(raw): os.chmod(os.path.join(raw, n), 0o755)
        with open(os.path.join(raw, 'tb-common.sh')) as f: text = f.read()
        self.assertIn('APPROVALS_FILE=/etc/time-billing/approved-scripts.sha256', text); self.assertNotIn('TB_APPROVALS_FILE', text)
        names = ('backup-quotidien.sh', 'verifier-sauvegarde.sh', 'tb-common.sh', 'lire-conf.sh')
        with open(self.approvals, 'w') as f:
            for n in names: f.write(subprocess.run(['sha256sum', os.path.join(raw, n)], capture_output=True, text=True).stdout.split()[0] + f'  {n}\n')
        os.chmod(self.approvals, 0o644)
        self.blocked(self.run_script('backup-quotidien.sh', self.prod, proc=raw, env={'TB_APPROVALS_FILE': self.approvals}))

    def test_the_exception_requires_privileged_mode_and_ignores_shadowed_commands(self):
        self.approve()
        self.blocked(self.run_script('backup-quotidien.sh', self.prod, privileged=False))                  # sans « bash -p » : fonctions / BASH_ENV hérités possibles -> pas d'exception
        self.reset_calls()
        with open(os.path.join(self.proc, 'backup-quotidien.sh'), 'a') as f: f.write('\n# modifié après approbation\n')
        want = open(self.approvals).read().split()[0]
        r = subprocess.run(['bash', '-c', f'sha256sum() {{ echo {want}  "$2"; }}; export -f sha256sum; exec bash -p "$0" "$1"', os.path.join(self.proc, 'backup-quotidien.sh'), self.prod],
                           capture_output=True, text=True, env=dict(os.environ, PATH=self.bin + ':' + os.environ['PATH'], FAKE_DOCKER_LOG=self.log), cwd=self.td)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr); self.assertEqual(self.calls(), [])        # -p n'importe pas la fonction ; le vrai sha256sum détecte la modification

    def test_symlinks_cannot_borrow_an_approval(self):
        self.approve(); evil = os.path.join(self.proc, 'evil.sh')
        with open(evil, 'w') as f: f.write('#!/bin/bash\n. "$(dirname "$0")/tb-common.sh" || exit 1\necho PWNED\n')
        os.chmod(evil, 0o755)
        link = os.path.join(self.proc, 'backup-quotidien-lien.sh'); os.symlink(evil, link)
        r = self.run_script('backup-quotidien-lien.sh', self.prod); self.blocked(r); self.assertNotIn('PWNED', r.stdout)
        os.remove(link); self.reset_calls()
        other = os.path.join(self.td, 'lien-vers-approuve'); os.makedirs(other, mode=0o755)
        for n in ('backup-quotidien.sh', 'tb-common.sh', 'lire-conf.sh'): os.symlink(os.path.join(self.proc, n), os.path.join(other, n))
        self.ran(self.run_script('backup-quotidien.sh', self.prod, proc=other))                              # un lien vers le script réellement approuvé exécute CE script (contrôle positif)

    def test_the_cron_example_starts_scripts_in_a_clean_environment(self):
        text = open(os.path.join(PROC, 'cron-sauvegarde.example')).read()
        cron = [l for l in text.splitlines() if l and not l.startswith('#') and 'root' in l and 'procedure' in l]
        self.assertEqual(len(cron), 2)
        for l in cron: self.assertIn('/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p ', l)


if __name__ == '__main__':
    unittest.main()
