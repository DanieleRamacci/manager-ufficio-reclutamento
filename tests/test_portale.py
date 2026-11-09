"""Area dei referenti: ognuno vede solo i propri bandi, con accesso dimostrato dalla casella."""
import re

import pytest

from monitoraggio import collegamento, mensile, portale, posta
from tests.test_collegamento import doc, salva, scheda
from tests.test_mensile import _configura_posta, ambiente  # noqa: F401

ANNA, BRUNO = "anna@cnr.it", "bruno@cnr.it"
CODICE_A, CODICE_B = "367.479 CTER", "367.500 CTER"


def _referente(db, id_esterno, chiave, email):
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = ?", (id_esterno,)).fetchone()[0]
    db.execute("INSERT INTO referente (scheda_id, chiave, nome, cognome, email, username, attivo, prima_rilevazione, ultima_rilevazione) "
               "VALUES (?, ?, 'N', 'C', ?, ?, 1, 'x', 'x')", (sid, chiave, email, chiave))


@pytest.fixture
def area(ambiente, db, monkeypatch):  # noqa: F811
    inviati = []
    _configura_posta(monkeypatch, inviati)
    monkeypatch.setattr(portale, "_in_background", lambda fn, *a: fn(*a))
    for diz in (portale._codici, portale._ultima_email, portale._richieste_ip):
        diz.clear()
    salva(db, "sol", [scheda("sol", "s1", CODICE_A, "367.479", documenti=[doc("g1", "graduatoria", "1001", "2026-04-12")]),
                      scheda("sol", "s2", CODICE_B, "367.500", documenti=[doc("g3", "graduatoria", "2001", "2026-04-13")])])
    salva(db, "urp", [scheda("urp", "/node/1", CODICE_A, "367.479", documenti=[doc("g2", "graduatoria", "1002", "2026-04-12")]),
                      scheda("urp", "/node/2", CODICE_B, "367.500", documenti=[doc("g4", "graduatoria", "2002", "2026-04-13")])])
    collegamento.collega(db)
    admin = ambiente()
    mese = mensile.crea(db, "2026-05", None, "capo.ufficio")["mese"]
    _referente(db, "s1", "a", ANNA)
    _referente(db, "s2", "b", BRUNO)
    posta.salva_email({"prova_attiva": False, "ufficiali_attive": True, "portale_referenti": True}, "t")
    return admin, mese, inviati


def _entra(admin, inviati, email):
    c = admin.application.test_client()
    assert c.post("/api/area-referenti/link", json={"email": email}).get_json() == {"ok": True}
    codice = re.search(r"codice=([\w-]+)", inviati[-1].get_content()).group(1)
    assert inviati[-1]["To"] == email and c.post("/api/area-referenti/entra", json={"codice": codice}).status_code == 200
    return c


def _segnalazione(mese, riga, **extra):
    return {"mese": mese, "chiave": riga["chiave"], "atto": riga["atto"], "protocollo": riga["protocollo"], "data": riga["data"],
            "rilievo": riga["rilievi"][0]["testo"], "nota": "Il protocollo è corretto", **extra}


def test_spenta_non_esiste(area):
    admin, _, inviati = area
    posta.salva_email({"portale_referenti": False}, "t")
    c = admin.application.test_client()
    assert c.get("/referenti").status_code == 404
    assert c.post("/api/area-referenti/link", json={"email": ANNA}).status_code == 404
    assert c.get("/api/area-referenti/bandi").status_code == 404 and inviati == []


def test_link_solo_ai_referenti_e_sempre_stessa_risposta(area):
    admin, _, inviati = area
    c = admin.application.test_client()
    for email in ("estraneo@cnr.it", "non-email", ""):
        assert c.post("/api/area-referenti/link", json={"email": email}).get_json() == {"ok": True}
    assert inviati == []
    assert c.post("/api/area-referenti/link", json={"email": ANNA.upper()}).get_json() == {"ok": True}
    assert len(inviati) == 1 and inviati[0]["To"] == ANNA
    assert c.post("/api/area-referenti/link", json={"email": ANNA}).get_json() == {"ok": True} and len(inviati) == 1  # non più di una al minuto


def test_troppe_richieste_dallo_stesso_indirizzo(area):
    admin, _, inviati = area
    c = admin.application.test_client()
    for _ in range(portale.MAX_RICHIESTE_IP):
        c.post("/api/area-referenti/link", json={"email": "estraneo@cnr.it"})
    c.post("/api/area-referenti/link", json={"email": ANNA})
    assert inviati == []


def test_link_monouso_e_codice_falso(area):
    admin, _, inviati = area
    c = admin.application.test_client()
    assert c.post("/api/area-referenti/entra", json={"codice": "inventato"}).status_code == 401
    assert c.get("/api/area-referenti/bandi").status_code == 401
    c.post("/api/area-referenti/link", json={"email": ANNA})
    codice = re.search(r"codice=([\w-]+)", inviati[-1].get_content()).group(1)
    assert c.post("/api/area-referenti/entra", json={"codice": codice}).status_code == 200
    assert admin.application.test_client().post("/api/area-referenti/entra", json={"codice": codice}).status_code == 401


def test_ognuno_vede_solo_i_suoi_bandi(area):
    admin, mese, inviati = area
    c = _entra(admin, inviati, ANNA)
    r = c.get("/api/area-referenti/bandi")
    d = r.get_json()
    assert r.headers["Cache-Control"] == "no-store" and d["email"] == ANNA
    righe = d["monitoraggi"][0]["bandi"]
    assert {x["chiave"] for x in righe} == {CODICE_A} and righe[0]["rilievi"]
    assert set(righe[0]) == {"chiave", "titolo_bando", "atto", "protocollo", "data", "fonti", "link_sol", "rilievi"}
    testo = r.get_data(as_text=True)
    assert BRUNO not in testo and CODICE_B not in testo


def test_il_referente_non_entra_nel_resto_del_sito(area):
    admin, mese, inviati = area
    c = _entra(admin, inviati, ANNA)
    for url in (f"/api/monitoraggi/{mese}", f"/api/monitoraggi/{mese}/atti", "/api/comunicazioni", f"/api/monitoraggi/{mese}/segnalazioni"):
        assert c.get(url).status_code in (302, 401, 403), url
    assert c.get("/monitoraggio/app.css").status_code == 200


def test_uscita_chiude_la_sessione(area):
    admin, _, inviati = area
    c = _entra(admin, inviati, ANNA)
    assert c.post("/api/area-referenti/esci").status_code == 200 and c.get("/api/area-referenti/bandi").status_code == 401


def test_escluso_dal_messaggio_non_vede_il_bando(area):
    admin, mese, inviati = area
    c = _entra(admin, inviati, ANNA)
    admin.put(f"/api/monitoraggi/{mese}/comunicazioni/{CODICE_A}/indirizzi", json={"esclusi": [ANNA], "cc": []})
    assert c.get("/api/area-referenti/bandi").get_json()["monitoraggi"][0]["bandi"] == []


def test_mese_chiuso_non_compare(area):
    admin, mese, inviati = area
    c = _entra(admin, inviati, ANNA)
    assert admin.post(f"/api/monitoraggi/{mese}/chiudi").status_code == 200
    assert c.get("/api/area-referenti/bandi").get_json()["monitoraggi"] == []


def test_segnalazione_del_falso_positivo(area):
    admin, mese, inviati = area
    a = _entra(admin, inviati, ANNA)
    riga = a.get("/api/area-referenti/bandi").get_json()["monitoraggi"][0]["bandi"][0]
    assert a.post("/api/area-referenti/segnala", json=_segnalazione(mese, riga)).status_code == 200
    assert a.post("/api/area-referenti/segnala", json=_segnalazione(mese, riga, nota="Motivo aggiornato")).status_code == 200  # niente doppioni
    assert a.get("/api/area-referenti/bandi").get_json()["monitoraggi"][0]["bandi"][0]["rilievi"][0]["segnalazione"]["nota"] == "Motivo aggiornato"
    assert admin.get(f"/api/monitoraggi/{mese}").get_json()["segnalazioni"] == {"totali": 1, "aperte": 1}
    voci = admin.get(f"/api/monitoraggi/{mese}/segnalazioni").get_json()["segnalazioni"]
    assert len(voci) == 1 and voci[0]["email"] == ANNA and voci[0]["nota"] == "Motivo aggiornato"
    url = f"/api/monitoraggi/{mese}/segnalazioni/{voci[0]['id']}"
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    assert admin.application.test_client().put(url, json={"gestita": True}).status_code in (302, 401, 403)
    assert admin.put(url, json={"gestita": True}).get_json() == {"ok": True}
    assert admin.get(f"/api/monitoraggi/{mese}").get_json()["segnalazioni"] == {"totali": 1, "aperte": 0}
    assert admin.put(f"/api/monitoraggi/{mese}/segnalazioni/999", json={"gestita": True}).status_code == 404


def test_non_si_segnala_sui_bandi_altrui_o_con_dati_personali(area):
    admin, mese, inviati = area
    a, b = _entra(admin, inviati, ANNA), _entra(admin, inviati, BRUNO)
    di_bruno = b.get("/api/area-referenti/bandi").get_json()["monitoraggi"][0]["bandi"][0]
    assert a.post("/api/area-referenti/segnala", json=_segnalazione(mese, di_bruno)).status_code == 404
    mia = a.get("/api/area-referenti/bandi").get_json()["monitoraggi"][0]["bandi"][0]
    assert a.post("/api/area-referenti/segnala", json=_segnalazione(mese, mia, rilievo="inventato")).status_code == 404
    assert a.post("/api/area-referenti/segnala", json=_segnalazione(mese, mia, nota="")).status_code == 400
    assert a.post("/api/area-referenti/segnala", json=_segnalazione(mese, mia, nota="x" * 1001)).status_code == 400
    assert a.post("/api/area-referenti/segnala", json=_segnalazione(mese, mia, nota="Candidato RSSMRA80A01H501U")).status_code == 400
    assert admin.get(f"/api/monitoraggi/{mese}").get_json()["segnalazioni"]["totali"] == 0


def test_spiegazione_solo_nell_email_ai_colleghi(area):
    admin, mese, _ = area
    url = f"/api/monitoraggi/{mese}/comunicazioni/{CODICE_A}/messaggio"
    assert "/referenti" not in admin.get(url).get_json()["corpo"]
    corpo = admin.get(f"/api/monitoraggi/{mese}").get_json()["email"]["corpo"]
    assert corpo.index("/referenti") < corpo.index("Per altro sono a disposizione") < corpo.rindex("Ciao,")
    posta.salva_email({"portale_referenti": False}, "t")
    assert "/referenti" not in admin.get(f"/api/monitoraggi/{mese}").get_json()["email"]["corpo"]


def test_bando_con_piu_referenti_visto_da_ciascuno_senza_vedere_gli_altri(area, db):
    admin, mese, inviati = area
    _referente(db, "s1", "c", "carla@cnr.it")
    for email in (ANNA, "carla@cnr.it"):
        r = _entra(admin, inviati, email).get("/api/area-referenti/bandi")
        assert {x["chiave"] for x in r.get_json()["monitoraggi"][0]["bandi"]} == {CODICE_A}
        altro = "carla@cnr.it" if email == ANNA else ANNA
        assert altro not in r.get_data(as_text=True)


def test_atto_senza_rdp_propri_non_si_mostra(db, monkeypatch):
    riga = {"chiave": "367.1 CTER", "atto": "graduatoria", "rilievi": ["x"], "rdp": [{"email": ANNA}]}
    monkeypatch.setattr(portale.comunicazioni, "righe_mese", lambda conn, m: [{**riga, "rdp_origine": "codice"}, {**riga, "rdp_origine": "tutti i codici"}])
    db.execute("INSERT INTO monitoraggio_mese (mese, mese_dati, creato_il) VALUES ('2026-05', '2026-04', 'x')")
    assert [r["rdp_origine"] for r in portale._righe_di(db, {"mese": "2026-05"}, ANNA)] == ["codice"]


def test_il_referente_apre_una_sola_pagina(area):
    admin, mese, inviati = area
    c = _entra(admin, inviati, ANNA)
    ammesse = {"/referenti", "/api/area-referenti/bandi", "/monitoraggio/app.css"}
    aperte = []
    for regola in admin.application.url_map.iter_rules():
        if "GET" in regola.methods and regola.endpoint != "static":
            url = regola.rule
            for nome in regola.arguments:
                url = re.sub(rf"<[^>]*{nome}>", {"mese": mese, "codice": CODICE_A}.get(nome, "1"), url)
            if url not in ammesse and c.get(url).status_code not in (302, 401, 403):
                aperte.append(url)
    assert aperte == []
