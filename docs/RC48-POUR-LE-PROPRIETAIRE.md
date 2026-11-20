# Time Billing 9.2-rc48 — en clair (préparée, pas encore en ligne)

- **Ce qui change pour vous** : un avoir sur toute une ligne finissant par un demi-centime est enfin accepté ; deux adresses de facturation ne peuvent plus différer seulement par les majuscules ; les refus de la base s'affichent en français.
- **Aussi dans cette version** : le mot de passe de l'application doit avoir 10 caractères au moins (votre demande du 20/11) ; un guide en bref (`docs/GUIDE-EN-BREF.md`) dit où cliquer.
- **QR-facture** : préparée et vérifiée sur des factures fictives, mais **éteinte** : vos factures restent comme avant. Pour l'allumer plus tard : 6 étapes dans `docs/QR-ALLUMAGE.md`.
- **Ce qui est vérifié** : les 1284 tests passent ; la mise à jour a été répétée sur une base fictive (50 contrôles, aucun échec) sans toucher aucune donnée de facture.
- **Pas encore vérifié** : la vraie base. Avant la mise en ligne, le superviseur la contrôle sur une copie, en lecture seule (`docs/revues-rc48/VERIFS-COPIE-PROD.md`).
- **Votre rôle** : donner le GO ; si deux adresses d'un même client se ressemblent à la casse près, les renommer avant.
- **Retour arrière** : application arrêtée, on lance `outils/retour_rc47.py` (copie de sécurité automatique, aucune donnée touchée), puis on redémarre rc47 ; ou on restaure la sauvegarde faite avant la mise en ligne.
