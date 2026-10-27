"""G4: the fourteen checks before a draft invoice may be issued (user directive 2026-10-05, section 9; check 13 and the derogations: decision D8, 2026-10-06;
check 14 (NOT derogable) and the zero over-billing tolerance of check 12: owner decisions of 2026-10-09, rc25).

Every figure is RECOMPUTED here from the database by a path independent of the one that builds the document, then compared with what the document
will print (the header of `invoice_service.live_data`, the single source of what the PDF shows). A failing check never lets an invoice be considered
valid: it is shown with its exact anomaly and the issuance is refused. 'warning' = said, never blocking (a fact the user decides on at issuance).
D8: the checks are strict. Only checks 12 (narrative coherence: quantity vs the work of the period, empty period) and 13 (period ending after the invoice
date) may be overridden, ONE BY ONE, by a written reason entered at issuance for THAT check (author, date and the anomaly kept in the append-only audit,
printed nowhere); 'derogable' says so. rc25: check 14 (net quantity invoiced beyond the quantity worked) is NOT derogable: D8 limits the exceptions to 12
and 13 and no business decision has extended it; no reason, for 14 or for 12, issues an invoice that fails it. An arithmetic failure of check 12 is never derogable.

  1 detail sheets belong to the invoiced period      7 credit notes are taken into account
  2 the sheets belong to the invoice's mandate        8 the contractual balance is right
  3 amount = quantity × rate                          9 no placeholder
  4 VAT                                              10 no test data in the printed fields
  5 historical days come from the validated registry 11 the layout is the one validated against the reference model
  6 the cumulative is computed up to the cutoff     12 invoice, annex and position tell the same story
                                                    13 the invoiced period ends on or before the invoice date
  14 the net quantity invoiced, cumulated, does not exceed the quantity worked, cumulated (never derogable)
"""
import hashlib, json, os, re, unicodedata
from decimal import Decimal, ROUND_HALF_UP

from app import billing_rules as rules, invoice_service, pdf_layout

CENT = Decimal("0.01")
EPS = 1e-5     # the position is printed rounded to 5 decimals
# whole words only, accents and case ignored; the list is the user's own test strings plus the usual stand-ins. Time-entry descriptions are NOT scanned
# (they are the real work log); only what the invoice prints from the invoice, the mandate and the issuer.
FORBIDDEN_WORDS = ("test", "tests", "demo", "fictif", "fictive", "lorem", "ipsum", "xxx", "placeholder", "punaise", "unn")   # "punaise" / "unn": the user's own test strings
PLACEHOLDER_MARKERS = ("a completer", "logo a fournir", "document non emis", "sans valeur comptable", "{{", "}}")   # the generator's own draft markers, and template braces
GOLDEN_FILE = os.path.join(os.path.dirname(__file__), "golden_layout.json")
DEROGABLE = (12, 13)          # D8 (2026-10-06): the only checks a written reason, given for that very check, may override at issuance (14 is NOT one of them)
MIN_REASON = 10               # characters of a derogation reason
OVER_TOLERANCE = 0.0          # rc25 (decision 6): days invoiced beyond the days worked in the period, tolerated by check 12 (zero: any excess is an exception)
UNDER_TOLERANCE = 0.5         # days invoiced below the days worked in the period, tolerated by check 12 (unchanged)


def forbidden_words():
    """INVOICE_CHECK_WORDS unset = the list above. Set (even empty) = exactly that comma-separated list: the throw-away TEST containers set it empty because their
    synthetic mandates are called « Test » / « Fictif »; no deployment file sets it (production and staging keep the default)."""
    v = os.environ.get("INVOICE_CHECK_WORDS")
    return FORBIDDEN_WORDS if v is None else tuple(w.strip().lower() for w in v.split(",") if w.strip())


def _plain(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def printed_fields(h):
    """(label, text) of every free field the invoice prints besides the time entries."""
    out = [(k, h.get(k)) for k in ("description", "note", "other_label", "client", "project", "project_short", "billing_contact", "billing_address", "dates_label", "po",
                                    "project_number", "client_legal_name")]
    out += [(f"ligne manuelle {n} · description", ln.get("description")) for n, ln in enumerate(h.get("lines") or (), 1)]     # rc37 (P1): printed free text
    out += [(f"émetteur · {k}", v) for k, v in (h.get("issuer") or {}).items()]
    if Decimal(str((h.get("amounts") or {}).get("other") or 0)) == 0:      # G4 §6: the label is not printed with a 0 amount, but would be again with one
        out = [("other_label (non imprimé tant que le montant « autres » est nul : le vider)" if k == "other_label" else k, v) for k, v in out]
    return [(k, v) for k, v in out if (v or "") != ""]


def layout_fingerprint():
    """Hash of every geometry constant and font of the PDF layout: any change of the validated layout changes it."""
    consts = {k: repr(v) for k, v in vars(pdf_layout).items() if k.isupper() and isinstance(v, (int, float, str, list, tuple)) and not k.startswith("_")
              and not k.endswith(("_DIR", "_PATH", "_FILE"))}      # geometry and font names only: a folder depends on where the service runs
    return hashlib.sha256(json.dumps(consts, sort_keys=True).encode()).hexdigest()


def _golden():
    try: return json.load(open(GOLDEN_FILE)).get("layout_sha256")
    except (OSError, ValueError): return None


def period_story(qdays, pdays, has_entries, pf, pt):
    """Narrative part of check 12 (D8; over-billing tolerance: rc25 decision 6): the gaps between the quantity invoiced (qdays) and the days worked in the
    period (pdays). Empty = no gap. The only implementation of that rule: run_checks uses it, and so does the draft form's read-only preview (UX lot 2, R-1)."""
    fr = rules.fr_date
    notes = []
    if not has_entries:
        notes.append(f"aucune saisie datée de la période facturée du {fr(pf)} au {fr(pt)} : l'annexe ne montre que du cumul antérieur")
    if qdays - pdays > OVER_TOLERANCE + EPS:
        notes.append(f"sur-facturation : quantité facturée {round(qdays, 4)} j pour {round(pdays, 4)} j réalisé(s) dans la période (tolérance de sur-facturation : {OVER_TOLERANCE:g} j)")
    elif pdays - qdays > UNDER_TOLERANCE + EPS:
        notes.append(f"quantité facturée {round(qdays, 4)} j pour {round(pdays, 4)} j réalisé(s) dans la période (sous-facturation tolérée jusqu'à {UNDER_TOLERANCE:g} j)")
    return notes


def run_checks(conn, iid):
    """The fourteen checks of one DRAFT, as [{'n','title','status': ok|warning|fail,'detail','derogable'}]. Empty for an invoice already issued (frozen, never re-checked)."""
    h, rows = invoice_service.live_data(conn, iid)
    if not h or h["status"] != "draft": return []
    pid, pf, pt = h["project_id"], h["period_from"], h["period_to"]
    p = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    dh = p["day_hours"] or 8
    bill_date = h["invoice_date"] or rules.local_today().isoformat()
    pos = h["position"]
    res = []
    fr = rules.fr_date

    def add(n, title, ok, detail, warn=False, derogable=False):
        res.append({"n": n, "title": title, "status": "ok" if ok else ("warning" if warn else "fail"), "detail": detail, "derogable": bool(derogable and not ok and not warn)})

    # 1 — detail of the period: exactly the entries of the mandate dated within it
    # decision billing-facturee-par-date = A: an entry of the period already billed by an earlier issued invoice (date corrected since) is
    # listed by the cumulative annex but is not work of this period (live_data marks it billed_elsewhere)
    elsewhere = [r for r in rows if r.get("billed_elsewhere") and pf <= r["work_date"] <= pt]
    sql_ids = {r[0] for r in conn.execute("SELECT id FROM entries WHERE project_id=? AND work_date BETWEEN ? AND ?", (pid, pf, pt))} - {r["id"] for r in elsewhere}
    detail_ids = {r["id"] for r in rows if pf <= r["work_date"] <= pt and not r.get("billed_elsewhere")}
    hrs_exact = sum(r["hours"] for r in rows if pf <= r["work_date"] <= pt and not r.get("billed_elsewhere"))   # compared unrounded: 7 h 20 = 7.3333… must not fail check 12 on a rounding gap
    hrs = round(hrs_exact, 4)
    excl = (f" ; {len(elsewhere)} saisie(s) datée(s) de la période, {round(sum(r['hours'] for r in elsewhere), 4)} h, déjà facturée(s) par "
            f"{', '.join(sorted({r['billed_elsewhere'] for r in elsewhere}))} : exclue(s) de cette facture (première facture émise qui l'a facturée)") if elsewhere else ""
    add(1, "Les feuilles détaillées de la période sont celles de la période", sql_ids == detail_ids,
        (f"{len(detail_ids)} saisie(s), {hrs} h dans la période du {fr(pf)} au {fr(pt)}" if detail_ids else f"aucune saisie dans la période du {fr(pf)} au {fr(pt)} (les feuilles jointes sont du cumul antérieur)") + excl
        if sql_ids == detail_ids else f"écart entre la base ({len(sql_ids)} saisies) et le détail ({len(detail_ids)})")
    # 2 — the sheets belong to the mandate
    ids = [r["id"] for r in rows]
    foreign = conn.execute(f"SELECT COUNT(*) FROM entries WHERE id IN ({','.join('?' * len(ids))}) AND project_id<>?", (*ids, pid)).fetchone()[0] if ids else 0
    add(2, "Les saisies affichées sont celles du bon mandat", foreign == 0 and h["project"] == p["name"],
        f"{len(ids)} saisie(s) de « {p['name']} »" if foreign == 0 and h["project"] == p["name"] else f"{foreign} saisie(s) d'un autre mandat ou nom du mandat différent")
    # 3 — amount = quantity × rate, rate = the mandate's
    a = h["amounts"]; ht = (Decimal(str(h["qty"])) * Decimal(str(h["unit_rate"]))).quantize(CENT, ROUND_HALF_UP)
    bad3 = []
    if a["ht"] != ht: bad3.append(f"montant HT imprimé {a['ht']} ≠ {h['qty']} × {h['unit_rate']} = {ht}")
    want = float(p["rate"] or 0) / (dh if h["unit"] == "hour" else 1)       # the draft stores the mandate's day rate, or its hourly equivalent
    if abs(float(h["unit_rate"]) - want) > 1e-9 and float(h["unit_rate"]) > 0:
        bad3.append(f"tarif de la facture {h['unit_rate']} ≠ tarif du mandat {round(want, 6)} par {'heure' if h['unit'] == 'hour' else 'jour'}"
                    " (un brouillon garde son tarif : rétablir celui du mandat, ou supprimer le brouillon et le recréer au nouveau tarif)")
    if not float(h["qty"]) > 0: bad3.append("quantité nulle ou négative")
    if not float(h["unit_rate"]) > 0:                                        # D8 sheet: a rate of 0 fails check 3 itself
        bad3.append("tarif nul : renseigner le tarif journalier du mandat, puis enregistrer de nouveau le brouillon" if not want > 0 else
                    f"tarif nul sur ce brouillon (tarif du mandat renseigné depuis : {round(want, 6)}) : enregistrer de nouveau le brouillon pour le reprendre")
    add(3, "Le montant est quantité × tarif", not bad3, "; ".join(bad3) or f"{h['qty']} × {h['unit_rate']} = {ht} CHF HT")
    # 4 — VAT
    lines = h.get("lines") or []
    taxed = sum((rules.line_amount(l["qty"], l["unit_rate"]) for l in lines if l["vat_mode"] != "hors_tva"), Decimal(0))
    untaxed = sum((rules.line_amount(l["qty"], l["unit_rate"]) for l in lines if l["vat_mode"] == "hors_tva"), Decimal(0))
    base = ht + taxed + (a["other"] if h.get("other_vat_mode") == "soumis" else Decimal(0))      # rc37 (P1): the manual lines « soumis » are in the VAT base
    tva = (base * Decimal(str(h["vat"])) / 100).quantize(CENT, ROUND_HALF_UP)
    bad4 = []
    if float(h["vat"]) != float(p["vat"] or 0): bad4.append(f"TVA de la facture {h['vat']} % ≠ TVA du mandat {p['vat']} %")
    if a["tva"] != tva or a["ttc"] != ht + taxed + untaxed + tva + a["other"]: bad4.append(f"TVA imprimée {a['tva']} / total {a['ttc']} ≠ recalcul {tva} / {ht + taxed + untaxed + tva + a['other']}")
    if float(h["vat"]) > 0 and not ((h.get("issuer") or {}).get("issuer_vat_number") or "").strip(): bad4.append("TVA facturée sans numéro de TVA de l'émetteur")
    add(4, "La TVA est correcte", not bad4, "; ".join(bad4) or f"taux {h['vat']} %, TVA {tva} CHF" + (f" (dont {len(lines)} ligne(s) manuelle(s) : {taxed} CHF soumis, {untaxed} CHF hors TVA)" if lines else ""))
    # 5 — historical days come from the validated registry (never from the hours)
    r5 = conn.execute("""SELECT COALESCE(SUM(qty_days),0) FROM historical_invoices WHERE project_id=? AND status='validated' AND invoice_date IS NOT NULL AND invoice_date<=?""",
                      (pid, bill_date)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM historical_invoices WHERE project_id=? AND status='proposed'", (pid,)).fetchone()[0]
    bad5 = []
    if abs(r5 - pos["historical"]) > EPS: bad5.append(f"jours historiques imprimés {pos['historical']} ≠ registre validé {round(r5, 5)}")
    if pending: bad5.append(f"{pending} facture(s) historique(s) de ce mandat attendent votre validation (page Factures historiques) : la position serait incomplète")
    add(5, "Les jours facturés historiques viennent du registre validé", not bad5,
        "; ".join(bad5) or (f"{pos['historical']} j ({pos['historical_count']} facture(s) historique(s) validée(s))" if pos["historical_count"] else "aucune facture historique pour ce mandat"))
    # 6 — cumulative up to the cutoff
    real = conn.execute("SELECT COALESCE(SUM(hours),0) FROM entries WHERE project_id=? AND work_date<=?", (pid, pt)).fetchone()[0] / dh
    # D9 (decision B, 2026-10-07): earlier invoices are counted by their DATE (invoice date, else Zurich day of issuance), up to this invoice's date
    issued = conn.execute("SELECT id,qty,unit,COALESCE(invoice_date,'') d,issued_at FROM invoices WHERE project_id=? AND status='issued' AND id<>?", (pid, iid)).fetchall()
    dated = {r["id"]: (r["d"] or rules.local_date(r["issued_at"])) for r in issued}
    prev = sum(rules.days(r["qty"], r["unit"], dh) for r in issued if dated[r["id"]] <= bill_date)
    bad6 = []
    if abs(real - pos["realized"]) > EPS: bad6.append(f"jours réalisés imprimés {pos['realized']} ≠ temps jusqu'au {fr(pt)} : {round(real, 5)}")
    if abs(prev - pos["previous"]) > EPS: bad6.append(f"jours Time Billing antérieurs imprimés {pos['previous']} ≠ factures émises datées jusqu'au {fr(bill_date)} : {round(prev, 5)}")
    add(6, "Le cumul est calculé jusqu'à la date de coupure", not bad6,
        "; ".join(bad6) or f"réalisé jusqu'au {fr(pt)} : {round(real, 5)} j ; facturé jusqu'à la date de facture {fr(bill_date)}"
        + (f" ; {pos['later']} j de factures émises datées après cette facture ne sont pas comptés" if pos["later"] else ""))
    # 7 — credit notes
    cr = 0        # on the invoices counted at the cutoff (R-E7-1), the credit note itself dated on or before it and not cancelled by then (D9)
    for r in conn.execute("""SELECT cn.id,cn.invoice_id,cn.qty,cn.issued_at,i.unit FROM credit_notes cn JOIN invoices i ON i.id=cn.invoice_id
                             WHERE i.project_id=? AND cn.status='issued' AND cn.qty IS NOT NULL""", (pid,)):
        x = conn.execute("SELECT issued_at FROM credit_note_cancellations WHERE credit_note_id=?", (r["id"],)).fetchone()
        if r["invoice_id"] in dated and dated[r["invoice_id"]] <= bill_date and rules.local_date(r["issued_at"]) <= bill_date \
                and not (x and rules.local_date(x["issued_at"]) <= bill_date):
            cr += r["qty"] / dh if r["unit"] == "hour" else r["qty"]
    add(7, "Les notes de crédit sont prises en compte", abs(cr - pos["credited"]) <= EPS,
        f"{round(cr, 5)} j annulés par notes de crédit" if abs(cr - pos["credited"]) <= EPS else f"jours annulés imprimés {pos['credited']} ≠ notes de crédit émises non annulées {round(cr, 5)}")
    # 8 — contractual balance, recomputed from its parts
    ordered = float(p["ordered_days"] or 0)
    bal = round(ordered - (r5 + prev + rules.days(h["qty"], h["unit"], dh) - cr), 5)
    add(8, "Le solde contractuel est correct", (not ordered) or abs(bal - pos["balance"]) <= EPS,
        "sans bon de commande (aucun solde imprimé)" if not ordered else (f"{ordered} j commandés − ({round(r5, 5)} + {round(prev, 5)} + {round(rules.days(h['qty'], h['unit'], dh), 5)} − {round(cr, 5)}) = {bal} j"
                                                                          if abs(bal - pos["balance"]) <= EPS else f"solde imprimé {pos['balance']} ≠ recalcul {bal}"))
    # 9 / 10 — placeholders and test data in everything the invoice prints besides the work log
    fields = printed_fields(h)
    hits9 = [f"{k} : « {str(v)[:40]} »" for k, v in fields if any(mk in _plain(v) for mk in PLACEHOLDER_MARKERS)]
    add(9, "Aucun placeholder", not hits9, "; ".join(hits9) or "aucun marqueur [À COMPLÉTER], logo à fournir, « document non émis », {{…}}")
    words = lambda v: set(re.findall(r"[a-z0-9]+", _plain(v)))
    bad_words = set(forbidden_words())
    hits10 = [f"{k} : « {str(v)[:40]} » ({', '.join(sorted(words(v) & bad_words))})" for k, v in fields if words(v) & bad_words]
    add(10, "Aucune donnée de test", not hits10, "; ".join(hits10) or "aucun mot de test dans les champs imprimés (description, note, libellé « autres », mandat, adresses, émetteur)")
    # 11 — layout validated against the reference model (positions measured by the test-suite; fingerprint of every geometry constant)
    gold = _golden(); fp = layout_fingerprint()
    dl = pdf_layout.description_line_count(h.get("description") or h["project"])
    bad11 = [] if gold == fp else ["aucune empreinte de référence enregistrée" if gold is None else "le gabarit PDF a changé depuis sa validation contre le modèle : refaire la comparaison"]
    if dl > pdf_layout.INVOICE_DESCRIPTION_LINES:      # D6 (a): a draft saved before the period moved into the cell would lose its last line
        bad11.append(f"description sur {dl} lignes : {pdf_layout.INVOICE_DESCRIPTION_LINES} au maximum, la dernière ligne de la cellule porte la période (raccourcir la description)")
    if not pdf_layout.note_fits(h.get("note")):          # E-4 (decision B, 2026-10-07): a draft saved before the one-line limit
        bad11.append("note de facture sur plusieurs lignes : la zone de note de la facture tient sur une seule ligne (la raccourcir)")
    problem_lines = pdf_layout.manual_lines_problem(h.get("lines"), h["unit"])     # rc37 (P1): the manual lines print whole on page 1 (count, wrapping, height)
    if problem_lines: bad11.append(problem_lines)
    elif h.get("lines") and pdf_layout.first_page_bottom(h) > pdf_layout.PAGE_ONE_LIMIT:
        bad11.append("la page 1 déborderait sur le pied de page (lignes manuelles, imputations de notes de crédit, note, conditions de paiement trop longues) : retirer une ligne ou raccourcir un texte")
    if not pdf_layout.other_label_fits(h, a["other"]):   # a draft saved before the label was measured against its totals row
        bad11.append("libellé « autres » trop long pour la ligne des totaux : il déborderait sur le montant (raccourcir le libellé)")
    add(11, "Le gabarit est celui validé contre le modèle de référence", not bad11,
        "; ".join(bad11) or "empreinte du gabarit conforme à celle validée contre la facture de référence ; description et période tiennent dans la cellule")
    # 12 — the same story: arithmetic invariants (blocking, never derogable) + narrative gaps (blocking, derogable with a written reason: D8)
    bad12 = []
    if abs(sum(r["hours"] for r in rows) / dh - pos["realized"]) > EPS: bad12.append("somme des heures de l'annexe ≠ jours réalisés cumulés imprimés")
    if abs(hrs_exact - h["period_hours"]) > EPS: bad12.append("heures de la période ≠ total de la section période")
    if abs(rules.days(h["qty"], h["unit"], dh) - pos["current"]) > EPS: bad12.append("quantité de la page 1 ≠ jours « cette facture » de la position")
    if abs(pos["invoiced"] - (pos["historical"] + pos["previous"] + pos["current"])) > EPS: bad12.append("jours facturés totaux ≠ historiques + antérieurs + cette facture")
    if bad12: add(12, "La facture, l'annexe et la position racontent la même histoire", False, "; ".join(bad12))
    else:
        pdays = h["period_hours"] / dh      # the printed total (6 decimals): a sum of clock entries carries float noise (28 h = 28.000000000000004), never a 0.5 j gap by itself
        qdays = rules.days(h["qty"], h["unit"], dh)
        notes = period_story(qdays, pdays, bool(detail_ids), pf, pt)
        add(12, "La facture, l'annexe et la position racontent la même histoire", not notes, "; ".join(notes) or "mêmes période, quantité, tarif et totaux sur les trois documents",
            derogable=True)
    # 13 — the invoiced period ends on or before the invoice date (D8, 2026-10-06): an invoice does not bill days still to come
    add(13, "La période facturée se termine au plus tard à la date de la facture", pt <= bill_date,
        f"fin de période {fr(pt)} ≤ date de facture {fr(bill_date)}" if pt <= bill_date else
        f"fin de période {fr(pt)} postérieure à la date de facture {fr(bill_date)}" + ("" if h["invoice_date"] else " (date d'émission = aujourd'hui)"), derogable=True)
    # 14 — rc25 (decision 3): the net quantity invoiced, cumulated up to the end of the period, never exceeds the quantity worked up to it. Recomputed from the
    # tables, not from the printed position: Time Billing invoices count by PERIOD (an invoice of a later period does not weigh on a catch-up of an earlier one, like
    # the reliquat), minus the issued, non-cancelled credit notes on them; the VALIDATED historical invoices count all, whatever their date (they carry no period:
    # an invoice issued outside the application for this very work, dated after the period, is the double billing this check exists for).
    hist14 = conn.execute("SELECT COALESCE(SUM(qty_days),0) FROM historical_invoices WHERE project_id=? AND status='validated' AND qty_days IS NOT NULL", (pid,)).fetchone()[0]
    inv14 = conn.execute("SELECT id,qty,unit FROM invoices WHERE project_id=? AND status='issued' AND id<>? AND period_to<=?", (pid, iid, pt)).fetchall()
    ids14 = {r["id"] for r in inv14}
    prev14 = sum(rules.days(r["qty"], r["unit"], dh) for r in inv14)
    cr14 = sum(r["qty"] / dh if r["unit"] == "hour" else r["qty"] for r in conn.execute(
        """SELECT cn.qty,i.unit,i.id inv FROM credit_notes cn JOIN invoices i ON i.id=cn.invoice_id WHERE i.project_id=? AND cn.status='issued' AND cn.qty IS NOT NULL
           AND cn.id NOT IN (SELECT credit_note_id FROM credit_note_cancellations)""", (pid,)) if r["inv"] in ids14)
    cur14 = rules.days(h["qty"], h["unit"], dh)
    net14 = hist14 + prev14 + cur14 - cr14
    real14 = conn.execute("SELECT COALESCE(SUM(hours),0) FROM entries WHERE project_id=? AND work_date<=?", (pid, pt)).fetchone()[0] / dh
    ok14 = net14 <= real14 + EPS
    add(14, "La quantité nette facturée cumulée ne dépasse pas la quantité réalisée cumulée", ok14,
        f"facturé net {round(net14, 5)} j (historique validé {round(hist14, 5)} + Time Billing jusqu'au {fr(pt)} {round(prev14, 5)} + cette facture {round(cur14, 5)} − notes de crédit {round(cr14, 5)}) "
        + (f"≤ réalisé jusqu'au {fr(pt)} : {round(real14, 5)} j" if ok14 else f"> réalisé jusqu'au {fr(pt)} : {round(real14, 5)} j (excédent {round(net14 - real14, 5)} j facturés au-delà du travail enregistré ; aucune dérogation possible : enregistrer le travail manquant, corriger la quantité ou créditer)"))
    return res


def failures(checks):
    return [c for c in checks if c["status"] == "fail"]


def blocking(checks):
    """Failures no reason can override."""
    return [c for c in failures(checks) if not c["derogable"]]


def summary_line(checks):
    return " | ".join(f"{c['n']}. {c['title']} — {c['detail']}" + (" (dérogation motivée possible)" if c["derogable"] else "") for c in failures(checks))


def derogations(checks, form):
    """D8: {n: reason} for every failing derogable check, read from the issue form (field derogation_<n>). Raises ValueError naming what is missing:
    a non-derogable failure, or a derogable one without a written reason of MIN_REASON characters at least."""
    hard = blocking(checks)
    if hard: raise ValueError("contrôles avant émission en échec — " + summary_line(hard))
    from app.app import change_reason          # late: app.app imports this module. The reason obeys the rule of every reason kept in the audit
    out, missing = {}, []
    for c in failures(checks):
        try: why = change_reason(" ".join((form.get(f"derogation_{c['n']}") or "").split()))
        except ValueError as e: raise ValueError(f"dérogation au contrôle {c['n']} : {e}")
        if len(why) < MIN_REASON: missing.append(c)
        else: out[c["n"]] = why
    if missing:
        raise ValueError("contrôles avant émission en échec — " + summary_line(missing)
                         + f" : émission possible seulement avec un motif de dérogation écrit ({MIN_REASON} caractères au moins) pour chacun")
    return out
