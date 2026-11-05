# Bibliothèques embarquées pour la QR-facture (BQR4)

Rien ici n'est écrit par l'application : ce sont des copies **non modifiées** des paquets publics, relevées de `/root/vendor-qrbill` (installation faite hors dépôt lors de BQR1), pour que l'image de production et les tests n'aient besoin ni d'un accès réseau ni d'un chemin extérieur. `app/qr_bill.py` ajoute ce dossier au chemin d'import **après** les paquets normaux, juste avant d'importer `qrbill` et `svglib` (variable `QR_BILL_VENDOR_DIR` pour pointer ailleurs, utile seulement aux tests).

| Paquet | Version | Licence | Rôle | Contenu embarqué |
|---|---|---|---|---|
| qrbill | 1.2.0 | MIT | construit le bulletin (SVG) | tout le paquet |
| svgwrite | 1.4.3 | MIT | dessin SVG (dépendance de qrbill) | tout le paquet |
| qrcode | 8.2 | BSD | matrice du code QR (dépendance de qrbill) | tout le paquet |
| iso3166 | 3.0.0 | MIT | codes pays (dépendance de qrbill) | tout le paquet |
| python-stdnum | 2.2 | LGPL-2.1+ | clé de contrôle IBAN et références (dépendance de qrbill) | seulement `iban`, `iso11649`, `ch.esr`, `iso7064.mod_97_10`, `numdb`, `util`, `exceptions`, `iban.dat` (le reste, 6 Mo de formats de numéros de pays, n'est pas utilisé) |
| svglib | 2.3.2 | LGPL-3.0+ | SVG → dessin reportlab | tout le paquet |
| cssselect2, tinycss2, webencodings | 0.10.1, 1.5.1, 0.6.1 | BSD | analyse CSS (dépendances de svglib) | tout le paquet |
| lxml | 6.1.3 | BSD-3 | analyse XML (dépendance de svglib) | `__init__.py` et les deux modules compilés `etree` et `_elementpath` |

**Attention, point de portabilité :** `lxml` n'est pas du Python pur. Les deux fichiers `.so` embarqués sont ceux de la roue `cp312-manylinux x86_64` : ils fonctionnent avec Python 3.12 sous Linux x86-64, ce qui est le cas de l'image `python:3.12-slim` du `Dockerfile` (architecture amd64). Sur une autre version de Python ou une autre architecture (arm64), l'import échoue et l'application affiche « La bibliothèque de QR-facture n'est pas installée sur ce serveur » (aucun autre effet : sans case cochée rien n'est utilisé). `reportlab` et `pillow`, requis aussi par svglib, sont déjà des dépendances de l'application.

Les fichiers de licence de chaque paquet sont dans `licences/<paquet>/`. `python-stdnum` et `svglib` sont sous LGPL : copies non modifiées, utilisées par import, licence jointe ; leur remplacement par une autre version est possible en remplaçant le dossier.

Mise à jour : relever la nouvelle version dans un environnement séparé, remplacer le dossier du paquet, relancer `python -m unittest tests.test_qr_bill tests.test_qr_bill_option tests.test_qr_bill_addresses`.
