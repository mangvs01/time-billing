#!/bin/bash
# 3. Répétition de la migration RC10 sur une copie de la sauvegarde (conteneur sans réseau). Code retour 0 = go.
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
# rc25 (TB-06) : GO = code 0 ET dernière ligne « GO » ; alors seulement le marqueur $B/rehearsal-GO est écrit (lié à la sauvegarde, à sa base, au code
# et à l'image de répétition) : 40 refuse de déployer sans lui. NO-GO ou échec : marqueur absent, ancienne version relancée (service arrêté par 20).
last_backup; same_tag; rm -f "$B/rehearsal-GO"; on_fail 'restart_old; log "NO-GO : aucun marqueur GO ; la sauvegarde $TS ne sert plus au déploiement si des données sont écrites (relancer 20)"'
R=$(mktemp -d); cleanup 'rm -rf "$R"'
same_app "$B"
(cd "$B" && sha256sum -c --quiet SHA256SUMS) || die "sauvegarde $B altérée"
cp "$B/timebilling.db" "$R/timebilling.db"
py_on_copy "$R" "$RC_IMAGE" "
import sqlite3,json,hashlib
before=sqlite3.connect('/data/timebilling.db'); before.row_factory=sqlite3.Row
orig={t:{r[1] for r in before.execute(f'PRAGMA table_info({t})')} for t in ('projects','entries','invoices','credit_notes','audit') if before.execute('SELECT 1 FROM sqlite_master WHERE name=?',(t,)).fetchone()}
snap={t:[tuple(r[k] for k in sorted(orig[t])) for r in before.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in orig}
has=lambda t: before.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',t)).fetchone()
annex0=before.execute('SELECT invoice_id,entry_id FROM invoice_annex_entries ORDER BY 1,2').fetchall() if has('invoice_annex_entries') else []
changes0=before.execute('SELECT id,entry_id,action,before_json,after_json,changed_at FROM entry_changes ORDER BY id').fetchall() if has('entry_changes') else []
snaps0={r[0] for r in before.execute('SELECT invoice_id FROM invoice_snapshots')} if has('invoice_snapshots') else set()
before.close()
import app.app as m                         # = premier démarrage RC10 : migration additive + gel des factures émises
c=sqlite3.connect('/data/timebilling.db'); c.row_factory=sqlite3.Row
ok=True
def chk(name,cond):
    global ok; ok=ok and bool(cond); print(('OK   ' if cond else 'ÉCHEC ')+name)
chk('integrity_check', c.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
chk('foreign_key_check vide', c.execute('PRAGMA foreign_key_check').fetchall()==[])
for t,rows in snap.items():
    after=[tuple(r[k] for k in sorted(orig[t])) for r in c.execute(f'SELECT * FROM {t} ORDER BY rowid')]
    if t=='audit': after=after[:len(rows)]          # l'audit reçoit seulement des lignes nouvelles
    chk(f'{t} : {len(rows)} ligne(s), colonnes d origine inchangées', after==rows)
chk('aucune facture émise sans copie figée', c.execute(\"SELECT COUNT(*) FROM invoices i LEFT JOIN invoice_snapshots s ON s.invoice_id=i.id WHERE i.status='issued' AND s.invoice_id IS NULL\").fetchone()[0]==0)
chk('empreintes des PDF figés valides', all(hashlib.sha256(p).hexdigest()==h for p,h in c.execute('SELECT pdf,pdf_sha256 FROM invoice_snapshots')))
from app import invoice_service
chk('PDF figés servis', all(invoice_service.frozen_pdf(c,i)[1] for (i,) in c.execute(\"SELECT id FROM invoices WHERE status='issued'\")))
v=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='trigger'\")]; chk(f'{len(v)} déclencheurs d immuabilité présents', 'invoice_issued_at_only_at_issue' in v and 'issued_invoice_no_update' in v)
annex1={tuple(x) for x in c.execute('SELECT invoice_id,entry_id FROM invoice_annex_entries')}; a0={tuple(x) for x in annex0}
chk(f'rc19 : {len(a0)} lien(s) d annexe conservés à l identique ; nouveaux liens uniquement pour les factures figées par cette migration ({len(annex1-a0)})', a0<=annex1 and {i for i,_ in annex1-a0}.isdisjoint(snaps0))
chk(f'rc19 : {len(changes0)} ligne(s) d historique des corrections identiques', [tuple(x) for x in c.execute('SELECT id,entry_id,action,before_json,after_json,changed_at FROM entry_changes ORDER BY id')]==[tuple(x) for x in changes0])
from app.schema_checks import rc19_problems
pb=rc19_problems(c); chk('rc19 : schéma (déclencheurs, clé retirée, écritures compilables, liens d annexe)'+(' — '+' ; '.join(pb) if pb else ''), not pb)
m.init(); chk('migration idempotente (2e passage sans erreur)', True)
chk('rc19 : schéma toujours conforme après le 2e passage', not rc19_problems(c))
print('GO' if ok else 'NO-GO'); raise SystemExit(0 if ok else 1)
" | tee "$R/rehearsal.out"
[ "$(tail -n 1 "$R/rehearsal.out")" = GO ] || die "répétition sans verdict GO"
( umask 077; go_marker > "$B/rehearsal-GO.tmp" ) && mv "$B/rehearsal-GO.tmp" "$B/rehearsal-GO"
log "marqueur GO écrit : $B/rehearsal-GO"
