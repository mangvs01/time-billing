# Avis indépendant — modèle opus — revue de 9.2-rc48

Mission BILL-REVUE-RC48. Revue en lecture seule de `git diff 2382090..e779517`, menée par un sous-agent (modèle opus) qui n'a pas vu l'avis du modèle sonnet. Texte ci-dessous = rapport du sous-agent, reproduit tel quel (aucune correction de fond). Ses essais ont tourné sur des bases jetables sous `/tmp/revue-rc48`.

---

# Revue indépendante de Time Billing 9.2-rc48 (`git diff 2382090..e779517`)

## Résumé et verdict

**GO sous condition.** Avant la mise en ligne, il faut exécuter sur une **copie** de la base de production les requêtes 1 et 2 de la dernière section. Si elles ne renvoient rien, la version peut partir. Si elles renvoient quelque chose, il faut d'abord renommer les adresses concernées sous rc47, ou corriger le constat 1.

Le code fait ce que les notes annoncent. Le nouveau calcul de plafond de l'avoir donne exactement le même montant que l'application : 0 désaccord sur 139 531 cas tirés au hasard, testés sur une base jetable dans /tmp. Les déclencheurs ajoutés ne gênent aucune écriture de l'application.

Il y a cependant trois angles morts, qui ne touchent que des données existantes ou le retour arrière :
- certaines adresses existantes ne peuvent plus être modifiées (constat 1) ;
- si la production contient déjà des adresses en double, la procédure de déploiement s'arrête et la restauration de ses sauvegardes est bloquée (constat 2) ;
- une sauvegarde faite sous rc48 peut ne plus se restaurer sous rc47 (constat 3).

## Constats

**1. IMPORTANT (vérifié en exécutant le code) : une adresse existante qui a un « jumeau » ne peut plus être modifiée du tout.**
- Preuve : `app/app.py:857` appelle `label_taken` à chaque enregistrement, même quand le libellé ne change pas. `app/address_service.py:51-54` compare les libellés avec `casefold()`, une comparaison Unicode complète.
- Scénario 1 : la base contient déjà « Zürich » et « ZÜRICH » pour le même client. L'index ne les voit pas comme des doublons (NOCASE ne traite que les lettres ASCII), donc il est créé. Ensuite, changer seulement le destinataire de « Zürich » est refusé avec « Adresse non modifiée : une adresse « Zürich » existe déjà pour ce client (à la casse près) ». Même résultat avec « Strasse » / « Straße ».
- Scénario 2 : la base contient « EGG FR » et « egg fr ». L'index n'est pas créé, et ces deux adresses ne sont plus modifiables non plus.
- Sous rc47, ces modifications passaient. Le message est aussi trompeur : il cite le propre libellé de l'adresse et ne dit pas qu'il suffit de la renommer. Le renommage, lui, fonctionne.
- Correctif suggéré : ne tester le doublon que si le libellé change réellement, en comparant avec `casefold` l'ancien et le nouveau libellé. Le message devrait dire « ne diffère que par les majuscules : renommer l'une des deux ».
- Aucun test ne couvre ce cas. `tests/test_bill_fa1ft.py:67` ne teste que le renommage.

**2. IMPORTANT (si la production contient déjà des doublons ASCII) : l'application démarre, mais toute la chaîne d'exploitation passe au rouge.**
- Preuve : `app/schema_checks.py:66` signale l'index absent comme un problème. Or `rc19_problems` sert de critère d'échec dans `procedure/30-rehearse.sh:45` (répétition déclarée NO-GO), `procedure/50-verify.sh:39` (« ÉCHEC base ») et `procedure/verifier-sauvegarde.sh:34` (« SAUVEGARDE NON EXPLOITABLE » chaque semaine, via cron).
- De plus, `app/restore_service.py:136` / `213-222` bloque la restauration JSON de **toute** sauvegarde de cette production, avec un message qui demande de corriger le fichier JSON à la main.
- Les notes (« l'application démarre… ») ne mentionnent aucune de ces conséquences.
- Correctif suggéré : vérifier l'absence de doublons avant le déploiement (requête 1). Ou bien décider explicitement, et documenter, que ce contrôle bloque le déploiement et dire comment s'en sortir (renommer depuis l'écran Adresses).

**3. IMPORTANT (retour arrière) : une sauvegarde JSON faite sous rc48 peut ne plus se restaurer sous rc47.**
- Mécanisme : la restauration sous rc47 reconstruit une base neuve avec le code rc47 (`restore_service.rebuild` → `init`). Cette base reçoit donc l'ancien déclencheur de plafond, qui refuse 0,23 sur une ligne de 1,5 × 0,15. C'est prouvé par `tests/test_bill_fc1.py:38-42`.
- Scénario : un avoir total sur une ligne qui finit sur un demi-centime est créé sous rc48, puis on revient à rc47 (chemin A ou B) et on restaure une sauvegarde JSON récente. Résultat : « Restauration refusée, base inchangée : The credits of an invoice line cannot exceed its amount », en anglais.
- La base reste intacte, mais le filet de sécurité du retour arrière ne marche plus. Le retour arrière B a aussi ce défaut. Ni `outils/repeter_migration_rc48.py` ni les notes ne l'ont testé.
- Correctif suggéré : le documenter dans les notes, et préférer dans ce cas la restauration du fichier SQLite. Ou garder le calcul exact dans tout retour arrière.

**4. IMPORTANT, mais déjà présent avant rc48 (vérifié en exécutant le code) : l'ordre de restauration fait refuser une sauvegarde pourtant légitime.**
- Preuve : `app/restore_service.py:17` insère `credit_note_lines` **avant** `credit_note_cancellations`. Or le plafond ne retire les avoirs annulés que s'il trouve leur annulation, déjà insérée.
- Scénario : une ligne de 100 est créditée par l'avoir 1, l'avoir 1 est annulé, puis un avoir 2 crédite à nouveau 100. En usage normal c'est accepté. À la restauration JSON, c'est refusé (« cannot exceed », en anglais).
- rc48 ne crée pas ce défaut, mais le plafond qu'elle remplace garde la même structure. `lines_consistency` ne le détecte pas à l'aperçu.
- Correctif suggéré : insérer les annulations avant les lignes d'avoir (ce qui n'est pas gênant, car l'insertion des lignes est contrôlée par la copie figée de l'avoir et non par son statut). Ou le signaler dès l'aperçu.

**5. MINEUR : le plafond est faux au-delà d'environ 900 millions de CHF par ligne.**
- Preuve : `app/credit_lines.py:52`. Quand q × r dépasse 9e18, le calcul repasse à l'ancienne méthode `ROUND(qty*unit_rate*100)` en virgule flottante.
- Cas vérifié : qty = 10, prix = 95 000 000,0005. Le montant facturé est 950 000 000,01 et l'avoir total est refusé. C'est possible en théorie (limite `MAX_AMOUNT` = 1e9), mais très improbable.

**6. MINEUR : le contrôle de schéma ne vérifie rien de rc48 hormis l'index.**
- Preuve : `app/schema_checks.py:47-66` ne vérifie pas la présence des cinq nouveaux déclencheurs ni la nouvelle formule de `credit_lines_within_line` (contrairement à `credit_ops_within_note`).
- Les sondes `PROBES` ne préparent pas non plus `UPDATE … SET invoice_id` / `credit_note_id`.
- Conséquence : après un retour arrière B partiel, les procédures 50-verify et verifier-sauvegarde affichent « OK ».

**7. MINEUR : petites incohérences de comparaison des libellés.**
- `label_taken` ne normalise pas l'Unicode : « Café » composé et « Café » décomposé ne sont pas vus comme un doublon.
- Les libellés déjà stockés ne sont pas ramenés aux espaces normalisés, contrairement à ce que dit le commentaire de `address_service.py:52`.
- `scripts/seed_adresses_egg.py:44` compare les libellés à l'identique : si « egg fr » existe déjà pour le client, le script s'arrête sur une IntegrityError brute (sans dommage, l'écriture est annulée).
- « à la casse près » reste du jargon pour l'utilisateur.

**8. MINEUR : des messages anglais peuvent encore s'afficher à l'écran.**
- Avoir : « Note de crédit non créée : The credits of an invoice line cannot exceed its amount » (`app.py` route `credit_new`, `str(e)`). Ce n'est plus atteignable en usage normal, sauf dans le cas du constat 5.
- Restauration : `app.py:2313` affiche l'erreur SQL brute (constats 3 et 4).
- « Lines of an issued invoice are immutable » ne peut pas apparaître : aucun code de l'application ne change le rattachement d'une ligne.
- Il n'y a pas d'API. Les erreurs non prévues donnent une page 500 en français, sans détail technique (`app.py:446-451`).

## Points vérifiés et jugés corrects

- **Calcul exact du plafond** : quantité limitée à 6 décimales et prix à 4 (`invoice_lines.py:61,63`), donc la conversion en entiers est exacte. Les valeurs négatives sont impossibles (`CHECK qty>0`, `unit_rate>=0`, `amount>0`). Le résultat est identique à `line_amount` sur 139 531 cas aléatoires.
- **Avoirs existants** : sous rc47, l'application les plafonnait déjà avec `line_amount`, qui est égal au nouveau plafond. Le nouveau déclencheur ne refuse donc aucun avoir existant, ni à la restauration ni ailleurs (hors constat 5). Le cumul de plusieurs avoirs partiels passe, avec la tolérance de 0,005.
- **Nouveaux déclencheurs de mise à jour** : aucun code ne fait `UPDATE credit_note_lines`, et `invoice_lines.py:104,109` ne touche jamais `invoice_id`. Ce sont des déclencheurs sur colonnes précises (`UPDATE OF`) : émission, annulation, gel, `freeze_legacy_issued` et restauration (qui ne fait que des INSERT) ne les déclenchent pas.
- **Migration aller** : additive. `executescript` valide d'abord la transaction en cours (et donc la note d'audit). Le remplacement de `credit_lines_within_line` se fait sous `BEGIN IMMEDIATE`, avec une seconde vérification dans la transaction, ce qui couvre deux processus qui démarrent en même temps. Un échec partiel se termine au démarrage suivant (`IF NOT EXISTS`).
- **`make_global` avec NOCASE** : évite qu'un déplacement d'adresse fasse échouer la création de l'index au démarrage.
- **rc47 sur une base migrée** : `credit_lines.migrate` de rc47 ne réécrit pas `credit_lines_within_line` (`IF NOT EXISTS` puis `return`). rc47 ne connaît pas l'index et ne s'en soucie pas. Ses routes d'adresse interceptent déjà l'IntegrityError et affichent un message en français. rc47 accepte les sauvegardes « 9.x » (hors constat 3).
- **Aperçu de restauration** : il compare les libellés comme NOCASE (lettres ASCII seulement), ce qui est cohérent avec l'index.

## Vérifications à faire sur une COPIE de la base de production (lecture seule, à exécuter par quelqu'un d'autre)

```sql
-- 1. Doublons ASCII (empêchent l'index, font échouer 30-rehearse/50-verify, bloquent les restaurations JSON)
SELECT client_key, group_concat(id||':'||label,' | '), COUNT(*) FROM billing_addresses GROUP BY client_key, label COLLATE NOCASE HAVING COUNT(*)>1;
-- 3. Libellés aux espaces non normalisés
SELECT id, client_key, '['||label||']' FROM billing_addresses WHERE label<>trim(label) OR label LIKE '%  %';
-- 4. Lignes manuelles au-delà de la zone exacte (constat 5)
SELECT id, invoice_id, qty, unit_rate, qty*unit_rate FROM invoice_lines WHERE qty*unit_rate > 9e8;
-- 5. Lignes recréditées après annulation (restauration JSON refusée, constat 4)
SELECT l.invoice_line_id, SUM(l.amount) total_y_compris_annules, ROUND(il.qty*il.unit_rate,2) facture
FROM credit_note_lines l JOIN invoice_lines il ON il.id=l.invoice_line_id GROUP BY l.invoice_line_id HAVING SUM(l.amount) > ROUND(il.qty*il.unit_rate,2)+0.005;
-- 6. Lignes d'avoir incohérentes avec leur ligne (seraient bloquées par les nouveaux garde-fous si on les modifiait)
SELECT l.id FROM credit_note_lines l JOIN invoice_lines il ON il.id=l.invoice_line_id JOIN credit_notes n ON n.id=l.credit_note_id WHERE il.invoice_id<>n.invoice_id OR il.vat_mode<>l.vat_mode;
-- 7. Adresses de la liste commune et du client d'origine
SELECT id, client_key, label FROM billing_addresses WHERE client_key IN ('*','NOM:bsci') ORDER BY label COLLATE NOCASE;
```

```
# 2. Doublons Unicode (constat 1), en lecture seule, sur la COPIE :
python3 -I -c "import sqlite3,collections,unicodedata as u;c=sqlite3.connect('file:/CHEMIN/COPIE.db?mode=ro',uri=True);d=collections.defaultdict(list)
for i,k,l in c.execute('SELECT id,client_key,label FROM billing_addresses'): d[(k,u.normalize('NFC',l).casefold())].append((i,l))
print([v for v in d.values() if len(v)>1])"
```

Ensuite, toujours sur la copie :
- (a) lancer `procedure/30-rehearse.sh` avec rc48 et vérifier qu'il annonce GO ;
- (b) faire un export JSON de la copie migrée, puis lancer l'aperçu de restauration sous rc48 et une restauration complète sous rc47 (image rc47) dans une instance jetable ;
- (c) répéter (b) après avoir créé, sur la copie, un avoir total de 0,23 sur une ligne de 1,5 × 0,15, pour confirmer le constat 3.

Je n'ai pas relancé la suite de 1 220 tests. Tous mes essais ont tourné sur des bases jetables sous /tmp/revue-rc48 ; aucun fichier du dépôt n'a été modifié.
