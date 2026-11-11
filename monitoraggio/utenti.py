"""Chi può entrare e cosa può fare (spec 006): tabella degli utenti con ruoli amministratore e lettura.

Le persone in UTENTI_AMMESSI sono sempre amministratori e non si possono togliere dalla pagina, così
nessuno resta chiuso fuori. Il ruolo si legge a ogni richiesta: togliere qualcuno ha effetto subito.
"""
import os
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import quote

from flask import jsonify, redirect, request, session

from . import config, db, posta

AMMINISTRATORE, DIRIGENTE, SEGRETERIA, LETTURA = "amministratore", "dirigente", "segreteria", "lettura"
RUOLI = (AMMINISTRATORE, DIRIGENTE, SEGRETERIA, LETTURA)
PAGINA_CONSULTAZIONE = "/monitoraggio/consulta/stato"
# chi non è amministratore vede solo la consultazione (decisione dell'utente del 2026-11-11)
PERCORSI_CONSULTAZIONE = ("/monitoraggio/consulta/", "/api/consulta/", "/api/menu", "/monitoraggio/menu.js", "/monitoraggio/app.css",
                          "/monitoraggio/app.js", "/api/sol/", "/api/vista-come/esci")


PAGINA_MONITORAGGI = "/monitoraggio/consulta/monitoraggi"


def _pagina_consultazione_per(percorso: str) -> str:
    """Chi non è amministratore e apre /monitoraggio (o un monitoraggio mensile) trova l'elenco dei monitoraggi."""
    if percorso.rstrip("/") == "/monitoraggio":
        return PAGINA_MONITORAGGI
    if percorso.startswith("/monitoraggio/mensili"):
        mese = percorso[len("/monitoraggio/mensili"):].strip("/").split("/")[0]
        return f"{PAGINA_MONITORAGGI}/{mese}" if mese.replace("-", "").isdigit() else PAGINA_MONITORAGGI
    return PAGINA_CONSULTAZIONE


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
    return [{**r, "ultimo_accesso": accessi.get(r["username"]), "link": link_accesso(r["username"])} for r in righe]


def link_accesso(nome: str) -> str:
    """Il link da dare alla persona, con il suo nome utente già compilato: non contiene credenziali."""
    return f"{config.sito_url()}/login?utente={quote(normalizza(nome))}"


def nome_da_indicazione(testo: str | None) -> str:
    """Dal nome utente o dall'email scritti nella pagina di accesso: un'email in tabella vale per il suo utente."""
    testo = (testo or "").strip().lower()
    if "@" in testo:
        conn = _conn()
        try:
            riga = conn.execute("SELECT username FROM utente WHERE lower(email) = ?", (testo,)).fetchone()
        finally:
            conn.close()
        if riga:
            return riga["username"]
    return normalizza(testo)


def invia_accesso(conn, nome: str, autore: str | None) -> str | None:
    """Scrive alla persona come entrare. Ritorna l'indirizzo usato, None se non è tra gli utenti."""
    nome = normalizza(nome)
    chi = ruolo(nome)
    if not chi:
        return None
    email = email_di(nome)
    posta.invia([email], "Accesso al monitoraggio bandi",
                "Buongiorno,\n\nper consultare il monitoraggio apri questo link. Se la pagina lo chiede, inserisci la tua email o il tuo "
                f"nome utente (nome.cognome) e richiedi il link di accesso: lo riceverai in questa casella, valido 15 minuti.\n{link_accesso(nome)}\n",
                sempre_reale=True)
    conn.execute("INSERT INTO utente_modifica (username, azione, autore, quando) VALUES (?, 'invito_accesso', ?, ?)", (nome, autore, _adesso()))
    return email


def traccia_anteprima(conn, chi: str, autore: str | None, cosa: str) -> None:
    conn.execute("INSERT INTO utente_modifica (username, azione, ruolo, autore, quando) VALUES (?, ?, NULL, ?, ?)",
                 (chi, cosa, autore, _adesso()))


def registro(conn, limite: int = 50) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM utente_modifica ORDER BY id DESC LIMIT ?", (limite,))]


def imposta(conn, nome: str, nuovo_ruolo: str, autore: str | None, email: str | None = None) -> str:
    nome = normalizza(nome)
    email = (email or "").strip().lower() or None
    if not nome or nuovo_ruolo not in RUOLI:
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


ESCI_ANTEPRIMA = "/api/vista-come/esci"


def vista_come() -> str | None:
    """Anteprima: un amministratore vede il sito come un altro utente, senza poter fare nulla a suo nome."""
    nome = session.get("vista_come")
    if not nome or session.get("solo_lettura") or ruolo(corrente()) != AMMINISTRATORE or ruolo(nome) is None:
        return None
    return nome


def ruolo_corrente() -> str | None:
    """Chi entra col link via email non opera: un amministratore vede come un dirigente, gli altri restano come sono."""
    anteprima = vista_come()
    if anteprima:
        return ruolo(anteprima)
    attuale = ruolo(corrente())
    return DIRIGENTE if attuale == AMMINISTRATORE and session.get("solo_lettura") else attuale


def email_correnti() -> set[str]:
    """Gli indirizzi con cui riconoscere la persona tra gli RdP: quello in tabella e quello di Selezioni Online."""
    anteprima = vista_come()
    if anteprima:
        return {email_di(anteprima).lower()}
    nome = corrente()
    trovate = {email_di(nome).lower()} if nome else set()
    if "@" in str(session.get("user_email") or ""):
        trovate.add(session["user_email"].strip().lower())
    return trovate


def referente_attivo(emails: set[str]) -> bool:
    """Risulta RdP di almeno un bando nell'ultimo aggiornamento dei referenti."""
    if not emails:
        return False
    conn = _conn()
    try:
        segnaposti = ", ".join("?" * len(emails))
        return conn.execute(f"SELECT 1 FROM referente WHERE attivo = 1 AND lower(trim(email)) IN ({segnaposti}) LIMIT 1",
                            tuple(emails)).fetchone() is not None
    finally:
        conn.close()


def _consentito(percorso: str) -> bool:
    return percorso == "/" or any(percorso.startswith(p) or percorso == p.rstrip("/") for p in PERCORSI_CONSULTAZIONE)


def _rifiuta(messaggio: str):
    if request.method == "GET" and not request.path.startswith("/api/"):
        return f'<!doctype html><html lang="it"><meta charset="utf-8"><title>Accesso non consentito</title><p>{messaggio}</p></html>', 403
    return jsonify({"error": messaggio}), 403


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
            anteprima = vista_come()
            if anteprima and request.method not in ("GET", "HEAD") and request.path != ESCI_ANTEPRIMA:
                return jsonify({"error": f"Anteprima come {anteprima}: le azioni non vengono eseguite. Torna amministratore per farle."}), 403
            attuale = ruolo_corrente()
            if attuale == LETTURA and not anteprima and not referente_attivo(email_correnti()):
                if uscita:
                    uscita()
                session.clear()
                return _rifiuta("Non risulti responsabile del procedimento (RdP) di nessun bando: l'accesso non è consentito.")
            if attuale != AMMINISTRATORE and not _consentito(request.path):
                if request.method == "GET" and not request.path.startswith("/api/"):
                    return redirect(_pagina_consultazione_per(request.path))
                return jsonify({"error": "Operazione riservata agli amministratori"}), 403
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
