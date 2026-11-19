# ÉTAT — Time Billing V9.2 (reprise du 05.10.2026, ~00:50 UTC / 08:50 WITA)

## Version et accès
| | |
|---|---|
| **Déployée sur staging** | **9.2-rc15** (code = commit `57983f1`, branche `design-liquid-glass-rc14`, non fusionnée, non poussée). `/health` → `{"status":"ok","version":"9.2-rc15"}` |
| Accès staging | écoute locale `127.0.0.1:8092` : `ssh -L 8092:127.0.0.1:8092 root@<serveur>` puis http://127.0.0.1:8092 (mot de passe : le vôtre, `.env` du staging) |
| Démo (données fictives) | `127.0.0.1:8095`, `tb-demo`, même image rc15, mot de passe dans `/root/demo-time-billing/mot-de-passe.txt` ; tunnel : `ssh -L 8095:127.0.0.1:8095 root@<serveur>` |
| Production | V9.0, `:8091`, **non touchée** : sha256 de la base = `bd31f410…f6d6` (identique à `audit/prod-fp-avant.txt`), même identifiant de conteneur `0b25a3430633…` |
| Dépôt de travail | `/root/time-billing-v9-rc10-20261004` (le nom « rc10 » est historique) |

## Diagnostic à la reprise (vérifié, pas repris des rapports)
* Mission de nuit RC14 terminée normalement à 23:14 WITA (`nuit/TERMINE`, superviseur « terminé », 1 lancement, aucun quota atteint, aucune erreur). Aucune session Time Billing active ; les autres sessions Claude en cours concernent d'autres projets (AMO, LUMO).
* Arbre de travail propre ; code staging == dépôt (`diff -r`) avant et après ce déploiement.
* LUMO, AMO Cockpit, production, Caddy/DNS/pare-feu/SSH/secrets : non touchés. Aucun import. Aucune facture émise modifiée.

## Fonctionnalités opérationnelles (vérifiées par les recettes de la section « Tests »)
Tableau de bord financier (indicateurs, jauge facturé/prévision, anneaux de mandats) · saisie des temps (début-fin ou durée, correction, suppression tracées, verrouillage) · mandats, tarifs, bons de commande, solde et consommation · prévisions mensuelles/annuelles · édition de factures (quantité non arrondie, arrondis, numérotation, émission, immutabilité, copie figée) · annexes cumulatives · notes de crédit partielles et totales, remboursement, compensation, annulation, remplacement · archive (recherche, filtres de statut, ZIP) · import Excel avec aperçu et validation explicite + annulation de lot (testé sur classeur fictif) · sauvegarde/restauration JSON avec prévisualisation et refus d'une sauvegarde amputée · PDF (facture, note de crédit, annulation) · responsive bureau/tablette/téléphone · Liquid Glass.

## Fonctionnalités partielles ou non vérifiées
1. **Fidélité au mockup approuvé : non vérifiable** — le fichier n'a jamais été disponible. Le design suit la direction écrite validée.
2. Pas de graphique de **consommation cumulée par mois** (demanderait une agrégation dans `app.py`, donc la couche de calcul ; non fait sans validation).
3. Rendu **Safari/iOS** (`backdrop-filter`, champs date) non vérifié sur appareil ; tests Chromium uniquement (champs date en `mm/dd/yyyy` sur les captures = paramètres régionaux du Chromium de test).
4. **Import des données historiques réelles : non fait** (interdit) ; registre `import/registre-final/` en attente de vos réponses (R1–R3, M1–M5, M7).
5. PDF : mise en page vérifiée visuellement contre `Facture-reelle-reference-2026-09.pdf` (même structure, même typographie) ; le logo des recettes est fictif.

## Modifications de cette reprise (RC15, commit `57983f1`)
* Onglet **Saisie des heures** : la moitié droite vide accueille désormais « Position des mandats actifs » (barres facturé net / réalisé non facturé / solde), avec mise en évidence du mandat choisi dans le formulaire. Aucun calcul modifié (panneau déjà existant, réutilisé).
* Contraste des textes indicatifs (placeholders) : 3,2:1 → 4,8:1 (WCAG AA).
* Nouveau `tests/test_rc15.py` (4 tests) ; `test_rc10`/`test_rc14_nuit` ajustés à la nouvelle valeur ; `VERSION` = `9.2-rc15`.
* Démo `tb-demo` relancée sur l'image rc15 (mêmes données fictives).

## Décisions qui restent les vôtres (documentées, non bloquantes pour le reste)
* **Mockup** : fournir le fichier pour comparaison.
* **T3** (saisies à cheval sur minuit), **« 1 jour = 8 h »**, registre d'import R1–R3 / M1–M5 / M7.
* **Autorisation séparée** pour l'import réel, puis pour la bascule en production (plan Caddy/DNS/pare-feu, rotation des secrets : `procedure/`, `PROCEDURE-DEPLOIEMENT-RC11.md`).
* **Fusion dans `main`** de la branche `design-liquid-glass-rc14` (après votre validation visuelle).
