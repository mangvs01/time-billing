# Procédure de déploiement — V9.2-rc11

> **Production : NON EXÉCUTÉE.** À dérouler uniquement après votre **autorisation explicite**. Chaque script refuse de toucher `/opt/time-billing-v9` tant que `CONFIRM_PROD=OUI-<AAAAMMJJ du jour>` n'est pas exporté.
> Ces scripts sont ceux **déjà joués sur le staging** (`procedure/staging.conf`, 2026-10-04 : sauvegarde, répétition, déploiement, vérification avec redémarrage, **retour arrière réel**, redéploiement) et en migration à blanc sur des copies de la base de production (`migration-blanc/`). Ils n'affichent jamais de secret.

Source : code `/root/time-billing-v9-rc10-20261004/app` (identique au code déployé en staging) · image de répétition `time-billing-v9-staging-time-billing-v9-staging:rc11` · configuration `procedure/prod.conf`.

## 0. Prérequis (avant la fenêtre)
| # | Prérequis | Pourquoi |
|---|---|---|
| 0.1 | Votre autorisation explicite, une date, une fenêtre (≈ 10 min d'interruption) | — |
| 0.2 | Nom DNS et site Caddy (`procedure/caddy-time-billing.example`), HTTPS testé | Le service n'écoute plus qu'en local (`127.0.0.1:8091`) |
| 0.3 | Nouveau mot de passe (≥ 16 caractères), différent de v7/v8 | Rotation : seul le hachage scrypt est stocké |
| 0.4 | Accès de secours testé : `ssh -L 8091:127.0.0.1:8091 root@<serveur>` | — |
| 0.5 | Sauvegarde JSON de l'application (Paramètres) si des données existent déjà | Le retour arrière ramène l'état d'avant |
| 0.6 | **Aucun import historique réel** n'est inclus dans cette bascule : la production reste vide jusqu'à un accord séparé | Périmètre |

## 1. Déroulé
```sh
cd /root/time-billing-v9-rc10-20261004/procedure
export CONFIRM_PROD=OUI-$(date -u +%Y%m%d)          # uniquement après accord
./10-preflight.sh prod.conf                          # sans interruption : santé, WAL, place disque, sources
./20-backup.sh    prod.conf                          # ARRÊT, image :pre-rc11-<TS>, base, arborescence, SHA256SUMS
./30-rehearse.sh  prod.conf                          # migration sur copie de la sauvegarde → GO (code 0) ou NO-GO
./rotate-secrets.sh prod.conf                        # mot de passe saisi sans écho → .env.rc11 (600)
./40-deploy.sh    prod.conf                          # code, compose RC11, .env, droits 700/600, build, démarrage
./50-verify.sh    prod.conf                          # contrôles, redémarrage, nouveaux contrôles
unset CONFIRM_PROD
```
Toute erreur arrête le script (`set -euo pipefail`). Avant l'étape 40 : `docker compose -p time-billing-v9 start` relance l'ancienne version. Après : `PROCEDURE-ROLLBACK-RC11.md`.

## 2. Critères de passage
| Étape | Go si |
|---|---|
| 20 | `sha256sum -c` conforme ; copie de la base identique à l'original |
| 30 | `GO` : intégrité, clés étrangères, colonnes d'origine inchangées, aucune facture émise sans copie figée, empreintes valides, migration idempotente |
| 50 | contrôles conformes avant **et** après redémarrage : santé `9.2-rc11`, connexion 200, en-têtes de sécurité, serveur gthread, pages protégées (302), **écoute locale uniquement**, base (intégrité, effectifs, copies figées, tables et déclencheurs RC11), aucun secret dans les journaux |

## 3. Après le déploiement (manuel)
1. Connexion via `https://<nom>` avec le nouveau mot de passe ; l'ancien est refusé.
2. Depuis un poste extérieur, `http://<IP>:8091` ne répond plus.
3. Empreinte finale : `journaux/prod-fp.sh` (rc8) > `/root/backups/time-billing-v9-prod/pre-rc11-<TS>/prod-empreinte-apres.txt`.
4. Tâches d'exploitation : `OPERATIONS-RC11.md` (sauvegarde quotidienne, vérification hebdomadaire, copie hors serveur).
5. Opérations à décider séparément : v7/v8/v30, pare-feu, SSH.

## 4. Ce que la bascule change en production
- **Code** : V9.0 → V9.2-rc11 ; migration additive au premier démarrage (`MIGRATIONS-RC11.md`) ; gel des factures émises (aucune aujourd'hui, base vide).
- **Compose** : aucun secret, écoute `127.0.0.1:8091`, `COOKIE_SECURE=1`, `TRUST_PROXY=1`, serveur gunicorn gthread.
- **Fichiers** : `.env` neuf (600), `data/` 700, base 600. **Secrets** : nouveau mot de passe (hachage scrypt), nouveau `SECRET_KEY` ; sessions ouvertes invalidées.

## 5. Import historique (après bascule, décision distincte)
Aucun import n'est exécuté par cette procédure. Quand vous l'autoriserez : sauvegarde (`20-backup`), création des mandats validés (table de correspondance), prévisualisation, décisions ligne à ligne, confirmation avec empreinte, puis contrôle de rapprochement (`import/staging-recette`) ; le retour arrière d'un lot est un bouton de l'application (refusé si une facture émise couvre une ligne du lot).

## Mise à jour 2026-10-07 — code déployé = copie de publication figée (bascule V9.0 → rc21)
- `procedure/prod.conf` et `procedure/staging.conf` déploient **`/root/time-billing-releases/9.2-rc21-51b7c1b/`** (git archive du commit 51b7c1b :
  app, requirements, Dockerfile, .dockerignore ; lecture seule ; `sha256sum -c SHA256SUMS`), et non plus l'arbre de développement. Empreinte
  `app_digest` 639d1594… = celle notée par 20 au déploiement du staging rc21 (13:09 UTC) : la production recevrait exactement le code recetté.
  Image de répétition : `tb-g4-cand:51b7c1b` (prod.conf désignait encore l'image rc14).
- Raison : 40 copie `SOURCE_APP` ; avec l'arbre, tout commit postérieur à la recette partait sous l'étiquette rc21. L'arbre est désormais en
  **9.2-rc22** (non déployée). Pour un futur déploiement rc22 : `git archive` vers `/root/time-billing-releases/9.2-rc22-<commit>/`, puis
  `SOURCE_APP`/`SOURCE_REQ`/`RC_IMAGE` des .conf mis à jour, après le go correspondant.
- Répétitions F avec cette copie (V9.0 → rc21 → retour V9.0, bacs à sable A21R/B21R reconstruits depuis l'archive A19/B19, aucune lecture de
  /opt) : **GO** (`migration-blanc/F-A21R-dryrun-rc21-publication.log`, `F-B21R-…`). Facture 3 de B = brouillon recalculé : écart de texte attendu
  (déjà présent en B19 et F-B21), identique à l'origine après retour.
- Données réelles en production : méthode à décider (Decision Center `billing-g4-donnees-production`, recommandation : promotion de la base du
  staging après recette, par un script dédié répété sur bac à sable). Le déroulé §1 ci-dessus ne charge aucune donnée.

## Mise à jour 2026-10-08 — données réelles : promotion de la base du staging (G4 = PROMOTE_STAGING_DB)
Décision de l'utilisateur (Decision Center `billing-g4-donnees-production`) : la base du staging, recettée, devient la base de la production ;
condition : toutes les données restent modifiables / corrigeables après la bascule. **Rien n'est exécuté avant l'autorisation de bascule (G5).**

Déroulé de la fenêtre de bascule (après la recette du staging : 24 historiques validées, brouillon de test n° 1 supprimé ou gardé selon ton choix) :
```sh
cd /root/time-billing-v9-rc10-20261004/procedure
export CONFIRM_PROD=OUI-$(date -u +%Y%m%d)                 # uniquement après accord G5
./10-preflight.sh prod.conf && ./20-backup.sh prod.conf && ./30-rehearse.sh prod.conf &&
./rotate-secrets.sh prod.conf &&                            # mot de passe de la PRODUCTION (celui du staging n'y sert pas)
./40-deploy.sh prod.conf && ./50-verify.sh prod.conf &&         # production dans la MÊME version que le staging, base encore vide
PROMOUVOIR=OUI ./70-promouvoir-base-staging.sh prod.conf staging.conf
unset CONFIRM_PROD
```
`70-promouvoir-base-staging.sh` refuse (sans rien arrêter) si : production et staging de versions ou de code différents ; la production contient
la moindre donnée métier (`outils/empreinte_metier.py vide` : saisies, mandats, factures, historiques, paramètres…) ; `PROMOUVOIR=OUI` absent.
Puis : arrêt du staging (gel) → copie cohérente de sa base → arrêt de la production → sauvegarde `BACKUP_BASE/promotion-<TS>/` (base d'origine,
copie du staging, copie promue, SHA256SUMS) → copie préparée (sessions web, formulaires gardés, échecs de connexion du staging retirés ;
événement d'audit `database_promoted_from_staging`) → installation → démarrage → contrôle **production = staging** sur toutes les tables
métier. Échec après l'arrêt de la production : base d'origine remise (SHA vérifié), production et staging relancés. Succès : le staging reste
**arrêté** (plus aucune saisie réelle dessus ; il redevient un environnement d'essai à sa relance). Les secrets restent ceux de la production.

Retour arrière : `ABANDONNER_CORRECTIONS=OUI-<TS du déploiement> ./90-rollback.sh prod.conf` → V9.0, base d'origine (SHA identique) ; sans la variable, refus
(les données promues comptent comme écrites depuis le déploiement). Les données restent intactes sur le staging et dans `promotion-<TS>/`.

Répétition H (`migration-blanc/dry-run-h-promotion.sh`, journal `H-PROMOTION-dryrun-20261008.log`, aucune lecture de /opt) : fausse production
V9.0 (archive A19, base vide) déployée en rc21 depuis la copie de publication, faux staging rc21 = sauvegarde du 07.10 13:08 avec les 24
historiques validées : refus versions différentes / sans confirmation / production non vide ; échec simulé après installation → base d'origine
remise, deux services relancés, staging intact ; promotion → production = staging, mot de passe du staging refusé et celui de la production
accepté, 24 historiques validées, une saisie corrigée en production après promotion (correction tracée) ; retour arrière → V9.0, base A d'origine
(SHA-256). **GO**. Relecture adverse du script (08.10) : piège de sortie robuste (set +e, signaux ignorés pendant la remise en place, base vivante jamais écrasée sans copie `production-echec.db`), indicateurs d arrêt posés avant l arrêt, gel du staging vérifié, configuration du staging lue sans héritage de la production, chiffres financiers dans la sauvegarde (600) et non dans le dépôt, contenu promu affiché avant installation ; répétition H rejouée : GO (36 contrôles). Lancer 70 dans tmux. Correction des factures historiques après bascule : décision `billing-g4-correction-historiques` (en attente).

## Mise à jour 2026-10-08 (~23:45 UTC) — G5 = PLAN_OK : prérequis, mot de passe, site Caddy (rien exécuté en production)
Décision `billing-g5-bascule-production` = PLAN_OK, nom **billing.hudd-l.com**, exécution **uniquement à la date et l'heure écrites par
l'utilisateur**, après contrôle des prérequis. Staging et copie désignée par prod.conf / staging.conf : **9.2-rc22** (D12, déployée le 07.10 23:38 UTC).
Fenêtre complète (dans tmux) :
```sh
cd /root/time-billing-v9-rc10-20261004/procedure
./00-prerequis-bascule.sh prod.conf staging.conf &&         # LECTURE SEULE, ne lit rien de la production ; code 0 exigé
export CONFIRM_PROD=OUI-$(date -u +%Y%m%d) &&              # uniquement à la date/heure de l'utilisateur
./10-preflight.sh prod.conf && ./20-backup.sh prod.conf && ./30-rehearse.sh prod.conf &&
./mot-de-passe-production.sh prod.conf &&                   # 24 caractères aléatoires → /root/time-billing-v9-mot-de-passe.txt (600), puis rotate-secrets
./40-deploy.sh prod.conf && ./50-verify.sh prod.conf &&
PROMOUVOIR=OUI ./70-promouvoir-base-staging.sh prod.conf staging.conf &&
./80-site-caddy.sh ajouter                                   # sauvegarde du Caddyfile, validate, reload, attente de https://billing.hudd-l.com/login = 200
unset CONFIRM_PROD
```
- `00-prerequis-bascule.sh` — bloquants : DNS A = 147.93.55.171 sur 1.1.1.1 et 8.8.8.8, aucun AAAA ; même copie de publication et même image
  dans les deux .conf, copie intacte ; staging en marche dans cette version ; Caddyfile candidat valide (`caddy validate` sur une copie) ;
  G5 = PLAN_OK et `billing-g4-correction-historiques` résolues ; 2 Go libres. Informatif : historiques / brouillons d'après la dernière sauvegarde
  du staging. État au 07.10 23:41 UTC : **seul manque le DNS** (enregistrement A billing.hudd-l.com → 147.93.55.171, chez Infomaniak).
  NB : la correction des historiques (A) sera livrée en rc23 : la bascule se fera alors dans la version du staging à ce moment (rc23 après
  son propre go de déploiement staging), les deux .conf désignant la même copie.
- `mot-de-passe-production.sh` : refuse si le fichier existe (jamais écrasé) ; fichier supprimé si rotate-secrets échoue ; mot de passe jamais affiché.
- `80-site-caddy.sh ajouter|retirer|bloc` : bloc entre marqueurs ; `retirer` redonne le Caddyfile d'origine à l'octet ; refus si un site du
  même nom non géré existe ; rechargement en échec → Caddyfile d'origine remis et rechargé ; Caddyfile réel → CONFIRM_PROD exigé.
  Répété sur une copie du Caddyfile (CADDY_RELOAD=true, ATTENTE=0) : ajout, refus en double, retrait (SHA identique), échec de rechargement
  (origine remise), refus sans confirmation, refus si site non géré présent. Caddyfile réel inchangé.
- Retour arrière : `./80-site-caddy.sh retirer` puis `ABANDONNER_CORRECTIONS=OUI-<TS du déploiement> ./90-rollback.sh prod.conf` (avec CONFIRM_PROD).

## Mise à jour 2026-10-08 (~00:10 UTC) — 9.2-rc23 : correction des factures historiques (billing-g4-correction-historiques = A)
Copie de publication figée `/root/time-billing-releases/9.2-rc23-50492d4` (git archive 50492d4, empreinte app_digest fb2bd971…, lecture seule,
SHA256SUMS), image de répétition `tb-g4-cand:50492d4`. **Non déployée** : fiche de déploiement staging `billing-d13-deploy-rc23` (Decision Center).
- Page « Factures historiques » : « Corriger » (ligne d'origine rejetée avec motif, valeurs du classeur conservées ; ligne corrigée validée,
  provenance « SUIVI 2026!M15 (correction 1) ») et « Ajouter une facture historique manquante » (« ajout manuel n° k »), motif obligatoire, journal
  d'audit `historical_invoice_corrected` / `historical_invoice_added`. Aucun changement de schéma (migration rc19 inchangée, 30-rehearse identique).
- Une facture n'est jamais comptée deux fois : une seule ligne validée par cellule source dès qu'une correction existe ; un n° validé une seule
  fois ; ligne manuelle identique à une ligne validée refusée ; ajout ressemblant = confirmation ; chargeur D1 et restauration JSON contrôlés.
- Preuves : unitaires 528/528 (16 nouveaux, échouent sur rc22) ; relecture adverse (2 défauts majeurs corrigés) ; répétition I
  (`migration-blanc/dry-run-i-rc23.sh`, journal `I-RC23-dryrun-20261008.log`, faux staging rc22 = sauvegarde pre-rc22-20261007T233832Z) : **GO**.
- Si D13 = GO : staging.conf **et** prod.conf → SOURCE_APP/SOURCE_REQ de la copie rc23, RC_IMAGE=tb-g4-cand:50492d4, puis 10 → 50 + test 90 +
  redéploiement (comme rc22) ; `.env.rc23` = copie du `.env` du staging. La bascule G5 se fait alors en rc23 (00-prerequis contrôle que les deux
  .conf désignent la même copie et que le staging tourne dans cette version).

## Mise à jour 2026-10-08 (~06:15 UTC) — D13 = GO_STAGING : exécution rc23 sur le staging
- 05:18 UTC : staging passé en rc23 (sauvegarde `pre-rc23-20261008T051822Z`, `procedure/staging-rc23.conf`) hors session Claude2 tracée.
  06:09 UTC : 50-verify conforme ; 06:10 : retour arrière réel → rc22 (base SHA identique) ; 06:11 : redéploiement 10/20/30 conformes, **40 arrêté
  avant modification** (`.env.rc23` absent, copie refusée à l'agent) ; 06:12 : staging relancé en **rc22**. Journaux : `journaux/deploy-staging-rc23-20261008/`.
- `staging.conf` et `prod.conf` désignent la copie figée `9.2-rc23-50492d4` (image `tb-g4-cand:50492d4`).
- **Ordre staging (mot de passe conservé)** : créer `.env.<rc>` AVANT 10 — `cp -p /opt/time-billing-v9-staging/.env /opt/time-billing-v9-staging/.env.rc23` —
  puis 10 → 50 (`procedure/staging.conf`). 10-preflight signale désormais `.env.<rc>` absent (« ATTENTION … 40 s'arrêtera ») ; ne pas lancer 20 dans ce cas.
  Production inchangée : rotate-secrets / mot-de-passe-production entre 30 et 40 (le service de production V9.0 est vide).

## Mise à jour 2026-10-08 (~09:15 UTC) — staging en rc23 : prérequis G5 tous remplis
- `.env.rc23` créé par l'utilisateur (08:35 UTC) ; 10 → 50 rejoués à 09:11 UTC avec `procedure/staging.conf` : staging = **9.2-rc23**
  (copie figée 50492d4), 50-verify conforme, données identiques (sauvegarde `pre-rc23-20261008T091053Z`). Journaux : `journaux/deploy-staging-rc23-20261008/*-final.log`.
- `00-prerequis-bascule.sh prod.conf staging.conf` (09:11 UTC) : **PRÉREQUIS REMPLIS**. La fenêtre ci-dessus se fait donc en rc23.
- Avant la fenêtre, à la main de l'utilisateur : la date et l'heure de la bascule (G5) ; la recette du staging (24 factures historiques encore
  « à valider », brouillon de test n° 1 à garder ou supprimer) ; la fiche `billing-g5-sauvegarde-quotidienne` (sans réponse, la production
  n'aura aucune sauvegarde automatique). La décision `billing-g4-correction-historiques` citée plus haut comme « en attente » est résolue (A, livrée en rc23).

## Mise à jour 2026-10-08 (~10:00 UTC) — bloc Caddy : request_buffers 64KB ; rc24 = 3f49b60
- `80-site-caddy.sh` : `reverse_proxy 127.0.0.1:8091 { request_buffers 64KB }` (connexions lentes : voir OPERATIONS-RC11 §3). Utile en rc23
  comme en rc24 ; protection complète avec rc24 (/login ≤ 16 Ko). Répétition 80 sur Caddyfile fictif : GO (`journaux/g5-caddy/`).
  Si le bloc a été ajouté avant cette modification, `retirer` l'enlève quand même (marqueurs) ; pour le mettre à jour : `retirer` puis `ajouter`.
- Copie figée rc24 à jour : `/root/time-billing-releases/9.2-rc24-3f49b60` (image `tb-g4-cand:3f49b60`) ; les copies 4a1d3d2 et 993cc82
  sont antérieures. Fiche de déploiement staging : `billing-d14-deploy-rc24`.

## Mise à jour 2026-10-09 — RC25 phase 2 (TB-06) : chaîne fail-closed
- **Enchaînement** : `&&` entre les étapes (un `;` laissait 40 partir après un 30 en échec). Surtout, 40 ne dépend plus de l'enchaînement :
  il **refuse** sans le marqueur `pre-<tag>-<TS>/rehearsal-GO` que seul un 30 GO écrit (code 0 et dernière ligne « GO »). Le marqueur est lié à
  la sauvegarde, au SHA-256 de sa base, à l'empreinte du code et à l'image de répétition : tout changement depuis 30 → relancer 30.
- **40, phase A (rien n'est modifié)** : SHA256SUMS de la sauvegarde, marqueur GO, service arrêté et base vivante identique à la sauvegarde
  (sinon des écritures postérieures seraient perdues au retour arrière : relancer 20 puis 30), image de retour disponible, `.env.<tag>` présent
  (600) et port publié = port de `URL`. Échec → l'ancienne version est relancée.
- **40, phase B (installation)** : un échec (build, compose, santé…) lance automatiquement `90-rollback.sh` (sans `ABANDONNER_CORRECTIONS`) ;
  90 refuse lui-même d'écarter des données écrites depuis la sauvegarde.
- **Pièges** (`tb-common.sh`) : un seul piège EXIT par script (`cleanup` / `on_fail`), interruptions comprises. 20 et 30 relancent l'ancienne
  version en cas d'échec (30 NO-GO compris : aucun marqueur GO ; la sauvegarde ne sert plus si des données sont écrites ensuite).
- **Port** : `rotate-secrets.sh` écrit `TB_PORT` = port de `URL` (8091 production, 8092 staging) ; avant, 8091 par défaut partout.
- **Image de retour** : 20 étiquette l'image réellement exécutée et en garde une copie `image.tar.gz` (SHA256SUMS) ; 90 la recharge si un
  `docker image prune -a` / `system prune -a` a supprimé l'étiquette `pre-…`, et vérifie son identifiant AVANT d'arrêter le service.
- Répétition N (`migration-blanc/dry-run-n-rc25-deploiement.sh`, bac à sable /tmp, base synthétique) : `N-RC25-dryrun-20261009.log` (50 contrôles
  conformes) ; même répétition sur les scripts d'avant (ee23940) : `N-RC25-dryrun-20261009-reference-ee23940.log` (40 déployé sans 30, etc.).
