# RAPPORT DE RECETTE — Time Billing V9.2-rc16 (2026-10-05)

# MISE À JOUR 2026-10-05 (~10:20 UTC) — C1 appliquée (19 mandats clôturés), lots rejoués sur l'état réel du staging

**rc18, état post-C1.** Écriture sur le staging réel : uniquement la clôture des 19 mandats (sauvegarde vérifiée `pre-c1-20261005T100700Z`), par l'application ; saisies identiques ligne à ligne ; 0 facture ; production inchangée.

| Lot (copies jetables du staging post-C1) | Résultat | Remarque |
|---|---|---|
| Unitaires | **376/376** | code inchangé depuis rc18 |
| A+B / C–G / extra / H–I–J | 55/55 · 94/94 · 23/23 · 37/37 | inchangés |
| D–E–G | **53/53** | +DH0 : PCR LV 2025, désormais clôturé, est rouvert par l'application avant la facture de mandat historique (la facturation d'un mandat clôturé reste refusée) |
| K (prévision) | **21/21** | état réel post-C1 : 19 clôturés / 5 actifs, **total 27 050 CHF** (au lieu de 134 521), recalcul indépendant identique au centime ; copie rouverte ensuite pour les cas limites (les suites supposaient ≥ 4 mandats actifs sans date) |
| M / N / L | 10/10 · 3/3 · 19/19 | inchangés |
| **Q (nouveau)** | **18/18** | entités volontairement vides (PCR LV 2026, STC GEM Oct, MSD) : brouillon possible, adresse signalée « à compléter », émission refusée (écran + POST direct), PDF « BROUILLON / À COMPLÉTER » sans adresse inventée, MSD sans tarif non émissible ; NHAF 2026 / EUROPCR 2027 : entité C2 présente, TVA 0 % ; ECIO 2025 : clôturé, tarif 0, aucune facture, aucun « offert » ; saisies inchangées |
| **HTTP total** | **333/333** | A–K 283 + L 19 + M 10 + N 3 + Q 18 |
| Répétition V9.0 → rc18 → V9.0 | **GO** (bacs A18 copie de prod, B18 jeu fictif) | retour arrière SHA-256 identique ; production inchangée |
| Navigateur | 387/387 (rc18, base d'avant import) + parcours des 7 onglets sur la base post-C1 | aucun débordement, aucune erreur console ; la saisie ne propose que les 5 mandats actifs ; tableau de bord : 6 762,51 CHF restants sur 2026 |

Les cinq adaptations de tests de cette passe (K, DH0, L2/L4, E+3, A5) sont des changements d'**état de données ou de règle décidée** (mandats clôturés, adresse C2, minuit autorisé), pas des défauts applicatifs ; aucun correctif de code n'a été nécessaire après rc18.

**Leçon de processus** : rc17 a été déployée avant la recette navigateur et contenait une erreur de syntaxe JS ; désormais la recette navigateur (y compris le lot « minuit ») passe **avant** tout déploiement staging.

---

# MISE À JOUR 2026-10-05 (~10:10 UTC) — rc17/rc18 : saisie passant minuit (C5), C2 appliqué, lots rejoués

**Version désormais sous recette : 9.2-rc18** (staging `:8092`, commit `d57c9b7`). Le reste de ce rapport (rc16) reste valable pour tout ce qui n'a pas changé ; ci-dessous ce qui a changé et les résultats **rejoués sur rc18**.

| Lot | Résultat rc18 | Remarque |
|---|---|---|
| Unitaires (24 modules) | **376/376** | +15 tests `tests/test_rc17.py` : 22:00→02:00 = une ligne de 4 h le jour de début, rien le lendemain ; 23→01, 22→00, 23:59→00:00, 18:30→06:15, 12:00→11:59 ; fin = début refusée ; formats invalides refusés ; fin de mois (30.09 22:00→02:00 reste en septembre, suggestion de facture, annexe PDF « 22,00 / 2,00 / 4,00 ») ; chevauchement d'un jour à l'autre (détecté / non détecté si la fin = le début suivant) ; total journalier rattaché au jour de début ; nuits de changement d'heure (24.10 22→04 : 6 h calculées, 7 h réelles signalées ; 28.03 23→04 : 5 h / 4 h) ; correction vers une saisie passant minuit (historique conservé, une seule ligne) ; liste « (+1 j) » et export CSV ; aperçu de durée des formulaires ; cumul mandat |
| A+B | 55/55 | A5 « fin avant début refusée » remplacé : fin = début refusée ; A5b/A5c : 22:00→02:00 = une saisie de 4 h, aucune ligne le lendemain |
| C–G | 94/94 | inchangé |
| D–E–G | 52/52 | inchangé |
| Extra | 23/23 | E+3 : la saisie 23:00→01:00 est acceptée en UNE saisie de 2 h (remplace « refusée, décision T3 en attente ») |
| H–I–J | 37/37 | inchangé |
| K | 14/14 | inchangé |
| M | 10/10 | clôture/réouverture sur copie jetable (C1 NON appliquée sur le staging) |
| N | 3/3 | 62 pages/exports |
| L | 19/19 | adapté : NHAF 2026 porte maintenant l'adresse belge (C2) → seuls les champs émetteur manquent avant émission |
| Navigateur (Chromium) | **387/387** | 372 existants (`recette-metier` adapté : « fin = début » au lieu de « fin avant début ») + **15 nouveaux** `recette-minuit.js` (bureau et téléphone : aperçu « 4 h 00 min, passe minuit », enregistrement, liste « 22:00 – 02:00 (+1 j) », aucune ligne le lendemain, formulaire de correction, pas de débordement, aucune erreur console) |
| **Total HTTP** | **307/307** | A–K 275 + M 10 + N 3 + L 19 |

**Défaut détecté par la recette et corrigé** : rc17 introduisait dans `index.html` (aperçu de durée de l'onglet Saisie) un `let` placé dans une déclaration `const` → erreur de syntaxe JavaScript qui neutralisait tout le script de la page. Les 376 tests unitaires et les suites HTTP ne l'ont **pas** vu (ils ne parsent pas le JavaScript) ; le nouveau lot navigateur « minuit » l'a vu (« let is disallowed as a lexically bound name »). Corrigé en rc18, rejoué, redéployé ; rc17 est restée ~10 minutes sur le staging, aucune donnée touchée. Constat : aucun test automatique ne contrôle la syntaxe JS des gabarits en dehors de la recette navigateur.

**Staging réel** (écritures par les formulaires de l'application, après sauvegarde vérifiée) : déploiements rc17 puis rc18 (procédure `procedure/*.sh`, répétition GO, 50-verify conforme) ; décision C2 : NHAF 2026 et EUROPCR 2027 reçoivent raison sociale « EGG BE », contact « Claudia Ntampaka », adresse de Jette ; TVA 0 % déjà en base. **Aucune saisie modifiée** : table `entries` identique ligne à ligne (toutes colonnes) à la sauvegarde `pre-mandats-20261005T090824Z` ; 0 facture ; 0 clôture. Production inchangée (base `bd31f410…`, conteneur `0b25a343…`).

**Limites connues de C5** : la durée d'une saisie passant minuit est calculée sur l'horloge (22:00→02:00 = 4 h) ; lors d'un changement d'heure l'application avertit mais ne corrige pas (saisir en mode durée si la durée réelle doit être facturée). L'annexe PDF imprime 22,00 / 2,00 / 4,00 (fin < début signifie « le lendemain »). Une saisie 12:00→11:00 est désormais valide (23 h) : l'avertissement « passant minuit » et celui de plus de 12 h par jour servent de garde-fou contre les fautes de frappe. L'import Excel historique n'est pas modifié.

**Non rejoué** : répétition de bascule V9.0 → rc18 → V9.0 (aucun changement de schéma depuis rc16, répétition rc16 = GO, et la répétition `30-rehearse` du déploiement rc18 est GO) ; Safari/iOS.

---


Version testée : **9.2-rc16** (staging `:8092`), code = commit `3dde16b`. Production V9.0 non touchée. Historique importé **gelé** : 2 247 saisies / 1 934,4987 h / 24 mandats, empreinte `7a154f1f…` identique avant et après chaque étape ci-dessous.

## Méthode
- Toutes les recettes qui écrivent tournent sur des **conteneurs jetables, sur une copie** de la base staging (historique inclus), jamais sur le staging réel ; le script vérifie à la fin que la base staging réelle n'a pas changé (SHA-256).
- Calculs (jours, arrondis, TVA, prévision, soldes) **recomputés indépendamment en `Decimal`** et comparés au rendu de l'application, au centime.
- Sur le staging réel, seules deux écritures ont été faites, par les formulaires de l'application après sauvegarde vérifiée : 7 mandats (champs vides complétés par des valeurs certaines) et les paramètres émetteur (vides). Aucune saisie, aucun lot d'import, aucune facture.

## Résultats

| Lot | Périmètre | Résultat |
|---|---|---|
| Unitaires (23 modules) | tous les tests du dépôt | **361/361** |
| A+B | saisie (créer, modifier, supprimer tracé, durée OU début/fin, 24 h, versions concurrentes, import verrouillé, conversion jours), mandats, positions | 54/54 |
| C–G | facturation (période, suggestion, arrondis, brouillon, émission, numéro AAAA-MM, 2ᵉ facture du mois, antidatage, reliquat, TVA), avoirs (partiel, total, remboursement, compensation, plafond, annulation, remplacement, traçabilité) | 94/94 |
| D–E–G | annexe cumulative (cumul depuis le début du mandat, coupure), facture sur mandat historique, verrouillage des factures émises (déclencheurs SQL), archive (ZIP + index SHA-256, filtres, recherche) | 52/52 |
| Extra | calculs limites, accès non authentifié, double soumission | 23/23 |
| H–I–J | sauvegarde JSON, restauration (aperçu, confirmation, 14 tables identiques, idempotente, refus amputée/falsifiée/tronquée), import idempotent (aucun doublon), PDF vs modèle | 37/37 |
| K | prévision recalculée indépendamment (échu, début futur, un mois, clôturé) | 14/14 |
| **M** *(nouveau)* | clôture / réouverture de mandats : historique conservé, nouvelles saisies refusées, réversible, prévision | 10/10 |
| **N** *(nouveau)* | parcours de 62 pages/exports sur la copie préparée (mandats clôturés inclus) : aucune erreur serveur | 3/3 |
| **L** *(nouveau)* | première facture réelle de bout en bout (voir ci-dessous) | 19/19 |
| Navigateur (Chromium) | métier, saisies, responsive 33 pages × 3 formats, RC12/RC14/nuit, e2e, concurrence — exécuté sur l'image rc16, code inchangé depuis | 372/372 |
| Répétition de bascule V9.0 → rc16 → V9.0 | copie de la base de production + jeu fictif, retour arrière identique à l'octet | GO |

**HTTP fonctionnel : 306 contrôles, 0 échec.** Le lot A–J a été rejoué **après** l'application des mandats et de l'émetteur sur le staging : 260/260 inchangé.

## Lot L — première facture réelle (copie jetable, mandat actif NHAF 2026)
1. Émetteur non paramétré : l'écran d'émission **liste précisément** ce qui manque (raison sociale, adresse, titulaire, IBAN, conditions de paiement, adresse de facturation) ; l'émission par POST direct est aussi refusée côté serveur.
2. Paramètres émetteur = ceux de la facture de référence ; il ne reste alors que « Adresse de facturation ».
3. Adresse saisie par le formulaire du mandat → émission : numéro `2026-09`, quantité 9,50 j (heures ÷ 8 arrondies au quart de jour), HT = 6 175,00 CHF, TVA 0 %.
4. PDF : valide, texte extractible, **18 libellés/mentions du modèle de référence présents**, « TAUX TVA 0,00 % », « TVA - CHF », PO et n° de projet imprimés, adresse de facturation complète, aucune mention « BROUILLON », annexe : un total par mois égal à la somme des heures en base, PDF figé identique octet pour octet au second téléchargement.
5. Position affichée par l'application = facturé net 9,5 j, solde contractuel 6,5 j sur 16 j, réalisé non facturé = écart heures/jours (recalcul indépendant).
- Comparaison visuelle avec `Facture-reelle-reference-2026-09.pdf` : même structure (blocs, colonnes, totaux, coordonnées bancaires, pied de page). **Écarts connus** : le **logo** (absent : à fournir) et le **libellé de ligne** — la référence porte un texte saisi à la main (« Production PM/DM - CIRSE 2026 - 2600137BE »), l'application propose par défaut le nom du mandat (modifiable à la création du brouillon).

## Constats de la séance
| # | Constat | Nature | Traitement |
|---|---|---|---|
| 1 | Prévision : **134 521 CHF** affichés vs **27 050 CHF** réels, car l'application ignore les factures émises hors application (aucun solde d'ouverture) | limite fonctionnelle, pas un défaut de calcul (la règle documentée est respectée) | décision C1 : clôturer les 19 mandats « TERMINE » (testé, réversible) |
| 2 | Paramètres émetteur entièrement vides en staging : aucune émission possible | configuration manquante | valeurs de la facture de référence appliquées (aucun écrasement) |
| 3 | Mon checkpoint précédent affirmait « les factures de référence sont à 8,1 % » : **faux** — la facture de référence indique TAUX TVA 0,00 % (client belge) | erreur de documentation | corrigé dans `CHECKPOINT-TIME-BILLING-V9.md` |
| 4 | 3 conflits entre sources de n° de projet / PO (NC STC Sept, SMM/EAHAD, n° du libellé de la facture de référence) | données sources | tous sur des mandats terminés ; consignés dans le CSV, sans objet si C1 |
| 5 | Aucun défaut de code découvert dans les nouveaux lots | – | les échecs rencontrés pendant l'écriture des lots L/M/N étaient des erreurs de mes scripts de test (quantité obligatoire, route inexistante, comparaison de total mensuel), corrigées et rejouées ; aucun correctif applicatif nécessaire en dehors de rc16 |

## Limites de cette recette
Safari/iOS non vérifié sur appareil ; logo réel absent ; mockup « Liquid Glass » jamais fourni (aucune conformité à un mockup n'est affirmée) ; saisie à cheval sur minuit non modifiée (aucune règle métier) ; rollback du staging rc16 → rc15 non rejoué (la répétition V9.0 ↔ rc16 l'est).

## Rejouer
```
IMG=time-billing-v9-rc10-test:latest journaux/run_unit.sh $(ls tests/test_*.py | sed 's#tests/#tests.#;s#\.py##')   # unitaires
journaux/fonc/run_http_suites.sh <tag> [image]                # A–K sur copie du staging
journaux/fonc/run_mandats_premiere_facture.sh                 # M, N, L (copie préparée : mandats « certain » + clôtures)
SRC_DB=…/pre-import-historique-20261005T014206Z.db journaux/recette_navigateur_final.sh   # navigateur, sur la base d'avant import
```
