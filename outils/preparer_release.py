"""Préparation (et seulement la préparation) d'une version Time Billing « rcNN » — BILL-OUTIL-RELEASE.

Usage (voir docs/OUTIL-RELEASE.md) :
    /root/venvs/rc25-test-venv/bin/python -I outils/preparer_release.py <sha> <rcNN> --sortie DOSSIER --conf-precedente prod-rcMM.conf [options]

Ce que fait l'outil, dans cet ordre, et s'arrête au premier refus (rien n'est publié avant que tout soit vert) :
  1. contrôle les arguments et les cibles (le dossier de sortie n'est ni sous /opt, ni dans le dépôt ; rien n'existe déjà à l'endroit des fichiers produits) ;
  2. vérifie que VERSION (app/app.py de CE commit) vaut « 9.2-rcNN » ;
  3. extrait le commit (git archive) dans une copie de travail JETABLE et y lance outils/run_tests_parallel.py : la suite doit être verte (code 0, « Ran N tests », « OK ») ;
  4. produit la copie figée « 9.2-rcNN-<sha7> » (git archive, lecture seule) dans SORTIE, et la contrôle (VERSION, fichiers indispensables, nombre de fichiers = arbre git) ;
  5. produit prod-rcNN.conf à partir de la conf précédente (SOURCE_APP, SOURCE_REQ, RC_IMAGE changés, une ligne d'historique ajoutée, tout le reste identique) et la fait relire
     par le lecteur sûr de la procédure (procedure/lire-conf.sh, lecture de données : la conf n'est jamais exécutée) ;
  6. écrit RESUME-rcNN.txt et l'affiche.
Ce que l'outil ne fait JAMAIS : lancer procedure/10 → 50 (ni aucun script de procedure/), toucher /opt/time-billing-v9, lire ou écrire un .env, utiliser Docker ou le réseau,
modifier le dépôt (aucun commit, aucun checkout : seulement des lectures git) ou la conf précédente.
Code de sortie : 0 = tout est prêt · 1 = refus ou échec (message sur stderr) · 2 = usage erroné.
"""
import argparse, datetime, fnmatch, hashlib, os, re, shutil, stat, subprocess, sys, tempfile, time

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIXE_VERSION = "9.2-"                                # VERSION de l'application = PREFIXE_VERSION + rcNN (tb-common.sh : RC_TAG=${VERSION#9.2-})
CLES_MODIFIEES = ("SOURCE_APP", "SOURCE_REQ", "RC_IMAGE")
CLES_CONF = ("ROOT", "PROJECT", "CONTAINER", "IMAGE", "URL", "BACKUP_BASE", "SOURCE_APP", "SOURCE_REQ", "RC_IMAGE", "COMPOSE_TEMPLATE")
FICHIERS_INDISPENSABLES = ("app/app.py", "requirements.txt", "Dockerfile", "procedure/lire-conf.sh")
INTERDIT = "/opt"                                       # aucune sortie ni chemin final là-dessous (la production vit dans /opt/time-billing-v9)
PATH_SUR = "/usr/sbin:/usr/bin:/sbin:/bin"


class Refus(Exception):
    """Une vérification a échoué : message en clair, code de sortie 1."""


def _dans(chemin, base):
    chemin, base = os.path.realpath(chemin), os.path.realpath(base)
    return chemin == base or chemin.startswith(base + os.sep)


def _git(depot, *args, entree=None, check=True):
    r = subprocess.run(["git", "-C", depot] + list(args), input=entree, capture_output=True, stdin=None if entree else subprocess.DEVNULL)
    if check and r.returncode != 0: raise Refus("git %s a échoué : %s" % (" ".join(args[:2]), r.stderr.decode(errors="replace").strip()[:300]))
    return r


def _env_propre(tmp):
    """Environnement des tests : rien d'hérité qui pointe vers une base, un travail ou une confirmation de production ; TMPDIR = dossier jetable."""
    env = {k: v for k, v in os.environ.items() if not (k.startswith("RC25_") or k in ("DB_PATH", "BASE_DB", "CONFIRM_PROD", "BASH_ENV", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"))}
    env["TMPDIR"] = tmp
    return env


# ---------------------------------------------------------------------------------------------------------------------------- contrôles d'arguments

def controler_arguments(a):
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", a.sha): raise Refus("sha invalide (7 à 40 caractères hexadécimaux attendus) : %r" % a.sha)
    if not re.fullmatch(r"rc[0-9]{2,3}", a.rc): raise Refus("étiquette invalide (« rc » + 2 ou 3 chiffres, ex. rc49) : %r" % a.rc)
    if "\n" in a.note or "\r" in a.note: raise Refus("--note ne doit tenir que sur une ligne")
    if a.date is not None and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", a.date): raise Refus("--date invalide (AAAA-MM-JJ) : %r" % a.date)
    for nom, chemin in (("--sortie", a.sortie), ("--chemin-final", a.chemin_final)):
        if chemin is None: continue
        if not os.path.isabs(chemin): raise Refus("%s doit être un chemin absolu : %s" % (nom, chemin))
        if _dans(chemin, INTERDIT): raise Refus("%s ne peut pas être sous %s (cet outil ne prépare rien dans la production) : %s" % (nom, INTERDIT, chemin))
    if _dans(a.sortie, a.depot): raise Refus("--sortie ne peut pas être dans le dépôt (%s) : choisir un dossier hors dépôt" % a.depot)
    if not os.path.isdir(os.path.join(a.depot, ".git")) and not os.path.isfile(os.path.join(a.depot, ".git")): raise Refus("pas un dépôt git : %s" % a.depot)
    if not os.path.isfile(a.conf_precedente): raise Refus("conf précédente introuvable : %s" % a.conf_precedente)


def lire_version(depot, sha):
    r = _git(depot, "show", "%s:app/app.py" % sha)
    m = re.search(r'^VERSION="([^"\n]*)"', r.stdout.decode("utf-8", "replace"), re.M)
    if not m: raise Refus("VERSION introuvable dans app/app.py du commit %s" % sha[:7])
    return m.group(1)


def controler_version(depot, sha, rc):
    v = lire_version(depot, sha); attendu = PREFIXE_VERSION + rc
    if v != attendu: raise Refus("VERSION du commit %s = « %s », attendue « %s » : ce commit n'est pas la %s (corriger VERSION dans app/app.py et committer, ou donner le bon sha)" % (sha[:7], v, attendu, rc))
    return v


# ---------------------------------------------------------------------------------------------------------------------------- conf

def analyser_conf(texte):
    """Lecture comme des DONNÉES (aucune exécution) : renvoie {clé: (index de ligne, valeur)}. Refuse toute ligne qui n'est ni vide, ni commentaire, ni CLÉ=valeur d'une clé connue, ou une clé en double."""
    cles = {}
    for i, ligne in enumerate(texte.split("\n")):
        if re.fullmatch(r"\s*(#.*)?", ligne): continue
        m = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([A-Za-z0-9_./:@%+,-]*)", ligne)
        if not m or m.group(1) not in CLES_CONF: raise Refus("conf précédente : ligne %d refusée (%r)" % (i + 1, ligne[:80]))
        if m.group(1) in cles: raise Refus("conf précédente : clé %s définie deux fois" % m.group(1))
        cles[m.group(1)] = (i, m.group(2))
    manque = [k for k in CLES_CONF if k not in cles]
    if manque: raise Refus("conf précédente : clé(s) manquante(s) : " + ", ".join(manque))
    return cles


def rc_precedente(valeur_source_app):
    m = re.search(r"/9\.2-(rc[0-9]+)-([0-9a-f]+)/app$", valeur_source_app)
    if not m: raise Refus("conf précédente : SOURCE_APP n'a pas la forme .../9.2-rcMM-<sha>/app : %s" % valeur_source_app)
    return m.group(1), m.group(2)


def numero(rc): return int(rc[2:])


def construire_conf(texte_prec, rc, sha7, base_finale, ligne_histo):
    """Texte de la nouvelle conf : celui de la précédente avec 3 valeurs remplacées sur place et UNE ligne de commentaire ajoutée à la fin. Rien d'autre ne change."""
    cles = analyser_conf(texte_prec)
    prec_rc, prec_sha = rc_precedente(cles["SOURCE_APP"][1])
    if numero(rc) <= numero(prec_rc): raise Refus("%s n'est pas postérieure à la conf précédente (%s) : une préparation va toujours vers l'avant" % (rc, prec_rc))
    dossier = "%s/9.2-%s-%s" % (base_finale.rstrip("/"), rc, sha7)
    neuf = {"SOURCE_APP": dossier + "/app", "SOURCE_REQ": dossier + "/requirements.txt", "RC_IMAGE": "tb-%s:%s" % (rc, sha7)}
    lignes = texte_prec.split("\n")
    for k, v in neuf.items(): lignes[cles[k][0]] = "%s=%s" % (k, v)
    while lignes and lignes[-1] == "": lignes.pop()
    lignes.append(ligne_histo.replace("{precedente}", "%s-%s" % (prec_rc, prec_sha)))
    return "\n".join(lignes) + "\n", neuf, (prec_rc, prec_sha)


def relire_par_le_lecteur_sur(copie_figee, fichier_conf, tmp):
    """Fait lire la conf produite par procedure/lire-conf.sh de la copie figée (bash -p, environnement vide : la conf est lue comme des données). Renvoie {clé: valeur}."""
    lecteur = os.path.join(copie_figee, "procedure", "lire-conf.sh")
    script = '. "$1" || exit 3; lire_conf "$2" X_ || exit 4; for k in %s; do v=X_$k; printf "%%s=%%s\\n" "$k" "${!v}"; done' % " ".join(CLES_CONF)
    r = subprocess.run(["/usr/bin/env", "-i", "PATH=" + PATH_SUR, "/bin/bash", "-p", "-c", script, "lire", lecteur, fichier_conf], capture_output=True, text=True, cwd=tmp, stdin=subprocess.DEVNULL)
    if r.returncode != 0: raise Refus("le lecteur sûr de la procédure refuse la conf produite (code %d) : %s" % (r.returncode, (r.stderr or r.stdout).strip()[:300]))
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)


# ---------------------------------------------------------------------------------------------------------------------------- tests

def lancer_suite(sha_complet, a, tmp, journal):
    """Extrait le commit dans une copie de travail jetable (sous tmp) et y lance outils/run_tests_parallel.py de CE commit. Renvoie (nombre de tests, secondes, dernières lignes)."""
    copie = os.path.join(tmp, "travail"); os.mkdir(copie)
    extraire_archive(a.depot, sha_complet, copie)
    lanceur = os.path.join(copie, "outils", "run_tests_parallel.py")
    if not os.path.isfile(lanceur): raise Refus("outils/run_tests_parallel.py absent du commit %s : impossible de vérifier la suite" % sha_complet[:7])
    scratch = os.path.join(tmp, "scratch"); os.mkdir(scratch)
    t0 = time.monotonic()
    with open(journal, "w") as out:
        try: r = subprocess.run([a.python, "-I", lanceur], stdout=out, stderr=subprocess.STDOUT, cwd=copie, env=_env_propre(scratch), stdin=subprocess.DEVNULL, timeout=a.delai_tests)
        except subprocess.TimeoutExpired: raise Refus("la suite n'a pas fini en %d s (journal : %s)" % (a.delai_tests, journal))
    duree = time.monotonic() - t0
    texte = open(journal, errors="replace").read(); queue = texte.strip().splitlines()[-15:]
    if r.returncode != 0: raise Refus("la suite n'est PAS verte (code %d). Fin du journal :\n    %s\n  Journal complet : %s" % (r.returncode, "\n    ".join(queue), journal))
    ran = re.findall(r"^Ran ([0-9]+) tests? in ", texte, re.M)
    ok = [l for l in texte.splitlines() if re.fullmatch(r"OK( \(.*\))?", l.strip())]
    if not ran or int(ran[-1]) < 1 or not ok: raise Refus("la suite rend le code 0 mais sans « Ran N tests … OK » lisible : verdict non vérifiable (journal : %s)" % journal)
    return int(ran[-1]), duree, ok[-1].strip()


# ---------------------------------------------------------------------------------------------------------------------------- copie figée

def extraire_archive(depot, sha, destination):
    """git archive <sha> | tar -x : le contenu EXACT du commit (ni .git, ni fichier non suivi, ni modification non commitée)."""
    ga = subprocess.Popen(["git", "-C", depot, "archive", "--format=tar", sha], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tar = subprocess.run(["tar", "-x", "-C", destination, "--no-same-owner"], stdin=ga.stdout, capture_output=True)
    ga.stdout.close(); err = ga.stderr.read().decode(errors="replace"); rc = ga.wait()
    if rc != 0 or tar.returncode != 0: raise Refus("git archive / tar a échoué : %s %s" % (err.strip()[:200], tar.stderr.decode(errors="replace").strip()[:200]))


def lecture_seule(chemin):
    """Même état que les copies figées faites à la main : dossiers r-xr-xr-x, fichiers r--r--r-- (r-xr-xr-x s'ils étaient exécutables)."""
    for dossier, sous, fichiers in os.walk(chemin, topdown=False):
        for f in fichiers:
            p = os.path.join(dossier, f)
            if os.path.islink(p): continue
            os.chmod(p, 0o555 if os.stat(p).st_mode & stat.S_IXUSR else 0o444)
        os.chmod(dossier, 0o555)


def rendre_ecrivable(chemin):
    for dossier, sous, fichiers in os.walk(chemin):
        os.chmod(dossier, 0o755)


def supprimer_notre_dossier(chemin):
    """Nettoyage d'un dossier créé par cet outil lui-même (jamais autre chose)."""
    if os.path.lexists(chemin):
        rendre_ecrivable(chemin); shutil.rmtree(chemin, ignore_errors=True)


def empreinte_app(app_dir):
    """Même empreinte que tb-common.sh:app_digest (find . -type f ! -path '*/__pycache__/*' ! -name '*.before-*' | sort -z | xargs sha256sum | sha256sum), calculée en Python (tri d'octets)."""
    lignes = []
    for dossier, sous, fichiers in os.walk(app_dir):
        for f in fichiers:
            p = os.path.join(dossier, f)
            rel = "./" + os.path.relpath(p, app_dir)
            if os.path.islink(p) or not os.path.isfile(p) or "/__pycache__/" in rel or fnmatch.fnmatchcase(f, "*.before-*"): continue
            with open(p, "rb") as fh: h = hashlib.sha256(fh.read()).hexdigest()
            lignes.append((rel.encode("utf-8", "surrogateescape"), "%s  %s\n" % (h, rel)))
    lignes.sort(key=lambda x: x[0])
    return hashlib.sha256("".join(l for _, l in lignes).encode("utf-8", "surrogateescape")).hexdigest()


def preparer_copie_provisoire(depot, sha_complet, sortie, nom, version):
    """Construit la copie dans un dossier provisoire de SORTIE et la contrôle ; elle n'a pas encore son nom définitif (publier_copie le lui donne, une fois la conf validée)."""
    provisoire = os.path.join(sortie, ".en-cours-" + nom)
    if os.path.lexists(provisoire): raise Refus("un dossier provisoire existe déjà (préparation interrompue ?) : %s — à examiner, l'outil n'y touche pas" % provisoire)
    os.mkdir(provisoire)
    try:
        extraire_archive(depot, sha_complet, provisoire)
        for f in FICHIERS_INDISPENSABLES:
            if not os.path.isfile(os.path.join(provisoire, f)): raise Refus("la copie figée n'a pas %s (la procédure en a besoin)" % f)
        with open(os.path.join(provisoire, "app", "app.py"), encoding="utf-8") as fh: v = re.search(r'^VERSION="([^"\n]*)"', fh.read(), re.M)
        if not v or v.group(1) != version: raise Refus("VERSION de la copie figée ≠ %s" % version)
        attendus = [l for l in _git(depot, "ls-tree", "-r", "-z", "--name-only", sha_complet).stdout.decode("utf-8", "surrogateescape").split("\0") if l]
        presents = sum(len(f) for _, _, f in os.walk(provisoire))
        if presents != len(attendus): raise Refus("la copie figée a %d fichiers, l'arbre git du commit en a %d" % (presents, len(attendus)))
        return provisoire, len(attendus), empreinte_app(os.path.join(provisoire, "app"))
    except BaseException:
        supprimer_notre_dossier(provisoire); raise


def publier_copie(provisoire, definitif):
    lecture_seule(provisoire); os.rename(provisoire, definitif)


# ---------------------------------------------------------------------------------------------------------------------------- programme

def ecrire_exclusif(chemin, texte):
    with open(chemin, "x", encoding="utf-8") as f: f.write(texte)


def branche_du_commit(depot, sha):
    cur = _git(depot, "branch", "--show-current", check=False).stdout.decode().strip()
    liste = [b.strip() for b in _git(depot, "branch", "--contains", sha, "--format=%(refname:short)", check=False).stdout.decode().splitlines() if b.strip()]
    return cur if cur in liste else (liste[0] if liste else "inconnue")


def preparer(a):
    controler_arguments(a)
    depot = os.path.realpath(a.depot)
    complet = _git(depot, "rev-parse", "--verify", "--quiet", a.sha + "^{commit}", check=False).stdout.decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", complet): raise Refus("commit introuvable (ou ambigu) dans le dépôt : %s" % a.sha)
    sha7 = complet[:7]; arbre = _git(depot, "rev-parse", complet + "^{tree}").stdout.decode().strip()
    nom = "9.2-%s-%s" % (a.rc, sha7)
    sortie = os.path.abspath(a.sortie); base_finale = a.chemin_final or sortie
    copie_finale = os.path.join(sortie, nom); conf_finale = os.path.join(sortie, "prod-%s.conf" % a.rc)
    resume_f = os.path.join(sortie, "RESUME-%s.txt" % a.rc); journal_tests = os.path.join(sortie, "tests-%s.log" % a.rc)
    for p in (copie_finale, conf_finale, resume_f, journal_tests):
        if os.path.lexists(p): raise Refus("existe déjà, l'outil n'écrase rien : %s" % p)
    # 2. VERSION, 3. conf précédente lisible (avant les tests : refus rapide)
    version = controler_version(depot, complet, a.rc)
    texte_prec = open(a.conf_precedente, encoding="utf-8").read()
    date = a.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    branche = a.branche or branche_du_commit(depot, complet)
    histo = "# %s (préparation par outils/preparer_release.py) : %s = %s ; git archive %s (branche %s). Précédente : {precedente}. GO propriétaire et rappel des limites : à compléter par le superviseur." % (
        date, a.rc, a.note or "version préparée", sha7, branche)
    nouvelle, neuf, (prec_rc, prec_sha) = construire_conf(texte_prec, a.rc, sha7, base_finale, histo)          # échoue ici si la conf précédente est mauvaise
    os.makedirs(sortie, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="preparer-release-")
    if _dans(tmp, depot): shutil.rmtree(tmp, ignore_errors=True); raise Refus("le dossier temporaire système est dans le dépôt : régler TMPDIR ailleurs")
    provisoire = None
    try:
        print("1/5 VERSION = %s (commit %s)" % (version, sha7), flush=True)
        print("2/5 suite de tests dans une copie jetable (quelques minutes) …", flush=True)
        nb, secondes, verdict = lancer_suite(complet, a, tmp, journal_tests)
        print("    %d tests, %s, %.0f s — journal : %s" % (nb, verdict, secondes, journal_tests), flush=True)
        print("3/5 copie figée …", flush=True)
        provisoire, nb_fichiers, empreinte = preparer_copie_provisoire(depot, complet, sortie, nom, version)
        copie = copie_finale
        print("4/5 conf %s …" % os.path.basename(conf_finale), flush=True)
        fichier_conf = os.path.join(tmp, "prod-%s.conf" % a.rc)
        with open(fichier_conf, "w", encoding="utf-8") as fh: fh.write(nouvelle)
        lu = relire_par_le_lecteur_sur(provisoire, fichier_conf, tmp)
        attendu = {k: v[1] for k, v in analyser_conf(texte_prec).items()}; attendu.update(neuf)
        if lu != attendu: raise Refus("la conf relue par le lecteur sûr diffère de ce qui était attendu : %s" % sorted(k for k in attendu if lu.get(k) != attendu[k]))
        publier_copie(provisoire, copie_finale)                                   # tout est validé : seulement maintenant la copie reçoit son nom définitif, puis la conf
        ecrire_exclusif(conf_finale, nouvelle)
        print("5/5 résumé", flush=True)
        diff = ["    %s : %s → %s" % (k, analyser_conf(texte_prec)[k][1], neuf[k]) for k in CLES_MODIFIEES]
        resume = "\n".join([
            "PRÉPARATION %s — %s UTC" % (a.rc.upper(), datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")),
            "",
            "Commit        : %s (branche %s), arbre %s" % (complet, branche, arbre),
            "VERSION       : %s (conforme)" % version,
            "Suite         : %d tests, %s (code 0), %.0f s, dans une copie de travail jetable — journal %s" % (nb, verdict, secondes, journal_tests),
            "Copie figée   : %s (%d fichiers, lecture seule)" % (copie, nb_fichiers),
            "Empreinte app : %s (même méthode que procedure/tb-common.sh)" % empreinte,
            "Conf produite : %s (à partir de %s, précédente %s-%s)" % (conf_finale, os.path.abspath(a.conf_precedente), prec_rc, prec_sha),
            "  Valeurs changées :", *diff,
            "  Ajouté : 1 ligne d'historique à la fin. Tout le reste est identique à la conf précédente ; relue sans erreur par procedure/lire-conf.sh (lecture de données).",
            "",
            "Pas fait (volontairement) : aucun script de procedure/ lancé ; /opt/time-billing-v9 et tout .env non touchés ; aucun Docker, aucun réseau, aucun commit.",
            "Reste au superviseur : relire la ligne d'historique de la conf (GO propriétaire), %s si la copie doit vivre ailleurs, créer .env.%s (le contrôle préalable de la procédure le signale), puis lancer lui-même la chaîne de la procédure." % (
                "déplacer la copie au chemin inscrit dans la conf" if a.chemin_final else "vérifier que le chemin inscrit dans la conf est bien l'emplacement définitif", a.rc),
            ""])
        ecrire_exclusif(resume_f, resume)
        print("\n" + resume)
    finally:
        supprimer_notre_dossier(tmp)
        if provisoire: supprimer_notre_dossier(provisoire)          # copie jamais publiée (refus en cours de route) ; rien si elle a été renommée
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prépare une version rcNN (copie figée + conf) après vérification de VERSION et de la suite. Ne déploie rien.")
    ap.add_argument("sha", help="commit à figer (7 à 40 hexadécimaux)")
    ap.add_argument("rc", help="étiquette de la version, ex. rc49")
    ap.add_argument("--sortie", required=True, help="dossier (absolu, hors dépôt, pas sous /opt) qui recevra la copie figée, prod-rcNN.conf, RESUME-rcNN.txt et le journal des tests")
    ap.add_argument("--conf-precedente", required=True, help="prod-rcMM.conf de la version en cours (lue, jamais modifiée)")
    ap.add_argument("--chemin-final", help="dossier parent inscrit dans la conf pour la copie figée, si elle doit être déplacée ensuite (défaut : --sortie)")
    ap.add_argument("--note", default="", help="texte de la ligne d'historique (une ligne)")
    ap.add_argument("--branche", help="nom de branche à inscrire (défaut : détectée)")
    ap.add_argument("--date", help="date de la ligne d'historique, AAAA-MM-JJ (défaut : aujourd'hui, UTC)")
    ap.add_argument("--depot", default=ROOT, help="dépôt git (défaut : celui de cet outil)")
    ap.add_argument("--python", default=sys.executable, help="interpréteur qui lance les tests (défaut : celui de l'outil)")
    ap.add_argument("--delai-tests", type=int, default=7200, help="durée maximale de la suite, en secondes")
    a = ap.parse_args(argv)
    try: return preparer(a)
    except Refus as e:
        print("REFUS : %s" % e, file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())
