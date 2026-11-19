#!/usr/bin/env python3
"""rc37 (P2) — semis IDEMPOTENT des adresses de facturation du client EGG dans la table `billing_addresses` (liste déroulante de l'éditeur de brouillon).

Données : app/donnees_adresses/egg.json (versionné) = les 4 adresses du commentaire du propriétaire sur le PDF brouillon annoté (EGG FR, EGG BE, EGG CH, EGG MEA).
Le client est identifié comme le fait l'application (décision D4, address_service.client_key) : par l'identité juridique de ses mandats (--client-legal-id = valeur de
projects.client_legal_id des mandats EGG) et, FAUTE d'identité juridique sur le mandat, par le nom court du client (--client-name EGG = projects.client). Le PDF brouillon annoté
du propriétaire n'imprime aucune ligne « N° d'identification » pour le mandat « GEM STC 2026 - 2600140AE » : son identité juridique est probablement vide, donc --client-name.
Les valeurs de production ne sont connues que du superviseur (elles ne sont pas dans ce dépôt) ; le script vérifie que des mandats portent bien la clé et les liste.

SIMULATION PAR DÉFAUT : la base n'est ouverte qu'en lecture seule, le script affiche ce qu'il ferait. Pour écrire (après une sauvegarde de la base, procedure/20-backup.sh) :
  --appliquer --confirmer SEMER-ADRESSES-EGG
Rejouable sans effet : une adresse déjà présente et identique n'est pas touchée ; une adresse présente mais DIFFÉRENTE n'est jamais écrasée sans --mettre-a-jour
(les brouillons qui l'ont copiée gardent leur instantané dans tous les cas). Rien d'autre n'est modifié ; une ligne d'audit est ajoutée seulement si quelque chose a été écrit.

Usage (hors conteneur : python3 -I scripts/seed_adresses_egg.py ... ; en conteneur : -e PYTHONPATH=/app, scripts/ monté en lecture seule) :
  python3 -I scripts/seed_adresses_egg.py --base /data/timebilling.db --client-legal-id <identité juridique EGG>      (ou : --client-name EGG, valeur par défaut depuis rc38)
  python3 -I scripts/seed_adresses_egg.py --base /data/timebilling.db --client-legal-id <...> --appliquer --confirmer SEMER-ADRESSES-EGG
"""
import argparse, json, os, sqlite3, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from app import address_service, billing_rules as rules      # noqa: E402  (no application start-up: no secret read, no network)

CONFIRM = "SEMER-ADRESSES-EGG"
DATA = os.path.join(os.path.dirname(HERE), "app", "donnees_adresses", "egg.json")


def load(path=DATA):
    data = json.load(open(path, encoding="utf-8"))
    out = []
    for a in data["addresses"]:
        contact, address = address_service.from_lines(a["lines"])
        label, contact, address = address_service.validate(a["label"], contact, address)
        out.append({"label": label, "contact": contact, "address": address, "sort_order": int(a.get("sort_order", 0))})
    labels = [a["label"] for a in out]
    if len(set(labels)) != len(labels): raise ValueError("libellés en double dans le fichier de données")
    return out


def plan(conn, key, wanted):
    """[(action, wanted address, existing row or None)] with action in insert | same | differs."""
    have = {r["label"]: r for r in conn.execute("SELECT * FROM billing_addresses WHERE client_key=?", (key,))}
    out = []
    for a in wanted:
        r = have.get(a["label"])
        if r is None: out.append(("insert", a, None))
        elif (r["contact"], r["address"]) == (a["contact"], a["address"]): out.append(("same", a, r))
        else: out.append(("differs", a, r))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="fichier SQLite de l'application")
    who = ap.add_mutually_exclusive_group()      # rc38 (owner decision Q4, 26.10): without either option the mandates are found by their short client name « EGG »
    who.add_argument("--client-legal-id", help="valeur de projects.client_legal_id des mandats EGG")
    who.add_argument("--client-name", help="projects.client des mandats EGG qui n'ont PAS d'identité juridique (clé de repli de l'application)")
    ap.add_argument("--donnees", default=DATA, help="fichier JSON des adresses (défaut : celui du dépôt)")
    ap.add_argument("--appliquer", action="store_true"); ap.add_argument("--confirmer", default="")
    ap.add_argument("--mettre-a-jour", action="store_true", help="remplacer le texte d'une adresse déjà présente mais différente")
    a = ap.parse_args(argv)
    if a.client_legal_id is None and a.client_name is None: a.client_name = "EGG"
    key = rules.legal_key(a.client_legal_id) if a.client_legal_id is not None else address_service.client_key({"client_legal_id": "", "client": a.client_name})
    if not key: sys.exit("identité juridique ou nom de client vide ou illisible : rien n'est fait")
    if not os.path.isfile(a.base): sys.exit(f"base introuvable : {a.base}")
    write = a.appliquer
    if write and a.confirmer != CONFIRM: sys.exit(f"écriture refusée : ajouter --confirmer {CONFIRM} (après sauvegarde de la base)")
    wanted = load(a.donnees)
    conn = sqlite3.connect(f"file:{a.base}?mode={'rw' if write else 'ro'}", uri=True, timeout=15, isolation_level=None); conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "projects" not in tables: sys.exit("base inattendue : table projects absente")
        mandates = [r["name"] for r in conn.execute("SELECT name,client,client_legal_id FROM projects") if address_service.client_key(r) == key]
        if not mandates: sys.exit(f"aucun mandat ne correspond à {a.client_legal_id or a.client_name!r} (clé {key}) : le nom court du client des mandats EGG doit être « EGG » et leur identité juridique vide (sinon utiliser --client-legal-id) ; rien n'est fait")
        print(f"Client : clé {key} — {len(mandates)} mandat(s) : {', '.join(mandates[:6])}{' …' if len(mandates) > 6 else ''}")
        exists = "billing_addresses" in tables
        if not exists and write: conn.execute("BEGIN IMMEDIATE"); conn.execute(address_service.DDL)
        rows = plan(conn, key, wanted) if exists else [("insert", w, None) for w in wanted]
        for action, w, r in rows:
            print(f"  {w['label']:<8} {action:<8} {w['contact']} / {w['address'].splitlines()[0]}" + ("   (texte DIFFÉRENT en base : --mettre-a-jour pour l'écraser)" if action == "differs" and not a.mettre_a_jour else ""))
        todo = [(act, w, r) for act, w, r in rows if act == "insert" or (act == "differs" and a.mettre_a_jour)]
        if not write:
            print(f"SIMULATION : {len(todo)} écriture(s) seraient faites. Rien n'a été modifié."); return 0
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not conn.in_transaction: conn.execute("BEGIN IMMEDIATE")
        for act, w, r in todo:
            if act == "insert":
                conn.execute("INSERT INTO billing_addresses(client_key,label,contact,address,active,sort_order,created_at) VALUES(?,?,?,?,1,?,?)", (key, w["label"], w["contact"], w["address"], w["sort_order"], now))
            else:
                conn.execute("UPDATE billing_addresses SET contact=?,address=?,sort_order=?,updated_at=? WHERE id=?", (w["contact"], w["address"], w["sort_order"], now, r["id"]))
        if todo: conn.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("billing_addresses_seeded", f"client_key={key};inserted={sum(1 for t in todo if t[0] == 'insert')};updated={sum(1 for t in todo if t[0] == 'differs')}"))
        conn.execute("COMMIT")
        print(f"APPLIQUÉ : {len(todo)} écriture(s). Rejouable : un second passage ne change rien."); return 0
    except Exception:
        if conn.in_transaction: conn.execute("ROLLBACK")
        raise
    finally: conn.close()


if __name__ == "__main__":
    sys.exit(main())
