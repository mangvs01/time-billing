#!/bin/bash
# Vérifie qu'une sauvegarde est RESTAURABLE : copie dans un conteneur jetable sans réseau, ouverture par l'application
# (migration idempotente), intégrité, clés étrangères, empreintes des PDF figés, annexes cohérentes, déclencheurs.
# Usage : verifier-sauvegarde.sh <fichier de configuration> <sauvegarde.db>      Code retour 0 = sauvegarde exploitable.
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
SRC=${2:?usage: $0 <conf> <sauvegarde.db>}; [ -f "$SRC" ] || die "fichier absent : $SRC"
R=$(mktemp -d); trap 'rm -rf "$R"' EXIT; cp "$SRC" "$R/timebilling.db"; chmod 777 "$R"; chmod 666 "$R/timebilling.db"
py_on_copy "$R" "$RC_IMAGE" "
import sqlite3,hashlib,json
import app.app as m                                   # ouverture par l'application : migration additive + gel d'éventuelles factures anciennes
c=sqlite3.connect('/data/timebilling.db'); c.row_factory=sqlite3.Row
ok=True
def chk(n,cond,extra=''):
    global ok; ok=ok and bool(cond); print(('OK    ' if cond else 'ÉCHEC ')+n+(' '+str(extra) if extra else ''))
chk('integrity_check', c.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
chk('foreign_key_check vide', c.execute('PRAGMA foreign_key_check').fetchall()==[])
n={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('projects','entries','invoices','credit_notes','invoice_snapshots','credit_note_snapshots')}
print('effectifs', json.dumps(n))
chk('toute facture émise a sa copie figée', c.execute(\"SELECT COUNT(*) FROM invoices i LEFT JOIN invoice_snapshots s ON s.invoice_id=i.id WHERE i.status='issued' AND s.invoice_id IS NULL\").fetchone()[0]==0)
chk('toute note émise a sa copie figée', c.execute(\"SELECT COUNT(*) FROM credit_notes k LEFT JOIN credit_note_snapshots s ON s.credit_note_id=k.id WHERE k.status='issued' AND s.credit_note_id IS NULL\").fetchone()[0]==0)
bad=[r[0] for r in c.execute('SELECT invoice_id,pdf,pdf_sha256 FROM invoice_snapshots') if hashlib.sha256(r[1]).hexdigest()!=r[2]]
chk('empreintes des PDF de factures', not bad, bad)
bad=[r[0] for r in c.execute('SELECT credit_note_id,pdf,pdf_sha256 FROM credit_note_snapshots') if hashlib.sha256(r[1]).hexdigest()!=r[2]]
chk('empreintes des PDF de notes de crédit', not bad, bad)
bad=[r[0] for r in c.execute('SELECT credit_note_id,pdf,pdf_sha256 FROM credit_note_cancellations') if hashlib.sha256(r[1]).hexdigest()!=r[2]]
chk('empreintes des PDF d annulation', not bad, bad)
# rc19 : une saisie facturée peut être corrigée ou supprimée (la facture garde sa copie figée) : schéma rc19 complet, déclencheurs compilables,
# tout lien d annexe vers une saisie absente expliqué par sa trace de suppression, aucun identifiant supprimé réutilisé
from app.schema_checks import rc19_problems
pb=rc19_problems(c); chk('schéma rc19 (déclencheurs, clé, écritures compilables, liens d annexe, identifiants)', not pb, pb)
chk('annexes = copie figée (nombre de lignes)', all(c.execute('SELECT COUNT(*) FROM invoice_annex_entries WHERE invoice_id=?',(i,)).fetchone()[0]==len(json.loads(a)) for i,a in c.execute('SELECT invoice_id,annex_json FROM invoice_snapshots')))
t=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='trigger'\")]
chk(f'{len(t)} déclencheurs d immuabilité', {'issued_invoice_no_update','issued_invoice_no_delete','invoice_snapshot_no_update','credit_snapshot_no_update','credit_ops_no_update'} <= set(t))
chk('numéros de facture uniques', c.execute('SELECT COUNT(*)-COUNT(DISTINCT number) FROM invoices WHERE number IS NOT NULL').fetchone()[0]==0)
print('SAUVEGARDE EXPLOITABLE' if ok else 'SAUVEGARDE NON EXPLOITABLE'); raise SystemExit(0 if ok else 1)
"
