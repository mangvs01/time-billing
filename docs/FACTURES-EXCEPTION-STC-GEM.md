# Exception « STC GEM » et tolérance de sous-facturation — 9.2-rc41

Mission BILLING-STC-GEM-EXCEPTION (claude2), décisions du propriétaire du 28.10.2026. Candidat **non déployé, non commité**. Base : `campaign/billing-factures` @ `a7a8448` (rc40 = production).

## 1. Ce qui change

### 1.1 Global : plus aucune tolérance sur les jours (point 1)
- `UNDER_TOLERANCE = 0.0` (`app/invoice_checks.py`), comme `OVER_TOLERANCE`. Toute quantité facturée **inférieure ou supérieure** aux jours travaillés de la période est un écart du contrôle 12 (dérogable par un motif écrit propre au contrôle 12, comme avant). Seul le bruit de calcul (`EPS = 1e-5` j) n'est pas un écart.
- Texte du contrôle : « … (tolérance de sous-facturation : 0 j) ». Commentaire de `app/post_billing.py` (`owners()`) mis à jour.
- Impact utilisateur : une facture à 1,5 j pour 2 j travaillés passait sans motif jusqu'à la rc40 ; elle demande maintenant une dérogation (contrôle 12). Les arrondis « au plus proche » ou « à l'inférieur » qui donnent un écart non nul sont signalés dès la création du brouillon (prévision du contrôle 12, même fonction `period_story`).
- Les factures déjà émises ne sont ni recontrôlées ni modifiées (un document émis n'est jamais recontrôlé).

### 1.2 Mandat « STC GEM » seulement (points 2 et 3)
1. **Aucun contrôle ne bloque l'émission.** Pour ce mandat, `run_checks` calcule les 14 contrôles comme avant, mais chaque échec devient un avertissement (`status = "warning"`, `would_fail = true`, `derogable = false`, `exception = "STC GEM"`). Conséquences : `failures()` et `blocking()` sont vides, `derogations()` ne demande aucun motif, le bouton d'émission reste actif — **y compris pour le contrôle 14, non dérogable partout ailleurs**.
2. **Écarts affichés, non bloquants** : page d'émission, ligne du contrôle « ÉCART · STC GEM (non bloquant) » + encadré `#exceptionNotice`.
3. **Tracés à l'audit** : à l'émission, une ligne `invoice_check_exception` par écart (JSON : `invoice_id`, `number`, `check`, `title`, `anomaly` exact, `exception = "exception STC GEM"`, `mandate`, `by`, `at`), et la ligne `invoice_issued` porte `;exception STC GEM=yes;exception_gaps=…`. Aucune ligne `invoice_check_derogation` n'est écrite (aucun motif).
4. **PDF et montants inchangés** : rien dans `pdf_layout`. L'en-tête figé (`invoice_snapshots.header_json`) reçoit la clé `exception` **uniquement** pour ce mandat ; les autres factures gardent exactement leurs clés.
5. **Tarif modifiable dans l'éditeur** (`/invoice/<id>/edit`) : champ `unit_rate` (par jour ou par heure selon l'unité du brouillon) + champ caché `unit_rate_shown` (tarif affiché à l'ouverture, pour savoir si le champ a été touché). Validation `billing_rules.unit_rate_typed` : nombre ASCII strictement positif, **au plus 4 décimales (refusé, jamais arrondi en silence)**, au plus `1 000 000 000` (même borne que `MAX_RATE` des lignes manuelles). Le tarif est stocké dans `invoices.unit_rate` du brouillon (donc dans l'instantané figé à l'émission), les totaux serveur, l'aperçu `/invoice/<id>/preview` et le PDF utilisent ce tarif. Audit `draft_rate_changed` (JSON : ancien tarif, nouveau tarif, utilisateur, date, unité, mandat). Changer l'unité sans toucher au champ reprend le tarif du mandat, comme avant. Le contrôle 3 signale (sans bloquer) que le tarif n'est plus celui du mandat.
6. **Autres mandats** : champ absent, valeur postée ignorée (non validée, non enregistrée), contrôles bloquants identiques. Preuves : `tests/test_rc41_stc_gem.py::OtherMandatesUnchanged`.

### 1.3 Ce que l'exception ne fait PAS
Elle ne touche pas aux garde-fous qui ne sont pas des contrôles de cohérence : champs obligatoires de l'émetteur / du mandat, chevauchement avec une facture émise, date de facture invalide ou antidatage non confirmé, total nul ou négatif, adresse trop longue, lignes manuelles (émission suspendue, rc38), numéro de facture déjà pris, reliquat à traiter. Elle ne modifie pas les factures existantes, les notes de crédit, ni la base.

## 2. Identification du mandat et réglage

Variable d'environnement **`BILLING_EXCEPTION_MANDATES`** (lue à chaque appel, jamais mise en cache) :

| Valeur | Effet |
|---|---|
| non définie (défaut) | liste `("STC GEM",)` |
| `STC GEM` ou `STC GEM, Autre mandat` | exactement ces noms (le défaut est **remplacé**, pas complété) |
| `id:12` (mélangeable : `STC GEM, id:12`) | désigne un mandat par son identifiant (`projects.id`) |
| définie mais vide | **aucune exception** (désactivation) |

Comparaison : nom du mandat (`projects.name`) **ou** nom court (`projects.short_name`), égalité complète après suppression de tous les espaces et de la casse (« stc gem », « STC  GEM », « STCGEM » correspondent ; « STC GEM 2 », « GEM STC » non). **Le nom du client n'est pas comparé** : un client porte souvent plusieurs mandats, et l'exception ne doit pas s'étendre à tous. Aucune migration de schéma : le réglage est un paramètre de déploiement.

**À valider (je n'ai pas lu la base de production)** : que le mandat s'appelle bien « STC GEM » (ou que ce soit son nom court). S'il s'appelle autrement (ex. « GEM STC 2026 – … », ou « STC GEM » n'est que le client), ou si plusieurs mandats portent un nom proche, **régler explicitement** `BILLING_EXCEPTION_MANDATES=id:<n>` (l'identifiant est visible dans l'URL de la fiche du mandat) plutôt que d'élargir la correspondance.

## 3. Migration

**Aucune migration de schéma ni de données.** Rien dans `init()`. Colonnes utilisées : `invoices.unit_rate` (existante), table `audit` (existante, nouveaux libellés d'événement `draft_rate_changed`, `invoice_check_exception`), `invoice_snapshots.header_json` (clé JSON supplémentaire pour ce seul mandat). Le déploiement ajoute seulement, si nécessaire, la variable `BILLING_EXCEPTION_MANDATES` dans la configuration du service (sinon la valeur par défaut « STC GEM » s'applique).

## 4. Désactiver, retour arrière

- **Désactiver l'exception sans redéployer le code** : définir `BILLING_EXCEPTION_MANDATES=` (vide) et redémarrer le service. Effets : les contrôles bloquent de nouveau pour STC GEM ; le champ de tarif disparaît ; un brouillon dont le tarif avait été modifié échoue au contrôle 3 (« tarif de la facture ≠ tarif du mandat… rétablir celui du mandat, ou supprimer le brouillon et le recréer ») ; les factures déjà émises ne sont pas touchées (leur instantané garde le tarif et la clé `exception`).
- **Retour arrière du code** : redéployer la copie figée rc40. Aucune donnée à défaire : les nouvelles lignes d'audit et la clé JSON de l'en-tête figé sont ignorées par rc40 ; un brouillon au tarif modifié ressortirait en échec du contrôle 3 sous rc40 (comportement de rc40 pour un tarif différent du mandat). Le point 1 (tolérance) revient à 0,5 j avec le code rc40.
- Retour partiel sur le point 1 seul : remettre `UNDER_TOLERANCE = 0.5` (un fichier).

## 5. Tests (écrits, non lancés par moi)

`tests/test_rc41_stc_gem.py` (nouveau) : réglage et correspondance des noms, validation du tarif, tolérances nulles, scénario complet STC GEM (facture ancienne émise, brouillon incohérent contrôles 12 + 14, tarif refusé puis modifié, aperçu, émission sans motif, audit, en-tête figé, ancienne facture inchangée octet pour octet), tarif horaire, changement d'unité ; scénarios négatifs sur un autre mandat (mêmes chiffres : émission refusée même avec motifs, champ de tarif absent et ignoré, noms voisins non concernés, désactivation par réglage vide ou par `id:`). Tests existants adaptés à la tolérance zéro : `test_rc25.py`, `test_ux_lot1.py`, `test_ux_lot2.py`, `test_g4_fidelite.py`; version : `test_calendrier.py`.

**Risque connu** : les autres fichiers de test de la suite n'ont pas été relus un à un ; une fixture qui facturait entre 0 et 0,5 j de moins que le travail enregistré (sans `RECORD_WORK`) échouera maintenant au contrôle 12. La recette du superviseur les révélera ; la correction attendue est d'aligner la quantité de la fixture sur le travail.

## 6. Fichiers

Code : `app/billing_rules.py`, `app/invoice_checks.py`, `app/invoice_service.py`, `app/app.py` (+ `VERSION = "9.2-rc41"`), `app/post_billing.py` (commentaire), `app/templates/invoice_edit.html`, `app/templates/issue_confirm.html`. Docs : ce fichier, `docs/GUIDE-FACTURES.md`, `docs/PAQUET-RC41.md`. Tests : voir §5.

## Correctif rc42 (28/10) : désignation par préfixe
Les mandats réels s'appellent « STC GEM Avril », « STC GEM Oct - DM job »… : la valeur par défaut est désormais `STC GEM*` (tous les mandats dont le nom commence par les mots « STC GEM », mots entiers, sans tenir compte de la casse ni des espaces multiples). « STC GEMINI », « NC STC Sept » ou « Mandat STC GEM » ne sont pas concernés. Les noms exacts et `id:<n>` restent possibles ; une valeur vide désactive l'exception.
