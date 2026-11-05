"""Chi può entrare e cosa può fare (spec 006): tabella degli utenti con ruoli amministratore e lettura.

Le persone in UTENTI_AMMESSI sono sempre amministratori e non si possono togliere dalla pagina, così
nessuno resta chiuso fuori. Il ruolo si legge a ogni richiesta: togliere qualcuno ha effetto subito.
"""
import os
from datetime import datetime, timezone
from functools import wraps

from flask import jsonify, request, session

from . import db

AMMINISTRATORE, LETTURA = "amministratore", "lettura"


class UtenteProtetto(Exception):
    pass


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalizza(nome: str | None) -> str:
    """Nome utente di SOL (nome.cognome); un'email vale per la parte prima della @."""
    return (nome or "").strip().lower().split("@")[0]


def iniziali() -> set[str]:
    return {normalizza(u) for u in os.environ.get("UTENTI_AMMESSI", "").split(",") if u.strip()}


def _conn():
    conn = db.connetti()
    db.inizializza(conn)
    return conn


def email_di(nome: str) -> str:
    """Dove mandare il link di accesso: l'indirizzo in tabella, altrimenti nome.cognome@cnr.it."""
    nome = normalizza(nome)
    conn = _conn()
    try:
        riga = conn.execute("SELECT email FROM utente WHERE username = ?", (nome,)).fetchone()
    finally:
        conn.close()
    return riga["email"] if riga and riga["email"] else f"{nome}@{os.environ.get('ACCESSO_DOMINIO_EMAIL', 'cnr.it')}"


def segna_ultimo_accesso(nome: str) -> None:
    conn = _conn()
    try:
        conn.execute("INSERT INTO utente_accesso (username, quando) VALUES (?, ?) ON CONFLICT(username) DO UPDATE SET quando = excluded.quando",
                     (normalizza(nome), _adesso()))
    finally:
        conn.close()


def registra_accesso(nome: str) -> None:
    conn = _conn()
    try:
        conn.execute("INSERT INTO utente_modifica (username, azione, quando) VALUES (?, 'link_accesso', ?)",
                     (normalizza(nome), _adesso()))
    finally:
        conn.close()


def ruolo(nome: str | None) -> str | None:
    nome = normalizza(nome)
    if not nome:
        return None
    if nome in iniziali():
        return AMMINISTRATORE
    conn = _conn()
    try:
        riga = conn.execute("SELECT ruolo FROM utente WHERE username = ?", (nome,)).fetchone()
    finally:
        conn.close()
    return riga["ruolo"] if riga else None


def elenco(conn) -> list[dict]:
    fissi = iniziali()
    accessi = {r["username"]: r["quando"] for r in conn.execute("SELECT * FROM utente_accesso")}
    righe = [{"username": u, "ruolo": AMMINISTRATORE, "iniziale": True, "email": None, "aggiunto_da": None, "aggiunto_il": None}
             for u in sorted(fissi)]
    righe += [{**dict(r), "iniziale": False} for r in conn.execute("SELECT * FROM utente ORDER BY username")
              if r["username"] not in fissi]
    return [{**r, "ultimo_accesso": accessi.get(r["username"])} for r in righe]


def registro(conn, limite: int = 50) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM utente_modifica ORDER BY id DESC LIMIT ?", (limite,))]


def imposta(conn, nome: str, nuovo_ruolo: str, autore: str | None, email: str | None = None) -> str:
    nome = normalizza(nome)
    email = (email or "").strip().lower() or None
    if not nome or nuovo_ruolo not in (AMMINISTRATORE, LETTURA):
        raise ValueError("Nome utente o ruolo non valido")
    if email and "@" not in email:
        raise ValueError("Email non valida")
    if nome in iniziali():
        raise UtenteProtetto(f"{nome} è un amministratore iniziale: si cambia solo dalla configurazione")
    ora = _adesso()
    conn.execute("INSERT INTO utente (username, ruolo, email, aggiunto_da, aggiunto_il) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(username) DO UPDATE SET ruolo = excluded.ruolo, email = COALESCE(excluded.email, email)",
                 (nome, nuovo_ruolo, email, autore, ora))
    conn.execute("INSERT INTO utente_modifica (username, azione, ruolo, autore, quando) VALUES (?, 'imposta', ?, ?, ?)",
                 (nome, nuovo_ruolo, autore, ora))
    return nome


def togli(conn, nome: str, autore: str | None) -> bool:
    nome = normalizza(nome)
    if nome in iniziali():
        raise UtenteProtetto(f"{nome} è un amministratore iniziale: si cambia solo dalla configurazione")
    tolti = conn.execute("DELETE FROM utente WHERE username = ?", (nome,)).rowcount
    if tolti:
        conn.execute("INSERT INTO utente_modifica (username, azione, autore, quando) VALUES (?, 'togli', ?, ?)",
                     (nome, autore, _adesso()))
    return bool(tolti)


def corrente() -> str | None:
    return session.get("user")


def ruolo_corrente() -> str | None:
    """Chi entra col link via email resta in lettura qualunque sia il suo ruolo."""
    attuale = ruolo(corrente())
    return LETTURA if attuale and session.get("solo_lettura") else attuale


def protezioni(base, uscita=None):
    """Da un decoratore di autenticazione ricava (protezione, solo_admin), con il ruolo letto a ogni richiesta."""
    def protezione(fn):
        @wraps(fn)
        def _controllo(*args, **kwargs):
            if not ruolo_corrente():
                if uscita:
                    uscita()
                session.clear()
                return jsonify({"error": "Utente non autorizzato"}), 403
            return fn(*args, **kwargs)
        return base(_controllo)

    def solo_admin(fn):
        @wraps(fn)
        def _controllo(*args, **kwargs):
            if ruolo_corrente() != AMMINISTRATORE:
                if request.method == "GET" and not request.path.startswith("/api/"):  # link aperto nel browser
                    return ('<!doctype html><html lang="it"><meta charset="utf-8"><title>Pagina riservata</title>'
                            '<p>Questa pagina è riservata agli amministratori. <a href="/monitoraggio">Vai al monitoraggio</a></p></html>'), 403
                return jsonify({"error": "Operazione riservata agli amministratori"}), 403
            return fn(*args, **kwargs)
        return _controllo

    return protezione, solo_admin
