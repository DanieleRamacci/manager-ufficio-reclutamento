"""Area dei referenti: ognuno vede solo i propri bandi, con accesso dimostrato dalla casella."""
import json
import re

import pytest

from monitoraggio import collegamento, mensile, portale, posta, punteggi, utenti
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
    return {"mese": mese, "chiave": riga["chiave"], "atto": riga["atto"], "protocollo": riga["protocollo"] or "", "data": riga["data"] or "",
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
    assert set(righe[0]) == {"chiave", "titolo_bando", "atto", "protocollo", "data", "fonti", "link_sol", "rilievi", "rdp", "profilo", "verifica_punteggi", "link_punteggi"}
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


def _pagine_aperte(admin, c, mese, ammesse):
    aperte = []
    for regola in admin.application.url_map.iter_rules():
        if "GET" in regola.methods and regola.endpoint != "static":
            url = regola.rule
            for nome in regola.arguments:
                url = re.sub(rf"<[^>]*{nome}>", {"mese": mese, "codice": CODICE_A}.get(nome, "1"), url)
            if url not in ammesse and c.get(url).status_code not in (302, 401, 403):
                aperte.append(url)
    return aperte


def _ammesse(mese):
    return {"/referenti", "/referenti/stato", "/referenti/monitoraggi", f"/referenti/monitoraggi/{mese}", "/referenti/profili",
            "/api/area-referenti/bandi", "/api/area-referenti/chi", "/api/area-referenti/consulta/stato", "/api/area-referenti/consulta/monitoraggi",
            f"/api/area-referenti/consulta/monitoraggi/{mese}", "/monitoraggio/app.css", "/monitoraggio/app.js"}


def test_il_referente_apre_solo_le_pagine_dell_area(area):
    admin, mese, inviati = area
    c = _entra(admin, inviati, ANNA)
    assert _pagine_aperte(admin, c, mese, _ammesse(mese)) == []
    stato = c.get("/api/area-referenti/consulta/stato").get_json()
    assert {r["numero_bando"] for r in stato["righe"]} == {"367.479"} and all(r["come"] == ["rdp"] for r in stato["righe"])
    righe = c.get(f"/api/area-referenti/consulta/monitoraggi/{mese}").get_json()["righe"]
    assert [r["codice"] for r in righe] == [CODICE_A] and righe[0]["url_punteggi"] and righe[0]["punteggi"] is None or righe[0]["punteggi"]["scheda_id"] is None
    assert c.get(f"/api/area-referenti/consulta/candidati/{1}").status_code == 404  # nomi e punteggi mai nell'area


# --- coordinatori
CTER, RIC = "Collaboratore tecnico VI livello", "Ricercatore III livello"
COORD = "coord@cnr.it"


def _profili(db):
    for id_esterno, profilo in (("s1", CTER), ("s2", RIC)):
        db.execute("UPDATE scheda SET dati_extra = ? WHERE id_esterno = ?", (json.dumps({"profilo": profilo}), id_esterno))


def _coordinatore(admin, db, inviati):
    _profili(db)
    assert admin.post("/api/coordinatori", json={"email": COORD.upper()}).get_json() == {"ok": True, "email": COORD}
    return _entra(admin, inviati, COORD)


def test_coordinatore_sceglie_i_profili_e_vede_quei_bandi_in_sola_consultazione(area, db):
    admin, mese, inviati = area
    c = _coordinatore(admin, db, inviati)
    assert c.get("/api/area-referenti/chi").get_json() == {"email": COORD, "coordinatore": True, "profili": [], "anteprima": False}
    d = c.get("/api/area-referenti/profili").get_json()
    assert [(p["profilo"], p["titolare"]) for p in d["profili"]] == [(CTER, None), (RIC, None)]
    assert c.get(f"/api/area-referenti/consulta/monitoraggi/{mese}").get_json()["righe"] == []
    assert c.post("/api/area-referenti/profili/prendi", json={"profilo": CTER}).get_json() == {"ok": True}
    righe = c.get(f"/api/area-referenti/consulta/monitoraggi/{mese}").get_json()["righe"]
    assert [x["codice"] for x in righe] == [CODICE_A] and righe[0]["come"] == ["coordinatore"] and righe[0]["url_punteggi"] is None and righe[0]["rilievi"]
    assert not any(x["segnalabile"] for x in righe[0]["rilievi"])
    assert {r["numero_bando"] for r in c.get("/api/area-referenti/consulta/stato").get_json()["righe"]} == {"367.479"}
    # i profili restano al prossimo accesso
    portale._ultima_email.clear()
    assert _entra(admin, inviati, COORD).get("/api/area-referenti/chi").get_json()["profili"] == [CTER]
    # solo tra quelli di Selezioni Online
    assert c.post("/api/area-referenti/profili/prendi", json={"profilo": "inventato"}).status_code == 400
    assert c.post("/api/area-referenti/profili/lascia", json={"profilo": CTER}).get_json() == {"ok": True}
    assert c.get("/api/area-referenti/chi").get_json()["profili"] == []


def test_un_profilo_un_coordinatore_e_la_richiesta_avvisa_entrambi(area, db):
    admin, mese, inviati = area
    c = _coordinatore(admin, db, inviati)
    c.post("/api/area-referenti/profili/prendi", json={"profilo": CTER})
    admin.post("/api/coordinatori", json={"email": "altro@cnr.it"})
    portale._ultima_email.clear()
    altro = _entra(admin, inviati, "altro@cnr.it")
    r = altro.post("/api/area-referenti/profili/prendi", json={"profilo": CTER})
    assert r.status_code == 409 and r.get_json()["titolare"] == COORD
    n = len(inviati)
    assert altro.post("/api/area-referenti/profili/richiedi", json={"profilo": CTER}).get_json() == {"ok": True}
    assert altro.post("/api/area-referenti/profili/richiedi", json={"profilo": CTER}).get_json() == {"ok": True}  # niente doppioni
    assert len(inviati) == n + 1 and {*inviati[-1]["To"].split(", ")} == {COORD, "altro@cnr.it"} and CTER in inviati[-1]["Subject"]
    assert altro.get("/api/area-referenti/profili").get_json()["profili"][0]["chiesto"] is True
    richiesta = c.get("/api/area-referenti/profili").get_json()["richieste_ricevute"][0]
    assert altro.post(f"/api/area-referenti/profili/richieste/{richiesta['id']}/cedi").status_code == 404  # cede solo chi lo ha
    assert c.post(f"/api/area-referenti/profili/richieste/{richiesta['id']}/cedi").get_json() == {"ok": True}
    assert altro.get("/api/area-referenti/chi").get_json()["profili"] == [CTER] and c.get("/api/area-referenti/chi").get_json()["profili"] == []
    # l'amministratore decide in ultima istanza
    c.post("/api/area-referenti/profili/richiedi", json={"profilo": CTER})
    voce = admin.get("/api/utenti").get_json()
    assert [p["titolare"] for p in voce["profili"] if p["profilo"] == CTER] == ["altro@cnr.it"] and len(voce["richieste_profili"]) == 1
    assert admin.post(f"/api/profili-coordinati/richieste/{voce['richieste_profili'][0]['id']}", json={"accolta": True}).get_json() == {"ok": True}
    assert c.get("/api/area-referenti/chi").get_json()["profili"] == [CTER]
    assert admin.post("/api/profili-coordinati/assegna", json={"profilo": RIC, "email": "nessuno@cnr.it"}).status_code == 400
    assert admin.post("/api/profili-coordinati/assegna", json={"profilo": RIC, "email": "altro@cnr.it"}).get_json() == {"ok": True}
    assert altro.get("/api/area-referenti/chi").get_json()["profili"] == [RIC]


def test_coordinatore_non_segnala_sui_bandi_altrui(area, db):
    admin, mese, inviati = area
    c = _coordinatore(admin, db, inviati)
    c.post("/api/area-referenti/profili/prendi", json={"profilo": CTER})
    riga = c.get(f"/api/area-referenti/consulta/monitoraggi/{mese}").get_json()["righe"][0]
    assert c.post("/api/area-referenti/segnala", json=_segnalazione(mese, riga)).status_code == 404


def test_coordinatore_apre_solo_l_area_e_non_e_utente_del_sito(area, db):
    admin, mese, inviati = area
    c = _coordinatore(admin, db, inviati)
    assert utenti.ruolo(COORD) is None
    assert _pagine_aperte(admin, c, mese, _ammesse(mese) | {"/api/area-referenti/profili"}) == []
    for metodo, url in (("post", f"/api/monitoraggi/{mese}/comunicazioni/{CODICE_A}/invia"), ("post", f"/api/monitoraggi/{mese}/comunicazioni-invia-tutti"),
                        ("post", "/api/coordinatori")):
        assert getattr(c, metodo)(url, json={"modo": "ufficiale"}).status_code in (302, 401, 403), url


def test_difformita_per_tutti_link_ai_punteggi_solo_a_chi_e_rdp(db, monkeypatch):
    riga = {"chiave": "367.1 CTER", "atto": "graduatoria", "scheda_sol_id": 7, "rdp_origine": "codice", "fonti": {}, "url_punteggi": "https://sol.esempio/punteggi?id=7",
            "rilievi": ["mancano i punteggi su SOL", "protocollo diverso: SOL 1, URP 2"], "punteggi": {"verificato_il": "2026-11-09T10:00:00Z"}}
    db.execute("INSERT INTO monitoraggio_mese (mese, mese_dati, creato_il) VALUES ('2026-05', '2026-04', 'x')")
    m = {"mese": "2026-05", "mese_dati": "2026-04"}
    monkeypatch.setattr(portale.comunicazioni, "righe_mese", lambda conn, mm: [{**riga, "rdp": [{"email": ANNA}]}])
    altro = portale._vista(db, m, COORD, [CTER], ({7: CTER}, {}))
    bando = altro["bandi"][0]
    assert len(bando["rilievi"]) == 2 and bando["rdp"] is False and bando["link_punteggi"] is None and bando["verifica_punteggi"] == "2026-11-09T10:00:00Z"
    assert [f["fonte"] for f in altro["aggiornamenti"]] == ["sol", "urp", "segreteria"]
    assert portale._vista(db, m, ANNA, [CTER], ({7: CTER}, {}))["bandi"][0]["link_punteggi"] == "https://sol.esempio/punteggi?id=7"


def test_nessun_dato_dei_candidati_nell_area(area, db, monkeypatch):
    admin, mese, inviati = area
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = 's1'").fetchone()[0]
    monkeypatch.setitem(punteggi._candidati, sid, {"verificato_il": "x", "candidati": [{"cognome": "Rossi", "nome": "Mario", "codice_fiscale": "RSSMRA80A01H501U"}]})
    a = _entra(admin, inviati, ANNA)
    r = a.get("/api/area-referenti/bandi")
    assert r.status_code == 200 and "Rossi" not in r.get_data(as_text=True) and "RSSMRA" not in r.get_data(as_text=True)
    assert a.get("/api/area-referenti/candidati").status_code == 404


def test_coordinatore_anche_rdp_vede_i_suoi_bandi_senza_scegliere_il_profilo(area, db):
    admin, mese, inviati = area
    _profili(db)
    admin.post("/api/coordinatori", json={"email": ANNA})
    righe = _entra(admin, inviati, ANNA).get("/api/area-referenti/bandi").get_json()["monitoraggi"][0]["bandi"]
    assert [(x["chiave"], x["rdp"]) for x in righe] == [(CODICE_A, True)]


def test_gestione_coordinatori(area, db):
    admin, mese, inviati = area
    c = _coordinatore(admin, db, inviati)
    voce = admin.get("/api/utenti").get_json()["coordinatori"]
    assert [x["email"] for x in voce] == [COORD]
    assert admin.post("/api/coordinatori", json={"email": "a b"}).status_code == 400
    assert admin.post("/api/coordinatori", json={"email": "Mario.Rossi"}).get_json()["email"] == "mario.rossi@cnr.it"
    admin.delete("/api/coordinatori/mario.rossi@cnr.it")
    n = len(inviati)
    assert admin.post(f"/api/coordinatori/{COORD}/invia-accesso").get_json() == {"ok": True}
    assert len(inviati) == n + 1 and inviati[-1]["To"] == COORD and "/referenti" in inviati[-1].get_content() and "codice=" not in inviati[-1].get_content()
    assert admin.post("/api/coordinatori/altro@cnr.it/invia-accesso").status_code == 404
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "dirigente"})
    with admin.application.test_client() as lettore:
        with lettore.session_transaction() as s:
            s["user"] = "lettore.uno"
        assert lettore.post("/api/coordinatori", json={"email": "x@cnr.it"}).status_code == 403
        assert lettore.delete(f"/api/coordinatori/{COORD}").status_code == 403
    posta.salva_email({"portale_referenti": False}, "t")
    assert admin.post(f"/api/coordinatori/{COORD}/invia-accesso").status_code == 409
    posta.salva_email({"portale_referenti": True}, "t")
    c.post("/api/area-referenti/profili/prendi", json={"profilo": CTER})
    assert admin.get("/api/utenti").get_json()["coordinatori"][0]["profili"] == [CTER]
    assert admin.delete(f"/api/coordinatori/{COORD}").get_json() == {"ok": True}
    d = c.get("/api/area-referenti/bandi").get_json()  # toglierlo ha effetto subito
    assert d["coordinatore"] is False and d["monitoraggi"][0]["bandi"] == []
    assert admin.delete(f"/api/coordinatori/{COORD}").status_code == 404


# --- anteprima dell'amministratore

def _come(admin, nome="capo.ufficio"):
    c = admin.application.test_client()
    with c.session_transaction() as s:
        s["user"] = nome
    return c

def test_anteprima_area_come_referente_senza_poter_segnalare(area, db):
    admin, mese, inviati = area
    c = _come(admin)
    assert c.post("/api/area-referenti/anteprima", json={"email": "nessuno@cnr.it"}).status_code == 404
    assert c.post("/api/area-referenti/anteprima", json={"email": ANNA.upper()}).get_json()["url"] == f"{portale.PAGINA}/stato"
    d = c.get("/api/area-referenti/bandi").get_json()
    assert d["email"] == ANNA and d["anteprima"] is True
    assert {b["chiave"] for m in d["monitoraggi"] for b in m["bandi"]} <= {CODICE_A}
    r = c.post("/api/area-referenti/segnala", json={"mese": mese, "nota": "x"})
    assert r.status_code == 403 and "Anteprima" in r.get_json()["error"]
    assert not db.execute("SELECT 1 FROM segnalazione").fetchone()
    assert c.post("/api/area-referenti/esci").get_json()["anteprima"] is True
    assert c.get("/api/utenti").status_code == 200  # resta amministratore
    assert c.get("/api/area-referenti/bandi").status_code == 401
    assert inviati == []  # nessuna email al referente


def test_anteprima_area_solo_per_amministratori(area):
    admin, _, _ = area
    utenti_conn = _come(admin)
    assert utenti_conn.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"}).status_code == 200
    lettore = _come(admin, "lettore.uno")
    assert lettore.post("/api/area-referenti/anteprima", json={"email": ANNA}).status_code == 403
    with lettore.session_transaction() as s:  # anche forzando la sessione, senza ruolo di amministratore non vale
        s["anteprima_referente"], s["anteprima_fino"] = ANNA, "2999-01-01T00:00:00+00:00"
    assert lettore.get("/api/area-referenti/bandi").status_code == 401


def test_anteprima_area_anche_se_spenta(area):
    admin, _, _ = area
    posta.salva_email({"portale_referenti": False}, "t")
    c = _come(admin)
    assert c.post("/api/area-referenti/anteprima", json={"email": ANNA}).status_code == 200
    assert c.get(portale.PAGINA).status_code == 200
    assert admin.application.test_client().get(portale.PAGINA).status_code == 404  # per gli altri resta spenta


def test_vista_come_utente_in_lettura(area):
    admin, mese, _ = area
    c = _come(admin)
    assert c.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"}).status_code == 200
    assert c.post("/api/utenti/capo.ufficio/vista").status_code == 400
    assert c.post("/api/utenti/lettore.uno/vista").status_code == 200
    menu = c.get("/api/menu").get_json()
    assert menu["ruolo"] == "lettura" and menu["vista_come"] == "lettore.uno" and menu["utente"] == "capo.ufficio"
    assert c.get("/api/utenti").status_code == 403  # come lui: niente pagine da amministratore
    assert c.get(f"/api/monitoraggi/{mese}").status_code == 403  # come lui: solo la consultazione
    assert c.get("/api/consulta/stato").get_json()["visitatore"]["senza_bandi"] is True  # e non essendo RdP non vedrebbe niente
    r = c.post("/api/sol/esci")
    assert r.status_code == 403 and "Anteprima come lettore.uno" in r.get_json()["error"]
    assert c.post("/api/vista-come/esci").status_code == 200
    assert c.get("/api/menu").get_json()["ruolo"] == "amministratore"
    registro = c.get("/api/utenti").get_json()["registro"]
    assert registro[0]["azione"] == "anteprima" and registro[0]["username"] == "lettore.uno"


def test_coordinatore_del_profilo_visibile_e_in_copia_solo_con_la_spunta(area, db):
    admin, mese, inviati = area
    c = _coordinatore(admin, db, inviati)
    c.post("/api/area-referenti/profili/prendi", json={"profilo": CTER})
    righe = admin.get(f"/api/monitoraggi/{mese}/atti").get_json()["righe"]
    assert next(r for r in righe if r["codice"] == CODICE_A)["coordinatore"] == {"email": COORD, "profilo": CTER}
    assert next(r for r in righe if r["codice"] == CODICE_B)["coordinatore"] is None
    url = f"/api/monitoraggi/{mese}/comunicazioni/{CODICE_A}"
    d = admin.get(url + "/messaggio").get_json()
    assert d["coordinatore"] == {"email": COORD, "profilo": CTER, "incluso": False} and COORD not in d["cc"]
    d = admin.put(url + "/indirizzi", json={"esclusi": [], "cc": [], "coordinatore": True}).get_json()
    assert d["coordinatore"]["incluso"] is True and COORD in d["cc"]
    d = admin.put(url + "/indirizzi", json={"esclusi": [], "cc": ["altro@cnr.it"]}).get_json()  # senza la voce resta com'era
    assert COORD in d["cc"] and "altro@cnr.it" in d["cc"]
    n = len(inviati)
    assert admin.post(url + "/invia", json={"modo": "ufficiale"}).status_code == 200
    assert len(inviati) == n + 1 and COORD in inviati[-1]["Cc"] and inviati[-1]["To"] == ANNA
