#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from flask import Flask, redirect, render_template, request, session, url_for, flash
import requests
import jwt
from urllib.parse import urlparse
import argparse
import secrets


APP_ID = os.environ.get("ENABLE_APP_ID")
PRIVATE_KEY_PATH = os.environ.get("ENABLE_PRIVATE_KEY_PATH")
PRIVATE_KEY_INLINE = os.environ.get("ENABLE_PRIVATE_KEY")  # contenu PEM direct (optionnel)
API_BASE = os.environ.get("ENABLE_API_BASE", "https://api.enablebanking.com").rstrip("/")
WEB_DEFAULT_REDIRECT_URL = os.environ.get("WEB_DEFAULT_REDIRECT_URL")  # ex: https://httpbin.org/anything
ACCESS_JSON = os.environ.get("ENABLE_ACCESS_JSON")  # optionnel: JSON brut pour le champ access


def _audience_from_api_base() -> str:
    try:
        host = urlparse(API_BASE).netloc or API_BASE
        return host
    except Exception:
        return "api.enablebanking.com"


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
        raise RuntimeError("Clé privée manquante: définissez ENABLE_PRIVATE_KEY (contenu PEM) ou ENABLE_PRIVATE_KEY_PATH (chemin fichier)")
    normalized = _normalize_path(PRIVATE_KEY_PATH)
    if not os.path.exists(normalized):
        raise RuntimeError(f"Fichier PEM introuvable: {normalized} (depuis ENABLE_PRIVATE_KEY_PATH='{PRIVATE_KEY_PATH}')")
    try:
        with open(normalized, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise RuntimeError(f"Impossible de lire la clé privée .pem: {e}")


def _get_access(valid_until_iso: str) -> Dict[str, Any]:
    # Permettre la configuration via JSON brut
    if ACCESS_JSON:
        try:
            obj = json.loads(ACCESS_JSON)
            if isinstance(obj, dict) and "valid_until" not in obj:
                obj["valid_until"] = valid_until_iso
            return obj
        except Exception as e:
            raise RuntimeError(f"ENABLE_ACCESS_JSON invalide: {e}")
    # Valeur par défaut raisonnable: accès balances et transactions pour tous les comptes
    # et validité côté access (certaines banques l'exigent)
    return {
        "valid_until": valid_until_iso,
        "all_accounts": ["balances", "transactions"],
    }


def _build_jwt() -> str:
    if not APP_ID:
        raise RuntimeError("Variable d'env ENABLE_APP_ID manquante")
    private_key = _load_private_key()
    now = int(time.time())
    payload = {
        "iss": "enablebanking.com",
        "aud": _audience_from_api_base(),
        "iat": now,
        "exp": now + 300,
    }
    headers = {"kid": APP_ID}
    try:
        token = jwt.encode(payload, private_key, algorithm="RS256", headers=headers)
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token
    except Exception as e:
        msg = str(e)
        if "Algorithm 'RS256' could not be found" in msg or "Do you have cryptography installed" in msg:
            raise RuntimeError("RS256 indisponible. Installez le support crypto: pip install 'PyJWT[crypto]' ou pip install cryptography")
        raise


def _headers(*, include_session: bool = True) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {_build_jwt()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if include_session:
        sid = session.get("session_id")
        if sid:
            headers["X-EnableBanking-Session"] = sid
    return headers


def _request(method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    url = f"{API_BASE}{path}"
    return requests.request(method=method.upper(), url=url, headers=_headers(), json=json_body, params=params, timeout=30)


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("WEB_SECRET_KEY", os.urandom(24))


@app.route("/")
def index():
    # Suggérer une redirect URL basée sur l'hôte courant
    callback_url = WEB_DEFAULT_REDIRECT_URL or url_for("callback", _external=True)
    return render_template("index.html", callback_url=callback_url)


@app.post("/start")
def start_consent():
    bank_name = request.form.get("bank_name", "").strip()
    country = request.form.get("country", "BE").strip() or "BE"
    default_redirect = WEB_DEFAULT_REDIRECT_URL or url_for("callback", _external=True)
    redirect_url = request.form.get("redirect_url", default_redirect).strip()

    if not bank_name:
        flash("Veuillez saisir le nom de la banque (aspsp.name).", "error")
        return redirect(url_for("index"))

    valid_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="seconds")
    # Génère un état aléatoire pour sécuriser le parcours OAuth-like
    oauth_state = secrets.token_urlsafe(16)
    session["oauth_state"] = oauth_state
    body = {
        "aspsp": {"name": bank_name, "country": country},
        "redirect_url": redirect_url,
        "valid_until": valid_until,
        "state": oauth_state,
        "access": _get_access(valid_until),
    }
    try:
        resp = _request("POST", "/auth", json_body=body)
    except Exception as e:
        flash(f"Erreur locale: {e}", "error")
        return redirect(url_for("index"))

    if resp.status_code != 200:
        msg = resp.text
        if resp.status_code == 422:
            msg = f"422 Unprocessable Entity. Vérifiez bank/country, redirect whitelistée, valid_until.\n{resp.text}"
        flash(f"Echec /auth ({resp.status_code}): {msg}", "error")
        return redirect(url_for("index"))

    data = resp.json()
    url = data.get("url")
    if not url:
        flash("Réponse /auth sans 'url'", "error")
        return redirect(url_for("index"))
    return redirect(url)


@app.get("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")
    if not code:
        flash("Paramètre 'code' manquant dans l'URL de retour.", "error")
        return redirect(url_for("index"))
    # Vérifier l'intégrité du parcours via 'state'
    expected_state = session.get("oauth_state")
    if expected_state and state and state != expected_state:
        flash("State de retour invalide. Relancez le parcours.", "error")
        return redirect(url_for("index"))

    resp = _request("POST", "/sessions", json_body={"code": code})
    if resp.status_code != 200:
        flash(f"Echec /sessions ({resp.status_code}): {resp.text}", "error")
        return redirect(url_for("index"))

    data = resp.json()
    session["session_id"] = data.get("session_id")
    session["accounts"] = data.get("accounts", [])
    flash("Consentement validé et comptes chargés.", "success")
    return redirect(url_for("accounts"))


@app.get("/accounts")
def accounts():
    accounts = session.get("accounts") or []
    if not accounts:
        flash("Aucun compte en session. Démarrez par la page d'accueil.", "error")
        return redirect(url_for("index"))
    return render_template("accounts.html", accounts=accounts)


@app.get("/balances/<uid>")
def balances(uid: str):
    if not uid:
        flash("UID manquant.", "error")
        return redirect(url_for("accounts"))

    path = f"/accounts/{uid}/balances"
    resp = _request("GET", path)
    if resp.status_code != 200:
        flash(f"Echec {path} ({resp.status_code}): {resp.text}", "error")
        return redirect(url_for("accounts"))
    data = resp.json()
    return render_template("balances.html", uid=uid, balances=data)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="enable-budget Web App")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5001")), help="Port HTTP (défaut: 5001)")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"), help="Hôte d'écoute (défaut: 0.0.0.0)")
    parser.add_argument("--debug", action="store_true", default=os.environ.get("FLASK_DEBUG") == "1", help="Active le mode debug Flask")
    parser.add_argument("--api-base", help="Override de l'API base URL (ex: https://api.enablebanking.com)")
    return parser.parse_args()


def main() -> None:
    global API_BASE
    args = _parse_args()
    if args.api_base:
        API_BASE = str(args.api_base).rstrip("/")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
