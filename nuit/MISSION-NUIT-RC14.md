# Mission de nuit — Time Billing V9 / RC14 (mandat de l'utilisateur, 2026-10-04)

Tu es une session Claude Code autonome lancée dans `tmux` (session `timebilling-nuit`). L'utilisateur a fermé son terminal : personne ne répondra à une question avant demain matin. Contexte complet : `HANDOFF-NUIT-RC14.md` (même dossier), plus la mémoire de projet chargée automatiquement.

## Objectif
Finaliser une candidate RC14 de qualité professionnelle, fidèle à la direction « Liquid Glass » validée (blanc perle, gris titane, bleu électrique, verre dépoli, navigation latérale, cartes financières, anneaux, graphiques fins).
**Le fichier du mockup approuvé n'est PAS disponible** (introuvable sur le serveur, le dépôt et la conversation). Cherche-le une fois au début et une fois à la fin (`/root/Downloads`, `/root`, dépôt : images/PDF/HTML récents). S'il reste introuvable, travaille depuis la description écrite (HANDOFF §3) et **écris dans le rapport que la fidélité au mockup n'a pas pu être vérifiée**. N'invente jamais cette vérification.

## Chantiers (dans cet ordre, un groupe à la fois)
1. Audit de l'état actuel (captures desktop/tablette/mobile sur une instance jetable, lecture du CSS).
2. Cohérence visuelle de tous les écrans, composants, espacements, typographies, transparences, ombres.
3. Dashboard : hiérarchie des indicateurs financiers.
4. Mandats : visualisation des soldes. Saisie des temps. Facturation et prévisualisation. Avoirs. Prévisions.
5. Archive : filtres et recherche. Import Excel : ergonomie, y compris mobile.
6. Responsive desktop / tablette / téléphone.
7. Accessibilité, lisibilité, états d'erreur (formulaires refusés, messages, champs invalides, désactivés).

## Autorisé
Lire/analyser le code ; modifier frontend/CSS/gabarits ; refactoriser les composants visuels ; corriger des défauts ergonomiques ; lancer les tests ; données exclusivement fictives, bases jetables ; captures ; commits locaux sur la branche `design-liquid-glass-rc14` ; plusieurs cycles ; déploiement du staging **uniquement** via `procedure/*.sh procedure/staging.conf` (voir HANDOFF §5) ; démo `tb-demo` (:8095) et instances jetables (ports 8300-8340, préfixe `tb-nuit-`).

## INTERDIT (absolu)
Production (port 8091, `/opt/time-billing-v9`, conteneur `time-billing-v9`) ; toute facture réelle ; tout import historique (jamais `import/`, jamais `/root/Time sheet CP.xlsx`) ; toute suppression de données ; schéma ou migration de la production ; DNS, Caddy, pare-feu, SSH, configuration de sécurité ; mots de passe et secrets (ne jamais afficher un `.env`) ; **fusion dans `main`** (`git merge`, `rebase`, `push`, `checkout main`) ; déploiement en production ; désactiver une protection pour faire passer un test. Autres applications du serveur (V7/V8/V30, amo-cockpit, chess-academy, n8n) : ne pas toucher.
Si une opération sort de ce périmètre : **arrête-toi sur ce point, documente le blocage dans le rapport, passe à autre chose**.
Ne sacrifie jamais la fiabilité métier pour un résultat visuel : aucun calcul, schéma, PDF, libellé métier modifié sans nécessité démontrée. Ne pas modifier les ids/classes/`name`/`action`/libellés utilisés par les recettes (voir HANDOFF §4).

## Méthode : cycles A→F
A. Audit. B. Correction d'un groupe de problèmes. C. Tests fonctionnels et visuels. D. Régressions (suite complète). E. Commit local quand le cycle est stable. F. Groupe suivant.
En cas d'échec : analyse la cause ; corrige si c'est dans le périmètre ; sinon restaure le dernier état stable (`git restore` / revert d'un commit RC14, jamais `reset --hard`) et documente.
Un seul agent : **n'utilise ni sous-agents, ni Workflow, ni tâches planifiées, ni boucle infinie**. Avant chaque commit : `git status` (d'autres sessions Claude existent sur le serveur ; lis `NOTE-SESSIONS-PARALLELES.md` avant de toucher au staging et ajoute une note datée).

## Condition d'arrêt
Tous les écrans prioritaires cohérents ; tests disponibles exécutés ; aucun défaut bloquant connu ; staging stable ; modifications commitées et documentées. Ne poursuis pas d'améliorations sans valeur. Durée maximale : une nuit (le lanceur coupe à 10 h).

## Rapport obligatoire : `RAPPORT-NUIT-RC14.md` (racine du dépôt)
État initial et final ; liste exacte des fichiers modifiés (`git diff --stat` depuis le commit de départ `10175fd`) ; fonctionnalités corrigées ; tests exécutés avec résultats **réels** (jamais « réussi » sans exécution) ; captures desktop/tablette/mobile (chemins) ; défauts restants ; commits ; état du staging ; confirmation explicite que la production et les données historiques n'ont pas été touchées (empreintes : `audit/prod-fp-avant.txt`, `sha256sum /opt/time-billing-v9/data/timebilling.db` comparé) ; commandes pour retrouver la session et les logs ; procédure de rollback ; statut du mockup (introuvable ou non).
Écris aussi une première version du rapport dès la fin du premier cycle, puis mets-la à jour : si la session est interrompue, le rapport existe déjà.

## Mode d'exécution (important)
Tu tournes en mode NON interactif (`claude -p`) sous un superviseur (`nuit/superviseur.py`). Conséquences :
* **Ta session s'arrête dès que tu rends ta réponse finale.** Ne conclus pas tant que la condition d'arrêt n'est pas atteinte ou qu'un blocage ne l'empêche.
* **N'utilise jamais l'exécution en arrière-plan** (`run_in_background`, `&`, Monitor) : la session pourrait se terminer avant la fin de la commande. Lance les commandes longues au premier plan avec un délai (`timeout` jusqu'à 600000 ms ; la recette complète dure ≈ 8 min).
* **Fichier de reprise** : `/root/time-billing-v9/CONTINUATION-RC14.md`. Mets à jour ses sections « État d'avancement », « Git », « Tests », « Défauts connus » **après chaque cycle et avant chaque tâche longue** (un arrêt pour quota peut survenir à tout moment ; le superviseur relancera une nouvelle session qui ne connaîtra que ce fichier). Ne supprime pas les sections « Arrêt automatique » ajoutées par le superviseur.
* **Fin de mission** : quand la condition d'arrêt est atteinte et `RAPPORT-NUIT-RC14.md` complet, crée le fichier `/root/time-billing-v9-rc10-20261004/nuit/TERMINE` (une ligne de résumé). Sans ce marqueur, le superviseur considère la mission inachevée.
* En cas de blocage hors périmètre : documente-le dans le rapport et le fichier de reprise, puis continue avec un autre chantier ; si plus rien n'est possible, finalise le rapport et crée TERMINE.
