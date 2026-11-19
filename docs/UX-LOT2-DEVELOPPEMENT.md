# Time Billing 9.2-rc34 (candidat) — UX lot 2 : développement

Mission BILLING-LOT2-DEV (claude2), 23.10.2026. Décision du propriétaire du 23.10 : « tout le lot 2 », recommandations R-1 à R-7 de [UX-LOT2-PROPOSITIONS.md](UX-LOT2-PROPOSITIONS.md).
Rien n'est commité, poussé, construit ni déployé. Aucune règle de facturation, de TVA, d'arrondi, de contrôle ou de numérotation n'est modifiée ; aucune écriture nouvelle (la seule route touchée, `/suggest`, reste en lecture seule).

## Propositions réalisées (ordre 1 → 4 → 2 → 3 → 6, puis 5, 8, 11, 7, 10, 9)

| # | Réalisé | Fichiers |
|---|---|---|
| 1 | Bloc « À traiter » (décision requise / à faire / conseil), un bouton par ligne vers la page de l'action (`/invoice/<id>/ecart`, `/issue/<id>`, `/credit/<id>`, Paramètres) ; cartes de chiffres cliquables (`?tab=archive&af=draft` filtre l'archive). R-4 : les 14 contrôles existants sont exécutés (lecture seule) pour au plus `DASH_CHECKS_MAX = 5` brouillons, sinon « à contrôler ». La sauvegarde n'est plus téléchargée depuis le tableau de bord (lien vers Paramètres). | `app.py` (`dashboard_todo`), `index.html`, `_ds.html` |
| 4 | Mode « Début / fin \| Durée » segmenté, raccourcis « Aujourd'hui · Hier » (jour de Zurich), durée dans le bouton (« Enregistrer le temps — 3 h 45 » ; libellés nuit / > 12 h du lot 1 inchangés), barre d'enregistrement collée en bas sur téléphone, aide raccourcie. | `index.html`, `_ds.html`, `app.py` (`yesterday_iso`) |
| 2 | Émission en trois temps : récapitulatif (colonne collante sur ordinateur, en tête sur téléphone), contrôles compacts dans leur ordre, motif de dérogation dans la ligne de l'anomalie (`<textarea form="issueForm" name="derogation_<n>">`), « Corriger le brouillon », décisions, bouton qui rappelle numéro et TTC. R-3 : position détaillée repliée, ouverte d'office si dépassement de PO, émission hors ordre ou écart. Champs postés identiques. | `issue_confirm.html`, `_ds.html` |
| 3 | Brouillon guidé : raccourcis de période (R-5, aucune date avant un clic), calcul automatique (anti-réponse périmée ; une quantité saisie à la main n'est jamais écrasée), pré-alertes avant création (brouillon chevauchant avec lien, facture émise chevauchée, 0 h, contrôle 12, PO), quantité et montant de chaque règle d'arrondi, options repliées. R-1 : le contrôle 12 est calculé par le serveur avec **la même fonction** que le contrôle (`invoice_checks.period_story`, extraite à l'identique de `run_checks`). R-2 : affichage seulement, « Sans arrondi » reste le défaut. | `invoice_checks.py`, `app.py` (`/suggest` : champs ajoutés `options`, `typed`, `overlapping_drafts`, `issued_clash`, `entries_in_period`, `po_*`), `index.html`, `_ds.html` |
| 6 | Archive : « Brouillons à émettre » puis « Documents émis » (même table `#archiveTable`, titres de groupe masqués sous filtre), une action principale par ligne + menu « Plus », détail replié sur téléphone. | `index.html`, `_ds.html` |
| 5 | Barre d'onglets basse sur téléphone (Tableau · Saisie · Mandats · Factures · Plus ; « Plus » : Édition des factures, Import, Paramètres, Déconnexion). **Remplace sur téléphone le bouton flottant B-6** (même rôle : onglet Saisie + focus « Heure de début ») ; le balisage du bouton reste, masqué. | `_sidebar.html`, `_ds.html`, `index.html` |
| 8 | R-6 : 2 décimales + valeur exacte en infobulle (liste des saisies, reliquat dans l'archive ; les jours du registre historique restent exacts) ; valeurs exactes conservées sur l'émission, l'écart (sans zéros de remplissage : « 10,00 j » au lieu de « 10,0000 j ») et les notes de crédit. | `index.html`, `entries.html`, `invoice_variance.html` |
| 11 | 5 dernières saisies sur le tableau de bord (15 sur l'onglet Saisie), synthèse repliable (ouverte sur ordinateur, fermée sur téléphone), barre simple pour un mandat sans PO. | `index.html`, `_ds.html` |
| 7 | Toutes les saisies : périodes rapides (liens GET, paramètres existants), filtrage à la sélection, totaux par jour et par semaine ISO calculés sur toute la sélection filtrée, une ligne par saisie sur téléphone (suppression depuis la page de modification). | `app.py` (`entries_list`), `entries.html`, `_ds.html` |
| 10 | « Reprendre » sur les dernières saisies : pré-remplissage navigateur à la date du jour, aucun enregistrement sans « Enregistrer ». | `index.html` |
| 9 | Partiel : formulaire de création en 4 sections avec repère « requis avant émission » (client, tarif, adresse : la règle réelle `missing_for_issue`), « sans PO » au lieu de 0,00 CHF, R-7 « Clôturer » déplacé dans la page du mandat (même route, même motif, même confirmation). **Non fait : tableau réduit à 6 colonnes** (voir points ouverts). | `index.html`, `project_edit.html`, `_ds.html` |

Version : `VERSION = "9.2-rc34"` (candidat ; le test `_app_facts.declared_version` impose le format `9.2-rcNN`, d'où l'absence de suffixe « -candidat »).

## Tests

Environnement : venv de test recréé le 23.10 (après le redémarrage de 17:41 qui a vidé `/tmp`) dans `/root/venvs/rc25-test-venv`, depuis `requirements.lock` (versions identiques, téléchargées depuis PyPI sur demande explicite du propriétaire). Runner isolé du dépôt (`validation-ui/rel-660516406feb/outils/run_tests_isolated.py`, racine passée par `VERIF_ROOT`), base SQLite synthétique jetable. Toutes les commandes lourdes lancées par `test-slot`, une à la fois.

| Étape | Résultat |
|---|---|
| Référence rc33 (HEAD, copie figée) | 708 tests, OK (1 ignoré, 5 échecs attendus) |
| Suite complète, arbre modifié, 1er passage | 768 tests, 7 échecs — tous dus au lot 2 et corrigés (voir ci-dessous) |
| Suite complète, arbre corrigé | **768 tests, OK (5 échecs attendus)** |
| `test_ux_lot2` + `test_ux_lot1` + `test_rc14_nuit` après le dernier correctif CSS | 56 tests, OK |
| Recette navigateur lot 1 (`recette-ux-lot1.js`, instance jetable, base vide) | **67/67** |
| Recette navigateur lot 2 (`recette-ux-lot2.js`, instance jetable, base vide) | **87/87**, aucune erreur console |
| Captures « après » (`docs/ux-lot2-captures-apres/`, 1280 × 900 et 390 × 844, mêmes données fictives que `docs/ux-lot2-captures/`) | 11 écrans × 2 largeurs (pleine page + premier écran), plus brouillon calculé et menu « Plus », `mesures.json`, 0 erreur console, aucun débordement horizontal, aucune cible < 44 px sur mobile |

Échecs du 1er passage et corrections :
- `test_functional.Ergonomics`, `test_rc14.Shell` : le menu « Plus » répétait des boutons `data-tab` → il active l'onglet d'origine par `data-go`.
- `test_g4.Indicators` : « dont 1 j historique » → jours historiques de nouveau au format exact (exception R-6 du registre).
- `test_rc10.BackupReminder` : casse du texte « aucune sauvegarde JSON » rétablie.
- `test_rc7.A3Dates` : date ISO littérale dans le script « Reprendre » → lue sur le bouton « Aujourd'hui ».
- `test_revue_rc19_restes` : `/entries` en 404 aux dates extrêmes (débordement du calcul des semaines) → bornage aux limites du calendrier.
- `test_rc11_security.Csp` : la confirmation de clôture a quitté `/` (R-7) → **test adapté** : `data-confirm` vérifié sur la page du mandat, absence d'`onsubmit` vérifiée sur les deux pages.

Recettes : scripts adaptés au lot 2 (lot 1 : « Édition des factures » via « Plus » sur téléphone ; détail du contrôle 3 lu en `textContent`, replié sur mobile par R-3 ; lot 2 : jeu fictif complété par du travail antérieur, sinon le contrôle 14 — non dérogeable — bloquait à juste titre ; attente de la navigation du filtrage automatique). La recette lot 2 a trouvé **une anomalie réelle**, corrigée : sur téléphone, les titres de groupe de l'archive restaient visibles sous filtre (`#archiveTable tr.grouprow[hidden]{display:none}`, assertion ajoutée).

Mesures avant → après (mobile 390) : tableau de bord 6 879 → 3 884 px ; saisies 16 626 → 7 134 px ; émission Alpha 4 595 → 3 173 px (bouton 4 296 → 2 727 px) ; archive 3 329 → 2 726 px ; saisie : bouton 941 → 706 px. Bureau 1280 : émission Alpha, bouton 2 254 → 1 778 px.

## Points ouverts et décisions à valider

1. **B-6 remplacé par la barre basse sur téléphone** (n° 5) : choix fait car le conflit est maîtrisé (« Saisie » reprend exactement le rôle du bouton flottant) ; à confirmer par le propriétaire.
2. **Tableau « Détail des mandats » gardé à 12 colonnes** (n° 9) : la recette métier A4, `test_functional` et `test_rc14_nuit` lisent ces colonnes par position et par en-tête ; les réduire contredirait une exigence de recette validée. À trancher.
3. R-6 : les pages du registre historique gardent leurs 4 décimales (valeurs comparées aux cellules source) ; les messages flash d'écart aussi (textes testés).
4. R-4 : seuil `DASH_CHECKS_MAX = 5` à confirmer.
5. Captures : « avant » dans `docs/ux-lot2-captures/` (rc33), « après » dans `docs/ux-lot2-captures-apres/` (13 Mo, 48 PNG : à alléger avant commit si souhaité, par exemple ne garder que les premiers écrans).
