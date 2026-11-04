"""Accesso al sito con il ticket di Selezioni Online, senza un client Keycloak dell'app.

Il server non può aprire Chrome né leggere il cookie di un altro sito: l'utente fa il login su SOL nel
suo browser e incolla qui il valore del cookie `ticket`, lo stesso usato dalla prova locale. SOL dice
chi è l'utente; entra solo chi è in UTENTI_AMMESSI. Il ticket resta in memoria, per utente, mai su disco.
"""
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, redirect, render_template_string, request, session

from . import sol_sessione

DURATA_ACCESSO = timedelta(hours=12)
_PAGINA = Path(__file__).resolve().parent / "static" / "accesso.html"
_FORMATO_TICKET = re.compile(r"[\w.\-=]{8,512}")

_lock = threading.Lock()
_ticket: dict[str, tuple[str, datetime]] = {}

bp = Blueprint("accesso", __name__)


def _adesso() -> datetime:
    return datetime.now(timezone.utc)


def utenti_ammessi() -> set[str]:
    """Nomi utente di SOL (nome.cognome); un'email vale per la parte prima della @."""
    return {u.strip().lower().split("@")[0] for u in os.environ.get("UTENTI_AMMESSI", "").split(",") if u.strip()}


def pulisci_ticket(testo: str) -> str | None:
    valore = (testo or "").strip().removeprefix("ticket=").strip().strip('"')
    return valore if _FORMATO_TICKET.fullmatch(valore) else None


def utente() -> str | None:
    return session.get("user")


def login_required(fn):
    @wraps(fn)
    def _wrapped(*args, **kwargs):
        fino = session.get("accesso_fino")
        if not session.get("user") or not fino or datetime.fromisoformat(fino) <= _adesso():
            return redirect(f"/login?next={request.path}")
        return fn(*args, **kwargs)
    return _wrapped


def _next_sicuro(valore: str | None) -> str:
    return valore if valore and valore.startswith("/") and not valore.startswith(("//", "/\\")) else "/monitoraggio"


def intestazioni() -> dict | None:
    """Header per SOL con il ticket dell'utente, solo se SOL lo riconosce ancora."""
    nome = session.get("user")
    with _lock:
        voce = _ticket.get(nome)
    if not voce or voce[1] <= _adesso():
        return None
    if (sol_sessione.identita(voce[0]) or {}).get("username") != nome:
        dimentica()
        return None
    return {"Cookie": f"ticket={voce[0]}"}


def stato() -> dict:
    with _lock:
        voce = _ticket.get(session.get("user"))
    valido = bool(voce and voce[1] > _adesso())
    return {"collegato": valido, "in_corso": False, "errore": None, "disponibile": True,
            "scade_il": voce[1].isoformat(timespec="minutes") if valido else None,
            "login_url": f"/login?next={_next_sicuro(request.referrer and '/' + request.referrer.split('/', 3)[-1])}"}


def dimentica() -> None:
    with _lock:
        _ticket.pop(session.get("user"), None)


def _mostra(errore: str | None = None, codice: int = 200):
    return render_template_string(_PAGINA.read_text(encoding="utf-8"), errore=errore,
                                  sol_login=f"{sol_sessione.base_url()}/sso/login",
                                  next=_next_sicuro(request.values.get("next"))), codice


@bp.get("/login")
def login():
    return _mostra()


@bp.post("/login")
def accedi():
    ticket = pulisci_ticket(request.form.get("ticket", ""))
    if not ticket:
        return _mostra("Il valore incollato non sembra un ticket: copia solo il contenuto del cookie.", 400)
    chi = sol_sessione.identita(ticket)
    if not chi:
        return _mostra("Selezioni Online non riconosce questo ticket: potrebbe essere scaduto. "
                       "Rifai il login su Selezioni Online e copia di nuovo il cookie.", 401)
    if chi["username"] not in utenti_ammessi():
        return _mostra(f"L'utente {chi['username']} non è autorizzato: va aggiunto a UTENTI_AMMESSI.", 403)
    destinazione = _next_sicuro(request.form.get("next"))
    session.clear()
    session["user"] = chi["username"]
    session["user_email"] = chi["email"] or chi["username"]
    session["accesso_fino"] = (_adesso() + DURATA_ACCESSO).isoformat()
    with _lock:
        _ticket[chi["username"]] = (ticket, _adesso() + sol_sessione.DURATA_TICKET)
    return redirect(destinazione)


@bp.get("/logout")
def logout():
    dimentica()
    session.clear()
    return redirect("/login")
