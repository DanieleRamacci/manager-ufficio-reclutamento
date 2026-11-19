"""Riepilogo e revisione del monitoraggio (spec 011): dai file caricati ai totali per gli altri."""
import io

from monitoraggio import avvisi_scorrimenti, posta  # noqa: F401
from tests.test_estrazione_sol import _candidato, _file
from tests.test_mensile import _configura_posta, _mese_con_rdp, ambiente  # noqa: F401  (fixture)


def _carica_estrazione(admin, mese, righe):
    return admin.post(f"/api/monitoraggi/{mese}/estrazione-graduatorie",
                      data={"file": (io.BytesIO(_file(righe)), "Punteggi.xlsx")}, content_type="multipart/form-data")


def test_estrazione_riepilogo_richiesta_e_revisione(ambiente, db, monkeypatch):  # noqa: F811
    inviati = []
    _configura_posta(monkeypatch, inviati, MAIL_PROVA="prova@esempio.it")
    admin, mese, _ = _mese_con_rdp(ambiente, db)
    r = admin.get(f"/api/monitoraggi/{mese}/riepilogo").get_json()
    graduatorie = next(c for c in r["totali"]["categorie"] if c["categoria"] == "Bandi con graduatoria")
    assert (graduatorie["totale"]["attesi"], graduatorie["totale"]["nei_file"]) == (1, 0) and graduatorie["nei_file_da"].startswith("estrazione")
    assert r["file"]["graduatorie"]["caricato"] is None
    # estrazione senza la graduatoria del monitoraggio: risulta mancante, con «Chiedi verifica» agli RdP del bando
    assert _carica_estrazione(admin, mese, [_candidato("367.999 RIC", "Ricercatore III livello", "Neri", "70", "1",
                                                      protocollo="0500001", data="10/04/2026")]).status_code == 200
    r = admin.get(f"/api/monitoraggi/{mese}/riepilogo").get_json()
    mancanti = next(c for c in r["totali"]["categorie"] if c["categoria"] == "Bandi con graduatoria")["mancanti"]
    assert [x["codice"] for x in mancanti] == ["367.479 CTER"]  # quale bando manca, per controllarlo nel monitoraggio
    voci = {v["codice"]: v for v in r["da_verificare"]}
    assert voci["367.479 CTER"]["problemi"][0] == "manca nell'estrazione da Selezioni Online (risulta: URP, Selezioni Online)" and "367.999 RIC" in voci
    anteprima = admin.get(f"/api/monitoraggi/{mese}/verifica-file/graduatorie/richiesta?chiave=367.479 CTER").get_json()
    assert anteprima["destinatari"] == ["rdp@cnr.it"] and "manca nell'estrazione" in anteprima["corpo"] and "nostro errore" in anteprima["corpo"]
    assert admin.post(f"/api/monitoraggi/{mese}/verifica-file/graduatorie/richiesta",
                      json={"chiave": "367.479 CTER", "modo": "prova", "oggetto": anteprima["oggetto"], "corpo": anteprima["corpo"]}).get_json() == {"ok": True, "prova": True}
    assert admin.post(f"/api/monitoraggi/{mese}/verifica-file/graduatorie/richiesta",
                      json={"chiave": "367.479 CTER", "modo": "boh", "oggetto": "x", "corpo": "y"}).status_code == 400
    assert inviati[-1]["To"] == "prova@esempio.it"
    r = admin.get(f"/api/monitoraggi/{mese}/riepilogo").get_json()
    assert next(v for v in r["da_verificare"] if v["codice"] == "367.479 CTER")["richiesta"]["esito"] == "prova"
    # con la graduatoria nell'estrazione è allineata e il file graduatorie si scarica
    _carica_estrazione(admin, mese, [_candidato("367.479 CTER", "Collaboratore tecnico enti di ricerca VI livello", "Rossi", "80", "1",
                                                protocollo="0001001", data="12/04/2026")])
    r = admin.get(f"/api/monitoraggi/{mese}/riepilogo").get_json()
    tot = next(c for c in r["totali"]["categorie"] if c["categoria"] == "Bandi con graduatoria")["totale"]
    assert (tot["attesi"], tot["nei_file"], tot["persone_nei_file"]) == (1, 1, 1)  # una graduatoria, una persona nell'estrazione
    assert r["file"]["graduatorie"]["allineato"] is True
    f = admin.get(f"/api/monitoraggi/{mese}/file-mese/graduatorie")
    assert f.status_code == 200 and f.headers["Cache-Control"] == "no-store"
    assert admin.get(f"/api/monitoraggi/{mese}/file-mese/graduatorie/anteprima").get_json()["righe"][0]["Cognome"] == "Rossi"
    assert admin.get(f"/api/monitoraggi/{mese}/file-mese/scorrimenti").status_code == 404
    # revisione: serve qualcuno a cui scrivere; poi email con il link e i totali, senza nominativi
    assert admin.post(f"/api/monitoraggi/{mese}/revisione").status_code == 400
    avvisi_scorrimenti.salva({"interni": "collega@cnr.it"}, "admin")
    admin.put(f"/api/monitoraggi/{mese}/riepilogo/testo", json={"testo": "Testo di prova della revisione."})
    esito = admin.post(f"/api/monitoraggi/{mese}/revisione", json={"modo": "prova"}).get_json()
    assert esito["ok"] and esito["prova"] and esito["destinatari"] == ["collega@cnr.it"] and inviati[-1]["To"] == "prova@esempio.it"
    assert admin.get(f"/api/monitoraggi/{mese}/riepilogo").get_json()["revisione"]["il"] is None  # la prova non la manda in revisione
    assert admin.post(f"/api/monitoraggi/{mese}/revisione", json={"modo": "ufficiale"}).status_code == 400  # ufficiali disattivate
    posta.salva_email({"ufficiali_attive": True}, "test")
    esito = admin.post(f"/api/monitoraggi/{mese}/revisione", json={"modo": "ufficiale"}).get_json()
    assert esito["ok"] and not esito["prova"] and inviati[-1]["To"] == "collega@cnr.it"  # invio vero, anche con le prove attive
    testo = inviati[-1].get_content()
    assert "Testo di prova della revisione." in testo and f"/referenti/monitoraggi/{mese}" in testo and "Bandi con graduatoria: 1 · nei file 1 (1 persona)" in testo
    assert "Rossi" not in testo
    assert admin.get(f"/api/monitoraggi/{mese}/riepilogo").get_json()["revisione"]["il"]
    # in consultazione: i link ai file e i totali, senza l'elenco e senza nominativi
    admin.put(f"/api/monitoraggi/{mese}", json={"link_scorrimenti": "https://onedrive.example/s.xlsx"})
    c = admin.get(f"/api/consulta/monitoraggi/{mese}").get_json()
    assert c["file_link"]["scorrimenti"] == "https://onedrive.example/s.xlsx" and c["revisione"]["totali"]["categorie"][1]["totale"]["nei_file"] == 1
    assert "da_verificare" not in c and "Rossi" not in str(c["revisione"])


def test_solo_amministratori(ambiente, db):  # noqa: F811
    admin, mese, _ = _mese_con_rdp(ambiente, db)
    admin.post("/api/utenti", json={"username": "lettore.uno", "ruolo": "lettura"})
    altro = admin.application.test_client()
    for url in (f"/api/monitoraggi/{mese}/riepilogo", f"/api/monitoraggi/{mese}/file-mese/graduatorie",
                f"/api/monitoraggi/{mese}/verifica-file/graduatorie/richiesta?chiave=x"):
        assert altro.get(url).status_code in (302, 401, 403)


def test_estrazione_mobilita_a_parte_e_nel_foglio_mobilita(ambiente, db):  # noqa: F811
    import openpyxl
    admin, mese, _ = _mese_con_rdp(ambiente, db)
    _carica_estrazione(admin, mese, [_candidato("367.479 CTER", "Collaboratore tecnico enti di ricerca VI livello", "Concorso", "80", "1",
                                                protocollo="0001001", data="12/04/2026")])
    r = admin.post(f"/api/monitoraggi/{mese}/estrazione-graduatorie?tipo=mobilita",
                   data={"file": (io.BytesIO(_file([_candidato("367.900 MOB", "Tecnologo III livello", "Mobile", "50", "1", protocollo="0009001",
                                                                data="15/04/2026")])), "Punteggi-mobilita.xls"[:-4] + ".xlsx")},
                   content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["caricati"]["mobilita"]["nome_file"] == "Punteggi-mobilita.xlsx"
    assert r.get_json()["caricati"]["concorsi"] is not None  # la prima estrazione resta
    assert admin.post(f"/api/monitoraggi/{mese}/estrazione-graduatorie?tipo=altro").status_code == 400
    # la graduatoria di mobilità non è nel monitoraggio: si segnala, e va nel foglio delle mobilità
    voci = admin.get(f"/api/monitoraggi/{mese}/riepilogo").get_json()["da_verificare"]
    assert any(v["codice"] == "367.900 MOB" for v in voci)
    wb = openpyxl.load_workbook(io.BytesIO(admin.get(f"/api/monitoraggi/{mese}/file-mese/graduatorie").data))
    cognomi = lambda foglio: [c.value for c in wb[foglio]["G"][2:]]  # noqa: E731  (colonna Cognome)
    assert "Mobile" in cognomi("Graduatorie mobilità") and "Mobile" not in cognomi("Graduatorie pubblicate")
    assert "Concorso" in cognomi("Graduatorie pubblicate")
