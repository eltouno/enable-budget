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
  - (optionnel) ENABLE_ACCESS_JSON : JSON brut du champ `access` envoyé à `/auth`.
    - Par défaut, l'app envoie: `{ "valid_until": "<ISO>", "all_accounts": ["balances", "transactions"] }`
    - Si vous fournissez votre JSON et qu'il ne contient pas `valid_until`, il sera ajouté automatiquement avec la même valeur que le `valid_until` global.
  - (optionnel) WEB_SECRET_KEY : secret Flask persistant pour conserver la session côté client (sinon un secret aléatoire est utilisé à chaque démarrage).
  - (optionnel) WEB_SESSION_DAYS : durée de vie de la session (jours, défaut 14).
  - (optionnel) WEB_STATE_FILE : chemin du cache local (JSON) pour persister `session_id` et `accounts` (défaut `.enable_budget_web_state.json`).

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

## Web App (soldes, transactions, CSV)
- Démarrer le serveur:
  - `python enable_budget_web.py`
- Ouvrir `http://localhost:5001` (port par défaut 5001) ou ajustez avec `--port` ou `PORT`.
  - Pour définir l’URL de redirection par défaut, exportez `WEB_DEFAULT_REDIRECT_URL` (ex: `https://httpbin.org/anything`).
  - Renseigner `Nom de la banque (aspsp.name)`, `Pays` (ex: `BE`).
  - Vérifier que la `Redirect URL` affichée (`http://localhost:5001/callback`, ou celle définie par `WEB_DEFAULT_REDIRECT_URL`) est whitelistée dans votre Control Panel.
  - Vous serez redirigé vers la banque pour le consentement, puis de retour sur l'app.
  - La page `Comptes` s'affiche; cliquez sur "Voir soldes" ou "Voir transactions" pour un compte.
  - Transactions: indiquez au moins la date de début. Par défaut, l'export CSV exige un filtre et limite la plage à `WEB_TX_MAX_DAYS` (défaut 90 jours).

Notes:
- Certaines banques exigent un `redirect_url` en HTTPS. Si nécessaire, utilisez un tunnel (ex: ngrok) et whitelistez l'URL publique (ex: `https://xxxx.ngrok.app/callback`).
- La web-app stocke `session_id` et `accounts` dans la session Flask côté serveur. Configurez `WEB_SECRET_KEY` pour un secret persistant.
 - La web-app persiste aussi `session_id` et `accounts` dans un fichier local (`WEB_STATE_FILE`) pour survivre aux redémarrages. À la reprise, la session est réhydratée automatiquement.

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

### Redirect URL non autorisée (localhost refusé)
- Option A — Tunnel HTTPS (recommandé):
  - `ngrok http 5001` puis whitelistez `https://<id>.ngrok-free.app/callback` dans le Control Panel.
  - Lancez l’app et utilisez cette URL comme Redirect URL.
- Option B — httpbin + callback manuel:
  - Utilisez `https://httpbin.org/anything` comme Redirect URL (via le formulaire ou `WEB_DEFAULT_REDIRECT_URL`).
  - À la fin du parcours, httpbin affiche les paramètres de la requête; copiez `code`.
  - Ouvrez `http://localhost:5001/callback?code=<votre-code>` pour finaliser la session dans l’app.
- Limitation d'export CSV:
  - Par défaut, l’export requiert `date_from` et impose une plage maximale de 90 jours.
  - Pour modifier cette limite: `export WEB_TX_MAX_DAYS=30` (par exemple).
- Assurez-vous d'avoir effectué le parcours de consentement (`auth-url` puis `exchange-code`).
- Listez les comptes: `python enable_budget_cli.py list-accounts`
- Définissez un compte par défaut (facultatif): `python enable_budget_cli.py set-default-account --account-uid "<uid>"`
- Réessayer avec debug: ajouter `--debug` à la commande.
