# RAPPORT QA fonctionnel — Time Billing V9.2-rc10 (commit 3365991)

Auditeur indépendant — 2026-10-04. Code testé : extraction `git archive 3365991 app` dans `qa/src-rc10/app` (le dépôt de travail a été modifié en parallèle vers RC11 pendant l'audit : seuls CSP / logout / gabarits diffèrent, la logique métier est identique ; tous les résultats ci-dessous ont été rejoués sur l'extraction rc10).
Méthode : client de test Flask dans des conteneurs jetables `tb-qa-*` (`--network none`, code monté en lecture seule, base vierge, données fictives), harness `audit/agent-calculs/harness.py` réutilisé. Aucun fichier sous `app/`, aucune base réelle, aucun `.env`, aucun import réel touchés ; plus aucun conteneur `tb-qa-` ne subsiste. Les tests unitaires existants n'ont pas été relancés (leur script écrit sous `recette/` et copie une base de recette).
Exécution : `qa/run.sh sNN_xxx.py` (journaux dans `qa/logs/`). 199 contrôles exécutés dont 154 passent et 45 échouent ; parmi ces 45, 3 sont des artefacts de test écartés (T4.11, T6.1e, trigger T7 « INSERT credit_operations » = injection volontaire) ; les 42 autres se regroupent en 25 défauts ci-dessous.

Légende : **CONFIRMÉ** = reproduit par exécution (script + identifiant de contrôle) ; **SUSPECTÉ** = lecture du code seulement.
Un correctif a été **vérifié par exécution** dans une copie (`qa/src-patched`, diff complet `qa/patch-verified.diff`) pour QA-01, 02, 03, 05, 10, 11, 16 et 18 (partiel : doublon de nom à la création) : les contrôles correspondants passent après patch.

---------------------------------------------------------------------------------------------------

## Synthèse

| Gravité | Nombre | Identifiants |
|---|---|---|
| Bloquant | 0 | — |
| Majeur | 6 | QA-01, 02, 03, 04, 05, 06 |
| Mineur | 14 | QA-07 à QA-20 |
| Confort | 5 | QA-21 à QA-25 |
| Suspectés (lecture) | 5 | QA-S1 à QA-S5 |

---------------------------------------------------------------------------------------------------

## DÉFAUTS CONFIRMÉS PAR EXÉCUTION

### QA-01 — MAJEUR — axe 4 (facturation) / 2 (PO) — Double facturation d'une même période : brouillons chevauchants puis émission sans contrôle
- Reproduction : `qa/s20_invoicing.py` (T4.1, T4.2, T4.3, T2.1).
  1. Mandat PO 10 j ; 10 j saisis en janvier. 2. Créer deux brouillons identiques `2026-01-01 → 2026-01-31`, qté 10 (le second est accepté, seul un message « dépassent le solde du bon de commande » est affiché). 3. Émettre les deux (`/issue/<id>`).
- Observé : factures `2026-01` et `2026-01-2` toutes deux émises pour la même période (20 j facturés, 10 j commandés, solde PO −10 j, 15 j réalisés). Aucun refus. Dans l'interface l'utilisateur voit seulement « reliquat −10 j facturés d'avance » et doit choisir « reporté ».
- Attendu : refus (ou blocage) d'un brouillon dont la période chevauche un autre brouillon, et surtout refus à l'émission si la période chevauche une facture émise du même mandat (le contrôle n'existe qu'à la création/édition, `draft_values`).
- Suspecté : `app/app.py:597-598` (contrôle fait seulement à la création/édition) et `app/app.py:696-712` (`issue()` ne le rejoue pas).
- Correction (vérifiée) :
```diff
@@ def issue(iid):  (après le contrôle date_problem, app.py ~704)
   if ctx["date_problem"]: raise ValueError(ctx["date_problem"])
+  clash=c.execute("SELECT number FROM invoices WHERE project_id=? AND status='issued' AND id<>? AND period_from<=? AND period_to>=? LIMIT 1",(i["project_id"],iid,i["period_to"],i["period_from"])).fetchone()
+  if clash: raise ValueError(f"la période chevauche la facture déjà émise {clash['number']} : modifier la période ou supprimer ce brouillon")
```
  (et, à la création, un `flash` d'avertissement si un autre brouillon couvre la période).

### QA-02 — MAJEUR — axe 2 (modification de tarif) — Modifier un brouillon (même seulement la note) réécrit silencieusement son tarif avec le tarif courant du mandat
- Reproduction : `qa/s20_invoicing.py` (T2.2). Brouillon de 5 j au tarif 1000 ; changer le tarif du mandat à 1200 ; ouvrir le brouillon, ne changer que la « note », enregistrer.
- Observé : `unit_rate` passe de 1000 à 1200 (montant +20 %), message « Brouillon modifié. » sans mention du tarif ; l'écran d'édition n'affiche d'ailleurs jamais le tarif. Avant l'édition, la liste montre encore l'ancien montant.
- Attendu : le tarif du brouillon ne change que sur action explicite (case « appliquer le tarif actuel du mandat »), ou au minimum être affiché et signalé.
- Suspecté : `app/app.py:645` (`v["unit_rate"]=i["rate"] …` relit le tarif du projet à chaque POST) ; texte trompeur `project_edit.html` (« ces changements valent pour les prochains documents »).
- Correction (vérifiée) :
```diff
-    v["unit_rate"]=i["rate"] if v["unit"]=="day" else i["rate"]/(i["day_hours"] or 8)
+    v["unit_rate"]=float(i["unit_rate"]) if v["unit"]==i["unit"] else (i["rate"] if v["unit"]=="day" else i["rate"]/(i["day_hours"] or 8))
```

### QA-03 — MAJEUR — axe 9 (sauvegarde/restauration) — La sauvegarde JSON produite par l'application dépasse la limite de 15 Mo et ne peut plus être restaurée par l'application
- Reproduction : `qa/s96_perf.py` (T9.8b) et `qa/s97_backup_size.py` (T9.8).
- Observé : 183 Ko de JSON par facture (PDF figés en base64 + `annex_json` + annexes cumulatives qui grossissent à chaque mois). 21 factures = 3,8 Mo ; 120 factures (5 mandats × 2 ans) = 35,1 Mo. `POST /restore` de ce fichier répond `413 Request Entity Too Large` (page anglaise brute) : `APP.config["MAX_CONTENT_LENGTH"]=15 Mo`. Le seuil est atteint vers 80-85 factures (≈ 1 an pour 7 mandats mensuels). Le bouton « Télécharger une sauvegarde JSON complète » reste utilisable, donnant une fausse impression de sécurité ; seule la copie SQLite (procédure) reste restaurable (aller-retour SQLite vérifié sans perte, S73).
- Attendu : tout fichier produit par `/backup` est restaurable (limite dédiée à `/restore`, message français, et/ou sauvegarde compressée).
- Suspecté : `app/app.py:18` et `app/app.py:1014` (`restore_upload`). OPERATIONS-RC10 §3 recommande en outre `max_size 20MB` côté Caddy : même plafond.
- Correction (vérifiée, Flask ≥ 3.1) :
```diff
 def restore_upload():
+ request.max_content_length=1024*1024*1024  # un JSON complet contient tous les PDF figés en base64
  f=request.files.get("backup")
```
  + aligner la directive Caddy ; idéalement compresser le JSON (gzip) et ne pas dupliquer `annex_json`.

### QA-04 — MAJEUR — axe 8 (PDF) — La quantité imprimée est arrondie à 2 décimales : quantité × prix unitaire ≠ montant imprimé
- Reproduction : `qa/s52_pdf_docs.py` puis `qa/s53_pdf_verify.py`. Déjà relevé par l'audit calculs (`audit/agent-calculs/out_t08_display.txt`) mais non corrigé en RC10 alors que RC10 introduit les quantités à 6 décimales.
- Observé : quantité 4,123457 j × 1 234,56 → facture imprimée « 4,12 × 1 234,56 CHF = 5 090,66 CHF » (le calcul de l'imprimé donne 5 086,39). Idem sur les notes de crédit (colonne JOUR) et, en unité heure, le coût horaire est imprimé à 2 décimales.
- Attendu : quantité imprimée avec toutes ses décimales significatives (jusqu'à 6), ou arrondi de quantité imposé à la saisie.
- Suspecté : `app/pdf_layout.py:73-76` (`num()`) utilisé à `pdf_layout.py:388` et `:415`.
- Correction : `qty_label(v)` = `num(v, 6).rstrip("0")` en conservant au moins 2 décimales, utilisé pour `h["qty"]` (facture, note) ; pour l'unité heure imprimer `unit_rate` avec 4 décimales.

### QA-05 — MAJEUR — axe 7 (archivage/traçabilité) — Réutilisation des identifiants : l'historique d'un brouillon ou d'une saisie supprimés est attribué au suivant, et il est figé dans la facture émise
- Reproduction : `qa/s10_entries.py` (T1.13) et `qa/s20_invoicing.py` (T4.4, T4.5).
  Les tables `invoices` et `entries` utilisent `INTEGER PRIMARY KEY` sans `AUTOINCREMENT` ; l'id du dernier enregistrement supprimé est donc réutilisé, alors que `invoice_date_changes`, `entry_changes` et `credit_operations.target_invoice_id` (append-only, sans clé étrangère par conception) y restent rattachés.
- Observé : (a) brouillon n° 5 modifié (2 traces de date) puis supprimé ; nouveau brouillon → n° 5 avec les 2 traces de l'ancien ; après émission, `header_json.invoice_date_history` de la facture émise (immuable, trigger) contient ces 2 traces étrangères. (b) saisie n° 18 supprimée ; la nouvelle saisie n° 18 affiche dans « historique des corrections » celui de la saisie supprimée. (c) idem possible pour `_now_issued` dans le suivi d'une note de crédit (libellé « brouillon … → émis facture X » attribué à un autre document).
- Attendu : l'historique d'un objet supprimé ne se rattache jamais à un nouvel objet ; l'en-tête figé d'une facture ne contient que sa propre histoire.
- Suspecté : `app/app.py:50-51` (schéma), `:413` (insert saisie), `:627` (insert brouillon), `:528`, `:613`, `invoice_service.py:31-32`.
- Correction minimale (vérifiée) sans migration de schéma : attribuer l'id explicitement au-dessus des ids historiques :
```diff
-   c.execute("INSERT INTO entries(work_date,project_id,...) VALUES(?,?,?,?,?,?)",(...))
+   c.execute("INSERT INTO entries(id,work_date,project_id,...) VALUES(MAX(COALESCE((SELECT MAX(id) FROM entries),0),COALESCE((SELECT MAX(entry_id) FROM entry_changes),0))+1,?,?,?,?,?,?)",(...))
+   # brouillons : v["id"]=MAX(MAX(invoices.id),MAX(invoice_date_changes.invoice_id),MAX(credit_operations.target_invoice_id))+1
```
  (le correctif propre : recréer les tables avec `AUTOINCREMENT`.)

### QA-06 — MAJEUR — axe 8 (PDF) — La description de la ligne de facture est tronquée en silence à 4 lignes sur le document émis (figé)
- Reproduction : `qa/s51_pdf_layout.py` (T8.2) : description de ≈ 450 caractères (champ sans limite de longueur côté serveur).
- Observé : seules les 4 premières lignes (~140 caractères) sont imprimées ; la fin est absente du PDF figé, aucune alerte à la saisie, au brouillon ni à l'émission.
- Attendu : limite de longueur à la saisie (ex. 140 caractères avec compteur) ou mise en page extensible ; jamais de perte silencieuse sur un document immuable.
- Suspecté : `app/pdf_layout.py:213` (`_wrap(...)[:4]`) ; `app/app.py:606` (pas de borne sur `description`).
- Correction : `if len(description)>140: raise ValueError("description trop longue (140 caractères au maximum)")` dans `draft_values`, ou supprimer le `[:4]` et décaler le bloc des totaux (`top` est déjà calculé dynamiquement).

---

### QA-07 — MINEUR — axe 1 (saisie) — Aucun contrôle de cohérence des saisies : chevauchement, doublon, > 24 h par jour, dates hors mandat/futur
- Reproduction : `qa/s10_entries.py` (T1.2 à T1.8). Observé : 09:00-12:00 puis 10:00-13:00 le même jour (même mandat, ou deux mandats différents) acceptés sans message ; saisie identique répétée acceptée ; 3 × 10 h le même jour (30 h) acceptées ; date 2030 (futur), 1999 (avant le début du mandat) et 2028 (après la fin de contrat) acceptées sans avertissement. L'import historique, lui, signale `time_overlap` et `date_suspect` : les deux chemins sont incohérents.
- Attendu : avertissement (flash) non bloquant au minimum, comme pour l'import.
- Suspecté : `app/app.py:407-419` (`entry()`), `:378-404` (`parse_entry_form`).
- Correction : après insertion, requêter les saisies du même jour (`work_date`) et `flash` si plage horaire chevauchante / somme > 24 h / date hors `[start_date, start_date+duration]` / date future.

### QA-08 — MINEUR — axe 1 — Une nouvelle saisie dans la période d'un brouillon n'avertit pas de recalculer le brouillon (la correction et la suppression le font)
- Reproduction : `qa/s11_draft_warning.py` (T1.15). Observé : « Temps enregistré : 8 h. » sans autre message ; le brouillon reste à 1 j alors que l'annexe figée contiendra 2 j (reliquat 1 j « reporté » imposé à l'émission).
- Suspecté : `app/app.py:407-419` (`entry()` n'appelle pas `draft_warning`, appelée en `:518-519` et `:551`).
- Correction : `with db() as c2: draft_warning(c2,p["id"],work_date)` après l'insertion.

### QA-09 — MINEUR — axe 1/5/2 — Perte de saisie après un refus
- Reproduction : `qa/s10_entries.py` (T1.14), `qa/s40_credits.py` (T5.24). Observé : après un refus, la saisie d'heures revient vide (redirection) ; le formulaire de note de crédit est ré-affiché sans motif ni quantité ; l'édition de brouillon et du mandat ré-affichent les valeurs de la base (pas celles tapées) — ex. `description` 1000 caractères perdue.
- Suspecté : `app/app.py:418-419` (flash + `back("time")`), `:806-815` (`credit_new` ré-affiche sans `request.form`), `:656-657`, `:341-342`.
- Correction : renvoyer `form=request.form` aux gabarits (comme `entry_edit`) ; pour la saisie, ré-afficher la page au lieu de rediriger ou mémoriser dans `sessionStorage`.

### QA-10 — MINEUR — axe 1 — Session expirée pendant une saisie : formulaire perdu puis « 405 Method Not Allowed »
- Reproduction : `qa/s12_session_expiry.py` (T1.16). La session serveur a une durée absolue de 24 h. Observé : `POST /entry` → redirection `/login?next=/entry` ; après connexion, redirection `GET /entry` → page anglaise « 405 Method Not Allowed » ; la saisie n'est pas enregistrée et rien n'en informe l'utilisateur.
- Attendu : message « session expirée, l'opération n'a pas été enregistrée » et retour à l'accueil.
- Suspecté : `app/app.py:176-182`. Correction (vérifiée) :
```diff
-   session.clear(); return redirect(url_for("login",next=request.path))
+   session.clear()
+   if request.method!="GET": flash("Session expirée : l'opération n'a pas été enregistrée. Se reconnecter puis recommencer.")
+   return redirect(url_for("login",next=request.path if request.method=="GET" else "/"))
```

### QA-11 — MINEUR — axe 9 — Une restauration remplace aussi `web_sessions` : déconnecte l'utilisateur et peut ressusciter une session révoquée
- Reproduction : `qa/s72_restore_session.py` (T9.6, T9.7). Observé : restauration d'une sauvegarde prise dans une autre session → `GET /` redirigé vers `/login` (le message de succès est perdu) ; une session supprimée (déconnexion) présente dans le fichier est réinsérée et redevient valide (≤ 24 h). Les identifiants de session valides sont aussi écrits dans le JSON téléchargeable.
- Suspecté : `app/restore_service.py:144-146` (toutes les tables sont vidées puis rechargées) et `app/app.py:1002-1011` (`/backup` exporte `web_sessions`).
- Correction (vérifiée) : exclure `web_sessions` et `login_failures` de la sauvegarde JSON et ne pas les vider dans `rebuild` :
```diff
-        for t in [t for t in schema if t not in ORDER] + [t for t in ORDER if t in schema]:
+        for t in [t for t in schema if t not in ORDER and t not in ("web_sessions", "login_failures")] + [t for t in ORDER if t in schema]:
```

### QA-12 — MINEUR — axe 4 — Factures à 0,00 CHF et factures négatives émissibles
- Reproduction : `qa/s22_zero_invoice.py` (T4.12, T4.13). Observé : mandat créé sans tarif (accepté, rate défaut 0) → facture « 2026-03 » émise à 0,00 CHF ; quantité 0,0000001 j → facture émise à 0,00 CHF ; « AUTRES » = −5 000 accepté côté serveur (le champ HTML a `min=0` mais pas le serveur) : brouillon à total −3 919,00 CHF. Une facture émise est irréversible et ne peut pas être créditée (solde 0) : le numéro est consommé.
- Suspecté : `app/billing_rules.py:122-128` (`missing_for_issue` ne contrôle pas le tarif), `app/app.py:606` (`money_field` accepte les négatifs), `:595`.
- Correction : `missing_for_issue` : ajouter `if not float(project["rate"] or 0)>0: miss.append("Tarif journalier du mandat")` ; dans `issue()` refuser si `a["ttc"]<=0` ; `money_field(...)` avec borne basse 0 pour « AUTRES ».

### QA-13 — MINEUR — axe 2 — Dépassement du bon de commande : aucun signalement à l'émission
- Reproduction : `qa/s20_invoicing.py` (T2.1, T4.3), `qa/s90_sequences.py` (séquence finale : 78,5 j facturés brut pour 70 commandés). Observé : l'alerte n'existe qu'à la création du brouillon (flash) ; la page d'émission affiche seulement « solde après émission −X j » sans bandeau ; le PDF imprime un solde contractuel négatif.
- Suspecté : `app/app.py:614-617` (`po_warning` appelé seulement `:631`, `:654`) ; `templates/issue_confirm.html`.
- Correction : bandeau `warnbox` dans `issue_confirm.html` quand `pos.po_balance_days-this_days<0 and pos.ordered_days`, et case de confirmation du dépassement.

### QA-14 — MINEUR — axe 4/6 — Reliquat « reporté » non repris par la suggestion de la facture suivante ; texte d'aide trompeur
- Reproduction : `qa/s21_issue_misc.py` (T4.8). Janvier : 10 j réalisés, 8 j facturés, reliquat 2 j « reporté ». Février : 5 j réalisés → `/suggest` propose 5 j alors que 7 j sont à facturer (la position affiche « 7 j réalisés non facturés » seulement en texte). `issue_confirm.html` promet pourtant que le reliquat reporté « apparaîtra dans le calcul de la prochaine facture ». Sans action manuelle, le reliquat se reporte indéfiniment.
- Suspecté : `app/app.py:589-590` (`suggest`), `templates/issue_confirm.html` (aide « Reporté »).
- Correction : ajouter au JSON `carried_days` et une case « inclure les 2 j reportés » préremplissant la quantité ; ou corriger le texte d'aide.

### QA-15 — MINEUR — axe 4 — Émettre une période antérieure après une période plus récente : reliquat « facturé d'avance » trompeur
- Reproduction : `qa/s90_sequences.py` (T4.9). Mars émis, puis février : l'écran affiche « Reliquat −5 j facturé(s) d'avance » (les 5 j de mars comptés comme facturés pour février) et impose une décision ; le récapitulatif PDF figé de février compte aussi les jours de mars comme « facturés ».
- Suspecté : `app/billing_rules.py:221-231` (`contract(..., upto=...)` borne les heures mais pas les factures).
- Correction : borner `billed`/`offered` aux factures dont `period_to <= upto`, ou refuser/avertir l'émission hors ordre chronologique.

### QA-16 — MINEUR — axe 3 (prévision) — Note de crédit comptée dans l'année UTC du jour d'émission, pas l'année civile de Zurich
- Reproduction : `qa/s30_forecast.py` (T3.10) : note émise le 01.01.2027 à 00:30 Zurich (`2026-12-31T23:30:00` UTC) → comptée en 2026 dans « Facturé 2026 », alors que la facture est datée en local (`invoice_date`) et que le document (archive ZIP) est daté 2027.
- Suspecté : `app/forecast.py:42-46` (`substr(issued_at,1,4)`).
- Correction (vérifiée) : `y = rules.local_date(r["issued_at"])[:4]` (diff dans `patch-verified.diff`).

### QA-17 — MINEUR — axe 2 — Modifier les « heures par jour » d'un mandat facturé réécrit rétroactivement les jours réalisés et crée un reliquat fictif
- Reproduction : `qa/s23_dayhours_numberpage.py` (T2.3b) et `qa/s20_invoicing.py` (T2.3). 32 h = 4 j facturés (8 h/j) ; passer à 7,5 h/j sans nouvelle saisie : « réalisé non facturé » 0,267 j ; la facture figée annonçait 4 j réalisés. Message : « Les factures déjà émises conservent les données figées » (vrai) sans avertir que la position du mandat change.
- Suspecté : `app/app.py:330-342` (`project_edit`) ; `billing_rules.py:221-238`.
- Correction : refuser la modification de `day_hours` (et de `ordered_days` < jours facturés) dès qu'une facture émise existe, ou afficher un avertissement explicite avec confirmation.

### QA-18 — MINEUR — axe interface — Messages techniques ou trompeurs
- Reproductions : `qa/s20_invoicing.py` (T2.4, T2.5, T2.6), `qa/s21_issue_misc.py` (T4.7), `qa/s80_import.py`.
  - Nom de mandat en double : « Projet non enregistré : UNIQUE constraint failed: projects.name » (aussi à la modification : « Mandat non modifié : UNIQUE constraint… ») — `app/app.py:326`, `:341`. Correction vérifiée : `except sqlite3.IntegrityError: flash("… un mandat porte déjà ce nom.")`.
  - Durée de mandat 0 ou −5 : remplacée par 1 mois sans message (`app/app.py:308`, `max(1,…)`) → refuser (`ValueError`).
  - Émission d'un brouillon supprimé dans un autre onglet : « Émission refusée : 404 Not Found: The requested URL was not found on the server… » (`app/app.py:677-678` `abort(404)` capturé en `:728`).
  - Annulation d'import refusée : « Rollback refusé : Rollback refusé : 5 prestation(s)… » (message doublé, `app/app.py:265` + `rollback_service.py:33`).
  - À la clôture/réouverture : `closed_reason` reste renseigné après réouverture (`app/app.py:365`).

### QA-19 — MINEUR — axe 5 (notes de crédit) — Trois incohérences de saisie
- Reproduction : `qa/s40_credits.py` (T5.7, T5.10), `qa/s41_hour_unit.py` (T5.25).
  1. Note en jours avec un tarif différent de la facture (1 j à 2 000 au lieu de 1 000) acceptée : crédit de 2 000 CHF HT pour 1 j (le plafond ne contrôle que les montants) — `app/app.py:772`.
  2. Remboursement daté d'avant l'émission de la note de crédit (2020 pour une note d'octobre 2026) accepté — `credit_service.py:259`.
  3. Facture en heures (unité « heure » proposée dans l'édition d'un brouillon) : la note de crédit libelle « Jours crédités » / « Tarif (CHF/j) » alors que la quantité et le tarif sont en heures (risque d'erreur ×8) — `templates/credit_new.html:21`.
- Correction : 1. refuser `unit_rate != inv.unit_rate` en mode jours ; 2. refuser `executed_on < local_date(cn.issued_at)` ; 3. libeller selon `inv.unit`.

### QA-20 — MINEUR — axe 7 — L'import historique accepte un mandat clôturé
- Reproduction : `qa/s81_import_closed.py` (T7.i5). Observé : « Import validé : 1 prestation(s) ajoutée(s) » dans un mandat clôturé, alors que la saisie manuelle et le brouillon sont refusés ; la position du mandat change après la clôture (la ligne importée ne peut ensuite être retirée que par annulation du lot).
- Suspecté : `app/historical_import.py:60-62` (aucun contrôle de `active`) ; `app/app.py:369-373` (`active_project`).
- Correction : ajouter une anomalie bloquante `project_closed` à `validate`.

---

### QA-21 — CONFORT — axe 8 — PDF : débordement de texte hors de la page A4 (page 1)
- Reproduction : `qa/s51_pdf_layout.py` (T8.1). Adresse de facturation et raison sociale légale longues (> ~55 caractères par ligne), libellé « AUTRES » long, conditions de paiement longues : textes imprimés au-delà du bord droit (jusqu'à x = 1053 pt pour 595 pt de large). La raison sociale légale est de plus imprimée en double quand elle n'est contenue qu'en partie dans l'adresse.
- Suspecté : `app/pdf_layout.py:204-205` (`lines` sans retour à la ligne), `:235`, `other_label`.
- Correction : passer ces blocs par `d.wrap(...)` (la fonction existe) avec la largeur de colonne.

### QA-22 — CONFORT — axe 8 — Annexe : texte dégradé (troncature « … », sauts de ligne fusionnés, glyphes absents)
- Reproduction : `qa/s50_annex_pdf.py` puis `pdftotext -layout qa/out/inv3.pdf`. Observé : motif tronqué à 133 pt avec « … » (« Préparation CHF 1’250.– budget … ») ; une description contenant un saut de ligne (cellule Excel importée : `s80_import.py` conserve `\n`) s'imprime « équipesuite de ligne » ; l'émoji ☕ disparaît (pas de glyphe Carlito). Les heures par ligne sont arrondies à 2 décimales (0,33 × 3 ≠ total 1,00 ; déjà connu, t08).
- Suspecté : `app/pdf_layout.py:304`, `:73`.
- Correction : remplacer `\s+` par un espace à l'enregistrement/import ; envisager le retour à la ligne dans la colonne Motif.

### QA-23 — CONFORT — axe 1 — Pas de saisie à cheval sur minuit ; durée naïve aux changements d'heure
- Reproduction : `qa/s10_entries.py` (T1.1), `qa/s13_dst.py`. 22:00-02:00 refusé (« l'heure de fin doit être postérieure ») : il faut scinder en deux saisies ; 01:30-03:30 le 29.03.2026 (passage à l'heure d'été) enregistré 2 h (1 h écoulée) et le 25.10.2026 enregistré 2 h (3 h écoulées).
- Suspecté : `app/app.py:388-390`.
- Correction : accepter fin < début comme « lendemain » avec scission automatique à minuit ; documenter/avertir pour les 2 dimanches de changement d'heure.

### QA-24 — CONFORT — axe 4/interface — Divers
- Reproductions : `qa/s23_dayhours_numberpage.py` (T4.14), `qa/s54_zip.py`.
  - Le numéro annoncé sur la page d'émission (« 2026-06 ») peut différer du numéro attribué (« 2026-06-2 ») si une autre facture du mois est émise entre-temps ; seul le message de succès donne le bon numéro (`app/app.py:683`, `:713`).
  - `/archive.zip?year=1999` renvoie un ZIP vide sans message ; le brouillon créé n'est visible que dans l'onglet « Factures émises » (le flash « Brouillon créé » ne renvoie pas vers lui) ; l'onglet « Édition des factures » ne liste pas les brouillons.

### QA-25 — CONFORT — axe 1 — Concurrence deux onglets : dernier écrit gagne sur la correction d'une saisie
- Reproduction : `qa/s13_dst.py`. Deux formulaires d'édition chargés avant enregistrement : le second écrase le premier sans alerte (les deux versions restent dans `entry_changes`). Corrections de saisie : ajouter un jeton de version (`created_at`/hash caché) comparé à la sauvegarde.

---------------------------------------------------------------------------------------------------

## DÉFAUTS SEULEMENT SUSPECTÉS (lecture du code ; non reproduits ou limites déjà documentées)

- **QA-S1 (mineur, axe 7)** — La restauration JSON accepte un fichier qui **ajoute** des lignes à `invoice_annex_entries` d'une facture émise : confirmé par exécution (`qa/s74_restore_additions.py`, T7.r12 : 10 lignes liées pour 9 dans l'annexe figée, la saisie ajoutée devient verrouillée) mais limite déjà documentée (OPERATIONS §4, fichier non signé). Correction : dans `restore_service.validate`, exiger pour chaque snapshot `{ids de annex_json} == {entry_id liés}` ; ajouter un trigger `BEFORE INSERT ON invoice_annex_entries WHEN invoice déjà snapshotée`.
- **QA-S2 (mineur, axe 5)** — `credit_service.target_candidates` / `legal_identity` lisent l'identifiant juridique **courant** du mandat pour un brouillon : après une imputation réservée sur un brouillon, modifier l'identifiant juridique du mandat de ce brouillon contourne la règle « même client juridique » (non reproduit).
- **QA-S3 (mineur, axe 7)** — Les contrôles de plafond des opérations de crédit (remboursement/imputation ≤ solde) ne sont qu'applicatifs : `INSERT INTO credit_operations … amount=1e9` direct est accepté par SQLite (reproduit en SQL, `qa/s60_immutable.py`, mais seul le code applicatif écrit). Les tables `audit`, `settings` et `projects` n'ont aucun trigger d'append-only (UPDATE/DELETE direct acceptés). Durcissement, pas défaut d'usage.
- **QA-S4 (confort, axe 8/9)** — Taille des PDF figés : l'annexe cumulative fait croître chaque PDF avec la durée du mandat (taille d'archive quadratique) ; 120 factures = 14,3 Mo de PDF, ZIP 10 Mo, JSON 35 Mo (`s96_perf.py`) ; temps d'émission < 0,7 s et accueil 0,11 s : aucun problème de performance observé.
- **QA-S5 (info, axe 3/4)** — Unité « heure » : coût horaire = tarif/h-par-jour stocké en flottant ; l'audit calculs (`out_t01_amounts.txt`) a déjà mesuré 1 537 écarts d'un centime sur 400 000 cas pour les factures en heures (non rejoué).

---------------------------------------------------------------------------------------------------

## ZONES TESTÉES SANS DÉFAUT (nombre de contrôles exécutés)

| Zone | Scénarios | Résultat |
|---|---|---|
| Numérotation mensuelle concurrente (8 fils, 24 brouillons, 6 mandats, mois identique) | 1 (24 émissions) + 2 onglets | aucun doublon ni trou ; deuxième onglet bloqué par le contrôle de reliquat (`s21`) |
| Séquence réaliste de 8 mois (saisies aléatoires, arrondis, AUTRES, reliquats offerts/reportés, saisies tardives, notes de crédit) | 1 séquence, 8 factures, reliquat recalculé indépendamment à chaque émission | 0 écart ; annexes, jours cumulés et positions figées cohérents (`s90`) |
| Annexes cumulatives figées (3 factures, saisie tardive, >21 lignes/mois → pagination « suite ») | 17 contrôles | `annex_json` = lignes liées ; annexe N ⊇ annexe N−1 ; jours réalisés figés = heures/h-par-jour ; saisies annexées non supprimables (`s50`) |
| Prévision (forecast) : mandat standard, PO épuisé/dépassé, mandat échu, clos, début futur, sans date, durée 0, 5 pages du tableau de bord | 15 contrôles | somme des mois = jours restants × tarif ; aucun montant négatif (`s30`) |
| Notes de crédit : partielles (jours/montant/AUTRES), totale, plafonds, VAT de clôture, remboursements partiels, annulation + remplacement, compensation sur brouillon, baisse du brouillon, suppression du brouillon imputé, crédit total refusé après compensation, client juridique différent | 30 contrôles | TTC crédité = facture ; tous les plafonds refusés ; pages `/credit/*` toutes en 200 (`s40`) |
| Déclencheurs d'immuabilité SQLite (22 UPDATE/DELETE/INSERT interdits) + routes UI sur document émis (édition, suppression, ré-émission, correction de saisie annexée, modification du mandat) | 27 contrôles | tous refusés ; PDF figé inchangé après modification du mandat (`s60`) |
| Restauration JSON : aller-retour sur base vide, 18 tables identiques, 9 PDF identiques octet à octet, 8 falsifications (quantité, suppression, PDF, PDF+hash, saisie annexée, opération de crédit, note, en-tête), restauration d'une sauvegarde antérieure à une émission | 36 + 2 contrôles | falsifications et pertes d'émis toutes refusées, base inchangée (`s71`, `s72`) |
| Sauvegarde SQLite : intégrité, FK, 17 tables identiques, empreintes des PDF | 17 contrôles | 0 écart (`s73`) |
| Archive ZIP (SHA256SUMS, index, PDF identiques aux copies figées) | 4 contrôles | conforme (`s54`) |
| PDF : montants imprimés = base (facture, cible avec imputation « NET À PAYER », 3 notes, annulation), caractères accentués/CHF/« »/’ rendus, hash figé stable, 120 factures en 28 s | 16 montants + 12 contrôles | conforme sauf QA-04/06/21/22 |
| Import → annulation de lot refusée après émission, saisie importée non supprimable, ligne antérieure à une facture refusée | 4 contrôles | conforme (`s80`) |
| Fuzzing de toutes les routes (≈ 1 500 requêtes : valeurs aberrantes, dates extrêmes, identifiants énormes, injections) | 1 contrôle global | 0 erreur 500, 0 exception (`s95`) |
| Clôture/réouverture de mandat, saisie sur mandat clos, brouillon refusé, verrou de saisie | 6 contrôles | conforme |
| Performance (7 180 saisies, 120 factures, ZIP 10 Mo) | 1 | accueil 0,11 s, émission ≤ 0,7 s |

Total : 154 contrôles réussis ; 45 échecs = 42 manifestations de défauts + 3 artefacts de test.

## Fichiers joints (dossier `qa/`)
`run.sh` (lanceur conteneur jetable), `qa.py`/`harness.py` (outils), scripts `s10`…`s97`, journaux `logs/`, PDF de test `out/`, extraction de référence `src-rc10/`, copie patchée `src-patched/`, diff vérifié `patch-verified.diff` (QA-01, 02, 03, 05, 10, 11, 16, 18-partiel ; les journaux après patch sont dans `logs-patched/`).
