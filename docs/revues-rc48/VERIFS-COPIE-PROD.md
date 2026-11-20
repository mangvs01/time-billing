# Vérifications sur une COPIE de la base de production avant la mise en ligne de 9.2-rc48 (constat B)

Mission BILL-RC48-FIX. **Rien de ce document n'a été exécuté sur une base de production** : aucune base réelle n'a été ouverte pour l'écrire. Il est à exécuter par une personne habilitée, **sur une copie**, avec des instances jetables. Chaque étape dit ce qu'on attend et quoi faire sinon.

## 0. Règles

- Travailler sur une **copie** de la base (jamais sur le fichier vivant). Copie : la sauvegarde habituelle (`procedure/20-backup.sh`) ou `sqlite3 base.db ".backup copie.db"`. Garder le fichier d'origine intact ; refaire une copie neuve avant chaque étape qui écrit (étapes 3 à 6).
- Étapes 1 et 2 : **lecture seule** (le script ouvre la base en `mode=ro`, SQLite refuse toute écriture).
- Aucune instance jetable ne doit pouvoir joindre la production ni envoyer de courrier ; pas de réseau nécessaire.
- Code rc48 : cette branche (`campaign/billing-mdp`). Code rc47 : `git archive 2382090` extrait dans un dossier jetable.
- Interprète : `/root/venvs/rc25-test-venv/bin/python -I` (ou tout Python 3 ≥ 3.12 avec les dépendances de l'application).

## 1. Contrôles de données (lecture seule) — la requête de contrôle

Commande unique : `python3 -I outils/controle_copie_rc48.py COPIE.db` → code 0 = rien à signaler, 1 = au moins un point à traiter.

Elle exécute les contrôles suivants (SQL à copier si on préfère `sqlite3 -readonly COPIE.db`) :

| N° | Ce qui est cherché | Requête (résultat attendu : **aucune ligne** sauf mention) | Si une ligne sort |
|---|---|---|---|
| 1 | Adresses d'un même client qui ne diffèrent que par les majuscules | `SELECT client_key, group_concat(id\|\|':'\|\|label,' \| '), COUNT(*) FROM billing_addresses GROUP BY client_key, label COLLATE NOCASE HAVING COUNT(*)>1;` | **Renommer** l'une des deux adresses dans l'écran Adresses **sous rc47, avant la mise en ligne** (sinon rc48 ne crée pas son index d'unicité, les scripts `30-rehearse.sh`, `50-verify.sh` et `verifier-sauvegarde.sh` passent au rouge, et la restauration JSON de cette base est bloquée) |
| 2 | Idem après normalisation Unicode, espaces et casse complète (« Zürich » / « ZÜRICH », « Strasse » / « Straße ») | script Python de l'outil (`unicode_twins`) : regroupe `(client_key, NFC(libellé aux espaces réduits).casefold())` | Renommer avant. Depuis BILL-RC48-FIX, rc48 laisse ces adresses modifiables tant que leur nom ne change pas, mais elles restent des doublons à corriger |
| 3 | Noms d'adresse aux espaces non normalisés | `SELECT id, client_key, '['\|\|label\|\|']' FROM billing_addresses WHERE label<>trim(label) OR label LIKE '%  %';` | Vérifier à la main si c'est un doublon caché |
| 4 | Cas du constat D : même nom à la casse près dans la liste commune (`'*'`) et chez le client d'origine (`NOM:bsci`), écrit différemment | `SELECT g.id,g.label,n.id,n.label FROM billing_addresses g JOIN billing_addresses n ON g.client_key='*' AND n.client_key='NOM:bsci' AND g.label=n.label COLLATE NOCASE AND g.label<>n.label;` | Un retour arrière vers rc47 **sans** `outils/retour_rc47.py` ferait refuser le démarrage de rc47 ; utiliser l'outil (étape 6), ou renommer avant |
| 5a | Lignes manuelles dont le montant finit sur un demi-centime (**information**) | `SELECT id,invoice_id,qty,unit_rate FROM invoice_lines WHERE (CAST(ROUND(qty*1000000) AS INTEGER)*CAST(ROUND(unit_rate*10000) AS INTEGER)) % 100000000 = 50000000;` | Aucune action : ce sont les lignes où rc48 accepte un avoir total que rc47 refusait. Si elles portent déjà des avoirs, relever leur nombre pour l'étape 7 |
| 5b | Lignes de plus de 900 000 000 CHF (constat H, accepté en l'état) | `SELECT id,invoice_id,qty,unit_rate,qty*unit_rate FROM invoice_lines WHERE qty*unit_rate > 9e8;` | Écart possible d'un centime sur le plafond d'avoir de ces lignes : à examiner |
| 6 | Lignes créditées, dont une note a été annulée, puis recréditées (constat E, défaut déjà présent en rc47) | `SELECT l.invoice_line_id, COUNT(*) FROM credit_note_lines l GROUP BY l.invoice_line_id HAVING COUNT(*)>1 AND SUM(l.credit_note_id IN (SELECT credit_note_id FROM credit_note_cancellations))>0;` | La restauration JSON de cette base est refusée (même sous rc47) : pour toute restauration, utiliser le **fichier SQLite** de la sauvegarde. Correctif dans un lot séparé |
| 7 | Lignes d'avoir incohérentes avec leur ligne de facture | `SELECT l.id FROM credit_note_lines l JOIN invoice_lines il ON il.id=l.invoice_line_id JOIN credit_notes n ON n.id=l.credit_note_id WHERE il.invoice_id<>n.invoice_id OR il.vat_mode<>l.vat_mode;` | À examiner avant mise en ligne |
| 8 | Intégrité | `PRAGMA integrity_check;` → `ok` ; `PRAGMA foreign_key_check;` → aucune ligne | Ne pas poursuivre |

À consigner : la sortie complète de l'outil, la date, l'empreinte (`sha256sum`) de la copie.

## 2. Décision selon le résultat

- Les contrôles 1, 2, 3, 4, 7, 8 sont vides → rc48 peut être préparé tel quel.
- Un doublon (1 ou 2) → le renommer sous rc47 (écran Adresses), refaire une copie, relancer l'outil jusqu'à « RIEN À SIGNALER ». C'est la solution recommandée : elle rend sans objet la section « doublons » des notes de version (index créé, contrôles de procédure verts, restauration JSON possible).
- Contrôle 4 non vide → noter que le retour arrière doit passer par `outils/retour_rc47.py` (section 6).
- Contrôle 6 non vide → noter que la restauration JSON n'est pas utilisable pour cette base ; garder la sauvegarde du fichier SQLite comme filet.

## 3. Migration aller sur une COPIE neuve (écrit sur la copie, jamais sur la production)

```
COPIE=/chemin/jetable/copie-migree.db ; cp COPIE-ORIGINALE.db "$COPIE"
SECRET_KEY=$(python3 -c 'print("0"*64)') COOKIE_SECURE=0 INVOICE_CHECK_WORDS= APP_PASSWORD=mot-de-passe-fictif-12 DB_PATH="$COPIE" \
  /root/venvs/rc25-test-venv/bin/python -I -c "import sys; sys.path.insert(0,'/root/billing-mdp'); import app.app as m; m.init(); print(m.VERSION)"
```

Attendu : `9.2-rc48`, aucune erreur, puis sur `$COPIE` :

1. `SELECT name FROM sqlite_master WHERE name IN ('idx_billing_addresses_label_nocase','credit_line_upd_no_move_frozen','credit_line_upd_same_invoice','credit_line_upd_same_vat_mode','credit_line_upd_within_line','invoice_line_no_move_to_issued');` → **6 lignes**.
2. `SELECT sql LIKE '%qty*1000000%' FROM sqlite_master WHERE name='credit_lines_within_line';` → `1`.
3. `SELECT COUNT(*) FROM audit WHERE event='billing_address_label_index_skipped';` → `0`.
4. `python3 -I outils/empreinte_metier.py comparer COPIE-ORIGINALE.db "$COPIE"` → **identique**.
5. Relancer le démarrage ci-dessus une 2e fois : aucune différence (idempotence).
6. Contrôle de schéma complet (il vérifie maintenant aussi les 5 déclencheurs et le texte du plafond d'avoir) :
   `python3 -I -c "import sys,sqlite3; sys.path.insert(0,'/root/billing-mdp'); from app.schema_checks import rc19_problems as p; print(p(sqlite3.connect(sys.argv[1])))" "$COPIE"` → `[]`.
7. Les scripts de procédure `procedure/30-rehearse.sh`, `procedure/50-verify.sh`, `procedure/verifier-sauvegarde.sh`, lancés comme d'habitude par la personne habilitée sur la copie → verdict GO / OK.

## 4. Répétition de migration sur base fictive (déjà faite à chaque modification, à relancer)

`/root/venvs/rc25-test-venv/bin/python -I outils/repeter_migration_rc48.py` → **0 échec** (50 vérifications dont les constats C et D, contre le vrai code rc47).

## 5. Restauration JSON (copie, instances jetables)

1. Depuis la copie migrée (rc48), exporter le JSON (route `/backup`), l'aperçu puis restaurer **sous rc48** dans une instance jetable → « Restauration effectuée », contrôles d'intégrité OK.
2. Sur la copie, créer un avoir total de 0,23 sur une ligne 1,5 × 0,15 (voir `outils/repeter_migration_rc48.py`, constante `HALF`), exporter le JSON, puis tenter de le restaurer **sous rc47** : il est **refusé** (message en français : « le total des avoirs d'une ligne de facture dépasse le montant de cette ligne… ») : c'est le comportement attendu de rc47 (constat C), la base reste inchangée. Marche à suivre : section 6.
3. Restaurer un export JSON de la copie sous rc47 puis sous rc48 pour confirmer ou écarter le constat E (contrôle 6 de la section 1).

## 6. Retour arrière rc48 → rc47 sur la copie (l'application est arrêtée)

L'outil fait tout et vérifie son résultat : `python3 -I outils/retour_rc47.py base COPIE.db` (simulation, ne modifie rien) puis `… base COPIE.db --oui` : copie de sécurité vérifiée à côté (`COPIE.db.avant-retour-rc47-<horodatage>`), retrait des 6 objets de rc48, plafond d'avoir remis à celui de rc47, schéma vérifié, une ligne au journal d'audit, **aucune ligne métier touchée**.

- Démarrer le code rc47 sur la copie ainsi défaite : doit démarrer sans erreur (constat D), `rc19_problems` de rc47 vert.
- JSON rc48 à restaurer pendant que rc47 tourne (constat C) : `python3 -I outils/retour_rc47.py json SAUVEGARDE.json SORTIE.db` produit un fichier SQLite **au schéma rc47** contenant les données du JSON ; l'installer comme base (application arrêtée, base actuelle gardée à part) ou, plus simple, restaurer le **fichier SQLite** de la sauvegarde.
- Comparer ensuite schéma et données avec une base rc47 neuve (la répétition `repeter_migration_rc48.py` le fait : texte SQL de chaque déclencheur et index identique).
- Un nouveau passage de rc48 sur la base défaite refait la migration sans problème.

## 7. Compte rendu à fournir

| Contrôle | Résultat | Action |
|---|---|---|
| 1 à 4, 7, 8 vides ? | | |
| 5a : nombre de lignes à demi-centime / avoirs déjà posés dessus | | |
| 6 vide ? | | |
| Migration aller : 6 objets, plafond à la nouvelle formule, 0 note d'audit, empreinte identique | | |
| Procédures 30 / 50 / verifier-sauvegarde | | |
| Restauration rc48→rc48 ; rc48→rc47 refusée et marche à suivre vérifiée | | |
| Retour arrière par l'outil, rc47 démarre | | |


## Ajout BILL-RC48-FIX2
- Le contrôle 2 de `controle_copie_rc48.py` sur-signale volontairement (variantes NFC/NFD, espaces multiples) : un « À TRAITER » n'impose pas de renommer ; regarder d'abord si les deux libellés s'affichent identiquement (N-5).
- `retour_rc47.py` refuse tout chemin sous `/opt/time-billing-v9` sans `--confirmer-chemin-production` ; pour tester le mode `json` sur une copie, travailler sur la COPIE hors de `/opt/time-billing-v9`.
- Avant un retour `base` : lire l'avertissement sur les avoirs au-dessus du plafond de rc47 (N-3) et copier le fichier SQLite.


## 8. Commandes EXACTES du superviseur avant la mise en ligne (BILL-RC48-PREP)

Écrit le 2026-11-19. Rien ci-dessous n'a été lancé sur une base réelle ; chaque commande a été essayée sur une base fictive. Tout le bloc s'exécute **sur une copie** : l'étape A lit la production (sauvegarde SQLite en lecture), les étapes B à D n'ouvrent que la copie. Aucune de ces commandes ne touche `/opt/time-billing-v9` en écriture, n'arrête ni ne démarre de service, n'utilise Docker ni le réseau.

Préparation déjà faite (jetable, à refaire par le superviseur pour la vraie mise en ligne) : `/root/venvs/rc25-test-venv/bin/python -I outils/preparer_release.py 24744d2 rc48 --sortie DOSSIER_HORS_OPT --conf-precedente prod-rc47.conf` (essai du 2026-11-19 avec une conf fictive : 1267 tests OK, copie figée `9.2-rc48-24744d2`, empreinte `app/` `aa9786f5…30ce`, conf relue sans erreur).

```
# A. Copie de la base (la production n'est ouverte qu'en lecture ; remplacer PROD_DB par le chemin réel de la base)
cd /root/billing-mdp
W=$(mktemp -d /root/rc48-copie-XXXXXX) ; chmod 700 "$W"
sqlite3 -readonly PROD_DB ".backup $W/copie.db"
sha256sum "$W/copie.db" | tee "$W/empreinte-copie.txt"
cp "$W/copie.db" "$W/copie-originale.db"

# B. Contrôles de données, lecture seule (code 0 = rien à signaler ; 1 = lire les lignes, voir sections 1 et 2)
python3 -I outils/controle_copie_rc48.py "$W/copie.db" | tee "$W/controle.txt" ; echo "code=${PIPESTATUS[0]}"

# C. Migration aller sur la copie (écrit sur la copie seulement)
SECRET_KEY=$(python3 -c 'print("0"*64)') COOKIE_SECURE=0 INVOICE_CHECK_WORDS= APP_PASSWORD=mot-de-passe-fictif-12 DB_PATH="$W/copie.db" \
  /root/venvs/rc25-test-venv/bin/python -I -c "import sys; sys.path.insert(0,'/root/billing-mdp'); import app.app as m; m.init(); print(m.VERSION)"
#   attendu : 9.2-rc48 ; relancer la même commande une 2e fois : aucune différence
sqlite3 -readonly "$W/copie.db" "SELECT count(*) FROM sqlite_master WHERE name IN ('idx_billing_addresses_label_nocase','credit_line_upd_no_move_frozen','credit_line_upd_same_invoice','credit_line_upd_same_vat_mode','credit_line_upd_within_line','invoice_line_no_move_to_issued');"   # attendu : 6
sqlite3 -readonly "$W/copie.db" "SELECT sql LIKE '%qty*1000000%' FROM sqlite_master WHERE name='credit_lines_within_line';"                                                                                                                                                        # attendu : 1
sqlite3 -readonly "$W/copie.db" "SELECT count(*) FROM audit WHERE event='billing_address_label_index_skipped';"                                                                                                                                                                   # attendu : 0
python3 -I outils/empreinte_metier.py comparer "$W/copie-originale.db" "$W/copie.db"                                                                                                                                                                                              # attendu : identique
/root/venvs/rc25-test-venv/bin/python -I -c "import sys,sqlite3; sys.path.insert(0,'/root/billing-mdp'); from app.schema_checks import rc19_problems as p; print(p(sqlite3.connect(sys.argv[1])))" "$W/copie.db"                                                                  # attendu : []

# D. Retour arrière sur la copie migrée (simulation, puis réel sur la copie seulement)
python3 -I outils/retour_rc47.py base "$W/copie.db"          # simulation : ne modifie rien ; lire l'avertissement sur les avoirs (N-3)
python3 -I outils/retour_rc47.py base "$W/copie.db" --oui    # copie de sécurité à côté, puis schéma rc47 vérifié
python3 -I outils/empreinte_metier.py comparer "$W/copie-originale.db" "$W/copie.db"                                                                                                                                                                                              # attendu : identique

# E. Répétition fictive (aucune donnée réelle) : attendu « 50 vérifications réussies, 0 échec(s) »
/root/venvs/rc25-test-venv/bin/python -I outils/repeter_migration_rc48.py | tail -1
```

Puis, par la personne habilitée, sur une **nouvelle** copie migrée (étape C refaite) : `procedure/30-rehearse.sh`, `procedure/50-verify.sh`, `procedure/verifier-sauvegarde.sh` comme d'habitude (section 3, point 7), et la restauration JSON de la section 5. Remplir le compte rendu de la section 7.

**Critères d'arrêt (ne pas mettre en ligne)** : contrôle B avec code 1 sur les points 1, 2, 4, 7 ou 8 non traités ; C : un des « attendu » différent ; D : empreinte non identique. Un doublon d'adresse se règle sous rc47 (renommage), puis on refait une copie.

À la mise en ligne réelle, le superviseur crée aussi `.env.rc48` et pose `prod-rc48.conf` (la préparation le rappelle) ; l'outil de préparation ne le fait pas.
