"""Accesso al sito con il ticket di Selezioni Online."""
import re
import time

from flask import Flask, session
from flask_session import Session

from monitoraggio import accesso, sol_sessione, utenti, web
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
    assert utenti.iniziali() == {"mario.rossi", "anna.bianchi"}


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


def test_programma_invia_il_ticket_e_il_link_vale_una_volta(db, tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch).test_client()
    r = c.post("/api/sol/ticket", data={"ticket": TICKET}, base_url="https://sito.esempio")
    corpo = r.get_json()
    assert r.status_code == 200 and corpo["utente"] == "mario.rossi" and TICKET not in r.get_data(as_text=True)
    assert corpo["link"].startswith("https://sito.esempio/login/completa?codice=")
    percorso = corpo["link"].split("sito.esempio", 1)[1]
    assert c.get("/monitoraggio").status_code == 302  # il ticket da solo non apre sessioni nel browser
    assert c.get(percorso).headers["Location"] == "/monitoraggio"
    assert c.get("/monitoraggio").status_code == 200
    assert c.get("/api/sol/sessione").get_json()["collegato"] is True
    assert c.get(percorso).status_code == 401


def test_link_scaduto_rifiutato(db, tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch).test_client()
    monkeypatch.setattr(accesso, "DURATA_LINK", accesso.timedelta(seconds=-1))
    corpo = c.post("/api/sol/ticket", data={"ticket": TICKET}, base_url="https://sito.esempio").get_json()
    assert c.get(corpo["link"].split("sito.esempio", 1)[1]).status_code == 401


def test_programma_rifiutato_per_utente_non_ammesso(db, tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch, nome="estraneo").test_client()
    r = c.post("/api/sol/ticket", data={"ticket": TICKET})
    assert r.status_code == 403 and r.get_json()["ok"] is False and "link" not in r.get_json()
    assert c.post("/api/sol/ticket", data={"ticket": "x"}).status_code == 400


def test_zip_del_programma(db, tmp_path, monkeypatch):
    import io
    import zipfile
    c = _app(tmp_path, monkeypatch).test_client()
    r = c.get("/login/programma", base_url="https://sito.esempio")
    assert r.status_code == 200 and "Collega-SOL.zip" in r.headers["Content-Disposition"]
    voce = zipfile.ZipFile(io.BytesIO(r.data)).getinfo("Collega-SOL.command")
    assert voce.create_system == 3 and voce.external_attr >> 16 == 0o100755  # file normale ed eseguibile
    testo = zipfile.ZipFile(io.BytesIO(r.data)).read(voce).decode()
    assert testo.startswith("#!/bin/sh") and 'SERVER = "https://sito.esempio"' in testo and "__SERVER__" not in testo


def _link_email(monkeypatch):
    inviate = []
    monkeypatch.setenv("SMTP_SERVER", "smtp.esempio")
    monkeypatch.setenv("MAIL_SENDER", "noreply@esempio.it")
    monkeypatch.setenv("SITO_URL", "https://sito.esempio")
    monkeypatch.setattr(accesso.posta, "invia", lambda d, o, c, sempre_reale=False: inviate.append((d, c, sempre_reale)) or False)
    monkeypatch.setattr(accesso, "_link_email", {})
    monkeypatch.setattr(accesso, "_ultima_email", {})
    return inviate


def _percorso(testo):
    return re.search(r"https://sito\.esempio(/login/visualizzatore\?codice=\S+)", testo).group(1)


def test_visualizzatore_entra_in_sola_lettura_col_link(db, tmp_path, monkeypatch):
    inviate = _link_email(monkeypatch)
    utenti.imposta(db, "anna.bianchi", "lettura", "x")
    c = _app(tmp_path, monkeypatch).test_client()
    assert "Accedi come visualizzatore autorizzato" in c.get("/login").get_data(as_text=True)
    assert c.post("/login/visualizzatore", data={"username": "Anna.Bianchi@altro.it"}).status_code == 200
    assert inviate[0][0] == ["anna.bianchi@cnr.it"]  # mai il dominio scritto da chi chiede
    assert inviate[0][2] is True  # il link arriva alla persona anche con le email di prova attive
    percorso = _percorso(inviate[0][1])
    codice = percorso.split("=")[1]
    # i controlli della posta aprono il link: aprirlo non deve consumarlo né aprire la sessione
    assert c.get(percorso).status_code == 200 and c.get(percorso).status_code == 200
    assert c.get("/monitoraggio").status_code == 302
    assert c.post("/login/visualizzatore/entra", data={"codice": codice}).headers["Location"] == "/monitoraggio"
    assert c.get("/monitoraggio").status_code == 200
    assert c.post("/login/visualizzatore/entra", data={"codice": codice}).status_code == 401  # una volta sola
    assert c.get(percorso).status_code == 401
    assert c.get("/api/sol/sessione").get_json()["disponibile"] is False
    assert [r["azione"] for r in utenti.registro(db)][0] == "link_accesso"


def test_stessa_risposta_per_chi_non_e_autorizzato(db, tmp_path, monkeypatch):
    inviate = _link_email(monkeypatch)
    utenti.imposta(db, "anna.bianchi", "lettura", "x")
    c = _app(tmp_path, monkeypatch).test_client()
    si = c.post("/login/visualizzatore", data={"username": "anna.bianchi"})
    no = c.post("/login/visualizzatore", data={"username": "estraneo"})
    assert si.status_code == no.status_code == 200 and si.get_data() == no.get_data() and len(inviate) == 1


def test_link_non_ripetuto_subito_e_indirizzo_in_tabella(db, tmp_path, monkeypatch):
    inviate = _link_email(monkeypatch)
    utenti.imposta(db, "anna.bianchi", "lettura", "x", "anna@cnr.it")
    c = _app(tmp_path, monkeypatch).test_client()
    for _ in range(3):
        c.post("/login/visualizzatore", data={"username": "anna.bianchi"})
    assert len(inviate) == 1 and inviate[0][0] == ["anna@cnr.it"]


def test_amministratore_col_link_resta_in_lettura(db, tmp_path, monkeypatch):
    inviate = _link_email(monkeypatch)
    app = _app(tmp_path, monkeypatch)
    c = app.test_client()
    c.post("/login/visualizzatore", data={"username": "mario.rossi"})  # è in UTENTI_AMMESSI
    codice = _percorso(inviate[0][1]).split("=")[1]
    c.post("/login/visualizzatore/entra", data={"codice": codice})
    with c.session_transaction() as s:
        assert s["solo_lettura"] is True and s["user"] == "mario.rossi"
    with app.test_request_context():
        session["user"], session["solo_lettura"] = "mario.rossi", True
        assert utenti.ruolo_corrente() == "lettura"
        session["solo_lettura"] = False
        assert utenti.ruolo_corrente() == "amministratore"


def test_utente_tolto_non_usa_il_link(db, tmp_path, monkeypatch):
    inviate = _link_email(monkeypatch)
    utenti.imposta(db, "anna.bianchi", "lettura", "x")
    c = _app(tmp_path, monkeypatch).test_client()
    c.post("/login/visualizzatore", data={"username": "anna.bianchi"})
    utenti.togli(db, "anna.bianchi", "x")
    codice = _percorso(inviate[0][1]).split("=")[1]
    assert c.post("/login/visualizzatore/entra", data={"codice": codice}).status_code == 401


def test_senza_posta_il_pulsante_lo_dice(db, tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_SERVER", raising=False)
    monkeypatch.delenv("MAIL_SENDER", raising=False)
    c = _app(tmp_path, monkeypatch).test_client()
    assert c.post("/login/visualizzatore", data={"username": "x.y"}).status_code == 503
