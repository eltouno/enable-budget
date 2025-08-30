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
PRIVATE_KEY_PATH = os.environ.get("ENABLE_PRIVATE_KEY_PATH")  # chemin vers .pem
API_BASE = os.environ.get("ENABLE_API_BASE", "https://api.enablebanking.com").rstrip("/")

LOCAL_STATE = ".enable_budget_local.json"  # stocke accounts après /sessions


def _die(msg: str, code: int = 1) -> None:
    print(f"Erreur: {msg}", file=sys.stderr)
    sys.exit(code)


def _load_private_key() -> str:
    if not PRIVATE_KEY_PATH:
        _die("Variable d'env ENABLE_PRIVATE_KEY_PATH manquante.")
    try:
        with open(PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        _die(f"Impossible de lire la clé privée .pem: {e}")
    return ""  # unreachable


def _build_jwt() -> str:
    """Construit un JWT signé RS256"""
    if not APP_ID:
        _die("Variable d'env ENABLE_APP_ID manquante.")

    private_key = _load_private_key()
    now = int(time.time())
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
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
    return {
        "Authorization": f"Bearer {_build_jwt()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    url = f"{API_BASE}{path}"
    try:
        resp = requests.request(method=method.upper(), url=url, headers=_headers(), json=json_body, params=params, timeout=30)
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


def cmd_balances(args: argparse.Namespace) -> None:
    """
    GET /accounts/{uid}/balances
    """
    if not args.account_uid:
        _die("--account-uid est requis")

    path = f"/accounts/{args.account_uid}/balances"
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
    if not args.account_uid:
        _die("--account-uid est requis")
    if not args.date_from:
        _die("--date-from est requis (format YYYY-MM-DD)")

    path = f"/accounts/{args.account_uid}/transactions"
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

def main() -> None:
    parser = argparse.ArgumentParser(
        description="enable-budget CLI (lecture seule: soldes & transactions)"
    )
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
    p_bal.add_argument("--account-uid", required=True, help="UID du compte")
    p_bal.set_defaults(func=cmd_balances)

    # transactions
    p_tx = sub.add_parser("transactions", help="Lire les transactions d'un compte (pagination auto)")
    p_tx.add_argument("--account-uid", required=True, help="UID du compte")
    p_tx.add_argument("--date-from", required=True, help="YYYY-MM-DD")
    p_tx.set_defaults(func=cmd_transactions)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Exécution
    args.func(args)


if __name__ == "__main__":
    main()
