#!/bin/bash
# État du superviseur et des dernières actions de Claude (lisible). --suivre : rafraîchit toutes les 20 s.
N=/root/time-billing-v9-rc10-20261004/nuit
show() {
  echo "=== $(TZ=Asia/Makassar date '+%d.%m %H:%M') WITA — superviseur ==="
  jq -r '"statut : \(.status)   lancements : \(.launches // 0)   attentes quota : \(.quota_waits // 0)   dernière cause : \(.last_outcome // "-")\nprochaine tentative : \(.next_attempt // "-")   heure limite : \(.deadline)\nraison de fin : \(.reason // "-")"' $N/ETAT-SUPERVISEUR.json 2>/dev/null || echo "(pas encore d'état)"
  [ -f $N/TERMINE ] && echo "MISSION DÉCLARÉE TERMINÉE : $(cat $N/TERMINE)"
  echo; echo "--- journal du superviseur ---"; tail -8 $N/logs/superviseur.log 2>/dev/null
  L=$(ls -t $N/logs/claude-*.jsonl 2>/dev/null | head -1)
  [ -n "$L" ] && { echo; echo "--- dernières actions de Claude ($(basename $L)) ---"
    tail -400 "$L" | jq -r 'select(.type=="assistant") | .message.content[]? | if .type=="text" then "💬 " + (.text|gsub("\n";" ")|.[0:220]) elif .type=="tool_use" then "🔧 " + .name + " " + ((.input.description // .input.command // .input.file_path // "")|tostring|gsub("\n";" ")|.[0:160]) else empty end' 2>/dev/null | tail -14; }
  echo; echo "--- dépôt ---"; git -C /root/time-billing-v9-rc10-20261004 log --oneline -4
}
if [ "$1" = --suivre ]; then while true; do clear; show; sleep 20; done; else show; fi
