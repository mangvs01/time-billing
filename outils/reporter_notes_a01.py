"""A-01 (Decision Center billing-a01-l01 … l15, réponse OUI du 2026-10-07) : reporter la note de la colonne I (« Colonne1 ») du classeur dans la
description des 15 saisies importées avec une description vide.

Chaque correction passe par la route de correction de l'application (/entry/<id>/edit) : même validation, même trace que dans l'interface
(historique des corrections avec avant/après, motif « note colonne I du classeur (Decision Center billing-a01-lNN) », journal d'audit).
Heures, date, horaires et mandat sont renvoyés inchangés : seule la description change. Rien n'est deviné :
  - chaque note est relue dans le classeur (empreinte vérifiée) et comparée à la fiche ; la saisie doit porter la provenance de la même ligne
    (source_ref « FEUILLE!ligne ») et une description vide ; une saisie déjà corrigée avec la note est sautée (idempotent) ;
  - le moindre écart (note, provenance, description non vide, saisie facturée par une facture émise) arrête TOUT avant la première écriture.

Usage (conteneur jetable SANS réseau, image de l'application, -w /app -e PYTHONPATH=/app, -v <dépôt>/outils:/app/outils:ro) :
  python outils/reporter_notes_a01.py --classeur "/src/Time sheet CP.xlsx" --base /data/timebilling.db --sortie /out            (simulation sur copie)
  python outils/reporter_notes_a01.py ... --appliquer --confirmer REPORTER-15-NOTES-A01      (staging seulement, service arrêté, après sauvegarde)
"""
import argparse, csv, json, os, shutil, sqlite3, sys, tempfile

WORKBOOK_SHA256 = "c93c610cdffe66d150fbb05d64513054d297f6170158effef99eb461eddac438"
CONFIRM = "REPORTER-15-NOTES-A01"
ACTOR = "outil-a01"
# (fiche, feuille, ligne, note attendue, saisie) : titres des fiches billing-a01-l01 … l15
A01 = [
    ("billing-a01-l01", "MAR 26", 148, "debrief", 1069), ("billing-a01-l02", "APR 26", 57, "cloture", 1537),
    ("billing-a01-l03", "APR 26", 64, "Debrief Anna", 2146), ("billing-a01-l04", "MAY 26", 56, "TL brief", 1214),
    ("billing-a01-l05", "JUL 26", 51, "DM", 1599),
    ("billing-a01-l06", "SEPT 26", 88, "session management", 2056), ("billing-a01-l07", "SEPT 26", 90, "session management", 2057),
    ("billing-a01-l08", "SEPT 26", 96, "session management", 2060), ("billing-a01-l09", "SEPT 26", 99, "session management", 2061),
    ("billing-a01-l10", "SEPT 26", 100, "session management", 2062), ("billing-a01-l11", "SEPT 26", 101, "session management", 2063),
    ("billing-a01-l12", "SEPT 26", 122, "session management", 2076), ("billing-a01-l13", "SEPT 26", 125, "session management", 2078),
    ("billing-a01-l14", "SEPT 26", 126, "session management", 2079), ("billing-a01-l15", "SEPT 26", 127, "session management", 2080),
]
NOTE_COLUMN = "I"


def reason(card): return f"note colonne I du classeur (Decision Center {card})"


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def read_notes(path):
    """Relit les 15 cellules de la colonne I ; arrêt si l'une diffère de la fiche (espaces de bord ignorés, rien d'autre)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    for card, sheet, row, note, _ in A01:
        raw = wb[sheet][f"{NOTE_COLUMN}{row}"].value
        if not isinstance(raw, str) or raw.strip() != note:
            raise SystemExit(f"ARRÊT : {sheet}!{NOTE_COLUMN}{row} contient {raw!r}, attendu {note!r} ({card}) : rien n'est modifié")


def plan(c, post_billing):
    """Vérifie les 15 saisies avant toute écriture. Retourne [(fiche, saisie, note, à_faire)] ou arrête."""
    out = []
    for card, sheet, row, note, eid in A01:
        e = c.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
        if not e: raise SystemExit(f"ARRÊT : saisie {eid} absente ({card}) : rien n'est modifié")
        if e["source_ref"] != f"{sheet}!{row}":
            raise SystemExit(f"ARRÊT : saisie {eid} provient de {e['source_ref']!r}, attendu {sheet}!{row} ({card}) : rien n'est modifié")
        if e["description"] == note: out.append((card, eid, note, False)); continue
        if (e["description"] or "") != "":
            raise SystemExit(f"ARRÊT : saisie {eid} a déjà la description {e['description']!r} ({card}) : rien n'est modifié (décision utilisateur requise)")
        billed = [x["number"] for x in post_billing.entry_invoices(c, eid) if x["role"] == "billed"]
        if billed:
            raise SystemExit(f"ARRÊT : saisie {eid} facturée par {', '.join(billed)} ({card}) : la fiche ne prévoit pas ce cas ; rien n'est modifié")
        out.append((card, eid, note, True))
    return out


def snapshot(c):
    """Tout ce qui ne doit PAS changer : chiffres des saisies, factures, positions."""
    return {"entries": [tuple(r) for r in c.execute("SELECT id,work_date,project_id,start_time,end_time,hours,source,source_ref FROM entries ORDER BY id")],
            "invoices": [tuple(r) for r in c.execute("SELECT * FROM invoices ORDER BY id")],
            "historical": [tuple(r) for r in c.execute("SELECT * FROM historical_invoices ORDER BY id")]}


def apply(m, todo):
    """Envoie les corrections par la route de l'application (client de test, session ouverte puis révoquée)."""
    cl = m.APP.test_client()
    r = cl.post("/login", data={"username": m.SEC["user"], "password": os.environ["APP_PASSWORD"]})
    if r.status_code != 302: raise SystemExit("ARRÊT : connexion de l'outil refusée : rien n'est modifié")
    done = []
    try:
        for card, eid, note, needed in todo:
            if not needed: continue
            c = m.db()
            try: e = c.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
            finally: c.close()
            form = {"rev": m.entry_rev(e), "work_date": e["work_date"], "project_id": str(e["project_id"]), "description": note, "reason": reason(card),
                    "billed_ids": "", "return_to": "/entries"}
            if e["start_time"] and e["end_time"]: form.update(entry_mode="clock", start_time=e["start_time"], end_time=e["end_time"])
            else: form.update(entry_mode="duration", manual_hours=repr(e["hours"]))
            with cl.session_transaction() as s: s.pop("_flashes", None)
            r = cl.post(f"/entry/{eid}/edit", data=form)
            with cl.session_transaction() as s: msgs = [x[1] for x in s.get("_flashes", [])]
            c = m.db()
            try: after = c.execute("SELECT description,hours,work_date,start_time,end_time,project_id FROM entries WHERE id=?", (eid,)).fetchone()
            finally: c.close()
            if r.status_code != 302 or after["description"] != note or tuple(after)[1:] != (e["hours"], e["work_date"], e["start_time"], e["end_time"], e["project_id"]):
                raise SystemExit(f"ARRÊT après {len(done)} correction(s) : saisie {eid} ({card}) non corrigée comme prévu : {msgs} "
                                 "(les corrections faites restent tracées ; relancer reprend là où l'outil s'est arrêté)")
            done.append(eid)
    finally:
        cl.post("/logout")
    return done


def load_app(db_path):
    os.environ["DB_PATH"] = db_path; os.environ["APP_USER"] = ACTOR
    os.environ.pop("APP_PASSWORD_HASH", None); os.environ["APP_PASSWORD"] = os.urandom(16).hex()
    os.environ.setdefault("SECRET_KEY", os.urandom(32).hex()); os.environ["COOKIE_SECURE"] = "0"
    import app.app as m
    from app import post_billing
    return m, post_billing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classeur", required=True); ap.add_argument("--base", required=True); ap.add_argument("--sortie", required=True)
    ap.add_argument("--appliquer", action="store_true"); ap.add_argument("--confirmer", default="")
    a = ap.parse_args()
    sha = sha256(a.classeur)
    if sha != WORKBOOK_SHA256: raise SystemExit(f"ARRÊT : classeur inattendu (sha256 {sha[:12]}…, attendu {WORKBOOK_SHA256[:12]}…)")
    read_notes(a.classeur)
    os.makedirs(a.sortie, exist_ok=True)
    if a.appliquer and a.confirmer != CONFIRM: raise SystemExit(f"ARRÊT : --appliquer exige --confirmer {CONFIRM}")

    tmp = None
    if a.appliquer: target = a.base
    else:
        tmp = tempfile.mkdtemp(prefix="simu-a01-"); target = os.path.join(tmp, "copie.db")
        src = sqlite3.connect(f"file:{a.base}?mode=ro", uri=True); dst = sqlite3.connect(target); src.backup(dst); dst.close(); src.close()
    try:
        m, post_billing = load_app(target)      # simulation : migre la COPIE ; application : la base est déjà au schéma rc19 (déployé)
        c = m.db()
        try: todo = plan(c, post_billing); before = snapshot(c)
        finally: c.close()
        done = apply(m, todo)
        c = m.db()
        try:
            unchanged = snapshot(c) == before
            rows = [(card, eid, note, c.execute("SELECT description FROM entries WHERE id=?", (eid,)).fetchone()[0],
                     c.execute("SELECT COUNT(*) FROM entry_changes WHERE entry_id=? AND action='update' AND reason=?", (eid, reason(card))).fetchone()[0])
                    for card, eid, note, _ in todo]
        finally: c.close()
        if not unchanged: raise SystemExit("ARRÊT : un chiffre (saisie, facture, registre) a changé : à examiner (base " + ("COPIE" if tmp else "RÉELLE") + ")")
    finally:
        if tmp: shutil.rmtree(tmp, ignore_errors=True)

    with open(os.path.join(a.sortie, "a01-lignes.csv"), "w", newline="") as f:
        w = csv.writer(f, delimiter=";"); w.writerow(["fiche", "saisie", "note", "description après", "corrections tracées"]); w.writerows(rows)
    summary = {"mode": "APPLICATION" if a.appliquer else "SIMULATION (copie temporaire supprimée ; base lue seulement)", "classeur_sha256": sha,
               "corrigees": done, "deja_faites": [eid for _, eid, _, need in todo if not need], "chiffres_inchanges": unchanged,
               "toutes_conformes": all(r[2] == r[3] and r[4] >= 1 for r in rows)}
    json.dump(summary, open(os.path.join(a.sortie, "a01-resume.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if not summary["toutes_conformes"]: sys.exit(1)


if __name__ == "__main__":
    main()
