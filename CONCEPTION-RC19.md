# Time Billing V9.2-rc19 — conception (version implémentée) : saisies toujours éditables, facture émise immuable

Exigence utilisateur (2026-10-05) : une saisie n'est JAMAIS verrouillée parce qu'elle est ancienne, importée, d'un mandat clôturé ou
déjà facturée. La facture émise reste IMMUABLE. Corriger une saisie facturée est permis, averti, audité (avant/après, date, utilisateur,
motif, factures), ne touche pas la facture et fait apparaître un « écart post-facturation » ; l'utilisateur décide ensuite (note de
crédit = avoir, compensation, ou rien). Contraintes : 2 247 saisies historiques non modifiées pendant l'implémentation, rien de
réimporté, production intacte, aucune modification esthétique (classes CSS existantes uniquement), sauvegarde + migration réversible +
tests + test de retour arrière avant tout changement de schéma.
Cette version intègre la relecture contradictoire de la première conception (4 critiques indépendants : règles métier, intégrité et
migration, régression, sécurité/ergonomie ; 1 bloquant et ~20 points majeurs, tous traités ci-dessous).

## 1. Ce qui verrouillait en RC18 (supprimé)
`entry_lock()` (annexe figée / import / mandat clôturé) ; `active_project()` sur le mandat cible d'une correction ; déclencheurs
`annexed_entry_no_update` / `annexed_entry_no_delete` ; clé étrangère `invoice_annex_entries.entry_id → entries(id)` (empêchait de
supprimer une saisie annexée) ; badge « verrouillée ».
Fait structurant : l'annexe d'une facture est **cumulative** (toutes les saisies du mandat jusqu'à la fin de période). Une saisie n'est
**facturée** que par la facture dont la période contient sa date **figée** ; les autres annexes la listent seulement.

## 2. Règles
- **Mandat clôturé** : refuse les nouvelles saisies (inchangé). Ses saisies restent modifiables et supprimables. Déplacer une saisie
  VERS un autre mandat clôturé : refusé par défaut ; permis avec la case « Rattacher à un mandat clôturé » ET un motif (avertissement :
  heures non facturables tant que le mandat reste clôturé ; position de clôture modifiée). Sortir une saisie d'un mandat clôturé : permis,
  avec avertissement. Ajouter une saisie oubliée à un mandat clôturé : le rouvrir puis le reclôturer (tracé), comme avant.
- **Saisie importée** : saisie normale. Provenance affichée et jamais modifiée (fichier, onglet · ligne, lot, date d'import, valeurs lues
  dans le classeur), recherchée par (lot de la saisie, saisie). La durée DÉCLARÉE d'une ligne importée est conservée tant que début et fin
  ne changent pas (elle peut différer des horaires : la page l'indique). Note affichée : la facturation hors application (suivi Excel)
  n'est pas suivie ; les écarts ne concernent que les factures émises par l'application.
- **Facture émise** : immuable (ligne, copie figée en-tête/annexe/PDF, liens d'annexe : déclencheurs existants inchangés).
- **Saisie facturée** (rôle « billed » d'après la date figée, calculé côté serveur dans la même transaction que l'écriture) : correction
  et suppression permises avec **motif obligatoire** + **case de confirmation** liée aux factures affichées (champ `billed_ids` : refus
  si une facture a été émise entre l'affichage et l'envoi). Saisie seulement listée par une annexe cumulative : simple information.
- **Suppression** : toujours permise ; saisie facturée : depuis sa page (motif + confirmation) ; la facture garde lien et copie figée.
  L'historique d'une saisie supprimée reste consultable (`/entry/<id>/historique`).
- **Identifiants** : un seul allocateur pour toute insertion (manuelle, import) = 1 + max(entries, entry_changes, invoice_annex_entries,
  import_batch_rows) ; déclencheur `entry_id_never_reused` en défense : un identifiant ayant existé n'est jamais redonné.
- **Motif** : une ligne, 500 caractères au plus, caractères de contrôle et d'inversion bidirectionnelle refusés ; jamais imprimé.
- **Courses** : jeton `rev` sur la correction ET la suppression ; double envoi reconnu (« déjà enregistrée ») ; saisie supprimée entre-temps
  → page d'historique au lieu d'une erreur.

## 3. Audit
`entry_changes` (ajout seul) + colonnes `reason`, `actor` (= compte unique `APP_USER`), `invoices_json` (factures concernées et rôle :
facturée / listée dans l'annexe / période d'arrivée), **nullables** (NULL = ligne antérieure à rc19 : une sauvegarde JSON rc18 reste
comparable). `before_json`/`after_json` complets (+ `import_batch_id`, `source_ref`). Journal `audit` : évènements applicatifs au format
JSON. Défense en profondeur en base : déclencheurs AFTER UPDATE/DELETE sur TOUTES les saisies (`entry_update_traced`,
`entry_delete_traced`) → ligne `audit` avant/après (`entry_row_updated` / `entry_row_deleted`, marqueur `invoiced`) : aucune modification
silencieuse, même hors application (une correction dans l'application produit donc 2 lignes d'audit ; une annulation de lot, une ligne
par saisie). Pas de déclencheur « historique d'abord » (verrouillerait de nouveau, fragile).

## 4. Écart post-facturation (calculé à la demande, jamais écrit)
Pour une facture émise F (mandat M, période P, annexe figée A) : lignes facturées = lignes de A datées dans P (valeurs figées).
Statut de chaque ligne : supprimée (0 h), autre mandat (0 h), **date reclassée** dans M hors de P (les heures restent facturées par F),
modifiée, inchangée. **Écart (h) = Σ heures actuelles − Σ heures figées**, en jours aux heures/jour figées ; valeur indicative au tarif
de F, dans l'unité de F (arrondi des documents). À part, hors écart : saisies ajoutées à P après émission et non facturées ailleurs
(reliquat, comme avant), saisies facturées par une autre facture de M dont la date tombe dans P (reclassées, aucune double facturation),
modifications des lignes antérieures de l'annexe cumulative. Notes de crédit émises sur F listées ; celles émises après la première
correction (une note en montant convertie au tarif) donnent l'« écart restant » (information).
**Décision** de l'utilisateur (note de crédit émise sur F / compensation / aucune action, motif obligatoire hors note de crédit),
table `invoice_variance_decisions` en ajout seul, liée à l'**empreinte** de l'écart : une nouvelle correction la rend caduque. Alerte du
tableau de bord = facture dont une saisie facturée a changé avec effet en heures (ou supprimée / changée de mandat) et sans décision pour
l'empreinte actuelle. Correction de description seule ou de date à durée égale : affichée, sans décision requise.
Affichage : page `/invoice/<id>/ecart` (contexte : quantité facturée, arrondi, reliquat d'émission, base « état à la migration » pour une
facture figée en V9.2) ; ligne sous la facture dans « Factures émises » (seulement si saisies facturées changées ou décision) ; badge
« facturée F » dans les listes (« modifiée après émission » en orange) ; message « Attention : … » après enregistrement ; écran
d'émission : encadré « saisies déjà facturées corrigées » (l'annexe cumulative de la nouvelle facture les reprendra avec leur valeur
actuelle, visible du client ; un écart non crédité revient dans le reliquat). Note de crédit proposée (`?ecart=1`) : quantité et motif
calculés par le serveur. Suggestion de facturation : les heures d'une saisie déjà facturée par une facture émise (date reclassée) sont
exclues et signalées. Indicateurs : position des mandats et tableau de bord recalculés depuis les saisies vivantes (la prévision repose
sur ordered − billed : non affectée par les heures).
Pré-filtre SQL : seules les factures susceptibles d'avoir un écart (historique ou trace après émission, ajout tardif, décision) sont
calculées à chaque affichage.

## 5. Annulation d'un lot d'import
Refusée si une saisie du lot a été corrigée, réaffectée ou supprimée depuis l'import (historique postérieur au lot, ou trace en base
d'une écriture hors application), avec le nombre et des références onglet!ligne ; incohérence de comptage → refus explicite.

## 6. Migration de schéma (init(), à chaque démarrage, une transaction BEGIN IMMEDIATE)
1. colonnes nullables `entry_changes.reason/actor/invoices_json` ; index `import_batch_rows(entry_id)` ; table et déclencheurs
   `invoice_variance_decisions` (ajout seul, facture émise seulement, note de la même facture) ;
2. `migrate_rc19()` : clé vérifiée SOUS verrou (2 processus gunicorn) ; si la clé `entry_id → entries` existe : tous les déclencheurs
   lisant l'annexe supprimés AVANT le renommage, table reconstruite (mêmes lignes, PK, index, déclencheurs d'immuabilité), contrôles
   (lignes identiques, clés, aucune table temporaire), audit `schema_rc19_annex_rebuilt` ; puis déclencheurs rc19 supprimés et recréés
   (auto-réparation) ; sondes de compilation (EXPLAIN UPDATE/DELETE/INSERT) ; tout échec → ROLLBACK, service non démarré. Une base neuve
   est créée sans la clé (pas de reconstruction, pas d'audit sur un fichier neuf, compatible avec la reconstruction de restauration).
3. aucune ligne de `entries` n'est écrite.
Contrôle partagé `app/schema_checks.rc19_problems()` (déclencheurs et rattachements, clé, index, colonnes, compilation, liens d'annexe
expliqués, identifiants non réutilisés, traçabilité des saisies annexées) utilisé par `30-rehearse`, `50-verify`, `verifier-sauvegarde`.
Restauration JSON : `annex_trail()` remplace le gel des saisies annexées : toute saisie annexée du fichier est égale à sa ligne figée, ou
expliquée par l'historique du fichier (correction dont l'« après » est la saisie, ou suppression) ; aucune résurrection ; décisions en
ajout seul (IMMUTABLE).

## 7. Retour arrière
**Chemin officiel : `procedure/90-rollback.sh`** (image + base d'avant déploiement, SHA identique). Nouveau : la base vivante est d'abord
copiée et vérifiée (`ecarte-<TS>/timebilling-avant-retour.db`) ; le retour est **refusé** s'il écarterait des corrections ou décisions
enregistrées depuis le déploiement, sauf `ABANDONNER_CORRECTIONS=OUI` (après export). Code rc18 sur base rc19 (sans restauration) :
NON pris en charge (rc18 recrée ses verrous mais ses restaurations JSON échouent sur les colonnes rc19) — secours uniquement. Pas de
script de « descente » de schéma : il détruirait l'audit rc19 (motifs, utilisateurs, décisions).

## 8. Fichiers
app/app.py, app/post_billing.py (nouveau), app/schema_checks.py (nouveau), app/import_service.py, app/rollback_service.py,
app/restore_service.py ; gabarits entry_edit, entries, index, credit_new, issue_confirm, invoice_variance (nouveau), entry_history
(nouveau), _entry_history_table (nouveau) ; procedure 30/50/90 + verifier-sauvegarde ; tests (test_rc19 + adaptations), recettes HTTP
(lots A, D/E adaptés, lot R nouveau), navigateur (recette-saisies adaptée, recette-rc19 nouvelle), répétition C (migration-blanc).
