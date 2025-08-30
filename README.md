# enable-budget (lecture seule)

Mini-CLI pour lire soldes et transactions via enable:Banking.

Une web-app minimaliste est également fournie pour démarrer le consentement, lister les comptes et afficher leurs soldes.

## Prérequis
- Python 3.10+
- Variables d'environnement:
  - ENABLE_APP_ID : 0472cd59-ae3d-4e53-8518-37afdbc149c3
  - ENABLE_PRIVATE_KEY_PATH : chemin complet vers votre fichier clé RSA privée au format PEM (ex: `/Users/xxxx/enable_private.pem`)
    - ou bien ENABLE_PRIVATE_KEY : contenu PEM directement (collez la clé, commencant par `-----BEGIN ...`)
  - (optionnel) ENABLE_API_BASE : défaut https://api.enablebanking.com
  - (optionnel) ENABLE_ACCESS_JSON : JSON brut du champ `access` envoyé à `/auth` (ex: `{ "all_accounts": ["balances", "transactions"] }`)

## Installation
python -m venv .venv
source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt  # inclut PyJWT[crypto] -> cryptography

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

## Web App (soldes en UI)
- Démarrer le serveur:
  - `python enable_budget_web.py`
- Ouvrir `http://localhost:5001` (port par défaut 5001) ou ajustez avec `--port` ou `PORT`.
  - Renseigner `Nom de la banque (aspsp.name)`, `Pays` (ex: `BE`).
  - Vérifier que la `Redirect URL` affichée (`http://localhost:5000/callback`) est whitelistée dans votre Control Panel.
  - Vous serez redirigé vers la banque pour le consentement, puis de retour sur l'app.
  - La page `Comptes` s'affiche; cliquez sur "Voir soldes" pour un compte.

Notes:
- Certaines banques exigent un `redirect_url` en HTTPS. Si nécessaire, utilisez un tunnel (ex: ngrok) et whitelistez l'URL publique (ex: `https://xxxx.ngrok.app/callback`).
- La web-app stocke `session_id` et `accounts` dans la session Flask côté serveur. Configurez `WEB_SECRET_KEY` pour un secret persistant.

## Dépannage rapide
- Erreur "No such file or directory ... .pem":
  - Corrigez `ENABLE_PRIVATE_KEY_PATH` vers le bon chemin absolu, ou utilisez `ENABLE_PRIVATE_KEY` avec le contenu PEM.
  - Evitez les guillemets résiduels dans la variable: `export ENABLE_PRIVATE_KEY_PATH=/Users/xxx/key.pem` (sans quotes), ou échappez correctement dans votre shell.
  - Le chemin `~` n'est pas toujours interprété par l'environnement: utilisez un chemin absolu ou laissez l’app l’expandre (support `~`, `$HOME`, `file://...`).
- Vérifiez les variables d'environnement: `ENABLE_APP_ID`, `ENABLE_PRIVATE_KEY_PATH`/`ENABLE_PRIVATE_KEY`, et l'accessibilité du fichier PEM.
- Erreur "Algorithm 'RS256' could not be found":
  - Installez le backend crypto pour PyJWT: `pip install 'PyJWT[crypto]'` (ou `pip install cryptography`).
  - Réinstallez les dépendances si besoin: `pip install -r requirements.txt`.
- Erreur 422 /auth (access/state requis):
  - L'API exige `state` et `access`.
  - Par défaut, l'app envoie `state` aléatoire et `access = {"all_accounts": ["balances", "transactions"]}`.
  - Si votre banque/compte exige un autre schéma, définissez `ENABLE_ACCESS_JSON` avec le JSON attendu.
- Assurez-vous d'avoir effectué le parcours de consentement (`auth-url` puis `exchange-code`).
- Listez les comptes: `python enable_budget_cli.py list-accounts`
- Définissez un compte par défaut (facultatif): `python enable_budget_cli.py set-default-account --account-uid "<uid>"`
- Réessayer avec debug: ajouter `--debug` à la commande.
