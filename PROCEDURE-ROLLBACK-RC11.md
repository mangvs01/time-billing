# Procédure de retour arrière — V9.2-rc11

> **Production : NON EXÉCUTÉE.** Le script a été **joué réellement sur le staging le 2026-10-04** (RC11 → RC9 : base restaurée avec SHA-256 identique à la sauvegarde `bf742496…`, code identique à la RC9, santé `9.2-rc9`, puis redéploiement de la RC11), et en migration à blanc sur copies de la base de production.

## Quand l'utiliser
`40-deploy.sh` ou `50-verify.sh` en erreur, ou contrôle manuel en échec après déploiement. **Avant** le déploiement, rien à restaurer : `docker compose -p <projet> start` relance l'ancienne version.

## Préalable si des données ont été saisies depuis la bascule
Le retour arrière remet **la base d'avant la migration** : toute saisie faite depuis serait perdue. Exporter d'abord (Paramètres → sauvegarde JSON + `procedure/backup-quotidien.sh`). Une sauvegarde JSON RC11 contient `entry_changes` et `web_sessions` : une version antérieure la refuserait par construction.

## Commandes
```sh
cd /root/time-billing-v9-rc10-20261004/procedure
export CONFIRM_PROD=OUI-$(date -u +%Y%m%d)      # production seulement ; staging : ./90-rollback.sh staging.conf
./90-rollback.sh prod.conf
unset CONFIRM_PROD
```

## Ce que fait `90-rollback.sh`
1. Contrôle `sha256sum -c` de la sauvegarde (arrêt si altérée). 2. Arrêt du service RC11. 3. Mise à l'écart (dossier 700 `ecarte-<TS>`) du code, compose, `.env`, requirements — rien n'est supprimé. 4. Restauration depuis l'archive du code, compose, requirements, Dockerfile et `.env` d'origine. 5. Restauration de la base, suppression des WAL, SHA-256 **identique** exigé. 6. L'image `:pre-rc11-<TS>` redevient `latest`. 7. **Refus de démarrer** si un secret de l'ancienne version manque (la V9.0 retomberait sur son mot de passe par défaut). 8. Démarrage sans reconstruction, attente de la santé.

## Contrôles après retour arrière
`/health` = version d'origine (`9.0-rc1` en production, `9.2-rc9` en staging) ; `journaux/prod-fp.sh` : base au même SHA-256 que l'empreinte d'avant, code identique.

## Conséquences à connaître
Le compose d'origine est restauré tel quel (V9.0 : mot de passe en clair, écoute `0.0.0.0:8091`) : les failles correspondantes reviennent, une rotation reste à refaire à part. Le site Caddy éventuel continue de joindre `127.0.0.1:8091`.

## Retour d'un lot d'import historique (sans toucher au reste)
Bouton « Annuler le lot » (onglet Migration) : supprime uniquement les saisies du lot, conserve le registre des lignes ; **refusé** si une facture émise couvre une ligne du lot (jamais de réécriture d'un document émis).

## Mise à jour 2026-10-07 — ce que `90-rollback.sh` vérifie avant de remettre la sauvegarde (rc19 → rc21)
- **Sauvegarde du déploiement** : celle que 40 a réellement déployée (fichier `deployed` écrit par 40 ; à défaut `last-backup`), retrouvée par
  son horodatage et non par la VERSION du dépôt : le retour reste possible si le dépôt a changé de version, et un 20 relancé sans 40 ne change
  pas la cible (« NB : le dépôt est maintenant en … »). 30/40/50 refusent au contraire une sauvegarde faite pour une autre version.
- **Refus automatique** si le retour écarterait des données écrites depuis la sauvegarde : lignes ajoutées, modifiées ou supprimées dans toutes
  les tables métier (saisies, corrections, mandats, factures/brouillons, notes de crédit et annulations, historiques, imports, paramètres,
  copies figées, liens d'annexe). Audit, sessions et formulaires conservés ne comptent pas. Comparaison refaite service arrêté. Passer outre :
  exporter, puis `ABANDONNER_CORRECTIONS=OUI-<TS>` (la base écartée reste dans `ecarte-<TS>-retour-<TS>/`).
- **Tables et colonnes ajoutées par la migration** (bascule V9.0 → rc21 : `settings`, `historical_invoices`, `invoice_snapshots`, colonnes
  de `projects`, `invoices`, `credit_notes`…) : comparées à la sauvegarde **migrée deux fois par l'image déployée** ; les colonnes qui diffèrent
  entre les deux migrations (horodatage et PDF des copies figées) ne sont comparées que par leurs lignes. Retour juste après le déploiement :
  accepté. Copie migrée avec l'environnement non secret et les polices du conteneur déployé ; impossible : refus prudent (journal
  `migration-copie-m1.log` dans le dossier de copie ; si le déploiement a échoué avant toute saisie, `ABANDONNER_CORRECTIONS=OUI-<TS>` n'écarte rien d'utile).
- Répétitions : `migration-blanc/test-90-f.sh` (11 scénarios V9.0 → rc21 : 19/19, après relecture adverse), `dry-run-f.sh` A21/B21 et `dry-run-e-rc21.sh` (staging) : GO.

## Mise à jour 2026-10-08 — retour arrière après la promotion de la base du staging (G4)
Après `70-promouvoir-base-staging.sh`, toutes les données promues comptent comme « écrites depuis la sauvegarde du déploiement » : `90-rollback.sh`
refuse (liste des tables) ; `ABANDONNER_CORRECTIONS=OUI-<TS>` remet la base V9.0 d'origine (SHA-256 identique, répétition H). Les données promues ne
sont pas perdues : base du staging (arrêté, intact) et `BACKUP_BASE/promotion-<TS>/staging.db`. Toute saisie faite EN PRODUCTION après la
promotion serait en revanche écartée : l'exporter d'abord (sauvegarde JSON / export des saisies), comme pour tout retour arrière.

## Mise à jour 2026-10-09 — RC25 phase 2 (TB-06) : retour arrière sans perte silencieuse
- **Toutes les tables** sont comparées à la sauvegarde, sauf les tables transitoires nommées (audit, sessions, échecs de connexion, formulaires
  gardés) : une table métier absente de l'ancienne liste fixe (table future) était écartée sans avertissement.
- **Audit** : ne bloque pas le retour (bruit de connexion), mais le nombre de lignes postérieures à la sauvegarde mises de côté est affiché ;
  elles restent dans la copie `ecarte-<TS>-retour-<TS>/timebilling-avant-retour.db`.
- **Confirmation liée au déploiement** : `ABANDONNER_CORRECTIONS=OUI-<TS>` (TS = horodatage de la sauvegarde du déploiement, affiché dans le
  refus) ; un `OUI` resté exporté d'un retour précédent est refusé. Quand des données sont écartées, elles sont listées dans le journal avec la copie.
- **Image** : `:pre-<tag>-<TS>` vérifiée (identifiant = `image-id.txt`) ou rechargée depuis `image.tar.gz` de la sauvegarde **avant** l'arrêt du
  service ; sauvegarde sans copie et étiquette supprimée → refus, service inchangé (avant : arrêt, arborescence déplacée, puis échec « No such image »).
- **Pièges** : de l'arrêt jusqu'au remplacement de l'arborescence, un échec relance le service tel qu'il était ; après, message explicite
  (service arrêté, emplacement des fichiers mis à l'écart et de la copie de la base).
- Les harnais historiques (`migration-blanc/test-90-f.sh`, `dry-run-*.sh`) utilisent encore `ABANDONNER_CORRECTIONS=OUI` : à adapter avant d'être rejoués.
