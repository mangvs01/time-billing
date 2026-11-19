# Time Billing RC25 — activation de la sauvegarde distante

## Architecture retenue

- Source : sauvegarde SQLite locale déjà produite et inscrite dans son manifeste SHA-256 ; le script ne lit pas la base vivante.
- Destination : OneDrive via le backend rclone de Restic (seul un remote `rclone:Remote:chemin` est autorisé ; la variante S3 et les clés `AWS_*` sont supprimées et refusées). OneDrive nécessite une autorisation OAuth explicite et une configuration rclone root-only ; l’accès OneDrive est désormais autorisé sur le VPS ; le dépôt distant Restic n’est pas encore initialisé.
- Chiffrement : dépôt Restic chiffré côté serveur avant transfert ; le mot de passe du dépôt reste dans un fichier root-only, distinct de l'autorisation OAuth OneDrive et des identifiants SMTP.
- Alerte : e-mail en cas d'échec du contrôle local, du transfert, du contrôle du dépôt ou de la rétention.
- Rétention initiale : 30 snapshots quotidiens et 12 mensuels.
- Vérification : contrôle SQLite local, vérification Restic des données (sous-ensemble tournant), puis vérification des métadonnées du dépôt.

## Fichiers

- `backup-offsite.sh` : exécution après la sauvegarde locale. Il lit sa configuration comme des données et refuse de s'exécuter (hors `bash -p`) si `BASH_ENV`, `ENV`, `SHELLOPTS` ou une fonction exportée (`BASH_FUNC_*`) est présent. Invocation durcie, identique à celle de `cron-sauvegarde.example` (0d2f3ce) :
  `/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p /chemin/procedure/backup-offsite.sh /root/backups/time-billing-v9-prod/quotidiennes/timebilling-<horodatage>.db`
  Contrôle de configuration seul : `… /bin/bash -p backup-offsite.sh --check-config <fichier>`.
- `backup-offsite.example.conf` : modèle sans identifiant réel.
- Ne jamais copier les jetons d'accès, le mot de passe Restic ou le mot de passe SMTP dans Git, un journal, ou un ticket.

## Activation — non exécutée

1. Pour OneDrive, installer rclone et configurer un remote `Onedrive` via OAuth dans une session autorisée ; valider l'accès en lecture/écriture sur un dossier dédié. Ne pas enregistrer de mot de passe Microsoft dans le dépôt Git.
2. Installer Restic depuis le dépôt de paquets de l'OS et vérifier les versions de Restic et rclone.
3. Placer la configuration rclone dans `/etc/time-billing-backup/rclone.conf` (`root:root`, mode `600`). Créer le fichier root-only du mot de passe Restic (`root:root`, mode `600`).
4. Configurer `RESTIC_REPOSITORY="rclone:Onedrive:TimeBilling/production"` et `RCLONE_CONFIG="/etc/time-billing-backup/rclone.conf"`. Initialiser le dépôt Restic une seule fois ; ne jamais réinitialiser un dépôt existant.
5. Copier le modèle vers `/etc/time-billing-backup.env`, compléter la destination, le chemin du mot de passe Restic et les paramètres SMTP, puis définir `root:root` et le mode `600`. Le destinataire d'alerte prévu est `oguzhannakin@gmail.com`.
6. Tester manuellement le script (invocation durcie ci-dessus) sur une sauvegarde locale existante et vérifier le snapshot distant.
7. Tester volontairement un échec en recette et confirmer la réception réelle de l'e-mail.
8. Restaurer depuis OneDrive vers un répertoire jetable ; vérifier l'intégrité SQLite, les clés étrangères, les PDF figés et le schéma.
9. Seulement après réussite, ajouter une tâche planifiée après la sauvegarde quotidienne, avec la même invocation `env -i … bash -p` (jamais `bash` nu ni `source`). Le journal doit contenir le code retour et le nom du fichier, jamais les secrets.
10. Prévoir une alerte indépendante si la sauvegarde ou l'e-mail échoue : le SMTP ne peut pas signaler sa propre indisponibilité.

## État au 2026-10-09

- Syntaxe Bash validée.
- Flux Restic simulé validé.
- Échec de transfert simulé : l'e-mail a été livré à un serveur SMTP local de test et son contenu vérifié.
- Compte OneDrive choisi : `akinoguzhan@hotmail.fr` ; destinataire d'alerte prévu : `oguzhannakin@gmail.com`. Aucun jeton OAuth, secret Restic ou identifiant SMTP n'est configuré ; les adresses sont seulement inscrites dans le modèle.
- Restic n'est pas installé et aucune tâche planifiée n'a été créée.
- **La sauvegarde distante n'est donc pas encore active.** Ne pas annoncer une protection hors serveur tant qu'un transfert réel et une restauration de contrôle ne sont pas démontrés.
