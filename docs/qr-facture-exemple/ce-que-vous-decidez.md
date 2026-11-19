# QR-facture : ce que vous décidez

À partir du 20 novembre 2026, les banques suisses refusent les paiements dont l'adresse n'est pas écrite en champs séparés (rue, numéro, code postal, localité, pays). Le paiement par QR-facture (le petit carré noir et blanc que l'on scanne avec son application bancaire) devient la norme.

## Ce qui est réglé

- **C'est une option, facture par facture** (vos réponses du 4 novembre). Sur chaque brouillon, et à l'écran d'émission, une case « Ajouter la QR-facture (bulletin de paiement suisse) » : décochée par défaut. Cochée, la facture reçoit une page de plus avec le bulletin ; décochée, elle sort exactement comme aujourd'hui. Les factures déjà émises ne changent jamais.
- **Si une information manque, l'émission est bloquée.** L'écran d'émission dit précisément quel champ corriger (par exemple « Adresse du client, code postal : champ obligatoire ») et donne le lien vers le bon écran. Vous pouvez toujours décocher la case pour émettre la facture sans bulletin.
- **Comptes non suisses** (France, Belgique, Moyen-Orient et Afrique) : la case est grisée avec « pas de bulletin pour ce compte » ; aucun message d'erreur, aucun blocage.
- **Les écrans de saisie existent maintenant** (4 novembre) : l'adresse de l'émetteur et son éventuel compte « QR-IBAN » se saisissent dans les Paramètres (bloc « Adresse de l'émetteur en champs séparés et compte QR ») ; l'adresse de chaque client se saisit dans la fiche du mandat (section « Adresse de facturation en champs séparés »). La bibliothèque qui dessine le bulletin est maintenant livrée avec l'application.

## Ce qu'il reste à décider : uniquement des valeurs à saisir et à confirmer

Rien n'est inventé par l'application. Il vous reste à :

1. **Émetteur** : saisir le numéro de compte bancaire suisse (IBAN) à imprimer (aujourd'hui, la facture de test porte un numéro fictif ; un IBAN dont la clé de contrôle est fausse est signalé) et l'adresse de l'entité en champs séparés. Si votre banque vous a donné un compte spécial « QR-IBAN », le saisir aussi : le bulletin utilisera alors une référence de 27 chiffres tirée du numéro de facture ; sinon, le compte habituel avec une référence tirée du numéro de facture.
2. **Chaque client (mandat)** : relire l'adresse en champs séparés, puis cocher « adresse vérifiée ». Trois adresses vous sont **proposées** d'après le texte que vous avez fourni, marquées « à confirmer » (rien n'est enregistré sans votre clic sur « Enregistrer ») :
   - EGG CH : Route de Saint Julien, 63, 1212 Lancy, CH ;
   - EGG FR : avenue Victor Hugo, 55, 75116 Paris, FR ;
   - EGG BE : Avenue du Bourgmestre Etienne Demunter, « 5, boîte 10 », 1090 JETTE, BE (à relire en particulier : le nom de la rue tenait sur deux lignes et le numéro porte une boîte).
   EGG MEA : **rien n'est proposé**, le texte ne donne ni code postal ni numéro ; à saisir par vous.
3. Tant qu'une adresse de client n'est pas marquée « vérifiée », l'émission avec QR-facture reste bloquée (vous pouvez décocher la case).

## Ce que nous n'avons pas pu vérifier

Le bulletin n'a pas encore été scanné par une vraie application bancaire ni passé au contrôle officiel : c'est la dernière étape avant d'allumer l'option en production. Nous avons vérifié que le code QR dessiné dans le PDF correspond, module par module, au contenu attendu, mais ce n'est pas une lecture par une banque.
