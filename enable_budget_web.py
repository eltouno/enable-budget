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


APP_ID = os.environ.get("ENABLE_APP_ID")
PRIVATE_KEY_PATH = os.environ.get("ENABLE_PRIVATE_KEY_PATH")
API_BASE = os.environ.get("ENABLE_API_BASE", "https://api.enablebanking.com").rstrip("/")


def _audience_from_api_base() -> str:
    try:
        host = urlparse(API_BASE).netloc or API_BASE
        return host
    except Exception:
        return "api.enablebanking.com"


def _load_private_key() -> str:
    if not PRIVATE_KEY_PATH:
        raise RuntimeError("Variable d'env ENABLE_PRIVATE_KEY_PATH manquante")
    with open(PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
        return f.read()


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
    token = jwt.encode(payload, private_key, algorithm="RS256", headers=headers)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


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
    callback_url = url_for("callback", _external=True)
    return render_template("index.html", callback_url=callback_url)


@app.post("/start")
def start_consent():
    bank_name = request.form.get("bank_name", "").strip()
    country = request.form.get("country", "BE").strip() or "BE"
    redirect_url = request.form.get("redirect_url", url_for("callback", _external=True)).strip()

    if not bank_name:
        flash("Veuillez saisir le nom de la banque (aspsp.name).", "error")
        return redirect(url_for("index"))

    valid_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="seconds")
    body = {
        "aspsp": {"name": bank_name, "country": country},
        "redirect_url": redirect_url,
        "valid_until": valid_until,
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
    if not code:
        flash("Paramètre 'code' manquant dans l'URL de retour.", "error")
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
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")), help="Port HTTP (défaut: 5000)")
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
