# RC25 — Conception d'une architecture de confiance indépendante pour la garde de production

**Statut : PROPOSITION POUR DÉCISION. Rien n'est implémenté, installé ni activé.** Aucun fichier de production n'a été modifié : `app/`, `procedure/*.sh`, `prod.conf`, `staging.conf`,
le cron, `/etc`, `/root`, `/opt` sont intacts. Ajouts de cette livraison : ce document, un **prototype de faisabilité** non branché (`conception/rc25-gate-prototype/`) et trois fichiers de tests
(`tests/test_gate_prototype.py`, `tests/test_procedure_residuel.py`, plus les `expectedFailure` déjà présents dans `tests/test_procedure_adverse.py`).
Départ : commit `59ee4449a5cd9f885dacc35e6b40ad79fdffb5cc` (branche `claude/rc25-garde-conf-sans-source`, PR #4 en brouillon). La garde actuelle **n'est pas validée pour la production**.

Légende : **[mesuré]** = observé dans cette session (commande et résultat conservés dans le compte rendu) ; **[propos]** = proposé, non réalisé ; **[hyp]** = hypothèse non vérifiable ici
(serveur réel, systemd, cron, noyau de production absents).

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 1. Architecture actuelle et chemin d'exécution (relevé dans le code, commit `59ee444`)

```
 cron (/etc/cron.d, non installé) ──► env -i PATH=… /bin/bash -p  backup-quotidien.sh <prod.conf>
                                                │
        (1) ligne 11-12 du script : contrôle d'environnement en mots-clés bash (BASH_FUNC_ / BASH_ENV)         ← code du script lui-même
        (2) . "$_d/tb-common.sh"                                                                               ← fichier modifiable par qui peut écrire le dossier
                │     (3) . lire-conf.sh          (code exécuté AVANT toute vérification d'empreinte)           ← idem
                │     (4) lire_conf prod.conf     (données validées ; jamais exécutées)
                │     (5) is_production ? ──oui──► CONFIRM_PROD ?  ── sinon ──► backup_exception_ok :
                │                                     stat / readlink / sha256sum / awk (PATH fixe) sur : le script, tb-common.sh, lire-conf.sh
                │                                     fichier d'empreintes /etc/time-billing/approved-scripts.sha256 (root-only)
                ▼
        (6) docker exec / docker cp / sha256sum / ls / xargs …  (PATH hérité du lanceur)                       ← commandes sensibles
```

**Ce qui s'exécute avant toute vérification d'intégrité** : l'interpréteur (variables `BASH_ENV`, `SHELLOPTS`, fonctions importées, `LD_PRELOAD` du lanceur), les lignes de contrôle d'environnement du
script, `tb-common.sh`, `lire-conf.sh`. **Ce qui peut modifier ou contourner les contrôles** : tout porteur du droit d'écriture sur ces trois fichiers ou sur leurs dossiers ; tout processus qui
démarre l'interpréteur avec un environnement hostile (`BASH_ENV`, `LD_PRELOAD`) ; un racer qui écrit dans le dossier après la vérification (le script est lu au fil de l'eau).
**Défaut de conception structurel** : *le contrôle d'intégrité est lui-même un des fichiers contrôlés* (auto-attestation).

### Faits mesurés sur cet hôte (bash 5.2.21, Linux 6.18.44, OpenSSL 3.0.13, Go 1.24.7, gcc ; **pas** de systemd actif, pas de cron)

| Vecteur dans l'environnement du lanceur | `bash script` | `bash -p script` | `env -i PATH=… bash script` | `env -i PATH=… bash -p script` | lanceur **statique** → `bash -p` |
|---|---|---|---|---|---|
| `BASH_ENV=fichier` | **exécuté** [mesuré] | ignoré [mesuré] | ignoré [mesuré] | ignoré [mesuré] | ignoré [mesuré] |
| fonction exportée (`readlink`) | **appelée** [mesuré] | non importée [mesuré] | non importée [mesuré] | non importée | non importée [mesuré] |
| `SHELLOPTS=xtrace` | **trace de chaque commande** développée sur stderr [mesuré] | ignoré [mesuré] | ignoré [mesuré] | ignoré [mesuré] | ignoré |
| `SHELLOPTS=xtrace` + `PS4='$(cmd)'` | trace oui ; `$(cmd)` **non évalué** par ce bash [mesuré] | ignoré | ignoré | ignoré | ignoré |
| `LD_PRELOAD=hostile.so` | **constructeur exécuté** dans bash [mesuré] | **constructeur exécuté** dans bash [mesuré] | **exécuté dans `env`** (binaire dynamique) [mesuré] | **exécuté dans `env`** [mesuré] | **jamais chargé** [mesuré] |

Enseignements : (a) `env -i … bash -p` neutralise `BASH_ENV`, `SHELLOPTS`, les fonctions exportées — **mais pas `LD_PRELOAD`** : `env` est un exécutable dynamique qui charge la bibliothèque *avant* d'effacer
l'environnement. (b) Seul un **lanceur statique** (aucun chargeur dynamique) est insensible à `LD_PRELOAD`. (c) `sudo` (env_reset) nettoie l'environnement de l'enfant, mais `LD_PRELOAD` s'exécute dans
`sudo` lui-même quand l'appelant est root [mesuré] ; pour un appelant non privilégié, `ld.so` ignore `LD_PRELOAD` sur un binaire setuid [hyp : comportement documenté de glibc, non testé ici].
(d) Un `PS4` hostile n'est pas évalué par bash 5.2.21 : propriété de cette version, gardée par un test-canari. (e) `bash -p` ne protège **ni les processus enfants** (un enfant `#!/bin/bash` lancé sans `-p`
réimporte les fonctions si l'environnement en contient encore — constaté avec le faux docker des tests) **ni** l'interpréteur lui-même contre `LD_PRELOAD`. D'où la nécessité de **reconstruire l'environnement** avant tout `execve`.

**Modèle de menace retenu.** Un processus root est tout-puissant : on ne prétend pas défendre contre root. On défend contre : (T1) un porteur d'écriture non root (compte applicatif, dépôt cloné
avec de mauvais droits) ; (T2) un environnement hérité contaminé (shell de login, automate, agent qui lance les scripts avec l'environnement de son choix) ; (T3) une erreur ou une initiative
d'un **agent root autonome** qui « répare » un script ou son approbation pour le faire passer (risque ouvert dans la mission du propriétaire) ; (T4) la dérive (fichier modifié par erreur après approbation). Root malveillant
et noyau compromis sont hors périmètre (§8).

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 2. Principes

1. **Le vérificateur n'appartient pas à l'ensemble qu'il vérifie** (ni script, ni configuration, ni fichier d'empreintes consultable avant lui).
2. **Aucun code d'un environnement non maîtrisé ne s'exécute avant le contrôle** : le premier programme est un exécutable **statique** ; il reconstruit l'environnement ; il lance l'interpréteur en `-p`.
3. **On exécute ce qu'on a vérifié, pas ce qu'on a trouvé** : les octets lus sont hachés puis copiés dans un **instantané privé** ; l'instantané est ce qui s'exécute (pas de course après la copie).
4. **La décision « production » est prise par le vérificateur** (confirmation passée en argument, opération autorisée dans le manifeste) ; la garde des scripts reste en seconde barrière, jamais en unique barrière.
5. **Échec fermé** à chaque doute (fichier absent, propriétaire, droits, lien, signature, empreinte, version, verrou).

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 3. Options comparées

### Option A — Vérificateur indépendant, approbation locale par empreintes
`/usr/local/sbin/tb-gate` (exécutable statique, root:root 0755) ; manifeste `/etc/time-billing/gate/manifest.json` (empreintes SHA-256 de chaque fichier de la « release » : scripts, `tb-common.sh`,
`lire-conf.sh`, `prod.conf`) ; l'approbation est faite **sur le serveur, par root**, avec `tb-gate approve`.

### Option B — Vérification cryptographique (manifeste signé hors serveur)
Même vérificateur, mais le manifeste est **signé en Ed25519 par une clé privée qui n'est jamais sur le serveur** (poste du propriétaire, idéalement matériel). La clé publique (32 octets) est dans
`/etc/time-billing/gate/release.pub`. Une mise à jour = bundle signé + `tb-gate install`, qui vérifie la signature, un **numéro de séquence croissant** (anti-retour arrière) et les droits.

### Option C (troisième, écartée pour RC25) — Sauvegarde « tirée » depuis l'extérieur
Le serveur n'exécute aucun script de sauvegarde planifié ; un hôte extérieur tire la sauvegarde par une clé SSH restreinte à une commande fixe, ou l'application planifie elle-même sa sauvegarde.
Supprime le problème du script root planifié, **mais exige une modification de `app/` ou une infrastructure externe** (hors périmètre, hors décision actuelle) et ne règle pas la chaîne de déploiement. À reconsidérer si le propriétaire
préfère déplacer le problème plutôt que le résoudre.

| Critère | A — empreintes locales | B — manifeste signé hors serveur |
|---|---|---|
| Vérificateur hors de l'ensemble vérifié | oui | oui |
| Environnement reconstruit / insensible à `LD_PRELOAD`, `BASH_ENV`… | oui (binaire statique) | oui |
| Instantané exécuté (pas de course après copie) | oui | oui |
| Modification par un non-root détectée | oui | oui |
| Dérive involontaire détectée | oui | oui |
| **Agent root « qui s'auto-approuve »** (T3) | **non** : `tb-gate approve` est une commande root du serveur ; l'agent peut la lancer | **oui, en pratique** : l'approbation exige une signature que le serveur ne peut pas produire ; l'agent peut seulement échouer (ou remplacer visiblement `release.pub`/`tb-gate`, ce qui sort du fonctionnement normal et se journalise à l'extérieur) |
| Root malveillant | non protégé | **non protégé non plus** : root peut remplacer `tb-gate` et `release.pub`. Ne pas présenter la signature comme une défense contre root. Gain réel : l'approbation d'un contenu **nouveau** exige un secret absent du serveur, et l'effraction se voit (binaire/clé changés) |
| Empreinte stockée à côté des scripts | c'est le cas de A : protège de T1/T2/T4 seulement | non (clé de confiance séparée du contenu) |
| Anti-retour arrière | à ajouter (compteur local, effaçable par root) | séquence signée + compteur local |
| Charge d'exploitation | faible | moyenne : gestion d'une clé (génération, sauvegarde, rotation, perte) et d'une étape de signature à chaque version |
| Dépendances nouvelles sur le serveur | 1 binaire statique (2 Mo, Go) | idem (la vérification Ed25519 est dans le binaire ; `openssl` sert au poste du propriétaire) |
| Faisabilité démontrée ici | oui (§7) | oui (§7 : signature, mauvaise clé, manifeste altéré) |

**Mesures de la faisabilité (prototype, hors production)** : 8 tests `tests/test_gate_prototype.py` OK : exécution depuis instantané, environnement hostile sans effet (y compris `LD_PRELOAD`), `env -i` seul
insuffisant contre `LD_PRELOAD` / vérificateur statique suffisant, script / manifeste / signature altérés refusés, chaîne non fiable refusée (dossier modifiable, groupe, autre propriétaire, clé modifiable, lien symbolique), parent
modifiable refusé / sticky toléré, échec fermé, source remplacée pendant l'exécution sans effet.

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 4. Recommandation unique

**Option B réduite à son noyau : le vérificateur statique indépendant de l'option A, avec manifeste signé hors serveur, périmètre initial limité aux deux opérations de sauvegarde.**
Justification : A seul laisse l'approbation à portée de l'agent root autonome (T3), qui est précisément le risque ouvert nommé dans la mission du propriétaire ; B ajoute cette séparation pour le coût d'une clé de 32 octets et
d'une commande de signature, sans changer le vérificateur (A est B sans le test de signature : on peut commencer par A et ajouter la signature sans refonte, c'est le plan §9). Les garanties réelles (§8) sont énoncées sans prétendre résister à root.
Si le propriétaire ne veut pas gérer une clé, **A est un repli valable** contre T1, T2, T4 — pas contre T3.

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 5. Spécification proposée

### 5.1 Schéma du chemin de confiance et du chemin d'exécution
```
   RACINE DE CONFIANCE (mise en place par le propriétaire, vérifiée hors serveur)          CHEMIN D'EXÉCUTION (à chaque lancement)
   ───────────────────────────────────────────────────────────────────────────          ─────────────────────────────────────────────
   clé privée Ed25519  (hors serveur)                                                      cron / systemd (fichier root:root, environnement fixé par lui)
            │ signe                                                                                    │
            ▼                                                                                          ▼
   manifeste.json  {sequence, release, files[{path,sha256}], ops{backup-quotidien:{…}}}   /usr/local/sbin/tb-gate run backup-quotidien      ← STATIQUE
            │ + release.pub (32 o) installée root:root                                                │ 1. chaîne de confiance de chaque fichier (lstat, root, non lien, non inscriptible)
            ▼                                                                                          │ 2. signature du manifeste (release.pub) ; sequence ≥ compteur local
   tb-gate (binaire statique, empreinte notée hors serveur)  ◄─── seule pièce « code » de confiance │ 3. lecture UNIQUE de chaque fichier → SHA-256 des octets lus → copie dans l'INSTANTANÉ
                                                                                                       │    /run/time-billing/gate/snap-XXXX (tmpfs, 0700 root, fichiers 0500)
   Hors racine (vérifiés par la racine, jamais autorité) :                                             │ 4. opération autorisée par le manifeste ; production : confirmation passée en argument
   scripts, tb-common.sh, lire-conf.sh, prod.conf, la garde interne des scripts                        │ 5. verrou (flock) ; journal (fichier + syslog) de CHAQUE décision
                                                                                                       │ 6. execve("/bin/bash","-p", snapshot/script, env reconstruit explicite, PATH root-only)
                                                                                                       ▼
                                                                                              script (copie vérifiée) → garde interne (2ᵉ barrière) → docker …
```

### 5.2 Fichiers constituant la racine de confiance
1. **Le noyau et le démarrage** (hors périmètre, supposés sains).
2. `/usr/local/sbin/tb-gate` (binaire statique) et sa chaîne de dossiers.
3. `/etc/time-billing/gate/release.pub` (clé publique) — et, en repli A, `manifest.json` qui devient alors autorité.
4. La **clé privée de signature** (hors serveur) — racine de l'**approbation**, pas de l'exécution.
5. Les binaires système appelés par les scripts (`/bin/bash`, `docker`, coreutils) : racine **par chemin** (propriétaire/droits/liens vérifiés par le vérificateur ; leur contenu relève du gestionnaire de paquets).
6. Le fichier root de planification (`/etc/cron.d/time-billing-sauvegarde` ou l'unité systemd) et `/etc/ld.so.preload` (doit être absent ou vide ; le vérificateur est statique donc non concerné, mais `bash` l'est).

Ne sont **pas** racine de confiance : `tb-common.sh`, `lire-conf.sh`, `prod.conf`, `approuver-sauvegarde.sh` (remplacé par `tb-gate install/approve`), les scripts eux-mêmes.

### 5.3 Propriétaires et permissions exigés (échec fermé sinon ; chaque parent jusqu'à `/`)
| Chemin | Propriétaire | Mode | Remarque |
|---|---|---|---|
| `/`, `/usr`, `/usr/local`, `/usr/local/sbin` | root:root | 0755 (aucun droit d'écriture groupe/autres) | parents du vérificateur |
| `/usr/local/sbin/tb-gate` | root:root | 0755, fichier ordinaire, pas un lien | empreinte notée hors serveur à l'installation |
| `/etc`, `/etc/time-billing`, `/etc/time-billing/gate` | root:root | 0755 | |
| `…/gate/release.pub`, `manifest.json`, `manifest.sig` | root:root | 0644 | pas de lien symbolique |
| `/usr/local/lib/time-billing/<release>/` et fichiers | root:root | dossiers 0755, scripts 0755, fichiers 0644 | **hors de `/root`** ; jamais un clone de travail |
| `/var/lib/time-billing/gate`, `…/sequence` | root:root | 0700 / 0600 | compteur de séquence |
| `/run/time-billing/gate` (tmpfs) | root:root | 0700 | instantanés ; vidés au redémarrage |
| `/var/log/time-billing/` | root:root | 0750 ; journal 0600 | + copie syslog / hôte distant |
| `/etc/cron.d/time-billing-sauvegarde` | root:root | 0644 | cron ignore un fichier aux droits incorrects |
| Dossier de sauvegardes `BACKUP_BASE` | root:root | 0700 | inchangé |
Sticky bit toléré uniquement sur un **ancêtre** (ex. `/tmp`), jamais sur le dossier ou le fichier vérifié.

### 5.4 Point d'entrée et commande de lancement exacts
Un seul point d'entrée pour toute opération pouvant atteindre la production : `tb-gate run <opération>`.
```
# cron (jamais installé par cette livraison) — pas besoin de « env -i … bash -p » : le vérificateur reconstruit l'environnement
17 2 * * *  root  /usr/local/sbin/tb-gate run backup-quotidien      >> /var/log/time-billing/backup.log 2>&1
43 3 * * 0  root  /usr/local/sbin/tb-gate run verifier-sauvegarde   >> /var/log/time-billing/backup.log 2>&1
# manuel (opération non planifiable, confirmation datée vérifiée PAR le vérificateur, pas par le script)
/usr/local/sbin/tb-gate run <opération> --confirm OUI-$(date -u +%Y%m%d)
```
Le vérificateur exécute : `execve("/bin/bash", ["/bin/bash","-p","<instantané>/<script>", <conf du manifeste>, …], env)` avec `env = {PATH=/usr/sbin:/usr/bin:/sbin:/bin, LANG=C.UTF-8, HOME=/root, TB_GATE=1}` et rien d'autre.
Les scripts **sensibles ne doivent être lancés que par ce point d'entrée** ; leur lancement direct reste possible pour le staging (même code), mais la production n'est atteignable sans `tb-gate` que par la garde interne
(seconde barrière, non fiable seule : voir `expectedFailure` d'auto-attestation).

### 5.5 Approbation et mise à jour
1. **Poste du propriétaire** : `git archive <sha du commit approuvé>` → arbre de release ; calcul du manifeste (`sequence` = précédent + 1, empreintes, opérations autorisées, conf associée) ; **signature hors serveur** (`openssl pkeyutl -sign -rawin`, exemple du prototype).
2. Transfert du bundle (arbre + `manifest.json` + `manifest.sig`) ; l'**empreinte du bundle est lue à voix haute / comparée par un second canal**.
3. Sur le serveur, root : `tb-gate install <bundle>` → vérifie signature, `sequence` > compteur, chaîne de confiance de la cible, dépose dans `/usr/local/lib/time-billing/<release>/` (écriture dans un dossier temporaire puis `rename`), met à jour le compteur. **Aucune édition sur place.**
4. Retour arrière = nouvelle signature d'un contenu ancien avec une `sequence` supérieure (jamais une séquence plus basse).
5. Mise à jour du binaire `tb-gate` : remplacement par le propriétaire avec contrôle d'empreinte hors serveur ; hors cycle des releases.
6. Perte de clé : procédure de remplacement de `release.pub` **sur place par le propriétaire, en présence d'un second contrôle** (décision D6).

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 6. Fichiers produits, prototype et limites du prototype
`conception/rc25-gate-prototype/main.go` (≈120 lignes) : signature, chaîne de confiance par `lstat` composant par composant, lecture unique + SHA-256 + copie, `execve` avec environnement reconstruit.
**Ce n'est pas l'implémentation.** Limites connues du prototype (à traiter à l'implémentation) : la chaîne est contrôlée par chemin (`lstat`) puis le fichier est ouvert avec `O_NOFOLLOW` : un
remplacement d'un ancêtre entre les deux par un acteur capable d'écrire dans un dossier root-only (root) reste possible → utiliser `openat2(RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS)` et comparer `fstat` au `lstat` ;
pas de verrou ; pas de journal ; pas de validation de la conf par le vérificateur ; pas de nettoyage des instantanés ; pas de compteur de séquence ; l'instantané n'est pas scellé (root peut l'écrire pendant l'exécution).

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 7. Tests adverses : comportement attendu, critère objectif, état

| # | Scénario | Comportement attendu | Critère objectif | Fichier / état |
|---|---|---|---|---|
| 1 | `tb-common.sh` modifié pour toujours dire « pas production » | **actuel** : non détecté (auto-attestation). **cible** : refus par le vérificateur | marqueur / appel docker absent | `test_procedure_adverse.py::test_KNOWN_LIMIT_a_rewritten_guard…` **expectedFailure** (échec constaté : la sauvegarde a tourné) ; cible : `test_gate_prototype` (empreinte différente → REFUS) **OK** |
| 2 | `lire-conf.sh` modifié, commande avant validation | **actuel** : le code s'exécute avant la vérification. **cible** : jamais exécuté | marqueur absent | `…::test_KNOWN_LIMIT_a_modified_reader…` **expectedFailure** ; cible : `test_modified_script_modified_manifest…` **OK** (aucune exécution sur REFUS : stdout vide) |
| 3 | `BASH_ENV` hostile | **actuel** : la charge s'exécute avant le script puis le script refuse. **cible** : jamais | marqueur absent | `test_BASH_ENV_payload_runs_before…` **constat OK** ; cible : `test_hostile_caller_environment…` **OK** |
| 4 | `SHELLOPTS=xtrace` | **actuel** : accepté, commandes tracées. **cible** : refus / ignoré | rc ≠ 0 ou pas de trace | `test_RESIDUAL_shellopts…` **expectedFailure** ; `test_fact_dash_p_and_env_i_ignore_shellopts…` **OK** |
| 5 | `PS4='$(cmd)'` | non évalué (bash 5.2.21) | marqueur absent | `test_fact_ps4_command_substitution…` **OK** (canari de version) |
| 6 | `LD_PRELOAD` hostile (gcc disponible) | **actuel** : s'exécute (script direct, et `env -i … bash -p`). **cible** : jamais (lanceur statique) | marqueur absent | `test_RESIDUAL_ld_preload…` et `…documented_env_i_bash_p_launch…` **expectedFailure** ; `test_fact_ld_preload_runs…` **OK** ; `test_env_i_alone_does_not_stop_ld_preload_but_the_static_gate_does` **OK** |
| 7 | Fonctions exportées `builtin`, `readlink`, `date`, `dirname`, `stat`, `sha256sum`, `awk`, `cut`, `exit`, `.`, `source` | refus avant toute commande ; aucune fonction appelée | témoin absent, aucun appel docker | `test_procedure_adverse.py` (11 pièges × 12 scripts) **OK** ; cible : `…hostile_caller_environment…` (fonction `BASH_FUNC_dirname%%`) **OK** |
| 8 | Configuration modifiée / remplacée | refusée (hors manifeste) ; une conf hostile n'exécute rien | rc ≠ 0, témoin absent | actuel : `test_procedure_conf.py` (22 variantes) **OK** ; cible (hash de conf dans le manifeste) : même mécanisme que le test 1 de `test_gate_prototype` |
| 9 | Liens symboliques, parents modifiables, propriétaire | refus | rc ≠ 0, aucune exécution | `test_untrusted_chain_is_refused`, `test_parent_directory_writable…` **OK** ; actuel : `test_procedure_guard.py` **OK** |
| 10 | TOCTOU : fichier remplacé après la vérification | **actuel** : la ligne ajoutée s'exécute. **cible** : sans effet (instantané) | marqueur absent | `test_RESIDUAL_a_script_replaced_after_the_hash_check…` **expectedFailure** (échec constaté) ; cible : `test_replacing_the_source_while_the_script_runs_has_no_effect` **OK** |
| 11 | Docker absent | arrêt propre, aucune sauvegarde partielle | rc ≠ 0, aucun `.db` | `test_fact_docker_absent_stops_the_backup_cleanly` **OK** |
| 12 | Chargement de la garde en échec (`tb-common.sh` / `lire-conf.sh` absents) | arrêt, aucun docker | rc ≠ 0, journal docker vide | `test_fact_missing_reader_or_guard_file…`, `test_entry_scripts_stop_when_the_guard_cannot_be_loaded` **OK** |
| 13 | Signature : manifeste altéré, mauvaise clé | refus | rc = 3, stdout vide | `test_modified_script_modified_manifest…` **OK** |

**Tests impossibles à exécuter ici** (déclarés **non exécutés**) : lancement réel par cron / unité systemd (aucun des deux actif) ; règles `sudoers` du serveur (modification de `/etc` interdite) ; chaîne réelle
`/usr/local/sbin` du serveur de production ; docker réel et conteneur de production ; `openat2` et sceaux `memfd` en conditions réelles du noyau de production ; attaquant root ; compromission du noyau ;
reconstruction reproductible du binaire sur une autre machine ; clé matérielle ; récupération après perte de clé ; `LD_PRELOAD` via `/etc/ld.so.preload` (fichier réel) ; versions de bash différentes de 5.2.21.

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 8. Garanties réelles et risques résiduels

**Garanties (conditionnées aux permissions du §5.3) :** un contenu non approuvé ne s'exécute pas sous le nom d'une opération sensible ; l'environnement de l'appelant n'atteint ni le vérificateur
(statique) ni l'interpréteur (reconstruit, `-p`) ; ce qui s'exécute est ce qui a été haché (instantané) ; un agent root qui édite un script, une conf ou le manifeste ne peut pas faire accepter le résultat sans
la clé de signature (B) ; chaque décision est journalisée.

**Risques résiduels (non éliminés) :**
* **Root** : peut remplacer `tb-gate`, `release.pub`, `/etc/ld.so.preload`, le cron, ou écrire dans l'instantané. La signature ne protège pas contre lui ; elle rend l'effraction visible (empreinte du binaire / de la clé ; journal distant).
* **Noyau / hyperviseur** compromis : hors périmètre.
* **TOCTOU** : éliminée entre vérification et exécution du **contenu** par l'instantané ; subsiste (a) la fenêtre `lstat`→`open` pour un acteur capable d'écrire dans un dossier root-only (prototype), (b) l'écriture de l'instantané pendant l'exécution par root, (c) les binaires système (`docker`, coreutils) vérifiés par chemin et non par contenu, (d) le contenu du conteneur de production exécuté par `docker exec`.
* **Processus enfants** : l'environnement reconstruit est transmis, mais un enfant exécute le code de ses binaires ; `bash -p` ne les protège pas.
* **Nouveau code de sécurité** (binaire Go) : bogues possibles, chaîne d'approvisionnement du compilateur, besoin de revue indépendante et de construction reproductible.
* **Disponibilité** : un échec fermé arrête la sauvegarde ; il faut une alerte (non existante aujourd'hui) et une copie hors serveur (non configurées).
* **Opérateur humain** qui lance un script directement avec `CONFIRM_PROD` : la garde interne reste la seule barrière sur ce chemin.
* **bash 5.2.21** seulement testé ; comportement de `PS4`/`SHELLOPTS` à re-vérifier à chaque changement de version.

---------------------------------------------------------------------------------------------------------------------------------------------------------------

## 9. Décisions exactes du propriétaire (avant toute implémentation)
* **D1 — Option** : (i) **B** manifeste signé hors serveur [recommandé], (ii) **A** empreintes locales [repli, sans protection contre T3].
* **D2 — Si B : clé** — qui la détient, support (matériel / poste hors ligne), sauvegarde, rotation, procédure de perte (D6).
* **D3 — Périmètre initial** — `backup-quotidien` et `verifier-sauvegarde` seulement [recommandé], ou aussi `deploy`/`rollback`/`promouvoir` dès la première version.
* **D4 — Planification** — cron ou unité systemd ? (non vérifiable ici : le serveur de production n'est pas accessible).
* **D5 — Nouveau binaire sur le serveur** — acceptation d'un exécutable statique Go (2 Mo) dans `/usr/local/sbin`, qui le construit, comment son empreinte est vérifiée hors serveur ; ou exiger une revue/réécriture.
* **D6 — Emplacement de l'arbre approuvé** — déplacer hors de `/root` vers `/usr/local/lib/time-billing/` (root-only), et procédure de perte / remplacement de clé.
* **D7 — Confirmation de production** — déplacer `CONFIRM_PROD` dans le vérificateur (argument `--confirm`, avec terminal obligatoire pour les opérations manuelles) [recommandé].
* **D8 — Agent root autonome** — conserve-t-il root ? Sinon, quels chemins lui sont interdits ; journal distant obligatoire pour `tb-gate` ?
* **D9 — Observabilité** — destination des journaux et alertes d'échec (aucune n'existe).
* **D10 — Prérequis déjà en attente** — décision `billing-g5-sauvegarde-quotidienne` (autoriser ou non la sauvegarde automatique) : sans elle, rien n'est installé.
* **D11 — Risques acceptés** — root, noyau, binaires système vérifiés par chemin.

## 10. Étapes ordonnées d'implémentation (après accord, sans les exécuter ici)
1. Trancher D1–D11 ; consigner la décision (Decision Center).
2. **FAIT (commit de ce paquet)** — Corriger d'abord le seul défaut mineur déjà démontré et réparable sans décision : refuser `SHELLOPTS` dans le contrôle d'environnement de la garde actuelle ; ne rien changer d'autre (le test `test_RESIDUAL_shellopts…` passerait alors de « échec attendu » à réussite et son décorateur serait retiré dans le même commit).
3. Écrire `tb-gate` à partir du prototype : `openat2`, verrou, journal (fichier + syslog), compteur de séquence, opérations nommées, validation de la conf (grammaire de `lire-conf.sh`) par le vérificateur, nettoyage des instantanés ; revue indépendante.
4. Construction reproductible (`CGO_ENABLED=0 go build -trimpath`), empreinte notée hors serveur ; tests unitaires + `tests/test_gate_prototype.py` étendu à l'implémentation.
5. Adapter les tests : transformer chaque `expectedFailure` d'auto-attestation en test de l'implémentation ; **ne supprimer aucun test avant que son remplaçant échoue puis réussisse**.
6. Journal et alerte d'échec ; copie hors serveur chiffrée (D9).
7. Répétition sur un **serveur d'essai** (jamais la production) : cron/systemd, permissions du §5.3, tous les tests de la §7 y compris ceux marqués impossibles ici.
8. Cérémonie de clé et première release signée (D2) ; `tb-gate install` sur l'essai puis sur la production, sur décision écrite.
9. Activation de la sauvegarde planifiée seulement ensuite (D10) ; retrait des exceptions d'empreinte locales (`approuver-sauvegarde.sh`) devenues inutiles.
10. Revue de sécurité finale ; supervision de la première semaine ; plan de retour arrière (désinstaller le cron, retirer `tb-gate` = retour au blocage total de la production sans CONFIRM_PROD).
