# Revue adverse indépendante des ajouts rc37 → rc40 (factures à lignes manuelles, avoirs sur lignes, adresses, numérotation, PDF, exports, restauration)

Mission BILLING-REVUE-AVOIRS-ADRESSES (claude2) · dépôt `/root/rc25-ui-20261014`, worktree `.claude/worktrees/billing-factures`, branche `campaign/billing-factures`, HEAD `4b8a98c` (9.2-rc40 en production).
Aucune donnée de production lue ni écrite. Aucun test exécuté (le superviseur les lance). Aucun commit, aucun push, aucun déploiement.

## 1. État Git au départ et à l'arrivée

- Au départ : arbre propre, sauf deux éléments non suivis qui ne sont pas à moi et que je n'ai pas touchés : `docs/facture-brouillon_avec_commentaires.pdf` et `docs/factures-impl-captures/`.
- À l'arrivée, modifiés (non commités) : `app/billing_rules.py`, `app/invoice_lines.py`, `app/address_service.py`, `app/restore_service.py`, `app/app.py` (3 lignes) ; ajoutés : `tests/test_revue_rc40.py`, `docs/FACTURES-REVUE-RC40.md`. Rien n'a été écrasé.
- Vérifications faites : compilation (`py_compile`) des fichiers modifiés, et quelques calculs ponctuels hors application (fonctions pures importées avec un module PDF factice ; un `ROUND` SQLite en mémoire). Ni `pytest`, ni serveur, ni `test-slot`.

## 2. Méthode

Lecture intégrale de `credit_lines.py`, `credit_service.py`, `address_service.py`, `invoice_lines.py`, `billing_rules.py`, `invoice_service.py`, `restore_service.py`, des routes de `app.py` (édition de brouillon, numéro, émission, avoirs, archive ZIP, sauvegarde), de `pdf_layout.py` (page 1, avoirs, annulation), des différences rc36→rc40 de `invoice_checks.py`, `schema_checks.py`, `forecast.py`, `gsheet_export.py`, `historical_billing.py`, et des tests existants pour ne pas les dupliquer. Pour chaque axe demandé, j'ai cherché un scénario concret qui casse l'invariant, puis soit corrigé (défaut local sûr), soit documenté avec un test `expectedFailure` (défaut confirmé mais qui touche le schéma de production ou une règle métier).

Échelle : **Haute** = intégrité d'un document émis ou montant faux possible ; **Moyenne** = refus à tort, collision ou texte non maîtrisé en usage normal ; **Basse** = défense en profondeur, cas rare ; **Info** = pas un défaut, point à connaître.

## 3. Synthèse

| Réf. | Axe | Gravité | État |
|---|---|---|---|
| F-R1 | Restauration : lignes manuelles d'une facture émise non protégées | Haute (fichier de sauvegarde modifié) | **Corrigé** |
| F-N1 | Numéros : `2026-09` / `2026-9` / `2026-009` pris pour des numéros différents | Moyenne | **Corrigé** |
| F-L1 | Lignes : caractères de contrôle / de direction acceptés dans la description | Moyenne | **Corrigé** |
| F-L3 | Lignes : montant d'une ligne non plafonné (jusqu'à ~10^15 CHF) | Moyenne | **Corrigé** |
| F-L2 | Lignes : quantité arrondie à 0 → erreur SQL brute | Basse | **Corrigé** |
| F-A2 | Adresses : isolats de direction, contrôles C1, trait d'union conditionnel acceptés | Basse | **Corrigé** |
| F-D1 | Noms de téléchargement avec `/` (numéro `2026/7`) | Basse | **Corrigé** |
| F-C1 | Avoir : plafond SQL d'une ligne arrondi en flottant → avoir total refusé sur un produit à demi-centime | Moyenne | **Ouvert** (migration de déclencheur) |
| F-T1 | Déclencheur `invoice_lines_no_update_issued` : une ligne de brouillon peut être déplacée sous une facture émise par SQL direct | Basse | **Ouvert** (déclencheur additif) |
| F-T2 | Lignes d'avoir brouillon : gardes en `BEFORE INSERT` seulement, contournables par `UPDATE` direct | Basse | **Ouvert** (déclencheur additif) |
| F-A1 | Adresses : libellés distincts seulement par la casse ; même libellé propre au client et global | Basse | **Ouvert** (règle métier) |
| F-H1 | Factures historiques : numéros comparés exactement (casse, zéros) | Basse | **Ouvert** (décision G4 « N1 exact ») |
| F-V1 | TVA : un taux par facture, « TVA par ligne » = régime soumis / hors TVA, arrondi unique sur la base | Info | À valider |
| F-V2 | Avoirs successifs : TVA arrondie par note + solde à la note de clôture | Info | Aucune action |
| F-V3 | Plafond SQL des remboursements : marge de 5 centimes | Info | Aucune action |
| F-N2 | Numéros libérés (brouillon supprimé) redonnés plus tard | Info | Décision D5 b du propriétaire |

Aucun défaut ne produit un document émis faux dans le fonctionnement normal : les montants, le PDF, l'écran, l'archive et le chiffre d'affaires lisent la même fonction (`rules.amounts`).

## 4. Constats corrigés (preuves et correctif)

### F-R1 — Restauration : lignes manuelles d'une facture émise (Haute)
- **Preuve** : `app/restore_service.py:146-160` (dictionnaire `IMMUTABLE`) ne comparait que `credit_note_lines` ; `invoice_lines` n'y figurait pas. L'ordre de reconstruction (`ORDER`, ligne 16-17) insère `invoice_lines` *avant* `invoice_snapshots` exprès (le déclencheur `invoice_lines_no_insert_frozen`, `app/app.py:177`, regarde le cliché). Un fichier de sauvegarde où `qty`, `unit_rate` ou `vat_mode` d'une ligne d'une facture émise a été modifié passait donc `preview()` : les plafonds d'avoir (`credit_service.inv_amounts`, `credit_service.py:59-61`), le chiffre d'affaires (`forecast.py:39-44`, `gsheet_export.py:145-148`) et l'index de l'archive (`app.py:1922`) lisent cette table, alors que le PDF figé et l'écran du document lisent le cliché → deux vérités.
- **Correctif** : `invoice_lines` ajouté à `IMMUTABLE` (comparaison colonne par colonne des lignes des factures émises) et nouvelle fonction `lines_consistency()` (`restore_service.py:184-209`, appelée dans `preview()` ligne 136) : les lignes du fichier doivent être exactement la copie imprimée du cliché (factures) et les lignes créditées du cliché (avoirs émis). Une sauvegarde sans ces lignes est aussi bloquée.
- **Risque du correctif** : une sauvegarde légitime ne peut pas différer (les lignes sont immuables par déclencheur depuis l'émission) ; en cas de faux blocage, le message nomme la facture. Non exécuté.

### F-N1 — Collision de numéros par zéros de tête (Moyenne)
- **Preuve** : `billing_rules.number_key` (avant : `strip().upper()`) ; `number_conflict` (`billing_rules.py:377-385`) et `propose_invoice_number` (`:390-399`) comparent cette clé. `2026-09` (format AAAA-MM des versions précédentes, par exemple la facture externe CIRSE) et `2026-9` ou `2026-009` (format AAAA-N, saisie libre autorisée) étaient « libres » l'un par rapport à l'autre, alors que `parse_number` (`:355-358`) les lit comme la même séquence. L'index SQL `idx_invoices_number_norm` (`app.py:116`) ne compare que `upper(trim())`.
- **Correctif** : `number_key` normalise les formats numériques `N-N[-N]` (entiers sans zéros de tête, `billing_rules.py:336-343`) ; `AAAA-MM-N` reste distinct de `AAAA-MM`. La proposition compare avec la même clé. Les formats libres (`EXT/5`, `ISS-1`) restent comparés tels quels (casse et espaces ignorés).
- **Compatibilité** : plus strict seulement. Le jeu de tests existant (`test_number_key_ignores_case_and_surrounding_spaces`) reste vrai.

### F-L1 — Description de ligne : caractères invisibles / de direction (Moyenne)
- **Preuve** : `invoice_lines.validate` ne faisait que `" ".join(split())` ; un `U+202E`, un `U+200B`, un NUL ou un `U+061C` passaient et étaient imprimés (PDF) et affichés (éditeur, avoir). Le texte des adresses filtrait déjà une partie de ces caractères (`address_service.py:16`) : incohérence.
- **Correctif** : refus explicite (`invoice_lines.py:17,60`) des contrôles C0/C1, des caractères de largeur nulle, de direction (embeddings, overrides, isolats), du trait d'union conditionnel et de la marque de lettre arabe (écrits en séquences `\u`, aucun caractère arabe littéral).

### F-L3 — Montant d'une ligne non plafonné (Moyenne)
- **Preuve** : `MAX_QTY = 1e6`, `MAX_RATE = 1e9` (`invoice_lines.py:15`, avant correctif) → ligne jusqu'à 10^15 CHF ; le formulaire d'avoir limite un montant à 1e9 (`app.py:409` `MAX_MONEY`, `:413-419` `money_field`) : une telle ligne ne pouvait plus jamais être créditée en entier, et la colonne MONTANT du PDF (alignée à droite en x = 552) déborde vers la quantité.
- **Correctif** : `MAX_AMOUNT = 1 000 000 000,00 CHF` par ligne et pour l'ensemble des lignes (`invoice_lines.py:15,78-80`).

### F-L2 — Quantité arrondie à zéro (Basse)
- **Preuve** : `_number(..., lo_open=True)` teste `d == 0` avant `quantize(0.000001)` : `0.0000004` passe puis vaut `0` ; le `CHECK(qty>0)` de `invoice_lines` (`app.py:~172`) renvoie « CHECK constraint failed » au lieu d'un message de ligne.
- **Correctif** : test après arrondi (`invoice_lines.py:62`).

### F-A2 — Texte des adresses (Basse)
- **Preuve** : `_CTRL` (`address_service.py:16`) s'arrête aux embeddings / overrides (`U+202A-202E`) et ne couvre ni les isolats `U+2066-2069`, ni `U+061C`, ni les contrôles C1, ni `U+00AD`.
- **Correctif** : `_CTRL_MORE` (`address_service.py:17`, appliqué dans `clean_text`, ligne 29). `U+0085` (saut de ligne C1) est volontairement conservé : `split()` le traite comme un blanc.

### F-D1 — Noms de fichiers téléchargés (Basse)
- **Preuve** : `app.py:1636, 1872, 1900` utilisaient le numéro tel quel (`2026/7` est un numéro valide) ; l'archive ZIP, elle, passe déjà par `_safe_name` (`:1905`).
- **Correctif** : `_safe_name` sur les trois noms ; `2026-09`, `NC-2026-09.2` restent identiques.

## 5. Constats ouverts (non corrigés, avec patch proposé)

### F-C1 — Avoir total d'une ligne dont le produit finit sur un demi-centime (Moyenne)
- **Preuve** : `app/credit_lines.py:33-37` : le déclencheur `credit_lines_within_line` plafonne à `ROUND(qty*unit_rate,2)+0.005` en **flottant** SQLite ; l'application et la facture arrondissent en `Decimal` demi-supérieur (`billing_rules.line_amount`, `:167-169`). Mesuré (SQLite en mémoire) : `1,5 × 0,15` → application 0,23, SQL 0,22 (plafond 0,225) ; idem `3 × 0,075`, `1,005 × 1`, `2,675 × 1`, `7 × 0,145` (1,02 contre 1,01). L'avoir total de ce type de ligne est refusé par la base (« The credits of an invoice line cannot exceed its amount ») alors que `check_creditable` (`credit_service.py:180-211`) l'accepte : le client ne peut pas être crédité de l'intégralité de la ligne.
- **Patch proposé** (migration comme celle de `credit_ops_within_note`, `credit_lines.py:56-69`) : remplacer `+0.005` par `+0.0101` dans le déclencheur (le contrôle exact reste celui de l'application), avec `DROP TRIGGER IF EXISTS` puis `CREATE` dans `migrate()` quand le SQL stocké ne contient pas le nouveau marqueur.
- **Pourquoi pas appliqué** : modifie un déclencheur de la base de production au démarrage. À valider.
- **Test** : `OpenDefects.test_F_C1_…` (`expectedFailure` ; « succès inattendu » une fois corrigé). **CORRIGÉ le 19/11/2026 (BILL-FC1)** : plafond SQL en centimes entiers exacts, décorateur retiré (voir `docs/TESTS-ATTENDUS.md` § D).

### F-T1 / F-T2 — Gardes de lignes contournables par UPDATE direct (Basse)
- **Preuve** : `app/app.py:178` — `invoice_lines_no_update_issued` teste `OLD.invoice_id` seulement ; `UPDATE invoice_lines SET invoice_id=<facture émise>, position=9 WHERE id=<ligne de brouillon>` passe. `credit_lines.py:27-37` — `same_invoice`, `same_vat_mode`, `within_line` sont des `BEFORE INSERT` ; un `UPDATE` de `invoice_line_id` / `amount` sur une ligne d'avoir brouillon les contourne (l'application le rattrape à l'émission par `check_creditable` + `credit_lines_totals_match`, pas la base). Aucune route n'exécute ces `UPDATE` ; exploitable seulement par accès SQL direct.
- **Patch proposé** (additif, `IF NOT EXISTS`, jouable au démarrage ; la restauration n'utilise que des `INSERT`) :
  ```sql
  CREATE TRIGGER IF NOT EXISTS invoice_lines_no_move BEFORE UPDATE OF invoice_id ON invoice_lines
    WHEN NEW.invoice_id IS NOT OLD.invoice_id BEGIN SELECT RAISE(ABORT,'Lines of an issued invoice are immutable: a line never changes invoice'); END;
  CREATE TRIGGER IF NOT EXISTS credit_lines_written_once BEFORE UPDATE OF credit_note_id, invoice_line_id, position, description, amount, vat_mode ON credit_note_lines
    BEGIN SELECT RAISE(ABORT,'Credited lines are written once'); END;
  ```
  puis ajouter les deux noms à la liste de `schema_checks.rc19_problems`. **Tests** : `OpenDefects.test_F_T1_…`, `test_F_T2_…`. **CORRIGÉ le 19/11/2026 (BILL-FA1FT)** par des déclencheurs plus ciblés que le patch ci-dessus (voir `docs/TESTS-ATTENDUS.md` § E) ; décorateurs retirés.

### F-A1 — Libellés d'adresse (Basse)
- **Preuve** : `address_service.py:14` — `UNIQUE(client_key,label)` est sensible à la casse ; `app.py:740-752` n'ajoute aucun contrôle ; `listing` (`address_service.py:123-125`) propose les adresses du client **et** la liste globale : « EGG FR » et « egg fr », ou un « EGG FR » propre au client en plus du global, apparaissent côte à côte dans le menu. Un choix par erreur imprime la mauvaise adresse sur une facture (la copie est ensuite figée).
- **Décision à prendre** : refuser un libellé identique à la casse et aux espaces près, au sein d'un client **et** face à la liste globale. **Test** : `OpenDefects.test_F_A1_…`. **CORRIGÉ le 19/11/2026 (BILL-FA1FT)** au sein d'un client (index unique NOCASE + contrôle applicatif) ; la comparaison avec la liste globale reste à décider (voir `docs/TESTS-ATTENDUS.md` § E).

### F-H1 — Numéros des factures historiques (Basse)
- **Preuve** : `historical_billing.py:111-117` et `:182-187` comparent exactement (`number=?`, `invoice_ref=?`) ; c'est la règle « N1 compare les numéros exactement » du module (en-tête, lignes 12-14). Les déclencheurs de brouillon (`app.py:~296-300`) sont, eux, insensibles à la casse. Conséquence : une facture historique `iss-1` peut être validée alors qu'une facture émise `ISS-1` existe. Hors périmètre rc37-rc40 ; signalé pour décision.

## 6. Points vérifiés sans défaut (preuves de lecture)

- **Double avoir concurrent** : création et émission d'un avoir sous `BEGIN IMMEDIATE` (`app.py:1760, 1800`), contrôle `check_creditable` dans la même transaction (cumul des brouillons et des émis, annulés exclus : `credit_service.py:105-111`) et filet SQL `credit_lines_within_line`. Trois tests de concurrence ajoutés (deux avoirs de la même ligne, deux avoirs totaux, deux émissions du même brouillon).
- **Immuabilité** : `issued_invoice_no_update/delete`, `issued_credit_no_update/delete`, `invoice_lines_*`, `credit_lines_*`, clichés immuables, `invoice_issue_needs_number` ; PDF servis uniquement depuis les octets figés, empreinte vérifiée (`invoice_service.py:116-120`) ; l'adresse d'une facture émise est la copie figée dans le cliché (`invoice_service.py:33-36`).
- **Arrondis** : `rules.amounts` (`billing_rules.py:172-189`) : chaque ligne arrondie au centime demi-supérieur, une seule TVA sur la base (service + lignes « soumis » + AUTRES si « soumis »), `ttc = ht + lignes + tva + autres` exact ; la même fonction sert l'éditeur (`/preview`), le PDF, le contrôle 4, l'archive, le chiffre d'affaires. La TVA des avoirs successifs est équilibrée par la note de clôture (`credit_service.closing_vat`, `:214-222`). Quantité × prix imprimés = montant imprimé (test de propriété ajouté sur `qty_label` / `rate_money`).
- **Injection** : Jinja avec échappement automatique, aucun `|safe` sur du texte libre ; le JavaScript de l'éditeur (`invoice_edit.html:50-57`) n'insère que le gabarit statique et écrit les totaux par `textContent` ; le PDF dessine par `drawString` (aucun balisage interprété) ; `index.csv` de l'archive ne contient aucun texte libre de ligne et neutralise les formules (`csv_cell`, `app.py:2225-2228`).
- **Exports** : `gsheet_export.documents` et `forecast.build` comptent les lignes d'une facture (`subtotal`) et les lignes créditées d'un avoir de la même façon ; AUTRES reste hors chiffre d'affaires des deux côtés.

## 7. Informations (pas de correctif)

- **F-V1 (à valider)** : le taux de TVA est celui de la facture ; « TVA par ligne » existe sous la forme du régime par ligne (soumis / hors TVA). Si le propriétaire attend des **taux différents par ligne** (par exemple 8,1 % et 2,6 %), ce n'est pas supporté et change le calcul, le PDF et les avoirs.
- **F-V2** : chaque avoir arrondit sa TVA ; la note qui épuise la facture reprend le solde exact. Avec des taux élevés et des montants de quelques centimes, ce solde pourrait être négatif ; sans effet à 8,1 % sur des montants réels.
- **F-V3** : le filet SQL des remboursements tolère 5 centimes (`app.py:247`, `credit_lines.py:44-48`) ; l'application, elle, refuse tout dépassement du solde exact (`credit_service.record_refund`, `:324`).
- **F-N2** : un numéro de brouillon supprimé est redonné (décision D5 b) ; une facture portant un numéro plus bas peut donc être émise après une plus haute. Pas un défaut de code ; à garder présent côté comptabilité.

## 8. Tests ajoutés (écrits, non exécutés) — `tests/test_revue_rc40.py`

| Classe | Contenu | Attendu |
|---|---|---|
| `Unit` | clé de numéro, format de numéro, caractères interdits, quantité arrondie à zéro, plafonds, adresses, quantité × prix = montant (400 cas), totaux = somme des parties (300 cas) | passent |
| `Numbers` | variantes `2026-9`, `2026-009`, ` 2026-09 ` d'un numéro émis refusées ; `2026-09-2` distinct ; la proposition ne donne jamais une variante ; préfixe `NC-`, caractères de direction, `../` | passent |
| `Concurrency` | deux avoirs de la même ligne, deux avoirs totaux, deux émissions du même brouillon ; avoir après épuisement d'une ligne | passent |
| `Injection` | texte libre balisé / `{{7*7}}` / formule : échappé sur éditeur, émission, archive, avoir ; imprimé tel quel dans le PDF ; index de l'archive ; caractère de direction refusé ; nom de téléchargement sans `/` | passent |
| `RestoreForged` | sauvegarde intacte non bloquée ; prix, régime de TVA, description, quantité d'une ligne émise modifiés ; lignes supprimées ; montant / cible d'une ligne créditée modifiés ; ligne ajoutée à un avoir émis | passent |
| `OpenDefects` | F-C1, F-T1, F-T2, F-A1 en `expectedFailure` | 4 « échecs attendus » |

À lancer avec le runner isolé habituel (`python -m unittest tests.test_revue_rc40`, base de test jetable). Les tests dépendent des assistants de `tests/test_credit_lines.py` (classe `Base`) ; si un assistant a changé de signature depuis rc40, c'est là qu'il faut regarder en premier. Les tests existants à relancer en même temps, car mes correctifs les touchent : `test_invoice_numbers`, `test_invoice_lines`, `test_credit_lines`, `test_billing_addresses`, `test_rc25_restore` / `test_rc10` (restauration, archive).

## 9. Décision finale

- **rc40 en production : acceptable, pas de retour arrière.** Je n'ai trouvé aucun scénario d'usage normal qui émette un montant faux ou modifie un document émis. Les risques réels sont : un avoir total refusé sur une ligne à demi-centime (F-C1, détecté par un message clair, aucune donnée altérée) et une restauration qui acceptait un fichier modifié à la main (F-R1).
- **Recommandation** : un **rc41** contenant les sept correctifs locaux ci-dessus (une fois la suite lancée par le superviseur), plus la décision sur F-C1 (je recommande de l'inclure : un seul déclencheur, pattern déjà utilisé en rc38).
- **Annulation d'un correctif** : chacun est indépendant (`number_key`, `validate`, `_CTRL_MORE`, `IMMUTABLE` + `lines_consistency`, `_safe_name`) ; `git checkout -- <fichier>` par le superviseur suffit à en retirer un.

## 10. Rapport de fin de mission

**Fait** : revue des cinq axes ; sept correctifs locaux ; 5 classes de tests négatifs + 4 défauts documentés en `expectedFailure` ; ce document.
**Non fait** : exécution des tests (interdit) ; correction de F-C1, F-T1, F-T2, F-A1, F-H1 (schéma de production ou règle métier) ; revue visuelle des PDF (aucun rendu lancé) ; relecture des gabarits HTML autres que l'éditeur / l'avoir / l'archive.
**Risques** : correctifs non testés (compilés seulement) — en particulier `lines_consistency` (un faux positif bloquerait une restauration légitime, avec un message explicite) et `number_key` (plus strict : un numéro déjà saisi mais équivalent à un autre ne sera plus accepté à l'avenir, sans effet sur l'existant).
**Décisions à valider** : (1) F-C1 : migration du déclencheur ; (2) F-T1/F-T2 : deux déclencheurs additifs ; (3) F-A1 : unicité des libellés à la casse près, et face à la liste globale ; (4) F-V1 : un taux de TVA par ligne est-il attendu ? ; (5) F-H1 : aligner la comparaison des factures historiques ; (6) rc41 : version et déploiement par le superviseur.
