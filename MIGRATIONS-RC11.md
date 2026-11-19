# Migrations Time Billing V9.2-rc10 → rc12 et retour arrière

Aucune migration n'a été exécutée en production. Ce document décrit ce qui sera appliqué au premier démarrage de la RC10 et comment revenir en arrière.

## 1. Principe
La migration est **additive et idempotente**, exécutée par `init()` à chaque démarrage : `CREATE TABLE/INDEX/TRIGGER IF NOT EXISTS`, ajout de colonnes par `ensure_column`. Aucune colonne ni ligne existante n'est modifiée ou supprimée. Les factures émises avant l'existence des copies figées (V9.0) sont figées une seule fois avec le rendu V9.0 qui les a produites (audit `legacy_invoices_frozen`).

## 2. Ce qui change entre la production (V9.0 RC1) et la RC10
| Étape | Objet | Nature |
|---|---|---|
| V9.1/V9.2 (déjà répété à blanc en RC8) | colonnes de mandat/facture/note, tables `settings`, `invoice_snapshots`, `invoice_annex_entries`, `credit_note_*`, `credit_operations`, déclencheurs d'immuabilité | additif |
| RC5 | `invoice_date_changes` (historique des dates, ajout seul) | additif |
| RC8 | `login_failures` (limitation des tentatives) | additif |
| RC9 | aucune | — |
| **RC10** | **`entry_changes`** (historique des corrections et suppressions de saisies, ajout seul : 2 déclencheurs, 1 index) | additif |
| **RC10** | **`web_sessions`** (sessions révocables côté serveur) | additif |
| RC11 | aucune table (conteneur non privilégié : propriétaire du dossier de données changé au déploiement) | — |
| **RC12** | **`kept_forms`** (saisie d'un formulaire refusé, un emplacement par session, 2 minutes ; **transitoire** : exclue de la sauvegarde JSON et de la restauration, comme `web_sessions`) | additif |
Aucune des deux tables RC10 ne porte de clé étrangère : une saisie supprimée garde sa trace.

## 3. Répétition avant bascule
`procedure/30-rehearse.sh` rejoue la migration sur une **copie** de la sauvegarde, dans un conteneur sans réseau : intégrité, clés étrangères, colonnes d'origine inchangées, factures émises figées, empreintes des PDF, déclencheurs, idempotence. Code retour 0 = GO. Le rejeu complet (sauvegarde, répétition, rotation des secrets, déploiement, vérification avec redémarrage, retour arrière) a été exécuté sur une copie de la base de production et sur une copie enrichie de données fictives : voir `RAPPORT-RC10.md`.

## 4. Retour arrière
1. **Avant toute saisie nouvelle** : `procedure/90-rollback.sh` restaure l'arborescence, le Dockerfile, le compose, l'image et la **base d'avant migration** (SHA-256 identique à la sauvegarde, vérifié) ; démarrage refusé si les secrets de l'ancienne version manquent.
2. **Si des données ont été saisies depuis la bascule** : exporter d'abord (Paramètres → sauvegarde JSON, et `procedure/backup-quotidien.sh`). Le retour arrière ramène l'état d'avant bascule ; ces saisies devront être ressaisies ou réimportées depuis la sauvegarde JSON dans la version cible (la restauration refuse toute perte de document émis).
3. **Retour RC10 → RC9 sur le staging** : les deux tables ajoutées sont inoffensives pour le code RC9 (ignorées) ; retour d'image `docker tag …:pre-<horodatage> …:latest` puis `docker compose up -d --no-build`.
4. Retour RC12 → RC11 : la table `kept_forms` est ignorée par le code RC11 ; la base d'avant migration est de toute façon restaurée à l'identique par `90-rollback.sh`.
5. Les sauvegardes JSON produites par la RC10 contiennent les tables `entry_changes` et `web_sessions` : une RC9 refuserait de les restaurer (« table inconnue »), par construction.

## 5. Vérifications après migration
`procedure/50-verify.sh` (avant et après redémarrage) : santé et version, en-têtes de sécurité, écoute locale, serveur gthread, pages protégées, intégrité, effectifs identiques à la sauvegarde, copies figées, empreintes, tables et déclencheurs RC10, absence de secrets dans les journaux.
