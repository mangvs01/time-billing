# TABLEAU DE DÉCISION G4 — D1 à D10
Établi le 2026-10-06 (~00:10 UTC). **Lecture seule** : aucun déploiement, aucun chargement, aucune migration, aucune donnée modifiée.
Sources revérifiées pour ce tableau : classeur `/root/Time sheet CP.xlsx` (sha `c93c610c…`, cellules et formules relues dans un conteneur jetable sans réseau), copie cohérente de la base staging (sqlite backup, lecture seule), `Facture-reelle-reference-2026-09.pdf`, `Facture-modele-reference.ods`, brouillon n°1 rendu par le code rc18 (celui du staging) **sur une copie** de la base.
État : staging **9.2-rc18** sain (`/health` ok), production **9.0-rc1** intacte. Le serveur a redémarré vers 23:51 UTC (pas de mon fait) ; tous les conteneurs sont revenus.

## A. Synthèse

| ID | Question | Recommandation | Bloquant pour |
|---|---|---|---|
| D1 | Le rapprochement SUIVI ↔ application (23 factures certaines, 18 mandats clôturés) sert-il de base au registre, chargé en « à valider » puis validé par toi ligne par ligne ? | **OUI**, par lots de mandats | correction du dashboard ; pas le déploiement |
| D2 | STC GEM Oct — 4 550 CHF en `SUIVI 2026!M15` : vraie facture ou doublon de la ligne Avril ? | **Ne pas charger** tant qu'aucune pièce comptable ne le prouve | chiffres de STC GEM Oct (mandat actif) |
| D3 | AL Jan-Mar — 19 400 CHF sans mandat : on l'enregistre (CA 2025 seulement) ou on l'ignore ? | **L'ignorer dans l'application** et le garder comme écart documenté. Aucun mandat créé | rien |
| D4 | Doublons A1 (31 lignes / 21,75 h) facturés via les récapitulatifs du classeur : garder l'exclusion ? | **OUI** : réalisé inchangé, écart documenté comme provenance | rien |
| D5 | EUROPCR 2027 : reprendre du classeur le n° de projet `2700091BE` et 15 j de PO ? Tarif, n° de PO ? | n° de projet OUI ; 15 j OUI seulement si tu les confirmes ; **tarif et PO à fournir par toi** | toute facture EUROPCR 2027 |
| D6 | Mise en page : ligne « Période facturée », annexe cumulative et pagination | Annexe **cumulative et chronologique** comme 2026-09, étiquetée seulement quand il y a lieu ; période sortie de la zone des totaux | 1ʳᵉ facture réelle émise par l'app |
| D7 | Logo (dans le `.ods`) et polices | Logo OUI ; polices de remplacement gardées sauf si tu fournis les fichiers sous licence | 1ʳᵉ facture réelle émise par l'app |
| D8 | Contrôles avant émission : blocage strict, ou dérogation motivée pour certains contrôles ? | Strict ; dérogation motivée et tracée **seulement** pour le contrôle 12 | déploiement G4 |
| D9 | Une facture antidatée ne compte que les factures (historiques ou app) datées au plus tard à sa date de fin de période ? | **OUI** | rien aujourd'hui (aucun cas réel) |
| D10 | Déploiement unique rc19 + G4 sur le staging : quand ? | Après D1–D9, après les répétitions, au moment que tu choisis (~1 min d'arrêt) | déploiement |

**Avertissement sur le code.** Le commit local `5652d26` (non déployé, après l'audit) contient déjà une version de G4 qui **suppose certaines réponses** :
- D6 : la ligne « Période facturée » reste en page 1, et l'annexe est **réordonnée** (période d'abord, cumul ensuite). Cela contredit ta consigne de reproduire fidèlement 2026-09.
- D8 : blocage strict sans aucune dérogation.
- D9 : OUI.

Rien de cela ne tourne nulle part. Je l'alignerai sur tes décisions avant toute recette ou tout déploiement.

---

## B. Fiches de décision

### D1 — Registre des factures historiques : base et mode de validation
| Champ | Contenu |
|---|---|
| Question exacte | Valides-tu les **23 cellules de facture certaines** ci-dessous comme base du registre ? Elles seraient chargées en statut « à valider » (sans aucun effet), puis tu les validerais **mandat par mandat**. Seules les lignes validées comptent. |
| Données source | Colonnes « Facture jj.mm » de `SUIVI 2025` (en-têtes I2:P2) et `SUIVI 2026` (J2:Q2) ; PDF réel 2026-09 pour CIRSE 2026 |
| Cellules | 2025 : I4, K4 (Endovascular) · I5, J5, K5 (EUROPCR 2025) · K7 (NC STC June) · N8 (CIRSE 2025) · J9, L9 (ERA 2025) · N10 (Rising stars Q3) · P11 (PCR LV 2025) · O12 (SMART Y90) · K13 (EAHAD) · M14 (NC STC Sept). 2026 : J3 (ASN 2025) · J4 (ERA 2025 « cloture ») · L5 (SMM) · N6 (EHRA) · K7 (EAU) · M8 (STC GEM Avril) · O9 (EUROPCR 2026) · P10 (EULAR) · Q12 (CIRSE 2026). En 2025, les cellules contiennent des **jours** (montant = jours × 650). En 2026, elles contiennent des **montants** (jours = montant ÷ 650). |
| Exclues de D1 | `SUIVI 2026!M15` (D2), `SUIVI 2025!H3` AL (D3), ERA 2026 (aucune facture, aucun mandat, 0 j réalisé : rien à charger), ECIO 2025 (jamais facturé, décision C3) |
| Mandats | les 18 mandats clôturés facturés ; aucun mandat actif |
| Factures | 23 (Endovascular 2, EUROPCR 2025 3, ERA 2025 3, les autres 1 chacune) |
| Montant CHF | **133 659,50** HT, dont 67 236,00 (2025) et 66 423,50 (2026) |
| Jours | **205,63 j** |
| Si OUI | Je développe l'outil de chargement en simulation par défaut. Je te montre la simulation. Puis, après ton go et sur le staging seulement, je charge les 23 lignes en « à valider », toutes sans effet. Ensuite tu valides sur la page « Factures historiques ». |
| Si NON | Le dashboard reste faux pour les 19 mandats clôturés : réalisé non facturé 214,03 j au lieu de 8,40 j, solde 165,34 j au lieu de −40,29 j, CA 2026 à 0. |
| Recommandation | **OUI**. Pour CIRSE 2026, le n° « 2026-09 » peut être repris tel quel : il est imprimé sur la facture réelle, donc non inventé (voir N1). |
| Impact dashboard | voir §7 : jours facturés 0 → 205,63 j ; réalisé non facturé des clôturés 214,03 → 8,40 j ; solde −40,29 j ; CA 2026 0 → 66 423,50 CHF. Les KPI des mandats actifs ne bougent pas. |
| Impact factures historiques | Elles sont **enregistrées, jamais recréées** : pas de numéro attribué, pas de PDF, pas d'émission, aucune modification possible des valeurs source (déclencheur), aucune suppression (rejet motivé à la place) |
| Impact modèle métier | Nouveau concept « facture externe » distinct des factures Time Billing. Jours facturés nets = historique validé + Time Billing − avoirs en jours. |
| Bloquant | Pour corriger le dashboard : oui. Pour déployer rc19 + G4 : non (la table arrive vide). |

### D2 — STC GEM Oct – DM job : 4 550 CHF « Facture 27/04 »
| Champ | Contenu |
|---|---|
| Question exacte | La valeur 4 550 de `SUIVI 2026!M15` est-elle une **facture réellement émise** pour le mandat STC GEM Oct, ou une **copie** de `M8` (STC GEM Avril) ? |
| Données source | `SUIVI 2026` lignes 8 et 15, `M16` ; tables latérales GEM STC de JAN 26 à SEPT 26 ; saisies de la base |
| Cellules | `M8` = 4550 (**constante tapée**) ; `M15` = 4550 (**constante tapée**, même valeur) ; `I8` = 650 × 7 = 4 550 ; `I15` = 600 × 18 = 10 800 ; `G15` (NB J) vide ; `R15` (statut) vide ; `M16 = SUM(M3:M15)` = 9 100 (additionne les deux) ; `MAR 26!S13` « Invoice 7 days sent » ; `SEPT 26!T9 = NB J TOTAL − 7` |
| Mandat | STC GEM Oct – DM job (**actif**, PO 18 j, 600 CHF/j) ; STC GEM Avril (clôturé, 7 j, 650 CHF/j) |
| Facture | une seule pièce prouvée : STC GEM Avril, 27.04.2026, 7 j × 650 = 4 550 CHF |
| Montant | 4 550,00 CHF |
| Jours | 7,5833 j si on divise par le tarif du mandat (600), **non entier** |
| Si OUI (vraie facture) | Je charge M15 en « à valider » sur STC GEM Oct. Jours facturés 0 → 7,58 j ; réalisé non facturé 16,44 → 8,86 j ; solde 18 → 10,42 j ; prévision 27 050 → 22 500 CHF ; CA 2026 +4 550. **Il faudrait une pièce indiquant le nombre de jours réellement facturés** (7,58 j à 600 n'est pas un nombre de jours plausible). |
| Si NON (doublon) | Rien n'est chargé. La cellule est consignée comme écart de la source, et l'ancienne note « 7 j déjà facturés » (N5) est retirée. STC GEM Oct reste à 0 j facturé, 16,44 j non facturés, solde 18 j. |
| Recommandation | **Ne pas charger.** 6 indices concordent pour un doublon : (1) valeur identique tapée dans la même colonne que M8 ; (2) 4 550 = 7 × 650, le tarif d'Avril, et non un multiple cohérent de 600 ; (3) **0 h réalisée sur STC GEM Oct au 27.04.2026**, puisque sa 1ʳᵉ saisie est du 28.04.2026, donc il n'y avait rien à facturer ; (4) événement du 05 au 08.10.2026, ligne sans statut ni NB J ; (5) une seule mention de facture dans les feuilles mensuelles (« Invoice 7 days sent ») ; (6) `SEPT 26!T9` ne retire que **7 j** du cumul GEM STC. Seule une pièce comptable peut trancher définitivement (facture PDF, relevé bancaire, extrait comptable) : **certitude « probable », pas « établie »**. |
| Impact dashboard | voir « Si OUI / Si NON » ; KPI « Réalisé non facturé » des mandats actifs 27,78 j → 20,20 j seulement si OUI |
| Impact factures historiques | OUI → 1 ligne de plus ; NON → aucune ligne |
| Impact modèle métier | aucun (cas d'une cellule source douteuse, traité par la règle « jamais chargé sans certitude ») |
| Bloquant | Non pour D1 et le déploiement. **Oui** pour toute facture STC GEM Oct émise par l'application : son solde de PO en dépend. |

### D3 — AL Jan-Mar : 19 400 CHF sans mandat
| Champ | Contenu |
|---|---|
| Question exacte | Faut-il enregistrer « AL Jan-Mar » dans l'application, et si oui sous quelle forme, sachant qu'aucun mandat ne lui correspond ? |
| Données source | `SUIVI 2025!A3` « AL Jan-Mar », `H3 = 6900+12500` (formule littérale), `R3` « TERMINE », `Q3 = 0` ; toutes les autres colonnes vides (client, n° de projet, dates, PO, NB J PO, tarif, colonnes de facture) |
| Recherche « autre libellé » (faite) | (1) Les 23 feuilles du classeur ont été relues texte et nombres : « AL », « Jan-Mar », 6 900, 12 500 et 19 400 n'apparaissent **nulle part ailleurs**. (2) Les récapitulatifs JAN/FEV/MAR 2025 ne contiennent que Endovascular, PCR LV 2025, ECIO 2025, NC STC, EUROPCR 2025, CIRSE 2025 et ERA 2025, qui ont tous leur propre ligne SUIVI et leurs propres factures. (3) Total saisi de janvier à mars 2025 : 165,55 h = 20,7 j, alors que 19 400 CHF à 650 CHF/j = 29,8 j : ce montant **ne peut pas** venir des heures de ces feuilles. (4) Base de l'application : aucun mandat, client ou description « AL ». (5) Drive connecté : aucun document trouvé. Gmail n'est pas autorisé pour ce connecteur, donc je n'ai pas pu chercher. **Conclusion : aucun mandat existant sous un autre libellé.** Il s'agit vraisemblablement d'une activité de début 2025 hors de ce suivi des temps (2 montants : 6 900 et 12 500). |
| Mandat | aucun, et **je n'en crée pas** |
| Factures | 2 montants probables (6 900 et 12 500), sans date ni numéro |
| Montant | 19 400,00 CHF (inclus dans le « CA » `SUIVI 2025!H15` = 86 636) |
| Jours | aucun (pas de quantité, pas de tarif) |
| Si OUI | Il faut un nouveau concept « chiffre d'affaires historique hors mandat ». Le registre G4 l'interdit volontairement (`project_id NOT NULL`), donc il faudrait **changer le schéma** : une table séparée, sans effet sur les jours ni les soldes. Elle n'alimenterait qu'un éventuel CA 2025. Il faudrait aussi des dates de facture : sans date, impossible de placer le montant dans une année. |
| Si NON | Rien dans l'application. Le CA 2025 de l'application sera de 67 236 CHF, contre 86 636 CHF dans le classeur ; l'écart de 19 400 CHF est documenté dans le registre d'écarts. |
| Recommandation | **NON (ignorer, documenter)**. L'application n'affiche pas de KPI 2025 ; ce montant n'influence ni jours, ni solde, ni prévision. On pourra le reprendre plus tard si tu fournis les 2 pièces. |
| Impact dashboard | aucun (le KPI affiché est l'année en cours, 2026) |
| Impact factures historiques | aucun |
| Impact modèle métier | NON : aucun. OUI : nouveau concept et migration supplémentaire. |
| Bloquant | Non |

### D4 — Doublons A1 (31 lignes / 21,75 h) et jours facturés
| Champ | Contenu |
|---|---|
| Question exacte | On garde l'exclusion A1 (le réalisé reste sans les doublons) et on documente que le SUIVI a facturé sur la base de récapitulatifs qui les comptaient ? |
| Données source | `AUG!175–203` (29 lignes datées du 01 au 03.09.2025, copies exactes de 29 lignes de `SEPT`, vérifiées 29/29 sur date, projet, début, fin et heures), `FEV!25/28`, `MAR!47/49` ; récapitulatifs `AUG!K7:L17`, `SEPT!K7:L17` |
| Mandats | NC STC Sept 9,75 h · ASN 2025 2,75 h · Rising stars Q3 3,75 h · SMM 2026 2,25 h · CIRSE 2025 1,75 h · SMART Y90 0,50 h · NC STC June 0,75 h (MAR!49) · ECIO 2025 0,25 h (FEV!28) |
| Factures | ASN `SUIVI 2026!J3` ; NC STC `SUIVI 2025!K7` et `M14` ; Rising `N10` ; CIRSE 2025 `N8` (SMM, SMART : aucun effet, voir §4) |
| Montant | effet sur ce qui a été facturé : **certain 1 044,06 CHF** (1,606 j : ASN + NC STC) ; **au plus 1 458,44 CHF** (2,244 j, en ajoutant Rising et CIRSE 2025) |
| Jours | 21,75 h = 2,72 j au total ; voir §4 pour l'effet réel par facture |
| Si OUI | Réalisé inchangé (2 247 saisies / 1 934,4987 h). Le registre porte une note de provenance sur les factures concernées. Le dashboard montre « facturé au-delà du réalisé » (nombre négatif, non écrêté) : ASN −0,53, Rising −0,53, NC STC Sept −1,46, CIRSE 2025 −0,17. |
| Si NON (réintégrer) | Il faudrait importer 31 lignes qui sont des copies d'un même créneau horaire, ce qui est physiquement impossible. Le réalisé passerait à 1 956,25 h, et la décision A1 que tu as validée serait annulée. |
| Recommandation | **OUI, garder l'exclusion ; information de provenance uniquement.** La question commerciale (remboursement ou avoir au client) reste ta décision, hors application. Je ne crée aucun avoir. |
| Impact dashboard | 4 mandats clôturés en négatif (Σ −2,71 j, dont 2,24 j au plus expliqués par A1, le reste par OCT!94 et des arrondis) |
| Impact factures historiques | une note sur 5 lignes (J3, K7, M14, N10, N8) ; valeurs source non modifiées |
| Impact modèle métier | aucun |
| Bloquant | Non |

### D5 — EUROPCR 2027 : données manquantes
| Champ | Contenu |
|---|---|
| Question exacte | Reprends-tu du classeur le n° de projet `2700091BE` et les 15 j de PO ? Peux-tu fournir le tarif, le n° de PO, les dates de l'événement et la période réellement à facturer ? |
| Données source | `JUN 26!J12/M12`, `JUL 26!J7/M7/O7`, `AUG 26!J7/M7/O7`, `SEPT 26!J7/M7/O7` ; absent de `SUIVI 2026` |
| Mandat | EUROPCR 2027 (actif) |
| Facture | **aucune facture historique**. Les « 2 j facturés » affichés = quantité tapée dans le brouillon n°1 (`qty = 2`, « test »). |
| Montant | 0 CHF (tarif 0) |
| Jours | réalisé 2,25 h = 0,28 j (26.06 0,75 h ; 14.07 0,25 h ; 21.07 1,25 h) |
| Si OUI | n° de projet imprimé sur la description et la page de synthèse ; PO 15 j → solde contractuel et prévision calculables (prévision = 14,72 j × tarif, dès que le tarif est connu) |
| Si NON | Le mandat reste « sans bon de commande » ; aucune facture possible tant que le tarif est à 0, car l'émission est refusée (règle tarif > 0, correcte). |
| Recommandation | n° de projet **OUI**, certitude élevée : identique sur 3 mois. 15 j **seulement si tu confirmes**, certitude moyenne : la valeur figure dans les feuilles mais pas dans le SUIVI, et sans n° de PO. Tarif, n° de PO et dates : **à fournir par toi, je n'invente rien**. |
| Impact dashboard | PO 0 → 15 j si OUI ; prévision +14,72 j × tarif |
| Impact factures historiques | aucun |
| Impact modèle métier | aucun |
| Bloquant | Oui, mais seulement pour facturer EUROPCR 2027 |

### D6 — Période / annexe / mise en page de la page 1
| Champ | Contenu |
|---|---|
| Question exacte | (a) Où imprimer la période de facturation sans décaler le modèle 2026-09 ? (b) Annexe : garder **l'historique cumulatif chronologique** du modèle, en étiquetant les pages seulement si la facture ne couvre pas tout le mandat ? (c) Pagination : reproduire le modèle ou numéroter toutes les pages ? |
| Données source | PDF 2026-09 (13 pages), brouillon n°1 (rc18, 4 pages), `app/pdf_layout.py` |
| Mandats / factures | tous ; cas concret : brouillon n°1 EUROPCR 2027 (période du 03.09 au 31.10.2026, date de facture 07.10.2026, 0 h dans la période) |
| Montant / jours | sans objet (présentation) ; aucun calcul modifié |
| Si OUI (proposition) | voir §5 et §6 : période dans la cellule DESCRIPTION, plus rien sous le total ; annexe chronologique avec une légende par page quand il y a lieu ; dernière page annonçant « Période facturée » et « Historique cumulatif jusqu'au [cutoff] ». J'annule le réordonnancement du commit `5652d26`. |
| Si NON | Le rendu rc18 reste : la ligne période et la note sous le total décalent « Je vous remercie… » de +4,8 pt (facture émise) à +15,8 pt (brouillon n°1), et l'ambiguïté période ↔ feuilles reste. |
| Recommandation | (a) période **dans la cellule DESCRIPTION** (2ᵉ ou 3ᵉ ligne, comme le n° de projet du modèle) ; (b) **OUI** ; (c) numéroter toutes les pages de l'annexe, écart volontaire et minime : le modèle ne numérote ni la 1ʳᵉ page d'annexe ni la synthèse. |
| Impact dashboard | aucun |
| Impact factures historiques | aucun ; les factures déjà émises dans l'app (aucune aujourd'hui) ne sont jamais re-rendues |
| Impact modèle métier | la notion « cutoff » devient explicite sur le document |
| Bloquant | Oui pour émettre la 1ʳᵉ vraie facture depuis l'app ; non pour déployer |

### D7 — Logo et polices
| Champ | Contenu |
|---|---|
| Question exacte | Charger dans Paramètres le logo extrait du modèle `.ods` (`media/image1.png`, 500×500) ? Garder les polices de remplacement libres ? |
| Données source | `.ods` : polices déclarées Avenir Next LT Pro Light, Cambria, Tahoma ; PDF réel : logo JPEG 321×322 placé à x = 50,05 pt, haut = 54,06 pt, largeur 105,4 pt |
| Mandats / factures / montants | tous les documents émis ; aucun montant |
| Si OUI | Logo à la position déjà codée (x = 49,9, haut = 54,2, 105,6 pt), soit un écart ≤ 0,2 pt par rapport au modèle. Le texte provisoire « [Logo à fournir] » disparaît, y compris des brouillons. |
| Si NON | page 1 sans logo (le modèle en a un) |
| Recommandation | Logo **OUI** (staging, puis production au moment de la bascule). Polices : garder Nunito Sans Light / Caladea / Carlito, sauf si tu fournis les fichiers sous licence ; ils sont pris automatiquement depuis `data/fonts`. |
| Impact dashboard / historiques / modèle métier | aucun |
| Bloquant | 1ʳᵉ facture réelle seulement |

### D8 — Rigueur des 12 contrôles avant émission
| Champ | Contenu |
|---|---|
| Question exacte | Les 12 contrôles bloquent-ils l'émission sans exception, ou une dérogation motivée et tracée est-elle permise pour le contrôle 12 (facture et annexe cohérentes, par ex. facture forfaitaire sans heures dans la période) ? |
| Données source | `app/invoice_checks.py` (commit `5652d26`, non déployé : **strict, aucune dérogation**) |
| Mandats / factures | toutes les futures émissions ; cas réel : le brouillon n°1 échouerait aux contrôles 1/12 (0 h dans la période), 3 (tarif 0) et 10 (« test », « unn », « PUNAISE ») |
| Montant / jours | sans objet |
| Si strict | aucune facture incohérente ne peut sortir ; une facture forfaitaire sans saisie dans la période est impossible |
| Si dérogation sur 12 | possible avec motif obligatoire, auteur, date et audit ; motif imprimé nulle part |
| Recommandation | Strict, **avec dérogation motivée pour le contrôle 12 seulement**. J'ajoute un 13ᵉ contrôle : « date de fin de période ≤ date de facture » (le brouillon n°1 facture jusqu'au 31.10 avec une date au 07.10, voir N4). |
| Impact dashboard / historiques | aucun |
| Impact modèle métier | règle d'émission renforcée |
| Bloquant | Oui pour déployer G4 (fixe le comportement de l'émission) |

### D9 — Cutoff d'une facture antidatée
| Champ | Contenu |
|---|---|
| Question exacte | Pour la page de position d'une facture, ne compter que les factures historiques ou Time Billing **datées au plus tard à sa date de fin de période** ? |
| Données / mandats / factures | toutes ; aucun cas réel aujourd'hui (0 facture émise dans l'app) |
| Montant / jours | sans objet |
| Si OUI | la position imprimée raconte l'état à la date de la facture, sans voir le futur |
| Si NON | une facture antidatée afficherait des jours facturés postérieurs à elle |
| Recommandation | **OUI** (déjà ainsi dans `5652d26`) |
| Impact | dashboard : aucun (le dashboard montre « aujourd'hui ») ; factures historiques : leur date sert de cutoff ; modèle : cutoff formalisé |
| Bloquant | Non |

### D10 — Déploiement rc19 + G4 sur le staging
| Champ | Contenu |
|---|---|
| Question exacte | Après D1–D9, quand déployer en **un seul passage** rc19 + G4 (1 migration additive, ~1 min d'arrêt), sachant que tu travailles sur le staging (brouillon n°1) ? |
| Données | staging rc18, 2 247 saisies (empreinte `93a442b1…`), brouillon n°1 conservé (table `invoices` non modifiée) |
| Montant / jours | aucun changement de donnée au déploiement (le registre arrive vide) |
| Si OUI | Dans l'ordre : sauvegarde, répétition GO, déploiement, vérification, test de retour arrière, redéploiement. Le chargement des factures historiques reste une étape séparée, après ton go (D1). |
| Si NON | le staging reste rc18 (dashboard faux pour les mandats clôturés) |
| Recommandation | Je termine d'abord les étapes restantes **sans toucher au staging** : contrôles de schéma, outil de chargement en simulation, répétitions A/B/C, recettes HTTP et navigateur. Ensuite, déploiement au moment exact que tu fixes. |
| Bloquant | Oui (c'est la décision de déploiement) |

---

## C. Analyses demandées

### 1. STC GEM Oct — CHF 4 550
Voir la fiche D2. Faits supplémentaires vérifiés :
- **La saisie de STC GEM Avril s'arrête le 23.04.2026, et celle de STC GEM Oct commence le 28.04.2026.** Au 27.04, le mandat Oct avait **0 h**.
- Les tables latérales mensuelles traitent GEM STC comme **un seul flux**. Jours PO : 15 de février à juin 2026, puis `15+7` = 22 à partir de JUL 26. En fin de série, `SEPT 26!T9 = NB J TOTAL − 7` : seuls 7 j sont décomptés comme facturés.
- Le SUIVI dit autre chose (Avril PO 7 j ; Oct PO 18 j = 25 j) : la source est incohérente sur les PO, en plus de M15.
- Le « +8,67 j » inexpliqué de GEM STC (S-8) a une cause précise : `APR 26!P11` (« J mois précédant(s) ») = `[[#This Row],[NB J TOTAL]]` de la table de MAR 26, mais **la ligne 11 de MAR 26 est EHRA 2026** (15,4062), pas GEM STC (ligne 13, 6,7375). C'est une erreur de formule du classeur. Le cumul de 32,57 j est donc faux ; la somme mensuelle de 23,90 j correspond à l'application (7,456 + 16,444).
- Correction d'un document antérieur : `import/MANDATS-DECISIONS-UTILISATEUR.md` (ligne 67) affirmait « STC GEM Oct a 7 j déjà facturés hors application ». Cette affirmation n'était **pas** établie et doit être retirée (N5).

### 2. AL Jan-Mar — CHF 19 400
Voir la fiche D3 : recherche exhaustive, **aucun mandat sous un autre libellé**, aucun mandat créé. Le registre G4 ne peut d'ailleurs pas l'accueillir sans mandat (`project_id NOT NULL`), ce qui est voulu.

### 3. EUROPCR 2027 — données manquantes et pourquoi
| Donnée | Ce que contient la source | Pourquoi elle est nécessaire |
|---|---|---|
| Tarif CHF/j | **absent** (ni SUIVI, ni feuilles) ; application : 0 | montant = quantité × tarif (contrôle 3) ; émission refusée si tarif 0 ; prévision |
| Jours commandés (PO) | 15 j dans `JUL/AUG/SEPT 26!O7` ; absent du SUIVI ; application : 0 | solde contractuel, page de position, contrôle 8, prévision |
| N° de PO client | **absent** | imprimé dans l'en-tête « PO: » (les factures BSCI en portent un ; un client peut refuser une facture sans PO) |
| N° de projet | `2700091BE` dans `JUN/JUL/AUG 26!M` ; `SEPT 26!M7` contient 0,28125 (formule erronée) ; application : vide | description et page de synthèse (« Num projet ») |
| Dates de l'événement | **absentes** | colonne « Dates » de la page de synthèse (aujourd'hui « [À COMPLÉTER : Dates] ») |
| Client (colonne « Client ») | absent du SUIVI ; entité EGG BE appliquée en C2 (déduite) | page de synthèse (« [À COMPLÉTER : Client] ») |
| Période à facturer | brouillon n°1 : du 03.09 au 31.10.2026, **0 h dans la période**, fin de période postérieure à la date de facture (07.10) | contrôles 1, 12 et nouveau 13 ; sens de la facture |
| Quantité | brouillon : 2 j tapés, « test » ; réalisé : 0,28 j | cohérence facture ↔ annexe (contrôle 12) |

### 4. Les 31 doublons exclus (21,75 h)
**Pourquoi ils pèsent sur les jours facturés.** Le récapitulatif d'août 2025 additionne toute la table d'août, y compris les 29 lignes copiées de septembre, qui sont **datées de septembre**. Exemple : NC STC 61,25 h avec les copies, 51,5 h sans. Septembre les recompte. La colonne « J mois précédant(s) » enchaîne les mois, donc le cumul « NB J TOTAL » est gonflé de 20,75 h. Les paires FEV!25/28 et MAR!47/49 ajoutent 1 h. Les quantités du SUIVI ont été fixées d'après ce cumul.

**Effet par projet** (h exclues : A1 = doublon ; C6 = exception validée, non importée) :
| Mandat | A1 (h) | C6 (h) | Facturé | Réalisé app | Réalisé classeur | Effet A1 sur la facture |
|---|---|---|---|---|---|---|
| ASN 2025 | 2,75 | **1,50 (OCT!94)** | 9,83 | 9,30 | 9,83125 | **certain** : facture = cumul du classeur au centième ⇒ 0,344 j (223,44 CHF) dus à A1, plus 0,1875 j dus à OCT!94 |
| NC STC June + Sept (même tableau) | 0,75 + 9,75 | – | 10,5 + 13,8 = 24,3 | 23,04 | 24,35 | **certain** : 24,3 ≈ 24,35 du classeur ⇒ 1,2625 j (820,63 CHF) |
| Rising stars Q3 | 3,75 | – | 6 (= PO) | 5,47 | 5,94 | **possible** : 0,469 j (304,69 CHF), mais 6 = PO, donc on ne peut pas savoir si c'est le cumul ou le PO qui a été facturé |
| CIRSE 2025 | 1,75 | – | 9,5 | 9,33 | 9,64 | **possible** : 0,169 j au plus (109,69 CHF) |
| SMM 2026 | 2,25 | – | 15 (= PO) | 15,03 | 15,31 | aucun (facturé ≤ réalisé de l'app) |
| SMART Y90 | 0,50 | 0,75 (OCT!93) | 10 (= PO) | 10,40 | 10,56 | aucun |
| ECIO 2025 | 0,25 | – | 0 | 2,66 | 2,69 | aucun (non facturé) |
| **Total** | **21,75** | 2,25 | | | | **certain 1,606 j / 1 044,06 CHF ; au plus 2,244 j / 1 458,44 CHF** |

**Correction de l'audit G4.** Il attribuait les 4,25 h d'ASN et les 1,25 h de SMART aux doublons A1. En réalité, 1,50 h et 0,75 h sont les **exceptions C6** OCT!93/94 : lignes sans date, que tu as décidé de ne pas importer. Les « 2,71 j facturés en plus » (≈ 1 750 CHF) mélangeaient A1, C6 et des arrondis.

**Effet sur le rapprochement.** Oui : il **explique** 4 des 5 cas où le facturé dépasse le réalisé importé.

**Faut-il changer le calcul des jours réalisés ?** **Non.** Ce sont des copies du même créneau horaire (même date, même heure). Les réintégrer annulerait A1.

**Que faire ?** **Une information de provenance seulement** : une note sur les lignes du registre concernées, et un réalisé non facturé négatif affiché tel quel. Le volet commercial (avoir au client ou non) reste ta décision, hors application.

### 5. Période / annexe — reproduire 2026-09 sans ambiguïté
Faits :
- La facture réelle 2026-09 (CIRSE 2026, date 01.10.2026) **ne porte aucune ligne de période**. Son annexe va de nov-25 à sept-26 : c'est le cumul depuis le début du mandat, en ordre chronologique, sans légende. Elle omet oct-25 (0,75 h, S-9) ; l'application inclurait une page oct-25.
- Ce n'est pas ambigu dans ce cas, parce que la facture couvre tout le mandat.
- L'ambiguïté apparaît quand la période ne commence pas au début du mandat. C'est le cas du brouillon n°1 : période du 03.09 au 31.10.2026, mais feuilles de juin et juillet, et aucune heure dans la période.

Proposition (D6), **sans limiter l'annexe à la période** :
1. **Période de la facture.** Elle va dans la cellule DESCRIPTION de la page 1, sur une ligne de plus, comme le n° de projet sur le modèle : « Période : 03.09.2026 – 31.10.2026 ». Plus rien sous le TOTAL, donc aucun élément du modèle ne bouge.
2. **Annexe = historique cumulatif jusqu'au cutoff**, du début du mandat à la fin de période, **dans l'ordre chronologique du modèle** (j'annule le réordonnancement de `5652d26`).
3. **Légende par page, seulement si nécessaire** (période ≠ début du mandat), en petit sous le mois :
   - « Prestations de la période facturée » ;
   - ou « Historique cumulatif — antérieur à la période facturée (information) ».
   Un mois à cheval est coupé en deux pages. Sans antériorité, comme pour 2026-09 : aucune légende, rendu identique au modèle.
4. **Dernière page** : « Période facturée : du … au … · Historique cumulatif des prestations jusqu'au [cutoff] » au-dessus de la ligne SUIVI.
5. **Période vide** : la mention « Aucune prestation datée dans la période facturée » s'imprime, et l'émission est bloquée (contrôles 1/12, sauf dérogation D8).

### 6. Mise en page — brouillon n°1 (rc18) vs facture réelle 2026-09 (mesures `pdftotext -bbox`)
| Élément | Modèle 2026-09 | Brouillon n°1 | Écart | Correction proposée |
|---|---|---|---|---|
| Positions page 1 (20 repères) | – | – | ≤ 1,5 pt (dy ≈ −0,6 pt partout ; JOUR +1,5 ; COUT +1,4 ; MONTANT +0,7) | aucune |
| Titre | « FACTURE » x = 465 | « FACTURE — BROUILLON » x = 322 | brouillon seulement ; une facture émise affiche « FACTURE » à la place du modèle | aucune |
| Logo | JPEG 105,4 pt à (50,05 ; 54,06) | « [Logo à fournir — Paramètres] » | logo absent | D7 (géométrie déjà juste à ≤ 0,2 pt) |
| Typographie | polices du modèle intégrées (Avenir Next LT Pro Light, Cambria, Tahoma/Calibri) | Nunito Sans Light, Caladea, Carlito | hauteur de boîte 10,9 vs 9,6 pt ; chasse légèrement différente | D7 (fichiers sous licence si disponibles) |
| Bloc client | « Avenue du Bourgmestre / Etienne Demunter 5, boîte 10 » | « Avenue du Bourgmestre Etienne Demunter 5, / boîte 10 » | coupure de ligne différente | respecter les retours à la ligne saisis dans l'adresse, comme dans le modèle |
| Tableau | 1 ligne, description sur 3 lignes avec n° de projet | « test » sur 1 ligne, sans n° de projet | données de test ; n° de projet manquant (D5) | contrôle 10 ; D5 |
| AUTRES | « AUTRES » | « AUTRES — Cadeau unn jour » avec « - CHF » | libellé imprimé alors que le montant est 0 | n'imprimer le libellé que si montant ≠ 0 ; contrôle 10 |
| Ligne période | absente | « Période facturée : … » sous le TOTAL (y = 455) | ajout, décalage | D6 : dans la cellule DESCRIPTION |
| Note libre | absente | « 3 PUNAISE DE JOUR OFFERT » sous la période | ajout, décalage | zone de note fixe hors flux, ou page de synthèse ; contrôle 10 |
| « Je vous remercie… » | (420,5 ; 475,0) | (426,1 ; 490,8) | **+15,8 pt** (brouillon) / +4,8 pt (facture émise sans note) | disparaît avec les deux corrections ci-dessus |
| Pied de page | « N° registre… » x = 163,6 | x = 160,7 | −2,8 pt (chasse de la police) | aucune (D7) |
| Annexe | paysage, « Feuille de temps / mois / Total des heures de travail du mois / tableau » | identique | ≤ 4 pt (boîtes de police) ; colonnes identiques | aucune |
| Pagination | « Page n of 12 » de la p.3 à la p.12 ; **ni la p.2 (1ʳᵉ feuille) ni la p.13 (synthèse) ne sont numérotées** ; la page 1 n'est pas comptée | « Page 1 of 3 » à « Page 3 of 3 » sur toutes les pages après la page 1 (x = 400,7 vs 398,0) | numérotation plus complète | D6 (c) : garder la numérotation de toutes les pages (recommandé) ou reproduire le modèle |
| Dernière page | « PROJET, Dates, Client, Num projet, PO, NB J PO, **NB J** » (1 ligne) | « … **Jours réalisés cumulés** » + bloc « Position contractuelle » (décision rc7) ; « Jours facturés **2** » = quantité du brouillon lui-même ; « [À COMPLÉTER : …] » | P-4 : la facture se compte elle-même dans « déjà facturé » | position en colonnes séparées (historique / Time Billing antérieur / **cette facture**) — prévu G4 |
| Marqueurs de brouillon | – | bandeau rouge, « (prévue) », « (attribué à l'émission) » | brouillon seulement (vérifié : 0 marqueur sur une facture émise) | aucune |
| Donnée du modèle à ne pas recopier | description « …CIRSE 2026 – **2600137BE** » (= n° d'EUROPCR 2026, faute de frappe S-10) | – | – | ne pas propager |

### 7. Dashboard — effet des factures historiques validées (D1 seul, D2 = NON)
| Indicateur | Aujourd'hui (rc18) | Après validation des 23 lignes | Mécanisme |
|---|---|---|---|
| Jours facturés (tableau, 19 clôturés) | 0 | **205,63 j**, avec « dont X j historique » par mandat | historique validé + Time Billing − avoirs en jours |
| Réalisé non facturé (clôturés) | 214,03 j | **8,40 j nets** = +11,11 j non facturés (ECIO 2,66 ; ERA 2025 1,85 ; EUROPCR 2025 1,84 ; EHRA 1,53 ; EULAR 1,13 ; EAU 0,55 ; < 0,5 j : 1,54) − 2,71 j facturés au-delà (ASN, Rising, NC STC Sept, CIRSE 2025, Endovascular) | réalisé − facturé net, **négatif affiché tel quel** |
| Solde contractuel (clôturés) | 165,34 j | **−40,29 j** : 8 mandats dépassent leur PO (Σ −45,16 j) ; reliquats ASN 0,17, CIRSE 2025 0,5, CIRSE 2026 4,0, NC STC Sept 0,2 | PO − facturé net |
| KPI « Réalisé non facturé » (5 actifs) | 27,78 j | **27,78 j** (inchangé ; 20,20 j seulement si D2 = OUI) | ne compte que les actifs |
| CA « Facturé 2026 » | 0 CHF | **66 423,50 CHF**, avec « dont historique » | historique validé daté en 2026 + Time Billing − avoirs |
| CA 2025 (non affiché) | 0 | 67 236 CHF (86 636 dans le classeur : l'écart de 19 400 vient d'AL, D3) | idem |
| Prévision restante | 27 050 CHF | **27 050 CHF** (inchangée ; 22 500 seulement si D2 = OUI) | concerne seulement les actifs, qui n'ont aucune facture historique certaine |
| Statut clôturé | 19 clôturés / 5 actifs | **inchangé** : valider une facture historique ne clôt ni ne rouvre aucun mandat. Les 8,40 j restent visibles sur les mandats clôturés, hors KPI. | clôture = ta décision C1 |

---

## D. Points nouveaux (hors D1–D10, à connaître)
- **N1 Numérotation.** L'application numérote selon le mois de fin de période (`next_invoice_number`), en ne regardant que ses propres factures. Une facture Time Billing dont la période se termine en septembre 2026 recevrait **« 2026-09 », déjà utilisé par la facture réelle CIRSE 2026**. Proposition : réserver les n° des factures historiques connues (seul 2026-09 est connu) dans le contrôle de numérotation.
- **N2 Code en avance.** Le commit `5652d26` (non déployé) suppose D6, D8 et D9 (voir l'avertissement en tête). Je l'aligne après tes réponses.
- **N3 Correction de l'audit.** Doublons A1 et exceptions C6 confondus pour ASN et SMART (§4) ; l'effet A1 sur la facturation est d'au plus 2,24 j, et non 2,71 j.
- **N4 Brouillon n°1.** Date de facture le 07.10.2026 (future, donc émission refusée, ce qui est correct), mais fin de période le 31.10.2026, après la date de facture. Proposition : 13ᵉ contrôle (D8).
- **N5 Document à rectifier.** `import/MANDATS-DECISIONS-UTILISATEUR.md`, ligne 67 : « 7 j déjà facturés » pour STC GEM Oct ne doit pas être présenté comme un fait (D2).
- **N6 Redémarrage du serveur** vers 23:51 UTC, pas de mon fait : staging rc18 et production 9.0 revenus sains.

## E. Non touché
Production, base staging, saisies, mandats, brouillon n°1, paramètres, classeur. Aucun chargement, aucune migration, aucun déploiement, aucun commit. Seuls ce fichier et des copies de travail dans le dossier temporaire de la session ont été écrits (copie de la base, PDF du brouillon rendu sur la copie).
