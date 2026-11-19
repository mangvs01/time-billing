# Génère migration-blanc/dry-run-j-rc24.sh depuis la répétition I (dry-run-i-rc23.sh, GO) : même déroulé, cible rc24 au lieu de rc23, base de
# départ = sauvegarde pre-rc23-20261008T061057Z (staging en rc22 à 06:10 UTC le 08.10, état réel le plus récent). Usage : python3 -I migration-blanc/genere-dry-run-j-rc24.py
import os, re
MB = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(MB, 'dry-run-i-rc23.sh')).read()
OLD_PRE, NEW_PRE = 'pre-rc22-20261007T233832Z', 'pre-rc23-20261008T061057Z'
assert OLD_PRE in s
s = s.replace(OLD_PRE, '@@PRE@@')
for a, b in (('Répétition I (rc23, 2026-10-08)', 'Répétition J (rc24, 2026-10-08)'), ('I-RC23', 'J-RC24'), ('irc23', 'jrc24'), ('PORT:-8437', 'PORT:-8438'),
             ('(port 8437', '(port 8438'), ('genere-dry-run-i-rc23.py', 'genere-dry-run-j-rc24.py'), ('dry-run-i-rc23', 'dry-run-j-rc24'),
             ('RÉPÉTITION I :', 'RÉPÉTITION J :')):
    assert a in s, a
    s = s.replace(a, b)
s = re.sub(r'rc23', 'rc24', s); s = re.sub(r'RC23', 'RC24', s); s = s.replace('REL23', 'REL24')
s = s.replace('@@PRE@@', NEW_PRE)
s = s.replace("après le déploiement rc22 du 2026-10-07 23:38 UTC", "en rc22 le 2026-10-08 06:10 UTC (avant le redéploiement rc23 arrêté à 40)")
out = os.path.join(MB, 'dry-run-j-rc24.sh')
open(out, 'w').write(s); os.chmod(out, 0o755)
print(out)
