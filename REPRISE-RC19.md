# MISE À JOUR 2026-10-05 ~23:05 UTC — RC19 EN ATTENTE (consigne « PILOTAGE GLOBAL » de l'utilisateur)
- Nouvelle consigne : STAGING uniquement, aucune nouvelle modification fonctionnelle avant l'audit G4 (rapprochement des factures historiques,
  modèle facture / période / timesheets / annexe, dashboard, PDF). Ordre : G4-1 → G4-6, puis seulement RC20. **Le déploiement staging de rc19 est suspendu.**
- Relecture de code rc19 faite (3 angles, lecture seule) : synthèse dans `REVUE-CODE-RC19.md`. 3 correctifs commités dans le checkpoint
  (suggestion par mandat, décision caduque après annulation de la note, note de crédit en heures exacte) ; unitaires 404/404 ; le reste est listé, non corrigé.
- **Le staging n'est plus vide de facture** : l'utilisateur y travaille (connexion 22:37 UTC) et a créé le **brouillon n° 1** (mandat EUROPCR 2027, période 2026-09-03 → 2026-10-31,
  2 j, description « test », date de facture 2026-10-07). Toute opération sur le staging (arrêt de 20-backup.sh compris) doit en tenir compte et le préserver.
  Sauvegarde cohérente du staging au checkpoint : `/root/backups/time-billing-v9-staging/checkpoint-g4-20261005T225128Z.db` (+ `.sha256`).
- Procédure de reprise de rc19 (ci-dessous) inchangée, mais les corrections de `procedure/90-rollback.sh` listées dans `REVUE-CODE-RC19.md` sont à faire avant le test de retour arrière.

# Reprise RC19 — état au 2026-10-05 ~13:45 UTC (pause demandée par l'utilisateur)

## Où on en est
- **Code rc19 : terminé, testé, commité localement** (branche `design-liquid-glass-rc14`), **non déployé**.
- **Staging (:8092) : toujours 9.2-rc18, non touché** (2 247 saisies, 1 934,4987 h, empreinte des saisies `c0feab5b…`, 0 facture).
  `procedure/staging.conf` pointe toujours `RC_IMAGE=…:rc18`.
- **Production : non touchée** (base `bd31f410…`, conteneur `0b25a343…` démarré le 02.10.2026).
- Image candidate construite : `time-billing-v9-staging-time-billing-v9-staging:rc19` (reconstruire si le code change).
- Aucun conteneur de test restant ; bacs à sable `migration-blanc/A19 B19 C19` (copies, hors dépôt) supprimables.

## Résultats obtenus (copies jetables uniquement)
Unitaires 401/401 · lot R (rc19, données réelles copiées) 49/49 · lots HTTP A–K + prévision + Q 303/303 · lots M/N/L 32/32 ·
navigateur 427/427 (dont recette-rc19 bureau + téléphone 37/37), 0 erreur console · répétitions de bascule A19 (prod V9.0) GO,
B19 (V9.0 fictive, factures héritées) GO, C19 (copie staging rc18 + 2 factures réelles, 2 processus, retour refusé puis forcé) GO.
Détails : `RAPPORT-RC19.md` (rapport utilisateur), `CONCEPTION-RC19.md` (conception implémentée), `journaux/rc19/recettes-rc19.txt`,
`migration-blanc/{A19,B19,C19}-dryrun-rc19.log`.

## Ce qui reste (dans l'ordre)
1. **Relecture de code contradictoire** du diff rc19 : interrompue par la pause (aucun constat produit). La relancer :
   3 angles (logique métier/écart, schéma/procédures/restauration, gabarits/sécurité) + vérification indépendante de chaque constat ;
   corriger les constats confirmés, rejouer `IMG=time-billing-v9-rc10-test:latest journaux/run_unit.sh $(ls tests/test_*.py | sed 's#tests/#tests.#;s#\.py##')`.
2. Si le code a changé : `docker build -t time-billing-v9-staging-time-billing-v9-staging:rc19 .` puis
   `journaux/rc19/toutes-recettes-rc19.sh` (lot R, A–Q, M/N/L, navigateur complet) et `migration-blanc/dry-run-c-rc19.sh`.
3. **Déploiement staging** (annoncer d'abord dans `NOTE-SESSIONS-PARALLELES.md`) :
   `sed -i 's/:rc18$/:rc19/' procedure/staging.conf` (ligne RC_IMAGE) ; `cp -p /opt/time-billing-v9-staging/.env /opt/time-billing-v9-staging/.env.rc19` ;
   `procedure/10-preflight.sh procedure/staging.conf` → `20-backup.sh` (arrête le service) → `30-rehearse.sh` → `40-deploy.sh` → `50-verify.sh`.
   Contrôler ensuite : santé rc19, 2 247 saisies identiques ligne à ligne (empreinte `c0feab5b…`), clé étrangère retirée, 0 facture.
4. **Test de retour arrière sur le staging** : `procedure/90-rollback.sh procedure/staging.conf` (aucune correction rc19 entre-temps,
   donc accepté) → base = sauvegarde (SHA identique), santé rc18 → puis redéploiement rc19 (recopier `.env` en `.env.rc19`, refaire
   10 → 50).
5. Mettre à jour `RAPPORT-RC19.md` §5 (statut staging), `CHECKPOINT-TIME-BILLING-V9.md`, la mémoire ; commit.

## Points d'attention pour la reprise
- `90-rollback.sh` refuse désormais d'écarter des corrections ou décisions enregistrées après la sauvegarde du déploiement (copie de la
  base vivante dans `ecarte-<TS>/`) ; forcer seulement avec `ABANDONNER_CORRECTIONS=OUI` après export.
- La migration rc19 s'exécute au premier démarrage (2 processus gunicorn : sérialisée par BEGIN IMMEDIATE, répétée en C19).
- Le staging réel n'a aucune facture : sa reconstruction de l'annexe porte sur 0 ligne (le chemin avec lignes est couvert par C19).
- Décisions utilisateur éventuelles (non bloquantes) pour RC20 : saisie oubliée sur mandat clôturé sans réouverture ; date
  « facturé hors application jusqu'au » par mandat ; identifiant juridique client des mandats actifs (compensation par note de crédit).
