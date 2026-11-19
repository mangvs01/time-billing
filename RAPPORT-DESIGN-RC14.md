# Time Billing V9.2-rc14 — intégration de l'identité « Liquid Glass » (04.10.2026)

## 1. Périmètre et résultat
Refonte visuelle seulement : CSS et gabarits. Aucun calcul, schéma, PDF, libellé ou règle métier n'a changé. Branche locale `design-liquid-glass-rc14` (la branche `main` reste en RC13). Déployée sur le **staging** (`http://127.0.0.1:8092`, 9.2-rc14). Production non touchée, aucun import réel.

## 2. Ce qui a été fait
| Lot | Contenu |
|---|---|
| Design system | `app/templates/_ds.html` : tokens (blanc perle, gris titane, bleu électrique, transparences, rayons 14/24 px, ombres diffuses, reflet intérieur d'1 px), surfaces vitrées (`backdrop-filter`), boutons, champs, tableaux, badges, alertes, états actif / survol / focus / désactivé / invalide, mouvements < 200 ms. Polices système (SF Pro sur Apple) : la CSP interdit les polices externes. |
| Coque | `_sidebar.html` : navigation latérale persistante, mêmes libellés, icônes en masque CSS. Tablette < 1100 px : colonne d'icônes. Téléphone < 760 px : barre supérieure défilante. |
| Tableau de bord | 5 cartes financières (facturé de l'année, prévision restante, réalisé non facturé, brouillons, avoirs à régler) et un anneau par mandat actif. Chiffres tirés des données déjà calculées (`fc`, `positions`, `invoices`, `cnotes`). |
| Prévisions | histogramme mensuel (SVG généré par le gabarit) au-dessus des tableaux existants. |
| Archive | pastilles de statut ; recherche instantanée (filtre d'affichage dans le navigateur, sans requête). |
| Connexion | carte vitrée. |
| Accessibilité | `prefers-reduced-motion`, `prefers-reduced-transparency`, repli sans `backdrop-filter`, focus visible, anneaux avec `aria-label`. |

## 3. Fichiers modifiés (19)
`app/app.py` (version) · `app/templates/` : **`_ds.html`** (nouveau), **`_sidebar.html`** (nouveau), `_navbar.html`, `_page.html`, `index.html`, `entries.html`, `entry_edit.html`, `import_review.html`, `login.html` · `procedure/staging.conf`, `procedure/prod.conf` (étiquette d'image rc14) · `tests/test_rc14.py` (nouveau), `tests/browser/recette-rc14.js` (nouveau), `tests/test_rc10.py` (version), `tests/browser/recette-responsive.js`, `tests/browser/recette-metier.js` · `PLAN-INTEGRATION-DESIGN-RC14.md`, `NOTE-SESSIONS-PARALLELES.md`.

## 4. Tests
| Contrôle | Résultat |
|---|---|
| Unitaire/fonctionnel (21 modules) | **344/344** (`journaux/unit-rc14-complet.log`), dont 11 nouveaux |
| Recette navigateur + HTTP + concurrence sur l'image déployée | **0 échec** : métier 107/107 et 15/15, saisies 34/34 et 7/7, responsive 33/33, RC12 22/22, **RC14 56/56**, e2e 30+18, concurrence 11/11, console et HTTP sans erreur (`journaux/recette-final14.out`) |
| Migration | aucune (aucune table touchée) ; répétition de migration : GO |
| Retour arrière réel RC14 → RC13 puis redéploiement | OK, base identique au SHA-256 |

Une première livraison RC14 avait fait échouer trois contrôles de recette. Causes : mes en-têtes de tableau en capitales changeaient le texte lu par les recettes (corrigé : casse normale), une course de timing dans la recette de restauration (test corrigé), la barre d'onglets défilante du téléphone comptée « hors écran » (test adapté, bord en fondu). Cette version a été retirée par un retour arrière réel avant le redéploiement final.

## 5. Retour arrière
```
cd /root/time-billing-v9-rc10-20261004/procedure
./90-rollback.sh staging.conf      # restaure code et base d'avant (RC13), vérifie le SHA-256
```
Sauvegarde : `/root/backups/time-billing-v9-staging/pre-rc14-*`, image de retour `:pre-rc14-<horodatage>`. Côté dépôt : `git checkout main`.

## 6. Incomplet ou à décider
* **Mockup approuvé introuvable** : comparaison visuelle à faire dès réception du fichier.
* L'aperçu d'import garde sa mise en page pleine largeur, sans navigation latérale ; ses pastilles de filtre gardent l'ancien bleu marine.
* Pas de mode sombre (non demandé). Pas de graphique de consommation cumulée. Le formulaire de création de mandat reste avant la liste des mandats.
* Les PDF gardent leur mise en page de référence, volontairement.
* Le staging est vide : les captures viennent de la démo (`http://127.0.0.1:8095`, mêmes images RC14, données fictives).
* Flask met les gabarits en cache par processus : après un changement de gabarit, redémarrer le conteneur (le déploiement le fait).
