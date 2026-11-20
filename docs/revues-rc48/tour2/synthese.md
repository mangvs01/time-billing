# Synthèse du tour 2 de la revue de 9.2-rc48 (BILL-REVUE-RC48B)

Périmètre : `048f6a9..1940682` (corrections A, C, D, F, G) puis `2382090..1940682`. Deux relecteurs indépendants en lecture seule (opus : `avis-opus.md` ; sonnet : `avis-sonnet.md`), même brief, sans connaissance l'un de l'autre. Aucun code modifié, aucune base de production consultée ; `git status` propre avant et après.

## Verdict
Les deux relecteurs : **GO conditionnel**. Aucun défaut bloquant dans le code de l'application. Condition principale nouvelle : **l'outil `outils/retour_rc47.py json` peut migrer la base de production** (N-1 ci-dessous) ; à corriger (3 lignes) ou à interdire dans la procédure avant la mise en ligne. Puis les vérifications sur copie.

Contrôle personnel : confirmé dans le code `app/app.py:331` (`init()` à l'import) et `outils/retour_rc47.py:93` (`setdefault("DB_PATH", …)`). Les reproductions (bases jetables /tmp) sont celles des relecteurs, non rejouées par moi ; sonnet a rejoué `repeter_migration_rc48.py` (50 vérifications, 0 échec). La suite de tests complète n'a été lancée par personne dans ce tour.

## Chaque constat du 1er tour est-il corrigé ?

| # | Constat | Avis des 2 relecteurs | Décision |
|---|---|---|---|
| A | adresse jumelle non modifiable | Corrigé pour le cas courant (reproduit) ; **résidu** : ancien libellé à espaces non normalisés (« Egg␣␣BE » + « egg be ») encore refusé, message peu clair (opus 2, sonnet N3, reproduit par les deux) | **Partiel → retenu comme N-2** (petit correctif + test) |
| B | doublons en production | Documenté, non corrigé par le code ; outil `controle_copie_rc48.py` en lecture seule vérifié | **Accepté** (conditionné aux vérifs 1–3 sur copie) |
| C | JSON rc48 non restaurable sous rc47 | Contourné par l'outil `json` ; **mais** l'outil est dangereux (N-1) et le retour `base` laisse des avoirs que le JSON rc47 refuserait (N-3) | **Partiel → N-1 et N-3** |
| D | rc47 ne démarre plus sur base rc48 | Corrigé : `retour_rc47.py base` reproduit/validé ; `make_global` rc48 insensible à la casse | **Corrigé** |
| E | ordre de restauration des avoirs | Non corrigé (défaut rc47), message traduit ; contrôle 6 de l'outil | **Écarté pour rc48** (lot séparé), à vérifier sur copie |
| F | contrôle de schéma | Corrigé (nom, table, texte des 6 objets) ; tests présents mais non rejoués | **Corrigé** |
| G | messages anglais bruts | Corrigé pour les gardes SQL (44 messages traduits, repli générique) ; **résidus** dans la restauration (N-4) | **Corrigé, résidus mineurs → N-4** |
| H | plafond au-delà de 9×10⁸ | Accepté | **Accepté** (vérif. 5b) |

## Nouveaux constats retenus

| # | Constat | Source | Gravité | Suite |
|---|---|---|---|---|
| N-1 | `retour_rc47.py json` importe `app.app`, qui exécute `init()` sur `DB_PATH` : si le shell porte la variable de production, l'outil **remigre la base de production en rc48** (même quand le fichier est refusé) et défait le retour `base`. Reproduit sur base jetable par les deux. Le test ne contrôle pas `DB_PATH`. | opus 1, sonnet N2 | **Importante (bloque la procédure de retour)** | À corriger avant mise en ligne : affecter `DB_PATH` (pas `setdefault`) vers un fichier jetable avant l'import, + test « base rc47 pointée par `DB_PATH` reste intacte ». À défaut : retirer le mode `json` de la procédure. |
| N-2 | Résidu du constat A (libellé stocké à espaces multiples) | opus 2, sonnet N3 | Moyenne, dépend des données (vérif. 3) | Comparer le libellé stocké normalisé au nouveau ; test. |
| N-3 | Après `retour_rc47.py base`, des avoirs 0,23 sur 0,225 restent ; tout JSON fait ensuite sous rc47 n'est plus restaurable (même par rc47). Les notes ne couvrent que les JSON rc48. | sonnet N1 (reproduit), opus 3 (déduit) | Moyenne (seulement si de tels avoirs existent) | Compter ces avoirs dans l'outil `base` (simulation et exécution) ; écrire dans les notes « tant qu'ils existent, ne restaurer que le fichier SQLite » et prévoir la copie du fichier SQLite dans la procédure. |
| N-4 | Messages de restauration encore techniques : identifiant interne « (client NOM:bsci) », `ValueError`, `meta.row_counts…` ; la phrase « restaurer le fichier SQLite » est ajoutée à toute erreur de base (y compris « base occupée »), et `readonly`/`malformed`/`no such table` donnent « a refusé cette écriture ». | sonnet N4 seul (reproduit en partie, lu) | Mineure | À traiter avec le lot E (restauration). Non bloquant. |
| N-5 | Le contrôle 2 de l'outil de copie sur-signale (NFC/NFD, espaces) ; faux positifs sans danger. | sonnet N5 | Information | Le dire dans `VERIFS-COPIE-PROD.md` pour éviter des renommages inutiles. |
| N-6 | Le contrôle 4 (cas D) ne regarde que la paire `'*'`/`NOM:bsci`. | opus 4 | Mineure | Confirmer sur la copie qu'aucune autre paire de clés n'a des libellés jumeaux (requête 1 sur toutes les clés). |

**Écarté** : l'erreur d'import de `tests/test_bill_rc48_fix.py` signalée par opus — probablement l'environnement du relecteur (pytest absent du venv), non investiguée ; à rejouer par la suite normale (`outils/run_tests_parallel.py`) avant mise en ligne, ce qui reste une condition.

## Décisions à faire valider
1. N-1 : corriger l'outil (recommandé, petit) avant mise en ligne ? Sinon interdire le mode `json` dans la procédure.
2. N-2 / N-3 : petit correctif A + comptage des avoirs dans `base`, ou simple documentation ?
3. Les décisions du tour 1 restent valables (B : pré-renommer les doublons éventuels ; E : lot séparé).

## Vérifications à faire sur une COPIE de la base de production avant la mise en ligne
(Aucun accès de ma part. Lecture seule : `sqlite3 -readonly` ou `file:copie.db?mode=ro`. L'outil `python3 -I outils/controle_copie_rc48.py COPIE.db` couvre les contrôles 1 à 8b ; détail des requêtes dans les deux avis.)

**Données existantes (lecture seule)**
1. `python3 -I outils/controle_copie_rc48.py COPIE.db` : aucun « À TRAITER » (les faux positifs NFC/NFD et espaces sont connus, N-5).
2. Doublons d'adresse à la casse près, **toutes clés confondues, `'*'` compris** : `SELECT client_key, group_concat(id||':'||label,' | '), COUNT(*) FROM billing_addresses GROUP BY client_key, label COLLATE NOCASE HAVING COUNT(*)>1;` (A, B, D, N-6).
3. Libellés à espaces non normalisés ayant un jumeau (N-2) : requête dans `avis-opus.md` ; plus doublons Unicode (`casefold`) en Python `-I`.
4. Cas D : même libellé à la casse près entre `'*'` et `NOM:bsci`.
5. Avoirs à demi-centime déjà posés ; lignes > 9×10⁸ ; avoirs dépassant le plafond rc47 (requête 5 de `avis-sonnet.md`) → N-3, H.
6. Lignes créditées puis annulées puis recréditées → E.
7. Cohérence avoirs/lignes ; `PRAGMA integrity_check; PRAGMA foreign_key_check; PRAGMA journal_mode` avant et après.

**Migration aller (copie jetable, code rc48)**
8. Démarrage rc48 : 6 objets présents (`idx_billing_addresses_label_nocase` + 5 déclencheurs), `credit_lines_within_line` à la nouvelle formule, 0 audit `billing_address_label_index_skipped`, `rc19_problems()==[]`.
9. `outils/empreinte_metier.py comparer avant après` identique ; `outils/repeter_migration_rc48.py` ; `30-rehearse.sh`, `50-verify.sh`, `verifier-sauvegarde.sh` sur la copie (GO attendu ; hors de cette session, Docker).
10. Suite de tests complète (`outils/run_tests_parallel.py`) verte, dont `tests/test_bill_rc48_fix.py`.

**Retour arrière et restauration (instances jetables uniquement)**
11. `retour_rc47.py base` (simulation puis exécution) sur la copie migrée, démarrage du code rc47, code de sortie 0 (D).
12. Retour B complet de la procédure, comparaison schéma/données à rc47.
13. **Avant de tester l'outil `json` : corriger N-1**, et le lancer dans un shell SANS variables de production, `DB_PATH` jetable ; vérifier ensuite que la copie de départ n'a pas changé (empreinte).
14. Avoir total 0,23 sur ligne 1,5×0,15 sur la copie → export JSON sous rc48 → restauration sous rc47 (C/N-3) ; export JSON sous rc47 après retour `base` → restauration rc47.
15. Export JSON de la copie → restauration rc47 puis rc48 pour confirmer ou écarter E.
