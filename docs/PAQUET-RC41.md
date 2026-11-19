# Notes de version 9.2-rc41 (candidat — non déployé)

Base : rc40 (`a7a8448`, production). Version : `VERSION = "9.2-rc41"` dans `app/app.py` (aucun autre fichier de version).

| Changement | Détail |
|---|---|
| Tolérance de sous-facturation supprimée | `UNDER_TOLERANCE = 0.0` : facturer moins **ou** plus que les jours travaillés de la période est un écart du contrôle 12 (dérogation motivée possible). |
| Exception « STC GEM » | Pour ce mandat seul : aucun contrôle ne bloque l'émission, écarts affichés et tracés (« exception STC GEM »), PDF et montants inchangés. |
| Tarif modifiable (STC GEM) | Champ de tarif dans l'éditeur du brouillon, validé, audité, figé avec la facture ; factures existantes inchangées. |
| Réglage | `BILLING_EXCEPTION_MANDATES` (défaut « STC GEM » ; vide = désactivé ; `id:<n>` possible). |
| Migration | **Aucune.** |

À faire avant déploiement (par le propriétaire / superviseur) : lancer la suite complète en conteneur de test (`tests/test_rc41_stc_gem.py` + suite existante), vérifier le nom exact du mandat en production (ou fixer `id:<n>`), commit, copie figée `9.2-rc41-<commit>`. Détails, désactivation et retour arrière : `docs/FACTURES-EXCEPTION-STC-GEM.md`.
