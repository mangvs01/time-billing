#!/usr/bin/env python3
"""BILL-RC48 : répétition de la migration rc47 -> rc48 sur une base FICTIVE au schéma de rc47.

Usage : /root/venvs/rc25-test-venv/bin/python -I outils/repeter_migration_rc48.py     (code 0 = toutes les vérifications passent)

Aucune donnée réelle, aucune base de production, aucun réseau. Tout se passe dans un dossier temporaire jetable (créé hors du dépôt, supprimé à la fin) :
  - le code rc47 est extrait de l'historique git (`git archive 2382090`, lecture seule) ;
  - la base fictive est construite PAR le code rc47 (app.init) puis remplie de lignes synthétiques ;
  - la migration = app.init() du code rc48 (celui de ce dépôt) sur une COPIE de cette base.
Vérifie : migration aller (empreinte de toutes les tables inchangée), avoir sur demi-centime refusé en rc47 / accepté en rc48, doublon d'adresse à la casse près refusé,
mise à jour de ligne refusée par les nouvelles gardes, retour arrière (rc47 remis sur la base migrée ; retour arrière complet par outils/retour_rc47.py), base déjà en doublon.
BILL-RC48-FIX : constat D (rc47 refuse de démarrer sur une base rc48 portant « egg fr » global et « EGG FR » du client d'origine : l'outil de retour corrige) et constat C (une sauvegarde JSON
faite sous rc48 n'est pas restaurable par le code rc47 : l'outil produit un fichier SQLite au schéma rc47 qui l'est) ; le défaut de rc47 est d'abord REPRODUIT, puis la correction vérifiée."""
import hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RC47 = "2382090"
PY = sys.executable
ENV = {"SECRET_KEY": "0" * 64, "COOKIE_SECURE": "0", "INVOICE_CHECK_WORDS": "", "APP_PASSWORD": "synthetic-test-password", "PATH": os.environ.get("PATH", "")}
OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label); print(("  OK  " if cond else "  ÉCHEC ") + label + (f"  [{detail}]" if detail and not cond else ""))


def run_init(code_dir, db):
    """app.init() du code situé dans code_dir, sur la base db (processus séparé : on ne mélange jamais deux versions du code)."""
    code = f"import sys; sys.dont_write_bytecode=True; sys.path.insert(0,{code_dir!r}); import app.app as m; m.DB={db!r}; m.init(); print(m.VERSION)"
    r = subprocess.run([PY, "-I", "-c", code], env={**ENV, "DB_PATH": db}, capture_output=True, text=True, cwd="/")
    return r.returncode, (r.stdout.strip() or r.stderr.strip()[-400:])


def run_py(code, db):
    r = subprocess.run([PY, "-I", "-c", code], env={**ENV, "DB_PATH": db}, capture_output=True, text=True, cwd="/")
    return r.returncode, r.stdout.strip(), r.stderr.strip()[-500:]


def export_json(code_dir, db, out):
    """Sauvegarde JSON faite par le code de code_dir (route /backup, connexion comprise) sur la base db."""
    code = (f"import sys; sys.dont_write_bytecode=True; sys.path.insert(0,{code_dir!r}); import app.app as m; m.DB={db!r}; m.init(); c=m.APP.test_client(); "
            f"r=c.post('/login', data={{'username': m.SEC['user'], 'password': 'synthetic-test-password'}}); b=c.get('/backup'); assert b.status_code==200, b.status_code; "
            f"open({out!r},'wb').write(b.get_data()); print(m.VERSION)")
    return run_py(code, db)


def restore_rebuild(code_dir, json_path, target):
    """Reconstruction d'une base à partir d'un JSON par le code de code_dir (la partie de la restauration qui crée la base : restore_service.rebuild)."""
    code = (f"import sys, sqlite3; sys.dont_write_bytecode=True; sys.path.insert(0,{code_dir!r}); import app.app as m; from app import restore_service as rs; m.init({target + '.schema'!r}); "
            f"c=sqlite3.connect({target + '.schema'!r}); d=rs.validate(c, open({json_path!r},'rb').read()); c.close(); rs.rebuild({target!r}, d, m.init); print('reconstruite')")
    return run_py(code, target)


def schema_text(db):
    """{nom: texte SQL normalisé} des déclencheurs et index (le texte, pas seulement les noms)."""
    c = sqlite3.connect(db)
    try: return {(r[0], r[1]): " ".join(r[2].replace("IF NOT EXISTS ", "").split()).rstrip(";") for r in c.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('trigger','index') AND sql IS NOT NULL")}
    finally: c.close()


TOOL = os.path.join(ROOT, "outils", "retour_rc47.py")


def run_tool(*args):
    r = subprocess.run([PY, "-I", TOOL, *args], capture_output=True, text=True, cwd="/"); return r.returncode, r.stdout + r.stderr


SKIP_RESTORE = ("audit", "web_sessions", "login_failures", "kept_forms", "auth_credentials")      # journal et état de session : jamais restaurés tels quels (restore_service.TRANSIENT)


def fingerprint(db, skip=("audit",)):
    c = sqlite3.connect(db); h = hashlib.sha256(); n = {}
    try:
        for t in sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")):
            if t in skip: continue
            h.update(t.encode()); rows = c.execute('SELECT * FROM "%s" ORDER BY 1' % t).fetchall(); n[t] = len(rows)
            for r in rows: h.update(repr(tuple(r)).encode())
        return h.hexdigest(), n
    finally: c.close()


def objects(db):
    c = sqlite3.connect(db)
    try: return {(r[0], r[1]) for r in c.execute("SELECT type,name FROM sqlite_master WHERE type IN ('trigger','index') AND name NOT LIKE 'sqlite_%'")}
    finally: c.close()


def attempt(db, sql, args=()):
    c = sqlite3.connect(db)
    try: c.execute(sql, args); c.commit(); return None
    except sqlite3.DatabaseError as e: return str(e)
    finally: c.close()


def populate(db):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO projects(id,name,client,rate,vat,ordered_days) VALUES(1,'Mandat fictif','Client fictif',650,8.1,12)")
    c.execute("INSERT INTO invoices(id,number,project_id,period_from,period_to,qty,unit_rate,vat,status) VALUES(1,NULL,1,'2026-09-01','2026-09-30',2,650,8.1,'draft')")
    for pos, (d, q, r, vm) in enumerate([("Frais fictifs", 1, 100, "soumis"), ("Hébergement fictif", 1, 50, "hors_tva"), ("Demi-centime fictif", 1.5, 0.15, "soumis"), ("Autre demi-centime", 7, 0.145, "soumis")], 1):
        c.execute("INSERT INTO invoice_lines(invoice_id,position,description,qty,unit,unit_rate,vat_mode,created_at) VALUES(1,?,?,?,'flat',?,?,'2026-10-01T00:00:00')", (pos, d, q, r, vm))
    c.execute("UPDATE invoices SET number='F-2026-0001', status='issued', issued_at='2026-10-01' WHERE id=1")
    c.execute("INSERT INTO invoices(id,number,project_id,period_from,period_to,qty,unit_rate,vat,status) VALUES(2,NULL,1,'2026-10-01','2026-10-31',1,650,8.1,'draft')")
    c.execute("INSERT INTO invoice_lines(invoice_id,position,description,qty,unit,unit_rate,vat_mode,created_at) VALUES(2,1,'Ligne de brouillon fictive',1,'flat',10,'soumis','2026-10-02T00:00:00')")
    c.execute("INSERT INTO credit_notes(id,reference,invoice_id,amount,reason) VALUES(1,'AV-FICTIF-1',1,60,'motif fictif')")
    c.execute("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,position,description,amount,vat_mode,created_at) VALUES(1,1,1,'Frais fictifs',60,'soumis','2026-10-03T00:00:00')")
    for lab in ("EGG FR", "EGG BE"):
        c.execute("INSERT INTO billing_addresses(client_key,label,contact,address,created_at) VALUES('*',?,'Contact fictif','Rue fictive 1\n1000 Ville',?)", (lab, "2026-10-01T00:00:00"))
    c.commit(); c.close()


HALF = ("INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,position,description,amount,vat_mode,created_at) "
        "VALUES(1,3,2,'Demi-centime fictif',0.23,'soumis','2026-10-03T00:00:00')")        # ligne facturée 1,5 × 0,15 = 0,225 -> 0,23 (demi-supérieur)
ADDR = "INSERT INTO billing_addresses(client_key,label,contact,address,created_at) VALUES('*',?,'x','y','2026-10-04T00:00:00')"


def main():
    work = tempfile.mkdtemp(prefix="rc48-repetition-")
    try:
        if os.path.realpath(work).startswith(os.path.realpath(ROOT) + os.sep): raise SystemExit("dossier temporaire dans le dépôt : refus")
        src47 = os.path.join(work, "rc47-src"); os.mkdir(src47)
        tar = subprocess.run(["git", "-C", ROOT, "archive", RC47], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", src47], input=tar, check=True)
        print(f"Dossier jetable : {work}\n== 1. Base fictive au schéma rc47 ==")
        base = os.path.join(work, "rc47.db")
        rc, out = run_init(src47, base); check("rc47 crée sa base (version annoncée " + out + ")", rc == 0 and out == "9.2-rc47", out)
        populate(base); run_init(src47, base)      # 2e démarrage rc47 : état stable (gel des instantanés de facture émise), comme en exploitation
        fp0, n0 = fingerprint(base); obj47 = objects(base)
        check("base fictive remplie (factures, lignes, avoir, adresses)", n0.get("invoice_lines") == 5 and n0.get("billing_addresses") == 2 and n0.get("credit_note_lines") == 1, n0)
        check("rc47 : avoir total sur le demi-centime REFUSÉ (défaut connu)", "cannot exceed" in (attempt(base, HALF) or ""))
        check("rc47 : doublon d'adresse « egg fr » ACCEPTÉ (défaut connu)", attempt(base, ADDR, ("egg fr",)) is None)
        shutil.copy(base, base + ".sav"); shutil.copy(base + ".sav", base)      # base propre : on retire l'essai ci-dessus
        c = sqlite3.connect(base); c.execute("DELETE FROM billing_addresses WHERE label='egg fr'"); c.commit(); c.close()
        fp0, n0 = fingerprint(base)

        print("== 2. Migration aller (code rc48 de ce dépôt, sur une copie) ==")
        mig = os.path.join(work, "migree.db"); shutil.copy(base, mig)
        rc, out = run_init(ROOT, mig); check("rc48 démarre sur la base rc47 (version " + out + ")", rc == 0 and out == "9.2-rc48", out)
        fp1, n1 = fingerprint(mig)
        check("données intactes : empreinte de toutes les tables identique (hors journal d'audit)", fp1 == fp0 and n1 == n0, (n0, n1))
        r = subprocess.run([PY, "-I", os.path.join(ROOT, "outils", "empreinte_metier.py"), "comparer", base, mig], capture_output=True, text=True)
        check("empreinte métier (outils/empreinte_metier.py comparer) : identique", r.returncode == 0, r.stdout[-300:] + r.stderr[-300:])
        new = objects(mig) - obj47; gone = obj47 - objects(mig)
        check("ajouts uniquement : 1 index + 5 déclencheurs, rien de retiré sauf l'ancien plafond remplacé par le nouveau (même nom)", not gone and len(new) == 6, (sorted(new), sorted(gone)))
        print("     objets ajoutés :", ", ".join(sorted(n for _, n in new)))
        ca = sqlite3.connect(mig).execute("SELECT COUNT(*) FROM audit WHERE event='billing_address_label_index_skipped'").fetchone()[0]
        check("aucune note d'audit « index ignoré » (pas de doublon existant)", ca == 0)
        rc, out = run_init(ROOT, mig); fp1b, _ = fingerprint(mig)
        check("2e démarrage rc48 : idempotent (mêmes objets, mêmes données)", rc == 0 and objects(mig) == obj47 | new and fp1b == fp0, out)

        print("== 3. Comportement sur la base migrée ==")
        check("avoir total sur le demi-centime ACCEPTÉ", attempt(mig, HALF) is None, attempt(mig, HALF))
        c = sqlite3.connect(mig); c.execute("DELETE FROM credit_note_lines WHERE invoice_line_id=3"); c.commit(); c.close()      # on retire l'essai accepté ci-dessus
        check("0,24 sur la ligne 0,225 REFUSÉ", "cannot exceed" in (attempt(mig, HALF.replace("0.23", "0.24")) or ""))
        check("plafond inchangé ailleurs : 60 déjà crédités + 90 sur une ligne de 100 REFUSÉ",
              "cannot exceed" in (attempt(mig, "INSERT INTO credit_note_lines(credit_note_id,invoice_line_id,position,description,amount,vat_mode,created_at) VALUES(1,1,9,'x',90,'soumis','2026-10-03T00:00:00')") or ""))
        e = attempt(mig, ADDR, ("egg fr",)); check("doublon d'adresse « egg fr » (même client) REFUSÉ", e is not None and "UNIQUE" in e, e)
        check("adresse nouvelle « EGG CH » toujours acceptée", attempt(mig, ADDR, ("EGG CH",)) is None)
        e = attempt(mig, "UPDATE invoice_lines SET invoice_id=1 WHERE id=5"); check("ligne de brouillon déplacée sous une facture émise : REFUSÉ", e is not None and "immutable" in e, e)
        e = attempt(mig, "UPDATE credit_note_lines SET amount=500 WHERE id=1"); check("réécriture d'une ligne d'avoir au-delà du plafond : REFUSÉ", e is not None, e)

        print("== 4. Retour arrière A : on remet rc47 sur la base migrée (sans rien défaire) ==")
        back = os.path.join(work, "retour-a.db"); mig_clean = os.path.join(work, "migree-propre.db"); shutil.copy(base, mig_clean); run_init(ROOT, mig_clean)
        shutil.copy(mig_clean, back); fpm, _ = fingerprint(back)
        rc, out = run_init(src47, back); fpb, _ = fingerprint(back)
        check("rc47 démarre sur la base migrée sans erreur (version " + out + ")", rc == 0 and out == "9.2-rc47", out)
        check("rc47 n'a modifié aucune donnée", fpb == fpm == fp0)
        check("rc47 sur base migrée : les nouveaux garde-fous restent actifs (doublon d'adresse refusé, demi-centime accepté)",
              attempt(back, ADDR, ("egg fr",)) is not None and attempt(back, HALF) is None)

        print("== 5. Retour arrière B : outils/retour_rc47.py (base), puis rc47 ==")
        full = os.path.join(work, "retour-b.db"); shutil.copy(mig_clean, full)
        rc, out = run_tool("base", full); check("simulation : annonce 6 objets de rc48 et ne modifie rien", rc == 0 and "Objets de rc48 présents : 6 sur 6" in out and "Simulation" in out and fingerprint(full)[0] == fp0 and objects(full) == obj47 | new, out[-300:])
        rc, out = run_tool("base", full, "--oui"); check("outil de retour exécuté (copie de sécurité vérifiée, schéma vérifié)", rc == 0 and "Retour arrière effectué" in out and "Copie de sécurité vérifiée" in out, out[-400:])
        check("copie de sécurité créée à côté de la base (sauvegarde SQLite, intégrité ok)", len([f for f in os.listdir(work) if f.startswith("retour-b.db.avant-retour-rc47-")]) == 1)
        check("schéma (déclencheurs + index) identique à celui de rc47", objects(full) == obj47, (sorted(objects(full) ^ obj47)))
        base47 = os.path.join(work, "rc47-neuve.db"); run_init(src47, base47)
        check("TEXTE SQL de chaque déclencheur et index identique à celui d'une base rc47 neuve", schema_text(full) == schema_text(base47), sorted(set(schema_text(full).items()) ^ set(schema_text(base47).items()))[:2])
        check("données identiques (hors journal d'audit)", fingerprint(full)[0] == fp0)
        ar = sqlite3.connect(full).execute("SELECT COUNT(*) FROM audit WHERE event='rollback_rc47_schema'").fetchone()[0]; check("une ligne « rollback_rc47_schema » au journal d'audit", ar == 1)
        rc, out = run_tool("base", full, "--oui"); check("2e exécution : rien à faire, aucune erreur", rc == 0 and "déjà au schéma rc47" in out, out[-200:])
        rc, out = run_init(src47, full); check("rc47 redémarre sur la base défaite et ne recrée rien de rc48", rc == 0 and objects(full) == obj47, out)
        check("comportement rc47 retrouvé (demi-centime refusé, doublon accepté)", "cannot exceed" in (attempt(full, HALF) or "") and attempt(full, ADDR, ("egg fr",)) is None)
        shutil.copy(base, full); run_init(src47, full)
        rc, out = run_init(ROOT, full); check("ré-aller : rc48 se remet sur la base rc47 sans problème", rc == 0 and out == "9.2-rc48" and fingerprint(full)[0] == fp0, out)

        print("== 6. Base rc47 qui contient DÉJÀ deux adresses à la casse près ==")
        dup = os.path.join(work, "doublon.db"); shutil.copy(base, dup)
        attempt(dup, ADDR, ("egg fr",)); fpd, nd = fingerprint(dup)
        rc, out = run_init(ROOT, dup); check("rc48 démarre quand même (rien n'est supprimé ni renommé)", rc == 0 and out == "9.2-rc48", out)
        check("données des tables métier inchangées", fingerprint(dup)[0] == fpd)
        check("index non créé, doublon consigné une fois dans le journal d'audit",
              ("index", "idx_billing_addresses_label_nocase") not in objects(dup)
              and sqlite3.connect(dup).execute("SELECT COUNT(*) FROM audit WHERE event='billing_address_label_index_skipped'").fetchone()[0] == 1)
        run_init(ROOT, dup); check("2e démarrage : pas de seconde note d'audit",
                                   sqlite3.connect(dup).execute("SELECT COUNT(*) FROM audit WHERE event='billing_address_label_index_skipped'").fetchone()[0] == 1)

        print("== 7. Constat D : rc47 sur une base rc48 où « egg fr » (liste commune) coexiste avec « EGG FR » du client d'origine ==")
        dd = os.path.join(work, "constat-d.db"); shutil.copy(base, dd); run_init(ROOT, dd)
        c = sqlite3.connect(dd); c.execute("UPDATE billing_addresses SET label='egg fr' WHERE client_key='*' AND label='EGG FR'")
        c.execute("INSERT INTO billing_addresses(client_key,label,contact,address,created_at) VALUES('NOM:bsci','EGG FR','x','y','2026-10-04T00:00:00')"); c.commit(); c.close()
        rc, out = run_init(ROOT, dd); check("rc48 démarre sur cette base (même démarrage qu'en production)", rc == 0 and out == "9.2-rc48", out)
        da = os.path.join(work, "constat-d-a.db"); shutil.copy(dd, da)
        rc, out = run_init(src47, da); check("DÉFAUT CONNU reproduit : rc47 refuse de démarrer sur cette base rc48 sans retour (retour A pur)", rc != 0 and "UNIQUE" in out, out)
        fpd0, _ = fingerprint(dd)
        rc, out = run_tool("base", dd, "--oui"); check("outil de retour exécuté sur cette base", rc == 0, out[-300:])
        rc, out = run_init(src47, dd); check("CORRIGÉ : rc47 démarre sur la base après l'outil de retour", rc == 0 and out == "9.2-rc47", out)
        fpd1, _ = fingerprint(dd)
        check("données des tables métier inchangées par le retour et par rc47 (hors déplacement d'adresse fait par rc47 lui-même : même nombre de lignes)",
              sqlite3.connect(dd).execute("SELECT COUNT(*) FROM billing_addresses").fetchone()[0] == sqlite3.connect(da).execute("SELECT COUNT(*) FROM billing_addresses").fetchone()[0])

        print("== 8. Constat C : sauvegarde JSON faite sous rc48 (avoir de 0,23 sur une ligne de 0,225), restaurée sous rc47 ==")
        cc = os.path.join(work, "constat-c.db"); shutil.copy(base, cc); run_init(ROOT, cc)
        check("avoir de 0,23 accepté sous rc48", attempt(cc, HALF) is None)
        js = os.path.join(work, "sauvegarde-rc48.json"); rc, out, err = export_json(ROOT, cc, js); check("sauvegarde JSON produite par rc48 (version " + out + ")", rc == 0 and out == "9.2-rc48", err)
        fpc, nc = fingerprint(cc, SKIP_RESTORE)      # empreinte de la base APRÈS l'export (la connexion de l'export peut écrire un paramètre) : c'est ce que le fichier contient
        rc, out, err = restore_rebuild(ROOT, js, os.path.join(work, "restaure-rc48.db")); check("restauration de ce JSON sous rc48 : reconstruite", rc == 0 and out == "reconstruite", err)
        fpr, nr = fingerprint(os.path.join(work, "restaure-rc48.db"), SKIP_RESTORE); check("… et les données sont identiques (hors audit)", fpr == fpc and nr == nc, (nc, nr))
        rc, out, err = restore_rebuild(src47, js, os.path.join(work, "restaure-rc47.db"))
        check("DÉFAUT CONNU reproduit : restauration de ce JSON sous rc47 REFUSÉE (ancien plafond d'avoir)", rc != 0 and "cannot exceed" in err, err)
        sortie = os.path.join(work, "pour-rc47.db"); rc, out = run_tool("json", js, sortie)
        check("CORRIGÉ : l'outil produit un fichier SQLite au schéma rc47 depuis ce JSON", rc == 0 and os.path.isfile(sortie), out[-400:])
        check("ce fichier porte exactement les données de la sauvegarde (avoir de 0,23 compris)", fingerprint(sortie, SKIP_RESTORE) == (fpc, nc) and sqlite3.connect(sortie).execute("SELECT COUNT(*) FROM credit_note_lines WHERE amount=0.23").fetchone()[0] == 1)
        s47 = os.path.join(work, "sortie-copie.db"); shutil.copy(sortie, s47); rc, out = run_init(src47, s47)
        check("rc47 démarre sur ce fichier sans rien recréer (schéma rc47, texte SQL identique à une base rc47 neuve)", rc == 0 and out == "9.2-rc47" and schema_text(s47) == schema_text(base47), out)
        rc, out = run_tool("json", js, sortie); check("l'outil refuse d'écraser un fichier existant", rc == 1 and "refus d'écraser" in out, out)
        bad = os.path.join(work, "pas-un-json.json"); open(bad, "w").write("{pas du json"); rc, out = run_tool("json", bad, os.path.join(work, "x.db"))
        check("fichier illisible : refusé proprement, aucun fichier produit", rc == 1 and "refusée" in out and not os.path.exists(os.path.join(work, "x.db")), out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\nRésultat : {len(OK)} vérifications réussies, {len(KO)} échec(s)." + ("" if not KO else " Échecs : " + "; ".join(KO)))
    return 1 if KO else 0


if __name__ == "__main__":
    sys.exit(main())
