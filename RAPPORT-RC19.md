# Time Billing V9.2-rc19 — saisies toujours éditables, facture émise immuable (2026-10-05)

Demande : « LES SAISIES NE DOIVENT JAMAIS ÊTRE VERROUILLÉES PARCE QU'ELLES SONT ANCIENNES OU DÉJÀ FACTURÉES » ; la facture émise
reste IMMUABLE ; écart post-facturation visible ; audit avant/après ; décision laissée à l'utilisateur (avoir, compensation, rien).
Conception détaillée (version implémentée, après relecture contradictoire par 4 critiques) : `CONCEPTION-RC19.md`.

## 1. Ce qui a été modifié
| Domaine | Avant (rc18) | rc19 |
|---|---|---|
| Saisie importée (2 247) | verrouillée (seule l'annulation du lot la retirait) | modifiable, réaffectable, supprimable ; provenance affichée et conservée (fichier, onglet · ligne, lot, date d'import, valeurs lues dans le classeur) ; durée déclarée conservée tant que début/fin ne changent pas |
| Saisie d'un mandat clôturé | verrouillée (rouvrir le mandat) | modifiable et supprimable sans rouvrir ; nouvelles saisies toujours refusées ; vers un AUTRE mandat clôturé : case explicite + motif |
| Saisie facturée | verrouillée (application + 2 déclencheurs + clé étrangère) | modifiable et supprimable avec avertissement explicite, motif et confirmation (liée aux factures affichées) ; facture émise strictement inchangée ; écart post-facturation affiché |
| Audit | avant/après, date | + utilisateur, motif, factures concernées (rôle) ; journal en JSON ; trace posée par la base elle-même pour toute écriture sur une saisie, même hors application ; historique consultable même après suppression |
| Décision | — | registre en ajout seul : note de crédit émise / compensation / aucune action, motif, utilisateur, lié à l'écart (une nouvelle correction le rend caduque) |
| Suggestion / émission | — | heures déjà facturées (date reclassée) exclues de la suggestion ; écran d'émission : avertissement si des saisies facturées ont été corrigées (l'annexe cumulative les reprendra) |
| Annulation d'un lot d'import | — | refusée si une saisie du lot a été corrigée depuis l'import (corrections protégées) |
| Identifiants | réutilisables par l'import | jamais redonnés (allocateur unique + déclencheur) |
| Restauration JSON | saisies annexées figées | traçabilité exigée : saisie annexée égale à sa ligne figée ou expliquée par l'historique ; aucune résurrection |
| Retour arrière (90) | écrase la base | copie vérifiée de la base vivante ; refus si des corrections/décisions seraient perdues, sauf `ABANDONNER_CORRECTIONS=OUI` |
Aucune modification esthétique : classes CSS existantes uniquement (`_ds.html` et `_style.html` inchangés), libellés et identifiants existants conservés.

Schéma (migration automatique, idempotente, une transaction, sauvegarde préalable par la procédure) : clé étrangère
`invoice_annex_entries.entry_id → entries` retirée (reconstruction de la table, lignes identiques), déclencheurs `annexed_entry_*`
remplacés par des déclencheurs de traçabilité, 3 colonnes nullables dans `entry_changes`, table `invoice_variance_decisions`, index.
Aucune ligne de `entries` n'est écrite par la migration.

## 2. Tests ajoutés et résultats (image candidate rc19, copies jetables ; jamais le staging réel)
| Suite | Résultat |
|---|---|
| Unitaires (`tests/test_rc19.py` : 25 nouveaux tests + adaptations rc10/import/readonly/security/version) | **401/401** |
| Lot R nouveau (`tests/recette_fonctionnelle/run_rc19.py`, copie des données réelles : les 2 247 saisies importées ouvrent un formulaire actif, R1–R10 de la demande) | **49/49** |
| Lots HTTP A–K, prévision, Q (A et D/E adaptés à la règle rc19) | **303/303** |
| Lots M, N, L (mandats préparés, première facture réelle) | **32/32** |
| Navigateur (Chromium) : métier, saisies (adaptée), adaptatif, rc12, rc14, nuit, minuit, **rc19 (nouveau, bureau + téléphone)**, e2e, concurrence | **427/427**, 0 erreur console |
| Répétitions de bascule : A (copie prod V9.0) → rc19 → V9.0 ; B (V9.0 fictive, factures héritées) ; **C (copie staging rc18 avec 2 factures réelles émises, 2 processus, retour refusé puis forcé)** | **GO / GO / GO** |
Correspondance avec la recette demandée : 1 saisie historique importée (`test_R1…`, R1a–R1d, navigateur §1) · 2 début/fin
(`test_R2_R3_R4…`, R2) · 3 durée (R3) · 4 description (R4, dont durée déclarée préservée) · 5 mandat clôturé (`test_R5…`, R5a–R5f) ·
6 saisie déjà facturée (`test_R6…`, R6a–R6f) · 7 facture strictement inchangée (ligne, copie figée, liens, PDF, archive ZIP : R7a–R7b) ·
8 écart visible (message, historique des factures, page d'écart, tableau de bord : R8a–R8e) · 9 audit avant/après (R9a–R9c) ·
10 un avoir corrige ensuite la situation (R10a–R10g : note de 0,0625 j, écart restant 0, décision enregistrée, alerte levée).

## 3. Comportement exact d'une saisie post-facturation (exemple de la demande)
Saisie 5 h facturée par F (0,625 j). Sur sa page : encadré « Saisie déjà facturée par la facture émise F (période …) … la facture
émise ne sera pas modifiée … », motif obligatoire, case « Je confirme : la facture émise F reste inchangée… ». Correction à 4,5 h :
- F reste à 5 h : ligne, PDF, annexe et montants identiques octet pour octet ;
- saisie actuelle 4,5 h ; position du mandat recalculée (réalisé −0,0625 j, facturé inchangé) ;
- message « Attention : saisie facturée — la facture F reste inchangée… Écart post-facturation de F : −0,50 h (−0,0625 j, facturé en
  trop)… À décider ensuite : note de crédit (avoir), compensation, ou aucune action » ;
- historique : avant 5 h / après 4,5 h, date-heure, utilisateur, motif, « facturée par F » ; journal d'audit (JSON) + trace en base ;
- Factures émises : ligne « Écart post-facturation : −0,50 h (−0,0625 j) … décision à prendre » ; tableau de bord : encadré d'alerte ;
- page d'écart : 5,00 h figées, 4,50 h actuelles, −0,50 h, −40,63 CHF indicatifs (−50,00 CHF à 800 CHF/j) ; proposition de note de
  crédit de 0,0625 j calculée par le serveur (rien n'est émis automatiquement) ;
- une fois la note émise : « écart restant après ces notes : 0 » ; l'utilisateur enregistre « note de crédit NC-… » → alerte levée.
Suppression d'une saisie facturée : mêmes garde-fous ; la facture garde son lien et sa copie figée ; écart = − la durée facturée.
Date corrigée dans le même mandat : les heures restent facturées par F (« date reclassée », pas de double facturation : exclues de la
suggestion suivante). Changement de mandat : écart − la durée sur F. Saisie seulement listée par l'annexe cumulative d'une facture
(antérieure à sa période) : simple information, pas de motif exigé.

## 4. Comportement exact d'un mandat clôturé
- nouvelle saisie : refusée (« le mandat … est clôturé ») ;
- saisie existante : modifiable (date, début, fin, durée, description) et supprimable sans rouvrir le mandat ; il reste clôturé ;
- la déplacer vers un mandat actif : permis (avertissement : position de clôture modifiée) ;
- la déplacer vers un AUTRE mandat clôturé : refusé par défaut ; permis avec la case « Rattacher à un mandat clôturé » et un motif
  (avertissement : heures non facturables tant qu'il reste clôturé) ;
- ajouter une saisie oubliée : rouvrir puis reclôturer le mandat (tracé), comme avant.

## 5. Statut
Voir la section « Déploiement staging » ci-dessous (complétée au déploiement). Production : NON touchée (empreinte `bd31f410…`,
conteneur `0b25a343…` démarré le 02.10.2026, identiques avant et après).

## 6. Limites connues et prochaine étape (RC20)
- Les factures émises AVANT l'application (historique Excel) ne sont pas connues : aucun écart n'est calculé pour elles (proposition
  RC20 : date « facturé hors application jusqu'au » par mandat).
- Compensation par note de crédit impossible sur un mandat sans identifiant juridique client (cas des 5 mandats actifs : C2) ; la page
  d'écart le dit et propose d'ajuster la prochaine facture.
- Retour arrière : seul `90-rollback.sh` est pris en charge ; il refuse désormais d'écarter des corrections sans confirmation explicite.
- L'application a un compte unique : « utilisateur » identifie ce compte, pas une personne.
- Prochaine étape RC20 (à décider par l'utilisateur) : faire valider le comportement rc19 sur le staging ; option « saisie oubliée
  sur mandat clôturé » sans réouverture ; cutoff de facturation historique ; puis autorisation séparée de bascule en production.
