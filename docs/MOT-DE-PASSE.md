# Mot de passe de Time Billing — changer, et revenir en arrière si on l'oublie (BMDP1)

## 1. Ce qui existe

Il y a **un seul compte** (l'utilisateur `APP_USER`, par défaut `admin`). Son mot de passe peut maintenant vivre à **deux endroits** :

| Où | Quand | Qui le change |
|---|---|---|
| **Le mot de passe de l'environnement** : variable `APP_PASSWORD_HASH` du fichier `.env` du serveur (hachage scrypt ; `APP_PASSWORD` en clair seulement dans l'ancien mode) | par défaut, tant que rien n'a été changé dans l'application | la personne qui gère le serveur (`procedure/rotate-secrets.sh`, `procedure/mot-de-passe-production.sh`) |
| **Le mot de passe changé dans l'application** : une ligne de la table `auth_credentials` de la base (hachage scrypt, jamais le mot de passe) | dès que le propriétaire utilise « Changer mon mot de passe » | le propriétaire, seul, depuis l'application |

**Règle de priorité : s'il y a une ligne dans `auth_credentials`, elle gagne ; l'environnement n'est alors plus consulté pour le mot de passe.** Sans ligne (base neuve, ou ligne effacée par la procédure de secours ci-dessous), tout se passe exactement comme avant. `SECRET_KEY` (la clé qui signe les cookies de session) reste dans l'environnement et n'est pas concernée.

## 2. Changer son mot de passe (propriétaire)

1. Se connecter. Menu **« Paramètres & sauvegardes »**, cadre **« Accès à l'application »**, bouton **« Changer mon mot de passe »** (sur téléphone : menu **« Plus »**, entrée **« Mot de passe »**).
2. Saisir le **mot de passe actuel**, puis le **nouveau mot de passe deux fois**.
3. Règles : **12 caractères au moins** (200 au plus), **différent de l'actuel**, deux saisies **identiques**. Une phrase de passe convient très bien. Le message de refus dit en français ce qui ne va pas, et rien n'est modifié.
4. Après « Mot de passe changé » : l'appareil utilisé **reste connecté** ; **tous les autres appareils sont déconnectés** (ils devront se reconnecter avec le nouveau mot de passe).
5. **5 erreurs de mot de passe actuel en 15 minutes** bloquent l'écran (et la connexion) depuis ce poste pendant 15 minutes : même compteur que la page de connexion.

Le mot de passe n'est **jamais** enregistré en clair : ni dans la base, ni dans le journal du service, ni dans le journal d'audit. L'audit note seulement **« mot de passe changé le <date et heure> »** (et les essais ratés avec l'adresse du poste, sans aucun mot de passe).

## 3. Secours : le nouveau mot de passe est oublié → revenir au mot de passe de l'environnement

À faire **sur le serveur**, par la personne qui le gère. On efface la ligne de la base : le mot de passe d'origine (celui de `APP_PASSWORD_HASH` dans le `.env`, rangé dans le gestionnaire de mots de passe du propriétaire) redevient valable. Rien d'autre n'est touché : factures, saisies, PDF figés, réglages restent identiques.

1. **Sauvegarder d'abord** (réflexe habituel avant toute intervention sur la base). Sur le serveur, depuis le dossier du projet :
   `procedure/backup-quotidien.sh procedure/prod.conf` — ou, au minimum, noter l'heure : une copie de la base existe déjà dans les sauvegardes quotidiennes.
2. **Vérifier la cible** : le conteneur de production s'appelle `time-billing-v9` (le staging : `time-billing-v9-staging`). Contrôle : `docker ps --format '{{.Names}}'`.
3. **Effacer le hachage de la base** (la commande n'affiche aucun mot de passe ; elle efface la ligne, révoque toutes les sessions ouvertes et écrit une ligne dans l'audit) :

```python
import sqlite3
c = sqlite3.connect("/data/timebilling.db", timeout=30)
n = c.execute("DELETE FROM auth_credentials").rowcount
c.execute("DELETE FROM web_sessions")
c.execute("INSERT INTO audit(event,detail) VALUES('password_reset_to_environment','retour au mot de passe de l''environnement (commande serveur)')")
c.commit()
print("lignes effacées :", n)
```

   Lancée dans le conteneur ainsi (copier le bloc Python ci-dessus dans `secours.py`, puis) :
   `docker exec -i time-billing-v9 python - < secours.py`
   Résultat attendu : `lignes effacées : 1` (ou `0` si le mot de passe n'avait jamais été changé dans l'application : alors le problème est ailleurs, voir 5).
4. **Se connecter** avec le mot de passe de l'environnement (celui d'avant le premier changement). Aucun redémarrage de service n'est nécessaire : la base est relue à chaque connexion. Une fois connecté, on peut choisir un nouveau mot de passe par l'écran « Changer mon mot de passe ». Supprimer `secours.py`.
5. **Si l'ancien mot de passe de l'environnement est lui aussi perdu** : générer un nouveau mot de passe d'environnement avec `procedure/mot-de-passe-production.sh procedure/prod.conf` (avec `CONFIRM_PROD=OUI-<AAAAMMJJ>`, comme `rotate-secrets.sh`) — **après** l'étape 3, sinon le mot de passe de l'application continuerait de primer.

## 4. Ce qu'il faut savoir sur les sauvegardes, la restauration et la promotion

- La **sauvegarde JSON** téléchargée depuis l'application **ne contient pas** le mot de passe (la table `auth_credentials` est de l'état de fonctionnement, comme les sessions) et sa **restauration ne le change pas** : restaurer une vieille sauvegarde ne ramène donc pas un vieux mot de passe.
- Les **copies de la base SQLite** (sauvegarde quotidienne, avant déploiement) contiennent le **hachage** (jamais le mot de passe) : revenir à une telle copie (`procedure/90-rollback.sh`) ramène le mot de passe **tel qu'il était à ce moment-là**. Si le propriétaire l'avait changé entre-temps, c'est l'ancien qui redevient valable (ou celui de l'environnement s'il n'y avait pas encore de ligne).
- La **promotion de la base du staging en production** (`procedure/70-promouvoir-base-staging.sh`) **efface** cette table de la copie : le mot de passe du staging ne passe jamais en production. `outils/empreinte_metier.py` ignore aussi cette table (hors données métier).
- Ce changement n'est pas une donnée métier : factures, PDF figés, contrôles et empreintes des tables métier sont identiques avant et après (vérifié par `tests/test_bmdp1_mot_de_passe.py`).

## 5. Si la connexion échoue malgré tout

| Constat | Piste |
|---|---|
| « Identifiants incorrects » avec le mot de passe d'environnement connu | une ligne existe dans `auth_credentials` : suivre l'étape 3 |
| « Trop de tentatives » | attendre 15 minutes (ou effacer les lignes de `login_failures` pour ce poste) |
| Le service ne démarre pas, message sur `APP_PASSWORD_HASH` / `SECRET_KEY` | contrôles de démarrage inchangés (`app/security.py`) : corriger le `.env` ; la base n'est pas en cause |
