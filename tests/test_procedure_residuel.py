"""rc25 — failles RÉSIDUELLES de la garde actuelle (procedure/*.sh), consignées en `expectedFailure` : le comportement SOUHAITÉ y est affirmé, il n'est pas atteint
aujourd'hui, et ces tests ne doivent pas être supprimés pour obtenir une suite verte (voir CONCEPTION-GARDE-CONFIANCE-RC25.md pour l'architecture qui les corrigerait).
Les tests non marqués constatent des faits (ils passent) : environnement d'exécution, absence de docker, chargement de la garde.

Dossier temporaire, faux docker, aucune base, aucun /etc /opt /root réel. Exécutés en root seulement.
"""
import os, shutil, subprocess, tempfile, time, unittest

from tests.test_procedure_guard import Base, PROC, today

HOSTILE_SO = r'''#include <stdio.h>
#include <stdlib.h>
__attribute__((constructor)) static void init(void){ const char*m=getenv("MK"); if(!m) return; FILE*f=fopen(m,"a"); if(f){fputs("preload\n",f); fclose(f);} }
'''

BLOCKING_DOCKER = r'''#!/bin/bash
echo "docker $*" >> "$FAKE_DOCKER_LOG"
case "$1" in
  exec) shift
    case "$*" in
      *" rm -f "*) exit 0 ;;
      *python*) cat >/dev/null; : > "$GATE_STARTED"; for _ in $(seq 1 100); do [ -e "$GATE_GO" ] && break; sleep 0.1; done; exit 0 ;;
    esac ;;
  cp) python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('create table if not exists t(x)'); c.commit()" "$3"; exit 0 ;;
esac
exit 0
'''


@unittest.skipUnless(os.geteuid() == 0, 'la garde exige des fichiers appartenant à root : tests exécutés en root seulement')
class Residual(Base):
    def marker(self): return os.path.join(self.td, 'MARKER')

    def hostile_so(self):
        if not shutil.which('gcc'): self.skipTest('gcc absent : LD_PRELOAD non testable ici')
        src = os.path.join(self.td, 'pre.c'); so = os.path.join(self.td, 'pre.so'); open(src, 'w').write(HOSTILE_SO)
        subprocess.run(['gcc', '-shared', '-fPIC', '-o', so, src], check=True); return so

    def run_raw(self, argv, env):
        e = dict(os.environ, PATH=self.bin + ':' + os.environ['PATH'], FAKE_DOCKER_LOG=self.log); e.pop('CONFIRM_PROD', None); e.update(env)
        return subprocess.run(argv, capture_output=True, text=True, env=e, cwd=self.td)

    # ---- faits constatés (passent) -----------------------------------------------------------------------------------------------------------------
    def test_fact_ps4_command_substitution_from_the_environment_is_not_executed_by_this_bash(self):
        """Garde-fou de version : sur ce bash, un PS4 hostile importé de l'environnement n'est pas évalué (même hors -p). Si une autre version l'évalue, ce test casse."""
        r = self.run_raw(['bash', os.path.join(self.proc, '20-backup.sh'), self.prod],
                         {'SHELLOPTS': 'xtrace', 'PS4': f'$(touch "{self.marker()}")+ ', 'CONFIRM_PROD': f'OUI-{today()}'})
        self.assertFalse(os.path.exists(self.marker()), f'bash {subprocess.run(["bash", "--version"], capture_output=True, text=True).stdout.splitlines()[0]} évalue PS4 : {r.stderr[:200]}')

    def test_fact_dash_p_and_env_i_ignore_shellopts_but_plain_bash_traces_every_command(self):
        plain = self.run_raw(['bash', os.path.join(self.proc, 'backup-quotidien.sh'), self.prod], {'SHELLOPTS': 'xtrace', 'CONFIRM_PROD': f'OUI-{today()}'})
        self.assertIn('\n+ ', '\n' + plain.stderr, 'hors -p, SHELLOPTS=xtrace active la trace des commandes (qui peut contenir des valeurs sensibles)')
        for argv in (['bash', '-p'], ['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', 'bash']):
            r = self.run_raw(argv + [os.path.join(self.proc, 'backup-quotidien.sh'), self.prod], {'SHELLOPTS': 'xtrace', 'CONFIRM_PROD': f'OUI-{today()}'}) if argv[0] == 'bash' else \
                subprocess.run(argv + [os.path.join(self.proc, 'backup-quotidien.sh'), self.prod], capture_output=True, text=True, env={'SHELLOPTS': 'xtrace'}, cwd=self.td)
            self.assertNotIn('\n+ ', '\n' + r.stderr, argv)

    def test_fact_docker_absent_stops_the_backup_cleanly(self):
        nodocker = os.path.join(self.td, 'bin-sans-docker'); os.makedirs(nodocker)
        for d in ('/usr/bin', '/bin'):
            for n in os.listdir(d):
                if n != 'docker' and not os.path.exists(os.path.join(nodocker, n)): os.symlink(os.path.join(d, n), os.path.join(nodocker, n))
        r = subprocess.run(['bash', '-p', os.path.join(self.proc, 'backup-quotidien.sh'), self.prod], capture_output=True, text=True, cwd=self.td,
                           env={'PATH': nodocker, 'CONFIRM_PROD': f'OUI-{today()}', 'FAKE_DOCKER_LOG': self.log})
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        db = os.path.join(self.backups, 'quotidiennes')
        self.assertEqual([f for f in (os.listdir(db) if os.path.isdir(db) else []) if f.endswith('.db')], [], 'aucune sauvegarde partielle ne doit rester')

    def test_fact_missing_reader_or_guard_file_stops_every_entry_point(self):
        for missing in ('lire-conf.sh', 'tb-common.sh'):
            d = os.path.join(self.td, 'sans-' + missing); shutil.copytree(self.proc, d); os.remove(os.path.join(d, missing))
            for script in ('20-backup.sh', 'backup-quotidien.sh', '90-rollback.sh'):
                with self.subTest(f'{script} sans {missing}'):
                    self.reset_calls(); r = self.run_script(script, self.prod, proc=d, env={'CONFIRM_PROD': f'OUI-{today()}'})
                    self.assertNotEqual(r.returncode, 0); self.assertEqual(self.calls(), [])

    def test_fact_ld_preload_runs_in_a_plain_bash_script_and_in_env_before_env_i_clears_it(self):
        so = self.hostile_so(); mk = self.marker()
        script = os.path.join(self.td, 's.sh'); open(script, 'w').write('#!/bin/bash\n:\n')
        for argv in (['bash', script], ['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', '/bin/bash', '-p', script]):
            if os.path.exists(mk): os.remove(mk)
            subprocess.run(argv, env=dict(os.environ, LD_PRELOAD=so, MK=mk), capture_output=True)
            self.assertTrue(os.path.exists(mk), f'{argv[:3]} : le code préchargé s\'est exécuté (limite démontrée du lancement par shell/env)')

    # ---- défauts résiduels : comportement souhaité affirmé, non atteint (expectedFailure) ----------------------------------------------------------------
    def test_shellopts_in_the_environment_is_refused_before_any_command(self):
        """Corrigé : le contrôle d'environnement refuse aussi SHELLOPTS (avant : accepté, et la trace xtrace exposait chaque commande développée sur stderr)."""
        r = self.run_raw(['bash', os.path.join(self.proc, 'backup-quotidien.sh'), self.prod], {'SHELLOPTS': 'xtrace', 'CONFIRM_PROD': f'OUI-{today()}'})
        self.assertNotEqual(r.returncode, 0, 'SHELLOPTS accepté'); self.assertEqual(self.calls(), [])

    @unittest.expectedFailure
    def test_RESIDUAL_ld_preload_in_the_callers_environment_should_never_execute(self):
        so = self.hostile_so()
        self.run_raw(['bash', os.path.join(self.proc, '20-backup.sh'), self.prod], {'LD_PRELOAD': so, 'MK': self.marker()})
        self.assertFalse(os.path.exists(self.marker()), 'LD_PRELOAD exécuté avant toute instruction du script')

    @unittest.expectedFailure
    def test_RESIDUAL_the_documented_env_i_bash_p_launch_should_stop_ld_preload(self):
        """SOUHAITÉ : la commande documentée dans l'exemple cron neutralise LD_PRELOAD. ACTUEL : `env` (dynamique) charge la bibliothèque avant d'effacer l'environnement."""
        so = self.hostile_so()
        self.run_raw(['/usr/bin/env', '-i', 'PATH=/usr/sbin:/usr/bin:/sbin:/bin', '/bin/bash', '-p', os.path.join(self.proc, '20-backup.sh'), self.prod], {'LD_PRELOAD': so, 'MK': self.marker()})
        self.assertFalse(os.path.exists(self.marker()))

    @unittest.expectedFailure
    def test_RESIDUAL_a_script_replaced_after_the_hash_check_should_not_run_the_new_content(self):
        """TOCTOU : le hachage est vérifié par tb-common.sh puis bash continue de lire le script au fil de l'eau. Un racer pouvant écrire dans le dossier (root ou
        défaillance de droits) ajoute une ligne après la vérification : elle s'exécute. SOUHAITÉ : aucune ligne ajoutée après vérification ne s'exécute (instantané)."""
        self.approve()
        dock = os.path.join(self.bin, 'docker'); open(dock, 'w').write(BLOCKING_DOCKER); os.chmod(dock, 0o755)
        started, go = os.path.join(self.td, 'started'), os.path.join(self.td, 'go')
        script = os.path.join(self.proc, 'backup-quotidien.sh')
        p = subprocess.Popen(['bash', '-p', script, self.prod], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.td,
                             env=dict(os.environ, PATH=self.bin + ':' + os.environ['PATH'], FAKE_DOCKER_LOG=self.log, GATE_STARTED=started, GATE_GO=go))
        for _ in range(100):
            if os.path.exists(started): break
            time.sleep(0.1)
        else: p.kill(); self.fail('le script n\'est pas arrivé à l\'étape docker')
        with open(script, 'a') as f: f.write(f'\ntouch "{self.marker()}"\n')                                        # modification APRÈS la vérification
        open(go, 'w').close(); p.communicate(timeout=60)
        self.assertFalse(os.path.exists(self.marker()), 'la ligne ajoutée après la vérification a été exécutée')


if __name__ == '__main__':
    unittest.main()
