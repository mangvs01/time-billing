# Prototype de faisabilité du vérificateur indépendant (RC25)

**Non utilisé, non installé, hors production.** Il sert uniquement à prouver, de façon reproductible, les propriétés annoncées dans
`CONCEPTION-GARDE-CONFIANCE-RC25.md` (tests : `tests/test_gate_prototype.py`, exécutés en root dans un dossier temporaire ; ignorés sans `go`, `openssl` ou root).

Ce n'est pas l'implémentation : pas de gestion d'opérations nommées, pas de conf validée par le vérificateur, pas de journal, pas de verrou, pas de mise à jour
de manifeste. Les clés utilisées par les tests sont générées à la volée dans un dossier temporaire et jamais conservées.
