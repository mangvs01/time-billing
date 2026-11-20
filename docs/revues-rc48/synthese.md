# Synthèse de la revue indépendante de 9.2-rc48 (BILL-REVUE-RC48)

Périmètre : `git diff 2382090..e779517` (BILL-FC1, BILL-FA1FT, migrations additives). Deux relecteurs indépendants en lecture seule (opus : `avis-opus.md` ; sonnet : `avis-sonnet.md`), même brief, sans connaissance de l'avis de l'autre. Aucun code modifié, aucune base de production consultée.

## Verdict

Les deux relecteurs concluent **GO conditionnel** : aucun défaut bloquant dans le code, migration aller additive et idempotente, retour arrière complet B exact. Le GO dépend (1) du résultat des vérifications sur une copie de la base de production (section finale) et (2) d'une décision sur le constat A ci-dessous.

Points confirmés par les deux avis (convergence) : le nouveau plafond d'avoir est exact (0 désaccord sur 139 531 et 38 067 cas aléatoires) et n'est jamais plus strict que l'ancien, donc aucun avoir existant n'est refusé ; les 5 nouveaux déclencheurs ne sont atteignables par aucun code de l'application ; les valeurs négatives sont impossibles (contraintes CHECK) ; les messages d'erreur des déclencheurs ne peuvent pas apparaître à l'écran en usage normal ; il n'y a pas de page 500 brute (gestionnaire global en français).

Contrôle personnel (relecture du code, sans réexécuter les essais des relecteurs) : confirmés `app/app.py:857` (`label_taken` appelé même quand le libellé ne change pas), `app/restore_service.py:17` (`credit_note_lines` avant `credit_note_cancellations`), l'usage de `rc19_problems` comme critère d'échec dans `procedure/30-rehearse.sh`, `50-verify.sh`, `verifier-sauvegarde.sh`, et le `make_global` rc47 comparé en binaire. Les chiffres des tirages aléatoires et les reproductions par base jetable sont ceux des relecteurs, non rejoués.

## Retenu

| # | Constat | Source | Gravité retenue | Pourquoi retenu / suite proposée |
|---|---|---|---|---|
| A | **Une adresse dont il existe un « jumeau » à la casse près (ASCII, ou Unicode type « Zürich »/« ZÜRICH ») ne peut plus être modifiée**, même sans toucher au libellé ; message trompeur. rc47 le permettait. | opus 1, sonnet 1 (reproduit par les deux) | Important, **régression conditionnelle** | Vérifié dans le code. Ne se produit que si la production contient de tels doublons (vérif. 1 et 2). Correctif à faire avant mise en ligne si des doublons existent : ne tester le jumeau que si le libellé change réellement ; message « à renommer ». Test à ajouter. |
| B | **Production avec doublons ASCII : l'application démarre, mais `rc19_problems` passe au rouge** → `30-rehearse.sh` NO-GO, `50-verify.sh` échec, `verifier-sauvegarde.sh` « non exploitable » (cron hebdomadaire) ; et la restauration JSON de toute sauvegarde de cette base est bloquée, sans action possible pour l'utilisateur. Les notes ne le disent pas. | opus 2, sonnet 2 et 6 | Important, conditionnel | Vérifié (appels dans les scripts). Décision à prendre : (i) pré-vérifier et renommer les doublons AVANT la mise en ligne (recommandé, rend le point sans objet) ; (ii) sinon documenter et/ou tolérer les doublons existants à la restauration. À reporter dans `RC48-NOTES.md`. |
| C | **Une sauvegarde JSON faite sous rc48 peut ne pas se restaurer sous rc47** (la base reconstruite reçoit l'ancien déclencheur d'arrondi qui refuse 0,23 sur 0,225). La note « sans danger pour rc47 » est trop forte. Concerne les retours A et B. | opus 3, sonnet 5 | Important pour le retour arrière (mineur selon sonnet) | Retenu avec la gravité la plus haute : le filet de sécurité du retour arrière est amoindri. Remède : documenter (restaurer le fichier SQLite et non le JSON en cas de retour arrière une fois un avoir demi-centime créé), ou refuser/éviter ce cas. À tester sur la copie. |
| D | **rc47 peut refuser de démarrer sur une base rc48** si une adresse globale `'*'/'egg fr'` coexiste avec `NOM:bsci/'EGG FR'` (le `make_global` de rc47 compare en binaire et se heurte à l'index NOCASE). Contredit « retour A sans erreur » pour ce cas. | sonnet 3 seul (reproduit) | Important, conditionnel, improbable | Retenu comme à vérifier : un seul relecteur, mais reproduit et cohérent avec le code rc47 relu. Requête 3 sur la copie ; sinon l'écrire dans la procédure de retour A (supprimer l'index avant de remettre rc47). |
| E | **Restauration JSON refusée pour une ligne créditée, annulée, puis recréditée** (ordre `credit_note_lines` avant `credit_note_cancellations`), message en anglais brut. **Déjà présent en rc47, pas une régression.** | opus 4, sonnet 4 (reproduit) | Important mais hors périmètre rc48 | Retenu comme défaut existant à traiter en lot séparé (ne pas bloquer rc48) ; mais à vérifier sur la copie (vérif. 5) car il rend la sauvegarde de production inutilisable pour la restauration JSON si le cas existe déjà. |
| F | **Le contrôle de schéma ne vérifie ni les 5 nouveaux déclencheurs ni la nouvelle formule d'arrondi** (seulement l'index d'adresse) : `50-verify.sh` passerait même après un retour arrière partiel. | opus 6, sonnet 6 | Mineur | Retenu : amélioration à planifier (comparer le texte du déclencheur comme pour `credit_ops_within_note`). Non bloquant. |
| G | **Messages anglais bruts encore possibles** : erreur de restauration (`app.py:2312/2313`, cas C et E) ; « Note de crédit non créée : … cannot exceed… » (`credit_new`, seulement via le cas H). | opus 8, sonnet 7 | Mineur | Retenu : à traduire/habiller avec C et E. Le message du doublon d'adresse est bien en français à la création et à la modification. |
| H | **Plafond d'avoir légèrement faux au-delà d'environ 9×10⁸ CHF par ligne** (repli flottant, écart d'un centime ou avoir total refusé). | opus 5, sonnet 8 | Mineur | Retenu mais accepté en l'état : limite `MAX_AMOUNT` = 10⁹, cas quasi inatteignable. Vérif. 4 sur la copie pour s'en assurer. |

## Écarté ou relégué

| Constat | Raison |
|---|---|
| Libellés « Café » NFC/NFD, doubles espaces d'anciens libellés non vus comme doublons (opus 7, sonnet 9) | Cas théoriques ; couverts par la vérification Unicode/espaces sur la copie. Pas d'action de code avant d'avoir vu les données. |
| `scripts/seed_adresses_egg.py` compare les libellés en binaire et échoue proprement avec une variante de casse (opus 7, sonnet 9) | Script d'amorçage hors chemin utilisateur, échec sans dommage (écriture annulée). À corriger à l'occasion. |
| Note d'audit « index ignoré » écrite par contrôle puis INSERT non atomiques (sonnet 9) | Sans conséquence fonctionnelle (au pire deux lignes d'audit). |
| « à la casse près » est du jargon (opus 7) | Intégré à la correction du message du constat A. |
| Messages de déclencheurs (« Lines of an issued invoice are immutable » …) | Inatteignables par l'interface ; aucune action. |
| Valeurs négatives non testées (sonnet) | Impossibles par CHECK ; test dédié facultatif. |

## Décisions à faire valider

1. Corriger le constat A avant la mise en ligne (petit changement + test), ou conditionner la mise en ligne à l'absence de doublons sur la copie (vérif. 1 et 2) ?
2. Constat B : pré-renommer les doublons éventuels avant déploiement (recommandé), ou tolérer ?
3. Constat C : accepter de documenter « retour arrière = restaurer le fichier SQLite, pas le JSON » plutôt que de modifier le code ?
4. Constat E : ouvrir un lot séparé pour l'ordre de restauration (défaut rc47).

## Vérifications à faire sur une COPIE de la base de production avant la mise en ligne

(Je n'ai accédé à aucune base de production ; à exécuter par une personne habilitée, sur une copie, en lecture seule — `sqlite3 -readonly copie.db` ou `file:copie.db?mode=ro`. Fusion et dédoublonnage des deux avis ; les requêtes complètes figurent dans `avis-opus.md` et `avis-sonnet.md`.)

**Requêtes (résultat attendu : aucune ligne sauf mention)**
1. Doublons d'adresse ASCII : `SELECT client_key, group_concat(id||':'||label,' | '), COUNT(*) FROM billing_addresses GROUP BY client_key, label COLLATE NOCASE HAVING COUNT(*)>1;` → constats A, B.
2. Doublons Unicode/espaces (script `python3 -I`, base ouverte en `mode=ro`) : regrouper `(client_key, NFC(label avec espaces normalisés).casefold())` → constat A.
3. Libellés aux espaces non normalisés : `SELECT id, client_key, '['||label||']' FROM billing_addresses WHERE label<>trim(label) OR label LIKE '%  %';`
4. Cas D : `SELECT id, client_key, label, active FROM billing_addresses WHERE client_key IN ('*','NOM:bsci') ORDER BY label COLLATE NOCASE;` — chercher un même libellé à une casse différente entre `'*'` et `NOM:bsci`.
5. Lignes d'avoir déjà posées sur des lignes finissant en demi-centime (voir requête 4 de `avis-sonnet.md`) et lignes au-delà de 9×10⁸ (`qty*unit_rate > 9e8`) → constat H.
6. Lignes créditées puis annulées puis recréditées (requête 5 de `avis-opus.md` ou 5 de `avis-sonnet.md`) → constat E.
7. Cohérence avoirs/lignes : `SELECT l.id FROM credit_note_lines l JOIN invoice_lines il ON il.id=l.invoice_line_id JOIN credit_notes n ON n.id=l.credit_note_id WHERE il.invoice_id<>n.invoice_id OR il.vat_mode<>l.vat_mode;`
8. `PRAGMA integrity_check; PRAGMA foreign_key_check;` avant et après migration.

**Migration aller (copie, code rc48)**
9. Démarrer rc48 sur la copie : 6 objets présents (`idx_billing_addresses_label_nocase` + 5 déclencheurs), `credit_lines_within_line` à la nouvelle formule (`sql LIKE '%qty*1000000%'`), 0 note d'audit `billing_address_label_index_skipped`.
10. `python3 -I outils/empreinte_metier.py comparer <copie_avant> <copie_après>` : identique ; `outils/repeter_migration_rc48.py` ; scripts `procedure/30-rehearse.sh`, `50-verify.sh`, `verifier-sauvegarde.sh` sur la copie (verdict GO attendu).

**Retour arrière et restauration (copie, instances jetables)**
11. Retour A : démarrer le code rc47 sur la copie migrée, vérifier le code de sortie (constat D).
12. Retour B : exécuter la procédure complète documentée et comparer schéma/données à rc47.
13. Export JSON de la copie migrée → aperçu puis restauration sous rc48 ; puis restauration du même JSON sous rc47 (constat C), après avoir créé sur la copie un avoir total de 0,23 sur une ligne 1,5 × 0,15.
14. Restauration d'un export JSON de la copie en rc47 puis rc48 pour confirmer ou écarter le constat E.
