# Proposition de pare-feu — NON APPLIQUÉE (opération O7, à valider : touche d'autres services du serveur)

Constat : `ufw` inactif, INPUT en ACCEPT. Les ports publiés par Docker sont routés par DNAT **avant** la chaîne INPUT :
`ufw` seul ne les protège pas. Le correctif principal pour Time Billing est l'écoute locale (`127.0.0.1:8091`, compose RC8).

1. Services hôte (garder une session SSH ouverte pendant l'opération) :
   ufw default deny incoming ; ufw default allow outgoing
   ufw allow 22/tcp        # idéalement restreint à vos IP : ufw allow from <IP> to any port 22 proto tcp
   ufw allow 80/tcp ; ufw allow 443/tcp
   ufw enable
2. Ports Docker encore publics à décider service par service (propriétaire à confirmer) :
   8088 (time-billing v30), 8089 (v7), 8090 (v8) : anciennes versions — arrêter ou lier à 127.0.0.1
   5678 (n8n, déjà servi par Caddy sous n8n.hudd-l.com) : lier à 127.0.0.1
   3000 (processus node hôte), 631 (CUPS) : arrêter si inutiles
   Filtrage Docker si une publication publique doit rester : règles dans la chaîne DOCKER-USER.
3. Vérification depuis l'extérieur (poste personnel) : nmap -Pn -p 1-10000 <IP publique>
