# Édition des brouillons de facture — audit (phases 1-2) et plan d'implémentation

Mission BILLING-FACTURES-AUDIT-ET-PLAN (claude0), 26.10.2026. **Lecture seule** : aucun fichier suivi modifié, rien commité, construit, déployé ni exécuté en production. Ce document est le seul fichier créé dans le dépôt. Aucun secret lu ni affiché, aucune lecture de la base de production (analyse du code et des tests uniquement).

## 0. Périmètre, limites et réserves

- Code audité : `app/` du dossier `.claude/worktrees/billing-factures`, `VERSION = "9.2-rc36"`.
- **Réserve 1 — ce dossier n'est pas un worktree git enregistré** : il n'a pas de `.git` propre ; git remonte vers le dépôt parent, branche `campaign/billing-ux-lot2`, HEAD `7934b04` (et non `campaign/billing-factures` / `7f8182c`). Le contenu est bien du rc36 (`VERSION`, `docs/PAQUET-RC36.md`), mais je n'ai pas comparé octet par octet avec `7f8182c`. À régler avant la phase 3 (commits impossibles de toute façon pour moi).
- **Réserve 2 — aucune reproduction exécutée** : l'écriture d'un script scratchpad sous `.claude/` a été refusée par le système ; je ne l'ai pas contournée. La cause du bug est établie par lecture du code et par les tests existants qui figent le comportement (§2). Les tests existants n'ont pas été lancés : ils demandent le conteneur de test et une copie de la base de recette (`BASE_DB`, `/data`), ce qui suppose Docker (interdit pour cette mission).
- **Réserve 3 — base de production non lue** : les contraintes réellement présentes en production (ex. `UNIQUE` sur `invoices.number`) sont déduites du `CREATE TABLE IF NOT EXISTS` de `init()`. À vérifier sur une **copie de sauvegarde** avec `schema_checks` / `procedure/30-rehearse.sh` avant toute migration.

---

## (a) Cartographie technique

### Architecture
Application Flask monolithique ; un seul fichier de routes `app/app.py` (2014 lignes, style compact), SQLite, rendu PDF ReportLab, gabarits Jinja dans `app/templates/`. Un seul émetteur (table `settings`, clé/valeur) ; pas de table `clients` ; pas d'entité juridique émettrice multiple.

### Frontend (templates / JS)
| Fichier | Rôle |
|---|---|
| `templates/index.html` | Onglets. Formulaire de **création** du brouillon (période, `/suggest`, quantité, arrondi) + bloc repliable « 3. Options de la facture » (`description`, `other_amount`, `other_label`, `other_vat_mode`, `invoice_date`, `note`). JS en ligne (CSP nonce) : `calculate()`, `updateAmount()` (montant HT = qté × tarif du mandat, **sans** « autres »). Liste des brouillons/factures (onglet archive) : montants via `rules.invoice_amounts`. |
| `templates/invoice_edit.html` | **Éditeur du brouillon** (`GET/POST /invoice/<id>/edit`). Formulaire HTML pur, **aucun JS**, aucun total affiché ni recalculé. Champs : période, `qty`, `unit`, arrondi, `vat`, `description`, `other_amount`, `other_label`, `other_vat_mode`, `invoice_date`, `note`. Le **tarif unitaire n'est pas un champ**. |
| `templates/issue_confirm.html` | Contrôles avant émission (les 14 contrôles, reliquat, dérogations), affiche `ctx["number"]`. |
| `templates/project_edit.html` | Adresse de facturation du mandat : `billing_contact` (input) + `billing_address` (textarea libre). |
| `templates/credit_new.html` | Avoir : reprend `other_amount` de la facture d'origine. |
| `_confirm.html`, `kept_forms` | Mécanisme « un formulaire refusé garde ce qui a été saisi » (une case par session, 2 min). À réutiliser pour l'éditeur. |

### Backend (routes et services)
| Élément | Fichier:ligne | Rôle |
|---|---|---|
| `init()` + `ensure_column` | `app.py:32`, `:107` | Migration **additive et idempotente** à chaque démarrage (`CREATE … IF NOT EXISTS`, `ALTER TABLE ADD COLUMN`). Pas de table de versions de schéma. |
| `migrate_rc19` | `app.py:63` | Seule reconstruction de table existante (annexe), sous `BEGIN IMMEDIATE`. Modèle de prudence à imiter si une reconstruction devenait nécessaire. |
| `suggest` | `app.py:1167` | Calcul serveur de la quantité proposée, aperçu des contrôles 12/PO (« jamais dans le navigateur »). |
| `draft_values` + `_checked_*` | `app.py:1225`, `:1203-1224` | Validation d'un brouillon (unité, quantité, période, chevauchement, TVA « autres », date, note ≤ 1 ligne, description ≤ 3 lignes, libellé « autres » qui tient sur la ligne des totaux). |
| `invoice` (création) | `app.py:1253` | `INSERT` du brouillon ; `number` reste **NULL**. L'identifiant est calculé à la main (`MAX(...)+1` sur plusieurs tables). |
| `invoice_edit` | `app.py:1274` | `UPDATE invoices SET … WHERE id=? AND status='draft'`. Tarif conservé du brouillon (ou repris du mandat si l'unité change). |
| `invoice_delete` | `app.py:1302` | Suppression d'un brouillon (libère les imputations d'avoir), tracée dans `audit`. |
| `issue_context` / `issue` | `app.py:1318`, `:1343` | Émission : `BEGIN IMMEDIATE`, 14 contrôles, reliquat, **attribution du numéro**, `UPDATE status='issued'`, `invoice_service.freeze` (PDF + en-tête + annexe figés), audit. |
| `pdf` | `app.py:1391` | Brouillon : rendu à la volée ; émise : octets figés (jamais regénérés). |
| `archive_zip` | `app.py:1641` | Export ZIP (PDF figés + index CSV : numéro, HT, TVA, autres, TTC). |
| `invoice_service.live_data` | `invoice_service.py:17` | Assemble l'en-tête depuis `invoices JOIN projects` (adresse lue **en direct** sur le mandat), annexe cumulative, position contractuelle. |
| `invoice_service.freeze` | `invoice_service.py:89` | Écrit `invoice_snapshots` (en-tête JSON, annexe JSON, PDF, SHA-256) + `invoice_annex_entries`. |
| `invoice_checks` | `invoice_checks.py` | 14 contrôles d'émission. N° 3 (« montant = quantité × tarif »), 4 (TVA), 10 (mots interdits dans les champs imprimés, `printed_fields`), 11 (gabarit : empreinte + descriptions/notes/libellés qui tiennent), 12-14 (récit, période, quantité nette ≤ réalisée). |
| `credit_service`, `post_billing`, `forecast`, `gsheet_export`, `historical_*`, `restore_service`, `schema_checks` | — | Consommateurs de `invoices` (voir « impacts » §3). |

### Modèle de données SQLite (tables concernées)
- `invoices(id, number TEXT UNIQUE, project_id FK, period_from, period_to, qty, unit, unit_rate, vat, status, issued_at, note, rounding, rounding_step, created_at` + colonnes ajoutées : `description, other_amount, other_label, invoice_date, reliquat_days, reliquat_treatment, reliquat_note, other_vat_mode)`. **Une seule ligne de prestation par facture** (colonnes `qty/unit/unit_rate/description`) + **une seule ligne « AUTRES »** (`other_amount/other_label/other_vat_mode`). Aucune table de lignes.
- `projects` (= mandat) : `client` (nom court), `client_legal_name`, `client_legal_id`, `billing_contact`, `billing_address` (texte libre multi-lignes), `project_number`, `po`, `rate`, `vat`, … Pas de table `clients` ni `addresses`.
- `invoice_snapshots(invoice_id PK, number NOT NULL, header_json, annex_json, pdf, pdf_sha256)` — immuable (triggers). `invoice_annex_entries` — immuable.
- `invoice_date_changes` — historique append-only des dates de brouillon (modèle pour tracer les changements de numéro).
- `credit_notes(reference UNIQUE, invoice_id FK, …)` ; référence dérivée `NC-<n° facture>[.N]`. `credit_operations` (remboursements/imputations) rattachées par `invoice_id`/`target_invoice_id` (**identifiants, pas le texte du numéro**). Il n'existe **aucune table de paiements**.
- `historical_invoices(invoice_ref, …)` : factures émises hors application (numéros à ne jamais réattribuer).
- `audit` : append-only (triggers).
- Triggers déjà présents sur `invoices` : `issued_invoice_no_update` / `no_delete` (**toute modification d'une facture émise est refusée par la base**), `invoice_issued_at_only_at_issue`, `invoice_issue_needs_issued_at`.

### Migrations
Additives, rejouées à chaque démarrage par `init()` ; documentées dans `MIGRATIONS-RC11.md` (principe, répétition `procedure/30-rehearse.sh`, retour arrière `procedure/90-rollback.sh`, sauvegarde `procedure/20-backup.sh`, vérification `procedure/50-verify.sh` + `schema_checks.rc19_problems`). Toute nouvelle table doit être ajoutée à `restore_service.ORDER` (sinon sauvegarde JSON/restauration incomplètes) et, si elle porte des déclencheurs, aux `PROBES` de `schema_checks.py`.

### Calculs (`billing_rules.py`)
- `amounts(qty, unit_rate, vat, other, other_vat)` : `ht = qty × unit_rate` arrondi au centime (`ROUND_HALF_UP`, `Decimal`), `tva = (ht [+ other si « soumis »]) × vat / 100`, `ttc = ht + tva + other`. `invoice_amounts(i)` l'applique à une ligne de `invoices`.
- `next_invoice_number(c, period_to)` : numérotation (§4). `next_credit_number`. `contract()` : position en jours (somme des `qty` convertis en jours). `external_invoice_numbers()`.

### Template PDF (`pdf_layout.py`)
`render_invoice` → `_first_page` : page 1 A4 portrait **à géométrie fixe** validée contre une facture de référence (`golden_layout.json`, empreinte SHA-256 de toutes les constantes de géométrie ; contrôle 11 bloque l'émission si l'empreinte change). Tableau de lignes : une rangée (`table["lines"]` contient un seul élément), description ≤ 3 lignes + ligne « Période ». Totaux : SOUS-TOTAL, TAUX TVA, TVA, **« AUTRES — libellé (mode TVA) »**, TOTAL. Bloc facturation : `billing_contact` + `billing_address` (+ identité légale dédupliquée, `legal_identity_lines`). Suivent annexes feuilles de temps et page récapitulative. Le numéro est imprimé seulement si `issued` (« (attribué à l'émission) » sinon).

### Tests existants (55 fichiers `tests/test_*.py`, synthétiques)
Utiles ici : `test_v92.py` (édition/suppression de brouillon l.267, adresse figée après émission l.94-100, classe `Numbering` l.102+, PDF de référence), `test_g4_fidelite.py` (l.325 : « AUTRES » vide / libellé non imprimé à 0 ; l.357 libellé trop long), `test_g4.py` (contrôles 10/11), `test_rc3.py`, `test_rc4.py` (« autres », TVA soumis/hors TVA), `test_rc10_numbers.py`, `test_functional.py` (cycle complet + `pdf_text`), `test_ux_lot2.py` (liste des brouillons, lien « Corriger le brouillon », champs du formulaire l.189), `tests/concurrency_http.py` (rafales concurrentes contre gunicorn : doublons de numéros, double émission), `tests/browser/*.js` (recettes Playwright — toujours `--workers=1`). Commande de lancement : voir l'en-tête de `tests/test_import.py` (conteneur sans réseau, copie de la base de recette).

---

## (b) Lignes manuelles — état réel, reproduction, cause

### Ce que le modèle permet aujourd'hui
Une facture = **1 ligne de prestation** (quantité et unité issues des heures via `/suggest`, tarif repris du mandat) + **1 ligne « AUTRES »** (montant + libellé + régime TVA). **Il n'existe pas de « lignes manuelles » multiples** : ni table, ni route, ni champ. La demande (1) est donc une **fonctionnalité nouvelle**, pas seulement un bug.

### Le bug « une ligne saisie dans l'éditeur ne s'affiche pas correctement dans la facture »
Je n'ai pas pu exécuter de reproduction (réserve 2). Par lecture du code, **trois défauts d'affichage** existent sur la seule ligne manuelle disponible (« AUTRES »), dont le premier est **confirmé par un test existant** qui l'a figé comme comportement voulu (`test_g4_fidelite.py::test_E3_an_empty_others_line_prints_AUTRES_alone`) :

| # | Constat | Cause (fichier:ligne) | Statut |
|---|---|---|---|
| B1 | Un **libellé « AUTRES » saisi avec un montant 0** est enregistré en base mais **n'est jamais imprimé** (la facture affiche « AUTRES » seul). L'éditeur n'avertit pas ; seul le contrôle 10 le signale, et seulement si le libellé contient un mot interdit. | `pdf_layout.other_label:361` (`if amount == 0: return prefix`), décision G4 §6 ; `invoice_checks.printed_fields:56` | **Confirmé** (code + test) |
| B2 | Un montant « AUTRES » ne s'imprime **pas comme une ligne du tableau** mais comme **une rangée des totaux** (« AUTRES — libellé (hors TVA) », 8 pt, sur une ligne, libellé refusé s'il déborde). Il n'entre **ni dans le SOUS-TOTAL**, ni dans la colonne MONTANT du tableau ; en régime « hors TVA » il s'ajoute après la TVA. | `pdf_layout.render_invoice:569-573`, `amounts():146` | **Confirmé** (code) |
| B3 | Une **description vidée** est remplacée **silencieusement** par le nom du mandat, à la création et à l'édition. | `app.py:1259`, `:1287` | **Confirmé** (code) |
| B4 | L'éditeur n'a **aucun total** (pas de JS, pas d'aperçu) et **pas de champ tarif** : un changement d'unité re-dérive le tarif du mandat (message flash seulement). | `invoice_edit.html`, `app.py:1283-1296` | **Confirmé** (code) |

**Hypothèse la plus probable pour le symptôme rapporté : B1 + B2** (la ligne saisie n'apparaît pas, ou pas là où l'utilisateur l'attend). Je n'ai **pas** d'exemple réel de brouillon : à confirmer avec le propriétaire (§(f) Q0) ; la reproduction sera écrite comme **test rouge d'abord** en phase 3.

Autre point vérifié et **sain** : les brouillons repassent bien par `draft_values` (mêmes validations qu'à la création), les montants utilisent `Decimal` avec arrondi au centime, la suppression/édition ne duplique pas de ligne (une seule ligne par construction).

---

## (c) Numérotation actuelle

### Règle
- **Format** : `AAAA-MM` = **mois de fin de la période facturée** (`period_to[:7]`), pas la date d'émission. Les factures suivantes du même mois : `AAAA-MM-2`, `-3`, … (`max(suffixes)+1`). Pas de préfixe, pas de compteur annuel, pas de remise à zéro. Exemple : `2026-09`, `2026-09-2`.
- **Moment d'attribution** : **à l'émission uniquement**. Brouillon : `number = NULL` (le PDF brouillon imprime « (attribué à l'émission) »). Le numéro est calculé dans `issue_context` (`billing_rules.next_invoice_number`) puis écrit dans le même `UPDATE` qui passe le statut à `issued`, sous `BEGIN IMMEDIATE` (écrivain unique SQLite) avec le gel du PDF.
- **Numéros « pris »** : `invoices.number` + `EXTERNAL_INVOICE_NUMBERS` (variable d'environnement, `2026-09` par défaut dans les `docker-compose.prod/staging.yml` : facture réelle CIRSE hors application) + `historical_invoices.invoice_ref` (tout statut).
- **Avoirs** : `NC-<n° facture>` puis `NC-<n°>.2`, `.3` ; la conception **suppose qu'un numéro de facture ne contient jamais « . »** (`next_credit_number`).
- **Sort des brouillons** : un brouillon abandonné ou supprimé ne consomme **aucun** numéro (il n'en a pas) ; aucune réservation, donc aucun trou. Suppression : `invoice_delete` (brouillon seulement), tracée.
- **Contraintes d'unicité en base** : `invoices.number TEXT UNIQUE` (binaire, sensible à la casse, plusieurs NULL admis = brouillons) ; `credit_notes.reference UNIQUE` ; `credit_note_cancellations.reference UNIQUE`. **Rien** n'empêche en base : un numéro de facture identique à une `historical_invoices.invoice_ref` ou à un numéro externe (contrôle applicatif seulement) ; un doublon à la casse près. `invoice_snapshots.number` n'a pas d'unicité (copie figée).
- **Immutabilité** : une facture émise ne peut plus être modifiée (trigger) ; son numéro est répété dans `invoice_snapshots`, `invoice_annex_entries`/`annex_json`, la référence des avoirs `NC-…`, les noms de fichiers du ZIP, l'`audit`. Il n'existe **aucune procédure de renumérotation**.

### Robustesse
- **Suffisante pour la règle actuelle** : écrivain unique + `BEGIN IMMEDIATE` + `UNIQUE` en filet ; `tests/concurrency_http.py` vérifie l'absence de doublon sous rafale. Une collision se terminerait par un `IntegrityError` → rollback → message « Émission refusée : UNIQUE constraint failed… » (peu lisible mais sûr).
- **Faiblesses à connaître** (pertinentes pour la demande 3) :
  1. Le numéro affiché sur l'écran d'émission (`GET /issue`) est **recalculé hors transaction** et le formulaire **ne renvoie pas le numéro attendu** (alors que `expected_reliquat` et `expected_invoice_date` existent) : le numéro affiché peut différer du numéro réellement attribué.
  2. Le numéro suit la période, pas la chronologie d'émission : une facture de septembre émise en novembre prend `2026-09-N`, après d'éventuelles `2026-10`. Séquence **non chronologique** (voir décision D5).
  3. Pas de réservation par les brouillons : deux brouillons du même mois « partagent » le même numéro futur ; l'ordre d'émission décide.
  4. `next_invoice_number` utilise `LIKE 'base-%'` : un numéro saisi à la main contenant `_` ou `%` serait traité comme joker ; contenant `.` il casserait l'invariant des références d'avoirs.
  5. L'unicité n'est pas insensible à la casse ni aux espaces.
- **Conclusion** : la règle automatique est **assez robuste telle quelle**. Elle ne l'est **pas** pour des numéros saisis à la main : il faut un cadre de format, une unicité normalisée, une réservation par les brouillons et une gestion explicite des conflits (§(e) P3). **Je ne propose aucune nouvelle convention** : le format `AAAA-MM[-N]` reste la valeur proposée par défaut ; la saisie manuelle l'accepte et l'étend dans des limites strictes.

---

## (d) Cartographie des adresses

- **Modèle actuel : une seule adresse de facturation par mandat**, en texte libre : `projects.billing_contact` + `projects.billing_address` (+ `client`, `client_legal_name`, `client_legal_id`). **Aucune notion de client multi-adresses**, de « livraison », d'entité ou de pays ; « client » n'est qu'un texte sur chaque mandat (l'identité juridique `client_legal_id` sert de clé de regroupement : `rules.legal_key`).
- **Lecture** : `invoice_service.live_data` fait un `JOIN projects` à **chaque** rendu → un **brouillon** suit en direct toute modification du mandat ; `pdf_layout._first_page:295-297` imprime `billing_contact`/`billing_address` (+ `legal_identity_lines`) ; `block_fits` (émission) refuse une adresse trop longue ; `rules.missing_for_issue` exige une `billing_address` non vide ; `invoice_checks.printed_fields` fait contrôler l'adresse (contrôle 10).
- **Copie** : **à l'émission seulement** — `freeze()` fige l'en-tête (adresse incluse) dans `invoice_snapshots.header_json` ; le PDF émis n'est jamais regénéré ; les avoirs relisent l'en-tête figé (`credit_data` → `frozen_header`). Vérifié par `test_v92.py:94-100` (adresse du mandat modifiée après émission : PDF inchangé). **`invoices` ne porte aucune colonne d'adresse.**
- **Conséquence** : changer l'adresse « Dubaï » ↔ « autre pays » aujourd'hui = **modifier la fiche du mandat** (ou dupliquer le mandat, avec un nom unique), ce qui modifie aussi les autres brouillons du mandat. Pas de choix par facture.
- Adresse émetteur (`settings.issuer_address`) : distincte, hors périmètre ; **ne pas la confondre** avec l'adresse de facturation.

---

## (e) Plan d'implémentation (phases 3+ — après validation du propriétaire)

Principes communs : migrations **additives** dans `init()` (`ensure_column`, `CREATE TABLE/INDEX/TRIGGER IF NOT EXISTS`) ; **sauvegarde avant** (`procedure/20-backup.sh`, répétition `30-rehearse.sh` sur copie, vérification `50-verify.sh`) ; **aucun** `UPDATE` des factures émises (de toute façon refusé par trigger) ; nouvelles tables ajoutées à `restore_service.ORDER` et leurs triggers aux `PROBES` ; calculs **côté serveur** (comme `/suggest`) ; tests d'abord (rouge → vert) ; une branche par problème pour pouvoir livrer séparément.

### P1 — Lignes manuelles multiples

**Cause** : modèle à une ligne + « AUTRES » (§(b)).

**Solution** (mécanisme existant conservé) : la ligne de prestation (heures → `/suggest`) et « AUTRES » restent **telles quelles** (compatibilité avoirs, contrôles 3/4, `contract()`). On **ajoute** les lignes manuelles :
- Table `invoice_lines(id PK, invoice_id FK→invoices ON DELETE CASCADE? non : suppression applicative, position INTEGER, kind TEXT CHECK(kind='manual'), description TEXT NOT NULL, qty REAL NOT NULL CHECK(qty>0), unit TEXT NOT NULL, unit_rate REAL NOT NULL CHECK(unit_rate>=0), vat_mode (même vocabulaire que `other_vat_mode`, décision D2), client_uid TEXT, created_at, UNIQUE(invoice_id, position), UNIQUE(invoice_id, client_uid))`.
- Triggers : `BEFORE INSERT/UPDATE/DELETE` refusés si la facture est `issued` (modèle `invoice_annex_*`) ; l'émission **fige** les lignes dans `header_json` (clé `lines`) et le PDF : une facture émise ne relit jamais `invoice_lines`.
- `rules.amounts` étendu (nouveau paramètre `lines`) : montant de ligne = `qty × unit_rate` arrondi au centime `HALF_UP` (comme aujourd'hui), sous-total = ligne prestation + lignes manuelles, base TVA selon le régime de chaque ligne, un seul arrondi de TVA sur la base (règle actuelle), total. **Les clés actuelles (`ht`, `tva`, `other`, `ttc`) gardent leur sens** pour que contrôle 3 (qté × tarif de la ligne prestation), avoirs (`credit_service`), ZIP et `forecast` restent corrects ; ajout de `lines_ht`.
- Éditeur : lignes rendues par le serveur dans `invoice_edit.html` (même formulaire POST) ; bouton explicite **« Ajouter une ligne »** (soumission serveur = fonctionne sans JS ; JS en ligne avec nonce pour cloner la ligne sans recharger) ; chaque ligne a description, quantité, unité, prix unitaire, régime TVA, bouton **« Supprimer »** ; **badge** « Prestations / heures » (ligne issue de `/suggest`, quantité non librement éditable ici) vs « Manuelle » (badge + fond distinct) ; aperçu des totaux calculé **serveur** via un endpoint `POST /invoice/<id>/preview` (sur le modèle de `/suggest`) ; le formulaire refusé réutilise `kept_forms`.
- Persistance **sans doublon ni perte** : chaque ligne envoie `line_id` (ou `client_uid` pour une nouvelle) ; le serveur fait un upsert par identifiant et supprime les lignes absentes, **dans une seule transaction** `BEGIN IMMEDIATE` avec jeton de révision du brouillon (`invoices.revision`, comparé comme `expected_reliquat`) pour refuser une sauvegarde depuis un onglet périmé ; `UNIQUE(invoice_id, client_uid)` rend le double-clic idempotent.
- Validations (front **et** serveur) : description non vide et qui tient sur N lignes imprimées (`description_line_count`), quantité > 0, prix ≥ 0 (négatif = note de crédit, comme « autres »), unité dans une liste fermée, plafond de lignes (§ risque PDF), total TTC > 0 (déjà contrôlé à l'émission).
- PDF : `table["lines"]` accepte déjà plusieurs éléments ; chaque ligne manuelle ajoute une rangée de hauteur variable. **Point dur** : la géométrie est figée (`golden_layout.json`, contrôle 11) et la page 1 est de capacité limitée (rangée ≥ 26,6 pt ; les totaux commencent à 350,5 pt et le bloc paiement à 549,2 pt minimum, le pied de page à 816 pt). Estimation à **valider par test de rendu** : environ 5 lignes manuelles avant que le bloc paiement descende, une limite dure à fixer (≈ 8) avec message explicite. Les rangées s'ajoutent sous la première sans toucher aux positions de la facture à une ligne (régression zéro attendue) ; l'empreinte du gabarit change si une constante est ajoutée → comparaison avec la référence et mise à jour de `golden_layout.json` (**décision propriétaire**, D3).
- Contrôles d'émission : 3 (inchangé sur la ligne prestation), 4 (TVA recalculée avec les lignes), 10 (`printed_fields` doit inclure les descriptions de lignes manuelles), 11 (les lignes tiennent), 14 et `contract()` : **les lignes manuelles ne comptent pas en jours** (recommandation D2).
- Correction du bug B1-B4 : message d'avertissement dans l'éditeur quand un libellé « AUTRES » est saisi avec un montant nul (« ce libellé ne sera pas imprimé »), description vide → avertissement explicite plutôt que remplacement silencieux, tarif affiché en lecture seule avec sa source, total affiché.

**Migration** : création de table/triggers/index, `ALTER TABLE invoices ADD COLUMN revision INTEGER DEFAULT 0`. Aucune donnée existante transformée ; les brouillons existants n'ont aucune ligne manuelle ; « AUTRES » reste (D1).

**Tests** : montants (arrondi demi-supérieur, TVA hors/soumis, plusieurs lignes, centimes limites) ; ajout/édition/suppression/ordre ; deux sauvegardes successives sans doublon ni perte ; double soumission ; onglet périmé refusé ; persistance après rechargement ; lignes présentes dans le PDF brouillon **et** figées dans le PDF émis ; facture émise : `invoice_lines` immuable (trigger) ; PDF facture à une ligne **identique octet pour octet** à avant (non-régression gabarit) ; débordement de page ; contrôles 3/4/10/11 ; avoir sur facture avec lignes manuelles ; sauvegarde JSON + restauration (`restore_service.ORDER`) ; navigateur (Playwright `--workers=1`) : ajouter/supprimer, badge visuel, mobile (barre d'onglets du lot 2).

**Risques** : géométrie PDF / `golden_layout` (élevé) ; avoirs et exports qui supposent « 1 ligne + autres » (`credit_service.credit_amounts`, ZIP index, `forecast.py:41`, `gsheet_export.py:143`, `post_billing.py:65`) — à ne pas casser, décision D6 sur l'inclusion des lignes manuelles dans le CA HT ; fichier `app.py` monolithique (conflits de merge avec les autres branches : isoler dans un module `app/invoice_lines.py` appelé depuis `draft_values`/`invoice_edit`, sans réécrire l'existant).

### P2 — Adresse de facturation sélectionnable

**Cause** : une adresse texte unique par mandat, lue en direct (§(d)).

**Solution** :
- Table `billing_addresses(id PK, client_key TEXT NOT NULL, label TEXT NOT NULL, entity TEXT, company TEXT, contact TEXT, address TEXT NOT NULL, city TEXT, country TEXT, active INTEGER DEFAULT 1, created_at, UNIQUE(client_key, label))` — gestion **centralisée** (écran « Adresses » dans la fiche du mandat/client, création/édition/désactivation, pas de suppression si utilisée). `client_key` = `legal_key(client_legal_id)` (repli : nom court normalisé) : **pas de nouvelle table clients** (D4).
- `invoices` : `billing_address_id` (référence, nullable) **+ copie** `bill_contact`, `bill_address`, `bill_label` (texte au moment de l'enregistrement du brouillon). Le choix est donc **stable** même si l'adresse du client change ; pour un brouillon, un bouton explicite « Actualiser depuis l'adresse » refait la copie.
- Lecture : `invoice_service.live_data` remplace `billing_contact`/`billing_address` de l'en-tête par la **copie de la facture** quand elle existe, sinon (brouillons et factures existants, clients à adresse unique) par les champs du mandat comme aujourd'hui. `pdf_layout`, `block_fits`, avoirs et snapshot ne changent pas (même clés d'en-tête). Une facture **émise** continue de ne lire que son snapshot : **aucune rétro-modification**.
- Éditeur : menu déroulant (libellé « Entité — Société — Ville, Pays — Destinataire ») ; aperçu de l'adresse choisie ; adresse choisie affichée dans le brouillon et le PDF ; changement = simple `UPDATE` du brouillon, aucun client créé. Distinction explicite dans l'UI et le modèle : adresse **de facturation** (celle-ci) ≠ adresse du client (fiche) ≠ livraison (**hors périmètre, non créée**).
- Contrôles : `missing_for_issue` vérifie l'adresse **effective** ; `block_fits` sur la copie ; contrôle 10 sur la copie.

**Migration** : `CREATE TABLE billing_addresses` ; `ADD COLUMN` ×4 sur `invoices` ; **amorçage idempotent** : pour chaque mandat dont `billing_address` est non vide, une adresse « Adresse du mandat » (copie, le champ du mandat reste lu en repli). Aucune facture existante modifiée (colonnes NULL).

**Tests** : un seul/plusieurs adresses ; changement de choix sans nouveau client ; stabilité du brouillon et du PDF après modification de l'adresse source ; actualisation explicite ; facture émise inchangée après modification/désactivation (extension de `test_v92.py:94-100`) ; avoir sur facture émise avec adresse choisie ; mandat sans adresse (refus d'émission inchangé) ; adresse trop longue (`block_fits`) ; sauvegarde/restauration ; XSS/HTML dans les libellés (échappement Jinja).

**Risques** : définition du « client » (D4) ; dérive entre copie et source (voulue, rendue visible) ; fiche mandat qui garde un champ libre en doublon (à marquer « adresse par défaut »).

### P3 — Numéro modifiable et unique

**Cause** : numéro attribué à l'émission seulement, non modifiable, non réservé (§(c)).

**Périmètre d'unicité proposé : GLOBAL** (toute la base). Justification d'architecture : un seul émetteur (`settings`), pas de table d'entités émettrices, pas de notion d'exercice dans le modèle (l'année est déjà dans le numéro `AAAA-MM`). L'unicité par entité/exercice n'aurait aucune colonne sur laquelle s'appuyer sans modifier le modèle. Voir D5.

**Solution** :
- **Colonne existante `invoices.number` réutilisée pour la réservation** : un brouillon porte son numéro proposé dès la création ; l'index `UNIQUE` existant le protège alors déjà contre tout doublon avec les autres brouillons et les factures émises (les numéros « réservés par les brouillons actifs » découlent du mécanisme existant). Alternative écartée à ce stade : colonne séparée `reserved_number` (nécessite des triggers croisés). **À vérifier avant de s'engager** : tout le code qui teste `number IS NULL` / `number` comme preuve d'émission (inventaire à faire : `app.py` l.842-876, 1032, 1122, `post_billing`, `credit_service`) ; le statut reste la seule vérité d'émission.
- Index complémentaire : `CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_number_nocase ON invoices(number COLLATE NOCASE) WHERE number IS NOT NULL` + trigger refusant un numéro égal (casse/espaces) à une `historical_invoices.invoice_ref`. **Prérequis** : requête de contrôle sur une copie de sauvegarde (doublons à la casse près) ; si doublon, l'index échoue → arrêt du démarrage : donc **créer l'index seulement après vérification** (migration gardée, comme `migrate_rc19`, transaction `BEGIN IMMEDIATE`).
- Colonne `number_manual INTEGER DEFAULT 0` : tant que le numéro n'a pas été modifié à la main, il est **re-proposé** si la période change ; une fois modifié à la main, il n'est plus jamais remplacé automatiquement.
- Format accepté (serveur **et** formulaire) : 1 à 20 caractères parmi `A-Z a-z 0-9 -` `/`, sans espaces en bordure, **sans « . » ni `_` ni `%`** (invariant des avoirs `NC-…` et `LIKE`), sans préfixe `NC-`, et qui tient dans la case « N° Facture » du PDF. Contrôle de format ≠ nouvelle convention : le proposé reste `AAAA-MM[-N]`.
- Écriture : validation + `UPDATE` dans **la même transaction `BEGIN IMMEDIATE`** ; sur `IntegrityError` : rollback, message explicite (« Le numéro X est déjà utilisé par la facture émise / le brouillon n° … ; numéro libre proposé : Y ») et **proposition seulement** — jamais de remplacement silencieux. `EXTERNAL_INVOICE_NUMBERS` et `historical_invoices.invoice_ref` restent réservés.
- Émission : le numéro du brouillon est repris tel quel (écran d'émission et `issue` lisent la même valeur ; fin de la faiblesse n°1 de §(c)). Brouillons **sans** numéro (existants) : chemin actuel inchangé (`next_invoice_number` à l'émission, avec garde « numéro attendu » ajoutée).
- Brouillon supprimé : numéro libéré ; brouillons abandonnés visibles dans la liste (colonne numéro) pour être nettoyés ; politique de réutilisation des numéros libérés : D5.
- **Factures émises jamais renumérotées** : déjà garanti par le trigger `issued_invoice_no_update`. Procédure traçable de correction = **note de crédit totale + nouvelle facture** (existe déjà) ; une renumérotation exceptionnelle n'est pas prévue (D7).
- Cohérence du numéro : une seule source (`invoices.number`) lue par éditeur, PDF, snapshot, ZIP/CSV, références d'avoir ; test de bout en bout qui compare le numéro à chacun de ces endroits.
- Trace : `invoice_number_changes` (append-only, modèle `invoice_date_changes`) + ligne `audit`.

**Migration** : `ADD COLUMN number_manual` ; index NOCASE après contrôle ; trigger historique ; table de trace. Aucune facture existante modifiée.

**Tests** : proposition à la création (et mise à jour si la période change) ; modification manuelle valide/invalide (format, `.`, `_`, `%`, `NC-`, longueur, casse, espaces) ; collision avec brouillon, facture émise, numéro externe, `invoice_ref` historique ; **collision concurrente** (deux requêtes simultanées : une seule gagne, l'autre reçoit un message + proposition) étendant `tests/concurrency_http.py` ; émission reprend le numéro réservé ; brouillon supprimé libère le numéro ; facture émise non renumérotable (trigger) ; numéro identique partout (éditeur, base, PDF figé, ZIP/CSV, avoir `NC-…`) ; brouillons existants (numéro NULL) émis comme avant ; sauvegarde/restauration.

**Risques** : code supposant `number NULL = brouillon` (inventaire ci-dessus) ; index NOCASE échouant sur des données existantes (contrôle préalable obligatoire) ; numéros non chronologiques (D5) ; une saisie manuelle peut « boucher » la suite automatique (`max+1` ne regarde que les suffixes `-N` du même mois).

### Ordre de livraison proposé
1. P3 (numéro) — petit, risque modèle faible, valeur forte ; 2. P2 (adresses) — pas de changement de gabarit PDF ; 3. P1 (lignes manuelles) — le plus lourd (PDF, avoirs, exports), à livrer en dernier avec la décision sur le gabarit. Chaque étape : sauvegarde + répétition sur copie + arrêt si `schema_checks` signale un problème.

---

## (f) Décisions métier à demander au propriétaire (choix fermés, avec recommandation)

**Q0 — Le bug signalé.** Pouvez-vous donner un exemple (mandat, n° de brouillon, ce qui a été saisi, ce qui est imprimé) ? *Sinon*, voulez-vous que nous traitions comme « le bug » : (A) libellé « autres » non imprimé quand le montant est 0 (B1) ; (B) montant « autres » imprimé seulement dans les totaux (B2) ; (C) les deux. **Recommandation : C**, résolu de toute façon par P1.

**D1 — « AUTRES » avec les lignes manuelles.** (A) Conserver « AUTRES » tel quel (ligne unique, dans les totaux) en plus des lignes manuelles ; (B) le remplacer par une ligne manuelle (migration des brouillons, avoirs à adapter). **Recommandation : A** (aucune régression sur avoirs/factures émises ; B à envisager plus tard).

**D2 — TVA et jours des lignes manuelles.** (A) Même TVA que la facture + choix « hors TVA / soumis » par ligne (comme « autres »), et lignes **exclues** du décompte en jours du mandat ; (B) taux de TVA propre à chaque ligne ; (C) lignes comptées en jours si l'unité est le jour. **Recommandation : A.**

**D3 — Gabarit PDF.** (A) Ajouter des rangées sous la première ligne, limite dure à N lignes (≈ 8, fixée par test), puis refus explicite ; mise à jour de l'empreinte `golden_layout.json` après comparaison avec la facture de référence ; (B) lignes supplémentaires sur une page de continuation ; (C) ne rien changer au gabarit (lignes manuelles seulement dans l'annexe). **Recommandation : A.**

**D4 — Qu'est-ce qu'un « client » pour les adresses ?** (A) Regroupement par identité juridique (`client_legal_id`) sans nouvelle table clients ; (B) nouvelle table `clients` rattachée aux mandats (plus propre, migration plus lourde) ; (C) adresses rattachées au mandat seulement. **Recommandation : A** (B plus tard si besoin d'entités émettrices multiples).

**D5 — Numérotation.** (a) Périmètre d'unicité : (A) global ; (B) par exercice ; (C) par entité émettrice. **Recommandation : A.** (b) Le numéro d'un brouillon supprimé jamais émis peut-il être réutilisé : (A) oui, c'est le premier libre qui est proposé ; (B) non, il reste consommé. **Recommandation : A** (rien n'a été émis). (c) Les numéros saisis à la main doivent-ils rester au format `AAAA-MM[-N]` : (A) oui, strict ; (B) format libre dans les limites de §P3 (alphanumérique, `-`, `/`, ≤ 20). **Recommandation : B** si vous avez besoin de numéros hors série (ex. reprise d'une facture externe), sinon A. (d) La séquence non chronologique (facture de septembre émise en novembre → `2026-09-2`) est-elle acceptable : (A) oui, règle actuelle conservée ; (B) à revoir avec votre fiduciaire. **Recommandation : A pour cette mission** (changer la règle est hors périmètre), question à poser à votre fiduciaire si une exigence de suite chronologique existe.

**D6 — Exports et CA.** Les lignes manuelles comptent-elles dans le CA HT des prévisions et de l'export tableur (`forecast.py`, `gsheet_export.py`, qui ne lisent aujourd'hui que quantité × tarif) : (A) oui ; (B) non, comme « autres » aujourd'hui. **Recommandation : A pour la cohérence avec le total facturé ; à confirmer** — à noter que « autres » en est aujourd'hui exclu, ce qui est déjà une incohérence connue.

**D7 — Correction d'un numéro après émission.** (A) Jamais : note de crédit totale + nouvelle facture (procédure existante, traçable) ; (B) procédure exceptionnelle de renumérotation avec journal (nécessite de lever un trigger d'immutabilité et de re-sceller snapshot, PDF, avoirs : déconseillé). **Recommandation : A.**

**D8 — Adresse affichée sur un brouillon existant sans choix.** (A) Continuer à lire l'adresse du mandat jusqu'au premier choix explicite ; (B) figer automatiquement la copie à la première ouverture de l'éditeur. **Recommandation : A** (aucun changement silencieux ; la copie se fait au premier enregistrement avec choix).

---

## Annexe — Fichiers lus (pour revue)
`app/app.py` (schéma `init`, routes brouillon/émission/PDF/ZIP/avoirs/sauvegarde), `app/billing_rules.py`, `app/invoice_service.py`, `app/invoice_checks.py`, `app/pdf_layout.py`, `app/restore_service.py`, `app/schema_checks.py`, `app/security.py` (variables d'environnement seulement), `app/templates/invoice_edit.html`, `index.html`, `project_edit.html`, `credit_new.html`, `docs/PAQUET-RC36.md` (en-tête), `MIGRATIONS-RC11.md`, `procedure/docker-compose.*.yml` (grep), tests cités. Aucun fichier `.env`, aucune base de données lue.
