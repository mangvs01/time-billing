#!/bin/bash
# Démarre le superviseur de nuit RC14 dans tmux (survit à la fermeture du terminal / de SSH). Idempotent.
S=timebilling-nuit; N=/root/time-billing-v9-rc10-20261004/nuit
tmux has-session -t $S 2>/dev/null && { echo "déjà active : tmux attach -t $S"; exit 0; }
rm -f $N/STOP; mkdir -p $N/logs
tmux new-session -d -s $S -n superviseur -x 200 -y 50 -c /root/time-billing-v9-rc10-20261004 "python3 $N/superviseur.py; echo; echo '=== superviseur arrêté — voir $N/voir.sh ==='; exec bash"
tmux new-window -d -t $S -n suivi "$N/voir.sh --suivre"
echo "démarré. Consulter : $N/voir.sh   ·   session : tmux attach -t $S"
