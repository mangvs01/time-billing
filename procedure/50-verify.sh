#!/bin/bash
# 5. Vérifications après déploiement, puis redémarrage et nouvelle vérification.
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
last_backup; same_tag; fail=0
chk() { if eval "$2"; then log "OK    $1"; else log "ÉCHEC $1"; fail=1; fi; }
run_checks() {
  chk "santé $VERSION" '[[ "$(health)" == *"$VERSION"* ]]'
  chk "page de connexion 200" '[ "$(curl -s -o /dev/null -w %{http_code} "$URL/login")" = 200 ]'
  chk "en-têtes de sécurité" 'h=$(curl -sI "$URL/login"); grep -qi "content-security-policy" <<<"$h" && grep -qi "x-frame-options: DENY" <<<"$h"'   # variable : "cmd | grep -q" échoue sous pipefail (SIGPIPE)
  chk "serveur gthread (pas de blocage par connexions lentes)" 'for _ in 1 2 3 4 5 6 7 8 9 10; do L=$(docker logs "$CONTAINER" 2>&1); grep -q "Using worker: gthread" <<<"$L" && break; sleep 1; done; grep -q "Using worker: gthread" <<<"$L"'
  chk "page Saisies protégée (redirection vers la connexion)" '[ "$(curl -s -o /dev/null -w %{http_code} "$URL/entries")" = 302 ]'
  chk "archive ZIP protégée" '[ "$(curl -s -o /dev/null -w %{http_code} "$URL/archive.zip")" = 302 ]'
  chk "service non privilégié (uid 10001)" '[ "$(docker exec "$CONTAINER" id -u)" = 10001 ]'
  chk "système de fichiers en lecture seule, aucune capacité, no-new-privileges" '[ "$(docker inspect "$CONTAINER" --format "{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.HostConfig.SecurityOpt}}")" = "true [ALL] [no-new-privileges:true]" ]'
  chk "CSP : scripts sans unsafe-inline, avec nonce" 'csp=$(curl -sI "$URL/login" | grep -i "^content-security-policy"); grep -q "script-src .self. .nonce-" <<<"$csp" && ! grep -o "script-src[^;]*" <<<"$csp" | grep -q unsafe-inline'
  chk "écoute locale uniquement" '[ -z "$(docker port "$CONTAINER" | grep -v "127.0.0.1:")" ]'
  docker exec -i "$CONTAINER" python -c "
import sqlite3,json,hashlib
c=sqlite3.connect('/data/timebilling.db')
before=json.load(open('/dev/stdin'))
t=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]
assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok', 'integrity'
assert c.execute('PRAGMA foreign_key_check').fetchall()==[], 'fk'
for x in ('projects','entries','invoices','credit_notes','historical_invoices','invoice_snapshots','entry_changes','credit_operations','credit_note_snapshots',
          'credit_note_cancellations','invoice_variance_decisions','invoice_date_changes','import_batches','import_batch_rows','settings'):   # 2026-10-07 : + tables de notes de crédit, imports, paramètres
    if x in before: assert c.execute(f'SELECT COUNT(*) FROM {x}').fetchone()[0]==before[x], x
$DIGEST_PY
for k,(x,cols,o) in DIGESTS.items():      # G4 : saisies, factures / brouillons, mandats, paramètres identiques ligne à ligne à la sauvegarde d'avant déploiement
    if k in before: assert digest(c,x,before.get(k+'_cols') or cols or table_cols(c,x),o)==before[k], k+' : contenu différent de la sauvegarde'
if 'historical_invoices' not in before: assert c.execute('SELECT COUNT(*) FROM historical_invoices').fetchone()[0]==0, 'registre non vide au déploiement'
assert c.execute(\"SELECT COUNT(*) FROM invoices i LEFT JOIN invoice_snapshots s ON s.invoice_id=i.id WHERE i.status='issued' AND s.invoice_id IS NULL\").fetchone()[0]==0, 'snapshots'
assert all(hashlib.sha256(p).hexdigest()==h for p,h in c.execute('SELECT pdf,pdf_sha256 FROM invoice_snapshots')), 'pdf sha'
assert {'entry_changes','web_sessions'} <= set(t), 'tables RC10'
from app.schema_checks import rc19_problems
p=rc19_problems(c); assert not p, 'schema rc19 : '+' ; '.join(p)
" < "$B/counts-before.json" && log "OK    base : intégrité, effectifs, empreintes saisies/factures/mandats/paramètres, copies figées, schéma rc19+G4" || { log "ÉCHEC base"; fail=1; }
  chk "secrets absents des journaux du conteneur" 'L=$(docker logs "$CONTAINER" 2>&1); ! grep -qiE "SECRET_KEY=|APP_PASSWORD(_HASH)?=|scrypt:" <<<"$L"'
}
run_checks
docker restart "$CONTAINER" >/dev/null; wait_health || { log "ÉCHEC redémarrage"; exit 1; }
log "après redémarrage :"; run_checks
[ $fail = 0 ] && log "VÉRIFICATIONS CONFORMES" || die "au moins un contrôle en échec : exécuter 90-rollback.sh"
