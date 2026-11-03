"""Accesso e sessione Selezioni Online dell'avvio di produzione."""
import json
import time
from datetime import datetime

import pytest
from flask import Flask

from monitoraggio import raccolta, scheduler, sol_sessione, web


@pytest.fixture
def auth(monkeypatch):
    """auth.py richiede le variabili OIDC già al primo import."""
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "x")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://esempio.cnr.it/oidc-callback")
    import auth as modulo
    return modulo


class Risposta:
    def __init__(self, status_code=200, corpo=None):
        self.status_code, self._corpo = status_code, corpo

    def json(self):
        if self._corpo is None:
            raise ValueError
        return self._corpo


def test_ticket_da_token_prova_prima_l_header(monkeypatch):
    chiamate = []

    def finto_get(url, **kw):
        chiamate.append(kw)
        return Risposta(200, {"ticket": "T"}) if "headers" in kw else Risposta(401)
    monkeypatch.setattr(sol_sessione.requests, "get", finto_get)
    monkeypatch.setattr(sol_sessione, "valida", lambda t: t == "T")
    assert sol_sessione.ticket_da_token("TOK") == "T"
    assert len(chiamate) == 1 and chiamate[0]["headers"]["Authorization"] == "Bearer TOK"


def test_ticket_da_token_usa_il_parametro_se_l_header_e_ignorato(monkeypatch):
    def finto_get(url, **kw):
        assert url.endswith("/openapi/security/sso/login")
        return Risposta(200, {"ticket": "T"}) if kw.get("params") == {"access_token": "TOK"} else Risposta(401)
    monkeypatch.setattr(sol_sessione.requests, "get", finto_get)
    monkeypatch.setattr(sol_sessione, "valida", lambda t: True)
    assert sol_sessione.ticket_da_token("TOK") == "T"


def test_ticket_da_token_non_valido_o_errore_e_nessun_dettaglio_nei_log(monkeypatch, caplog):
    def finto_get(url, **kw):
        raise sol_sessione.requests.ConnectionError(f"errore su {url}?access_token=TOK")
    monkeypatch.setattr(sol_sessione.requests, "get", finto_get)
    assert sol_sessione.ticket_da_token("TOK") is None
    assert "TOK" not in caplog.text
    monkeypatch.setattr(sol_sessione.requests, "get", lambda url, **kw: Risposta(200, {"ticket": "T"}))
    monkeypatch.setattr(sol_sessione, "valida", lambda t: False)
    assert sol_sessione.ticket_da_token("TOK") is None


def _client(token, **kw):
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint(token_utente=lambda: token, **kw))
    return app.test_client()


def test_produzione_verifica_con_ticket_dal_token(db, monkeypatch):
    monkeypatch.setattr(sol_sessione, "ticket_da_token", lambda t: "TICKET" if t == "TOK" else None)
    ricevute = []
    monkeypatch.setattr(web.punteggi, "verifica", lambda c, dal, al, intest: ricevute.append(intest) or {"esito": "ok"})
    c = _client("TOK")
    assert c.get("/api/sol/sessione").get_json()["collegato"] is True
    assert c.post("/api/punteggi/verifica", json={"mese": "2026-10"}).status_code == 202
    for _ in range(50):
        if ricevute:
            break
        time.sleep(0.02)
    assert ricevute == [{"Cookie": "ticket=TICKET"}]


def test_produzione_senza_ticket_risponde_401(db, monkeypatch):
    monkeypatch.setattr(sol_sessione, "ticket_da_token", lambda t: None)
    r = _client("TOK").post("/api/punteggi/verifica", json={"mese": "2026-10"})
    assert r.status_code == 401 and "SSO" in r.get_json()["error"]
    c = _client(None)
    assert c.get("/api/sol/sessione").get_json()["collegato"] is False
    assert c.post("/api/punteggi/verifica", json={"mese": "2026-10"}).status_code == 401


@pytest.mark.parametrize("claims,ammesso", [
    ({"email": "A@cnr.it", "is_cnr_user": True}, True),
    ({"email": "altro@cnr.it", "is_cnr_user": True}, False),
    ({"email": "a@cnr.it", "is_cnr_user": False}, False),   # stessa email ma accesso SPID
    ({"email": "a@cnr.it"}, False),
    ({"is_cnr_user": True}, False),
])
def test_utenti_ammessi(auth, monkeypatch, claims, ammesso):
    monkeypatch.setenv("UTENTI_AMMESSI", "a@cnr.it, b@cnr.it")
    assert auth._utente_ammesso(claims) is ammesso


def _callback(auth, monkeypatch, claims):
    app = Flask(__name__)
    app.secret_key = "x"
    app.register_blueprint(auth.auth_bp)
    app.add_url_rule("/", "root", lambda: "ok")
    tokens = {"access_token": "A", "refresh_token": "R", "id_token": "I", "expires_in": 300}

    class Token:
        def raise_for_status(self):
            pass

        def json(self):
            return tokens

    class Jwks:
        def __init__(self, url):
            pass

        def get_signing_key_from_jwt(self, t):
            return type("K", (), {"key": "k"})
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: Token())
    monkeypatch.setattr(auth.jwt, "PyJWKClient", Jwks)
    monkeypatch.setattr(auth.jwt, "decode", lambda *a, **k: {"nonce": "N", **claims})
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(oidc_state="S", oidc_nonce="N", oidc_next="/")
    risposta = c.get("/oidc-callback?code=x&state=S")
    with c.session_transaction() as s:
        return risposta.status_code, dict(s)


def test_utente_rifiutato_non_resta_collegato(auth, monkeypatch):
    monkeypatch.setenv("UTENTI_AMMESSI", "a@cnr.it")
    codice, sessione = _callback(auth, monkeypatch, {"email": "altro@cnr.it", "is_cnr_user": True})
    assert codice == 403 and "access_token" not in sessione


def test_utente_ammesso_resta_collegato(auth, monkeypatch):
    monkeypatch.setenv("UTENTI_AMMESSI", "a@cnr.it")
    codice, sessione = _callback(auth, monkeypatch, {"email": "a@cnr.it", "is_cnr_user": True})
    assert codice == 302 and sessione["access_token"] == "A"


def test_modalita_del_giorno(monkeypatch):
    monkeypatch.setenv("RACCOLTA_COMPLETA_GIORNO", "dom")
    assert scheduler.modalita(datetime(2026, 11, 8)) == "completa"
    assert scheduler.modalita(datetime(2026, 11, 9)) == "notturna"


def test_esegui_collega_e_salta_le_raccolte_in_corso(db, monkeypatch):
    chiamate = []

    def finto(conn, fonte, **kw):
        chiamate.append((fonte, kw["modalita"], kw["avviata_da"]))
        if fonte == "urp":
            raise raccolta.RaccoltaInCorso(fonte)
    monkeypatch.setattr(scheduler, "raccogli", finto)
    scheduler.esegui(scheduler.FONTI, "notturna", "pianificata")
    assert chiamate == [("urp", "notturna", "pianificata"), ("sol", "notturna", "pianificata")]


def test_fonti_mai_lette(db):
    assert scheduler.fonti_mai_lette() == ["urp", "sol"]
    rid = raccolta.avvia(db, "urp", "manuale", "test")
    raccolta.chiudi(db, rid, "completata", {})
    assert scheduler.fonti_mai_lette() == ["sol"]


def test_avvio_una_sola_volta_e_disattivabile(monkeypatch):
    avviati = []
    monkeypatch.setattr(scheduler, "_ciclo", lambda: avviati.append(1))
    monkeypatch.setattr(scheduler, "_avviato", scheduler.threading.Event())
    monkeypatch.setenv("RACCOLTA_NOTTURNA", "0")
    assert scheduler.avvia() is False
    monkeypatch.setenv("RACCOLTA_NOTTURNA", "1")
    assert scheduler.avvia() is True and scheduler.avvia() is False


def test_nessun_token_nel_json_di_stato(db, monkeypatch):
    c = _client("SEGRETO")
    assert "SEGRETO" not in json.dumps(c.get("/api/sol/sessione").get_json())
