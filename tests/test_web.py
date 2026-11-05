from functools import wraps

from flask import Flask

from monitoraggio import collegamento, raccolta, web
from tests.test_collegamento import doc, salva, scheda


def app_di_prova(protezione=lambda f: f):
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint(protezione))
    return app.test_client()


def test_stato_e_bandi_vuoti(db):
    client = app_di_prova()
    stato = client.get("/api/raccolta/stato").get_json()
    assert set(stato["fonti"]) == {"urp", "sol"}
    assert client.get("/api/bandi").get_json() == {"totale": 0, "bandi": []}
    assert client.get("/api/bandi/999").status_code == 404


def test_bandi_con_segnalazioni(db, monkeypatch):
    monkeypatch.setenv("MONITORAGGIO_DAL", "2026-01-01")
    salva(db, "urp", [scheda("urp", "/node/9", "367.900 RIC", "367.900", documenti=[
        doc("u2", "scorrimento", "175370", "2026-04-15", "utilizzo")])])
    salva(db, "sol", [scheda("sol", "s9", "367.900 RIC", "367.900")])
    collegamento.collega(db)
    client = app_di_prova()
    dati = client.get("/api/bandi").get_json()
    assert dati["totale"] == 1
    bando = dati["bandi"][0]
    assert bando["stato_collegamento"] == "entrambi"
    assert bando["documenti"]["scorrimento"] == {"totale": 1, "subentro": 0, "ulteriore": 0, "utilizzo": 1,
                                                 "non_specificato": 0}
    assert bando["segnalazioni"] == ["scorrimento_mancante_sol"]
    dettaglio = client.get(f"/api/bandi/{bando['id']}").get_json()
    assert {s["fonte"] for s in dettaglio["schede"]} == {"urp", "sol"}
    mesi = client.get("/api/riepilogo").get_json()["mesi"]
    assert mesi[0]["mese"] == "2026-04" and mesi[0]["scorrimento_urp"] == 1


def test_riepilogo_rdp_usa_i_referenti_del_database(db):
    salva(db, "sol", [scheda("sol", "s-rdp", "367.901 CTER", "367.901")])
    collegamento.collega(db)
    scheda_id = db.execute("SELECT id FROM scheda WHERE fonte = 'sol'").fetchone()[0]
    db.execute("INSERT INTO referente (scheda_id, chiave, nome, cognome, email, username, attivo, prima_rilevazione, ultima_rilevazione) "
               "VALUES (?, 'rdp-1', 'Ada', 'Rossi', 'ada.rossi@cnr.it', 'arossi', 1, '2026-10-01', '2026-10-01')",
               (scheda_id,))
    client = app_di_prova()
    righe = client.get("/api/riepilogo-rdp").get_json()
    riga = next(r for r in righe if r["codice"].startswith("367.901"))
    assert riga["rdp_members"] == ["Ada Rossi"]


def test_le_pagine_legacy_non_migrate_non_sono_servite(db):
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint_pagine_esistenti())
    client = app.test_client()
    assert client.get("/rdp-tool.html").status_code == 404
    assert client.get("/privacy.html").status_code == 404


def test_avvio_concorrente_risponde_409(db):
    raccolta.avvia(db, "sol", "manuale", "test")
    risposta = app_di_prova().post("/api/raccolta/avvia", json={"fonti": ["sol"]})
    assert risposta.status_code == 409
    assert "sol" in risposta.get_json()["msg"]


def test_protezione_applicata(db):
    def nega(f):
        @wraps(f)
        def _vietato(*a, **k):
            return "vietato", 401
        return _vietato
    client = app_di_prova(nega)
    assert client.get("/api/bandi").status_code == 401
    assert client.get("/monitoraggio").status_code == 401


def test_menu_voci_esistenti():
    from monitoraggio import config
    for gruppo in web.MENU:
        for voce in gruppo["voci"]:
            if "pagina" in voce:
                assert (config.ROOT / voce["pagina"]).exists(), voce["pagina"]
                assert voce["url"] == f"/{voce['pagina']}"
            else:
                assert voce["route"] and voce["url"].startswith("/monitoraggio")


def test_menu_locale_segna_le_voci_non_disponibili(db):
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint(pagine_disponibili=web.PAGINE_LOCALI))
    gruppi = app.test_client().get("/api/menu").get_json()["gruppi"]
    voci = {v["titolo"]: v["disponibile"] for g in gruppi for v in g["voci"]}
    assert voci["Riepilogo atti"] and voci["Controllo bandi"] and voci["Mobilità"]
    assert not voci["Redazione firme"] and not voci["Job firme"]


def test_tutte_le_pagine_includono_il_menu():
    from monitoraggio import config
    pagine = [v["pagina"] for g in web.MENU for v in g["voci"] if "pagina" in v] + ["privacy.html"]
    for pagina in pagine:
        assert '<script src="/monitoraggio/menu.js"' in (config.ROOT / pagina).read_text(encoding="utf-8"), pagina
    assert '<script src="/monitoraggio/menu.js"' in (web.STATIC / "riepilogo.html").read_text(encoding="utf-8")


def test_pagina_servita(db):
    risposta = app_di_prova().get("/monitoraggio")
    assert risposta.status_code == 200 and b"Monitoraggio bandi" in risposta.data


def test_caricamento_file_segreteria(db):
    import io

    from tests.test_segreteria import crea_excel
    client = app_di_prova()
    r = client.post("/api/segreteria/carica", data={"file": (io.BytesIO(crea_excel()), "riepilogo.xlsx")},
                    content_type="multipart/form-data")
    assert r.status_code == 201
    corpo = r.get_json()
    assert corpo["versione"]["esito"] == "in_uso" and corpo["differenze"]["precedente"] is None
    atti_file = client.get("/api/segreteria/atti").get_json()["atti"]
    grad = next(a for a in atti_file if a["categoria"] == "graduatoria" and a["protocollo"] == "270086")
    righe = client.get(f"/api/segreteria/atti/{grad['id']}/righe").get_json()["righe"]
    assert len(righe) == 2
    assert len(client.get("/api/segreteria/versioni").get_json()["versioni"]) == 1
    assert client.get("/monitoraggio/segreteria").status_code == 200


def test_caricamento_rifiutato(db):
    import io
    client = app_di_prova()
    r = client.post("/api/segreteria/carica", data={"file": (io.BytesIO(b"rotto"), "rotto.xlsx")},
                    content_type="multipart/form-data")
    assert r.status_code == 400 and "Excel" in r.get_json()["error"]
    r = client.post("/api/segreteria/carica", data={"file": (io.BytesIO(b"x"), "dati.csv")},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_referenti_senza_login_401(db):
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint(login_url="/login?next=/monitoraggio"))
    client = app.test_client()
    r = client.post("/api/referenti/aggiorna")
    assert r.status_code == 401 and r.get_json()["login"] == "/login?next=/monitoraggio"
    assert client.get("/api/referenti/stato").get_json()["collegato"] is False


def test_referenti_con_token_avvia(db, monkeypatch):
    chiamate = []
    monkeypatch.setattr(web.referenti, "aggiorna", lambda conn, token, utente: chiamate.append((token, utente)))
    monkeypatch.setattr(web.threading, "Thread", lambda target, **k: type("T", (), {"start": lambda self: target()})())
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint(token_utente=lambda: "TOKEN", utente_corrente=lambda: "u@cnr.it"))
    r = app.test_client().post("/api/referenti/aggiorna")
    assert r.status_code == 202 and chiamate == [("TOKEN", "u@cnr.it")]


def test_atti_con_rdp(db):
    from monitoraggio import atti, collegamento
    from tests.test_collegamento import salva, scheda
    salva(db, "sol", [scheda("sol", "obj-1", "367.601 FA ISTC", "367.601", data="2026-02-01")])
    collegamento.collega(db)
    scheda_id = db.execute("SELECT id FROM scheda").fetchone()[0]
    db.execute("INSERT INTO referente (scheda_id, chiave, nome, cognome, email, username, attivo, prima_rilevazione, "
               "ultima_rilevazione) VALUES (?, 'a', 'Anna', 'Esempio', 'anna@cnr.it', 'a', 1, 'x', 'x')", (scheda_id,))
    righe = atti.elenco_atti(db, "2026-01-01", "2026-12-31")
    assert righe[0]["rdp"] == [{"nome": "Anna", "cognome": "Esempio", "email": "anna@cnr.it"}]


def test_sessione_sol_solo_in_locale(db, monkeypatch):
    from monitoraggio import sol_sessione
    sol_sessione.dimentica()
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint())
    c = app.test_client()
    assert c.post("/api/sol/accedi").status_code == 404
    assert c.get("/api/sol/sessione").get_json()["disponibile"] is False
    avviati = []
    monkeypatch.setattr(sol_sessione, "avvia_login", lambda: avviati.append(1) or True)
    app2 = Flask(__name__)
    app2.register_blueprint(web.crea_blueprint(login_sol=True))
    r = app2.test_client().post("/api/sol/accedi")
    assert r.status_code == 202 and avviati == [1]


def test_ticket_solo_in_memoria_e_scadenza(monkeypatch):
    from datetime import timedelta

    from monitoraggio import sol_sessione
    sol_sessione.dimentica()
    with sol_sessione._lock:
        sol_sessione._stato.update(ticket="T", scade_il=sol_sessione._adesso() + timedelta(minutes=5))
    assert sol_sessione.ticket() == "T" and sol_sessione.intestazioni() == {"Cookie": "ticket=T"}
    assert "ticket" not in sol_sessione.stato() and sol_sessione.stato()["collegato"] is True
    with sol_sessione._lock:
        sol_sessione._stato["scade_il"] = sol_sessione._adesso() - timedelta(seconds=1)
    assert sol_sessione.ticket() is None and sol_sessione.stato()["collegato"] is False
    sol_sessione.dimentica()


def test_punteggi_api(db, monkeypatch):
    from monitoraggio import sol_sessione
    sol_sessione.dimentica()
    c = app_di_prova()
    assert c.post("/api/punteggi/verifica", json={"mese": "ottobre"}).status_code == 400
    r = c.post("/api/punteggi/verifica", json={"mese": "2026-10"})
    assert r.status_code == 401 and "SSO" in r.get_json()["error"]
    locale = Flask(__name__)
    locale.register_blueprint(web.crea_blueprint(login_sol=True))
    r = locale.test_client().post("/api/punteggi/verifica", json={"mese": "2026-10"})
    assert r.status_code == 401 and "Collega" in r.get_json()["error"]
    assert c.get("/api/punteggi?mese=2026-10").get_json()["righe"] == []


def test_file_segreteria_problemi_e_storico(db):
    import io

    from monitoraggio import atti
    from tests.test_segreteria import crea_excel
    c = app_di_prova()
    assert c.get("/api/segreteria/versioni").get_json()["versioni"] == []
    for nome in ("uno.xlsx", "due.xlsx"):
        c.post("/api/segreteria/carica", data={"file": (io.BytesIO(crea_excel()), nome)}, content_type="multipart/form-data")
    versioni = c.get("/api/segreteria/versioni").get_json()["versioni"]
    assert [v["esito"] for v in versioni] == ["in_uso", "precedente"] and [v["numero"] for v in versioni] == [2, 1]
    assert versioni[1]["differenze"]["precedente"] is None
    assert versioni[0]["differenze"] == {"precedente": versioni[1]["id"], "nuovi": 0, "spariti": 0, "modificati": 0}
    problemi = c.get(f"/api/segreteria/versioni/{versioni[0]['id']}/problemi").get_json()
    voci = problemi["scorrimento"]
    assert {"riga": 6, "bando": None, "problema": "senza_bando"} in voci
    assert {"riga": 5, "bando": "367.601 FA ISTC", "problema": "senza_tipologia"} in voci
    pagina = c.get("/monitoraggio/segreteria/file?atto=7")
    assert pagina.status_code == 302 and pagina.headers["Location"].endswith("/monitoraggio/segreteria?atto=7")
    assert atti.url_file_segreteria(atto=7) == "/monitoraggio/segreteria?atto=7"
    assert c.get("/api/segreteria/foglio").status_code == 404


def test_atti_del_file_con_link_a_urp(db):
    import io

    from tests.test_collegamento import doc, salva, scheda
    from tests.test_segreteria import crea_excel
    salva(db, "urp", [scheda("urp", "/n/1", "367.601 FA ISTC", "367.601", documenti=[{**doc("g1", "graduatoria", "270086", "2026-06-12"), "url": "http://urp/graduatoria.pdf"}]),
                      scheda("urp", "/n/2", "367.500", "367.500")])
    c = app_di_prova()
    c.post("/api/segreteria/carica", data={"file": (io.BytesIO(crea_excel()), "f.xlsx")}, content_type="multipart/form-data")
    atti = c.get("/api/segreteria/atti").get_json()["atti"]
    con_doc = next(a for a in atti if a["protocollo"] == "270086")
    assert con_doc["url_documento_urp"] == "http://urp/graduatoria.pdf" and con_doc["url_pagina_urp"] == "http://urp//n/1"
    altro_atto = next(a for a in atti if a["numero_bando"] == "367.601" and a["protocollo"] != "270086")
    assert altro_atto["url_documento_urp"] is None and altro_atto["url_pagina_urp"] == "http://urp//n/1"  # protocollo diverso: la pagina
    pagina = next(a for a in atti if a["numero_bando"] == "367.500")
    assert pagina["url_documento_urp"] is None and pagina["url_pagina_urp"] == "http://urp//n/2"
    assert next(a for a in atti if a["numero_bando"] == "367.434")["url_pagina_urp"] is None

