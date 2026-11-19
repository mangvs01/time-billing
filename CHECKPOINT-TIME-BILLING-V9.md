# CHECKPOINT — Time Billing V9.2 (mis à jour 2026-10-05, ~10:20 UTC — TOUTES les décisions C1–C6 tranchées et appliquées, rc18 sur staging)

> **2026-10-06 ~21:10 UTC** : chantier G4 (D1–D10, revue de fidélité) en cours, non commité, non déployé. État, résultats de tests et décisions à prendre : `REPRISE-G4.md`, section « ÉTAT COURANT ». Le présent checkpoint décrit l'état du 2026-10-05.

Établi à partir de l'état **réellement vérifié** (serveur, base, conteneurs, code, tests rejoués), pas des rapports précédents.
Dépôt : `/root/time-billing-v9-rc10-20261004`, branche `design-liquid-glass-rc14`, local, non fusionné, non poussé. Rapport de recette : `RAPPORT-RECETTE-RC16.md`. Décisions : `import/MANDATS-DECISIONS-UTILISATEUR.md`. Données mandats : `import/MANDATS-A-COMPLETER.csv`.

# ÉTAT ACTUEL

| | |
|---|---|
| Staging `:8092` | **9.2-rc18** (commit d57c9b7), sain, 50-verify conforme ; mandats « niveau certain », paramètres émetteur et **décision C2** (NHAF 2026 + EUROPCR 2027 : EGG BE, Jette, TVA 0 %) appliqués. **19 mandats clôturés / 5 actifs (C1)**. Sauvegardes : `pre-mandats-*`, `pre-emetteur-*`, `pre-rc17-20261005T094522Z`, `pre-c2-20261005T094622Z`, `pre-rc18-20261005T100203Z`, `pre-c1-20261005T100700Z` |
| Production `:8091` | V9.0, **non touchée** : conteneur `0b25a343…`, 0 redémarrage, base `bd31f410…f6d6`, `/health` 9.0-rc1 |
| Sessions concurrentes | aucune sur Time Billing |

## TERMINÉ
## C1 + C3 APPLIQUÉS (2026-10-05 ~10:07 UTC, décision utilisateur : C1 OUI, C3 validé)
- **C1** : 19 mandats clôturés sur le staging par l'application (conteneur d'écriture éphémère, staging arrêté ~1 min, sauvegarde vérifiée `pre-c1-20261005T100700Z.db` SHA-256 OK), motif exact « Terminé selon le SUIVI 2025/2026 ; facturé hors application (historique importé) ». État vérifié en base : 19 inactifs / 5 actifs (EUROPCR 2027, MSD, NHAF 2026, PCR LV 2026, STC GEM Oct - DM job) ; 19 événements d'audit `project_closed` ; 0 facture ; 0 avoir. La liste de saisie ne propose plus que les 5 mandats actifs ; les clôtures sont réversibles (« Rouvrir », testé lot M).
- **C3** : ECIO 2025 clôturé (C1), tarif 0 non modifié, aucun statut « offert », aucune facture : « non facturé — tarif historique non retrouvé ».
- **Prévision** : 27 050 CHF (5 850 PCR LV 2026 + 10 400 NHAF 2026 + 10 800 STC GEM Oct), au lieu de 134 521 CHF ; tableau de bord : 6 762,51 CHF restants sur 2026 (3 mois sur 12). Recalcul indépendant K identique au centime.
- **Saisies** : table `entries` toujours identique ligne à ligne (toutes colonnes) à `pre-mandats-20261005T090824Z` : 2 247 / 1 934,4987 h ; 31 doublons exclus et 3 exceptions non touchés ; production inchangée (`bd31f410…`, conteneur `0b25a343…`).
- **Lots rejoués après C1 (copies jetables du staging post-C1)** : M 10/10, N 3/3, L 19/19, K 21/21 (K adapté : état réel 19/5 + total 27 050 vérifiés, puis la copie est rouverte pour les cas limites), A+B 55/55, C–G 94/94, D–E–G 53/53 (DH0 : PCR LV 2025 rouvert par l'application avant de facturer un mandat historique), extra 23/23, H–I–J 37/37 + **Q 18/18 (nouveau)** ⇒ **HTTP 333/333** ; unitaires **376/376** ; répétition de bascule V9.0 → rc18 → V9.0 sur 2 bacs à sable (copie de la base de prod + jeu fictif) : **GO**, retour arrière SHA-256 identique, production inchangée. Parcours navigateur de la base post-C1 : 7 onglets sans débordement ni erreur console.

## MIS À JOUR AVEC LES RÉPONSES DE L'UTILISATEUR (2026-10-05)
- **C4 OUI** : 1 jour = 8 h par défaut ; vérifié en base : 24 mandats sur 24 à 8 h ; aucun mandat historique ne démontre une autre base (154/154 totaux de feuilles à 8,0 h/j).
- **C5 OUI — implémenté (rc17 → rc18)** : une saisie 22:00 → 02:00 = **UNE** ligne de 4 h, rattachée au jour de début, sans scission ; chevauchement contrôlé d'un jour à l'autre ; avertissement « passant minuit » et avertissement de changement d'heure (la durée reste calculée sur l'horloge murale) ; marqueur « (+1 j) » dans la liste ; aperçu de durée corrigé dans les deux formulaires. Fin = début reste refusée. Import historique inchangé (les lignes source fin < début restent des exceptions, C6).
- **C6 OUI** : OCT!93, OCT!94, JUL 26!39 conservées comme exceptions documentées, non importées.
- **C2 OUI pour NHAF 2026 et EUROPCR 2027** : appliqué sur le staging (raison sociale, contact, adresse ; TVA 0 % déjà en base). **PCR LV 2026, STC GEM Oct, MSD : champs entité/adresse/TVA laissés vides** (aucune source).
- **C1 et C3 : appliqués ensuite (voir ci-dessus).** C3 : recherche exhaustive faite, **aucun tarif historique retrouvé** pour ECIO 2025 (voir `import/MANDATS-DECISIONS-UTILISATEUR.md`) ; rien n'est facturé ni offert.
- **Défaut trouvé et corrigé pendant la mise en œuvre** : rc17 (déployée ~10 min sur le staging) contenait une erreur de syntaxe JavaScript dans l'aperçu de durée de l'onglet Saisie (`let` dans une déclaration `const`), qui neutralisait tout le script de la page ; non vu par les tests unitaires, vu par la recette navigateur ; corrigé en **rc18** et redéployé. Aucune donnée touchée.
- **Recettes rejouées sur rc18** : unitaires **376/376** (dont 15 nouveaux tests de saisie passant minuit) ; HTTP A–K **275/275** (A+B 55, C–G 94, D–E–G 52, extra 23, H–I–J 37, K 14) + M 10/10 + N 3/3 + L 19/19 = **307/307** ; navigateur **387/387** (372 + 15 du nouveau lot « minuit » bureau + téléphone).
- Saisies : table `entries` **identique ligne à ligne (toutes colonnes)** à la sauvegarde `pre-mandats-20261005T090824Z` (2 247 / 1 934,4987 h). Remarque : l'empreinte « 7a154f1f… » citée plus haut utilisait une autre méthode de hachage ; la comparaison de référence est désormais ligne à ligne et `lib.entries_digest` = `93a442b1…`.

- **Import historique** : gelé et revérifié (voir section dédiée) ; empreinte des saisies `7a154f1f…` identique avant/après toutes les écritures de cette phase.
- **rc16** déployée sur staging : une ligne déjà importée ne peut plus être forcée en doublon. *RECTIFIÉ le 2026-10-06 (constat B4 de la revue de fidélité G4) : en rc16-rc19, seulement depuis le même fichier à l'octet près (même sha256) ; une copie ré-enregistrée ou complétée du classeur peut réimporter les mêmes lignes. Corrigé dans l'arbre de travail le 2026-10-06 (identité de ligne par onglet, ligne et valeurs ; non déployé).*
- **Mandats préparés** : CSV de 24 mandats (30 colonnes, source/certitude par valeur) + document de décisions regroupées. 7 mandats complétés sur le staging avec des valeurs certaines ; **paramètres émetteur** (vides jusque-là) renseignés depuis la facture de référence.
- **Analyses** : « 1 jour = 8 h » (154/154 lignes sources à 8,0 h/j) ; saisie passant minuit (refus volontaire documenté QA-23/T3, aucun cas historique).
- **Recette HTTP fonctionnelle : 306/306** (A–K + nouveaux lots L première facture réelle, M clôture/réouverture, N parcours de 62 pages) ; unitaires **361/361** ; navigateur **372/372** ; répétition de bascule V9.0 → rc16 → V9.0 : GO.
- Outils : `tests/recette_fonctionnelle/mandats_appliquer.py` (simulation par défaut, par les formulaires de l'application), `appliquer_emetteur.py`, `journaux/fonc/run_mandats_premiere_facture.sh`.

## EN COURS
Rien en cours d'exécution.

## BLOQUÉ (décisions de l'utilisateur, aucune ne bloque la recette technique)
- **C1** clôture des 19 mandats « TERMINE » · **C2** entité de facturation/TVA des 5 mandats actifs · **C3** ECIO 2025 (21,3 h) · **C4** « 1 jour = 8 h » · **C5** saisie passant minuit · **C6** 3 lignes d'import indéterminables.
- Mockup jamais fourni ; logo réel ; autorisations d'import en production / bascule.

## À FAIRE (priorisé)
1. Réponses C1–C6 → je régénère le CSV, applique (`--level all --close-termine`) et rejoue les lots M/N/L.
2. Recette utilisateur sur le staging rc16 (tunnel SSH `-L 8092:127.0.0.1:8092`).
3. Safari/iOS sur appareil ; logo réel ; PO/n° de projet de PCR LV 2026 et STC GEM Oct quand disponibles.
4. Fusion dans `main` après validation visuelle ; plan de bascule production (Caddy / DNS / pare-feu / secrets, `procedure/`).

# IMPORT HISTORIQUE (revérifié sur la base staging réelle, lecture seule)

| | Constaté |
|---|---|
| Saisies importées | **2 247** — 1 934,4987 h (≈ 1 934,50) — 24 mandats — 11 lots COMMITTED — 0 facture — intégrité ok |
| Source (hors 15 SUBTOTAL) | 2 282 lignes / 1 958,45 h (classeur inchangé, sha `c93c610c…`) |
| Doublons exacts exclus | 31 / 21,75 h |
| Exceptions | 3 / 2,20 h (OCT!93, OCT!94, JUL 26!39) + AVR!90 (0 h) |
| Écart | 0 ligne / 0,0000 h ; 21 mois et 24 mandats identiques au rapprochement indépendant `REEL2` |
| Période | **2025-01-06 → 2026-09-30** (et non 2025-06-01) |

# TESTS

**X/Y : unitaires 376/376 · HTTP fonctionnels 333/333 (post-C1, avec le nouveau lot Q) · navigateur 387/387 · bascule V9.0→rc18→V9.0 GO.**
Détail par lot dans `RAPPORT-RECETTE-RC16.md`. Fragiles : assertions de version codées en dur (`test_rc10.test_version_is_rc12`, `test_rc15.test_version`, `test_rc17.test_version`, à relever à chaque RC) ; la recette navigateur suppose une base fictive (la lancer avec `SRC_DB=…/pre-import-historique-20261005T014206Z.db`). Manquants : Safari/iOS ; charge longue ; retour staging rc18 → rc17 non rejoué (retour rc17 contient le défaut JS, donc rollback vers `pre-rc17`/rc16) ; pas de contrôle automatique de syntaxe JS dans les gabarits hors recette navigateur.

# MATURITÉ PAR DOMAINE

| # | Domaine | État | Preuve (rejouée) | Reste à faire |
|---|---|---|---|---|
| 1 | Historique / import | Terminé avec exceptions (C6 : conservées, non importées) | base : 2 247 / 1 934,4987 h / 24, 0 écart | – |
| 2 | Saisie des temps | Terminé (C5 : minuit en une saisie) | A : 42 contrôles ; 15 tests unitaires minuit ; 15 contrôles navigateur | – |
| 3 | Mandats | Terminé ; **C1 appliquée (19 clôturés / 5 actifs)** | B : 13 ; CSV 24 mandats ; 9 complétés (dont NHAF 2026, EUROPCR 2027 : C2) ; M : 10 (clôture) | PO/n° de PCR LV 2026 et STC GEM Oct ; entité de PCR LV 2026, STC GEM Oct, MSD |
| 4 | Prévision | Terminé ; **27 050 CHF après C1** (134 521 avant) | K : 21, recalcul indépendant au centime | – |
| 5 | Calcul des jours | Terminé | 154/154 lignes sources à 8 h/j ; 24 mandats à 8 h ; **C4 confirmé** | – |
| 6 | Arrondis | Terminé | C 10 + C+ 10 | – |
| 7 | Facturation | Terminé | C : 34 ; L : 19 (première facture réelle) | – |
| 8 | Numérotation | Terminé | AAAA-MM, 2ᵉ facture du mois, L6 | – |
| 9 | Annexes cumulatives | Terminé | D : 18 ; L14 (total mensuel = base) | – |
| 10 | PDF | Terminé (logo fictif) | J : 10 ; L7–L13 vs facture de référence | logo réel, libellé de ligne à saisir |
| 11 | Factures émises | Terminé | E : 22 | – |
| 12–14 | Avoirs / remboursements / compensations | Terminé | F : 49 | – |
| 15–16 | Archive / recherche | Terminé | G : 12 ; N : 62 pages | – |
| 17–18 | Backup JSON / restore | Terminé | H : 20 | – |
| 19 | Import Excel | Terminé (rc16) | I : 7 + 32 unitaires | – |
| 20 | Tests | voir TESTS | – | Safari/iOS |
| 21 | Responsive / mobile | Terminé (Chromium) | 33 pages × 3 formats | Safari/iOS |
| 22–23 | Authentification / sécurité | Terminé côté application | verrouillage 429, accès non authentifié refusé, CSP à nonce, uid 10001, déclencheurs append-only | secrets/Caddy/DNS/pare-feu au cutover |
| 24 | Prêt pour la production | **NO-GO** | – | voir PRODUCTION |

# BUGS CORRIGÉS
1. **rc16 — import** : une décision *importer* sur une ligne déjà importée créait un doublon ; bloquant maintenant (test unitaire + recette HTTP). *RECTIFIÉ le 2026-10-06 (B4) : bloquant seulement pour le même fichier (même sha256) ; voir la rectification de la section ÉTAT.*
2. **Documentation** : mon checkpoint précédent écrivait que les factures de référence sont à 8,1 % ; **faux**, la facture de référence est à **TVA 0,00 %** (client belge) — corrigé.
3. Paramètres émetteur vides en staging (aucune émission possible) → renseignés depuis la facture de référence.

# BUGS RESTANTS
- Aucun défaut de code connu. Les échecs rencontrés lors de cette phase étaient des erreurs de mes scripts de test (quantité obligatoire, route inexistante, isolation du lot K), corrigées et rejouées.
- **Limite fonctionnelle** : pas de « solde d'ouverture » pour les jours facturés hors application (classeur) ; contournée par la clôture (C1). ~~Impact résiduel : STC GEM Oct - DM job affichera 18 j de solde au lieu de 11 (7 j déjà facturés le 27/04).~~ *RECTIFIÉ le 2026-10-06 (D2 = NON, N5, constat D-05) : les « 7 j facturés le 27/04 » n'étaient pas établis (`SUIVI 2026!M15` = doublon de `M8`) ; STC GEM Oct - DM job : 0 j facturé, solde 18 j correct. Le registre des factures historiques (G4, D1) remplace le « solde d'ouverture ».*
- Mineur : brouillon V9.0 re-rendu dans la nouvelle mise en page à la migration (attendu) ; assertions de version codées en dur.

# DÉCISIONS HUMAINES RESTANTES
**Aucune décision métier bloquante.** À fournir plus tard (non bloquant) : PO / n° de projet de PCR LV 2026 et STC GEM Oct ; entité de facturation de PCR LV 2026, STC GEM Oct et MSD ; tarif, PO, jours commandés de MSD et EUROPCR 2027 ; logo réel ; mockup. Autorisations séparées : import en production, bascule production. *(C1–C6 : tranchées et appliquées.)*

# PROCHAINE ACTION
Recette utilisateur sur le staging rc18 (tunnel SSH `-L 8092:127.0.0.1:8092`) ; Safari/iOS sur appareil ; fusion dans `main` après validation visuelle ; plan de bascule production sur autorisation séparée.

# PRODUCTION
**NO-GO** (aucun déploiement sans validation) :
- GO technique : rc18 saine, 0 défaut de code ouvert, migration V9.0 → rc16 répétée avec retour arrière identique.
- NO-GO tant que : validation visuelle / mockup, Safari/iOS non vérifié, logo réel absent, plan Caddy/DNS/pare-feu/secrets et import en production non autorisés.
- Production vérifiée inchangée.
