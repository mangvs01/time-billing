"""BSAV1: pop-up at login, at most once per calendar month, advising to download the JSON backup. Replaces the permanent « Sauvegarde conseillée » line of the
dashboard « À traiter » list. Pure helpers (no database, no Flask): app.py reads the settings and the audit, asks `backup_stale` and `reminder_due`."""
from datetime import datetime, timedelta, timezone

REMINDER_KEY = "sauvegarde_rappel_dernier"      # settings key: UTC time (ISO) of the last time the pop-up was shown
STALE_DAYS = 30


def _naive_utc(v):
    try:
        d = datetime.fromisoformat(str(v).strip().replace(" ", "T", 1))
    except (TypeError, ValueError):
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo is not None else d


def backup_stale(last_backup, now, days=STALE_DAYS):
    """True when no JSON backup was ever downloaded, when the stored date cannot be read, or when it is `days` days old or more. `now`: naive UTC datetime."""
    last = _naive_utc(last_backup)
    return last is None or now - last >= timedelta(days=days)


def reminder_due(last_iso, now):
    """True when the pop-up has not been shown yet during the current calendar month (UTC) of `now`, or when the stored value cannot be read.
    A value from another month, including a future one (clock set back), counts as due: the reminder cannot stay silent for months."""
    last = _naive_utc(last_iso)
    return last is None or (last.year, last.month) != (now.year, now.month)
