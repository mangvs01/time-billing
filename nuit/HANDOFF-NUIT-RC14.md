# Transfert de contexte — RC14 (rédigé par la session interactive, 2026-10-04 ~15:45 UTC)

## 1. Où en est le projet
* Dépôt : `/root/time-billing-v9-rc10-20261004`, branche **`design-liquid-glass-rc14`**, commit de départ de la nuit **`10175fd`**. `main` = RC13 (ne pas fusionner).
* Staging : `/opt/time-billing-v9-staging`, `127.0.0.1:8092`, **9.2-rc14**, base vide. Sauvegardes `/root/backups/time-billing-v9-staging/pre-rc14-*` ; la plus récente (`pre-rc14-20261004T132654Z`) contient l'état RC13 (cible du rollback).
* Production : V9.0 sur `:8091`, **hors périmètre**. Empreintes de référence : `audit/prod-fp-avant.txt`.
* Démo : conteneur `tb-demo`, `127.0.0.1:8095`, image staging RC14, données fictives dans `/root/demo-time-billing/data` (mot de passe `/root/demo-time-billing/mot-de-passe.txt`, ne pas l'afficher). Outils de capture : `/root/demo-time-billing/outils/shots_rc14.js` (BASE, OUT, W, H, PFX), `shots_import.js`. Ne pas modifier les données de la démo : pour tester des écritures, utiliser une copie (`cp data/timebilling.db` vers un dossier jetable + conteneur `tb-nuit-*`).
* Documents : `RAPPORT-DESIGN-RC14.md`, `PLAN-INTEGRATION-DESIGN-RC14.md`, `RAPPORT-CONSOLIDE-RC13.md`.

## 2. Ce que RC14 contient déjà
`app/templates/_ds.html` (design system, chargé après `_style.html`), `_sidebar.html` (navigation latérale, boutons `data-tab` sur index, liens ailleurs), cartes financières + anneaux (index, panneau dashboard), histogramme des prévisions, badges de statut et recherche d'archive (`#archiveSearch`, `#archiveTable`), connexion vitrée. Pages : `index.html` (7 panneaux `data-panel`), `entries.html`, `entry_edit.html`, `_page.html` (pages de détail : émission, avoirs, mandat, brouillon, restauration), `import_review.html` (sans barre latérale), `login.html`.
Défauts connus restants : aperçu d'import sans barre latérale et pastilles de filtre en ancien bleu marine ; formulaire de création de mandat avant la liste ; page de facturation à moitié vide sur grand écran ; pas de graphique de consommation cumulée ; tableaux larges (mandats, archive) serrés en tablette.

## 3. Direction artistique (texte validé par l'utilisateur)
Interface premium Apple / Tesla, Liquid Glass. Fond blanc perle, gris titane, dégradés froids très subtils. Surfaces translucides frosted glass. Profondeur réelle : superposition, ombres diffuses, reflets légers, contours fins. Navigation latérale élégante et persistante. Cartes financières avec hiérarchie typographique forte. Bleu électrique pour actions principales, sélections, indicateurs. Graphiques fins, anneaux de progression, visualisations financières. Coins arrondis cohérents, espacements généreux. Transitions discrètes. Responsive desktop et tablette ; mobile fonctionnel sans reproduire la densité desktop.
À éviter : dashboard SaaS générique, aplats colorés excessifs, verre trop opaque ou trop prononcé, animations décoratives, changements de terminologie métier.

## 4. Pièges connus (à respecter)
* Flask met les gabarits en cache **par processus** (2 workers) : après une modification, **redémarrer** le conteneur de test avant de capturer.
* Montage du code pour itérer : `docker run ... -v $PWD/app:/app/app:ro ... time-billing-v9-staging-time-billing-v9-staging:latest` sur une base copiée.
* Les recettes lisent `innerText` : **pas de `text-transform:uppercase`** sur des libellés ; ne change aucun id, classe, `name`, `action`, libellé, ni le texte direct des boutons `data-tab` (un test lit `data-tab="x">Texte<`).
* Test de politique : `overflow-wrap:anywhere` interdit dans les feuilles de style. Un test refuse « V5 » dans la page de connexion (attention aux tracés SVG).
* CSP : `style-src 'self' 'unsafe-inline'`, `script-src` à nonce (`nonce="{{csp_nonce}}"` sur tout `<script>`), `img-src 'self' data:` → aucune police ni ressource externe.
* Captures pleine page avec viewport 900 px : le fond s'arrête à 900 px (artefact) ; `shots_rc14.js` ajuste la hauteur du viewport.
* Sous `set -o pipefail`, ne jamais faire `cmd | grep -q` (SIGPIPE) : capturer dans une variable.
* Le rollback consomme `.env.<tag>` : avant un redéploiement, `cp -p /opt/time-billing-v9-staging/.env /opt/time-billing-v9-staging/.env.rc14` (ne jamais afficher le fichier).

## 5. Commandes
* Tests unitaires : `MODS=$(ls tests/test_*.py | sed 's#tests/#tests.#;s#\.py$##' | tr '\n' ' '); IMG=time-billing-v9-rc10-test:latest journaux/run_unit.sh $MODS` (≈ 2 min, 344 tests au départ).
* Recette complète sur l'image déployée (≈ 8 min, au premier plan avec un délai de 600000 ms, jamais en arrière-plan) : `RUN=final14n PFX=tb-nuitf PB=8300 IMG_REF=time-billing-v9-staging-time-billing-v9-staging:latest journaux/recette_navigateur_final.sh > journaux/recette-nuit.out 2>&1` (référence : métier 107/107 + 15/15, saisies 34/34 + 7/7, responsive 33/33, RC12 22/22, RC14 56/56, e2e 30 + 18, concurrence 11/11). Tests navigateur dans `tests/browser/` (Playwright : `/root/node_modules/playwright`).
* Déployer le staging (après tests verts) : `cd procedure && cp -p /opt/time-billing-v9-staging/.env /opt/time-billing-v9-staging/.env.rc14 && ./10-preflight.sh staging.conf && ./20-backup.sh staging.conf && ./30-rehearse.sh staging.conf && ./40-deploy.sh staging.conf && ./50-verify.sh staging.conf`. Puis relancer la démo sur la nouvelle image (`docker rm -f tb-demo` puis même `docker run` que dans `RAPPORT-DESIGN-RC14.md` / mémoire, `--restart unless-stopped`, `ENV_LABEL=DÉMO`, mot de passe lu depuis le fichier).
* Rollback staging : `cd procedure && ./90-rollback.sh staging.conf`.
