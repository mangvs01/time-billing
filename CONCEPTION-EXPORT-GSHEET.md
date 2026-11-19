# Export Google Sheet — relevé de structure (2026-10-07, préparation, rien n'est développé)

Décision utilisateur `billing-import-rule` (ARCHITECTURE_REFORMULATED, 2026-10-07) : import initial unique, ensuite tout passe par Billing,
**export Google Sheet à la demande via un bouton**, structure et logique du classeur inchangées. Mécanisme du bouton en attente :
Decision Center `billing-gsheet-export-mechanism` (A = .xlsx téléchargé et importé à la main dans Google Sheets, recommandé ; B = API Google).

## Structure du classeur de base (« /root/Time sheet CP.xlsx », lu en lecture seule sur une copie, conteneur sans réseau)
- 23 onglets : 21 mensuels (`JAN` … `DEC` pour 2025 — `JULY` pour juillet —, puis `JAN 26` … `SEPT 26`) et 2 onglets de suivi (`SUIVI 2025`, `SUIVI 2026`).
- Onglet mensuel : titre « Feuille de temps » (B1), dates de début/fin de période en B2/C2 (copie parfois non mise à jour : `SEPT 26`!B2 = 01.06.2026),
  « Total des heures de travail du mois » (B3) = `=SUM(FeuilleDeTemps…[Heures de travail])` (B4).
- Tableau Excel « FeuilleDeTemps… » (nom différent par onglet), en-tête ligne 5 : `Date(s)` · `Motif` · `Projet` · `Numéro de projet` (absent de `FEV`)
  · `Heure début` · `Heure fin` · `Heures de travail` (+ `Colonne1` sur MAR/APR/MAY/JUL/AUG/SEPT 26 : notes, cf. A-01).
- `Heure début` / `Heure fin` : **heures décimales** (9, 10, 13.25, 16.5…), format `0.00` ; `Heures de travail` = formule
  `=[@[Heure fin]]-[@[Heure début]]` (références structurées). Conforme à la règle A-03 (partie décimale × 60 = minutes).
  Les saisies sans horaires ont une durée tapée à la main dans `Heures de travail`.
- À droite de chaque onglet : un second tableau « Tableau… » récapitulatif `PROJET` / `TOTAL H` (/ `TOTAL J` en 2026).
- `SUIVI 2026` (« Tableau7 », en-tête ligne 2) : `PROJET` · `Dates` · `Client` · `Num projet` · `PO` · `NB J PO` · `NB J ` · `TARIF` ·
  `TOTAL` (= TARIF × NB J) · une colonne par facture (`Facture 16/02`, `Facture 31/03`, …), montants en CHF. `SUIVI 2025` : même idée, colonnes dans un autre ordre.

## Points à trancher avec l'utilisateur une fois le mécanisme choisi (aucun n'est décidé ici)
1. Périmètre : seulement les onglets mensuels (saisies), ou aussi les onglets SUIVI (factures Time Billing + historiques validées) ?
2. Onglets : un onglet par mois de saisie présent dans Billing, nommés comme dans le classeur (`OCT 26`, …) ?
3. Heures : `Heure début` / `Heure fin` réécrites en heures décimales (14:09 → 14.15) pour garder la formule d'origine ; les saisies sans horaires gardent leur durée.
4. `Colonne1` : reprise telle quelle pour les lignes importées (selon les réponses A-01), vide pour les nouvelles saisies ?

## Mise en œuvre (2026-10-07 ~07:50 UTC, non déployée)
- Mécanisme tranché : `billing-gsheet-export-mechanism` = DOWNLOADABLE_EXCEL. Route `GET /export/classeur.xlsx` (connexion requise, ligne d'audit
  `gsheet_export_downloaded`), bouton dans l'onglet Migration ; générateur `app/gsheet_export.py` ; tests `tests/test_gsheet_export.py`.
- Contenu actuel = option A recommandée : onglets mensuels seulement (noms du classeur), saisies dans leur mois de prestation, Colonne1 vide.
  Points 1-4 ci-dessus soumis à l'utilisateur : Decision Center `billing-gsheet-export-scope` (A / B = + onglets SUIVI / C = onglet d'origine).
- Mesure sur copie des données du staging : 21 onglets, 2 247 saisies, 1 934,4987 h = Billing ; 2 239 formules fin − début, 8 valeurs (durée
  déclarée ≠ horaires, durée sans horaires, passage de minuit) ; A et C identiques sur les données actuelles ; 8 onglets diffèrent du classeur
  (décisions d'import : doublons, lignes de total, corrections R1).
- Écart de structure assumé : le récapitulatif a partout les 9 colonnes des onglets récents (JAN–FEV 2025 en avaient 7) ; formules en références
  A1 (`=G6-F6`) plutôt que structurées, pour un import fiable dans Google Sheets (même calcul).

## Option B — onglets SUIVI (2026-10-07 ~09:00 UTC, non déployée)
- Décision utilisateur `billing-gsheet-export-scope` = **B** (08:39 UTC) : A + onglets SUIVI reconstruits depuis Billing. Choix techniques tracés :
  decision-log-agent `billing-agent-20261007085349`.
- Un onglet « SUIVI AAAA » par année, après le dernier onglet mensuel de l'année (ordre du classeur). Colonnes de SUIVI 2026 pour toutes les années
  (HT en CHF, 2025 compris) : PROJET · Dates · Client · Num projet · PO · NB J PO · NB J · TARIF · TOTAL · une colonne par date de document · Statut.
- Documents = ceux du « Facturé » de Billing : factures émises (HT prestation, date de facture, D9), notes de crédit émises non annulées (colonne
  « Note de crédit jj/mm », négatif, jour de Zurich de l'émission), factures historiques VALIDÉES (date de facture). NB J = jours de ces documents ;
  TOTAL = somme des colonnes de la ligne ; ligne « CA » ; Statut TERMINE si mandat clôturé. Lignes : mandats ayant un document dans l'année, plus
  tous les mandats ouverts dans l'onglet de l'année en cours.
- Différence assumée avec le classeur : le TOTAL du classeur est parfois un montant prévu (TARIF × NB J PO) ; ici TOTAL = facturé.
- Mesure (copie du staging, 24 historiques validées en simulation) : `journaux/export-suivi-20261007/LISEZMOI.txt` — 24/24 cellules identiques,
  CA = Billing au centime, recalcul LibreOffice sans erreur. Tests : `tests/test_gsheet_export.py` (classe Suivi).
