# Note de coordination (2026-10-04 ~02:55 UTC)
Une session Claude (compte 1, tâche « RC10 ») a déployé **9.2-rc10 sur le staging** (:8092) à 02:48 UTC via procedure/staging.conf
(sauvegarde `/root/backups/time-billing-v9-staging/pre-rc10-20261004T024826Z`, image de retour `:pre-rc10-20261004T024826Z`).
Une autre session (compte 2, tâche « clôture RC9 », `recette_rc9.sh`, SCRATCH=/tmp/rc9-reprise-*) tourne en parallèle : sa garde « staging = 9.2-rc9 » ne peut plus être vraie.
Ports/containers de la recette RC10 : tb-rc10f-* ; ports 8194-8198. La recette RC9 utilise tb-rc9-* et 8093.
Retour du staging en RC9 : `procedure/90-rollback.sh procedure/staging.conf` (restaure la base d'avant, identique SHA-256).

# Mise à jour (2026-10-04 ~10:45 UTC, session compte 2 « Time Billing V9 — autonomie élargie »)
- Dépôt local : RC11 en cours (commit d93f8b4 : CSP à nonce sans `unsafe-inline`, déconnexion POST, conteneur non-root/lecture seule, dépendances épinglées `requirements.lock`, Flask 3.1.3).
- Le staging (:8092) tourne toujours en 9.2-rc10 ; il sera redéployé en **9.2-rc11** par `procedure/*.sh procedure/staging.conf` (sauvegarde + image de retour automatiques). Merci de ne pas déployer/modifier le staging pendant ce temps ; si une autre session le fait, écrire ici avant.
- Conteneurs de test de cette session : préfixes `tb-qa-` et `tb-rc11-` ; ports 8201-8210.
- Aucun import réel, aucune action sur la production.

# Mise à jour (2026-10-04 11:37 UTC, session compte 2 « Time Billing V9 — mandat d'autonomie »)
- Dépôt local : RC12 (commits 1719371, c462d1f) : PDF sans débordement (QA-21), saisie conservée après refus (QA-09), jeton de version des corrections (QA-25), archive vide (QA-24).
- Le staging (:8092) va être redéployé en **9.2-rc12** maintenant (procedure/*.sh procedure/staging.conf : sauvegarde + image de retour automatiques). Ne pas toucher au staging pendant ce temps.
- Conteneurs de test de cette session : préfixes `tb-rc12-` et `tb-rc12f-` ; ports 8211-8225. Aucune action sur la production.

# Mise à jour (2026-10-04 12:2x UTC, session compte 2 « Time Billing V9 — autonomie élargie », RC13)
- Dépôt local : RC13 (annexe sans troncature QA-22, déclencheurs SQL QA-S3, verrou d'identité juridique QA-S2). Migration à blanc V9.0→RC13→V9.0 : GO (A13/B13).
- Le staging (:8092) va être redéployé en **9.2-rc13** maintenant (procedure/*.sh procedure/staging.conf : sauvegarde + image de retour automatiques). Ne pas toucher au staging pendant ce temps.
- Conteneurs de test : préfixes `tb-rc13-` / `tb-rc13f-`, ports 8226-8245. Aucune action sur la production.

# Mise à jour (2026-10-04 ~15:3x UTC, session compte 2 « Time Billing V9 — direction artistique », RC14)
- Branche locale `design-liquid-glass-rc14` : refonte visuelle (CSS/gabarits uniquement, aucun calcul modifié).
- Le staging (:8092) va être redéployé en **9.2-rc14** maintenant (procedure/*.sh procedure/staging.conf : sauvegarde + image de retour automatiques `:pre-rc14-<TS>`). Ne pas toucher au staging pendant ce temps.
- Conteneurs de test : `tb-rc14f-*` (ports 8260-8275), `tb-rc14-dev` (:8096), démo `tb-demo` (:8095, sera relancée sur l'image rc14). Aucune action sur la production.

# Mise à jour (2026-10-04 ~15:50 UTC) — session de NUIT RC14
- Une session Claude autonome tourne sous superviseur (`nuit/superviseur.py`) dans `tmux` (`timebilling-nuit`), avec reprise après quota à 23:20 WITA, branche `design-liquid-glass-rc14`, mission `nuit/MISSION-NUIT-RC14.md`. Elle peut redéployer le staging (procédure + sauvegarde). Conteneurs `tb-nuit-*` / `tb-nuitf-*`, ports 8300-8340. Merci de ne pas modifier ce dépôt ni le staging cette nuit.

# Mise à jour (2026-10-04 15:06 UTC) — session de NUIT RC14 (compte 2)
- Branche `design-liquid-glass-rc14` : 7 cycles commités (27e82b0 → 23e00c7), présentation seulement. Recette complète sur image locale tb-nuit:c6 : 0 échec.
- Le staging (:8092) va être REDÉPLOYÉ maintenant en 9.2-rc14 (procedure/*.sh procedure/staging.conf : sauvegarde + image de retour `:pre-rc14-<TS>`). Ne pas toucher au staging pendant ce temps.
- Ensuite : démo tb-demo (:8095) relancée sur la nouvelle image (mêmes données fictives). Conteneurs jetables tb-nuit-* / tb-nuitf-*, ports 8300-8340. Aucune action sur la production.

# Mise à jour (2026-10-05 ~00:40 UTC) — session de reprise « Time Billing V9 » (compte 2)
- Nuit RC14 terminée normalement (aucune session TB active). Branche `design-liquid-glass-rc14` : commit rc15 (position des mandats sur l'onglet Saisie, contraste des placeholders).
- Le staging (:8092) va être redéployé en **9.2-rc15** maintenant (procedure/*.sh procedure/staging.conf : sauvegarde + image de retour `:pre-rc15-<TS>`). Ne pas toucher au staging pendant ce temps.
- Conteneurs de test : `tb-rpr-*`, `tb-r15-*` (ports 8350-8370), `tb-nuit-dev` (:8300). Aucune action sur la production.

# Mise à jour (2026-10-05 ~01:40 UTC) — session « Time Billing V9 — import historique » (compte 2)
- Autorisation explicite de l'utilisateur : import des données historiques `Time sheet CP.xlsx` dans le **STAGING uniquement** (:8092, base vide au départ). Production (:8091) interdite et non touchée.
- Le staging (:8092) va recevoir des écritures (création de mandats, lots d'import via le mécanisme natif de l'application, sauvegarde préalable + annulation de lot). Ne pas déployer/redémarrer/modifier le staging pendant ce temps ; écrire ici avant si nécessaire.
- Répétition d'abord sur COPIE de la base : conteneurs `tb-imp-*`, ports 8380-8390. Aucun changement de code prévu.

# Mise à jour (2026-10-05 ~01:50 UTC) — import historique TERMINÉ (lot 1, staging)
- Lot 1 validé sur le staging (:8092) : 15 mandats, 1 371 saisies, 1 173,35 h. Staging redémarré, sain (9.2-rc15). Conteneurs `tb-imp-*` retirés (ports 8380-8382 libres). Production inchangée. Rapport et rollback : `import/execution-staging/RAPPORT-IMPORT-HISTORIQUE-STAGING.md`. Le staging n'est donc plus vide : toute restauration/rollback d'une autre session doit tenir compte de ce lot.

# Mise à jour (2026-10-05 ~05:05 UTC) — reprise « import historique » : lots F1–F5 sur le STAGING (compte 2)
- Autorisation explicite de l'utilisateur (autonomie, staging uniquement). Répétition complète déjà faite sur copies (0 écart, rollbacks OK).
- Le conteneur staging (:8092) va être ARRÊTÉ quelques minutes pendant les écritures puis redémarré. Ne pas déployer/redémarrer/modifier le staging pendant ce temps. Sauvegarde préalable : `/root/backups/time-billing-v9-staging/pre-final-*.db`. Production (:8091) non touchée. Dossier de travail : `import/final/`.

# Mise à jour (2026-10-05 ~05:10 UTC) — import historique F1–F5 TERMINÉ sur le staging
- Staging (:8092) redémarré, sain (9.2-rc15) : 2 155 saisies / 1 857,25 h / 23 mandats, 6 lots COMMITTED. 96 lignes (79,45 h) en attente de décision humaine. Production inchangée. Rapport : `import/IMPORT-FINAL-HISTORIQUE-STAGING.md`. Sauvegarde : `pre-final-20261005T045449Z.db`. Toute restauration/rollback doit tenir compte de ces lots.

# Mise à jour (2026-10-05 ~07:55 UTC) — import historique : dernière passe G1–G5 sur le STAGING (compte 2)
- Autorisation explicite de l'utilisateur (autonomie, staging uniquement). Répétition complète + rollback + test d'idempotence déjà faits sur copie. Sauvegarde avant chaque lot : `/root/backups/time-billing-v9-staging/pre-G*-*.db`.
- Le conteneur staging (:8092) va être ARRÊTÉ quelques minutes puis redémarré. Ne pas déployer/redémarrer/modifier le staging pendant ce temps. Production (:8091) non touchée. Dossier : `import/final/`.

# Mise à jour (2026-10-05 ~07:55 UTC) — dernière passe G1–G5 TERMINÉE sur le staging
- Staging (:8092) redémarré, sain (9.2-rc15) : 2 247 saisies / 1 934,50 h / 24 mandats, 11 lots COMMITTED, 0 facture. 3 lignes (2,20 h) restent à décider. Production inchangée. Rapport : `import/RAPPORT-DERNIERE-PASSE-G1-G5.md`. Sauvegardes `pre-G1…G5-*.db`. Toute restauration/rollback doit tenir compte de ces lots.

# Mise à jour (2026-10-05 ~08:45 UTC) — session « checkpoint + reprise autonome » (compte 2)
- La session précédente (import + recette fonctionnelle A–J, travail non commité : rc16, `tests/recette_fonctionnelle/`, `journaux/fonc/`) est à l'arrêt depuis 08:22 (tâches de fond « killed »). Je la reprends : je ne lance pas de second jeu de recettes concurrent, je termine rc16 (I5, H6b) et j'écris `CHECKPOINT-TIME-BILLING-V9.md`. Conteneurs `tb-fonc-*` (8300/8301/8310) = les siens, je les réutilise puis les retire. Staging (:8092) : lecture seule tant que rien n'est annoncé ici. Production non touchée.

# Mise à jour (2026-10-05 ~08:49 UTC) — déploiement 9.2-rc16 sur le STAGING (session checkpoint, compte 2)
- rc16 = « une ligne déjà importée ne peut plus être forcée en doublon » (commit 3dde16b). *RECTIFIÉ le 2026-10-06 (constat B4) : en rc16-rc19, seulement pour le même fichier à l'octet près (même sha256) ; identité de ligne par onglet, ligne et valeurs corrigée dans l'arbre de travail (non déployé).* Le staging (:8092) va être redéployé via procedure/*.sh procedure/staging.conf (sauvegarde + image de retour `:pre-rc16-<TS>`, arrêt de quelques secondes). Ne pas toucher au staging pendant ce temps. Les 2 247 saisies importées ne sont pas modifiées (empreinte avant/après contrôlée). Production non touchée.

# Mise à jour (2026-10-05 ~08:51 UTC) — déploiement 9.2-rc16 TERMINÉ sur le staging
- Staging (:8092) en **9.2-rc16**, sain, 50-verify conforme avant/après redémarrage. Sauvegarde `/root/backups/time-billing-v9-staging/pre-rc16-20261005T084938Z`, image de retour `:pre-rc16-20261005T084938Z`. Empreinte des 2 247 saisies identique avant/après. Production inchangée.

# Mise à jour (2026-10-05 ~09:55 UTC) — mandats : application « niveau certain » sur le STAGING (session checkpoint, compte 2)
- Le staging (:8092) va être ARRÊTÉ ~1 minute (sauvegarde vérifiée `pre-mandats-*.db` + conteneur d'écriture éphémère par les formulaires de l'application, 7 mandats : n° projet / PO vides complétés, identité de facturation de CIRSE 2026), puis redémarré. Aucune saisie, aucun lot d'import, aucune facture touchés ; clôtures NON appliquées (décision utilisateur). Ne pas toucher au staging pendant ce temps. Production non touchée.

# Mise à jour (2026-10-05 ~10:25 UTC) — mandats : application « niveau certain » TERMINÉE sur le staging
- Staging (:8092) redémarré, sain (9.2-rc16). Appliqué par les formulaires de l'application : 7 mandats (n° projet / PO vides, identité de facturation CIRSE 2026) + paramètres émetteur (étaient vides), sauvegardes `pre-mandats-*`, `pre-emetteur-*`. Saisies inchangées (empreinte 7a154f1f…), 0 facture, clôtures NON appliquées. Production inchangée.

# Mise à jour (2026-10-05 ~11:10 UTC) — rc17 (saisie passant minuit) : build + recette sur copies, puis déploiement STAGING (session compte 2)
- Code rc17 commité localement (eef5868) : une saisie 22:00→02:00 = UNE ligne de 4 h (décision utilisateur C5). Image de répétition `…:rc17` construite ; recettes HTTP sur copies jetables (conteneurs `tb-fonc-*`). Le staging (:8092) sera arrêté ~1 min pour le déploiement rc17 (procedure/*.sh), puis pour l'application des décisions C2 (NHAF 2026 + EUROPCR 2027 : adresse/contact/TVA). Ne pas toucher au staging pendant ce temps. Aucune saisie importée modifiée. Production NON touchée.

# Mise à jour (2026-10-05 ~09:46 UTC) — rc17 DÉPLOYÉ sur le staging
- Staging (:8092) en **9.2-rc17**, 50-verify conforme, sauvegarde `/root/backups/time-billing-v9-staging/pre-rc17-20261005T094522Z`, image de retour `:pre-rc17-20261005T094522Z`. Saisies identiques (2 247 / 1 934,4987 h, empreinte lib.entries_digest identique à la sauvegarde). Prochaine étape : application C2 (NHAF 2026, EUROPCR 2027) — arrêt ~1 min. Production inchangée.

# Mise à jour (2026-10-05 ~09:58 UTC) — rc18 : déploiement STAGING en cours (session compte 2)
- rc17 (déployé 09:45) contenait une erreur de syntaxe JS dans l'aperçu de durée de l'onglet Saisie (détectée par la recette navigateur, pas par les tests unitaires). Corrigé → **9.2-rc18** ; recettes sur copies : unitaires 376/376, HTTP A–N 100 %, navigateur 387/387. Le staging (:8092) va être arrêté ~1 min (procedure/*.sh, sauvegarde `pre-rc18-*`). C2 (NHAF 2026, EUROPCR 2027) déjà appliqué (sauvegarde `pre-c2-20261005T094622Z`). Saisies importées intactes. Production inchangée.

# Mise à jour (2026-10-05 ~10:15 UTC) — rc18 DÉPLOYÉ sur le staging, décisions C2/C4/C5/C6 appliquées
- Staging (:8092) en **9.2-rc18**, 50-verify conforme (sauvegarde `pre-rc18-20261005T100203Z`, image de retour `:pre-rc18-…`). Aucune saisie modifiée (table `entries` identique ligne à ligne à `pre-mandats-*`). Production inchangée. Le staging n'est plus arrêté par cette session ; prochaine écriture possible : clôtures C1 (si l'utilisateur répond OUI).

# Mise à jour (2026-10-05 ~10:30 UTC) — C1 : clôture des 19 mandats TERMINE sur le STAGING (décision utilisateur OUI)
- Le staging (:8092) va être ARRÊTÉ ~1 min : sauvegarde vérifiée `pre-c1-*.db`, puis clôture des 19 mandats par le formulaire de l'application (conteneur d'écriture éphémère), puis redémarrage. Aucune saisie, aucune facture touchées. Ne pas toucher au staging pendant ce temps. Production non touchée.

# Mise à jour (2026-10-05 ~10:20 UTC) — C1 appliquée sur le STAGING : TERMINÉ
- Staging (:8092) redémarré, sain (9.2-rc18). 19 mandats clôturés (sauvegarde `pre-c1-20261005T100700Z`), 0 saisie / 0 facture touchées. Lots M/N/L/K + A–J rejoués sur copies : 315/315. Répétition de bascule V9.0→rc18→V9.0 : GO (bacs `migration-blanc/A18`, `B18`). Production inchangée. Le staging n'est plus arrêté par cette session.

# Mise à jour (2026-10-05 ~10:33 UTC) — réinitialisation du mot de passe admin du STAGING (demande utilisateur)
- Hash `APP_PASSWORD_HASH` + `SECRET_KEY` du `.env` staging remplacés (autres clés inchangées), conteneur staging recréé (même image, 9.2-rc18). Sauvegarde de l'ancien `.env` + base : `/root/backups/time-billing-v9-staging/env-avant-reset-20261005T103223Z`. Base staging inchangée (sha identique), prod inchangée, 50-verify conforme. Retour arrière : recopier `.env` de la sauvegarde puis `docker compose -p time-billing-v9-staging up -d --force-recreate`.

# Mise à jour (2026-10-05 ~12:40 UTC) — session « RC19 : saisies toujours éditables » (compte 2)
- Demande utilisateur : aucune saisie verrouillée (ancienne, importée, mandat clôturé, facturée) ; facture émise immuable ; écart post-facturation visible ; audit avant/après.
- Travail en cours dans le dépôt (branche design-liquid-glass-rc14) : conception `CONCEPTION-RC19.md`, code rc19, tests. Conteneurs de test `tb-r19-*` (ports 8400-8420).
- Staging (:8092) : LECTURE SEULE pour l'instant. Un déploiement rc19 (avec sauvegarde + migration de schéma réversible + test de retour arrière) sera annoncé ici avant toute action. Les 2 247 saisies historiques ne seront pas modifiées. Production non touchée.

# Mise à jour (2026-10-05 ~13:45 UTC) — RC19 : PAUSE demandée par l'utilisateur
- Code rc19 terminé et testé sur copies (unitaires 401/401, HTTP 384/384 dont lot R 49/49, navigateur 427/427, répétitions A19/B19/C19 GO), commité localement (branche design-liquid-glass-rc14), NON déployé.
- Staging (:8092) : TOUJOURS 9.2-rc18, non touché par cette session (2 247 saisies, empreinte c0feab5b…). `procedure/staging.conf` toujours sur rc18. Production non touchée (bd31f410…).
- Reprise : voir `REPRISE-RC19.md` (relecture de code à relancer, puis déploiement staging + test de retour arrière). Aucun conteneur de test restant.

# Mise à jour (2026-10-05, reprise RC19, compte 2) — relecture de code en cours
- Reprise du plan RC19 sur instruction utilisateur : relecture de code (lecture seule), puis tests, puis déploiement STAGING (sauvegarde + procedure/*.sh), test de retour arrière, redéploiement. Annonce détaillée avant l'arrêt du staging (:8092). Production non touchée.

# Mise à jour (2026-10-05 ~23:05 UTC) — CHECKPOINT G4 (compte 2) : rc19 NON déployé, audit des factures historiques lancé
- Consigne utilisateur « PILOTAGE GLOBAL » : staging uniquement, aucune nouvelle modification fonctionnelle avant l'audit (G4-1 rapprochement factures historiques, G4-2 modèle facture/période/annexe, G4-3 dashboard/périodes, G4-4 PDF). Le déploiement rc19 est SUSPENDU ; le staging reste en 9.2-rc18.
- L'UTILISATEUR TRAVAILLE SUR LE STAGING (connexion 22:37 UTC, brouillon n° 1 créé 22:42 : EUROPCR 2027, 2026-09-03 → 2026-10-31, 2 j, « test »). Ne pas arrêter ni redéployer le staging sans le prévenir. Saisies inchangées (2 247 / 1 934,4987 h, identiques ligne à ligne à `pre-mandats-20261005T090824Z`).
- Sauvegarde cohérente : `/root/backups/time-billing-v9-staging/checkpoint-g4-20261005T225128Z.db`. Production non touchée (`bd31f410…`, conteneur `0b25a343…`).
- Cette session ne fait que LIRE (classeur source, copies de la base) jusqu'au rapport d'audit ; aucune écriture sur le staging.

# Mise à jour (2026-10-05 ~23:40 UTC) — AUDIT G4 terminé (phases A–C), commit ba1cc87 ; staging toujours en rc18, non touché
- `RAPPORT-AUDIT-G4.md` : rapprochement SUIVI ↔ application (26 lignes), incohérences, causes racines, architecture proposée (registre `historical_invoices` additif + annexe période/cumul + 12 contrôles avant émission), décisions D-1…D-10 pour l'utilisateur. Lecture seule : rien écrit dans le staging ni la production.
- Phase D (code) = sur copies et dans le dépôt uniquement ; AUCUN déploiement staging sans prévenir ici (l'utilisateur teste sur le staging : brouillon n°1). Aucune donnée historique chargée tant que l'utilisateur n'a pas validé le tableau.

# Mise à jour (2026-10-06 ~03:55 UTC) — session « UX/tests + conformité C1–C6 » (compte 2, PID 119438)
- Une autre session Time Billing (PID 116681, « robustesse RC18 / préparation cutover ») tourne dans CE dépôt depuis 03:43. Pour ne pas la gêner : je travaille dans un **worktree séparé** `/root/tb-wt-ux6` (branche `ux-tests-c1c6-20261006`, partie de 74cf62a + les adaptations D8 non commitées des tests). Je ne modifie pas l'arbre de travail principal (hors ce paragraphe).
- Staging (:8092) : **LECTURE SEULE** (l'utilisateur y travaille ; aucun déploiement sans son go, cf. REPRISE-G4). Production (:8091) non touchée.
- Conteneurs de test : préfixe `tb-ux6-*`, ports **8450-8479**, copies jetables uniquement.

# Mise à jour (2026-10-06 ~06:40 UTC) — session « reprise Time Billing G4 → claude2 16h41 » (PID 173120)
- Sessions 116681 et 119438 terminées (plus aucun processus). Branche `design-liquid-glass-rc14` alignée sur 40ee1dc (commit de 119438 = exactement les adaptations D8 qui étaient non commitées ici, contenu vérifié identique ; ancien diff : `/root/backups/tb-reprise-1641/`). Aucun code applicatif modifié.
- Tests relancés sur l'image candidate `:rc19` (= `app/` du dépôt, vérifié) : unitaires (conteneur sans réseau) puis recettes HTTP/navigateur sur COPIES jetables (conteneurs `tb-fonc-*`, `tb-rep-*`, ports 8230-8245, 8301-8320, 8404). Staging (:8092) : LECTURE SEULE, toujours 9.2-rc18. Production (:8091) non touchée. Aucun déploiement.
- 06:50 UTC : TERMINÉ. Unitaires 440/440, recettes R/A–K/Q/M/N/L/navigateur 0 échec (`recette/reprise-1641/recettes-reprise.txt`). Staging `24884dfe…` et production `bd31f410…` inchangés, aucun conteneur restant. État de reprise : `REPRISE-G4.md`.

# Mise à jour (2026-10-06 ~08:55 UTC) — session « reprise G4 : fidélité corrections/saisies/imports + finalisation » (PID 215222)
- Constat à la reprise : base staging `958c76ed…` (≠ `24884dfe…` de 06:50) ; seule différence = connexion de l'utilisateur à 07:16 UTC (1 ligne `audit` login_ok + 1 session web). Saisies, mandats, brouillon n°1 inchangés.
- Vérifications sur COPIES jetables uniquement (dossier `/tmp/tb-g4-0842`, conteneurs `tb-g4v-*`, ports **8480-8499**, réseau coupé quand possible). Staging (:8092) : LECTURE SEULE. Production (:8091) non touchée. Aucun déploiement.
- (constat 14:05 UTC) Session 215222 arrêtée net à 09:20:57 (limite d'usage) ; stabilisation PID 280047 (10:35-10:40) arrêtée elle aussi avant la fin (relance unitaire tronquée, marqueur `RESULTAT_RELANCE` non rempli). État : `journaux/g4/fidelite-20261006/ETAT-FIDELITE-G4.md`.

# Mise à jour (2026-10-06 ~14:05 UTC) — session « reprise G4 : intégration des correctifs de fidélité + tests » (PID 323542)
- Seule session Time Billing dans ce dépôt (les autres sessions Claude actives travaillent sur lumo, chess-academy, amo-v2-e2).
- Travail : intégrer `correctifs-non-integres.patch` dans l'arbre de travail (NON commité sans accord), contre-vérifier l'axe E, suite unitaire complète, recettes HTTP/navigateur sur COPIES jetables (image candidate distincte, jamais `:latest`/`:rc19`), corriger les régressions.
- Staging (:8092) : LECTURE SEULE (base `958c76ed…` à 14:05). Production (:8091) non touchée (`bd31f410…`). Aucun déploiement.
- (constat 20:22 UTC) Session 323542 arrêtée à 14:26 UTC (limite d'usage) juste après la revue adverse (2 relecteurs sur 4 terminés, aucune vérification) ; chaîne p1 (image `tb-g4-fidelite-cand:p1-20261006`) : tout OK sauf A5, corrigé dans l'arbre à 14:15 mais non rejoué.

# Mise à jour (2026-10-06 ~20:25 UTC) — session « reprise HANDOFF-CLAUDE2-20261007-0315 : G4/D8, fin d'intégration des correctifs de fidélité » (PID 412386)
- Seule session Time Billing dans ce dépôt (les sessions 412232/412282/412514 lancées à 20:21 travaillent dans amo-v2-e2, lumo, chess-academy).
- Consigne de l'utilisateur : travailler uniquement dans ce dépôt ; ne jamais toucher à `/opt/time-billing-v9` ni à un environnement de production. Cette session ne lit AUCUN fichier sous `/opt/` (pas même les empreintes) ; recettes sur copies tirées du dépôt ou de `/root/backups/` uniquement.
- Travail : exploiter la revue adverse de 14:26 (R-CHK-1/2, R-E3-1/2 ; E-2/E-4/E-5 = décisions utilisateur), terminer les relectures import et formulaires, suite unitaire complète, chaîne de recettes p2 sur COPIES jetables (image candidate distincte, jamais `:latest`/`:rc19`), corriger les régressions. Rien commité sans accord. Aucun déploiement.

# Mise à jour (2026-10-07 ~02:25 UTC) — session Claude2 billing (PID 13709) : application des décisions du Decision Center
- Seule session Time Billing dans ce dépôt (les sessions lancées à 10:21 +0800 travaillent sur amo et lumo).
- Décisions RÉSOLUES à appliquer (source : /srv/decision-center) : D9=B (date de facture), E-4=B (zone fixe d'une ligne + limite de saisie), N1=OUI, import (import initial unique, réimport volontaire = écrase), A-01 (revue ligne à ligne), A-03 (heures décimales), E-8 (retours à la ligne conservés), R-E3-1 (AUTRES à 0 non imprimé), D10=GO staging.
- Travail dans l'arbre de travail du dépôt, tests sur COPIES jetables. Production (:8091) et /opt/time-billing-v9 : jamais touchés. Le staging (:8092) ne sera arrêté qu'après annonce ici (déploiement D10, sauvegarde préalable).

# Mise à jour (2026-10-07 ~02:50 UTC) — session Claude2 billing (PID 15821) : DÉPLOIEMENT STAGING (D10 = GO_STAGING)
- Code : commit local `8afd867` (G4 + correctifs de fidélité + D9=B + E-4=B), version 9.2-rc19. Unitaires 472/472 ; chaîne de recettes p6 sur
  l'image `tb-g4-decisions-cand:8afd867` (= commit) : R 49/49, A–K/Q 305/305, M/N/L 32/32, navigateur/e2e/concurrence 0 échec ; répétition D sur copie
  du staging : GO (`migration-blanc/D-G4-dryrun-decisions-20261007.log`).
- **Le staging (:8092) va être ARRÊTÉ quelques minutes** : 10 → 20 (sauvegarde, service arrêté) → 30 → 40 → 50, mot de passe et secret de session
  conservés (.env inchangé), puis test du retour arrière (refusé automatiquement si des données ont été saisies entre-temps) et redéploiement.
- Production (:8091) et /opt/time-billing-v9 : jamais touchés.
- (02:50 UTC) TERMINÉ. Staging = **9.2-rc19** (commit 8afd867), 50-verify conforme (24/24, avant et après redémarrage). Retour arrière réel testé
  (rc18, base = sauvegarde SHA identique) puis redéploiement conforme. Sauvegardes : `/root/backups/time-billing-v9-staging/pre-rc19-20261007T024757Z`
  (avant le 1er déploiement) et `pre-rc19-20261007T024945Z` (avant le redéploiement). Mot de passe inchangé. Le staging n'est plus arrêté par cette session.
  Journaux : `journaux/deploy-staging-20261007/`. Production non touchée.

# Mise à jour (2026-10-07 ~07:23 UTC) — session Claude2 billing : DONNÉES STAGING (D1/D2 = GO_STAGING / IMPORT_4550, A-01 = OUI)
- **Le staging (:8092) va être ARRÊTÉ ~15 secondes** par `procedure/60-donnees-d1-d2-a01.sh procedure/staging.conf` : sauvegarde vérifiée
  (`/root/backups/time-billing-v9-staging/pre-donnees-d1d2a01-<TS>`), simulation sur la copie arrêtée, puis chargement des 24 factures historiques
  « à valider » (aucune validée : sans effet sur les chiffres tant que l'utilisateur ne les valide pas) et report des 15 notes A-01 dans les descriptions
  (correction tracée, motif « note colonne I du classeur (Decision Center billing-a01-lNN) », acteur `outil-a01`). Échec → base sauvegardée remise en place.
- Répété sur faux staging (commit fb2298b). Production (:8091) et /opt/time-billing-v9 : jamais touchés.
- (07:23 UTC) TERMINÉ. Staging relancé (9.2-rc19, sain). 24 factures historiques « à valider » (ids 1-24, 138 209,50 CHF, aucune validée),
  15 descriptions A-01 corrigées (chiffres inchangés). Sauvegarde : `pre-donnees-d1d2a01-20261007T072306Z` (sha 9e3c5cfd1447).
  Journal : `journaux/donnees-staging-20261007T072306Z/`. NB : `90-rollback.sh` refusera désormais le retour rc18 sans ABANDONNER_CORRECTIONS (données ajoutées).

# Mise à jour (2026-10-07 ~13:15 UTC) — session Claude2 billing : DÉPLOIEMENT STAGING rc21 (D11 = GO_STAGING)
- Code : 9.2-rc21 (commit 51b7c1b, application inchangée depuis ; image de répétition `tb-g4-cand:51b7c1b`, chaîne p10 verte, répétition E : GO).
- **Le staging (:8092) va être ARRÊTÉ quelques minutes** : 10 → 20 (sauvegarde, service arrêté) → 30 → 40 → 50, mot de passe et secret de session
  conservés (.env inchangé), puis test du retour arrière (90 : refusé automatiquement si des données métier ont changé entre-temps) et redéploiement.
- Production (:8091) et /opt/time-billing-v9 : jamais touchés.
- (13:09 UTC) TERMINÉ. Staging = **9.2-rc21** (commit 51b7c1b), 50-verify conforme (avant et après redémarrage). Retour arrière réel testé
  (rc19, base = sauvegarde SHA identique) puis redéploiement conforme. Sauvegardes : `/root/backups/time-billing-v9-staging/pre-rc21-20261007T130801Z`
  (avant le 1er déploiement) et `pre-rc21-20261007T130853Z` (avant le redéploiement). Mot de passe inchangé. Données inchangées (24 historiques
  « à valider », 2 247 saisies, brouillon n° 1). Le staging n'est plus arrêté par cette session. Journaux : `journaux/deploy-staging-rc21-20261007/`.

# Mise à jour (2026-10-07 ~23:45 UTC) — session Claude2 billing : DÉPLOIEMENT STAGING rc22 (D12 = GO_STAGING)
- Code : 9.2-rc22 = copie de publication figée `/root/time-billing-releases/9.2-rc22-2282419` (image de répétition `tb-g4-cand:2282419`,
  chaîne p12 verte, répétition G : GO).
- **Le staging (:8092) va être ARRÊTÉ quelques minutes** : 10 → 20 (sauvegarde, service arrêté) → 30 → 40 → 50, mot de passe et secret de session
  conservés (.env inchangé), puis test du retour arrière (90 : refusé automatiquement si des données métier ont changé entre-temps) et redéploiement.
- Production (:8091) et /opt/time-billing-v9 : jamais touchés.
- (23:38 UTC) TERMINÉ. Staging = **9.2-rc22** (copie figée 2282419), 50-verify conforme (avant et après redémarrage). Retour arrière réel testé
  (rc21, base = sauvegarde SHA identique) puis redéploiement conforme. Sauvegardes : `/root/backups/time-billing-v9-staging/pre-rc22-20261007T233730Z`
  (avant le 1er déploiement) et `pre-rc22-20261007T233832Z` (avant le redéploiement). Mot de passe inchangé (.env.rc22 = copie du .env).
  Données identiques (empreinte_metier : IDENTIQUES ; 24 historiques « à valider », 2 247 saisies / 1 934,4987 h, brouillon n° 1).
  Le staging n'est plus arrêté par cette session. Journaux : `journaux/deploy-staging-rc22-20261008/`. Production non touchée.

# Mise à jour (2026-10-08 ~06:20 UTC) — session Claude2 billing : STAGING rc23 (D13 = GO_STAGING, résolue 05:17 UTC)
- Constaté : le staging est déjà en **9.2-rc23** depuis 05:18 UTC (sauvegarde `pre-rc23-20261008T051822Z`, `procedure/staging-rc23.conf`,
  image construite depuis la copie figée 9.2-rc23-50492d4, empreinte fb2bd971… identique), mais sans journal, sans note ici, sans test du retour
  arrière ; auteur non identifié (aucune session Claude2 billing tracée à cette heure).
- Cette session rejoue **50-verify** (redémarrage de quelques secondes) pour tracer la conformité ; si les données sont inchangées depuis 05:18,
  **test du retour arrière (90, staging ARRÊTÉ ~1 min) puis redéploiement 10→50**, comme pour rc19/21/22. 90 refuse si des données ont été saisies
  entre-temps (rien n'est alors fait). Production (:8091) et /opt/time-billing-v9 : jamais touchés.
- (06:12 UTC) 50-verify du déploiement de 05:18 : CONFORME (données identiques à la sauvegarde). Retour arrière réel testé (06:10 : rc22, base =
  sauvegarde pre-rc23-20261008T051822Z SHA identique). Redéploiement : 10/20/30 conformes (sauvegarde `pre-rc23-20261008T061057Z`), **40 arrêté
  avant toute modification** : `/opt/time-billing-v9-staging/.env.rc23` absent et sa création (cp -p du .env) REFUSÉE à l'agent par le classifieur.
  Staging relancé aussitôt (`docker compose -p time-billing-v9-staging start`) : **9.2-rc22, sain, données intactes** (arrêt ≈ 1 min 30).
  Fiche `billing-d13-execution-rc23` (Decision Center) : copie du .env à faire par l'utilisateur, puis 10 → 50 avec procedure/staging.conf.
  NB : le marqueur `deployed` désigne encore 20261008T051822Z (déploiement retiré) : un 90 maintenant restaurerait la même base (identique).

# Mise à jour (2026-10-08 ~09:15 UTC) — session Claude2 billing : FIN DU DÉPLOIEMENT STAGING rc23 (D13 = GO_STAGING, fiche billing-d13-execution-rc23 option A)
- `/opt/time-billing-v9-staging/.env.rc23` présent (créé 08:35 UTC par l'utilisateur, identique au .env, mode 600).
- **Le staging (:8092) va être ARRÊTÉ environ une minute** : 10 → 20 (sauvegarde, service arrêté) → 30 → 40 → 50 avec procedure/staging.conf
  (copie figée 9.2-rc23-50492d4, image tb-g4-cand:50492d4). Mot de passe et secret de session conservés. Pas de nouveau test du retour arrière
  (déjà fait à 06:10 UTC). Production (:8091) et /opt/time-billing-v9 : jamais touchés.
- (09:11 UTC) TERMINÉ. Staging = **9.2-rc23** (copie figée 50492d4), 50-verify CONFORME avant et après redémarrage, arrêt ≈ 25 s.
  Sauvegarde `pre-rc23-20261008T091053Z` ; données identiques à 06:10 UTC (empreinte_metier IDENTIQUES : 24 historiques « à valider »,
  2 247 saisies, brouillon n° 1). Prérequis G5 : tous remplis. Le staging n'est plus arrêté par cette session. Production non touchée.
