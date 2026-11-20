"""BILL-OUTIL-RELEASE : outils/preparer_release.py ne fait que PRÉPARER une version (copie figée + conf), après avoir vérifié VERSION et la suite.

Tout se passe sur un DÉPÔT FICTIF créé dans un dossier temporaire (app/app.py minimal, faux lanceur de tests, vrai procedure/lire-conf.sh copié du dépôt, et des scripts
« 10 → 50 » PIÈGES qui laisseraient une trace s'ils étaient lancés). Aucune donnée réelle, aucun réseau, aucun /opt réel, aucun Docker.
"""
import contextlib, hashlib, io, os, re, shutil, stat, subprocess, sys, tempfile, unittest, unittest.mock

from outils import preparer_release as pr

REEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent"}

CONF_PREC = """# Configuration PRODUCTION fictive
ROOT=/srv/fictif-v9
PROJECT=fictif-v9
CONTAINER=fictif-v9
IMAGE=fictif-v9-fictif-v9
URL=http://127.0.0.1:9999
BACKUP_BASE=/srv/sauvegardes
# 2026-01-01 : ancienne ligne d'historique
SOURCE_APP=/srv/versions/9.2-rc49-aaaaaaa/app
SOURCE_REQ=/srv/versions/9.2-rc49-aaaaaaa/requirements.txt
RC_IMAGE=tb-rc49:aaaaaaa
COMPOSE_TEMPLATE=/srv/modeles/docker-compose.prod.yml
# 2026-01-02 (superviseur) : rc49 = la précédente. GO propriétaire.
"""


def ecrit(chemin, texte):
    with open(chemin, "w", encoding="utf-8") as f: f.write(texte)


def lu(chemin):
    with open(chemin, encoding="utf-8") as f: return f.read()


def tests_verts(nb=3):
    return "import sys\nprint('Ran %d tests in 0.1s')\nprint()\nprint('OK (expected failures=1)')\nsys.exit(0)\n" % nb


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="test-preparer-release-"))
        self.addCleanup(self.nettoyer)
        self.depot = os.path.join(self.tmp, "depot"); os.mkdir(self.depot)
        self.sortie = os.path.join(self.tmp, "sortie")
        self.sentinelle = os.path.join(self.tmp, "SCRIPT-DE-PROCEDURE-EXECUTE")
        self.conf_prec = os.path.join(self.tmp, "prod-rc49.conf")
        ecrit(self.conf_prec, CONF_PREC)
        self.git("init", "-q", "-b", "branche-test")
        self.ecrire("app/app.py", 'import os\nVERSION="9.2-rc50"\n')
        self.ecrire("app/templates/x.html", "<p>x</p>\n"); self.ecrire("requirements.txt", "flask==1\n"); self.ecrire("Dockerfile", "FROM scratch\n")
        shutil.copy(os.path.join(REEL, "procedure", "lire-conf.sh"), self.ecrire("procedure/lire-conf.sh", ""))
        for n in ("10-preflight", "20-backup", "30-rehearse", "40-deploy", "50-verify"):
            self.ecrire("procedure/%s.sh" % n, '#!/bin/bash\ntouch "%s"\n' % self.sentinelle, mode=0o755)
        self.ecrire("outils/run_tests_parallel.py", tests_verts())
        self.sha = self.commit("v50")

    def nettoyer(self):
        for d, _, _ in os.walk(self.tmp): os.chmod(d, 0o755)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.depot] + list(args), check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()

    def ecrire(self, rel, texte, mode=None):
        p = os.path.join(self.depot, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f: f.write(texte)
        if mode: os.chmod(p, mode)
        return p

    def commit(self, msg):
        self.git("add", "-A"); self.git("commit", "-q", "-m", msg); return self.git("rev-parse", "HEAD")

    def lancer(self, sha=None, rc="rc50", extra=(), sortie=None, conf=None, avec_sortie=True):
        argv = [sha or self.sha, rc, "--depot", self.depot, "--conf-precedente", conf or self.conf_prec, "--date", "2026-11-20", "--branche", "branche-test", "--delai-tests", "60"]
        if avec_sortie: argv += ["--sortie", sortie or self.sortie]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try: code = pr.main(argv + list(extra))
            except SystemExit as e: code = e.code
        return code, out.getvalue(), err.getvalue()

    def contenu_sortie(self):
        return sorted(os.listdir(self.sortie)) if os.path.isdir(self.sortie) else []

    def somme(self, chemin):
        with open(chemin, "rb") as f: return hashlib.sha256(f.read()).hexdigest()


class CheminNominal(Base):
    def test_la_preparation_produit_la_copie_figee_la_conf_et_le_resume(self):
        avant = self.somme(self.conf_prec)
        code, out, err = self.lancer(extra=["--note", "rc50 = fictive"])
        self.assertEqual(code, 0, err + out)
        nom = "9.2-rc50-%s" % self.sha[:7]
        self.assertEqual(self.contenu_sortie(), sorted([nom, "prod-rc50.conf", "RESUME-rc50.txt", "tests-rc50.log"]))
        copie = os.path.join(self.sortie, nom)
        # copie figée = contenu exact du commit, en lecture seule (comme les copies faites à la main)
        git_fichiers = sorted(self.git("ls-tree", "-r", "--name-only", self.sha).splitlines())
        presents = sorted(os.path.relpath(os.path.join(d, f), copie) for d, _, fs in os.walk(copie) for f in fs)
        self.assertEqual(presents, git_fichiers)
        for rel in git_fichiers:
            self.assertEqual(self.somme(os.path.join(copie, rel)), hashlib.sha256(subprocess.run(["git", "-C", self.depot, "show", "%s:%s" % (self.sha, rel)], capture_output=True, env=GIT_ENV).stdout).hexdigest())
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(copie, "app", "app.py")).st_mode), 0o444)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(copie, "procedure", "20-backup.sh")).st_mode), 0o555)
        self.assertEqual(stat.S_IMODE(os.stat(copie).st_mode), 0o555)
        # conf : seules 3 valeurs changent + 1 ligne d'historique ajoutée à la fin
        nouv = lu(os.path.join(self.sortie, "prod-rc50.conf")).split("\n")
        anc = CONF_PREC.split("\n")
        self.assertEqual(len(nouv), len(anc) + 1)
        diff = [(a, n) for a, n in zip(anc[:-1], nouv) if a != n]
        self.assertEqual([n for _, n in diff], ["SOURCE_APP=%s/app" % copie, "SOURCE_REQ=%s/requirements.txt" % copie, "RC_IMAGE=tb-rc50:%s" % self.sha[:7]])
        self.assertEqual([l for l in nouv if l.startswith("ROOT=")], ["ROOT=/srv/fictif-v9"])
        histo = nouv[-2]
        self.assertTrue(histo.startswith("# 2026-11-20 (préparation par outils/preparer_release.py) : rc50 = rc50 = fictive ; git archive %s (branche branche-test). Précédente : rc49-aaaaaaa." % self.sha[:7]), histo)
        self.assertEqual(nouv[-1], "")
        # intacts : conf précédente ; rien exécuté de la procédure
        self.assertEqual(self.somme(self.conf_prec), avant)
        self.assertFalse(os.path.exists(self.sentinelle), "un script de procedure/ a été exécuté")
        resume = lu(os.path.join(self.sortie, "RESUME-rc50.txt"))
        for attendu in (self.sha, "9.2-rc50", "3 tests", "OK (expected failures=1)", copie, "aucun script de procedure/ lancé", ".env.rc50"): self.assertIn(attendu, resume)
        self.assertIn(out.strip().splitlines()[-1], resume)

    def test_la_copie_vient_du_commit_pas_de_l_arbre_de_travail(self):
        self.ecrire("app/app.py", 'VERSION="9.2-rc99"\n'); self.ecrire("fichier-non-suivi.txt", "x")      # modifications non commitées
        code, out, err = self.lancer()
        self.assertEqual(code, 0, err)
        copie = os.path.join(self.sortie, "9.2-rc50-%s" % self.sha[:7])
        self.assertIn('VERSION="9.2-rc50"', lu(os.path.join(copie, "app", "app.py")))
        self.assertFalse(os.path.exists(os.path.join(copie, "fichier-non-suivi.txt")))
        self.assertFalse(os.path.exists(os.path.join(copie, ".git")))

    def test_chemin_final_est_celui_inscrit_dans_la_conf_la_copie_reste_dans_la_sortie(self):
        code, out, err = self.lancer(extra=["--chemin-final", "/srv/releases"])
        self.assertEqual(code, 0, err)
        conf = lu(os.path.join(self.sortie, "prod-rc50.conf"))
        self.assertIn("SOURCE_APP=/srv/releases/9.2-rc50-%s/app\n" % self.sha[:7], conf)
        self.assertTrue(os.path.isdir(os.path.join(self.sortie, "9.2-rc50-%s" % self.sha[:7])))
        self.assertIn("déplacer la copie", lu(os.path.join(self.sortie, "RESUME-rc50.txt")))

    def test_les_tests_tournent_dans_une_copie_jetable_avec_un_environnement_propre(self):
        self.ecrire("outils/run_tests_parallel.py", tests_verts() .replace("import sys", "import sys, os\nprint('LANCEUR', os.path.abspath(__file__))\nprint('TMPDIR', os.environ.get('TMPDIR'))\n"
                     "for k in ('DB_PATH', 'BASE_DB', 'RC25_WORK', 'CONFIRM_PROD'): print(k, os.environ.get(k, 'absent'))"))
        sha = self.commit("lanceur bavard")
        self.ecrire("app/app.py", 'VERSION="9.2-rc51"\n'); sha = self.commit("v51")
        env = unittest.mock.patch.dict(os.environ, {"DB_PATH": "/opt/time-billing-v9/data/x.db", "BASE_DB": "/x", "RC25_WORK": "/x", "CONFIRM_PROD": "OUI-20261120"})
        env.start(); self.addCleanup(env.stop)                                   # restaure l'environnement d'origine (le lanceur isolé en dépend)
        code, out, err = self.lancer(sha=sha, rc="rc51")
        self.assertEqual(code, 0, err)
        journal = lu(os.path.join(self.sortie, "tests-rc51.log"))
        lanceur = re.search(r"LANCEUR (\S+)", journal).group(1)
        self.assertFalse(pr._dans(lanceur, self.depot), "les tests ont tourné dans le dépôt lui-même : " + lanceur)
        self.assertFalse(os.path.exists(lanceur), "la copie de travail jetable n'a pas été supprimée")
        self.assertFalse(pr._dans(re.search(r"TMPDIR (\S+)", journal).group(1), self.depot))
        for k in ("DB_PATH", "BASE_DB", "RC25_WORK", "CONFIRM_PROD"): self.assertIn("%s absent" % k, journal)

    def test_empreinte_app_identique_a_celle_du_shell_de_la_procedure(self):
        app = os.path.join(self.tmp, "app-test"); os.makedirs(os.path.join(app, "__pycache__")); os.makedirs(os.path.join(app, "sous dossier"))
        for rel, txt in (("a.py", "1"), ("B.py", "2"), ("sous dossier/c d.html", "3"), ("__pycache__/x.pyc", "4"), ("app.py.before-fix", "5"), ("z", "6")):
            ecrit(os.path.join(app, rel), txt)
        shell = ("cd '%s' && find . -type f ! -path '*/__pycache__/*' ! -name '*.before-*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64" % app)
        attendu = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}).stdout.strip()
        self.assertEqual(pr.empreinte_app(app), attendu)


class Refus(Base):
    def assertRefus(self, res, motif):
        code, out, err = res
        self.assertEqual(code, 1, out + err)
        self.assertIn("REFUS", err); self.assertRegex(err, motif)
        self.assertFalse(os.path.exists(self.sentinelle))

    def test_version_differente_refuse_avant_de_lancer_les_tests(self):
        self.ecrire("outils/run_tests_parallel.py", tests_verts() + "open('%s', 'w').write('x')\n" % os.path.join(self.tmp, "TESTS-LANCES"))
        sha = self.commit("lanceur marqueur")
        self.assertRefus(self.lancer(sha=sha, rc="rc51"), r"VERSION .*9\.2-rc50.*attendue .*9\.2-rc51")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "TESTS-LANCES")))
        self.assertEqual(self.contenu_sortie(), [])

    def test_suite_rouge_refuse_sans_copie_ni_conf_et_garde_le_journal(self):
        self.ecrire("outils/run_tests_parallel.py", "import sys\nprint('Ran 3 tests in 0.1s')\nprint('FAILED (failures=1)')\nsys.exit(1)\n")
        sha = self.commit("rouge")
        res = self.lancer(sha=sha)
        self.assertRefus(res, r"PAS verte")
        self.assertIn("FAILED (failures=1)", res[2])
        self.assertEqual(self.contenu_sortie(), ["tests-rc50.log"])

    def test_code_zero_sans_verdict_lisible_refuse(self):
        self.ecrire("outils/run_tests_parallel.py", "print('rien à dire')\n")
        sha = self.commit("muet")
        self.assertRefus(self.lancer(sha=sha), r"sans « Ran N tests")
        self.assertEqual(self.contenu_sortie(), ["tests-rc50.log"])

    def test_zero_test_refuse(self):
        self.ecrire("outils/run_tests_parallel.py", tests_verts(0)); sha = self.commit("zero")
        self.assertRefus(self.lancer(sha=sha), r"sans « Ran N tests")

    def test_depassement_du_delai_refuse(self):
        self.ecrire("outils/run_tests_parallel.py", "import time\ntime.sleep(30)\n"); sha = self.commit("lent")
        self.assertRefus(self.lancer(sha=sha, extra=["--delai-tests", "2"]), r"pas fini en 2 s")
        self.assertEqual(self.contenu_sortie(), ["tests-rc50.log"])

    def test_commit_sans_lanceur_de_tests_refuse(self):
        self.git("rm", "-q", "outils/run_tests_parallel.py"); sha = self.commit("sans lanceur")
        self.assertRefus(self.lancer(sha=sha), r"run_tests_parallel.py absent")

    def test_commit_inconnu_ou_arguments_invalides(self):
        self.assertRefus(self.lancer(sha="0" * 40), r"commit introuvable")
        self.assertRefus(self.lancer(sha="zz"), r"sha invalide")
        self.assertRefus(self.lancer(rc="50"), r"étiquette invalide")
        self.assertRefus(self.lancer(rc="rc5; rm -rf /"), r"étiquette invalide")
        self.assertRefus(self.lancer(extra=["--note", "a\nb"]), r"une ligne")
        self.assertRefus(self.lancer(extra=["--date", "demain"]), r"--date invalide")
        self.assertRefus(self.lancer(conf=os.path.join(self.tmp, "nexistepas.conf")), r"introuvable")
        self.assertRefus(self.lancer(sortie="relatif/dossier"), r"chemin absolu")
        self.assertEqual(self.contenu_sortie(), [])

    def test_aucune_sortie_ni_chemin_final_sous_opt_ni_dans_le_depot(self):
        cible = "/opt/preparer-release-test-ne-pas-creer"
        self.assertRefus(self.lancer(sortie=cible), r"sous /opt")
        self.assertRefus(self.lancer(sortie="/opt/time-billing-v9"), r"sous /opt")
        self.assertRefus(self.lancer(sortie="/opt/time-billing-v9/../time-billing-v9/rc"), r"sous /opt")
        self.assertRefus(self.lancer(extra=["--chemin-final", "/opt/time-billing-v9/releases"]), r"--chemin-final.*sous /opt")
        self.assertRefus(self.lancer(sortie=os.path.join(self.depot, "sortie")), r"dans le dépôt")
        self.assertFalse(os.path.exists(cible)); self.assertFalse(os.path.exists(os.path.join(self.depot, "sortie")))
        lien = os.path.join(self.tmp, "lien-vers-opt"); os.symlink("/opt", lien)                              # un lien vers /opt est reconnu aussi
        self.assertRefus(self.lancer(sortie=os.path.join(lien, "x")), r"sous /opt")
        self.assertFalse(os.path.exists("/opt/x"))

    def test_rien_n_est_ecrase(self):
        os.makedirs(self.sortie)
        for nom in ("prod-rc50.conf", "RESUME-rc50.txt", "tests-rc50.log", "9.2-rc50-%s" % self.sha[:7]):
            p = os.path.join(self.sortie, nom)
            if nom.startswith("9.2"): os.mkdir(p)
            else: ecrit(p, "à conserver")
            self.assertRefus(self.lancer(), r"existe déjà")
            self.assertEqual(os.listdir(self.sortie), [nom])
            if os.path.isdir(p): os.rmdir(p)
            else: os.unlink(p)

    def test_version_rc_non_posterieure_a_la_precedente_refuse(self):
        self.ecrire("app/app.py", 'VERSION="9.2-rc49"\n'); sha = self.commit("v49")
        self.assertRefus(self.lancer(sha=sha, rc="rc49"), r"pas postérieure")
        self.assertEqual(self.contenu_sortie(), [])

    def test_conf_precedente_mal_formee_refuse(self):
        mauvaises = {"ligne exécutable": CONF_PREC + "touch /tmp/x\n", "clé inconnue": CONF_PREC + "PATH=/tmp/evil\n", "clé en double": CONF_PREC + "ROOT=/autre\n",
                     "clé manquante": CONF_PREC.replace("RC_IMAGE=tb-rc49:aaaaaaa\n", ""), "SOURCE_APP sans forme": CONF_PREC.replace("9.2-rc49-aaaaaaa/app", "quelque-part/app")}
        for nom, texte in mauvaises.items():
            with self.subTest(nom):
                c = os.path.join(self.tmp, "mauvaise.conf"); ecrit(c, texte)
                code, out, err = self.lancer(conf=c)
                self.assertEqual(code, 1, nom); self.assertIn("conf précédente", err)
                self.assertEqual(self.contenu_sortie(), [])

    def test_une_sortie_au_chemin_non_lisible_par_le_lecteur_sur_est_refusee_et_ne_laisse_rien(self):
        code, out, err = self.lancer(sortie=os.path.join(self.tmp, "chemin avec espace"))              # le lecteur de conf refuse l'espace
        self.assertEqual(code, 1); self.assertIn("lecteur sûr", err)
        d = os.path.join(self.tmp, "chemin avec espace")
        self.assertEqual(sorted(os.listdir(d)), ["tests-rc50.log"])                                    # ni copie figée, ni dossier provisoire, ni conf publiés

    def test_copie_incomplete_refusee_et_retiree(self):
        self.git("rm", "-q", "requirements.txt"); sha = self.commit("sans requirements")
        self.assertRefus(self.lancer(sha=sha), r"requirements.txt")
        self.assertEqual(self.contenu_sortie(), ["tests-rc50.log"])


class Garde(unittest.TestCase):
    def test_la_source_de_l_outil_ne_lance_aucun_script_de_procedure_ni_docker_ni_reseau(self):
        src = lu(os.path.join(REEL, "outils", "preparer_release.py"))
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        code = re.sub(r'""".*?"""', "", code, flags=re.S)
        for interdit in ("10-preflight", "20-backup", "30-rehearse", "40-deploy", "50-verify", "90-rollback", "docker", "urllib", "socket", "requests", "http.client", ".env\"", "rotate-secrets"):
            self.assertFalse(interdit in code, "mot interdit dans le code de l'outil : " + interdit)
        # seuls programmes appelés : git, tar, bash (lecture de la conf) et l'interpréteur des tests
        self.assertEqual(sorted(set(re.findall(r'subprocess\.(?:run|Popen)\(\[("[^"]+"|a\.python|[a-z_]+)', code))), sorted(['"/usr/bin/env"', '"git"', '"tar"', "a.python"]))

    def test_aucun_chemin_de_production_n_est_ecrit_dans_le_code_sauf_la_barriere(self):
        src = lu(os.path.join(REEL, "outils", "preparer_release.py"))
        self.assertEqual(re.findall(r'"/opt[^"]*"', src), ['"/opt"'])


if __name__ == "__main__":
    unittest.main()
