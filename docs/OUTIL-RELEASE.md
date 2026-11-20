# Outil de préparation d'une version (BILL-OUTIL-RELEASE)

`outils/preparer_release.py` remplace les gestes manuels **avant** la chaîne de la procédure : copie figée, conf `prod-rcNN.conf`, vérifications. Il **prépare seulement** : il ne lance jamais `procedure/10 → 50` (ni aucun script de `procedure/`), ne touche ni `/opt/time-billing-v9` ni aucun `.env`, n'utilise ni Docker ni réseau, ne modifie pas le dépôt (lectures git seulement, aucun commit) et n'écrase rien.

## Lancer

```
/root/venvs/rc25-test-venv/bin/python -I outils/preparer_release.py <sha> <rcNN> \
    --sortie /dossier/hors/depot --conf-precedente /chemin/prod-rcMM.conf \
    [--chemin-final /dossier/definitif] [--note "ce que contient la version"] [--branche B] [--date AAAA-MM-JJ]
```
`--sortie` : absolu, hors dépôt, **jamais sous `/opt`** (refusé, liens symboliques compris). `--chemin-final` : dossier parent à inscrire dans la conf si la copie doit être déplacée ensuite (défaut : `--sortie`, ex. `/root/time-billing-releases`). `--python` / `--delai-tests` (défaut 7 200 s) règlent le lancement des tests. Suite complète : ≈ 2 min 30 (1 220 tests).

## Ce qu'il fait, dans l'ordre (premier refus = arrêt, code 1 ; rien n'est publié avant que tout soit bon)

1. Contrôle des arguments ; refuse si un des fichiers à produire existe déjà.
2. **VERSION** : `app/app.py` **du commit** doit valoir `9.2-rcNN`, et `rcNN` doit être postérieure à la conf précédente.
3. **Suite verte** : extrait le commit (`git archive`) dans une copie de travail **jetable** (supprimée ensuite) et y lance `outils/run_tests_parallel.py` avec un environnement nettoyé (`DB_PATH`, `BASE_DB`, `RC25_*`, `CONFIRM_PROD`… retirés). Exige code 0 **et** « Ran N tests » (N ≥ 1) **et** « OK » : un code 0 muet est refusé. Journal : `tests-rcNN.log`.
4. **Copie figée** `9.2-rcNN-<sha7>/` : contenu exact du commit (ni arbre de travail, ni fichier non suivi), contrôlée (`VERSION`, `app.py`, `requirements.txt`, `Dockerfile`, `lire-conf.sh`, nombre de fichiers = arbre git), puis lecture seule (comme les copies faites à la main). Construite sous un nom provisoire, renommée seulement quand la conf est validée.
5. **Conf** `prod-rcNN.conf` = la précédente avec `SOURCE_APP`, `SOURCE_REQ`, `RC_IMAGE` (`tb-rcNN:<sha7>`) changés **et une ligne d'historique** ajoutée à la fin ; tout le reste est identique. Relue par le lecteur sûr de la procédure (`lire-conf.sh`, lecture de données) et comparée à l'attendu.
6. `RESUME-rcNN.txt` (affiché aussi) : sha complet, arbre, VERSION, résultat des tests, copie, empreinte de `app/` (même méthode que `tb-common.sh`), valeurs changées.

## Ce qui reste au superviseur

Compléter la ligne d'historique (GO propriétaire), poser la conf et la copie à leur emplacement définitif, créer `.env.rcNN`, puis lancer lui-même 10 → 50.

## Limites

Fait pour la chaîne actuelle (`9.2-rcNN-<sha7>`, conf à 10 clés connues). Les tests ne prouvent pas la migration sur une base réelle : la répétition (30) reste à faire par la procédure.

## Tests

`tests/test_preparer_release.py` (20 tests, dépôt fictif, faux lanceur de tests, scripts « 10 → 50 » piégés qui laisseraient une trace) : chemin nominal, copie issue du commit, environnement des tests, empreinte comparée au shell, tous les refus ci-dessus, et garde statique (aucun script de procédure, Docker ni réseau appelé).
