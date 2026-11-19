#!/bin/bash
# Arrêt propre et volontaire : aucune relance. Claude reçoit SIGINT, le superviseur écrit l'état dans le fichier de reprise.
N=/root/time-billing-v9-rc10-20261004/nuit; touch $N/STOP
P=$(jq -r .pid_superviseur $N/ETAT-SUPERVISEUR.json 2>/dev/null); [ -n "$P" ] && kill -0 $P 2>/dev/null && kill -TERM $P && echo "superviseur $P : arrêt demandé"
for i in $(seq 1 30); do kill -0 $P 2>/dev/null || break; sleep 2; done
kill -0 $P 2>/dev/null && echo "toujours actif après 60 s" || echo "arrêté. La session tmux reste ouverte pour consultation : tmux kill-session -t timebilling-nuit pour la fermer."
