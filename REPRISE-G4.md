# Reprise G4 — état au 2026-10-06 (décisions D1-D10 reçues) — état courant : section « ÉTAT COURANT » ci-dessous

## ÉTAT COURANT — 2026-10-08 ~10:15 UTC (Claude2 billing) — À LIRE EN PREMIER (les sections plus bas sont l'historique)
- **Staging = 9.2-rc23** depuis 09:11 UTC : `.env.rc23` créé par l'utilisateur (08:35 UTC), 10 → 50 rejoués par Claude2, 50-verify conforme,
  données identiques (sauvegarde `pre-rc23-20261008T091053Z`). **Prérequis G5 : tous remplis** (`journaux/deploy-staging-rc23-20261008/`).
  La fiche `billing-d13-execution-rc23` est encore « pending » : la marquer résolue a été REFUSÉE à l'agent (fiche utilisateur) → à fermer par l'utilisateur.
- **Arbre rc24** (non publié) : + audit de connexion borné (4a1d3d2, `billing-agent-20261008092227`) : un robot bloqué sur /login ajoutait
  ~106 lignes d'audit/s (≈ 9 M/jour) ; désormais une ligne `login_throttled` par client et par fenêtre de 15 min, verrou inchangé. Unitaires 541/541.
- **Connexions lentes (09:50 UTC)** : 16 connexions envoyant un corps au compte-gouttes rendaient l'application indisponible (mesuré, direct et à
  travers le bloc Caddy prévu). Parade : `request_buffers 64KB` dans le bloc de `80-site-caddy.sh` + `/login` ≤ 16 Ko (3f49b60,
  `billing-agent-20261008095827`) ; répétition 80 GO (`journaux/g5-caddy/`) ; envoi de 11,6 Mo inchangé. Unitaires 542/542.
- **rc24 = 3f49b60** : copie figée `/root/time-billing-releases/9.2-rc24-3f49b60` (empreinte 23c0e56e…, image `tb-g4-cand:3f49b60`) ; chaîne p17,
  répétitions L (61) et M (36), aller-retour : tout vert. Les copies 4a1d3d2 / 993cc82 sont antérieures (ne pas déployer).
- (antérieur, remplacé par 3f49b60) copie figée `/root/time-billing-releases/9.2-rc24-4a1d3d2` (empreinte 4a2e4a66…, image `tb-g4-cand:4a1d3d2`) ;
  chaîne p16 tout vert ; répétition L (faux staging rc23 = sauvegarde 09:10 → rc24 → retour → rc24 → parcours → retour refusé) GO 61 ;
  aller-retour des formulaires sur pre-rc23-20261008T091053Z : 2 273, 0 refus, IDENTIQUES. **Fiche `billing-d14-deploy-rc24`** (en attente) :
  si GO → l'utilisateur crée `.env.rc24` (cp -p .env .env.rc24), puis staging.conf ET prod.conf → copie 9.2-rc24-3f49b60 / tb-g4-cand:3f49b60,
  note dans NOTE-SESSIONS-PARALLELES, 10 → 50, test 90, redéploiement, `00-prerequis-bascule.sh`. Aucun .conf ne désigne rc24 aujourd'hui.
- **Répétition M** (promotion G4 = fenêtre G5, données du staging de 09:10) : rc23 GO 36, rc24 GO 36 (`migration-blanc/dry-run-m-promotion-cible.sh`).
- REVUE-CODE-RC19 annotée : tous les points techniques corrigés ; reste seulement le point métier « facturée par date » (fiche).
- En attente utilisateur : `billing-d14-deploy-rc24`, `billing-facturee-par-date` (HIGH), `billing-g5-sauvegarde-quotidienne` (HIGH),
  fermeture de `billing-d13-execution-rc23` (faite côté technique), date/heure G5, recette du staging (24 historiques à valider, brouillon n° 1).

## ÉTAT — 2026-10-08 ~09:15 UTC (Claude2 billing) (historique)
- **Staging toujours en 9.2-rc22** : `/opt/time-billing-v9-staging/.env.rc23` toujours absent (08:30 UTC) → fiche `billing-d13-execution-rc23`
  en attente (mise à jour 08:51 : seul prérequis G5 manquant).
- **G5 : DNS billing.hudd-l.com en place** (A 147.93.55.171 sur 1.1.1.1 et 8.8.8.8, sans AAAA). `00-prerequis-bascule.sh` à 08:51 UTC :
  seul manque le staging en rc23 (`journaux/g5-prerequis/`).
- **Nouvelle fiche `billing-g5-sauvegarde-quotidienne` (HIGH)** : la sauvegarde nocturne de la production n'est pas planifiée et la ligne
  cron d'OPERATIONS-RC11 serait arrêtée chaque nuit par le garde-fou CONFIRM_PROD de tb-common.sh. Exemption par nom de script refusée à
  l'agent (« Security Weaken ») et annulée. Scripts répétés : répétition K GO (`migration-blanc/K-SAUV-dryrun-20261008.log`).
- **Arbre rc24** (non publié) : + paramètres de l'émetteur enregistrés sans changement ne réécrivent plus rien (trouvé par l'aller-retour
  des formulaires étendu aux paramètres ; `outils/lancer_aller_retour.sh` : 2 273 formulaires, tables métier IDENTIQUES) ; `app/app.py.orig`
  retiré. Unitaires 540/540. Recette p14 sur 993cc82 : tout vert ; chaîne p15 sur f6d6801 : tout vert.
  La copie figée `9.2-rc24-993cc82` (répétition J : GO) est ANTÉRIEURE à ces deux commits : refaire une copie si rc24 est proposé au déploiement.
- `billing-facturee-par-date` : toujours en attente (bloque seulement ce correctif).

## ÉTAT — 2026-10-08 ~06:45 UTC (Claude2 billing) (historique)
- **Staging = 9.2-rc22** (sain, données intactes). D13 = GO_STAGING : rc23 déployé à 05:18 UTC hors session tracée, contrôlé (50 conforme),
  retour arrière réel testé (06:10), redéploiement arrêté à 40 AVANT modification : `/opt/time-billing-v9-staging/.env.rc23` absent, copie
  refusée à l'agent → staging relancé en rc22 (06:12). Fiche **`billing-d13-execution-rc23`** : l'utilisateur crée la copie, puis 10 → 50
  (`procedure/staging.conf`, déjà en rc23). 10-preflight signale désormais `.env.<rc>` absent. Journaux : `journaux/deploy-staging-rc23-20261008/`.
- staging.conf et prod.conf → copie figée `9.2-rc23-50492d4` (image `tb-g4-cand:50492d4`).
- Recette rc23 : navigateur dédié « Corriger / Ajouter » 25/25 (`tests/browser/recette-rc23.js`) ; chaîne p13b (`recette/reprise-2025/p13b-rc23/`).
- Nouvelle fiche **`billing-facturee-par-date`** (HIGH, en attente) : double facturation possible d'une saisie facturée puis déplacée dans la
  période suivante (sonde `journaux/sonde-facturee-20261008/`) ; recommandation A (la première facture émise garde la saisie), rc24.
- G5 : DNS billing.hudd-l.com toujours absent (06:15 UTC, 1.1.1.1 et 8.8.8.8).
- Conteneur `tb-fonc-m` (recette interrompue) toujours là : retrait refusé à l'agent ; la recette n'en dépend plus (MNL_NAME/MNL_PORT).
- `.env.rc23` à la racine du dépôt (copie du .env du staging, 600, non suivie, désormais ignorée par .gitignore) : origine inconnue, non supprimée.
- (06:50 UTC) Arbre rc24 : **verrou partiel des saisies importées corrigé** (REVUE-CODE-RC19 : une valeur acceptée par l'import mais refusée par le
  formulaire — > 24 h, < 0,01 h, secondes, début = fin, horaire seul, description longue / multiligne — rendait la saisie non corrigible ou se
  perdait) : valeur inchangée conservée, nouvelle valeur aux règles habituelles. 0 saisie réelle concernée. Unitaires 537/537 ; navigateur 31/31
  (rc23 : 14/31). Journaux `journaux/verrou-import-20261008/`. Non publié, non déployé.

## ÉTAT COURANT — 2026-10-07 ~23:00 UTC (Claude2 billing) (historique)
- Staging inchangé : **9.2-rc21** (aucune action sur le staging ni la production dans cette session ; rien lu sous /opt).
- **G4 tranchée par l'utilisateur : PROMOTE_STAGING_DB**, condition « toutes les données restent modifiables/corrigeables après bascule ».
  Préparé (non exécuté, attend G5) : `procedure/70-promouvoir-base-staging.sh` + `outils/empreinte_metier.py` (vide / comparer / empreinte) ;
  répétition H (`migration-blanc/dry-run-h-promotion.sh`) : **GO**. Procédure : PROCEDURE-DEPLOIEMENT-RC11.md, section 2026-10-08.
- Inventaire « corrigeable » : tout l'est (saisies, mandats, brouillons, paramètres, lots d'import ; documents émis par note de crédit) SAUF
  les valeurs des factures historiques (statut seulement) → fiche `billing-g4-correction-historiques` (en attente, recommandation A : bouton
  « Corriger » = rejet tracé + ligne corrigée validée, et « Ajouter » ; rc23).
- **rc22** (arbre, non déployée) : unitaires 511/511 ; chaîne p12 verte (e2e : défaut du TEST corrigé — date UTC vs jour de Zurich —, rejoué
  30/30 + 18/18) ; copie de publication figée `/root/time-billing-releases/9.2-rc22-2282419` + image `tb-g4-cand:2282419` ; répétition G
  staging rc21 → rc22 : **GO**. Fiche **D12** (`billing-d12-deploy-rc22`, en attente). Si D12 = GO : staging.conf/prod.conf → copie rc22.
- Journaux : `journaux/g4-commun-20261008/`, `migration-blanc/G-RC22-dryrun-20261008.log`, `migration-blanc/H-PROMOTION-dryrun-20261008.log`.
- Script 70 relu (relecture adverse, correctifs appliqués), répétition H rejouée : GO (36 contrôles, `H-PROMOTION-dryrun-20261008-apres-relecture.log`).
- Fiche **G5** créée (`billing-g5-bascule-production`, en attente) : plan, nom billing.hudd-l.com (DNS A → 147.93.55.171 ABSENT à ce jour), date.
- Arbre passé en **9.2-rc23** (non publiée) : sonde schema_checks INSERT entries + rattachement d'entry_id_never_reused ; unitaires 512/512.
  rc23 accueillera la correction des historiques si `billing-g4-correction-historiques` = A ou B.

## ÉTAT COURANT — 2026-10-07 ~13:10 UTC (Claude2 billing) (historique)
- **D11 = GO_STAGING → staging déployé en 9.2-rc21** (commit 51b7c1b) à 13:09 UTC : 10 → 50 conformes, retour arrière réel testé (rc19, base =
  sauvegarde SHA identique), redéploiement 10 → 50 conforme. Sauvegardes `pre-rc21-20261007T130801Z` et `pre-rc21-20261007T130853Z`.
  Données inchangées : 24 historiques « à valider » (138 209,50 CHF), 2 247 saisies / 1 934,4987 h, brouillon n° 1. Journaux :
  `journaux/deploy-staging-rc21-20261007/`. Production jamais touchée.
- Reste à l'utilisateur, sur le staging : validation des 24 factures historiques (page Factures historiques), bouton « Télécharger le classeur
  (.xlsx) » (page Migration), E-8 (adresse EGG BE, retours à la ligne) via l'interface.
- **Préparation de la bascule production (G5, autorisation séparée, NON exécutée)** — répétitions F (V9.0 → rc21) sur bac à sable reconstruit
  depuis l'archive A19/B19 (`migration-blanc/setup-sandbox-copie.sh`, `dry-run-f.sh` ; aucune lecture de /opt). Défauts trouvés et corrigés
  (commit ba170a0, `billing-agent-20261007133946`) : 20-backup échouait sur une base V9.0 ; 90 refusait à tort le retour juste après déploiement
  et ne voyait pas les colonnes ajoutées ; cible du retour indépendante de la VERSION du dépôt (fichier `deployed`). Relecture adverse : aucune
  perte silencieuse, 5 défauts mineurs corrigés. `migration-blanc/test-90-f.sh` 19/19 ; A21/B21/E : GO. Les deux points « non corrigés » de la
  section ~12:40 sont réglés. Reste pour G5 : plan Caddy/DNS/pare-feu, rotation des secrets, gel des saisies, décision de l'utilisateur.

## ÉTAT — 2026-10-07 ~12:40 UTC (Claude2 billing) (historique)
- **Répétition E** (`migration-blanc/dry-run-e-rc21.sh`, journal `migration-blanc/E-RC21-dryrun-20261007.log`) : séquence D11 exacte sur un faux
  staging reconstitué (sauvegarde `pre-donnees-d1d2a01-20261007T072306Z` + procedure/60 rejouée ; aucune lecture de /opt) : rc19 → rc21 10→50,
  données identiques à rc19 (2 247 saisies, 24 historiques « à valider », 15 descriptions A-01, brouillon n°1 et ses contrôles 3/10/12/13),
  bouton + export, retour arrière accepté, redéploiement, validation des 24 historiques, export 23 onglets (CA 67 236,00 / 70 973,50) : **GO**.
- **Défaut trouvé et corrigé dans `procedure/90-rollback.sh`** (commits 8dc951d, 11df89e ; `billing-agent-20261007123110`) : seules les lignes
  modifiées de entries/projects étaient comparées → un retour arrière après validation des historiques (ou brouillon modifié, paramètre modifié,
  annulation de note de crédit) les écartait sans avertissement. Désormais : ajoutées ou modifiées dans toutes les tables métier → refus sauf
  ABANDONNER_CORRECTIONS=OUI. Vérifié : 9 scénarios sur copies + répétition E (essai 1 NO-GO conservé : `E-RC21-dryrun-20261007-essai1-defaut-90.log`).
- **Relecture adverse des scripts de procédure** (agent, lecture seule) → correctifs (commits a19d872 et suivant ; `billing-agent-20261007124232`) :
  90 refait la comparaison service ARRÊTÉ et détecte les suppressions ; 20 refuse si la version cible tourne déjà ou si un -journal reste après
  l'arrêt ; stop_grace_period 30s (compose staging/prod) ; 50 compare les effectifs de toutes les tables métier ; 60 : restauration fiable /
  interruption ; empreinte du code notée par 20 et contrôlée par 30/40 ; backup-quotidien ne recalcule plus SHA256SUMS. Répétition E rejouée : GO.
  Restent pour la bascule PRODUCTION (non corrigés) : 90 ne compare que les colonnes communes (colonne ajoutée par une migration puis renseignée
  = non vue ; solution : comparer à une copie de la sauvegarde migrée) ; 90 ne voit pas un changement de VERSION dans l'arbre avant le retour.
- Fiche D11 (`billing-d11-deploy-rc20`, toujours **pending**) complétée avec ces preuves (sauvegarde `decisions.json.bak-before-d11-repetition-e-*`).
- Application inchangée depuis 51b7c1b (image tb-g4-cand:51b7c1b toujours valable) ; staging = rc19, non touché ; production jamais touchée.

## ÉTAT — 2026-10-07 ~09:30 UTC (Claude2 billing) (historique)
- Decision Center : `billing-gsheet-export-scope` résolue = **B** (08:39 UTC) → développée : onglets « SUIVI AAAA » de l'export .xlsx reconstruits
  depuis Billing (commit 063f108 ; choix techniques `billing-agent-20261007085349`). Relecture adverse : 2 défauts corrigés (51b7c1b ;
  `billing-agent-20261007090813`) : texte « =… » écrit comme formule (hérité de rc20), caractère de contrôle → export en échec.
- Code **9.2-rc21** (commits locaux, NON déployé ; staging = rc19 ; rc20 jamais déployée) : image `tb-g4-cand:51b7c1b` (= commit 51b7c1b,
  `procedure/staging.conf` à jour, commit 8b356a6) : unitaires 494/494 ; chaîne p10 R 49/49, A–K/Q 305/305, M/N/L 32/32, navigateur/e2e/concurrence
  0 échec (`journaux/export-suivi-20261007/chaine-p10-image-51b7c1b.txt`).
- Mesure option B sur copie du staging (`journaux/export-suivi-20261007/LISEZMOI.txt`) : 23 onglets = classeur, 24/24 historiques identiques,
  CA 2025 67 236,00 / 2026 70 973,50 = « Facturé » de Billing ; recalcul LibreOffice sans erreur.
- EN ATTENTE utilisateur : `billing-d11-deploy-rc20` (fiche mise à jour pour **rc21**, GO recommandé → annoncer dans NOTE-SESSIONS-PARALLELES puis
  `procedure/10…50 procedure/staging.conf`, retour arrière testé (90), redéploiement, comme rc19). Validation des 24 historiques et E-8 : par l'utilisateur.

## ÉTAT COURANT — 2026-10-07 ~08:15 UTC (Claude2 billing) — À LIRE EN PREMIER (les sections plus bas sont l'historique)
- Decision Center : D1 GO, D2 IMPORT_4550, A-01 l01–l15 OUI, A-02 KEEP, import OVERWRITE_MATCHING, export DOWNLOADABLE_EXCEL, D5 DEFER_BILLING (résolues).
- **Staging (07:23 UTC), `procedure/60-donnees-d1-d2-a01.sh`** (répété sur faux staging) : 24 factures historiques « à valider » (D1 23 + D2
  SUIVI 2026!M15 = 4 550 CHF, 7,5833 j à 600 CHF/j, colonne « Facture 27/04 »), aucune validée ; 15 descriptions A-01 (correction tracée, acteur
  `outil-a01`). Sauvegarde `pre-donnees-d1d2a01-20261007T072306Z`. Journal `journaux/donnees-staging-20261007T072306Z/`. À VALIDER par l'utilisateur
  (page « Factures historiques ») ; après validation : 5 mandats clôturés légèrement négatifs (attendu, cf. simulation).
- Code **9.2-rc20** (commits locaux, NON déployé ; staging = rc19) : F-C2-1 ; réimport « écraser » (OVERWRITE_MATCHING, corrigé après relecture adverse :
  4 éléments date/mandat/horaires+durée/motif, au plus un différent, aucun décalage, provenance exigée ; choix explicite ligne à ligne ; correction
  tracée ; lot non annulable en bloc) ; export .xlsx (onglets mensuels, bouton Migration). Image `tb-g4-cand:0a07ff7` (= commit 0a07ff7, staging.conf
  à jour) : unitaires 487/487 ; chaîne p8 R 49/49, A–K/Q 305/305, M/N/L 32/32, navigateur/e2e/concurrence 0 échec.
- EN ATTENTE utilisateur (Decision Center) : `billing-d11-deploy-rc20` (GO recommandé → `procedure/10…50 procedure/staging.conf`, retour arrière testé,
  redéploiement, comme rc19) ; `billing-gsheet-export-scope` (A recommandé ; B = + onglets SUIVI à développer ; C = A sur les données actuelles).
- E-8 (adresse EGG BE : « Avenue du Bourgmestre » / « Etienne Demunter 5, boîte 10 », mandats 11 clôturé, 13, 22) : à saisir dans la fiche mandat
  (écriture directe refusée par le classifieur le 07.10, non retentée).

## ÉTAT COURANT — 2026-10-07 ~02:55 UTC (Claude2 billing, PID 15821) — À LIRE EN PREMIER (les sections plus bas sont l'historique)
- Décisions du Decision Center appliquées : D9=B (coupure = date de la facture pour historiques, factures TB, notes de crédit et annulations ;
  exercice = année de la date de facture), E-4=B (note libre : zone fixe d'une ligne, refus au-delà, contrôle 11 pour les anciens brouillons),
  N1=OUI (déjà en place), R-E3-1 (déjà en place : libellé AUTRES à 0 non imprimé, contrôle 10 inchangé), A-03 (lecture décimale déjà appliquée
  aux 2 247 saisies : aucune donnée modifiée). Choix techniques tracés par decision-log-agent (billing-agent-20261007023520-a..d).
- Commit local **8afd867** (rien poussé). Unitaires 472/472 ; chaîne p6 sur `tb-g4-decisions-cand:8afd867` (= commit) : R 49/49, A–K/Q 305/305,
  M/N/L 32/32, navigateur/e2e/concurrence 0 échec (`recette/reprise-2025/p6/recettes-reprise.txt`) ; répétition D sur copie du staging : GO.
- **D10 exécuté : staging = 9.2-rc19** (02:48 UTC), retour arrière réel testé puis redéploiement (02:50), 50-verify conforme. Voir NOTE-SESSIONS-PARALLELES.
- Decision Center (en attente, créées par cette session) : `billing-a01-l01`…`l15` (une fiche par note de la colonne I, A-01),
  `billing-import-overwrite-scope` (portée de « écrase » au réimport), `billing-gsheet-export-mechanism` (bouton d'export : .xlsx ou API Google).
  `billing-a02-l01`…`l09` (dates hors séquence, règle A-03 « ligne par ligne »), `billing-d1-load-go` (chargement des 23 factures historiques).
  Déjà en attente : D2 (STC GEM Oct 4 550), D5 (données EUROPCR 2027). Structure du classeur pour l'export : `CONCEPTION-EXPORT-GSHEET.md`.
- Commit 82a9899 (F-C2-1, nombres en chiffres ASCII) : NON déployé (partira avec le prochain lot).
- Bloqué par les permissions de la session (classifieur) : lecture/écriture de la base du staging hors procédure. Donc NON fait :
  E-8 (adresse des mandats CIRSE 2026, NHAF 2026, EUROPCR 2027 : « Avenue du Bourgmestre » / « Etienne Demunter 5, boîte 10 » sur deux lignes,
  comme la facture réelle 2026-09) → à saisir par l'utilisateur dans la fiche mandat, ou permission à accorder.
- Suite : (1) réponses A-01 → corrections de description tracées ; (2) réponse import-overwrite → code d'import ; (3) réponse export → bouton ;
  (4) D1 : chargement des 23 factures historiques « à valider » (go séparé, chargeur prêt) ; (5) D5 pour facturer EUROPCR 2027.
Branche design-liquid-glass-rc14, rien de poussé, rien de déployé. Staging = 9.2-rc18 (brouillon n°1 de l'utilisateur dedans), prod intacte.
Décisions : `DECISIONS-G4-D1-D10.md` + réponses utilisateur du 2026-10-06 : D1 OUI · D2 NON · D3 NON · D4 OUI · D5 (a) OUI, (b) à confirmer si nécessaire,
(c) tarif / PO / dates à fournir · D6 (a)(b)(c) OUI · D7 OUI · D8 strict + dérogation motivée sur 12 ET 13 · D9 OUI · D10 déploiement après D1-D9, après checkpoint.

## Fait le 2026-10-06
- D8 : contrôle 13 (fin de période ≤ date de facture) ; 12 et 13 bloquants, dérogeables un par un avec motif écrit ≥ 10 car. (audit
  `invoice_check_derogation` : contrôle, anomalie, motif, auteur, horodatage ; imprimé nulle part) ; échec arithmétique du 12 jamais dérogeable.
- D6 : période dans la cellule DESCRIPTION (3 lignes de description max sur facture, 4 sur note de crédit) ; plus rien sous les totaux ;
  annexe chronologique (historique d'abord), légendes seulement si l'annexe contient de l'antériorité ; ligne période + cutoff en dernière page ;
  toutes les pages numérotées (inchangé). Gabarit revalidé contre la facture réelle 2026-09 (écarts verticaux ≤ 0,7 pt) → `app/golden_layout.json`.
- D1/D2/D3/D4 : `outils/charger_factures_historiques.py` (simulation par défaut ; --appliquer --confirmer CHARGER-23-A-VALIDER, « à valider » seulement).
  Simulation sur copie staging : 23 lignes, 205,63 j, 133 659,50 CHF ; résultats `import/g4-simulation-d1-20261006/`. N5 rectifié.
- schema_checks : registre (table, déclencheurs, index, écritures compilables). 20-backup/50-verify : empreintes saisies/factures/mandats/paramètres.
- Unitaires 440/440.

## État pour la reprise par claude2 (16h41) — vérifié le 2026-10-06 06:50 UTC
- Branche `design-liquid-glass-rc14` = **40ee1dc** (tests adaptés à D8, journaux G4, `migration-blanc/dry-run-d-g4.sh`). Code `app/` inchangé depuis 74cf62a.
  Le worktree `/root/tb-wt-ux6` (branche `ux-tests-c1c6-20261006`) pointe sur le même commit, propre : peut être retiré.
- Image candidate `time-billing-v9-staging-time-billing-v9-staging:rc19` (sha256:131cf0c998ea…) = `app/` + `requirements.lock` du dépôt (48 fichiers identiques).
- Tests relancés sur cette image : unitaires **440/440** ; recettes sur copies jetables (`recette/reprise-1641/recettes-reprise.txt`) :
  R 49/49, A–K/Q 305/305, M/N/L 32/32, navigateur + e2e + concurrence 0 échec. Répétitions C et D : GO (00:55-00:56 UTC, même code, non relancées).
- Staging : 9.2-rc18, base `24884dfe…` inchangée depuis le brouillon n°1 (2026-10-05 22:42). Production : `bd31f410…`, non touchée.
- Non commités dans l'arbre : ce fichier et `NOTE-SESSIONS-PARALLELES.md` (deux paragraphes). Non suivis, laissés tels quels :
  `audit/g4/sortie/rendu-reference-d6-20261006.pdf` (mode 600), `journaux/fonc/staging-sha-debut.txt` (2026-10-05).

## ÉTAT COURANT — 2026-10-06 ~21:10 UTC (session 412386, reprise de HANDOFF-CLAUDE2-20261007-0315) — À LIRE EN PREMIER
- Git : branche `design-liquid-glass-rc14`, HEAD **40ee1dc**, RIEN commité ni poussé, rien déployé. Arbre de travail = correctifs de fidélité
  (`journaux/g4/fidelite-20261006/correctifs-non-integres.patch`, intégré par la session 323542) + suites de la revue adverse ci-dessous.
  Instantané complet de l'arbre : `journaux/g4/fidelite-20261006/arbre-de-travail-20261006-2110.patch` (git diff HEAD + fichiers non suivis).
- Consigne de l'utilisateur (2026-10-06 20:21) : travailler uniquement dans le dépôt, ne JAMAIS toucher `/opt/time-billing-v9` ni la production.
  Cette session n'a lu AUCUN fichier sous `/opt` (empreintes staging/prod non relevées). Recettes sur la copie exacte du staging 958c76ed…
  (`recette/reprise-2025/source/`, prise le 06.10 à 08:42 UTC, = base de la chaîne p1) avec des copies des scripts sans chemin `/opt`
  (`recette/reprise-2025/outils-chaine/`, LISEZMOI). Lancement : `recette/reprise-2025/chaine.sh <image> <tag>`.
- Revue adverse (workflows des 14:26 et 20:25, `journaux/g4/fidelite-20261006/revue-adverse-20261006.json`) : relecteurs axe E/PDF, contrôles,
  import, formulaires/numérotation, points ouverts ; contre-vérifications de l'axe E. Corrigé dans l'arbre (chaque correctif a un test qui échoue
  avant et passe après, sauf mention) :
  | Réf. | Sévérité | Correctif |
  |---|---|---|
  | A5 (recette) | régression du patch | durée : le signe est lu, « -1 » garde le message « positive » |
  | R-CHK-1 | mineur, régression du patch | contrôle 12 : écart narratif mesuré sur le total imprimé (6 déc.) avec tolérance ; 28 h de pointages = 3,5 j exactement |
  | R-CHK-2 / R-PO-B2 | majeur (brouillon n°1) | un brouillon au tarif 0 reprend le tarif du mandat à son enregistrement (flash) ; un tarif ≠ 0 reste figé (rc11 QA-02) ; messages du contrôle 3 explicites |
  | R-E3-1 | choix d'implémentation | contrôle 10 : un libellé AUTRES non imprimé (montant 0) bloque toujours, l'anomalie dit « non imprimé… : le vider » |
  | R-E3-2 | mineur, préexistant | libellé AUTRES refusé s'il déborde sur son montant dans les totaux (facture et « AUTRES CRÉDITÉ ») ; contrôle 11 pour les anciens brouillons |
  | R-E5-1 / E-5 | mineur | une 3e ligne de description et la période restent dans la colonne DESCRIPTION : les totaux ne bougent plus (application de D6 « aucun élément du modèle ne bouge » ; mesuré par pdftotext -bbox sur l'hôte : `e5-mesure-2040/`) |
  | R-E7-1 | mineur | « Jours annulés » = notes de crédit sur les factures comptées à la coupure (position, contrôle 7, légende) |
  | F-N1-1 | majeur | n° 2026-09 (CIRSE 2026, facture réelle) réservé même registre vide : `EXTERNAL_INVOICE_NUMBERS` (défaut `2026-09` dans `procedure/docker-compose.staging.yml` et `.prod.yml`, vide dans les tests) ; le chargeur D1 s'arrête si une facture TB porte déjà ce n° |
  | F-C3-1/2 | mineurs | motifs : invisibles collés depuis Word/le web retirés (U+00AD, U+200B, U+2060, U+FEFF), joints d'emoji acceptés, caractère refusé nommé ; la même règle s'applique aux motifs de dérogation D8 |
  | F-C5-1 | mineur | heures : chiffres ASCII seulement (saisie et import) |
  | F-D02-1, F-D06-1, F-D07-1 | mineurs | date de rejet en JJ.MM.AAAA (Zurich) ; libellé de la prévision exact ; le chargeur se lance tel que documenté (simulation reproduite à l'octet) |
  | R-IMP-1..4 | 1 majeur, 3 mineurs | import : `source_row_changed` devient une ERREUR si la saisie issue de cette ligne existe et 4 valeurs sur 6 sont identiques (sinon avertissement « saisie supprimée depuis ») ; ligne sans horaire déjà importée et décalée → avertissement `possible_already_imported` ; valeurs comparées normalisées (0.8000000000000007 = 0.800000000000001, date/datetime) ; exclusion rappelée après décalage |
- Tests : suite unitaire complète et chaîne de recettes complète sur l'image candidate `tb-g4-fidelite-cand:p5-20261006` : voir le bloc RÉSULTATS
  ci-dessous. Passe p2 (avant les derniers correctifs) : unitaires 457/457, R 49/49, A–K/Q 305/305, M/N/L 32/32, navigateur/e2e/concurrence 0 échec.
- NON corrigé, documenté : F-C2-1 (`num_field` accepte « 1_5 » / chiffres non latins, requête fabriquée seulement), R-IMP-5 (copie LibreOffice
  du classeur illisible par openpyxl, préexistant), R-PO-B3 (motif de dérogation non lié à l'anomalie affichée), R-PO-C (aucun contrôle ne détecte
  des saisies en double ; 0 cas sur les mandats actifs), R-PO-D (l'import ne compare pas les chevauchements avec la base), B5-B8, C4 (mineurs latents).

## DÉCISIONS À SOUMETTRE À L'UTILISATEUR (checkpoint, avant tout déploiement)
1. **D9 / E-2 (majeur, latent)** : date de coupure de la page de position. La fiche D9 est ambiguë (question : « datées au plus tard à sa date
   de fin de période » ; « Si OUI » : « état à la date de la facture »). Aujourd'hui : factures historiques coupées à la DATE DE LA FACTURE,
   factures TB antérieures coupées sur leur FIN DE PÉRIODE (une facture datée du 05.10 compte dans une facture antidatée du 01.10 : faux sous
   les deux lectures). À trancher : X = fin de période ou date de la facture ; ensuite une seule règle (historiques, TB par leur date, notes de crédit).
2. **E-4 (majeur)** : la note libre s'imprime sous le TOTAL et décale « Je vous remercie » (+5,4 pt par ligne ; au-delà de 3 lignes le bloc
   de paiement bouge). Le brouillon n°1 a une note d'une ligne. Choix : (a) note sur la dernière page (synthèse), ou (b) zone fixe d'une ligne
   avec limite à la saisie. Rien n'est appliqué.
3. **N1** : confirmer que les n° des factures réelles (2026-09 = CIRSE 2026) ne sont jamais réattribués (implémenté : registre + `EXTERNAL_INVOICE_NUMBERS`).
4. **Import** : confirmer la nouvelle règle (ligne du classeur modifiée depuis son import = erreur tant que sa saisie existe ; pour la réimporter,
   supprimer d'abord la saisie, ce qui est tracé). Sur le classeur réel : 33 lignes concernées (toutes déjà importées sous leur forme R1 corrigée).
5. **Données** : A-01 (15 notes de la colonne I non importées ; 11 sur mandats actifs) ; A-03 (notation h.mm : −1,032 h sur 43 saisies,
   −0,632 h sur 11 saisies actives : NHAF 2026 −0,232 h, STC GEM Oct −0,400 h) ; E-8 (adresse EGG BE sans retour à la ligne) ; R-E3-1 (choix ci-dessus).
6. Brouillon n°1 après déploiement : il échouera aux contrôles 3 (tarif 0 : saisir le tarif EUROPCR 2027 puis enregistrer le brouillon),
   10 (« test », « punaise », « unn »), 12 et 13 (dérogeables avec motif). Attendu (fiche D8).
7. Commit des modifications de l'arbre (rien n'est commité sans accord), puis D10 (déploiement staging) après go explicite.

## Reste
1. ~~Répétition dry-run C avec le code G4 ; lots HTTP / navigateur adaptés à D8 ; rebuild image :rc19~~ : FAIT (voir ci-dessus).
2. Checkpoint à l'utilisateur avec les décisions de la section « DÉCISIONS À SOUMETTRE » (D9/E-2, E-4, N1, règle d'import, données A-01/A-03/E-8).
   AUCUNE action staging avant son go. Appliquer ses choix E-2 / E-4 (tests + mesure pdftotext -bbox + comparer_pdf_reference.py si le gabarit change).
3. Après accord : commit de l'arbre (message à rédiger, rien n'est commité), image reconstruite depuis le commit et vérifiée identique,
   chaîne `recette/reprise-2025/chaine.sh` rejouée sur elle.
4. Après go D10 : déploiement staging (backup + 10→50 ; le fichier compose installe `EXTERNAL_INVOICE_NUMBERS=2026-09`), retour arrière testé,
   redéploiement ; puis logo (D7), n° projet EUROPCR 2027 (D5a), tarif EUROPCR 2027 (D5c) puis « enregistrer » le brouillon n°1 (il reprend
   alors le tarif), chargement des 23 lignes « à valider » (D1, go séparé ; le chargeur s'arrête si un n° de facture TB = un n° réel).
