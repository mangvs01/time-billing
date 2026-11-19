# Génère migration-blanc/dry-run-i-rc23.sh à partir de la répétition G (dry-run-g-rc22.sh) : même déroulé, versions rc22 → rc23, parcours
# « correction + ajout » des factures historiques. Usage : python3 -I migration-blanc/genere-dry-run-i-rc23.py
import os
MB = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(MB, 'dry-run-g-rc22.sh')).read()
head_old = s[:s.index('set -uo pipefail')]
head_new = '''#!/bin/bash
# Répétition I (rc23, 2026-10-08) : la séquence prévue pour le déploiement de 9.2-rc23 sur le staging (correction des factures historiques,
# décision billing-g4-correction-historiques = A ; déploiement soumis à un nouveau go de l'utilisateur), sur un faux staging jetable dans l'état
# du staging réel après le déploiement rc22 du 2026-10-07 23:38 UTC. Aucune lecture de /opt : base = sauvegarde pre-rc22-20261007T233832Z
# (SHA vérifié ; celle que 40 a migrée en rc22 à 23:38), code rc22 = copie figée 9.2-rc22-2282419 (staging.conf), code rc23 = copie figée REL23.
#   0. faux staging rc22 (secrets de test)        1. 10 → 20 → 30 → 40 → 50 (rc23)
#   2. contrôles rc23 : données métier identiques (outils/empreinte_metier.py + pages), brouillon n°1, export .xlsx, pages « Corriger » / « Ajouter »
#   3. retour arrière (rien d'écrit) : accepté → rc22, base = sauvegarde      4. redéploiement 10 → 50
#   5. parcours utilisateur : validation des 24 historiques, correction d'une ligne, ajout d'une ligne, export (CA = « Facturé »)
#   6. retour arrière après ces écritures : doit être refusé
# Jamais le staging réel ni la production. Généré par genere-dry-run-i-rc23.py depuis dry-run-g-rc22.sh.
# Usage : REL23=<copie figée rc23> RC23_IMAGE=<image> [PORT=<port>] migration-blanc/dry-run-i-rc23.sh   (port 8437, bac à sable migration-blanc/I-RC23, recréé)
'''
s = head_new + s[len(head_old):]
REP = [
    ("S=$MB/G-RC22; P=$W/procedure; PORT=${PORT:-8436}", "S=$MB/I-RC23; P=$W/procedure; PORT=${PORT:-8437}"),
    ("REL21=/root/time-billing-releases/9.2-rc21-51b7c1b; REL22=/root/time-billing-releases/9.2-rc22-2282419",
     "REL22=/root/time-billing-releases/9.2-rc22-2282419; REL23=${REL23:?copie figée rc23}"),
    ("RC21_IMAGE=tb-g4-cand:51b7c1b; RC22_IMAGE=tb-g4-cand:2282419", "RC22_IMAGE=tb-g4-cand:2282419; RC23_IMAGE=${RC23_IMAGE:?image rc23}"),
    ("PRE=/root/backups/time-billing-v9-staging/pre-rc21-20261007T130853Z", "PRE=/root/backups/time-billing-v9-staging/pre-rc22-20261007T233832Z"),
    ("for R in $REL21 $REL22; do", "for R in $REL22 $REL23; do"),
    ("""grep -q '^VERSION="9.2-rc22"' $REL22/app/app.py || { echo "copie rc22 : VERSION inattendue"; exit 1; }""",
     """grep -q '^VERSION="9.2-rc23"' $REL23/app/app.py || { echo "copie rc23 : VERSION inattendue"; exit 1; }"""),
    ('chmod -R u+w "$S" 2>/dev/null; rm -rf "$S"; }', 'chmod -R u+w "${S:?}" 2>/dev/null; rm -rf "${S:?}"; }'),
    ("tbmb-grc22", "tbmb-irc23"),
    ('step "0. faux staging rc21 : code = copie figée 9.2-rc21-51b7c1b, base', 'step "0. faux staging rc22 : code = copie figée 9.2-rc22-2282419, base'),
    ('ok "sauvegarde pre-rc21 intacte" || { ko "sauvegarde pre-rc21 altérée"', 'ok "sauvegarde pre-rc22 intacte" || { ko "sauvegarde pre-rc22 altérée"'),
    ("cp -r $REL21/app $REL21/requirements.txt $REL21/requirements.lock $REL21/Dockerfile $REL21/.dockerignore $ROOT/",
     "cp -r $REL22/app $REL22/requirements.txt $REL22/requirements.lock $REL22/Dockerfile $REL22/.dockerignore $ROOT/"),
    ("HASH=$(docker run --rm --network none $RC21_IMAGE", "HASH=$(docker run --rm --network none $RC22_IMAGE"),
    ("SOURCE_APP=$REL22/app\nSOURCE_REQ=$REL22/requirements.txt\nRC_IMAGE=$RC22_IMAGE", "SOURCE_APP=$REL23/app\nSOURCE_REQ=$REL23/requirements.txt\nRC_IMAGE=$RC23_IMAGE"),
    ("""grep -q '9.2-rc21' <<<"$V0" && ok "faux staging en rc21\"""", """grep -q '9.2-rc22' <<<"$V0" && ok "faux staging en rc22\""""),
    ('SHEETS() { docker run --rm --network none -v "$1:/x.xlsx:ro" $RC22_IMAGE', 'SHEETS() { docker run --rm --network none -v "$1:/x.xlsx:ro" $RC23_IMAGE'),
    ("COPY $S/base-rc21.db; SNAP $S/etat-rc21.json\nEXPORT $S/export-rc21.xlsx; SHEETS $S/export-rc21.xlsx > $S/onglets-rc21.txt",
     "COPY $S/base-rc22.db; SNAP $S/etat-rc22.json\nEXPORT $S/export-rc22.xlsx; SHEETS $S/export-rc22.xlsx > $S/onglets-rc22.txt"),
    ('step "1. déploiement rc22 :', 'step "1. déploiement rc23 :'),
    ("cp -p $ROOT/.env $ROOT/.env.rc22", "cp -p $ROOT/.env $ROOT/.env.rc23"),
    ('grep -q "$(cd $REL22/app', 'grep -q "$(cd $REL23/app'),
    ('$S/backups/pre-rc22-$(cat $S/backups/last-backup)/source-app.sha256 \\\n  && ok "empreinte du code noté par 20 = copie figée rc22"',
     '$S/backups/pre-rc23-$(cat $S/backups/last-backup)/source-app.sha256 \\\n  && ok "empreinte du code noté par 20 = copie figée rc23"'),
]
for a, b in REP:
    assert a in s, a[:70]
    s = s.replace(a, b)
s = s[:s.index('step "2. contrôles rc22')] + open(os.path.join(MB, 'dry-run-i-rc23.suite.sh')).read()
out = os.path.join(MB, 'dry-run-i-rc23.sh')
open(out, 'w').write(s); os.chmod(out, 0o755)
print(out)
