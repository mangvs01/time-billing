"""Parallel runner of the unit suites: N processes, each one is outils/run_tests_isolated.py on a batch of test modules, with its OWN throw-away scratch directory.

Usage (from anywhere; the repository root is found from this file):
    /root/venvs/rc25-test-venv/bin/python -I outils/run_tests_parallel.py                       whole suite (tests/test_*.py), N = number of CPUs
    /root/venvs/rc25-test-venv/bin/python -I outils/run_tests_parallel.py -j 4 tests.test_rc10 tests.test_import      chosen modules
    options: -j N (processes) · --lots K (batches, default 8 x N) · -v (print every batch's console) · --durations K (the K slowest tests) · --durable (keep fsync on, see below)
             --json FILE (all per-test records, merged) · --ref REF.json [REF2.json ...] (compare this run, test by test, with earlier records) · --list (show the batches, run nothing)
             --compare NEW.json [NEW2.json ...] --ref REF.json [...]  (compare two earlier runs, run nothing) · --write-weights (rewrite outils/run_tests_parallel_poids.json from this run)

What it guarantees: the tests are exactly those of run_tests_isolated.py, unchanged and unfiltered (a module is never split, nothing is skipped or retried); the result is the sum of the batches:
the exit status is 0 only if every batch is OK, and the summary has the same vocabulary as unittest (Ran N tests ... OK (expected failures=5)). Every batch is a fresh process with its own
synthetic scratch directory (made and removed by run_tests_isolated.py), so no database, temporary file or port is shared between two batches. No network, no real data.
Speed (see docs/TESTS-DUREE.md): batches run side by side, longest first (weights in outils/run_tests_parallel_poids.json, measured; fallback = file size), and each process runs with
RC25_FAST=1: SQLite does not fsync the throw-away databases (--durable switches this off). Only durability against a power cut is given up; locks, transactions and SQL are the same.
Exit status: 0 = all OK · 1 = a test failed / errored / succeeded unexpectedly, or a batch died or timed out · 2 = bad usage or comparison with the reference differs.
"""
import argparse, collections, concurrent.futures, glob, json, os, resource, shutil, subprocess, sys, tempfile, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "outils", "run_tests_isolated.py")
WEIGHTS = os.path.join(ROOT, "outils", "run_tests_parallel_poids.json")
LOT_TIMEOUT = 3300      # seconds per batch (the longest sequential batch of the old procedure took a few minutes, even on a loaded server)


def _inside(path, base):
    path, base = os.path.realpath(path), os.path.realpath(base)
    return path == base or path.startswith(base + os.sep)


def all_modules():
    return sorted("tests." + os.path.basename(f)[:-3] for f in glob.glob(os.path.join(ROOT, "tests", "test_*.py")))


def module_of(unit):
    """tests.test_x[.Class[.test]] -> tests.test_x"""
    parts = unit.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else unit


def weight_table():
    try: return json.load(open(WEIGHTS))
    except (OSError, ValueError): return {}


def weight(unit, table):
    mod = module_of(unit)
    if mod in table: return float(table[mod])
    try: return os.path.getsize(os.path.join(ROOT, *mod.split(".")) + ".py") / 4000.0      # crude fallback: ~ seconds from the file size
    except OSError: return 1.0


def make_lots(units, k, table):
    """Greedy longest-first partition of the units into k batches (a unit is never split). Returns the batches, heaviest first."""
    k = max(1, min(k, len(units)))
    lots = [[0.0, []] for _ in range(k)]
    for u in sorted(units, key=lambda u: -weight(u, table)):
        lot = min(lots, key=lambda l: l[0]); lot[0] += weight(u, table); lot[1].append(u)
    lots = [l for l in lots if l[1]]
    return sorted(lots, key=lambda l: -l[0])


def run_lot(idx, units, py, outdir, fast):
    env = {k: v for k, v in os.environ.items() if k not in ("RC25_WORK", "DB_PATH", "BASE_DB", "RC25_FAST", "RC25_RESULT_JSON")}
    if fast: env["RC25_FAST"] = "1"
    jpath = os.path.join(outdir, f"lot{idx}.json"); env["RC25_RESULT_JSON"] = jpath
    cpath = os.path.join(outdir, f"lot{idx}.out")
    t0 = time.perf_counter(); status = "ok"
    with open(cpath, "w") as out:
        p = subprocess.Popen([py, "-I", RUNNER] + units, stdout=out, stderr=subprocess.STDOUT, env=env, cwd=ROOT, stdin=subprocess.DEVNULL)
        try: rc = p.wait(timeout=LOT_TIMEOUT)
        except subprocess.TimeoutExpired:
            p.kill(); p.wait(); rc = None; status = "timeout"
    secs = time.perf_counter() - t0
    try: data = json.load(open(jpath))
    except (OSError, ValueError): data = None
    if rc is None: pass
    elif data is None: status = "died"          # no record file: the runner refused to start or crashed before the end
    elif rc != 0 and data.get("ok"): status = "died"
    return {"idx": idx, "units": units, "rc": rc, "status": status, "seconds": secs, "console": cpath, "data": data}


def load_records(paths):
    recs = {}
    for p in paths:
        d = json.load(open(p))
        for r in d["records"]: recs[r["id"]] = r["status"]
    return recs


def compare(new, ref, label_new="this run", label_ref="reference"):
    only_new = sorted(set(new) - set(ref)); only_ref = sorted(set(ref) - set(new))
    diff = sorted(i for i in set(new) & set(ref) if new[i] != ref[i])
    print(f"Comparison ({label_new}: {len(new)} tests, {label_ref}: {len(ref)} tests): same test ids = {len(set(new) & set(ref)) - len(diff)}, different status = {len(diff)}, only in {label_new} = {len(only_new)}, only in {label_ref} = {len(only_ref)}")
    for i in diff: print(f"  STATUS  {i}: {label_ref}={ref[i]} {label_new}={new[i]}")
    for i in only_new: print(f"  ONLY {label_new}: {i} ({new[i]})")
    for i in only_ref: print(f"  ONLY {label_ref}: {i} ({ref[i]})")
    return not (diff or only_new or only_ref)


def main():
    ap = argparse.ArgumentParser(description="Parallel runner of the unit suites (see the module docstring).")
    ap.add_argument("units", nargs="*", help="test modules (tests.test_x), default: every tests/test_*.py")
    ap.add_argument("-j", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--lots", type=int, default=0)
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--durations", type=int, default=30)
    ap.add_argument("--durable", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--ref", nargs="+")
    ap.add_argument("--compare", nargs="+")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--write-weights", action="store_true")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args()

    if a.compare:
        if not a.ref: print("--compare needs --ref", file=sys.stderr); return 2
        return 0 if compare(load_records(a.compare), load_records(a.ref), "new", "reference") else 2
    if a.j < 1: print("-j must be >= 1", file=sys.stderr); return 2
    if a.json and (not os.path.isabs(a.json) or _inside(a.json, ROOT)): print("--json must be an absolute path outside the repository", file=sys.stderr); return 2
    units = a.units or all_modules()
    known = set(all_modules())
    bad = [u for u in units if module_of(u) not in known]
    if bad: print("unknown test module(s): " + ", ".join(bad), file=sys.stderr); return 2
    table = weight_table()
    lots = make_lots(units, a.lots or 8 * a.j, table)
    if a.list:
        for i, (w, us) in enumerate(lots, 1): print(f"batch {i}: weight {w:.0f} s: {' '.join(us)}")
        return 0

    outdir = tempfile.mkdtemp(prefix="rc25-par-")            # console + records of the batches; removed at the end
    if _inside(outdir, ROOT): shutil.rmtree(outdir, ignore_errors=True); print("TMPDIR is inside the repository; set TMPDIR elsewhere", file=sys.stderr); return 2
    t0 = time.perf_counter(); ru0 = resource.getrusage(resource.RUSAGE_CHILDREN); lock = threading.Lock(); results = []
    print(f"run_tests_parallel: {len(units)} module(s) in {len(lots)} batch(es), {min(a.j, len(lots))} process(es) at a time" + (" [durable: fsync kept]" if a.durable else " [RC25_FAST=1: no fsync on the throw-away databases]"), flush=True)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(a.j, len(lots))) as pool:
            futs = [pool.submit(run_lot, i, us, a.python, outdir, not a.durable) for i, (w, us) in enumerate(lots, 1)]
            for f in concurrent.futures.as_completed(futs):
                r = f.result(); results.append(r)
                ran = r["data"]["ran"] if r["data"] else "?"
                with lock: print(f"  batch {r['idx']:2d}: {len(r['units']):2d} modules, {ran} tests, {r['seconds']:.0f} s, {r['status'].upper() if r['status'] != 'ok' or r['rc'] else 'OK'}", flush=True)
        wall = time.perf_counter() - t0; ru1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = (ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)
        results.sort(key=lambda r: r["idx"])
        records = []; problems = []
        for r in results:
            if r["data"]: records += r["data"]["records"]
            if r["status"] != "ok" or r["rc"] != 0 or not (r["data"] and r["data"]["ok"]) or a.v:
                if r["status"] != "ok" or r["rc"] != 0 or not (r["data"] and r["data"]["ok"]): problems.append(r)
                print(f"\n======== console of batch {r['idx']} ({' '.join(r['units'])}) ========")
                sys.stdout.write(open(r["console"], errors="replace").read())
        cnt = collections.Counter(x["status"] for x in records)
        ran = len(records) - cnt.get("SUBFAIL", 0)
        bad_n = cnt.get("FAIL", 0) + cnt.get("ERROR", 0) + cnt.get("SUBFAIL", 0) + cnt.get("unexpected success", 0)
        extra = [f"{k}={v}" for k, v in (("failures", cnt.get("FAIL", 0)), ("errors", cnt.get("ERROR", 0)), ("subtest failures", cnt.get("SUBFAIL", 0)), ("skipped", cnt.get("skipped", 0)),
                                         ("expected failures", cnt.get("expected failure", 0)), ("unexpected successes", cnt.get("unexpected success", 0))) if v]
        if a.durations:
            print(f"\nSlowest {a.durations} tests (seconds, measured inside their process):")
            for x in sorted(records, key=lambda x: -x["seconds"])[:a.durations]: print(f"  {x['seconds']:7.2f}  {x['id']}")
        ok = not problems and bad_n == 0
        print("\n" + "-" * 70); print(f"Ran {ran} tests in {wall:.1f}s (wall clock; CPU of the processes: {cpu:.1f}s)")
        print(("OK" if ok else "FAILED") + (f" ({', '.join(extra)})" if extra else ""))
        if problems: print("batches in error: " + ", ".join(f"{r['idx']} ({r['status']}, rc={r['rc']})" for r in problems))
        if a.json:
            with open(a.json, "w") as f: json.dump({"records": records, "ran": ran, "ok": ok, "wall": wall, "cpu": cpu, "batches": [{"units": r["units"], "seconds": r["seconds"]} for r in results]}, f)
        if a.write_weights:
            per = collections.defaultdict(float)
            for x in records: per[module_of(x["id"])] += x["seconds"]
            with open(WEIGHTS, "w") as f: json.dump({k: round(v, 1) for k, v in sorted(per.items())}, f, indent=0, sort_keys=True)
            print("weights written: " + WEIGHTS)
        if a.ref and not compare({x["id"]: x["status"] for x in records}, load_records(a.ref), "this run", "reference"): return 2
        return 0 if ok else 1
    finally:
        shutil.rmtree(outdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
