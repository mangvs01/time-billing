# Durée de la suite de tests — mesures et accélération (BILL-SUITE-RAPIDE, 20/11/2026, base 9.2-rc48 e779517)

**Résultat en une phrase.** La suite complète (1 220 tests) passe de **≈ 570 s à ≈ 195 s** en séquentiel → parallèle sur ce serveur (de 840 s à 200-280 s aux heures de plus forte charge), avec **exactement les mêmes 1 220 tests, les mêmes résultats, les mêmes 5 échecs attendus**, vérifié test par test (§ 5). Aucun test retiré, aucune assertion changée, aucun `sleep` raccourci.

## 1. Comment lancer

```
/root/venvs/rc25-test-venv/bin/python -I outils/run_tests_parallel.py                 # toute la suite, un processus par cœur
/root/venvs/rc25-test-venv/bin/python -I outils/run_tests_parallel.py tests.test_rc10 tests.test_import   # quelques modules
/root/venvs/rc25-test-venv/bin/python -I outils/run_tests_parallel.py --json /chemin/hors/depot/resultats.json --ref autres.json   # comparer test par test à un relevé antérieur
```
Options : `-j N` (processus, défaut = nombre de cœurs ; plus n'a rien apporté ici, § 4), `--lots K` (défaut 8 × N), `-v` (affiche la console de chaque lot), `--durations K` (les K tests les plus lents, 30 par défaut, 0 = tous), `--durable` (garde les `fsync` et les bases de départ complètes = comportement d'origine), `--list` (montre les lots sans rien lancer), `--write-weights` (réécrit `outils/run_tests_parallel_poids.json`, poids mesurés par module servant à équilibrer les lots), `--compare NOUVEAU.json --ref REF.json` (compare deux relevés sans rien lancer). Code de sortie : 0 tout OK · 1 échec / erreur / succès inattendu / lot mort ou en dépassement de délai · 2 usage erroné ou écart avec la référence.
La procédure d'origine reste valable et inchangée par défaut : `python -I outils/run_tests_isolated.py [-v] tests.test_x …`.

## 2. Ce qui a été changé (et rien d'autre)

| Fichier | Changement |
|---|---|
| `outils/run_tests_parallel.py` (nouveau) | N processus ; chacun = `run_tests_isolated.py` sur un lot de modules, avec **son propre dossier jetable** (créé et supprimé par `run_tests_isolated.py` : aucune base, fichier temporaire ni port partagé). Un module n'est jamais coupé ni rejoué ; le résultat est la somme des lots ; mêmes mots que unittest (« Ran N tests … OK (expected failures=5) »). Lots les plus lourds d'abord (poids mesurés dans `outils/run_tests_parallel_poids.json`). |
| `outils/run_tests_isolated.py` | **Deux options, désactivées par défaut** : `RC25_FAST=1` (chaque connexion SQLite fait `PRAGMA synchronous=OFF` : plus de `fsync` à chaque validation, rien d'autre ne change) et `RC25_RESULT_JSON=/chemin` (écrit un enregistrement par test : identifiant, statut, secondes). Sans ces variables le fichier se comporte comme avant (garde des connexions, dossier jetable, sortie console, code de sortie). |
| `tests/test_import.py` (`Base`) | Mode rapide seulement : l'état atteint à la fin de `Base.setUp` (copie de la base, `init()`, connexion, émetteur fictif, 2 projets) est construit **une fois par processus** par les étapes d'origine, puis **copié** (copie de fichier + même cookie de session) au lieu d'être refait 970 fois. Chaque test a sa propre copie dans son propre dossier. Sans `RC25_FAST` : les étapes d'origine, pour chaque test. Nouvelle méthode `fill_once(nom, fn)` (même principe pour un remplissage de données lourd). |
| `tests/test_rc10.py` (`ListAndExport.setUp`) | Le remplissage (122 saisies postées une à une, refait pour chacun des 6 tests) passe par `fill_once` : mêmes données, mêmes 6 tests, mêmes assertions ; en mode rapide les 5 suivants copient la base remplie. |

Rien dans `app/`, aucune assertion, aucun décorateur de test, aucun `sleep`, aucune donnée réelle, rien dans `/opt/time-billing-v9`.

## 3. Où passait le temps (mesures)

Machine : 2 cœurs, partagée avec d'autres sessions (charge moyenne 3 à 6 pendant les mesures) ; **le temps réel (« mur ») varie donc de 1 à 3 selon la charge**, le temps processeur (CPU) est la mesure stable.

1. **Les `fsync` (cause n° 1 du temps réel).** L'application ouvre SQLite avec les réglages par défaut (`synchronous=FULL`) : chaque validation attend l'écriture disque. Un seul `setUp` valide une dizaine de fois (mesuré : 10 validations par montage : réglages, 2 projets, journal d'audit…). Sur un disque occupé, c'est ce qui faisait varier la suite de 8 min à plus d'1 h 30. Mesure sur le lot 1 (307 tests) : **175 s → 71 s** rien qu'avec `synchronous=OFF` (CPU 60 s → 52 s : le temps gagné est de l'attente, pas du calcul).
2. **Les montages répétés (cause n° 1 du CPU).** 970 des 1 220 tests dérivent de `Base`. Mesuré sur 611 tests : `setUp` = **45 % du CPU** (41 s sur 92 s), dont ≈ 0,06 s CPU par test pour recopier la base, rejouer `init()` (≈ 37 ms : ≈ 60 `ensure_column`, scripts de migration, déclencheurs), se connecter, enregistrer l'émetteur et créer 2 projets par requêtes HTTP. Après modèle copié : 27 % sur les 609 autres tests (15 s sur 57 s), le reste étant des montages propres à chaque classe (mandat + factures émises), non mutualisés.
3. **Les connexions SQLite (incompressible sans toucher à l'application).** ≈ 39 connexions par test (≈ 11 800 pour 304 tests) ; chacune relit le schéma (120 objets, 27 Ko) à sa première requête : **≈ 1,4 ms** mesuré, soit ≈ 15 % du CPU. Réduire ce coût exigerait de changer l'application (une connexion par requête) : hors mission.
4. **Les PDF.** Chaque émission de facture rend et fige un PDF (`pdf_layout.render_invoice` ≈ 0,1 s CPU, 335 rendus sur 609 tests ≈ 12 % du temps profilé). reportlab 4.4.1 tourne ici **sans son accélérateur C** (`reportlab.lib._rl_accel` absent : fonctions Python pures `_py_fp_str`…) ; le paquet `rl_accel` n'est pas installé dans le venv de test. Non fait : l'installer demande le réseau (interdit) et doit être décidé aussi pour la production (même sortie PDF attendue, à vérifier).
5. **Les attentes réelles (`sleep`, sous-processus).** Seulement 4 appels `time.sleep` dans les tests (`test_gate_prototype` : 0,05 s en sondage, 1,0 s et 0,6 s ; `test_procedure_residuel` : 0,1 s), mais `test_gate_prototype` simule des courses avec `strace` (retards injectés de 1 ms à 4 s, une demi-douzaine de tests) et compile le vérificateur Go (`go build`, plusieurs secondes selon la charge) : ce module pèse ≈ 35 s de temps réel par passage, en grande partie de l'attente, pas du calcul. **Ces délais font partie de ce que les tests vérifient : ils ne sont pas raccourcis.** Ils se recouvrent désormais avec le calcul des autres lots.
6. **Gros tests isolés** : `test_rc3…test_random_sequences` (40 scénarios complets facture/avoirs, ≈ 10-20 s), `test_rc10_security…test_workbook_row_limit` (classeur de 20 001 lignes écrit puis lu par openpyxl, ≈ 5-10 s), `test_rc19…test_concurrent_start_of_two_workers…` (≈ 3-10 s). Non modifiés (leur taille est ce qui est testé).

## 4. Chiffres avant / après (même machine, enchaînés, charge moyenne 3,5 à 4,5)

| Procédure | Temps réel | CPU (user + sys) | Tests / échecs attendus |
|---|---|---|---|
| Avant : `run_tests_isolated.py`, 4 lots séquentiels (113 + 131 + 139 + 185 s) | **568 s** | 240 s | 1 220 / 5 |
| Après : `run_tests_parallel.py` (2 processus, 16 lots) | **196 s** (×2,9) | 184 s (−23 %) | 1 220 / 5 |

Autres mesures (charge différente, donc non comparables entre elles au-delà de l'ordre de grandeur) : avant, aux heures chargées : 837 s (175 + 184 + 251 + 227 ; CPU 259 s) ; après : 188, 201, 196 s (2 processus) ; 203 s (3) ; 219 s (4) → **plus de processus que de cœurs n'accélère pas** sur une machine déjà occupée (le CPU consommé augmente avec la concurrence). Première version (fsync coupés + parallèle, sans modèle copié) : 284 s ; avec modèle `Base` : 188 s. Sur une machine libre le plancher est ≈ CPU / 2 ≈ 90-100 s.

Temps par module (secondes cumulées dans leur processus ; avant = procédure d'origine, après = parallèle ; les valeurs « après » incluent la concurrence entre processus) :

| Module | Avant | Après |
|---|---|---|
| `test_rc10` | 37 | 5 |
| `test_gate_prototype` | 37 | 35 |
| `test_qr_bill_addresses` | 31 | 12 |
| `test_rc3` | 31 | 18 |
| `test_sauvegarde_rappel` | 23 | 6 |
| `test_credit_lines` | 19 | 9 |
| `test_bmdp1_mot_de_passe` | 19 | 11 |
| `test_invoice_lines` | 18 | 5 |
| `test_qr_bill_option` | 17 | 7 |
| `test_qr_rappel` | 14 | 2 |

Médiane par test : 0,25 s → 0,15 s.

### Les 30 tests les plus lents avant, et leur durée après (secondes)

| # | Test | Avant | Après |
|---|---|---|---|
| 1 | `test_rc3.CumulativeRounding.test_random_sequences` | 21.2 | 10.7 |
| 2 | `test_gate_prototype.GatePrototype.test_file_growing_during_read_is_cut_at_the_limit_not_loaded_in_memory` | 16.3 | 12.3 |
| 3 | `test_rc10.ListAndExport.test_list_html_escapes_descriptions` | 8.8 | 0.0 |
| 4 | `test_qr_bill_option.Ticked.test_issued_invoice_never_changes` | 5.6 | 1.1 |
| 5 | `test_rc10_security.Inputs.test_workbook_row_limit` | 4.9 | 10.3 |
| 6 | `test_qr_bill_addresses.Entry.test_pure_validators` | 4.5 | 0.1 |
| 7 | `test_qr_bill_exception.ExceptionMandate.test_ticked_with_the_client_address_not_verified_blocks_on_stc_gem` | 4.5 | 1.1 |
| 8 | `test_rc10.ListAndExport.test_pagination_and_totals` | 4.2 | 0.1 |
| 9 | `test_sauvegarde_rappel.Popup.test_markup_is_accessible_and_csp_friendly` | 4.0 | 0.4 |
| 10 | `test_sauvegarde_rappel.Popup.test_dashboard_todo_no_longer_has_the_advice_line` | 4.0 | 0.6 |
| 11 | `test_rc10.ListAndExport.test_filters` | 4.0 | 0.1 |
| 12 | `test_rc10.ListAndExport.test_like_wildcards_are_literal` | 3.8 | 0.0 |
| 13 | `test_rc10.ListAndExport.test_csv_export_matches_the_filter_and_neutralises_formulas` | 3.3 | 1.1 |
| 14 | `test_invoice_lines.LinesRestore.test_manual_lines_survive_a_json_backup_and_restore` | 3.2 | 0.3 |
| 15 | `test_rc10.ListAndExport.test_dashboard_and_time_tabs_offer_the_same_actions` | 3.2 | 0.1 |
| 16 | `test_gate_prototype.GatePrototype.test_trusted_key_replaced_between_check_and_open_is_refused` | 3.1 | 3.3 |
| 17 | `test_qr_bill_addresses.Entry.test_qrr_reference` | 3.1 | 0.1 |
| 18 | `test_gate_prototype.GatePrototype.test_source_file_replaced_by_identical_content_between_check_and_open_is_refused` | 3.1 | 3.1 |
| 19 | `test_gate_prototype.GatePrototype.test_trusted_key_chowned_between_check_and_open_is_refused` | 3.1 | 3.1 |
| 20 | `test_gate_prototype.GatePrototype.test_trusted_key_made_writable_between_check_and_open_is_refused` | 3.1 | 3.3 |
| 21 | `test_gate_prototype.GatePrototype.test_source_file_swapped_for_a_symlink_between_check_and_open_is_refused` | 3.0 | 3.1 |
| 22 | `test_credit_lines.CreditOnLines.test_credited_lines_survive_a_json_backup_and_restore` | 3.0 | 0.4 |
| 23 | `test_rc19.Robustness.test_concurrent_start_of_two_workers_migrates_once_and_leaves_working_triggers` | 2.7 | 3.5 |
| 24 | `test_qr_bill_addresses.Entry.test_settings_screen_saves_issuer_address_and_qr_iban` | 2.6 | 0.4 |
| 25 | `test_rc4.ScreenFormat.test_french_numbers_on_screen` | 2.4 | 1.2 |
| 26 | `test_sauvegarde_rappel.Popup.test_viewing_the_dashboard_writes_nothing_and_wrong_password_never_arms_it` | 2.3 | 0.6 |
| 27 | `test_qr_bill_exception.ExceptionMandate.test_unticked_keeps_every_rc41_warning_and_issues_without_reason` | 2.2 | 0.6 |
| 28 | `test_sauvegarde_rappel.Popup.test_not_shown_when_the_backup_is_recent_and_nothing_is_written` | 2.2 | 0.5 |
| 29 | `test_procedure_adverse.Adverse.test_with_dash_p_inherited_functions_are_ignored_and_the_guard_still_decides` | 2.2 | 4.1 |
| 30 | `test_functional.ArchiveAndBackup.test_archive_lists_all_invoices` | 2.2 | 0.8 |

Lecture : les tests de `test_rc10.ListAndExport` ne paient plus leur remplissage (le premier de la classe le construit : ≈ 5 s, une fois) ; les écarts de ±1 s sur les tests restants sont du bruit de charge. Les tests `test_gate_prototype` (délais `strace` voulus) et les 3 gros tests du § 3.6 restent en tête.

## 5. Ce qui garantit « mêmes tests, mêmes résultats »

- Relevé test par test (`RC25_RESULT_JSON`) de la procédure d'origine (4 lots, sans mode rapide) : 1 220 tests = 1 215 `ok` + 5 `expected failure`. Relevé du mode parallèle : mêmes 1 220 identifiants, mêmes statuts, **0 écart, 0 test en plus, 0 en moins** (`--ref`, « same test ids = 1220, different status = 0 »). Quatre autres passages parallèles (2, 3 et 4 processus), comparés au premier : toujours 0 écart.
- Les 5 échecs attendus restent les 5 limites du shell de `docs/TESTS-ATTENDUS.md` § B (1 220 = 1 215 + 5 dans les deux modes).
- `--durable` rejoue les étapes d'origine (fsync actifs, base de départ reconstruite pour chaque test) : testé sur 3 modules.
- Un lot qui meurt, ne rend pas son relevé ou dépasse 3 300 s fait sortir l'outil en code 1 (vérifié avec un interpréteur factice).

## 6. Précautions et limites

- **Durabilité** : en mode rapide les bases jetables ne sont pas protégées contre une coupure de courant (sans objet : elles sont supprimées en fin de test). Verrous, transactions, SQL, ordre des écritures : inchangés. Aucun test ne lit `PRAGMA synchronous`/`journal_mode`.
- **Modèle `Base` copié** : valable tant que `Base.setUp` ne dépend que de ce qui compose la clé (base de départ, identifiants, émetteur fictif, méthode `project` de la classe). Une sous-classe qui changerait autre chose (variable d'environnement, constante du module) *avant* d'appeler `super().setUp()` obtiendrait le modèle construit sans ce changement : aucune sous-classe actuelle ne le fait (suite identique) ; en cas de doute, lancer cette classe avec `run_tests_isolated.py` (sans `RC25_FAST`). L'horodatage de la session et des lignes d'audit du `setUp` est celui de la construction du modèle (au plus quelques minutes plus tôt ; la durée de vie d'une session est de 24 h).
- **Poids des lots** : `outils/run_tests_parallel_poids.json` est une mesure de ce jour ; un module absent du fichier est estimé d'après la taille de son fichier. L'équilibre des lots n'affecte que la durée, jamais le résultat. À réécrire de temps en temps (`--write-weights`).
- **Charge du serveur** : les temps réels de ce document dépendent des autres sessions ; comparer deux versions avec `--json`/`--ref` plutôt qu'avec l'horloge.
- **Pistes non faites** (à décider) : (1) installer `rl_accel` dans le venv de test et de production (PDF plus rapides ; réseau) ; (2) mutualiser les montages de classe restants (≈ 27 % du CPU) comme `ListAndExport` ; (3) un cache de compilation pour `go build` (`test_gate_prototype`) ; (4) une seule connexion SQLite par requête dans l'application (≈ 15 % du CPU des tests, mais c'est un changement applicatif).
