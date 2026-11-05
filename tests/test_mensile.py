"""Monitoraggio mensile, ruoli, Excel e invio delle email (spec 006)."""
import io
import time
from datetime import date

import openpyxl
import pytest
from flask import Flask, session
from flask_session import Session

from monitoraggio import excel_mese, mensile, posta, punteggi, utenti
from monitoraggio import web as web_modulo
from monitoraggio.mensile_web import crea_blueprint_mensile
from monitoraggio.web import crea_blueprint, crea_blueprint_pagine_esistenti
from tests.test_collegamento import doc, salva, scheda


@pytest.fixture
def ambiente(db, tmp_path, monkeypatch):
    monkeypatch.setenv("UTENTI_AMMESSI", "capo.ufficio")
    for nome in ("SMTP_SERVER", "MAIL_SENDER", "MAIL_REPLY_TO", "MAIL_PROVA", "SMTP_STARTTLS", "SMTP_PORT"):
        monkeypatch.delenv(nome, raising=False)

    def base(fn):
        def _controllo(*a, **k):
            if not session.get("user"):
                return "login", 302
            return fn(*a, **k)
        _controllo.__name__ = fn.__name__
        return _controllo

    protezione, solo_admin = utenti.protezioni(base)
    app = Flask(__name__)
    app.config.update(SECRET_KEY="x", SESSION_TYPE="filesystem", SESSION_FILE_DIR=str(tmp_path / "s"))
    Session(app)
    app.register_blueprint(crea_blueprint(protezione=protezione, solo_admin=solo_admin, ruolo_corrente=utenti.ruolo_corrente,
                                          utente_corrente=utenti.corrente))
    app.register_blueprint(crea_blueprint_pagine_esistenti(protezione=protezione, solo_admin=solo_admin))
    app.register_blueprint(crea_blueprint_mensile(protezione=protezione, solo_admin=solo_admin, utente_corrente=utenti.corrente))

    def client(nome="capo.ufficio"):
        c = app.test_client()
        with c.session_transaction() as s:
            s["user"] = nome
        return c
    return client


def _configura_posta(monkeypatch, inviati, **extra):
    monkeypatch.setenv("SMTP_SERVER", "smtp.esempio")
    monkeypatch.setenv("SMTP_PORT", "25")
    monkeypatch.setenv("MAIL_SENDER", "noreply@esempio.it")
    monkeypatch.setenv("MAIL_REPLY_TO", "ufficio@esempio.it")
    for chiave, valore in extra.items():
        monkeypatch.setenv(chiave, valore)
    posta.salva_prova("MAIL_PROVA" in extra, extra.get("MAIL_PROVA"), "test")

    class Smtp:
        def __init__(self, host, port, timeout):
            self.host, self.port = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, messaggio):
            inviati.append(messaggio)
    monkeypatch.setattr(posta.smtplib, "SMTP", Smtp)


def _rdp(db, email="rdp@cnr.it", numero="367.479"):
    salva(db, "sol", [scheda("sol", f"s{numero}", f"{numero} CTER", numero)])
    sid = db.execute("SELECT id FROM scheda WHERE numero_bando = ?", (numero,)).fetchone()[0]
    db.execute("INSERT INTO referente (scheda_id, chiave, nome, cognome, email, username, attivo, prima_rilevazione, "
               "ultima_rilevazione) VALUES (?, 'a', 'Anna', 'Esempio', ?, 'a', 1, 'x', 'x')", (sid, email))


# --- ruoli

def test_lettura_vede_ma_non_modifica(ambiente, db):
    admin = ambiente()
    assert admin.post("/api/utenti", json={"username": "Anna.Bianchi@cnr.it", "ruolo": "lettura"}).status_code == 200
    c = ambiente("anna.bianchi")
    assert c.get("/monitoraggio").status_code == 200 and c.get("/api/monitoraggi").status_code == 200
    assert c.get("/api/menu").get_json()["ruolo"] == "lettura"
    for metodo, url in [("post", "/api/raccolta/avvia"), ("post", "/api/run"), ("post", "/api/punteggi/verifica"),
                        ("post", "/api/referenti/aggiorna"), ("post", "/api/segreteria/carica"), ("post", "/api/monitoraggi"),
                        ("post", "/api/utenti"), ("get", "/api/utenti"), ("get", "/monitoraggio/utenti")]:
        assert getattr(c, metodo)(url).status_code == 403, url


def test_voce_utenti_solo_per_amministratori(ambiente):
    ambiente().post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    voci = lambda c: {v["titolo"] for g in c.get("/api/menu").get_json()["gruppi"] for v in g["voci"]}  # noqa: E731
    assert "Impostazioni" in voci(ambiente())
    voci_lettura = voci(ambiente("lettore.uno"))
    assert "Impostazioni" not in voci_lettura and "Monitoraggi mensili" in voci_lettura
    assert ambiente().get("/monitoraggio/utenti").headers["Location"] == "/monitoraggio/impostazioni#utenti"


def test_togliere_ha_effetto_alla_richiesta_successiva(ambiente, db):
    admin = ambiente()
    admin.post("/api/utenti", json={"username": "anna.bianchi", "ruolo": "lettura"})
    c = ambiente("anna.bianchi")
    assert c.get("/api/monitoraggi").status_code == 200
    assert admin.delete("/api/utenti/anna.bianchi").status_code == 200
    assert c.get("/api/monitoraggi").status_code == 403
    azioni = [r["azione"] for r in utenti.registro(db)]
    assert azioni == ["togli", "imposta"]
    assert utenti.registro(db)[0]["autore"] == "capo.ufficio"


def test_amministratore_iniziale_non_si_tocca(ambiente):
    admin = ambiente()
    assert admin.delete("/api/utenti/capo.ufficio").status_code == 409
    assert admin.post("/api/utenti", json={"username": "capo.ufficio", "ruolo": "lettura"}).status_code == 409
    assert admin.get("/api/monitoraggi").status_code == 200


def test_sconosciuto_rifiutato_e_ruolo_non_valido(ambiente):
    assert ambiente("estraneo").get("/monitoraggio").status_code == 403
    assert ambiente().post("/api/utenti", json={"username": "x", "ruolo": "capo"}).status_code == 400


# --- monitoraggio

def test_anno_corrente_e_mese_dei_dati():
    assert mensile.mese_anno_corrente(5, date(2026, 11, 4)) == "2026-05"
    assert mensile.mese_precedente("2026-05") == "2026-04" and mensile.mese_precedente("2026-01") == "2025-12"
    for sbagliato in (0, 13, "5", None):
        with pytest.raises(ValueError):
            mensile.mese_anno_corrente(sbagliato)


def test_crea_senza_duplicare(ambiente):
    admin = ambiente()
    anno = date.today().year
    r = admin.post("/api/monitoraggi", json={"numero_mese": 5})
    assert r.status_code == 201 and r.get_json()["mese"] == f"{anno}-05"
    d = admin.get(f"/api/monitoraggi/{anno}-05").get_json()
    assert d["mese_dati"] == f"{anno}-04" and d["etichetta"] == f"maggio {str(anno)[2:]}"
    assert d["dal"] == f"{anno}-04-01" and d["al"] == f"{anno}-04-30"
    assert d["link_vista"] == f"/monitoraggio?monitoraggio={anno}-05&mese={anno}-04"
    again = admin.post("/api/monitoraggi", json={"numero_mese": 5})
    assert again.status_code == 200 and again.get_json()["creato"] is False
    assert len(admin.get("/api/monitoraggi").get_json()["monitoraggi"]) == 1
    assert admin.post("/api/monitoraggi", json={"numero_mese": 13}).status_code == 400
    assert admin.get("/api/monitoraggi/2026-13").status_code == 404


def test_cambio_mese_dei_dati(ambiente):
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    assert admin.put(f"/api/monitoraggi/{mese}", json={"mese_dati": "2026-02"}).get_json()["mese_dati"] == "2026-02"
    assert admin.put(f"/api/monitoraggi/{mese}", json={"mese_dati": "sbagliato"}).status_code == 400


# --- Excel

def test_nomi_dei_file():
    assert excel_mese.nome_scorrimenti("2026-05") == "MODELLO-scorrimenti-maggio-26.xlsx"
    assert excel_mese.nome_graduatorie("2026-05") == "MODELLO-Graduatorie-e-bandi-pubblicati-maggio-26.xlsx"


def test_scorrimenti_vuoto_con_tipologia_e_nota():
    wb = openpyxl.load_workbook(io.BytesIO(excel_mese.excel_scorrimenti()))
    assert wb.sheetnames == ["CTER 6", "CTER 7", "FUNZ 5", "OTP", "DT", "RIC", "PT"]
    for ws in wb.worksheets:
        assert ws["H2"].value == "TIPOLOGIA" and "subentro" in ws["H2"].comment.text and "6 mesi" in ws["H2"].comment.text
        assert ws["G2"].value == "PROVVEDIMENTO RECLUTAMENTO"
        assert not ws.data_validations.dataValidation  # niente menu a tendina
        assert ws.auto_filter.ref == "A2:H22" and "A1:H1" in [str(m) for m in ws.merged_cells.ranges]
        assert ws["H2"].fill.fgColor.rgb == ws["G2"].fill.fgColor.rgb
        assert all(ws.cell(r, c).value is None for r in range(3, 23) for c in range(1, 9))


def test_download_vuoti_rinominati(ambiente):
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    aa = mese[2:4]
    r = admin.get(f"/api/monitoraggi/{mese}/excel/scorrimenti")
    assert r.status_code == 200 and f"MODELLO-scorrimenti-maggio-{aa}.xlsx" in r.headers["Content-Disposition"]
    r = admin.get(f"/api/monitoraggi/{mese}/excel/graduatorie")
    assert f"MODELLO-Graduatorie-e-bandi-pubblicati-maggio-{aa}.xlsx" in r.headers["Content-Disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames == ["Bandi pubblicati", "Graduatorie pubblicate", "Mobilità pubblicate", "Graduatorie mobilità"]
    assert all(c.value is None for ws in wb.worksheets for riga in ws.iter_rows(min_row=2) for c in riga)
    assert admin.get(f"/api/monitoraggi/{mese}/excel/altro").status_code == 404


def test_graduatorie_con_dati_e_giallo(db, monkeypatch):
    salva(db, "sol", [scheda("sol", "s1", "367.1 CTER", "367.1", data="2026-04-10", documenti=[doc("g", "graduatoria", "11", "2026-04-20")]),
                      scheda("sol", "s2", "01-COMANDO", "01", data="2026-04-11", tipologia="comando",
                             documenti=[doc("h", "graduatoria", "12", "2026-04-21")])])
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = 's1'").fetchone()[0]
    monkeypatch.setattr(punteggi, "_candidati", {sid: {"candidati": [
        {"cognome": "Rossi", "nome": "Mario", "graduatoria": 1, "esito": "V", "numero_protocollo_graduatoria": "11"},
        {"cognome": "Verdi", "nome": "Anna", "graduatoria": 2, "esito": "I", "numero_protocollo_graduatoria": ""}]}})
    wb = openpyxl.load_workbook(io.BytesIO(excel_mese.excel_graduatorie(db, "2026-04-01", "2026-04-30")))
    bandi, mobilita = wb["Bandi pubblicati"], wb["Mobilità pubblicate"]
    assert [bandi.cell(2, 1).value, bandi.cell(3, 1).value, bandi.cell(3, 7).value] == ["Codice bando", "367.1 CTER", "10/04/2026"]
    assert mobilita.cell(3, 1).value == "01-COMANDO" and bandi.cell(4, 1).value is None
    grad = wb["Graduatorie pubblicate"]
    assert [c.value for c in grad[2]][:2] == ["Codice bando", "Sede di lavoro"] and len(list(grad[2])) >= 20
    assert grad.cell(3, 7).value == "ROSSI" and grad.cell(3, 1).fill.fgColor.rgb != "00" + punteggi.GIALLO_EXCEL
    assert grad.cell(4, 7).value == "VERDI" and grad.cell(4, 1).fill.fgColor.rgb.endswith(punteggi.GIALLO_EXCEL)
    assert grad.freeze_panes == "A3"
    # graduatoria di mobilità senza verifica: riga col codice e avviso, non un foglio vuoto
    assert "verifica dei punteggi" in wb["Graduatorie mobilità"].cell(3, 16).value
    assert excel_mese.graduatorie_senza_elenco(db, "2026-04-01", "2026-04-30") == 1
    dump = "\n".join(str(r) for t in ("scheda", "documento", "impostazione") for r in map(tuple, db.execute(f"SELECT * FROM {t}")))
    assert "Rossi" not in dump and "Verdi" not in dump


# --- email di compilazione

def test_testo_con_segnaposto(db):
    m = mensile.crea(db, "2026-05", None, "x")
    mensile.aggiorna(db, "2026-05", {"link_scorrimenti": "https://drive/a", "link_graduatorie": "https://drive/b"})
    mensile.salva_impostazioni_email(db, {"destinatari": "uno@cnr.it; due@cnr.it\nuno@cnr.it"}, "x")
    e = mensile.email_compilazione(db, mensile.leggi(db, "2026-05"))
    assert e["destinatari"] == ["uno@cnr.it", "due@cnr.it"] and e["mancanti"] == []
    assert e["oggetto"] == "Monitoraggio maggio 26: predisposizione dei dati"
    for atteso in ("mese di maggio 26", "scorrimenti del mese di aprile", "MONITORAGGIO -> 2026 -> MAGGIO", "https://drive/a",
                   "https://drive/b", "MODELLO-scorrimenti-maggio-26.xlsx", "MODELLO-Graduatorie-e-bandi-pubblicati-maggio-26.xlsx"):
        assert atteso in e["corpo"], atteso
    assert "{" not in e["corpo"] and m["mese_dati"] == "2026-04"


def test_invio_bloccato_se_manca_qualcosa(ambiente, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    r = admin.post(f"/api/monitoraggi/{mese}/email-compilazione/invia")
    assert r.status_code == 400 and "link" in r.get_json()["error"] and "destinatari" in r.get_json()["error"]
    assert inviati == []


def test_invio_della_richiesta_e_registro(ambiente, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    admin.put(f"/api/monitoraggi/{mese}", json={"link_scorrimenti": "https://a", "link_graduatorie": "https://b"})
    admin.put("/api/impostazioni/email", json={"destinatari": "uno@cnr.it, due@cnr.it"})
    assert admin.post(f"/api/monitoraggi/{mese}/email-compilazione/invia").get_json() == {"ok": True, "prova": False}
    m = inviati[0]
    assert m["From"] == "noreply@esempio.it" and m["Reply-To"] == "ufficio@esempio.it" and m["To"] == "uno@cnr.it, due@cnr.it"
    assert "https://a" in m.get_content()
    voce = admin.get(f"/api/monitoraggi/{mese}").get_json()["invii"][0]
    assert voce["esito"] == "inviata" and voce["utente"] == "capo.ufficio" and voce["tipo"] == "compilazione"


def test_testo_del_mese_e_testo_generale(ambiente):
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    d = admin.put(f"/api/monitoraggi/{mese}", json={"testo": "Solo {mese}"}).get_json()
    assert d["email"]["corpo"].startswith("Solo maggio") and d["email"]["personalizzato"] is True
    d = admin.put(f"/api/monitoraggi/{mese}", json={"testo": ""}).get_json()
    assert d["email"]["personalizzato"] is False and "Buongiorno" in d["email"]["corpo"]
    admin.put("/api/impostazioni/email", json={"testo": "Generale {mese_dati}"})
    assert admin.get(f"/api/monitoraggi/{mese}").get_json()["email"]["corpo"] == "Generale aprile"


def test_destinatario_non_valido_rifiutato(ambiente):
    assert ambiente().put("/api/impostazioni/email", json={"destinatari": "senza-chiocciola"}).status_code == 400


# --- solleciti

def _sollecito(numero="367.479", destinatari=("rdp@cnr.it",), **extra):
    return {"numero_bando": numero, "destinatari": list(destinatari), "oggetto": f"{numero} — Monitoraggio",
            "corpo": "Rilievi del bando", **extra}


def test_sollecito_inviato_segnato_con_autore(ambiente, db, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    _rdp(db)
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    url = f"/api/monitoraggi/{mese}/solleciti"
    assert admin.post(url + "/invia", json=_sollecito()).get_json()["ok"] is True
    assert inviati[0]["To"] == "rdp@cnr.it"
    stato = admin.get(url).get_json()["solleciti"]["367.479"]
    assert stato["stato"] == "inviata" and stato["autore"] == "capo.ufficio" and stato["destinatari"] == "rdp@cnr.it"
    r = admin.post(url + "/invia", json=_sollecito())
    assert r.status_code == 409 and r.get_json()["gia_inviato"] and len(inviati) == 1
    assert admin.post(url + "/invia", json=_sollecito(conferma=True)).status_code == 200 and len(inviati) == 2


def test_sollecito_controlli_lato_server(ambiente, db, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    _rdp(db)
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    url = f"/api/monitoraggi/{mese}/solleciti/invia"
    r = admin.post(url, json=_sollecito(destinatari=["altro@esempio.it"]))
    assert r.status_code == 400 and "altro@esempio.it" in r.get_json()["error"]
    r = admin.post(url, json={**_sollecito(), "corpo": "Candidato RSSMRA80A01H501U"})
    assert r.status_code == 400 and "codice fiscale" in r.get_json()["error"]
    assert admin.post(url, json=_sollecito(destinatari=[])).status_code == 400
    assert inviati == []


def test_lettura_non_invia_e_non_spunta(ambiente, db, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    _rdp(db)
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    c = ambiente("lettore.uno")
    assert c.post(f"/api/monitoraggi/{mese}/solleciti/invia", json=_sollecito()).status_code == 403
    assert c.put(f"/api/monitoraggi/{mese}/solleciti/367.479", json={"inviata": True}).status_code == 403
    assert c.get(f"/api/monitoraggi/{mese}/excel/scorrimenti").status_code == 403
    assert c.get(f"/api/monitoraggi/{mese}/solleciti").status_code == 200 and inviati == []


def test_errore_di_invio_non_segna_inviata(ambiente, db, monkeypatch):
    _configura_posta(monkeypatch, [])

    def rotto(*a, **k):
        raise OSError("connessione rifiutata")
    monkeypatch.setattr(posta.smtplib, "SMTP", rotto)
    _rdp(db)
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    r = admin.post(f"/api/monitoraggi/{mese}/solleciti/invia", json=_sollecito())
    assert r.status_code == 502
    assert admin.get(f"/api/monitoraggi/{mese}/solleciti").get_json()["solleciti"] == {}
    assert admin.get(f"/api/monitoraggi/{mese}").get_json()["invii"][0]["esito"] == "errore"


def test_modalita_di_prova_non_segna_inviata(ambiente, db, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati, MAIL_PROVA="prova@cnr.it")
    _rdp(db)
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    assert admin.post(f"/api/monitoraggi/{mese}/solleciti/invia", json=_sollecito()).get_json()["prova"] is True
    m = inviati[0]
    assert m["To"] == "prova@cnr.it" and m["Subject"].startswith("[PROVA]") and "rdp@cnr.it" in m.get_content()
    assert admin.get(f"/api/monitoraggi/{mese}/solleciti").get_json()["solleciti"] == {}


def test_senza_configurazione_resta_la_spunta(ambiente, db):
    _rdp(db)
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    url = f"/api/monitoraggi/{mese}/solleciti"
    assert admin.get(url).get_json()["posta"]["configurata"] is False
    assert admin.post(url + "/invia", json=_sollecito()).status_code == 502
    assert admin.put(url + "/367.479", json={"inviata": True}).get_json()["solleciti"]["367.479"]["stato"] == "inviata_a_mano"
    assert admin.put(url + "/367.479", json={"inviata": False}).get_json()["solleciti"] == {}


def test_starttls_solo_se_richiesto(db, monkeypatch):
    chiamate = []
    _configura_posta(monkeypatch, [])

    class Smtp:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            chiamate.append("starttls")

        def send_message(self, m):
            pass
    monkeypatch.setattr(posta.smtplib, "SMTP", Smtp)
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    posta.invia(["a@b.it"], "o", "c")
    assert chiamate == []
    monkeypatch.setenv("SMTP_STARTTLS", "1")
    posta.invia(["a@b.it"], "o", "c")
    assert chiamate == ["starttls"]


def test_sollecito_per_codice_con_i_referenti_del_bando(ambiente, db, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    salva(db, "sol", [scheda("sol", "s5", "367.434 CA - TRIESTE Codice 05", "367.434", sotto="05"),
                      scheda("sol", "s13", "367.434 CA - ROMA Codice 13", "367.434", sotto="13")])
    from monitoraggio import collegamento
    collegamento.collega(db)
    for id_esterno, email in (("s5", "trieste@cnr.it"), ("s13", "roma@cnr.it")):
        sid = db.execute("SELECT id FROM scheda WHERE id_esterno = ?", (id_esterno,)).fetchone()[0]
        db.execute("INSERT INTO referente (scheda_id, chiave, nome, cognome, email, username, attivo, prima_rilevazione, "
                   "ultima_rilevazione) VALUES (?, 'a', 'A', 'B', ?, 'a', 1, 'x', 'x')", (sid, email))
    admin = ambiente()
    mese = admin.post("/api/monitoraggi", json={"numero_mese": 5}).get_json()["mese"]
    url = f"/api/monitoraggi/{mese}/solleciti"
    codice = "367.434 CA - TRIESTE Codice 05"
    r = admin.post(url + "/invia", json=_sollecito(codice, ["trieste@cnr.it"]))
    assert r.status_code == 200 and inviati[0]["To"] == "trieste@cnr.it"
    stati = admin.get(url).get_json()["solleciti"]
    assert list(stati) == [codice]  # lo stato vale per il codice, non per tutto il bando
    assert admin.put(f"{url}/367.434 CA - ROMA Codice 13", json={"inviata": True}).status_code == 200
    assert len(admin.get(url).get_json()["solleciti"]) == 2
    assert admin.post(url + "/invia", json=_sollecito("367.434 CA - ROMA Codice 13", ["estraneo@cnr.it"])).status_code == 400


# --- chiusura

def _mese_con_dati(ambiente, db):
    from monitoraggio import collegamento
    salva(db, "sol", [scheda("sol", "s1", "367.479 CTER", "367.479", documenti=[doc("g1", "graduatoria", "1001", "2026-04-12")])])
    salva(db, "urp", [scheda("urp", "/node/1", "367.479 CTER", "367.479", documenti=[doc("g2", "graduatoria", "1002", "2026-04-12")])])
    collegamento.collega(db)
    admin = ambiente()
    mese = mensile.crea(db, "2026-05", None, "capo.ufficio")["mese"]
    return admin, mese


def test_chiusura_salva_la_fotografia_che_non_cambia(ambiente, db):
    admin, mese = _mese_con_dati(ambiente, db)
    admin.put(f"/api/monitoraggi/{mese}/solleciti/367.479 CTER", json={"inviata": True})
    d = admin.post(f"/api/monitoraggi/{mese}/chiudi").get_json()
    assert d["stato"] == "chiuso" and d["chiuso_da"] == "capo.ufficio"
    f = d["fotografia"]
    assert f["totale"] == 1 and f["difformi"] == 1 and f["inviate"] == 1
    r = f["righe"][0]
    assert (r["codice"], r["sol_protocollo"], r["urp_protocollo"]) == ("367.479 CTER", "1001", "1002")
    assert "protocollo diverso" in r["note"][0] and r["sollecito_stato"] == "inviata_a_mano"
    # cambiano le fonti: la fotografia resta uguale
    db.execute("UPDATE documento SET presente = 0")
    db.execute("DELETE FROM referente")
    assert admin.get(f"/api/monitoraggi/{mese}").get_json()["fotografia"]["righe"][0]["sol_protocollo"] == "1001"
    assert [e["azione"] for e in f["eventi"]] == ["chiuso", "creato"]


def test_chiuso_non_si_modifica_finche_non_si_riapre(ambiente, db, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    admin, mese = _mese_con_dati(ambiente, db)
    admin.post(f"/api/monitoraggi/{mese}/chiudi")
    assert admin.post(f"/api/monitoraggi/{mese}/chiudi").status_code == 409
    assert admin.put(f"/api/monitoraggi/{mese}", json={"mese_dati": "2026-01"}).status_code == 409
    assert admin.put(f"/api/monitoraggi/{mese}/solleciti/x", json={"inviata": True}).status_code == 409
    assert admin.post(f"/api/monitoraggi/{mese}/solleciti/invia", json=_sollecito()).status_code == 409
    assert admin.post(f"/api/monitoraggi/{mese}/email-compilazione/invia").status_code == 409
    assert inviati == []
    d = admin.post(f"/api/monitoraggi/{mese}/riapri").get_json()
    assert d["stato"] == "aperto" and d["fotografia"]["totale"] == 1  # le versioni restano
    assert admin.put(f"/api/monitoraggi/{mese}", json={"mese_dati": "2026-04"}).status_code == 200
    assert admin.post(f"/api/monitoraggi/{mese}/chiudi").get_json()["fotografia"]["totale"] == 1
    assert [e["azione"] for e in admin.get(f"/api/monitoraggi/{mese}").get_json()["fotografia"]["eventi"]] == ["chiuso", "riaperto", "chiuso", "creato"]


def test_lettura_vede_il_chiuso_ma_non_chiude(ambiente, db):
    admin, mese = _mese_con_dati(ambiente, db)
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    c = ambiente("lettore.uno")
    assert c.post(f"/api/monitoraggi/{mese}/chiudi").status_code == 403
    admin.post(f"/api/monitoraggi/{mese}/chiudi")
    assert c.get(f"/api/monitoraggi/{mese}").get_json()["fotografia"]["totale"] == 1
    assert c.post(f"/api/monitoraggi/{mese}/riapri").status_code == 403


def test_nessun_dato_dei_candidati_nella_fotografia(ambiente, db, monkeypatch):
    admin, mese = _mese_con_dati(ambiente, db)
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = 's1'").fetchone()[0]
    monkeypatch.setattr(punteggi, "_candidati", {sid: {"candidati": [
        {"cognome": "Rossi", "nome": "Mario", "codice_fiscale": "RSSMRA80A01H501U", "esito": "V"}]}})
    admin.post(f"/api/monitoraggi/{mese}/chiudi")
    dump = "\n".join(str(tuple(r)) for t in ("monitoraggio_riga", "monitoraggio_punteggi", "monitoraggio_fonte", "monitoraggio_evento")
                     for r in db.execute(f"SELECT * FROM {t}"))
    assert "Rossi" not in dump and "RSSMRA" not in dump


def test_aggiornamento_da_uno_schema_precedente(tmp_path, monkeypatch):
    import sqlite3
    from monitoraggio import config, db as dbmod
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    c = sqlite3.connect(config.db_path())
    c.executescript("CREATE TABLE schema_version(versione INTEGER); INSERT INTO schema_version VALUES (8);"
                    "CREATE TABLE monitoraggio_mese (mese TEXT PRIMARY KEY, mese_dati TEXT NOT NULL, link_scorrimenti TEXT, "
                    "link_graduatorie TEXT, oggetto TEXT, testo TEXT, creato_da TEXT, creato_il TEXT NOT NULL);"
                    "INSERT INTO monitoraggio_mese (mese, mese_dati, creato_il) VALUES ('2026-10', '2026-09', 'x');")
    c.commit()
    c.close()
    conn = dbmod.connetti()
    dbmod.inizializza(conn)
    assert conn.execute("SELECT stato FROM monitoraggio_mese").fetchone()["stato"] == "aperto"  # i dati restano
    assert conn.execute("SELECT versione FROM schema_version").fetchone()[0] == dbmod.SCHEMA_VERSION


def test_avviso_se_i_dati_non_sono_su_un_volume(tmp_path, monkeypatch):
    from monitoraggio import config
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config.os.path, "ismount", lambda p: False)
    assert "volume" in config.avviso_dati_non_persistenti()
    monkeypatch.setattr(config.os.path, "ismount", lambda p: True)
    assert config.avviso_dati_non_persistenti() is None


def test_riapro_correggo_aggiorno_e_richiudo(ambiente, db):
    from monitoraggio import collegamento
    admin, mese = _mese_con_dati(ambiente, db)
    admin.put(f"/api/monitoraggi/{mese}/solleciti/367.479 CTER", json={"inviata": True})
    prima = admin.post(f"/api/monitoraggi/{mese}/chiudi").get_json()["fotografia"]["righe"][0]
    assert prima["difforme"] == 1 and prima["sol_protocollo"] == "1001"
    # i dati raccolti restano e si aggiornano anche a mese chiuso: la fotografia no
    admin.post(f"/api/monitoraggi/{mese}/riapri")
    salva(db, "sol", [scheda("sol", "s1", "367.479 CTER", "367.479", documenti=[doc("g1", "graduatoria", "1002", "2026-04-12")])])
    collegamento.collega(db)
    dopo = admin.post(f"/api/monitoraggi/{mese}/chiudi").get_json()["fotografia"]
    riga = dopo["righe"][0]
    assert riga["sol_protocollo"] == "1002" and riga["difforme"] == 0 and riga["note"] == []
    assert riga["sollecito_stato"] == "inviata_a_mano"  # la spunta non si perde


def test_i_dati_sincronizzati_non_dipendono_dalla_chiusura(db):
    from monitoraggio import collegamento
    salva(db, "sol", [scheda("sol", "s1", "367.479 CTER", "367.479", documenti=[doc("g1", "graduatoria", "1001", "2026-04-12")])])
    collegamento.collega(db)
    mensile.crea(db, "2026-05", None, "x")
    assert db.execute("SELECT COUNT(*) FROM documento").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM monitoraggio_riga").fetchone()[0] == 0  # nessuna chiusura: i dati ci sono già
    mensile.segna(db, "2026-05", "367.479 CTER", "inviata_a_mano", "x")
    assert len(mensile.solleciti(db, "2026-05")) == 1


def test_nuova_versione_dopo_la_correzione_su_sol(ambiente, db):
    from monitoraggio import collegamento
    admin, mese = _mese_con_dati(ambiente, db)
    uno = admin.post(f"/api/monitoraggi/{mese}/chiudi").get_json()["fotografia"]
    assert (uno["versione"], uno["ultima"], uno["difformi"], uno["dati_piu_recenti"]) == (1, 1, 1, [])
    assert admin.post(f"/api/monitoraggi/{mese}/riapri").status_code == 200
    assert admin.post(f"/api/monitoraggi/{mese}/nuova-versione").status_code == 409  # da aperto si chiude
    admin.post(f"/api/monitoraggi/{mese}/chiudi")
    # correggono SOL, si rilegge e si genera la nuova versione senza riaprire
    salva(db, "sol", [scheda("sol", "s1", "367.479 CTER", "367.479", documenti=[doc("g1", "graduatoria", "1002", "2026-04-12")])])
    collegamento.collega(db)
    db.execute("INSERT INTO raccolta (fonte, modalita, inizio, fine, esito) VALUES ('sol', 'manuale', '2030-01-01T00:00:00Z', "
               "'2030-01-01T00:00:00Z', 'completata')")
    assert admin.get(f"/api/monitoraggi/{mese}").get_json()["fotografia"]["dati_piu_recenti"] == ["raccolta dei dati"]
    d = admin.post(f"/api/monitoraggi/{mese}/nuova-versione", json={"motivo": "SOL corretto"}).get_json()
    f = d["fotografia"]
    assert d["stato"] == "chiuso" and f["versione"] == f["ultima"] == 3
    assert f["difformi"] == 0 and f["righe"][0]["sol_protocollo"] == "1002"
    assert [(v["versione"], v["difformi"], v["motivo"]) for v in f["versioni"]] == [(3, 0, "SOL corretto"), (2, 1, None), (1, 1, None)]
    # le versioni precedenti restano uguali
    vecchia = admin.get(f"/api/monitoraggi/{mese}?versione=1").get_json()["fotografia"]
    assert vecchia["versione"] == 1 and vecchia["righe"][0]["sol_protocollo"] == "1001" and vecchia["difformi"] == 1
    assert admin.get(f"/api/monitoraggi/{mese}?versione=99").get_json()["fotografia"]["versione"] == 3


def test_verifica_punteggi_dopo_la_versione_viene_segnalata(ambiente, db):
    admin, mese = _mese_con_dati(ambiente, db)
    admin.post(f"/api/monitoraggi/{mese}/chiudi")
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = 's1'").fetchone()[0]
    db.execute("INSERT INTO punteggi_verifica (scheda_id, verificato_il, domande, con_punteggi, vincitori, idonei, scorrimento, "
               "senza_protocollo, esito) VALUES (?, '2030-01-01T00:00:00Z', 5, 5, 1, 4, 0, 0, 'completi')", (sid,))
    f = admin.get(f"/api/monitoraggi/{mese}").get_json()["fotografia"]
    assert f["dati_piu_recenti"] == ["verifica dei punteggi"]
    assert all(p["con_punteggi"] is None for p in f["punteggi"])  # la versione salvata non cambia
    nuova = admin.post(f"/api/monitoraggi/{mese}/nuova-versione").get_json()["fotografia"]
    assert [p["con_punteggi"] for p in nuova["punteggi"] if p["codice"] == "367.479 CTER"] == [5]


def test_solo_amministratori_generano_versioni(ambiente, db):
    admin, mese = _mese_con_dati(ambiente, db)
    admin.post(f"/api/monitoraggi/{mese}/chiudi")
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    assert ambiente("lettore.uno").post(f"/api/monitoraggi/{mese}/nuova-versione").status_code == 403


def test_fotografie_della_versione_9_diventano_versione_1(tmp_path, monkeypatch):
    import sqlite3
    from monitoraggio import config, db as dbmod
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    c = sqlite3.connect(config.db_path())
    c.executescript("""
        CREATE TABLE schema_version(versione INTEGER); INSERT INTO schema_version VALUES (9);
        CREATE TABLE monitoraggio_mese (mese TEXT PRIMARY KEY, mese_dati TEXT NOT NULL, link_scorrimenti TEXT, link_graduatorie TEXT,
            oggetto TEXT, testo TEXT, creato_da TEXT, creato_il TEXT NOT NULL, stato TEXT NOT NULL DEFAULT 'aperto', chiuso_da TEXT, chiuso_il TEXT);
        INSERT INTO monitoraggio_mese VALUES ('2026-10','2026-09',NULL,NULL,NULL,NULL,'x','2026-10-01T00:00:00Z','chiuso','capo','2026-10-30T00:00:00Z');
        CREATE TABLE monitoraggio_riga (id INTEGER PRIMARY KEY, mese TEXT NOT NULL, numero_bando TEXT, codice TEXT, titolo_bando TEXT, tipologia TEXT,
            atto TEXT NOT NULL, sottotipo TEXT, data TEXT, protocollo TEXT, sol_stato TEXT, sol_protocollo TEXT, urp_stato TEXT, urp_protocollo TEXT,
            segreteria_stato TEXT, segreteria_protocollo TEXT, rdp TEXT, note TEXT, difforme INTEGER NOT NULL DEFAULT 0,
            sollecito_stato TEXT, sollecito_autore TEXT, sollecito_quando TEXT);
        INSERT INTO monitoraggio_riga (mese, codice, atto, difforme) VALUES ('2026-10', 'X', 'graduatoria', 1);
        CREATE TABLE monitoraggio_punteggi (id INTEGER PRIMARY KEY, mese TEXT NOT NULL, numero_bando TEXT, codice TEXT, protocollo TEXT, data TEXT,
            domande INTEGER, con_punteggi INTEGER, vincitori INTEGER, idonei INTEGER, scorrimento INTEGER, senza_protocollo INTEGER, esito TEXT,
            verificato_il TEXT, difformita TEXT);
        CREATE TABLE monitoraggio_fonte (mese TEXT NOT NULL, fonte TEXT NOT NULL, ultima_raccolta TEXT, PRIMARY KEY (mese, fonte));
        INSERT INTO monitoraggio_fonte VALUES ('2026-10', 'sol', '2026-10-29T00:00:00Z');
    """)
    c.commit()
    c.close()
    conn = dbmod.connetti()
    dbmod.inizializza(conn)
    dbmod.inizializza(conn)  # idempotente
    f = mensile.fotografia(conn, "2026-10")
    assert f["versione"] == 1 and f["totale"] == 1 and f["versioni"][0]["creata_da"] == "capo"
    assert f["fonti"] == [{"fonte": "sol", "ultima_raccolta": "2026-10-29T00:00:00Z"}]
    assert conn.execute("SELECT versione FROM schema_version").fetchone()[0] == dbmod.SCHEMA_VERSION


# --- impostazioni email

def test_nuova_installazione_parte_in_prova(ambiente, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    monkeypatch.setenv("MAIL_REPLY_TO", "me@cnr.it")
    from monitoraggio import db as dbmod
    conn = dbmod.connetti()
    conn.execute("DELETE FROM impostazione")
    conn.close()
    assert posta.stato()["prova"] == "me@cnr.it"
    assert posta.invia(["vero@cnr.it"], "Oggetto", "Testo") is True
    assert inviati[0]["To"] == "me@cnr.it" and "vero@cnr.it" in inviati[0].get_content()


def test_spunta_prova_dalla_pagina(ambiente, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    admin = ambiente()
    assert admin.get("/monitoraggio/impostazioni").status_code == 200
    d = admin.put("/api/impostazioni/posta", json={"attiva": True, "indirizzo": "Me@cnr.it"}).get_json()
    assert d["prova"] == "me@cnr.it" and d["prova_impostazioni"]["modificata_da"] == "capo.ufficio"
    assert posta.invia(["vero@cnr.it"], "Oggetto", "Testo") is True
    assert inviati[-1]["To"] == "me@cnr.it" and inviati[-1]["Subject"] == "[PROVA] Oggetto"
    d = admin.put("/api/impostazioni/posta", json={"attiva": False, "indirizzo": "me@cnr.it"}).get_json()
    assert d["prova"] is None and d["prova_impostazioni"]["indirizzo"] == "me@cnr.it"
    assert posta.invia(["vero@cnr.it"], "Oggetto", "Testo") is False
    assert inviati[-1]["To"] == "vero@cnr.it" and inviati[-1]["Subject"] == "Oggetto"
    assert admin.put("/api/impostazioni/posta", json={"attiva": True, "indirizzo": "sbagliato"}).status_code == 400
    assert admin.put("/api/impostazioni/posta", json={"attiva": "si"}).status_code == 400


def test_prova_senza_indirizzo_non_invia_a_nessuno(ambiente, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    monkeypatch.delenv("MAIL_REPLY_TO")
    from monitoraggio import db as dbmod
    conn = dbmod.connetti()
    conn.execute("DELETE FROM impostazione")
    conn.close()
    with pytest.raises(posta.PostaErrore):
        posta.invia(["vero@cnr.it"], "Oggetto", "Testo")
    assert inviati == []
    assert ambiente().put("/api/impostazioni/posta", json={"attiva": True}).status_code == 400


def test_link_di_accesso_arriva_alla_persona_anche_in_prova(ambiente, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati, MAIL_PROVA="me@cnr.it")
    assert posta.invia(["collega@cnr.it"], "Accesso", "link", sempre_reale=True) is False
    assert inviati[0]["To"] == "collega@cnr.it"


def test_impostazioni_solo_per_amministratori_e_voce_di_menu(ambiente):
    admin = ambiente()
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    c = ambiente("lettore.uno")
    assert c.get("/monitoraggio/impostazioni").status_code == 403
    assert c.put("/api/impostazioni/posta", json={"attiva": False}).status_code == 403
    voci = lambda x: {v["titolo"] for g in x.get("/api/menu").get_json()["gruppi"] for v in g["voci"]}  # noqa: E731
    assert "Impostazioni" in voci(admin) and "Impostazioni" not in voci(c)


# --- aggiornamenti e avviso

def test_orario_e_giorno_dalle_impostazioni(ambiente, monkeypatch):
    from datetime import datetime
    from monitoraggio import impostazioni, scheduler, web
    monkeypatch.setenv("RACCOLTA_ORARIO", "02:30")
    admin = ambiente()
    d = admin.get("/api/impostazioni/aggiornamenti").get_json()
    assert d["orario"] == "02:30" and d["giorno_completa"] == "dom" and d["avviso_modo"] == "completi"
    d = admin.put("/api/impostazioni/aggiornamenti", json={"orario": "21:15", "giorno_completa": "lun"}).get_json()
    assert d["orario"] == "21:15" and d["giorno_completa"] == "lun"
    assert impostazioni.orario_raccolta() == (21, 15)
    ora = datetime(2026, 11, 5, 20, 0).astimezone()
    assert web.prossima_notturna(ora).startswith("2026-11-05T21:15")
    assert scheduler.modalita(datetime(2026, 11, 9)) == "completa" and scheduler.modalita(datetime(2026, 11, 8)) == "notturna"
    for sbagliato in ({"orario": "25:00"}, {"orario": "mattina"}, {"giorno_completa": "xyz"}, {"avviso_modo": "boh"},
                      {"avviso_indirizzo": "sbagliato"}):
        assert admin.put("/api/impostazioni/aggiornamenti", json=sbagliato).status_code == 400, sbagliato


def test_storico_degli_aggiornamenti(ambiente, db):
    from monitoraggio import raccolta
    rid = raccolta.avvia(db, "urp", "completa", "pianificata")
    raccolta.chiudi(db, rid, "completata", {"bandi_trovati": 241, "documenti_trovati": 2118})
    d = ambiente().get("/api/impostazioni/aggiornamenti").get_json()
    voce = d["storico"][0]
    assert (voce["fonte"], voce["modalita"], voce["esito"], voce["errori"]) == ("urp", "completa", "completata", 0)
    assert voce["fine"] and d["ultimo_completo"] == voce["fine"]


def test_impostazioni_aggiornamenti_solo_amministratori(ambiente):
    ambiente().post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    c = ambiente("lettore.uno")
    assert c.get("/api/impostazioni/aggiornamenti").status_code == 403
    assert c.put("/api/impostazioni/aggiornamenti", json={"orario": "01:00"}).status_code == 403


def _esiti(esito="completata"):
    return {"urp": {"esito": esito, "bandi_trovati": 241, "documenti_trovati": 2118, "errori": 0},
            "sol": {"esito": "completata", "bandi_trovati": 1203, "documenti_trovati": 900, "errori": 0}}


def test_avviso_solo_dopo_il_completo_all_indirizzo_scelto(ambiente, monkeypatch):
    from monitoraggio import notifiche
    inviati = []
    _configura_posta(monkeypatch, inviati, MAIL_PROVA="prova@cnr.it")  # anche con le email di prova attive
    ambiente().put("/api/impostazioni/aggiornamenti", json={"avviso_indirizzo": "admin@cnr.it", "avviso_modo": "completi"})
    assert notifiche.dopo_aggiornamento(_esiti(), "notturna") is False and inviati == []
    assert notifiche.dopo_aggiornamento(_esiti(), "completa") is True
    m = inviati[0]
    assert m["To"] == "admin@cnr.it" and m["Subject"] == "Monitoraggio: aggiornamento completo completato"
    assert "URP: completata, 241 bandi, 2118 documenti" in m.get_content() and "#aggiornamenti" in m.get_content()


def test_avviso_per_tutti_mai_e_quando_non_riesce(ambiente, monkeypatch):
    from monitoraggio import notifiche
    inviati = []
    _configura_posta(monkeypatch, inviati)
    admin = ambiente()
    admin.put("/api/impostazioni/aggiornamenti", json={"avviso_indirizzo": "admin@cnr.it", "avviso_modo": "tutti"})
    assert notifiche.dopo_aggiornamento(_esiti("fallita"), "notturna") is True
    assert "NON riuscito" in inviati[0]["Subject"]
    admin.put("/api/impostazioni/aggiornamenti", json={"avviso_modo": "mai"})
    assert notifiche.dopo_aggiornamento(_esiti(), "completa") is False and len(inviati) == 1


def test_avviso_non_blocca_la_raccolta(ambiente, monkeypatch):
    from monitoraggio import notifiche
    _configura_posta(monkeypatch, [])
    ambiente().put("/api/impostazioni/aggiornamenti", json={"avviso_indirizzo": "admin@cnr.it", "avviso_modo": "tutti"})

    def rotto(*a, **k):
        raise OSError("rete")
    monkeypatch.setattr(posta.smtplib, "SMTP", rotto)
    assert notifiche.dopo_aggiornamento(_esiti(), "completa") is False


def test_lo_scheduler_avvisa_a_fine_ciclo(ambiente, monkeypatch):
    from monitoraggio import scheduler
    avvisi = []
    monkeypatch.setattr(scheduler, "raccogli", lambda conn, f, **k: {"esito": "completata", "fonte": f})
    monkeypatch.setattr(scheduler.notifiche, "dopo_aggiornamento", lambda e, m: avvisi.append((sorted(e), m)))
    scheduler.esegui(scheduler.FONTI, "completa", "pianificata")
    assert avvisi == [(["sol", "urp"], "completa")]


def test_la_raccolta_dalla_pagina_avvisa_a_fine_lavoro(ambiente, monkeypatch):
    avvisi = []
    monkeypatch.setattr(web_modulo.notifiche, "dopo_aggiornamento", lambda e, m: avvisi.append((sorted(e), m)))
    monkeypatch.setattr(web_modulo, "raccogli", lambda conn, f, **k: {"esito": "completata", "fonte": f})
    r = ambiente().post("/api/raccolta/avvia", json={"fonti": ["urp", "sol"], "completa": True})
    assert r.status_code == 202
    for _ in range(100):
        if avvisi:
            break
        time.sleep(0.02)
    assert avvisi == [(["sol", "urp"], "completa")]


# --- registro delle difformità

def _raccolte_riuscite(db):
    from monitoraggio import raccolta
    for fonte in ("urp", "sol"):
        rid = raccolta.avvia(db, fonte, "manuale", "test")
        raccolta.chiudi(db, rid, "completata", {})


def _correggi(db, protocollo="1002"):
    from monitoraggio import collegamento
    salva(db, "sol", [scheda("sol", "s1", "367.479 CTER", "367.479", documenti=[doc("g1", "graduatoria", protocollo, "2026-04-12")])])
    collegamento.collega(db)


def test_difformita_corretta_resta_in_elenco_con_il_badge(ambiente, db):
    from monitoraggio import difformita
    admin, mese = _mese_con_dati(ambiente, db)
    _raccolte_riuscite(db)
    d = admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()
    voce = d["voci"][0]
    assert d["totale"] == 1 and voce["badge"] == "da_correggere" and voce["codice"] == "367.479 CTER"
    assert "protocollo diverso: SOL 1001, URP 1002" in voce["rilievi"][0]["testo"] and not voce["rilievi"][0]["risolto"]
    _correggi(db)
    assert difformita.sincronizza(db, mese)["corrette"] == 1
    d = admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()
    voce = d["voci"][0]
    assert d["totale"] == 1 and voce["badge"] == "corretta" and voce["corretta_il"] and d["conteggi"]["corretta"] == 1
    assert voce["rilievi"][0]["risolto"] and "SOL 1001" in voce["rilievi"][0]["testo"]  # il testo originale resta
    assert [e["tipo"] for e in voce["storico"]] == ["corretta", "rilevata"]


def test_ricompare_torna_da_correggere(ambiente, db):
    from monitoraggio import difformita
    admin, mese = _mese_con_dati(ambiente, db)
    _raccolte_riuscite(db)
    difformita.sincronizza(db, mese)
    _correggi(db)
    difformita.sincronizza(db, mese)
    _correggi(db, "1001")
    assert difformita.sincronizza(db, mese)["ricomparse"] == 1
    voce = admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()["voci"][0]
    assert voce["badge"] == "da_correggere" and voce["corretta_il"] is None
    assert [e["tipo"] for e in voce["storico"]] == ["ricomparsa", "corretta", "rilevata"]
    assert admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()["totale"] == 1  # nessun doppione


def test_correzione_parziale(ambiente, db):
    from monitoraggio import atti, difformita
    admin, mese = _mese_con_dati(ambiente, db)
    _raccolte_riuscite(db)
    uno, due = "primo rilievo", "secondo rilievo"
    reale = atti.elenco_atti
    note = [uno, due]

    def finto(conn, dal=None, al=None):
        righe = reale(conn, dal, al)
        for r in righe:
            r["note"], r["difforme"] = list(note), True
        return righe
    from unittest import mock
    with mock.patch.object(difformita.atti, "elenco_atti", finto):
        difformita.sincronizza(db, mese)
        note[:] = [due]
        difformita.sincronizza(db, mese)
    voce = admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()["voci"][0]
    assert voce["badge"] == "parziale"
    assert {r["testo"]: r["risolto"] for r in voce["rilievi"]} == {uno: True, due: False}


def test_atto_non_trovato_non_diventa_verde(ambiente, db):
    from monitoraggio import difformita
    admin, mese = _mese_con_dati(ambiente, db)
    _raccolte_riuscite(db)
    difformita.sincronizza(db, mese)
    db.execute("UPDATE documento SET presente = 0")
    difformita.sincronizza(db, mese)
    voce = admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()["voci"][0]
    assert voce["badge"] == "da_controllare" and voce["corretta_il"] is None


def test_con_una_raccolta_fallita_nessuna_correzione(ambiente, db):
    from monitoraggio import difformita, raccolta
    admin, mese = _mese_con_dati(ambiente, db)
    _raccolte_riuscite(db)
    difformita.sincronizza(db, mese)
    _correggi(db)
    rid = raccolta.avvia(db, "urp", "manuale", "test")
    raccolta.chiudi(db, rid, "fallita", messaggio="URP non raggiunto")
    assert difformita.sincronizza(db, mese)["fonti_affidabili"] is False
    d = admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()
    assert d["voci"][0]["badge"] == "da_correggere" and d["fonti_affidabili"] is False


def test_mese_chiuso_badge_aggiornato_e_versione_ferma(ambiente, db):
    from monitoraggio import difformita
    admin, mese = _mese_con_dati(ambiente, db)
    _raccolte_riuscite(db)
    difformita.sincronizza(db, mese)
    admin.post(f"/api/monitoraggi/{mese}/chiudi")
    _correggi(db)
    difformita.sincronizza(db, mese)
    assert admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()["voci"][0]["badge"] == "corretta"
    f = admin.get(f"/api/monitoraggi/{mese}").get_json()["fotografia"]
    assert f["difformi"] == 1 and f["righe"][0]["sol_protocollo"] == "1001"


def test_il_registro_non_contiene_dati_dei_candidati(ambiente, db, monkeypatch):
    from monitoraggio import difformita
    admin, mese = _mese_con_dati(ambiente, db)
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = 's1'").fetchone()[0]
    monkeypatch.setattr(punteggi, "_candidati", {sid: {"candidati": [{"cognome": "Rossi", "codice_fiscale": "RSSMRA80A01H501U"}]}})
    difformita.sincronizza(db, mese)
    dump = "\n".join(str(tuple(r)) for t in ("difformita", "difformita_evento") for r in db.execute(f"SELECT * FROM {t}"))
    assert "Rossi" not in dump and "RSSMRA" not in dump


def _attendi(difformita):
    for _ in range(300):
        if not difformita.stato_verifica().get("in_corso"):
            return difformita.stato_verifica()
        time.sleep(0.02)
    raise AssertionError("verifica non finita")


def test_verifica_di_una_sola_difformita(ambiente, db, monkeypatch):
    from monitoraggio import difformita, raccolta
    admin, mese = _mese_con_dati(ambiente, db)
    _raccolte_riuscite(db)
    salva(db, "sol", [scheda("sol", "s1", "367.479 CTER", "367.479", documenti=[doc("g1", "graduatoria", "1001", "2026-04-12")]),
                      scheda("sol", "s2", "367.800 RIC", "367.800", documenti=[doc("g5", "graduatoria", "5001", "2026-04-15")])], )
    salva(db, "urp", [scheda("urp", "/node/1", "367.479 CTER", "367.479", documenti=[doc("g2", "graduatoria", "1002", "2026-04-12")]),
                      scheda("urp", "/node/8", "367.800 RIC", "367.800", documenti=[doc("g6", "graduatoria", "5002", "2026-04-15")])])
    from monitoraggio import collegamento
    collegamento.collega(db)
    difformita.sincronizza(db, mese)
    voci = admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()["voci"]
    assert len(voci) == 2
    chiamati = []

    def finto(conn, numero, codice, c1, c2):
        chiamati.append(numero)
        conn.execute("UPDATE documento SET protocollo = '1002', protocollo_originale = '1002' WHERE id_esterno = 'g1'")
        return []
    monkeypatch.setattr(raccolta, "aggiorna_bando", finto)
    scelta = next(v for v in voci if v["numero_bando"] == "367.479")
    r = admin.post(f"/api/monitoraggi/{mese}/difformita/verifica", json={"ids": [scelta["id"]]})
    assert r.status_code == 202
    fine = _attendi(difformita)
    assert chiamati == ["367.479"] and fine["risultato"]["corrette"] == 1 and fine["punteggi_riletti"] is False
    stati = {v["numero_bando"]: v["badge"] for v in admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()["voci"]}
    assert stati == {"367.479": "corretta", "367.800": "da_correggere"}


def test_verifica_tutte_salta_le_corrette_e_una_alla_volta(ambiente, db, monkeypatch):
    from monitoraggio import difformita, raccolta
    admin, mese = _mese_con_dati(ambiente, db)
    _raccolte_riuscite(db)
    difformita.sincronizza(db, mese)
    _correggi(db)
    difformita.sincronizza(db, mese)
    chiamati = []
    monkeypatch.setattr(raccolta, "aggiorna_bando", lambda *a: chiamati.append(a[1]) or [])
    assert admin.post(f"/api/monitoraggi/{mese}/difformita/verifica", json={}).status_code == 202
    _attendi(difformita)
    assert chiamati == []
    monkeypatch.setitem(difformita._verifica, "in_corso", True)
    assert admin.post(f"/api/monitoraggi/{mese}/difformita/verifica", json={}).status_code == 409
    monkeypatch.setitem(difformita._verifica, "in_corso", False)
    assert admin.post(f"/api/monitoraggi/{mese}/difformita/verifica", json={"ids": "tutte"}).status_code == 400


def test_verifica_riporta_gli_errori_e_con_sol_collegato_rilegge_i_punteggi(ambiente, db, monkeypatch):
    from monitoraggio import difformita, raccolta
    admin, mese = _mese_con_dati(ambiente, db)
    _raccolte_riuscite(db)
    difformita.sincronizza(db, mese)
    monkeypatch.setattr(raccolta, "aggiorna_bando", lambda *a: ["367.479: URP non riletto"])
    riletti = []
    monkeypatch.setattr(punteggi, "verifica_schede", lambda c, s, d, a, i, cl: riletti.append((len(s), i)) or {"esito": "completata"})
    difformita.avvia_verifica(mese, None, {"Cookie": "ticket=T"}, "capo.ufficio")
    fine = _attendi(difformita)
    assert fine["errori"] == ["367.479: URP non riletto"] and fine["punteggi_riletti"] is True
    assert riletti == [(1, {"Cookie": "ticket=T"})]


def test_lettura_vede_il_registro_ma_non_verifica(ambiente, db):
    admin, mese = _mese_con_dati(ambiente, db)
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    c = ambiente("lettore.uno")
    assert c.get(f"/api/monitoraggi/{mese}/difformita").status_code == 200
    assert c.post(f"/api/monitoraggi/{mese}/difformita/verifica", json={}).status_code == 403


def test_cambio_del_mese_dei_dati_rifa_il_registro(ambiente, db):
    from monitoraggio import difformita
    admin, mese = _mese_con_dati(ambiente, db)
    difformita.sincronizza(db, mese)
    assert admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()["totale"] == 1
    admin.put(f"/api/monitoraggi/{mese}", json={"mese_dati": "2026-02"})
    assert admin.get(f"/api/monitoraggi/{mese}/difformita").get_json()["totale"] == 0


def test_aggiorna_bando_non_tocca_gli_altri_bandi(db, client_finto):
    from monitoraggio import raccolta
    salva(db, "sol", [scheda("sol", "s1", "367.1 CTER", "367.1", documenti=[doc("a", "graduatoria", "1", "2026-04-12")]),
                      scheda("sol", "s2", "367.2 CTER", "367.2", documenti=[doc("b", "graduatoria", "2", "2026-04-12")])])
    item = {"cmis:objectId": "s1", "cmis:objectTypeId": "F:jconon_call_tind:folder_concorsi_pubblici", "jconon_call:codice": "367.1 CTER"}
    allegato = {"cmis:objectId": "nuovo", "cmis:name": "Graduatoria", "cmis:objectTypeId": "D:jconon_attachment:call_classification",
                "jconon_protocollo:numero": "99", "jconon_protocollo:data": "2026-04-20"}

    def risposte(url, params):
        lista = [item] if "jconon_call:folder" in params["q"] else [allegato]
        return {"totalNumItems": len(lista), "hasMoreItems": False, "items": lista}
    client = client_finto(json_per_chiave=risposte)
    assert raccolta.aggiorna_bando(db, "367.1", "367.1 CTER", client, client) == []
    presenti = {r[0]: r[1] for r in db.execute("SELECT id_esterno, presente FROM scheda WHERE fonte = 'sol'")}
    assert presenti == {"s1": 1, "s2": 1}
    assert {r[0] for r in db.execute("SELECT d.protocollo FROM documento d JOIN scheda s ON s.id = d.scheda_id WHERE s.id_esterno = 's1' AND d.presente = 1")} == {"99"}
    assert {r[0] for r in db.execute("SELECT d.protocollo FROM documento d JOIN scheda s ON s.id = d.scheda_id WHERE s.id_esterno = 's2' AND d.presente = 1")} == {"2"}


# --- comunicazioni, email e attività (specifiche grafiche)

def _mese_con_rdp(ambiente, db, email="rdp@cnr.it"):
    admin, mese = _mese_con_dati(ambiente, db)
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = 's1'").fetchone()[0]
    db.execute("INSERT INTO referente (scheda_id, chiave, nome, cognome, email, username, attivo, prima_rilevazione, "
               "ultima_rilevazione) VALUES (?, 'a', 'Anna', 'Bianchi', ?, 'a', 1, 'x', 'x')", (sid, email))
    return admin, mese, f"/api/monitoraggi/{mese}/comunicazioni/367.479 CTER"


def test_crea_dal_mese_di_riferimento_con_tipologie(ambiente):
    admin = ambiente()
    r = admin.post("/api/monitoraggi", json={"mese_riferimento": "2026-10", "tipologie": ["MOB"]}).get_json()
    assert r["mese"] == "2026-11" and r["creato"] is True
    d = admin.get("/api/monitoraggi/2026-11").get_json()
    assert d["id"] == "MON-10.2026" and d["titolo"] == "ottobre 2026" and d["mese_dati"] == "2026-10" and d["tipologie"] == ["MOB"]
    assert d["file_scorrimenti"] == "MODELLO-scorrimenti-novembre-26.xlsx"
    doppio = admin.post("/api/monitoraggi", json={"mese_riferimento": "2026-10"}).get_json()
    assert doppio["creato"] is False and doppio["mese"] == "2026-11"
    assert admin.post("/api/monitoraggi", json={"mese_riferimento": "2026-12", "tipologie": []}).status_code == 400
    assert admin.post("/api/monitoraggi", json={"mese_riferimento": "2026-12", "tipologie": ["TD"]}).status_code == 400


def test_anteprima_e_allineamento(ambiente, db):
    from monitoraggio import raccolta
    salva(db, "sol", [scheda("sol", "s1", "367.479 CTER", "367.479", documenti=[doc("g1", "graduatoria", "1001", "2026-10-12")])])
    salva(db, "urp", [scheda("urp", "/node/1", "367.479 CTER", "367.479", documenti=[doc("g2", "graduatoria", "1002", "2026-10-12")])])
    from monitoraggio import collegamento
    collegamento.collega(db)
    rid = raccolta.avvia(db, "sol", "manuale", "t")
    raccolta.chiudi(db, rid, "completata", {})
    d = ambiente().get("/api/monitoraggi/anteprima?mese=2020-01").get_json()
    assert d["id"] == "MON-01.2020" and d["esistente"] is None
    voce = {f["fonte"]: f for f in d["allineamento"]}
    assert voce["sol"]["allineata"] is True and voce["urp"]["allineata"] is False and voce["segreteria"]["allineata"] is False
    assert ambiente().get("/api/monitoraggi/anteprima?mese=xx").status_code == 400
    d = ambiente().get("/api/monitoraggi/anteprima?mese=2026-10").get_json()
    assert d["per_tipologia"]["TI"]["atti"] == 1 and d["per_tipologia"]["TI"]["da_inviare"] == 1 and d["per_tipologia"]["MOB"]["atti"] == 0


def test_tipologie_del_monitoraggio_filtrano_gli_atti(ambiente, db):
    admin, mese = _mese_con_dati(ambiente, db)
    assert admin.get(f"/api/monitoraggi/{mese}/atti").get_json()["conteggi"]["atti"] == 1
    admin.put(f"/api/monitoraggi/{mese}", json={"tipologie": ["MOB"]})
    assert admin.get(f"/api/monitoraggi/{mese}/atti").get_json()["conteggi"]["atti"] == 0
    assert admin.put(f"/api/monitoraggi/{mese}", json={"tipologie": []}).status_code == 400


def test_messaggio_standard_per_codice(ambiente, db):
    admin, mese, url = _mese_con_rdp(ambiente, db)
    m = admin.get(url + "/messaggio").get_json()
    assert m["destinatari"] == ["rdp@cnr.it"] and m["referenti"][0]["nome"] == "Anna Bianchi"
    assert m["oggetto"] == "[MON-04.2026] Monitoraggio aprile 2026 – bando 367.479 CTER: 1 difformità"
    assert m["corpo"].startswith("Gentile Anna Bianchi,") and "(rif. MON-04.2026)" in m["corpo"]
    assert "1) Graduatoria del 12/04/2026" in m["corpo"] and "protocollo diverso: SOL 1001, URP 1002" in m["corpo"]
    assert "Cordiali saluti," in m["corpo"] and m["stato"] == "da_inviare"
    assert admin.get(f"/api/monitoraggi/{mese}/comunicazioni/inesistente/messaggio").status_code == 404


def test_prova_e_ufficiale_sono_separate(ambiente, db, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati, MAIL_PROVA="prova@cnr.it")
    admin, mese, url = _mese_con_rdp(ambiente, db)
    posta.salva_email({"prova_attiva": True, "ufficiali_attive": False}, "t")
    r = admin.post(url + "/invia", json={"modo": "ufficiale"})
    assert r.status_code == 502 and "disattivate" in r.get_json()["error"] and inviati == []
    r = admin.post(url + "/invia", json={"modo": "prova"}).get_json()
    assert r["prova"] is True and inviati[0]["To"] == "prova@cnr.it" and inviati[0]["Subject"].startswith("[PROVA] [MON-04.2026]")
    a = admin.get(f"/api/monitoraggi/{mese}/atti").get_json()
    assert a["righe"][0]["comunicazione"]["stato"] == "da_inviare"  # la prova non cambia lo stato
    registro = admin.get(f"/api/comunicazioni?mese={mese}").get_json()["comunicazioni"]
    assert registro[0]["stato"] == "prova" and registro[0]["canale"] == "Email di prova"
    posta.salva_email({"prova_attiva": False, "ufficiali_attive": True, "cc": "cc@cnr.it"}, "t")
    assert admin.post(url + "/invia", json={"modo": "prova"}).status_code == 502
    r = admin.post(url + "/invia", json={"modo": "ufficiale", "oggetto": "Oggetto mio"}).get_json()
    assert r["prova"] is False and inviati[-1]["To"] == "rdp@cnr.it" and inviati[-1]["Subject"] == "Oggetto mio" and inviati[-1]["Cc"] == "cc@cnr.it"
    a = admin.get(f"/api/monitoraggi/{mese}/atti").get_json()
    assert a["righe"][0]["comunicazione"]["stato"] == "inviata" and a["conteggi"]["inviate"] == 1
    assert admin.post(url + "/invia", json={"modo": "ufficiale"}).status_code == 409
    assert admin.post(url + "/invia", json={"modo": "ufficiale", "conferma": True}).status_code == 200
    ids = [c["id"] for c in admin.get(f"/api/comunicazioni?mese={mese}").get_json()["comunicazioni"]]
    assert len(ids) == len(set(ids)) and any(i.endswith("-2") for i in ids)
    assert admin.post(url + "/invia", json={"modo": "altro"}).status_code == 400


def test_copia_da_confermare_e_spunta(ambiente, db):
    admin, mese, url = _mese_con_rdp(ambiente, db)
    assert admin.post(url + "/traccia", json={"canale": "Copia manuale"}).status_code == 200
    assert admin.post(url + "/traccia", json={"canale": "Boh"}).status_code == 400
    stato_ora = lambda: admin.get(f"/api/monitoraggi/{mese}/atti").get_json()["righe"][0]["comunicazione"]["stato"]  # noqa: E731
    assert stato_ora() == "da_confermare"
    spunta = f"/api/monitoraggi/{mese}/solleciti/367.479 CTER"
    admin.put(spunta, json={"inviata": True})
    assert stato_ora() == "inviata"
    registro = admin.get(f"/api/comunicazioni?mese={mese}").get_json()["comunicazioni"]
    assert len(registro) == 1 and registro[0]["stato"] == "inviata"  # ha confermato la voce esistente
    admin.put(spunta, json={"inviata": False})
    assert stato_ora() == "da_inviare"
    admin.put(spunta, json={"inviata": True})
    assert stato_ora() == "inviata_a_mano"
    assert [c["stato"] for c in admin.get(f"/api/comunicazioni?mese={mese}").get_json()["comunicazioni"]] == ["inviata", "annullata", "inviata"]


def test_controlli_sul_messaggio_e_mese_chiuso(ambiente, db, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati)
    admin, mese, url = _mese_con_rdp(ambiente, db)
    r = admin.post(url + "/invia", json={"modo": "ufficiale", "corpo": "Candidato RSSMRA80A01H501U"})
    assert r.status_code == 400 and "codice fiscale" in r.get_json()["error"] and inviati == []
    admin.post(f"/api/monitoraggi/{mese}/chiudi")
    assert admin.post(url + "/invia", json={"modo": "ufficiale"}).status_code == 409
    assert admin.post(url + "/traccia", json={"canale": "Copia manuale"}).status_code == 409
    assert admin.post(f"/api/monitoraggi/{mese}/comunicazioni-invia-tutti").status_code == 409
    assert inviati == []


def test_invia_tutti_solo_con_ufficiali_e_salta_le_inviate(ambiente, db, monkeypatch):
    inviati = []
    _configura_posta(monkeypatch, inviati, MAIL_PROVA="prova@cnr.it")
    admin, mese, _ = _mese_con_rdp(ambiente, db)
    posta.salva_email({"prova_attiva": True, "ufficiali_attive": False}, "t")
    tutti = f"/api/monitoraggi/{mese}/comunicazioni-invia-tutti"
    assert admin.post(tutti).status_code == 409 and inviati == []
    posta.salva_email({"prova_attiva": False, "ufficiali_attive": True}, "t")
    assert admin.post(tutti).get_json() == {"ok": True, "inviate": 1, "errori": []}
    assert admin.post(tutti).get_json()["inviate"] == 0 and len(inviati) == 1


def test_lettura_non_tocca_comunicazioni_e_impostazioni(ambiente, db):
    admin, mese, url = _mese_con_rdp(ambiente, db)
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    c = ambiente("lettore.uno")
    assert c.get(url + "/messaggio").status_code == 200 and c.get("/api/comunicazioni").status_code == 200
    for metodo, u, dati in [("post", url + "/invia", {"modo": "prova"}), ("post", url + "/traccia", {"canale": "Copia manuale"}),
                            ("post", f"/api/monitoraggi/{mese}/comunicazioni-invia-tutti", {}), ("post", f"/api/monitoraggi/{mese}/verifica-fonti", {}),
                            ("get", "/api/monitoraggi/anteprima?mese=2026-01", None), ("get", "/api/impostazioni/attivita", None),
                            ("put", "/api/impostazioni/attivita/sol", {"attiva": False}), ("post", "/api/impostazioni/attivita/sol/esegui", {}),
                            ("put", "/api/impostazioni/posta", {"ufficiali_attive": True})]:
        assert getattr(c, metodo)(u, json=dati).status_code == 403, u


def test_impostazioni_email_due_interruttori(ambiente, monkeypatch):
    _configura_posta(monkeypatch, [])
    admin = ambiente()
    d = admin.put("/api/impostazioni/posta", json={"prova_attiva": True, "indirizzo_prova": "Me@cnr.it", "ufficiali_attive": False,
                                                   "mittente": "ufficio@cnr.it", "cc": "", "firma": "Ufficio concorsi"}).get_json()
    assert d["prova_attiva"] and not d["ufficiali_attive"] and d["indirizzo_prova"] == "me@cnr.it" and d["firma"] == "Ufficio concorsi" and d["mittente"] == "ufficio@cnr.it"
    assert admin.put("/api/impostazioni/posta", json={"indirizzo_prova": "sbagliato"}).status_code == 400
    assert admin.put("/api/impostazioni/posta", json={"prova_attiva": True, "indirizzo_prova": ""}).status_code == 400
    assert admin.put("/api/impostazioni/posta", json={"ufficiali_attive": True, "mittente": ""}).status_code == 400
    assert admin.put("/api/impostazioni/posta", json={"prova_attiva": "si"}).status_code == 400


def test_nuova_installazione_nessuna_email_ai_referenti(ambiente, monkeypatch):
    monkeypatch.setenv("SMTP_SERVER", "x")
    monkeypatch.setenv("MAIL_SENDER", "a@b.it")
    monkeypatch.setenv("MAIL_REPLY_TO", "me@cnr.it")
    e = posta.impostazioni_email()
    assert e["prova_attiva"] is True and e["ufficiali_attive"] is False


def test_attivita_orari_stato_e_storico(ambiente):
    from datetime import datetime, timezone
    from monitoraggio import attivita
    admin = ambiente()
    d = admin.get("/api/impostazioni/attivita").get_json()
    assert [a["chiave"] for a in d["attivita"]] == ["sol", "urp", "referenti", "confronto", "riepilogo"]
    assert d["attivita"][0]["attiva"] is True and d["attivita"][2]["attiva"] is False
    assert admin.put("/api/impostazioni/attivita/urp", json={"orario": "25:00"}).status_code == 400
    assert admin.put("/api/impostazioni/attivita/xx", json={"attiva": True}).status_code == 400
    r = admin.put("/api/impostazioni/attivita/urp", json={"orario": "04:10", "attiva": False}).get_json()
    voce = next(a for a in r["attivita"] if a["chiave"] == "urp")
    assert voce["orario"] == "04:10" and voce["attiva"] is False
    attese = {}
    ora = datetime(2026, 11, 5, 4, 9, tzinfo=timezone.utc)
    assert attivita.dovute(ora, attese) == []  # la prima volta segna solo gli orari
    admin.put("/api/impostazioni/attivita/urp", json={"attiva": True})
    assert "urp" in attivita.dovute(datetime(2026, 11, 5, 4, 11, tzinfo=timezone.utc), attese)
    assert admin.post("/api/impostazioni/attivita/xx/esegui").status_code == 404


def test_esegui_attivita_registra_esito(ambiente, monkeypatch, db):
    from monitoraggio import attivita
    avvisi = []
    monkeypatch.setattr(attivita, "raccogli", lambda conn, f, **k: {"esito": "completata", "bandi_trovati": 3, "documenti_trovati": 7, "errori": 0})
    monkeypatch.setattr(attivita.notifiche, "dopo_aggiornamento", lambda e, m: avvisi.append((sorted(e), m)))
    admin = ambiente()
    assert admin.post("/api/impostazioni/attivita/urp/esegui").status_code == 202
    for _ in range(200):
        d = admin.get("/api/impostazioni/attivita").get_json()
        if d["storico"]:
            break
        time.sleep(0.02)
    assert d["storico"][0]["esito"] == "ok" and d["storico"][0]["dettaglio"] == "3 bandi, 7 documenti"
    assert avvisi == [(["urp"], "manuale")]
    assert admin.get("/api/impostazioni/attivita?problemi=1").get_json()["storico"] == []


def test_referenti_di_notte_non_partono_senza_accesso(ambiente, monkeypatch):
    from monitoraggio import attivita
    monkeypatch.delenv("RDP_SENZA_TOKEN", raising=False)
    esito, dettaglio = attivita._esegui_referenti(None)
    assert esito == "avviso" and "Collega-SOL" in dettaglio


def test_badge_del_menu_e_ultimo_accesso(ambiente, db):
    admin, mese, _ = _mese_con_rdp(ambiente, db)
    from monitoraggio import difformita
    difformita.sincronizza(db, mese)
    assert admin.get("/api/menu").get_json()["da_comunicare"] == 1
    admin.put(f"/api/monitoraggi/{mese}/solleciti/367.479 CTER", json={"inviata": True})
    assert admin.get("/api/menu").get_json()["da_comunicare"] == 0
    utenti.segna_ultimo_accesso("capo.ufficio")
    voce = next(u for u in admin.get("/api/utenti").get_json()["utenti"] if u["username"] == "capo.ufficio")
    assert voce["ultimo_accesso"]


def test_solleciti_gia_segnati_entrano_nel_registro(db):
    mensile.crea(db, "2026-05", None, "x")
    db.execute("INSERT INTO sollecito (mese, numero_bando, stato, autore, quando, destinatari, oggetto) VALUES "
               "('2026-05', '367.1 CTER', 'inviata', 'a', '2026-05-02T00:00:00Z', 'x@cnr.it', 'O')")
    from monitoraggio import db as dbmod
    dbmod.inizializza(db)
    dbmod.inizializza(db)
    assert db.execute("SELECT COUNT(*) FROM comunicazione").fetchone()[0] == 1
    assert mensile.solleciti(db, "2026-05")["367.1 CTER"]["stato"] == "inviata"
