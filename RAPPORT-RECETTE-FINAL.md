# RAPPORT DE RECETTE FINAL — Time Billing V9.2-rc15 (staging) — 05.10.2026

Tous les résultats ci-dessous ont été produits pendant cette reprise (journaux dans le dépôt). Données exclusivement fictives, sur copies de la base staging ; ni écriture en production, ni import réel.

## Version testée et déployée
Code `57983f1` (9.2-rc15). Recette complète exécutée **deux fois** : sur l'image RC14 déployée (avant modification, `journaux/recette-reprise.out`) et sur l'image candidate RC15 (`journaux/recette-rc15cand.out`) ; RC15 ensuite déployée en staging.

## Résultats
| Contrôle | RC14 (avant) | RC15 (candidate) |
|---|---|---|
| Unitaires (calculs de jours facturables, arrondis, consommation/solde, prévisions, numérotation, émission/immutabilité, avoirs/compensation, annexes cumulatives, import/rollback, PDF, sauvegarde/restauration, sécurité) | 356/356 | **360/360** (`journaux/unit-rc15.log`) |
| Parcours métier navigateur (phase 1 + redémarrage + phase 2) | 107/107 + 15/15 | 107/107 + 15/15 |
| Gestion des saisies | 34/34 + 7/7 | 34/34 + 7/7 |
| Responsive (bureau/tablette/téléphone, 33 pages) | 33/33 | 33/33 |
| RC12 / RC14 / NUIT navigateur | 22/22, 56/56, 34/34 | 22/22, 56/56, 34/34 |
| HTTP bout en bout (2 phases) / rc13 | 30/30 + 18/18 / 5/5 | 30/30 + 18/18 / 5/5 |
| Concurrence (gthread) | 11/11 | 11/11 |
| Erreurs console navigateur | 0 | 0 |
| Base staging inchangée par la recette | oui | oui |

Les tests en échec pendant le développement : 2 assertions (`test_rc14_nuit` épinglait l'attribut exact du panneau ; ma première version de `test_rc15` lisait la première règle de placeholder au lieu de la dernière) — corrigées, aucun défaut applicatif.

## Procédure staging (RC15)
Préflight OK · sauvegarde `pre-rc15-20261005T004416Z` conforme · répétition de migration **GO** (intégrité, clés étrangères, 35 déclencheurs d'immuabilité, migration idempotente) · déploiement · `50-verify` **conforme avant et après redémarrage** (santé 9.2-rc15, en-têtes, CSP à nonce, uid 10001, FS lecture seule, écoute locale, secrets absents des journaux). Code déployé == dépôt.

## Contrôles visuels
Captures de la recette : `recette/reprise/ecrans/`, `recette/rc15cand/ecrans/`. PDF générés comparés à `Facture-reelle-reference-2026-09.pdf` : structure et typographie identiques (logo fictif). Onglet Saisie vérifié à 1440 px et 390 px, sans erreur console.

## Non testé / limites
Safari/iOS et appareils réels ; fidélité au mockup (fichier absent) ; graphique de consommation cumulée (non implémenté) ; rollback RC15→RC14 non rejoué ; tout ce qui touche aux données réelles (import, production).

## Production
Aucune action. sha256 de la base de production recalculé en fin de session : `bd31f410305d6623dbf2237158ad8820cd3cbbfba20a37df0f17c54af7b0f6d6` (identique à la référence) ; conteneur `0b25a3430633…` inchangé ; `/login` répond 200.

## Problèmes restants / décisions
Voir `ETAT-TIME-BILLING.md` (mockup, T3, « 8 h », registre d'import, autorisations d'import et de production, fusion dans `main`). Rollback et prochaine étape : `CONTINUATION-TIME-BILLING.md`.
