"""rc25 — garde-fous de tests/recette_fonctionnelle/run_clone_recette.sh (aucun docker, aucune base : seulement le refus des mauvaises cibles).
Le comportement complet du script n'est validé qu'en simulation locale (faux docker, base synthétique, hors dépôt) : voir RUNBOOK-CLONE-ISOLE-RC25.md §0 bis."""
import os, subprocess, unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tests', 'recette_fonctionnelle', 'run_clone_recette.sh')


def run(*args, **env):
    e = {'PATH': '/usr/bin:/bin', 'HOME': '/tmp'}; e.update(env)
    return subprocess.run(['bash', SCRIPT, *args], capture_output=True, text=True, env=e)


class CloneScriptGuards(unittest.TestCase):
    def test_staging_and_production_targets_are_refused_even_in_simulation_mode(self):
        for kw in ({'C': '/opt/time-billing-v9-staging'}, {'N': 'time-billing-v9-staging'}, {'C': '/opt/time-billing-v9'}, {'N': 'time-billing-v9'}):
            for sim in ({}, {'TB_SIM': '1'}):
                with self.subTest(kw=kw, sim=sim):
                    r = run('check', **kw, **sim); self.assertEqual(r.returncode, 1); self.assertIn('cible interdite', r.stderr)

    def test_any_other_target_is_refused_without_the_simulation_flag(self):
        r = run('check', C='/tmp/autre-dossier'); self.assertEqual(r.returncode, 1); self.assertIn('cible différente du clone isolé', r.stderr)
        r = run('check', P='8092'); self.assertEqual(r.returncode, 1); self.assertIn('cible différente du clone isolé', r.stderr)

    def test_unknown_command_and_missing_command_do_nothing(self):
        self.assertNotEqual(run().returncode, 0)
        r = run('detruire', TB_SIM='1', C='/tmp/rc25-test-inexistant'); self.assertNotEqual(r.returncode, 0)

    def test_the_script_never_runs_apply_or_import_tools(self):
        code = [l for l in open(SCRIPT).read().splitlines() if l.strip() and not l.lstrip().startswith('#') and 'bloque ' not in l]
        for forbidden in ('mandats_appliquer', 'appliquer_emetteur', 'charger_factures_historiques', 'aller_retour_formulaires', 'reporter_notes_a01', '--apply'):
            self.assertEqual([l for l in code if forbidden in l], [], forbidden)


if __name__ == '__main__':
    unittest.main()
