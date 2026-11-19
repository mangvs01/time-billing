"""Calendrier des choses importantes (candidat 9.2-rc36) : Pâques et jours fériés, données sourcées, échéances, alertes (seuils), jalons, iCal, routes, jeton d'abonnement.

Aucune règle de facturation / TVA / arrondi / contrôle n'est touchée : les tests d'alerte lisent la base, les tests « aucune écriture » comparent la base avant et après.
Données synthétiques seulement (voir test_import.py pour la commande de lancement). Les alertes reçoivent leur « aujourd'hui » en paramètre : aucun test ne dépend de la date du jour.
"""
import json, os, re, shutil, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import app.app as m
from app import calendar_service as cal
from tests.test_functional import Cycle

DONNEES = cal.charger()
CFG = cal.reglages({})


def jours_feries(y): return {f["nom"]: f["date"].isoformat() for f in cal.jours_feries(y, DONNEES["feries"])}


class Paques(unittest.TestCase):
    # dates de Pâques (grégorien) publiées dans toutes les tables astronomiques usuelles
    CONNUES = {1961: (4, 2), 1990: (4, 15), 1999: (4, 4), 2000: (4, 23), 2008: (3, 23), 2011: (4, 24), 2016: (3, 27), 2019: (4, 21), 2024: (3, 31),
               2025: (4, 20), 2026: (4, 5), 2027: (3, 28), 2028: (4, 16), 2029: (4, 1), 2030: (4, 21), 2038: (4, 25), 2040: (4, 1), 2085: (4, 15), 2100: (3, 28)}

    def test_dates_connues(self):
        for y, (mo, d) in self.CONNUES.items(): self.assertEqual(cal.paques(y), date(y, mo, d), y)

    def test_toujours_un_dimanche_entre_le_22_mars_et_le_25_avril(self):
        for y in range(1900, 2201):
            p = cal.paques(y)
            self.assertEqual(p.weekday(), 6, y)
            self.assertTrue(date(y, 3, 22) <= p <= date(y, 4, 25), y)

    def test_ascension_pentecote_2026(self):
        f = jours_feries(2026)
        self.assertEqual(f["Ascension"], "2026-05-14"); self.assertEqual(f["Lundi de Pentecôte"], "2026-05-25")
        self.assertEqual(f["Vendredi saint"], "2026-04-03"); self.assertEqual(f["Lundi de Pâques"], "2026-04-06")
        for y in range(2000, 2101):   # Ascension = jeudi, Pentecôte = lundi, 39 et 50 jours après Pâques
            f = {x["id"]: x["date"] for x in cal.jours_feries(y, DONNEES["feries"])}
            self.assertEqual((f["ascension"] - cal.paques(y)).days, 39); self.assertEqual(f["ascension"].weekday(), 3)
            self.assertEqual((f["lundi-pentecote"] - cal.paques(y)).days, 50); self.assertEqual(f["lundi-pentecote"].weekday(), 0)
            self.assertEqual(f["vendredi-saint"].weekday(), 4)


class JoursFeriesGeneve(unittest.TestCase):
    ATTENDU = {
        2026: {"Nouvel An": "2026-01-01", "Vendredi saint": "2026-04-03", "Lundi de Pâques": "2026-04-06", "Ascension": "2026-05-14", "Lundi de Pentecôte": "2026-05-25",
               "Fête nationale suisse (1er août)": "2026-08-01", "Jeûne genevois": "2026-09-10", "Noël": "2026-12-25", "Restauration de la République": "2026-12-31"},
        2027: {"Nouvel An": "2027-01-01", "Vendredi saint": "2027-03-26", "Lundi de Pâques": "2027-03-29", "Ascension": "2027-05-06", "Lundi de Pentecôte": "2027-05-17",
               "Fête nationale suisse (1er août)": "2027-08-01", "Jeûne genevois": "2027-09-09", "Noël": "2027-12-25", "Restauration de la République": "2027-12-31"},
        2028: {"Nouvel An": "2028-01-01", "Vendredi saint": "2028-04-14", "Lundi de Pâques": "2028-04-17", "Ascension": "2028-05-25", "Lundi de Pentecôte": "2028-06-05",
               "Fête nationale suisse (1er août)": "2028-08-01", "Jeûne genevois": "2028-09-07", "Noël": "2028-12-25", "Restauration de la République": "2028-12-31"},
    }

    def test_ge_2026_2028(self):
        for y, att in self.ATTENDU.items(): self.assertEqual(jours_feries(y), att, y)

    def test_jeune_genevois_jeudi_apres_le_premier_dimanche_de_septembre(self):
        for y in range(2000, 2101):
            j = cal.jeune_genevois(y)
            self.assertEqual(j.weekday(), 3, y); self.assertEqual(j.month, 9, y)
            dim = j - timedelta(days=4)
            self.assertEqual(dim.weekday(), 6); self.assertLessEqual(dim.day, 7)   # le dimanche précédent est le premier de septembre

    def test_portee_federale_et_genevoise(self):
        p = {f["nom"]: f["portee"] for f in cal.jours_feries(2026, DONNEES["feries"])}
        self.assertEqual({n for n, v in p.items() if v == "federal"}, {"Nouvel An", "Ascension", "Fête nationale suisse (1er août)", "Noël"})
        for n in ("Jeûne genevois", "Restauration de la République", "Vendredi saint", "Lundi de Pâques", "Lundi de Pentecôte"): self.assertEqual(p[n], "GE")

    def test_jour_ouvre(self):
        fer = {f["date"] for a in (2026, 2027) for f in cal.jours_feries(a, DONNEES["feries"])}
        self.assertEqual(cal.jour_ouvre_precedent(date(2026, 12, 31), fer), date(2026, 12, 30))
        self.assertEqual(cal.jour_ouvre_suivant(date(2026, 12, 31), fer), date(2027, 1, 4))   # 1er janvier 2027 = vendredi férié, puis week-end
        self.assertEqual(cal.jour_ouvre_suivant(date(2026, 9, 10), fer), date(2026, 9, 11))


class DonneesSourcees(unittest.TestCase):
    OFFICIELS = ("fedlex.admin.ch", "estv.admin.ch", "ge.ch", "silgeneve.ch", "ahv-iv.ch")

    def toutes_les_sources(self):
        for it in DONNEES["echeances"]["echeances"]: yield "échéance " + it["id"], it["source"], it["statut"]
        for f in DONNEES["feries"]["feries"]: yield "férié " + f["id"], f["source"], f["statut"]
        yield "vacances", DONNEES["vacances"]["source"], "-"

    def test_chaque_date_a_sa_source_officielle(self):
        n = 0
        for nom, s, statut in self.toutes_les_sources():
            n += 1
            self.assertTrue(s["titre"].strip(), nom); self.assertTrue(s["url"].startswith("https://"), nom)
            host = s["url"].split("/")[2]
            self.assertTrue(any(host == o or host.endswith("." + o) for o in self.OFFICIELS), f"{nom} : domaine non officiel {host}")
        self.assertGreaterEqual(n, 14)

    def test_statuts_connus_et_a_verifier_present(self):
        statuts = {it["statut"] for it in DONNEES["echeances"]["echeances"]} | {f["statut"] for f in DONNEES["feries"]["feries"]} | {a["statut"] for a in DONNEES["vacances"]["annees"]}
        self.assertLessEqual(statuts, set(cal.STATUTS))
        self.assertIn("a_verifier", statuts)   # rien n'est présenté comme confirmé sans relecture de la source
        self.assertNotIn("confirme", statuts)

    def test_vacances_scolaires_coherentes(self):
        annees = [a["annee"] for a in DONNEES["vacances"]["annees"]]
        for must in ("2026-2027", "2027-2028"): self.assertIn(must, annees)
        for a in DONNEES["vacances"]["annees"]:
            ps = sorted((date.fromisoformat(p["du"]), date.fromisoformat(p["au"])) for p in a["periodes"])
            for (d1, f1), (d2, f2) in zip(ps, ps[1:]): self.assertLess(f1, d2, a["annee"])   # pas de chevauchement
            for d, f in ps: self.assertLessEqual(d, f)

    def test_fichier_incomplet_refuse(self):
        tmp = tempfile.mkdtemp()
        try:
            for n in os.listdir(cal.DATA_DIR): shutil.copy(os.path.join(cal.DATA_DIR, n), tmp)
            self.assertIn("echeances", cal.charger(tmp))
            e = json.load(open(os.path.join(tmp, "echeances.json"), encoding="utf-8"))
            e["echeances"][0]["source"] = {"titre": "", "url": "http://exemple.invalid"}
            json.dump(e, open(os.path.join(tmp, "echeances.json"), "w", encoding="utf-8"))
            with self.assertRaises(cal.CalendarDataError) as cm: cal.charger(tmp)
            self.assertIn("sans source officielle", str(cm.exception))
            open(os.path.join(tmp, "echeances.json"), "w").write("{pas du json")
            with self.assertRaises(cal.CalendarDataError): cal.charger(tmp)
        finally: shutil.rmtree(tmp, ignore_errors=True)

    def test_revue_annuelle(self):
        self.assertEqual(len(cal.a_revoir(DONNEES, date(2026, 10, 24))), 3)   # jamais relues
        revu = {k: dict(v, revue_le="2026-01-15") for k, v in DONNEES.items()}
        self.assertEqual(cal.a_revoir(revu, date(2026, 10, 24)), [])
        self.assertEqual(len(cal.a_revoir(revu, date(2027, 1, 20))), 3)       # une revue de l'an dernier ne suffit pas


class Echeances(unittest.TestCase):
    def ev(self, debut, fin, **cfg):
        return cal.evenements_echeances(DONNEES, cal.reglages(cfg), debut, fin)

    def test_tva_semestrielle_60_jours(self):
        e = [x for x in self.ev(date(2026, 1, 1), date(2027, 12, 31)) if x["titre"].startswith("Décompte TVA")]
        self.assertEqual([(x["titre"], x["date"].isoformat()) for x in e], [("Décompte TVA — 2e semestre 2025", "2026-03-01"), ("Décompte TVA — 1er semestre 2026", "2026-08-29"),
                                                                              ("Décompte TVA — 2e semestre 2026", "2027-03-01"), ("Décompte TVA — 1er semestre 2027", "2027-08-29")])
        for x in e: self.assertEqual(x["statut"], "regle_legale")

    def test_tva_trimestrielle_60_jours(self):
        e = [x for x in self.ev(date(2026, 1, 1), date(2026, 12, 31), cal_tva_periodicite="trimestriel") if x["titre"].startswith("Décompte TVA")]
        self.assertEqual([x["date"].isoformat() for x in e], ["2026-03-01", "2026-05-30", "2026-08-29", "2026-11-29"])
        self.assertTrue(e[0]["titre"].endswith("4e trimestre 2025"))

    def test_sans_tva_aucune_echeance_tva(self):
        self.assertFalse([x for x in self.ev(date(2026, 1, 1), date(2027, 12, 31), cal_tva_periodicite="aucune") if "TVA" in x["titre"]])

    def test_impot_geneve_et_acomptes(self):
        e = self.ev(date(2027, 1, 1), date(2027, 12, 31))
        imp = [x for x in e if x["titre"].startswith("Déclaration d'impôt Genève")]
        self.assertEqual([(x["titre"][:33], x["date"].isoformat(), x["statut"]) for x in imp], [("Déclaration d'impôt Genève 2026 (", "2027-03-31", "a_verifier")])
        self.assertEqual([x["date"].isoformat() for x in e if "AVS" in x["titre"]], ["2027-03-31", "2027-06-30", "2027-09-30", "2027-12-31"])
        self.assertTrue(all(x["statut"] == "a_verifier" for x in e if "AVS" in x["titre"]))
        self.assertEqual([x["date"].isoformat() for x in e if "pilier 3a" in x["titre"]], ["2027-12-31"])
        self.assertFalse([x for x in e if "impôt cantonal" in x["titre"]])   # modèle désactivé

    def test_jour_non_ouvre_signale(self):
        x = [x for x in self.ev(date(2026, 12, 1), date(2026, 12, 31)) if "3a" in x["titre"]][0]
        self.assertIn("jour ouvré précédent, le 30.12.2026", x["detail"])
        y = [x for x in self.ev(date(2027, 3, 1), date(2027, 3, 31)) if "Déclaration" in x["titre"]][0]
        self.assertNotIn("non ouvré", y["detail"])   # 31.03.2027 = mercredi

    def test_vacances_scolaires(self):
        v = cal.evenements_vacances(DONNEES, date(2026, 10, 1), date(2027, 1, 31))
        self.assertEqual([(x["titre"], x["date"].isoformat(), x["fin"].isoformat()) for x in v][:2], [("Vacances d'automne", "2026-10-26", "2026-10-30"), ("Vacances de Noël", "2026-12-21", "2027-01-01")])
        self.assertTrue(all(x["statut"] == "a_verifier" and x["detail"].startswith("Estimation") for x in v))


class Reglages(unittest.TestCase):
    def test_defauts(self):
        self.assertEqual({k: CFG[k] for k in cal.REGLAGES}, {"cal_seuil_non_facture": "8000.00", "cal_retard_jours": "45", "cal_seuil_retard": "8000.00", "cal_budget_pct": "80",
                                                              "cal_brouillon_jours": "14", "cal_paiement_jours": "30", "cal_tva_periodicite": "semestriel"})

    def form(self, **kw): return dict({k: d for k, (_, d, _) in cal.REGLAGES.items()}, **kw)

    def test_valeurs_valides_et_formats_suisses(self):
        v = cal.valider_reglages(self.form(cal_seuil_non_facture="12'500", cal_seuil_retard="8 000,50", cal_budget_pct="90"))
        self.assertEqual((v["cal_seuil_non_facture"], v["cal_seuil_retard"], v["cal_budget_pct"]), ("12500.00", "8000.50", "90"))

    def test_valeurs_invalides(self):
        for k, bad in (("cal_seuil_non_facture", "abc"), ("cal_seuil_non_facture", "0"), ("cal_seuil_non_facture", "-5"), ("cal_seuil_non_facture", "1e99"), ("cal_seuil_non_facture", "NaN"),
                       ("cal_budget_pct", "0"), ("cal_budget_pct", "101"), ("cal_retard_jours", "0"), ("cal_retard_jours", "12.5"), ("cal_brouillon_jours", "366"),
                       ("cal_paiement_jours", ""), ("cal_tva_periodicite", "mensuel")):
            with self.assertRaises(ValueError, msg=(k, bad)): cal.valider_reglages(self.form(**{k: bad}))

    def test_valeur_enregistree_invalide_retombe_sur_defaut(self):
        r = cal.reglages({"cal_seuil_non_facture": "n'importe quoi"})
        self.assertEqual(r["cal_seuil_non_facture"], "8000.00"); self.assertTrue(r["_defauts"])


class Ics(unittest.TestCase):
    @staticmethod
    def analyser(texte):
        """Analyseur iCalendar minimal et strict (RFC 5545 §3.1) : CRLF, lignes ≤ 75 octets, dépliage, VEVENT complets."""
        assert texte.endswith("\r\n") and "\n" not in texte.replace("\r\n", ""), "fins de ligne CRLF"
        brutes = texte[:-2].split("\r\n")
        for l in brutes: assert len(l.encode("utf-8")) <= 75, f"ligne trop longue : {l!r}"
        lignes = []
        for l in brutes:
            if l.startswith((" ", "\t")): lignes[-1] += l[1:]
            else: lignes.append(l)
        assert lignes[0] == "BEGIN:VCALENDAR" and lignes[-1] == "END:VCALENDAR"
        assert "VERSION:2.0" in lignes and any(l.startswith("PRODID:") for l in lignes)
        events, cur = [], None
        for l in lignes[1:-1]:
            if l == "BEGIN:VEVENT": assert cur is None; cur = {}
            elif l == "END:VEVENT": events.append(cur); cur = None
            elif cur is not None:
                nom, _, val = l.partition(":"); cur[nom] = val
        assert cur is None
        return events

    def test_flux_valide(self):
        ev = cal.agenda(None, DONNEES, CFG, date(2026, 1, 1), date(2027, 12, 31), mandats=False)
        txt = cal.ics(ev, datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc))
        evs = self.analyser(txt)
        self.assertEqual(len(evs), len(ev)); self.assertGreater(len(evs), 40)
        uids = [e["UID"] for e in evs]; self.assertEqual(len(uids), len(set(uids)))
        for e in evs:
            self.assertEqual(e["DTSTAMP"], "20261024T120000Z")
            self.assertTrue(re.fullmatch(r"\d{8}", e["DTSTART;VALUE=DATE"])); self.assertTrue(re.fullmatch(r"\d{8}", e["DTEND;VALUE=DATE"]))
            self.assertGreater(e["DTEND;VALUE=DATE"], e["DTSTART;VALUE=DATE"]); self.assertTrue(e["SUMMARY"])
        self.assertEqual(txt, cal.ics(ev, datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)))   # stable : les agendas ne dupliquent pas

    def test_evenement_sur_plusieurs_jours_et_a_verifier(self):
        ev = [e for e in cal.evenements_vacances(DONNEES, date(2026, 12, 1), date(2026, 12, 31))]
        evs = self.analyser(cal.ics(ev, datetime(2026, 10, 24, tzinfo=timezone.utc)))
        self.assertEqual((evs[0]["DTSTART;VALUE=DATE"], evs[0]["DTEND;VALUE=DATE"]), ("20261221", "20270102"))   # DTEND exclusif : dernier jour 01.01.2027
        self.assertIn("(à vérifier)", evs[0]["SUMMARY"])

    def test_echappement_et_pliage_utf8(self):
        longue = "Échéance, avec ; virgule et point-virgule " + "é" * 120
        e = {"genre": "echeance", "date": date(2026, 3, 1), "fin": None, "titre": longue, "detail": "ligne 1\nligne 2 \\ fin", "source": {"titre": "S", "url": "https://www.ge.ch/"}, "statut": "a_verifier"}
        txt = cal.ics([e], datetime(2026, 1, 1, tzinfo=timezone.utc))
        evs = self.analyser(txt)   # lignes ≤ 75 octets et dépliage sans couper un caractère (le décodage UTF-8 réussit)
        self.assertIn("\\, avec \\; virgule", evs[0]["SUMMARY"]); self.assertIn("ligne 1\\nligne 2 \\\\ fin", evs[0]["DESCRIPTION"])
        self.assertEqual(evs[0]["SUMMARY"].count("é"), longue.count("é") + "(à vérifier)".count("é"))


class Base3(Cycle):
    """Mandats synthétiques dans la base jetable ; les alertes reçoivent leur date en paramètre."""
    RECORD_WORK = False

    def alertes(self, today, **cfg):
        c = m.db()
        try: return cal.alertes(c, today, cal.reglages(cfg))
        finally: c.close()

    def codes(self, al): return sorted((a["code"], a["portee"], a["niveau"]) for a in al)

    def travail(self, pid, jours, debut='2026-10-01', heures=8):
        """`jours` journées de `heures` h sur des jours consécutifs à partir de debut."""
        d = date.fromisoformat(debut)
        for i in range(jours):
            self.entry(pid, (d + timedelta(days=i)).isoformat(), heures)

    def facture_sept(self, pid, h=8, qty=1):
        self.entry(pid, '2026-09-02', h)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', qty, invoice_date='2026-09-30')
        self.issue(iid)
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'issued', self.flashes())
        return iid

    def etat(self):
        return (self.scalar('SELECT COUNT(*) FROM audit'), [tuple(r) for r in self.sql('SELECT * FROM invoices ORDER BY id')], [tuple(r) for r in self.sql('SELECT * FROM entries ORDER BY id')],
                [tuple(r) for r in self.sql('SELECT key,value FROM settings ORDER BY key')], [tuple(r) for r in self.sql('SELECT * FROM projects ORDER BY id')],
                self.scalar('SELECT COUNT(*) FROM credit_notes'), self.scalar('SELECT COUNT(*) FROM historical_invoices'))


class AlertesSeuils(Base3):
    def test_non_facture_au_dessus_du_seuil_strictement(self):
        pid = self.mandate(name='Mandat 8000', rate='1000', ordered='0', start='2026-01-01', months='12')
        self.travail(pid, 8)   # 8 j × 1 000 = 8 000,00 CHF : égal au seuil -> pas d'alerte (strictement supérieur)
        self.assertEqual([a for a in self.alertes(date(2026, 10, 24)) if a['code'] == 'non_facture'], [])
        self.entry(pid, '2026-10-20', 0.5)   # 8,0625 j -> 8 062,50 CHF
        al = [a for a in self.alertes(date(2026, 10, 24)) if a['code'] == 'non_facture']
        self.assertEqual(len(al), 1); self.assertEqual(al[0]['montant'], Decimal('8062.50')); self.assertEqual(al[0]['niveau'], 'err')
        self.assertIn('Mandat 8000', al[0]['titre']); self.assertIn('8', al[0]['titre'])

    def test_seuil_reglable(self):
        pid = self.mandate(name='Mandat seuil', rate='1000', ordered='0', start='2026-01-01', months='12')
        self.travail(pid, 3)   # 3 000 CHF
        self.assertFalse([a for a in self.alertes(date(2026, 10, 24)) if a['code'] == 'non_facture'])
        self.assertTrue([a for a in self.alertes(date(2026, 10, 24), cal_seuil_non_facture='2500') if a['code'] == 'non_facture'])

    def test_une_facture_emise_reduit_le_non_facture(self):
        pid = self.mandate(name='Mandat facturé', rate='1000', ordered='40', start='2026-01-01', months='12')
        self.facture_sept(pid)
        self.travail(pid, 7)   # 7 000 CHF non facturés -> sous le seuil
        self.assertFalse([a for a in self.alertes(date(2026, 10, 24)) if a['code'] == 'non_facture'])
        self.entry(pid, '2026-10-20', 8); self.entry(pid, '2026-10-21', 8)   # 9 000
        self.assertEqual(len([a for a in self.alertes(date(2026, 10, 24)) if a['code'] == 'non_facture']), 1)

    def test_client_sur_plusieurs_mandats(self):
        a = self.mandate(name='Mandat A', rate='1000', ordered='0', start='2026-01-01', months='12')
        b = self.mandate(name='Mandat B', rate='1000', ordered='0', start='2026-01-01', months='12')   # même client « Client Fictif SA »
        self.travail(a, 5); self.travail(b, 5, debut='2026-10-10')   # 5 000 + 5 000 : aucun mandat seul au-dessus, le client oui
        al = [x for x in self.alertes(date(2026, 10, 24)) if x['code'] == 'non_facture']
        self.assertEqual([(x['portee'], x['montant']) for x in al], [('client', Decimal('10000.00'))])
        self.assertIn('Client Fictif SA', al[0]['titre'])
        self.travail(a, 4, debut='2026-10-12')   # le mandat A seul dépasse (9 000) : alerte de mandat, plus d'alerte client en double
        al = [x for x in self.alertes(date(2026, 10, 24)) if x['code'] == 'non_facture']
        self.assertEqual([x['portee'] for x in al], ['mandat'])

    def test_mandat_cloture_ignore(self):
        import sqlite3
        pid = self.mandate(name='Mandat clos', rate='1000', ordered='0', start='2026-01-01', months='12')
        self.travail(pid, 10)
        self.assertTrue(self.alertes(date(2026, 10, 24)))
        cn = sqlite3.connect(self.db); cn.execute('UPDATE projects SET active=0 WHERE id=?', (pid,)); cn.commit(); cn.close()   # clôture simulée : le calendrier ne lit que les mandats actifs
        self.assertEqual([a for a in self.alertes(date(2026, 10, 24)) if a['code'] in ('non_facture', 'retard')], [])


class AlertesRetard(Base3):
    def test_pas_facture_depuis_n_jours_et_retard(self):
        pid = self.mandate(name='Mandat retard', rate='1000', ordered='60', start='2026-01-01', months='12')
        self.facture_sept(pid)                # dernière facture : 30.09.2026
        self.travail(pid, 10)                 # 10 000 CHF non facturés
        r = [a for a in self.alertes(date(2026, 11, 20)) if a['code'] == 'retard']
        self.assertEqual(len(r), 1); self.assertIn('Pas facturé depuis 51 jours', r[0]['titre']); self.assertEqual(r[0]['montant'], Decimal('10000.00'))
        self.assertIn('dernière facture le 30.09.2026', r[0]['detail'])

    def test_limite_des_jours_et_du_montant(self):
        pid = self.mandate(name='Mandat limite', rate='1000', ordered='60', start='2026-01-01', months='12')
        self.facture_sept(pid); self.travail(pid, 8)   # exactement 8 000 : retard « ≥ 8 000 » -> alerte dès le 45e jour
        self.assertFalse([a for a in self.alertes(date(2026, 11, 13)) if a['code'] == 'retard'])   # 44 jours
        self.assertEqual(len([a for a in self.alertes(date(2026, 11, 14)) if a['code'] == 'retard']), 1)   # 45 jours
        self.assertFalse([a for a in self.alertes(date(2026, 11, 14), cal_seuil_retard='8000.01') if a['code'] == 'retard'])   # 8 000,00 < seuil de 8 000,01

    def test_jamais_facture(self):
        pid = self.mandate(name='Mandat neuf', rate='1000', ordered='0', start='2026-01-01', months='12')
        self.travail(pid, 9, debut='2026-08-03')
        r = [a for a in self.alertes(date(2026, 10, 24)) if a['code'] == 'retard']
        self.assertEqual(len(r), 1); self.assertIn('jamais facturé (première saisie 03.08.2026)', r[0]['detail']); self.assertIn('82 jours', r[0]['titre'])

    def test_pas_de_retard_sans_montant(self):
        pid = self.mandate(name='Mandat calme', rate='1000', ordered='60', start='2026-01-01', months='12')
        self.facture_sept(pid)
        self.assertFalse([a for a in self.alertes(date(2027, 3, 1)) if a['code'] == 'retard'])   # plus de 150 jours mais rien à facturer

    def test_retard_au_niveau_client(self):
        a = self.mandate(name='Mandat A2', rate='1000', ordered='0', start='2026-01-01', months='12')
        b = self.mandate(name='Mandat B2', rate='1000', ordered='0', start='2026-01-01', months='12')
        self.travail(a, 5, debut='2026-08-03'); self.travail(b, 5, debut='2026-08-10')
        r = [x for x in self.alertes(date(2026, 10, 24)) if x['code'] == 'retard']
        self.assertEqual([(x['portee'], x['montant']) for x in r], [('client', Decimal('10000.00'))])


class AlertesPoBrouillonsPaiement(Base3):
    def po(self, ordered, jours):
        pid = self.mandate(name=f'Mandat PO {ordered}-{jours}', rate='1', ordered=str(ordered), start='2026-01-01', months='12')
        self.travail(pid, int(jours), heures=8)
        return [a for a in self.alertes(date(2026, 10, 24)) if a['code'] == 'po']

    def test_seuils_du_bon_de_commande(self):
        self.assertEqual(self.po(10, 7), [])                                   # 70 %
        a = self.po(10, 8)                                                     # 80 % exactement -> alerte (≥)
        self.assertEqual([(x['niveau'], x['titre'][:35]) for x in a], [('warn', 'Bon de commande consommé à 80 % — M')])
        a = self.po(10, 10)                                                    # 100 % : consommé, pas dépassé
        self.assertEqual(a[0]['niveau'], 'warn')

    def test_depassement(self):
        pid = self.mandate(name='Mandat dépassé', rate='1', ordered='10', start='2026-01-01', months='12')
        self.travail(pid, 10); self.entry(pid, '2026-10-20', 2)
        a = [x for x in self.alertes(date(2026, 10, 24)) if x['code'] == 'po']
        self.assertEqual((a[0]['niveau'], a[0]['titre'][:35]), ('err', 'Bon de commande dépassé à 103 % — M'))

    def test_seuil_pct_reglable_et_sans_po(self):
        pid = self.mandate(name='Mandat 5 j', rate='1', ordered='10', start='2026-01-01', months='12'); self.travail(pid, 5)
        self.assertFalse([x for x in self.alertes(date(2026, 10, 24)) if x['code'] == 'po'])
        self.assertTrue([x for x in self.alertes(date(2026, 10, 24), cal_budget_pct='50') if x['code'] == 'po'])
        self.mandate(name='Mandat sans PO', rate='1', ordered='0', start='2026-01-01', months='12')
        self.assertFalse([x for x in self.alertes(date(2026, 10, 24), cal_budget_pct='1') if x['code'] == 'po' and 'sans PO' in x['titre']])

    def test_brouillon_ancien(self):
        pid = self.mandate(name='Mandat brouillon', rate='1000', ordered='60', start='2026-01-01', months='12')
        self.entry(pid, '2026-09-02', 8)
        iid, _ = self.draft(pid, '2026-09-01', '2026-09-30', 1, invoice_date='2026-09-30')
        self.assertEqual(self.scalar('SELECT status FROM invoices WHERE id=?', (iid,)), 'draft')
        cree = date.fromisoformat(m.rules.local_date(self.scalar("SELECT created_at FROM invoices WHERE id=?", (iid,))))   # jour de Zurich, comme le service
        self.assertFalse([a for a in self.alertes(cree + timedelta(days=13)) if a['code'] == 'brouillon'])
        b = [a for a in self.alertes(cree + timedelta(days=14)) if a['code'] == 'brouillon']
        self.assertEqual(len(b), 1); self.assertEqual(b[0]['lien'], f'/issue/{iid}'); self.assertIn('14 jours', b[0]['titre'])
        self.assertTrue([a for a in self.alertes(cree + timedelta(days=3), cal_brouillon_jours='2') if a['code'] == 'brouillon'])

    def test_echeance_de_paiement(self):
        pid = self.mandate(name='Mandat paiement', rate='1000', ordered='60', start='2026-01-01', months='12')
        iid = self.facture_sept(pid)                                          # facture du 30.09.2026, échéance 30.10.2026
        num = self.scalar('SELECT number FROM invoices WHERE id=?', (iid,))
        self.assertFalse([a for a in self.alertes(date(2026, 10, 30)) if a['code'] == 'paiement'])
        p = [a for a in self.alertes(date(2026, 10, 31)) if a['code'] == 'paiement']
        self.assertEqual(len(p), 1); self.assertEqual(p[0]['niveau'], 'info'); self.assertIn(num, p[0]['titre']); self.assertIn("n'est pas suivi", p[0]['detail'])
        self.assertTrue([a for a in self.alertes(date(2026, 12, 29)) if a['code'] == 'paiement'])      # dernier jour de la fenêtre de 60 jours
        self.assertFalse([a for a in self.alertes(date(2026, 12, 30)) if a['code'] == 'paiement'])

    def test_ordre_des_alertes(self):
        pid = self.mandate(name='Mandat ordre', rate='1000', ordered='9', start='2026-01-01', months='12')
        self.facture_sept(pid); self.travail(pid, 9)
        niv = [a['niveau'] for a in self.alertes(date(2026, 11, 20))]
        self.assertEqual(niv, sorted(niv, key={'err': 0, 'warn': 1, 'info': 2}.get))
        self.assertTrue({'err', 'info'} <= set(niv))


class Jalons(Base3):
    def test_debut_fin_et_hors_periode(self):
        pid = self.mandate(name='Mandat jalons', rate='1000', ordered='20', start='2026-11-01', months='11')
        c = m.db()
        try:
            ev = cal.evenements_mandats(c, date(2026, 11, 1), date(2027, 12, 31))
            self.assertEqual([(e['titre'], e['date'].isoformat(), e['public']) for e in ev if 'jalons' in e['titre']],
                             [('Début du mandat Mandat jalons', '2026-11-01', False), ('Fin prévue du mandat Mandat jalons', '2027-09-30', False)])
            fin = [e for e in ev if e['titre'].startswith('Fin prévue')][0]
            self.assertIn('PO-TEST-001', fin['detail']); self.assertIn('20 j commandés', fin['detail']); self.assertEqual(fin['lien'], f'/project/{pid}/edit')
            self.assertEqual([e for e in cal.evenements_mandats(c, date(2028, 1, 1), date(2028, 12, 31))], [])
        finally: c.close()

    def test_agenda_trie_et_sans_mandats_pour_le_flux_public(self):
        self.mandate(name='Mandat tri', rate='1000', ordered='20', start='2026-11-01', months='11')
        c = m.db()
        try:
            ev = cal.agenda(c, DONNEES, CFG, date(2026, 10, 24), date(2026, 12, 31))
            self.assertEqual([e['date'] for e in ev], sorted(e['date'] for e in ev))
            self.assertTrue(any(e['genre'] == 'jalon' for e in ev))
            self.assertFalse(any(e['genre'] == 'jalon' for e in cal.agenda(c, DONNEES, CFG, date(2026, 10, 24), date(2026, 12, 31), mandats=False)))
        finally: c.close()


class Pages(Base3):
    def test_authentification_requise(self):
        anon = m.APP.test_client()
        for u in ('/calendrier', '/calendrier.ics'):
            r = anon.get(u); self.assertEqual(r.status_code, 302, u); self.assertIn('/login', r.headers['Location'])
        for u in ('/calendrier/reglages', '/calendrier/abonnement', '/calendrier/abonnement/revoquer'):
            r = anon.post(u, data={}); self.assertEqual(r.status_code, 302, u); self.assertIn('/login', r.headers['Location'])

    def test_page_calendrier(self):
        pid = self.mandate(name='Mandat page', rate='1000', ordered='0', start='2026-01-01', months='12'); self.travail(pid, 10)
        before = self.etat()
        r = self.c.get('/calendrier?mois=2026-12'); self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        for needle in ('id="calAlertes"', 'id="calProchains"', 'id="calMois"', 'Décembre 2026', 'Restauration de la République', 'id="calIcs"', 'id="calReglages"', 'id="calSources"', 'id="calRevue"',
                       'Heures non facturées', 'à vérifier', 'Vacances de Noël', 'href="/calendrier.ics"', '/calendrier?mois=2026-11', '/calendrier?mois=2027-01', 'Source :'):
            self.assertIn(needle, h, needle)
        self.assertEqual(len(re.findall(r'<tr>(?:<td[^>]*data-date=)', h)), 5)   # décembre 2026 : 5 semaines (lun. 30.11 → dim. 03.01)
        self.assertEqual(self.etat(), before)   # une page n'écrit rien

    def test_mois_invalide_retombe_sur_le_mois_courant(self):
        today = m.rules.local_today()
        for q in ('', '?mois=abc', '?mois=2026-13', '?mois=1999-01', '?mois=2026-1'):
            h = self.c.get('/calendrier' + q).get_data(as_text=True)
            self.assertIn(f'{today.year}</h2>', h, q)

    def test_tableau_de_bord_encart(self):
        pid = self.mandate(name='Mandat tableau', rate='1000', ordered='0', start='2026-01-01', months='12'); self.travail(pid, 10)
        before = self.etat()
        h = self.c.get('/?tab=dashboard').get_data(as_text=True)
        self.assertIn('id="calPanel"', h); self.assertIn('Calendrier et alertes', h); self.assertIn('href="/calendrier"', h)
        self.assertIn('data-alert="non_facture"', h); self.assertIn('id="reglagesCalendrier"', h)
        self.assertEqual(self.etat(), before)

    def test_navigation(self):
        h = self.c.get('/?tab=dashboard').get_data(as_text=True)
        self.assertGreaterEqual(h.count('href="/calendrier"'), 3)   # menu latéral, menu « Plus » du téléphone, encart
        h = self.c.get('/calendrier').get_data(as_text=True)
        self.assertIn('aria-current="page">Calendrier</a>', h)

    def test_csp_et_couleurs(self):
        r = self.c.get('/calendrier'); h = r.get_data(as_text=True)
        self.assertIn("script-src 'self' 'nonce-", r.headers['Content-Security-Policy'])
        for tag in re.findall(r'<script\b[^>]*>', h): self.assertIn('nonce="', tag)
        self.assertFalse(re.findall(r'\bon[a-z]+=["\']', h.split('<body', 1)[1]), 'aucun gestionnaire inline')
        css = open(os.path.join(os.path.dirname(m.__file__), 'templates', '_ds.html'), encoding='utf-8').read()
        bloc = css[css.index('/* ---------- Calendrier (candidat rc36)'):css.index("/* ---------- préférences d'accessibilité")]
        self.assertGreater(len(bloc), 3000)
        self.assertFalse(re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(', bloc), 'couleurs en dur dans le CSS du calendrier : utiliser les jetons')
        for n in ('calendrier.html', '_calendrier_blocs.html', '_calendrier_reglages.html'):
            t = open(os.path.join(os.path.dirname(m.__file__), 'templates', n), encoding='utf-8').read()
            self.assertFalse(re.findall(r'#[0-9a-fA-F]{6}\b|rgba?\(|style="[^"]*(?:color|background)', t), n)

    def test_ics_authentifie(self):
        self.mandate(name='Mandat flux', rate='1000', ordered='0', start='2026-11-01', months='11')
        before = self.etat()
        r = self.c.get('/calendrier.ics'); self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers['Content-Type'].startswith('text/calendar')); self.assertIn('attachment', r.headers['Content-Disposition'])
        self.assertEqual(r.headers['Cache-Control'], 'no-store')
        txt = r.get_data(as_text=True); evs = Ics.analyser(txt)
        self.assertGreater(len(evs), 40)
        self.assertIn('Mandat flux', txt)                                  # le flux authentifié contient les jalons des mandats
        self.assertEqual(self.etat(), before)


class Reglages_HTTP(Base3):
    def form(self, **kw): return dict({k: d for k, (_, d, _) in cal.REGLAGES.items()}, **dict({'retour': 'calendrier'}, **kw))

    def test_enregistrement_et_audit(self):
        n = self.scalar('SELECT COUNT(*) FROM audit')
        r = self.c.post('/calendrier/reglages', data=self.form(cal_seuil_non_facture="12'000", cal_budget_pct='90', cal_tva_periodicite='trimestriel'))
        self.assertEqual(r.status_code, 302); self.assertTrue(r.headers['Location'].endswith('/calendrier'))
        got = dict((r['key'], r['value']) for r in self.sql("SELECT key,value FROM settings WHERE key LIKE 'cal\\_%' ESCAPE '\\'"))
        self.assertEqual(got, {'cal_seuil_non_facture': '12000.00', 'cal_budget_pct': '90', 'cal_tva_periodicite': 'trimestriel'})   # seules les valeurs modifiées sont écrites
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM audit'), n + 1)
        self.assertEqual(self.sql("SELECT detail FROM audit ORDER BY id DESC LIMIT 1")[0][0], 'calendrier : cal_seuil_non_facture, cal_budget_pct, cal_tva_periodicite')
        h = self.c.get('/calendrier').get_data(as_text=True)
        self.assertIn('value="12000.00"', h); self.assertIn('<option value="trimestriel" selected>', h)

    def test_inchange_n_ecrit_rien(self):
        before = self.etat()
        self.c.post('/calendrier/reglages', data=self.form())
        self.assertEqual(self.etat(), before)

    def test_valeur_invalide_refusee_sans_rien_ecrire(self):
        before = self.etat()
        r = self.c.post('/calendrier/reglages', data=self.form(cal_budget_pct='150', retour='settings'))
        self.assertEqual(r.status_code, 302); self.assertIn('tab=settings', r.headers['Location'])
        self.assertTrue(any('non enregistrés' in f and 'pourcentage' not in f and '%' in f for f in self.flashes()))
        self.assertEqual(self.etat(), before)

    def test_alerte_suit_le_reglage(self):
        pid = self.mandate(name='Mandat réglage', rate='1000', ordered='0', start='2026-01-01', months='12'); self.travail(pid, 3)
        self.assertNotIn('data-alert="non_facture"', self.c.get('/calendrier').get_data(as_text=True))
        self.c.post('/calendrier/reglages', data=self.form(cal_seuil_non_facture='2000'))
        self.assertIn('data-alert="non_facture"', self.c.get('/calendrier').get_data(as_text=True))


class Abonnement(Base3):
    def creer(self):
        r = self.c.post('/calendrier/abonnement'); self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        liens = re.findall(r'http://localhost/calendrier/abonnement/([A-Za-z0-9_-]{43})\.ics', h)
        self.assertEqual(len(liens), 1, h[-3000:])
        return liens[0], h

    def test_cycle_jeton(self):
        pid = self.mandate(name='Mandat Secret XYZ', rate='1000', ordered='0', start='2026-11-01', months='11')
        anon = m.APP.test_client()
        tok, page = self.creer()
        self.assertIn('id="calNouveauLien"', page)
        # seule l'empreinte est conservée
        stock = self.scalar("SELECT value FROM settings WHERE key='cal_ics_token_sha256'")
        self.assertEqual(stock, cal.jeton_empreinte(tok)); self.assertNotIn(tok, json.dumps([tuple(r) for r in self.sql('SELECT * FROM settings')]))
        self.assertNotIn(tok, json.dumps([tuple(r) for r in self.sql('SELECT * FROM audit')]))
        # le flux répond SANS session, ne contient aucune donnée client ni de mandat
        r = anon.get(f'/calendrier/abonnement/{tok}.ics'); self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers['Content-Type'].startswith('text/calendar')); self.assertEqual(r.headers['Cache-Control'], 'no-store')
        txt = r.get_data(as_text=True); Ics.analyser(txt)
        for secret in ('Mandat Secret XYZ', 'Client Fictif', 'PO-TEST-001', 'Début du mandat', 'Fin prévue'): self.assertNotIn(secret, txt)
        self.assertIn('Jeûne genevois', txt)
        # la page ne réaffiche plus le lien ; jeton erroné ou mal formé : 404
        self.assertNotIn(tok, self.c.get('/calendrier').get_data(as_text=True))
        for bad in ('x' * 43, tok[:-1] + ('A' if tok[-1] != 'A' else 'B'), 'court', tok + 'a'):
            self.assertEqual(anon.get(f'/calendrier/abonnement/{bad}.ics').status_code, 404, bad)
        # remplacement : l'ancien lien cesse de fonctionner
        tok2, _ = self.creer(); self.assertNotEqual(tok, tok2)
        self.assertEqual(anon.get(f'/calendrier/abonnement/{tok}.ics').status_code, 404)
        self.assertEqual(anon.get(f'/calendrier/abonnement/{tok2}.ics').status_code, 200)
        # révocation
        r = self.c.post('/calendrier/abonnement/revoquer'); self.assertEqual(r.status_code, 302)
        self.assertEqual(anon.get(f'/calendrier/abonnement/{tok2}.ics').status_code, 404)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM settings WHERE key='cal_ics_token_sha256'"), 0)
        ev = [r[0] for r in self.sql("SELECT event FROM audit WHERE event LIKE 'calendar_feed_token_%' ORDER BY id")]
        self.assertEqual(ev, ['calendar_feed_token_created', 'calendar_feed_token_created', 'calendar_feed_token_revoked'])

    def test_sans_jeton_configure_tout_est_404(self):
        anon = m.APP.test_client()
        self.assertEqual(anon.get('/calendrier/abonnement/' + 'a' * 43 + '.ics').status_code, 404)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM settings WHERE key='cal_ics_token_sha256'")[0][0], 0)

    def test_lecture_du_flux_n_ecrit_rien(self):
        tok, _ = self.creer(); before = self.etat()
        m.APP.test_client().get(f'/calendrier/abonnement/{tok}.ics'); m.APP.test_client().get('/calendrier/abonnement/' + 'z' * 43 + '.ics')
        self.assertEqual(self.etat(), before)

    def test_jeton_post_depuis_un_autre_site_refuse(self):
        r = self.c.post('/calendrier/abonnement', headers={'Origin': 'https://autre.invalid', 'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM settings WHERE key='cal_ics_token_sha256'"), 0)


class DonneesIllisibles(Base3):
    def test_page_et_tableau_de_bord_survivent(self):
        orig = cal.DATA_DIR
        tmp = tempfile.mkdtemp()
        try:
            cal.DATA_DIR = tmp   # dossier vide : fichiers absents
            h = self.c.get('/calendrier'); self.assertEqual(h.status_code, 200); self.assertIn('id="calErreur"', h.get_data(as_text=True))
            d = self.c.get('/?tab=dashboard'); self.assertEqual(d.status_code, 200); self.assertIn('Calendrier incomplet', d.get_data(as_text=True))
            self.assertEqual(self.c.get('/calendrier.ics').status_code, 500)
        finally:
            cal.DATA_DIR = orig; shutil.rmtree(tmp, ignore_errors=True)


class NonRegression(Base3):
    def test_version(self):
        self.assertEqual(m.VERSION, '9.2-rc47'); self.assertEqual(self.c.get('/health').get_json()['version'], '9.2-rc47')

    def test_aucune_regle_de_facturation_touchee(self):
        """Le calendrier ne modifie pas la position d'un mandat : `contract` donne les mêmes chiffres avant et après l'affichage des pages."""
        pid = self.mandate(name='Mandat inchangé', rate='650', ordered='12', start='2026-01-01', months='12'); self.facture_sept(pid); self.travail(pid, 3)
        c = m.db()
        try: p = c.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone(); avant = m.rules.contract(c, p)
        finally: c.close()
        for u in ('/calendrier', '/?tab=dashboard', '/calendrier.ics'): self.assertEqual(self.c.get(u).status_code, 200)
        c = m.db()
        try: self.assertEqual(m.rules.contract(c, c.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()), avant)
        finally: c.close()


if __name__ == '__main__':
    unittest.main()
