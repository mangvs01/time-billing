# RC25 — contrôle 14 et acomptes contractuels
Date : 2026-10-09
Statut : analyse réalisée ; aucun changement de règle de facturation appliqué

## 1. État constaté dans le code candidat `1ca5578`

- `app/invoice_checks.py` définit actuellement **13 contrôles** ; le contrôle 14 n'existe pas comme contrôle autonome.
- Les contrôles 12 et 13 sont dérogeables, avec un motif écrit propre à chaque contrôle en échec.
- `app/app.py` autorise déjà un reliquat négatif (facturation au-delà du travail réalisé ou déjà facturé) si le formulaire contient `negative_reliquat_reason` avec au moins 10 caractères.
- Le motif est conservé dans `reliquat_note` sur la facture figée et dans le journal d'audit append-only (`invoice_negative_reliquat_exception`).
- Cette voie est une exception motivée de facturation anticipée, mais elle n'identifie pas formellement un acompte contractuel et ne vérifie pas un plafond contractuel d'acomptes ni leur amortissement sur les factures suivantes.

## 2. Risque de la règle actuelle

Un motif écrit prouve qu'un utilisateur a justifié l'exception ; il ne prouve pas qu'un acompte a été convenu, qu'il respecte le plafond contractuel, ni qu'il sera déduit ultérieurement. En l'état, la voie d'exception est donc plus large qu'un mécanisme d'acompte contrôlé.

**Recommandation : ne pas rendre le contrôle 14 globalement dérogeable.** Ne pas assimiler toute sur-facturation à un acompte autorisé.

## 3. Modèle cible recommandé

1. **Type explicite de document :** facture ordinaire ou facture d'acompte contractuel. Une facture ordinaire reste soumise au contrôle 14 sans dérogation.
2. **Fondement obligatoire :** référence de contrat/PO ou clause d'acompte, motif écrit et auteur/date conservés dans l'audit.
3. **Plafond contrôlé :** l'acompte émis ne peut pas dépasser le plafond contractuel enregistré, diminué des acomptes antérieurs encore non amortis.
4. **Comptabilisation séparée :** le montant d'acompte reste dans un solde d'acomptes à amortir ; il ne gonfle pas les jours de prestations réalisées ou les jours facturés de prestations.
5. **Amortissement explicite :** chaque facture de prestations peut imputer tout ou partie du solde d'acompte ; l'imputation est atomique, tracée et ne peut pas être appliquée deux fois.
6. **Documents immuables :** le PDF d'acompte et les factures émises restent figés ; une correction passe par un document correctif, jamais par la modification rétroactive.
7. **Annulation / remboursement :** les règles d'annulation et de remboursement doivent préserver le solde d'acomptes et empêcher une double récupération.
8. **Restauration et concurrence :** les sauvegardes doivent conserver les acomptes et imputations ; les émissions simultanées ne doivent pas dépasser le plafond ni consommer deux fois le même solde.

## 4. Tests requis avant de livrer cette fonction

- acompte dans le plafond, exactement au plafond et au-delà du plafond ;
- absence de clause/référence contractuelle ;
- plusieurs acomptes, acomptes partiellement amortis et solde nul ;
- imputation totale et partielle sur une facture de prestations ;
- double imputation concurrente, émission concurrente et rejeu de requête ;
- annulation/refus de note de crédit après imputation, remboursement et réémission ;
- restauration, retour arrière, intégrité des PDF figés et continuité du journal d'audit ;
- vérification que le tableau des jours réalisés/facturés et le reliquat de prestations ne comptent pas l'acompte comme du travail.

## 5. Décision de livraison

La présente décision autorise **l'étude et la spécification**, pas l'activation d'une dérogation générale au contrôle 14. La règle métier finale, le plafond et la méthode d'amortissement doivent être validés avant d'implémenter une migration ou de modifier l'émission des factures.

Jusqu'à cette validation, RC25 reste NO-GO pour la production. Aucun changement de base ni déploiement n'a été effectué.
