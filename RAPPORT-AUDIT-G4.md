# RAPPORT D'AUDIT G4 — factures historiques, période / annexe, dashboard, PDF
Date : 2026-10-05 (nuit, ~23:30 UTC). **Lecture seule** : aucune donnée, aucun code applicatif, aucun staging, aucune production modifiés par cet audit.
Outils reproductibles : `audit/g4/rapprochement_suivi.py`, `audit/g4/exclusions_import.py`, `audit/g4/rapport_tables.py` (sorties CSV/JSON dans `audit/g4/sortie/`).

## 0. Résumé en 10 lignes
1. **Le dashboard est faux pour tout mandat déjà facturé hors application, et la cause est structurelle** : l'application n'a *aucun* concept de facture historique externe. « Jours facturés » = factures émises *dans* l'application (0 aujourd'hui), donc « Réalisé non facturé » = tout le réalisé.
2. Sur les **19 mandats clôturés (TERMINE)** : 214,03 j réalisés, **205,63 j déjà facturés au SUIVI (133 659,50 CHF)**. L'application affiche 214,03 j « réalisés non facturés » ; la réalité selon le classeur est **8,40 j nets** (11,11 j non facturés − 2,71 j facturés en plus du réalisé importé).
3. « Solde contractuel » des mandats clôturés : l'application affiche **165,34 j** de PO restants ; en comptant l'historique : **−40,29 j** (8 mandats ont été facturés au-delà de leur PO, pour 45,16 j).
4. KPI « Facturé 2026 » : 0 CHF dans l'application ; le classeur : **66 423,50 CHF** de factures 2026 certaines (+4 550 CHF ambigus) ; 2025 (non affiché) : **86 636 CHF** dont 19 400 « AL Jan-Mar » sans mandat.
5. Tes 9 exemples (ASN 2025, ERA 2025, SMM, EHRA, EAU, STC GEM Avril, EUROPCR 2026, EULAR, CIRSE 2026) sont **confirmés à la cellule près** dans `SUIVI 2026` (tableau §3).
6. **Les « 2 j facturés » d'EUROPCR 2027 ne sont PAS une facture historique** : c'est la quantité tapée dans le brouillon n°1 (`qty = 2`, description « test »). Le SUIVI ne contient aucune facture pour ce mandat.
7. **L'annexe du brouillon est incohérente avec sa période par construction** : le générateur annexe *toutes* les saisies du mandat jusqu'à la fin de période (cumul depuis le début, comme la vraie facture de référence), sans borne basse ni distinction « détail de période / cumul ». Le brouillon n°1 (période 03.09 → 31.10.2026) n'a **aucune** saisie dans sa période : les 3 feuilles affichées sont du cumul antérieur.
8. Le PDF **émis** est déjà fidèle à la vraie facture 2026-09 (positions de la page 1 à ≤ 1,5 pt, sauf pied de page −2,8 pt et remerciement +4,8 pt ; aucun placeholder) ; écarts réels : **logo absent (il est dans ton modèle .ods)**, ligne « Période facturée » ajoutée (absente du modèle), page de synthèse enrichie, césure de l'adresse.
9. Un fait métier à trancher par toi : **les jours facturés du SUIVI incluent les 31 « doublons exacts » (21,75 h) exclus à l'import** (ASN 2025 : 9,83 j facturés = 9,83125 j du classeur, l'application a 9,30 j).
10. Architecture proposée (§9) : registre **additif** de factures historiques (provenance cellule par cellule, jamais éditable comme facture, validation explicite), indicateurs et annexe qui distinguent réalisé / facturé historique / facturé Time Billing / facture courante / avoirs / solde, annexe en deux sections (période / cumul), 12 contrôles bloquants avant émission. **Rien n'est chargé tant que tu n'as pas validé le tableau.**


## 1. CURRENT STATE CHECKPOINT (phase A)
| Élément | État |
|---|---|
| Branche / HEAD | `design-liquid-glass-rc14` / **`e8953b2`** (rc19 non déployé : `4191c8e` + 3 correctifs de relecture, 404/404 tests) — local, rien de poussé |
| Dernier commit sûr avant ce travail | `4191c8e` (rc19) ; `969dd8c` (rc18, celui qui tourne sur le staging) |
| Travail terminé | rc19 (code + tests + relecture de code 3 angles) ; synthèse `REVUE-CODE-RC19.md` |
| Modifications non commitées | uniquement l'audit G4 (`audit/g4/*`, ce rapport) + `journaux/fonc/staging-sha-debut.txt` (non suivi, d'une session précédente, conservé) |
| Migrations en cours | aucune ; le staging est en schéma rc18 |
| Staging (:8092) | **9.2-rc18**, sain, 2 247 saisies / 1 934,4987 h (identiques ligne à ligne à `pre-mandats-20261005T090824Z`), 24 mandats (19 clôturés / 5 actifs). **Tu y travailles** : connexion 22:37 UTC, **brouillon de facture n°1** créé 22:42 (EUROPCR 2027, 2026-09-03 → 2026-10-31, 2 j, tarif 0, « test ») — conservé, jamais arrêté ni redéployé |
| Sauvegarde du checkpoint | `/root/backups/time-billing-v9-staging/checkpoint-g4-20261005T225128Z.db` (+ `.sha256`, intégrité ok) |
| Production (:8091) | non touchée : base `bd31f410…` (vide : 0 mandat, 0 saisie, 0 facture), conteneur `0b25a343…` depuis le 02.10 |
| Prochain point de reprise | décisions du §13 → phase D (code) sur le staging uniquement |

## 2. Sources effectivement lues
- **Classeur `/root/Time sheet CP.xlsx`** (sha256 `c93c610c…`, 304 204 octets) : **23 feuilles sur 23, cellule par cellule (valeurs ET formules, 3 196 formules)** — 12 feuilles 2025 (JAN…DEC), 9 feuilles 2026 (JAN 26…SEPT 26), **SUIVI 2025**, **SUIVI 2026** ; 42 tableaux mensuels (feuille de temps + récapitulatif par projet) + 2 tableaux SUIVI ; 3 noms définis (tous `#REF!`) ; aucune feuille/ligne/colonne masquée ; aucun commentaire. Seules mentions de facturation hors SUIVI : `MAR 26!S13` « Invoice 7 days sent » (STC GEM) et `MAR!C48` « Meeting suivi factures » (une saisie de temps). **Aucune note de crédit, aucun avoir, aucun numéro de facture** dans le classeur : seules les en-têtes « Facture jj.mm » donnent des dates.
- **`Facture-reelle-reference-2026-09.pdf`** (13 p., sha `40b896a8…`) : texte, rendu image, positions de mots. C'est la facture réelle CIRSE 2026 (01.10.2026, 8 j × 650 = 5 200 CHF) : p.1 facture, p.2–12 une feuille de temps par mois nov-25 → sept-26 (annexe **cumulative depuis le début du mandat**), p.13 extrait du SUIVI (NB J PO 12, NB J 8,15).
- **`Facture-modele-reference.ods`** (sha `c3e6dc6f…`) : converti en PDF dans un dossier temporaire (1 page) ; contient `media/image1.png` = **le logo Huddl** (500×500).
- **Base staging** (copie cohérente du checkpoint), **code rc18 (`969dd8c`) et rc19 (`e8953b2`)**, bases prod / V8 / V7 (lecture immuable : prod vide ; V8/V7 = 1 mandat de test), rapports d'import précédents (`import/…`, dont registre A1).
- **Aucun autre classeur ni dossier de factures** n'existe sur le serveur (recherche `.xlsx/.ods/.xls/.xlsm/factur*/invoice*`).

## 3. Résultats du rapprochement (G4-1)
Légende : *J = jours* ; « J réalisés classeur » = Σ des tableaux récapitulatifs mensuels du classeur (**doublons inclus**) ; « Réalisé non facturé selon classeur » = J réalisés app − J facturés source (**négatif = facturé en plus du réalisé importé**) ; « Écart affiché − classeur » = ce que le dashboard gonfle (= jours facturés au SUIVI, car « facturé application » = 0). Catégories : **A** facturé au SUIVI / 0 facturé dans l'app ; **B** TERMINE + clôturé + réalisé non facturé gonflé ; **C** réalisé > facturé ; **D** plusieurs factures ; **E** notes de crédit ; **F** montant sans quantité ; **G** ambigu (voir §4).

| Projet (source) | Client | Statut | NB J PO | J réalisés classeur | J facturés source | Montant facturé (CHF) | Réf. / date facture | Mandat application | J réalisés app | J facturés app | NC | Réalisé non facturé app (affiché) | Réalisé non facturé selon classeur | Écart affiché − classeur | Cat. | Commentaire |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AL Jan-Mar |  | TERMINE |  |  | 0 | 19 400,00 | (TOTAL de la ligne, sans colonne de facture) (SUIVI 2025!ligne 3: 19400.0 CHF) | (aucun) | 0 | 0 | 0 |  |  |  | AF | 19 400 CHF (= 6 900 + 12 500) sans jours, sans tarif, sans date de facture, sans mandat ni saisie dans l'application : facturé 2025 non rattachable (F/G) |
| ASN 2025 | CSL | TERMINE | 10 | 9,831 | 9,83 | 6 389,50 | Facture 16/02 (SUIVI 2026!J3: 6389.5 CHF) | ASN 2025 | 9,3 | 0 | 0 | 9,3 | -0,53 | 9,83 | AB | facturé 9,83 j = cumul du classeur (9,83125 j) ; l'application n'a que 9,30 j : les 4,25 h (0,53 j) des doublons A1 exclus à l'import sont facturées |
| CIRSE 2025 | BSCI | TERMINE | 10 | 9,644 | 9,5 | 6 175,00 | Facture 03.10 (SUIVI 2025!N8: 9.5 j) | CIRSE 2025 | 9,331 | 0 | 0 | 9,331 | -0,169 | 9,5 | AB | facturé 9,5 j ; app 9,33 j ; 1,75 h de doublons A1 exclues (0,22 j) |
| CIRSE 2026 | BSCI | TERMINE | 12 | 8,025 | 8 | 5 200,00 | Facture 01/10 (SUIVI 2026!Q12: 5200 CHF) | CIRSE 2026 | 8,244 | 0 | 0 | 8,244 | 0,244 | 8 | ABC | = facture de référence 2026-09 (8 j, 5 200 CHF, PDF fourni, 01.10.2026) ; app 8,24 j (65,95 h) vs 8,15 j sur la facture (65,2 h : 0,75 h d'octobre 2025 absentes de ses feuilles annexées) |
| EAHAD |  | TERMINE | 1 | 1,062 | 1 | 650,00 | Facture 16.06 (SUIVI 2025!K13: 1 j) | EAHAD | 1,062 | 0 | 0 | 1,062 | 0,062 | 1 | ABC | 1 j facturé = PO 1 j ; réalisé 1,06 j |
| EAU 2026 | BSCI | TERMINE | 10 | 14,55 | 14 | 9 100,00 | Facture 31/03 (SUIVI 2026!K7: 9100 CHF) | EAU 2026 | 14,55 | 0 | 0 | 14,55 | 0,55 | 14 | ABC | 14 j facturés pour un PO de 10 j (+4 j) ; 4 h (0,5 j) saisies après la facture (clôture du 13.04.2026) |
| ECIO 2025 | BSCI | TERMINE |  | 2,694 | 0 | 0 | — | ECIO 2025 | 2,663 | 0 | 0 | 2,663 | 2,663 | 0 | - | non facturé selon le SUIVI (pas de PO, pas de tarif) — décision C3 : « non facturé, tarif historique non retrouvé » |
| EHRA 2026 | BSCI | TERMINE | 10 | 19,531 | 18 | 11 700,00 | Facture 11/05 (SUIVI 2026!N6: 11700 CHF) | EHRA 2026 | 19,531 | 0 | 0 | 19,531 | 1,531 | 18 | ABC | 18 j facturés pour un PO de 10 j (+8 j) ; réalisé 19,53 j : 1,53 j (12,25 h) non facturés, dont 2,5 h postérieures à la facture |
| Endovascular Summit | BSCI | TERMINE | 6 | 12,875 | 12,9 | 8 385,00 | Facture 09.04 (SUIVI 2025!I4: 5.2 j)<br>Facture 16.06 (SUIVI 2025!K4: 7.7 j) | Endovascular Summit | 12,875 | 0 | 0 | 12,875 | -0,025 | 12,9 | ABD | 2 factures (5,2 j + 7,7 j) pour un PO de 6 j (+6,9 j) ; réalisé 12,875 j |
| ERA 2025 + ERA 2025 (cloture) | CSL Vifor | TERMINE | 5 | 16,531 | 14,56 | 9 464,00 | Facture 12.05 (SUIVI 2025!J9: 5.6 j)<br>Facture 14.07 (SUIVI 2025!L9: 8.4 j)<br>Facture 16/02 (SUIVI 2026!J4: 364.00000000000006 CHF) | ERA 2025 | 16,406 | 0 | 0 | 16,406 | 1,846 | 14,56 | ABCD | 3 factures (5,6 j + 8,4 j en 2025, 0,56 j = 364 CHF dans la ligne 2026 « ERA 2025 (cloture) ») pour un PO de 5 j ; réalisé 16,41 j. Le chiffre de 11,66 j « réalisé non facturé » donné précédemment ignorait la ligne 2026 |
| ERA 2026 | CSL | TERMINE | 4 |  | 0 | 0 | — | (aucun) | 0 | 0 | 0 |  |  |  | F | PO 4 j, 0 j réalisé, TERMINE, aucune facture, aucun mandat dans l'application (0 saisie) |
| EULAR 2026 | CSL | TERMINE | 10 | 13,625 | 12,5 | 8 125,00 | Facture 16/07 (SUIVI 2026!P10: 8125 CHF) | EULAR 2026 | 13,625 | 0 | 0 | 13,625 | 1,125 | 12,5 | ABC | 12,5 j facturés pour un PO de 10 j ; réalisé 13,63 j : 1,13 j non facturé |
| EUROPCR 2025 | BSCI | TERMINE | 10 | 21,238 | 19,4 | 12 610,00 | Facture 09.04 (SUIVI 2025!I5: 6.6 j)<br>Facture 12.05 (SUIVI 2025!J5: 5.3 j)<br>Facture 16.06 (SUIVI 2025!K5: 7.5 j) | EUROPCR 2025 | 21,238 | 0 | 0 | 21,238 | 1,837 | 19,4 | ABCD | 3 factures (6,6 + 5,3 + 7,5 j) pour un PO de 10 j ; réalisé 21,24 j ; 7,75 h postérieures à la dernière facture |
| EUROPCR 2026 | BSCI | TERMINE | 15 | 17,469 | 17,3 | 11 245,00 | Facture 16/06 (SUIVI 2026!O9: 11245 CHF) | EUROPCR 2026 | 17,469 | 0 | 0 | 17,469 | 0,169 | 17,3 | ABC | 17,3 j facturés pour un PO de 15 j ; réalisé 17,47 j (1 h après la facture) |
| NC STC June | BSCI | TERMINE | 8 | regroupé | 10,5 | 6 825,00 | Facture 16.06 (SUIVI 2025!K7: 10.5 j) | NC STC June | 10,694 | 0 | 0 | 10,694 | 0,194 | 10,5 | ABC | 10,5 j facturés pour un PO de 8 j ; réalisé 10,69 j |
| NC STC Sept | BSCI | TERMINE | 14 | regroupé | 13,8 | 8 970,00 | Facture 30.09 (SUIVI 2025!M14: 13.8 j) | NC STC Sept | 12,344 | 0 | 0 | 12,344 | -1,456 | 13,8 | AB | 13,8 j facturés ; app 12,34 j : 9,75 h de doublons A1 exclues (1,22 j). Σ des 2 factures NC STC = 24,3 j ≈ cumul du classeur 24,35 j ; app 23,04 j |
| NHAF 2026 | BSCI |  | 16 | 9,55 | 0 | 0 | — | NHAF 2026 | 9,525 | 0 | 0 | 9,525 | 9,525 | 0 | - | actif, aucune facture au SUIVI ; PO 16 j |
| PCR LV 2025 | BSCI | TERMINE | 6,34 | 6,344 | 6,34 | 4 121,00 | Facture 15/12 (SUIVI 2025!P11: 6.34 j) | PCR LV 2025 | 6,344 | 0 | 0 | 6,344 | 0,004 | 6,34 | AB | facturé = PO = réalisé (6,34 j) |
| PCR LV 2026 | BSCI |  | 9 | 0,656 | 0 | 0 | — | PCR LV 2026 | 0,656 | 0 | 0 | 0,656 | 0,656 | 0 | - | actif, aucune facture au SUIVI ; PO 9 j |
| Rising stars Q3 | BSCI | TERMINE | 6 | 5,938 | 6 | 3 900,00 | Facture 03.10 (SUIVI 2025!N10: 6 j) | Rising stars Q3 | 5,469 | 0 | 0 | 5,469 | -0,531 | 6 | AB | facturé 6 j = PO ; app 5,47 j ; classeur 5,94 j (3,75 h de doublons A1 exclues) |
| SMART Y90 | BSCI | TERMINE | 10 | 10,556 | 10 | 6 500,00 | Facture 27.11 (SUIVI 2025!O12: 10 j) | SMART Y90 | 10,4 | 0 | 0 | 10,4 | 0,4 | 10 | ABC | facturé 10 j = PO ; app 10,40 j ; classeur 10,56 j (1,25 h exclues dont 0,75 h d'exception OCT!93) |
| SMM 2026 | BSCI | TERMINE | 15 | 15,312 | 15 | 9 750,00 | Facture 03/04 (SUIVI 2026!L5: 9750 CHF) | SMM 2026 | 15,031 | 0 | 0 | 15,031 | 0,031 | 15 | AB | facturé 15 j = PO ; réalisé 15,03 j (1 h après la facture) |
| STC GEM Avril | BSCI | TERMINE | 7 | regroupé | 7 | 4 550,00 | Facture 27/04 (SUIVI 2026!M8: 4550 CHF) | STC GEM Avril | 7,456 | 0 | 0 | 7,456 | 0,456 | 7 | ABC | 7 j facturés = PO 7 j ; réalisé 7,46 j |
| STC GEM Oct - DM job | BSCI |  | 18 | regroupé | 7,583 | 4 550,00 | Facture 27/04 (SUIVI 2026!M15: 4550 CHF) | STC GEM Oct - DM job | 16,444 | 0 | 0 | 16,444 | 8,86 | 7,583 | AC | 4 550 CHF en colonne « Facture 27/04 » alors que TOTAL = 10 800 (18 j × 600 CHF) et que la ligne STC GEM Avril porte déjà 4 550 (7 j × 650) : doublon probable, incohérent avec le tarif 600 (= 7,58 j) — À TRANCHER, non retenu comme facture certaine |
| (absent du SUIVI) |  |  |  | 0,281 | 0 | 0 | — | EUROPCR 2027 | 0,281 | 0 | 0 | 0,281 | 0,281 | 0 | - |  |
| (absent du SUIVI) |  |  |  | 0,875 | 0 | 0 | — | MSD | 0,875 | 0 | 0 | 0,875 | 0,875 | 0 | - |  |

### 3.1 Synthèse par catégorie
- **A** (20 lignes SUIVI facturées, 0 facturé dans l'app) : 18 mandats clôturés facturés (le 19e, ECIO 2025, ne l'a jamais été) + « AL Jan-Mar » (sans mandat) + STC GEM Oct (ambigu). Total certain : **205,63 j / 133 659,50 CHF** (18 mandats clôturés) ; 2025 : 14 cellules = 67 236 CHF ; 2026 : 9 cellules certaines = 66 423,50 CHF.
- **B** : les **19 mandats clôturés** (C1) affichent « Réalisé non facturé » = réalisé (Σ 214,03 j) au lieu de 8,40 j nets, et « Solde contractuel » = PO entier (Σ 165,34 j) au lieu de −40,29 j.
- **C** (réalisé > facturé, ≥ 0,5 j) : ECIO 2025 2,66 j (jamais facturé, décision C3), ERA 2025 1,85 j, EUROPCR 2025 1,84 j, EHRA 2026 1,53 j, EULAR 2026 1,13 j, EAU 2026 0,55 j. En dessous de 0,5 j (arrondi commercial probable) : CIRSE 2026 0,24, STC GEM Avril 0,46, SMART Y90 0,40, NC STC June 0,19, EUROPCR 2026 0,17, EAHAD 0,06, SMM 0,03, PCR LV 2025 0,004. Total non facturé : **11,11 j** (le « 11,66 j » donné lors de la décision C1 omettait la ligne 2026 « ERA 2025 (cloture) », 0,56 j).
- **Facturé en plus du réalisé importé** : ASN 2025 +0,53 j, Rising stars Q3 +0,53 j, NC STC Sept +1,46 j, CIRSE 2025 +0,17 j, Endovascular +0,03 j (Σ 2,71 j) — **expliqué par les doublons A1** (cf. G-1).
- **D** : EUROPCR 2025 (3 factures), ERA 2025 (3 : 2 en 2025 + 1 dans la ligne 2026), Endovascular Summit (2) ; « NC STC » = 2 mandats pour 1 tableau du classeur ; « GEM STC » = 2 mandats pour 1 tableau.
- **E** : **aucune** note de crédit (ni source, ni application).
- **F** : « AL Jan-Mar » 19 400 CHF (=6 900+12 500), sans jours ni tarif ni date ni mandat ; STC GEM Oct 4 550 CHF sans quantité cohérente avec son tarif.
- **G** : cf. §4.

## 4. Liste complète des incohérences
**Classeur (source)**
- **S-1** `SUIVI 2025` colonne « PO diff » : formules qui ne retiennent que « Facture 09.04 » et « Facture 16.06 » → valeurs fausses pour les lignes facturées à d'autres dates (ERA 2025 : 5 au lieu de −9 ; PCR LV 2025 : 6,34).
- **S-2** `SUIVI 2026!M15` = 4 550 en colonne « Facture 27/04 » pour *STC GEM Oct – DM job* (TOTAL = 10 800 = 18 j × 600 ; la ligne *STC GEM Avril* porte déjà 4 550 = 7 j × 650) ; `M16 = SUM(M3:M15)` = 9 100 compte les deux. 4 550 ÷ 600 = 7,58 j : incohérent avec le tarif du mandat → **doublon probable, non retenu**.
- **S-3** `SUIVI 2026` : pas de total pour « Facture 01/10 » (Q16 absent) ; `I16` = 93 473,50 additionne des lignes non facturées (PCR LV 2026, NHAF 2026, STC Oct).
- **S-4** Jours facturés > jours de PO (SUIVI) : EHRA 18/10, EAU 14/10, ERA 2025 14,56/5, EUROPCR 2025 19,4/10, Endovascular 12,9/6, EULAR 12,5/10, EUROPCR 2026 17,3/15, NC STC June 10,5/8.
- **S-5** « Jours PO » des tableaux mensuels ≠ SUIVI : EAU 8 (vs 10), EHRA 8 (vs 10), EULAR 11 (vs 10), CIRSE 2026 10 (vs 12).
- **S-6** N° de PO : *NC STC Sept* = `PO-559` (= le PO de *Rising stars Q3*) au SUIVI, `PO-1169` dans les tableaux mensuels ; *SMM 2026* sans PO ni n° de projet.
- **S-7** *EUROPCR 2027* : le classeur contient n° de projet `2700091BE` (JUN–AOÛT 26) et 15 j de PO (JUL–SEPT 26), sans n° de PO ni tarif ; la cellule « Num projet » de SEPT 26 contient `0,28125` (formule pointant sur « NB J TOTAL »). L'application : PO 0 j, pas de n° de projet.
- **S-8** « J mois précédant(s) » de *GEM STC* saute de 6,7375 (MAR 26) à 15,40625 (APR 26) : +8,67 j sans saisie correspondante → cumul 32,57 j vs Σ mensuel 23,9 j.
- **S-9** *CIRSE 2026* : 2 saisies d'octobre 2025 (27 et 28.10, 0,75 h) sont dans la feuille OCT mais pas dans son récapitulatif ; la facture de référence (65,2 h = 8,15 j) ne les annexe pas ; l'application les a (65,95 h = 8,24 j).
- **S-10** Description du modèle/de la facture de référence : « Poduction PM/DM – CIRSE 2026 – **2600137BE** » (n° de projet d'EUROPCR 2026) alors que CIRSE 2026 = `2600403BE` (SUIVI et p.13 de la même facture). Faute de frappe dans le modèle ; reproduite à l'identique dans mes essais de rendu, à ne pas propager.
- **G-1 (métier, à trancher)** Les **31 doublons exacts AUG↔SEPT / FEV!28↔MAR!49 (21,75 h)** exclus à l'import (décision A1) sont **comptés deux fois par les récapitulatifs du classeur, et les jours facturés du SUIVI suivent ces récapitulatifs** : ASN 2025 facturé 9,83 j = 9,83125 j du classeur, l'application 9,30 j (les 4,25 h exclues = 0,53 j exactement) ; NC STC Sept : 9,75 h exclues ≈ +1,22 j ; Rising stars Q3 : 3,75 h ; CIRSE 2025 : 1,75 h ; SMM : 2,25 h ; SMART Y90 : 1,25 h. Si ces lignes étaient de vrais doublons, les clients ont été facturés ≈ 2,7 j (≈ 1 750 CHF) en trop ; si c'étaient des heures réelles, l'exclusion A1 sous-compte le réalisé. **Je n'y touche pas.**

**Application (rc18)**
- **P-1** Aucune facture historique : `billed_days` = factures émises dans l'app (0) pour *tous* les mandats ; « Réalisé non facturé » et « Solde contractuel » faux pour les mandats clôturés (§5).
- **P-2** KPI « Facturé 2025/2026 » et jauge « Facturé % » : 0 CHF (historique ignoré).
- **P-3** Annexe = toutes les saisies du mandat `≤ period_to` (`invoice_service.live_data`), **sans borne basse** ; aucune distinction détail de période / cumul ; ligne « Période facturée » sans lien avec les feuilles.
- **P-4** Page de synthèse : « Jours facturés » = factures émises **+ la quantité du brouillon lui-même** (tapée à la main, sans lien avec le temps) → « 2 » pour 0,28 j réalisés.
- **P-5** Aucun contrôle de cohérence avant émission (seulement champs obligatoires, total > 0, chevauchement) ; textes libres (description, note, libellé « autres ») non filtrés → « test », « Cadeau unn jour », « PUNAISE DE JOUR OFFERT » peuvent atteindre une facture émise.
- **P-6** Écarts PDF vs modèle (§7).
- **P-7** Mandat *EUROPCR 2027* incomplet alors que le classeur donne n° de projet et PO (S-7) ; tarif 0 → total 0 CHF au brouillon (l'émission est bloquée par la règle « tarif > 0 », c'est correct).

## 5. Dashboard (G4-3) — ce qu'il affiche, ce qu'il devrait afficher
Mesuré sur la copie du staging avec le code rc18 (celui que tu vois), puis comparé au classeur.
| Indicateur | Définition actuelle (code) | Affiché | Selon le classeur | Verdict |
|---|---|---|---|---|
| KPI « Facturé 2026 » | factures **émises dans l'app** − notes de crédit (HT, par année de date de facture) | 0,00 CHF | 66 423,50 CHF certains (+4 550 CHF ambigus) | faux par omission (historique ignoré) |
| KPI « Prévision restante 2026 / 2027 » | Σ (PO − facturé) × tarif des mandats **actifs**, étalé sur 12 mois | 6 762,51 + 20 287,49 = 27 050 CHF | NHAF 16 j × 650 + PCR LV 2026 9 j × 650 + STC Oct 18 j × 600 = 27 050 | cohérent *tant que ces 3 mandats n'ont rien de facturé hors app* (STC Oct : cf. S-2) |
| KPI « Réalisé non facturé » | Σ (réalisé − facturé app) des mandats **actifs** | 27,78 j | 27,78 j (aucune facture certaine sur les 5 actifs) | correct |
| Tableau « Situation synthétique » — Jours facturés | factures émises dans l'app | 0 pour les 24 | 205,63 j sur les 19 clôturés | **faux** |
| idem — Réalisé non facturé | réalisé − facturé app | Σ 214,03 j sur les clôturés | 8,40 j nets | **faux (gonflé de 205,63 j)** |
| idem — Solde contractuel | PO − (facturé app − annulé) | Σ 165,34 j | Σ −40,29 j (8 mandats > PO de 45,16 j ; 4 mandats avec reliquat de PO : ASN 0,17, CIRSE 2025 0,5, CIRSE 2026 4,0, NC STC Sept 0,2) | **faux** |
| Anneaux / barres « Avancement » | mandats actifs seulement | cohérent avec les définitions | – | correct |
La clôture C1 des 19 mandats avait neutralisé la **prévision** mais pas **leurs lignes de position** : c'est le même défaut racine (P-1), pas un bug de calcul isolé.

## 6. Période, annexe, cutoff (G4-2 / G4-3)
- **Faits** : `invoice_service.live_data` annexe `SELECT … FROM entries WHERE project_id=? AND work_date<=period_to` — cumul depuis le début, sans `period_from`. C'est exactement la pratique de la vraie facture 2026-09 (annexe = tous les mois depuis nov-25). La page de synthèse calcule les « jours réalisés cumulés » avec le même cutoff (`period_to`) mais « jours facturés » sans cutoff (toutes les factures émises + le brouillon).
- **Brouillon n°1** (EUROPCR 2027, 03.09 → 31.10.2026) : 0 h dans la période ; annexe = 26.06 (0,75 h), 14.07 (0,25 h), 21.07 (1,25 h) = cumul antérieur présenté comme feuilles de la facture ; position « Jours facturés 2 » = la quantité du brouillon ; « Jours réalisés cumulés 0,28 » ; solde « sans bon de commande » (PO 0). Ces trois nombres ne racontent pas la même histoire (exigence « CHECK 12 »).
- **Règle demandée** (G4-3) : détail de période = exactement la période ; cumul antérieur = section distincte et étiquetée. Faisable **sans changer l'annexe figée** (`annex_json` garde toutes les lignes cumulatives ; une ligne est « détail de période » si sa date ∈ [period_from, period_to], « cumul » sinon — c'est déjà la définition utilisée par l'écart post-facturation rc19). Un mois à cheval sur `period_from` est coupé en deux pages (la partie dans la période, puis le cumul).
- **Cutoff** : nouvelle facture = `period_to` ; facture historique = date de sa colonne SUIVI. « Jours facturés historiques » d'une facture = Σ des historiques **validés** dont la date ≤ `period_to` ; les factures Time Billing émises postérieurement sont exclues du calcul d'une facture antidatée (aujourd'hui incluses).

## 7. Générateur PDF vs modèle de référence (G4-4)
Comparé : facture réelle 2026-09 (13 p.), modèle `.ods` converti, rendu de l'application en mode **émis** pour les mêmes données (CIRSE 2026 : mêmes montants, PO, adresse), positions de mots mesurées à `pdftotext -bbox`.
| Élément | Modèle | Application | Écart |
|---|---|---|---|
| Page 1 : « FACTURE », Date/N°/PO, bloc Huddl, bloc client, tableau, sous-total/TVA/autres/total, remerciement, paiement, pied | – | – | positions identiques à **≤ 1,5 pt** sur 20 repères ; hors pied de page (−2,8 pt, largeur de police) et remerciement (ci-dessous) |
| « Je vous remercie… » | y = 475,0 | y = 479,8 | **+4,8 pt**, décalé par la ligne « Période facturée » |
| Ligne « Période facturée : du … au … » | **absente** | présente sous le total | à décider (§13, D-6) |
| Logo Huddl | présent | **absent** (aucun logo en Paramètres) | le logo est dans `Facture-modele-reference.ods` (`media/image1.png`, 500×500) → à charger via Paramètres (D-7) |
| Bloc client | « Avenue du Bourgmestre / Etienne Demunter 5, boîte 10 » | « …Etienne Demunter 5, / boîte 10 » | césure 1 mot plus tôt (largeur de colonne) |
| Police | polices intégrées du modèle (noms anonymisés) | Nunito Sans Light + Caladea + Carlito (approximation, travail rc4/rc7) | rendu très proche, pas identique |
| Annexe | une page par mois « Feuille de temps / mois / Total des heures de travail du mois / tableau » | identique | OK (pages "Page x of y" : modèle 2 → 12 sur 13 p. ; application x → n) |
| Dernière page | ligne du SUIVI : PROJET, Dates, Client, Num projet, PO, **NB J PO**, **NB J** | même ligne mais « Jours réalisés cumulés » à la place de « NB J » **+ bloc « Position contractuelle »** (rc7) | écart voulu (rc7) ; à restructurer selon G4-4 |
| Marqueurs de brouillon / `[Logo à fournir]` / `[À COMPLÉTER]` | – | **uniquement sur brouillon** ; vérifié : PDF émis rejoué = 0 occurrence de brouillon/logo/compléter/test/démo | OK pour les marqueurs du générateur |
| Textes libres de test (« test », « Cadeau unn jour », « PUNAISE DE JOUR OFFERT ») | – | saisis par toi dans le brouillon n°1 (description, libellé « autres », note) ; **aucun contrôle ne les arrête à l'émission** | contrôles 9/10 à ajouter (P-5) |

## 8. Causes racines
1. **RC-1** Pas de modèle de « facture historique externe » (concept 3) : `contract()` ne connaît que `invoices` (app). Toutes les anomalies de §5 en découlent.
2. **RC-2** Les indicateurs mélangent des bases différentes sans cutoff commun (temps jusqu'à `period_to`, facturé sans date) — acceptable tant que l'app était seule, faux dès qu'il existe un historique.
3. **RC-3** L'annexe cumulative a été conçue pour reproduire la vraie facture, sans notion de période de détail ni de contrôle de cohérence période ↔ feuilles ↔ position.
4. **RC-4** Aucun garde-fou de cohérence avant émission (les 12 contrôles demandés n'existent pas) ; les textes libres ne sont pas contrôlés.
5. **RC-5** La décision C1 (clôture des 19 mandats) a traité le symptôme (prévision) ; les lignes de position des clôturés restaient faussées.

## 9. Architecture corrective proposée (additive, réversible, design inchangé)
**Séparer strictement les 9 concepts de G4-2**
| Concept | Support | État |
|---|---|---|
| Saisies de temps | `entries` | existe, intact |
| Jours réalisés | calcul Σ heures ÷ h/j (jamais stocké) | existe |
| **Factures historiques externes** | **`historical_invoices` (nouvelle table)** | à créer |
| Factures Time Billing | `invoices`, `invoice_snapshots` | existe, immuable |
| Quantité facturée | `invoices.qty/unit` ; `historical_invoices.qty_days` | existe / nouveau |
| Notes de crédit | `credit_notes` | existe |
| Période facturée | `invoices.period_from/to` | existe |
| Cutoff | `period_to` (nouvelle facture) ; date de colonne SUIVI (historique) | à formaliser dans `contract()` |
| Cumul historique | `contract(upto=cutoff)` = réalisé ≤ cutoff, facturé historique ≤ cutoff, facturé app, avoirs | à corriger |

**`historical_invoices`** : `id, project_id (mandat), source_file, source_sha256, source_sheet, source_cell, source_column, invoice_date (NULL si inconnue), invoice_ref (NULL : jamais inventé), qty_days (NULL si montant seul), amount_ht, unit_rate, basis ∈ {days, amount, amount_only}, qty_derived (0/1), status ∈ {proposed, validated, rejected}, note, created_at, validated_at, validated_by, batch`. Contraintes : `UNIQUE(source_sha256, source_cell)` (jamais de doublon), suppression interdite (trigger), seuls `status/validated_*/note` modifiables (trigger, comme `entry_changes`/`invoice_variance_decisions`), chaque transition auditée. **Seules les lignes `validated` comptent** ; `proposed` n'a aucun effet sur un indicateur ni un document. Une facture historique **n'est jamais une facture éditable**, n'a pas de PDF Time Billing, ne reçoit pas de numéro, ne passe pas par `/issue`. Le PDF réel fourni (CIRSE 2026) peut être rattaché comme pièce de provenance.
**Indicateurs** : `contract()` renvoie en plus `historical_days`, `historical_amount` ; `billed_days = historique + app − avoirs` ; `unbilled`, `po_balance` en découlent ; `upto` borne temps *et* historique. Tableau du dashboard : colonnes « Facturé (historique) » et « Facturé (Time Billing) » séparées ; KPI « Facturé {année} » = historique validé + app − avoirs, sous-libellé « dont historique ». Prévision : inchangée dans sa formule (le solde de PO tient compte de l'historique).
**Annexe PDF** : section A « période facturée » (feuilles bornées à `[period_from, period_to]`), section B « cumul antérieur — information » (étiquetée page par page), dernière page : ligne SUIVI + bloc **PO / réalisés cumulés au cutoff / facturés historiques / facturés Time Billing antérieurs / facture courante / annulés par notes de crédit / solde** (le détail « historique » liste les factures : date, cellule source). `annex_json` figé et colonnes de l'en-tête figé : champs ajoutés, anciens snapshots lus avec repli (aucun PDF figé n'est jamais re-rendu).
**Contrôles bloquants (module `invoice_checks`)** : CHECK 1 détail ⊂ période ; 2 mandat des feuilles = mandat de la facture ; 3 montant = quantité × tarif (+ autres) à la décimale ; 4 TVA = mandat, n° de TVA si TVA > 0 ; 5 jours historiques issus du registre validé, jamais des heures ; 6 cumul calculé au cutoff, aucune facture postérieure comptée ; 7 avoirs en jours pris en compte ; 8 solde recalculé indépendamment = solde imprimé ; 9 aucun placeholder (`[À COMPLÉTER`, `Logo à fournir`, `BROUILLON`, `{{`…) ; 10 aucune donnée de test dans les champs imprimés (liste de mots exacts configurable : « test », « démo », « fictif », « lorem »…, comparaison par mot entier) ; 11 PDF conforme au modèle (test d'or automatique : positions des repères de la p.1 à ≤ 2 pt) ; 12 facture et annexe cohérentes (mêmes période, quantité, tarif, totaux de pages = Σ lignes, toute différence réalisé/facturé couverte par un traitement de reliquat enregistré). Affichés sur la page du brouillon et dans l'aperçu ; **l'émission est refusée** tant qu'un contrôle bloquant échoue, avec l'anomalie exacte (rien n'est « considéré valide »).
**Chargement des données** : outil séparé (comme `mandats_appliquer.py`), sur le staging seulement, après sauvegarde et **après ta validation explicite du tableau §3** ; il n'insère que des lignes `proposed` ; la page « Factures historiques » (nouvelle, mêmes composants visuels) te laisse valider/rejeter ligne par ligne avec provenance. **Aucune ligne n'est chargée avant ton feu vert.**
**Migration** : `CREATE TABLE IF NOT EXISTS` + triggers ; aucune table existante modifiée, aucune ligne touchée ; réversible par restauration de la sauvegarde (procédure 90-rollback, éprouvée sur les RC précédentes) ; `ORDER` de `restore_service` + export JSON complétés (table vide au déploiement, donc rien à perdre au retour arrière).
**Hors périmètre** (inchangé) : aucun écart post-facturation sur facture historique (décision RC20 n°2) ; aucune modification des saisies ; aucun changement du design Liquid Glass (tables/colonnes dans les composants existants) ; pas de recréation des factures historiques comme factures émises.

## 10. Impact sur RC19 (commit `e8953b2`, non déployé)
- **Compatible, aucune réécriture** : RC19 lit `annex_json` (lignes cumulatives) et `invoice_annex_entries` ; la nouvelle annexe ne change ni l'un ni l'autre (seul le rendu du PDF se découpe en deux sections). Les factures historiques n'entrent pas dans l'écart post-facturation.
- **Fusion recommandée dans UN seul passage de déploiement staging** (rc19 + G4) : une seule migration (rc19 retire la clé étrangère de l'annexe et ajoute `invoice_variance_decisions`, G4 ajoute une table), une seule coupure d'environ 1 minute — alors que tu y travailles.
- **Avant le test de retour arrière rc19**, corriger `procedure/90-rollback.sh` (5 défauts de `REVUE-CODE-RC19.md`, dont l'écrasement de la copie de sûreté en cas de relance) et étendre le garde-fou aux nouvelles saisies / factures / lignes historiques.
- Constats rc19 non corrigés (liste dans `REVUE-CODE-RC19.md`) : aucun ne bloque ; deux touchent le modèle facture/annexe (rôle « facturée » par date seule ; annexe cumulative d'une facture ultérieure) et se règlent mieux **après** G4.
- Le brouillon n°1 (rc18) est conservé par la migration (table `invoices` non modifiée).

## 11. Impact sur RC20
- (1) Saisie oubliée sur mandat clôturé (confirmation + motif + audit) : indépendante ; à compléter par un message d'information si la date est antérieure à une facture historique validée du mandat. Pas d'écart calculé.
- (2) « Écart basé sur une date de facturation hors application » : **reste non implémenté** — le registre G4 fournit les dates mais on n'en déduit aucun écart.
- (3) Identifiants juridiques des 5 mandats actifs : indépendant (donnée à fournir). Rappel : *EUROPCR 2027* a, dans le classeur, un n° de projet et 15 j de PO (S-7) à valider.

## 12. Tests nécessaires
- **Unitaires** : `contract()` avec/sans historique, `upto` (cutoff), avoirs, mandats clôturés, dépassement de PO ; migration (table vide, idempotente, triggers, `ORDER` restore, export JSON) ; chaque contrôle 1→12 (cas passant + cas échouant) ; annexe période/cumul (mois à cheval, période sans saisie) ; en-tête figé ancien (repli) ; PDF : aucun marqueur sur émis, test d'or de positions vs modèle.
- **HTTP** (lot S) : page « Factures historiques » (valider/rejeter, audit, refus de suppression/édition), dashboard (colonnes, KPI), brouillon (panneau des contrôles), émission refusée si un contrôle bloque, émission acceptée sinon, facture émise inchangée octet par octet.
- **Navigateur** : bureau + téléphone (aucune erreur console), rejeu de la recette complète rc19.
- **Non-régression** : 404 unitaires existants, lots A→Q, M/N/L, navigateur 427, répétitions de bascule A/B/C (prod V9.0 vide, V9.0 fictive, copie staging), restauration d'une sauvegarde sans table historique.
- **Staging** : sauvegarde, `30-rehearse` GO, déploiement, `50-verify`, empreinte des saisies identique (`93a442b1…`), brouillon n°1 conservé, rollback testé puis redéploiement.

## 13. Décisions à prendre par toi (aucune n'a été anticipée)
| N° | Question | Recommandation |
|---|---|---|
| **D-1** | Valides-tu le tableau §3 comme base du registre des factures historiques (charge en `proposed`, puis validation ligne par ligne par toi) ? | **Oui**, par lots de mandats |
| **D-2** | STC GEM Oct – DM job : 4 550 CHF en « Facture 27/04 » (S-2) = facture réelle ou doublon d'Avril ? | Ne **pas** charger tant que non confirmé (≠ 7 j × 600) |
| **D-3** | « AL Jan-Mar » 19 400 CHF (sans mandat, sans jours) : l'enregistrer comme facture historique « sans mandat » (chiffre d'affaires 2025) ou l'ignorer ? | Enregistrer *sans quantité* si tu veux le CA 2025, sinon ignorer |
| **D-4** | Doublons A1 (21,75 h) facturés dans le SUIVI (G-1) : on garde l'exclusion (écart expliqué dans le registre) ou tu veux autre chose ? | Garder, documenter l'écart ; **décision commerciale (avoir éventuel) = la tienne** |
| **D-5** | *EUROPCR 2027* : appliquer n° de projet `2700091BE` et 15 j de PO du classeur ? (tarif toujours absent) | Oui pour n° et PO ; tarif à fournir |
| **D-6** | Garder la ligne « Période facturée » sur la page 1 (absente du modèle) ? | La retirer de la p.1 (fidélité) et l'imprimer en tête de la section A de l'annexe |
| **D-7** | Charger le logo du modèle `.ods` dans Paramètres (staging, puis prod au moment du cut-over) ? | Oui |
| **D-8** | Contrôles bloquants : blocage strict, ou dérogation motivée possible pour 12 (facture forfaitaire sans heures dans la période) ? | Blocage strict ; dérogation motivée seulement pour le contrôle 12, tracée |
| **D-9** | Une facture antidatée ne compte que les factures historiques/émises dont la date ≤ son cutoff ? | Oui |
| **D-10** | Déploiement staging unique rc19 + G4, à quel moment (tu es en train de tester) ? | Quand tu me le dis ; avertissement ~1 min d'arrêt |

## 14. Ce qui n'a PAS été modifié
Production, staging (lecture d'une copie cohérente uniquement), base staging, saisies, mandats, brouillon n°1, factures, paramètres (logo non chargé), design Liquid Glass, code applicatif de l'audit (seuls des scripts `audit/g4/*` en lecture seule et ce rapport ont été ajoutés). Aucun import historique, aucune suppression, aucun reset, aucun push.
