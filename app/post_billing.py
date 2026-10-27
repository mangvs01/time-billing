"""rc19: an issued invoice never changes; the time entries it billed stay editable.

Post-invoicing variance of one issued invoice F (mandate M, period P), computed on demand and never written anywhere:
- billed rows = rows of F's frozen annex that F owns (owners(): an entry belongs to the FIRST issued invoice whose period contained its
  frozen date, whatever its date becomes later — rc25: never an entry merely listed by a later cumulative annex; the annex is cumulative:
  other rows are listed, not billed by F);
- each billed row is compared with the live entry of the same id: deleted, moved to another mandate (both count 0 h), date reclassified
  within M outside P (its hours stay billed by F: a date fix is not a second billing), modified (date, start, end, hours or
  description), unchanged;
- variance (hours) = Σ current hours of the billed rows − Σ frozen hours; in days at F's frozen hours per day (a mandate's hours per
  day cannot change once an invoice is issued);
- apart, never in the variance: entries added to (M, P) after issuance and not billed by another invoice of M (reliquat, as before
  rc19), entries billed by another invoice of M whose date now falls in P (reclassified), changes of the earlier annex rows;
- credit notes issued on F are listed; those issued after the first change count (an amount-only note at F's rate) in the remaining
  variance, shown as information;
- the user's decision (credit note, compensation, no action) is recorded append-only against the variance fingerprint: the alert
  stays until the current variance has a decision.
"""
import hashlib, json

from app import billing_rules as rules, credit_service

FIELDS = ("work_date", "start_time", "end_time", "hours", "description")
EPS = 1e-9
# rc19: one id allocator for EVERY insert path (manual entry, historical import). Since an invoiced entry can be deleted (the frozen annex
# keeps its link row, there is no foreign key any more), an id that ever existed is never given again: otherwise a new entry would inherit
# the annex link, the correction history and the import provenance of a deleted one. entries.id has no AUTOINCREMENT, hence the explicit max.
NEXT_ENTRY_ID = """(SELECT MAX(COALESCE((SELECT MAX(id) FROM entries),0),COALESCE((SELECT MAX(entry_id) FROM entry_changes),0),
                   COALESCE((SELECT MAX(entry_id) FROM invoice_annex_entries),0),COALESCE((SELECT MAX(entry_id) FROM import_batch_rows),0))+1)"""


def same_values(a, b):
    """True when two entry snapshots carry the same billable values (date, clock times, hours, description)."""
    for k in FIELDS:
        if k == "hours":
            if abs(float(a.get(k) or 0) - float(b.get(k) or 0)) > EPS: return False
        elif (a.get(k) or "") != (b.get(k) or ""): return False
    return True


def _snapshot(conn, iid):
    s = conn.execute("SELECT annex_json,header_json,frozen_at FROM invoice_snapshots WHERE invoice_id=?", (iid,)).fetchone()
    if not s: return None, {}, None
    try: annex = json.loads(s["annex_json"])
    except (ValueError, TypeError): annex = None
    try: header = json.loads(s["header_json"])
    except (ValueError, TypeError): header = {}
    return annex, header, s["frozen_at"]


def day_hours(conn, inv, header=None):
    dh = (header or {}).get("day_hours")
    if not dh:
        p = conn.execute("SELECT day_hours FROM projects WHERE id=?", (inv["project_id"],)).fetchone()
        dh = p["day_hours"] if p else None
    return float(dh or 8)


def credit_notes_on(conn, inv, dh, since):
    """Issued, non-cancelled credit notes on F, each converted to days: its quantity (hours ÷ h/j for an hour-unit invoice), or, for an
    amount-only note, its service amount at F's unit rate. 'after' marks the notes issued after the first change of a billed entry (since)."""
    out = []
    for r in conn.execute("""SELECT id,reference,qty,amount,issued_at,reason,treatment FROM credit_notes WHERE invoice_id=? AND status='issued'
                             AND id NOT IN (SELECT credit_note_id FROM credit_note_cancellations) ORDER BY issued_at,id""", (inv["id"],)):
        q = float(r["qty"]) if r["qty"] else (float(r["amount"] or 0) / float(inv["unit_rate"]) if float(inv["unit_rate"] or 0) else 0.0)
        d = q / dh if inv["unit"] == "hour" else q
        out.append(dict(r, days=round(d, 6), units=round(q, 6), by_amount=not r["qty"], after=bool(since) and (r["issued_at"] or "")[:19] >= since[:19]))
    return out


def fingerprint(rows):
    """Identity of a variance: the changed billed rows with their current values. A decision recorded for one fingerprint no longer
    covers the variance once a billed entry changes again."""
    key = [[x["id"], x["status"], [x["current"][k] for k in ("work_date", "project_id", "start_time", "end_time", "hours", "description")] if x["current"] else None]
           for x in sorted(rows, key=lambda x: x["id"])]
    return hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:24]


def invoice_variance(conn, inv):
    """Variance of one issued invoice F (sqlite Row or dict with id, number, project_id, period_from, period_to, unit, unit_rate,
    issued_at, qty, status). Returns None for a draft or an invoice without frozen copy. Nothing is ever written."""
    if inv["status"] != "issued": return None
    annex, header, frozen_at = _snapshot(conn, inv["id"])
    if annex is None: return None
    pf, pt, pid = inv["period_from"], inv["period_to"], inv["project_id"]
    dh = day_hours(conn, inv, header)
    rows_all = [r for r in annex if isinstance(r, dict) and "id" in r]
    own = owners(conn, pid)
    billed = [r for r in rows_all if own.get(r["id"], {}).get("id") == inv["id"]]
    earlier = [r for r in rows_all if own.get(r["id"], {}).get("id") != inv["id"]]   # listed by the cumulative annex, not billed by F
    live = _live(conn, [r["id"] for r in rows_all])
    rows = []; frozen_h = 0.0; now_h = 0.0
    for r in billed:
        frozen_h += float(r["hours"])
        e = live.get(r["id"])
        if e is None: status, cur, where = "supprimée", 0.0, None
        elif e["project_id"] != pid: status, cur, where = "autre mandat", 0.0, None
        elif e["work_date"] != r.get("work_date") and not (pf <= e["work_date"] <= pt):
            # same mandate, new date outside P: the hours stay billed by F (a date fix, not a second billing); where they land now
            status, cur = "date reclassée", float(e["hours"])
            g = period_invoice(conn, pid, e["work_date"])
            d = conn.execute("SELECT COUNT(*) FROM invoices WHERE project_id=? AND status='draft' AND period_from<=? AND period_to>=?", (pid, e["work_date"], e["work_date"])).fetchone()[0]
            where = {"invoice": g["number"] if g else None, "draft": bool(d)}
        elif not same_values(r, e): status, cur, where = "modifiée", float(e["hours"]), None
        else: status, cur, where = "inchangée", float(e["hours"]), None
        now_h += cur
        rows.append({"id": r["id"], "status": status, "frozen": r, "current": e, "where": where, "delta_hours": round(cur - float(r["hours"]), 6)})
    billed_ids = {r["id"] for r in billed}
    in_period = [dict(e) for e in conn.execute("""SELECT id,work_date,start_time,end_time,hours,description FROM entries
                                                  WHERE project_id=? AND work_date BETWEEN ? AND ? ORDER BY work_date,id""", (pid, pf, pt))
                 if e["id"] not in billed_ids]
    other = entries_invoices(conn, [e["id"] for e in in_period])
    late, reclassified = [], []
    for e in in_period:
        by = [x for x in other.get(e["id"], []) if x["role"] == "billed" and x["id"] != inv["id"] and x["project_id"] == pid]
        if by: reclassified.append(dict(e, billed_by=by[0]["number"]))   # billed by another invoice of the mandate: no second billing
        else: late.append(e)
    earlier_changed = []
    for r in earlier:
        e = live.get(r["id"])
        if e is None or e["project_id"] != pid or not same_values(r, e):
            earlier_changed.append({"id": r["id"], "frozen": r, "current": e,
                                    "delta_hours": round((float(e["hours"]) if e and e["project_id"] == pid else 0.0) - float(r["hours"]), 6)})
    variance_h = round(now_h - frozen_h, 6); variance_d = round(variance_h / dh, 6)
    changed = [x for x in rows if x["status"] != "inchangée"]
    since = None
    if changed:
        ids = [x["id"] for x in changed]
        since = conn.execute(f"SELECT MIN(changed_at) FROM entry_changes WHERE entry_id IN ({','.join('?' * len(ids))}) AND changed_at>=?",
                             (*ids, (inv["issued_at"] or "")[:19])).fetchone()[0] or (inv["issued_at"] or "")[:19]
    notes = credit_notes_on(conn, inv, dh, since)
    credited_after = round(sum(n["days"] for n in notes if n["after"]), 6)
    credited_after_units = round(sum(n["units"] for n in notes if n["after"]), 6)
    fp = fingerprint(changed) if changed else None
    # a « note de crédit » decision rests on that note: once the note is cancelled (documented correction path) the decision no longer treats
    # the variance, so the alert comes back; the decision row itself stays (append-only) and is shown as void
    decisions = [dict(d) for d in conn.execute("""SELECT d.*,cn.reference credit_reference,
                                                         (d.credit_note_id IS NOT NULL AND d.credit_note_id IN (SELECT credit_note_id FROM credit_note_cancellations)) void
                                                  FROM invoice_variance_decisions d
                                                  LEFT JOIN credit_notes cn ON cn.id=d.credit_note_id WHERE d.invoice_id=? ORDER BY d.id""", (inv["id"],))] if _has_decisions(conn) else []
    current = next((d for d in reversed(decisions) if d["fingerprint"] == fp and not d["void"]), None) if fp else None
    # a description-only or same-duration change is shown, but asks for no decision: no effect on the billed hours
    material = [x for x in changed if abs(x["delta_hours"]) > EPS or x["status"] in ("supprimée", "autre mandat")]
    keys = inv.keys() if hasattr(inv, "keys") else []
    unit_q = variance_h if inv["unit"] == "hour" else variance_d
    return {"invoice_id": inv["id"], "number": inv["number"], "period_from": pf, "period_to": pt, "project_id": pid, "frozen_at": frozen_at,
            "legacy": str(_frozen_by(conn, inv["id"]) or "").startswith("migration"),
            "day_hours": dh, "unit": inv["unit"], "unit_rate": float(inv["unit_rate"]), "qty": float(inv["qty"]),
            "reliquat_days": inv["reliquat_days"] if "reliquat_days" in keys else None,
            "reliquat_treatment": inv["reliquat_treatment"] if "reliquat_treatment" in keys else None,
            "rounding": inv["rounding"] if "rounding" in keys else None,
            "billed_rows": rows, "changed": changed, "late": late, "late_hours": round(sum(float(e["hours"]) for e in late), 6),
            "reclassified": reclassified, "earlier_changed": earlier_changed,
            "earlier_delta_hours": round(sum(x["delta_hours"] for x in earlier_changed), 6),
            "frozen_hours": round(frozen_h, 6), "current_hours": round(now_h, 6),
            "variance_hours": variance_h, "variance_days": variance_d,
            # information only: the variance valued at F's rate in F's unit (days, or hours for an hour-unit invoice); never written
            "variance_amount": rules.amounts(unit_q, inv["unit_rate"], 0)["ht"],
            "first_change_at": since, "credit_notes": notes, "credited_after_days": credited_after,
            "remaining_days": round(variance_d + credited_after, 6) if changed else 0.0,
            # same remainder in the invoice's own unit, computed without the hours→days→hours round trip: the credit note proposed for an
            # hour-unit invoice is then exactly the billed hours, never a few millionths above them (which a credit note would refuse)
            "remaining_units": round(unit_q + credited_after_units, 6) if changed else 0.0,
            "fingerprint": fp, "decisions": decisions, "decision": current, "needs_decision": bool(material) and current is None, "material": material,
            "has_variance": abs(variance_h) > EPS, "has_changes": bool(changed) or bool(late) or bool(reclassified) or bool(earlier_changed)}


def variance_candidates(conn):
    """Ids of the issued invoices whose variance may be non-empty (the full computation parses a cumulative annex): a billed or listed
    entry changed after issuance (application history, or database trace since rc19 for a change made outside the application), an entry
    of the period absent from the annex (late addition, reclassified), or a recorded decision. Before rc19 an annexed entry could not change."""
    return {r[0] for r in conn.execute("""SELECT i.id FROM invoices i WHERE i.status='issued' AND (
        EXISTS(SELECT 1 FROM entry_changes ec JOIN invoice_annex_entries x ON x.entry_id=ec.entry_id WHERE x.invoice_id=i.id AND ec.changed_at>=substr(i.issued_at,1,19))
     OR EXISTS(SELECT 1 FROM audit a JOIN invoice_annex_entries x ON x.invoice_id=i.id WHERE a.event IN ('entry_row_updated','entry_row_deleted')
               AND replace(a.created_at,' ','T')>=substr(i.issued_at,1,19)
               AND CASE WHEN a.event IN ('entry_row_updated','entry_row_deleted') AND json_valid(a.detail) THEN json_extract(a.detail,'$.id') END=x.entry_id)
     OR EXISTS(SELECT 1 FROM entries e WHERE e.project_id=i.project_id AND e.work_date BETWEEN i.period_from AND i.period_to
               AND NOT EXISTS(SELECT 1 FROM invoice_annex_entries x WHERE x.invoice_id=i.id AND x.entry_id=e.id))
     OR EXISTS(SELECT 1 FROM invoice_variance_decisions d WHERE d.invoice_id=i.id))""")}


def _live(conn, ids):
    live = {}
    for k in range(0, len(ids), 500):  # bounded IN lists
        chunk = ids[k:k + 500]
        for e in conn.execute(f"""SELECT e.id,e.work_date,e.project_id,e.start_time,e.end_time,e.hours,e.description,p.name project
                                  FROM entries e JOIN projects p ON p.id=e.project_id WHERE e.id IN ({','.join('?' * len(chunk))})""", chunk):
            live[e["id"]] = dict(e)
    return live


def _frozen_by(conn, iid):
    r = conn.execute("SELECT frozen_by FROM invoice_snapshots WHERE invoice_id=?", (iid,)).fetchone()
    return r["frozen_by"] if r else None


def _has_decisions(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='invoice_variance_decisions'").fetchone())


def _annex_rows(conn, iid, cache):
    """Rows of an issued invoice's frozen annex (parsed once per call through cache)."""
    if iid not in cache:
        s = conn.execute("SELECT annex_json FROM invoice_snapshots WHERE invoice_id=?", (iid,)).fetchone()
        try: cache[iid] = [a for a in json.loads(s["annex_json"]) if isinstance(a, dict) and "id" in a] if s else []
        except (ValueError, TypeError): cache[iid] = []
    return cache[iid]


def owners(conn, project_id, cache=None):
    """rc25 (owner decisions 1 and 2, 2026-10-09): {entry id: {'id', 'number'} of the issued invoice of this mandate that really billed it}.

    An entry belongs to the FIRST issued invoice (issuance order) whose frozen annex lists it with a frozen date inside that invoice's own period:
    that period is what the invoice bills (the quantity of an invoice is entered by hand, so the period is the only proof of what it claims).
    The present date of the entry never decides, and neither does the presence of the entry in a later cumulative annex: an entry added late, into a
    period already invoiced, is NOT taken over by the next invoice just because its annex lists it (it has no owner until an invoice bills it).
    An entry whose date is corrected afterwards keeps its owner, so no later invoice bills it again.
    An invoice that is entirely credited (credit_service.fully_credited) bills nothing any more: its entries have no owner and its period may be
    invoiced again (decision 4). A row its annex froze as « billed_elsewhere » (excluded at issuance, billed by another invoice) is never claimed by
    that invoice, even after the other invoice is entirely credited: it did not really bill it (decision 1), so the work stays billable.

    LIMIT OF PROOF (rc25, documented on purpose). The quantity of an invoice is typed by hand: nothing in the database links a quantity to
    particular entries. Neither an annex (cumulative: it lists every entry up to the end of the period) nor a period proves, on its own, how much of
    the quantity really covers a given entry. What this function asserts is therefore only "the period of this invoice, at issuance, contained the
    entry's date": the same proof for every entry of the period, which is the reading the invoice itself prints (period hours, check 12) and the one
    the owner confirmed. It does NOT assert that a late entry, added after a period was invoiced, was included in a later quantity, even when that
    quantity was deliberately raised (the raise needs a written exception of check 12): such an entry stays without owner, the variance and the
    credit-note proposals never attach it to a later invoice, and only a future explicit declaration at issuance could change that (not implemented).
    Conversely, an entry owned by an invoice may in fact never have been counted in a quantity typed below the period's hours (within the 0.5 day
    under-billing tolerance): the variance then measures the entry, not the quantity."""
    cache = {} if cache is None else cache
    own = {}
    for f in conn.execute("""SELECT id,number,period_from,period_to FROM invoices WHERE project_id=? AND status='issued'
                             ORDER BY replace(COALESCE(issued_at,''),' ','T'),id""", (project_id,)).fetchall():
        if credit_service.fully_credited(conn, f["id"]): continue
        for a in _annex_rows(conn, f["id"], cache):
            if a["id"] in own or a.get("billed_elsewhere"): continue      # frozen as billed by another invoice: this one never billed it (decision 1)
            if f["period_from"] <= (a.get("work_date") or "") <= f["period_to"]:
                own[a["id"]] = {"id": f["id"], "number": f["number"]}
    return own


def entries_invoices(conn, entry_ids):
    """{entry id: issued invoices whose frozen annex lists it}, each with its role for that entry: 'billed' when the invoice owns it
    (owners(): first issued invoice of its mandate that billed it), 'annex' otherwise (listed by the cumulative annex only). Each annex
    parsed once."""
    ids = list(dict.fromkeys(entry_ids)); links = []
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        links += conn.execute(f"""SELECT x.entry_id,i.id,i.number,i.project_id,i.period_from,i.period_to,i.issued_at FROM invoice_annex_entries x
                                  JOIN invoices i ON i.id=x.invoice_id WHERE i.status='issued' AND x.entry_id IN ({','.join('?' * len(chunk))})
                                  ORDER BY i.period_to,i.id""", chunk).fetchall()
    cache, annexes, own, out = {}, {}, {}, {}
    for l in links:
        iid = l["id"]
        if iid not in annexes: annexes[iid] = {a["id"]: a for a in _annex_rows(conn, iid, cache)}
        if l["project_id"] not in own: own[l["project_id"]] = owners(conn, l["project_id"], cache)
        frozen = annexes[iid].get(l["entry_id"])
        role = "billed" if frozen and own[l["project_id"]].get(l["entry_id"], {}).get("id") == iid else "annex"
        out.setdefault(l["entry_id"], []).append({"id": iid, "number": l["number"], "project_id": l["project_id"], "period_from": l["period_from"],
                                                  "period_to": l["period_to"], "issued_at": l["issued_at"], "role": role, "frozen": frozen})
    return out


def entry_invoices(conn, entry_id):
    return entries_invoices(conn, [entry_id]).get(entry_id, [])


def changed_since(inv, entry):
    """True when the entry no longer matches what this invoice froze: values (date included) or mandate. A late entry taken up by a
    cumulative annex (owners(), case 3) is frozen outside the invoice period: unchanged while its values are."""
    f = inv.get("frozen")
    if not f: return True
    return (not same_values(f, entry)) or entry["project_id"] != inv["project_id"]


def period_invoice(conn, project_id, work_date):
    """The issued invoice of this mandate whose period contains the date and that still stands, if any (issued periods that stand never overlap:
    an entirely credited invoice no longer stands, rc25)."""
    for r in conn.execute("""SELECT id,number,period_from,period_to FROM invoices WHERE project_id=? AND status='issued'
                             AND period_from<=? AND period_to>=? ORDER BY id""", (project_id, work_date, work_date)):
        if not credit_service.fully_credited(conn, r["id"]): return dict(r)
    return None
