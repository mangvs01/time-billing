#!/bin/bash
# Test contrôlé du superviseur avec un faux claude (aucun jeton consommé), temps accéléré (1 min = 0,1 s).
D=$(cd "$(dirname "$0")" && pwd); R=${R:-/tmp/claude-0/-root/bc1e5850-4039-4def-b7dc-79de6ca9fdb6/scratchpad/sup-tests}; rm -rf $R; mkdir -p $R
F=0; ok(){ echo "OK    $1"; }; ko(){ echo "ÉCHEC $1"; F=$((F+1)); }
run() { # nom scénario [env supplémentaires...]
  local name=$1 sc=$2; shift 2; local S=$R/$name; mkdir -p $S/logs
  env SUP_STATE_DIR=$S SUP_CONT=$S/CONTINUATION.md CLAUDE_BIN=$D/faux-claude.sh FAUX_SCENARIO=$sc FAUX_COMPTEUR=$S/compteur FAUX_STATE=$S \
      SUP_TIME_SCALE=600 SUP_RESET_IN_S=1200 SUP_DEADLINE_IN_S=360000 "$@" python3 $D/../superviseur.py > $S/sortie.txt 2>&1
  echo $? > $S/rc; }
calls(){ cat $R/$1/compteur 2>/dev/null || echo 0; }
st(){ jq -r "$2" $R/$1/ETAT-SUPERVISEUR.json; }

run t1 succes_marqueur
[ "$(calls t1)" = 1 ] && [ "$(st t1 .reason)" = "fin normale de Claude" ] && ok "1. arrêt propre détecté, aucune relance (1 lancement)" || ko "1. arrêt propre ($(calls t1) lancements, $(st t1 .reason))"
grep -q "Arrêt automatique n° 1" $R/t1/CONTINUATION.md && grep -q "Branche : \`design-liquid-glass-rc14\`" $R/t1/CONTINUATION.md && grep -q "dernier commit" $R/t1/CONTINUATION.md \
  && ok "2. contexte sauvegardé (section d'arrêt : cause, branche, commit, état git)" || ko "2. contexte non sauvegardé"

run t3 quota,succes_marqueur
[ "$(calls t3)" = 2 ] && grep -q "attente jusqu.*réinitialisation du quota" $R/t3/sortie.txt && grep -q "Cause classée : \*\*quota\*\*" $R/t3/CONTINUATION.md \
  && ok "3-5. quota détecté, attente de la fenêtre, reprise effectuée (2 lancements)" || ko "3-5. reprise après quota ($(calls t3) lancements)"
grep -q "^REPRISE" $R/t3/prompt-2.txt && grep -q "CONTINUATION.md" $R/t3/prompt-2.txt && ok "   la reprise repart du fichier de continuation (pas de l'historique)" || ko "   invite de reprise"

run t4 quota SUP_MAX_QUOTA_WAITS=3
[ "$(calls t4)" = 4 ] && grep -q "quota toujours indisponible" $R/t4/sortie.txt && ok "4b. quota indisponible : 3 nouvelles tentatives espacées puis arrêt (pas de boucle)" || ko "4b. quota persistant ($(calls t4) lancements)"

run t5 surcharge,succes_marqueur
[ "$(calls t5)" = 2 ] && grep -q "transitoire" $R/t5/sortie.txt && ok "surcharge serveur (529) classée transitoire, pas confondue avec le quota" || ko "surcharge ($(calls t5))"

run t6a technique,succes_marqueur
[ "$(calls t6a)" = 1 ] && [ "$(st t6a .reason)" = erreur_technique ] && ok "6a. erreur d'authentification : erreur technique, aucune relance" || ko "6a. erreur technique ($(calls t6a), $(st t6a .reason))"
run t6b plantage,succes_marqueur
[ "$(calls t6b)" = 1 ] && [ "$(st t6b .reason)" = erreur_technique ] && ok "6b. plantage (code 139) : aucune relance" || ko "6b. plantage ($(calls t6b))"

S=$R/t6c; mkdir -p $S/logs
( env SUP_STATE_DIR=$S SUP_CONT=$S/CONTINUATION.md CLAUDE_BIN=$D/faux-claude.sh FAUX_SCENARIO=long FAUX_COMPTEUR=$S/compteur FAUX_STATE=$S SUP_TIME_SCALE=600 SUP_DEADLINE_IN_S=360000 python3 $D/../superviseur.py > $S/sortie.txt 2>&1 & echo $! > $S/pid; wait )&
sleep 3; kill -TERM $(cat $S/pid); sleep 3
[ "$(calls t6c)" = 1 ] && grep -q "arret_volontaire : aucune relance" $S/sortie.txt && ! kill -0 $(cat $S/faux.pid) 2>/dev/null && ok "6c. arrêt volontaire (SIGTERM) : Claude arrêté proprement, aucune relance" || ko "6c. arrêt volontaire ($(calls t6c)) restants: $(ps -eo pid,args | grep "faux-claude.sh -p" | grep -v grep | cut -c1-80)"

S=$R/t6d; mkdir -p $S/logs
( env SUP_STATE_DIR=$S SUP_CONT=$S/CONTINUATION.md CLAUDE_BIN=$D/faux-claude.sh FAUX_SCENARIO=quota FAUX_COMPTEUR=$S/compteur FAUX_STATE=$S SUP_TIME_SCALE=600 SUP_RESET_IN_S=60000 SUP_DEADLINE_IN_S=360000 python3 $D/../superviseur.py > $S/sortie.txt 2>&1 )&
sleep 3; touch $S/STOP; sleep 32; [ "$(calls t6d)" = 1 ] && grep -q "arrêt volontaire" $S/sortie.txt && ok "6d. fichier STOP pendant l'attente du quota : arrêt sans relance" || ko "6d. STOP pendant l'attente ($(calls t6d)) $(tail -1 $S/sortie.txt)"

run t7 succes,succes,succes
[ "$(calls t7)" = 2 ] && ok "7. fin normale sans marqueur : une seule relance de vérification, pas plus" || ko "7. fin sans marqueur ($(calls t7))"
run t8 quota SUP_MAX_QUOTA_WAITS=50 SUP_MAX_LAUNCHES=5
[ "$(calls t8)" = 5 ] && grep -q "nombre maximal de lancements" $R/t8/sortie.txt && ok "8. plafond global de lancements respecté (5)" || ko "8. plafond ($(calls t8))"
run t9 quota SUP_DEADLINE_IN_S=600 SUP_RESET_IN_S=1200
[ "$(calls t9)" = 1 ] && grep -q "dépasse l'heure limite" $R/t9/sortie.txt && ok "9. fenêtre de quota après l'heure limite : pas d'attente inutile" || ko "9. heure limite ($(calls t9))"
echo "échecs : $F"; exit $F
