"""Credit-note settlement: refund or offset, chosen per document and immutable once issued.

A credit note is a separate document linked to an issued invoice (never modified). It may credit the
service line (days, or an amount), the « AUTRES » line and, since rc38, each manual line of the invoice
(an HT amount per line, in whole or in part: credit_lines.py); the VAT treatment of « AUTRES » and of each
manual line is the one of the original invoice (copied onto the note), so a credit always mirrors how the invoice was taxed.

Once issued, its amount in the client's favour (TTC) is settled through an append-only ledger,
credit_operations:
  refund           money actually paid back (date, bank reference); partial payments allowed
  offset           imputation on a later invoice of the SAME LEGAL CLIENT (same legal identifier)
  *_reversal       cancels one earlier operation; the original row stays, nothing is updated or deleted
Offset on a DRAFT invoice is a reservation printed on it, applied (and frozen) when it is issued.

The mode is immutable after issuance. A wrong note is corrected by a cancellation document
(ANN-<reference>, frozen PDF; only while nothing was refunded or imputed) and a NEW credit note that
references the cancelled one (replaces_credit_id): both stay visible and traceable.

Refund deadline: optional per note (default from settings, empty = none); due date fixed at issuance.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from app import billing_rules as rules
from app.billing_rules import fr_chf, fr_g, fr_date

TREATMENTS = {"remboursement": "Remboursement", "compensation": "Compensation sur facture ultérieure"}
KIND_LABELS = {"refund": "Remboursement exécuté", "refund_reversal": "Annulation de remboursement",
               "offset": "Imputation sur facture", "offset_reversal": "Annulation d'imputation"}
ZERO = Decimal("0.00")


def dec(v):
    return Decimal(str(v or 0)).quantize(rules.CENT)


def _get(row, k, default=None):
    return row[k] if k in row.keys() and row[k] is not None else default


def credit_amounts(cn):
    """HT (service line) / AUTRES / TVA / TTC of one credit-note row; rc38: also the credited manual lines (lines_taxed / lines_untaxed / lines_ht) and the printed
    `subtotal` (service + lines). `ht` stays the SERVICE line only, like for an invoice.

    tva_amount, when set, is the VAT balance carried by the note that exhausts the invoice: per-note
    rounding would otherwise let the credited TTC exceed the invoice TTC by a cent."""
    # `amount` is the authoritative service HT (qty × rate rounded, or the exact balance for a closing note)
    other = _get(cn, "other_amount", 0); mode = _get(cn, "other_vat_mode")
    lines = [{"qty": 1, "unit_rate": dec(_get(cn, k, 0)), "vat_mode": m} for k, m in (("lines_taxed", "soumis"), ("lines_untaxed", "hors_tva")) if dec(_get(cn, k, 0)) != ZERO]
    a = rules.amounts(1, cn["amount"] or 0, cn["vat"], other, mode, lines)
    if _get(cn, "tva_amount") is not None:
        a["tva"] = dec(cn["tva_amount"]); a["ttc"] = a["ht"] + a["lines_ht"] + a["tva"] + a["other"]
    return a


invoice_amounts = rules.invoice_amounts


def inv_amounts(c, inv):
    """Amounts of the invoice row `inv` WITH its manual lines (rc38): what a credit note is measured against. The lines of an issued invoice are immutable (triggers)."""
    return rules.invoice_amounts_full(c, inv)


def is_cancelled(c, cid):
    return c.execute("SELECT 1 FROM credit_note_cancellations WHERE credit_note_id=?", (cid,)).fetchone() is not None


# --- ledger reads -------------------------------------------------------------------------------

def operations(c, cid):
    ops = [dict(r) for r in c.execute("SELECT * FROM credit_operations WHERE credit_note_id=? ORDER BY id", (cid,))]
    for o in ops: o["target_now"] = _now_issued(c, o)
    return ops


def _active(ops):
    reversed_ids = {o["reverses_id"] for o in ops if o["reverses_id"]}
    return [o for o in ops if o["kind"] in ("refund", "offset") and o["id"] not in reversed_ids]


def active_offsets_on(c, iid, exclude_op=None):
    """Active (non-reversed) offsets imputed on invoice iid, with their credit-note reference."""
    rows = c.execute("""SELECT o.*,cn.reference FROM credit_operations o JOIN credit_notes cn ON cn.id=o.credit_note_id
                        WHERE o.kind='offset' AND o.target_invoice_id=?
                          AND NOT EXISTS(SELECT 1 FROM credit_operations r WHERE r.reverses_id=o.id) ORDER BY o.id""", (iid,)).fetchall()
    return [dict(r) for r in rows if r["id"] != exclude_op]


def offsets_total_on(c, iid):
    return sum((dec(o["amount"]) for o in active_offsets_on(c, iid)), ZERO)


def credited_on(c, iid, exclude=None, statuses=("draft", "issued")):
    """Service HT, AUTRES, manual lines (taxed / untaxed / total), TVA, TTC and quantity credited on invoice iid (cancelled notes excluded)."""
    ht = other = tva = ttc = lt = lu = ZERO; qty = 0.0
    q = f"""SELECT * FROM credit_notes WHERE invoice_id=? AND status IN ({','.join('?' * len(statuses))})
            AND id NOT IN (SELECT credit_note_id FROM credit_note_cancellations)"""
    for r in c.execute(q, (iid, *statuses)):
        if r["id"] == exclude: continue
        a = credit_amounts(r); ht += a["ht"]; other += a["other"]; tva += a["tva"]; ttc += a["ttc"]; qty += r["qty"] or 0
        lt += a["lines_taxed"]; lu += a["lines_untaxed"]
    return {"ht": ht, "other": other, "tva": tva, "ttc": ttc, "qty": round(qty, 6), "lines_taxed": lt, "lines_untaxed": lu, "lines": lt + lu}


def credited_by_line(c, iid, exclude=None, statuses=("draft", "issued")):
    """{invoice line id: HT already credited} on invoice iid by its notes (cancelled notes excluded, like credited_on)."""
    q = f"""SELECT l.invoice_line_id,l.amount FROM credit_note_lines l JOIN credit_notes n ON n.id=l.credit_note_id WHERE n.invoice_id=? AND n.status IN ({','.join('?' * len(statuses))})
            AND n.id NOT IN (SELECT credit_note_id FROM credit_note_cancellations) AND n.id IS NOT ?"""
    out = {}
    for r in c.execute(q, (iid, *statuses, exclude)): out[r["invoice_line_id"]] = out.get(r["invoice_line_id"], ZERO) + dec(r["amount"])
    return out


def note_lines(c, cid):
    """The credited manual lines of one credit note, in the order of the invoice: [{invoice_line_id, position, description, amount (Decimal), vat_mode}]."""
    return [{"invoice_line_id": r["invoice_line_id"], "position": r["position"], "description": r["description"], "amount": dec(r["amount"]), "vat_mode": r["vat_mode"]}
            for r in c.execute("SELECT * FROM credit_note_lines WHERE credit_note_id=? ORDER BY position,id", (cid,))]


def creditable(c, inv, exclude=None):
    """What can still be credited on an issued invoice, per line and in total."""
    a = inv_amounts(c, inv); done = credited_on(c, inv["id"], exclude); off = offsets_total_on(c, inv["id"])
    by_line = credited_by_line(c, inv["id"], exclude); lines = []
    for ln in rules.invoice_lines(c, inv["id"]):          # rc38: what is left to credit on each manual line (HT)
        amt = rules.line_amount(ln["qty"], ln["unit_rate"]); got = by_line.get(ln["id"], ZERO)
        lines.append({"id": ln["id"], "position": ln["position"], "description": ln["description"], "vat_mode": ln["vat_mode"], "amount": amt, "credited": got, "remaining": amt - got})
    return {"invoiced_ht": a["ht"] + a["other"] + a["lines_ht"], "invoiced_service": a["ht"], "invoiced_other": a["other"], "invoiced_lines": a["lines_ht"], "invoiced_ttc": a["ttc"],
            "invoiced_qty": float(inv["qty"]), "other_vat_mode": rules.other_vat_mode(_get(inv, "other_vat_mode")),
            "credited_ht": done["ht"] + done["other"] + done["lines"], "credited_service": done["ht"], "credited_other": done["other"], "credited_lines": done["lines"],
            "credited_ttc": done["ttc"], "credited_qty": done["qty"], "offsets_ttc": off,
            "remaining_ht": a["ht"] + a["other"] + a["lines_ht"] - done["ht"] - done["other"] - done["lines"], "remaining_service": a["ht"] - done["ht"],
            "remaining_other": a["other"] - done["other"], "remaining_lines": a["lines_ht"] - done["lines"], "remaining_lines_taxed": a["lines_taxed"] - done["lines_taxed"],
            "remaining_lines_untaxed": a["lines_untaxed"] - done["lines_untaxed"], "remaining_ttc": a["ttc"] - done["ttc"] - off,
            "remaining_qty": round(float(inv["qty"]) - done["qty"], 6), "lines": lines}


def fully_credited(c, iid, exclude_credit=None):
    """rc25 (decision 4): True when the issued invoice is entirely credited by ISSUED, non-cancelled credit notes: service line, AUTRES line AND
    quantity (days) and, rc38, every manual line. A draft credit note, a cancelled one or an amount-only note that leaves days uncredited never counts. exclude_credit: ignore
    that note (what the invoice would be if it were cancelled)."""
    inv = c.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if not inv or inv["status"] != "issued": return False
    a = inv_amounts(c, inv); done = credited_on(c, iid, exclude_credit, statuses=("issued",))
    return (a["ht"] + a["other"] + a["lines_ht"] > ZERO and a["ht"] - done["ht"] <= ZERO and a["other"] - done["other"] <= ZERO and a["lines_ht"] - done["lines"] <= ZERO
            and float(inv["qty"]) - done["qty"] <= 1e-6)


def period_clash(c, project_id, period_from, period_to, exclude_id=None):
    """rc25 (decision 4): the issued invoice of the mandate whose period overlaps [period_from, period_to] and still stands, or None.
    An invoice that is entirely credited (fully_credited) no longer stands: its period may be invoiced again; it stays in the history."""
    for r in c.execute("""SELECT id,number,period_from,period_to FROM invoices WHERE project_id=? AND status='issued' AND id IS NOT ?
                          AND period_from<=? AND period_to>=? ORDER BY period_from,id""", (project_id, exclude_id, period_to, period_from)):
        if not fully_credited(c, r["id"]): return r
    return None


def total_credit_blockers(c, inv):
    """Why the invoice cannot be credited in full because it received offsets (rc5, decision 6); '' = no obstacle.

    - offset frozen on the invoice at its issuance (printed as NET À PAYER): definitively consumed, never taken
      back; a total credit is refused for good (only partial credits within the net amount remain possible);
    - offset recorded after its issuance (not printed): still reversible, so it must first be cancelled by a
      traceable reversal row on the credit note that carries it.
    Offsets on a draft are cancelled the same way, before the draft is issued. The issued invoice is never changed."""
    if inv["status"] != "issued": return ""
    offs = active_offsets_on(c, inv["id"])
    if not offs: return ""
    frozen = frozen_offset_ids(c, inv["id"])
    final = [o for o in offs if o["id"] in frozen]; open_ = [o for o in offs if o["id"] not in frozen]
    if final:
        det = ", ".join(f"{o['reference']} {fr_chf(dec(o['amount']))} (imputation n° {o['id']})" for o in final)
        return (f"crédit total refusé : la facture {inv['number']} a reçu une compensation définitivement consommée à son émission ({det}). "
                "Une compensation consommée n'est jamais reprise et la facture émise n'est pas modifiée ; seul un crédit partiel "
                "dans la limite du net à payer reste possible")
    det = ", ".join(f"{o['reference']} {fr_chf(dec(o['amount']))} (imputation n° {o['id']})" for o in open_)
    return (f"crédit total impossible tant que des imputations sont actives sur la facture {inv['number']} ({det}) : "
            "les annuler d'abord depuis le suivi de la note de crédit concernée (écriture d'annulation traçable)")


def check_creditable(c, inv, qty, a, exclude=None, line_amounts=None):
    """Refuse any credit note whose cumulative amount would exceed what the invoice can still absorb.
    a: amounts of the new note (ht = service line, other = AUTRES line, lines_taxed / lines_untaxed = manual lines, ttc).
    line_amounts: {invoice line id: HT credited by the note} (rc38); required as soon as the note credits manual lines."""
    k = creditable(c, inv, exclude)
    line_amounts = {int(i): dec(v) for i, v in (line_amounts or {}).items()}
    if sum(line_amounts.values(), ZERO) != a["lines_ht"]:
        raise ValueError("le détail des lignes manuelles créditées ne correspond pas au montant des lignes de la note")
    # a note that exhausts every line is a total credit: explicit rule when the invoice received offsets
    if a["ht"] >= k["remaining_service"] and a["other"] >= k["remaining_other"] and a["lines_ht"] >= k["remaining_lines"] and k["offsets_ttc"] > 0:
        why = total_credit_blockers(c, inv)
        if why: raise ValueError(why)
    by_id = {ln["id"]: ln for ln in k["lines"]}
    for lid, amt in line_amounts.items():
        ln = by_id.get(lid)
        if ln is None: raise ValueError("une ligne créditée n'appartient pas à cette facture")
        if amt <= ZERO: raise ValueError(f"le montant crédité de la ligne {ln['position']} doit être positif")
        if amt > ln["remaining"]:
            raise ValueError(f"le cumul crédité sur la ligne {ln['position']} « {ln['description']} » ({fr_chf(ln['credited'] + amt)} HT) dépasserait son montant "
                             f"({fr_chf(ln['amount'])} HT ; déjà crédité {fr_chf(ln['credited'])} HT, solde créditable {fr_chf(ln['remaining'])} HT)")
    if a["ht"] > k["remaining_service"]:
        raise ValueError(f"le cumul crédité sur la prestation ({fr_chf(k['credited_service'] + a['ht'])} HT) dépasserait le montant créditable "
                         f"({fr_chf(k['invoiced_service'])} HT ; déjà crédité {fr_chf(k['credited_service'])} HT, solde créditable {fr_chf(k['remaining_service'])} HT)")
    if a["other"] > k["remaining_other"]:
        raise ValueError(f"le cumul crédité sur « AUTRES » ({fr_chf(k['credited_other'] + a['other'])}) dépasserait le montant facturé "
                         f"({fr_chf(k['invoiced_other'])} ; solde créditable {fr_chf(k['remaining_other'])})")
    if qty and qty > k["remaining_qty"] + 1e-9:
        raise ValueError(f"le cumul des quantités créditées ({fr_g(k['credited_qty'] + qty)}) dépasserait la quantité facturée ({fr_g(k['invoiced_qty'])})")
    if a["ttc"] > k["remaining_ttc"]:
        raise ValueError(f"le cumul crédité TTC ({fr_chf(k['credited_ttc'] + a['ttc'])}) augmenté des imputations reçues ({fr_chf(k['offsets_ttc'])}) "
                         f"dépasserait le total de la facture ({fr_chf(k['invoiced_ttc'])} TTC)")
    return k


def closing_vat(c, inv, a, vat_rate, exclude=None):
    """VAT for a note that exhausts both lines of the invoice: the invoice's VAT balance (exact cumulative
    total); else None (normal rounding of the note's own VAT base)."""
    if float(vat_rate) != float(inv["vat"]): return None
    inv_a = inv_amounts(c, inv); done = credited_on(c, inv["id"], exclude)
    if a["ht"] != inv_a["ht"] - done["ht"] or a["other"] != inv_a["other"] - done["other"]: return None
    if a["lines_taxed"] != inv_a["lines_taxed"] - done["lines_taxed"] or a["lines_untaxed"] != inv_a["lines_untaxed"] - done["lines_untaxed"]: return None
    balance = inv_a["tva"] - done["tva"]
    return None if balance == a["tva"] else balance


# --- per-credit-note position -------------------------------------------------------------------

def position(c, cn):
    """Credited amount, executed / imputed amounts, balance, deadline and status of one credit note."""
    a = credit_amounts(cn); ttc = a["ttc"]; ops = operations(c, cn["id"]); act = _active(ops)
    out = {"ht": a["ht"], "other": a["other"], "lines_ht": a["lines_ht"], "tva": a["tva"], "ttc": ttc, "treatment": cn["treatment"],
           "treatment_label": TREATMENTS.get(cn["treatment"], "mode non défini"), "refunded": ZERO, "applied": ZERO, "reserved": ZERO,
           "used": ZERO, "balance": ttc, "operations": ops, "due_on": _get(cn, "refund_due_on"), "overdue": False, "cancelled": None}
    if cn["status"] != "issued":
        out.update(status="brouillon"); return out
    canc = c.execute("SELECT reference,issued_at,reason FROM credit_note_cancellations WHERE credit_note_id=?", (cn["id"],)).fetchone()
    if canc:
        out.update(status=f"annulée ({canc['reference']})", balance=ZERO, cancelled=dict(canc)); return out
    if cn["treatment"] == "remboursement":
        out["refunded"] = sum((dec(o["amount"]) for o in act if o["kind"] == "refund"), ZERO)
        out["used"] = out["refunded"]; out["balance"] = ttc - out["refunded"]
        out["status"] = "à rembourser" if out["refunded"] == 0 else ("remboursée" if out["balance"] == 0 else "partiellement remboursée")
        if out["due_on"] and out["balance"] > 0 and out["due_on"] < rules.local_today().isoformat():
            out["overdue"] = True; out["status"] += f" — échéance dépassée ({fr_date(out['due_on'])})"
    elif cn["treatment"] == "compensation":
        for o in act:
            if o["kind"] != "offset": continue
            st = c.execute("SELECT status FROM invoices WHERE id=?", (o["target_invoice_id"],)).fetchone()
            out["applied" if st and st["status"] == "issued" else "reserved"] += dec(o["amount"])
        out["used"] = out["applied"] + out["reserved"]; out["balance"] = ttc - out["used"]
        if out["used"] == 0: out["status"] = "disponible"
        elif out["balance"] > 0: out["status"] = "partiellement compensée"
        elif out["reserved"] > 0: out["status"] = "entièrement affectée (imputation en attente d'émission)"
        else: out["status"] = "compensée"
    else:
        out["status"] = "mode non défini"
    return out


def history(c, cn):
    """Chronological history: issuance, ledger rows, offsets applied at target issuance, cancellation, replacement."""
    h = []
    if cn["issued_at"]:
        d = f"{cn['reference']} — mode : {TREATMENTS.get(cn['treatment'], 'non défini')}"
        if _get(cn, "refund_due_on"): d += f" — échéance de remboursement {fr_date(cn['refund_due_on'])}"
        if _get(cn, "replaces_credit_id"):
            r = c.execute("SELECT reference FROM credit_notes WHERE id=?", (cn["replaces_credit_id"],)).fetchone()
            d += f" — remplace {r['reference'] if r else '?'}"
        h.append({"at": cn["issued_at"], "event": "Émission", "amount": None, "detail": d})
    for o in operations(c, cn["id"]):
        d = []
        if o["target_label"]: d.append(rules.fr_periods_in(o["target_label"]) + _now_issued(c, o))
        if o["executed_on"]: d.append(f"exécuté le {fr_date(o['executed_on'])}")
        if o["external_ref"]: d.append(f"réf. {o['external_ref']}")
        if o["reverses_id"]: d.append(f"annule l'opération n° {o['reverses_id']}")
        if o["note"]: d.append(o["note"])
        sign = -1 if o["kind"].endswith("_reversal") else 1
        h.append({"at": o["created_at"], "event": f"n° {o['id']} — {KIND_LABELS[o['kind']]}", "amount": dec(o["amount"]) * sign, "detail": " · ".join(d)})
        if o["kind"] == "offset":
            t = c.execute("SELECT number,status,issued_at FROM invoices WHERE id=?", (o["target_invoice_id"],)).fetchone()
            # imputed on a draft, then frozen with the invoice when it was issued
            if t and t["status"] == "issued" and o["id"] in frozen_offset_ids(c, o["target_invoice_id"]):
                h.append({"at": t["issued_at"], "event": f"Imputation n° {o['id']} appliquée", "amount": None, "detail": f"émission de la facture {t['number']}"})
    canc = c.execute("SELECT * FROM credit_note_cancellations WHERE credit_note_id=?", (cn["id"],)).fetchone()
    if canc: h.append({"at": canc["issued_at"], "event": f"Annulation {canc['reference']}", "amount": None, "detail": canc["reason"]})
    rep = c.execute("SELECT reference,issued_at,status FROM credit_notes WHERE replaces_credit_id=?", (cn["id"],)).fetchone()
    if rep: h.append({"at": rep["issued_at"] or "", "event": "Remplacement", "amount": None,
                      "detail": f"remplacée par {rep['reference'] or 'un brouillon de note de crédit'}"})
    return sorted(h, key=lambda e: e["at"])


# --- ledger writes (caller owns a BEGIN IMMEDIATE transaction) ----------------------------------

def _issued_cn(c, cid):
    cn = c.execute("SELECT * FROM credit_notes WHERE id=?", (cid,)).fetchone()
    if not cn: raise ValueError("note de crédit introuvable")
    if cn["status"] != "issued": raise ValueError("seule une note de crédit émise peut être remboursée ou compensée")
    if is_cancelled(c, cid): raise ValueError("note de crédit annulée : aucune opération possible")
    return cn


def _amount(raw):
    try: v = Decimal(str(raw or "").replace(",", ".").strip()).quantize(rules.CENT)
    except Exception: raise ValueError("montant invalide")
    if v <= 0: raise ValueError("le montant doit être positif")
    return v


def _insert(c, cid, kind, amount, **kw):
    # created_at in the same local ISO format as issued_at, so the two can be ordered
    cols = {"credit_note_id": cid, "kind": kind, "amount": float(amount), "created_at": rules.utc_now_iso(), **kw}
    cur = c.execute(f"INSERT INTO credit_operations({','.join(cols)}) VALUES({','.join('?' * len(cols))})", tuple(cols.values()))
    return cur.lastrowid


def record_refund(c, cid, amount, executed_on, external_ref="", note=""):
    cn = _issued_cn(c, cid)
    if cn["treatment"] != "remboursement": raise ValueError("cette note de crédit est traitée par compensation, pas par remboursement")
    amount = _amount(amount)
    try: d = date.fromisoformat((executed_on or "").strip())
    except ValueError: raise ValueError("date d'exécution du remboursement invalide (AAAA-MM-JJ)")
    if d > rules.local_today(): raise ValueError("un remboursement ne peut être enregistré qu'une fois exécuté (date future refusée)")
    if d.isoformat() < rules.local_date(cn["issued_at"]): raise ValueError("la date d'exécution ne peut pas précéder l'émission de la note de crédit")
    pos = position(c, cn)
    if amount > pos["balance"]:
        raise ValueError(f"le remboursement ({fr_chf(amount)}) dépasse le solde restant à rembourser ({fr_chf(pos['balance'])} sur {fr_chf(pos['ttc'])} crédités)")
    oid = _insert(c, cid, "refund", amount, executed_on=d.isoformat(), external_ref=(external_ref or "").strip(), note=(note or "").strip())
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("credit_refund_recorded", f"{cn['reference']};op={oid};amount={amount};executed_on={d}"))
    return oid


def legal_identity(c, iid):
    """(legal name, legal id) of the client of invoice iid: frozen at issuance for issued invoices, the
    mandate's current values for drafts."""
    from app import invoice_service
    i = c.execute("SELECT i.status,p.client_legal_name,p.client_legal_id FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id=?", (iid,)).fetchone()
    if not i: return "", ""
    if i["status"] == "issued":
        h = invoice_service.frozen_header(c, iid) or {}
        return h.get("client_legal_name") or "", h.get("client_legal_id") or ""
    return i["client_legal_name"] or "", i["client_legal_id"] or ""


def target_candidates(c, cn):
    """Invoices that may receive an offset: same legal client (same normalised legal identifier), not the
    original invoice, draft or issued after the credit note. Returns (candidates, refusal reason)."""
    _, oid = legal_identity(c, cn["invoice_id"]); key = rules.legal_key(oid)
    if not key:
        return [], "identifiant juridique du client absent de la facture d'origine : compensation impossible (rembourser, ou annuler et remplacer la note)"
    out = []
    for i in c.execute("SELECT i.*,p.name project,p.client FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id<>? ORDER BY i.id DESC", (cn["invoice_id"],)):
        if rules.legal_key(legal_identity(c, i["id"])[1]) != key: continue
        if i["status"] == "issued" and (i["issued_at"] or "") < (cn["issued_at"] or ""): continue
        a = inv_amounts(c, i); done = credited_on(c, i["id"], statuses=("issued",))["ttc"]; off = offsets_total_on(c, i["id"])
        out.append(dict(i, ttc=a["ttc"], offsets=off, room=a["ttc"] - done - off))
    return out, ("" if out else "aucune facture ultérieure du même client juridique : créer d'abord un brouillon de facture")


def _now_issued(c, o):
    """A draft target issued since the imputation: say which invoice it became."""
    if not o["target_invoice_id"] or not (o["target_label"] or "").startswith("brouillon"): return ""
    t = c.execute("SELECT number,status FROM invoices WHERE id=?", (o["target_invoice_id"],)).fetchone()
    return f" → émis : facture {t['number']}" if t and t["status"] == "issued" else ""


def _target_label(i):
    return f"facture {i['number']}" if i["status"] == "issued" else f"brouillon de facture n° {i['id']} ({i['project']}, {i['period_from']} → {i['period_to']})"


def record_offset(c, cid, target_id, amount, note=""):
    cn = _issued_cn(c, cid)
    if cn["treatment"] != "compensation": raise ValueError("cette note de crédit est traitée par remboursement, pas par compensation")
    amount = _amount(amount)
    cands, why = target_candidates(c, cn)
    t = next((i for i in cands if i["id"] == int(target_id or 0)), None)
    if not t: raise ValueError("facture cible non admissible : " + (why or "même client juridique, facture ultérieure, autre que la facture d'origine"))
    pos = position(c, cn)
    if amount > pos["balance"]:
        raise ValueError(f"l'imputation ({fr_chf(amount)}) dépasse le solde disponible de la note de crédit ({fr_chf(pos['balance'])} sur {fr_chf(pos['ttc'])})")
    if amount > t["room"]:
        raise ValueError(f"l'imputation ({fr_chf(amount)}) dépasse le montant restant dû sur la facture cible ({fr_chf(t['room'])})")
    oid = _insert(c, cid, "offset", amount, target_invoice_id=t["id"], target_label=_target_label(t), note=(note or "").strip())
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("credit_offset_recorded", f"{cn['reference']};op={oid};amount={amount};target_invoice={t['id']};target_status={t['status']}"))
    return oid


def frozen_offset_ids(c, iid):
    from app import invoice_service
    h = invoice_service.frozen_header(c, iid) or {}
    return {o["op_id"] for o in h.get("offsets", [])}


def reverse(c, op_id, note, executed_on=None):
    o = c.execute("SELECT * FROM credit_operations WHERE id=?", (op_id,)).fetchone()
    if not o: raise ValueError("opération introuvable")
    if o["kind"] not in ("refund", "offset"): raise ValueError("une annulation ne peut pas être annulée ; enregistrer une nouvelle opération")
    if c.execute("SELECT 1 FROM credit_operations WHERE reverses_id=?", (op_id,)).fetchone(): raise ValueError("opération déjà annulée")
    note = (note or "").strip()
    if not note: raise ValueError("motif d'annulation obligatoire")
    if o["kind"] == "offset":
        t = c.execute("SELECT status,number FROM invoices WHERE id=?", (o["target_invoice_id"],)).fetchone()
        if t and t["status"] == "issued" and op_id in frozen_offset_ids(c, o["target_invoice_id"]):
            raise ValueError(f"imputation figée sur la facture émise {t['number']} : elle ne peut plus être annulée (corriger par une nouvelle note de crédit)")
    oid = _insert(c, o["credit_note_id"], o["kind"] + "_reversal", o["amount"], reverses_id=op_id, target_invoice_id=o["target_invoice_id"],
                  target_label=o["target_label"], executed_on=executed_on, note=note)
    ref = c.execute("SELECT reference FROM credit_notes WHERE id=?", (o["credit_note_id"],)).fetchone()[0]
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("credit_operation_reversed", f"{ref};op={oid};reverses={op_id};amount={o['amount']};note={note}"))
    return oid


def release_draft_offsets(c, iid, why):
    """Draft invoice deleted: every active reservation on it is released by a reversal row."""
    n = 0
    for o in active_offsets_on(c, iid):
        reverse(c, o["id"], why); n += 1
    return n


# --- refund deadline ----------------------------------------------------------------------------

def parse_delay(raw, label="délai de remboursement"):
    """'' → None (no deadline); else a whole number of days between 0 and 365."""
    raw = (raw or "").strip()
    if not raw: return None
    try: n = int(raw)
    except ValueError: raise ValueError(f"{label} invalide (nombre entier de jours, ou vide)")
    if not 0 <= n <= 365: raise ValueError(f"{label} hors limites (0 à 365 jours)")
    return n


def due_date(issued_on, delay):
    return None if delay is None else (date.fromisoformat(rules.local_date(issued_on)) + timedelta(days=int(delay))).isoformat()  # RC8: from the Zurich issuance day


# --- traceable correction: cancellation of an issued note ---------------------------------------

def cancellation_blockers(c, cn):
    if cn["status"] != "issued": return "seule une note de crédit émise peut être annulée (un brouillon se supprime)"
    if is_cancelled(c, cn["id"]): return "note de crédit déjà annulée"
    pos = position(c, cn)
    if pos["used"] > 0:
        return (f"{fr_chf(pos['used'])} déjà remboursés ou imputés : annuler d'abord ces opérations (écritures d'annulation) ; "
                "une imputation figée sur une facture émise ne peut plus être annulée")
    # rc25 (decision 4): cancelling the note that made the invoice entirely credited would bring it back next to the invoice that re-billed its period
    if fully_credited(c, cn["invoice_id"]) and not fully_credited(c, cn["invoice_id"], exclude_credit=cn["id"]):
        inv = c.execute("SELECT project_id,period_from,period_to,number FROM invoices WHERE id=?", (cn["invoice_id"],)).fetchone()
        again = period_clash(c, inv["project_id"], inv["period_from"], inv["period_to"], exclude_id=cn["invoice_id"])
        if again:
            return (f"annulation impossible : la période de la facture {inv['number']} a été facturée de nouveau par la facture {again['number']} "
                    "(la facture d'origine redeviendrait facturante : double facturation)")
    return ""


def cancel(c, cid, reason):
    """Issue the cancellation document ANN-<reference>. Caller owns the transaction; returns the reference."""
    from app import invoice_service
    cn = c.execute("SELECT * FROM credit_notes WHERE id=?", (cid,)).fetchone()
    if not cn: raise ValueError("note de crédit introuvable")
    reason = (reason or "").strip()
    if not reason: raise ValueError("motif d'annulation obligatoire")
    why = cancellation_blockers(c, cn)
    if why: raise ValueError(why)
    ref = "ANN-" + cn["reference"]
    invoice_service.freeze_cancellation(c, cid, ref, reason, rules.utc_now_iso())
    c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("credit_note_cancelled", f"{cn['reference']};document={ref};reason={reason}"))
    return ref


def replaceable(c, inv_id):
    """Cancelled notes of this invoice not yet replaced by another note."""
    return [dict(r) for r in c.execute("""SELECT cn.id,cn.reference,cn.treatment,k.reference cancel_ref FROM credit_notes cn
                                          JOIN credit_note_cancellations k ON k.credit_note_id=cn.id
                                          WHERE cn.invoice_id=? AND NOT EXISTS(SELECT 1 FROM credit_notes r WHERE r.replaces_credit_id=cn.id)
                                          ORDER BY cn.id""", (inv_id,))]
