# QR-facture : allumer l'option, en 6 étapes

**Où on en est.** La QR-facture (le petit carré noir et blanc que l'on scanne avec son application bancaire) est prête, vérifiée sur des factures fictives, mais **éteinte** : vos factures sont exactement comme avant. Rien ne change tant que les 6 étapes ci-dessous ne sont pas faites. Les étapes 1 à 3 et 5 à 6 sont pour vous ; l'étape 4 est faite par la personne qui gère le serveur (elle vous prévient).

**Pourquoi.** Depuis le 20 novembre 2026, les banques suisses refusent les paiements dont l'adresse n'est pas écrite en champs séparés. La QR-facture porte ces champs.

## Étape 1 — Votre IBAN et votre adresse (3 minutes)

Menu **« Paramètres & sauvegardes »**.
- Champ IBAN : votre **IBAN suisse ordinaire** (il commence par CH), celui de votre compte habituel. Pas de compte spécial à demander à la banque. Laissez le champ « QR-IBAN (facultatif) » vide.
- Cadre **« Adresse de l'émetteur en champs séparés et compte QR »** : rue, numéro, code postal, localité, pays (CH pour la Suisse).
- Cliquez **« Enregistrer les paramètres »**. Si quelque chose est refusé, l'écran dit quoi et pourquoi.

## Étape 2 — L'adresse de chaque client actif (2 minutes par client)

Menu **« Mandats & prévisionnel »**, puis **« Modifier »** sur le mandat : rue, numéro, code postal, localité, pays (deux lettres : CH, FR, BE…). Relisez les adresses déjà proposées (EGG CH, EGG FR, EGG BE) ; **EGG MEA est à saisir à la main**. Cochez **« adresse vérifiée »**, puis enregistrez. Un client à l'étranger n'est pas un problème : seul **votre** compte doit être suisse.

## Étape 3 — Vérifier que tout est rempli

À la connexion suivante, la fenêtre de rappel ne doit plus s'afficher. Si elle s'affiche, elle dit exactement ce qui manque, avec un bouton vers l'écran concerné. Ne passez à l'étape 4 qu'ensuite, et dites que c'est prêt à la personne qui gère le serveur.

## Étape 4 — Allumage (par la personne qui gère le serveur, 10 minutes, avec votre accord)

Rien à faire de votre côté, sauf être joignable. Elle fait, dans l'ordre :
1. une **sauvegarde** de la base, vérifiée (retour possible à l'identique) ;
2. s'assure que la version en ligne contient la ligne `QR_BILL_ENABLED` dans son fichier de service (sans elle, la valeur écrite dans le fichier de secrets n'arrive jamais à l'application) ;
3. écrit `QR_BILL_ENABLED=1` dans le fichier de secrets du serveur, puis redémarre le service (coupure d'une minute environ) ;
4. contrôle que la case **« Ajouter la QR-facture »** apparaît sur un brouillon, **décochée**, et qu'une facture ordinaire sort identique à avant.

*Retour arrière* : retirer cette ligne et redémarrer ; les factures déjà émises ne bougent jamais.

## Étape 5 — Essai avec votre application bancaire, sans payer

Sur un **brouillon**, cochez **« Ajouter la QR-facture »** et ouvrez le PDF : la page de bulletin porte la mention BROUILLON en rouge. Scannez le carré avec l'application de **votre banque** et vérifiez : votre nom et votre IBAN, l'adresse de votre client, le montant (le net à payer si un avoir est imputé). **Ne payez pas.** Sur un brouillon, la référence peut manquer : c'est normal, elle est attribuée à l'émission. Si l'application refuse le code ou si une information est fausse : décochez la case, ne facturez pas avec la QR-facture et prévenez-nous.

## Étape 6 — Première vraie facture

Cochez **« Ajouter la QR-facture »** sur une facture réelle, émettez-la (si une information manque, l'émission est bloquée avec un message clair ; la sortie est de décocher la case), ouvrez le PDF, scannez-le une dernière fois avant l'envoi. Les factures suivantes : la case reste à cocher facture par facture, décochée par défaut. Un avoir n'a jamais de bulletin ; une facture dont un avoir couvre tout le montant ne peut pas en avoir non plus (rien à payer).

---
*Pour la personne qui gère le serveur : la recette automatique est `tests/test_qr_recette.py` ; le détail technique est dans `docs/QR-FACTURE.md`. Limite connue : aucun lecteur de code QR n'est installé sur le serveur, le scan par une vraie application bancaire (étape 5) est la seule lecture réelle avant l'émission.*
