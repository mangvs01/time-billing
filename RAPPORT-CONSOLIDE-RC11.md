# Time Billing V9.2-rc11 — rapport consolidé (04.10.2026)

Contient des références à des données réelles agrégées : ne pas publier. **Aucun import réel, aucun déploiement en production, aucune donnée source supprimée ou modifiée.** Production (V9.0, port 8091) : empreintes identiques avant/après (`audit/prod-fp-avant.txt`). Classeur source : SHA-256 `c93c610c…eddac438`, inchangé.

Cadre : autonomie accordée sur le staging et le dépôt local. Le staging tourne en **9.2-rc11** (déployé avec les scripts de la procédure). Dépôt : `/root/time-billing-v9-rc10-20261004`, commits locaux `3365991` (RC10) → `218956d` (RC11).

## 1. Recommandation

**Passer à la recette métier sur le staging en RC11 : oui.** La version est stable, testée de bout en bout, et le retour arrière est démontré. **Ne pas importer ni basculer en production avant** : (a) vos décisions du registre (§5) ; (b) votre autorisation explicite et séparée ; (c) la fenêtre de bascule décrite dans `PROCEDURE-DEPLOIEMENT-RC11.md` (qui corrige au passage des failles de la production actuelle, voir §6.2).

## 2. Fonctionnalités effectivement terminées et vérifiées

| Domaine | État |
|---|---|
| Saisie des heures | Début/fin ou durée directe ; liste, filtres, export CSV ; correction et suppression tracées (historique en ajout seul), verrouillage si annexe figée ou lot d'import ; **RC11 : avertissements non bloquants** (chevauchement horaire, jour > 12 h, date future ou hors période du mandat, brouillon à recalculer) |
| Mandats et bons de commande | Jours commandés/réalisés/facturés/disponibles, clôture/réouverture, prévision de consommation (somme des mois = jours restants × tarif, vérifiée sur PO épuisé/dépassé/échu/clos) |
| Émission de factures | Numérotation mensuelle sans doublon ni trou (24 émissions concurrentes), quantité non arrondie visible avant l'arrondi, reliquat à décision explicite, antidatage confirmé, TVA, ligne « AUTRES » ; **RC11 : refus d'une période déjà facturée à l'émission, de 0,00 CHF, d'un mandat sans tarif, d'une description qui serait tronquée ; bandeaux de dépassement de PO et d'émission hors ordre** |
| Notes de crédit | Partielles/totales, remboursements, compensations, annulation + remplacement, plafonds ; **RC11 : tarif identique à la facture, remboursement jamais antérieur à la note, libellés heures/jours** |
| Annexes cumulatives, archivage, immutabilité | Annexes figées, 32 déclencheurs SQLite, PDF servis uniquement depuis la copie figée (SHA-256), archive ZIP (index + sommes) |
| PDF | Quantité imprimée avec toutes ses décimales (quantité × prix = montant imprimé) ; pagination, accents, CHF vérifiés |
| Sauvegarde / restauration | Sauvegarde SQLite à chaud + vérification de restaurabilité (conteneur sans réseau) ; JSON complet restaurable **même au-delà de 15 Mo** (RC11) ; la restauration ne déconnecte plus et n'embarque plus les sessions ; refuse tout fichier qui modifierait un document émis ou **ajouterait** des saisies à une annexe figée |
| Import historique | Prévisualisation, décisions ligne à ligne, rollback de lot ; **RC11 : refus d'import dans un mandat clôturé** |

## 3. Défauts corrigés dans cette étape

QA fonctionnelle indépendante sur RC10 (agent distinct, 199 contrôles, données fictives, conteneurs jetables) : 0 bloquant, **6 majeurs**, 14 mineurs, 5 de confort (`audit/qa-rc10/RAPPORT-QA.md`).

* **Majeurs, tous corrigés** : QA-01 double facturation d'une même période · QA-02 tarif d'un brouillon réécrit par une simple édition · QA-03 sauvegarde JSON non restaurable au-delà de ~80 factures · QA-04 quantité imprimée arrondie à 2 décimales · QA-05 historique d'un brouillon/saisie supprimé rattaché au suivant (identifiants réutilisés) · QA-06 description tronquée en silence sur le PDF figé.
* **Mineurs corrigés (11/14)** : QA-07, 08, 10, 11, 12, 13, 16, 17, 18, 19, 20 (+ QA-S1, annexe ajoutée par restauration forgée).
* **Atténués, non corrigés** : QA-14 (le reliquat « reporté » n'est pas ajouté automatiquement à la quantité suggérée : texte d'aide corrigé), QA-15 (émission hors ordre : bandeau d'avertissement), QA-09 (saisie perdue après un refus de formulaire), QA-22 (espaces dans les motifs d'annexe : corrigé au rendu ; troncature « … » conservée).
* **Ouverts, confort** : QA-21 (adresse très longue qui déborde du PDF), QA-23 (saisie à cheval sur minuit à scinder à la main ; durée naïve aux 2 changements d'heure), QA-24 (numéro annoncé pouvant différer si deux émissions concurrentes), QA-25 (dernier écrit gagne sur une même correction ouverte dans deux onglets), QA-S2/S3 (durcissements SQL de défense en profondeur).
* Rejeu des scénarios QA sur le code corrigé : les échecs restants sont ces points ouverts et 5 artefacts de test (dates antérieures à la note de crédit, désormais refusées à raison).

Sécurité (chantier prioritaire, voir §6) : CSP sans `unsafe-inline`, déconnexion POST, conteneur non-root, dépendances épinglées, CVE Flask corrigée.

## 4. Résultats des tests (RC11)

| Contrôle | Résultat |
|---|---|
| Suite unitaire/fonctionnelle (18 modules, conteneur sans réseau, utilisateur non privilégié) | **308/308** (`journaux/unit-rc11-complet.log`) dont 27 nouveaux tests RC11 (CSP, déconnexion, régressions QA) |
| Recette navigateur sur l'image déployée (Chromium, données fictives) | métier 107 + 15 · saisies 34 + 7 · responsive 33 pages sans défaut, 0 erreur console → **0 échec** |
| HTTP de bout en bout (2 phases + redémarrage) ; concurrence gthread | 30 + 18 ; 11/11, **0 échec** ; rejoué aussi sous `--read-only --cap-drop ALL` : 48/48 |
| Recette d'import RC11 (sans import réel) | simulation ×2 identique · réconciliation (2 297 lignes = 2 282 saisies + 15 totaux) · audit indépendant 25/25 · e2e 48/48 · Chromium 71/71 (classeur réel **refusé**, import + rollback sur classeur fictif) · production, staging et classeur inchangés |
| Migration à blanc (copie de la base de production ; V9.0 avec factures fictives) | V9.0 → RC11 → **retour V9.0** : GO, vérifications avant et après redémarrage, base = sauvegarde (SHA-256 identique) ; texte des PDF figés identique à V9.0 (le brouillon est rendu avec la nouvelle mise en page, attendu) |
| QA fonctionnelle | 199 contrôles ; voir §3 |
| `pip-audit` sur l'image RC11 | aucune vulnérabilité connue (14 sur RC10 : Flask 3.1.1, pip) |

## 5. Données historiques : qualité, cohérence et arbitrages

Source : 2 297 lignes = **2 282 saisies (1 958,45 h)** + 15 totaux ; 154 lignes vides du modèle ignorées ; chaque ligne dans un seul état terminal, simulation reproductible, aucun doublon d'identifiant.

| Ensemble | Lignes | Heures | Montant HT indicatif* |
|---|---|---|---|
| **Prêtes** (déterminées) | 2 150 | **1 856,15** | ≈ CHF 93 645 sur 1 152,55 h à tarif connu ; 703,60 h sans tarif connu |
| Exclues (décisions 1–2, copies/doublons exacts) | 31 | 21,75 | — |
| En attente | 101 | 80,55 | voir ci-dessous |

\* journée = 8 h (défaut de l'application) ; tarif = celui du SUIVI quand le nom du projet est **identique** à une ligne du SUIVI, jamais deviné ; HT, hors TVA, hors plafond de PO.

**Registre final (`import/registre-final/REGISTRE-FINAL-DECISIONS.md`, CSV `decisions-finales.csv`)** — classement demandé :

* **Automatiques (aucune action)** : exclusion des 31 copies/doublons, 15 totaux, 40 durées exactes, aucune fusion de noms, 4 lignes du 23.10.2026 mises en attente sans date inventée, 2 150 lignes prêtes.
* **Recommandées (une réponse en bloc)** : **R1** règle de date « année et mois de l'onglet » pour 32 lignes (+21,50 h) — recommandation : valider ; **R2** conséquence automatique de R1 sur 10 lignes en chevauchement (+9,00 h) ; **R3** création des **15 mandats certains** avec les paramètres du SUIVI (1 173,35 h) — vous validez le tableau `valorisation-par-regroupement.csv`.
* **Obligatoirement soumises à vous** : **M1–M3** mandat des **21 noms non certains** (5 ambigus, 7 partiels, 9 absents du SUIVI : 721,40 h) ; **M4** six lignes métier (0,25 à 4 h chacune ; 8,75 h au plus) ; **M5** treize journées de chevauchement (18,35 h en double potentiel ; recommandation : conserver) ; **M7** autorisation d'import, séparée.
* **Information** : cinq mandats certains dont les jours réalisés dépassent les jours commandés du SUIVI (35,78 j au-delà, ≈ CHF 23 257 à leurs tarifs) : constat à confirmer (plusieurs POs successifs ? journée ≠ 8 h ?). Aucune donnée modifiée.

Limites : aucun mandat n'existe encore, donc les montants ne sont pas rapprochés de vraies factures ; la règle de date (32/32) est corroborée mais non démontrée ; les décisions 1–5 déjà prises ne sont pas datées/signées dans les documents.

## 6. État de sécurité

### 6.1 Constats de l'audit (SEC-01…15) après RC11
Corrigés : **SEC-01** immutabilité à la restauration (+ cohérence des annexes, RC11) · **02** redirection ouverte · **03** XSS stocké (suppression du sink, puis CSP à nonce : plus de script en ligne autorisé) · **04** déni de service par connexions lentes (gthread) · **05** limitation de tentatives (par /64 IPv6) · **06** logo (bombe de décompression) · **07** bornes numériques · **08–09** validation de restauration/import, limites de lignes · **10** en-têtes (HSTS sous HTTPS, Permissions-Policy, CSP) · **11** sessions révocables côté serveur, durée absolue · **12** `/logout` en POST · **13** conteneur non-root, lecture seule, sans capacité, `no-new-privileges`, dépendances épinglées (`requirements.lock`) · **CVE** Flask.
Restent (faibles) : POST sans `Origin` ni `Sec-Fetch-Site` accepté (seuls des clients non navigateurs, `SameSite=Lax` s'applique) · `/health` public affiche la version · image de base non épinglée par empreinte · sauvegardes `pre-restore-*` sans plan de rétention (constat d'audit, non retesté) · `style-src 'unsafe-inline'` conservé (attributs de style) · mono-utilisateur sans rôles.
Non couvert (hors périmètre autorisé) : TLS/Caddy, DNS, pare-feu, SSH.

### 6.2 Risques de la production **actuelle** (V9.0, non modifiée)
Mot de passe en clair dans le compose, écoute sur `0.0.0.0:8091` ; V7/V8/V30 encore actives sur 8088–8090 avec des mots de passe partagés. La procédure RC11 y remédie (secrets par `.env` 600, écoute locale, rotation) mais **elle nécessite le plan Caddy/DNS/pare-feu et votre validation** (`procedure/caddy-time-billing.example`, `pare-feu-proposition.md`) : je n'ai rien touché.

## 7. Sauvegarde et retour arrière

* **Avant toute migration** : `20-backup.sh` arrête le service, copie la base, l'arborescence, l'image (`:pre-rc11-<TS>`), SHA-256 ; `30-rehearse.sh` rejoue la migration sur une copie (GO/NO-GO) ; `40-deploy.sh` ; `50-verify.sh` (avant et après redémarrage : santé, en-têtes, CSP, non-root, lecture seule, écoute locale, intégrité, copies figées, secrets absents des journaux).
* **Retour arrière** `90-rollback.sh` : joué réellement sur le staging (RC11 → RC10, base identique octet pour octet, ancienne version non-root/root compatible) et sur les migrations à blanc (V9.0). Scripts adaptés à toute RC : tag dérivé de `VERSION`.
* **Exploitation** (non installée) : sauvegarde à chaud quotidienne + vérification hebdomadaire (`OPERATIONS-RC11.md`) ; **une copie hors serveur reste à organiser par vous**. Sauvegarde JSON : rappel à 30 jours. Rollback d'un lot d'import : bouton, refusé si une facture émise couvre une prestation du lot.

## 8. Risques résiduels

1. Production exposée tant que la bascule n'est pas faite (§6.2).
2. Aucun mandat réel : montants non rapprochés de factures réelles ; hypothèse « jour = 8 h » à confirmer.
3. Décisions de reprise non prises (§5) ; une facture émise sur un projet importé empêche le rollback du lot : **ne rien facturer avant validation de l'import**.
4. Points ouverts de confort (§3) ; QA-09 peut faire perdre une saisie après un refus de formulaire.
5. Taille des sauvegardes : ~180 Ko par facture (PDF + annexe cumulative) — surveiller l'espace et la copie hors serveur ; limite Caddy `/restore` à régler (≥ 200 Mo).
6. Sessions parallèles de Claude sur le même serveur : coordination par `NOTE-SESSIONS-PARALLELES.md` ; le staging a été redéployé par cette session (sauvegardes `pre-rc11-*` conservées).
7. Fonctionnement non éprouvé derrière le vrai Caddy HTTPS (cookies `Secure`, `TRUST_PROXY=1`).

## 9. Pour la recette métier (staging, mot de passe inchangé)

Parcours conseillé : créer un mandat de test → saisir des heures → brouillon → émettre → note de crédit/remboursement → annexe, PDF, archive ZIP → sauvegarde JSON et SQLite. Supprimer ensuite les données de test avant tout import (bouton rollback ou restauration de `pre-rc11-*`). Puis répondre au registre (§5).
