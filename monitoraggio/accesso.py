"""Accesso al sito con il ticket di Selezioni Online, senza un client Keycloak dell'app.

Il server non può aprire Chrome né leggere il cookie di un altro sito: l'utente fa il login su SOL nel
suo browser e incolla qui il valore del cookie `ticket`, lo stesso usato dalla prova locale, oppure lo
invia il programma scaricabile da questa pagina (static/collega_sol.py). SOL dice chi è l'utente; entra
solo chi è in UTENTI_AMMESSI. Il ticket resta in memoria, per utente, mai su disco.
"""
import io
import os
import re
import secrets
import stat
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template_string, request, send_file, session

from . import sol_sessione

DURATA_ACCESSO = timedelta(hours=12)
DURATA_LINK = timedelta(minutes=2)
_PAGINA = Path(__file__).resolve().parent / "static" / "accesso.html"
_PROGRAMMA = Path(__file__).resolve().parent / "static" / "collega_sol.py"
_FORMATO_TICKET = re.compile(r"[\w.\-=]{8,512}")

_lock = threading.Lock()
_ticket: dict[str, tuple[str, datetime]] = {}
_link: dict[str, tuple[dict, datetime]] = {}  # codice monouso -> utente, per entrare dal programma

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


def _riconosci(testo: str) -> tuple[dict | None, str | None, int]:
    """Controlla il ticket e, se l'utente è ammesso, lo tiene in memoria. Ritorna (utente, errore, codice)."""
    ticket = pulisci_ticket(testo)
    if not ticket:
        return None, "Il valore incollato non sembra un ticket: copia solo il contenuto del cookie.", 400
    chi = sol_sessione.identita(ticket)
    if not chi:
        return None, ("Selezioni Online non riconosce questo ticket: potrebbe essere scaduto. "
                      "Rifai il login su Selezioni Online e copia di nuovo il cookie."), 401
    if chi["username"] not in utenti_ammessi():
        return None, f"L'utente {chi['username']} non è autorizzato: va aggiunto a UTENTI_AMMESSI.", 403
    with _lock:
        _ticket[chi["username"]] = (ticket, _adesso() + sol_sessione.DURATA_TICKET)
    return chi, None, 200


def _apri_sessione(chi: dict) -> None:
    session.clear()
    session["user"] = chi["username"]
    session["user_email"] = chi["email"] or chi["username"]
    session["accesso_fino"] = (_adesso() + DURATA_ACCESSO).isoformat()


@bp.post("/login")
def accedi():
    chi, errore, codice = _riconosci(request.form.get("ticket", ""))
    if not chi:
        return _mostra(errore, codice)
    destinazione = _next_sicuro(request.form.get("next"))
    _apri_sessione(chi)
    return redirect(destinazione)


@bp.post("/api/sol/ticket")
def ricevi_dal_programma():
    """Dal programma sul computer dell'utente: niente sessione, vale il ticket stesso. Risponde con un link
    monouso che apre la sessione nel browser abituale."""
    chi, errore, codice = _riconosci(request.form.get("ticket", ""))
    if not chi:
        return jsonify({"ok": False, "error": errore}), codice
    link = secrets.token_urlsafe(32)
    ora = _adesso()
    with _lock:
        for vecchio in [k for k, v in _link.items() if v[1] <= ora]:
            del _link[vecchio]
        _link[link] = (chi, ora + DURATA_LINK)
    return jsonify({"ok": True, "utente": chi["username"], "link": f"{request.host_url}login/completa?codice={link}"})


@bp.get("/login/completa")
def completa():
    with _lock:
        voce = _link.pop(request.args.get("codice", ""), None)
    if not voce or voce[1] <= _adesso():
        return _mostra("Il link è scaduto o è già stato usato: avvia di nuovo il programma.", 401)
    _apri_sessione(voce[0])
    return redirect("/monitoraggio")


@bp.get("/login/programma")
def programma():
    """Il programma per Mac, in uno zip che conserva il permesso di esecuzione. Contiene solo l'indirizzo del sito."""
    script = _PROGRAMMA.read_text(encoding="utf-8").replace("__SERVER__", request.host_url.rstrip("/"))
    comando = ("#!/bin/sh\ncommand -v python3 >/dev/null 2>&1 || { echo 'Serve Python 3: incolla il ticket nella "
               "pagina di accesso.'; exit 1; }\nexec python3 - <<'COLLEGA_SOL'\n" + script + "\nCOLLEGA_SOL\n")
    voce = zipfile.ZipInfo("Collega-SOL.command", date_time=(2026, 1, 1, 0, 0, 0))
    voce.create_system = 3  # Unix: senza tipo di file e sistema, Archive Utility toglie il permesso di esecuzione
    voce.external_attr = (stat.S_IFREG | 0o755) << 16
    voce.compress_type = zipfile.ZIP_DEFLATED
    contenuto = io.BytesIO()
    with zipfile.ZipFile(contenuto, "w") as archivio:
        archivio.writestr(voce, comando)
    contenuto.seek(0)
    return send_file(contenuto, mimetype="application/zip", as_attachment=True, download_name="Collega-SOL.zip")


@bp.get("/logout")
def logout():
    dimentica()
    session.clear()
    return redirect("/login")
