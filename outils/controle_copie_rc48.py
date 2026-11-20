#!/usr/bin/env python3
"""BILL-RC48-FIX (constat B de la revue rc48) : contrôles de données à passer sur une COPIE de la base de production AVANT la mise en ligne de rc48. LECTURE SEULE.

Usage : python3 -I outils/controle_copie_rc48.py COPIE.db        (code 0 = rien à signaler ; 1 = au moins un point à traiter ; 2 = mauvais usage)

La base est ouverte en `file:…?mode=ro` (SQLite refuse toute écriture) ; l'outil n'écrit rien, n'ouvre aucun réseau et ne lit aucune autre base. Il ne doit JAMAIS être pointé sur la base vivante :
travailler sur une copie faite avec la sauvegarde SQLite habituelle (`procedure/20-backup.sh`) ou `sqlite3 base.db ".backup copie.db"`. Procédure complète : docs/revues-rc48/VERIFS-COPIE-PROD.md."""
import collections, os, sqlite3, sys, unicodedata

CHECKS = [
    # (numéro, titre, requête SQL, "à traiter" si des lignes sortent, conséquence)
    ("1", "adresses d'un même client dont les noms ne diffèrent que par les majuscules (ASCII)",
     "SELECT client_key, group_concat(id||':'||label,' | '), COUNT(*) FROM billing_addresses GROUP BY client_key, label COLLATE NOCASE HAVING COUNT(*)>1", True,
     "rc48 ne crée pas son index d'unicité et le contrôle de schéma (30-rehearse, 50-verify, verifier-sauvegarde) passe au rouge : renommer l'une des deux adresses (écran Adresses de rc47) AVANT la mise en ligne"),
    ("3", "noms d'adresse avec espaces en début/fin ou doubles espaces",
     "SELECT id, client_key, '['||label||']' FROM billing_addresses WHERE label<>trim(label) OR label LIKE '%  %'", True,
     "ces noms peuvent cacher un doublon que la comparaison de rc48 verrait : vérifier à la main"),
    ("4", "adresse de la liste commune ('*') et adresse du client d'origine (NOM:bsci) de même nom à la casse près mais écrites différemment",
     "SELECT g.id, g.label, n.id, n.label FROM billing_addresses g JOIN billing_addresses n ON g.client_key='*' AND n.client_key='NOM:bsci' AND g.label=n.label COLLATE NOCASE AND g.label<>n.label", True,
     "avec cette base, rc47 refuserait de démarrer après un retour arrière sans passer par outils/retour_rc47.py (constat D) : prévoir l'outil, ou renommer avant"),
    ("5a", "lignes de facture manuelles dont le montant finit sur un demi-centime (information : rc47 refusait un avoir total sur ces lignes, rc48 l'accepte)",
     "SELECT id, invoice_id, qty, unit_rate FROM invoice_lines WHERE (CAST(ROUND(qty*1000000) AS INTEGER)*CAST(ROUND(unit_rate*10000) AS INTEGER)) % 100000000 = 50000000", False,
     "information seulement : ces lignes sont celles où le correctif d'arrondi change quelque chose"),
    ("5b", "lignes de facture manuelles de plus de 900 000 000 CHF (le plafond d'avoir repasse à l'ancien calcul flottant au-delà)",
     "SELECT id, invoice_id, qty, unit_rate, qty*unit_rate FROM invoice_lines WHERE qty*unit_rate > 9e8", True, "constat H : écart possible d'un centime, à examiner"),
    ("6", "lignes déjà créditées, dont une note a été annulée, puis recréditées (la restauration JSON les refuserait : défaut de rc47, constat E)",
     "SELECT l.invoice_line_id, COUNT(*) FROM credit_note_lines l GROUP BY l.invoice_line_id HAVING COUNT(*)>1 AND SUM(l.credit_note_id IN (SELECT credit_note_id FROM credit_note_cancellations))>0", True,
     "la restauration JSON de cette base échouerait même sous rc47 : s'appuyer sur la sauvegarde du fichier SQLite ; correctif prévu dans un lot séparé"),
    ("7", "lignes d'avoir incohérentes avec leur ligne de facture (autre facture ou autre régime de TVA)",
     "SELECT l.id FROM credit_note_lines l JOIN invoice_lines il ON il.id=l.invoice_line_id JOIN credit_notes n ON n.id=l.credit_note_id WHERE il.invoice_id<>n.invoice_id OR il.vat_mode<>l.vat_mode", True,
     "les nouveaux garde-fous les empêcheraient d'être modifiées : à examiner"),
    ("8a", "contrôle d'intégrité SQLite", "PRAGMA integrity_check", None, "doit répondre « ok »"),
    ("8b", "contrôle des clés étrangères", "PRAGMA foreign_key_check", True, "doit être vide"),
]


def unicode_twins(c):
    """Groupes d'adresses d'un client dont les noms sont identiques après normalisation Unicode (NFC), espaces réduits et casse complète (casefold) : ce que `label_taken` de rc48 voit."""
    groups = collections.defaultdict(list)
    for i, k, l in c.execute("SELECT id, client_key, label FROM billing_addresses"): groups[(k, unicodedata.normalize("NFC", " ".join(l.split())).casefold())].append((i, l))
    return [v for v in groups.values() if len(v) > 1]


def main(argv):
    if len(argv) != 1 or argv[0].startswith("-"): print(__doc__); return 2
    path = os.path.abspath(argv[0])
    if not os.path.isfile(path): print(f"Fichier introuvable : {path}"); return 2
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    todo = 0
    try:
        print(f"Contrôles en LECTURE SEULE sur {path}\n")
        for num, title, sql, bad, why in CHECKS:
            if num == "3":          # le contrôle 2 (Unicode) se range entre 1 et 3
                tw = unicode_twins(c); flag = "OK" if not tw else "À TRAITER"; todo += bool(tw)
                print(f"[{flag:9}] 2. adresses d'un même client identiques après normalisation Unicode, espaces et casse complète (Zürich / ZÜRICH) : {len(tw)}"
                      + ("" if not tw else "\n            rc48 refuserait de renommer/créer ces adresses et les signalerait comme doublons : renommer l'une des deux avant"))
                for g in tw[:10]: print("            ", g)
            rows = c.execute(sql).fetchall()
            if num == "8a": flag = "OK" if rows == [("ok",)] else "À TRAITER"
            else: flag = "OK" if not rows else ("À TRAITER" if bad else "INFO")
            if flag == "À TRAITER": todo += 1
            print(f"[{flag:9}] {num}. {title} : {len(rows) if num != '8a' else rows[0][0]}" + ("" if flag == "OK" else f"\n            {why}"))
            for r in (rows[:10] if num != "8a" else []): print("            ", tuple(r))
    finally: c.close()
    print(f"\n{'RIEN À SIGNALER' if not todo else str(todo) + ' point(s) à traiter avant la mise en ligne'} (les lignes « INFO » ne bloquent rien).")
    return 1 if todo else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
