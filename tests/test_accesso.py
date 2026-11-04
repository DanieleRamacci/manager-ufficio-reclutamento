"""Accesso al sito con il ticket di Selezioni Online."""
import time

from flask import Flask, session
from flask_session import Session

from monitoraggio import accesso, sol_sessione, web
from monitoraggio.fonti import sol_rdp

TICKET = "TICKET_abcdef0123456789"


class Risposta:
    def __init__(self, corpo, status_code=200):
        self.corpo, self.status_code = corpo, status_code

    def json(self):
        return self.corpo


def _utente(nome="mario.rossi", guest=False, email="mario.rossi@cnr.it"):
    return Risposta({"isGuest": guest, "User": {"userName": nome, "id": nome, "guest": guest, "email": email}})


def test_identita_del_ticket(monkeypatch):
    chiamate = []

    def finto(url, **kw):
        chiamate.append((url, kw["headers"]))
        return _utente("Mario.Rossi")
    monkeypatch.setattr(sol_sessione.requests, "get", finto)
    assert sol_sessione.identita(TICKET) == {"username": "mario.rossi", "email": "mario.rossi@cnr.it"}
    assert chiamate[0][0].endswith("/rest/common") and chiamate[0][1] == {"Cookie": f"ticket={TICKET}"}


def test_ticket_scaduto_risulta_guest(monkeypatch):
    monkeypatch.setattr(sol_sessione.requests, "get", lambda u, **k: _utente("guest", guest=True))
    assert sol_sessione.identita(TICKET) is None
    monkeypatch.setattr(sol_sessione.requests, "get", lambda u, **k: Risposta({}, 500))
    assert sol_sessione.identita(TICKET) is None


def test_pulisci_ticket():
    assert accesso.pulisci_ticket(f"  ticket={TICKET}\n") == TICKET
    assert accesso.pulisci_ticket(f'"{TICKET}"') == TICKET
    for cattivo in ("", "corto", "TICKET_abc\r\nSet-Cookie: x=1", "a b c d e f g h i"):
        assert accesso.pulisci_ticket(cattivo) is None


def test_ammessi_per_nome_utente(monkeypatch):
    monkeypatch.setenv("UTENTI_AMMESSI", "mario.rossi, Anna.Bianchi@cnr.it")
    assert accesso.utenti_ammessi() == {"mario.rossi", "anna.bianchi"}


def _app(tmp_path, monkeypatch, nome="mario.rossi"):
    monkeypatch.setenv("UTENTI_AMMESSI", "mario.rossi")
    monkeypatch.setattr(accesso, "_ticket", {})
    monkeypatch.setattr(sol_sessione, "identita", lambda t: {"username": nome, "email": "m@cnr.it"} if t == TICKET else None)
    app = Flask(__name__)
    app.config.update(SECRET_KEY="x", SESSION_TYPE="filesystem", SESSION_FILE_DIR=str(tmp_path / "s"))
    Session(app)
    app.register_blueprint(accesso.bp)
    app.register_blueprint(web.crea_blueprint(protezione=accesso.login_required, utente_corrente=accesso.utente,
                                              token_utente=accesso.intestazioni, sessione_sol=accesso))
    return app


def test_pagine_protette_e_login(db, tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch).test_client()
    assert c.get("/monitoraggio").headers["Location"] == "/login?next=/monitoraggio"
    assert c.get("/login?next=/monitoraggio").status_code == 200
    assert c.post("/login", data={"ticket": "TICKET_sbagliato_123"}).status_code == 401
    assert c.get("/monitoraggio").status_code == 302
    r = c.post("/login", data={"ticket": TICKET, "next": "/monitoraggio"})
    assert r.status_code == 302 and r.headers["Location"] == "/monitoraggio"
    assert c.get("/monitoraggio").status_code == 200
    assert c.get("/api/sol/sessione").get_json()["collegato"] is True


def test_utente_non_ammesso_non_entra(db, tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch, nome="estraneo").test_client()
    r = c.post("/login", data={"ticket": TICKET})
    assert r.status_code == 403 and "estraneo" in r.get_data(as_text=True)
    assert c.get("/monitoraggio").status_code == 302


def test_next_esterno_rifiutato(db, tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch).test_client()
    assert c.post("/login", data={"ticket": TICKET, "next": "//sito.esempio"}).headers["Location"] == "/monitoraggio"


def test_ticket_mai_su_disco_e_mai_nelle_risposte(db, tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch).test_client()
    c.post("/login", data={"ticket": TICKET})
    assert TICKET not in c.get("/api/sol/sessione").get_data(as_text=True)
    assert TICKET not in c.get("/api/menu").get_data(as_text=True)
    file_scritti = [p for p in (tmp_path / "s").rglob("*") if p.is_file()]
    assert file_scritti and all(TICKET.encode() not in p.read_bytes() for p in file_scritti)


def test_ticket_per_utente_e_scadenza_rilevata(db, tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    c = app.test_client()
    c.post("/login", data={"ticket": TICKET})
    with app.test_request_context():
        session["user"] = "mario.rossi"
        assert accesso.intestazioni() == {"Cookie": f"ticket={TICKET}"}
        session["user"] = "altro.utente"
        assert accesso.intestazioni() is None
        session["user"] = "mario.rossi"
        monkeypatch.setattr(sol_sessione, "identita", lambda t: None)  # scaduto su SOL
        assert accesso.intestazioni() is None
        assert accesso._ticket == {}


def test_verifica_punteggi_con_il_ticket(db, tmp_path, monkeypatch):
    ricevute = []
    monkeypatch.setattr(web.punteggi, "verifica", lambda c, dal, al, i: ricevute.append(i) or {"esito": "ok"})
    c = _app(tmp_path, monkeypatch).test_client()
    c.post("/login", data={"ticket": TICKET})
    assert c.post("/api/punteggi/verifica", json={"mese": "2026-10"}).status_code == 202
    for _ in range(100):
        if ricevute:
            break
        time.sleep(0.01)
    assert ricevute == [{"Cookie": f"ticket={TICKET}"}]


def test_esci_dimentica_il_ticket(db, tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch).test_client()
    c.post("/login", data={"ticket": TICKET})
    assert c.post("/api/sol/esci").status_code == 200
    assert c.get("/api/sol/sessione").get_json()["collegato"] is False
    assert c.post("/api/punteggi/verifica", json={"mese": "2026-10"}).status_code == 401
    assert c.get("/monitoraggio").status_code == 200  # il sito resta accessibile


def test_rdp_con_il_cookie_del_ticket():
    class Client:
        def get_json(self, url, params, intestazioni):
            self.intestazioni = intestazioni
            return {"items": []}
    client = Client()
    sol_rdp.rdp_bando(client, {"Cookie": f"ticket={TICKET}"}, "X")
    assert client.intestazioni == {"Cookie": f"ticket={TICKET}"}
    sol_rdp.rdp_bando(client, "TOK", "X")
    assert client.intestazioni == {"Authorization": "Bearer TOK"}
