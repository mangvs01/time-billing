#!/usr/bin/env python3
"""Empreinte des données métier d'une base Time Billing — contrôles communs aux deux méthodes de la décision G4
(Decision Center billing-g4-donnees-production : promotion de la base du staging OU rejeu des imports en production).

LECTURE SEULE : chaque base est ouverte en « mode=ro » ; rien n'est jamais écrit. Bibliothèque standard seulement : s'exécute sur l'hôte
(python3 -I outils/empreinte_metier.py …) sur une COPIE (sauvegarde 20-backup), jamais sur une base vivante sous /opt.

  vide <base>                 code 0 si aucune table métier ne contient de ligne (la production doit être vide au moment de la bascule,
                              quelle que soit la méthode) ; sinon code 1 et liste des tables non vides.
  empreinte <base>            effectifs, empreinte SHA-256 de chaque table métier et chiffres de contrôle (JSON).
  comparer <base A> <base B>  code 0 si toutes les tables métier sont identiques (mêmes colonnes, mêmes lignes) ; sinon code 1 et, par table,
                              le nombre de lignes présentes seulement dans A / seulement dans B.

Tables métier = celles que procedure/90-rollback.sh compare (même liste). Hors comparaison, effectifs seulement : audit (journal propre à
chaque environnement), web_sessions, login_failures, kept_forms (transitoires), auth_credentials (mot de passe changé dans l'application, BMDP1), sqlite_sequence. Empreinte d'une table : toutes ses
colonnes (triées par nom), lignes triées sur toutes les colonnes — indépendante de l'ordre physique et de l'ordre des colonnes.
"""
import hashlib, json, sqlite3, sys

TABLES_METIER = ("entries", "entry_changes", "projects", "invoices", "credit_notes", "credit_operations", "invoice_variance_decisions",
                 "historical_invoices", "invoice_date_changes", "import_batches", "invoice_snapshots", "credit_note_snapshots", "settings",
                 "credit_note_cancellations", "invoice_annex_entries", "import_batch_rows")
HORS_COMPARAISON = ("audit", "web_sessions", "login_failures", "kept_forms", "auth_credentials", "sqlite_sequence")


def ouvrir(chemin):
    c = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    c.execute("SELECT 1 FROM sqlite_master LIMIT 1")      # fichier illisible / pas une base : erreur ici, pas plus loin
    return c


def tables(c, schema="main"):
    return {r[0] for r in c.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table'")}


def colonnes(c, t, schema="main"):
    return sorted(r[1] for r in c.execute(f"PRAGMA {schema}.table_info([{t}])"))


def qi(cols):
    return ",".join(f"[{x}]" for x in cols)


def _valeur(v):
    return {"blob_sha256": hashlib.sha256(v).hexdigest()} if isinstance(v, (bytes, bytearray, memoryview)) else v


def empreinte_table(c, t):
    cols = colonnes(c, t)
    h = hashlib.sha256(json.dumps(cols).encode())
    n = 0
    for r in c.execute(f"SELECT {qi(cols)} FROM [{t}] ORDER BY {qi(cols)}"):
        h.update(json.dumps([_valeur(v) for v in r], ensure_ascii=False, default=repr).encode()); h.update(b"\n"); n += 1
    return n, h.hexdigest()


def chiffres(c):
    """quelques totaux lisibles, pour le journal de contrôle (absents si la table ou la colonne n'existe pas)"""
    t, out = tables(c), {}
    q = lambda sql: c.execute(sql).fetchall()
    if "entries" in t:
        out["saisies"], out["heures"] = q("SELECT COUNT(*), ROUND(COALESCE(SUM(hours),0),4) FROM entries")[0]
    if "projects" in t:
        out["mandats"] = q("SELECT COUNT(*) FROM projects")[0][0]
        if "closed_at" in colonnes(c, "projects"):
            out["mandats_clotures"] = q("SELECT COUNT(*) FROM projects WHERE closed_at IS NOT NULL")[0][0]
    if "invoices" in t:
        out["factures_par_statut"] = dict(q("SELECT status, COUNT(*) FROM invoices GROUP BY status ORDER BY status"))
    if "credit_notes" in t and "status" in colonnes(c, "credit_notes"):
        out["notes_de_credit_par_statut"] = dict(q("SELECT status, COUNT(*) FROM credit_notes GROUP BY status ORDER BY status"))
    if "historical_invoices" in t:
        out["historiques_par_statut"] = {s: {"nombre": n, "montant_ht": m}
                                         for s, n, m in q("SELECT status, COUNT(*), ROUND(SUM(amount_ht),2) FROM historical_invoices GROUP BY status ORDER BY status")}
    if "import_batches" in t:
        out["lots_import_par_statut"] = dict(q("SELECT status, COUNT(*) FROM import_batches GROUP BY status ORDER BY status"))
    return out


def empreinte(chemin):
    c = ouvrir(chemin)
    t = tables(c)
    res = {"integrite": c.execute("PRAGMA integrity_check").fetchone()[0], "tables_metier": {}, "hors_comparaison": {}}
    for x in TABLES_METIER:
        if x in t:
            n, h = empreinte_table(c, x)
            res["tables_metier"][x] = {"lignes": n, "sha256": h}
    for x in sorted(t - set(TABLES_METIER)):
        res["hors_comparaison"][x] = c.execute(f"SELECT COUNT(*) FROM [{x}]").fetchone()[0]
    res["chiffres"] = chiffres(c)
    return res


def vide(chemin):
    """tables métier non vides (liste de (table, lignes)) ; liste vide = base sans aucune donnée métier"""
    c = ouvrir(chemin)
    t = tables(c)
    return [(x, n) for x in TABLES_METIER if x in t for n in [c.execute(f"SELECT COUNT(*) FROM [{x}]").fetchone()[0]] if n]


def comparer(a, b):
    """écarts table par table (liste de textes) ; liste vide = données métier identiques"""
    c = ouvrir(a)
    c.execute("ATTACH DATABASE ? AS b", (f"file:{b}?mode=ro",))
    ta, tb = tables(c), tables(c, "b")
    out = []
    for x in TABLES_METIER:
        if x not in ta and x not in tb:
            continue
        if (x in ta) != (x in tb):
            out.append(f"{x} : table présente seulement dans {'A' if x in ta else 'B'}")
            continue
        ca, cb = colonnes(c, x), colonnes(c, x, "b")
        if ca != cb:
            out.append(f"{x} : colonnes différentes (seulement A : {sorted(set(ca) - set(cb)) or '-'} ; seulement B : {sorted(set(cb) - set(ca)) or '-'})")
            continue
        cols = qi(ca)
        # EXCEPT élimine les doublons : on compare aussi les effectifs (deux lignes identiques dans A, une seule dans B = écart)
        na, nb = (c.execute(f"SELECT COUNT(*) FROM {s}.[{x}]").fetchone()[0] for s in ("main", "b"))
        sa = c.execute(f"SELECT COUNT(*) FROM (SELECT {cols} FROM main.[{x}] EXCEPT SELECT {cols} FROM b.[{x}])").fetchone()[0]
        sb = c.execute(f"SELECT COUNT(*) FROM (SELECT {cols} FROM b.[{x}] EXCEPT SELECT {cols} FROM main.[{x}])").fetchone()[0]
        if sa or sb or na != nb:
            out.append(f"{x} : {na} ligne(s) dans A, {nb} dans B ; {sa} ligne(s) seulement dans A, {sb} seulement dans B")
    return out


def main(argv):
    if len(argv) == 3 and argv[1] == "vide":
        nv = vide(argv[2])
        if nv:
            print("NON VIDE : " + " ; ".join(f"{x} {n} ligne(s)" for x, n in nv))
            return 1
        print("VIDE : aucune ligne dans les tables métier présentes")
        return 0
    if len(argv) == 3 and argv[1] == "empreinte":
        print(json.dumps(empreinte(argv[2]), ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    if len(argv) == 4 and argv[1] == "comparer":
        ec = comparer(argv[2], argv[3])
        if ec:
            print("DIFFÉRENTES :\n  " + "\n  ".join(ec))
            return 1
        print("IDENTIQUES : toutes les tables métier (mêmes colonnes, mêmes lignes)")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
