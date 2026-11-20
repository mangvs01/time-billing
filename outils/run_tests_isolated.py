"""Unit-test runner for a disposable checkout (no Docker, no network, no real data).

Usage:  /root/venvs/rc25-test-venv/bin/python -I outils/run_tests_isolated.py [-v] tests.test_invoice_lines [tests.test_x ...]      (the repository root is found from this file)

The suites expect a COPY of the staging database (BASE_DB) and a /data directory. Here both are replaced by a synthetic, empty database created by
app.init() and a private scratch directory created OUTSIDE the repository (system temporary directory, mode 0700, removed on exit).
RC25_WORK may name another scratch directory: it must be absolute, outside the repository, and either new / empty or already marked by this runner.
RC25_FAST=1 (opt-in; set by outils/run_tests_parallel.py): every SQLite connection of the process runs PRAGMA synchronous=OFF, i.e. no fsync at COMMIT. Nothing else changes (same locks, same
transactions, same SQL, same results); only the durability against a power cut of the throw-away test databases is given up. See docs/TESTS-DUREE.md.
RC25_RESULT_JSON=/absolute/path.json (opt-in; set by outils/run_tests_parallel.py): after the run, one record per test (id, status, seconds) is written there (outside the repository);
the console output and the exit status are those of unittest, unchanged.
Guards: DB_PATH / BASE_DB (if set in the environment) must lie inside the scratch directory, else the run is refused; every sqlite3.connect() of the
process is refused outside the scratch directory (":memory:" aside); temporary files go to the scratch directory; no .pyc is written.
No secret is read from the environment (the application key and password below are synthetic) and none is printed. Synthetic data only.
"""
import atexit, os, shutil, sqlite3, sys, tempfile, unittest
from urllib.parse import unquote

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the checkout this file belongs to (outils/ is at its root)
MARK = ".rc25-synthetic-scratch"


def _inside(path, base):
    path, base = os.path.realpath(path), os.path.realpath(base)
    return path == base or path.startswith(base + os.sep)


def _refuse(msg):
    sys.stderr.write("run_tests_isolated: refused: " + msg + "\n")
    sys.exit(2)


def _scratch():
    want = os.environ.get("RC25_WORK")
    if not want:
        w = os.path.realpath(tempfile.mkdtemp(prefix="rc25-scratch-"))   # 0700, outside the repository unless TMPDIR points into it (checked below)
        if _inside(w, ROOT):
            shutil.rmtree(w, ignore_errors=True); _refuse("the system temporary directory is inside the repository; set TMPDIR or RC25_WORK elsewhere")
        open(os.path.join(w, MARK), "w").close()
        atexit.register(shutil.rmtree, w, True)
        return w
    if not os.path.isabs(want): _refuse("RC25_WORK must be an absolute path")
    w = os.path.realpath(want)
    if _inside(w, ROOT) or _inside(ROOT, w): _refuse("RC25_WORK must be outside the repository")
    if w == os.sep or _inside(w, "/data") or os.path.dirname(w) == os.sep: _refuse("RC25_WORK must not be a root-level or data directory")
    if os.path.lexists(w):
        if not os.path.isdir(w) or os.path.islink(want): _refuse("RC25_WORK must be a real directory")
        if os.listdir(w) and not os.path.exists(os.path.join(w, MARK)): _refuse("RC25_WORK exists, is not empty and was not created by this runner")
    else:
        os.makedirs(w, mode=0o700)
    open(os.path.join(w, MARK), "w").close()
    return w


WORK = _scratch()
for _k in ("DB_PATH", "BASE_DB"):
    if os.environ.get(_k) and not _inside(os.environ[_k], WORK): _refuse(_k + " points outside the synthetic scratch directory")
os.environ.update({"SECRET_KEY": "0" * 64, "COOKIE_SECURE": "0", "INVOICE_CHECK_WORDS": "", "APP_PASSWORD": "synthetic-test-password",
                   "DB_PATH": os.path.join(WORK, "boot.db"), "BASE_DB": os.path.join(WORK, "base.db")})
for _k in ("APP_USER", "APP_PASSWORD_HASH", "TRUST_PROXY", "SESSION_HOURS", "EXTERNAL_INVOICE_NUMBERS", "LICENSED_FONT_DIR"): os.environ.pop(_k, None)

_connect, _mkdtemp = sqlite3.connect, tempfile.mkdtemp
FAST = os.environ.get("RC25_FAST") == "1"


def _guarded_connect(database, *a, **k):
    p = os.fspath(database) if not isinstance(database, (bytes, str)) else database
    if isinstance(p, bytes): p = os.fsdecode(p)
    # SQLite accepts URI filenames such as file:/tmp/.../backup.db?mode=ro.
    # Normalize only the filesystem component before applying the same strict scratch guard.
    checked = p
    if isinstance(checked, str) and checked.startswith("file:"):
        checked = unquote(checked[5:].split("?", 1)[0])
    if p != ":memory:" and not _inside(checked, WORK): raise sqlite3.OperationalError("refused by run_tests_isolated: database outside the synthetic scratch directory: " + p)
    conn = _connect(database, *a, **k)
    if FAST and p != ":memory:":
        try: conn.execute("PRAGMA synchronous=OFF")      # no fsync on the throw-away databases (never changes what a test sees)
        except sqlite3.Error: pass
    return conn


def _scratch_mkdtemp(*a, **k):
    k = dict(k); k["dir"] = WORK     # the suites ask for dir='/data'
    return _mkdtemp(*a, **k)


sqlite3.connect = _guarded_connect
tempfile.mkdtemp = _scratch_mkdtemp
tempfile.tempdir = WORK
sys.path.insert(0, ROOT)
import app.app as m
if not os.path.exists(os.environ["BASE_DB"]):
    m.DB = os.environ["BASE_DB"]; m.init()
m.DB = os.environ["DB_PATH"]
RESULT_JSON = os.environ.get("RC25_RESULT_JSON")
if not RESULT_JSON:
    unittest.main(module=None, argv=["run_tests_isolated"] + sys.argv[1:])
else:
    if not os.path.isabs(RESULT_JSON) or _inside(RESULT_JSON, ROOT): _refuse("RC25_RESULT_JSON must be an absolute path outside the repository")
    import json, time

    class _RecordingResult(unittest.TextTestResult):
        """Same console behaviour as TextTestResult; additionally remembers (id, status, seconds) of every test and sub-test."""
        records = []
        def startTest(self, test): self._t0 = time.perf_counter(); super().startTest(test)
        def _add(self, test, status): type(self).records.append({"id": test.id(), "status": status, "seconds": round(time.perf_counter() - getattr(self, "_t0", time.perf_counter()), 4)})
        def addSuccess(self, test): super().addSuccess(test); self._add(test, "ok")
        def addFailure(self, test, err): super().addFailure(test, err); self._add(test, "FAIL")
        def addError(self, test, err): super().addError(test, err); self._add(test, "ERROR")
        def addSkip(self, test, reason): super().addSkip(test, reason); self._add(test, "skipped")
        def addExpectedFailure(self, test, err): super().addExpectedFailure(test, err); self._add(test, "expected failure")
        def addUnexpectedSuccess(self, test): super().addUnexpectedSuccess(test); self._add(test, "unexpected success")
        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            if err is not None: type(self).records.append({"id": subtest.id(), "status": "SUBFAIL", "seconds": 0.0})

    class _Runner(unittest.TextTestRunner): resultclass = _RecordingResult

    prog = unittest.main(module=None, argv=["run_tests_isolated"] + sys.argv[1:], testRunner=_Runner, exit=False)
    with open(RESULT_JSON, "w") as f: json.dump({"records": _RecordingResult.records, "ran": prog.result.testsRun, "ok": prog.result.wasSuccessful()}, f)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
