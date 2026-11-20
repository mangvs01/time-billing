# Avis du relecteur « sonnet » — tour 2 de la revue de 9.2-rc48 (BILL-REVUE-RC48B)

Périmètre : `048f6a9..1940682`, puis `2382090..1940682`. Lecture seule ; essais sur bases jetables dans /tmp. Avis recopié tel que rendu par le sous-agent (sans connaissance de l'avis d'opus). Légende : **[R]** reproduit, **[L]** lu dans le code, **[S]** supposé.

## Verdict : GO conditionnel
Aucun défaut bloquant dans le code. La migration aller et l'outil de retour fonctionnent. Trois conditions avant mise en ligne :
- passer les contrôles sur une copie de la base de production ;
- corriger ou documenter N1 et N2 ;
- vérifier que `retour_rc47.py json` n'est jamais lancé depuis un shell portant les variables de production (N2).

`outils/repeter_migration_rc48.py` rejoué : 50 vérifications, 0 échec **[R]**. Suite de tests complète non relancée.

## Constats du 1er tour (A–H)

| # | Corrigé ? | Preuve |
|---|---|---|
| A | **Oui, résidu mineur (N3)** | [R] `egg fr` / `EGG FR`, puis `Zürich` / `ZÜRICH` : changer le contact sans toucher au libellé est accepté. Renommer vers un jumeau (`Egg Fr` → `egg fr`) est refusé avec un message en français. Renommage ordinaire OK. |
| B | **Documenté, pas corrigé par le code** (acceptable) | [L] `RC48-NOTES.md` et `VERIFS-COPIE-PROD.md`. [R] `controle_copie_rc48.py` détecte doublons ASCII, Unicode et à espaces ; copie inchangée octet pour octet (sha256), code de sortie 1. Conditionné aux requêtes 1 et 2 sur la copie. |
| C | **En partie** | [R] `retour_rc47.py json` produit un SQLite que rc47 accepte. [R] Le retour par `base` laisse l'avoir à 0,23 en place → N1. |
| D | **Oui** | [R] Défaut reproduit, puis corrigé par l'outil `base` (section 7 de la répétition). [L] `make_global` de rc48 compare sans tenir compte de la casse. |
| E | **Non corrigé, documenté** (lot séparé) | [L] Contrôle 6 prévu. Non rejoué. |
| F | **Oui** | [L] `schema_checks.py` compare nom, table et texte SQL normalisé. Tests 108 à 123 présents, non rejoués. |
| G | **Oui pour les gardes SQL, résidus mineurs (N4)** | [R] Les 44 messages `RAISE` de `app/**` ont une traduction, sans collision de sous-chaîne. Texte inconnu → phrase générique. |
| H | **Accepté** | [L] `MAX_AMOUNT` = 10⁹. Contrôle 5b sur la copie. |

## Nouveaux constats

**N1 (moyenne). Le retour `base` laisse des avoirs de 0,23 sur 0,225 ; les JSON faits ensuite par rc47 ne sont plus restaurables, même par rc47.**
- [R] Base rc47 migrée en rc48, avoir 0,23 sur ligne 1,5 × 0,15, puis `retour_rc47.py base --oui` : rc47 démarre, son export JSON réussit, mais la reconstruction de ce JSON par rc47 échoue (`IntegrityError: The credits of an invoice line cannot exceed its amount`).
- Les notes ne couvrent que les JSON faits sous rc48. Seul filet : le fichier SQLite, que la procédure de retour n'écrit pas.
- Correctif suggéré : l'outil `base` compte (simulation comme exécution) les lignes d'avoir dépassant le plafond rc47 ; phrase dans les notes : « tant que ces avoirs existent, ne restaurer que le fichier SQLite ».

**N2 (moyenne). `retour_rc47.py json` ouvre et migre la base désignée par `DB_PATH`, contrairement à son commentaire (« jamais ouvert »).**
- [L] `app/app.py:331` exécute `init()` à l'import ; l'outil utilise `os.environ.setdefault("DB_PATH", …)` (`outils/retour_rc47.py:93`).
- [R] Avec `DB_PATH=/tmp/rv/w/ghost-prod.db`, l'outil crée et initialise ce fichier (62 déclencheurs). Sans `DB_PATH`, il crée `/tmp/retour-rc47-inutilise.db` (nom fixe, dossier partagé).
- [S] Depuis un shell portant `DB_PATH` de production, l'outil migrerait la base de production en rc48 en plein retour arrière (non testé sur base réelle).
- Correctif suggéré : affectation directe de `DB_PATH` vers un fichier du dossier jetable, ou refus si `DB_PATH` déjà défini ; test vérifiant qu'aucun fichier hors sortie n'est créé (le test `test_bill_rc48_fix.py:224` ne regarde que le dossier de sortie).

**N3 (mineure). Résidu de A avec un libellé stocké à espaces multiples.** [R] `Egg  BE` (deux espaces) et `egg be` : modifier seulement le contact de `Egg  BE` est refusé ; `validate()` normalise l'espace, le libellé « change ». Le message cite « Egg BE » et « egg be », que l'utilisateur ne voit pas comme modifié. Correctif : comparer le libellé normalisé de la valeur stockée avec la nouvelle.

**N4 (mineure). Jargon et incohérences dans certains messages.**
- [L] Message de conflit à la restauration : identifiant interne `(client NOM:bsci)`.
- [L] `RestoreRefused` garde des textes hérités : `fichier JSON illisible (ValueError)`, `meta.row_counts absent…`.
- [L] `restore_refusal_text` ajoute « Ce fichier n'est pas utilisable… restaurer le fichier SQLite » à toute `DatabaseError` (contredit « base occupée, réessayer », inadapté à une base corrompue).
- [R] Les erreurs `readonly`, `malformed`, `no such table` donnent « a refusé cette écriture », trompeur.
- Correctif : traduire ces cas à part ; n'ajouter la phrase SQLite que pour les gardes connues.

**N5 (information). Le contrôle 2 de `controle_copie_rc48.py` sur-signale.** [R] Il marque « À TRAITER » `Café` NFC/NFD et `Egg  BE`/`egg be`, alors que `label_twin` de rc48 ne normalise pas en NFC (donc ne refuserait pas la paire NFC/NFD). Faux positif sans danger ; à dire dans la procédure pour éviter des renommages inutiles.

## Vérifications sur une COPIE de la base de production (lecture seule)
Tout est dans `outils/controle_copie_rc48.py COPIE.db` (ouvre en `mode=ro`, vérifié sans effet sur le fichier [R]).
1. Doublons d'adresse à la casse près, **toutes clés confondues, y compris `'*'`** : `SELECT client_key, group_concat(id||':'||label,' | '), COUNT(*) FROM billing_addresses GROUP BY client_key, label COLLATE NOCASE HAVING COUNT(*)>1;` (peut venir de l'ancien `make_global` de rc47 qui déplaçait `EGG FR` vers `'*'` même si `egg fr` y était).
2. Doublons Unicode et à espaces (script `unicode_twins` de l'outil), plus la requête 3 (espaces doubles/en bordure).
3. Cas D : même libellé à la casse près entre `'*'` et `NOM:bsci`.
4. Demi-centime déjà crédité (5a), lignes > 9×10⁸ (5b), recréditées après annulation (6), cohérence avoirs/lignes (7).
5. Nouveau (N1) : `SELECT il.id FROM credit_note_lines l JOIN invoice_lines il ON il.id=l.invoice_line_id GROUP BY il.id HAVING SUM(l.amount) > ROUND(il.qty*il.unit_rate,2);` — avoirs que le plafond rc47 refuserait à une reconstruction JSON.
6. `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, `PRAGMA journal_mode`.
7. Sur copie neuve (hors lecture seule) : démarrage rc48, 6 objets présents, empreinte métier identique, `rc19_problems() == []` ; puis `retour_rc47.py base`, démarrage rc47, export puis restauration JSON sous rc47 (N1).

## Ce que le relecteur n'a pas pu vérifier
- Données de production ; `30-rehearse.sh`, `50-verify.sh`, `verifier-sauvegarde.sh` (Docker interdit).
- Suite complète (1262 tests) ; constats E et H non reproduits.
- Retour `base` sur base en mode WAL ou application active.
- Rendu dans de vrais navigateurs (messages lus via le client de test Flask).

Fichiers d'essai du relecteur : `/tmp/rv/` (hors dépôt).
