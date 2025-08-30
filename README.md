# enable-budget (lecture seule)

Mini-CLI pour lire soldes et transactions via enable:Banking.

## Prérequis
- Python 3.10+
- Variables d'environnement:
  - ENABLE_APP_ID : 0472cd59-ae3d-4e53-8518-37afdbc149c3
  - ENABLE_PRIVATE_KEY_PATH : chemin complet vers votre fichier clé RSA privée au format PEM (ex: /Users/antoinedelfosse/Documents/enable_private.pem)
  - (optionnel) ENABLE_API_BASE : défaut https://api.enablebanking.com

## Installation
python -m venv .venv
source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt

## Utilisation rapide
# 1) Générer l'URL de consentement (ouvrir dans un navigateur)
python enable_budget_cli.py auth-url --bank-name "..." --country "BE" --redirect-url "https://httpbin.org/anything"

# 2) À la fin du parcours, copiez le paramètre ?code=... depuis l'URL de retour
python enable_budget_cli.py exchange-code --code "<uuid-du-code>"

# 3) Lister les comptes mémorisés localement
python enable_budget_cli.py list-accounts

# 4) Soldes
python enable_budget_cli.py balances --account-uid "<uid>"

# 5) Transactions (avec pagination automatique)
python enable_budget_cli.py transactions --account-uid "<uid>" --date-from 2025-01-01

## Astuces
- Vous pouvez surcharger l'URL de l'API par `--api-base https://...` si vous utilisez un autre endpoint que celui par défaut.
- Le script ajoute automatiquement l'en-tête `X-EnableBanking-Session` s'il trouve un `session_id` dans `.enable_budget_local.json`.
- `--debug` affiche des informations détaillées (URL, statut HTTP) pour diagnostiquer.
- Si vous n'indiquez pas `--account-uid`, le script utilisera le compte par défaut (définissable via `set-default-account`) ou, à défaut, le seul compte présent en cache.

## Dépannage rapide
- Vérifiez les variables d'environnement: `ENABLE_APP_ID`, `ENABLE_PRIVATE_KEY_PATH`, et l'accessibilité du fichier PEM.
- Assurez-vous d'avoir effectué le parcours de consentement (`auth-url` puis `exchange-code`).
- Listez les comptes: `python enable_budget_cli.py list-accounts`
- Définissez un compte par défaut (facultatif): `python enable_budget_cli.py set-default-account --account-uid "<uid>"`
- Réessayer avec debug: ajouter `--debug` à la commande.
