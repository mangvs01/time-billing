"""Calendrier des choses importantes (candidat 9.2-rc36) : échéances fiscales et sociales, jours fériés, vacances scolaires, jalons des mandats, alertes.

LECTURE SEULE : rien de ce module n'écrit en base ni ne modifie une règle de facturation, de TVA, d'arrondi ou de contrôle. Les alertes sont calculées à
chaque lecture à partir de ce que `billing_rules.contract` et les tables existantes donnent déjà ; les seuils sont des réglages (table `settings`,
clés `cal_*`, aucune migration). Les dates fiscales, les jours fériés et les vacances scolaires sont dans `app/donnees_calendrier/*.json`, avec leur
source officielle et un statut, et ne sont jamais codés ici (seule la RÈGLE de calcul des jours fériés mobiles l'est : Pâques, Jeûne genevois).
"""
import calendar as _cal
import hashlib, json, os, re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app import billing_rules as rules
from app import credit_service as credits

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "donnees_calendrier")
CENT = Decimal("0.01")
STATUTS = {"confirme": "confirmé", "regle_legale": "règle légale", "a_verifier": "à vérifier"}
GENRES = {"echeance": "Échéance", "ferie": "Jour férié", "vacances": "Vacances scolaires", "jalon": "Mandat", "alerte": "Alerte"}
TVA_PERIODICITES = {"semestriel": "Semestriel", "trimestriel": "Trimestriel", "aucune": "Non assujetti à la TVA (aucune échéance TVA)"}

# réglage -> (libellé, valeur par défaut, aide). Stockés dans `settings` (clé/valeur existante) : aucune migration.
REGLAGES = {
    "cal_seuil_non_facture": ("Heures non facturées : seuil d'alerte (CHF HT)", "8000.00", "alerte quand le travail saisi et non facturé d'un mandat (ou d'un client) dépasse ce montant"),
    "cal_retard_jours": ("« Pas facturé depuis » : nombre de jours", "45", "délai sans facture émise au-delà duquel un retard est signalé"),
    "cal_seuil_retard": ("« Pas facturé depuis » : retard minimal (CHF HT)", "8000.00", "le retard n'est signalé que si le travail non facturé atteint ce montant"),
    "cal_budget_pct": ("Bon de commande consommé : seuil d'alerte (%)", "80", "alerte dès que les jours travaillés atteignent ce pourcentage des jours commandés"),
    "cal_brouillon_jours": ("Brouillon ancien : nombre de jours", "14", "un brouillon non émis depuis ce délai est signalé"),
    "cal_paiement_jours": ("Délai de paiement des factures (jours)", "30", "sert à repérer les échéances de paiement atteintes (le paiement n'est pas suivi dans l'application)"),
    "cal_tva_periodicite": ("Périodicité des décomptes TVA", "semestriel", "choisit les échéances TVA affichées"),
}


class CalendarDataError(RuntimeError):
    """Fichier de données du calendrier illisible ou incohérent (le message nomme le fichier)."""


# --- jours : Pâques, fériés, jours ouvrés --------------------------------------------------------------------------------------------------
def paques(annee):
    """Dimanche de Pâques (calendrier grégorien) — algorithme de Meeus/Jones/Butcher."""
    a = annee % 19; b, c = divmod(annee, 100); d, e = divmod(b, 4); f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i, k = divmod(c, 4); l = (32 + 2 * e + 2 * i - h - k) % 7; m = (a + 11 * h + 22 * l) // 451
    mois, jour = divmod(h + l - 7 * m + 114, 31)
    return date(annee, mois, jour + 1)


def jeune_genevois(annee):
    """Jeudi qui suit le premier dimanche de septembre."""
    s = date(annee, 9, 1)
    return s + timedelta(days=(6 - s.weekday()) % 7 + 4)


def ajouter_mois(d, n):
    y, m = divmod(d.month - 1 + n, 12); y += d.year; m += 1
    return date(y, m, min(d.day, _cal.monthrange(y, m)[1]))


def jours_feries(annee, donnees):
    """Jours fériés (fédéraux + canton) d'une année civile, calculés d'après les règles du fichier de données."""
    out = []
    for f in donnees["feries"]:
        r = f["regle"]; t = r["type"]
        if t == "fixe": d = date(annee, r["mois"], r["jour"])
        elif t == "paques": d = paques(annee) + timedelta(days=r["decalage"])
        elif t == "jeune_genevois": d = jeune_genevois(annee)
        else: raise CalendarDataError(f"jours_feries.json : règle inconnue « {t} » ({f.get('id')})")
        out.append({"date": d, "nom": f["nom"], "portee": f["portee"], "statut": f["statut"], "source": f["source"], "id": f["id"]})
    return sorted(out, key=lambda x: x["date"])


def jour_ouvre_precedent(d, feries):
    """Dernier jour ouvré (ni samedi, ni dimanche, ni férié) avant d, d exclu. feries : ensemble de dates."""
    d -= timedelta(days=1)
    while d.weekday() >= 5 or d in feries: d -= timedelta(days=1)
    return d


def jour_ouvre_suivant(d, feries):
    """Premier jour ouvré (ni samedi, ni dimanche, ni férié) à partir de d inclus. feries : ensemble de dates."""
    while d.weekday() >= 5 or d in feries: d += timedelta(days=1)
    return d


# --- données (JSON) ------------------------------------------------------------------------------------------------------------------------
def _lire(nom, dossier=None):
    chemin = os.path.join(dossier or DATA_DIR, nom)
    try:
        with open(chemin, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError) as e:
        raise CalendarDataError(f"{nom} : fichier illisible ({e})")


def _source(obj, nom, ident):
    s = obj.get("source")
    if not isinstance(s, dict) or not str(s.get("titre") or "").strip() or not str(s.get("url") or "").startswith("https://"):
        raise CalendarDataError(f"{nom} : « {ident} » sans source officielle (titre + URL https)")


def _iso(v, nom, ident):
    try: return date.fromisoformat(str(v))
    except ValueError: raise CalendarDataError(f"{nom} : date invalide « {v} » ({ident})")


def charger(dossier=None):
    """Lit et valide les trois fichiers. Chaque échéance, chaque férié et chaque année scolaire doit porter sa source."""
    ech = _lire("echeances.json", dossier); fer = _lire("jours_feries.json", dossier); vac = _lire("vacances_scolaires_ge.json", dossier)
    for it in ech.get("echeances", []):
        ident = it.get("id", "?")
        if it.get("statut") not in STATUTS: raise CalendarDataError(f"echeances.json : statut inconnu ({ident})")
        _source(it, "echeances.json", ident)
        if it.get("type") not in ("tva", "annuel", "dates"): raise CalendarDataError(f"echeances.json : type inconnu ({ident})")
        if it["type"] == "tva":
            for p in it["periodes"]: _iso(f"2000-{p['du']}", "echeances.json", ident); _iso(f"2000-{p['au']}", "echeances.json", ident)
        elif it["type"] == "annuel": _iso(f"2000-{it['mois_jour']}", "echeances.json", ident)
        else:
            for e in it.get("dates", []):
                if "date" in e: _iso(e["date"], "echeances.json", ident)
                else: _iso(f"2000-{e['mois_jour']}", "echeances.json", ident)
    for f in fer.get("feries", []):
        if f.get("statut") not in STATUTS: raise CalendarDataError(f"jours_feries.json : statut inconnu ({f.get('id')})")
        _source(f, "jours_feries.json", f.get("id", "?"))
    _source(vac, "vacances_scolaires_ge.json", "fichier")
    for a in vac.get("annees", []):
        if a.get("statut") not in STATUTS: raise CalendarDataError(f"vacances_scolaires_ge.json : statut inconnu ({a.get('annee')})")
        for p in a["periodes"]:
            if _iso(p["du"], "vacances_scolaires_ge.json", a["annee"]) > _iso(p["au"], "vacances_scolaires_ge.json", a["annee"]):
                raise CalendarDataError(f"vacances_scolaires_ge.json : période inversée ({a['annee']} — {p['nom']})")
    return {"echeances": ech, "feries": fer, "vacances": vac}


def revue(donnees):
    """Date de dernière revue de chaque fichier (None = jamais) : la page affiche un bandeau tant qu'un fichier n'a pas été revu dans l'année."""
    return {k: donnees[k].get("revue_le") for k in ("echeances", "feries", "vacances")}


def a_revoir(donnees, aujourdhui):
    out = []
    for k, label in (("echeances", "échéances fiscales et sociales"), ("feries", "jours fériés"), ("vacances", "vacances scolaires")):
        v = donnees[k].get("revue_le")
        if not v: out.append(f"{label} : jamais relues sur la source officielle")
        elif str(v)[:4] != str(aujourdhui.year): out.append(f"{label} : dernière revue le {rules.fr_date(v)} (à refaire cette année)")
    return out


# --- réglages ------------------------------------------------------------------------------------------------------------------------------
def _montant(v, label):
    s = re.sub(r"[\s'’\u00a0\u202f]", "", str(v or "")).replace(",", ".")
    try: d = Decimal(s)
    except InvalidOperation: raise ValueError(f"{label} : nombre invalide")
    if not d.is_finite() or d < 1 or d > Decimal("10000000"): raise ValueError(f"{label} : entre 1 et 10 000 000")
    return d.quantize(CENT, ROUND_HALF_UP)


def _entier(v, label, lo, hi):
    s = str(v or "").strip()
    if not re.fullmatch(r"\d{1,5}", s) or not lo <= int(s) <= hi: raise ValueError(f"{label} : nombre entier entre {lo} et {hi}")
    return int(s)


def valider_reglages(form):
    """Formulaire -> valeurs normalisées (texte, prêtes pour `settings`). ValueError (français) à la première valeur invalide."""
    out = {}
    out["cal_seuil_non_facture"] = format(_montant(form.get("cal_seuil_non_facture"), "Seuil d'heures non facturées"), "f")
    out["cal_seuil_retard"] = format(_montant(form.get("cal_seuil_retard"), "Retard minimal"), "f")
    out["cal_retard_jours"] = str(_entier(form.get("cal_retard_jours"), "Nombre de jours sans facture", 1, 3650))
    out["cal_budget_pct"] = str(_entier(form.get("cal_budget_pct"), "Seuil du bon de commande (%)", 1, 100))
    out["cal_brouillon_jours"] = str(_entier(form.get("cal_brouillon_jours"), "Brouillon ancien (jours)", 1, 365))
    out["cal_paiement_jours"] = str(_entier(form.get("cal_paiement_jours"), "Délai de paiement (jours)", 1, 365))
    if form.get("cal_tva_periodicite") not in TVA_PERIODICITES: raise ValueError("Périodicité TVA inconnue")
    out["cal_tva_periodicite"] = form["cal_tva_periodicite"]
    return out


def reglages(settings):
    """Réglages effectifs (valeurs enregistrées, sinon défauts). Une valeur enregistrée devenue invalide retombe sur le défaut."""
    brut = {k: (settings.get(k) if settings.get(k) not in (None, "") else d) for k, (_, d, _) in REGLAGES.items()}
    try: return valider_reglages(brut) | {"_defauts": False}
    except ValueError:
        return valider_reglages({k: d for k, (_, d, _) in REGLAGES.items()}) | {"_defauts": True}


def types_reglages(cfg):
    return {"seuil_non_facture": Decimal(cfg["cal_seuil_non_facture"]), "seuil_retard": Decimal(cfg["cal_seuil_retard"]),
            "retard_jours": int(cfg["cal_retard_jours"]), "budget_pct": int(cfg["cal_budget_pct"]),
            "brouillon_jours": int(cfg["cal_brouillon_jours"]), "paiement_jours": int(cfg["cal_paiement_jours"]),
            "tva": cfg["cal_tva_periodicite"]}


# --- événements ----------------------------------------------------------------------------------------------------------------------------
def _ev(genre, d, titre, **kw):
    e = {"genre": genre, "date": d, "fin": None, "titre": titre, "detail": "", "source": None, "statut": "", "niveau": "", "lien": "", "public": True}
    e.update(kw); return e


def _remplacer(modele, **kw):
    for k, v in kw.items(): modele = modele.replace("{" + k + "}", str(v))
    return modele


def evenements_echeances(donnees, cfg, debut, fin):
    """Échéances fiscales et sociales entre debut et fin (inclus), d'après echeances.json et la périodicité TVA choisie."""
    reg = types_reglages(cfg); feries = set()
    for a in range(debut.year - 1, fin.year + 2): feries |= {f["date"] for f in jours_feries(a, donnees["feries"])}
    out = []
    for it in donnees["echeances"]["echeances"]:
        if it.get("actif", True) is False: continue
        cond = it.get("condition")
        if cond and cfg.get(cond["reglage"]) != cond["valeur"]: continue
        if it["type"] == "tva" and reg["tva"] == "aucune": continue
        occ = []   # (date, titre, précision)
        for a in range(debut.year - 1, fin.year + 1):
            if it["type"] == "tva":
                for p in it["periodes"]:
                    debut_p, fin_p = date.fromisoformat(f"{a}-{p['du']}"), date.fromisoformat(f"{a}-{p['au']}")
                    occ.append((fin_p + timedelta(days=it["delai_jours"]), _remplacer(it["titre"], periode=f"{p['nom']} {a}"),
                                f"période du {rules.fr_date(debut_p.isoformat())} au {rules.fr_date(fin_p.isoformat())} + {it['delai_jours']} jours"))
            elif it["type"] == "annuel":
                occ.append((date.fromisoformat(f"{a}-{it['mois_jour']}"), _remplacer(it["titre"], annee_fiscale=a - it.get("decalage_annee", 0)), ""))
            else:
                for e in it.get("dates", []):
                    if "date" in e:
                        if a == date.fromisoformat(e["date"]).year: occ.append((date.fromisoformat(e["date"]), it["titre"], e.get("precision", "")))
                    else: occ.append((date.fromisoformat(f"{a}-{e['mois_jour']}"), it["titre"], e.get("precision", "")))
        for d, titre, prec in occ:
            if not debut <= d <= fin: continue
            detail = prec
            if d.weekday() >= 5 or d in feries:
                av = jour_ouvre_precedent(d, feries)
                detail = (detail + " — " if detail else "") + f"tombe un jour non ouvré (week-end ou férié) : viser le jour ouvré précédent, le {rules.fr_date(av.isoformat())} ; un report au jour ouvré suivant est à confirmer, ne pas y compter"
            out.append(_ev("echeance", d, titre, detail=detail, source=it["source"], statut=it["statut"], note=it.get("note", ""), ident=it["id"],
                           source_complementaire=it.get("source_complementaire")))
    return sorted(out, key=lambda e: (e["date"], e["titre"]))


def evenements_feries(donnees, debut, fin):
    out = []
    for a in range(debut.year, fin.year + 1):
        for f in jours_feries(a, donnees["feries"]):
            if debut <= f["date"] <= fin:
                out.append(_ev("ferie", f["date"], f["nom"], detail="Férié fédéral" if f["portee"] == "federal" else "Férié genevois", source=f["source"], statut=f["statut"], ident=f["id"]))
    return out


def evenements_vacances(donnees, debut, fin):
    out = []
    for a in donnees["vacances"]["annees"]:
        for p in a["periodes"]:
            d, f = date.fromisoformat(p["du"]), date.fromisoformat(p["au"])
            if f < debut or d > fin: continue
            out.append(_ev("vacances", d, p["nom"], fin=f, detail=("Estimation — " if a.get("estimation") else "") + f"année scolaire {a['annee']}",
                           source=donnees["vacances"]["source"], statut=a["statut"], ident=f"{a['annee']}-{p['nom']}"))
    return sorted(out, key=lambda e: e["date"])


def _date_ou_none(v):
    try: return date.fromisoformat(str(v or "").strip()[:10])
    except ValueError: return None


def evenements_mandats(c, debut, fin):
    """Jalons tirés de la base, en lecture seule : début et fin prévue des mandats actifs (début + durée), échéances de remboursement des notes de crédit."""
    out = []
    for p in c.execute("SELECT * FROM projects WHERE active=1 ORDER BY name"):
        d0 = _date_ou_none(p["start_date"])
        if not d0: continue
        po = (p["po"] or "").strip()
        dp = f"client {p['client']}" if (p["client"] or "").strip() else ""
        d1 = ajouter_mois(d0, max(1, int(p["duration_months"] or 12))) - timedelta(days=1)
        lien = f"/project/{p['id']}/edit"
        if debut <= d0 <= fin: out.append(_ev("jalon", d0, f"Début du mandat {p['name']}", detail=dp, lien=lien, public=False, ident=f"debut-{p['id']}"))
        if debut <= d1 <= fin:
            bc = (f"bon de commande {po}" if po else "sans bon de commande") + (f", {rules.fr_g(p['ordered_days'])} j commandés" if (p["ordered_days"] or 0) else "")
            out.append(_ev("jalon", d1, f"Fin prévue du mandat {p['name']}", detail=(dp + " · " if dp else "") + bc, lien=lien, public=False, ident=f"fin-{p['id']}"))
    for cn in c.execute("SELECT * FROM credit_notes WHERE status='issued' AND treatment='remboursement' AND refund_due_on IS NOT NULL AND refund_due_on<>''"):
        d = _date_ou_none(cn["refund_due_on"])
        if not d or not debut <= d <= fin: continue
        pos = credits.position(c, cn)
        if pos["balance"] > 0 and not pos["cancelled"]:
            out.append(_ev("jalon", d, f"Remboursement à effectuer — note de crédit {cn['reference']}", detail=f"solde {rules.fr_chf(pos['balance'])} TTC", lien=f"/credit/{cn['id']}", public=False, niveau="warn", ident=f"cn-{cn['id']}"))
    return out


def agenda(c, donnees, cfg, debut, fin, mandats=True):
    ev = evenements_echeances(donnees, cfg, debut, fin) + evenements_feries(donnees, debut, fin) + evenements_vacances(donnees, debut, fin)
    if mandats: ev += evenements_mandats(c, debut, fin)
    ordre = {"echeance": 0, "jalon": 1, "ferie": 2, "vacances": 3}
    return sorted(ev, key=lambda e: (e["date"], ordre[e["genre"]], e["titre"]))


# --- alertes (calculées à la lecture, aucune écriture) ---------------------------------------------------------------------------------------
def _derniere_facture(c, pid):
    """Date de la dernière facture émise (ou facture historique validée) d'un mandat, ou None."""
    dates = [rules.doc_date(r) for r in c.execute("SELECT invoice_date, issued_at FROM invoices WHERE project_id=? AND status='issued'", (pid,))]
    dates += [r[0] for r in c.execute("SELECT invoice_date FROM historical_invoices WHERE project_id=? AND status='validated' AND invoice_date IS NOT NULL", (pid,))]
    dates = [d for d in (_date_ou_none(x) for x in dates) if d]
    return max(dates) if dates else None


def chiffres_mandats(c, aujourdhui):
    """Par mandat actif : travail non facturé (CHF HT, jamais négatif), dernière facture, jours depuis, consommation du bon de commande."""
    out = []
    for p in c.execute("SELECT * FROM projects WHERE active=1 ORDER BY name"):
        pos = rules.contract(c, p)
        taux = Decimal(str(p["rate"] or 0))
        non_fact = (Decimal(str(max(pos["unbilled_days"], 0))) * taux).quantize(CENT, ROUND_HALF_UP)
        derniere = _derniere_facture(c, p["id"])
        premiere = c.execute("SELECT MIN(work_date) FROM entries WHERE project_id=?", (p["id"],)).fetchone()[0]
        repere = derniere or _date_ou_none(premiere) or _date_ou_none(p["start_date"])
        out.append({"id": p["id"], "nom": p["name"], "client": (p["client"] or "").strip(), "non_facture": non_fact, "non_facture_jours": pos["unbilled_days"],
                    "derniere_facture": derniere, "jamais_facture": derniere is None, "repere": repere,
                    "jours_depuis": (aujourdhui - repere).days if repere else None, "commande": float(p["ordered_days"] or 0),
                    "consomme": pos["consumed_days"], "facture": pos["billed_days"]})
    return out


def alertes(c, aujourdhui, cfg):
    """Alertes du moment, de la plus grave à la plus légère. Aucune écriture."""
    reg = types_reglages(cfg); ms = chiffres_mandats(c, aujourdhui); out = []
    par_client = {}
    for m in ms:
        if m["client"]: par_client.setdefault(m["client"].casefold(), []).append(m)
    # 1) travail saisi non facturé au-dessus du seuil (> seuil), par mandat puis par client (si plusieurs mandats et aucun mandat déjà signalé)
    for m in ms:
        if m["non_facture"] > reg["seuil_non_facture"]:
            out.append({"code": "non_facture", "portee": "mandat", "niveau": "err", "titre": f"Heures non facturées : {rules.fr_chf(m['non_facture'])} HT — {m['nom']}",
                        "detail": f"{rules.fr_g(round(m['non_facture_jours'], 2))} j saisis et non facturés, au-dessus du seuil de {rules.fr_chf(reg['seuil_non_facture'])}", "montant": m["non_facture"], "lien": "/?tab=billing", "cle": f"nf-{m['id']}"})
    for cl, lst in par_client.items():
        if len(lst) < 2: continue
        tot = sum((m["non_facture"] for m in lst), Decimal(0))
        if tot > reg["seuil_non_facture"] and not any(m["non_facture"] > reg["seuil_non_facture"] for m in lst):
            out.append({"code": "non_facture", "portee": "client", "niveau": "err", "titre": f"Heures non facturées : {rules.fr_chf(tot)} HT — client {lst[0]['client']}",
                        "detail": f"{len(lst)} mandats ({', '.join(m['nom'] for m in lst)}), au-dessus du seuil de {rules.fr_chf(reg['seuil_non_facture'])}", "montant": tot, "lien": "/?tab=billing", "cle": f"nfc-{cl}"})
    # 2) pas facturé depuis N jours avec un retard >= seuil
    def retard(jours, montant, nom, portee, jamais, lien, cle, repere):
        if jours is None or jours < reg["retard_jours"] or montant < reg["seuil_retard"]: return
        depuis = "jamais facturé (première saisie " + rules.fr_date(repere.isoformat()) + ")" if jamais else "dernière facture le " + rules.fr_date(repere.isoformat())
        out.append({"code": "retard", "portee": portee, "niveau": "err", "titre": f"Pas facturé depuis {jours} jours — {nom}",
                    "detail": f"{depuis} ; {rules.fr_chf(montant)} HT de travail non facturé (seuil {rules.fr_chf(reg['seuil_retard'])}, délai {reg['retard_jours']} jours)", "montant": montant, "lien": lien, "cle": cle})
    for m in ms: retard(m["jours_depuis"], m["non_facture"], m["nom"], "mandat", m["jamais_facture"], "/?tab=billing", f"rt-{m['id']}", m["repere"])
    for cl, lst in par_client.items():
        if len(lst) < 2: continue
        dernieres = [m["derniere_facture"] for m in lst if m["derniere_facture"]]
        derniere = max(dernieres) if dernieres else None
        reperes = [m["repere"] for m in lst if m["repere"]]
        repere = derniere or (min(reperes) if reperes else None)
        tot = sum((m["non_facture"] for m in lst), Decimal(0))
        if repere and not any(a["code"] == "retard" and a["cle"] == f"rt-{m['id']}" for m in lst for a in out):
            retard((aujourdhui - repere).days, tot, "client " + lst[0]["client"], "client", derniere is None, "/?tab=billing", f"rtc-{cl}", repere)
    # 3) bon de commande / budget consommé
    for m in ms:
        if m["commande"] > 0:
            ratio = Decimal(str(m["consomme"])) * 100 / Decimal(str(m["commande"]))
            if ratio > 100: niv, mot = "err", "dépassé"
            elif ratio >= reg["budget_pct"]: niv, mot = "warn", "consommé"
            else: continue
            out.append({"code": "po", "portee": "mandat", "niveau": niv, "titre": f"Bon de commande {mot} à {rules.fr_num(ratio.quantize(Decimal(1), ROUND_HALF_UP), 0)} % — {m['nom']}",
                        "detail": f"{rules.fr_g(round(m['consomme'], 2))} j travaillés sur {rules.fr_g(m['commande'])} j commandés ({rules.fr_g(round(m['facture'], 2))} j facturés) ; seuil d'alerte {reg['budget_pct']} %", "montant": None,
                        "lien": f"/project/{m['id']}/edit", "cle": f"po-{m['id']}"})
    # 4) brouillons anciens
    for d in c.execute("SELECT i.id,i.created_at,i.period_from,i.period_to,p.name project FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.status='draft' ORDER BY i.created_at"):
        cree = _date_ou_none(rules.local_date(d["created_at"]))
        if cree and (aujourdhui - cree).days >= reg["brouillon_jours"]:
            out.append({"code": "brouillon", "portee": "mandat", "niveau": "warn", "titre": f"Brouillon ancien ({(aujourdhui - cree).days} jours) — {d['project']}",
                        "detail": f"période {rules.fr_date(d['period_from'])} → {rules.fr_date(d['period_to'])}, créé le {rules.fr_date(cree.isoformat())}", "montant": None, "lien": f"/issue/{d['id']}", "cle": f"br-{d['id']}"})
    # 5) échéance de paiement atteinte (le paiement lui-même n'est pas suivi : information à vérifier sur le compte)
    for i in c.execute("SELECT i.id,i.number,i.invoice_date,i.issued_at,p.name project FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.status='issued'"):
        emise = _date_ou_none(rules.doc_date(i))
        if not emise: continue
        due = emise + timedelta(days=reg["paiement_jours"])
        if due < aujourdhui <= due + timedelta(days=60):
            out.append({"code": "paiement", "portee": "mandat", "niveau": "info", "titre": f"Échéance de paiement atteinte le {rules.fr_date(due.isoformat())} — facture {i['number']}",
                        "detail": f"{i['project']} : facture du {rules.fr_date(emise.isoformat())}, délai de {reg['paiement_jours']} jours. Le paiement n'est pas suivi dans l'application : vérifier sur le compte avant de relancer.", "montant": None, "lien": f"/invoice/{i['id']}.pdf", "cle": f"pay-{i['id']}"})
    rang = {"err": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda a: (rang[a["niveau"]], -(a["montant"] or 0), a["titre"]))


def resume_tableau_de_bord(c, aujourdhui, settings, horizon=30, max_lignes=6):
    """Encart du tableau de bord : alertes + prochains événements des 30 jours. Ne lève jamais : une erreur de données devient un message."""
    cfg = reglages(settings)
    try:
        donnees = charger()
        prochains = [e for e in agenda(c, donnees, cfg, aujourdhui, aujourdhui + timedelta(days=horizon)) if e["genre"] in ("echeance", "jalon", "ferie")]
        bandeau = a_revoir(donnees, aujourdhui)
    except CalendarDataError as e:
        return {"erreur": str(e), "alertes": alertes(c, aujourdhui, cfg), "prochains": [], "reste": 0, "a_revoir": []}
    return {"erreur": "", "alertes": alertes(c, aujourdhui, cfg), "prochains": prochains[:max_lignes], "reste": max(0, len(prochains) - max_lignes), "a_revoir": bandeau}


# --- vue mois ------------------------------------------------------------------------------------------------------------------------------
def grille_mois(annee, mois, evenements, aujourdhui):
    """Semaines (lundi → dimanche) du mois ; chaque jour porte ses événements (une vacance scolaire couvre chacun de ses jours)."""
    premier = date(annee, mois, 1); dernier = date(annee, mois, _cal.monthrange(annee, mois)[1])
    d = premier - timedelta(days=premier.weekday()); fin = dernier + timedelta(days=6 - dernier.weekday())
    par_jour = {}
    for e in evenements:
        a, b = e["date"], e["fin"] or e["date"]
        k = max(a, d)
        while k <= min(b, fin): par_jour.setdefault(k, []).append(e); k += timedelta(days=1)
    semaines = []
    while d <= fin:
        sem = []
        for _ in range(7):
            ev = par_jour.get(d, [])
            sem.append({"date": d, "dans_mois": d.month == mois, "aujourdhui": d == aujourdhui, "we": d.weekday() >= 5, "evenements": ev,
                        "genres": sorted({e["genre"] for e in ev}), "ferie": any(e["genre"] == "ferie" for e in ev)})
            d += timedelta(days=1)
        semaines.append(sem)
    return semaines


def mois_valide(v, aujourdhui):
    m = re.fullmatch(r"(\d{4})-(\d{2})", str(v or ""))
    if m and 2000 <= int(m[1]) <= 2100 and 1 <= int(m[2]) <= 12: return int(m[1]), int(m[2])
    return aujourdhui.year, aujourdhui.month


# --- export iCalendar (RFC 5545) -------------------------------------------------------------------------------------------------------------
def _echapper(t):
    return str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _plier(ligne):
    """Pliage des lignes à 75 octets maximum (UTF-8, sans couper un caractère), suite précédée d'une espace."""
    b = ligne.encode("utf-8")
    if len(b) <= 75: return [ligne]
    out, cur, limite = [], b"", 75
    for ch in ligne:
        cb = ch.encode("utf-8")
        if len(cur) + len(cb) > limite:
            out.append(cur.decode("utf-8")); cur = b""; limite = 74
        cur += cb
    out.append(cur.decode("utf-8"))
    return [out[0]] + [" " + x for x in out[1:]]


def ics(evenements, maintenant, nom="Time Billing — calendrier"):
    """Flux iCalendar : un événement « journée entière » par échéance / férié / vacances / jalon. Les alertes (état du moment) n'y figurent pas."""
    lignes = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Time Billing//Calendrier 9.2//FR", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
              "X-WR-CALNAME:" + _echapper(nom), "X-WR-TIMEZONE:Europe/Zurich"]
    stamp = maintenant.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for e in evenements:
        fin = (e["fin"] or e["date"]) + timedelta(days=1)    # DTEND exclusif pour une journée entière
        uid = hashlib.sha256(f"{e['genre']}|{e.get('ident', '')}|{e['date'].isoformat()}|{e['titre']}".encode()).hexdigest()[:32] + "@time-billing"
        titre = e["titre"] + (" (à vérifier)" if e.get("statut") == "a_verifier" else "")
        desc = [x for x in (e.get("detail"), ("Source : " + e["source"]["titre"] + " — " + e["source"]["url"]) if e.get("source") else "", "Statut : " + STATUTS.get(e.get("statut"), "") if e.get("statut") else "") if x]
        lignes += ["BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + stamp, "DTSTART;VALUE=DATE:" + e["date"].strftime("%Y%m%d"), "DTEND;VALUE=DATE:" + fin.strftime("%Y%m%d"),
                   "SUMMARY:" + _echapper(titre), "CATEGORIES:" + _echapper(GENRES[e["genre"]]), "TRANSP:TRANSPARENT"]
        if desc: lignes.append("DESCRIPTION:" + _echapper("\n".join(desc)))
        lignes.append("END:VEVENT")
    lignes.append("END:VCALENDAR")
    return "\r\n".join(part for l in lignes for part in _plier(l)) + "\r\n"


# --- jeton d'abonnement (flux sans contenu client) -------------------------------------------------------------------------------------------
def jeton_empreinte(jeton):
    return hashlib.sha256(jeton.encode()).hexdigest()
