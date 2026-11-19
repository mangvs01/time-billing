#!/usr/bin/env python3
"""Génère les tableaux Markdown du rapport d'audit G4 à partir de sortie/rapprochement-suivi.json (lecture seule)."""
import json, sys

D = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "audit/g4/sortie/rapprochement-suivi.json"))
R = D["rapprochement"]
COMMENTS = {
    "AL Jan-Mar": "19 400 CHF (= 6 900 + 12 500) sans jours, sans tarif, sans date de facture, sans mandat ni saisie dans l'application : facturé 2025 non rattachable (F/G)",
    "ERA 2026": "PO 4 j, 0 j réalisé, TERMINE, aucune facture, aucun mandat dans l'application (0 saisie)",
    "ASN 2025": "facturé 9,83 j = cumul du classeur (9,83125 j) ; l'application n'a que 9,30 j : les 4,25 h (0,53 j) des doublons A1 exclus à l'import sont facturées",
    "CIRSE 2025": "facturé 9,5 j ; app 9,33 j ; 1,75 h de doublons A1 exclues (0,22 j)",
    "CIRSE 2026": "= facture de référence 2026-09 (8 j, 5 200 CHF, PDF fourni, 01.10.2026) ; app 8,24 j (65,95 h) vs 8,15 j sur la facture (65,2 h : 0,75 h d'octobre 2025 absentes de ses feuilles annexées)",
    "EAHAD": "1 j facturé = PO 1 j ; réalisé 1,06 j",
    "EAU 2026": "14 j facturés pour un PO de 10 j (+4 j) ; 4 h (0,5 j) saisies après la facture (clôture du 13.04.2026)",
    "ECIO 2025": "non facturé selon le SUIVI (pas de PO, pas de tarif) — décision C3 : « non facturé, tarif historique non retrouvé »",
    "EHRA 2026": "18 j facturés pour un PO de 10 j (+8 j) ; réalisé 19,53 j : 1,53 j (12,25 h) non facturés, dont 2,5 h postérieures à la facture",
    "Endovascular Summit": "2 factures (5,2 j + 7,7 j) pour un PO de 6 j (+6,9 j) ; réalisé 12,875 j",
    "ERA 2025": "3 factures (5,6 j + 8,4 j en 2025, 0,56 j = 364 CHF dans la ligne 2026 « ERA 2025 (cloture) ») pour un PO de 5 j ; réalisé 16,41 j. Le chiffre de 11,66 j « réalisé non facturé » donné précédemment ignorait la ligne 2026",
    "EULAR 2026": "12,5 j facturés pour un PO de 10 j ; réalisé 13,63 j : 1,13 j non facturé",
    "EUROPCR 2025": "3 factures (6,6 + 5,3 + 7,5 j) pour un PO de 10 j ; réalisé 21,24 j ; 7,75 h postérieures à la dernière facture",
    "EUROPCR 2026": "17,3 j facturés pour un PO de 15 j ; réalisé 17,47 j (1 h après la facture)",
    "EUROPCR 2027": "absent du SUIVI ; le classeur donne n° de projet 2700091BE (tableaux JUN–AOÛT 26) et 15 j de PO (JUL–SEPT 26), sans n° de PO ni tarif ; l'application : PO 0 j, pas de n° de projet. Les « 2 j facturés » du brouillon n°1 sont la quantité tapée dans ce brouillon, pas une facture historique",
    "MSD": "absent du SUIVI",
    "NC STC June": "10,5 j facturés pour un PO de 8 j ; réalisé 10,69 j",
    "NC STC Sept": "13,8 j facturés ; app 12,34 j : 9,75 h de doublons A1 exclues (1,22 j). Σ des 2 factures NC STC = 24,3 j ≈ cumul du classeur 24,35 j ; app 23,04 j",
    "NHAF 2026": "actif, aucune facture au SUIVI ; PO 16 j",
    "PCR LV 2025": "facturé = PO = réalisé (6,34 j)",
    "PCR LV 2026": "actif, aucune facture au SUIVI ; PO 9 j",
    "Rising stars Q3": "facturé 6 j = PO ; app 5,47 j ; classeur 5,94 j (3,75 h de doublons A1 exclues)",
    "SMART Y90": "facturé 10 j = PO ; app 10,40 j ; classeur 10,56 j (1,25 h exclues dont 0,75 h d'exception OCT!93)",
    "SMM 2026": "facturé 15 j = PO ; réalisé 15,03 j (1 h après la facture)",
    "STC GEM Avril": "7 j facturés = PO 7 j ; réalisé 7,46 j",
    "STC GEM Oct - DM job": "4 550 CHF en colonne « Facture 27/04 » alors que TOTAL = 10 800 (18 j × 600 CHF) et que la ligne STC GEM Avril porte déjà 4 550 (7 j × 650) : doublon probable, incohérent avec le tarif 600 (= 7,58 j) — À TRANCHER, non retenu comme facture certaine",
}
f = lambda v: "" if v is None else (f"{v:,.2f}".replace(",", " ").replace(".", ",") if isinstance(v, float) and abs(v) >= 100 else (f"{v:.3f}".rstrip("0").rstrip(".").replace(".", ",") if isinstance(v, float) else str(v)))
print("| Projet (source) | Client | Statut | NB J PO | J réalisés classeur | J facturés source | Montant facturé (CHF) | Réf. / date facture | Mandat application | J réalisés app | J facturés app | NC | Réalisé non facturé app (affiché) | Réalisé non facturé selon classeur | Écart affiché − classeur | Cat. | Commentaire |")
print("|" + "---|" * 17)
for r in sorted(R, key=lambda x: (x["projet_source"].startswith("(absent"), x["projet_source"].lower())):
    key = r["projet_source"].split(" + ")[0] if r["mandat_application"] != "ERA 2025" else "ERA 2025"
    cl = r["jours_realises_classeur"]
    realm = r["realise_non_facture_si_historique_compte"]
    ecart = (r["realise_non_facture_application"] - realm) if (realm is not None and r["realise_non_facture_application"] is not None) else None
    refs = r["reference_date_facture"].replace(" ; ", "<br>") if r["reference_date_facture"] else ("—" if not r["montant_facture_source_chf"] else "")
    refs = refs.replace("(SUIVI", "(SUIVI") 
    print("| " + " | ".join([
        r["projet_source"], str(r["client_source"] or ""), r["statut_source"], f(r["nb_j_po_source"]) if r["nb_j_po_source"] is not None else "",
        f(cl) if cl is not None else ("regroupé" if r["groupe_classeur"] else ""), f(r["jours_factures_source"]), f(r["montant_facture_source_chf"]), refs,
        r["mandat_application"] or "(aucun)", f(r["jours_realises_application"]), f(r["jours_factures_application"]), "0",
        f(r["realise_non_facture_application"]), f(realm), f(ecart), r["categories"], COMMENTS.get(key, "")]) + " |")
