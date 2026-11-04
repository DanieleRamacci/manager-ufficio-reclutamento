"""WSGI entrypoint for the Coolify deployment."""
import os

from dotenv import load_dotenv
from flask import Flask, redirect, session
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix

from . import accesso, collegamento, config, db, scheduler, utenti
from .mensile_web import crea_blueprint_mensile
from .web import PAGINE_LOCALI, crea_blueprint, crea_blueprint_pagine_esistenti


def _protezione_sso():
    import auth

    auth.verifica_utente = lambda claims: claims.get("is_cnr_user") is True and bool(
        utenti.ruolo(claims.get("preferred_username") or claims.get("email")))
    return auth.auth_bp, dict(protezione=auth.login_required, utente_corrente=lambda: session.get("user_email"),
                              token_utente=auth.token_valido, logout_url="/logout")


def _protezione_ticket():
    return accesso.bp, dict(protezione=accesso.login_required, utente_corrente=accesso.utente,
                            token_utente=accesso.intestazioni, sessione_sol=accesso, logout_url="/logout")


def crea_app() -> Flask:
    load_dotenv()
    # ACCESSO_SSO=1 solo con un client Keycloak di produzione; altrimenti si entra col ticket di SOL
    sso = os.environ.get("ACCESSO_SSO") == "1"
    richieste = ("FLASK_SECRET_KEY", "UTENTI_AMMESSI") + (("OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI") if sso else ())
    mancanti = [nome for nome in richieste if not os.environ.get(nome)]
    if mancanti:
        raise RuntimeError("Configurazione di produzione incompleta: " + ", ".join(mancanti))

    app = Flask(__name__)
    cartella_sessioni = config.data_dir() / "flask_session"
    cartella_sessioni.mkdir(parents=True, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ["FLASK_SECRET_KEY"],
        SESSION_TYPE="filesystem",
        SESSION_FILE_DIR=str(cartella_sessioni),
        SESSION_PERMANENT=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PREFERRED_URL_SCHEME="https",
    )
    Session(app)

    blueprint_accesso, opzioni = _protezione_sso() if sso else _protezione_ticket()
    protezione, solo_admin = utenti.protezioni(opzioni.pop("protezione"), accesso.dimentica if not sso else None)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.register_blueprint(blueprint_accesso)
    app.register_blueprint(crea_blueprint(protezione=protezione, solo_admin=solo_admin, ruolo_corrente=utenti.ruolo_corrente,
                                          login_url="/login?next=/monitoraggio", login_sol=False, **opzioni))
    app.register_blueprint(crea_blueprint_pagine_esistenti(protezione=protezione, solo_admin=solo_admin))
    app.register_blueprint(crea_blueprint_mensile(protezione=protezione, solo_admin=solo_admin,
                                                  utente_corrente=opzioni["utente_corrente"]))

    @app.get("/")
    @protezione
    def root():
        return redirect("/monitoraggio")

    conn = db.connetti()
    try:
        db.inizializza(conn)
        collegamento.collega(conn)
    finally:
        conn.close()
    scheduler.avvia()
    return app


app = crea_app()
