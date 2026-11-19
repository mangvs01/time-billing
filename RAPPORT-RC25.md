# RAPPORT RC25 — corrections de facturation B-01 à B-06 (9.2-rc25)

Base : snapshot `ba2514e` (code « facturée-par-date » non publié, étiqueté à tort `9.2-rc24`). Ce lot en fait la version **9.2-rc25** : tout code modifié depuis la copie figée rc24 (`3f49b60`) porte désormais l'identifiant rc25.
Aucun déploiement, aucun accès au serveur ni aux données réelles : tout a été exécuté sur des bases jetables de données synthétiques, dans un répertoire hors dépôt.

## Décisions du propriétaire appliquées (2026-10-09)

| # | Décision | Mise en œuvre |
|---|---|---|
| 1 | Une saisie appartient à la première facture émise qui l'a réellement facturée ; ni sa date courante ni sa présence dans une annexe cumulative ne suffisent | `post_billing.owners()` : propriétaire = première facture émise dont l'annexe figée liste la saisie avec une date figée **dans la période de cette facture**. Un déplacement de date ne change jamais le propriétaire. |
| 2 | Une saisie tardive n'est pas attribuée à la facture suivante du seul fait de son annexe | Le « cas 3 » (reprise automatique par l'annexe cumulative) est supprimé de `owners()`. La saisie tardive n'a pas de propriétaire tant qu'aucune facture ne la facture dans sa propre période. Écarts et avoirs proposés suivent le propriétaire. |
| 3 | Contrôle 14 : quantité nette facturée cumulée ≤ quantité réalisée cumulée ; aucune dérogation implicite ; non contournable par le contrôle 12 | `invoice_checks.run_checks` : contrôle 14, **non dérogeable** (voir « Révision après prévalidation »). Aucun motif, pour le 14 ou pour le 12, n'émet une facture qui le met en échec. |
| 4 | Réémission d'une période seulement si la facture précédente est intégralement créditée | `credit_service.fully_credited` / `period_clash` : crédit intégral = lignes service et AUTRES **et** quantité couvertes par des notes **émises et non annulées**. Utilisé à la création du brouillon, à l'émission, par `owners()` et `period_invoice()`. Annuler la note de crédit qui rend la facture « intégralement créditée » est refusé si la période a été refacturée (`cancellation_blockers`). Aucun document n'est modifié ni supprimé. |
| 5 | Reliquat selon la borne temporelle des règles existantes | `billing_rules.contract(..., through=period_to)` : `billed_through_days` / `offered_through_days` ne comptent que les factures dont la fin de période ≤ fin de la période de la facture (comme `consumed_days` est borné par `upto`). Les chiffres globaux (`billed_days`, solde PO, `unbilled_days`) restent globaux. |
| 6 | Tolérance de sur-facturation 0 ; sous-facturation 0,5 j ; tests sans dérogation par défaut | `OVER_TOLERANCE = 0.0`, `UNDER_TOLERANCE = 0.5` (contrôle 12, toujours dérogeable avec son propre motif). Les helpers de test ne dérogent plus à rien par défaut. |

## Révision après prévalidation (2026-10-09, second commit)

1. **Contrôle 14 non dérogeable.** D8 limite les contrôles dérogeables à 12 et 13 et aucune décision métier explicite ne l'étend : `DEROGABLE = (12, 13)`, le contrôle 14 est un blocage (`derogable=False`). Un champ `derogation_14` envoyé à la main est ignoré ; l'écran d'émission n'offre aucun champ de motif pour le 14 et désactive le bouton. Issues légitimes pour une facture qui dépasse le travail enregistré : enregistrer le travail manquant, corriger la quantité, créditer, ou — pour un doublon avec une facture historique — rejeter la ligne du registre avec motif (la ligne est conservée, jamais supprimée ; test `test_the_exit_is_to_correct_the_data_and_the_history_is_kept`).
   Conséquence métier à connaître : **facturer d'avance (acompte au-delà du travail enregistré) est désormais impossible** ; le reliquat négatif n'est plus atteignable que par des jours déjà « offerts » (test `test_negative_reliquat_cannot_be_offered`).
2. **Tests des crédits et de la réémission** (`tests/test_rc25.py`, classe `B04b_CreditCases` et `B04_CreditThenReissue`) : avoirs partiels cumulés, avoir en montant seul (ne libère jamais la période), jours + montant, note annulée puis note de remplacement, arrondis monétaires (deux partiels qui dépassent d'un centime → refus puis crédit « total » exact ; deux partiels qui laissent un centime → période bloquée jusqu'à son crédit), brouillon de note, crédit intégral puis réémission, annulation refusée après réémission, historique intact (ligne, copie figée, liens d'annexe et octets du PDF comparés).
3. **Fixtures de test** : le contrôle 14 n'étant plus dérogeable, les fixtures qui facturaient des jours jamais travaillés enregistrent désormais le travail correspondant (`RECORD_WORK = True` au niveau de la classe, `record_work()`), ou utilisent une quantité cohérente. Les dérogations restantes (`DEROGATE`, `derogate=`) ne portent plus que sur 12 et 13 et sont nommées dans le test.
4. **Recettes externes** : voir « Recettes » ci-dessous.
5. **Cohérence de `procedure/staging.conf`** : voir « Staging et garde de production ».
6. **Limite de preuve de la propriété des saisies** : voir « Limite de preuve ».

## Limite de preuve de la propriété des saisies (décisions 1 et 2)

La quantité d'une facture est saisie à la main : rien en base ne relie une quantité à des saisies précises. Ni une annexe (cumulative : elle liste toutes les saisies jusqu'à la fin de période) ni une période ne prouvent, à elles seules, quelle part de la quantité couvre réellement une saisie donnée. `owners()` n'affirme donc qu'une chose : « la période de cette facture contenait, à l'émission, la date de la saisie » — la même preuve pour toutes les saisies de la période, qui est celle que la facture imprime (heures de la période, contrôle 12) et que le propriétaire a retenue.

- Elle n'affirme pas qu'une saisie tardive (ajoutée après la facturation de sa période) a été incluse dans une quantité ultérieure, même augmentée volontairement : la saisie reste sans propriétaire ; écarts et avoirs proposés ne l'attachent jamais à une facture ultérieure (test `test_a_late_entry_taken_up_by_a_larger_quantity_is_an_explicit_exception`). Seule une « reprise déclarée » à l'émission pourrait la rattacher : **non implémentée**, décision à prendre.
- Inversement, une saisie possédée par une facture peut n'avoir jamais été comptée dans une quantité saisie en dessous des heures de la période (tolérance de sous-facturation de 0,5 j) : l'écart post-facturation mesure la saisie, pas la quantité.
Cette limite est aussi écrite dans la docstring de `post_billing.owners()`.

## Fichiers modifiés

- `app/app.py` : `VERSION = "9.2-rc25"` ; `draft_values` et `issue` utilisent `credits.period_clash` ; `issue_context` calcule le reliquat avec `through` ; le refus de chevauchement précède les contrôles à l'émission (message plus clair, même refus).
- `app/post_billing.py` : `owners()` (décisions 1, 2, 4, limite de preuve documentée), `period_invoice()`.
- `app/credit_service.py` : `fully_credited`, `period_clash`, garde dans `cancellation_blockers`.
- `app/billing_rules.py` : paramètre `through` de `contract()`.
- `app/invoice_checks.py` : contrôle 14 (non dérogeable), tolérances du contrôle 12, `DEROGABLE = (12, 13)`.
- `app/templates/issue_confirm.html` : texte des dérogations (12 et 13), avertissement « hors ordre chronologique », ligne « facturés nets jusqu'à la fin de période ».
- `procedure/staging.conf` : cohérence avec `prod.conf` (rc23), voir plus bas.
- Tests : `tests/test_rc25.py` (nouveau, 29 tests) ; helpers `tests/test_functional.py` et `tests/test_import.py` ; 18 autres fichiers de tests ajustés ; `tests/concurrency_http.py` (préparation des données).
- Recettes : `tests/browser/recette-saisies.js`, `recette-nuit.js`, `recette-rc14.js`, `tests/recette_fonctionnelle/run_cg.py`, `run_extra.py`.

## Migrations

Aucune : pas de changement de schéma, pas de nouvelle table ni colonne ; `init()` / `migrate_rc19()` inchangés. Les triggers d'immuabilité, les tables append-only, les `BEGIN IMMEDIATE` et les blocages de restauration ne sont pas touchés. Rollback : revenir à la copie figée précédente (aucune donnée écrite par ce lot ne conditionne l'ancien code).

## Tests exécutés et résultats exacts

Environnement : copie du dépôt hors dépôt, Python 3.13, dépendances de `requirements.lock`, secrets factices, bases jetables de données synthétiques (la copie du staging est absente du dépôt et n'a pas été touchée), serveur gunicorn local (2 processus × 8 fils), Chromium 141 / Playwright 1.56.1 (`/opt/pw-browsers`). Docker n'existe pas ici : `docker exec` n'est émulé que pour les scripts Python des recettes (voir plus bas). Tous les chiffres ci-dessous viennent de la dernière exécution, sur l'arbre final.

| Suite | Résultat |
|---|---|
| Unitaires, 35 modules (542 existants + 29 nouveaux dans `tests/test_rc25.py`) | **571 tests, OK** (≈ 90 s) |
| `tests/test_rc25.py` contre le code applicatif d'avant ce lot (première version, 22 tests) | 17 échecs/erreurs sur 22 : les tests détectent bien les défauts |
| `tests/concurrency_http.py` | **11/11 PASS** |
| `tests/e2e_http.py` (phase 1, redémarrage, phase 2) | **48 PASS / 0 FAIL** |
| `tests/e2e_rc13.py` + contrôle `pdftotext` de l'annexe | **5 PASS / 0 FAIL**, motif d'annexe imprimé en entier, aucune troncature |

Avant le premier commit, la suite donnait 542 tests : 539 OK, 1 échec réel (`test_rc19.PostInvoicing.test_moves_across_periods_and_mandates_and_late_entries`, corrigé) et 2 erreurs d'environnement (chemin `/app`, résolues par un shim hors dépôt).

## Recettes

**Recettes navigateur** (Chromium, serveur local, base jetable ; `rc19`, `rc23` et `verrou-import` sur un **substitut synthétique** de la copie du staging : mandat NHAF 2026, mandats clos avec saisies « importées », 24 lignes historiques « à valider » dont SUIVI 2026!M15 et M8 — aucune donnée réelle) :

| Recette | PASS | FAIL |
|---|---|---|
| `recette-saisies.js` (phases 1 et 2, redémarrage) — **adaptée** | 44 | 0 |
| `recette-metier.js` (phases 1 et 2) | 122 | 0 |
| `recette-nuit.js` — **adaptée** | 34 | 0 |
| `recette-rc14.js` — **adaptée** | 56 | 0 |
| `recette-rc12.js` | 22 | 0 |
| `recette-minuit.js` | 15 | 0 |
| `recette-rc19.js` (substitut) | 37 | 0 |
| `recette-rc23.js` (substitut) | 25 | 0 |
| `recette-verrou-import.js` (substitut + `preparer-copie-verrou-import.py`) | 43 | 0 |
| `recette-responsive.js` (après `seed-ux.js`) | 33 | 0 |

Adaptations : `recette-saisies.js` facturait 1 j pour 3 h 45 enregistrées (échec au contrôle 14, vérifié : 33 PASS puis cascade d'échecs avant correction ; 44 PASS avec le code d'avant et après correction) → quantité 0,46875 j, aucune dérogation. `recette-nuit.js` et `recette-rc14.js` n'envoyaient que des dérogations 12 **et 13** par défaut : le 13 n'était pas nécessaire et est retiré ; le 12 (sous-facturation voulue, reliquat traité) est conservé, avec un motif qui le dit.

**Recettes fonctionnelles Python** (`tests/recette_fonctionnelle`, même substitut ; `docker exec` émulé localement pour les seuls scripts qui l'utilisent). Elles sont écrites pour la copie du staging : plusieurs vérifications portent sur ses 2 247 saisies et ses 24 mandats. Les résultats ont donc été comparés **avant** (`ba2514e`) et **après** :

| Script | Après (rc25) | Avant (`ba2514e`) | Lecture |
|---|---|---|---|
| `run_ab.py` | 54 PASS / 3 FAIL | 54 / 3 | 3 échecs = comptes de la vraie copie (2 247 saisies, 24 mandats) |
| `run_cg.py` — **adapté** | **101 PASS / 0 FAIL** | 96 / 0 avant adaptation | voir ci-dessous |
| `run_dg.py` | 51 / 2 | 50 / 3 | DH5 et DH9 (empreinte des 2 247 saisies) échouent aussi avant ; D1 n'échouait qu'avant |
| `run_extra.py` — **adapté** | **25 PASS / 0 FAIL** | 25 / 0 | |
| `run_pages.py` | 3 / 0 | 3 / 0 | |
| `run_forecast.py` | 12 / 9 | 12 / 9 | échecs identiques : valeurs de la vraie copie |
| `run_mandats.py` | 6 / 4 | 6 / 4 | échecs identiques : valeurs de la vraie copie |

`run_cg.py` : la facture 1 facturait 1,25 j pour 9 h = 1,125 j enregistrés (« facturé d'avance », reliquat −0,125 j) — impossible désormais. Le script vérifie maintenant que l'émission est **refusée** par le contrôle 14 (C3b), qu'**aucun motif** (12, 13 ni 14) n'y change rien (C3d), enregistre l'heure manquante, puis émet (reliquat 0, traitement « aucun ») ; les décisions de traitement du reliquat (C5, C6b) sont testées sur la facture 2, dont le reliquat est positif ; le test « reliquat négatif ne peut pas être offert » (C6) est retiré (inatteignable, couvert par `test_negative_reliquat_cannot_be_offered`) ; la facture 3 enregistre les 6 h qu'elle facture. `run_extra.py` : X3 (arrondi au centime), X4 (total nul) et X5 (grand montant) facturaient plus que le travail enregistré, la facture restait en **brouillon** et le PDF de brouillon donnait les mêmes montants — le script « réussissait » sans rien émettre. Le travail correspondant est maintenant enregistré (X5 : 9 876 h), et deux contrôles vérifient que la facture est bien émise (X3a, X5a).

**Impossibles ici, avec la raison exacte :**
- `run_entites_vides.py` (échoue avant et après, `IndexError`) : exige les mandats réels « PCR LV 2026 », « STC GEM Oct - DM job », « MSD » (décision C2) de la copie du staging.
- `run_rc19.py` (python) : exige des identifiants de saisies importées réels de la copie (`IndexError` dès le premier `entries where id=?`) ; 2 échecs de comptage identiques avant/après.
- `run_hij.py` : exige `/root/Time sheet CP.xlsx` (classeur réel), `journaux/fonc/launch_fonc.sh` et de **vrais conteneurs Docker** supplémentaires (restauration, import) — absents.
- `run_premiere_facture.py` : exige la copie réelle (mandat NHAF 2026 chargé) et `Facture-reelle-reference-2026-09.pdf` (absent du dépôt).
- `tests/recette_fonctionnelle/appliquer_emetteur.py`, `mandats_appliquer.py` : outils d'application sur le staging (`--apply`), volontairement non exécutés ; le second exige `import/MANDATS-A-COMPLETER.csv` (absent).
- `journaux/recette_navigateur_final.sh` (orchestrateur Docker sur l'image déployée) : non exécutable sans Docker ; ses recettes ont été rejouées une à une par l'exécuteur local ci-dessus.

Les recettes dépendant de la copie réelle (`run_ab`, `run_dg`, `run_forecast`, `run_mandats`, `run_rc19.py`, `run_entites_vides`, `run_hij`, `run_premiere_facture`) restent **à rejouer par vous sur la copie du staging** avant tout déploiement ; `run_cg.py` et `run_extra.py` y ont été adaptés mais n'y ont pas été exécutés.

## Staging et garde de production

**`procedure/staging.conf` (modifié).** Le snapshot désignait la copie figée rc24 (`3f49b60`) alors que le staging exécute rc23, que `prod.conf` désigne rc23, que la décision D14 (déploiement rc24) n'est pas prise et que `00-prerequis-bascule.sh` exige la **même** copie et la même image dans les deux fichiers. Les valeurs rc23 (`SOURCE_APP`, `SOURCE_REQ`, `RC_IMAGE`) sont rétablies, avec un commentaire décrivant la livraison de rc25 : décision écrite du propriétaire → copie figée par `git archive <sha rc25>` sur le serveur → image de répétition `tb-g4-cand:<sha7>` → changement **simultané** des trois valeurs dans `staging.conf` et `prod.conf`. Aucune copie rc25 n'existe encore, donc aucun chemin rc25 n'est inventé. Vérifié : les deux fichiers, sourcés séparément, donnent la même copie (`9.2-rc23-50492d4`) et la même image (`tb-g4-cand:50492d4`).

**MISE À JOUR (commit 94e519c et suivants) : cette section décrit l'état au commit 6de4526. La branche contient désormais une proposition de garde liée au contenu (SHA-256), NON activée en production et sans décision propriétaire : voir `RAPPORT-GARDE-PRODUCTION-RC25.md`. Les deux textes ne se contredisent plus sur ce point : « non modifiée » ne vaut que pour 6de4526.**

**Garde de production (`procedure/tb-common.sh`) — examinée, non modifiée (au commit 6de4526).** L'exception ajoutée par le snapshot dispense de `CONFIRM_PROD` les scripts `backup-quotidien.sh` et `verifier-sauvegarde.sh` lorsqu'ils s'exécutent depuis `/root/time-billing-v9-rc10-20261004/procedure`.
- *Autorisation non démontrée* : le commentaire dit « authorized by G5 A » ; HANDOFF-CLAUDE2-20261008-1815 et REPRISE-G4 donnent la décision `billing-g5-sauvegarde-quotidienne` comme **en attente**, et HANDOFF-1715 indique qu'une exception identique avait été refusée puis retirée. Je ne peux pas vérifier le Decision Center.
- *Portée de l'exception* : liée à un chemin et à un nom de script, pas à l'empreinte du contenu. Ce chemin est l'arbre de développement, modifiable par les sessions Claude (dont le superviseur de nuit, qui peut éditer `procedure/`). Un `backup-quotidien.sh` modifié s'exécuterait contre la production sans confirmation.
- *« Lecture seule » inexact* : `backup-quotidien.sh` fait `docker exec` dans le conteneur de production, écrit `/data/.backup-auto.db` dans le volume de production, et n'a pas de nettoyage en cas d'échec avant la suppression du fichier ; `verifier-sauvegarde.sh` ne touche qu'une copie.
- *Incohérence avec la documentation* : la ligne cron proposée par `OPERATIONS-RC11.md` pointe `/opt/time-billing-v9/procedure/…`, chemin que l'exception n'accepte pas : installée telle quelle, la tâche s'arrêterait chaque nuit.
- *Recommandation (décision du propriétaire)* : tant que la décision n'est pas enregistrée, rétablir la garde stricte ; si elle l'est, lier l'exception à l'empreinte SHA-256 des deux scripts (fichier d'empreintes appartenant à root, hors dépôt) plutôt qu'à un chemin, installer le cron sur le chemin réellement autorisé et ajouter un nettoyage (`trap`) du fichier temporaire. Aucune modification faite : changer cette garde, dans un sens ou dans l'autre, est une décision de sécurité qui vous appartient.

## Points qui exigent encore votre décision

1. Autoriser (ou non) une exception motivée au contrôle 14 (par exemple pour les acomptes). Aujourd'hui : non.
2. Arrondi « au quart supérieur » / « au plus proche » avec tolérance zéro : une quantité arrondie au-dessus du travail de la période échoue au contrôle 12 (exception motivée possible) **et**, au cumul, au 14 (aucune exception) : le mode « haut » n'est plus utilisable que si le travail cumulé le couvre (test `test_rounding_up_beyond_the_recorded_work_cannot_be_issued`).
3. « Reprise déclarée » des saisies tardives à l'émission (voir « Limite de preuve »).
4. Mandats déjà sur-facturés dans l'historique (jours historiques validés > travail enregistré) : le contrôle 14 compte les jours historiques validés **quelle que soit leur date** (choix prudent, ils n'ont pas de période) ; ces mandats ne pourront plus être facturés tant que le travail manquant n'est pas enregistré ou que la ligne du registre n'est pas corrigée par remplacement (page « Factures historiques »).
5. Crédit « intégral » : une note en montant seul qui laisse des jours non crédités ne libère pas la période (blocage conservateur ; sortie : créditer aussi les jours).
6. Garde de production et décision `billing-g5-sauvegarde-quotidienne` (ci-dessus).
7. Recettes qui visent la copie réelle du staging (liste dans « Recettes ») : à rejouer par vous sur cette copie avant tout déploiement.

## Risques résiduels

- Le calcul de **propriétaire** change pour les données existantes : une saisie tardive précédemment « facturée » par la facture suivante (cas 3) apparaît désormais comme « annexe seulement ». Aucune donnée stockée n'est modifiée ; les écarts post-facturation affichés peuvent différer. Sans objet sur la production actuelle (base vide, V9.0).
- `owners()` et `period_invoice()` appellent `fully_credited` par facture (quelques requêtes par facture émise du mandat) : sans effet à l'échelle actuelle.
- Dépendance à l'horloge dans les tests : des fixtures datées d'octobre/décembre 2026 dépassent la date du jour (contrôle 13) ; elles déclarent `DEROGATE = (13,)`.
- Limites déjà connues, non traitées ici : pas de sauvegarde automatique de la production, restauration JSON qui accepte une table `entries` absente, retour arrière sans conservation des données récentes (voir le rapport d'audit).
