# Avis du relecteur « opus » — tour 2 de la revue de 9.2-rc48 (BILL-REVUE-RC48B)

Périmètre : `048f6a9..1940682`, puis `2382090..1940682`. Lecture seule ; essais sur bases jetables dans /tmp. Avis recopié tel que rendu par le sous-agent (sans connaissance de l'avis de sonnet).

**Verdict : GO conditionnel.** Les corrections A, C, D, F et G tiennent dans l'ensemble. Un nouveau défaut grave touche l'outil de retour arrière (constat 1) : il doit être corrigé, ou son mode `json` interdit dans la procédure, avant la mise en ligne. Les vérifications sur une copie de la production restent nécessaires.

## Constats du 1er tour → corrigé ?

| Constat | Corrigé ? | Preuve |
|---|---|---|
| A – adresse avec un « jumeau » (même nom à une majuscule près) non modifiable | **En partie** | Lu dans le code : seul un vrai changement de nom est contrôlé (`rename_conflict`). **Reste un cas non couvert (constat 2, reproduit).** |
| B – doublons déjà présents en production | Documenté, non corrigé (accepté) | Notes, `VERIFS-COPIE-PROD.md` et `outils/controle_copie_rc48.py`. Le contrôle 2 de l'outil peut signaler plus de cas que l'application n'en refuse (il normalise aussi les accents), ce qui est prudent. |
| C – sauvegarde JSON rc48 non restaurable sous rc47 | Contourné (outil `json` et documentation) | Lu dans le code et dans les tests. **Mais l'outil `json` est dangereux (constat 1).** Il manque aussi un cas dans les notes (constat 3). |
| D – rc47 refuse de démarrer sur une base rc48 dans certains cas | Contourné (`retour_rc47.py base`) | Reproduit : simulation, puis retrait des 6 objets rc48, copie de sécurité, ligne au journal ; le schéma revient à rc47. |
| E – ordre de restauration des avoirs | Non corrigé ; défaut déjà présent en rc47, lot séparé | Le message est maintenant traduit (lu dans le code). Le contrôle 6 de l'outil le détecte. |
| F – contrôle de schéma incomplet | Corrigé | Lu dans le code : nom, table et texte des 6 déclencheurs comparés. Tests ciblés présents ; non lancés (voir la fin). |
| G – messages en anglais brut | Corrigé | Lu dans le code : traduction par texte exact, sinon phrase générique, jamais le texte brut. |
| H – plafond faux au-delà d'environ 9×10⁸ CHF par ligne | Accepté | Contrôle 5b sur la copie. |

## Nouveaux constats

**1. Grave : `outils/retour_rc47.py json` remigre la base de production vers rc48, même quand le fichier est refusé.** Confirmé par essai.
- Cause : `import app.app` exécute `init()` dès le chargement du module (`app/app.py:331`), sur `DB_PATH`. L'outil se contente de `os.environ.setdefault("DB_PATH", …)` (`outils/retour_rc47.py:93`). Si l'outil tourne dans l'environnement de l'application, où `DB_PATH` pointe vers la vraie base, il réinstalle l'index et les 5 déclencheurs rc48 sur cette base.
- Conséquence : pendant un retour arrière, l'outil défait en silence le retour fait avec `base --oui`, alors que rc47 tourne. Le constat D peut réapparaître au redémarrage suivant de rc47.
- Reproduction (dans /tmp) : (1) `retour_rc47.py base prod.db --oui` : objets rc48 retirés ; (2) `env DB_PATH=/tmp/rv2/prod.db … retour_rc47.py json b.json out.db` : « Sauvegarde refusée », code 1 ; (3) `prod.db` contient de nouveau `idx_billing_addresses_label_nocase` et les 5 déclencheurs ; (4) avec un `DB_PATH` inexistant, la base est même créée.
- Le test ne le voit pas : `tool()` lance l'outil avec l'environnement du test sans contrôler `DB_PATH`.
- Correctif suggéré : forcer `os.environ["DB_PATH"]` vers un fichier jetable (affectation, pas `setdefault`) avant l'import, ou importer `init` sans charger `app.app`. Ajouter un test : `DB_PATH` pointé sur une base rc47 doit rester intacte.

**2. Moyen : le constat A n'est corrigé qu'en partie.** Confirmé par essai.
- Cas : un ancien nom contient des espaces non normalisés et a un jumeau (« EGG␣␣FR » à côté de « egg fr », ou « Zürich␣ » à côté de « ZÜRICH »).
- Effet : modifier seulement le contact ou le texte est refusé (« choisir un autre nom »). `validate()` normalise les espaces, donc `new_label != a["label"]`. rc47 acceptait.
- Correctif suggéré : comparer avec l'ancien nom passé par la même normalisation (ou après `casefold`), et ajouter un test.
- Gravité : dépend des données réelles (contrôles 1, 2 et 3 sur la copie).

**3. Mineur : constat C après un retour par `base --oui`** (déduit du mécanisme, non reproduit). Une base revenue à rc47 garde les avoirs de 0,23 sur les lignes de 0,225 ; toute sauvegarde JSON faite ensuite sous rc47 sera refusée par la restauration de rc47. Les notes ne parlent que des « JSON faites sous rc48 ». À écrire ; utiliser le fichier SQLite ou l'outil `json` une fois le constat 1 corrigé.

**4. Mineur : le contrôle 4 ne regarde qu'une paire de clients** (`'*'` / `'NOM:bsci'`) (lu dans le code). À confirmer que le déplacement d'adresses de rc47 ne touche que cette paire.

## Vérifications sur une COPIE de la base de production (lecture seule, `file:copie.db?mode=ro`)
- `python3 -I outils/controle_copie_rc48.py copie.db` (contrôles 1 à 8b). Attendu : aucun « À TRAITER », ou la liste exacte des adresses à renommer sous rc47.
- Constat 2 :
  `SELECT a.id, '['||a.label||']', b.id, b.label FROM billing_addresses a JOIN billing_addresses b ON a.client_key=b.client_key AND a.id<>b.id WHERE (a.label<>trim(a.label) OR a.label LIKE '%  %') AND lower(trim(replace(a.label,'  ',' ')))=lower(b.label);` → aucune ligne attendue. Faire aussi le regroupement en Python avec `casefold()`.
- Avoirs à demi-centime déjà posés (constat 3) :
  `SELECT l.id FROM credit_note_lines l JOIN invoice_lines il ON il.id=l.invoice_line_id WHERE (CAST(ROUND(il.qty*1000000) AS INTEGER)*CAST(ROUND(il.unit_rate*10000) AS INTEGER)) % 100000000 = 50000000;`
- `PRAGMA integrity_check; PRAGMA foreign_key_check;` avant et après la migration.
- Après migration : `SELECT name FROM sqlite_master WHERE name IN ('idx_billing_addresses_label_nocase','credit_line_upd_no_move_frozen','credit_line_upd_same_invoice','credit_line_upd_same_vat_mode','credit_line_upd_within_line','invoice_line_no_move_to_issued');` → 6 lignes ; `SELECT COUNT(*) FROM audit WHERE event='billing_address_label_index_skipped';` → 0.
- Instance jetable : `retour_rc47.py base` puis démarrage de rc47. Ne lancer l'outil `json` qu'une fois le constat 1 corrigé, avec un `DB_PATH` jetable.

## Ce que le relecteur n'a pas pu vérifier
- La suite de tests et `tests/test_bill_rc48_fix.py` (sorti en erreur dès l'import, cause non examinée ; pytest absent du venv).
- Le démarrage réel du code rc47 et `outils/repeter_migration_rc48.py` (non rejoués).
- Les scripts `procedure/*` (Docker, interdit).
- Aucune base de production consultée.

Fichiers d'essai du relecteur : `/tmp/rv2` (hors dépôt).

> Note de l'agent principal : « tests/test_bill_rc48_fix.py en erreur dès l'import » est un symptôme probable de l'environnement du relecteur (pytest absent) ; non investigué, à rejouer par la suite normale (`outils/run_tests_parallel.py`).
