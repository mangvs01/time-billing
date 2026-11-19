# RC25 — rapport de validation et de livraison
Date : 2026-10-09
Statut : **NO-GO production — tests applicatifs et de déploiement verts, opérations distantes et gouvernance des données encore bloquantes**

## Référence du candidat
- Branche : `remediation/rc25-production-readiness-local`.
- HEAD avant les compléments d'exploitation : `46952f7`.
- Code applicatif figé : commit `1ca5578`, archive immuable `/root/time-billing-releases/9.2-rc25-1ca5578`.
- SHA-256 de `app/app.py` dans le commit et l'archive : `7d7859816c4d3374dc647678f8d8d3d62885aa6d7230a1163db17e949fc4d75e`.
- Image candidate : `tb-g4-cand:1ca5578`, version `9.2-rc25`.
- Les fichiers de configuration de livraison pointent vers cette archive et cette image.
- Aucun push distant n'est configuré dans ce dépôt ; aucune publication n'a été effectuée.

## Résultats vérifiés sur le candidat
- Suite unitaire complète : **564 OK, 1 skipped** (dépendance environnementale `pdftotext` absente), exécutée sur base synthétique et environnement isolé.
- Tests ciblés facturation/restauration : **22 OK**.
- E2E phase 1, exécution antérieure : **30/30 PASS**.
- E2E complet sur une base synthétique fraîche avec l'image `1ca5578` : **phase 1 = 30/30 PASS ; redémarrage du conteneur ; phase 2 = 18/18 PASS**.
- Concurrence HTTP sur une instance jetable distincte et base vide synthétique : **11/11 PASS**.
- Répétition de déploiement/rollback `migration-blanc/dry-run-n-rc25-deploiement.sh`, avec `PROC=/root/time-billing-v9-rc25/procedure`, image `tb-g4-cand:1ca5578`, base synthétique : **50/50 scénarios conformes**, sortie finale `RÉPÉTITION N : TOUT CONFORME`.
- `git diff --check` et `bash -n` sur les scripts de livraison : OK avant les derniers ajouts d'exploitation ; revalider après commit.
- Smoke test de l'image, réseau désactivé : module démarre et annonce `9.2-rc25`.

## Copie de sauvegarde de production vérifiée en lecture seule
Autorisation donnée le 2026-10-09. Copie utilisée : `/tmp/rc25-prod-backup-readonly-20261009.db`, mode `0400`, issue de la sauvegarde locale du 2026-10-09.
- Empreinte contrôlée contre `SHA256SUMS` : conforme.
- `PRAGMA integrity_check` : `ok`.
- `PRAGMA foreign_key_check` : aucune violation.
- Validateur applicatif RC25 sur une copie jetable : **SAUVEGARDE EXPLOITABLE** ; déclencheurs, factures/notes figées, empreintes PDF et schéma contrôlés.
- Constat de contenu : les tables principales de cette sauvegarde contiennent zéro projet, zéro saisie, zéro facture et zéro note de crédit. C'est cohérent avec une base de production initialement vide, mais ce constat doit rester explicite avant toute promotion.
- Aucune base live n'a été ouverte ou modifiée.

## Sauvegarde distante et alerte e-mail
Décisions reçues : stockage objet/cloud et alerte e-mail.
- Script préparé : `procedure/backup-offsite.sh`, basé sur Restic vers un dépôt S3-compatible. Restic chiffre le contenu avant envoi ; le script vérifie l'empreinte et l'intégrité SQLite de la sauvegarde locale avant transfert, contrôle le dépôt, applique une rétention (30 quotidiennes / 12 mensuelles) et tente d'envoyer un e-mail en cas d'échec.
- Exemple de configuration sans secret : `procedure/backup-offsite.example.conf` ; procédure d'activation : `procedure/SAUVEGARDE-DISTANTE-RC25.md`.
- Syntaxe Bash et flux de commande validés avec un exécutable Restic simulé : **PASS**. Une panne de transfert simulée a déclenché un e-mail vers un serveur SMTP local de test ; sujet, étape en échec et code retour contrôlés : **PASS**. Aucun transfert distant ni e-mail réel n'a été tenté.
- Bloquants d'activation : Restic n'est pas installé ; aucun endpoint/bucket, identifiant de stockage, fichier de mot de passe Restic, serveur SMTP ou destinataire n'est configuré dans l'environnement. Ne pas mettre de secret dans Git. Le script n'a pas été ajouté à cron/systemd et n'est pas en production.
- La tâche locale de sauvegarde existante n'est pas modifiée ni exécutée pendant ces tests.

## Contrôle 14 / acomptes
- Analyse consignée dans `DECISION-CONTROLE-14-ACOMPTES-RC25.md`.
- Le candidat actuel comporte **13 contrôles**, pas de contrôle 14 autonome.
- Le reliquat négatif est déjà accepté via `negative_reliquat_reason` (motif d'au moins 10 caractères), avec trace dans la facture figée et dans l'audit append-only. Cette voie ne plafonne pas l'acompte à une clause/PO et ne gère pas un solde d'acomptes à amortir.
- Recommandation : ne pas rendre une règle générale de sur-facturation dérogeable. Étudier un type de facture d'acompte explicite, un plafond contractuel, un solde séparé et des imputations atomiques sur les factures suivantes. Aucun changement métier n'a été appliqué sans validation de la règle cible.

## Données réelles dans Git — blocage sécurité
- Le fichier de base confirmé comme copie de données réelles reste suivi dans l'historique Git local. Il a été ajouté au commit `2533019` du 2026-10-04.
- Aucun remote Git n'est configuré ici, et aucune publication n'a été faite depuis ce dépôt.
- Ne pas pousser ni publier le dépôt. Avant publication future, il faut retirer la base de l'arbre courant, l'exclure de Git, puis purger sa présence de tous les historiques/références concernés après sauvegarde sécurisée et revue. L'autre fichier de base, identifié comme fictif, doit être conservé séparément selon son usage de test.
- La purge de l'historique réel n'a pas été effectuée dans cette passe ; ce point reste bloquant.

## Environnements et sécurité
- Production, port 8091 : `/health` annonce `9.0-rc1`.
- Staging, port 8092 : `/health` annonce `9.2-rc25`.
- Candidat isolé, port 8093 : `/health` annonce `9.2-rc25`.
- Aucun déploiement ni changement de base n'a été réalisé.
- Le superviseur Billing/Claude2 reste désactivé ; ne pas réactiver un agent exécuté en root avant d'avoir livré et testé une isolation dédiée.
- Les tests E2E/concurrence ont utilisé des conteneurs jetables exposés uniquement sur loopback. Ils ne sont pas des environnements de service. Trois conteneurs de test synthétique restent démarrés sur `127.0.0.1:18093`, `:18094` et `:18095` ; ils devront être arrêtés après validation.

## Conditions restantes avant GO
1. Activer et prouver le transfert Restic réel vers un dépôt objet, puis tester l'alerte SMTP d'échec et un contrôle de restauration distante.
2. Finaliser la spécification des acomptes et décider si le mécanisme actuel de reliquat négatif doit être resserré avant RC25.
3. Purger le fichier réel de l'historique Git local et vérifier toutes les références avant toute publication.
4. Livrer l'isolation de l'agent autonome et faire une revue de sécurité adversariale indépendante.
5. Revalider les scripts et l'état des services après intégration des compléments d'exploitation.

## Conclusion
La validation fonctionnelle et la répétition de déploiement/rollback du candidat RC25 sont vertes. **La livraison reste NO-GO production** jusqu'à la configuration réelle du stockage objet/e-mail, à la décision sur les acomptes, à la purge sécurisée de l'historique Git et à la revue d'isolation de l'agent. Aucune bascule production n'est autorisée par ce rapport.
