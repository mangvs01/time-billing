# BILL-GARDE — Conception d'une garde EXTÉRIEURE pour les 5 « limites du shell »

**Statut : CONCEPTION POUR DÉCISION. Aucun code, aucune procédure, aucun test n'a été modifié ; rien n'est installé ni activé ; `/opt/time-billing-v9` n'a pas été touché.**
Document rédigé le 19/11/2026 sur la branche `campaign/billing-mdp` (HEAD au moment de la rédaction : `fd063cc` ; la mission citait `de6d51e`, parent direct, sans effet sur ce sujet : ni `app/` ni `procedure/` n'ont changé).

Sources lues : `docs/TESTS-ATTENDUS.md` (§ B), `procedure/tb-common.sh`, `procedure/lire-conf.sh`, les scripts d'entrée de `procedure/` (`20-backup.sh`, `backup-quotidien.sh`, `verifier-sauvegarde.sh`, `approuver-sauvegarde.sh`, `cron-sauvegarde.example`, `backup-offsite.sh`, `80-site-caddy.sh` en en-tête), `RAPPORT-GARDE-PRODUCTION-RC25.md`, `CONCEPTION-GARDE-CONFIANCE-RC25.md` (le grand dossier d'architecture déjà rédigé, dont celui-ci est le **complément opérationnel**, centré sur les 5 tests), `tests/test_procedure_adverse.py`, `tests/test_procedure_residuel.py`.

Légende : **[lu]** = constaté dans le code ou la documentation du dépôt ; **[mesuré]** = mesuré par une session précédente et consigné dans `CONCEPTION-GARDE-CONFIANCE-RC25.md` (pas re-mesuré ici) ; **[hyp]** = hypothèse non vérifiée.

**Ce qui n'a pas pu être vérifié dans cette session** : les droits réels des dossiers du serveur (`/root`, le dossier d'où le cron lancerait les scripts, `/etc/time-billing`), la présence de systemd, la liste des membres du groupe `docker`. Une lecture de ces droits (`stat`) a été **refusée** par le système de permissions de la session (elle sortait du dossier du projet) ; je ne l'ai pas contournée. Tout ce qui en dépend est marqué **[hyp]**.

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 1. Ce qu'est « la garde » et pourquoi elle a des limites (en clair)

Les scripts de `procedure/` (sauvegarde, déploiement, retour arrière…) commencent par charger `tb-common.sh`, qui contient la **garde de production** : « si la cible est la production, refuser sans confirmation datée (`CONFIRM_PROD=OUI-<date>`) ; sauf pour les deux scripts de sauvegarde dont les empreintes SHA-256 sont inscrites dans un fichier réservé à root ».

Le défaut de fond, appelé **auto-attestation** : *le contrôle est un des fichiers qu'il contrôle*. Un fichier qu'on peut réécrire peut aussi être réécrit pour dire « tout va bien ». De plus, **le shell exécute des choses avant la première ligne du script** (variables d'environnement, bibliothèques préchargées) et **relit le script au fil de l'eau**. Aucune amélioration du texte du script ne peut régler cela : il faut qu'une pièce **extérieure** aux fichiers contrôlés décide, avant, de ce qui a le droit de s'exécuter et dans quel environnement.

### Les 5 limites (les 5 tests marqués « échec attendu »)

| N° | Test (`expectedFailure`) | En une phrase |
|---|---|---|
| L1 | `test_procedure_adverse::test_KNOWN_LIMIT_a_rewritten_guard_can_switch_its_own_checks_off` | Un `tb-common.sh` réécrit pour se déclarer « pas production » n'est pas arrêté. |
| L2 | `test_procedure_adverse::test_KNOWN_LIMIT_a_modified_reader_runs_its_top_level_code_before_any_hash_is_checked` | Un `lire-conf.sh` modifié exécute son code avant qu'aucune empreinte ne soit contrôlée. |
| L3 | `test_procedure_residuel::test_RESIDUAL_ld_preload_in_the_callers_environment_should_never_execute` | Une bibliothèque désignée par `LD_PRELOAD` dans l'environnement de celui qui lance le script s'exécute avant le script. |
| L4 | `test_procedure_residuel::test_RESIDUAL_the_documented_env_i_bash_p_launch_should_stop_ld_preload` | La commande « durcie » de l'exemple cron (`env -i … bash -p`) n'arrête pas non plus `LD_PRELOAD` : c'est `env` lui-même qui charge la bibliothèque. |
| L5 | `test_procedure_residuel::test_RESIDUAL_a_script_replaced_after_the_hash_check_should_not_run_the_new_content` | Si le script est modifié **après** le contrôle d'empreinte, la nouvelle ligne s'exécute (course « contrôle puis usage »). |

### Qui peut vraiment exploiter ces limites aujourd'hui ? (lecture d'ensemble)

Les cinq limites ont **un point commun** : **un attaquant qui n'est pas déjà root n'a, en principe, aucune prise** — à condition que les droits soient ceux qu'on suppose. Elles décrivent ce qui se passe quand cette condition tombe, pas une porte ouverte à un inconnu :

* **L1, L2, L5 exigent le droit d'ÉCRIRE dans le dossier des scripts** (ou dans `/etc/time-billing`). Les scripts sont lus dans `/root/time-billing-v9-rc10-20261004/procedure` d'après `cron-sauvegarde.example` [lu] : un dossier sous `/root`. Si `/root` est fermé aux autres (cas normal, mais **[hyp]** : non vérifié ici), seul root peut écrire. Les acteurs réalistes sont alors : **(a)** l'**agent autonome qui tourne en root** et « répare » un script pour qu'il passe (le risque ouvert nommé par le propriétaire, T3 de `CONCEPTION-GARDE-CONFIANCE-RC25.md`) ; **(b)** une **erreur de droits** (dépôt cloné ou décompressé par un compte non root, `chmod -R`, volume monté), qui ouvre l'écriture à quelqu'un d'autre sans que personne ne le voie ; **(c)** un **compte applicatif ou un service compromis** qui, s'il peut écrire là, passe root au prochain lancement du cron (escalade de privilèges).
* **L3 et L4 exigent de maîtriser l'ENVIRONNEMENT du processus qui lance le script.** Le cron de `/etc/cron.d` (écrit par root) fixe cet environnement : un attaquant extérieur n'y a aucune prise. Restent : **(a)** un humain ou un agent qui lance le script à la main avec un environnement hérité de son shell (bash de connexion, variable laissée par un outil) ; **(b)** une règle `sudo` qui conserve `LD_PRELOAD` (`env_keep`, `SETENV`) ; **(c)** une tâche lancée par un autre automate. Sur le chemin cron planifié, **le risque est faible** ; sur le chemin « manuel avec CONFIRM_PROD », il est réel mais ne concerne que quelqu'un qui peut déjà lancer ce script en root.

**Gravité si l'une est exploitée** : exécution de code arbitraire **en root sur l'hôte**, qui héberge la production (`docker exec` sur le conteneur de production, lecture de `/root/backups`, secrets). C'est donc **élevé en impact, faible en probabilité** tant que les droits sont corrects, et **non nul** à cause de (a) l'agent root et (b) l'erreur de droits.

**Ce qu'aucune solution ci-dessous ne résout** (à dire sans détour) : un **root malveillant ou compromis** peut tout remplacer, y compris le vérificateur. On vise : (i) l'erreur et la dérive, (ii) l'agent root autonome qui se « corrige » tout seul, (iii) l'attaquant non root qui parvient à écrire un fichier, (iv) l'environnement hérité contaminé.

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 2. Les solutions possibles (catalogue commun)

Les mêmes briques répondent à plusieurs limites ; je les décris une fois, puis j'attribue ce qu'elles font pour chaque limite en §3.

### S1 — Lancer par une unité systemd (service + minuteur) qui fait le contrôle **avant** le script
Le minuteur (`tb-backup.timer`) déclenche un service (`tb-backup.service`, `Type=oneshot`, fichiers dans `/etc/systemd/system`, propriété root). L'environnement du service est **construit par systemd** à partir de l'unité (`Environment=`, `PATH=` fixe) : **rien n'est hérité du shell de l'appelant**, y compris quand un humain fait `systemctl start tb-backup` (le processus naît de systemd, pas du terminal). Un `ExecStartPre=` lance un **vérificateur** (petit programme extérieur : S2 ou version simple en S4) avant `ExecStart=`. L'unité peut ajouter des restrictions : `NoNewPrivileges=`, `ProtectSystem=strict`, `ReadOnlyPaths=` sur le dossier des scripts, `PrivateTmp=`, `ProtectHome=` si les scripts sont déplacés hors de `/root`, journal automatique (`journalctl`), alerte via `OnFailure=`.
* **Avantages** : supprime **par construction** la classe « environnement de l'appelant » (L3, L4) sur le chemin planifié **et** manuel ; journal et alerte d'échec gratuits (aujourd'hui il n'y en a aucun) ; un point d'entrée unique et nommé ; modeste en nouveau code (de la configuration, pas un programme).
* **Coûts / limites** : dépend de la présence de systemd sur le serveur **[hyp : non vérifié ; l'hôte de développement n'en a pas, d'après `CONCEPTION-GARDE-CONFIANCE-RC25.md`]** ; ne protège **pas** à lui seul les fichiers (L1, L2, L5) : un `ExecStartPre=` qui est un script du même dossier recrée l'auto-attestation ; root peut modifier l'unité ; à tester sur un serveur d'essai (le contrôle `systemd-analyze security` est utile mais non exécuté ici). Le principe « un seul chemin de lancement » ne tient que si les scripts refusent de tourner hors de ce chemin (un lancement direct reste possible pour root).

### S2 — Vérificateur extérieur compilé, avec **instantané** (« tb-gate », déjà prototypé)
Un exécutable **statique** root-only (`/usr/local/sbin/tb-gate`, ~2 Mo, déjà prototypé en Go dans `conception/rc25-gate-prototype/`) fait, dans cet ordre : vérifier la chaîne de droits de chaque fichier ; vérifier l'empreinte (variante locale) ou la **signature** (variante B, cf. S3) ; **copier les octets vérifiés dans un instantané privé** (tmpfs root 0700) ; lancer `bash -p` **sur la copie** avec un environnement reconstruit.
* **Avantages** : traite **L1, L2, L3, L4 et L5 ensemble** (le vérificateur n'est pas dans l'ensemble qu'il vérifie ; il est insensible à `LD_PRELOAD` parce que statique ; il exécute la copie, donc plus de course) ; faisabilité déjà démontrée par 8 tests de prototype **[mesuré]**.
* **Coûts** : **nouveau code de sécurité à écrire, revoir et maintenir** (Go) ; chaîne d'approvisionnement du compilateur ; construction reproductible à mettre en place ; chaque version des scripts passe par une étape d'installation ; une panne du vérificateur arrête la sauvegarde (échec fermé voulu ; d'où l'alerte de S1).

### S3 — **Signature** des scripts hors serveur (variante « B » du dossier précédent)
Le manifeste (liste des fichiers + empreintes + numéro de séquence croissant) est signé en Ed25519 sur **le poste du propriétaire** ; seule la clé **publique** (32 octets) est sur le serveur. Le vérificateur (S2) refuse tout contenu non signé.
* **Avantages** : c'est **la seule option qui empêche l'agent root autonome de s'auto-approuver** (T3) : approuver un contenu nouveau exige un secret que le serveur n'a pas ; une effraction (clé publique ou vérificateur remplacés) se voit au lieu d'être silencieuse ; contrairement aux empreintes locales, l'approbation n'est pas « à côté » du contenu.
* **Coûts** : **gérer une clé** (génération, sauvegarde, perte, rotation) ; une étape de signature à chaque version ; ne protège pas contre root qui remplace aussi la clé publique (elle rend l'attaque *visible*, pas impossible) ; sans S2 elle ne sert à rien (il faut un vérificateur pour la contrôler).

### S4 — Contrôle d'intégrité **plus simple** : copie root immuable et vérifieur en script minimal
Variante sans nouveau binaire : déplacer l'arbre approuvé hors de `/root` vers `/usr/local/lib/time-billing/<release>/`, root:root, fichiers rendus **immuables** (`chattr +i`) ; un **tout petit** script de contrôle (≈ 20 lignes, **un seul fichier**, root-only, sans `source`, lancé par systemd) calcule les empreintes, **copie** les fichiers vérifiés vers un tmpfs et exécute la copie.
* **Avantages** : pas de langage ni de binaire en plus ; faible coût ; `chattr +i` empêche une modification **accidentelle ou par un non-root** même avec des droits laxistes (hors `CAP_LINUX_IMMUTABLE`, donc hors root) ; une relecture humaine de 20 lignes est possible.
* **Coûts / limites** : le contrôle reste un **script bash** : il hérite des limites de l'interpréteur (`LD_PRELOAD` pour les lancements hors systemd, TOCTOU sur lui-même s'il est modifiable) ; l'immutabilité est annulable par root (`chattr -i`) ; les empreintes restent **à côté** (pas de séparation T3) ; à ne retenir que comme **palier** vers S2/S3 ou si le propriétaire refuse un binaire.

### S5 — Exécution par un **utilisateur dédié** sans droits d'écriture sur les scripts
Un compte système (`tb-run`) lance la sauvegarde ; les scripts, `tb-common.sh`, `lire-conf.sh` et la configuration appartiennent à **root** et ne sont **pas modifiables** par `tb-run`.
* **Avantages** : un compromis du **processus de sauvegarde** ne permet plus de réécrire la garde ni les scripts (sépare « celui qui exécute » de « celui qui peut modifier ») ; `LD_PRELOAD` ou l'environnement hostile n'obtient plus root, seulement `tb-run` (réduction du dégât).
* **Coûts / limite majeure** : **les scripts pilotent `docker`** (`docker exec`, `docker cp`, `docker compose stop`…). Un compte qui peut parler au démon Docker (groupe `docker`) est **équivalent à root** sur l'hôte (il peut monter `/` dans un conteneur) : le gain est donc **illusoire** pour la sécurité s'il est simplement ajouté à ce groupe. Seules deux voies le rendent utile : (i) Docker **rootless** pour ce compte (migration lourde, à écarter : le conteneur de production est un service existant) ; (ii) un **wrapper root minimal** (`sudo`/unité systemd) qui n'autorise que les commandes précises (`docker exec <conteneur> python …`, `docker cp`) — ce qui revient à réécrire la sauvegarde en « liste blanche de commandes ». Utile surtout pour le cas (c) du §1 (service compromis) et **inutile contre l'agent root autonome**. Ne règle ni L1/L2 (si root peut écrire) ni L5 pour root.

### S6 — Durcir les **droits** et les vérifier (palier sans nouveau code)
Déplacer l'arbre approuvé hors de `/root` vers un dossier root-only de `/usr/local/lib` ; `chmod`/`chown` stricts ; `chattr +i` ; **audit automatique** (`find -perm`, `stat`) lancé par une unité systemd et alerte si un fichier du jeu devient inscriptible par un non-root ; `auditd` ou `inotify` sur ces dossiers pour journaliser toute écriture.
* **Avantages** : peu coûteux, aucune dépendance de développement ; transforme l'**hypothèse** « seul root peut écrire » en fait vérifié en continu ; détecte l'erreur de droits (b).
* **Coûts / limites** : ne **bloque** rien (détection) ; root garde la main ; l'écriture par root (agent autonome) est journalisée mais pas empêchée.

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 3. Limite par limite

### L1 — Garde réécrite (`tb-common.sh`) : auto-attestation

**Risque réel (en clair).** Quelqu'un qui peut écrire `tb-common.sh` y met `is_production() { return 1; }` : la garde déclare que la production n'est pas la production, **la sauvegarde (et plus largement tout script qui source le fichier) s'exécute sans `CONFIRM_PROD`**. Test : la sauvegarde factice a tourné, code retour 0 **[lu]**.
* **Qui** : tout porteur du droit d'écriture sur le dossier des scripts : agent root autonome (qui s'« arrange »), compte non root si les droits sont mal posés, service compromis dans ce cas.
* **Avec quel accès** : écriture sur `procedure/tb-common.sh` **ou** sur son dossier (renommage). Aucun accès réseau n'est nécessaire ; aucun mot de passe de l'application non plus.
* **Conséquence** : contournement de la garde de production, avec les droits du lanceur (root par cron) : exécution de **n'importe quelle** commande sous le nom d'une opération autorisée.
* **Gravité / probabilité** : impact **élevé**, probabilité **faible** si les droits sont corrects et si l'agent root est tenu en bride ; non démontrée comme nulle (**[hyp]** sur les droits).

| Solution | Ce qu'elle apporte | Coût | Verdict |
|---|---|---|---|
| **A. S2 + S3 (vérificateur extérieur, manifeste signé hors serveur)** | Aucun contenu non signé ne s'exécute sous le nom d'une opération sensible ; la garde interne devient une **2ᵉ barrière**, plus l'unique. Le test devient un vrai test (« réécrit → refusé »). | Nouveau programme + gestion d'une clé. | **Recommandée** (cible). |
| **B. S2 seul, empreintes locales (variante « A » du dossier précédent)** | Même effet contre l'erreur et le non-root ; **pas** contre l'agent root, qui peut relancer l'approbation. | Moins cher : pas de clé. | Repli valable. |
| **C. S4 + S6 (copie immuable, contrôle de 20 lignes, audit des droits)** | Bloque l'écriture accidentelle ou par non-root ; rend visible le reste. Aucun binaire. | Peu cher ; le contrôle est lui-même un script. | Palier intermédiaire si le propriétaire refuse un binaire. |

**Recommandation** : **A** (via S2+S3) ; **C** comme palier immédiat sans nouveau code.
**Décision propriétaire (une phrase)** : « Acceptez-vous qu'un petit programme extérieur, vérifié hors serveur, décide seul ce qui s'exécute en production, et voulez-vous une clé de signature que vous gardez, hors du serveur ? »

### L2 — Lecteur de configuration (`lire-conf.sh`) exécuté avant la vérification

**Risque réel (en clair).** `tb-common.sh` fait `. lire-conf.sh` **à la ligne 5**, **avant** tout contrôle d'empreinte ; l'empreinte de `lire-conf.sh` n'est contrôlée que plus bas (`backup_exception_ok`). Un `lire-conf.sh` modifié exécute donc **ses lignes de premier niveau** (témoin créé dans le test) ; l'exception « sauvegarde » est refusée ensuite, mais la charge a déjà tourné. Même un script qui sera *refusé* a déjà agi.
* **Qui / quel accès** : comme L1 (écriture dans `procedure/`). C'est la même porte ; la nuance : **ici la garde, même correcte, ne protège pas**, parce que l'ordre des opérations est inversé.
* **Gravité / probabilité** : même que L1 ; **plus facile à déclencher par accident**, car une modification maladroite d'un fichier « de lecture de configuration » paraît anodine.

| Solution | Ce qu'elle apporte | Coût | Verdict |
|---|---|---|---|
| **A. S2 (vérificateur extérieur) : le fichier est haché AVANT d'être lu** | Aucun octet de `lire-conf.sh` ne s'exécute s'il n'est pas approuvé ; remplace l'ordre fautif. | Inclus dans S2/S3. | **Recommandée**. |
| **B. Changer l'ordre dans le script (hacher `lire-conf.sh` avant de le sourcer)** | Supprime la fenêtre pour une modification par un non-root. | **Reste auto-attesté** : le code qui hache est dans `tb-common.sh` (L1). Et c'est du **code de procédure à modifier** (hors de cette mission). | À ne prendre que combiné avec A. |
| **C. Fusionner `lire-conf.sh` dans le vérificateur** (le vérificateur lit la configuration, valide la grammaire et passe les valeurs en argument) | Le lecteur sort du jeu de fichiers non fiables ; la configuration est validée par du code approuvé. | Le vérificateur grossit (déjà prévu en « étape 3 » du dossier précédent). | Bon complément de A. |

**Recommandation** : **A + C** (le vérificateur lit et valide la configuration lui-même ; le script reçoit des valeurs, plus un fichier à « sourcer »).
**Décision propriétaire** : « Autorisez-vous le vérificateur à lire et valider seul `prod.conf` avant tout script, et à ne plus laisser aucun fichier de procédure s'exécuter avant ce contrôle ? »

### L3 — `LD_PRELOAD` dans l'environnement de l'appelant

**Risque réel (en clair).** `LD_PRELOAD` désigne une bibliothèque que le système charge **dans tout programme dynamique, avant sa première instruction**. Si celui qui lance le script l'a défini, la bibliothèque s'exécute **dans bash**, avant la garde ; aucun contrôle du script ne peut l'arrêter. Mesure : constructeur exécuté dans `bash script` et dans `bash -p script` **[mesuré]** ; les protections existantes (`env -i`, `bash -p`, refus de `BASH_ENV` / `SHELLOPTS` / fonctions exportées) **ne couvrent pas ce vecteur** **[lu]**.
* **Qui** : quelqu'un qui **lance** le script avec l'environnement de son choix : humain en shell de connexion, agent qui exécute des commandes, règle `sudo` qui conserve l'environnement, autre automate. **Pas** un attaquant extérieur (le cron de `/etc/cron.d` fixe son environnement).
* **Quel accès** : pouvoir lancer le script ; pour être **dangereux**, ce lanceur doit avoir des droits supérieurs à ceux qu'il a sans le script (sinon rien n'est gagné). Cas concrets : `sudo` mal réglé (`env_keep`/`SETENV`), service tournant en root avec un environnement partiellement contrôlé.
* **Gravité / probabilité** : impact **élevé** si le script tourne en root ; probabilité **faible** sur le chemin planifié, **moyenne** sur le chemin « manuel » si un agent root lance les scripts avec un environnement hérité.

| Solution | Ce qu'elle apporte | Coût | Verdict |
|---|---|---|---|
| **A. S1 (unité systemd)** | L'environnement du service ne vient **pas** de l'appelant : `LD_PRELOAD` du shell n'y arrive jamais, y compris pour un lancement manuel par `systemctl start`. | De la configuration ; nécessite systemd **[hyp]**. | **Recommandée** (la plus simple et la plus complète pour L3). |
| **B. S2 (lanceur statique qui reconstruit l'environnement)** | Un exécutable statique ne charge aucune bibliothèque préchargée **[mesuré]** ; il lance ensuite bash avec un environnement vide. Marche aussi **sans** systemd. | Binaire à maintenir. | Bon, indispensable si on veut garder le lancement manuel direct. |
| **C. Interdire les lancements directs en production** (les scripts refusent de tourner s'ils ne viennent pas d'un parent connu) | Réduit le chemin manuel. | **Faux sentiment de sécurité** : l'interpréteur a déjà chargé la bibliothèque avant que le script puisse refuser. | **Écartée** (incapable de résoudre L3). |

**Recommandation** : **A** (S1) ; **B** si systemd n'est pas disponible. Aucune solution qui ne soit pas « avant bash » ne règle L3.
**Décision propriétaire** : « Tous les lancements sensibles doivent-ils passer par un seul point d'entrée extérieur (unité systemd ou lanceur statique), y compris pour vos lancements manuels ? »

### L4 — La commande « durcie » du cron (`env -i … bash -p`) n'arrête pas `LD_PRELOAD`

**Risque réel (en clair).** C'est **la même faille que L3, mais plus gênante** : l'exemple cron fourni (`cron-sauvegarde.example` : `/usr/bin/env -i PATH=… /bin/bash -p …`) donne l'**impression** d'un lancement propre. Or `env` est un programme dynamique : il **charge la bibliothèque désignée par `LD_PRELOAD` avant d'effacer l'environnement** **[mesuré]**. La documentation promet donc une protection qu'elle n'apporte pas ; un exploitant peut s'y fier à tort.
* **Qui / quel accès** : comme L3, avec une nuance **rassurante** : dans un vrai `/etc/cron.d`, l'environnement vient du cron (root) ; l'attaquant doit donc déjà avoir contrôlé `/etc/cron.d` ou le processus parent. Le risque **s'active surtout si cette commande est recopiée** dans un lanceur manuel, un `sudo`, un script d'administration ou un automate (où l'environnement est hérité).
* **Gravité / probabilité** : impact **élevé** (root), probabilité **faible** sur le cron réel, **non négligeable** sur les copies manuelles ; **risque de documentation** (fausse assurance) à corriger quoi qu'il arrive.

| Solution | Ce qu'elle apporte | Coût | Verdict |
|---|---|---|---|
| **A. S1 (systemd)** | Supprime `env -i … bash -p` de la chaîne : l'unité fixe l'environnement. Même solution que L3. | Voir S1. | **Recommandée**. |
| **B. S2 (lanceur statique)** | Remplace `env` par un binaire statique ; le point d'entrée documenté devient `tb-gate run …`. | Voir S2. | Équivalent si pas de systemd. |
| **C. Corriger la documentation seulement** (`cron-sauvegarde.example`, `RAPPORT-GARDE-PRODUCTION-RC25.md` : dire que `env -i … bash -p` **ne protège pas** de `LD_PRELOAD`) | Retire la fausse assurance, sans changer le comportement. | Aucun, mais **c'est du texte hors de cette mission** (aucune modification faite ici). | À faire **en plus**, pas à la place. |

**Recommandation** : **A** (ou B) + **C** (texte). L3 et L4 se résolvent **ensemble** ; ils ne justifient qu'**un** chantier.
**Décision propriétaire** : « Confirmez-vous que la commande `env -i … bash -p` n'est plus présentée comme protectrice et qu'elle sera remplacée par le point d'entrée unique de L3 ? »

### L5 — Script remplacé après le contrôle d'empreinte (TOCTOU)

**Risque réel (en clair).** Le contrôle calcule l'empreinte du fichier **puis** bash continue de **lire le script au fur et à mesure** ; une ligne ajoutée entre les deux s'exécute (démontré : le script bloqué sur l'étape `docker`, ligne ajoutée, la ligne s'exécute). Le « tampon » ne couvre donc pas ce qui s'exécute réellement.
* **Qui / quel accès** : quelqu'un qui peut **écrire dans le dossier pendant l'exécution** (fenêtre d'une à plusieurs minutes pendant la sauvegarde : `docker exec` peut durer). C'est la limite qui **exige le plus** : l'attaquant doit déjà avoir le droit d'écriture (comme L1) **et** viser le bon moment. Sans ce droit, personne ne peut l'exploiter.
* **Gravité / probabilité** : impact **élevé** mais **probabilité la plus faible** des cinq (double condition). Elle ne vaut surtout que comme **preuve** que « contrôler puis lire » ne suffit pas.

| Solution | Ce qu'elle apporte | Coût | Verdict |
|---|---|---|---|
| **A. S2 (instantané)** : on exécute la **copie** qui a été hachée | La modification de l'original n'a plus d'effet. Démontré par le prototype **[mesuré]**. | Inclus dans S2. | **Recommandée**. |
| **B. S1 avec `LoadCredential=`** (systemd copie le fichier dans un dossier privé en lecture seule au démarrage) ou `BindReadOnlyPaths=` | Instantané fourni par systemd, sans code supplémentaire. | **[hyp]** : comportement à valider sur le serveur d'essai ; dépend de la version de systemd ; la copie par systemd n'est pas elle-même hachée sans contrôle. | Piste intéressante, à tester avant de s'y fier. |
| **C. S4/S6 : fichiers immuables (`chattr +i`) dans un dossier root-only** | La fenêtre n'existe plus pour un non-root ; **root** peut encore faire `chattr -i`. | Peu cher. | Palier (réduit, n'élimine pas). |
| **D. Charger tout le script en mémoire avant exécution** (`bash -c "$(cat …)"` après contrôle) | Supprime la relecture au fil de l'eau. | **Code de procédure à modifier**, et reste auto-attesté (L1). | Non retenue seule. |

**Recommandation** : **A** (S2) ; **C** en palier ; **B** à étudier sur un serveur d'essai.
**Décision propriétaire** : « Acceptez-vous que ce qui s'exécute soit toujours une copie figée de ce qui a été approuvé, et non le fichier du dossier ? »

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 4. Tableau de couverture (qui résout quoi)

| | L1 garde réécrite | L2 lecteur avant contrôle | L3 `LD_PRELOAD` | L4 `env -i` ne suffit pas | L5 TOCTOU | Contre l'agent root autonome |
|---|---|---|---|---|---|---|
| S1 systemd | non (le contrôle reste à faire) | non | **oui** | **oui** | partiel (si `LoadCredential`/lecture seule, **[hyp]**) | non |
| S2 vérificateur statique + instantané | **oui** | **oui** | **oui** | **oui** | **oui** | non seul (empreintes locales) |
| S2 + S3 signature | **oui** | **oui** | **oui** | **oui** | **oui** | **oui en pratique** (approbation = secret absent du serveur), pas contre root qui remplace le binaire/la clé (effraction **visible**) |
| S4 copie immuable + petit contrôleur | partiel | partiel | non (hors systemd) | non | partiel | non |
| S5 utilisateur dédié | non | non | **réduit** (le dégât devient celui de `tb-run`) | **réduit** | non | **non** (root reste root) ; **gain illusoire** si `tb-run` est dans le groupe `docker` |
| S6 droits durcis + audit | détecte | détecte | non | non | réduit | **détecte** (journal), n'empêche pas |

## 5. Recommandation d'ensemble et paliers

**Cible (à retenir) : S1 + S2 + S3**, périmètre initial **limité aux deux scripts de sauvegarde** (`backup-quotidien.sh`, `verifier-sauvegarde.sh`) — c'est exactement la recommandation de `CONCEPTION-GARDE-CONFIANCE-RC25.md` (§4), que je confirme à la lecture des 5 tests : **les cinq limites tombent avec les mêmes trois pièces**, et aucune ne peut être résolue par une retouche des scripts.

Pourquoi **systemd en plus** du vérificateur statique : il apporte l'environnement propre, le journal et l'alerte d'échec (qui n'existent pas aujourd'hui) pour peu de coût, et il règle L3/L4 sans dépendre d'un binaire. Le vérificateur règle L1, L2, L5 ; la signature règle T3.

**Paliers** (chacun utile seul, aucun ne bloque le suivant) :
1. **Palier 0 — aucun code** : S6 (déplacer l'arbre hors de `/root`, droits stricts, `chattr +i`, audit des droits par une unité d'essai) + corriger le texte qui laisse croire que `env -i … bash -p` protège de `LD_PRELOAD` (L4). *Résultat* : L1/L2/L5 réduits aux seuls porteurs de root ; L4 n'induit plus en erreur.
2. **Palier 1 — configuration systemd** (S1) : unité + minuteur + `OnFailure=` (alerte). *Résultat* : L3 et L4 supprimés sur tout lancement, journal d'exécution.
3. **Palier 2 — vérificateur (S2) avec empreintes locales** : L1, L2, L5 supprimés contre l'erreur et le non-root.
4. **Palier 3 — signature (S3)** : approbation hors serveur ; l'agent root ne peut plus s'auto-approuver.
5. **Palier 4 — élargir** à déploiement / retour arrière / promotion, selon décision.

**Non recommandé** : S5 (utilisateur dédié) **comme remède**, tant que le script a besoin de `docker` avec les droits du démon ; à reconsidérer seulement si la sauvegarde est réécrite sous forme de commandes à liste blanche (hors périmètre).

## 6. Ce qui reste hors de portée et risques de la solution recommandée

* **Root** : peut remplacer le vérificateur, la clé publique, l'unité systemd, `/etc/ld.so.preload`. La signature rend l'attaque **visible** (empreinte du binaire / de la clé notée hors serveur, journal hors serveur), pas impossible. À ne jamais présenter comme une défense contre root.
* **Disponibilité** : échec fermé = sauvegarde arrêtée en cas de doute ; **sans alerte, cela passe inaperçu** (point d'ouverture d'ailleurs déjà signalé dans `RAPPORT-GARDE-PRODUCTION-RC25.md` §4). L'alerte est donc **indissociable** du chantier.
* **Nouveau code de sécurité** (S2) : bogues possibles, chaîne d'approvisionnement du compilateur, besoin de revue indépendante et de construction reproductible.
* **Hypothèses non vérifiées ici** : droits réels du serveur, présence/version de systemd, appartenance au groupe `docker`, sudoers. **Rien de ce qui précède n'a été exécuté** : conception seulement, aucune installation, aucun test.

## 7. Décisions à faire valider par le propriétaire (une phrase chacune)

| N° | Décision | Réponse recommandée |
|---|---|---|
| **G1** | « Tous les lancements sensibles (même manuels) passent-ils par un point d'entrée unique et extérieur aux scripts (unité systemd, puis vérificateur) ? » (règle L3, L4) | **Oui.** |
| **G2** | « Un petit programme extérieur, qui n'est pas un des fichiers vérifiés, décide-t-il seul de ce qui s'exécute en production ? » (règle L1, L2, L5) | **Oui**, périmètre initial = les deux sauvegardes. |
| **G3** | « Voulez-vous une clé de signature gardée hors du serveur (poste ou support matériel) pour approuver chaque nouvelle version, au prix d'une étape de signature par version ? » (T3 : agent root) | **Oui** ; sinon repli sur empreintes locales (sans protection contre l'agent root). |
| **G4** | « Acceptez-vous d'abord un palier sans nouveau code (arbre déplacé hors de `/root`, droits stricts, `chattr +i`, audit des droits) et la correction des textes qui présentent `env -i … bash -p` comme protecteur de `LD_PRELOAD` ? » | **Oui**, immédiatement. |
| **G5** | « Confirmez-vous que le serveur de production utilise bien systemd (sinon le lanceur statique devient le seul point d'entrée) et que l'agent autonome garde ou non les droits root ? » | À vérifier par le propriétaire ou l'exploitant ; non vérifiable depuis cette session. |

Ces décisions s'ajoutent à D1–D11 de `CONCEPTION-GARDE-CONFIANCE-RC25.md` (elles en précisent surtout D1, D3, D4, D8) et à la décision déjà en attente `billing-g5-sauvegarde-quotidienne` : **sans cette dernière, rien n'est installé**, quel que soit le choix ci-dessus.

## 8. Tests à prévoir (conception, rien n'est écrit)

Principe fixé par le dossier précédent (§10, étape 5) : **ne supprimer aucun `expectedFailure` avant que son remplaçant échoue puis réussisse.**

| Limite | Test de remplacement (sur un serveur d'essai, jamais la production) | Critère objectif |
|---|---|---|
| L1 | `tb-common.sh` réécrit (`is_production() { return 1; }`), lancement par le point d'entrée | code ≠ 0, aucune commande `docker` journalisée |
| L2 | `lire-conf.sh` avec une ligne de premier niveau (témoin) | témoin absent ; refus journalisé |
| L3 | `LD_PRELOAD=<bibliothèque d'essai>` dans l'environnement de `systemctl start` / de `tb-gate run` | marqueur absent |
| L4 | idem avec l'ancienne commande `env -i … bash -p` **remplacée** : le point d'entrée documenté ne passe plus par `env` | marqueur absent ; texte de `cron-sauvegarde.example` à jour |
| L5 | script modifié pendant l'étape `docker` bloquée | ligne ajoutée **non** exécutée |
Chaque test doit tourner d'abord **contre l'état actuel** (échec attendu constaté), puis contre l'état cible (réussite). Les tests unitaires du prototype (`tests/test_gate_prototype.py`) couvrent déjà L1, L2, L3, L5 pour le vérificateur seul **[mesuré]** ; manquent : le lancement réel par unité systemd, les règles `sudoers`, `LoadCredential=` et le comportement de `chattr +i`, **tous non exécutables dans cette session**.

## 9. Mise en œuvre (non exécutée) — ordre proposé après décision
1. Consigner G1–G5 (Decision Center) ; lever la décision `billing-g5-sauvegarde-quotidienne`.
2. Palier 0 (droits, déplacement hors de `/root`, textes) sur un **serveur d'essai** d'abord.
3. Palier 1 : unité systemd + `OnFailure=` ; test réel de L3/L4.
4. Palier 2 : implémentation de `tb-gate` à partir du prototype (revue indépendante), tests de remplacement des 5 `expectedFailure`.
5. Palier 3 : cérémonie de clé, première release signée, installation sur l'essai puis sur la production **sur décision écrite**.
6. Retrait des approbations locales (`approuver-sauvegarde.sh`) devenues inutiles.
**Retour arrière** à chaque palier : désactiver le minuteur / retirer l'unité = retour au **blocage total de la production sans `CONFIRM_PROD`** (comportement actuel du dépôt) ; aucune donnée de l'application n'est concernée.
