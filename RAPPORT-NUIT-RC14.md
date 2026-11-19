# Rapport de la mission de nuit — Time Billing V9.2-rc14 « Liquid Glass » (04.10.2026)

Session Claude autonome sous superviseur (`nuit/superviseur.py`, tmux `timebilling-nuit`), branche `design-liquid-glass-rc14`.
**Résultat : 7 cycles commités, recette complète finale sans aucun échec sur l'image déployée en staging, staging redéployé et vérifié, production non touchée.**

## 1. Statut du mockup
**Introuvable**, recherché au début et à la fin de la nuit : `/root/Downloads` (seulement des archives AMO Cockpit), `/root` (images/PDF/HTML récents : uniquement des captures de recette et des PDF de factures fictives), tout le disque pour `*mockup*`, `*maquette*`, `*liquid*glass*` (seulement des références de plugins sans rapport sous `/root/.codex`).
**La fidélité au mockup n'a pas pu être vérifiée.** Le travail suit la direction écrite validée (HANDOFF §3). Il faudra comparer dès réception du fichier.

## 2. État initial → état final
| | Début de nuit | Fin de nuit |
|---|---|---|
| Commit | `10175fd` (code) / `b6b8072` (outillage de nuit) | **`23e00c7`** (+ commit de ce rapport) |
| Tests unitaires | 344/344 | **356/356** (12 nouveaux, `tests/test_rc14_nuit.py`) |
| Recette navigateur | 7 recettes, 0 échec | 8 recettes (nouvelle `tests/browser/recette-nuit.js`, 34 contrôles), **0 échec** |
| Staging :8092 | 9.2-rc14 initiale | **9.2-rc14 de la nuit** (code = `23e00c7`), vérifications conformes |
| Démo :8095 | image rc14 initiale | relancée sur la nouvelle image, données fictives inchangées |

Défauts relevés à l'audit initial (captures `/root/demo-time-billing/nuit-rc14/00-audit-initial/`) :
* pages de détail sans étiquette d'environnement ni entrée active ;
* cellules « Actions » en `flex`, qui cassaient les lignes des tableaux ;
* grille encore à 2 colonnes sur tablette (formulaire écrasé) ;
* champ fichier natif ;
* mandats : formulaire avant la liste, aucune visualisation des soldes ;
* facturation à moitié vide ;
* archive sans filtre de statut et illisible au téléphone ;
* aperçu d'import hors de la coque, pastilles bleu marine ;
* colonne d'actions de la liste des saisies à 540 px.

## 3. Ce qui a été corrigé (par cycle)
| Cycle | Commit | Contenu |
|---|---|---|
| C1 cohérence | `27e82b0` | Étiquette d'environnement sur toutes les pages (processeur de contexte : seule modification de `app.py`, 1 ligne). Entrée latérale active déduite de l'URL sur les pages de détail, avec `aria-current`. Cellules d'actions redevenues de vraies cellules de tableau. Grille à 1 colonne et indication de défilement sur tablette. Sélecteur de fichier au design system. |
| C2 tableau de bord | `0e0dc10` | Carte « Facturé » dominante (2 rangées, chiffre de 44 px) avec une jauge facturé / prévision restante et le total estimé de l'année (chiffres déjà calculés par les prévisions, aucun nouveau calcul). Les 4 autres cartes forment un bloc 2 × 2. Plus d'effet de survol sur des cartes non cliquables. Titre de section au-dessus des anneaux. « Solde contractuel » sur sa propre ligne. |
| C3 mandats, facturation, avoirs | `11416ad` | Panneau « Position des mandats actifs » : une barre par mandat (facturé net / réalisé non facturé / solde contractuel, avec un repère si la commande est dépassée). Il est affiché en tête de « Mandats » et à droite du formulaire de facturation (collant, mandat choisi mis en évidence). Ordre de lecture des mandats : positions, détail, prévisions, puis création (pleine largeur, 3 colonnes). Synthèse chiffrée et jauge en tête du suivi d'une note de crédit. Actions destructives en rouge discret. |
| C4 archive, import | `886304b` | Pastilles de statut (Tous / Brouillons / Émises / Avec note de crédit) combinées à la recherche. Archive en cartes au téléphone. **Correctif : au téléphone, la recherche et les filtres ne masquaient rien** (`table.cards tr{display:block}` l'emportait sur `tr[hidden]`). Aperçu d'import dans la coque (barre latérale, entrée active), pastilles et statuts aux couleurs du design, panneaux qui défilent au lieu de déborder. **Barre d'outils de l'import plus collante au téléphone** : elle mesurait ≈ 690 px et aurait masqué l'écran. Pastilles défilantes. |
| C5 responsive | `7988af2` | Téléphone : « Situation synthétique », « Détail des mandats » et « Notes de crédit » en cartes (libellés recopiés des en-têtes par un script ; le HTML servi est inchangé). Tablette (761–1100 px) : archive, détail des mandats et notes de crédit en cartes à 2 colonnes, **les boutons d'action ne sont plus hors de l'écran**. Histogramme des prévisions réparti sur toute la largeur. |
| C6 accessibilité, erreurs | `691e3ca` | Messages : refus (rouge, `role="alert"`), avertissements « Attention » (ambre), confirmations (`role="status"`). Ils sont classés sur leur texte existant, sans en modifier aucun. Contraste du texte secondaire : 3,0:1 → 4,6:1 (WCAG AA). Astérisque rouge sur les champs requis. Chaque libellé est relié à son champ. `aria-label` sur les champs sans libellé. Lien d'évitement « Aller au contenu ». |
| C7 finitions | `23e00c7` | Liste des saisies : le motif de verrouillage (en `nowrap`) imposait 540 px à la colonne d'actions ; il passe maintenant à la ligne. Astérisques des Paramètres harmonisés. |

Aucun calcul, schéma, PDF, libellé métier, route, id, `name` ou `action` n'a été modifié. Les classes et ids existants sont conservés (seulement des ajouts).

## 4. Tests exécutés (résultats réels)
| Contrôle | Résultat | Journal |
|---|---|---|
| Unitaires (22 modules), fin de nuit | **356/356 OK** | `journaux/unit-nuit-c7.log` (aussi c1…c6) |
| Recette complète sur l'image locale `tb-nuit:c3` | 0 échec | `journaux/recette-nuitc3.out` |
| Recette complète sur l'image locale `tb-nuit:c6` | 0 échec | `journaux/recette-nuitc6.out` |
| **Recette complète finale sur l'image DÉPLOYÉE en staging** | **0 échec** : métier 107/107 + 15/15, saisies 34/34 + 7/7, responsive 33/33, RC12 22/22, RC14 56/56, **NUIT 34/34**, e2e 30/30 + 18/18, rc13 5/5, concurrence 11/11, « base staging inchangée » | `journaux/recette-nuitfinal.out`, détails dans `journaux/nuitfinal/` et `recette/nuitfinal/` |
| Recettes rapides par cycle (RC14 + NUIT + responsive) | toutes vertes à chaque commit | `nuit/outils/recette-rapide.sh` |
| Aperçu d'import à 1440 / 834 / 390 px (prévisualisation seulement, jamais de validation) | 0 échec | `nuit/outils/shots_import_nuit.js` |
| Procédure staging : préparation, sauvegarde, répétition (GO), déploiement, `50-verify` | conformes | §6 |

Pendant la nuit, deux échecs sont survenus, tous deux dans mes propres tests, et ont été corrigés : un comptage de `class="kpi` qui incluait le conteneur `kpis`, et une assertion qui attendait `class="cards"`, devenu `class="cards tcards"`. La nouvelle recette a par ailleurs détecté un vrai défaut, « filtres sans effet au téléphone », corrigé en C4.

## 5. Captures (bureau 1440, tablette 834, téléphone 390)
* Finales : `/root/demo-time-billing/nuit-rc14/99-final/` (`bureau-*`, `tablette-*`, `mobile-*`, dont `*-import-apercu.png`), sur une instance jetable avec des données fictives.
* Démo après redéploiement : `/root/demo-time-billing/nuit-rc14/demo-finale/`.
* Par cycle : `/root/demo-time-billing/nuit-rc14/00-audit-initial/`, `01-cycle1/` … `06-cycle6/`. Captures des recettes : `recette/nuitfinal/ecrans-*`.

## 6. Staging
Redéployé le 04.10.2026 à 15:06 UTC par `procedure/*.sh procedure/staging.conf` :
* préparation conforme ;
* sauvegarde `/root/backups/time-billing-v9-staging/pre-rc14-20261004T150641Z` (image de retour `:pre-rc14-20261004T150641Z`) ;
* répétition **GO** ;
* déploiement, santé `{"status":"ok","version":"9.2-rc14"}` ;
* `50-verify` : **vérifications conformes** (en-têtes, CSP à nonce, uid 10001, lecture seule, écoute locale, intégrité de la base, secrets absents des journaux).

Le code déployé est identique à celui du dépôt (`diff -r`, hors un ancien fichier `.before-*` exclu par la procédure). Une note datée a été ajoutée dans `NOTE-SESSIONS-PARALLELES.md`. La démo `tb-demo` a été relancée sur la nouvelle image (`--restart unless-stopped`, `ENV_LABEL=DÉMO`, mêmes données fictives).

## 7. Production et données historiques
* **Aucune commande n'a visé la production** (port 8091, son dossier sous /opt, son conteneur). Aucun import historique, aucune donnée réelle, aucune fusion dans `main`, aucun push.
* **Empreinte SHA-256 de la base de production : je ne l'ai pas recalculée.** La commande est refusée par les permissions de nuit (toute commande citant le chemin de la production est bloquée) et je n'ai pas contourné ce garde-fou. Référence : `bd31f410…f6d6` dans `audit/prod-fp-avant.txt`, retrouvée identique par la session interactive à 21:54 WITA (`nuit/prod-empreinte-debut.txt`).
* Preuve indirecte : le conteneur de production a le **même identifiant au début et à la fin de la nuit** (`0b25a3430633…`, celui de `audit/prod-fp-avant.txt`, démarré le 02.10). Seuls le conteneur staging et `tb-demo` ont changé (`nuit/docker-ps-debut.txt`, `nuit/docker-ps-fin.txt`). Les identifiants des autres applications (V7/V8/V30, amo-cockpit, chess-academy, n8n) sont inchangés, et aucune commande ne les a visées.
* **À faire au réveil** (une commande, en session interactive) : calculer le `sha256sum` de la base de production. Il doit donner `bd31f410305d6623dbf2237158ad8820cd3cbbfba20a37df0f17c54af7b0f6d6`.

## 8. Défauts restants / non fait
1. Fidélité au mockup non vérifiée (fichier absent).
2. Pas de graphique de consommation cumulée : il demanderait une agrégation mensuelle par mandat dans `app.py`. Je ne l'ai pas fait pour ne pas toucher à la couche de calcul sans validation.
3. Onglet « Saisie des heures » sur grand écran : le formulaire occupe la moitié gauche et la droite reste vide.
4. Tests uniquement sous Chromium (Playwright) : Safari/iOS (rendu de `backdrop-filter`, sélecteurs de date) n'a pas été vérifié sur un appareil réel. Sur les captures, les champs date affichent `mm/dd/yyyy` (paramètres régionaux du Chromium sans interface), et non le format fr-CH d'un vrai navigateur.
5. Le classement des messages (refus / avertissement / confirmation) repose sur leur texte : un futur message reformulé pourrait être mal coloré (sans effet fonctionnel).
6. La liaison des libellés aux champs et les libellés des cartes téléphone sont posés par script : sans JavaScript, le comportement reste celui d'avant.
7. Contraste des textes indicatifs des champs (placeholders) : 3,2:1, sous le seuil AA de 4,5:1.
8. PDF inchangés (volontairement) ; pas de mode sombre (non demandé).

## 9. Commits de la nuit (branche `design-liquid-glass-rc14`, ni fusionnée ni poussée)
```
23e00c7 rc14 nuit C7: final review polish
691e3ca rc14 nuit C6: accessibility, readability, error states
7988af2 rc14 nuit C5: responsive tables on tablet and phone
886304b rc14 nuit C4: archive status filters, phone cards, import preview in the shell
11416ad rc14 nuit C3: mandate balances, billing side panel, credit-note summary
0e0dc10 rc14 nuit C2: hierarchy of the financial indicators on the dashboard
27e82b0 rc14 nuit C1: coherence of the shell on every page
```
Plus le commit final qui ajoute ce rapport, les empreintes `docker ps` et la recette finale.

## 10. Fichiers modifiés depuis `10175fd` (`git diff --stat 10175fd`, avant le commit de ce rapport)
```
 .gitignore                            |   1 +
 NOTE-SESSIONS-PARALLELES.md           |   8 +++
 app/app.py                            |   2 +-
 app/templates/_confirm.html           |   2 +-
 app/templates/_ds.html                | 131 +++++++++++++++++++---
 app/templates/_flash.html             |   1 +
 app/templates/_navbar.html            |   4 +-
 app/templates/_page.html              |   4 +-
 app/templates/_sidebar.html           |   4 +-
 app/templates/credit_detail.html      |   6 +-
 app/templates/import_review.html      |   8 +--
 app/templates/index.html              |  38 ++++---
 app/templates/login.html              |   2 +-
 journaux/recette-nuitc3.out           |  13 +++
 journaux/recette-nuitc6.out           |  14 +++
 journaux/recette_navigateur_final.sh  |   6 +-
 journaux/unit-nuit-c1.log             |  23 ++++
 journaux/unit-nuit-c2.log             |  23 ++++
 journaux/unit-nuit-c3.log             |  23 ++++
 journaux/unit-nuit-c4.log             |  23 ++++
 journaux/unit-nuit-c5.log             |  23 ++++
 journaux/unit-nuit-c6.log             |  23 ++++
 journaux/unit-nuit-c7.log             |  23 ++++
 nuit/.gitignore                       |   4 +
 nuit/HANDOFF-NUIT-RC14.md             |  32 ++++++
 nuit/MISSION-NUIT-RC14.md             |  44 ++++++++
 nuit/arreter.sh                       |   6 +
 nuit/demarrer.sh                      |   8 +
 nuit/outils/crop.py                   |   4 +
 nuit/outils/dev.sh                    |  10 ++
 nuit/outils/recette-rapide.sh         |  23 ++++
 nuit/outils/shots_import_nuit.js      |  24 ++++
 nuit/prod-empreinte-debut.txt         |   4 +
 nuit/settings-nuit.json               |  85 ++++++++++++++
 nuit/superviseur.py                   | 227 ++++++++++++++++++++++++++++++++
 nuit/tests/faux-claude.sh             |  15 +++
 nuit/tests/test-superviseur.sh        |  49 +++++++++
 nuit/voir.sh                          |  14 +++
 tests/browser/recette-nuit.js         | 122 ++++++++++++++++++
 tests/browser/releve-fictif-nuit.xlsx | Bin 0 -> 5404 bytes
 tests/test_rc14_nuit.py               | 129 ++++++++++++++++++
 41 files changed, 1168 insertions(+), 37 deletions(-)
```
Code applicatif modifié cette nuit : `app/app.py` (1 ligne, processeur de contexte) et `app/templates/` (`_ds.html`, `_flash.html` nouveau, `_confirm.html`, `_navbar.html`, `_page.html`, `_sidebar.html`, `credit_detail.html`, `import_review.html`, `index.html`, `login.html`). Les fichiers `nuit/*.sh`, `nuit/superviseur.py`, `nuit/settings-nuit.json`, `nuit/tests/*` ainsi que MISSION et HANDOFF proviennent du commit d'outillage `b6b8072` de la session interactive.

## 11. Retrouver la session et les journaux
* État du superviseur et dernières actions : `/root/time-billing-v9-rc10-20261004/nuit/voir.sh`. Session : `tmux attach -t timebilling-nuit` (Ctrl-b puis d pour se détacher). Journaux : `nuit/logs/` (superviseur et `claude-*.jsonl`).
* Fichier de reprise : `/root/time-billing-v9/CONTINUATION-RC14.md`.
* Recettes : `journaux/recette-nuitfinal.out`, `journaux/nuitfinal/`, `recette/nuitfinal/`. Unitaires : `journaux/unit-nuit-c*.log`.
* Pour relancer :
  * unitaires : ``MODS=$(ls tests/test_*.py | sed 's#tests/#tests.#;s#\.py$##' | tr '\n' ' '); IMG=time-billing-v9-rc10-test:latest journaux/run_unit.sh $MODS`` ;
  * recette complète : `RUN=x PFX=tb-nuitf PB=8320 IMG_REF=time-billing-v9-staging-time-billing-v9-staging:latest journaux/recette_navigateur_final.sh` ;
  * recette rapide d'une image locale : `IMG=tb-nuit:c7 nuit/outils/recette-rapide.sh`.

## 12. Retour arrière
* Staging vers l'état d'avant cette nuit (RC14 initiale) : `cd /root/time-billing-v9-rc10-20261004/procedure && ./90-rollback.sh staging.conf`. Le script restaure le code et la base de `pre-rc14-20261004T150641Z` et contrôle le SHA-256. Pour revenir à RC13, la sauvegarde `pre-rc14-20261004T132654Z` reste disponible (voir `PROCEDURE-ROLLBACK-RC11.md`).
* Dépôt : chaque cycle est un commit isolé, annulable par `git revert <commit>` sans réécrire l'historique. Pour retrouver l'état d'avant la nuit : `git checkout 10175fd -- app tests`.
* Démo : `docker rm -f tb-demo`, puis relance sur `time-billing-v9-staging-time-billing-v9-staging:pre-rc14-20261004T150641Z` avec les mêmes options.

## 13. Ressources laissées
* Images locales de test `tb-nuit:c6` et `tb-nuit:c7` (supprimables).
* Aucun conteneur `tb-nuit-*` en marche.
* Données de test sous `/tmp/nuit/` et `recette/nuit*/` (fictives, jetables).
