# Avis indépendant — modèle sonnet — revue de 9.2-rc48

Mission BILL-REVUE-RC48. Revue en lecture seule de `git diff 2382090..e779517`, menée par un sous-agent (modèle sonnet) qui n'a pas vu l'avis du modèle opus. Texte ci-dessous = rapport du sous-agent, reproduit tel quel (aucune correction de fond). Ses essais ont tourné sur des bases jetables sous `/tmp/rev48`.

---

# Revue indépendante rc48 (`git diff 2382090..e779517`), lecture seule

## Résumé et verdict

**GO conditionnel.** Je n'ai trouvé aucun défaut bloquant dans le code. La migration aller est sûre, idempotente et additive. Le retour arrière B est exact, y compris pour le texte SQL des déclencheurs. Aucun code de l'application n'écrit les colonnes protégées par les 5 nouveaux déclencheurs, donc ils ne peuvent pas bloquer l'interface.

Le GO dépend du résultat des requêtes de la dernière section, à passer sur une copie de la production. Trois constats « important » (1, 2, 3) n'existent que si les données réelles contiennent des adresses en double ou la configuration décrite au constat 3. Le constat 4 existe déjà en rc47 et n'est pas une régression.

**Comment j'ai vérifié :** lecture du diff, puis expériences sur des bases jetables sous `/tmp/rev48` (rc47 extrait par `git archive`, venv `/root/venvs/rc25-test-venv`). Je n'ai pas relancé la suite de tests de 1220 tests. Le chiffre « 1220 OK » des notes reste une affirmation de l'auteur que je n'ai pas contrôlée.

## Constats

### 1. Important (conditionnel) : modifier le contact ou l'adresse d'une adresse déjà en doublon devient impossible
- **Preuve :** `app/address_service.py:51-54` (`label_taken`), appelé à `app/app.py:857`. Le formulaire renvoie toujours le libellé. `label_taken` exclut seulement l'identifiant lui-même, pas son jumeau.
- **Scénario :** deux adresses d'un même client, « Basel » et « BASEL », ont été créées sous rc47. L'index est alors ignoré, et seule une note d'audit le signale. L'utilisateur corrige le texte de l'adresse « Basel » sans toucher au libellé. Il reçoit « Adresse non modifiée : une adresse « Basel » existe déjà pour ce client (à la casse près) ». Il est donc bloqué, alors que rc47 le laissait faire.
- **Cas Unicode :** « Zürich » et « ZÜRICH » ne sont pas vus comme doublons par NOCASE (ASCII seulement), donc l'index est créé. Mais `casefold` les voit, et `label_taken` bloque la même modification.
- **Vérifié par expérience :** `label_taken(c,'K','Zürich',1)` renvoie True, et `label_taken(c,'K','Basel',5)` aussi.
- **Correctif suggéré :** ne refuser que si le libellé change réellement par rapport à celui déjà enregistré, et ne tester le jumeau que dans ce cas.

### 2. Important (conditionnel) : une sauvegarde de la base qui contient des doublons devient non restaurable
- **Preuve :** `app/restore_service.py:213-221`, appelé à `restore_service.py:136`. L'aperçu bloque avec « à corriger dans le fichier ».
- **Scénario :** la base de production contient des doublons ASCII, l'index est ignoré et l'application fonctionne. L'export JSON de cette base contient les doublons. La restauration est refusée, et l'utilisateur ne peut pas corriger un fichier JSON. Il n'y a ni contournement ni message d'action.
- **Autre point :** `rebuild()` recrée toujours l'index, ce qui crée cette asymétrie entre la base vivante et la base restaurée.
- **Correctif suggéré :** soit tolérer les doublons existants à la restauration (ne pas créer l'index dans la base reconstruite), soit proposer une correction guidée.

### 3. Important (conditionnel, improbable) : rc47 peut refuser de démarrer sur une base rc48, contrairement à ce que dit le retour arrière A
- **Preuve :** le `make_global` de rc47 utilise un `NOT EXISTS` comparé en binaire, alors que l'index NOCASE reste dans la base migrée.
- **Scénario reproduit :** sur une base migrée en rc48, l'adresse `'*'/'egg fr'` et l'adresse `'NOM:bsci'/'EGG FR'` coexistent (clients différents, donc autorisées). Le démarrage de rc47 échoue avec `IntegrityError: UNIQUE constraint failed: billing_addresses.client_key, billing_addresses.label`. rc48 démarre sans erreur sur la même base.
- **Impact :** il contredit « rc47 démarre sans erreur » de `docs/RC48-NOTES.md` pour ce cas. Il suppose qu'un client `NOM:bsci` porte un libellé du jeu semé avec une casse différente de l'entrée globale.
- **Correctif suggéré :** vérifier ce cas sur la copie de production (requête 3 ci-dessous). Le cas échéant, retirer l'index avant de remettre rc47, ou l'écrire dans la procédure de retour A.

### 4. Important, **déjà présent en rc47**, non régression : la restauration peut échouer pour un avoir annulé puis remplacé
- **Preuve :** `restore_service.py:17-18` insère `credit_note_lines` avant `credit_note_cancellations`. Le déclencheur du plafond exclut les lignes des notes annulées, mais pendant la reconstruction l'annulation n'existe pas encore.
- **Scénario :**
  - Une ligne de 100 est créditée par la note A (100), puis A est annulée.
  - La note B remplace A et recrédite 100. C'est le flux `replaceable`.
  - Sur la base vivante, l'ordre A, annulation, B est accepté (vérifié).
  - Dans l'ordre de restauration (A, B, puis annulation), l'insertion de B est refusée (vérifié).
- **Message affiché :** « Restauration refusée, base inchangée : The credits of an invoice line cannot exceed its amount », en anglais et brut (`app.py:2312`).
- **Impact :** la sauvegarde ne se restaure pas, et rc48 ne corrige rien. Il touche la restauration de toute sauvegarde rc47 contenant ce cas.
- **Correctif suggéré :** insérer les annulations avant les lignes, ou différer le déclencheur pendant la reconstruction.

### 5. Mineur : une sauvegarde faite sous rc48 peut ne pas se restaurer sous rc47
- **Preuve :** le `rebuild` de rc47 recrée une base neuve avec l'ancien déclencheur `credit_lines_within_line`.
- **Scénario :** après retour A, une sauvegarde contenant un avoir de 0,23 sur une ligne de 0,225 est refusée par `rebuild` à la restauration (même message qu'au constat 4).
- **Impact :** les notes disent « sans danger pour rc47 » sans signaler ce cas.

### 6. Mineur : le contrôle de schéma ne vérifie pas ce que les notes affirment
- **Preuve :** `app/schema_checks.py:47-51`. `credit_lines_within_line` n'est contrôlé que par nom et table. Seul le texte de `credit_ops_within_note` est comparé. Les 5 nouveaux déclencheurs ne sont pas contrôlés du tout. Seul l'index d'adresse l'est.
- **Impact :** `procedure/50-verify.sh` passerait même si le remplacement de la formule d'arrondi n'avait pas eu lieu.
- **Conséquence inverse :** en présence de doublons, `50-verify.sh` (`assert not p`), `verifier-sauvegarde.sh` et `30-rehearse.sh` échouent. La mise en production serait donc vue comme échec alors que l'application tourne.

### 7. Mineur : des messages bruts en anglais restent possibles
- Restauration : `app.py:2312` affiche `str(e)`. Cas : doublon à casse exacte (`UNIQUE constraint failed: ...`) ou déclencheur (constat 4).
- Création d'avoir : `app.py:1844` affiche `"Note de crédit non créée : " + str(e)`. Le message anglais n'apparaît que si le garde SQL refuse alors que le contrôle Python a accepté. Voir le constat 8 pour un cas qui y mène. Rien ne le produit en usage courant.
- **Pas de 500 :** le gestionnaire global (`app.py:446-451`) masque les autres cas.
- **Nouveaux messages :** les 5 déclencheurs ne sont atteignables ni par l'interface ni par l'API. Aucun code n'écrit `invoice_lines.invoice_id`, `credit_note_lines.credit_note_id`, `invoice_line_id`, `amount` ni `vat_mode`, et il n'y a pas d'`OR REPLACE` ni d'`ON CONFLICT` sur ces tables. Je l'ai vérifié par grep.
- **Doublon d'adresse :** le message est en français à la création (`app.py:836`) comme à la modification (`app.py:857`). L'application n'a pas d'API d'adresses séparée. La mention « (à la casse près) » est inexacte pour un doublon exact.

### 8. Mineur : écart d'un centime sur le repli flottant
- **Preuve :** `credit_lines.py` (`_CAP_SQL`), branche `ELSE CAST(ROUND(qty*unit_rate*100)...)`. Elle s'applique quand `q*r > 9e18`, soit un montant d'environ 9e8 CHF ou plus.
- **Expérience :** 7119,7 × 132921,55 donne un plafond de 946361559,535 au lieu de ,545.
- **Impact :** `MAX_AMOUNT` est à 1e9, donc le cas est quasi inatteignable. Le plafond est cependant d'un centime trop bas, et le garde SQL refuserait ce que Python accepte.

### 9. Mineur
- `label_taken` ne détecte ni les variantes de normalisation NFC/NFD (« é » composé contre décomposé) ni les doubles espaces d'anciens libellés.
- `scripts/seed_adresses_egg.py:plan()` compare les libellés en binaire. Avec une variante de casse déjà en base, il tente un INSERT et échoue sur l'index, avec trace Python et annulation propre.
- La note d'audit « index ignoré » est écrite par un contrôle puis un INSERT non atomiques. Deux workers simultanés pourraient l'écrire deux fois, sans conséquence fonctionnelle.

## Points vérifiés et jugés corrects

- **Formule d'arrondi (`_CAP_SQL`) :**
  - Sur 38 067 couples quantité/prix tirés au hasard (6 et 4 décimales, y compris des demi-centimes), le plafond SQL est égal à `Decimal` demi-supérieur + 0,005. Le seul écart est le constat 8.
  - L'ancienne formule différait de `Decimal` dans 223 cas. Le nouveau plafond n'est jamais plus strict que l'ancien : il ne refuse aucun avoir ou ligne historique que rc47 acceptait.
  - Les valeurs négatives sont impossibles : `qty>0`, `unit_rate>=0` et `amount>0` sont garantis par des CHECK. Un prix à 0 donne un plafond de 0,005, comme avant.
- **Migration aller :**
  - L'ordre dans `init()` est bon. `make_global` (ligne 174) passe avant `ensure_label_index` (ligne 318), et ses `NOT EXISTS` ont été passés en NOCASE.
  - Le remplacement du déclencheur est atomique : `BEGIN IMMEDIATE`, nouvelle lecture dans la transaction, puis `DROP` et `CREATE`.
  - Un échec partiel est rattrapé au démarrage suivant. L'état intermédiaire (garde de mise à jour neuve, garde d'insertion ancienne) est sans danger.
  - Durée négligeable, aucune ligne métier modifiée. En cas de doublon, une seule ligne d'audit est ajoutée.
  - Le démarrage sur une base en lecture seule déjà migrée ne demande pas d'écriture (tout est `IF NOT EXISTS` ou un contrôle préalable).
- **Retour arrière :**
  - **Retour A :** `CREATE TRIGGER IF NOT EXISTS` de rc47 ne réécrit pas le déclencheur d'arrondi neuf, et le test de la formule de plafond (`ops_cap_is_current`) reste vrai. La seule faille est le constat 3.
  - **Retour B :** je l'ai rejoué. Le texte SQL (pas seulement les noms) de tous les déclencheurs et index est identique à une base rc47 neuve, après `drop_label_index`, `rollback_update_guards`, `line_guards.rollback` et `rollback_within_line`. Une base rc48 neuve ne diffère de rc47 que par 1 index et 5 déclencheurs ajoutés, et `credit_lines_within_line` changé.
- **Restauration d'une sauvegarde rc47 dans rc48 :** les 5 nouveaux déclencheurs sont sur UPDATE, donc inertes pendant les INSERT du `rebuild`. L'index est créé avant l'insertion des données. L'ordre des tables est inchangé et le nouveau plafond n'est pas plus strict.
- **Déclencheurs de mise à jour :** le garde de déplacement vers une facture émise teste le snapshot ou le statut de la facture d'arrivée. Les guides de mise à jour des lignes d'avoir comptent bien les autres lignes (`l.id<>NEW.id`) et ne s'activent que si une colonne protégée est écrite. Les `UPDATE invoice_lines` de l'éditeur n'écrivent pas `invoice_id`.
- **Tests existants :** la modification vers une variante d'une autre adresse (et le changement de casse de sa propre adresse), les doublons existants avec index ignoré et audit unique, les avoirs cumulés sur demi-centime, la restauration bloquée sur doublon ASCII, l'idempotence et le retour arrière de chaque lot.

## Cas non couverts par les tests (axe 4)

- Modifier le contact ou l'adresse d'une adresse déjà dans une paire de doublons, avec index ignoré, ou avec une paire Unicode (constat 1).
- Restauration d'une sauvegarde provenant d'une base qui contient des doublons (constat 2).
- Restauration avec une note annulée puis remplacée (constat 4).
- Démarrage de rc47 sur une base migrée avec la configuration du constat 3.
- Plafond au-delà de 9e8 CHF contre `Decimal` (constat 8).
- Les « valeurs négatives » demandées sont couvertes par les CHECK de la base, pas par un test dédié.

## Vérifications à faire sur une COPIE de la base de production

Toutes les requêtes sont en lecture seule : ouvrir la copie avec `sqlite3 -readonly copie.db`.

1. **Doublons d'adresse ASCII (constats 1, 2, 6) :**
   `SELECT client_key, group_concat(label,' | '), COUNT(*) FROM billing_addresses GROUP BY client_key, label COLLATE NOCASE HAVING COUNT(*)>1;`
   Résultat attendu : aucune ligne.
2. **Doublons Unicode ou d'espaces :** script `python3 -I`, ouvrir `file:copie.db?mode=ro`. Regrouper `(client_key, unicodedata.normalize('NFC', ' '.join(label.split())).casefold())` et afficher les groupes de plus d'un libellé. Attendu : aucun.
3. **Cas du constat 3 :**
   `SELECT client_key,label,active FROM billing_addresses WHERE client_key IN ('*','NOM:bsci') ORDER BY label COLLATE NOCASE;`
   Chercher un même libellé (casse ignorée) sous `'*'` et sous `NOM:bsci` avec une casse différente.
4. **Lignes se terminant sur un demi-centime, avec leurs avoirs :**
   `SELECT id,invoice_id,qty,unit_rate FROM invoice_lines WHERE (CAST(ROUND(qty*1000000) AS INTEGER)*CAST(ROUND(unit_rate*10000) AS INTEGER)) % 100000000 = 50000000;`
   Puis, pour ces identifiants, `SELECT invoice_line_id, SUM(amount) FROM credit_note_lines WHERE credit_note_id NOT IN (SELECT credit_note_id FROM credit_note_cancellations) GROUP BY invoice_line_id;` pour voir les avoirs déjà émis.
5. **Notes annulées avec lignes (constat 4) :**
   `SELECT l.invoice_line_id, COUNT(*) FROM credit_note_lines l GROUP BY l.invoice_line_id HAVING COUNT(*)>1 AND SUM(l.credit_note_id IN (SELECT credit_note_id FROM credit_note_cancellations))>0;`
   Si des lignes sortent, une restauration de la sauvegarde de cette base échouerait même en rc47.
6. **Contrôle d'intégrité :** `PRAGMA integrity_check; PRAGMA foreign_key_check;` sur la copie avant et après migration.
7. **Après démarrage de rc48 sur la copie :**
   - `SELECT name FROM sqlite_master WHERE name IN ('idx_billing_addresses_label_nocase','credit_line_upd_no_move_frozen','credit_line_upd_same_invoice','credit_line_upd_same_vat_mode','credit_line_upd_within_line','invoice_line_no_move_to_issued');` doit renvoyer 6 lignes.
   - `SELECT sql LIKE '%qty*1000000%' FROM sqlite_master WHERE name='credit_lines_within_line';` doit renvoyer 1.
   - `SELECT COUNT(*) FROM audit WHERE event='billing_address_label_index_skipped';` doit renvoyer 0.
8. **Commandes à exécuter par quelqu'un d'autre :**
   - `/root/venvs/rc25-test-venv/bin/python -I outils/repeter_migration_rc48.py`
   - `python3 -I outils/empreinte_metier.py comparer <copie_avant> <copie_après>`
   - Les scripts de procédure (`procedure/30-rehearse.sh`, `procedure/verifier-sauvegarde.sh`, `procedure/50-verify.sh`) sur la copie, pour obtenir le verdict de procédure.
9. **Répétition de restauration et de retour arrière complets sur la copie :**
   - Exporter le JSON depuis une instance rc47 chargée avec la copie, puis le restaurer dans une instance rc48 jetable, et inversement (JSON rc48 vers rc47).
   - Démarrer le code rc47 contre la copie migrée (retour A) et vérifier le code de sortie du démarrage.

Fichiers d'expérience laissés hors dépôt : `/tmp/rev48/exp1.py`, `exp2.py`, `exp3b.py`, bases jetables `/tmp/rev48/*.db`.
