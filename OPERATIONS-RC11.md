# Exploitation de Time Billing V9.2-rc11

Aucune des opérations ci-dessous n'est installée en production : ce sont des propositions prêtes à exécuter après accord.

## 1. Sauvegardes
| Quoi | Comment | Fréquence proposée |
|---|---|---|
| Copie SQLite à chaud (cohérente, sans arrêt) | `procedure/backup-quotidien.sh <conf>` : API de sauvegarde SQLite dans le conteneur, contrôle d'intégrité, SHA-256, rétention 30 quotidiennes + 12 mensuelles dans `BACKUP_BASE` (dossier 700, fichiers 600) | chaque nuit |
| Vérification de restaurabilité | `procedure/verifier-sauvegarde.sh <conf> <fichier.db>` : conteneur jetable sans réseau, intégrité, clés étrangères, empreintes de tous les PDF figés, annexes, déclencheurs ; code retour 0 = exploitable | chaque semaine, sur la dernière copie |
| Sauvegarde JSON complète (données + PDF figés) | bouton **Paramètres & sauvegardes** ; un rappel s'affiche sur le tableau de bord après 30 jours sans téléchargement | avant chaque opération sensible ; à conserver hors serveur |
| Archive des documents émis | onglet **Factures émises** → ZIP (PDF figés, index CSV, sommes SHA-256), par année ou complet | clôture annuelle, remise au comptable |

Proposition de tâche cron (à installer par root après accord, hors production tant que non autorisé) :
```
17 2 * * *  root  /root/time-billing-v9-rc10-20261004/procedure/backup-quotidien.sh /opt/time-billing-v9/procedure/prod.conf >> /var/log/time-billing-backup.log 2>&1
43 3 * * 0  root  /root/time-billing-v9-rc10-20261004/procedure/verifier-sauvegarde.sh /opt/time-billing-v9/procedure/prod.conf "$(ls -1t /root/backups/time-billing-v9-prod/quotidiennes/timebilling-*.db | head -1)" >> /var/log/time-billing-backup.log 2>&1
```
**ATTENTION (2026-10-08, répétition K) : ne pas installer ces lignes telles quelles.** Avec `prod.conf` (ROOT=/opt/time-billing-v9), le garde-fou
de `tb-common.sh` arrête tout script sans `CONFIRM_PROD=OUI-<date du jour>` : la sauvegarde s'arrêterait chaque nuit sans rien sauvegarder. Les
scripts sont dans le dépôt (`/root/time-billing-v9-rc10-20261004/procedure/`), pas sous `/opt/time-billing-v9/procedure/`. Choix soumis à
l'utilisateur (proposition de garde par empreinte SHA-256 : `RAPPORT-GARDE-PRODUCTION-RC25.md`, `procedure/cron-sauvegarde.example` ; non appliquée) : fiche Decision Center `billing-g5-sauvegarde-quotidienne`. Scripts eux-mêmes répétés sur une production fictive rc23 : GO
(`migration-blanc/K-SAUV-dryrun-20261008.log`).

Les sauvegardes restent sur le même serveur : **une copie hors serveur est indispensable** (disque ou stockage distant au choix du propriétaire ; non configuré).

## 2. Surveillance minimale
- Santé : `curl -s http://127.0.0.1:8091/health` → `{"status":"ok","version":"9.2-rc11"}` ; le conteneur redémarre seul (`restart: unless-stopped`).
- Journal d'audit applicatif : connexions (réussies, échouées, limitées), émissions, notes de crédit, corrections de saisies, sauvegardes, restaurations.
- À surveiller : espace disque (`df -h /`), nombre de redémarrages (`docker inspect time-billing-v9 --format '{{.RestartCount}}'`), taille de la base.

## 3. Accès réseau (inchangé depuis RC8, non appliqué)
- Écoute locale `127.0.0.1:8091` ; accès externe uniquement par Caddy en HTTPS (`procedure/caddy-time-billing.example`, nom DNS à confirmer). `TRUST_PROXY=1` n'est sûr que si l'application n'est **joignable que par Caddy** (sinon un client peut forger `X-Forwarded-For`).
- Caddy : limiter le corps des requêtes (`request_body { max_size 20MB }` globalement, mais **au moins 200 MB pour `/restore`** : une sauvegarde JSON complète contient tous les PDF figés, environ 180 Ko par facture, soit 35 Mo pour 120 factures ; l'application accepte jusqu'à 1 Go sur cette route) et les délais de lecture (`transport http { read_timeout 30s }` côté proxy) ; l'application est servie par gunicorn `gthread` (16 requêtes simultanées par défaut) et reste disponible face à des connexions lentes (essai : 6 connexions bloquées, `/health` en 30 ms).
- **Mise à jour 2026-10-08 (G5, billing.hudd-l.com)** : le bloc réellement installé est celui de `procedure/80-site-caddy.sh` (pas
  `caddy-time-billing.example`). Mesuré : 16 connexions envoyant le corps d'une requête au compte-gouttes occupaient les 16 fils du serveur
  (application indisponible). Le bloc contient donc `reverse_proxy … { request_buffers 64KB }` et `/login` refuse dès l'en-tête un corps
  > 16 Ko (rc24) ; les deux sont nécessaires (`journaux/audit-connexion-20261008/`). Les réglages globaux de Caddy (`timeouts`, `request_body`
  global) ne sont PAS modifiés : le Caddy est partagé avec d'autres sites. Un robot bloqué sur /login n'ajoute plus qu'une ligne d'audit
  par adresse et par quart d'heure (rc24 ; avant : environ 100 lignes/s).
- Pare-feu et SSH : voir `procedure/pare-feu-proposition.md` (décision du propriétaire du serveur).
- Anciennes versions V7/V8/V30 : leurs mots de passe étaient partagés avec V9 ; à arrêter ou isoler avant la rotation (opération O9 de la RC8).

## 4. Limites connues d'exploitation (voir aussi le rapport)
- Le conteneur s'exécute en utilisateur non privilégié (uid 10001), système de fichiers en lecture seule, sans capacité Linux, `no-new-privileges` (RC11). Le dossier de données de l'hôte doit appartenir à l'uid 10001 : `procedure/40-deploy.sh` le fait ; un retour arrière vers une ancienne version (root) reste possible sans changement.
- La sauvegarde JSON n'est pas signée : ne restaurer que des fichiers produits par l'application. La restauration contrôle que tout document émis, sa copie figée, son annexe et les historiques restent identiques colonne par colonne, mais un fichier forgé peut **ajouter** des lignes.
- L'application est mono-utilisateur (un seul mot de passe) ; pas de gestion de droits par rôle.
- CSP (RC11) : scripts uniquement avec nonce par requête, plus aucun gestionnaire en ligne ; `unsafe-inline` ne reste admis que pour les styles. Déconnexion = formulaire POST.
