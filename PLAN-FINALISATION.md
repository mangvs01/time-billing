# Plan de finalisation — Time Billing V9.2 (état au 2026-10-05)

> Ce document est un **plan**. Rien n'y est exécuté en production. Aucun import réel, aucune modification de facture émise, aucun déploiement en production sans autorisation explicite et séparée de l'utilisateur.

Version sous recette : **9.2-rc15** (commit `c3b91cb`, branche `design-liquid-glass-rc14`, non fusionnée). Production : V9.0, :8091, inchangée.

## 0. Portes de passage

| Porte | Condition | Qui décide |
|---|---|---|
| G1 — Validation visuelle | Liste de retouches fermée, RC finale figée | Utilisateur |
| G2 — Recette | Sections 1 à 4 toutes vertes sur la RC finale | Vérifié par script + relecture utilisateur |
| G3 — Décisions d'import | R1, R3, M1–M5 répondues, T3, « jour = 8 h » | Utilisateur |
| G4 — Import réel | Autorisation écrite M7 (séparée), sauvegarde et rollback vérifiés | Utilisateur |
| G5 — Bascule production | Autorisation écrite séparée (Caddy/DNS/pare-feu/secrets) | Utilisateur |

Aucune porte ne s'ouvre implicitement : le silence n'est pas une autorisation.

## 1. Recette fonctionnelle complète

Exécutée sur la RC finale, sur une copie fictive (démo) puis sur le staging. Reprend `journaux/recette_navigateur_final.sh` (0 échec requis) et les tests unitaires (360/360 en rc15), complétés par une relecture manuelle guidée par l'utilisateur.

| Domaine | Parcours à valider | Automatisé | Manuel |
|---|---|---|---|
| Accès | connexion, déconnexion, session expirée, verrouillage après essais | oui | – |
| Saisie | début-fin, durée directe, correction, suppression tracée, verrouillage après émission | oui | ergonomie |
| Mandats | création, tarif, bon de commande, jours commandés, solde, clôture | oui | libellés |
| Prévisions | mensuelles / annuelles, jauge facturé vs prévision | oui | lisibilité |
| Facturation | période, arrondi (haut/bas/commercial), brouillon, édition, émission, numérotation, copie figée | oui | texte des mentions |
| Avoirs | partiel, total, remboursement, compensation, annulation, remplacement | oui | libellés |
| Archive | recherche, filtres, ZIP | oui | – |
| Import Excel | aperçu, validation explicite, annulation de lot (classeur fictif) | oui | – |
| Sauvegarde | export JSON, prévisualisation, refus d'une sauvegarde amputée, restauration sur copie | oui | – |
| Responsive | bureau 1440, tablette 820, mobile 390, sans débordement horizontal | oui | **Safari/iOS sur appareil** (non vérifié à ce jour) |

Critère de sortie : 0 échec automatisé, 0 anomalie bloquante en relecture manuelle, liste de retouches mineures tracée.

## 2. PDF et annexes

1. Générer, sur le jeu fictif, une facture émise, une annexe cumulative, un récapitulatif contractuel, un brouillon avec imputation d'avoir, un avoir de compensation, un avoir de remboursement (déjà produits dans `ecrans/pdf/`, à régénérer sur la RC finale).
2. Comparer avec `Facture-reelle-reference-2026-09.pdf` : structure, typographie, mentions légales, bloc de paiement, pagination.
3. Contrôles automatiques : nombre de pages, texte extractible (pas d'image), polices embarquées, absence de coupure de ligne dans les annexes (garde-fou QA-22), total PDF = total en base au centime.
4. Cas limites : annexe de plus de 2 pages, libellé très long, projet avec accents, montant à 0, avoir supérieur à la facture (doit être refusé).
5. Le **logo réel** de l'entreprise : fourni par l'utilisateur (celui des recettes est fictif).

## 3. Avoirs

1. Invariants : somme des avoirs d'une facture ≤ montant facturé ; une facture annulée ne reçoit plus d'avoir ; journal d'audit append-only (triggers SQL QA-S3).
2. Scénarios à rejouer : avoir partiel puis solde ; avoir total ; remboursement ; compensation sur facture suivante (imputation visible sur le PDF du brouillon) ; annulation puis remplacement ; double soumission (idempotence).
3. Vérifier la numérotation des avoirs (séquence sans trou, sans doublon) et l'immutabilité de la facture d'origine (hash/copie figée inchangé).
4. Réconciliation : pour chaque facture, `facturé − avoirs remboursés − avoirs compensés = solde` recalculé indépendamment (script SQL en lecture seule).

## 4. Calculs et arrondis

1. Jeu de tests croisé indépendant du code applicatif : recalcul en `decimal` des heures → jours (journée = 8 h, à confirmer), tarif/jour, remise éventuelle, arrondi, TVA, total.
2. Cas d'arrondi : 0,125 j, 0,5 j exact, 1/3 j, quantités non arrondies sur la facture, arrondi par ligne vs par total (la règle doit rester celle de la facture de référence).
3. Cohérence trois points : écran = PDF = base (au centime), pour 20 factures fictives générées aléatoirement avec graine fixe.
4. Heures : saisie à cheval sur minuit (**décision T3 en attente**), changement d'heure d'été/hiver, chevauchements.
5. Critère : 0 écart d'un centime sur le jeu complet ; toute divergence documentée avant toute décision.

## 5. Import historique Excel — préparation et rapport d'anomalies

État : registre `import/registre-final/` (données réelles, dossier 700, **non publié**). 2 150 lignes prêtes (1 856,15 h), 101 lignes en attente (80,55 h), 36 regroupements de projets (15 certains, 5 ambigus, 7 partiels, 9 sans équivalent).

Préparation (sans import réel) :
1. Dry-run sur **copie** de la base de production et sur le staging, jamais sur la production (`migration-blanc/setup-sandbox.sh`, `dry-run.sh`).
2. Rapport d'anomalies généré à chaque dry-run, au format CSV + synthèse : doublons, dates à corriger (R1), chevauchements (M5), lignes métier (M4), noms sans mandat (M1–M3), durées incohérentes, lignes sans tarif. Une ligne du rapport = une décision de l'utilisateur ou une règle automatique tracée.
3. Réconciliation obligatoire avant/après : lignes lues = lignes importées + lignes écartées (avec motif) ; heures lues = heures importées + heures écartées ; montants valorisés recalculés par regroupement.
4. L'import réel, quand il sera autorisé : en un seul lot nommé, avec aperçu, validation explicite, sauvegarde préalable vérifiée (SHA-256), et annulation de lot testée au préalable sur la même copie.
5. Les factures déjà émises ne sont jamais touchées : l'import n'écrit que des saisies et des mandats, jamais dans les tables de factures ou d'avoirs (contrôle par comptage avant/après).

Décisions attendues : R1 (règle de date), R3 (15 mandats certains), M1–M3 (21 noms), M4 (6 lignes), M5 (13 journées), T3, « jour = 8 h ».

## 6. Sauvegarde et bascule

Scripts existants (`procedure/`) : `10-preflight`, `20-backup`, `30-rehearse`, `40-deploy`, `50-verify`, `90-rollback`, `backup-quotidien`, `rotate-secrets`, plus `pare-feu-proposition.md` et `caddy-time-billing.example`.

Séquence de bascule (à n'exécuter qu'après G5) :
1. **T-7 j** : répétition complète sur copie de la production (dry-run V9.0 → RC finale → V9.0), résultat GO attendu.
2. **T-1 j** : gel des saisies annoncé ; sauvegarde JSON applicative + `20-backup.sh` ; hash SHA-256 relevé hors serveur ; test de restauration sur copie.
3. **T-0** : préflight → sauvegarde → déploiement → vérification (`50-verify.sh`) → contrôle manuel d'un parcours de bout en bout par l'utilisateur.
4. Domaine, TLS, pare-feu : plan séparé (Caddy HTTPS testé sur instance jetable, `journaux/test_https_proxy.sh`) ; le port 8091 et les autres services du serveur (AMO, LUMO, Chess) ne sont pas modifiés avant autorisation explicite.
5. Rotation des secrets après bascule (`rotate-secrets.sh`).
6. Surveillance 7 jours : santé, journal d'audit, sauvegarde quotidienne.

## 7. Procédure de rollback

Déclencheurs : échec de `50-verify`, écart de calcul, défaut bloquant constaté dans les 24 h.

1. Exporter d'abord les saisies faites depuis la bascule (JSON + `backup-quotidien.sh`) : le retour arrière remet la base d'**avant** la migration.
2. `90-rollback.sh` : contrôle `sha256sum -c` de la sauvegarde, arrêt du service, mise à l'écart (rien n'est supprimé), restauration du code, du compose, des secrets et de la base avec SHA-256 identique exigé, retour de l'image précédente, refus de démarrer si un secret d'origine manque, vérification de santé.
3. Vérifier : version affichée, SHA de la base, nombre de factures/avoirs identique à la sauvegarde.
4. Ressaisir les saisies exportées si besoin, après analyse.
5. Retour d'un **lot d'import seul** (sans toucher au reste) : fonction « annuler le lot », testée sur copie avant tout import réel.

Déjà éprouvé sur staging : RC11 → RC9, RC13 → RC12, RC14 → RC13. **Non rejoué : RC15 → RC14** (à faire avant G2).

## 8. Calendrier indicatif (sans date, dépend des décisions)

| Étape | Dépend de |
|---|---|
| Retouches visuelles → RC16 | Vos retours (G1) |
| Recette complète sur RC finale + rollback RC15 → RC14 rejoué | G1 |
| Dry-runs d'import, rapport d'anomalies | G3 |
| Fusion dans `main` | G1 + G2 |
| Import réel | G3 + G4 |
| Bascule | G4 + G5 |
