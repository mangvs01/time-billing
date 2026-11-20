# Tests « échec attendu » (`unittest.expectedFailure`) — état au 19/11/2026 (HEAD de6d51e = BILL-FC1 commité, + BILL-FA1FT non commité, 9.2-rc47)

Mission BILL-XFAIL. Méthode : pour chaque test, le décorateur a été neutralisé dans un script **hors dépôt** (`/tmp`, sans modifier le test) afin de lire la VRAIE cause de l'échec.
Résultat : **les 9 échecs attendus étaient de vrais défauts ou limites connues, aucun n'est dû à l'environnement ni à un test périmé.** Aucun test n'avait donc été modifié ; aucun code applicatif n'avait été touché.

**Mise à jour BILL-FC1 (19/11/2026) : F_C1 est CORRIGÉ** (voir § D). **Mise à jour BILL-FA1FT (19/11/2026) : F_A1, F_T1 et F_T2 sont CORRIGÉS** (voir § E) : **plus aucun défaut applicatif** ; il reste **5** échecs attendus, tous des limites du shell (§ B).
Un « succès inattendu » signifie que le défaut est corrigé : retirer alors le décorateur.

## A. Défauts de l'application (tests/test_revue_rc40.py, classe OpenDefects ; origine : commit 010f734, revue contradictoire rc40)

| Test | Fichier:ligne du défaut | Effet pour l'utilisateur |
|---|---|---|
| ~~`test_F_A1_two_global_addresses_differing_only_by_case_are_refused`~~ **CORRIGÉ (BILL-FA1FT)** | `app/address_service.py` (`ensure_label_index`, index `idx_billing_addresses_label_nocase`, `label_taken`) ; `app/app.py` (`address_add`, `address_update`) | Était : « EGG FR » puis « egg fr » acceptés pour les adresses globales. Maintenant refusés (message « existe déjà … à la casse près »). Test devenu un vrai test (décorateur retiré). |
| ~~`test_F_C1_a_line_whose_product_ends_on_a_half_cent_can_be_credited_in_full`~~ **CORRIGÉ (BILL-FC1)** | `app/credit_lines.py` (`WITHIN_LINE_TRIGGER`, déclencheur `credit_lines_within_line`) | Était : ligne 1,5 × 0,15 = 0,225 → facturée 0,23 mais plafond SQL 0,22 + 0,005 : l'avoir total (0,23) était refusé. Maintenant le plafond est le montant FACTURÉ (centimes entiers exacts, demi-supérieur comme `billing_rules.line_amount`) + 0,005 ; le test est un vrai test (décorateur `expectedFailure` retiré) et passe. |
| ~~`test_F_T1_a_draft_line_cannot_be_moved_under_an_issued_invoice_by_sql`~~ **CORRIGÉ (BILL-FA1FT)** | `app/line_guards.py` (déclencheur `invoice_line_no_move_to_issued`) | Était : un UPDATE SQL pouvait rattacher une ligne de brouillon à une facture émise. Maintenant refusé (« Lines of an issued invoice are immutable »). Vrai test. |
| ~~`test_F_T2_a_credited_line_row_of_a_draft_note_cannot_be_redirected_by_sql`~~ **CORRIGÉ (BILL-FA1FT)** | `app/credit_lines.py` (`UPDATE_GUARDS` : déclencheurs `credit_line_upd_*`) | Était : un UPDATE SQL d'une ligne d'avoir brouillon contournait les gardes d'insertion. Maintenant les mêmes gardes existent en BEFORE UPDATE. Vrai test. |

Corrections : F_C1 → § D ; F_A1, F_T1, F_T2 → § E (toutes faites, additives et réversibles).

## B. Limites connues de la garde de procédure (shell) — choix d'architecture, pas des bogues de test

| Test | Cause réelle | Effet |
|---|---|---|
| `tests/test_procedure_adverse.py::test_KNOWN_LIMIT_a_rewritten_guard_can_switch_its_own_checks_off` | Auto-attestation : les empreintes sont vérifiées par `procedure/tb-common.sh` lui-même | Un `tb-common.sh` réécrit n'est pas arrêté (la sauvegarde a tourné, code retour 0). Seules propriété root + droits protègent. |
| `tests/test_procedure_adverse.py::test_KNOWN_LIMIT_a_modified_reader_runs_its_top_level_code_before_any_hash_is_checked` | `procedure/tb-common.sh:5` source `lire-conf.sh` avant toute vérification d'empreinte | Un `lire-conf.sh` modifié exécute son code avant d'être refusé. |
| `tests/test_procedure_residuel.py::test_RESIDUAL_ld_preload_in_the_callers_environment_should_never_execute` | `LD_PRELOAD` de l'appelant est honoré par bash avant la 1re instruction | Bibliothèque hostile exécutée. |
| `tests/test_procedure_residuel.py::test_RESIDUAL_the_documented_env_i_bash_p_launch_should_stop_ld_preload` | `env` (dynamique) charge la bibliothèque avant d'effacer l'environnement | La commande cron documentée ne neutralise pas `LD_PRELOAD`. |
| `tests/test_procedure_residuel.py::test_RESIDUAL_a_script_replaced_after_the_hash_check_should_not_run_the_new_content` | TOCTOU : bash relit le script au fil de l'eau après le contrôle d'empreinte | Une ligne ajoutée après vérification s'exécute (attaquant devant déjà pouvoir écrire dans le dossier). |

Remède : vérificateur extérieur au jeu de fichiers approuvés (voir CONCEPTION-GARDE-CONFIANCE-RC25.md) — décision du propriétaire.

## C. `tests/test_ux_lot2.py::Archive::test_drafts_first_one_main_action_same_markers`

**Non reproduit** le 19/11/2026 : réussit seul (3 fois) et dans la suite complète découpée en 4 lots. Aucune modification faite. Le test dépend de l'année courante uniquement via `YEAR` (non utilisé ici) et d'entrées datées fixes (2026-09/10). Si l'échec réapparaît, relever le message exact (quelle assertion) : hypothèses à vérifier = ordre d'exécution dans un processus unique, ou date système.

## D. BILL-FC1 — correction de F_C1 (19/11/2026)

- **Changement** : le déclencheur `credit_lines_within_line` (BEFORE INSERT sur `credit_note_lines`) plafonne le cumul des avoirs d'une ligne à `montant facturé + 0,005`, où le montant facturé est calculé en entiers : quantité × 10⁶ et prix × 10⁴ (la base les stocke avec au plus 6 et 4 décimales), produit en 10⁻¹⁰ CHF, arrondi au centime demi-supérieur par division entière (`(q*r+50000000)/100000000`). Même résultat que `billing_rules.line_amount` (Decimal, `ROUND_HALF_UP`). Au-delà de ~9·10¹⁸ (hors plage entière SQLite), repli sur l'ancienne formule flottante (aucune erreur). Tolérance 0,005 et message d'erreur inchangés.
- **Migration** : additive et idempotente, rejouée à chaque démarrage par `credit_lines.migrate` (appelée par `init()`) : si le déclencheur n'est pas la version courante (détection : texte `qty*1000000`), `DROP TRIGGER` + `CREATE TRIGGER` dans la même transaction `BEGIN IMMEDIATE` que le plafond des opérations. Aucune donnée, aucune table, aucune colonne touchées : l'empreinte métier de la base est identique avant/après (testé).
- **Retour arrière** (documenté et testé) : `credit_lines.rollback_within_line(conn)` = `DROP TRIGGER credit_lines_within_line` puis recréation de `LEGACY_WITHIN_LINE_TRIGGER` (ancienne version, conservée dans le module). Attention : tant que le code BILL-FC1 est déployé, le démarrage suivant réinstalle le déclencheur exact ; pour un retour arrière durable il faut aussi revenir au code précédent.
- **Tests** : `tests/test_bill_fc1.py` (déclencheur seul comparé à l'application sur 15 produits, cas à demi-centime refusés avant / acceptés après, cas sans demi-centime identiques à l'ancien, cumul et avoirs annulés, repli hors plage, application de bout en bout, base « ancienne » migrée sans perte avec empreinte métier, idempotence, retour arrière) ; `tests/test_revue_rc40.py::OpenDefects::test_F_C1_…` n'est plus `expectedFailure`.

## E. BILL-FA1FT — correction de F_A1, F_T1, F_T2 (19/11/2026)

Trois migrations **additives** (aucune table, colonne ni ligne modifiée ou supprimée), rejouées à chaque démarrage par `app.init()`, idempotentes, avec retour arrière documenté et testé. Tests : `tests/test_bill_fa1ft.py` (22 tests : comportement, migration d'une base « ancienne » avec **empreinte métier identique** avant/après, idempotence, retour arrière, base avec données déjà en défaut) ; les trois `test_F_*` de `tests/test_revue_rc40.py` ont perdu `@expectedFailure` et passent.

| | F_A1 — libellés d'adresse à la casse près | F_T1 — ligne de facture déplacée sous une facture émise | F_T2 — ligne d'avoir brouillon redirigée par UPDATE |
|---|---|---|---|
| **Objet créé** | index unique `idx_billing_addresses_label_nocase` sur `billing_addresses(client_key, label COLLATE NOCASE)` (`address_service.ensure_label_index`) + contrôle applicatif `address_service.label_taken` (casse Unicode complète : « Écu » / « écu », que NOCASE, limité à l'ASCII, ne voit pas) dans `address_add` et `address_update` | déclencheur `invoice_line_no_move_to_issued`, BEFORE UPDATE OF `invoice_id` sur `invoice_lines` (`app/line_guards.py`) : refuse si la facture d'ARRIVÉE est émise ou a une copie figée (même critère que la garde d'insertion) | 4 déclencheurs BEFORE UPDATE sur `credit_note_lines` (`credit_lines.UPDATE_GUARDS`) : `credit_line_upd_same_invoice`, `_same_vat_mode`, `_within_line` (même plafond exact en centimes que BILL-FC1, la ligne réécrite n'étant pas comptée deux fois : `l.id<>NEW.id`), `_no_move_frozen` (pas de rattachement à une note émise ou figée). Ils ne se déclenchent que si une colonne protégée est écrite : description et position restent libres |
| **Vérification préalable des données** | `address_service.label_duplicates` avant création de l'index : **s'il existe déjà un doublon à la casse près, l'index N'EST PAS créé** : une ligne dans `audit` (`billing_address_label_index_skipped`, une seule fois), signalement par `schema_checks.rc19_problems`, démarrage non bloqué, aucune donnée touchée ; l'application refuse quand même les nouveaux doublons (`label_taken`). Dès que les doublons sont corrigés, le démarrage suivant crée l'index | un déclencheur ne contrôle pas les lignes existantes : rien à vérifier côté données, rien ne peut bloquer le démarrage | idem F_T1 |
| **Retour arrière** | `address_service.drop_label_index(c)` = `DROP INDEX IF EXISTS idx_billing_addresses_label_nocase` | `line_guards.rollback(c)` = `DROP TRIGGER IF EXISTS invoice_line_no_move_to_issued` | `credit_lines.rollback_update_guards(c)` = `DROP TRIGGER IF EXISTS` des 4 noms |
| **Autres changements nécessaires** | `address_service.make_global` compare maintenant les libellés `COLLATE NOCASE` (sinon son UPDATE aurait pu heurter l'index et faire échouer le démarrage) ; `restore_service.address_label_conflicts` bloque, dès l'aperçu, une sauvegarde qui contiendrait deux libellés identiques à la casse près (la reconstruction aurait échoué en cours de route) ; `schema_checks.rc19_problems` signale l'index absent | — | refactoring sans effet de `credit_lines` : le plafond (`_CAP_SQL`) est partagé avec le déclencheur d'insertion de BILL-FC1, dont le texte est resté **identique octet pour octet** (vérifié) |

**Note de retour arrière** : tant que le code BILL-FA1FT est déployé, le démarrage suivant recrée ce qui a été supprimé ; pour un retour arrière durable, supprimer les objets **et** revenir au code précédent (même remarque que BILL-FC1).

**Contrôle de données à lancer en lecture seule sur une COPIE avant déploiement** (rien n'a été lancé sur des données réelles ; les tests utilisent des bases synthétiques) :
```sql
-- F_A1 : doit renvoyer 0 ligne (sinon l'index ne sera pas créé, voir ci-dessus)
SELECT client_key, group_concat(label,' | ') FROM billing_addresses GROUP BY client_key, label COLLATE NOCASE HAVING COUNT(*)>1;
-- F_T1 (information) : lignes rattachées à une facture émise mais créées après sa copie figée (doit être vide)
SELECT l.id FROM invoice_lines l JOIN invoice_snapshots s ON s.invoice_id=l.invoice_id WHERE l.created_at>s.frozen_at;
-- F_T2 (information) : lignes d'avoir dont le régime TVA ou la facture ne correspond pas à la ligne facturée (doit être vide)
SELECT cl.id FROM credit_note_lines cl JOIN credit_notes n ON n.id=cl.credit_note_id JOIN invoice_lines il ON il.id=cl.invoice_line_id WHERE il.invoice_id IS NOT n.invoice_id OR il.vat_mode IS NOT cl.vat_mode;
```

**Limites assumées** : (1) l'index NOCASE ne replie que les lettres ASCII ; le contrôle applicatif couvre le reste pour les ajouts/modifications par l'interface, pas pour un INSERT SQL direct avec accents. (2) La revue rc40 suggérait aussi de refuser un libellé propre à un client identique à un libellé de la liste globale : **non fait** (hors périmètre du test F_A1, qui porte sur la liste globale ; c'est une règle métier à décider). (3) Le correctif F_T2 est « les gardes d'insertion rejouées en UPDATE » (équivalent demandé), pas le verrou plus strict « écrit une seule fois » proposé par la revue ; un UPDATE qui respecte les trois règles reste possible par SQL direct. (4) Les nouveaux déclencheurs ne sont pas listés dans `schema_checks.rc19_problems` (seul l'index F_A1 l'est), pour ne pas faire échouer les contrôles de déploiement d'une base pas encore redémarrée.
