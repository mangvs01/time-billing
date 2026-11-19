#!/bin/bash
# 6. Retour arrière : base d'avant migration, arborescence d'origine, image d'origine. (Exporter d'abord les données
#    saisies depuis le déploiement : elles ne sont pas dans la sauvegarde.)
# rc25 (revue adverse) : AVANT tout le reste, uniquement des mots-clés bash (aucune commande qu'une fonction exportée pourrait masquer). Hors « bash -p », refus si
# l'environnement porte des fonctions exportées ou BASH_ENV ; ${…:?} termine le shell sans appeler « exit ». Voir RAPPORT-GARDE-PRODUCTION-RC25.md.
[[ $- == *p* ]] || { { [[ -r /proc/self/environ ]] && _e=$(< /proc/self/environ); } 2>/dev/null && [[ $_e != *BASH_FUNC_* && $_e != *BASH_ENV=* && $_e != *SHELLOPTS=* ]] || : "${BASH_SOURCE[999]:?ARRÊT : environnement non sûr (fonction exportée, BASH_ENV ou /proc illisible) : relancer par /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin /bin/bash -p <script>}"; }
_d=.; [[ $0 == */* ]] && _d=${0%/*}
. "$_d/tb-common.sh" || : "${BASH_SOURCE[999]:?ARRÊT : garde de production (tb-common.sh) introuvable ou en erreur : rien ne s exécute}"
# sauvegarde par horodatage : celle du dernier déploiement fait par 40 (« deployed »), sinon la dernière de 20 — retour possible même si la VERSION
# du dépôt a changé depuis, et un 20 relancé pour une autre version sans 40 ne change pas la cible du retour (relecture adverse)
if [ -f "$BACKUP_BASE/deployed" ]; then last_backup "$BACKUP_BASE/deployed"; else last_backup; fi
[ "$BTAG" = "$RC_TAG" ] || log "NB : le dépôt est maintenant en $VERSION ; retour arrière du déploiement $BTAG (sauvegarde $TS)"
(cd "$B" && sha256sum -c --quiet SHA256SUMS) || die "sauvegarde altérée : ne pas poursuivre"
rollback_image          # rc25 (TB-06) : image de retour présente (ou rechargée depuis la sauvegarde) AVANT tout arrêt du service
# rc25 (TB-06) : écarter des données exige ABANDONNER_CORRECTIONS=OUI-<TS de CE déploiement> ; un « OUI » resté exporté d'un retour précédent
# ne vaut plus pour un autre déploiement
ABANDON=0; [ "${ABANDONNER_CORRECTIONS:-}" = "OUI-$TS" ] && ABANDON=1
[ -n "${ABANDONNER_CORRECTIONS:-}" ] && [ "$ABANDON" = 0 ] && die "ABANDONNER_CORRECTIONS=${ABANDONNER_CORRECTIONS} ne correspond pas à ce déploiement : la valeur attendue est OUI-$TS"
# rc19 : la base vivante est d'abord copiée (vérifiée) ; le retour est refusé s'il écarterait des données écrites depuis le déploiement
# (corrections, décisions, nouvelles saisies, factures et brouillons, notes de crédit, factures historiques, mandats modifiés), sauf
# ABANDONNER_CORRECTIONS=OUI-<TS> (rc25 ; après export : la copie ci-dessous les contient).
# G4 : le dossier de copie porte l'heure du RETOUR (pas celle du déploiement) et n'est jamais réutilisé : relancer le script après un retour
# partiel ne peut plus écraser l'unique copie des données écrites depuis le déploiement par la base déjà restaurée.
RB=$(date -u +%Y%m%dT%H%M%SZ); ECARTE="$BACKUP_BASE/ecarte-$TS-retour-$RB"
[ -e "$ECARTE" ] && die "dossier de copie déjà présent ($ECARTE) : relancer dans une seconde"
mkdir -p "$ECARTE"; chmod 700 "$ECARTE"; KEEP="$ECARTE/timebilling-avant-retour.db"
python3 - "$ROOT/data/timebilling.db" "$KEEP" <<'PY' || die "copie de la base vivante impossible : retour arrière non effectué"
import sqlite3, sys
s = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d)
assert d.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; d.close(); s.close()
PY
chmod 600 "$KEEP"; (cd "$(dirname "$KEEP")" && sha256sum "$(basename "$KEEP")" > "$(basename "$KEEP").sha256")
log "base vivante copiée avant retour : $KEEP (sha $(cut -c1-12 "$KEEP.sha256"))"
DEP=$(sed -E 's/^([0-9]{4})([0-9]{2})([0-9]{2})T([0-9]{2})([0-9]{2})([0-9]{2})Z$/\1-\2-\3T\4:\5:\6/' <<<"$TS")
# ce que le retour arrière écarterait : lignes de tables métier absentes de la sauvegarde (par identifiant) + lignes déjà présentes dont une valeur
# a changé ou supprimées (elles réapparaîtraient), dans TOUTES ces tables. 2026-10-07 (répétition E) : seules les saisies et les mandats étaient comparés — valider les
# factures historiques, modifier un brouillon ou un paramètre émetteur après le déploiement était écarté sans avertissement. Tables sans « id »
# (paramètres, copies figées, annulations de notes de crédit) : toute ligne absente de la sauvegarde à l'identique. La journalisation d'audit et les sessions ne comptent pas (bruit de connexion).
# 2026-10-07 (répétition production F, V9.0 → rc21) : les tables et colonnes AJOUTÉES par la migration n'existent pas dans la sauvegarde. Avant :
# tables nouvelles = toutes leurs lignes « ajoutées » (retour refusé juste après le déploiement : copies figées et liens d'annexe créés par la
# migration elle-même) et colonnes nouvelles jamais comparées (une valeur saisie après le déploiement dans une colonne ajoutée aurait été écartée
# sans avertissement). Désormais elles sont comparées à la sauvegarde MIGRÉE par l'image déployée, deux fois : les colonnes qui diffèrent entre les
# deux migrations sont recalculées par la migration (horodatage et PDF des copies figées) — leurs lignes sont comptées, pas leur contenu.
# Copie migrée impossible : comportement d'avant (refus, prudent). La copie est migrée avec l'environnement NON secret du conteneur déployé
# (libellé, numérotation…) et ses polices (lecture seule) ; journal de la migration dans le dossier de copie (relecture adverse).
MIG=$(mktemp -d); cleanup 'rm -rf "$MIG"'
IMG=$(docker inspect "$CONTAINER" --format '{{.Image}}' 2>/dev/null || true)
( umask 077; docker inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
  | grep -E '^[A-Za-z_][A-Za-z0-9_]*=' | grep -vE '^(PATH|HOME|HOSTNAME|DB_PATH|[A-Z0-9_]*(PASSWORD|SECRET|KEY|HASH|TOKEN)[A-Z0-9_]*)=' > "$MIG/env" ) || true
FONTS=(); [ -d "$ROOT/data/fonts" ] && FONTS=(-v "$ROOT/data/fonts:/data/fonts:ro")
migre() { mkdir -p "$MIG/$1" && cp "$B/timebilling.db" "$MIG/$1/timebilling.db" && docker run --rm --user 0:0 --network none --env-file "$MIG/env" \
  -v "$MIG/$1:/data" "${FONTS[@]}" -e DB_PATH=/data/timebilling.db -e SECRET_KEY="$(openssl rand -hex 32)" -e APP_PASSWORD="$(openssl rand -hex 16)" \
  -e COOKIE_SECURE=0 -w /app "$IMG" python -c 'import app.app' > "$ECARTE/migration-copie-$1.log" 2>&1; }
if [ -n "$IMG" ] && migre m1 && sleep 1 && migre m2; then M1="$MIG/m1/timebilling.db"; M2="$MIG/m2/timebilling.db"; log "sauvegarde migrée par l'image déployée (${IMG:7:12}) : référence des tables et colonnes ajoutées"
else M1=""; M2=""; log "copie migrée de la sauvegarde impossible (image : ${IMG:-aucune} ; journal : $ECARTE/migration-copie-m*.log) : tables et colonnes ajoutées par la migration comptées comme données nouvelles. Si le déploiement a échoué avant toute saisie (service jamais ouvert), ABANDONNER_CORRECTIONS=OUI-$TS n'écarte rien d'utile"
  [ -f "$ECARTE/migration-copie-m1.log" ] && tail -n 5 "$ECARTE/migration-copie-m1.log" | sed 's/^/    /'; fi
ecartees() { python3 - "$KEEP" "$B/timebilling.db" "$M1" "$M2" <<'PY'
import sqlite3, sys
live = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); live.execute("ATTACH DATABASE ? AS o", (f"file:{sys.argv[2]}?mode=ro",))
mig = bool(sys.argv[3])
if mig:
    live.execute("ATTACH DATABASE ? AS m", (f"file:{sys.argv[3]}?mode=ro",)); live.execute("ATTACH DATABASE ? AS m2", (f"file:{sys.argv[4]}?mode=ro",))
cols = lambda db, t: [r[1] for r in live.execute(f"PRAGMA {db}.table_info({t})")]
tabs = lambda db: {r[0] for r in live.execute(f"SELECT name FROM {db}.sqlite_master WHERE type='table'")}
cnt = lambda q: live.execute(f"SELECT COUNT(*) FROM ({q})").fetchone()[0]
qi = lambda cl: ",".join(f"[{x}]" for x in cl)     # noms de colonnes entre crochets : une future colonne « order » ou « default » reste valide
def compare(t, ref, cl, out, quoi=""):
    """lignes de main.t ajoutées / modifiées / supprimées par rapport à ref.t, sur les colonnes cl"""
    c = qi(cl) or "NULL"     # aucune colonne comparable : seules les lignes (identifiants) comptent
    if "id" in cols("main", t) and "id" in cols(ref, t):
        n = cnt(f"SELECT 1 FROM main.{t} WHERE id NOT IN (SELECT id FROM {ref}.{t})")
        if n: out.append(f"{t} : {n} ligne(s) ajoutée(s)")
        n = cnt(f"SELECT {c} FROM main.{t} WHERE id IN (SELECT id FROM {ref}.{t}) EXCEPT SELECT {c} FROM {ref}.{t}")
        if n: out.append(f"{t} : {n} ligne(s) modifiée(s){quoi}")
        n = cnt(f"SELECT 1 FROM {ref}.{t} WHERE id NOT IN (SELECT id FROM main.{t})")
        if n: out.append(f"{t} : {n} ligne(s) supprimée(s) (réapparaîtraient)")
    else:
        n = cnt(f"SELECT {c} FROM main.{t} EXCEPT SELECT {c} FROM {ref}.{t}")
        if n: out.append(f"{t} : {n} ligne(s) ajoutée(s) ou modifiée(s){quoi}")
        n = cnt(f"SELECT {c} FROM {ref}.{t} EXCEPT SELECT {c} FROM main.{t}")
        if n: out.append(f"{t} : {n} ligne(s) supprimée(s) ou modifiée(s) (ancienne valeur réapparaîtrait){quoi}")
out, recalc = [], []
# rc25 (TB-06) : TOUTES les tables sont comparées, sauf les tables transitoires nommées ici ; une table métier future (absente d'une liste fixe)
# était écartée sans avertissement. L'audit n'empêche pas le retour (bruit de connexion) mais ses lignes mises de côté sont comptées (ci-dessous).
TRANSITOIRES = {"audit", "web_sessions", "login_failures", "kept_forms", "auth_credentials"}   # BMDP1 : mot de passe changé dans l'application, propre à chaque environnement
for t in sorted(x for x in tabs("main") if x not in TRANSITOIRES and not x.startswith("sqlite_")):
    old = t in tabs("o")
    base = [c for c in cols("main", t) if old and c in cols("o", t)]
    neuves = [c for c in cols("main", t) if c not in base]            # table ou colonnes ajoutées par la migration
    if old: compare(t, "o", base, out)
    if not neuves: continue
    if not (mig and t in tabs("m") and t in tabs("m2") and all(c in cols("m", t) and c in cols("m2", t) for c in neuves)):
        n = cnt(f"SELECT 1 FROM main.{t}")
        if not old and n: out.append(f"{t} : {n} ligne(s) ajoutée(s) (table absente de la sauvegarde ; copie migrée indisponible)")
        elif old: out.append(f"{t} : colonnes ajoutées par la migration non vérifiables ({', '.join(neuves)} ; copie migrée indisponible)")
        continue
    vol = [c for c in cols("main", t) if c in cols("m", t)
           and cnt(f"SELECT [{c}] FROM m.{t} EXCEPT SELECT [{c}] FROM m2.{t}") + cnt(f"SELECT [{c}] FROM m2.{t} EXCEPT SELECT [{c}] FROM m.{t}")]
    if vol: recalc.append(f"{t}({','.join(vol)})")
    cl = [c for c in neuves if c not in vol]
    if old and "id" in base:   # colonnes ajoutées, lignes déjà présentes dans la sauvegarde (les lignes ajoutées sont comptées ci-dessus)
        if cl:
            n = cnt(f"SELECT id,{qi(cl)} FROM main.{t} WHERE id IN (SELECT id FROM o.{t}) EXCEPT SELECT id,{qi(cl)} FROM m.{t}")
            if n: out.append(f"{t} : {n} ligne(s) modifiée(s) (colonnes ajoutées par la migration)")
    else:                      # table ajoutée par la migration, ou table sans « id » ayant reçu des colonnes : comparaison complète à la sauvegarde migrée
        compare(t, "m", [c for c in cols("main", t) if c in cols("m", t) and c not in vol], out, " (par rapport à la sauvegarde migrée)")
if recalc: print("colonnes recalculées par la migration (lignes comparées, contenu non comparé) : " + " ".join(recalc), file=sys.stderr)
if "audit" in tabs("main"):
    n = cnt("SELECT 1 FROM main.audit" + (" WHERE id NOT IN (SELECT id FROM o.audit)" if "audit" in tabs("o") else ""))
    if n: print(f"journal d'audit : {n} ligne(s) postérieure(s) à la sauvegarde mises de côté (conservées dans la copie de la base vivante)", file=sys.stderr)
print(len(out) and "; ".join(dict.fromkeys(out)) or 0)
PY
}
N=$(ecartees) || die "comparaison avec la sauvegarde impossible : retour arrière non effectué (service inchangé)"
if [ "$N" != 0 ] && [ "$ABANDON" != 1 ]; then
  die "des données écrites depuis la sauvegarde du déploiement ($DEP) seraient écartées par le retour arrière : $N. Copie conservée : $KEEP. Les exporter (sauvegarde JSON) puis relancer avec ABANDONNER_CORRECTIONS=OUI-$TS."
fi
compose stop || true
on_fail restart_old     # rc25 (TB-06) : jusqu'au remplacement de l'arborescence, un échec relance le service tel qu'il était (rien n'est modifié)
python3 - "$ROOT/data/timebilling.db" "$KEEP" <<'PY' || die "copie finale de la base vivante impossible : retour arrière interrompu (service arrêté, base inchangée)"
import sqlite3, sys   # copie finale, service arrêté : rien n'a pu être écrit entre-temps
s = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d)
assert d.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; d.close(); s.close()
PY
(cd "$(dirname "$KEEP")" && sha256sum "$(basename "$KEEP")" > "$(basename "$KEEP").sha256")
# 2026-10-07 (relecture adverse) : la comparaison ci-dessus est faite service EN MARCHE ; une écriture faite pendant le calcul ou pendant l'arrêt
# (requêtes terminées par gunicorn) aurait été écartée sans avertissement. Elle est refaite ici sur la copie finale, service arrêté.
N=$(ecartees) || die "comparaison finale impossible : retour arrière non effectué, service relancé"
if [ "$N" != 0 ] && [ "$ABANDON" != 1 ]; then
  die "données écrites pendant l'arrêt, qui seraient écartées par le retour arrière : $N. Service relancé, rien restauré. Copie : $KEEP. Exporter puis relancer avec ABANDONNER_CORRECTIONS=OUI-$TS."
fi
[ "$N" != 0 ] && log "ABANDONNER_CORRECTIONS=OUI-$TS : données écartées par le retour arrière : $N — copie vérifiée de la base vivante : $KEEP (sha $(cut -c1-12 "$KEEP.sha256"))"
on_fail 'log "ATTENTION : retour arrière interrompu après l'"'"'arrêt : service ARRÊTÉ ; fichiers déplacés et base vivante (copie vérifiée) dans $ECARTE ; sauvegarde $B"'
compose rm -f >/dev/null 2>&1 || true
for f in app docker-compose.yml .env requirements.txt requirements.lock .dockerignore Dockerfile; do [ -e "$ROOT/$f" ] && mv "$ROOT/$f" "$ECARTE/"; done
tar -C "$(dirname "$ROOT")" -xzf "$B/tree.tar.gz" "$(basename "$ROOT")/app" "$(basename "$ROOT")/docker-compose.yml" "$(basename "$ROOT")/requirements.txt" "$(basename "$ROOT")/Dockerfile"
# listing kept in a variable: "tar | grep -q" fails under pipefail (SIGPIPE) and silently skipped .env (found by the dry run)
LIST=$(tar -tzf "$B/tree.tar.gz")
# G4 : tout fichier d'origine déplacé ci-dessus est restauré s'il figure dans la sauvegarde (requirements.lock et .dockerignore ne l'étaient pas :
# un « docker compose build » de l'arborescence restaurée échouait)
for f in .env requirements.lock .dockerignore; do
  if grep -qx "$(basename "$ROOT")/$f" <<<"$LIST"; then tar -C "$(dirname "$ROOT")" -xzf "$B/tree.tar.gz" "$(basename "$ROOT")/$f"; log "$f d'origine restauré"; fi
done
cp -p "$B/timebilling.db" "$ROOT/data/timebilling.db"; rm -f "$ROOT/data/timebilling.db-wal" "$ROOT/data/timebilling.db-shm" "$ROOT/data/timebilling.db-journal"
[ "$(sha256sum < "$ROOT/data/timebilling.db")" = "$(sha256sum < "$B/timebilling.db")" ] || die "base restaurée différente de la sauvegarde"
rollback_image; docker tag "$IMAGE:pre-${BTAG}-$TS" "$IMAGE:latest"
# refuse to start the previous version without its secrets (V9.0 would fall back to its built-in default password)
CFG=$(compose config 2>&1 || true)          # variable : "cmd | grep -q" échoue sous pipefail (SIGPIPE) et laisserait démarrer l'ancienne version sans secrets
if grep -q 'variable is not set' <<<"$CFG"; then die "secrets de l'ancienne version manquants : ne pas démarrer"; fi
compose up -d --no-build
wait_health || die "l'ancienne version ne répond pas"
on_fail ""
log "retour arrière effectué — santé : $(health) ; base = sauvegarde $TS (SHA-256 identique)"
