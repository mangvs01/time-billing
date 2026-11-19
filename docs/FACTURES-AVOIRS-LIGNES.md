# Avoirs sur factures à lignes manuelles — blocage d'émission et extension du circuit d'avoirs (rc38 candidate)

Mission BILLING (claude2), 26.10.2026, sur la base rc37 (`9927428`, en production). **Rien n'est commité, construit, déployé ni exécuté en production** ; aucune base ni `.env` de production lus (tests sur bases synthétiques jetables). `app/app.py:VERSION` n'est **pas** modifié (voir §6).

Décisions du propriétaire appliquées : **Q1 = B puis C** (étendre les avoirs aux lignes manuelles ; en attendant, bloquer l'émission d'une facture à lignes manuelles, brouillon autorisé ; lever le blocage seulement quand les avoirs sont livrés et testés) · **Q2** ligne « AUTRES » à 0 : non imprimée + avertissement · **Q3** année du numéro = date de facture · **Q4** adresses EGG par nom court « EGG » · **Q5** brouillon à 14 pt, émis inchangé.

## 1. Ce qui change

### 1.1 Blocage de l'émission (Q1 = C) — livré, actif par défaut
- Interrupteur unique `billing_rules.MANUAL_LINES_ISSUANCE_BLOCKED = True` (+ `manual_lines_issuance_problem(c, iid)`), lu au moment de chaque usage.
- Trois barrières : (1) la route d'émission `POST /issue/<id>` refuse avec un message explicite (nombre de lignes, motif, issue : supprimer les lignes) ; (2) l'écran `GET /issue/<id>` affiche l'encadré « Émission impossible », l'état « lignes manuelles (émission suspendue) » et désactive le bouton ; (3) `invoice_service.freeze` (dernier rempart, hors migration d'anciennes factures).
- Le **brouillon reste entièrement utilisable** : création, édition des lignes, PDF brouillon, suppression. Bandeau dans l'éditeur, mention « émission suspendue (lignes manuelles) » dans la liste.
- **Lever le blocage** = passer cette constante à `False` (une ligne, après la recette du superviseur) : rien d'autre à modifier (les tests de ce module la lèvent eux-mêmes).

### 1.2 Avoirs sur lignes manuelles (Q1 = B) — livré
Une note de crédit peut maintenant créditer **chaque ligne manuelle, en tout ou en partie, par un montant HT par ligne** (une ligne n'est pas faite de jours : la position en jours du mandat n'est pas touchée). La TVA suit celle de la ligne d'origine (soumis / hors TVA). Combinable dans une même note avec des jours / un montant de prestation et « AUTRES ».
- **Colonnes** (`credit_notes`) : `lines_taxed`, `lines_untaxed` (HT crédité sur les lignes soumises / hors TVA ; `REAL NOT NULL DEFAULT 0`).
- **Table `credit_note_lines`** : `credit_note_id, invoice_line_id, position, description, amount > 0, vat_mode, created_at`, `UNIQUE(credit_note_id, invoice_line_id)` (description et régime TVA **copiés** de la ligne de facture : le texte imprimé ne dépend d'aucune lecture ultérieure).
- **Plafonds, application** (`credit_service`) : `creditable()` donne le solde par ligne et par total (service, lignes, AUTRES, TTC) ; `check_creditable()` refuse le dépassement d'une ligne (message nommant la ligne, son montant, le déjà crédité, le solde), vérifie que le détail égale les totaux, applique la règle « crédit total + imputations reçues » à l'ensemble ; les brouillons de notes comptent dans le cumul, les notes annulées non.
- **Plafonds, SQL** (déclencheurs, additifs) : `credit_lines_within_line` (cumul d'une ligne ≤ son montant + 0,005, notes annulées exclues), `credit_lines_same_invoice` (la ligne appartient à la facture de la note), `credit_lines_same_vat_mode`, `credit_lines_no_insert_frozen / no_update_issued / no_delete_issued` (lignes d'une note émise immuables), `credit_lines_totals_match` (à l'émission, les totaux de la note égalent la somme des lignes).
- **Déclencheur de plafonnement des remboursements / imputations `credit_ops_within_note`** : remplacé (DROP + CREATE dans une transaction `BEGIN IMMEDIATE`, relue à l'intérieur pour deux workers simultanés) par la formule `(montant + AUTRES + lignes soumises) × (1 + TVA %) + lignes hors TVA + 0,05`. Sans lignes : **identique à avant**.
- **Calculs** : `credit_amounts` renvoie aussi `lines_taxed / lines_untaxed / lines_ht / subtotal` ; `ht` reste la prestation seule (comme pour une facture). TVA de clôture (`closing_vat`) : une note qui épuise service, AUTRES **et** lignes porte le solde exact de TVA de la facture (la somme des TVA des avoirs = la TVA de la facture, test dédié). `fully_credited` exige maintenant aussi les lignes. Cibles d'imputation (`target_candidates`) : le reste dû d'une facture cible compte ses lignes.
- **PDF d'avoir** : les lignes créditées s'impriment sous la ligne de prestation (mêmes rangées que la facture, sans quantité ni prix unitaire), pas de ligne de prestation à 0,00 pour un avoir « lignes seules », SOUS-TOTAL CRÉDITÉ = prestation + lignes. Les lignes sont **figées dans l'en-tête du snapshot** de la note (`header_json.lines`) ; le PDF émis ne relit jamais la table. Le **document d'annulation** (`ANN-…`) liste les mêmes lignes. Les notes émises avant rc38 se rendent comme avant (aucune clé `lines`).
- **Garde de page** (`credit_page_problem`, `pdf_layout.credit_page_bottom`) : à la création et à l'émission, rendu à blanc ; refus complet (rien d'écrit) si la note ne tient pas sur la page 1 (≤ 807 pt, même mesure que le contrôle 11).
- **Écrans** : formulaire d'avoir (tableau des lignes : montant, déjà crédité, solde, champ « à créditer » par ligne), détail de la note (lignes créditées), liste des factures (statut crédité / solde y compris lignes).
- **Exports** : CA HT (`forecast.py`, `gsheet_export.py`) et index CSV du ZIP : un avoir de lignes réduit le CA comme la facture l'avait augmenté (D6 = A) ; pas de jours.
- **Sauvegarde / restauration** : `credit_note_lines` dans `restore_service.ORDER` (après `credit_notes`, avant `credit_note_snapshots`) et dans `IMMUTABLE` (lignes des notes émises) ; sondes ajoutées à `schema_checks` (déclencheurs, table, colonnes, formule du plafond).
- Ancien refus (`CREDIT_LINES_REFUSAL`) **supprimé**.

### 1.3 Q2 – Q5 (constats)
- **Q2** déjà conforme (rc37) : « AUTRES » à 0 non imprimé + avertissement à l'enregistrement et sous le champ (tests `test_E3…`, `test_the_other_label…`). Aucune modification.
- **Q3** déjà conforme (rc37) : année du numéro = année de la date de facture. Aucune modification.
- **Q4** : `scripts/seed_adresses_egg.py` utilise désormais **`--client-name EGG` par défaut** (sans option) ; `--client-legal-id` reste possible ; toujours simulation par défaut. Test ajouté. Rappel : la clé de regroupement par nom ne vaut que si les mandats EGG n'ont **pas** d'identité juridique (sinon la clé est cette identité et le script s'arrête avec un message explicite).
- **Q5** déjà conforme (rc37) : brouillon à 14 pt, émis inchangé. Aucune modification.

## 2. Migration (additive, idempotente, rejouée à chaque démarrage par `init()`)
Ajouts : colonnes `credit_notes.lines_taxed`, `lines_untaxed` ; table `credit_note_lines` + index `idx_credit_lines_invoice_line` ; 7 déclencheurs `credit_lines_*` ; **remplacement** du déclencheur `credit_ops_within_note` (seul objet existant modifié : même résultat sans lignes). Module : `app/credit_lines.py`. **Aucune donnée existante transformée ni supprimée** ; aucune facture, note, snapshot, opération touchés ; aucune écriture dans `audit`. Test `Migration` : une base à la forme rc37 (table, colonnes et déclencheurs retirés, ancienne formule rétablie) est migrée deux fois, chaque ligne ancienne est identique, `schema_checks.rc19_problems == []`, la note rc37 se lit comme avant.
Retour arrière : les ajouts sont inertes pour rc37 (colonnes/table ignorées) **mais** une note créditant des lignes, créée avec rc38 puis lue par rc37, y serait mal montée (TTC sans les lignes) et le plafond d'opérations rc37 la refuserait : en cas de retour arrière après la première note sur lignes, restaurer la sauvegarde (`procedure/90-rollback.sh`). Tant que `MANUAL_LINES_ISSUANCE_BLOCKED` reste `True`, aucune nouvelle facture à lignes n'est émise ; seules les factures **déjà émises en rc37 avec des lignes** (s'il y en a) peuvent recevoir une note.

## 3. Tests
Fichier `tests/test_credit_lines.py` (35 tests) : blocage (route, écran, éditeur/liste, brouillon sans ligne, retrait des lignes, levée de la constante) ; montants (total, avec AUTRES, partiel d'une ligne, mixte jours + ligne, somme des TVA = TVA de la facture) ; plafonds (cumul sur plusieurs notes, valeurs invalides, total après partiel, ligne d'une autre facture) ; déclencheurs SQL ; plafond des remboursements ; PDF de la note (lignes, totaux, figé), brouillon, annulation + libération des lignes + remplacement, suppression d'un brouillon, garde de page, six lignes sur deux lignes ; imputation sur une facture cible à lignes ; remboursement ; CA / ZIP ; sauvegarde-restauration ; migration depuis rc37. Tests existants adaptés : `tests/test_invoice_lines.py` (les classes qui émettent une facture à lignes lèvent le blocage ; ancien test « avoir refusé » remplacé), `tests/test_invoice_numbers.py` (migration rc36 : retrait préalable des objets rc38), `tests/test_billing_addresses.py` (+1 test Q4).

Commande (isolée, base synthétique jetable, aucun accès à la production) :
```
cd /root/rc25-ui-20261014/.claude/worktrees/billing-factures
/root/venvs/rc25-test-venv/bin/python -I outils/run_tests_isolated.py tests.test_credit_lines tests.test_invoice_lines tests.test_billing_addresses tests.test_invoice_numbers
# suite complète (≈ 6 min) :
/root/venvs/rc25-test-venv/bin/python -I outils/run_tests_isolated.py $(ls tests/test_*.py | sed 's#/#.#;s#\.py$##')
```
**Résultats (exécutés par moi dans le lanceur isolé, base synthétique jetable)** : suite complète **966 tests, OK** (5 échecs attendus déjà présents en rc37 ; 931 en rc37 + 35 nouveaux), 236 s. À rejouer par le superviseur dans son bac à sable.
**Non exécutés** (inchangé depuis rc37) : `tests/concurrency_http.py` (serveur local) et les recettes navigateur ; le formulaire d'avoir n'a pas de JavaScript (champs HTML simples), donc rien de nouveau côté navigateur, mais l'affichage n'a pas été vu dans un navigateur.

## 4. Risques et points d'attention
1. **Levée du blocage** : ne la faire qu'après recette humaine d'un cycle complet (facture à lignes → émission → avoir partiel → avoir total → remboursement) sur la copie de recette.
2. **Factures à lignes déjà émises en rc37** : à recenser sur la copie de production (`SELECT i.number FROM invoices i WHERE i.status='issued' AND EXISTS(SELECT 1 FROM invoice_lines WHERE invoice_id=i.id)`) : elles peuvent maintenant être créditées.
3. **Plafond SQL par ligne** : calculé sur `ROUND(qty × prix, 2)` en virgule flottante avec 0,005 de tolérance ; le contrôle exact (Decimal, demi-supérieur) est applicatif. Un écart d'un centime sur une ligne aux produits limites est donc possible d'un côté ou de l'autre mais jamais au-delà de la tolérance.
4. **Clôture de TVA** : une note qui épuise tout porte le solde exact de TVA ; un avoir de lignes seules à TVA mixte arrondit sa propre base (comme les avoirs existants).
5. **Pas de JavaScript** sur le formulaire d'avoir : le total TTC de la note n'est pas prévisualisé avant création (il l'est sur le détail du brouillon et son PDF).
6. **Version** : `VERSION` reste `9.2-rc37` ; plusieurs tests figent ce numéro. À décider avec le superviseur (rc38 = bump + adaptation des tests concernés).
7. `app.py` monolithique : ajouts isolés dans `app/credit_lines.py` ; modifications de `app.py` limitées à `init`, `issue`, `credit_values`, `credit_new`, `credit_issue`, `credit_delete`, `credit_detail`, index des factures, ZIP.

## 5. Décisions à faire valider
- **R1 — Lever le blocage** (constante à `False`) après recette : GO du propriétaire, ou garder le blocage et n'utiliser les avoirs de lignes que pour les factures déjà émises ?
- **R2 — Granularité** : l'avoir crédite un **montant HT par ligne** (pas une quantité). Si le propriétaire veut créditer des quantités (ex. 1 pièce sur 3), c'est une évolution (colonnes `qty` sur `credit_note_lines`).
- **R3 — Bump de version** `9.2-rc38` et mise à jour de `docs/PAQUET-RC*.md`.

## 6. Fichiers
**Créés** : `app/credit_lines.py`, `tests/test_credit_lines.py`, `docs/FACTURES-AVOIRS-LIGNES.md`.
**Modifiés** : `app/app.py`, `app/billing_rules.py`, `app/credit_service.py`, `app/invoice_service.py`, `app/pdf_layout.py`, `app/forecast.py`, `app/gsheet_export.py`, `app/restore_service.py`, `app/schema_checks.py`, `app/templates/credit_new.html`, `credit_detail.html`, `issue_confirm.html`, `invoice_edit.html`, `index.html`, `scripts/seed_adresses_egg.py`, `tests/test_invoice_lines.py`, `tests/test_invoice_numbers.py`, `tests/test_billing_addresses.py`.
`golden_layout.json` : **inchangé** (aucune constante de géométrie ajoutée ; empreinte vérifiée identique). Rien n'est commité.
