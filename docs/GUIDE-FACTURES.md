# Guide des factures — pas à pas

Pour le propriétaire. Version de l'application décrite : **9.2-rc40**.
Les noms de boutons et de champs ci-dessous sont recopiés tels qu'ils s'affichent à l'écran. Les messages d'erreur sont ceux de l'application (écrits ici sans les parties techniques).

**Les trois idées à retenir**

1. Un **brouillon** se modifie autant qu'on veut. Il n'a aucune valeur comptable (le PDF porte le mot « BROUILLON »).
2. Une **facture émise** ne change plus jamais, ni son numéro, ni son PDF.
3. Pour corriger une facture émise, on ne la modifie pas : on fait une **note de crédit** (un avoir). Si tout est faux, on crédite tout, puis on refait une facture.

---

## 1. Créer un brouillon

**Où :** menu de gauche **Édition des factures** (sur téléphone : barre du bas, **Plus**, puis **Édition des factures**).

1. Dans **1. Mandat et période** : choisir le **Projet à facturer**.
2. Choisir la période : soit les boutons **Depuis la dernière facture**, **Mois dernier**, **Ce mois, jusqu'à aujourd'hui**, soit les deux dates **Début de la période** et **Date d'arrêté / fin de période**.
3. L'application calcule seule le temps enregistré (« Temps enregistré sur la période », « Jours facturables exacts »). Bouton **Recalculer** si besoin.
4. Dans **2. Quantité à facturer** : choisir la **Règle d'arrondi** (« Sans arrondi » par défaut) et le **Pas d'arrondi**, puis vérifier la **Quantité à facturer (jours)**. Elle reste modifiable à la main.
5. Facultatif : ouvrir **3. Options de la facture** (description, montant « AUTRES », date de facture, note).
6. Cliquer **Créer le brouillon**.

**Ce qui s'affiche :** un cadre « **Brouillon créé** » avec deux boutons, **Ouvrir le brouillon** et **Contrôler avant émission**. Deux messages précisent : « Numéro de facture proposé et réservé : AAAA-N (modifiable dans l'éditeur du brouillon) » et « Il figure dans « Factures et brouillons » (statut brouillon) ».

**Messages courants et quoi faire**

| Message | Que faire |
|---|---|
| « La période finit après aujourd'hui (ou après la date de facture) : l'émission demandera une dérogation écrite (contrôle 13) » | Ce n'est pas bloquant. Soit raccourcir la période, soit prévoir un motif écrit à l'émission. |
| « Attention : N autre(s) brouillon(s) couvre(nt) déjà cette période du mandat. Un seul des deux pourra être émis » | Supprimer l'un des deux brouillons (bouton **Supprimer** dans **Factures et brouillons**). |
| « la période chevauche la facture émise … : pour la facturer de nouveau, créditer d'abord cette facture intégralement (note de crédit totale émise) » | La période est déjà facturée. Changer les dates, ou voir le chapitre 7 (annuler et refaire). |
| « Attention : les brouillons et factures émises (… j) dépassent le solde du bon de commande » | Avertissement seulement. Vérifier qu'un bon de commande complémentaire existe. |
| « description trop longue pour le document imprimé … : la raccourcir » | Raccourcir la description (environ 35 caractères par ligne imprimée). |
| « note de facture trop longue … (environ 90 caractères) » | Raccourcir la note : elle tient sur une seule ligne. |
| « le montant « autres » ne peut pas être négatif (pour un geste commercial, utiliser une note de crédit) » | Ne jamais saisir de montant négatif : faire une note de crédit. |

---

## 2. Ouvrir et modifier le brouillon

**Où :** menu **Factures et brouillons**, ligne du brouillon, bouton **Modifier** (ou **Ouvrir le brouillon** juste après la création). Autres boutons de la ligne : **PDF (brouillon)**, **Contrôler et émettre**, **Supprimer**.

Page « **Modifier le brouillon** ». On enregistre avec le grand bouton **Enregistrer le brouillon** en bas (la touche Entrée fait la même chose).

Si le message « ce brouillon a été modifié depuis l'ouverture de cette page (autre onglet ?) … rien n'a été enregistré » apparaît, c'est que le brouillon est ouvert dans deux onglets. Rouvrir le brouillon : on voit la dernière version, et il faut refaire sa modification.

Si l'enregistrement échoue, la page affiche « **Brouillon non modifié : …** » suivi de la raison. Rien n'est enregistré, rien n'est perdu à l'écran.

---

## 3. Saisir des lignes manuelles (frais, forfaits…)

**Où :** dans « Modifier le brouillon », rubrique **Lignes de la facture**.

- La première ligne, **Prestations (heures)**, est en lecture seule : quantité × tarif du mandat. Pour changer le tarif, il faut modifier le mandat puis recréer le brouillon (seul le mandat « STC GEM » permet de saisir le tarif dans le brouillon : voir §6 bis).
- Cliquer **Ajouter une ligne**. Chaque ligne manuelle (fond coloré, étiquette « Ligne manuelle ») demande :
  - **Description** (exemple affiché : « Frais de déplacement »), 200 caractères au maximum ;
  - **Quantité** ;
  - **Unité** : jour, heure, forfait ou pièce (« forfait » par défaut) ;
  - **Prix unitaire (CHF)** ;
  - **TVA de la ligne** : **soumis à TVA (inclus dans la base TVA)** ou **hors TVA (ajouté après la TVA)**.
- **La TVA se choisit ligne par ligne.** Une nouvelle ligne manuelle est **soumise à TVA par défaut** : il faut changer le choix si elle ne doit pas l'être.
- **Supprimer cette ligne** retire la ligne (ne pas se contenter de vider la description).
- Maximum **8 lignes manuelles** (la page 1 de la facture est limitée ; une description tient sur 2 lignes imprimées au plus). Au-delà : « 8 lignes manuelles au maximum sur la page 1 de la facture ».
- Un tableau **Totaux du brouillon** se met à jour tout seul : SOUS-TOTAL, TVA, AUTRES, TOTAL TTC. S'il affiche « Totaux non calculés : … », corriger la ligne signalée.
- Les lignes manuelles ne comptent **pas** dans les jours du mandat.

**La ligne « AUTRES » (à ne pas confondre avec les lignes manuelles)**

Plus bas dans la page : **Montant « AUTRES » HT (CHF)**, **Libellé « AUTRES »** et **TVA sur « AUTRES »**. Elle s'imprime dans les totaux, seulement si le montant est supérieur à 0.
- Le choix proposé pour la TVA vient de **Paramètres & sauvegardes**, réglage « Traitement TVA par défaut de la ligne « AUTRES » ». **Point à vérifier :** tant que ce réglage n'a pas été enregistré, l'application propose **hors TVA**, pas « soumis ». Pour que « AUTRES » soit soumis à TVA par défaut, régler ce paramètre sur « soumis à TVA » puis cliquer **Enregistrer les paramètres**. Il s'applique aux **nouveaux** brouillons ; sur un brouillon existant, changer la liste **TVA sur « AUTRES »**.
- Si le libellé est rempli mais le montant est 0, l'application prévient : « Le libellé « AUTRES » n'est imprimé que si un montant est saisi… ».

**Messages courants (le début indique le numéro de la ligne fautive : « ligne 2 : … »)**

| Message | Que faire |
|---|---|
| « description obligatoire (pour retirer une ligne, utiliser « Supprimer ») » | Remplir la description, ou cliquer **Supprimer cette ligne**. |
| « quantité invalide » / « prix unitaire (CHF) invalide ou hors limites » | Saisir un nombre simple (ex. 2 ou 150,50). Pas de signe moins, pas de lettres. |
| « description trop longue (200 caractères au maximum) » | Raccourcir. |
| « montant … au-dessus de la limite » | Un montant dépasse 1 000 000 000 CHF : vérifier quantité et prix. |
| « une ligne de ce brouillon n'existe plus (modifiée dans un autre onglet ?) » | Rouvrir le brouillon. |

Les lignes manuelles peuvent s'émettre : l'émission des factures à lignes manuelles est autorisée depuis la version rc39. Si un jour un bandeau « **Émission suspendue pour les lignes manuelles** » apparaît, c'est que l'émission a été suspendue ; dans ce cas, le brouillon reste modifiable mais ne s'émet pas tant que le bandeau est là.

---

## 4. Choisir l'adresse de facturation

**Où :** « Modifier le brouillon », champ **Adresse de facturation** (liste déroulante), sous les réglages de la période.

- Par défaut : « **Adresse de la fiche du mandat (par défaut)** ».
- La liste propose **EGG FR, EGG BE, EGG CH, EGG MEA** pour **tous** les mandats (depuis rc40), plus les éventuelles adresses propres au client.
- L'adresse choisie s'affiche dans l'encadré juste dessous : vérifier que c'est la bonne, puis **Enregistrer le brouillon**. Message de confirmation : « Adresse de facturation : EGG BE. » (par exemple).
- **Important :** le choix **copie** le texte de l'adresse dans la facture. Si l'adresse est modifiée plus tard, le brouillon ne bouge pas. Pour reprendre la nouvelle version : cocher « **Actualiser la copie d'après l'adresse enregistrée** » (visible quand une adresse est déjà choisie), puis enregistrer. Une facture émise ne change jamais.
- Une adresse désactivée apparaît avec « (désactivée) » : un brouillon peut la garder, mais on ne peut pas la choisir ailleurs.
- **Ajouter, corriger ou désactiver une adresse :** lien **Gérer les adresses** (page « Adresses de facturation ») : bouton **Enregistrer cette adresse**, **Désactiver** / **Réactiver**, ou « Ajouter une adresse pour ce client » puis **Ajouter l'adresse**. Une adresse ne se supprime pas.

**Messages courants**

| Message | Que faire |
|---|---|
| « cette adresse est désactivée » | Choisir une autre adresse, ou la **Réactiver** dans « Adresses de facturation ». |
| « cette adresse n'appartient pas au client de ce mandat » | Choisir dans la liste proposée. |
| « adresse trop longue pour le bloc de facturation du document imprimé : choisir une adresse plus courte » | Raccourcir l'adresse dans « Adresses de facturation » (6 lignes imprimées au plus, destinataire compris, 80 caractères par ligne). |
| « Adresse non ajoutée : une adresse « … » existe déjà pour ce client » | Changer le libellé. |
| Aperçu : « [À COMPLÉTER : Adresse de facturation] » | Aucune adresse n'est renseignée : en choisir une, ou compléter la fiche du mandat. L'émission est impossible avec ce marqueur. |

---

## 5. Le numéro de facture (AAAA-N)

**Où :** « Modifier le brouillon », tout en haut, champ **Numéro de facture**.

**Comment ça marche**

- Le format proposé est **l'année, un tiret, un numéro d'ordre** : par exemple 2026-11 après 2026-10. Le numéro d'ordre repart à 1 chaque année.
- Dès la création, le brouillon **réserve** un numéro (« proposé par l'application et réservé par ce brouillon »). Il est repris tel quel à l'émission.
- Le numéro proposé est le premier libre de l'année, en tenant compte des factures émises, des brouillons, des **factures historiques** et des **numéros externes** (factures faites hors de l'application). Si un brouillon est supprimé, son numéro redevient libre et peut être reproposé.
- **Modifier à la main :** taper le numéro voulu et cliquer **Enregistrer le brouillon**. Le message « Numéro de facture saisi : … » confirme. Un numéro saisi à la main n'est **jamais remplacé automatiquement** (« saisi à la main »). Règles : 20 caractères au maximum, lettres, chiffres, « - » et « / », en commençant par une lettre ou un chiffre.
- **Revenir au numéro automatique :** vider le champ et enregistrer (« Vide = reproposer le prochain numéro libre »).
- Si la date de facture change d'année, un numéro automatique suit l'année ; un numéro saisi à la main reste tel quel.
- Chaque changement est **tracé** dans « Historique du numéro » (non modifiable).
- Les numéros « 2026-09 », « 2026-9 » et « 2026-009 » sont considérés comme **le même numéro**.
- Une facture **émise** n'est jamais renumérotée. Pour changer un numéro après émission : note de crédit totale, puis nouvelle facture (chapitre 7).

**Numéros réservés (donc refusés)**

Un numéro est refusé s'il est déjà pris par une facture émise, un autre brouillon, une facture historique (faite hors de l'application) ou un numéro externe réservé. Le préfixe « NC- » est réservé aux notes de crédit.

**Ce que dit l'application en cas de conflit**

> « Le numéro 2026-10 est déjà utilisé par la facture émise 2026-10 (mandat « … ») ; numéro libre proposé : 2026-11. Rien n'a été modifié : aucun numéro n'est jamais remplacé automatiquement. »

Selon le cas, « utilisé par » est suivi de : « le brouillon n° … (numéro réservé) », « une facture historique (hors application) n° … » ou « un numéro de facture externe réservé (…) ». **Que faire :** saisir le numéro libre proposé (ou un autre), puis enregistrer. Le brouillon reste inchangé tant que le conflit n'est pas réglé.

Autres messages :
- « numéro invalide : lettres latines, chiffres, « - » et « / » seulement … (caractère refusé : espace) » : retirer les espaces ou signes interdits.
- « numéro trop long (20 caractères au maximum) ».
- « le préfixe « NC- » est réservé aux notes de crédit ».
- À l'émission : « le numéro de facture a changé depuis l'affichage … ; vérifier le numéro » (la page est restée ouverte pendant un changement : recharger) ou « le numéro … vient d'être pris … : modifier le numéro du brouillon (numéro libre proposé : …) ».

---

## 6. Émettre la facture

**Où :** **Factures et brouillons**, ligne du brouillon, bouton **Contrôler et émettre** (ou, depuis « Édition des factures », **Contrôler avant émission**). La page « **Émettre la facture** » se lit en trois temps.

**À gauche (ou en haut sur téléphone) : le récapitulatif**, toujours visible : Total TTC, Numéro de facture, Date imprimée, Période, Quantité facturée, Lignes manuelles, Montants, Reliquat, Solde contractuel. Une ligne d'état dit soit « **Prêt à émettre** », soit « **Avant d'émettre :** … » (ce qu'il reste à décider), soit « **Émission impossible** ».

**1. Contrôles avant émission.** 14 contrôles, chacun « conforme », « à noter » ou « ANOMALIE ».
- Un contrôle en anomalie : bouton **Corriger le brouillon** (retour à l'éditeur).
- Seuls les contrôles **12** (« La facture, l'annexe et la position racontent la même histoire ») et **13** (« La période facturée se termine au plus tard à la date de la facture ») admettent une **dérogation** : écrire un motif dans la case sous le contrôle (« Dérogation motivée — obligatoire », avec un nombre minimum de caractères indiqué). Le motif est gardé dans le journal d'audit et n'est pas imprimé.
- Autre anomalie : « **Émission impossible** », le bouton d'émission est grisé. Il faut corriger le brouillon.
- **Aucune tolérance sur les jours (depuis la 9.2-rc41).** La quantité facturée doit être égale aux jours réellement travaillés dans la période : une facture **inférieure ou supérieure** (même de 0,25 j) est un écart au contrôle 12, qui demande un motif écrit. Avant la rc41, une sous-facturation jusqu'à 0,5 j était admise sans motif ; ce n'est plus le cas. Pour éviter l'écart, choisir « Sans arrondi » ou la règle d'arrondi qui donne exactement les jours travaillés, ou corriger la quantité.

**2. Décisions.** Peuvent apparaître :
- **Traitement du reliquat** (jours réalisés non facturés, ou facturés d'avance) : choisir **Offert au client**, **Reporté sur une prochaine facture** ou **Autre traitement (préciser)** et remplir **Précision** pour « autre ».
- **Facture antidatée** (date imprimée antérieure à aujourd'hui) : cocher « Je confirme émettre cette facture avec la date du … ».
- Sinon : « Aucune décision à prendre ».

**3. Émission.** Bouton **Émettre définitivement la facture 2026-N — montant**. Avant, le bouton **Aperçu PDF (brouillon)** montre le document tel qu'il sera figé. **L'émission est définitive** : numéro, PDF, date et annexe sont figés.

**Ce qui s'affiche après :** « Facture 2026-N émise le … ». La facture apparaît dans **Factures et brouillons** avec les boutons **PDF** et **Note de crédit…**.

**Messages courants à l'émission** (précédés de « Émission refusée : »)

| Message | Que faire |
|---|---|
| « Champs à compléter : … » (bandeau, avec liens **Paramètres** et **Mandat**) | Compléter les paramètres de l'émetteur ou la fiche du mandat (par exemple le client, l'adresse). |
| « la période chevauche la facture déjà émise … : modifier la période ou supprimer ce brouillon » | Corriger la période du brouillon. |
| « le total de la facture est nul ou négatif : modifier le brouillon » | Vérifier quantité et montants. |
| « date de facture … postérieure au jour d'émission » ou « la date de facture précède le début de la période facturée » | Corriger la **Date de facture** dans l'éditeur (ou la vider). |
| « date de facture … antérieure à la date réelle d'émission : cocher la confirmation explicite de l'antidatage » | Cocher la case de confirmation dans « 2. Décisions ». |
| « adresse trop longue pour le document imprimé … » | Raccourcir l'adresse (paramètres, fiche du mandat ou liste d'adresses). |
| « facture déjà émise » | Elle l'est déjà : consulter **Factures et brouillons**. |

---

## 7. Corriger une erreur : la note de crédit (avoir)

Une facture émise ne se modifie pas. Dans **Factures et brouillons**, ligne de la facture, bouton **Note de crédit…** ouvre la page « **Note de crédit sur la facture 2026-N** ». Le tableau du haut résume ce qui est **Créditable (facture)**, **Déjà crédité (brouillons et émises)** et le **Solde créditable** (HT, TTC, quantité ; avec le détail prestation / lignes manuelles / AUTRES).

**Remplir le formulaire**

1. **Mode de traitement** (obligatoire, définitif après émission) :
   - **Remboursement** : le montant crédité est à rendre au client. Option **Délai de remboursement (jours, facultatif)** : vide = aucune échéance, sinon la date limite est imprimée et suivie.
   - **Compensation sur facture ultérieure** (imputation) : le montant est déduit d'une facture ultérieure **du même client**, en une ou plusieurs fois.
2. **Étendue** :
   - **Crédit total du solde créditable** : tout ce qui reste est crédité (prestation, lignes manuelles et « AUTRES »). Les champs de montants sont alors ignorés.
   - **Crédit partiel** : renseigner **soit** des jours (**Jours crédités**, au tarif de la facture), **soit** un **montant HT crédité**. Les jours crédités réduisent les jours facturés du mandat ; un montant seul ne change pas la position en jours.
3. **Lignes manuelles, ligne à ligne :** s'il y en a, un tableau **Lignes manuelles de la facture — montant HT crédité par ligne** montre pour chaque ligne le montant, ce qui est déjà crédité et le solde créditable. Saisir dans **À créditer (HT)** le montant voulu pour chaque ligne (en tout ou partie ; vide = ligne non créditée). La TVA suit celle de la facture d'origine pour chaque ligne. Une ligne entièrement créditée affiche « entièrement créditée ».
4. **Montant « AUTRES » crédité (CHF)** si la facture comportait une ligne « AUTRES ».
5. **Motif** (obligatoire, imprimé) ; **Description de la ligne** (facultatif, par défaut « Note de crédit sur facture 2026-N »).
6. Cliquer **Créer le brouillon de note de crédit**. Message : « Brouillon de note de crédit créé. La facture d'origine reste inchangée. »

**Émettre la note.** Dans **Factures et brouillons** (ou la section « Notes de crédit — remboursements et compensations »), la ligne du brouillon de note propose **Émettre** et **Supprimer**. Message : « Note de crédit NC-… émise (facture … inchangée). Mode : … ». La note a son propre numéro (NC-2026-N) et son PDF figé. Boutons de la ligne : **PDF** et **Suivi**.

**Suivre et clôturer (bouton Suivi, page « Note de crédit … — suivi »)**

- **Remboursement :** une fois le virement fait, formulaire **Enregistrer un remboursement exécuté** : **Montant remboursé (CHF)**, **Date d'exécution**, **Référence du virement**, **Note**, puis **Enregistrer le remboursement**. Ne saisir qu'un virement réellement exécuté. Un remboursement partiel laisse un « Reste à rembourser ».
- **Compensation :** formulaire **Imputer sur une facture ultérieure** : choisir la **Facture cible**, le **Montant imputé (CHF)**, puis **Imputer**. Sur un brouillon de facture, l'imputation s'imprime (« NET À PAYER ») et devient définitive à l'émission de celui-ci ; sur une facture déjà émise, elle est seulement enregistrée (le PDF émis ne change pas).
- **Se tromper dans une opération :** bouton **Annuler** sur la ligne de l'opération, avec un **Motif d'annulation** (une écriture d'annulation est ajoutée ; rien n'est effacé). Une imputation déjà figée sur une facture émise ne peut plus être annulée.

**Messages courants**

| Message | Que faire |
|---|---|
| « choisir le mode de traitement : remboursement ou compensation » | Cocher un des deux modes. |
| « motif obligatoire » | Remplir le motif. |
| « indiquer des jours, un montant HT de prestation, un montant « AUTRES » ou un montant sur une ligne manuelle à créditer » | Remplir au moins un champ de montant, ou choisir « Crédit total ». |
| « prestation : indiquer soit une quantité de jours, soit un montant HT (l'un des deux) » | Ne remplir que l'un des deux. |
| « le tarif de la note de crédit … doit être celui de la facture d'origine … ; pour un autre montant, créditer un montant HT » | Laisser le tarif proposé, ou créditer un montant HT. |
| « le cumul crédité sur la ligne 2 « … » (… HT) dépasserait son montant … solde créditable … » | Saisir un montant inférieur ou égal au solde créditable de la ligne. De même pour la prestation, « AUTRES » ou le total TTC (« le cumul … dépasserait … »). Tout dépassement est refusé. |
| « cette facture est déjà entièrement créditée » | Il n'y a plus rien à créditer. |
| « Crédit total indisponible — … » | La facture a reçu une compensation déjà consommée à son émission, ou des imputations actives : seul un crédit partiel dans la limite du net à payer est possible, ou annuler d'abord les imputations actives depuis le suivi de la note concernée. |
| « la note de crédit ne tient pas sur une page … : créditer moins de lignes à la fois (plusieurs notes) ou raccourcir le motif » | Faire plusieurs notes, ou raccourcir le motif. |
| « le remboursement … dépasse le solde restant à rembourser » ; « l'imputation … dépasse le solde disponible … / le montant restant dû sur la facture cible » | Réduire le montant. |
| « un remboursement ne peut être enregistré qu'une fois exécuté (date future refusée) » | Saisir la vraie date du virement. |
| « facture cible non admissible : même client juridique, facture ultérieure, autre que la facture d'origine » | Choisir une autre facture cible dans la liste. |

---

## 8. Annuler une note de crédit, ou annuler et refaire une facture

**Cas A — je me suis trompé dans la note de crédit déjà émise**

1. Ouvrir la note : **Suivi**, puis le cadre **Corriger : annuler cette note de crédit**.
2. Remplir **Motif d'annulation (imprimé)**, cliquer **Émettre le document d'annulation** et confirmer la question posée. Un document **ANN-NC-…** (PDF figé) est émis ; la note et son annulation restent visibles toutes les deux.
3. Créer la note correcte : lien **créer la note de remplacement** (ou **Note de crédit…** sur la facture). Dans le formulaire, la liste « **Remplace une note annulée (facultatif)** » permet de relier la nouvelle note à l'ancienne.

Si le cadre dit « Annulation impossible pour l'instant : … » : des montants sont déjà remboursés ou imputés (« annuler d'abord ces opérations (écritures d'annulation) »), ou la période de la facture a été refacturée entre-temps (double facturation à éviter).

**Cas B — la facture émise est fausse, il faut la refaire**

1. Sur la facture, **Note de crédit…**, choisir le mode (**Remboursement** s'il n'y a rien à redéduire, sinon **Compensation**), puis **Crédit total du solde créditable**, un **Motif**, **Créer le brouillon de note de crédit**, puis **Émettre**.
2. Une facture **entièrement créditée** libère sa période : elle peut de nouveau être facturée. Dans **Édition des factures**, créer un nouveau brouillon sur la même période (chapitre 1), puis le compléter et l'émettre.
3. Le nouveau numéro est le prochain libre ; l'ancien numéro n'est **jamais** réutilisé. Si la période ne peut pas être refacturée, c'est que le crédit n'est pas total ou pas encore émis (message « pour la facturer de nouveau, créditer d'abord cette facture intégralement (note de crédit totale émise) »).
4. Si une compensation avait déjà été imputée et figée sur la facture, le crédit total est refusé : voir « Crédit total indisponible » plus haut.

**Cas C — j'ai seulement un brouillon à jeter**

Dans **Factures et brouillons**, bouton **Supprimer** du brouillon. Message : « Brouillon supprimé. » Son numéro redevient libre. Les imputations réservées sur ce brouillon sont libérées (« N imputation(s) de note de crédit libérée(s) »). Seul un brouillon peut être supprimé ; une facture émise ne se supprime jamais.

## 6 bis. Le mandat « STC GEM » : émission sans blocage et tarif modifiable (9.2-rc41)

Ce mandat — et lui seul — fonctionne autrement (décision du propriétaire du 28.10.2026). Détail technique, désactivation et retour arrière : `docs/FACTURES-EXCEPTION-STC-GEM.md`.

- **Rien ne bloque l'émission.** Les 14 contrôles sont toujours calculés et affichés, mais un contrôle en échec (y compris le 14, d'ordinaire sans dérogation possible) s'affiche « **ÉCART · STC GEM (non bloquant)** » ; aucun motif n'est demandé et le bouton d'émission reste actif. Un encadré rappelle que ces écarts sont conservés dans le journal d'audit avec la mention « exception STC GEM ». Le PDF et les montants ne changent pas.
- **Ce qui continue de bloquer** (ce ne sont pas des contrôles de cohérence) : champs obligatoires à compléter, période qui chevauche une facture déjà émise, date de facture invalide, total nul ou négatif, adresse trop longue, lignes manuelles (émission suspendue), numéro déjà pris.
- **Tarif modifiable.** Dans « Modifier le brouillon », la ligne **Prestations** montre un champ de tarif (par jour ou par heure selon l'unité). Saisir le nouveau tarif (strictement positif, 4 décimales au plus, 1 000 000 000 au maximum), puis **Enregistrer le brouillon** : le message « Tarif du brouillon modifié (exception STC GEM) » confirme, les totaux de la page et le PDF utilisent ce tarif. L'ancien tarif, le nouveau et l'utilisateur sont écrits dans le journal d'audit. Le contrôle 3 signale alors, sans bloquer, que le tarif n'est plus celui de la fiche du mandat.
- **Les factures déjà émises ne changent jamais** : le tarif saisi n'est enregistré que sur ce brouillon, puis figé avec la facture.
- Changer l'unité (jours ↔ heures) sans toucher au champ tarif reprend le tarif du mandat pour la nouvelle unité, comme avant.
- Pour tous les autres mandats, rien ne change (hors le point sur les tolérances du §6) : tarif en lecture seule, contrôles bloquants.

---

## 9. Tableau « Je veux… → je fais… »

| Je veux… | Je fais… |
|---|---|
| Créer une facture | **Édition des factures** → choisir le projet et la période → **Créer le brouillon** |
| Retrouver un brouillon | **Factures et brouillons** → filtre **Brouillons** → **Modifier** |
| Voir à quoi ressemblera la facture | Ligne du brouillon → **PDF (brouillon)** (ou **Aperçu PDF (brouillon)** sur la page d'émission) |
| Ajouter des frais ou un forfait | **Modifier** le brouillon → **Ajouter une ligne** → remplir → **Enregistrer le brouillon** |
| Mettre une ligne hors TVA | Dans la ligne : **TVA de la ligne** → « hors TVA (ajouté après la TVA) » |
| Retirer une ligne | **Supprimer cette ligne** → **Enregistrer le brouillon** |
| Changer le traitement TVA de « AUTRES » | Liste **TVA sur « AUTRES »** du brouillon ; par défaut des futurs brouillons : **Paramètres & sauvegardes** |
| Choisir l'adresse EGG FR / BE / CH / MEA | Brouillon → **Adresse de facturation** → choisir → **Enregistrer le brouillon** |
| Ajouter ou corriger une adresse | Lien **Gérer les adresses** (page « Adresses de facturation ») |
| Mettre à jour la copie d'une adresse modifiée | Cocher « Actualiser la copie d'après l'adresse enregistrée » → enregistrer |
| Changer le numéro de facture | Brouillon → champ **Numéro de facture** → taper le numéro → **Enregistrer le brouillon** |
| Revenir au numéro automatique | Vider le champ **Numéro de facture** → enregistrer |
| Comprendre « numéro déjà utilisé » | Lire qui le détient dans le message ; prendre le « numéro libre proposé » |
| Changer la date de facture | Brouillon → **Date de facture** (vide = jour d'émission) |
| Émettre | **Contrôler et émettre** → vérifier les 14 contrôles → décisions → **Émettre définitivement la facture …** |
| Émettre malgré la période qui dépasse la date (contrôle 13) | Écrire le motif dans la case du contrôle 13, puis émettre |
| Facturer moins (ou plus) de jours que ceux travaillés | Écrire le motif dans la case du contrôle 12 (plus aucune tolérance de 0,5 j depuis la rc41) |
| Changer le tarif d'une facture du mandat STC GEM | **Modifier** le brouillon → champ de tarif de la ligne Prestations → **Enregistrer le brouillon** (§6 bis) |
| Corriger une facture émise en partie | Ligne de la facture → **Note de crédit…** → **Crédit partiel** |
| Corriger une seule ligne manuelle | Même formulaire → colonne **À créditer (HT)** de la ligne concernée |
| Annuler toute la facture | **Note de crédit…** → **Crédit total du solde créditable** → **Créer le brouillon de note de crédit** → **Émettre** |
| Rendre l'argent au client | Mode **Remboursement**, puis au **Suivi** : **Enregistrer le remboursement** après le virement |
| Déduire l'avoir d'une prochaine facture | Mode **Compensation sur facture ultérieure**, puis au **Suivi** : **Imputer** |
| Annuler un remboursement ou une imputation saisis par erreur | **Suivi** → tableau « Opérations » → **Annuler** (avec motif) |
| Annuler une note de crédit déjà émise | **Suivi** → **Corriger : annuler cette note de crédit** → **Émettre le document d'annulation** |
| Refaire une facture fausse | Note de crédit **totale** émise → nouveau brouillon sur la même période |
| Supprimer un brouillon inutile | **Factures et brouillons** → **Supprimer** |
| Télécharger les documents émis | **Factures et brouillons** → **Télécharger l'archive des documents émis (ZIP)** |

---

## 10. Quand on est bloqué

1. **Lire le message en entier** : il dit presque toujours ce qui ne va pas et ce qu'il faut changer.
2. Un message « … Rien n'a été modifié » signifie que la page n'a rien enregistré : on peut corriger et recommencer sans risque.
3. Le bouton d'émission est grisé : lire le bandeau « Émission impossible » en haut de la page d'émission (champs à compléter, date à corriger, contrôle sans dérogation possible).
4. Ne jamais essayer de « contourner » un numéro, une date ou un montant déjà figé : passer par une note de crédit.
5. Si un message ressemble à une erreur interne (par exemple « Avertissements non calculés (erreur interne, détail dans le journal du service) »), noter le texte exact et prévenir la personne qui gère l'application.
