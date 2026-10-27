"""RC8 security: startup secret checks, session-cookie policy, login throttling, same-origin check, response headers.

Secrets are read from the environment only (a compose `.env` file, mode 600) and are never logged, printed or
echoed in an error message: every message below names the variable, never its value.

Environment:
  APP_USER            login name (default admin)
  APP_PASSWORD_HASH   preferred: werkzeug hash (scrypt:… or pbkdf2:…) of the password, so the clear password is
                      stored nowhere on the server
  APP_PASSWORD        legacy clear password, accepted only when no hash is given (12 characters minimum)
  SECRET_KEY          session signing key: random, 32 characters minimum, different from the password
  COOKIE_SECURE       1 (default): session cookie sent over HTTPS only; 0 only for plain-HTTP local access
  SESSION_HOURS       session lifetime in hours (default 8)
  TRUST_PROXY         1 behind the local reverse proxy (client IP / scheme / host from X-Forwarded-*)
"""
import hmac, ipaddress
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash

WEAK = {"", "replace-with-long-random-secret", "change-me-now", "changeme", "change-me", "secret", "password", "admin"}
MIN_SECRET, MIN_PASSWORD = 32, 12
MAX_FAILURES, WINDOW_MIN = 5, 15


class ConfigError(RuntimeError):
    pass


def load(env):
    """Validated security settings; raises ConfigError (variable names only, never values)."""
    user = (env.get("APP_USER") or "admin").strip()
    pw_hash = (env.get("APP_PASSWORD_HASH") or "").strip()
    pw = env.get("APP_PASSWORD") or ""
    key = env.get("SECRET_KEY") or ""
    problems = []
    if pw_hash:
        if not pw_hash.startswith(("scrypt:", "pbkdf2:")): problems.append("APP_PASSWORD_HASH n'est pas un hachage werkzeug (scrypt: ou pbkdf2:)")
    elif not pw:
        problems.append("APP_PASSWORD_HASH (recommandé) ou APP_PASSWORD absent")
    elif pw.lower() in WEAK or len(pw) < MIN_PASSWORD:
        problems.append(f"APP_PASSWORD trop faible ({MIN_PASSWORD} caractères minimum, valeur par défaut interdite)")
    if key.lower() in WEAK or len(key) < MIN_SECRET:
        problems.append(f"SECRET_KEY absent, par défaut ou trop court ({MIN_SECRET} caractères aléatoires minimum)")
    if key and pw and hmac.compare_digest(key.encode(), pw.encode()):
        problems.append("SECRET_KEY identique au mot de passe")
    if problems: raise ConfigError("configuration de sécurité refusée : " + " ; ".join(problems))
    return {"user": user, "pw_hash": pw_hash or None, "pw": None if pw_hash else pw, "key": key,
            "cookie_secure": (env.get("COOKIE_SECURE") or "1").strip() != "0",
            "session_hours": max(1, int(env.get("SESSION_HOURS") or 8)), "trust_proxy": (env.get("TRUST_PROXY") or "0").strip() == "1"}


def cookie_config(cfg):
    return {"SESSION_COOKIE_NAME": "tb_session", "SESSION_COOKIE_HTTPONLY": True, "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": cfg["cookie_secure"], "PERMANENT_SESSION_LIFETIME": timedelta(hours=cfg["session_hours"])}


def credentials_ok(cfg, user, password):
    user_ok = hmac.compare_digest((user or "").encode(), cfg["user"].encode())
    if cfg["pw_hash"]: pw_ok = check_password_hash(cfg["pw_hash"], password or "")
    else: pw_ok = hmac.compare_digest((password or "").encode(), cfg["pw"].encode())
    return user_ok and pw_ok


# --- login throttling (shared by the gunicorn workers through SQLite) ------------------------------
SCHEMA = """CREATE TABLE IF NOT EXISTS login_failures(id INTEGER PRIMARY KEY, ip TEXT NOT NULL, at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_login_failures ON login_failures(ip, at);"""


def client_key(ip):
    """Throttling key: an IPv6 address counts as its /64 network (one customer holds a whole /64), IPv4 as is."""
    try: a = ipaddress.ip_address((ip or "").strip())
    except ValueError: return ip or "?"
    if a.version == 6:
        if a.ipv4_mapped: return str(a.ipv4_mapped)
        return str(ipaddress.ip_network(f"{a}/64", strict=False))
    return str(a)


def _since(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).replace(tzinfo=None).isoformat(timespec="seconds")


def locked(c, ip):
    ip = client_key(ip)
    return c.execute("SELECT COUNT(*) FROM login_failures WHERE ip=? AND at>=?", (ip, _since(WINDOW_MIN))).fetchone()[0] >= MAX_FAILURES


def record_failure(c, ip):
    ip = client_key(ip)
    c.execute("DELETE FROM login_failures WHERE at<?", (_since(24 * 60),))
    c.execute("INSERT INTO login_failures(ip,at) VALUES(?,?)", (ip, datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")))


def throttle_logged(c, ip, tail=2000):
    """True when a refused login of this client (same key as the lock) is already in the audit for the current window.
    A bot hammering a locked login otherwise added one audit row (and one write transaction) per request: ~100/s, 9 M rows a day.
    Only the most recent `tail` audit rows are read (bounded cost); beyond that many interleaved clients, a row may be written again."""
    key = client_key(ip)
    rows = c.execute("SELECT detail FROM (SELECT event, detail, created_at FROM audit ORDER BY id DESC LIMIT ?) "
                     "WHERE event='login_throttled' AND created_at>=datetime('now',?)", (tail, f"-{WINDOW_MIN} minutes")).fetchall()
    return any(client_key(r[0][3:] if r[0].startswith("ip=") else r[0]) == key for r in rows)


def clear_failures(c, ip):
    ip = client_key(ip)
    c.execute("DELETE FROM login_failures WHERE ip=?", (ip,))


# --- request / response hardening -----------------------------------------------------------------
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def cross_site(request):
    """True for a state-changing request coming from another site (defence in depth on top of SameSite=Lax)."""
    if request.method not in UNSAFE: return False
    if request.headers.get("Sec-Fetch-Site") == "cross-site": return True
    origin = request.headers.get("Origin")
    if origin is None: return False                 # non-browser client or same-origin navigation without Origin: SameSite=Lax still applies
    return origin == "null" or origin.rstrip("/") != request.host_url.rstrip("/")


HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


def csp(nonce):
    """RC11: no inline event handler remains ; inline <script> blocks carry the per-request nonce, so injected script cannot run."""
    return (f"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'nonce-{nonce}'; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'")


def harden(response, authenticated, secure=False, nonce=""):
    for k, v in HEADERS.items(): response.headers.setdefault(k, v)
    response.headers.setdefault("Content-Security-Policy", csp(nonce))
    if secure: response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")   # only over HTTPS (behind the proxy: X-Forwarded-Proto)
    if authenticated: response.headers["Cache-Control"] = "no-store"   # invoices, PDFs, backups: never cached
    return response
