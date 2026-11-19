# Time Billing V9.2 — RC11

Saisie des temps, mandats et prévisions, facturation (factures émises immuables, annexes cumulatives figées, notes de crédit),
archivage et import historique Excel. Application Flask + SQLite, mono-utilisateur, derrière un reverse proxy HTTPS.

## Parcours
Tableau de bord · Saisie des heures (début/fin **ou** durée directe ; liste, correction, suppression tracées) · Mandats & prévisionnel ·
Édition des factures (quantité non arrondie visible avant le choix de l'arrondi) · Factures émises (PDF figés, notes de crédit, archive ZIP) ·
Import historique · Paramètres & sauvegardes.

## Démarrage (staging ou production)
- Secrets **uniquement** dans `.env` (mode 600) : `APP_PASSWORD_HASH` (hachage scrypt), `SECRET_KEY` (≥ 32 caractères aléatoires), voir `procedure/rotate-secrets.sh`.
- `COOKIE_SECURE=1` (défaut) derrière HTTPS ; `TRUST_PROXY=1` derrière Caddy ; `ENV_LABEL=STAGING` pour afficher une pastille d'environnement.
- `docker compose up -d --build` ; santé : `curl http://127.0.0.1:8091/health`.
- Serveur : gunicorn `gthread` (2 processus × 8 fils) ; écoute locale `127.0.0.1` uniquement.

## Tests
`journaux/run_unit.sh` (conteneur sans réseau, copie de base) · `tests/e2e_http.py` · `tests/concurrency_http.py` · `tests/browser/*.js` (Chromium/Playwright).

## Exploitation
Voir `OPERATIONS-RC11.md`, `PROCEDURE-DEPLOIEMENT-RC11.md`, `PROCEDURE-ROLLBACK-RC11.md`, `MIGRATIONS-RC11.md`.
