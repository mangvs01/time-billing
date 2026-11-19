# RUNBOOK — recette RC25 sur le clone isolé `billing-rc25-isolated` (127.0.0.1:8093)

**À exécuter par une personne ayant accès au VPS.** La session d'audit qui a rédigé ce runbook n'a **aucun accès** au VPS : ni `/opt/time-billing-rc25-isolated`, ni démon Docker, ni port 8093
(vérifié : `ls -ld /opt/time-billing-rc25-isolated` → absent ; `docker ps` → « failed to connect to the docker API » ; `curl 127.0.0.1:8093/health` → rien). **Aucune recette n'a donc été exécutée sur le clone** ; le §6
donne l'état réel (BLOCKED) et ce qui a été prouvé ailleurs. Ne jamais lire ce runbook comme un résultat.

Version testée : branche `claude/rc25-garde-conf-sans-source` (PR #4 → #3 → #2, base `cloud/audit-20261008`). Code applicatif `app/` **identique** sur les trois PR ;
empreinte du code (méthode de `procedure/tb-common.sh::app_digest`) : `41d097488abeda82a01346810c5efa4506027fe140d0fbcc350d17ba025f4e4f` ; `requirements.lock` SHA-256 `ecac54a8ec2a27deef85b7868dcdb976bc06f0c64f1bf536b3cd9019eeb4a538` ; `VERSION="9.2-rc25"`.

## 0. Règles absolues (rappel)
Aucune écriture dans la base du staging d'origine (`/opt/time-billing-v9-staging`) ni en production (`/opt/time-billing-v9`) ; aucun merge ni déploiement ; aucune installation de garde, aucun cron, aucune sauvegarde automatique ;
**ne jamais coller de mot de passe, de clé ou de `docker inspect` dans un chat, un ticket ou un commit** ; ne lancer **aucun** `--apply` (`mandats_appliquer.py`, `appliquer_emetteur.py`), aucun script d'import.
Toute commande ci-dessous vise **uniquement** le conteneur `billing-rc25-isolated` et le dossier `/opt/time-billing-rc25-isolated`. En cas de doute sur une cible : **STOP**.

## 0 bis. Raccourci scripté (recommandé) — `tests/recette_fonctionnelle/run_clone_recette.sh`
Le script automatise §2, §3, §4 et §5.1 (Python) avec les mêmes garde-fous ; la cible est figée (`billing-rc25-isolated`, `/opt/time-billing-rc25-isolated`, 8093) et toute cible contenant `time-billing-v9` est refusée.
```bash
cd /root/rc25-recette                                              # clone git du commit testé
tests/recette_fonctionnelle/run_clone_recette.sh check             # 1. LECTURE SEULE : isolement, version, empreinte du code, préconditions (rien n'est écrit)
export E=/opt/time-billing-rc25-isolated/preuves/$(date -u +%Y%m%dT%H%M%SZ)   # même dossier pour prepare et run (le golden y est conservé)
tests/recette_fonctionnelle/run_clone_recette.sh prepare           # 2. écrit dans le CLONE : golden + mot de passe de test propre au clone + recréation du conteneur du clone
tests/recette_fonctionnelle/run_clone_recette.sh run               # 3. écrit dans le CLONE : recettes aux préconditions satisfaites (les autres : BLOCKED), restauration du golden après chacune
```
Sortie : `$E/resultats.txt` (`PASS|FAIL|BLOCKED|recette|rc|ligne RÉSULTAT`), journaux par recette, `preflight.txt`, `SHA256SUMS-preuves`. **Validation du script : uniquement en simulation locale** (faux `docker` + serveur local sur base synthétique,
`TB_SIM=1`, hors dépôt) — `check`, `prepare` et `run` y fonctionnent ; **il n'a jamais tourné sur le vrai clone**. Les lots navigateur (§5.2) et `e2e_http` (§5.3) ne sont pas automatisés par ce script.

## 1. Variables et dossier de preuves
```bash
set -euo pipefail
C=/opt/time-billing-rc25-isolated; N=billing-rc25-isolated; P=8093
REPO=/root/rc25-recette                                   # clone git en LECTURE du commit testé (git checkout <sha>) ; jamais un dossier de production
E=$C/preuves/$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$E"; chmod 700 "$C/preuves" "$E"
git -C "$REPO" rev-parse HEAD | tee "$E/commit.txt"       # attendu : le SHA annoncé du paquet RC25 testé
```

## 2. Garde-fous d'isolement (échec = STOP, ne rien lancer ; toutes ces commandes sont en lecture)
```bash
STG=/opt/time-billing-v9-staging/data/timebilling.db                      # lecture de métadonnées seulement (stat), jamais ouvert
docker ps --filter "name=^/${N}\$" --format '{{.Names}}  {{.Ports}}' | tee "$E/ps.txt"
#   attendu : "billing-rc25-isolated  127.0.0.1:8093->8000/tcp" (et aucun autre port publié)
docker inspect -f '{{range .Mounts}}{{.Source}}:{{.Destination}}{{"\n"}}{{end}}' "$N" | sed '/^$/d' | tee "$E/mounts.txt"
docker inspect -f '{{.HostConfig.Privileged}} {{.HostConfig.NetworkMode}} {{.HostConfig.PidMode}}' "$N" | tee "$E/hostconfig.txt"
fail() { echo "STOP : $*"; exit 1; }
[ "$(cat "$E/mounts.txt")" = "$C/data:/data" ] || fail "montages différents de l'unique montage attendu $C/data:/data (le staging, la production, docker.sock ou un dossier parent seraient visibles)"
[ "$(cat "$E/hostconfig.txt")" = "false bridge " ] || [ "$(cat "$E/hostconfig.txt")" = "false default " ] || fail "conteneur privilégié, réseau hôte ou PID hôte"
[ "$(readlink -f "$C/data")" = "$C/data" ] || fail "$C/data est un lien symbolique ou passe par un lien"
[ "$(stat -c %h "$C/data/timebilling.db")" = 1 ] || fail "la base du clone a plusieurs liens physiques (partagée avec une autre base ?)"
if [ -e "$STG" ]; then [ "$(stat -c %d:%i "$C/data/timebilling.db")" != "$(stat -c %d:%i "$STG")" ] || fail "la base du clone EST la base du staging (même inode)"; fi
[ "$(docker exec "$N" printenv DB_PATH)" = /data/timebilling.db ] || fail "DB_PATH inattendu dans le conteneur"
# le fichier vu DANS le conteneur est bien le fichier du clone (contenu identique octet pour octet)
H1=$(docker exec "$N" python -c "import hashlib;print(hashlib.sha256(open('/data/timebilling.db','rb').read()).hexdigest())"); H2=$(sha256sum "$C/data/timebilling.db" | cut -d' ' -f1)
[ "$H1" = "$H2" ] || fail "le fichier /data/timebilling.db du conteneur diffère du fichier du clone ($H1 ≠ $H2)"
echo "ISOLEMENT OK" | tee "$E/isolement.txt"
curl -s http://127.0.0.1:$P/health | tee "$E/health-avant.txt"     # attendu : {"status":"ok","version":"9.2-rc25"}
```
Si l'instance est en cours d'écriture entre les deux calculs de hachage, relancer ce bloc après avoir arrêté tout client (le clone n'a qu'un utilisateur : l'opérateur de la recette).

## 3. Identité du code testé (SHA / version)
```bash
D='cd %s && find . -type f ! -path "*/__pycache__/*" ! -name "*.before-*" -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64'
( eval "$(printf "$D" "$REPO/app")" ) | tee "$E/digest-depot.txt"                       # attendu : 41d097488abeda82a01346810c5efa4506027fe140d0fbcc350d17ba025f4e4f
docker exec "$N" sh -c "$(printf "$D" /app/app)" | tee "$E/digest-conteneur.txt"       # attendu : IDENTIQUE à la ligne précédente
diff -q "$E/digest-depot.txt" "$E/digest-conteneur.txt" && echo "CODE CONFORME" || echo "NO-GO : l'image ne contient pas le code testé"
```
Critère : les deux empreintes sont égales **et** `version` = `9.2-rc25`. Sinon **NO-GO** (reconstruire l'image depuis le commit testé, hors de ce runbook).

## 4. Sauvegarde « golden », mot de passe de test propre au clone, restauration entre lots
```bash
# 4.1 sauvegarde cohérente du clone (conteneur arrêté : pas de WAL en cours) — le clone seulement
docker stop "$N"
python3 -I - "$C/data/timebilling.db" "$E/golden.db" <<'PY'
import sqlite3, sys
s = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()
PY
chmod 600 "$E/golden.db"; sha256sum "$E/golden.db" | tee "$E/golden.sha256"
python3 -I -c "import sqlite3,sys; c=sqlite3.connect('file:$E/golden.db?mode=ro',uri=True); print('integrity_check =',c.execute('PRAGMA integrity_check').fetchone()[0])"   # attendu : ok
# 4.2 mot de passe PROPRE au clone (jamais celui du staging) : généré ici, jamais affiché
[ -e "$C/pw.txt" ] || { umask 077; openssl rand -hex 12 > "$C/pw.txt"; }; chmod 600 "$C/pw.txt"
# 4.3 (re)création du conteneur du clone avec ce mot de passe — mêmes options que journaux/fonc/launch_fonc.sh ; le conteneur d'origine est conservé tel quel en inspection (SECRETS : fichier 0600, ne pas diffuser)
IMG=$(docker inspect -f '{{.Image}}' "$N"); docker inspect "$N" > "$E/inspect-avant.json"; chmod 600 "$E/inspect-avant.json"
docker rm -f "$N"
docker run -d --name "$N" -p 127.0.0.1:$P:8000 -v "$C/data:/data" -e SECRET_KEY="$(openssl rand -hex 32)" -e COOKIE_SECURE=0 -e INVOICE_CHECK_WORDS= \
  -e DB_PATH=/data/timebilling.db -e ENV_LABEL=RECETTE -e APP_PASSWORD="$(cat "$C/pw.txt")" "$IMG"
for i in $(seq 1 40); do curl -sf http://127.0.0.1:$P/health >/dev/null && break; sleep 1; done; curl -s http://127.0.0.1:$P/health
# 4.4 fonction de restauration entre lots (le clone seulement)
restore_golden() { docker stop "$N" >/dev/null; rm -f "$C/data/timebilling.db-wal" "$C/data/timebilling.db-shm"; cp "$E/golden.db" "$C/data/timebilling.db"
  chown 10001:10001 "$C/data/timebilling.db"; chmod 600 "$C/data/timebilling.db"; docker start "$N" >/dev/null
  for i in $(seq 1 40); do curl -sf http://127.0.0.1:$P/health >/dev/null && return 0; sleep 1; done; echo "STOP : le clone ne redémarre pas"; return 1; }
```
Si le conteneur ne démarre pas à cause des droits : `chown -R 10001:10001 "$C/data"` (dossier du clone uniquement).

## 5. Séquence de validation (dans cet ordre ; chaque lot repart de `restore_golden`)
### 5.0 Pré-contrôle lecture seule des préconditions de données (obligatoire avant tout lot)
```bash
restore_golden
python3 -I "$REPO/tests/recette_fonctionnelle/preflight_clone.py" "$C/data/timebilling.db" --url http://127.0.0.1:$P | tee "$E/preflight.txt"
```
Preuve : tableau OK/ÉCART + SHA-256 de la base avant/après lecture **identiques** (aucune écriture). Les « ÉCART » prévisibles sont décrits au §6 ; **ne pas modifier les scripts de recette pour les faire disparaître** :
un contrôle de précondition qui échoue est consigné `FAIL (précondition de données)`, pas corrigé.

### 5.1 Lots Python (HTTP + base du clone), `CTN` = nom du conteneur
```bash
run() { local n=$1; shift; ( cd "$REPO" && env "$@" python3 tests/recette_fonctionnelle/$n.py $P "$C" ) > "$E/$n.log" 2>&1; echo "$n rc=$? $(grep '^RÉSULTAT' "$E/$n.log" || echo 'sans ligne RÉSULTAT')" | tee -a "$E/resultats.txt"; }
restore_golden; run run_pages
# chaîne ab -> cg -> dg -> extra sur UNE instance, SANS restauration entre (cg lit state-ab.json écrit par ab ; dg lit state-cg.json) ; ab n'est lançable que si ses préconditions sont satisfaites (§5.0)
restore_golden; run run_ab CTN=$N; run run_cg CTN=$N; run run_dg CTN=$N; run run_extra CTN=$N
restore_golden; run run_forecast
restore_golden; run run_entites_vides
restore_golden; run run_rc19 TB_EXPECT_VERSION=9.2-rc25
```
`run_mandats`, `run_premiere_facture`, `run_hij` : **ne pas lancer** (voir §6 : BLOCKED).

### 5.2 Lots navigateur (Node + Playwright/Chromium sur l'hôte, contre le même conteneur 8093)
Prérequis : `node -v`, `npx playwright --version`, Chromium installé (`ls ~/.cache/ms-playwright`). Chaque ligne repart de `restore_golden`. `OUT` = captures dans `$E` (pas dans le dépôt).
```bash
B="$REPO/tests/browser"; env_b="PW_FILE=$C/pw.txt BASE_URL=http://127.0.0.1:$P DB_FILE=$C/data/timebilling.db OUT=$E/ecrans OUT_DIR=$E/ecrans EXPECT_VERSION=9.2-rc25"; mkdir -p "$E/ecrans"
nav() { local f=$1; shift; ( cd "$B" && env $env_b node $f "$@" ) > "$E/$f.log" 2>&1; echo "$f $* rc=$? $(tail -2 "$E/$f.log" | tr '\n' ' ')" | tee -a "$E/resultats.txt"; }
restore_golden; nav recette-metier.js phase1; docker restart "$N" >/dev/null; sleep 5; nav recette-metier.js phase2
restore_golden; nav recette-saisies.js phase1; docker restart "$N" >/dev/null; sleep 5; nav recette-saisies.js phase2
restore_golden; nav recette-rc12.js
restore_golden; nav recette-rc14.js
restore_golden; cp "$B/releve-fictif-nuit.xlsx" "$E/"; nav recette-nuit.js
restore_golden; nav recette-minuit.js
restore_golden; nav recette-rc19.js
restore_golden; nav recette-rc23.js
restore_golden; mkdir -p "$E/ux"; cp "$B/seed-ux.js" "$E/ux/"; cp "$C/pw.txt" "$E/ux/pw.txt"; chmod 600 "$E/ux/pw.txt"     # seed-ux.js lit pw.txt dans SON dossier (copie de travail hors dépôt)
( cd "$E/ux" && BASE_URL=http://127.0.0.1:$P node seed-ux.js ) > "$E/seed-ux.log" 2>&1; nav recette-responsive.js
```
Chaque script de recette imprime sa ligne finale ; la preuve est le journal complet + le code retour.

### 5.3 HTTP de bout en bout dans le conteneur du clone
```bash
restore_golden
docker cp "$REPO/tests/e2e_http.py" "$N":/app/e2e_http.py; docker cp "$REPO/tests/e2e_rc13.py" "$N":/app/e2e_rc13.py
docker exec -e APP_PASSWORD="$(cat "$C/pw.txt")" "$N" python -W ignore /app/e2e_http.py phase1 > "$E/e2e_phase1.log" 2>&1; echo "e2e phase1 rc=$?"
docker restart "$N" >/dev/null; sleep 5
docker exec -e APP_PASSWORD="$(cat "$C/pw.txt")" "$N" python -W ignore /app/e2e_http.py phase2 > "$E/e2e_phase2.log" 2>&1; echo "e2e phase2 rc=$?"
```
Le test de **concurrence** (`concurrency_http.py`) suppose une base vide (28 saisies, 2 brouillons) : **BLOCKED sur ce clone** (2 247 saisies) — il exige un second conteneur jetable sur base vide, hors du périmètre « un seul clone »
(décision du propriétaire, §8). `e2e_rc13.py` : même conteneur, après `restore_golden` (vérifier son en-tête).

### 5.4 Contrôle final et collecte
```bash
curl -s http://127.0.0.1:$P/health | tee "$E/health-apres.txt"
sha256sum "$E"/*.log "$E"/resultats.txt > "$E/SHA256SUMS-preuves"
restore_golden                      # le clone retrouve son état d'origine
docker stop "$N" >/dev/null     # fichier au repos (le démarrage de l'application peut réécrire des octets sans changer les données)
python3 -I "$REPO/outils/empreinte_metier.py" comparer "$E/golden.db" "$C/data/timebilling.db"; echo "comparer rc=$?"     # attendu : rc=0 (toutes les tables métier identiques) — comparaison LOGIQUE, pas d'octets
python3 -I -c "import sqlite3; c=sqlite3.connect('file:$C/data/timebilling.db?mode=ro',uri=True); print('integrity_check =', c.execute('PRAGMA integrity_check').fetchone()[0])"; docker start "$N" >/dev/null
```
Preuves à conserver (hors dépôt, `0700`) : `commit.txt`, `digest-*.txt`, `preflight.txt`, tous les `*.log`, `resultats.txt`, `SHA256SUMS-preuves`, `health-*.txt`.

## 6. État réel et attendus par recette (colonne « attendu » = ce qui est connu AVANT exécution)
| Recette | Statut dans cette session | Cause / prérequis exact | Attendu sur le clone (référence rc24 → rc25) |
|---|---|---|---|
| `run_pages.py` | **BLOCKED** (pas d'accès VPS) | clone + mot de passe de test | 3/3 (lecture seule) |
| `run_ab.py` | **BLOCKED** ; **précondition probablement en écart** | ligne 12 exige `(2247, 24, (1 facture, 0 émise, 0 numérotée))` ; le clone annoncé a **0 facture** | réf. rc24 57/57 ; sur le clone : 1 FAIL de précondition attendu, le reste à comparer au détail |
| `run_cg.py` | **BLOCKED** | `CTN=billing-rc25-isolated` (`docker exec`) ; **lit `state-ab.json` écrit par `run_ab`** : inexécutable sans `run_ab` (constaté en simulation : `FileNotFoundError state-ab.json`) | 101/101 (recette adaptée RC25) |
| `run_dg.py` | **BLOCKED** | suite de `run_cg` (même instance) ; DH5/DH9 comparent l'empreinte des 2 247 saisies | réf. 53/53 ; en synthétique 51/53 pour la seule raison des données réelles |
| `run_extra.py` | **BLOCKED** | idem | 25/25 (adapté RC25) |
| `run_forecast.py` | **BLOCKED** | copie fraîche ; modifie des paramètres de mandats **en SQL sur le clone** (autorisé : clone) | réf. 21/21 |
| `run_entites_vides.py` | **BLOCKED** | mandats « PCR LV 2026 », « STC GEM Oct - DM job », « MSD », « NHAF 2026 », « EUROPCR 2027 », « ECIO 2025 » avec les valeurs C2/C3 ; émet 2,66 j sur ECIO (clôturé) | réf. 18/18 ; **point d'attention RC25** : contrôle 14 non dérogeable et tolérance 0 — un refus « surfacturation » à la place du refus « entité » est possible ; à classer, jamais à assouplir |
| `run_rc19.py` | **BLOCKED** ; **précondition probablement en écart** | R0a exige 24 mandats dont **19 clôturés** et **1 brouillon** ; clone : 0 facture, clôtures inconnues | réf. 49/49 ; R0a FAIL attendu si ces états diffèrent |
| `run_mandats.py` | **BLOCKED** | exige 19 clôtures produites par `mandats_appliquer.py --close-termine --apply` : **interdit** | non exécutable sans autorisation d'un `--apply` sur le clone (décision §8) |
| `run_premiere_facture.py` | **BLOCKED** | exige `mandats_appliquer.py --level certain` déjà appliqué (**interdit**) **et** `Facture-reelle-reference-2026-09.pdf` (absent du dépôt) | non exécutable |
| `run_hij.py` | **BLOCKED** | exige `/root/Time sheet CP.xlsx`, `journaux/fonc/launch_fonc.sh`, 2 conteneurs supplémentaires (restauration 8301, import 8302) hors périmètre 8093 ; scripts d'import | non exécutable |
| Navigateur : métier, saisies, rc12, rc14, nuit, minuit, rc19, rc23, responsive | **BLOCKED** | Node + Playwright + Chromium sur le VPS (inconnu) | réf. rc24 : métier 107+15, saisies 36+8, rc12 22, rc14 56, nuit 34, minuit 15, rc19 37, responsive 33 ; RC25 : saisies 44, métier 122 (cumulé) |
| `recette-verrou-import.js` | **BLOCKED** | exige `preparer-copie-verrou-import.py` (prépare une copie d'import) : effets d'import → **non lancé** | — |
| `e2e_http.py` phases 1+2, `e2e_rc13.py` | **BLOCKED** | `docker cp` dans le clone | réf. 30+18 et 5 |
| `concurrency_http.py` | **BLOCKED** (périmètre) | base vide requise | réf. 11/11 |

**Ce qui a été réellement exécuté dans cette session (hors clone, base synthétique jetable, pas équivalent) :** suite unitaire complète `645 tests OK (expected failures=5)`, dont `tests/test_rc25.py` (29 tests B-01..B-06) ;
recettes navigateur et fonctionnelles du commit `6de4526` sur base synthétique (`RAPPORT-RC25.md`, `app/` inchangé depuis) ; `preflight_clone.py` validé sur une base synthétique (SHA-256 avant/après identiques).

### Anomalies connues avant exécution (classées)
| Gravité | Anomalie | Preuve | Statut |
|---|---|---|---|
| BLOQUANT recette | Aucune recette n'a été exécutée sur le clone (accès VPS absent de l'environnement d'audit) | §6 | à faire par une personne ayant accès |
| ÉLEVÉE | Préconditions de `run_ab`, `run_rc19`, `run_hij` incompatibles avec « 0 facture » (attendent 1 brouillon n°1 ; rc19 : 19 clôtures) | lecture des scripts (`run_ab.py:12`, `run_rc19.py:32`, `run_hij.py:23`) | décision §9.4 |
| ÉLEVÉE | `run_mandats`, `run_premiere_facture`, `run_hij` non exécutables sans `--apply` / fichiers externes / conteneurs supplémentaires | §6 | décisions §9.1–9.3 |
| MOYENNE | Garde de production : auto-attestation, TOCTOU après vérification, `LD_PRELOAD` avant `env -i` — corrigés seulement par l'architecture B (vérificateur statique signé), non implémentée | `CONCEPTION-GARDE-CONFIANCE-RC25.md`, 4 `expectedFailure` | décision distincte (option B validée par le propriétaire, implémentation à venir) ; ne conditionne pas la recette fonctionnelle |
| FAIBLE | `SHELLOPTS=xtrace` exposait les commandes développées : **corrigé** (refus dans le contrôle d'environnement), test de régression `test_shellopts_in_the_environment_is_refused_before_any_command` | `tests/test_procedure_residuel.py` | corrigé et testé |
| FAIBLE | Chiffres périmés dans les descriptions des PR #2/#3/#4 (571/595/610 tests) | suite actuelle : 645 tests, 5 échecs attendus | à actualiser par le propriétaire (aucune modification de PR faite ici) |
| FAIBLE | `pyflakes app` : 3 imports inutilisés, 1 f-string sans variable | exécuté | non corrigé (sans effet fonctionnel) |

## 7. Critères d'acceptation (GO / NO-GO pour proposer le staging)
GO **seulement si tous** :
1. §2 `ISOLEMENT OK` ; §3 `CODE CONFORME` + version `9.2-rc25` ; `golden` en `integrity_check = ok`.
2. §5.0 : SHA-256 de la base identique avant/après lecture.
3. Chaque lot §5.1–5.3 exécuté jusqu'au bout (code retour 0 **ou** FAIL expliqués), **aucun** FAIL qui ne soit ni une précondition de données documentée (§6) ni accepté par écrit ; zéro erreur console navigateur.
4. Aucun FAIL touchant B-01..B-06 : contrôle 14 refusé sans motif, réémission après crédit intégral seulement, tolérance 0, reliquat borné, propriété des saisies.
5. Retour à l'état d'origine vérifié (§5.4 : `outils/empreinte_metier.py comparer` golden/clone = rc 0, `integrity_check = ok` ; ne pas comparer les octets : le démarrage de l'application peut réécrire le fichier — constaté en simulation).
6. Preuves archivées (§5.4) et SHA-256 des journaux notés.
NO-GO dès qu'un critère manque, qu'une commande a visé un chemin hors clone, ou qu'un résultat ne peut pas être prouvé.

## 8. Rollback
* **Pendant la recette** : `restore_golden` (§4.4) ramène le clone à l'état sauvegardé en < 1 min. Le staging d'origine et la production ne sont jamais concernés.
* **Conteneur recréé en §4.3** : l'ancienne configuration est dans `$E/inspect-avant.json` (secrets : ne pas diffuser) ; l'image est la même (`$IMG`) ; pour revenir à un clone « tel que trouvé » : `docker rm -f "$N"` puis `docker run` avec les mêmes options et l'ancien mot de passe connu du seul propriétaire.
* **Fin de session** : `restore_golden`, puis laisser le clone arrêté (`docker stop "$N"`) ou le supprimer seulement sur décision du propriétaire.

## 9. Décisions du propriétaire encore nécessaires pour compléter la recette sur le clone
1. Autoriser (ou non) **`mandats_appliquer.py --level certain --close-termine --apply` sur le CLONE** (jamais sur le staging) : prérequis de `run_mandats`, `run_premiere_facture`, `run_rc19` (19 clôtures).
2. Fournir `Facture-reelle-reference-2026-09.pdf` et `/root/Time sheet CP.xlsx` (hors dépôt) pour `run_premiere_facture` et `run_hij`, et autoriser deux conteneurs supplémentaires jetables (8301/8302) pour `run_hij`.
3. Autoriser un second conteneur jetable sur **base vide** pour `concurrency_http.py`.
4. Confirmer l'état attendu du clone : « 0 facture » (annoncé) ou « 1 brouillon n°1 » (attendu par `run_ab`, `run_rc19`, `run_hij`) — ou valider l'adaptation documentée de ces préconditions.

## 10. Étape suivante — staging réel (seulement après GO du §7 et décision écrite du propriétaire)
Séquence inchangée de `PROCEDURE-DEPLOIEMENT-RC11.md` / `PROCEDURE-ROLLBACK-RC11.md` et `RECETTE-STAGING-RC25.md` : copie de publication figée de `9.2-rc25` (`git archive <sha>`), `SOURCE_APP`/`SOURCE_REQ`/`RC_IMAGE` changés ensemble dans `staging.conf` **et** `prod.conf`, chaîne `00 → 30` du staging, sauvegarde `20-backup.sh` avant `40-deploy.sh`, retour arrière `90-rollback.sh`.
La garde de production proposée (PR #3/#4) et la sauvegarde quotidienne sont **une décision distincte** et ne conditionnent pas ce paquet fonctionnel.
