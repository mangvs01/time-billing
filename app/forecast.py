"""Calendar-year forecast from the real purchase-order balance (HT).

Remaining value = max(0, ordered − billed days) × daily rate, spread evenly over the
mandate's remaining months (from the current month, or its start if later, to its end).
Closed mandates are excluded. A mandate whose end has passed with a positive balance is
reported apart ("échu") instead of being silently spread. Actuals = issued invoices
(HT, by invoice date) plus validated historical invoices (HT, by invoice date) minus issued credit notes (HT, by issue date).
"""
from decimal import Decimal, ROUND_HALF_UP

from app import billing_rules as rules

CENT = Decimal("0.01")


def _idx(ym): return int(ym[:4]) * 12 + int(ym[5:7]) - 1
def _ym(i): return f"{i // 12:04d}-{i % 12 + 1:02d}"


def build(c, today):
    cur = today.year * 12 + today.month - 1
    months, expired, undated = {}, [], []
    for p in c.execute("SELECT * FROM projects WHERE active=1 ORDER BY name"):
        pos = rules.contract(c, p)
        balance = (Decimal(str(max(pos["po_balance_days"], 0))) * Decimal(str(p["rate"] or 0))).quantize(CENT, ROUND_HALF_UP)
        if balance <= 0: continue
        if p["start_date"]: start = _idx(p["start_date"])
        else: start = cur; undated.append(p["name"])
        end = start + max(1, int(p["duration_months"] or 12)) - 1
        first = max(cur, start)
        if end < first:
            expired.append({"project": p["name"], "end": _ym(end), "balance": balance}); continue
        n = end - first + 1; share = (balance / n).quantize(CENT, ROUND_HALF_UP)
        for k in range(n):
            amount = share if k < n - 1 else balance - share * (n - 1)  # last month absorbs rounding: total stays exact
            m = months.setdefault(_ym(first + k), {"amount": Decimal(0), "detail": []})
            m["amount"] += amount; m["detail"].append((p["name"], amount))
    actual = {}
    mlines = rules.invoice_lines_by_id(c)
    for r in c.execute("SELECT id, invoice_date, issued_at, qty, unit_rate, vat FROM invoices WHERE status='issued'"):
        y = rules.doc_date(r)[:4]  # D9: the year of the invoice date (work of 2026 invoiced in 2027 belongs to 2027); legacy rows: Zurich day of issuance
        # rc37 (D6 = A): the manual lines of an invoice are part of its turnover (« AUTRES » stays out, as before)
        actual[y] = actual.get(y, Decimal(0)) + rules.amounts(r["qty"], r["unit_rate"], 0, lines=mlines.get(r["id"], ()))["subtotal"]
    # service HT only, like invoices above; cancelled credit notes are neutralised by their cancellation document
    for r in c.execute("""SELECT issued_at, qty, unit_rate, amount, other_amount, lines_taxed, lines_untaxed FROM credit_notes WHERE status='issued'
                          AND id NOT IN (SELECT credit_note_id FROM credit_note_cancellations)"""):
        ht = rules.amounts(1, r["amount"], 0)["ht"] + Decimal(str(r["lines_taxed"] or 0)) + Decimal(str(r["lines_untaxed"] or 0))  # service HT of the note + (rc38) the manual lines it credits
        y = rules.local_date(r["issued_at"])[:4]  # Zurich calendar year of the document (UTC timestamp near New Year differs)
        actual[y] = actual.get(y, Decimal(0)) - ht
    # G4: invoices issued outside the application and VALIDATED by the user count in the turnover of their year (service HT, by invoice date)
    from app import historical_billing
    for y, ht in historical_billing.amounts_by_year(c).items(): actual[y] = actual.get(y, Decimal(0)) + ht
    years = sorted({m[:4] for m in months} | {str(today.year)} | set(actual))
    out = []
    for y in years:
        rows = [{"month": m, "amount": months[m]["amount"], "detail": months[m]["detail"]} for m in sorted(months) if m[:4] == y]
        planned = sum((r["amount"] for r in rows), Decimal(0)); done = actual.get(y, Decimal(0))
        out.append({"year": y, "months": rows, "planned": planned, "actual": done, "total": planned + done})
    return {"years": out, "expired": expired, "undated": undated}
