# HANDOFF RC25 — Phase 2 (restore + deploy/rollback safety) — 2026-10-09

Branch `remediation/rc25-production-readiness-local`, commit **`3a0f337`** (parent `ee23940`). Not pushed.
Production, staging, /opt, real DBs, .env and secrets: not touched or read. Billing logic and golden PDF: unchanged.
All scenarios were reproduced on disposable copies only: unit-test DBs in /tmp, and a Docker sandbox in /tmp/rc25p2 (project `tbsbx25`, port 18493, synthetic data, random test secrets).

## TB-05 — Restore

### Gaps reproduced on ee23940
The new tests fail 6 of 7 on the baseline code:
- A backup missing `entries`, `projects`, `settings` or `audit` restored and emptied the table. Only issued-invoice links protected anything.
- `meta.row_counts` was never checked: missing rows, inflated counts and missing or malformed counts were all accepted.
- `rebuild()` replaced the current audit log with the file's log. Audit rows written after the backup were lost, and a file's rewritten audit row replaced the original.

### Fix (`app/restore_service.py`, `app/app.py`, `restore_review.html`)
- **New check `completeness()`**, run as part of `preview()`'s blocking reasons. It blocks:
  - a table declared in `meta.row_counts` but absent from the file;
  - a table present in the file but not declared;
  - a row count different from the declared count;
  - a missing or malformed `meta.row_counts`;
  - any business table of the current schema missing from the file.
- **Exception for older backups**: a table may be missing only when the file's own `meta.schema` does not create it (the backup predates the table) and the current table is empty.
- **`rebuild()` re-checks** the rebuilt counts against `meta.row_counts`, as a second layer.
- **Audit log**: `swap(db, rebuilt, file_audit)` now merges the audit log under its `BEGIN EXCLUSIVE` lock.
  - The current audit log is copied verbatim, with the same ids.
  - The file's rows that the current log does not hold are appended with new ids.
  - `json_restored` records `audit_kept` and `audit_appended`.
  - Because the merge happens under the lock, audit rows written between rebuild and swap are no longer lost.
- **Refusals stay non-destructive**: blocking happens before any write, and failures in rebuild or merge remove the rebuilt file.

### Tests
- New file `tests/test_rc25_restore.py`, 7 tests. Each refusal is checked by comparing every row of every table, audit included, before and after.
- **Changed fixture in `test_rc19`**: the "pre-rc19 backup" fixture removed the table but still declared it in `row_counts` and `meta.schema`, which is exactly what an amputated file looks like.
  - The fixture now drops the table from all three places, as a real pre-rc19 file would.
  - The old half-edited variant is now asserted to be refused, so an assertion was added rather than weakened.

## TB-06 — Deploy / rollback (`procedure/`)

### Gaps reproduced on ee23940
Reproduced with `migration-blanc/dry-run-n-rc25-deploiement.sh` run against the ee23940 scripts (`PROC=…`); log in `migration-blanc/N-RC25-dryrun-20261009-reference-ee23940.log`.
- 40 deploys without any 30 run.
- A failed 30 leaves the service stopped.
- **Destructive prune case**: after an image prune, 90 stops the service, moves the tree and restores the DB, and only then dies on `No such image`. Production is left stopped and half rolled back.
- A failure during 40's install leaves the service stopped, with no rollback.
- 40 also never checked that the live DB was still the backed-up one.
- Shown by reading the code:
  - 90 compared a fixed list of tables, so data in any table outside that list was discarded silently.
  - `ABANDONNER_CORRECTIONS=OUI` was not bound to a deployment, and the discarded data was not logged.
  - `rotate-secrets.sh` wrote `TB_PORT=8091` for every environment, including staging, whose URL uses 8092.
  - The second `trap … EXIT` in 30 and 90 replaced any earlier one.

### Fix
- **`tb-common.sh`**: new helpers.
  - One chained EXIT trap per script: `cleanup` always runs; `on_fail` runs only on failure. INT, TERM and HUP go through EXIT.
  - `restart_old`.
  - `url_port`: port taken from `URL`.
  - `go_marker`: bound to TS, tag, backup DB sha, `app_digest` and the rehearsal image id.
  - `rollback_image`: checks the `pre-<tag>-<TS>` tag against `image-id.txt`, or reloads it from `image.tar.gz`.
- **20**:
  - Tags the image the container actually runs, not `:latest`.
  - Saves it with `docker save | gzip` to `image.tar.gz` (about 62 MB in the sandbox), covered by `SHA256SUMS`.
  - Restarts the old version on any failure after `compose stop`.
- **30**:
  - Removes any stale marker first.
  - Requires exit 0 and a last line of `GO` before writing `rehearsal-GO` atomically.
  - On NO-GO or error: no marker, and the old version is restarted.
- **40, phase A** (nothing is modified; any failure restarts the old version). It checks:
  - `SHA256SUMS`;
  - the GO marker, compared exactly;
  - that the container is not running;
  - that the live DB sha equals the backup's;
  - the rollback image;
  - that `.env.<tag>` exists with mode 600;
  - that the published port (`TB_PORT` line, or the compose template's default) equals the URL's port.
- **40, phase B**: any failure runs `env -u ABANDONNER_CORRECTIONS 90-rollback.sh`. 90 still refuses to discard post-deployment data.
- **`rotate-secrets.sh`**: `TB_PORT` is now the URL's port. A conflicting `TB_PORT` in the environment is refused.
- **90**:
  - Runs `rollback_image` before stopping anything.
  - Compares every table except the named transient ones (`audit`, `web_sessions`, `login_failures`, `kept_forms`).
  - Reports the post-backup audit rows it sets aside.
  - Requires `ABANDONNER_CORRECTIONS=OUI-<TS>`; a plain `OUI` is refused.
  - Logs what it discards and where the verified copy is.
  - A failure between stop and tree replacement restarts the service; later failures print an explicit state message.
- **Docs**: `PROCEDURE-DEPLOIEMENT-RC11.md` now chains steps with `&&` instead of `;` and has an RC25 section. `PROCEDURE-ROLLBACK-RC11.md` uses `OUI-<TS>` and has an RC25 section.

## Tests and results
| Run | Result |
|---|---|
| `test_rc25_restore` on ee23940 app code | 7 tests, **FAILED (failures=6)**, as expected |
| `test_rc25_restore` after the fix | 7, OK |
| Restore-related modules (rc19, v92, rc10, rc10_security, rc11_qa, rc12, rc5, rc3, g4, rc23_historiques, credit_settlement, functional) | 264 tests: 1 FAIL, the rc19 fixture above; after the fixture fix, `test_rc19.Robustness` 8 tests OK |
| **Full unit suite** (37 modules, container `tb-g4-cand:3f49b60`, `--network none`, synthetic empty base; runner `/tmp/rc25p2/run.sh`) | **564 OK (skipped=1: `pdftotext absent`, environmental, same as Phase 1)** |
| Sandbox rehearsal N, fixed scripts (`migration-blanc/N-RC25-dryrun-20261009.log`) | **50/50 OK**, scenarios A–H |
| Rehearsal N on the ee23940 scripts | 14 OK, many FAIL. Scenario A deploys without GO, and the later scenarios fail because of that state |

Rehearsal N scenarios:
- A: 40 without a GO marker.
- B: 30 fails.
- C: port mismatch.
- D: GO marker made stale by a write (service running, then DB changed).
- E: full chain 10→50.
- F: unknown-table data refused, and a plain `OUI` refused.
- G: rollback image pruned; rollback with `OUI-<TS>` reloads it, the DB equals the backup, and the data is kept in the copy.
- H: install failure triggers automatic rollback.

No secrets appear in the logs (checked).

## Not proven / remaining blockers
- **`rotate-secrets.sh` was not executed.** The session policy denies any command naming it. The fix relies on the same `url_port` helper that 40 uses, which scenario C exercised. Running it on a sandbox is still to do.
- **The new scripts are not yet the ones production uses.** `prod.conf` and `staging.conf` use `COMPOSE_TEMPLATE` from `/root/time-billing-v9-rc10-20261004/procedure`. `tb-common.sh` also ties the backup exception to that path. Phase 2 has no effect until that procedure directory is promoted from this branch, under human review.
- **Historical harnesses** (`migration-blanc/test-90-f.sh`, `dry-run-*.sh`) still pass `ABANDONNER_CORRECTIONS=OUI` and continue to 40 after `|| ko`. They need updating before being rerun; 40 now refuses in that case anyway.
- **Older JSON backups**:
  - Backups without `meta.row_counts` are now refused. Every backup in this repo's history (from rc9 on) has it; V9.0 backups were not checked.
  - Backups predating a table are accepted only when their `meta.schema` lacks the table and the current table is empty.
- **Restore session window**: transient tables (sessions) are still copied at rebuild time, not under the swap lock. A login in that window could be lost; the audit log no longer can.
- **Rollback audit rows**: post-deploy audit rows are reported and kept in the `ecarte-…` copy, but are not re-inserted into the restored DB, which must match the backup's SHA.
- **Disk space**: `10-preflight` still requires only 500 MB free, and every backup now also holds the image copy (about 62 MB here).
- **Noticed, out of Phase 2 scope, unchanged**:
  - `rotate-secrets.sh` defaults `TRUST_PROXY=1` for every environment, while the staging template defaults to 0.
  - `80-site-caddy.sh` defaults its target to `127.0.0.1:8091`, which is production-only by design.
  - **`migration-blanc/extraction-A-copie-prod.db` is tracked in Git** and named as a production copy, which conflicts with the "no real data in Git" rule. To review.
- **Not run**: browser, E2E and concurrency suites, and the HTTP recette `tests/recette_fonctionnelle/run_hij.py` (H6 amputated backup). They need a running instance, which is Phase 7.
- **Remaining RC25 phases**: 0/1 (VERSION RC25, staging/prod version check), 5 (backup), 6 (agent security model), 7 (E2E/concurrency on a candidate image) and 8 (adversarial review, including Phases 1 and 2).

The untracked files `nuit/HANDOFF-RC25-PHASE1.md`, `nuit/claude2-phase*.log` and `nuit/settings-rc25.json` were left untouched. This handoff is not committed because it contains the commit SHA.
