# Time Billing V9.2-rc13 — rapport de livraison (04.10.2026)

Complète `RAPPORT-CONSOLIDE-RC12.md` (le reste de l'état RC12 est inchangé).

## 1. Modifié
| Réf. | Changement |
|---|---|
| QA-22 | Annexe cumulative : la colonne « Motif » passe à la ligne au lieu d'être coupée par « … » ; la pagination suit la hauteur réelle des lignes (21 lignes d'une ligne par page, comme avant). Seule coupure : > 28 lignes (≈ 700 caractères). Les PDF déjà figés ne changent pas. |
| QA-S3 | Défense en profondeur dans SQLite : journal d'audit en ajout seul (triggers `audit_no_update/delete`) ; plafond du cumul remboursé/imputé d'une note de crédit (`credit_ops_within_note`, TTC + 5 centimes de tolérance d'arrondi). Additif (`CREATE TRIGGER IF NOT EXISTS`), sans migration de données. |
| QA-S2 | L'identité juridique du client d'un mandat ne peut plus être modifiée tant qu'un de ses brouillons reçoit une imputation de note de crédit réservée (règle « même client juridique »). |
| Test proxy | `journaux/test_https_proxy.sh` : application derrière un Caddy **jetable** (ports 8231/8443, certificat interne, `admin off`) : cookie `Secure`+`HttpOnly`, HSTS, session, POST même origine accepté, origine étrangère refusée (403), `/health`. 9/9. Ne touche pas au Caddy du serveur. |
| Test | Recette finale : nouvelle étape `e2e_rc13` (motif long imprimé en entier, vérifié par `pdftotext`; triggers actifs dans l'application en marche). |

Non modifiés, par choix : **QA-14** (le reliquat « reporté » reste affiché à côté de la suggestion — « X j réalisés non facturés » — sans être ajouté automatiquement : c'est une décision de facturation), **QA-15** (bandeau d'avertissement hors ordre conservé), **QA-23 / T3** (voir §5).

## 2. Tests
| Contrôle | Résultat |
|---|---|
| Unitaire/fonctionnel, 20 modules, conteneur sans réseau | **333/333** (`journaux/unit-rc13-complet.log`), dont 11 tests RC13 |
| Recette navigateur + HTTP + concurrence sur l'image déployée en staging | **0 échec** : métier 107+15, saisies 34+7, responsive 33/33, RC12 22/22, RC13 5/5, e2e 30+18 (dont restauration JSON avec les nouveaux triggers), concurrence 11/11 (`journaux/recette-final13.out`) |
| Migration à blanc V9.0 → RC13 → V9.0 (copie exacte de la prod + base fictive V9.0) | **GO** des deux côtés, idempotente, retour arrière : base identique au SHA-256 (`migration-blanc/*-dryrun-rc13.log`) |
| Staging : sauvegarde, répétition, déploiement, vérifications avant/après redémarrage | conformes |
| Staging : retour arrière réel RC13 → RC12 puis redéploiement | OK (base identique SHA-256 ; `journaux/final12/rollback-rc13.log`, `redeploy-rc13.log`) |
| Proxy HTTPS jetable | 9/9 |

## 3. État
* **Staging** (`:8092`) : **9.2-rc13**, base vide (aucun mandat). Sauvegarde `/root/backups/time-billing-v9-staging/pre-rc13-*`, image de retour `:pre-rc13-20261004T121834Z`.
* **Production** (V9.0, `:8091`) : **non touchée** (base et conteneur identiques à `audit/prod-fp-avant.txt`).
* **Import réel** : non effectué. **Git** : local, propre, rien poussé.

## 4. Sécurité
Inchangé depuis RC12 (CSP à nonce, conteneur non-root en lecture seule, déconnexion POST, dépendances épinglées), plus les triggers QA-S3 et le test de comportement derrière HTTPS. Restent à votre charge : le plan Caddy/DNS/pare-feu et la rotation des secrets de production (`procedure/`), sans quoi la production reste exposée (compose en clair, écoute `0.0.0.0`, V7/V8/V30 actives).

## 5. Ce qui dépend de vous (inchangé)
1. **Registre d'import** `import/registre-final/` (R1–R3, M1–M5, M7) — bloque l'import.
2. **T3** : saisies à cheval sur minuit (scission automatique 22:00–02:00 ?) — choix métier.
3. Hypothèse « jour = 8 h ».
4. Autorisation **séparée** pour l'import réel, puis pour la bascule en production.

## 6. Risques résiduels
Production exposée tant que la bascule n'est pas faite · sauvegardes à copier hors serveur · fonctionnement derrière le vrai Caddy non éprouvé (seulement un proxy jetable équivalent) · archives ≈ 180 Ko/facture · sessions Claude parallèles (`NOTE-SESSIONS-PARALLELES.md`).

## 7. Recommandation
Le produit est stable sur le staging : passer à la **recette métier** sur l'URL de staging avec vos données de test, répondre au registre (§5), puis demander l'import réel et la bascule. Je ne vois plus de défaut ouvert qui justifie une RC14 avant votre retour.
