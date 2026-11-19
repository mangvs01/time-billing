# Plan d'intégration de la direction artistique « Liquid Glass » — RC14

## 1. Audit (phase 1)
* **Dépôt** : `/root/time-billing-v9-rc10-20261004` (git local, branche `main` = RC13 ; travail sur la branche `design-liquid-glass-rc14`). **Staging** : `/opt/time-billing-v9-staging`, conteneur `time-billing-v9-staging`, `127.0.0.1:8092`, RC13 ; déploiement/retour arrière par `procedure/*.sh procedure/staging.conf`. Production V9.0 (`:8091`) hors périmètre.
* **Front actuel** : Flask + Jinja, sans framework JS ni fichier statique. 12 gabarits (≈ 97 Ko). CSS en ligne dans chaque page : `_style.html` (index, saisies, correction de saisie) et une feuille réduite dans `_page.html` (pages de détail). `index.html` (31 Ko) est une page unique à 7 panneaux (`data-panel`) pilotés par des boutons `data-tab` ; les autres pages sont des gabarits séparés.
* **Contraintes techniques** : CSP `style-src 'self' 'unsafe-inline'`, `script-src` à nonce, `img-src 'self' data:` → pas de police ni de CDN externe ; polices système (SF Pro sur Mac/iOS) ; icônes en CSS (masques SVG `data:`) ; aucun script décoratif.
* **Contraintes de non-régression** : tests unitaires et recettes navigateur s'appuient sur des identifiants, classes et textes (`#invoiceForm`, `#calculateBtn`, `button.wide`, `data-tab`, `a.btn`, `form.panel button`…, et un test qui lit `data-tab="x">Texte<`). **Aucun identifiant, classe, attribut `name`, `action` ni libellé n'est modifié ; on ajoute seulement.**
* **Écrans réutilisables** : tous. Les calculs (positions, prévisions, montants) sont déjà fournis aux gabarits (`positions`, `fc`, `invoices`, `cnotes`) : les nouveaux indicateurs n'en font que des sommes d'affichage.

## 2. Proposition
| Lot | Contenu | Risque |
|---|---|---|
| A. Design system | `_ds.html` : tokens (couleurs, transparences, rayons, ombres, typographie, mouvements), composants (surface vitrée, boutons, champs, tableaux, onglets, badges, alertes), états (actif, survol, focus, désactivé, erreur), responsive (bureau, tablette, mobile), `prefers-reduced-motion` / `prefers-reduced-transparency` | faible : CSS seul, repose sur les classes existantes |
| B. Coque d'application | `_sidebar.html` : navigation latérale persistante (mêmes libellés), marque, étiquette d'environnement, déconnexion ; reprise sur index, saisies, correction de saisie, pages de détail, connexion | moyen : balisage de la coque modifié sur 8 gabarits, sans toucher au contenu |
| C. Tableau de bord | cartes financières (facturé de l'année, prévision restante, réalisé non facturé, brouillons, avoirs à régler) et anneaux de progression par mandat, à partir des données déjà calculées ; tableau existant conservé | faible : lecture seule |
| D. Prévisions | histogramme fin mensuel (SVG généré par le gabarit) au-dessus des tableaux existants | faible |
| E. Tableaux et statuts | badges (brouillon, émise, créditée…) autour des textes existants ; recherche instantanée dans l'archive (filtre d'affichage côté navigateur, sans requête) | faible |
| F. Recette | tests unitaires complets, recette navigateur/HTTP complète, captures desktop/tablette/mobile, console et HTTP | — |

Hors périmètre : calculs, schéma, PDF (les PDF gardent leur mise en page de référence), terminologie, sécurité, production.

## 3. Déploiement et retour arrière
Version `9.2-rc14`. `procedure/10→50` sur le staging : sauvegarde base + image de retour automatiques (`pre-rc14-<horodatage>`), répétition de migration (aucune migration de schéma : le design ne touche pas la base). Retour arrière : `procedure/90-rollback.sh procedure/staging.conf` (restaure code et base d'avant, SHA-256 vérifié), ou `git checkout main` + redéploiement RC13.

## 4. Points à signaler
* **Le mockup approuvé n'est pas disponible dans cet environnement** (introuvable sur le serveur, dans le dépôt et dans la conversation) : l'intégration suit la direction écrite. La comparaison visuelle avec le mockup reste à faire sur pièce.
* Pas de mode sombre (non demandé).
