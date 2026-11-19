# Édition des brouillons de facture — implémentation P1 → P2 → P3 (9.2-rc37)

Mission BILLING-FACTURES-IMPLÉMENTATION (claude0, reprise de claude2), 26.10.2026. Base : production 9.2-rc36 (`7f8182c`). **Rien n'est commité, construit, déployé ni exécuté en production** ; aucune base ni `.env` de production lus (jeux de données synthétiques jetables uniquement). Version du code : `9.2-rc37` (`app/app.py:VERSION`).

**Mise à jour 26.10.2026 (décision Q1 = B puis C)** : le refus d'avoir sur lignes manuelles décrit aux §0, §2 et §7 est remplacé par l'extension du circuit d'avoirs et par le blocage de l'émission des factures à lignes manuelles : voir `docs/FACTURES-AVOIRS-LIGNES.md`.

Documents de référence : `docs/FACTURES-AUDIT-PLAN.md` (audit et plan), `docs/HANDOFF-CLAUDE2.md` (décisions D1-D8 du propriétaire et compléments du PDF annoté).

## 0. En bref

| Étape | Demande | État | Tests de l'étape |
|---|---|---|---|
| P1 | Plusieurs lignes manuelles sur une facture (+ bug d'affichage de la ligne saisie) | livré | 38 tests, suite complète verte |
| P2 | Adresse de facturation choisie dans une liste déroulante (EGG FR / BE / CH / MEA) | livré | 19 tests, suite complète verte |
| P3 | Numéro `AAAA-N` proposé et réservé dès le brouillon, modifiable, unique ; chevauchement date/numéro du PDF corrigé | livré | 35 tests, suite complète verte |

Suite complète finale : **931 tests, OK** (5 échecs attendus déjà présents en rc36) ; avant la mission : 839 tests OK. Détail et commandes au §8.

**Deux choses à connaître avant tout** (détail aux §7 et §9) :
1. **Notes de crédit sur une facture à lignes manuelles : refusées explicitement (fail closed)**, faute de décision. Une facture sans ligne manuelle se crédite comme avant. → question Q1.
2. **Avant la mise en production** : `EXTERNAL_INVOICE_NUMBERS` doit contenir `2026-10` (la facture réelle émise hors application), sinon le premier brouillon créé se verra proposer `2026-10`.

## 1. Décisions appliquées

D1 « AUTRES » conservé tel quel en plus des lignes manuelles · D2 TVA de la facture avec choix « soumis / hors TVA » par ligne, lignes manuelles **exclues** du décompte en jours · D3 rangées sous la ligne de prestation, limite dure **8 lignes** + budget de hauteur, refus explicite au-delà, `golden_layout.json` mis à jour · D4 adresses regroupées par identité juridique, sans table clients · D5 unicité **globale**, numéro d'un brouillon supprimé réutilisable (premier libre proposé), numéros saisis à la main en **format libre dans les limites du plan** (reco. B) · D6 lignes manuelles dans le CA HT (`forecast.py`, `gsheet_export.py`) · D7 jamais de renumérotation après émission · D8 un brouillon existant garde l'adresse du mandat jusqu'au premier choix explicite, la copie se fait à l'enregistrement du choix.

Interprétations que j'ai dû faire (à valider, §9) : Q0 (bug), année du numéro, mandat EGG sans identité juridique.

## 2. P1 — Lignes manuelles multiples

### Causes (voir audit §(b))
- **Fonctionnalité absente** : le modèle ne connaissait qu'une ligne de prestation (heures) + une ligne « AUTRES » ; aucune table, route ni champ pour plusieurs lignes.
- **Bug « ma ligne ne s'affiche pas »** (B1-B4 de l'audit, aucune reproduction réelle possible, aucun brouillon de production lu) : B1 libellé « AUTRES » enregistré mais non imprimé quand le montant est 0 ; B2 le montant « AUTRES » n'est imprimé que dans les totaux ; B3 description vidée remplacée silencieusement par le nom du mandat ; B4 éditeur sans total ni tarif visible.

### Solution
- **Table `invoice_lines`** (additive) : `id, invoice_id, position, kind='manual', description, qty>0, unit (day|hour|flat|piece), unit_rate>=0, vat_mode (soumis|hors_tva), client_uid, created_at`, `UNIQUE(invoice_id, position)`, `UNIQUE(invoice_id, client_uid)`. Trois déclencheurs : plus d'insertion une fois la facture figée (snapshot présent), plus de modification ni suppression d'une facture émise.
- **`rules.amounts(..., lines)`** : montant de ligne = quantité × prix arrondi au centime demi-supérieur ; base TVA = prestation + lignes « soumises » (+ « AUTRES » si soumis) ; **une seule** arrondie de TVA sur la base. Les clés historiques gardent leur sens (`ht` = prestation seule) ; ajout de `lines_ht`, `lines_taxed`, `lines_untaxed`, `subtotal`. `ttc = ht + lignes + tva + autres`.
- **Éditeur** (`invoice_edit.html`, `app/invoice_lines.py`) : bloc « Lignes de la facture » — ligne de prestation en lecture seule (badge « Prestations (heures) », tarif du mandat affiché), lignes « manuelles » (badge, fond distinct), « Ajouter une ligne » / « Supprimer cette ligne » **qui fonctionnent sans JavaScript** (le serveur réaffiche le formulaire, rien n'est écrit tant qu'on n'enregistre pas) et avec JS (ajout sans rechargement), récapitulatif des totaux **calculé par le serveur** (`POST /invoice/<id>/preview`, même fonction que le PDF), bouton par défaut du formulaire = Enregistrer (Entrée ne déclenche jamais « Supprimer »).
- **Persistance** : un enregistrement = **une transaction** (`BEGIN IMMEDIATE`) : mise à jour du brouillon + upsert des lignes (par `line_id`, ou par `client_uid` pour une ligne nouvelle : un double-clic ne crée rien deux fois) + suppression des lignes absentes. Jeton **`invoices.revision`** : un onglet périmé est refusé (« modifié depuis l'ouverture de cette page ») et la page réaffichée garde le jeton périmé (impossible de l'écraser à l'aveugle). Un refus annule tout (le brouillon reste intact, les lignes tapées sont réaffichées).
- **PDF** : rangées sous la ligne de prestation, 1 ou 2 lignes de description, quantité + unité (si ≠ JOUR/HEURES), prix, montant ; SOUS-TOTAL = prestation + lignes. Les lignes sont **figées dans le snapshot** à l'émission (`header_json.lines`) ; une facture émise ne relit jamais la table.
- **Limites (D3)** : 8 lignes maximum, description ≤ 2 lignes imprimées, aucun mot plus large que la colonne, quantité qui tient dans sa cellule, hauteur totale ≤ 170 pt (`MANUAL_ROWS_BUDGET`). Deux protections : le formulaire (refus explicite) et le **contrôle 11** à l'émission, qui mesure par un rendu à blanc que la page 1 ne descend pas dans le pied de page (`first_page_bottom` ≤ 807 pt), y compris avec imputations de notes de crédit, note longue ou conditions de paiement longues.
- **Contrôles d'émission** : 3 inchangé (ligne de prestation), 4 recalcule TVA et total avec les lignes, 10 contrôle le texte des lignes (mots de test), 11 voir ci-dessus. `contract()` / contrôle 14 : lignes **non comptées en jours**.
- **Bug** : le libellé « AUTRES » avec montant 0 reste non imprimé (décision G4 §6 inchangée, test `E3` conservé) mais **n'est plus silencieux** : avertissement à l'enregistrement et mention sous le champ ; description vide → avertissement explicite ; tarif et totaux visibles dans l'éditeur ; les lignes « réelles » vont dans le tableau.
- **Exports** (D6 = A) : `forecast.py` et `gsheet_export.py` comptent les lignes manuelles dans le CA HT (pas dans les jours) ; liste des factures et index CSV de l'archive ZIP : HT = sous-total imprimé.
- **Suppression d'un brouillon** : ses lignes partent avec lui (tracé dans l'audit).
- **Notes de crédit** : **refus explicite** sur une facture portant des lignes manuelles (`CREDIT_LINES_REFUSAL`) — voir §7 / Q1. Avertissement sur l'écran d'émission.

### Confirmation explicite : persistance des lignes manuelles
Les lignes manuelles **sont persistées sans doublon ni perte**. Prouvé par : enregistrement puis rechargement de l'éditeur (`test_add_edit_remove_and_persist_after_reload`) ; deux enregistrements successifs de la même page (`test_two_successive_saves…`) ; double soumission du même formulaire (`test_double_submission…`) ; onglet périmé (`test_a_stale_tab…`) ; refus partiel = rien d'écrit et rollback du brouillon (`test_a_refused_save…`, `test_failure_in_the_lines_rolls_back…`) ; six enregistrements simultanés du même formulaire et deux enregistrements concurrents de même révision (`test_concurrent_saves…`, et `tests/concurrency_http.py` §1c — **non exécuté**, voir §8) ; lignes présentes dans le PDF brouillon, **figées** dans le PDF émis (le PDF émis ne change pas même si la table est modifiée hors application) ; triggers d'immutabilité ; aller-retour sauvegarde JSON → restauration (`LinesRestore`) ; suppression du brouillon.

### Fichiers P1
`app/invoice_lines.py` (nouveau) · `app/app.py` (schéma, éditeur, preview, suppression, listes, ZIP, garde avoirs) · `app/billing_rules.py` · `app/pdf_layout.py` · `app/invoice_service.py` · `app/invoice_checks.py` · `app/forecast.py` · `app/gsheet_export.py` · `app/restore_service.py` (`ORDER`) · `app/schema_checks.py` · `app/golden_layout.json` · `app/templates/invoice_edit.html`, `issue_confirm.html` · `tests/test_invoice_lines.py`, `tests/fixtures/page1_rc36_below_header.json`.

## 3. P2 — Adresse de facturation sélectionnable

### Cause
Une seule adresse texte libre par mandat, lue **en direct** (un brouillon suivait toute modification du mandat), pas de choix par facture.

### Solution
- **Table `billing_addresses`** (additive) `client_key, label, contact, address, active, sort_order`, `UNIQUE(client_key, label)` ; `client_key` = identité juridique normalisée (`rules.legal_key`) **et, à défaut d'identité juridique sur le mandat, le nom court du client** (préfixe `NOM:`). Aucune table clients (D4).
- **Colonnes `invoices`** : `billing_address_id` + copie `bill_label, bill_contact, bill_address` (instantané). Le choix **copie** le texte dans la facture ; il ne bouge plus si l'adresse est modifiée (bouton « Actualiser la copie » explicite). Valeur vide = retour explicite à l'adresse de la fiche du mandat. Un formulaire sans le champ (ancien script) laisse le choix inchangé. Une adresse désactivée reste visible sur le brouillon qui la porte mais ne peut plus être choisie.
- **Lecture** : `invoice_service.live_data` imprime la copie du brouillon, sinon l'adresse du mandat (D8) ; l'en-tête figé à l'émission contient `billing_label`, `billing_source` (`choix`/`mandat`) et `billing_address_id` ; les notes de crédit réutilisent l'en-tête figé (test : adresse choisie imprimée sur l'avoir). `missing_for_issue` exige l'adresse **effective** (un mandat sans adresse devient émissible avec une adresse choisie). Libellé d'alerte `[À COMPLÉTER : Adresse de facturation]` conservé tant qu'aucune adresse n'est disponible.
- **Éditeur** : liste déroulante « Adresse de facturation » (option par défaut « Adresse de la fiche du mandat »), aperçu du texte choisi (échappé), lien « Gérer les adresses ». Écran **`/adresses`** (ajout, modification, désactivation ; jamais de suppression ; nombre de factures ayant copié chaque adresse).
- **Les 4 adresses EGG, texte du propriétaire tel quel** : `app/donnees_adresses/egg.json` (libellés dans l'ordre EGG FR, EGG BE, EGG CH, EGG MEA ; un test relit `docs/commentaire-pdf-adresses.txt` et compare ligne à ligne ; la dernière ligne d'EGG FR, `FR74 433 639 523`, est le n° de TVA).
- **Script idempotent `scripts/seed_adresses_egg.py`** : **simulation par défaut** ; écriture seulement avec `--appliquer --confirmer SEMER-ADRESSES-EGG` (après sauvegarde) ; une adresse déjà présente et identique n'est pas touchée, différente = jamais écrasée sans `--mettre-a-jour` ; crée la table si absente ; vérifie qu'au moins un mandat porte la clé et les liste ; une ligne d'audit si quelque chose est écrit. Paramétré par `--client-legal-id <identité>` **ou `--client-name EGG`**.

### Fichiers P2
`app/address_service.py`, `app/donnees_adresses/egg.json`, `app/templates/adresses.html`, `scripts/seed_adresses_egg.py` (nouveaux) · `app/app.py` (schéma, éditeur, routes `/adresses*`) · `app/invoice_service.py` · `app/pdf_layout.py` (`block_rows`, `BILLING_MAX_ROWS`) · `app/restore_service.py` · `app/templates/invoice_edit.html`, `project_edit.html` · `tests/test_billing_addresses.py`.

## 4. P3 — Numéro `AAAA-N`, réservé, modifiable, unique

### Causes
Numéro attribué **à l'émission seulement** (`AAAA-MM` du mois de fin de période), non modifiable, non réservé ; écran d'émission recalculé hors transaction.

### Solution
- **Format proposé `AAAA-N`** (année de la **date de facture** — à défaut du jour —, puis numéro d'ordre de l'année, sans zéro initial). `N` = premier numéro **libre** au-dessus du plus grand numéro déjà **émis** de l'année parmi `invoices.number` émis, `historical_invoices.invoice_ref` (tout statut), `EXTERNAL_INVOICE_NUMBERS` ; un numéro d'une version antérieure (`AAAA-MM`, `AAAA-MM-N`) compte comme pris et son mois se lit comme le numéro d'ordre (**`2026-10` → la suite est `2026-11`**, l'exemple du propriétaire). Les trous laissés par un brouillon supprimé sont comblés (D5 b).
- **Numéro réservé dès le brouillon** : `invoices.number` (déjà `UNIQUE`) est renseigné à la **création** (`BEGIN IMMEDIATE`), affiché dans l'éditeur, sur l'écran d'émission et sur le **PDF brouillon** (« 2026-11 (proposé) » ; « (attribué à l'émission) » n'existe plus), repris tel quel à l'émission. Les brouillons créés avant rc37 (numéro NULL) gardent leur absence de numéro : l'éditeur affiche la proposition (non réservée, aucune écriture par un GET), elle est réservée à l'enregistrement, ou attribuée à l'émission.
- **Modification** : champ « Numéro de facture » ; saisie libre dans les limites de D5 c : 1 à 20 caractères parmi lettres latines, chiffres, `-`, `/`, commençant par une lettre ou un chiffre, **sans** espace, `.`, `_`, `%`, **sans** préfixe `NC-`. Un numéro saisi est marqué `number_manual=1` : **jamais remplacé automatiquement**. Vide = reproposer. Un numéro automatique suit l'année de la date de facture ; à l'émission, un numéro automatique d'une autre année que la date imprimée est remplacé par le premier libre de l'année imprimée (annoncé sur l'écran d'émission).
- **Unicité** (confirmée, voir plus bas) et **conflit explicite** : « le numéro X est déjà utilisé par la facture émise Y / le brouillon n° Z (mandat M) / une facture historique (hors application) / un numéro externe réservé ; numéro libre proposé : W. Rien n'a été modifié : aucun numéro n'est jamais remplacé automatiquement ». Le numéro libre est une **proposition**, jamais appliquée.
- **Émission** : le formulaire renvoie `expected_number` (refus si le numéro a changé depuis l'affichage), contrôle de conflit sous `BEGIN IMMEDIATE`, message explicite en cas de collision tardive (facture historique ajoutée entre-temps), `IntegrityError` transformée en message lisible. **Jamais de renumérotation après émission** (trigger existant ; correction = note de crédit totale + nouvelle facture, D7).
- **Traçabilité** : table `invoice_number_changes` (append-only) + ligne d'audit à chaque changement (création, modification, émission si le numéro a dû changer) ; suppression d'un brouillon : numéro libéré noté dans l'audit.
- **Impact sur les avoirs** : `NC-<n° facture>` puis `NC-<n°>.2`, `.3`. Aucun numéro ne contenant `.` ni `%` ni `_`, la dérivation reste sans ambiguïté ; **nouveauté** : un numéro peut contenir `/` (`NC-EXT/42`) ; le nom de fichier du ZIP l'assainit (`_`). Exemples : `NC-2026-11`, `NC-2026-11.2`. Les avoirs déjà émis (`NC-2026-09`) ne changent pas.
- **Autres adaptations** : `historical_billing.TB_NUMBER_RE` accepte les deux formats ; la validation d'une facture historique ne compare plus qu'aux factures **émises** (un brouillon ne fait que réserver, son conflit est signalé à l'émission : le fait réel l'emporte).

### Confirmation explicite : unicité des numéros
Les numéros de facture sont **uniques globalement**, par plusieurs barrières indépendantes : (1) contrainte `UNIQUE` binaire existante sur `invoices.number` ; (2) **index unique normalisé** `idx_invoices_number_norm` sur `upper(trim(number))` (casse et espaces) — créé seulement si les données existantes n'ont aucun doublon à la casse près (sinon : ignoré, une ligne d'audit, signalé par `schema_checks`, le démarrage n'échoue pas) ; (3) **triggers** : un brouillon (ou l'émission) ne peut pas prendre un numéro de `historical_invoices` ; une facture ne peut pas être émise sans numéro ; (4) contrôle applicatif sous `BEGIN IMMEDIATE` contre factures, brouillons, historiques, numéros externes (`EXTERNAL_INVOICE_NUMBERS`, qui n'a pas d'existence en base) ; (5) émission sous `BEGIN IMMEDIATE`. Prouvé par : variantes de casse et d'espaces, collision avec facture émise / brouillon / historique / externe (messages), triggers au niveau SQL, **six créations simultanées → six numéros distincts**, quatre brouillons qui saisissent le même numéro en même temps → un seul gagne, numéro d'un brouillon supprimé réutilisé, facture émise non renumérotable.
*Limite* : `EXTERNAL_INVOICE_NUMBERS` n'est pas visible de la base : son contrôle est applicatif seulement ; il doit être tenu à jour à chaque facture émise hors application (§7).

### Fichiers P3
`app/billing_rules.py` (`propose_invoice_number`, `check_invoice_number`, `number_conflict`…, remplace `next_invoice_number`) · `app/app.py` (schéma, création, éditeur, émission, suppression) · `app/invoice_service.py` · `app/pdf_layout.py` (texte du numéro, `DRAFT_REF_ROW_PITCH`) · `app/schema_checks.py` · `app/historical_billing.py` · `app/restore_service.py` · `app/templates/invoice_edit.html`, `issue_confirm.html`, `index.html` · `tests/test_invoice_numbers.py` ; tests existants dont les attentes de numéros `AAAA-MM` ont été **adaptées à la nouvelle règle** : `test_v92, test_functional, test_rc3, test_rc4, test_rc5, test_rc7, test_rc8, test_rc10, test_rc23_historiques, test_rc25, test_rc25_c0_anticipation, test_g4_fidelite, test_credit_settlement, test_ux_lot2, test_calendrier` (version), `test_rc6` (épinglage rc5 du brouillon) — les attentes dépendent de l'année du jour (`YEAR`), pas d'une année codée en dur.

## 5. PDF brouillon — vérification contre le PDF fourni

Scénario reconstruit avec des données synthétiques (mandat « GEM STC 2026 - 2600140AE », client EGG, 16,43 j × 600 CHF, TVA 0, date prévue 26.10.2026, `EXTERNAL_INVOICE_NUMBERS=2026-10`) ; fichiers : `docs/factures-impl-captures/` (`01-sans-adresse`, `02-EGG-CH`, `02-EGG-FR`, `03-avec-lignes`, `.pdf` et `.png`).

- **Comparaison de positions** avec `audit/g4/comparer_pdf_reference.py` (`docs/facture-brouillon_avec_commentaires.pdf` contre `01-sans-adresse.pdf`) : 18 étiquettes sur 20 **à 0,0 pt** ; seules « N° Facture » (+2,9 pt) et « PO: » (+5,8 pt) bougent, volontairement (ci-dessous). Écart maximal 5,8 pt.
- **Chevauchement date / numéro** : dans le fichier fourni, les deux lignes sont espacées de 11,1 pt pour un texte de 8 pt dont la boîte de ligne fait 10,9 pt (écart de 0,19 pt entre la boîte de « 26.10.2026 (prévue) » et celle de la ligne suivante) : elles se touchent, et le rectangle de commentaire rouge du propriétaire passe sur la ligne de date. Correction : **le brouillon** espace les trois lignes date / numéro / PO de **14,0 pt** (`DRAFT_REF_ROW_PITCH`, ≈ 3 pt entre boîtes) ; le document **émis** garde 11,1 pt (géométrie de référence). Constaté sur le PDF généré : `26.10.2026 (prévue)` puis `2026-11 (proposé)`, sans superposition. Test : `test_the_planned_date_and_the_number_do_not_overlap…`.
- **Adresse** : libellé `[À COMPLÉTER : Adresse de facturation]` conservé sans choix ; avec EGG CH ou EGG FR le texte du propriétaire s'imprime ligne à ligne (`02-EGG-CH`, `02-EGG-FR`). `03-avec-lignes` : trois lignes manuelles sous la prestation, SOUS-TOTAL 10 468,50 CHF.
- **Anomalie trouvée par ce contrôle visuel et corrigée** : une description de prestation sur 2 lignes + la ligne « Période » (3 lignes imprimées) chevauchait la première ligne manuelle ; la ligne de prestation garde désormais sa hauteur réelle quand des lignes manuelles la suivent (test dédié ; le pire cas de hauteur a été remesuré avec cette ligne la plus haute). Sans ligne manuelle, aucune position ne bouge.
- **Non-régression gabarit** : sans ligne manuelle, **toutes** les instructions de dessin de la facture (108 appels de dessin, brouillon avec et sans « AUTRES ») sont identiques à celles de rc36 (capture avant/après), et un oracle versionné (`tests/fixtures/page1_rc36_below_header.json`, capturé sur le code rc36) le vérifie à chaque exécution pour la partie sous l'en-tête. **`golden_layout.json` mis à jour** (nouvelle empreinte `91cad972…`) : aucune constante existante modifiée, constantes ajoutées (`MAX_MANUAL_LINES`, `MANUAL_*`, `PAGE_ONE_*`, `BILLING_MAX_ROWS`, `REF_ROW_PITCH`, `DRAFT_REF_ROW_PITCH`). **Réserve** : la facture réelle de référence `Facture-reelle-reference-2026-09.pdf` n'est pas disponible dans cet environnement ; la comparaison de 2026-10-06 reste la mesure de référence et le PDF brouillon fourni sert de seconde référence (0,0 pt).

## 6. Migration (additive, idempotente, rejouée à chaque démarrage par `init()`)

Créations : tables `invoice_lines`, `billing_addresses`, `invoice_number_changes` ; colonnes `invoices.revision` (`INTEGER NOT NULL DEFAULT 0`), `billing_address_id`, `bill_label`, `bill_contact`, `bill_address`, `number_manual` (`INTEGER NOT NULL DEFAULT 0`) ; index `idx_number_changes_invoice`, `idx_invoices_number_norm` (conditionnel) ; triggers `invoice_lines_*` (3), `invoice_number_changes_no_update/no_delete`, `invoice_number_not_historical_ins/upd`, `invoice_issue_needs_number`. **Aucune donnée existante transformée ni supprimée** : aucune facture, aucun avoir, aucun snapshot touché ; les brouillons existants gardent numéro NULL, adresse du mandat, aucune ligne. Test `MigrationFromRc36` : une base à la forme rc36 (nouveaux objets retirés, données rc36) est migrée deux fois de suite, chaque colonne ancienne de chaque ligne est identique, `schema_checks.rc19_problems` = `[]`, l'audit n'est pas écrit, le brouillon NULL est ensuite émis normalement.
- `restore_service.ORDER` : `billing_addresses` après `projects`, `invoice_number_changes` avant `invoices`, `invoice_lines` entre `invoices` et `invoice_snapshots` (les lignes d'une facture émise sont reconstruites avant son snapshot, ce qui explique que le trigger d'insertion regarde le snapshot). Aller-retour sauvegarde JSON / restauration testé pour les trois tables.
- `schema_checks` : nouveaux triggers, tables, colonnes, index et sondes d'écriture (`PROBES`).
- **Sauvegarde et répétition avant production** : procédure habituelle (`procedure/20-backup.sh`, `30-rehearse.sh` sur copie, `50-verify.sh`) ; **à vérifier sur la copie de production** : requête de doublons à la casse près sur `invoices.number` (l'index est alors ignoré et signalé, le démarrage ne s'arrête pas). **Retour arrière** : les ajouts sont inertes pour rc36 (colonnes/tables ignorées) mais un retour arrière après création de brouillons rc37 laisserait des numéros réservés sur ces brouillons (rc36 les ignorerait et attribuerait `AAAA-MM` à l'émission) : restaurer plutôt la sauvegarde (`procedure/90-rollback.sh`).

## 7. Risques et points d'attention

1. **Avoirs et lignes manuelles** (le plus important). Le mécanisme d'avoirs (`credit_service`, déclencheur SQL de plafonnement des remboursements, PDF d'avoir) ne connaît que « prestation » et « AUTRES ». Faire entrer les lignes manuelles dans le `ttc` sans l'adapter aurait laissé un crédit total incomplet sans signal. Choix retenu : **refus explicite** de toute note de crédit sur une facture à lignes manuelles ; tout le reste des avoirs est inchangé. Conséquence : une facture émise avec une ligne manuelle ne peut pas être corrigée par note de crédit dans rc37 (avertissement sur l'écran d'émission). Voir Q1.
2. **`EXTERNAL_INVOICE_NUMBERS`** doit être `2026-09,2026-10` en production avant le premier brouillon (les fichiers `procedure/docker-compose.*.yml` ont `2026-09` par défaut ; non modifiés ici). Un numéro externe oublié = numéro proposé en doublon avec une facture réelle, détecté seulement si le numéro est connu.
3. **Mandat EGG sans identité juridique** : le PDF annoté n'imprime aucune ligne « N° d'identification » pour « GEM STC 2026 - 2600140AE », donc `client_legal_id` est probablement vide ; la clé de groupement est alors le nom court du client (`NOM:egg`) : les mandats EGG doivent porter **le même nom court « EGG »** (casse et espaces ignorés) ou la même identité juridique, sinon ils ne partagent pas la liste.
4. **Réservation** : les brouillons réservent leurs numéros ; une rafale de brouillons abandonnés consomme des numéros tant qu'ils ne sont pas supprimés (liste des factures : mention « réservé (brouillon) »). Deux brouillons ne partagent plus jamais un numéro futur.
5. **Année du numéro = année de la date de facture** (à défaut, du jour d'émission) ; une facture de décembre émise en janvier sans date fixée change de numéro à l'émission s'il était automatique (annoncé sur l'écran). Séquence non chronologique possible (D5 d, règle actuelle conservée).
6. **Géométrie PDF** : la limite des lignes manuelles est conservatrice (170 pt) ; le contrôle 11 mesure la page réelle. Le brouillon espace davantage ses lignes d'en-tête (14,0 pt) que le document émis.
7. **`app.py` monolithique** : ajouts isolés dans `app/invoice_lines.py` et `app/address_service.py` pour limiter les conflits de fusion avec les autres branches (`billing-calendrier`, thème) ; `app/templates/invoice_edit.html` est entièrement réécrit (il n'avait que 12 lignes).
8. La création de brouillon (formulaire de l'onglet « Édition des factures ») n'a pas de champs adresse / lignes / numéro : tout se fait dans l'éditeur du brouillon, immédiatement après la création.

## 8. Tests

**Commande** (runner isolé du scratchpad des missions précédentes, copié et rendu indépendant de l'emplacement dans `outils/run_tests_isolated.py` ; venv `rc25-test-venv`, base synthétique jetable créée par `app.init()` dans un dossier temporaire privé, aucune lecture de `.env`, `sqlite3.connect` refusé hors de ce dossier) :

```
cd /root/rc25-ui-20261014/.claude/worktrees/billing-factures
/root/venvs/rc25-test-venv/bin/python -I outils/run_tests_isolated.py tests.test_invoice_lines tests.test_billing_addresses tests.test_invoice_numbers
# suite complète (≈ 6 min) :
/root/venvs/rc25-test-venv/bin/python -I outils/run_tests_isolated.py $(ls tests/test_*.py | sed 's#/#.#;s#\.py$##')
```

**Résultats** (chaque étape lancée et verte avant la suivante) :

| Point de contrôle | Tests | Résultat |
|---|---|---|
| Avant toute modification (rc36) | 839 | OK (5 échecs attendus) |
| Après P1 | 876 | OK |
| Après P2 | 894 | OK |
| Après P3 (puis corrections : chevauchement ligne de prestation / lignes, espacement brouillon, migration, script par nom de client) | **931** | **OK** (5 échecs attendus) |

Tests ajoutés : `tests/test_invoice_lines.py` (38 : montants, formulaire, persistance, concurrence, PDF, pire cas de hauteur, contrôles, gel à l'émission, avoirs, exports, sauvegarde/restauration, migration), `tests/test_billing_addresses.py` (19), `tests/test_invoice_numbers.py` (35 dont migration depuis la forme rc36, concurrence par threads sur l'application complète) ; 34 tests existants adaptés à la nouvelle règle de numérotation (§4).

**Non exécutés (refusés dans cet environnement, non contournés)** :
- `tests/concurrency_http.py` (rafales contre un gunicorn réel, 2 workers) : le lancement d'un serveur local a été refusé. Le script a été **mis à jour** (créations simultanées, numéro saisi par 4 brouillons, enregistrements simultanés du même formulaire, numérotation `AAAA-N`) mais **n'a pas été lancé** ; la concurrence est couverte en attendant par des tests à threads sur l'application complète (Flask), qui ne remplacent pas le test multi-processus. À lancer par le superviseur (voir l'en-tête du script).
- Recettes navigateur (Playwright, `tests/browser/*.js`) : non lancées ; **JavaScript de l'éditeur non vérifié dans un navigateur** (ajout / suppression de ligne sans rechargement, aperçu des totaux, aperçu de l'adresse). Les chemins sans JavaScript (boutons serveur) sont testés. Aucune recette `recette-factures.js` n'a été écrite.

## 9. Décisions à faire valider (choix fermés)

- **Q1 — Notes de crédit sur une facture à lignes manuelles.** (A) Livrer rc37 avec le refus explicite actuel, et traiter les avoirs sur lignes manuelles dans rc38 ; (B) étendre maintenant le mécanisme d'avoirs (lignes créditables en bloc avec le crédit total : colonnes sur `credit_notes`, plafonds, déclencheur SQL des opérations, PDF d'avoir, `fully_credited`), ce qui touche le circuit financier et son déclencheur de plafonnement ; (C) n'autoriser les lignes manuelles que sur le brouillon et interdire leur émission tant que B n'est pas fait. **Recommandation : B avant toute émission réelle d'une facture à lignes manuelles ; sinon C**. A est le plus risqué pour la comptabilité : une erreur sur une telle facture ne se corrigerait pas par avoir.
- **Q2 — Bug signalé (Q0).** Interprétation retenue : « libellé AUTRES non imprimé à 0 » rendu **non silencieux** (avertissement) plutôt que imprimé (la décision G4 §6 le garde non imprimé) ; « montant AUTRES dans les totaux » conservé (D1) avec les vraies lignes dans le tableau. Choix : (A) conforme à cette interprétation ; (B) imprimer le libellé « AUTRES » même à 0 (change la facture de référence). **Recommandation : A.**
- **Q3 — Année du numéro.** (A) année de la date de facture (retenu) ; (B) année du jour de création du brouillon, sans suivre la date ; (C) année du jour d'émission. **Recommandation : A.**
- **Q4 — Clé de regroupement des adresses EGG.** Confirmer que les mandats EGG n'ont pas d'identité juridique : (A) utiliser `--client-name EGG` ; (B) renseigner la même identité juridique sur tous les mandats EGG puis `--client-legal-id`. **Recommandation : B si EGG a une identité juridique connue (plus robuste que le nom), sinon A.**
- **Q5 — Espacement du brouillon.** (A) Brouillon à 14,0 pt, émis inchangé (retenu) ; (B) tout à 14,0 pt, nouvelle comparaison de référence à faire ; (C) ne rien changer (le chevauchement n'était dû qu'à l'annotation). **Recommandation : A.**
- **Q6 — Mise en production** : exécuter `scripts/seed_adresses_egg.py` (simulation d'abord) après sauvegarde, régler `EXTERNAL_INVOICE_NUMBERS=2026-09,2026-10`, vérifier les doublons de casse sur la copie de production, puis seulement GO.

## 10. Liste des fichiers

**Modifiés** : `app/app.py`, `app/billing_rules.py`, `app/forecast.py`, `app/golden_layout.json`, `app/gsheet_export.py`, `app/historical_billing.py`, `app/invoice_checks.py`, `app/invoice_service.py`, `app/pdf_layout.py`, `app/restore_service.py`, `app/schema_checks.py`, `app/templates/index.html`, `invoice_edit.html`, `issue_confirm.html`, `project_edit.html`, `tests/concurrency_http.py` et 15 fichiers de tests existants (§4).
**Créés** : `app/address_service.py`, `app/invoice_lines.py`, `app/donnees_adresses/egg.json`, `app/templates/adresses.html`, `scripts/seed_adresses_egg.py`, `outils/run_tests_isolated.py`, `tests/test_invoice_lines.py`, `tests/test_billing_addresses.py`, `tests/test_invoice_numbers.py`, `tests/fixtures/page1_rc36_below_header.json`, `docs/factures-impl-captures/*`, ce document.
Rien n'est commité (le superviseur commite par chemins).
