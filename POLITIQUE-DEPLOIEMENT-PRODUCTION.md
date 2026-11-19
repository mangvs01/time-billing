# Politique permanente — déploiements Time Billing

Décision utilisateur du 2026-10-09.

## Disponibilité
- Une fois la production ouverte aux utilisateurs, privilégier une bascule blue-green ou équivalente : démarrer la version candidate sur une cible distincte, la contrôler, puis basculer Caddy sans arrêter l'instance active.
- Ne pas annoncer « zéro interruption » sans mesure démontrée. Une courte interruption n'est acceptable que si elle est nécessaire, annoncée et limitée.
- Conserver l'instance et l'image précédentes jusqu'à validation post-bascule et expiration de la fenêtre de retour arrière; empêcher toute purge automatique de détruire l'unique image de rollback.
- Les migrations doivent être compatibles avec l'ancienne et la nouvelle version pendant la fenêtre de bascule (expand/contract). Aucune migration destructive pendant que les deux versions peuvent servir du trafic.

## Intégrité et conservation des données
- La base métier persistante est la source de vérité; ne jamais remplacer la base active par une copie ancienne de sauvegarde lors d'un déploiement ordinaire.
- Avant bascule : sauvegarde cohérente, intégrité SQLite, empreinte SHA-256, décompte et empreintes métier vérifiés.
- Après bascule : vérifier que les données métier sont identiques à la référence attendue et que les écritures fonctionnent.
- Un retour arrière ne doit jamais supprimer silencieusement les écritures effectuées depuis le déploiement. Priorité au rollback du code en conservant la base compatible; si ce n'est pas sûr, bloquer le retour arrière jusqu'à export ET réintégration vérifiés des nouvelles écritures.
- Les factures émises, PDF figés, notes de crédit, saisies, historiques, mandats, paramètres et journal d'audit sont des données à préserver. Aucune purge de données métier pour faciliter une publication.
- La base du staging ne peut être promue qu'après recette et revue explicite de son contenu; les données de test doivent être identifiées, jamais supprimées implicitement.

## Garde-fous
- Aucun déploiement production sans préflight, répétition GO liée à la version/code/base, sauvegarde vérifiée, procédure de rollback testée et contrôle post-déploiement.
- Arrêt au premier échec; ne pas poursuivre la chaîne par des séparateurs qui masquent un code retour non nul.
- La procédure de déploiement et le mécanisme de bascule doivent être testés sur environnement jetable avec scénarios d'échec, concurrence, données écrites pendant/après la bascule et image de rollback purgée.
- Cette politique prévaut sur les anciens runbooks en cas de conflit. Avant chaque prochain déploiement après la première mise en service, vérifier que la procédure implémente ces garanties.
