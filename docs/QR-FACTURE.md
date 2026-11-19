# QR-facture suisse — module, état et suite (missions BQR1 à BQR5)

Dates : 2026-10-31 (BQR1/2), 2026-11-04 (BQR3, BQR4). Rien n'est déployé ni migré en production. **BQR3 : la QR-facture est une OPTION choisie facture par facture** (case « Ajouter la QR-facture (bulletin de paiement suisse) », décochée par défaut) et **bloque l'émission** si une information manque. `QR_BILL_ENABLED` n'est plus qu'un garde-fou global (« QR-facture proposée ») : éteint, aucune case n'apparaît et tout est comme avant ; une facture dont la case n'est pas cochée sort octet pour octet comme avant.

## 0. BQR3 — ce qui change (remplace le comportement « avertir, ne pas bloquer » de BQR2, §1 ci-dessous)

- **Stockage** : colonne `invoices.qr_bill INTEGER NOT NULL DEFAULT 0` (migration additive, voir ci-dessous). Écrite par l'éditeur du brouillon (case + champ caché `qr_bill_present`) et par l'écran d'émission (`POST /invoice/<id>/qr-bill`, brouillon seulement) : **même valeur** dans les deux écrans. À l'émission, l'en-tête figé (`live_data`) porte `qr_bill: 1` (clé présente seulement si cochée ; l'en-tête d'une facture ordinaire garde ses clés) ainsi que l'adresse structurée du client si le mandat la porte.
- **Compte non suisse** (IBAN valide ni CH ni LI, p. ex. FR, BE) : case grisée, « Pas de bulletin pour ce compte (IBAN ni suisse ni liechtensteinois) », jamais d'erreur, jamais de contrôle, jamais de page.
- **Contrôle n° 15 « La QR-facture demandée peut être produite »** (`invoice_checks.run_checks`) : n'existe que si la case est cochée (et le garde-fou allumé) ; **bloquant, non dérogable** ; le détail reprend le message précis du module (IBAN invalide, adresse du créancier ou du client non structurée, QR-IBAN sans référence QRR, montant nul…) et dit quoi corriger, avec les liens « Paramètres de l'émetteur », « Fiche du mandat » et la case de l'écran d'émission. Sortie permanente : décocher la case. Case décochée : aucun contrôle QR, les quatorze contrôles habituels.
- **PDF** : seules les factures à case cochée reçoivent la page de bulletin (juste après la page 1, comme BQR2). Un brouillon porte en plus « BROUILLON — bulletin non valable, facture non émise ». Une facture émise n'est jamais régénérée (PDF figé).
- **Migration (additive, non appliquée en production)** : `ALTER TABLE invoices ADD COLUMN qr_bill INTEGER NOT NULL DEFAULT 0;` exécutée au démarrage par `ensure_column` (comme `projects.client_legal_name`) ; aucune ligne existante n'est modifiée (elles lisent 0). **Retour arrière** : `ALTER TABLE invoices DROP COLUMN qr_bill;` (SQLite ≥ 3.35) ou ne rien faire (colonne ignorée par l'ancien code). Les deux sens sont testés dans `tests/test_qr_bill_option.py` (`Migration`). Faire la sauvegarde avant tout déploiement.
- **BQR4 (2026-11-04) : l'écart est comblé**, voir §0 bis. La rue reste facultative pour la norme ; code postal, localité et pays sont obligatoires.

## 0 ter. BQR5 — portage sur la base de production (rc42, branche `campaign/billing-qr`)

Les commits BQR1-BQR4 reposaient sur rc35. BQR5 les reporte sur le commit de production `db3a936` (rc42 : lignes manuelles, liste d'adresses EGG FR/BE/CH/MEA, numéro AAAA-N, avoirs, exception STC GEM) sans rien retirer de ces fonctions.

- **Adresse de la liste EGG** : chaque adresse de `billing_addresses` porte `addr_street`, `addr_house_num`, `addr_pcode`, `addr_city`, `addr_country` et `addr_verified` (page « Adresses de facturation », champs « Forme structurée »). Au démarrage, `address_service.migrate` découpe EGG FR, EGG BE et EGG CH d'après `app/address_presets.py` (seulement si le texte enregistré est bien celui du propriétaire et si rien n'est encore saisi) ; **EGG MEA reste vide** (ni code postal ni numéro dans le texte) ; **rien n'est marqué « vérifiée »** : le propriétaire confirme.
- **Instantané** : choisir une adresse dans le brouillon recopie aussi son découpage dans `invoices.bill_street`, `bill_house_num`, `bill_pcode`, `bill_city`, `bill_country`, `bill_addr_verified` (comme le texte : « Actualiser » le recopie, l'adresse du client modifiée ensuite ne bouge pas le brouillon). Sans choix, la QR-facture lit les colonnes de la fiche du mandat (BQR4).
- **Facture avec la case cochée** : l'en-tête figé reprend la copie (ou le mandat) ; case non cochée : mêmes clés, mêmes 14 contrôles, PDF identique octet pour octet (testé).
- **Contrôle n° 15** : ajouté après le 14 uniquement case cochée ; il passe par la même fonction `add` que les autres, mais **BQR6 (décision du propriétaire, 04/11) : sur STC GEM aussi, une case cochée avec une information manquante bloque l'émission ; la sortie est de décocher la case** (les contrôles 1 à 14 restent de simples avertissements sur ce mandat, règle rc41 ; pas de dérogation pour le 15). Le numéro de facture (AAAA-N) n'est pas touché.
- **Migrations additives** : `invoices.qr_bill`, `invoices.bill_*` (6 colonnes), `projects.client_*` (6 colonnes), `billing_addresses.addr_*` (6 colonnes), toutes par défaut vides/0. **Retour arrière** : `ALTER TABLE … DROP COLUMN …` colonne par colonne (SQLite ≥ 3.35) ou ne rien faire (ignorées par l'ancien code) ; `address_service.unmigrate` retire les six colonnes de la liste. Testé dans `tests/test_qr_bill_egg.py`. Sauvegarde avant tout déploiement.
- **Bibliothèque embarquée** : le dossier `app/vendor/svgwrite/data/` manquait dans le commit BQR4 (le `.gitignore` excluait tout dossier `data/`) ; il est ajouté ici avec l'exception `!app/vendor/**/data/` du `.gitignore`.

## 0 bis. BQR4 — saisie des adresses en champs séparés, compte QR, bibliothèque embarquée

- **Adresse du client (par mandat)** : fiche du mandat, section « Adresse de facturation en champs séparés (pour la QR-facture) » (ancre `#adresse-structuree`) : rue, numéro, code postal, localité, pays (2 lettres), case « adresse vérifiée ». Colonnes `projects.client_street`, `client_house_num`, `client_pcode`, `client_city`, `client_country` (texte, vides par défaut : **aucun pays par défaut, rien d'inventé**) et `client_addr_verified INTEGER NOT NULL DEFAULT 0`. L'adresse en texte libre (`billing_address`) reste celle qui est imprimée sur la facture, inchangée.
- **Préremplissage** (`app/address_presets.py`) : les 4 adresses EGG du commentaire du propriétaire. Découpage proposé seulement quand il est sans ambiguïté : **EGG CH** (Route de Saint Julien / 63 / 1212 / Lancy / CH), **EGG FR** (avenue Victor Hugo / 55 / 75116 / Paris / FR), **EGG BE** (Avenue du Bourgmestre Etienne Demunter / « 5, boîte 10 » / 1090 / JETTE / BE ; le nom de rue court sur deux lignes du texte). **EGG MEA : rien de prérempli** (ni code postal ni numéro dans le texte). Le préremplissage n'est **jamais enregistré** par la page : elle l'affiche avec le badge « à confirmer — proposé d'après le texte de l'adresse », ou le met dans les champs quand on choisit une adresse EGG dans la liste « Préremplir… » ; il n'est enregistré que par « Enregistrer », et ne compte pour la QR-facture qu'une fois « adresse vérifiée » cochée. Aucune donnée existante n'est modifiée par la migration.
- **Émetteur** : Paramètres, bloc « Adresse de l'émetteur en champs séparés et compte QR » (ancre `#adresse-emetteur`) : rue, numéro, code postal, localité, pays, **QR-IBAN facultatif**. Clés de la table `settings` (aucun changement de schéma) : `issuer_street`, `issuer_house_num`, `issuer_pcode`, `issuer_city`, `issuer_country`, `qr_iban` ; elles n'entrent dans l'en-tête figé que d'une facture à case cochée (une facture ordinaire garde exactement ses clés). Le nom imprimé sur le bulletin est le titulaire du compte (à défaut la raison sociale) déjà saisi ; le compte est l'IBAN déjà saisi. Une seule entité émettrice existe dans l'application (une seule série de paramètres) : « une adresse par société qui facture » n'a donc pas de support aujourd'hui (point ouvert).
- **Règle de référence** : QR-IBAN renseigné ⇒ le bulletin porte le QR-IBAN et une référence **QRR de 27 chiffres** (chiffres du numéro de facture, « 2026-09 » → 000000000000000000002026090, complétés à gauche par des zéros, chiffre de contrôle modulo 10) ; sinon l'IBAN habituel et une référence **SCOR** (RF…) tirée du numéro. Un brouillon (pas encore de numéro) reçoit une référence provisoire, sur une page marquée « BROUILLON ».
- **Validation à la saisie** (messages simples) : adresse vide acceptée ; dès qu'un champ est rempli, code postal, localité et pays sont obligatoires ; pays = 2 lettres ; numéro collé à la rue, caractères non admis (arabe, « ¤ »…) et longueurs refusés. QR-IBAN : clé de contrôle, pays CH/LI, chiffres 5 à 9 entre 30000 et 31999. **IBAN principal : la clé de contrôle fausse n'empêche pas l'enregistrement** (des IBAN fictifs de recette existent) mais un avertissement est affiché et la QR-facture reste bloquée.
- **Branchement** : `live_data` lit les colonnes (plus de « seulement si la colonne existe ») ; l'adresse client et son état « vérifiée » sont figés dans l'en-tête de la facture à case cochée, donc **une facture émise ne change plus** même si le mandat ou les paramètres sont modifiés ensuite. Le contrôle n° 15 nomme le champ en cause (« Adresse du créancier, code postal : champ obligatoire… ») et renvoie à l'écran concerné (Paramètres ou fiche du mandat, avec ancre). « Non structurée » n'est dit que si seul le bloc de texte libre existe. **Adresse du client non vérifiée = émission bloquée** (« Adresse du client à confirmer… »).
- **Bibliothèque embarquée** : `app/vendor/` (6,5 Mo, 117 fichiers), voir `app/vendor/VENDOR.md` et `app/vendor/licences/`. `qr_bill.VENDOR_DIR` pointe dessus par défaut ; plus aucun chemin extérieur. `lxml` y est en binaire (Python 3.12, Linux x86-64). `Dockerfile` : `COPY app ./app` emporte déjà `app/vendor` — **aucun changement nécessaire** ; `procedure/*.sh` : aucun (copie du dossier `app`). Voir le rapport de mission pour les réserves.
- **Migration BQR4 (additive, non appliquée en production)** : six `ALTER TABLE projects ADD COLUMN …` exécutés au démarrage par `ensure_column` (liste ci-dessus), valeurs par défaut vides / 0 ; aucune ligne modifiée. **Retour arrière** : `ALTER TABLE projects DROP COLUMN client_street;` (et les cinq autres : `client_house_num`, `client_pcode`, `client_city`, `client_country`, `client_addr_verified`) avec SQLite ≥ 3.35, ou ne rien faire (colonnes ignorées par l'ancien code). Testé dans `tests/test_qr_bill_addresses.py` (`Migration`). Sauvegarde avant tout déploiement.
- **Tests** : `python -m unittest tests.test_qr_bill tests.test_qr_bill_option tests.test_qr_bill_addresses`. Le test `Flow.test_issued_slip_is_read_back_field_by_field` rend la page du bulletin du PDF émis (`pdftoppm`), échantillonne le code QR module par module et le compare à un QR encodé à neuf depuis la charge utile reconstruite des champs saisis ; il compare aussi cette charge utile champ par champ et le texte du bulletin. Ce n'est pas la lecture par une application bancaire.


## 1. Ce qui est fait

| Élément | Où |
|---|---|
| Module isolé (ne dépend d'aucun autre module de l'application) | `app/qr_bill.py` |
| Drapeau `QR_BILL_ENABLED` (variable d'environnement, éteint si absent ; valeurs actives : `1`, `true`, `oui`, `yes`, `on`) | `app/qr_bill.py` → `enabled()` |
| Point d'insertion, commenté, juste avant l'annexe | `app/pdf_layout.py`, `render_invoice` (6 lignes) |
| Tests du module et de l'insertion (27 tests, verts) | `tests/test_qr_bill.py` |
| Exemple de facture rendue avec bulletin (données fictives) et script qui le régénère | `docs/qr-facture-exemple/` |

Le bulletin (210 × 106 mm : « Récépissé » + « Section paiement ») est produit en SVG par la bibliothèque MIT `qrbill` 1.2.0 (embarquée dans `app/vendor/` depuis BQR4, ajoutée au chemin d'import **après** les paquets du venv, **pas** dans `requirements.txt`), converti en dessin reportlab par `svglib`, puis posé en bas d'une page A4.

**Emplacement du bulletin : une page A4 portrait supplémentaire juste après la page 1** (le bulletin occupe les 106 derniers millimètres de la page). Raison : sur la page 1 actuelle, le bloc de paiement (à partir de 549 pt depuis le haut) et le pied de page (816 pt) occupent déjà cette zone ; les loger sur la même page obligerait à changer la mise en page de référence, ce que la mission interdit. La numérotation « Page x of y » de l'annexe ne bouge pas. Variante (décision à prendre plus tard) : bulletin sur la page 1 elle-même, en déplaçant le bloc de paiement et le pied de page — c'est un changement de mise en page à revalider avec l'empreinte de référence.

### Ce que le module accepte et refuse (messages en français simple, `QrBillError`)

- **Adresses structurées uniquement** (nom, rue, numéro, code postal, localité, pays en champs séparés) ; un bloc de texte libre est refusé (« adresse non structurée »), de même qu'un numéro collé à la rue, un code postal ou une localité vide, un pays qui n'est pas un code à 2 lettres. Le client est facultatif pour la norme (case à remplir à la main) ; s'il est fourni, il doit être complet.
- **IBAN** : valide (clé de contrôle), suisse ou liechtensteinois. IBAN classique : référence **SCOR** (ISO 11649, `RF…`, construite par `scor_reference()` à partir du numéro de facture, p. ex. `2026-09` → `RF70202609`) ou **aucune** (« NON »). **QR-IBAN** : référence **QRR** (27 chiffres) obligatoire ; QRR refusée avec un IBAN classique.
- **Montant** strictement positif (0, négatif, illisible : refusés), arrondi au centime, devise **CHF** ou **EUR**.
- **Texte** : caractères admis par la norme seulement (lettres latines accentuées, ASCII ; le tiret long « — » et l'arabe sont refusés), message de 140 caractères au plus.

### Comportement BQR2 (historique : remplacé par §0 pour l'avertissement/blocage et pour l'option par facture)

- **Avertir, ne pas bloquer** (recommandation, à confirmer par le propriétaire) : si une donnée manque ou est invalide (IBAN absent ou faux, adresse non structurée, montant nul, devise autre que CHF/EUR, bibliothèque absente), la QR-facture est **omise** : le PDF sort exactement comme drapeau éteint, et l'écran d'émission affiche « La QR-facture sera omise de cette facture (l'émission n'est pas bloquée) : <raison> » (`qr_bill.warning_for_header`, encadré `#qrBillWarning` de `issue_confirm.html`). Rien n'est imprimé de ce message sur la facture.
- **IBAN valide mais ni suisse ni liechtensteinois** (entités FR, BE, MEA) : QR-facture omise **sans aucun message**.
- Facture **émise** : jamais re-générée ; `/invoice/<id>.pdf` sert les octets figés à l'émission. Le bulletin n'est donc ajouté qu'aux factures émises après l'allumage du drapeau.
- Montant = TOTAL, ou NET À PAYER si une note de crédit est imputée. Référence = SCOR du numéro de facture ; message = « Facture <numéro> ». Un brouillon n'a pas de numéro : pas de référence (« NON »). Devise : `h["currency"]` si la colonne existe un jour, sinon CHF.
- Variante « bloquer » : **retenue par le propriétaire le 04/11 (BQR3)**, voir §0 : le contrôle n° 15 bloque, seulement quand la case est cochée.

## 2. Vérifié / non vérifié

Vérifié : 27 tests ciblés verts ; empreinte de la mise en page de référence (`golden_layout.json`) identique ; PDF de la facture **identique octet pour octet** à celui du dernier commit, drapeau éteint (4 cas : émise/brouillon, avec/sans saisies) ; page du bulletin relue à l'écran (récépissé, QR, montant, adresses, référence).

Non vérifié : la suite complète, les tests de base de données (`PdfLayout`, etc. : ils exigent une copie de la base de recette, lancée par le superviseur) ; **la lecture du QR par une vraie application bancaire ou le validateur officiel SIX** (pas d'accès réseau ici) ; l'impression à l'échelle 100 % et la perforation ; le rendu avec les polices sous licence (le bulletin utilise Helvetica, pas les polices de la facture).

## 3. Modèle de données (état initial BQR2 ; **réalisé en BQR4**, voir §0 bis — conservé pour mémoire, sauf `invoices.currency` toujours non créée)

Aujourd'hui (constaté dans `app/app.py`, `billing_rules.py`, `invoice_service.py`) :

| Donnée nécessaire | État actuel | Manque |
|---|---|---|
| IBAN du créancier | `settings.iban`, texte libre, obligatoire à l'émission | Existe, mais **non validé** (la facture de test porte `CH00 0000…`). À valider à la saisie (clé de contrôle). |
| Nom du créancier | `settings.account_holder` | Existe. |
| **Adresse du créancier en champs séparés** | `settings.issuer_address` : un bloc de texte libre | **Manque** : rue, numéro, code postal, localité, pays. |
| **Adresse du client en champs séparés** | `projects.billing_address` : un bloc de texte libre, par mandat | **Manque** : rue, numéro, code postal, localité, pays. |
| Devise | aucune colonne : tout est en CHF | **Manque** `invoices.currency` si EUR est voulu (sinon CHF fixe). |
| Référence | aucune | Rien à stocker pour SCOR (dérivée du numéro de facture). Un QR-IBAN demanderait en plus un `settings.qr_iban` et une référence QRR de 27 chiffres tirée du numéro (à décider). |
| Données figées à l'émission | `live_data` ne fige que `billing_address` | Les nouveaux champs client doivent entrer dans la liste `keys` de `live_data`, sinon le gel de la facture ne les contient pas. |

### Proposition de migration additive (NON appliquée)

À mettre dans la liste des colonnes ajoutées au démarrage (même mécanisme que `projects.client_legal_name`), toutes facultatives avec valeur par défaut vide : aucune ligne existante n'est modifiée, un retour en arrière revient à ignorer les colonnes.

```sql
ALTER TABLE projects ADD COLUMN client_street      TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN client_house_num   TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN client_pcode       TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN client_city        TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN client_country     TEXT DEFAULT 'CH';
ALTER TABLE invoices ADD COLUMN currency           TEXT DEFAULT 'CHF';   -- seulement si EUR est voulu
-- créancier : pas de changement de schéma, clés ajoutées dans la table settings et dans ISSUER_FIELDS :
--   issuer_street, issuer_house_num, issuer_pcode, issuer_city, issuer_country, (qr_iban)
```

Ensuite : champs dans le formulaire du mandat et des paramètres, ajout à `live_data.keys`, et **aucun remplissage automatique** des adresses existantes (découper un bloc de texte libre est un jeu de devinettes ; à proposer au propriétaire avec une vérification humaine adresse par adresse). Les noms de champs lus par `inputs_from_header` sont déjà ceux ci-dessus (`issuer_*` dans les paramètres, `client_*` dans l'en-tête).

## 4. Ce qui reste à faire

1. ~~Saisie des adresses structurées~~ : **fait en BQR4**. Reste : **saisir et confirmer les VALEURS** (IBAN, adresse de l'émetteur, adresse de chaque client), le propriétaire seul peut le faire ; le formulaire de CRÉATION d'un mandat n'a pas encore les champs séparés (saisie dans la fiche « Modifier »).
2. **Validation par la banque** : tester un bulletin réel avec le validateur SIX et la banque du propriétaire (et l'application mobile), avec le vrai IBAN ; pas encore fait.
3. **Gabarit** : décision sur l'emplacement (page dédiée comme ici, ou bas de la page 1 avec mise en page revalidée), police, pied de page, éventuel texte d'accompagnement sur la page du bulletin.
4. QR-IBAN + QRR : **géré en BQR4** (champ facultatif) ; reste à savoir si la banque en a fourni un.
5. ~~Bibliothèque hors dépôt~~ : **embarquée en BQR4** (`app/vendor/`), sans changement de `requirements.txt` ni du `Dockerfile`. À valider : l'embarquement de `lxml` compilé (Python 3.12, x86-64) et des deux licences LGPL (voir `app/vendor/VENDOR.md`).
6. Rapprochement des paiements (la référence SCOR est reprise par la banque ; rien n'est lu ici).
7. Les notes de crédit n'ont pas de bulletin (hors périmètre).

## 5. Risques

- Facture émise bloquée si le drapeau est allumé avant que les adresses soient saisies (voulu : mieux vaut un refus clair qu'un bulletin refusé par la banque ; allumer le drapeau seulement après la saisie).
- Une page de plus par facture (impression recto : 1 feuille de plus) ; le bulletin n'est pas sur la page 1.
- Bibliothèque tierce embarquée (versions figées : qrbill 1.2.0, svglib 2.3.2, qrcode 8.2) ; `lxml` compilé propre à Python 3.12 / x86-64 : un autre interpréteur ou une autre architecture désactive la QR-facture (message « bibliothèque non installée »), sans autre effet.
- Le bulletin est lu par les banques : un détail (marge, taille du QR, caractère) peut le faire refuser alors que le PDF paraît correct ; seul le test bancaire le garantit.
- Le dessin SVG → PDF passe par svglib : traits et croix suisse sont vectoriels ; Helvetica standard (non intégrée) suffit pour le texte du bulletin.
- Fixtures : l'IBAN `CH93 0076 2011 6238 5295 7` des exemples est un IBAN de documentation, pas un compte réel.
- Mise en garde « mots interdits » (contrôles d'émission) : l'exemple utilise « Test SA » ; il n'est pas émis par l'application et ne passe donc pas par ces contrôles.

## BQR9 — référence unique (2026-11-11)

**Défaut** : `qrr_reference` ne garde que les chiffres du numéro, `scor_reference` que les lettres et chiffres ; « 2026-10-1 » et « 2026-101 » (ou « 2026-1-1 » et « 2026-11 ») donnaient donc la même référence de paiement. Aucune collision aujourd'hui (les numéros réels sont AAAA-NN, QR-facture éteinte), le risque vient du mélange de numérotations.

- **Règle unique** : `qr_bill.payment_reference(numéro, qr_iban)` (QRR si un QR-IBAN est réglé, sinon SCOR ; sans numéro ni QR-IBAN : aucune). `inputs_from_header` l'utilise (plus de règle recopiée). `qr_bill.reference_clash` (pure) et `billing_rules.reference_conflict(c, numéro, exclude_id)` cherchent, parmi les mêmes sources que `number_conflict` (factures de tout statut dont les brouillons **numérotés**, factures historiques, `EXTERNAL_INVOICE_NUMBERS`), un AUTRE numéro de même référence. Deux écritures du même numéro (« 2026-09 » / « 2026-9 », `number_key`) ne sont pas une collision de référence : le refus « déjà utilisé » existant s'applique. Les brouillons sans numéro ne comptent pas.
- **Saisie d'un numéro** (`number_refusal`, éditeur de brouillon) : refus « Ce numéro donnerait la même référence de paiement que la facture 2026-101 : choisissez un autre numéro » ; rien n'est écrit (ni numéro, ni révision, ni historique). Le contrôle ne dépend pas du drapeau `QR_BILL_ENABLED`.
- **Numérotation automatique** (`propose_invoice_number`) : saute le numéro dont la référence serait déjà prise (ex. 2026-11 si « 2026-1-1 » existe → 2026-12) ; elle ne peut donc jamais attribuer une collision. Décision à valider : saut silencieux plutôt qu'un refus (le numéro n'est pas saisi par l'utilisateur).
- **Bulletin** (`assess`) : `invoice_service.live_data` ajoute `reference_clash` à l'en-tête, **seulement** si la case QR est cochée et qu'une collision existe (l'en-tête de toute autre facture garde ses clés) ; `assess` omet alors le bulletin avec le même message (donc le contrôle n° 15 bloque l'émission, la sortie reste de changer le numéro ou de décocher la case). Jamais de bulletin avec une référence en double.
- **Non-régression** : références inchangées (`2026-09` → `RF70202609` / `000000000000000000002026090`), PDF identique case décochée (tests existants verts).
- **Limites** : l'application a un seul émetteur, la comparaison porte sur toutes les factures numérotées. Seule la référence du mode courant est comparée (un changement de QR-IBAN plus tard peut créer une collision sur des numéros anciens : le bulletin sera alors omis avec le message). Une facture déjà émise en collision n'est pas modifiée.
- **Tests** : `tests/test_qr_reference_unique.py` (14 tests).
