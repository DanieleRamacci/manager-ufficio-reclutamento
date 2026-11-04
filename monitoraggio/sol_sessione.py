"""Sessione Selezioni Online (spec 004).

In produzione il ticket si ottiene dal token SSO dell'utente collegato (`ticket_da_token`) e non resta
salvato: se ne chiede uno nuovo a ogni verifica.

Nella prova locale l'app non può leggere il cookie di un altro sito: per questo apre una finestra di Chrome
(con un profilo temporaneo, separato da quello dell'utente) su Selezioni Online, l'utente fa il
login normalmente e l'app legge il cookie `ticket` da quella finestra. Il ticket resta solo in
memoria (mai su disco, nel database o nei log) e scade dopo un'ora come su Selezioni Online.
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)

DURATA_TICKET = timedelta(minutes=55)   # SOL imposta il cookie per 3600 s
ATTESA_LOGIN_S = 300

_lock = threading.Lock()
_stato = {"ticket": None, "ottenuto_il": None, "scade_il": None, "in_corso": False, "errore": None}


def base_url() -> str:
    return os.environ.get("JCONON_BASE_URL", "https://selezionionline.cnr.it/jconon").rstrip("/")


def _adesso() -> datetime:
    return datetime.now(timezone.utc)


def stato() -> dict:
    """Stato pubblico della sessione (mai il ticket)."""
    with _lock:
        valido = bool(_stato["ticket"]) and _stato["scade_il"] and _stato["scade_il"] > _adesso()
        return {"collegato": bool(valido), "in_corso": _stato["in_corso"], "errore": _stato["errore"],
                "scade_il": _stato["scade_il"].isoformat(timespec="minutes") if valido else None}


def ticket() -> str | None:
    with _lock:
        if _stato["ticket"] and _stato["scade_il"] and _stato["scade_il"] > _adesso():
            return _stato["ticket"]
        return None


def dimentica() -> None:
    with _lock:
        _stato.update(ticket=None, ottenuto_il=None, scade_il=None, errore=None)


def valida(valore: str) -> bool:
    try:
        r = requests.post(f"{base_url()}/openapi/security/validate", params={"ticket": valore}, timeout=20)
        r.raise_for_status()
        return bool(r.json().get("isValid"))
    except (requests.RequestException, ValueError):
        return False


def identita(valore: str) -> dict | None:
    """Chi è l'utente del ticket, secondo /rest/common (lo stesso oggetto `common.User` usato dalle pagine
    di SOL). None se il ticket non è valido: senza un ticket valido SOL risponde con l'utente guest."""
    try:
        r = requests.get(f"{base_url()}/rest/common", headers={"Cookie": f"ticket={valore}"}, timeout=20,
                         allow_redirects=False)
        dati = r.json() if r.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        log.warning("Selezioni Online: identità dell'utente non disponibile")
        return None
    utente = dati.get("User") if isinstance(dati, dict) else None
    if not isinstance(utente, dict) or dati.get("isGuest") or utente.get("guest"):
        return None
    nome = str(utente.get("userName") or utente.get("id") or "").strip().lower()
    return {"username": nome, "email": (utente.get("email") or "").strip().lower() or None} if nome else None


def ticket_da_token(token: str) -> str | None:
    """Scambia il token SSO con il ticket di SOL: lo stesso del cookie `ticket` del login dal browser
    (entrambi da CustomKeyCloakAuthSuccessHandler.createTicketForUser). Il filtro Keycloak di SOL non
    legge l'header Authorization (KeycloakConfiguration), solo il parametro `access_token`: l'header si
    prova per primo per non mettere il token in un URL. Niente dettagli nei log: l'URL contiene il token."""
    url = f"{base_url()}/openapi/security/sso/login"
    for richiesta in ({"headers": {"Authorization": f"Bearer {token}"}}, {"params": {"access_token": token}}):
        try:
            r = requests.get(url, timeout=20, allow_redirects=False, **richiesta)
            valore = r.json().get("ticket") if r.status_code == 200 else None
        except (requests.RequestException, ValueError, AttributeError):
            log.warning("Selezioni Online: scambio del token SSO non riuscito")
            continue
        if valore and valida(valore):
            return valore
    return None


def _apri_finestra_e_attendi() -> None:
    from playwright.sync_api import sync_playwright  # solo per la prova locale

    errore, trovato = None, None
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome", headless=False)
            except Exception:
                browser = p.chromium.launch(headless=False)
            contesto = browser.new_context()
            pagina = contesto.new_page()
            pagina.goto(f"{base_url()}/sso/login", wait_until="domcontentloaded")
            fine = time.monotonic() + ATTESA_LOGIN_S
            while time.monotonic() < fine and not trovato:
                for cookie in contesto.cookies(base_url()):
                    if cookie.get("name") == "ticket" and cookie.get("value"):
                        trovato = cookie["value"]
                        break
                if not trovato:
                    if not browser.is_connected() or not contesto.pages:
                        errore = "Finestra chiusa prima del login"
                        break
                    time.sleep(1)
            try:
                browser.close()
            except Exception:
                pass
        if not trovato and not errore:
            errore = "Login non completato entro 5 minuti"
        if trovato and not valida(trovato):
            errore, trovato = "Selezioni Online non riconosce la sessione ottenuta", None
    except Exception as e:  # Playwright o Chrome non disponibili
        errore = f"Impossibile aprire la finestra di login ({type(e).__name__})"
    with _lock:
        _stato["in_corso"] = False
        _stato["errore"] = errore
        if trovato:
            _stato.update(ticket=trovato, ottenuto_il=_adesso(), scade_il=_adesso() + DURATA_TICKET)
    log.info("Sessione Selezioni Online: %s", "collegata" if trovato else errore)


def avvia_login() -> bool:
    """Apre la finestra di login in background. False se un login è già in corso."""
    with _lock:
        if _stato["in_corso"]:
            return False
        _stato.update(in_corso=True, errore=None)
    threading.Thread(target=_apri_finestra_e_attendi, daemon=True, name="login-sol").start()
    return True


def intestazioni() -> dict:
    """Header per le chiamate autenticate a SOL con il ticket della sessione."""
    t = ticket()
    return {"Cookie": f"ticket={t}"} if t else {}
