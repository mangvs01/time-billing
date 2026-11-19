#!/bin/bash
# Faux « claude » pour tester le superviseur SANS consommer de jetons. Rejoue le n-ième comportement de FAUX_SCENARIO (liste séparée par des virgules).
n=$(( $(cat "$FAUX_COMPTEUR" 2>/dev/null || echo 0) + 1 )); echo $n > "$FAUX_COMPTEUR"
IFS=, read -ra S <<< "$FAUX_SCENARIO"; c=${S[$((n-1))]:-${S[-1]}}
printf "%s" "$2" > "$FAUX_STATE/prompt-$n.txt"; echo $$ > "$FAUX_STATE/faux.pid"
echo "{\"type\":\"system\",\"subtype\":\"init\",\"faux\":true,\"appel\":$n,\"scenario\":\"$c\"}"
case $c in
  succes) echo '{"type":"result","subtype":"success","is_error":false,"result":"Cycle terminé.","num_turns":12}'; exit 0;;
  succes_marqueur) touch "$FAUX_STATE/TERMINE"; echo '{"type":"result","subtype":"success","is_error":false,"result":"Mission terminée.","num_turns":40}'; exit 0;;
  quota) echo '{"type":"result","subtype":"success","is_error":true,"result":"Claude AI usage limit reached · resets 11:20pm","num_turns":3}'; exit 1;;
  surcharge) echo 'API Error: 529 {"type":"error","error":{"type":"overloaded_error"}} Server is temporarily limiting requests (not your usage limit)' >&2; exit 1;;
  technique) echo 'Invalid API key · Please run /login' >&2; exit 1;;
  plantage) echo 'Segmentation fault' >&2; exit 139;;
  long) sleep 60; echo '{"type":"result","subtype":"success","is_error":false,"result":"fin longue","num_turns":2}'; exit 0;;
esac
