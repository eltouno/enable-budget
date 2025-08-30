#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
enable-budget CLI (lecture seule)
- JWT RS256 (headers.kid = ENABLE_APP_ID)
- /auth -> URL d'autorisation banque
- /sessions (échange code)
- /accounts/{uid}/balances
- /accounts/{uid}/transactions?date_from=YYYY-MM-DD (+ pagination continuation_key)

Sécurité / bonnes pratiques:
- Ne JAMAIS committer la clé .pem
- Utiliser les variables d'env: ENABLE_APP_ID, ENABLE_PRIVATE_KEY_PATH
- valid_until ISO8601 avec fuseau (+00:00)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
import requests

# ----------------------------
# Config & utilitaires
# ----------------------------

APP_ID = os.environ.get("ENABLE_APP_ID")  # <Application ID> (UUID) -> kid
PRIVATE_KEY_PATH = os.environ.get("ENABLE_PRIVATE_KEY_PATH")  # chemin vers .pem (fichier)
PRIVATE_KEY_INLINE = os.environ.get("ENABLE_PRIVATE_KEY")  # contenu PEM direct (optionnel)
API_BASE = os.environ.get("ENABLE_API_BASE", "https://api.enablebanking.com").rstrip("/")

LOCAL_STATE = ".enable_budget_local.json"  # stocke accounts après /sessions
DEBUG = os.environ.get("ENABLE_DEBUG", "").lower() in {"1", "true", "yes"}


def _die(msg: str, code: int = 1) -> None:
    print(f"Erreur: {msg}", file=sys.stderr)
    sys.exit(code)


def _normalize_path(p: str) -> str:
    p = (p or "").strip().strip('"').strip("'")
    if p.startswith("file://"):
        p = p[len("file://"):]
    p = os.path.expanduser(os.path.expandvars(p))
    return p


def _load_private_key() -> str:
    # 1) Autoriser le contenu PEM directement via ENABLE_PRIVATE_KEY
    if PRIVATE_KEY_INLINE:
        return PRIVATE_KEY_INLINE
    # 2) Sinon lire depuis le chemin de fichier ENABLE_PRIVATE_KEY_PATH
    if not PRIVATE_KEY_PATH:
        _die("Clé privée manquante: définissez ENABLE_PRIVATE_KEY (contenu PEM) ou ENABLE_PRIVATE_KEY_PATH (chemin fichier).")
    normalized = _normalize_path(PRIVATE_KEY_PATH)
    if not os.path.exists(normalized):
        _die(f"Fichier PEM introuvable: {normalized} (depuis ENABLE_PRIVATE_KEY_PATH='{PRIVATE_KEY_PATH}')")
    try:
        with open(normalized, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        _die(f"Impossible de lire la clé privée .pem: {e}")
    return ""  # unreachable


def _log(msg: str) -> None:
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def _audience_from_api_base() -> str:
    """Retourne l'"aud" dérivé de API_BASE (host)."""
    try:
        from urllib.parse import urlparse
        host = urlparse(API_BASE).netloc or API_BASE
        # Par compat: si l'env contient déjà un host sans schéma
        return host
    except Exception:
        return "api.enablebanking.com"


def _build_jwt() -> str:
    """Construit un JWT signé RS256"""
    if not APP_ID:
        _die("Variable d'env ENABLE_APP_ID manquante.")

    private_key = _load_private_key()
    now = int(time.time())
    payload = {
        "iss": "enablebanking.com",
        "aud": _audience_from_api_base(),
        "iat": now,
        "exp": now + 300,  # 5 minutes
    }
    headers = {
        "kid": APP_ID
    }
    try:
        token = jwt.encode(payload, private_key, algorithm="RS256", headers=headers)
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token
    except Exception as e:
        _die(f"Echec de signature JWT: {e}")
    return ""  # unreachable


def _headers() -> Dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_build_jwt()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    # Joindre la session si disponible (certaines routes peuvent l'exiger)
    try:
        state = _load_local_state()
        session_id = state.get("session_id")
        if session_id:
            headers["X-EnableBanking-Session"] = session_id
    except Exception:
        pass
    _log(f"Using API_BASE={API_BASE} aud={_audience_from_api_base()} headers={{'Accept','Content-Type','Authorization','X-EnableBanking-Session' in headers}}")
    return headers


def _request(method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    url = f"{API_BASE}{path}"
    try:
        _log(f"HTTP {method.upper()} {url} params={params} body={(json_body if json_body else None)}")
        resp = requests.request(method=method.upper(), url=url, headers=_headers(), json=json_body, params=params, timeout=30)
        _log(f"-> {resp.status_code} {resp.reason}; len={len(resp.text or '')}")
        return resp
    except requests.RequestException as e:
        _die(f"Requête réseau échouée ({method} {url}): {e}")
    return None  # type: ignore


def _save_local_state(data: Dict[str, Any]) -> None:
    try:
        with open(LOCAL_STATE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _die(f"Impossible d'écrire {LOCAL_STATE}: {e}")


def _load_local_state() -> Dict[str, Any]:
    if not os.path.exists(LOCAL_STATE):
        return {}
    try:
        with open(LOCAL_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _die(f"Impossible de lire {LOCAL_STATE}: {e}")
    return {}  # unreachable


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _explain_422() -> None:
    print(
        "\n[Astuce 422]\n"
        "- Vérifiez `valid_until` (ISO 8601 avec fuseau, p.ex. +00:00)\n"
        "- Vérifiez `aspsp.name` et `aspsp.country`\n"
        "- Vérifiez que `redirect_url` est bien whitelistée dans le Control Panel\n",
        file=sys.stderr
    )


# ----------------------------
# Commandes CLI
# ----------------------------

def cmd_auth_url(args: argparse.Namespace) -> None:
    """
    POST /auth -> { url: "<banque>" }
    """
    valid_for = timedelta(minutes=args.valid_minutes)
    valid_until = (datetime.now(timezone.utc) + valid_for).isoformat(timespec="seconds")

    body = {
        "aspsp": {
            "name": args.bank_name,
            "country": args.country
        },
        "redirect_url": args.redirect_url,
        "valid_until": valid_until
        # Ajoutez d'autres champs si votre usage le nécessite (psu_type, etc.)
    }

    resp = _request("POST", "/auth", json_body=body)
    if resp.status_code == 200:
        data = resp.json()
        url = data.get("url")
        if not url:
            _die("Réponse /auth sans `url`.")
        print("\nOuvrez ce lien dans un navigateur pour donner le consentement :\n")
        print(url)
        print("\nUne fois terminé, récupérez le paramètre ?code=... de l'URL de retour.\n")
    elif resp.status_code == 422:
        print(f"Réponse 422 /auth:\n{resp.text}", file=sys.stderr)
        _explain_422()
        sys.exit(1)
    else:
        _die(f"Echec /auth ({resp.status_code}): {resp.text}")


def cmd_exchange_code(args: argparse.Namespace) -> None:
    """
    POST /sessions { code } -> session_id + accounts[]
    """
    body = {"code": args.code}
    resp = _request("POST", "/sessions", json_body=body)
    if resp.status_code != 200:
        _die(f"Echec /sessions ({resp.status_code}): {resp.text}")

    data = resp.json()
    session_id = data.get("session_id")
    accounts = data.get("accounts", [])

    # On mémorise localement pour éviter de ressaisir
    state = _load_local_state()
    state.update({
        "session_id": session_id,
        "accounts": accounts,
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    _save_local_state(state)

    print("\nSession créée. Comptes disponibles (extrait):\n")
    for idx, acc in enumerate(accounts, start=1):
        uid = acc.get("uid")
        name = acc.get("name") or acc.get("nickname") or acc.get("product") or "-"
        iban = acc.get("iban") or acc.get("masked_pan") or "-"
        print(f"{idx:02d}. uid={uid} | name={name} | iban/pan={iban}")

    print("\nAstuce: utilisez --account-uid <uid> pour balances/transactions.\n")


def cmd_list_accounts(_: argparse.Namespace) -> None:
    """
    Affiche les comptes mémorisés depuis /sessions
    """
    state = _load_local_state()
    accounts = state.get("accounts") or []
    if not accounts:
        _die("Aucun compte mémorisé. Exécutez d'abord: exchange-code --code ...")

    print("\nComptes mémorisés:\n")
    for idx, acc in enumerate(accounts, start=1):
        uid = acc.get("uid")
        name = acc.get("name") or acc.get("nickname") or acc.get("product") or "-"
        iban = acc.get("iban") or acc.get("masked_pan") or "-"
        currency = acc.get("currency") or "-"
        print(f"{idx:02d}. uid={uid} | {name} | {iban} | {currency}")

    # Indiquer le défaut si présent
    default_uid = _get_default_account_uid(allow_single=False)
    if default_uid:
        print(f"\nCompte par défaut: {default_uid}")


def _get_default_account_uid(allow_single: bool = True) -> Optional[str]:
    state = _load_local_state()
    accounts = state.get("accounts") or []
    default_uid = state.get("default_account_uid")
    if default_uid and any(acc.get("uid") == default_uid for acc in accounts):
        return default_uid
    if allow_single and len(accounts) == 1:
        return accounts[0].get("uid")
    return None


def cmd_set_default_account(args: argparse.Namespace) -> None:
    uid = args.account_uid
    if not uid:
        _die("--account-uid est requis")
    state = _load_local_state()
    accounts = state.get("accounts") or []
    if not accounts:
        _die("Aucun compte en cache. Exécutez d'abord: exchange-code --code ...")
    if not any(acc.get("uid") == uid for acc in accounts):
        _die("UID inconnu. Utilisez list-accounts pour vérifier.")
    state["default_account_uid"] = uid
    _save_local_state(state)
    print(f"Compte par défaut défini: {uid}")


def cmd_balances(args: argparse.Namespace) -> None:
    """
    GET /accounts/{uid}/balances
    """
    uid = args.account_uid or _get_default_account_uid()
    if not uid:
        _die("Aucun UID fourni. Fournissez --account-uid ou définissez un compte par défaut (set-default-account), ou assurez-vous qu'un seul compte est en cache.")

    path = f"/accounts/{uid}/balances"
    resp = _request("GET", path)
    if resp.status_code != 200:
        _die(f"Echec {path} ({resp.status_code}): {resp.text}")

    data = resp.json()
    print("\nBalances:\n")
    _print_json(data)


def cmd_transactions(args: argparse.Namespace) -> None:
    """
    GET /accounts/{uid}/transactions?date_from=YYYY-MM-DD (+ continuation_key)
    """
    uid = args.account_uid or _get_default_account_uid()
    if not uid:
        _die("Aucun UID fourni. Fournissez --account-uid ou définissez un compte par défaut (set-default-account), ou assurez-vous qu'un seul compte est en cache.")
    if not args.date_from:
        _die("--date-from est requis (format YYYY-MM-DD)")
    # Validation stricte du format de date
    try:
        datetime.strptime(args.date_from, "%Y-%m-%d")
    except ValueError:
        _die("--date-from doit être au format YYYY-MM-DD")

    path = f"/accounts/{uid}/transactions"
    params = {"date_from": args.date_from}
    all_tx = []

    while True:
        resp = _request("GET", path, params=params)
        if resp.status_code != 200:
            _die(f"Echec {path} ({resp.status_code}): {resp.text}")

        page = resp.json()
        items = page.get("transactions") or page.get("items") or []
        all_tx.extend(items)

        continuation_key = page.get("continuation_key")
        if continuation_key:
            params = {"continuation_key": continuation_key}
        else:
            break

    print(f"\nTransactions depuis {args.date_from} (total: {len(all_tx)}):\n")
    _print_json(all_tx)


# ----------------------------
# Entrée CLI
# ----------------------------
def cmd_check_setup(_: argparse.Namespace) -> None:
    """Validation locale: variables d'env, clé privée PEM, JWT généré."""
    info: Dict[str, Any] = {}

    # Python / Env
    info["python_version"] = sys.version.split()[0]
    info["api_base"] = API_BASE
    info["audience"] = _audience_from_api_base()
    info["enable_app_id_present"] = bool(APP_ID)
    info["enable_app_id_preview"] = (APP_ID[:8] + "...") if APP_ID else None
    info["private_key_path_present"] = bool(PRIVATE_KEY_PATH)

    # Clé privée
    key_stat: Dict[str, Any] = {}
    if PRIVATE_KEY_PATH:
        try:
            with open(PRIVATE_KEY_PATH, "rb") as f:
                content = f.read()
            key_stat["readable"] = True
            key_stat["bytes"] = len(content)
            head = content[:64]
            # Détection grossière du type de PEM
            text_head = head.decode("utf-8", errors="ignore")
            if "BEGIN RSA PRIVATE KEY" in text_head:
                key_stat["pem_type"] = "RSA PRIVATE KEY"
            elif "BEGIN PRIVATE KEY" in text_head:
                key_stat["pem_type"] = "PRIVATE KEY (PKCS#8)"
            else:
                key_stat["pem_type"] = "unknown"
        except Exception as e:
            key_stat["readable"] = False
            key_stat["error"] = str(e)
    info["private_key_status"] = key_stat

    # JWT
    try:
        token = _build_jwt()
        # En-têtes non signés
        header = jwt.get_unverified_header(token)
        # Claims sans vérification (pas de secret ici)
        claims = jwt.decode(token, options={"verify_signature": False})
        # Durée de validité
        now = int(time.time())
        exp = int(claims.get("exp", now))
        info["jwt"] = {
            "header": header,
            "claims": claims,
            "seconds_until_expiry": max(0, exp - now),
        }
    except Exception as e:
        info["jwt_error"] = str(e)

    _print_json(info)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="enable-budget CLI (lecture seule: soldes & transactions)"
    )
    parser.add_argument("--api-base", help="Override de l'API base URL (ex: https://api.enablebanking.com)")
    parser.add_argument("--debug", action="store_true", help="Active le mode debug (logs HTTP et contexte)")
    sub = parser.add_subparsers(dest="command")

    # auth-url
    p_auth = sub.add_parser("auth-url", help="Démarrer un consentement et obtenir l'URL bancaire")
    p_auth.add_argument("--bank-name", required=True, help="Nom banque (aspsp.name)")
    p_auth.add_argument("--country", required=True, help="Pays (aspsp.country), ex: BE")
    p_auth.add_argument("--redirect-url", required=True, help="URL whitelistée (https ou schéma custom). En test: https://httpbin.org/anything")
    p_auth.add_argument("--valid-minutes", type=int, default=15, help="Durée de validité du consentement (minutes)")
    p_auth.set_defaults(func=cmd_auth_url)

    # exchange-code
    p_ex = sub.add_parser("exchange-code", help="Échanger le code d'autorisation contre une session et lister les comptes")
    p_ex.add_argument("--code", required=True, help="Code d'autorisation (UUID)")
    p_ex.set_defaults(func=cmd_exchange_code)

    # list-accounts
    p_la = sub.add_parser("list-accounts", help="Lister les comptes mémorisés (depuis /sessions)")
    p_la.set_defaults(func=cmd_list_accounts)

    # balances
    p_bal = sub.add_parser("balances", help="Lire les soldes d'un compte")
    p_bal.add_argument("--account-uid", help="UID du compte (optionnel si compte par défaut ou unique)")
    p_bal.set_defaults(func=cmd_balances)

    # transactions
    p_tx = sub.add_parser("transactions", help="Lire les transactions d'un compte (pagination auto)")
    p_tx.add_argument("--account-uid", help="UID du compte (optionnel si compte par défaut ou unique)")
    p_tx.add_argument("--date-from", required=True, help="YYYY-MM-DD")
    p_tx.set_defaults(func=cmd_transactions)

    # set-default-account
    p_def = sub.add_parser("set-default-account", help="Définir le compte par défaut (utilisé si --account-uid absent)")
    p_def.add_argument("--account-uid", required=True, help="UID du compte à définir par défaut")
    p_def.set_defaults(func=cmd_set_default_account)

    # check-setup
    p_chk = sub.add_parser("check-setup", help="Vérifie la configuration locale (clé PEM, JWT, audience)")
    p_chk.set_defaults(func=cmd_check_setup)

    args = parser.parse_args()
    # Permet de surcharger API_BASE depuis la CLI
    if getattr(args, "api_base", None):
        global API_BASE
        API_BASE = str(args.api_base).rstrip("/")
    # Debug flag
    if getattr(args, "debug", False):
        global DEBUG
        DEBUG = True
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Exécution
    args.func(args)


if __name__ == "__main__":
    main()
