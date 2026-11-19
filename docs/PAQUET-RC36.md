# Paquet de déploiement Billing 9.2-rc36 (candidat)

Mission BILLING-CALENDRIER-FINAL (claude0), 25.10.2026. Document de préparation : **rien n'a été exécuté en production**, rien n'est commité, construit ni déployé. Aucun secret n'est lu ni affiché ici.

## Conclusion

**Prêt à cliquer GO : NON.** Bloquants :

1. **rc36 n'est pas commité.** Le travail est dans le worktree `.claude/worktrees/billing-calendrier` (arbre de travail, non suivi en grande partie). Un commit par le propriétaire est nécessaire avant de figer la copie de publication (message proposé en section 7).
2. **rc35 n'est pas encore en production** (production = rc34 d'après `PAQUET-RC35.md`, ou rc35 si ce paquet a été exécuté depuis : à confirmer). rc36 **contient** rc35 : déployer rc36 revient à déployer thème + calendrier d'un coup. Décision section 8.
3. **Copie de publication figée absente** et **`procedure/prod.conf` à mettre à jour** (mêmes points que `PAQUET-RC35.md`, sections 1 et 3).
4. **Données du calendrier jamais relues** : `revue_le` vaut `null` dans les 3 fichiers de `app/donnees_calendrier/`. Le bandeau « Données à revoir » reste affiché tant que le propriétaire n'a pas relu les dates sur les sources officielles.

## 1. Version et contenu

| | |
|---|---|
| Version à produire | `9.2-rc36` (`VERSION` dans `app/app.py`) |
| Base | `campaign/billing-ux-lot2` @ `7934b04` (rc35 : `c32c619`, `1d5c9e7`, `c4b652d`, paquet) |
| Worktree | `.claude/worktrees/billing-calendrier` — **parti de `0dfcdb7` (rc34)** ; les changements rc35 (`app/` et `tests/`) y ont été **intégrés dans l'arbre de travail**, sans commit, checkout ni reset (voir ci-dessous) |
| Copie à figer | `9.2-rc36-<commit>` (à créer par le propriétaire après commit) |

**Calendrier (rc36)** : page `/calendrier` (alertes, 30 prochains jours, vue du mois, réglages), export iCal `/calendrier.ics`, abonnement par lien secret (`/calendrier/abonnement/<jeton>.ics`, création et révocation), encart « Calendrier et alertes » sur le tableau de bord. Échéances fiscales et sociales (Genève), jours fériés, vacances scolaires et jalons des mandats viennent de trois fichiers de données ; alertes à 8 000 CHF (non facturé, retard), bon de commande. Tout est calculé à l'affichage.

Fichiers du calendrier : `app/calendar_service.py`, `app/donnees_calendrier/{echeances,jours_feries,vacances_scolaires_ge}.json`, `app/templates/{calendrier,_calendrier_blocs,_calendrier_reglages}.html`, modifications de `app/app.py` (routes, version), `_ds.html` (CSS), `_sidebar.html`, `index.html`, tests `tests/test_calendrier.py`, `tests/browser/recette-calendrier.js`.

**Intégration rc35 dans le worktree** (cette mission) :

- Fichiers non touchés par le calendrier : repris tels quels de `7934b04` (`_page.html`, `_style.html`, `_theme_head.html` nouveau, `entries.html`, `entry_edit.html`, `import_review.html`, `login.html`, `test_theme.py` nouveau, `recette-theme.js` nouveau, `recette-ux-lot1.js`, `recette-ux-lot2.js`, `test_rc14_nuit.py`).
- Fichiers modifiés des deux côtés : fusion à trois voies (base `0dfcdb7`) pour `_ds.html` et `index.html` (sans conflit) ; `app.py` (version rc36 conservée), `test_ux_lot2.py` (assertion de version souple de rc35), `_sidebar.html` (bouton de bascule d'en-tête et bouton « Thème » du menu « Plus » ajoutés à la barre qui porte déjà le lien Calendrier).
- Adaptations nécessaires au calendrier : `calendrier.html` porte `data-theme="dark"` et inclut `_theme_head.html` (sinon la page s'ouvrait claire et sans bascule) ; `test_theme.py` : version ≥ rc35 au lieu de `== rc35`, `calendrier.html` ajouté à la liste des pages, `/calendrier` ajouté aux pages ouvertes en sombre ; `_ds.html` : `overflow-wrap:anywhere` (3 occurrences, interdit par `test_rc10`) remplacé par `overflow-wrap:break-word` / `word-break:break-all`.
- Non repris : `docs/PAQUET-RC35.md` (déjà dans la branche).

Nature : **affichage et lecture seule**. Aucune règle de facturation, TVA, arrondi, contrôle ni numérotation. **Aucune migration, aucune table ni colonne ajoutée.** Seules écritures nouvelles : clés `cal_*` et jeton d'abonnement dans la table `settings` (la table existe). `requirements.*`, `Dockerfile`, compose et `procedure/` inchangés. Retour arrière du code vers rc35 sans risque pour la base (les clés `cal_*` sont ignorées par rc35).

## 2. Tests exigés

Lancement : `test-slot` (aucune attente), venv `/root/venvs/rc25-test-venv`, lanceur isolé `run_tests_isolated.py` (copie dans le scratchpad, racine fixée sur le worktree), base synthétique jetable, mot de passe et `SECRET_KEY` synthétiques, aucun `.env` lu. Recettes : instances jetables gunicorn sur 127.0.0.1:18095 à 18098 et 18097 (jamais 8091 ni 8092), bases vides dans le scratchpad, arrêtées à la fin de chaque recette. Aucune copie `git archive`, aucun `rm -rf`.

| Test | Résultat rc36 (arbre de travail) |
|---|---|
| Suite Python complète (51 modules `tests/test_*.py`) | **839 tests, OK (5 échecs attendus)**, 346 s |
| `recette-calendrier.js` (thèmes clair et sombre réels, bureau et téléphone) | **77/77 OK, 0 KO** |
| `recette-theme.js` `THEMES=light` | **141/141 OK** |
| `recette-theme.js` `THEMES=dark` | **141/141 OK** |
| `recette-ux-lot1.js` | **67/67 OK** |
| `recette-ux-lot2.js` | **87/87 OK** |

Historique : une première suite après intégration donnait 2 échecs (`test_rc10` : `overflow-wrap:anywhere` ; `test_theme` : liste des gabarits sans `calendrier.html`), corrigés comme décrit en section 1. Les 3 contrastes restants de la mission précédente (jetons clairs `--ink-3`, bleu, vert) disparaissent avec les jetons AA de rc35 (`1d5c9e7`). Le test du bouton « Exporter l'agenda » (fond en dégradé lu comme transparent, faux positif) est corrigé dans `recette-calendrier.js` : le fond en dégradé est la moyenne de ses couleurs, comme dans `recette-theme.js`. La palette sombre « simulée » de la recette est remplacée par le vrai thème (`localStorage` `tb-theme`).

Journaux et captures : scratchpad de la mission (`suite2.log`, `recette-cal.log`, `recette-light.log`, `recette-dark.log`, `recette-lot1.log`, `recette-lot2.log`, dossiers `run2-*`), non conservés dans le dépôt.

## 3. Commandes exactes

Identiques à `PAQUET-RC35.md` section 3, avec `rc36` à la place de `rc35` :

```sh
# A1 (après commit par le propriétaire, hors projet)
mkdir /root/time-billing-releases/9.2-rc36-<commit>
git -C /root/rc25-ui-20261014 archive <commit> app requirements.txt requirements.lock Dockerfile .dockerignore \
  | tar -x -C /root/time-billing-releases/9.2-rc36-<commit>
# A3 : prod.conf -> SOURCE_APP, SOURCE_REQ = 9.2-rc36-<commit> ; RC_IMAGE=tb-g4-cand:<commit> ; COMPOSE_TEMPLATE du dépôt courant
# A4 : cp -p /opt/time-billing-v9/.env /opt/time-billing-v9/.env.rc36 ; stat -c %a → 600
export CONFIRM_PROD=OUI-$(date -u +%Y%m%d)
bash $P/10-preflight.sh $P/prod.conf
bash $P/20-backup.sh   $P/prod.conf      # ARRÊTE le service ; sauvegarde pre-rc36-<TS>
bash $P/30-rehearse.sh $P/prod.conf
bash $P/40-deploy.sh   $P/prod.conf
bash $P/50-verify.sh   $P/prod.conf
unset CONFIRM_PROD
```

## 4. Vérifications de santé

Automatiques (`50-verify.sh`) : `/health` = `9.2-rc36`, `/login` 200, en-têtes CSP et `X-Frame-Options`, uid 10001, rootfs en lecture seule, base intacte (effectifs et empreintes identiques à `counts-before.json`).

Manuelles :

- `curl -s http://127.0.0.1:8091/health` → `{"status":"ok","version":"9.2-rc36"}`.
- Thème : fond graphite par défaut, bascule fonctionnelle, **y compris sur la page Calendrier**.
- `/calendrier` : alertes cohérentes avec le tableau de bord, 30 prochains jours, mois, bandeau « Données à revoir » visible (tant que `revue_le` est nul).
- `/calendrier.ics` (connecté) : 200 `text/calendar`. Abonnement : créer un lien, l'ouvrir hors session (200), le révoquer (le lien ne marche plus). **Ne pas coller le lien secret dans un message ou un journal.**
- Réglages du calendrier : envoyer le formulaire sans rien changer ne crée pas de ligne d'audit « settings_updated » (défauts `8000.00`).
- Aucune création de facture sur des données réelles sans accord.

## 5. Retour arrière

Cible : rc35 (ou rc34 si rc35 n'a pas été déployé). Image `time-billing-v9-time-billing-v9:pre-rc36-<TS>` et `bash $P/90-rollback.sh $P/prod.conf` (voir `PAQUET-RC35.md` section 5). Pas de migration : la base est compatible dans les deux sens, les clés `cal_*` de `settings` restent inertes. Si `90` refuse pour des écritures légitimes, ne pas forcer (exporter d'abord, puis seulement avec accord `ABANDONNER_CORRECTIONS=OUI-<TS>`).

## 6. Garde : au plus 2 versions antérieures conservées

Après rc36 : conserver les deux versions précédentes déployées (rc35 et rc34 si rc35 a été en production, sinon rc34 et rc33). Aucune suppression n'a été faite par cette mission ; tout retrait est une décision du propriétaire.

## 7. Message de commit proposé (propriétaire)

```
feat(billing): calendrier (échéances GE, fériés, vacances, jalons), alertes à 8 000 CHF, export iCal, version 9.2-rc36 candidate

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
```

Le worktree est sur la base rc34 mais son arbre contient désormais le contenu rc35 : avant de commiter, comparer à la branche (`git diff 7934b04 --stat` ne doit montrer que le calendrier, `version` et les adaptations de la section 1). Si l'arbre est commité sur `campaign/billing-ux-lot2` à `7934b04`, aucun conflit n'est attendu ; sinon refaire la fusion.

## 8. Décisions à faire valider

1. Déployer rc36 (thème + calendrier) en une fois, ou rc35 d'abord (paquet existant) puis rc36.
2. Relire les dates des 3 fichiers de données sur les sources officielles et renseigner `revue_le` (le bandeau « jamais relues » disparaît alors).
3. Canton « par défaut » : fixé par les données (`GE`), sans réglage. À confirmer.
4. Valider l'intégration rc35 faite à la main (section 1), ou la refaire par merge/rebase git au moment du commit.
5. Mêmes décisions que `PAQUET-RC35.md` section 7 : création de la copie de publication et mise à jour de `prod.conf`, réutilisation des secrets `.env`, courte interruption annoncée (procédure non blue-green), retrait de la plus ancienne version.
