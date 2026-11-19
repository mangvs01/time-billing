# Time Billing 9.2-rc33 — UX lot 2 : propositions (lecture + maquettes, aucun déploiement)

Mission BILLING-LOT2-PROPOSITIONS (claude2), 23.10.2026. Décision du propriétaire du 23.10 : « lot 2 UX : propositions d'abord ».
Ce dossier ne modifie **aucun** fichier de `app/` ni de `tests/`. Rien n'est commité, poussé ou déployé.

## 1. Méthode

- **Relecture du lot 1** : commits `986e9f5` (lot 1 : cartes mobiles, synthèse des contrôles, aides en direct, mandat conservé, suite du brouillon, format suisse) et `1bd79f1` (badge « réalisé > commandé » sur une ligne, rc33), `tests/test_ux_lot1.py`, `tests/browser/recette-ux-lot1.js`, puis les gabarits (`app/templates/*.html`), `_ds.html` (design system « Liquid Glass ») et les routes de `app/app.py`. Le dépôt ne contient ni `PROGRESS.md` ni dossier `docs/` (créé pour ce dossier) : le lot 1 n'est documenté que par ses commits, ses commentaires « UX lot 1 (n° …) / B-… » dans le code et sa recette.
- **Instance jetable** : `gunicorn` (venv de test existant `/tmp/rc25-test-venv`, versions identiques à `requirements.lock`) sur `127.0.0.1:8190`, base SQLite **vide** créée dans le scratchpad de la session, secrets aléatoires jetables, `COOKIE_SECURE=0`, `ENV_LABEL=MAQUETTE`, `INVOICE_CHECK_WORDS=` (mécanisme prévu pour les instances de test : sans lui, le contrôle 10 refuse les données « fictives »). Ni Docker, ni `/data`, ni base staging, ni production (8091) touchés.
- **Données synthétiques** (Playwright, par les formulaires et routes de l'application) : émetteur fictif, 3 mandats (Alpha 900 CHF/j, 40 j commandés, TVA 8,1 % ; Beta 650 CHF/j, 12 j, **dépassé** ; Gamma 720 CHF/j **sans PO**, TVA 0), 84 saisies (juillet à septembre 2026), 2 factures émises (2026-08, 2026-08-2), 2 brouillons (Alpha 01.09 → 31.10.2026 ; Gamma août), 1 note de crédit émise (NC-2026-08, remboursement), 1 saisie facturée corrigée (écart post-facturation −5 h sur 2026-08).
- **Captures** : 15 écrans × 2 largeurs (bureau 1280 × 900, mobile 390 × 844), pleine page et premier écran, avec mesures automatiques (hauteur de page, débordement horizontal, cibles < 44 px, position du premier bouton principal). Une sélection est dans [`docs/ux-lot2-captures/`](ux-lot2-captures/) ; les mesures dans [`mesures.json`](ux-lot2-captures/mesures.json).

**Constats généraux** : aucune erreur console, aucun débordement horizontal (bureau comme mobile), cibles tactiles ≥ 44 px partout sur mobile (acquis du lot 1). Les problèmes restants portent sur la **hiérarchie** (ce qui est à faire n'est pas mis en avant), la **longueur** des pages critiques sur mobile et des **conséquences découvertes trop tard** (au moment d'émettre).

| Écran (mobile 390) | Hauteur de page | Premier bouton principal à |
|---|---|---|
| Tableau de bord | 6 879 px (≈ 8 écrans) | — (aucune action directe) |
| Saisie des heures | 5 629 px | 941 px (sous la ligne de flottaison : 844) |
| Émettre la facture | 4 595 px | 4 296 px (≈ 5 écrans de défilement) |
| Toutes les saisies | 16 626 px | — |
| Bureau 1280 : Émettre la facture | 2 458 px | 2 254 px |

## 2. Synthèse priorisée

Impact : effet sur le travail quotidien et sur le risque d'erreur de facturation. Effort : S ≈ ½ jour, M ≈ 1 à 2 jours (gabarit + CSS + tests de recette), L > 2 jours.

| # | Proposition | Impact | Effort | Risque données | Décision métier ? | Maquette |
|---|---|---|---|---|---|---|
| 1 | Tableau de bord « À traiter » : une liste d'actions au lieu de bandeaux rouges | Fort | S | Aucun | Non (option « contrôles en échec » : voir R-4) | [01-tableau-de-bord-a-traiter.html](maquettes-lot2/01-tableau-de-bord-a-traiter.html) |
| 2 | Émission en trois temps : anomalies, décisions et bouton regroupés en haut | Fort | M | Aucun (champs du formulaire inchangés) | Oui, partielle (R-3) | [02-emission-en-trois-temps.html](maquettes-lot2/02-emission-en-trois-temps.html) |
| 3 | Brouillon guidé : calcul automatique et pré-alertes avant création | Fort | M | Aucun si le serveur calcule | Oui (R-1, R-2, R-5) | [03-brouillon-guide.html](maquettes-lot2/03-brouillon-guide.html) |
| 4 | Saisie mobile : bouton d'enregistrement toujours visible, raccourcis de date | Fort | S | Aucun | Non | — |
| 5 | Navigation mobile : barre d'onglets en bas (5 destinations visibles) | Moyen-fort | S-M | Aucun | Non | — |
| 6 | Factures et brouillons : une action principale par ligne, brouillons séparés | Moyen-fort | M | Aucun | Non | — |
| 7 | Toutes les saisies : périodes rapides, totaux par jour et par semaine | Moyen | M | Aucun | Non | — |
| 8 | Nombres lisibles : 2 décimales à l'affichage, valeur exacte en infobulle | Moyen | S | Aucun (affichage seul) | Oui, à confirmer (R-6) | — |
| 9 | Mandats : création par sections, clôture sortie du tableau, tableau allégé | Moyen | M | Aucun | Non (déplacement d'un geste : R-7) | — |
| 10 | « Reprendre » une saisie (pré-remplir le formulaire depuis une saisie récente) | Moyen | S | Aucun (création par la route existante) | Non | — |
| 11 | Tableau de bord allégé : 5 dernières saisies, tableau de synthèse repliable | Moyen | S | Aucun | Non | — |

Ordre recommandé pour un lot 2 : **1 → 4 → 2 → 3 → 6**, puis 5, 8, 11, 7, 10, 9. Les n° 1, 4, 8, 11 sont de l'affichage pur et peuvent partir ensemble ; les n° 2 et 3 demandent d'abord les décisions R-1 à R-5 (section 4).

## 3. Propositions détaillées

### 1. Tableau de bord « À traiter » — Impact fort, effort S

**Problème observé** — [bureau](ux-lot2-captures/desktop-dashboard.png), [mobile, premier écran](ux-lot2-captures/mobile-dashboard-viewport.png)
- Deux bandeaux de **même style rouge** en tête : un écart post-facturation (décision à prendre) et un simple conseil de sauvegarde. Rien ne distingue l'urgent du conseil. Sur mobile, ils occupent tout le premier écran ; les chiffres commencent sous la ligne de flottaison.
- Le lien de l'écart mène à l'onglet « Factures et brouillons », pas à la page `/invoice/<id>/ecart` où la décision se prend (il faut retrouver la ligne puis « Détail et décision »).
- Les cartes « Brouillons en attente : 2 » et « Avoirs à régler : 1 » ne sont pas cliquables : l'utilisateur voit le travail à faire sans pouvoir y aller.
- Aucun rappel des brouillons en échec de contrôle ni des remboursements à échéance (NC-2026-08 : 351,33 CHF au 22.11.2026).

**Solution** — un bloc unique « À traiter (n) » en tête du tableau de bord : une ligne par action, chacune avec un libellé, son contexte chiffré et **un seul bouton** qui mène à la page où l'action se fait :
écart post-facturation → `/invoice/<id>/ecart` ; brouillon → `/issue/<id>` ; note de crédit à rembourser ou à imputer → `/credit/<id>` ; sauvegarde → `/backup`.
Trois niveaux visuels : **décision requise** (rouge), **à faire** (bleu), **conseil** (gris/ambre). Les cartes de chiffres deviennent des liens (« Brouillons » → archive filtrée sur les brouillons ; « Réalisé non facturé » → Édition des factures ; « Avoirs » → notes de crédit). Bloc vide : « Rien à traiter ».

**Fichiers** : `app/templates/index.html` (bloc `data-panel="dashboard"`), `app/templates/_ds.html` (styles `.todo`), éventuellement `app/app.py` (vue `/` : liste déjà disponible via `open_variances`, `invoices`, `cnotes` ; l'option « contrôles en échec par brouillon » demanderait `invoice_checks.run_checks` par brouillon). Recette : `tests/browser/recette-ux-lot1.js` (sélecteur `#variancesAlert` à conserver ou à migrer), `tests/test_ux_lot1.py`.
**Risque données** : aucun (lecture et liens vers des pages existantes ; aucune action exécutée depuis le tableau de bord).
**Maquette** : [01-tableau-de-bord-a-traiter.html](maquettes-lot2/01-tableau-de-bord-a-traiter.html).

### 2. Émission en trois temps — Impact fort, effort M

**Problème observé** — [bureau](ux-lot2-captures/desktop-issue-alpha.png), [mobile](ux-lot2-captures/mobile-issue-alpha-viewport.png)
- La page la plus engageante de l'application (émission définitive) se lit de haut en bas sur 2 458 px (bureau) / 4 595 px (mobile) : 14 contrôles, puis un tableau de 13 lignes de position, puis seulement les décisions (reliquat, antidatage, **dérogations**) et le bouton (à 4 296 px sur mobile).
- Les motifs de dérogation sont saisis **loin de l'anomalie** qu'ils justifient (le texte de l'anomalie est répété en petit au-dessus du champ).
- Sur mobile, chaque contrôle conforme prend une carte de 3 lignes (≈ 110 px) : 12 cartes conformes avant d'atteindre la suite.
- Les chiffres essentiels (numéro, date imprimée, total TTC, reliquat, solde PO après émission) sont dispersés dans le tableau de position.

**Solution**
1. **Récapitulatif fixe** en tête (colonne de droite collante sur bureau, bandeau compact sur mobile) : numéro attribué, date imprimée, période, quantité, total TTC, reliquat, solde PO après émission, état « 2 dérogations à motiver ».
2. **Étape 1 — Contrôles** : les 14 lignes restent visibles et **dans leur ordre** (décision du lot 1, n° 2) mais en lignes compactes ; une ligne en échec s'ouvre en place avec son champ de motif (`textarea` rattaché au formulaire par l'attribut `form="issueForm"`, mêmes `name="derogation_<n>"`). Lien « Corriger le brouillon » à côté de chaque anomalie.
3. **Étape 2 — Décisions** : reliquat (si non nul) et confirmation d'antidatage, regroupés.
4. **Étape 3 — Émettre** : bouton qui rappelle le montant (« Émettre la facture 2026-10 — 6 930,30 CHF »), « Aperçu PDF (brouillon) » à côté.
5. Le tableau détaillé de la position (13 lignes) passe dans un `<details>` « Position détaillée du mandat », fermé par défaut sauf en cas d'alerte (dépassement de PO, émission hors ordre, écarts).

**Fichiers** : `app/templates/issue_confirm.html`, `app/templates/_ds.html`. Aucune modification de `issue()` / `issue_context()` : les champs postés (`expected_reliquat`, `expected_invoice_date`, `from_confirm`, `reliquat_treatment`, `reliquat_note`, `confirm_backdate`, `derogation_<n>`) restent identiques. Identifiants à conserver pour la recette : `#issueChecks`, `#checkSummary`, `#chk<n>`, `#derogationNeeded`, `#draftPdfPreview`, `#noPoBalance`, `#issueVariances`.
**Risque données** : aucun sur les règles (14 contrôles, dérogations limitées à 12 et 13, motif de 10 caractères : inchangés). Risque d'implémentation : un champ de dérogation sorti du `<form>` sans attribut `form` ne serait pas envoyé → l'émission serait refusée (pas de fausse émission) ; à couvrir par un test.
**Décision** : R-3 (repli de la position détaillée ; compactage des contrôles sur mobile).
**Maquette** : [02-emission-en-trois-temps.html](maquettes-lot2/02-emission-en-trois-temps.html).

### 3. Brouillon guidé : calcul automatique et pré-alertes — Impact fort, effort M

**Problème observé** — [bureau après calcul](ux-lot2-captures/desktop-billing-calc.png), [mobile](ux-lot2-captures/mobile-billing-viewport.png), [émission qui en résulte](ux-lot2-captures/desktop-issue-alpha.png)
- **Cas réel de la recette** : brouillon Alpha 01.09 → 31.10.2026 créé avec la règle « Au plus proche, 0,25 j » → 7,00 j pour 6,96875 j réalisés. Le contrôle 12 (tolérance de sur-facturation **0 j** depuis la décision rc25 n° 6) n'apparaît qu'à la page d'émission : **ANOMALIE, dérogation obligatoire**. Rien ne l'annonçait à la création.
- Le calcul exige un clic sur « Calculer les jours facturables non arrondis » ; changer de période n'efface pas l'ancien résultat. Une période sans saisie affiche « 0 h / 0 jours » sans message.
- Un brouillon couvrant déjà la période n'est signalé **qu'après** la création (message flash « Attention : 1 autre(s) brouillon(s)… »).
- Aucune période proposée : il faut saisir deux dates à chaque facture, alors que l'application connaît la fin de la dernière facture émise du mandat.
- Les options rares (« AUTRES », date de facture, note) occupent la moitié du formulaire (bureau : bouton « Créer le brouillon » à 1 179 px).

**Solution**
1. **Étape 1 — Mandat et période** : raccourcis « Depuis la dernière facture », « Mois dernier », « Ce mois » qui remplissent les deux dates (modifiables). Calcul **automatique** (route `/suggest` existante, inchangée) dès que mandat et période sont complets ; message explicite si 0 h.
2. **Pré-alertes avant création** : brouillon existant sur la période (avec lien « Ouvrir ce brouillon ») ; période après la date de facture (contrôle 13, déjà fait au lot 1) ; **quantité supérieure au réalisé de la période** (contrôle 12) ; dépassement de PO.
3. **Étape 2 — Quantité** : la règle d'arrondi devient une rangée de choix qui **affiche la quantité et le montant obtenus** pour chaque règle (exact 6,96875 j · au plus proche 7,00 j ⚠ · à l'inférieur 6,75 j · au supérieur 7,00 j ⚠), la quantité reste modifiable à la main.
4. **Étape 3 — Options** (`<details>` fermé) : description, « AUTRES », date de facture, note.
5. Bouton : « Créer le brouillon — 6,75 j · 6 075,00 CHF HT ».

**Fichiers** : `app/templates/index.html` (panneau `data-panel="billing"` et script associé), `app/templates/_ds.html` ; pour les pré-alertes 12 et chevauchement, `app/app.py` (`/suggest` renvoie déjà `raw_days`, `billed_days_before`, `po_balance_days` ; il faudrait y ajouter, **en lecture seule**, le brouillon chevauchant et la fin de la dernière facture émise).
**Risque données** : aucun tant que les chiffres viennent du serveur. Le contrôle 12 ne doit **pas** être recopié en JavaScript (deux implémentations divergeraient) : R-1.
**Décisions** : R-1, R-2, R-5.
**Maquette** : [03-brouillon-guide.html](maquettes-lot2/03-brouillon-guide.html).

### 4. Saisie des heures sur mobile — Impact fort (usage quotidien), effort S

**Problème observé** — [mobile, premier écran](ux-lot2-captures/mobile-time-viewport.png)
- Le bouton « Enregistrer le temps » est à 941 px : **hors du premier écran** (844 px). Le choix « Début / fin » vs « Durée » occupe un cadre de 130 px ; l'aide « Présélectionné : … Le changer si besoin. » 3 lignes ; la case « Durée calculée » 90 px.
- La date se choisit dans le sélecteur natif, alors que l'immense majorité des saisies portent sur aujourd'hui ou hier.

**Solution** : contrôle segmenté « Début/fin | Durée » sur une ligne ; raccourcis « Aujourd'hui · Hier » sous la date ; durée calculée affichée **dans** le bouton (le lot 1 le fait déjà pour les cas de nuit : l'étendre à tous les cas, « Enregistrer 3 h 45 ») ; sur l'onglet Saisie en mobile, barre d'enregistrement **collée en bas** (le bouton flottant « Saisir » y est déjà masqué) ; aide de présélection raccourcie à « Mandat de la dernière saisie ».
**Fichiers** : `app/templates/index.html` (panneau `data-panel="time"`, script `submitLabel`), `app/templates/_ds.html`. Recette : `recette-ux-lot1.js` vérifie le libellé exact « Enregistrer 16 h (fin le lendemain) » : à adapter si l'on change la règle d'affichage.
**Risque données** : aucun (mêmes champs `entry_mode`, `start_time`, `end_time`, `manual_hours`, même route `/entry`).

### 5. Navigation mobile : barre d'onglets en bas — Impact moyen-fort, effort S-M

**Problème observé** — [mobile](ux-lot2-captures/mobile-mandates-viewport.png) : la barre supérieure fait défiler 7 onglets horizontalement ; seuls « Tableau de bord » et « Saisie des heures » sont visibles, « Édition des factures » et « Factures et brouillons » sont **hors écran** (masque en dégradé). L'en-tête (marque, pastille, déconnexion, onglets) occupe 128 px en permanence. Le bouton flottant « Saisir » recouvre le bas des contenus (cartes d'archive, boutons).
**Solution** : sur ≤ 760 px, barre basse fixe à 5 entrées (Tableau · Saisie · Mandats · Factures · Plus) ; « Plus » ouvre Édition des factures, Import, Paramètres, Déconnexion. L'entrée « Saisie » remplace le bouton flottant. En-tête réduit à la marque.
**Fichiers** : `app/templates/_sidebar.html`, `app/templates/_ds.html`. Recette : les tests B-6 (bouton flottant) et n° 12 (cibles 44 px) de `recette-ux-lot1.js` sont à réécrire.
**Risque données** : aucun. **À noter** : remplace une décision du lot 1 (B-6, bouton flottant) → à valider par le propriétaire.

### 6. Factures et brouillons : une action principale par ligne — Impact moyen-fort, effort M

**Problème observé** — [bureau](ux-lot2-captures/desktop-archive.png), [mobile](ux-lot2-captures/mobile-archive.png)
- Chaque brouillon porte **4 boutons empilés** de même poids (PDF, Modifier, Émettre…, Supprimer) : la ligne fait 175 px, la colonne « Projet » est réduite à 4 lignes. L'action attendue (« Émettre… ») ne ressort pas.
- Brouillons et factures émises sont mélangés dans un même tableau trié par numéro ; un brouillon affiche « Brouillon » dans la colonne Numéro et « à l'émission » dans la colonne Date.
- Sur mobile, chaque document est une carte de 10 lignes libellé/valeur (≈ 400 px).

**Solution** : section « Brouillons à émettre » au-dessus de « Documents émis » (les filtres existants restent) ; par ligne un **bouton principal** (« Contrôler et émettre » pour un brouillon, « PDF » pour une facture émise) et un menu « Plus » (`<details>`) pour Modifier, Supprimer, Note de crédit… ; sur mobile, en-tête de carte « Mandat · statut · TTC », le reste replié.
**Fichiers** : `app/templates/index.html` (panneau `data-panel="archive"`, script de recherche `#archiveSearch` à adapter aux deux sections), `app/templates/_ds.html`.
**Risque données** : aucun. « Supprimer » garde sa confirmation (`data-confirm`) et son style destructif.

### 7. Toutes les saisies : périodes rapides et totaux — Impact moyen, effort M

**Problème observé** — [bureau](ux-lot2-captures/desktop-entries-viewport.png), [mobile](ux-lot2-captures/mobile-entries-viewport.png) : 84 saisies → 3 960 px (bureau), **16 626 px** (mobile). Il faut remplir deux dates et cliquer « Filtrer » ; aucun total par jour ni par semaine (seul le total global du filtre). Chaque ligne a deux boutons (« Modifier », « Supprimer »).
**Solution** : puces « Cette semaine · Semaine dernière · Ce mois · Mois dernier » (remplissent `date_from`/`date_to`, paramètres GET existants) ; filtrage à la sélection (le bouton reste pour le clavier) ; regroupement par jour avec sous-total d'heures, total par semaine ; sur mobile, une ligne par saisie (heure, mandat, durée) et actions dans la page de modification.
**Fichiers** : `app/templates/entries.html`, `app/app.py` (vue `/entries` : regroupement à l'affichage seulement), `app/templates/_ds.html`.
**Risque données** : aucun (lecture). L'export CSV reste identique.

### 8. Nombres lisibles — Impact moyen, effort S

**Problème observé** : « Reliquat 0,03125 j — Reporté… » ([archive](ux-lot2-captures/desktop-archive.png)) ; « 10,0000 j », « 9,3750 j », « 0,0000 j », « −0,6250 j » sur la page d'écart ([bureau](ux-lot2-captures/desktop-ecart.png)) ; « 6,9688 j » dans le contrôle 12 ([émission](ux-lot2-captures/desktop-issue-alpha.png)) ; « 0,7188 » dans la colonne « Jours équiv. » de la liste des saisies. Les zéros de fin et les 4 à 5 décimales rendent la lecture lente, alors que les montants sont à 2 décimales.
**Solution** : afficher 2 décimales pour les jours (« 0,03 j », « 10,00 j ») avec la **valeur exacte en infobulle** (classe `.exact` introduite au lot 1, décision B-2) ; garder la valeur exacte là où elle fonde une décision (contrôles avant émission, motif de dérogation, note de crédit pré-remplie).
**Fichiers** : `app/app.py` (filtres `nb`, `nbg`, `nbt`), gabarits concernés.
**Risque données** : aucun sur les données stockées ni sur les PDF (non touchés). **Décision R-6** : quelles pages gardent la valeur exacte visible.

### 9. Mandats : création par sections, clôture hors du tableau — Impact moyen, effort M

**Problème observé** — [bureau](ux-lot2-captures/desktop-mandates.png)
- « Détail des mandats » : 12 colonnes à 1280 px ; noms de mandats coupés sur 4 lignes ; chaque ligne contient un **champ « Motif de clôture » et un bouton « Clôturer »** en permanence, à côté de « Modifier » : geste rare et engageant placé au même niveau que les gestes courants.
- « Créer un mandat » : 17 champs à plat sur 3 colonnes ; seul « Nom du projet » est marqué obligatoire, alors que l'adresse de facturation et l'identifiant juridique sont exigés **avant l'émission** (indiqué seulement en aide).
- La valeur commandée de Gamma (sans PO) s'affiche « 0,00 CHF ».

**Solution** : formulaire en 4 sections (Identification · Conditions contractuelles · Facturation · Identité juridique) avec un repère « requis avant émission » ; tableau réduit à 6 colonnes (mandat, période, commandé, facturé net, solde, réalisé non facturé) et détail repliable ; « Clôturer » déplacé dans la page « Modifier le mandat » (même route `POST /project/<id>/close`, même confirmation) ; « sans PO » au lieu de 0,00 CHF.
**Fichiers** : `app/templates/index.html` (panneaux `p-create`, `p-detail`), `app/templates/project_edit.html`, `app/templates/_ds.html`.
**Risque données** : aucun (mêmes champs et routes). **R-7** : déplacement du geste de clôture.

### 10. « Reprendre » une saisie — Impact moyen, effort S

**Problème observé** — [bureau](ux-lot2-captures/desktop-time.png) : les saisies se répètent (même mandat, mêmes horaires 08:30–12:15, même type de description) ; la liste « Dernières saisies » n'offre que « Modifier ».
**Solution** : bouton « Reprendre » sur chaque saisie récente : remplit le formulaire (mandat, mode, horaires ou durée, description) avec la **date du jour** ; rien n'est enregistré sans clic sur « Enregistrer ».
**Fichiers** : `app/templates/index.html` (tableau « Dernières saisies » + script), `app/templates/_ds.html`.
**Risque données** : aucun (pré-remplissage côté navigateur, création par la route `/entry` existante, contrôles serveur inchangés). Risque d'usage : doublon involontaire → le bouton n'enregistre jamais directement.

### 11. Tableau de bord allégé — Impact moyen, effort S

**Problème observé** — [bureau](ux-lot2-captures/desktop-dashboard.png) : le tableau de bord répète deux blocs présents ailleurs : « Dernières saisies » (15 lignes, identique à l'onglet Saisie) et « Situation synthétique des mandats » (9 colonnes, recoupe « Détail des mandats »). Mobile : 6 879 px.
**Solution** : 5 dernières saisies + lien « Toutes les saisies » ; tableau de synthèse dans un `<details>` « Situation chiffrée des mandats » (ouvert sur bureau, fermé sur mobile) ; les anneaux d'avancement restent la vue principale. Carte « Sans bon de commande » (Gamma) : barre de réalisé simple au lieu d'une carte presque vide.
**Fichiers** : `app/templates/index.html`, `app/templates/_ds.html` (et `app/app.py` si la limite de `recent` change pour le seul tableau de bord).
**Risque données** : aucun.

## 4. Points touchant des règles métier — à valider séparément

Aucune proposition ne modifie un calcul, un contrôle, l'émission, la TVA, l'arrondi stocké ou la numérotation. Les points suivants **exposent** une règle plus tôt ou changent un comportement par défaut ; ils demandent l'accord du propriétaire avant toute réalisation.

| Réf. | Proposition | Question au propriétaire | Recommandation |
|---|---|---|---|
| R-1 | 3 | Afficher, **avant** la création du brouillon, le résultat prévisible du contrôle 12 (quantité vs réalisé de la période, tolérances 0 j au-dessus / 0,5 j en dessous). | Oui, mais calculé par le serveur (fonction partagée avec `invoice_checks`, en lecture seule), jamais recopié en JavaScript. |
| R-2 | 3 | L'arrondi « au plus proche » ou « au supérieur » produit régulièrement une sur-facturation de quelques centièmes de jour, refusée sans dérogation par le contrôle 12. Faut-il seulement l'**afficher** (proposition), ou changer la **règle d'arrondi par défaut** (aujourd'hui « Sans arrondi ») ? | Afficher seulement. Changer le défaut est une règle de facturation. |
| R-3 | 2 | Le lot 1 (n° 2) a fixé « les 14 lignes restent visibles, dans leur ordre ». La maquette garde les 14 lignes en ordre mais **compactées** ; elle replie le tableau de position détaillée (13 lignes) dans un `<details>`. | Accepter le compactage ; ouvrir automatiquement la position détaillée dès qu'une alerte la concerne. |
| R-4 | 1 | Afficher sur le tableau de bord le nombre de contrôles en échec de chaque brouillon (exécution des 14 contrôles à chaque affichage du tableau de bord). | Oui si le nombre de brouillons reste faible ; sinon afficher seulement « à contrôler ». |
| R-5 | 3 | Proposer une période par défaut (« depuis la dernière facture émise du mandat »). La période reste saisie et validée par l'utilisateur. | Oui, en simple raccourci (aucune date pré-remplie sans clic). |
| R-6 | 8 | Liste des pages où les jours restent affichés en valeur exacte. | Exacte : contrôles avant émission, dérogations, écart, note de crédit. Arrondie à 2 décimales ailleurs, exacte en infobulle. |
| R-7 | 9 | Retirer « Clôturer » du tableau des mandats pour le placer dans la page du mandat. | Oui (geste rare, déjà confirmé par une boîte de dialogue). |
| — | 5 | Remplacer le bouton flottant « Saisir » (décision B-6 du lot 1) par une barre d'onglets basse. | À trancher avec la n° 4 : les deux ensemble, ou garder B-6. |

## 5. Ce qui a été vérifié et ce qui ne l'a pas été

- Vérifié sur l'instance jetable : tous les écrans listés s'affichent sans erreur console ni débordement horizontal, à 1280 et 390 px.
- Les maquettes sont des fichiers HTML **statiques** (aucun script, aucune requête, aucun lien actif, données fictives) ; elles reprennent les jetons de couleur, rayons et typographie de `_ds.html`. Contrôlées à 1280 et 390 px dans Chromium.
- Non vérifié : Safari / iOS réels, lecteurs d'écran, impression. Les dates des champs natifs apparaissent au format `mm/dd/yyyy` sur les captures : c'est la langue du Chromium de test, pas l'application (un navigateur réglé en fr-CH affiche `jj.mm.aaaa`).
- Aucun test unitaire ni de recette n'a été lancé : aucun fichier de `app/` ou `tests/` n'a changé.
