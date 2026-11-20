#!/usr/bin/env python3
"""BILL-RC48-FIX (constats C et D de la revue rc48) : retour arrière rc48 -> rc47 SANS perte de données, par un outil testé plutôt que par des fonctions à enchaîner à la main.

Deux commandes (l'application doit être ARRÊTÉE ; l'outil n'arrête ni ne démarre rien, n'ouvre aucun réseau) :

  python3 -I outils/retour_rc47.py base FICHIER.db            simulation : dit ce qui serait fait, ne modifie rien
  python3 -I outils/retour_rc47.py base FICHIER.db --oui      1) copie vérifiée FICHIER.db.avant-retour-rc47-<horodatage> (API de sauvegarde SQLite, integrity_check) ;
                                                              2) retire de la base les 6 objets de rc48 (1 index + 5 déclencheurs) et remet l'ancien plafond d'avoir
                                                                 (schéma identique à rc47, vérifié) ; AUCUNE ligne métier touchée, une ligne est ajoutée au journal d'audit
  python3 -I outils/retour_rc47.py json SAUVEGARDE.json SORTIE.db    construit, avec le code de CE dépôt (rc48), un fichier SQLite contenant les données d'une sauvegarde JSON
                                                              (faite sous rc48), au schéma rc47 : à installer comme base quand rc47 tourne (la restauration JSON de rc47 refuserait
                                                              un avoir de 0,23 sur une ligne de 0,225). SORTIE.db ne doit pas exister ; rien d'autre n'est modifié.

Pourquoi : (D) rc47 ne connaît pas l'index d'unicité des adresses ; si une adresse globale « egg fr » coexiste avec « EGG FR » du client d'origine, rc47 refuse de démarrer sur une base
rc48 (son déplacement d'adresses se heurte à l'index). (C) rc47 reconstruit la base d'une restauration JSON avec son ANCIEN plafond d'avoir, qui refuse un avoir total sur un demi-centime
accepté par rc48. Dans les deux cas, ramener la base au schéma rc47 avant de lancer rc47 supprime le problème. Un nouveau passage de rc48 refait la migration tout seul.
BILL-RC48-FIX2 (constat N-1 de la 2e revue) : l'outil n'agit QUE sur les chemins donnés en argument, jamais sur la base « par défaut » de l'application (variable DB_PATH). Le mode json force DB_PATH vers
un dossier jetable privé AVANT d'importer l'application (dont l'import exécute init() et migrerait la base visée), puis le supprime. Tout chemin sous /opt/time-billing-v9 (ou égal à DB_PATH de
l'environnement) est REFUSÉ, sauf option explicite --confirmer-chemin-production (procédure de retour : docs/RC48-NOTES.md). Le mode json n'écrit jamais sur la base de production en place.
Code de sortie : 0 = fait (ou simulation réussie) ; 1 = refusé ou échec (rien n'est modifié : la transaction est annulée) ; 2 = mauvais usage."""
import datetime, os, shutil, sqlite3, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True
from app import address_service, credit_lines, line_guards                       # noqa: E402  (aucun de ces modules ne lit la configuration de l'application)

PROD_ROOT = "/opt/time-billing-v9"
CONFIRM = "--confirmer-chemin-production"


def is_production(path):
    """True for any path under /opt/time-billing-v9 (symlinks resolved) or equal to the DB_PATH of the environment (the application's default database)."""
    real = os.path.realpath(path)
    if real == PROD_ROOT or real.startswith(PROD_ROOT + os.sep): return True
    env = os.environ.get("DB_PATH")
    return bool(env) and real in (os.path.realpath(env), *(os.path.realpath(env + x) for x in ("-wal", "-shm", "-journal")))


def refuse_production(paths, confirmed):
    bad = [p for p in paths if is_production(p)]
    if bad and not confirmed:
        print(f"REFUS : {', '.join(bad)} est un chemin de production (sous {PROD_ROOT} ou DB_PATH). Rien n'a été fait. "
              f"Si c'est voulu (procédure de retour, application arrêtée, sauvegarde faite), relancer avec {CONFIRM}."); return True
    return False


def over_rc47_cap(c):
    """N-3: ids of the invoice lines whose (non-cancelled) credits exceed what the ceiling of rc47 accepts (ROUND(qty*unit_rate,2)+0.005)."""
    return [r[0] for r in c.execute(
        "SELECT il.id FROM credit_note_lines l JOIN invoice_lines il ON il.id=l.invoice_line_id WHERE l.credit_note_id NOT IN (SELECT credit_note_id FROM credit_note_cancellations) "
        "GROUP BY il.id HAVING SUM(l.amount) > ROUND(il.qty*il.unit_rate,2)+0.005")]


RC48_OBJECTS = (("index", address_service.LABEL_INDEX), *(("trigger", n) for n in credit_lines.UPDATE_GUARD_NAMES), ("trigger", line_guards.NAME))


def state(c):
    """(objets de rc48 présents, plafond d'avoir à la formule de rc48 ?)"""
    have = {(r[0], r[1]) for r in c.execute("SELECT type,name FROM sqlite_master WHERE type IN ('index','trigger')")}
    return [o for o in RC48_OBJECTS if o in have], credit_lines.within_line_is_current(c)


def undo(c):
    """Les quatre fonctions documentées, dans l'ordre. À appeler dans une transaction ouverte par l'appelant."""
    address_service.drop_label_index(c); credit_lines.rollback_update_guards(c); line_guards.rollback(c)
    if credit_lines.within_line_is_current(c): credit_lines.rollback_within_line(c)


def verify_rc47(c):
    """Problèmes restants ([] = base au schéma rc47 : plus aucun objet de rc48, plafond d'avoir de rc47, intégrité)."""
    out = []
    present, current = state(c)
    if present: out.append("objets de rc48 encore présents : " + ", ".join(n for _, n in present))
    if current: out.append("plafond d'avoir encore à la formule de rc48")
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='credit_lines_within_line'").fetchone()
    if row is None: out.append("déclencheur credit_lines_within_line absent")
    elif credit_lines.norm_sql(row[0]) != credit_lines.norm_sql(credit_lines.LEGACY_WITHIN_LINE_TRIGGER): out.append("déclencheur credit_lines_within_line différent de celui de rc47")
    if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok": out.append("integrity_check en échec")
    if c.execute("PRAGMA foreign_key_check").fetchall(): out.append("foreign_key_check en échec")
    return out


def cmd_base(path, yes):
    if not os.path.isfile(path): print(f"Fichier introuvable : {path}"); return 1
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        present, current = state(src)
        if src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='credit_note_lines'").fetchone() is None:
            print("Cette base n'a pas le schéma de rc47 ou plus (table credit_note_lines absente) : rien à faire."); return 1
        risky = over_rc47_cap(src)
    finally: src.close()
    if risky: print(f"ATTENTION : {len(risky)} ligne(s) de facture (id {', '.join(map(str, risky[:10]))}{'…' if len(risky) > 10 else ''}) portent des avoirs au-dessus du plafond de rc47 (demi-centime). Le retour de schéma les laisse en place ; "
                    f"tant qu'ils existent, une sauvegarde JSON faite sous rc47 N'EST PAS restaurable : ne restaurer que le FICHIER SQLite (le copier avant le retour).")
    print(f"Objets de rc48 présents : {len(present)} sur {len(RC48_OBJECTS)} ({', '.join(n for _, n in present) or 'aucun'}) ; plafond d'avoir à la formule de rc48 : {'oui' if current else 'non'}.")
    if not present and not current: print("La base est déjà au schéma rc47 : rien à faire."); return 0
    if not yes: print("Simulation : rien n'a été modifié. Relancer avec --oui (application arrêtée) pour appliquer."); return 0
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"); bak = f"{path}.avant-retour-rc47-{stamp}"
    if os.path.exists(bak): print(f"Copie déjà présente : {bak}"); return 1
    s = sqlite3.connect(f"file:{path}?mode=ro", uri=True); d = sqlite3.connect(bak)
    try:
        s.backup(d)
        if d.execute("PRAGMA integrity_check").fetchone()[0] != "ok": os.remove(bak); print("Copie de sécurité invalide : retour arrière NON effectué."); return 1
    finally: d.close(); s.close()
    os.chmod(bak, 0o600); print(f"Copie de sécurité vérifiée : {bak}")
    c = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            undo(c)
            c.execute("INSERT INTO audit(event,detail) VALUES(?,?)", ("rollback_rc47_schema", f"objets retirés : {', '.join(n for _, n in present)} ; plafond d'avoir remis à la formule de rc47 ; copie : {os.path.basename(bak)}"))
            bad = verify_rc47(c)
            if bad: raise RuntimeError("; ".join(bad))
            c.execute("COMMIT")
        except Exception as e:
            c.execute("ROLLBACK"); print(f"ÉCHEC, base inchangée : {e}"); return 1
    finally: c.close()
    print("Retour arrière effectué : la base est au schéma rc47 (vérifié). On peut démarrer rc47. Un nouveau démarrage de rc48 refera la migration.")
    return 0


def cmd_json(json_path, out_path, confirmed=False):
    if refuse_production((json_path, out_path), confirmed): return 1
    if os.path.exists(out_path): print(f"{out_path} existe déjà : refus d'écraser."); return 1
    if not os.path.isfile(json_path): print(f"Fichier introuvable : {json_path}"); return 1
    # N-1 : importer app.app exécute init() sur DB_PATH. On AFFECTE (jamais setdefault) un fichier jetable dans un dossier privé, et des secrets fictifs, avant l'import.
    sandbox = tempfile.mkdtemp(prefix="retour-rc47-env-")
    for k, v in (("DB_PATH", os.path.join(sandbox, "inutilise.db")), ("SECRET_KEY", "0" * 64), ("COOKIE_SECURE", "0"), ("APP_PASSWORD", "outil-retour-rc47-mot-de-passe-fictif"), ("INVOICE_CHECK_WORDS", "")): os.environ[k] = v
    try: return _json_build(json_path, out_path, sandbox)
    finally: shutil.rmtree(sandbox, ignore_errors=True)


def _json_build(json_path, out_path, sandbox):
    import app.app as m
    if os.path.realpath(m.DB) != os.path.realpath(os.path.join(sandbox, "inutilise.db")): print("REFUS : l'application pointe vers une autre base que le dossier jetable ; rien n'a été fait."); return 1
    from app import restore_service
    raw = open(json_path, "rb").read()
    work = tempfile.mkdtemp(prefix="retour-rc47-", dir=os.path.dirname(os.path.abspath(out_path)))
    try:
        scratch = os.path.join(work, "schema.db"); m.init(scratch)
        sc = sqlite3.connect(scratch)
        try: data = restore_service.validate(sc, raw)
        finally: sc.close()
        conflicts = restore_service.address_label_conflicts(data)
        if conflicts: print("Sauvegarde refusée : " + " ; ".join(conflicts)); return 1
        built = os.path.join(work, "sortie.db")
        restore_service.rebuild(built, data, m.init)            # schéma rc48, données du fichier, contrôles d'intégrité et d'empreintes de la restauration
        c = sqlite3.connect(built, isolation_level=None)
        try:
            c.execute("BEGIN IMMEDIATE"); undo(c)
            bad = verify_rc47(c)
            if bad: c.execute("ROLLBACK"); print("ÉCHEC : " + "; ".join(bad)); return 1
            c.execute("COMMIT")
        finally: c.close()
        os.replace(built, out_path); os.chmod(out_path, 0o600)
    except restore_service.RestoreRefused as e: print(f"Sauvegarde refusée : {e}"); return 1
    except sqlite3.DatabaseError as e: print(f"ÉCHEC de la reconstruction : {e}"); return 1
    finally:
        for f in os.listdir(work): os.remove(os.path.join(work, f))
        os.rmdir(work)
    print(f"Fichier produit : {out_path} (données de la sauvegarde, schéma rc47). À installer comme base quand l'application est arrêtée ; garder la base actuelle à part.")
    return 0


def main(argv):
    confirmed = CONFIRM in argv; argv = [a for a in argv if a != CONFIRM]
    if argv[:1] == ["base"] and len(argv) in (2, 3) and (len(argv) == 2 or argv[2] == "--oui"):
        if refuse_production((argv[1],), confirmed): return 1
        return cmd_base(argv[1], len(argv) == 3)
    if argv[:1] == ["json"] and len(argv) == 3: return cmd_json(argv[1], argv[2], confirmed)
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
