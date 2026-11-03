"""WSGI entrypoint for the Coolify deployment."""
import os

from dotenv import load_dotenv
from flask import Flask, redirect, session
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix

from . import collegamento, config, db, scheduler
from .web import PAGINE_LOCALI, crea_blueprint, crea_blueprint_pagine_esistenti


def crea_app() -> Flask:
    load_dotenv()
    richieste = ("OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI", "FLASK_SECRET_KEY", "UTENTI_AMMESSI")
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

    import auth

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.register_blueprint(auth.auth_bp)
    app.register_blueprint(
        crea_blueprint(
            protezione=auth.login_required,
            utente_corrente=lambda: session.get("user_email"),
            token_utente=auth.token_valido,
            login_url="/login?next=/monitoraggio",
            logout_url="/logout",
            login_sol=False,
        )
    )
    app.register_blueprint(crea_blueprint_pagine_esistenti(protezione=auth.login_required))

    @app.get("/")
    @auth.login_required
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
