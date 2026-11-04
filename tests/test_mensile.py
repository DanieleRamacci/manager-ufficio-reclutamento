"""Monitoraggio mensile, ruoli, Excel e invio delle email (spec 006)."""
import io
from datetime import date

import openpyxl
import pytest
from flask import Flask, session
from flask_session import Session

from monitoraggio import excel_mese, mensile, posta, punteggi, utenti
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
    assert "Utenti" in voci(ambiente())
    voci_lettura = voci(ambiente("lettore.uno"))
    assert "Utenti" not in voci_lettura and "Monitoraggi mensili" in voci_lettura


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
