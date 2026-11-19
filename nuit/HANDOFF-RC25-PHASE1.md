# HANDOFF RC25 — Phase 1 (billing correctness) — 2026-10-08

Branch `remediation/rc25-production-readiness-local`, commit **`ee23940`** (parent `6eeaba3`). Not pushed. Production, staging, /opt, .env and real DBs: not touched or read.
The audit document (`ba2514e`) is not in this repo, so the gaps were reproduced from the code (TB-xx labels below are this session's, see `tests/test_rc25_billing.py`).

## Problems found (baseline 6eeaba3)
1. **Ownership (TB-01)**: decision A was already in the baseline (`owners()`), but an invoice could later claim an annex row it had frozen as `billed_elsewhere` once the original owner was fully credited.
   Also `tests.test_rc19 ... test_moves_across_periods...` still asserted the pre-A warning, so the baseline suite was red: 542 tests, 1 FAIL.
2. **Date moved after invoicing (TB-02)**: the issuance reliquat counted entries by their *current* date. Moving a billed entry past the next period made the next invoice's reliquat falsely negative (−1 j in the test).
3. **historical_invoices (TB-03)**: the reliquat counted historical invoices only up to the invoice date. A backdated TB invoice could bill again what a later-dated external invoice had already billed, and nothing flagged it.
   `set_status(validated)` also did not refuse a historical row carrying a Time Billing invoice number.
4. **Negative reliquat (TB-04)**: it was issued silently with "reporté" or "autre".
5. **Exceptions (TB-05)**: D8 derogation reasons were stored only in the audit log, not with the invoice.
6. **Full credit note (TB-06)**: the period of a fully credited invoice could never be invoiced again (period clash, and the entries stayed owned by it).
7. **Catch-up invoice (TB-07)**: for an out-of-order invoice, the reliquat subtracted the days of invoices for *later* periods (−1 j in the test).
8. **Tolerance (TB-08)**: check 12 accepted up to +0.5 j over the period's work with no reason.

## Changes (11 files)
- `app/post_billing.py`
  - `owners()` skips `billed_elsewhere` rows and fully credited invoices.
  - `period_invoice()` ignores fully credited invoices.
  - New `remainder()`: reliquat = min(cumulative up to the period end, mandate-wide with *all* validated historical invoices, own-period work − qty when catch-up). It is ownership-aware.
- `app/credit_service.py`: `fully_credited`, `neutralised_ids`, `reissue_blockers` (cancelling a note is refused once the work was re-invoiced).
- `app/app.py`:
  - Draft and issue period clashes ignore fully credited invoices.
  - `issue_context` uses `remainder()`.
  - A negative reliquat requires `negative_reliquat_reason` (≥ 10 chars). The reason is stored in `reliquat_note`, in the frozen header `issue_exceptions`, and in the audit event `invoice_negative_reliquat_exception`.
  - Check-12/13 derogations are also frozen in `issue_exceptions`.
- `app/invoice_service.py`: `freeze(..., exceptions=)` adds the exceptions to `header_json` only, after rendering, so the PDF is unchanged.
- `app/invoice_checks.py`: `OVERBILLING_TOLERANCE_DAYS = 0.0`. Over-billing fails check 12 (derogable with a written reason); under-billing keeps 0.5 j.
- `app/historical_billing.py`: validation refuses a row carrying a TB invoice number.
- `app/templates/issue_confirm.html`: reason field for a negative reliquat; corrected text for an out-of-order invoice.
- Tests:
  - New `tests/test_rc25_billing.py` (15 tests). Against baseline app code, 10 of them fail (7 FAIL, 3 ERROR). The other 5 guard behaviour that already worked.
  - `test_rc19`: stale assertion replaced by decision A, plus a check that /suggest does not propose the hours again.
  - `test_g4_fidelite` (2 tests): moved from the old +0.5 j tolerance to the zero boundary, with added assertions that +0.042 j and +0.5 j now fail.
  - `test_functional.DEROGATION` fixture: adds `negative_reliquat_reason`, following the same pattern as the D8 reasons, for fixtures that bill more than their entries.
- No tests skipped, xfailed or disabled. No schema change: no new table, trigger or migration, so restore and backup are unaffected.

## Tests run (container `tb-g4-cand:3f49b60`, `--network none`, SYNTHETIC EMPTY base DB in /tmp; runner `/tmp/rc25p1/run.sh`)
| Run | Tests | Result |
|---|---|---|
| Baseline full suite | 542 | FAILED (failures=1: test_rc19 moves…), skipped=1 |
| Billing subset after the change (7 modules) | 147 | OK, except the same rc19 test (fixed afterwards) |
| `test_rc25_billing` on baseline app code | 15 | FAILED (failures=7, errors=3), as expected |
| `test_rc25_billing` | 15 | OK |
| Full suite, first pass | 557 | FAILED (2: g4_fidelite tolerance tests, updated) |
| **Full suite, final** | **557** | **OK (skipped=1: `pdftotext absent`, environmental, same as baseline)** |

Not run: browser/E2E/concurrency HTTP (`tests/browser`, `e2e_*.py`, `concurrency_http.py`). They need a running instance; that is Phase 7.
Not verified against the staging DB copy (forbidden here). The historical staging runner `journaux/run_unit.sh` uses it.

## Assumptions (not backed by an audit text; to confirm)
- **"Catch-up invoice"** = an issued, non-credited invoice already covers a later period (this matches the existing "hors ordre chronologique" banner).
- **"Fully credited"** = issued, non-cancelled notes cover service HT, AUTRES and the full quantity. A total credit by amount only does not reopen the period (the days are not reversed in the position).
- **Mandate-wide reliquat** counts every validated historical invoice whatever its date. On mandates already billed ahead historically, every new invoice now needs a written reason.
- **Carry-over billing** (qty above the period's work, absorbed by a "reporté" reliquat) now requires a check-12 derogation reason, which follows directly from zero tolerance.
- **Out of scope:** the printed position (D9), `contract()` and the dashboard "unbilled" figure are unchanged and not ownership-aware. Moving an entry to *another mandate* still relies on the post-billing variance decision.

## Remaining RC25 blockers
Phases 0/1 (VERSION RC25, staging/prod version check), 3 (restore: amputated backups, `meta.row_counts`, audit replacement, destructive tests), 4 (fail-closed deploy/rollback, GO marker, traps, ports, durable rollback image), 5 (backup), 6 (agent security model), 7 (E2E/concurrency on a candidate image), and 8 (adversarial review, including of this phase). Untracked `nuit/claude2-phase1.log` and `nuit/settings-rc25.json` were left untouched.
