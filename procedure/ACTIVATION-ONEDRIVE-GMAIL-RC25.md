# Time Billing RC25 — autorisation OneDrive et alertes Gmail

Ce guide configure uniquement les identifiants de sauvegarde distante. Il ne déploie pas l'application et ne modifie pas la base de production.

## 1. Autoriser OneDrive personnel

Compte prévu : `akinoguzhan@hotmail.fr`.

### Sur le VPS

Depuis un terminal SSH administrateur :

```bash
sudo install -d -o root -g root -m 700 /etc/time-billing-backup
sudo rclone config --config /etc/time-billing-backup/rclone.conf
```

Dans l'assistant rclone : créer un nouveau remote nommé `Onedrive`, sélectionner le backend `onedrive`, laisser l'identifiant client et le secret client vides, choisir la région `global`, puis refuser la configuration automatique si le VPS n'a pas de navigateur. Suivre exactement les instructions d'autorisation affichées par rclone.

### Sur le Mac ou l'ordinateur disposant d'un navigateur

Si rclone n'est pas installé, installer rclone depuis sa source officielle ou avec Homebrew (`brew install rclone`). Exécuter la commande `rclone authorize` exactement comme elle est affichée dans l'assistant du VPS. Se connecter au compte Microsoft personnel prévu et autoriser rclone.

Copier le JSON de jeton affiché par rclone directement dans l'invite du terminal VPS qui l'attend. **Ne jamais coller ce jeton dans ChatGPT, un e-mail, un ticket ou un dépôt Git.** Il s'agit d'un identifiant d'accès sensible.

Terminer l'assistant en sélectionnant le lecteur OneDrive personnel approprié et confirmer la configuration. Puis sur le VPS :

```bash
sudo chown root:root /etc/time-billing-backup/rclone.conf
sudo chmod 600 /etc/time-billing-backup/rclone.conf
sudo rclone lsd Onedrive: --config /etc/time-billing-backup/rclone.conf
```

La dernière commande doit lister les répertoires OneDrive sans afficher le jeton. Si elle échoue, arrêter et corriger l'autorisation avant de continuer.

## 2. Préparer le mot de passe Restic

Le mot de passe Restic protège le contenu du dépôt distant. S'il est perdu, les sauvegardes peuvent devenir irrécupérables même si le compte OneDrive reste accessible.

1. Générer un mot de passe long dans un gestionnaire de mots de passe.
2. Le conserver dans ce gestionnaire, avec une copie de récupération indépendante du VPS.
3. Sur le VPS, créer le fichier sans transmettre le secret par messagerie :

```bash
sudo install -o root -g root -m 600 /dev/null /etc/time-billing-backup/restic-password
sudoedit /etc/time-billing-backup/restic-password
sudo chown root:root /etc/time-billing-backup/restic-password
sudo chmod 600 /etc/time-billing-backup/restic-password
```

Coller le mot de passe dans l'éditeur local, enregistrer et quitter. Ne pas afficher le contenu du fichier dans le terminal partagé.

## 3. Préparer Gmail SMTP

Destinataire et expéditeur prévus : `oguzhannakin@gmail.com`.

1. Ouvrir le compte Google, puis **Sécurité → Comment vous connecter à Google → Validation en deux étapes**.
2. Si elle est désactivée, l'activer.
3. Ouvrir **Mots de passe des applications** et créer un mot de passe pour `Time Billing VPS` si cette option est disponible.
4. Utiliser `smtp.gmail.com`, port `587`, STARTTLS, et le compte Gmail complet comme identifiant SMTP.
5. Saisir le mot de passe d'application directement dans `/etc/time-billing-backup.env` sur le VPS. Ne pas le transmettre dans ChatGPT.

Ne pas activer la tâche planifiée à cette étape.

## 4. Après autorisation

Seulement après validation des accès, compléter `/etc/time-billing-backup.env` à partir du modèle `backup-offsite.example.conf`, avec propriétaire `root:root` et mode `600`. Initialiser le dépôt Restic une seule fois, exécuter une sauvegarde réelle, tester une alerte d'échec et restaurer vers un répertoire temporaire. Vérifier SQLite, les clés étrangères, les PDF figés et le schéma avant d'ajouter une tâche planifiée.

Ne jamais lancer `restic init` une seconde fois sur un dépôt existant. Ne pas modifier la tâche de sauvegarde de production avant validation de la restauration et autorisation explicite.
