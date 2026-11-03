# auth.py
from flask import Blueprint, request, session, redirect, url_for, jsonify
from urllib.parse import urlencode, urlparse
from functools import wraps
import os, time, json, requests, jwt
import secrets
from dotenv import load_dotenv

auth_bp = Blueprint("auth", __name__)

# ========== Config ==========
load_dotenv()

# Predefiniti: Keycloak di produzione di Selezioni Online (realm CNR, client "selezioni"),
# così il token è accettato dalle API di Selezioni Online (spec 003). Il secret resta in .env.
OIDC_BASE_URL      = os.getenv("OIDC_BASE_URL", "https://sso.cnr.it/auth/realms/CNR/protocol/openid-connect")
OIDC_CLIENT_ID     = os.getenv("OIDC_CLIENT_ID", "selezioni")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET")
OIDC_REDIRECT_URI  = os.getenv("OIDC_REDIRECT_URI")   # es: http://localhost:8081/oidc-callback
OIDC_AUTH_URL      = os.getenv("OIDC_AUTH_URL", f"{OIDC_BASE_URL}/auth")
OIDC_TOKEN_URL     = os.getenv("OIDC_TOKEN_URL", f"{OIDC_BASE_URL}/token")
OIDC_USERINFO_URL  = os.getenv("OIDC_USERINFO_URL", f"{OIDC_BASE_URL}/userinfo")

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


def _salva_token(tokens: dict) -> None:
    session["access_token"]       = tokens["access_token"]
    session["refresh_token"]      = tokens.get("refresh_token") or session.get("refresh_token")
    session["expires_at"]         = int(time.time()) + int(tokens.get("expires_in", 300))
    session["refresh_expires_at"] = int(time.time()) + int(tokens.get("refresh_expires_in", 0))
    if tokens.get("id_token"):
        session["id_token"] = tokens["id_token"]


def token_valido(margine: int = 30) -> str | None:
    """Token di accesso dell'utente collegato, rinnovato con il refresh_token se sta per scadere.
    Ritorna None se l'utente non è collegato o il rinnovo non riesce (serve un nuovo login)."""
    token = session.get("access_token")
    if token and int(session.get("expires_at", 0)) - time.time() > margine:
        return token
    refresh = session.get("refresh_token")
    if not refresh:
        return None
    try:
        r = requests.post(OIDC_TOKEN_URL, data={
            "grant_type": "refresh_token", "refresh_token": refresh,
            "client_id": OIDC_CLIENT_ID, "client_secret": OIDC_CLIENT_SECRET,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
        r.raise_for_status()
        _salva_token(r.json())
    except (requests.RequestException, KeyError, ValueError):
        return None
    return session.get("access_token")


def _utente_ammesso(claims: dict) -> bool:
    """Con UTENTI_AMMESSI (email separate da virgole) entrano solo quegli utenti CNR: il realm accetta
    anche SPID/CIE e l'app mostra dati personali dei candidati."""
    ammessi = {e.strip().lower() for e in os.getenv("UTENTI_AMMESSI", "").split(",") if e.strip()}
    if not ammessi:
        return claims.get("is_cnr_user") is not False
    return claims.get("is_cnr_user") is True and (claims.get("email") or "").lower() in ammessi


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

    nonce = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)
    session["oidc_state"] = state
    session["oidc_nonce"] = nonce
    session["oidc_next"] = next_url
    params = {
        "client_id": OIDC_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": OIDC_REDIRECT_URI,
        "state": state,
        "nonce": nonce,
    }
    return redirect(f"{OIDC_AUTH_URL}?{urlencode(params)}")


@auth_bp.route("/oidc-callback")
def oidc_callback():
    """Gestisce il ritorno da OIDC e salva la sessione."""
    try:
        code = request.args.get("code")
        if not code:
            return "Codice OIDC mancante", 400
        state = request.args.get("state")
        if not state or not secrets.compare_digest(state, session.get("oidc_state", "")):
            session.clear()
            return "Stato OIDC non valido", 400
        nonce = session.get("oidc_nonce")
        next_url = session.get("oidc_next")

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

        id_token = tokens.get("id_token")
        if not id_token:
            return "ID token OIDC mancante", 401
        # dal token endpoint in uso: il tool firme può configurare solo OIDC_TOKEN_URL
        base_oidc = OIDC_TOKEN_URL.rsplit("/token", 1)[0]
        jwks = jwt.PyJWKClient(f"{base_oidc}/certs")
        chiave = jwks.get_signing_key_from_jwt(id_token).key
        issuer = base_oidc.rsplit("/protocol/openid-connect", 1)[0]
        decoded = jwt.decode(id_token, chiave, algorithms=["RS256"], audience=OIDC_CLIENT_ID, issuer=issuer)
        if not nonce or not secrets.compare_digest(decoded.get("nonce", ""), nonce):
            session.clear()
            return "Nonce OIDC non valido", 401
        if not _utente_ammesso(decoded):  # prima di salvare i token: altrimenti la sessione resta valida
            session.clear()
            return "Accesso riservato agli utenti autorizzati", 403

        session.clear()
        _salva_token(tokens)
        session["user_email"] = decoded.get("email")
        session["user"]       = decoded.get("preferred_username") or decoded.get("email") or decoded.get("sub")
        session["user_info"]  = decoded

        # redirect "safe"
        default_after = url_for("root", _external=True)
        dest = next_url or default_after
        if not ALLOW_EXTERNAL_REDIRECTS:
            current_origin = request.host_url.rstrip("/")
            if not _same_host(current_origin, dest):
                dest = default_after

        return redirect(dest)

    except Exception as e:
        # Non registrare i corpi delle risposte: possono contenere token.
        try:
            print("[OIDC] errore durante lo scambio del codice di autorizzazione", flush=True)
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
