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
import csv
import io


APP_ID = os.environ.get("ENABLE_APP_ID")
PRIVATE_KEY_PATH = os.environ.get("ENABLE_PRIVATE_KEY_PATH")
PRIVATE_KEY_INLINE = os.environ.get("ENABLE_PRIVATE_KEY")  # contenu PEM direct (optionnel)
API_BASE = os.environ.get("ENABLE_API_BASE", "https://api.enablebanking.com").rstrip("/")
WEB_DEFAULT_REDIRECT_URL = os.environ.get("WEB_DEFAULT_REDIRECT_URL")  # ex: https://httpbin.org/anything
TX_MAX_DAYS = int(os.environ.get("WEB_TX_MAX_DAYS", "90"))
ACCESS_JSON = os.environ.get("ENABLE_ACCESS_JSON")  # optionnel: JSON brut pour le champ access
WEB_STATE_FILE = os.environ.get("WEB_STATE_FILE", ".enable_budget_web_state.json")
WEB_SESSION_DAYS = int(os.environ.get("WEB_SESSION_DAYS", "14"))


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


def _save_web_state(data: Dict[str, Any]) -> None:
    try:
        with open(WEB_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # best effort; ignorer en cas d'échec
        pass


def _load_web_state() -> Dict[str, Any]:
    if not os.path.exists(WEB_STATE_FILE):
        return {}
    try:
        with open(WEB_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@app.before_request
def _ensure_session_persistence() -> None:
    # Rendre la session persistante (cookie avec expiration)
    session.permanent = True
    # Réhydratation depuis le cache fichier si la session est vide (ex: redémarrage serveur)
    if not session.get("accounts") or not session.get("session_id"):
        st = _load_web_state()
        if not session.get("accounts") and st.get("accounts"):
            session["accounts"] = st.get("accounts")
        if not session.get("session_id") and st.get("session_id"):
            session["session_id"] = st.get("session_id")


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
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=WEB_SESSION_DAYS)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config.setdefault("SESSION_COOKIE_SECURE", False)


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
    session_id = data.get("session_id")
    accounts_list = data.get("accounts", [])
    session["session_id"] = session_id
    session["accounts"] = accounts_list
    # Persister localement pour survivre aux redémarrages du serveur
    _save_web_state({
        "session_id": session_id,
        "accounts": accounts_list,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
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


def _collect_transactions(uid: str, *, date_from: Optional[str] = None, date_to: Optional[str] = None, max_pages: int = 20) -> Dict[str, Any]:
    # Si aucune date fournie, ne supposez rien ici; laissez les routes décider
    if not date_from:
        raise RuntimeError("Veuillez indiquer une date de début (date_from)")

    path = f"/accounts/{uid}/transactions"
    params: Dict[str, Any] = {"date_from": date_from}
    if date_to:
        params["date_to"] = date_to

    all_tx = []
    pages = 0
    while True:
        resp = _request("GET", path, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Echec {path} ({resp.status_code}): {resp.text}")
        page = resp.json()
        items = page.get("transactions") or page.get("items") or []
        all_tx.extend(items)
        cont = page.get("continuation_key")
        pages += 1
        if cont and pages < max_pages:
            params = {"continuation_key": cont}
        else:
            break
    return {"transactions": all_tx, "count": len(all_tx), "date_from": date_from, "date_to": date_to}


def _flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            if isinstance(v, (dict, list)):
                # pour les listes, garder JSON compact; pour les dicts, aplatir récursivement
                if isinstance(v, dict):
                    out.update(_flatten(v, key))
                else:
                    out[key] = json.dumps(v, ensure_ascii=False)
            else:
                out[key] = v
    else:
        out[prefix or "value"] = obj
    return out


def _transactions_to_csv(transactions: Any) -> str:
    # Aplatit tous les objets et crée des colonnes union
    rows = [_flatten(t) for t in (transactions or [])]
    # En-têtes: union triée pour stabilité
    headers = sorted({k for r in rows for k in r.keys()})
    sio = io.StringIO()
    writer = csv.DictWriter(sio, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in headers})
    return sio.getvalue()


@app.get("/transactions/<uid>")
def transactions(uid: str):
    if not uid:
        flash("UID manquant.", "error")
        return redirect(url_for("accounts"))

    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    err = None
    result: Dict[str, Any] = {"transactions": [], "count": 0, "date_from": date_from, "date_to": date_to}

    # Afficher la page sans requête si aucun filtre saisi
    if not date_from:
        return render_template("transactions.html", uid=uid, result=result, error=None, max_days=TX_MAX_DAYS)

    # Valider le format et la plage
    try:
        df = datetime.strptime(date_from, "%Y-%m-%d").date()
        dt = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else datetime.now(timezone.utc).date()
        if df > dt:
            raise ValueError("La date de début est après la date de fin")
        if (dt - df).days > TX_MAX_DAYS:
            raise ValueError(f"Plage trop large: max {TX_MAX_DAYS} jours")
        # OK, charger les transactions
        result = _collect_transactions(uid, date_from=date_from, date_to=dt.isoformat())
    except Exception as e:
        err = str(e)
    return render_template("transactions.html", uid=uid, result=result, error=err, max_days=TX_MAX_DAYS)


@app.get("/transactions/<uid>/csv")
def transactions_csv(uid: str):
    if not uid:
        flash("UID manquant.", "error")
        return redirect(url_for("accounts"))
    date_from = (request.args.get("date_from") or "").strip() or None
    date_to = (request.args.get("date_to") or "").strip() or None
    # Exiger un filtre de date pour limiter l'export
    if not date_from:
        flash("Veuillez préciser au moins 'date_from' pour exporter en CSV.", "error")
        return redirect(url_for("transactions", uid=uid))
    # Appliquer la limite de plage
    try:
        df = datetime.strptime(date_from, "%Y-%m-%d").date()
        dt = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else datetime.now(timezone.utc).date()
        if df > dt:
            raise ValueError("La date de début est après la date de fin")
        if (dt - df).days > TX_MAX_DAYS:
            raise ValueError(f"Plage trop large pour l'export: max {TX_MAX_DAYS} jours")
        result = _collect_transactions(uid, date_from=df.isoformat(), date_to=dt.isoformat())
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for("transactions", uid=uid, date_from=(date_from or ""), date_to=(date_to or "")))

    csv_text = _transactions_to_csv(result.get("transactions") or [])
    filename = f"transactions_{uid}_{result.get('date_from') or ''}_{result.get('date_to') or ''}.csv".replace("/", "-")
    return app.response_class(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\""
        },
    )


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
