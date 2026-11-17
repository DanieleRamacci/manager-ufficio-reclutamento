"""App installabile (spec 009): manifest, icone e service worker, raggiungibili senza accesso perché il browser
li legge prima del login. Il service worker non salva dati (static/sw.js). `/app` è la pagina iniziale dell'app:
porta ognuno alla propria pagina, compresi i referenti, che hanno un accesso separato."""
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, redirect, send_from_directory, session

from . import portale

_STATIC = Path(__file__).resolve().parent / "static"
FILE = {"manifest.webmanifest": "application/manifest+json", "sw.js": "text/javascript", "pwa.js": "text/javascript",
        "icona-192.png": "image/png", "icona-512.png": "image/png", "icona-apple.png": "image/png"}

bp = Blueprint("pwa", __name__)


def _servi(nome: str):
    risposta = send_from_directory(_STATIC, nome, mimetype=FILE[nome], max_age=0)
    if nome == "sw.js":
        risposta.headers["Cache-Control"] = "no-cache"  # una nuova versione arriva alla prossima apertura
        risposta.headers["Service-Worker-Allowed"] = "/"
    return risposta


for _nome in FILE:
    bp.add_url_rule(f"/{_nome}", f"file_{_nome.replace('.', '_').replace('-', '_')}", lambda n=_nome: _servi(n))


def _sito_attivo() -> bool:
    fino = session.get("accesso_fino")
    try:
        return bool(session.get("user") and (not fino or datetime.fromisoformat(fino) > datetime.now(timezone.utc)))
    except ValueError:
        return False


@bp.get("/app")
def app():
    if not _sito_attivo() and portale.referente_corrente():
        return redirect(portale.PAGINA)
    return redirect("/")
