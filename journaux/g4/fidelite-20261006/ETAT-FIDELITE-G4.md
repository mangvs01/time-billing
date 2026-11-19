# G4 — revue de fidélité du 2026-10-06 (session 215222, 08:42-09:21 UTC) : état après arrêt brutal

Session « reprise G4 : fidélité corrections/saisies/imports + finalisation » (compte 2), arrêtée net à **09:20:57 UTC** par la limite d'usage
(« session limit · resets 1:40pm UTC »). Stabilisation faite le 2026-10-06 vers 10:35-10:50 UTC (session de reprise PID 280047) : rien
d'applicatif n'a été modifié dans le dépôt, aucun déploiement, staging et production inchangés.

## Ce qui a été TERMINÉ par la session 215222
- Tests unitaires de référence sur l'image `:rc19` (= code du dépôt 40ee1dc) : **440/440** (`unitaires-reference-depot-rc19-0851.log`).
- Workflow `tb-g4-fidelite` : 5 audits de fidélité sur copies jetables (A données importées, B code d'import, C corrections de saisies,
  D registre D1, E code D6/D8/D9), puis une contre-vérification sceptique par axe. **4 contre-vérifications sur 5 faites (A, B, C, D) ;
  celle de l'axe E a échoué (limite de session)** : les constats E-2 à E-8 ne sont donc PAS contre-vérifiés.
  Résultats bruts complets : `resultats-audits-fidelite.json`.
- Résultat principal de l'axe A (fidélité des données) : les **2 247 saisies concordent à 100 %** avec leurs lignes source (date corrigée,
  début, fin, heures déclarées, motif, mandat) ; bilan 2 247 + 31 doublons A1 + 4 exceptions = 2 282 lignes ; 1 934,4987 + 21,75 + 2,20 =
  1 958,4487 h ; les 32 corrections R1 + l'exception AUG 26!67 vérifiées une à une ; table `entries` identique à `pre-mandats`.
- Résultat principal de l'axe C (corrections rc19) : valeurs stockées fidèles (7 h 20 = 440/60, minuit, durée déclarée conservée),
  `before_json`/`after_json` exacts, aucune autre saisie touchée, factures émises inchangées ; lot R 49/49.
- Résultat principal de l'axe D : les 23 lignes D1 conformes une à une (205,63 j, 133 659,50 CHF) ; simulation reproduite à l'octet.
- Préparation d'un lot de correctifs **dans une copie hors dépôt** (`/tmp/tb-g4-0842/fix`), avec un nouveau module de tests
  `tests/test_g4_fidelite.py` (14 tests). Les 11 premiers tests échouent sur le code du dépôt (10 échecs/erreurs, le 11e — lot annulé — passe
  dans les deux cas) et passent sur le code corrigé (`nouveaux-tests-sur-code-*-0915.log`, état de 09:15) ; les 3 tests de mise en page
  (E3/E6/E7), ajoutés à 09:19, échouent sur le dépôt et passent sur la copie corrigée (constat dans la transcription, pas de journal).
- Rejeu de la revue d'import du classeur réel (original, R1, original ré-enregistré) sur copie, code du dépôt vs code corrigé :
  `rejeu-import-avant-correctif.json`, `rejeu-import-apres-correctif.json` (script `rejeu-import-replay.py`).

## Ce qui a été INTERROMPU
1. Suite unitaire complète sur la copie corrigée (lancée à 09:20:03) : journal tronqué (`unitaires-copie-corrigee-0920-INTERROMPU.log`).
   → **Relancée à l'identique par la stabilisation** : voir `unitaires-copie-corrigee-reprise.log` (résultat ci-dessous).
2. Contre-vérification de l'axe E (decisions-code) : échec ; son conteneur jetable `tb-g4v-ev1` (:8495, copie dans `/tmp`) était resté
   actif → **retiré par la stabilisation**. Non relancée (nouveau travail d'agent, à décider par claude2).
3. Aucune décision prise sur l'intégration des correctifs, aucune question posée à l'utilisateur, `REPRISE-G4.md` non mis à jour,
   paragraphe d'annonce de `NOTE-SESSIONS-PARALLELES.md` resté « en cours » → mis à jour par la stabilisation.

## Correctifs préparés, NON intégrés : `correctifs-non-integres.patch`
S'applique proprement sur 40ee1dc (`git apply --check -p1` OK). Copie de travail d'origine : `/tmp/tb-g4-0842/fix` (volatile) ;
sauvegarde complète : `/root/backups/tb-reprise-g4-fidelite-20261006/scratch-tb-g4-0842/fix`.

| Constat | Sévérité (après contre-vérif.) | Correctif dans le patch | Test |
|---|---|---|---|
| B1 anti-doublon d'import lié au seul sha256 du fichier (copie ré-enregistrée/complétée ⇒ centaines de doublons, dont « ok » sans décision) | bloquant (confirmé) | `historical_import.validate` : identité de ligne par (onglet, ligne, valeurs) + par contenu si horaires ; nouvelles issues `source_row_changed`, `previously_excluded` ; `possible_existing_entry` tous mandats si horaires | B1 ×2 |
| B2 saisie corrigée après import réimportée avec son ancienne valeur | majeur (confirmé) | idem B1 | B2 |
| B3 lignes remplacées/exclues lors d'un import précédent ré-importables sans rappel | mineur (confirmé, lecture corrigée : ce sont les lignes ré-importées depuis R1) | idem B1 | B3, lot annulé |
| C1 période contenant 7 h 20 (tout total non multiple de 3 min) inémettable : contrôle 12 compare round(4) à round(6) | majeur (confirmé, latent : 0 cas) | `invoice_checks` : comparaison non arrondie | C1 |
| N1 (D-01/E-1) n° « 2026-09 » de la facture réelle CIRSE 2026 réattribuable à une facture Time Billing | majeur (N1 = « proposition » du §D de DECISIONS, pas une décision D1-D10 : **à confirmer par l'utilisateur**) | `billing_rules.next_invoice_number` réserve les `historical_invoices.invoice_ref` | N1 |
| D-02 un rejet écrase la note de provenance D4 | mineur | rejet ajouté à la note ; note incluse dans l'audit de proposition | D02 |
| D-03 n° de facture réelle invisible sur /historique | mineur | `historical.html` affiche `invoice_ref`, texte reformulé | — |
| D-06 légende du prévisionnel (« émis ») inexacte avec l'historique validé | mineur | `index.html` : libellé « émis et historique validé » (l'écart D3 de 19 400 CHF n'est PAS signalé) | — |
| D-07 usage du chargeur sans `PYTHONPATH=/app` | mineur | docstring | — |
| C2 durée : « 1_5 », « 1e1 », chiffres non latins acceptés | mineur | regex avant `float` | C2 |
| C3 motif : U+2028/U+200B/U+FEFF acceptés | mineur | refus des catégories Zl, Zp, Cf | C3 |
| C5 « 7:05 » ⇒ erreur Python brute | mineur | normalisation HH:MM | C5 |
| C7 `step=0.01` empêche 7,3333 h en mode durée | mineur | `step="any"` (entry_edit.html, index.html) | — |
| E-3 « AUTRES — libellé » imprimé avec un montant nul | majeur (non contre-vérifié) | `pdf_layout.other_label` | E3 |
| E-6 contrôle 3 « conforme » avec un tarif à 0 | mineur (non contre-vérifié) | contrôle 3 : « tarif nul » | E6 |
| E-7 légende de synthèse inexacte (factures TB antérieures) | mineur (non contre-vérifié) | libellé « dont la période se termine au plus tard le … » | E7 |

Écarté volontairement par la session : minimum de 10 caractères pour le motif de rejet d'une facture historique (D-04, « info »,
non demandé) — ajouté puis retiré à 09:19, absent du patch.

Point à évaluer par claude2 (rejeu après correctif) : sur l'original mappé vers un mandat actif, 32 lignes restent importables si
l'utilisateur force « importer » ; ce sont des lignes signalées `source_row_changed` (avertissement, pas erreur), c.-à-d. les lignes déjà
importées sous leur forme corrigée R1. Faut-il en faire une erreur ? Avant correctif : 10 « ok » sans décision et 72 si tout importer ;
copie ré-enregistrée : 2 144 « ok » sans décision (→ 0 après correctif).

## Constats NON traités (ouverts)
Décisions utilisateur (aucune donnée du staging ne doit être modifiée sans son go) :
- **A-01 (majeur, confirmé)** : 15 notes de la colonne I « Colonne1 » (MAR/APR/MAY/JUL/AUG/SEPT 26) non importées ; les 15 saisies ont
  une description vide (1069, 1537, 2146, 1214, 1599, 2056, 2057, 2060-2063, 2076, 2078-2080) ; 11 sur mandats actifs (NHAF 2026,
  STC GEM Oct - DM job). Les rapports d'import annoncent « 0 écart » sans mentionner cette colonne.
- **A-03 (mineur selon la contre-vérif.)** : notation h.mm mêlée au décimal (horaires hors quart d'heure). Trois chiffrages divergents
  dans la session : audit −1,67 h (42 saisies), contre-vérif. −0,87 h (dont −0,47 h actifs), calcul final de 09:20 : 43 saisies, 12
  forcément décimales, 31 autres ⇒ −1,03 h dont −0,63 h sur 11 saisies de mandats actifs. **À recalculer une fois avant de présenter.**
- A-02 (mineur) : 11 dates hors séquence dans leur mois (dont APR 26!64-66, 74 déjà présentes dans les registres d'arbitrage).
- **E-2 (majeur, non contre-vérifié)** : D9 — factures historiques coupées à la date de facture, pas à la fin de période ; la fiche D9
  est elle-même ambiguë ⇒ faire trancher.
- **E-4 (majeur, non contre-vérifié)** : D6 (a) — la note libre reste sous le TOTAL et décale « Je vous remercie » (+5,4 pt/ligne).
- E-5 (mineur, non contre-vérifié) : description de 3 lignes + période ⇒ totaux −10,3 pt.
- E-8 (mineur) : adresse EGG BE sans retour à la ligne (CIRSE 2026, EUROPCR 2027, NHAF 2026) ⇒ à saisir par l'utilisateur après déploiement.
Code, mineurs non corrigés : B5 (import plus permissif que la saisie), B6 (minuit à l'import), B7 (`clock_rounded` sans décision,
`clock_ambiguous`), B8 (paire horaire incomplète effacée à l'édition), C4 (description multi-ligne aplatie par l'`<input>`).
Documentation : B4 (CHECKPOINT l. 33/93 et NOTE l. 68 surestiment la règle rc16), D-05 (CHECKPOINT l. 99 « 7 j déjà facturés » contredit D2 = NON).
Points relevés comme non vérifiés par les contre-vérifications : fuseau/affichage de `changed_at` ; correction d'une saisie dans la période
du brouillon n° 1 ; aucun des 13 contrôles avant émission ne détecte les doublons ; `time_overlap` ignore la base ; annulation d'un lot
doublon dont une saisie a été corrigée ; effet des lignes « à valider » sur le contrôle 5.
Infos sans action : A-04, A-05, B9, B10, C6, C8, C9, D-08, D-09, D-10, E-9.

## Résultat de la relance (stabilisation)
Jamais exécutée par la stabilisation (marqueur resté vide). Remplacée par les exécutions de la session 323542 (14:06 UTC : correctifs intégrés
dans l'arbre, 454 tests, 3 erreurs `test_v92` = libellé « Facturé YYYY (émis et historique validé) », test adapté) puis de la session 412386
(20:24 UTC : **454/454** sur l'arbre intégré ; suite complète relancée sur l'état final : voir `REPRISE-G4.md`).

## Suite (sessions 323542 du 2026-10-06 14:05 et 412386 du 2026-10-06 20:21) — voir `REPRISE-G4.md` pour l'état courant
- Correctifs du tableau ci-dessus INTÉGRÉS dans l'arbre de travail (non commités), + A5 (signe accepté dans la durée : « -1 » garde le message
  « positive ») + `test_v92` adapté (D-06).
- A-03 recalculé deux fois indépendamment (`a03-recalcul-1405/`) : **−1,032 h** sur 43 saisies (12 forcément décimales, 31 en h.mm dont 28 à
  écart non nul) ; mandats actifs : **−0,632 h** sur 11 saisies (NHAF 2026 −0,232 h ; STC GEM Oct - DM job −0,400 h). Le chiffrage de 09:20 était juste.
- Axe E contre-vérifié (revue adverse de 14:26, relecteur « axeE-pdf ») : E-3 confirmé et corrigé ; E-7 corrigé mais incomplet (R-E7-1) ;
  E-2, E-4, E-5 confirmés, NON corrigés : décisions utilisateur (voir `REPRISE-G4.md`).

