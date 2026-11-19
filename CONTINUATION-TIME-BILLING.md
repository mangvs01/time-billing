# CONTINUATION — Time Billing V9.2 (source de vérité pour toute reprise)

> Lire d'abord `ETAT-TIME-BILLING.md`, puis `RAPPORT-RECETTE-FINAL.md`. Ne rien relancer qui tourne déjà : vérifier `ps`, `tmux ls`, `git status`.

## Contexte
* Dépôt `/root/time-billing-v9-rc10-20261004`, branche `design-liquid-glass-rc14` (HEAD `57983f1`, 9.2-rc15), `main` = RC13. Local uniquement.
* Staging `/opt/time-billing-v9-staging` (:8092, 9.2-rc15). Production `/opt/time-billing-v9` (:8091, V9.0) : **interdite**, empreintes dans `audit/prod-fp-avant.txt`.
* Autres sessions : lire/écrire `NOTE-SESSIONS-PARALLELES.md` avant de toucher au staging.
* Interdits permanents : LUMO, AMO Cockpit, production, import réel, factures émises, secrets/DNS/Caddy/pare-feu/SSH, fusion dans `main` sans validation.

## Commandes
* Unitaires (360) : `MODS=$(ls tests/test_*.py | sed 's#tests/#tests.#;s#\.py$##' | tr '\n' ' '); IMG=time-billing-v9-rc10-test:latest journaux/run_unit.sh $MODS`
* Recette complète d'une image non déployée : `docker build -t tb-x:rcN .` puis `RUN=x PFX=tb-x PB=83xx IMG_REF=tb-x:rcN journaux/recette_navigateur_final.sh` (copie de base jetable ; ports libres).
* Recette rapide : `IMG=tb-x:rcN nuit/outils/recette-rapide.sh`.
* Déploiement staging : `cp -p /opt/time-billing-v9-staging/.env /opt/time-billing-v9-staging/.env.<tag>` (ne jamais afficher), puis `cd procedure && ./10-preflight.sh staging.conf && ./20-backup.sh staging.conf && ./30-rehearse.sh staging.conf && ./40-deploy.sh staging.conf && ./50-verify.sh staging.conf`. Tag dérivé de `VERSION` dans `app/app.py` ; mettre à jour `RC_IMAGE` dans `procedure/staging.conf`.
* Pièges : Flask met les gabarits en cache par processus (redémarrer le conteneur) ; pas de `text-transform:uppercase` sur les libellés (les recettes lisent `innerText`) ; pas de `overflow-wrap:anywhere` ; ne pas changer ids/classes/libellés.

## Prochaine étape exacte
1. L'utilisateur parcourt le staging (tunnel `:8092`) ou la démo (`:8095`) et se prononce sur le design (et fournit le mockup s'il existe).
2. Selon retours : RC16 (retouches visuelles) — ou, si validé : répondre aux décisions R1–R3/M1–M5/M7/T3/« 8 h », puis autorisation d'import réel, puis plan de bascule production.
3. Optionnel après validation métier : graphique de consommation cumulée par mois (nécessite une agrégation en lecture seule dans `app.py` + tests de calcul).

## Rollback
* Staging RC15 → RC14 : `cd procedure && ./90-rollback.sh staging.conf` (restaure code + base de `/root/backups/time-billing-v9-staging/pre-rc15-20261005T004416Z`, image `:pre-rc15-20261005T004416Z`, contrôle SHA-256 ; re-`cp -p .env .env.rc15` avant un redéploiement). Retour RC13 : sauvegarde `pre-rc14-20261004T132654Z`.
* Dépôt : `git revert 57983f1` (ou `git checkout d33dca2 -- app tests procedure`).
* Démo : `docker rm -f tb-demo` puis relance sur `…:pre-rc15-20261005T004416Z` avec `/root/demo-time-billing/data`.
* Le rollback RC15 → RC14 n'a pas été rejoué cette session (rollbacks RC14→RC13 et RC13→RC12 l'ont été) ; la sauvegarde et la répétition de migration (GO) sont en place.
