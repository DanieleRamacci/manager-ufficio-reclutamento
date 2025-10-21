# auth.py
from flask import Blueprint, request, session, redirect, url_for, jsonify
from urllib.parse import urlencode, urlparse
from functools import wraps
import os, time, json, requests, jwt
from dotenv import load_dotenv

auth_bp = Blueprint("auth", __name__)

# ========== Config ==========
load_dotenv()

OIDC_CLIENT_ID     = os.getenv("OIDC_CLIENT_ID")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET")
OIDC_REDIRECT_URI  = os.getenv("OIDC_REDIRECT_URI")   # es: http://localhost:8081/oidc-callback
OIDC_AUTH_URL      = os.getenv("OIDC_AUTH_URL")
OIDC_TOKEN_URL     = os.getenv("OIDC_TOKEN_URL")
OIDC_USERINFO_URL  = os.getenv("OIDC_USERINFO_URL")

# opzionale: limita i redirect post-login all’host corrente
ALLOW_EXTERNAL_REDIRECTS = os.getenv("ALLOW_EXTERNAL_REDIRECTS", "0") == "1"

REQUIRED_VARS = [
    "OIDC_CLIENT_ID","OIDC_CLIENT_SECRET","OIDC_REDIRECT_URI",
    "OIDC_AUTH_URL","OIDC_TOKEN_URL"
]
missing = [v for v in REQUIRED_VARS if not globals().get(v)]
if missing:
    raise RuntimeError(f"Variabili OIDC mancanti: {', '.join(missing)}")


# ========== Helpers ==========
def _same_host(url1: str, url2: str) -> bool:
    """Permette redirect solo allo stesso host (anti open redirect)."""
    try:
        a, b = urlparse(url1), urlparse(url2)
        return (a.scheme, a.netloc) == (b.scheme, b.netloc)
    except Exception:
        return False

def _safe_next(default_url: str) -> str:
    """Restituisce la URL di redirect 'safe' dopo il login."""
    nxt = request.args.get("next") or request.args.get("state") or default_url
    if ALLOW_EXTERNAL_REDIRECTS:
        return nxt
    # consenti solo stesso host
    current_origin = request.host_url.rstrip("/")
    return nxt if _same_host(current_origin, nxt) else default_url


# ========== Decoratore ==========
def login_required(fn):
    @wraps(fn)
    def _wrapped(*args, **kwargs):
        if "access_token" not in session:
            nxt = request.url
            return redirect(url_for("auth.login", next=nxt))
        return fn(*args, **kwargs)
    return _wrapped


# ========== Routes Auth ==========
@auth_bp.route("/login")
def login():
    """Avvia il flusso OIDC."""
    # default: homepage dell’app (view 'root' definita in avvia_tool)
    default_after = url_for("root", _external=True)
    next_url = request.args.get("next") or default_after

    params = {
        "client_id": OIDC_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": OIDC_REDIRECT_URI,
        "state": next_url,  # la useremo come destinazione post-login
    }
    return redirect(f"{OIDC_AUTH_URL}?{urlencode(params)}")


@auth_bp.route("/oidc-callback")
def oidc_callback():
    """Gestisce il ritorno da OIDC e salva la sessione."""
    try:
        code = request.args.get("code")
        if not code:
            return "Codice OIDC mancante", 400

        token_response = requests.post(
            OIDC_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OIDC_REDIRECT_URI,
                "client_id": OIDC_CLIENT_ID,
                "client_secret": OIDC_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        token_response.raise_for_status()
        tokens = token_response.json()

        access_token        = tokens["access_token"]
        refresh_token       = tokens.get("refresh_token")
        id_token            = tokens.get("id_token")
        expires_in          = int(tokens.get("expires_in", 300))
        refresh_expires_in  = int(tokens.get("refresh_expires_in", 0))

        # salva in sessione
        session["access_token"]        = access_token
        session["refresh_token"]       = refresh_token
        session["expires_at"]          = int(time.time()) + expires_in
        session["refresh_expires_at"]  = int(time.time()) + refresh_expires_in
        session["id_token"]            = id_token

        # decodifica senza verifica firma (solo per leggere claim)
        decoded = jwt.decode(access_token, options={"verify_signature": False, "verify_aud": False})
        session["user_email"] = decoded.get("email")
        session["user"]       = decoded.get("preferred_username") or decoded.get("email") or decoded.get("sub")
        session["user_info"]  = decoded

        # opzionale: vincolo utenti CNR
        if decoded.get("is_cnr_user") is False:
            return "Accesso riservato agli utenti CNR", 403

        # redirect "safe"
        default_after = url_for("root", _external=True)
        dest = request.args.get("state") or default_after
        if not ALLOW_EXTERNAL_REDIRECTS:
            current_origin = request.host_url.rstrip("/")
            if not _same_host(current_origin, dest):
                dest = default_after

        return redirect(dest)

    except Exception as e:
        # proviamo a loggare corpo/errore del token endpoint
        try:
            print("[OIDC] token error:", token_response.status_code, token_response.text, flush=True)
        except Exception:
            pass
        return f"Errore OIDC: {e}", 500


@auth_bp.route("/logout")
def logout():
    """Logout locale + redirect al logout del provider (se possibile)."""
    id_token = session.get("id_token")
    session.clear()
    session.modified = True

    # tenta di derivare l'endpoint di logout dal path di AUTH_URL:
    # es: .../protocol/openid-connect/auth  -> .../logout
    base_logout_url = OIDC_AUTH_URL.rsplit("/auth", 1)[0] + "/logout"

    post_back = url_for("auth.login", _external=True)
    logout_url = (
        f"{base_logout_url}"
        f"?post_logout_redirect_uri={post_back}"
        f"&scope=openid%20email%20profile&prompt=login"
    )
    if id_token:
        logout_url += f"&id_token_hint={id_token}"

    return redirect(logout_url)


# ========== API protetta ==========
@auth_bp.route("/api/userinfo")
@login_required
def userinfo():
    return jsonify({
        "email": session.get("user_email"),
        "username": session.get("user"),
    })
