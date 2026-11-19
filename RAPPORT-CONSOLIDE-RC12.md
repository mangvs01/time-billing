# Time Billing V9.2-rc12 — rapport de livraison (04.10.2026)

Complète `RAPPORT-CONSOLIDE-RC11.md` (toujours valable pour tout ce que RC12 ne mentionne pas). Données fictives uniquement.
**Aucun import réel, aucun déploiement en production, aucune donnée source supprimée.**

## 1. Résumé

RC12 solde les points ouverts de la QA RC10 qui relevaient du périmètre autorisé et corrige trois défauts de la procédure de recette découverts en route. Staging : **9.2-rc12 déployé, vérifié avant et après redémarrage**. Production : **inchangée** (empreintes identiques à `audit/prod-fp-avant.txt` : base, `app.py`, compose, conteneur démarré le 02.10 sans redémarrage). Recommandation inchangée : recette métier sur le staging, puis vos décisions du registre avant tout import.

## 2. Ce qui a été modifié

| Réf. | Changement |
|---|---|
| QA-21 (critère P3 « PDF sans débordement ») | Page 1 : adresse émetteur, adresse et contact de facturation, raison sociale juridique passent à la ligne dans leur colonne (150 / 164 pt) et réduisent leur corps (8 → 7 → 6,5 pt) si le bloc dépasse sa hauteur ; conditions de paiement, remerciements et pied de page passent à la ligne ou se réduisent. Aucun mot n'est coupé ni perdu. **À l'émission**, une adresse impossible à imprimer, ou un libellé « AUTRES » de plus de 4 lignes (contrôlé aussi à la création du brouillon), est **refusé avec un message** plutôt que tronqué sur un document immuable. Rendu court : identique à RC11 |
| QA-09 | Un formulaire refusé (saisie, mandat création/modification, brouillon création/modification, note de crédit) se réaffiche **avec ce qui a été tapé**. Stockage serveur transitoire (`kept_forms`, 1 emplacement par session, 2 min, usage unique, champs cachés jamais restitués, exclu de la sauvegarde et de la restauration) ; remplissage par script à nonce (CSP inchangée) |
| QA-25 | Le formulaire de correction d'une saisie porte un jeton de version : si un autre onglet a enregistré entre-temps, la 2e sauvegarde est **refusée**, les valeurs tapées sont conservées, l'historique n'est pas touché ; un nouvel enregistrement volontaire passe |
| QA-24 | `/archive.zip?year=AAAA` sans document → message explicite (plus de ZIP vide) ; le message « Brouillon créé » indique où le retrouver ; la page d'émission précise que le numéro définitif est confirmé à l'émission |
| Procédure | `50-verify.sh` : trois contrôles lisaient `cmd \| grep -q` sous `pipefail` (SIGPIPE) → faux échecs aléatoires **et**, pour « secrets absents des journaux », un faux succès possible ; réécrits avec une variable (détection d'un secret planté vérifiée) · `recette_navigateur_final.sh` : un échec ne faisait pas échouer le script, version attendue lue dans le code (plus de `rc11` en dur) · `migration-blanc/*.sh` indépendants du numéro de RC |
| Version | 9.2-rc12 (migration additive : table transitoire `kept_forms`) |

## 3. Ce qui a été testé et résultats

| Contrôle | Résultat |
|---|---|
| Suite unitaire/fonctionnelle, 19 modules, conteneur sans réseau, sur le code final | **322/322** (`journaux/unit-rc12-complet.log`) dont 14 nouveaux tests RC12 |
| Les 14 nouveaux tests rejoués sur le code RC11 | 12 échouent (ils détectent bien les défauts) ; 2 passent légitimement (texte conservé inerte dans la page, aucun texte perdu) |
| PDF : toutes les chaînes dessinées mesurées avec la vraie police (page portrait) | rien hors de 30–565 pt ; blocs au-dessus du tableau ; contrôle visuel (rendu PNG) d'un PDF à textes très longs et d'un PDF court |
| Recette navigateur RC12 (Chromium) : saisie conservée, mandat refusé, 2 onglets, facture émise à adresses très longues + `pdftotext -bbox`, archive vide | **22/22**, 0 erreur console (a révélé un bug réel de mon script de remplissage — radios — corrigé avant livraison) |
| Recette finale sur l'image déployée : métier 107+15 · saisies 34+7 · responsive 33 pages · HTTP 30+18 · concurrence 11/11 | **0 échec**, base staging inchangée |
| Migration à blanc V9.0 → RC12 → retour V9.0 (A : copie de la base de production, vide ; B : V9.0 avec factures fictives) | **GO** ; PDF figés identiques à V9.0 ; retour : base = sauvegarde (SHA-256), code = production V9.0, PDF identiques |
| Rollback réel sur le staging RC12 → RC11 puis redéploiement RC12 | base identique octet pour octet à la sauvegarde `pre-rc12-20261004T113715Z` ; redéploiement complet (préflight, sauvegarde `pre-rc12-20261004T114503Z`, répétition GO, déploiement, vérifications conformes avant/après redémarrage) |

Le premier lancement de la recette finale a montré 3 échecs (chaîne `9.2-rc11` codée en dur dans les scripts de recette, pas dans l'application) et que le script rendait quand même `rc=0` : les deux défauts sont corrigés, la recette a été rejouée en entier.

## 4. État

* **Staging** (`:8092`) : 9.2-rc12, non privilégié, lecture seule, écoute locale ; mot de passe inchangé ; base vide (aucun mandat). Retour possible : `procedure/90-rollback.sh procedure/staging.conf` (image `:pre-rc12-20261004T114503Z`).
* **Production** (V9.0, `:8091`) : non touchée. V7/V8/V30 toujours actives sur 8088–8090 (constat inchangé, §6.2 du rapport RC11).
* **Git** : dépôt local propre après le dernier commit ; rien n'a été poussé.

## 5. Registre de décisions techniques (prises par défaut conservateur, réversibles)

| # | Sujet | Décision | À confirmer par vous ? |
|---|---|---|---|
| T1 | POST sans `Origin` ni `Sec-Fetch-Site` | Toujours accepté (clients non navigateur, scripts de recette) ; `SameSite=Lax` s'applique | Non (risque faible) |
| T2 | `/health` public affiche la version | Conservé : les scripts de déploiement/rollback s'en servent. À restreindre au niveau de Caddy lors de la bascule | Avec le plan Caddy |
| T3 | QA-23 : prestation à cheval sur minuit / changement d'heure | Inchangé (refus de fin < début ; durée naïve aux 2 dimanches de changement d'heure). Une scission automatique à minuit est un choix métier | **Oui** si vous voulez la saisie « 22:00–02:00 » |
| T4 | QA-S2/S3 durcissements SQL (plafonds des opérations de crédit, tables sans déclencheur append-only) | Non faits : défense en profondeur sur un schéma déjà migré en production ; à traiter avec la bascule | Non |
| T5 | Registre d'import (R1–R3, M1–M5, M7) | Inchangé : `import/registre-final/` | **Oui** — bloque l'import |

## 6. Risques résiduels

1. Production exposée tant que la bascule n'est pas faite (mots de passe en clair dans le compose, écoute `0.0.0.0`, V7/V8/V30) — nécessite votre accord et le plan Caddy/DNS/pare-feu.
2. Le staging est vide : le rapprochement avec de vraies factures n'est pas possible tant qu'aucun mandat n'existe ; hypothèse « jour = 8 h » à confirmer.
3. Restent ouverts (confort) : QA-14/15 (reliquat, hors ordre : avertissements seulement), QA-22 (troncature « … » dans la colonne Motif de l'annexe), QA-23, QA-S2/S3, taille des archives (~180 Ko par facture).
4. Fonctionnement derrière le vrai Caddy HTTPS (cookies `Secure`, `TRUST_PROXY=1`) non éprouvé.
5. Copie hors serveur des sauvegardes à organiser par vous.
6. Sessions parallèles de Claude sur le serveur : coordination par `NOTE-SESSIONS-PARALLELES.md`.

## 7. Prochaine étape

Exécutée : RC12 livrée et déployée sur le staging. **Bloquée par une décision qui vous appartient** : recette métier sur le staging, réponses au registre (T3, T5), puis autorisation explicite et séparée pour l'import réel et pour la bascule en production.
