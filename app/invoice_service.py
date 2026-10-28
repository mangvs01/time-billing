"""Invoice / credit-note assembly, issuance-time freezing and frozen PDF serving.

An issued document is served only from its snapshot: header (including issuer and
billing data as they were), cumulative annex and PDF bytes are captured in the
issuing transaction and never regenerated.
"""
import hashlib, json
from datetime import datetime

from app import address_service, billing_rules as rules, historical_billing, pdf_layout, post_billing


def _jsonable(h):
    return {k: ({kk: str(vv) for kk, vv in v.items()} if k == "amounts" else v) for k, v in h.items()}


def live_data(conn, iid):
    i = conn.execute("""SELECT i.*,p.name project,p.client,p.po,p.day_hours,p.project_number,p.billing_contact,p.billing_address,
                               p.dates_label,p.ordered_days,p.client_legal_name,p.client_legal_id,p.short_name project_short,p.id pid FROM invoices i JOIN projects p ON p.id=i.project_id WHERE i.id=?""", (iid,)).fetchone()
    if not i: return None, []
    # Decision billing-facturee-par-date = A (2026-10-08): an entry of the period already billed by an earlier issued invoice of the mandate
    # (its date was corrected into this period afterwards) stays in the cumulative annex, marked with the number of the invoice that billed
    # it, but is not work of this period: not in the period hours, check 1 / 12 or the section « période » of the annex (no second billing).
    own = post_billing.owners(conn, i["project_id"])
    rows = [dict(r, billed_elsewhere=own[r["id"]]["number"]) if r["id"] in own and own[r["id"]]["id"] != iid and i["period_from"] <= r["work_date"] <= i["period_to"]
            else dict(r) for r in conn.execute("SELECT id,work_date,start_time,end_time,hours,description FROM entries WHERE project_id=? AND work_date<=? ORDER BY work_date,id",
                                               (i["project_id"], i["period_to"]))]
    keys = ("id", "number", "status", "issued_at", "invoice_date", "project_id", "project", "client", "po", "period_from", "period_to", "qty", "unit",
            "unit_rate", "vat", "note", "rounding", "rounding_step", "day_hours", "project_number", "billing_contact", "billing_address", "dates_label",
            "ordered_days", "description", "other_amount", "other_label", "reliquat_days", "reliquat_treatment", "reliquat_note",
            "client_legal_name", "client_legal_id", "project_short")
    header = {k: i[k] for k in keys}
    # rc37 (P2): the address printed is the COPY chosen on the invoice, else the mandate's own (drafts and invoices that never chose one); frozen with the invoice
    label, contact, address, source = address_service.effective(i, i)
    header["billing_contact"], header["billing_address"] = contact, address
    header["billing_label"], header["billing_source"], header["billing_address_id"] = label, source, i["billing_address_id"]
    header["other_vat_mode"] = rules.other_vat_mode(i["other_vat_mode"])  # explicit in the frozen copy, even for legacy NULL
    header["client_legal_id_display"] = rules.legal_display(i["client_legal_id"])  # rc5: printed form; client_legal_id stays as entered
    # rc5: invoice-date changes made on the draft, frozen with the invoice
    header["invoice_date_history"] = [dict(r) for r in conn.execute(
        "SELECT old_date,new_date,context,changed_at FROM invoice_date_changes WHERE invoice_id=? ORDER BY id", (iid,))]
    header["consumed_days"] = round(sum(r["hours"] for r in rows) / (i["day_hours"] or 8), 5)
    # A4 (rc7): contract position in days, kept apart (realised / invoiced / cancelled by credit notes / balance).
    # Computed from the stored history, never written back; frozen with the invoice at issuance (then this invoice
    # is already 'issued' and counted). A draft preview counts the draft itself as invoiced.
    p = conn.execute("SELECT * FROM projects WHERE id=?", (i["project_id"],)).fetchone()
    # G4: the figures of invoiced days are kept apart and never deduced from the time entries: historical invoices (issued outside Time Billing, VALIDATED in the
    # registry), earlier Time Billing invoices and this invoice itself. D9 (decision B, 2026-10-07): one cutoff for every document, the DATE OF THIS INVOICE:
    # a document counts when it is dated on or before it (historical invoices, Time Billing invoices, credit notes and their cancellations alike).
    dh = i["day_hours"] or 8
    bill_date = i["invoice_date"] or rules.local_today().isoformat()
    k = rules.contract(conn, p, upto=i["period_to"], exclude_invoice=iid, historical_upto=bill_date)
    others = conn.execute("SELECT id,qty,unit,invoice_date,issued_at FROM invoices WHERE project_id=? AND status='issued' AND id<>?", (i["project_id"], iid)).fetchall()
    counted = {r["id"] for r in others if rules.doc_date(r) <= bill_date}
    previous = sum(rules.days(r["qty"], r["unit"], dh) for r in others if r["id"] in counted)
    later = sum(rules.days(r["qty"], r["unit"], dh) for r in others if r["id"] not in counted)   # dated after this invoice: not counted at this cutoff
    current = rules.days(i["qty"], i["unit"], dh)
    hist = k["historical_days"]
    # R-E7-1 (2026-10-06): the days cancelled are those of the credit notes on the invoices counted above, themselves dated on or before the cutoff (D9);
    # a cancellation dated after the cutoff did not exist yet
    credited = round(sum(rules.days(r["qty"], r["unit"], dh) for r in conn.execute(
        """SELECT cn.qty,o.unit,o.id inv,cn.issued_at,x.issued_at cancelled_at FROM credit_notes cn JOIN invoices o ON o.id=cn.invoice_id
           LEFT JOIN credit_note_cancellations x ON x.credit_note_id=cn.id WHERE o.project_id=? AND cn.status='issued' AND cn.qty IS NOT NULL""", (i["project_id"],))
        if r["inv"] in counted and rules.local_date(r["issued_at"]) <= bill_date and not (r["cancelled_at"] and rules.local_date(r["cancelled_at"]) <= bill_date)), 5)
    header["position"] = {"ordered": k["ordered_days"], "realized": header["consumed_days"], "historical": hist, "previous": round(previous, 5), "current": round(current, 5),
                          "invoiced": round(hist + previous + current, 5), "credited": credited,
                          "balance": round(k["ordered_days"] - (hist + previous + current - credited), 5), "later": round(later, 5),
                          "historical_count": k["historical_count"], "cutoff": bill_date,
                          "historical_items": [{"date": r["invoice_date"], "days": r["qty_days"], "cell": historical_billing.cell_label(r["source_sheet"], r["source_cell"])} for r in conn.execute(
                              """SELECT invoice_date,qty_days,source_sheet,source_cell FROM historical_invoices WHERE project_id=? AND status='validated' AND qty_days IS NOT NULL
                                 AND invoice_date IS NOT NULL AND invoice_date<=? ORDER BY invoice_date,id""", (i["project_id"], bill_date))]}
    header["period_hours"] = round(sum(r["hours"] for r in rows if i["period_from"] <= r["work_date"] <= i["period_to"] and not r.get("billed_elsewhere")), 6)
    elsewhere = sorted({r["billed_elsewhere"] for r in rows if r.get("billed_elsewhere")})
    if elsewhere: header["period_billed_elsewhere"] = elsewhere      # only then: the frozen header of an ordinary invoice keeps its keys
    if rules.exception_mandate(p): header["exception"] = rules.EXCEPTION_LABEL      # rc41: only then (the frozen header of any other invoice keeps its keys); the PDF does not print it
    header["issuer"] = rules.get_settings(conn)
    # rc37 (P1): manual lines. A draft reads its live rows; an issued invoice read at the freeze moment reads the same (now immutable) rows, and its snapshot header
    # keeps the printed copy: a document issued is never rendered again from the table.
    # rc37 (P3): a draft prints the number it reserved, or (a draft created before rc37 that has none yet) the free number that would be proposed; issued: the number as frozen
    header["number_reserved"] = i["number"] is not None
    if i["status"] == "draft" and i["number"] is None:
        header["number"] = rules.propose_invoice_number(conn, int((i["invoice_date"] or rules.local_today().isoformat())[:4]), exclude_id=iid)
    header["lines"] = [{k: ln[k] for k in ("position", "description", "qty", "unit", "unit_rate", "vat_mode")} for ln in rules.invoice_lines(conn, iid)]
    header["amounts"] = rules.invoice_amounts(i, header["lines"])
    # credit notes imputed on this invoice (offset mode): printed, and frozen with it at issuance
    from app import credit_service
    offs = credit_service.active_offsets_on(conn, iid)
    header["offsets"] = [{"op_id": o["id"], "reference": o["reference"], "amount": str(credit_service.dec(o["amount"]))} for o in offs]
    header["net_due"] = str(header["amounts"]["ttc"] - sum((credit_service.dec(o["amount"]) for o in offs), credit_service.ZERO))
    return header, [dict(r) for r in rows]


def render(conn, iid):
    header, rows = live_data(conn, iid)
    if header and header["status"] == "draft":      # G4: a draft says on its own page which checks (before issuance) fail
        from app import invoice_checks
        header["checks_failed"] = [c["n"] for c in invoice_checks.failures(invoice_checks.run_checks(conn, iid))]
    return pdf_layout.render_invoice(header, rows, issued=header["status"] == "issued")


def freeze(conn, iid, frozen_by, legacy=False):
    """Capture header, annex and PDF of an issued invoice. Caller owns the transaction."""
    header, rows = live_data(conn, iid)
    if not header or header["status"] != "issued": raise ValueError("seule une facture émise peut être figée")
    if not legacy:      # rc38: last barrier (the issuance route checks it first) while the credit notes on manual lines are not in service
        why = rules.manual_lines_issuance_problem(conn, iid)
        if why: raise ValueError(why)
    data = render_v90(header, rows) if legacy else pdf_layout.render_invoice(header, rows, issued=True)[0]
    conn.execute("""INSERT INTO invoice_snapshots(invoice_id,number,frozen_at,frozen_by,header_json,annex_json,pdf,pdf_sha256)
                    VALUES(?,?,?,?,?,?,?,?)""",
                 (iid, header["number"], rules.utc_now_iso(), frozen_by,
                  json.dumps(_jsonable(header), ensure_ascii=False), json.dumps(rows, ensure_ascii=False), data, hashlib.sha256(data).hexdigest()))
    conn.executemany("INSERT INTO invoice_annex_entries(invoice_id,entry_id) VALUES(?,?)", [(iid, r["id"]) for r in rows])
    return len(rows)


def frozen_pdf(conn, iid):
    s = conn.execute("SELECT number,pdf,pdf_sha256 FROM invoice_snapshots WHERE invoice_id=?", (iid,)).fetchone()
    if not s: return None, None
    if hashlib.sha256(s["pdf"]).hexdigest() != s["pdf_sha256"]: raise RuntimeError("empreinte du PDF figé invalide")
    return s["number"], bytes(s["pdf"])


def frozen_header(conn, iid):
    s = conn.execute("SELECT header_json FROM invoice_snapshots WHERE invoice_id=?", (iid,)).fetchone()
    return json.loads(s["header_json"]) if s else None


def render_v90(i, rows):
    """Exact V9.0 renderer, kept only to freeze invoices issued before snapshots existed: the PDF a
    client received from V9.0 was produced by this code, not by the V9.2 reference layout."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    b = io.BytesIO(); pdf = canvas.Canvas(b, pagesize=A4); w, h = A4; y = h - 45
    pdf.setFont("Helvetica-Bold", 17); pdf.drawString(45, y, "FACTURE / BROUILLON"); y -= 28; pdf.setFont("Helvetica", 9)
    for s in [f"Numéro : {i['number'] or 'BROUILLON'}", f"Client : {i['client']}", f"Projet : {i['project']}", f"PO : {i['po']}", f"Période facturée : {i['period_from']} au {i['period_to']}", f"Quantité : {i['qty']:g} {i['unit']} × CHF {i['unit_rate']:.2f}", f"Total HT : CHF {i['qty']*i['unit_rate']:.2f}", f"TVA : {i['vat']:g}%", f"Total TTC : CHF {i['qty']*i['unit_rate']*(1+i['vat']/100):.2f}"]:
        pdf.drawString(45, y, s); y -= 15
    y -= 8; pdf.setFont("Helvetica-Bold", 10); pdf.drawString(45, y, "ANNEXE CUMULATIVE — du début du projet à la date d'arrêté"); y -= 17; pdf.setFont("Helvetica", 8)
    total = 0
    for e in rows:
        total += e["hours"]
        if y < 45: pdf.showPage(); y = h - 40; pdf.setFont("Helvetica", 8)
        pdf.drawString(45, y, f"{e['work_date']} | {e['hours']:.2f} h | {e['description'][:95]}"); y -= 12
    pdf.drawString(45, max(30, y - 10), f"Cumul temps enregistré au {i['period_to']} : {total:.2f} h / {total/(i['day_hours'] or 8):.3f} jours")
    pdf.save(); return b.getvalue()


def freeze_legacy_issued(conn):
    """One-time migration: issued invoices without snapshot are frozen with the V9.0 renderer that produced them."""
    todo = [r["id"] for r in conn.execute("SELECT i.id FROM invoices i LEFT JOIN invoice_snapshots s ON s.invoice_id=i.id WHERE i.status='issued' AND s.invoice_id IS NULL")]
    for iid in todo: freeze(conn, iid, "migration-v9.2 (rendu V9.0)", legacy=True)
    return len(todo)


# --- credit notes -------------------------------------------------------------------------------

def credit_data(conn, cid):
    cn = conn.execute("SELECT * FROM credit_notes WHERE id=?", (cid,)).fetchone()
    if not cn: return None
    inv = frozen_header(conn, cn["invoice_id"])
    if inv is None: raise ValueError("facture d'origine sans copie figée")
    h = dict(cn)
    # Snapshots frozen before V9.2 carry neither issuer data nor invoice_date: fall back explicitly.
    inv.setdefault("invoice_date", rules.local_date(inv.get("issued_at") or ""))
    for k in ("billing_contact", "billing_address", "project_number", "dates_label"): inv.setdefault(k, "")
    h["invoice"] = inv
    # the issued document reuses the issuer data frozen with the original invoice, not today's settings
    h["issuer"] = inv.get("issuer") or rules.get_settings(conn)
    from app import credit_service
    h["amounts"] = credit_service.credit_amounts(cn)
    # rc38: the manual lines credited by this note, as printed (description and amount copied when the note was created, frozen with the document)
    h["lines"] = [{"position": ln["position"], "invoice_line_id": ln["invoice_line_id"], "description": ln["description"], "amount": str(ln["amount"]), "vat_mode": ln["vat_mode"]}
                  for ln in credit_service.note_lines(conn, cid)]
    h["other_vat_mode"] = rules.other_vat_mode(cn["other_vat_mode"])
    if cn["replaces_credit_id"]:
        r = conn.execute("SELECT cn.reference,k.reference cancel_ref FROM credit_notes cn LEFT JOIN credit_note_cancellations k ON k.credit_note_id=cn.id WHERE cn.id=?",
                         (cn["replaces_credit_id"],)).fetchone()
        h["replaces"] = dict(r) if r else None
    return h


def render_credit(conn, cid):
    h = credit_data(conn, cid)
    return pdf_layout.render_credit_note(h, issued=h["status"] == "issued")


def freeze_credit(conn, cid):
    h = credit_data(conn, cid)
    data, _ = pdf_layout.render_credit_note(h, issued=True)
    conn.execute("INSERT INTO credit_note_snapshots(credit_note_id,reference,frozen_at,header_json,pdf,pdf_sha256) VALUES(?,?,?,?,?,?)",
                 (cid, h["reference"], rules.utc_now_iso(), json.dumps(_jsonable(h), ensure_ascii=False, default=str), data, hashlib.sha256(data).hexdigest()))


def frozen_credit_pdf(conn, cid):
    s = conn.execute("SELECT reference,pdf,pdf_sha256 FROM credit_note_snapshots WHERE credit_note_id=?", (cid,)).fetchone()
    if not s: return None, None
    if hashlib.sha256(s["pdf"]).hexdigest() != s["pdf_sha256"]: raise RuntimeError("empreinte du PDF figé invalide")
    return s["reference"], bytes(s["pdf"])


def freeze_cancellation(conn, cid, reference, reason, issued_at):
    """Cancellation document of an issued credit note: the note's frozen header + reason, own frozen PDF."""
    s = conn.execute("SELECT header_json FROM credit_note_snapshots WHERE credit_note_id=?", (cid,)).fetchone()
    if not s: raise ValueError("note de crédit sans copie figée")
    note = json.loads(s["header_json"])
    h = {"reference": reference, "reason": reason, "issued_at": issued_at, "note": note, "invoice": note["invoice"], "issuer": note["issuer"]}
    data, _ = pdf_layout.render_cancellation(h)
    conn.execute("INSERT INTO credit_note_cancellations(credit_note_id,reference,reason,issued_at,header_json,pdf,pdf_sha256) VALUES(?,?,?,?,?,?,?)",
                 (cid, reference, reason, issued_at, json.dumps(h, ensure_ascii=False, default=str), data, hashlib.sha256(data).hexdigest()))


def frozen_cancellation_pdf(conn, cid):
    s = conn.execute("SELECT reference,pdf,pdf_sha256 FROM credit_note_cancellations WHERE credit_note_id=?", (cid,)).fetchone()
    if not s: return None, None
    if hashlib.sha256(s["pdf"]).hexdigest() != s["pdf_sha256"]: raise RuntimeError("empreinte du PDF figé invalide")
    return s["reference"], bytes(s["pdf"])
