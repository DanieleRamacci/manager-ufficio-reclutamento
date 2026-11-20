"""Spec 012: concorsi deserti, bandi revocati, concorsi senza esito, esportazione Excel."""
import io
import json
from datetime import date

import openpyxl
import pytest
from flask import Flask

from monitoraggio import atti, collegamento, db as dbmod, esporta, web
from monitoraggio.classifica import categoria
from tests.test_collegamento import doc, salva, scheda


# ----------------------------------------------------------------- classificazione

@pytest.mark.parametrize("titolo, tipo, attesa", [
    ("conclusione del procedimento con esito negativo - Prot. n. 196365", None, "deserto"),
    ("364.304 CONCORSO DESERTO_signed.pdf", None, "deserto"),
    ("SELEZIONE DESERTA 365.145", None, "deserto"),
    ("Provvedimento di conclusione senza candidati", None, "deserto"),
    ("Graduatoria - esito negativo - cod. 07", None, "deserto"),
    ("Provv di Graduatoria deserta", "D:jconon_attachment:call_classification", "deserto"),
    ("Provv-approvazione-atti-bando-IR_signed.pdf", "D:jconon_attachment:call_deserto", "deserto"),
    ("Esito negativo prova asincrona del 29 aprile 2026", None, "altro"),
    ("Esito prova orale", None, "altro"),
    ("Esito - Prot. 14107 del 17/01/2024", None, "altro"),
    ("Errata corrige Bando deserto", None, "rettifica"),
    ("Revoca bando - Prot. n. 166639", None, "revocato"),
    ("Provvedimento di revoca - prot. AMMCEN n. 0016708/2022", None, "revocato"),
    ("Decreto revoca bando", None, "revocato"),
    ("Revoca della nomina della commissione", None, "altro"),
    ("Graduatoria - cod. 04", None, "graduatoria"),
])
def test_classifica_deserti_e_revoche(titolo, tipo, attesa):
    assert categoria(titolo, tipo) == attesa


def test_migrazione_categorie_documento(db):
    """Da schema 33: la tabella documento con il vecchio CHECK si ricrea, i dati restano, i deserti si riclassificano."""
    db.executescript("""
        DROP TABLE documento;
        CREATE TABLE documento (id INTEGER PRIMARY KEY, scheda_id INTEGER NOT NULL REFERENCES scheda (id), id_esterno TEXT NOT NULL,
            titolo TEXT, categoria TEXT NOT NULL CHECK (categoria IN ('bando', 'graduatoria', 'scorrimento', 'rettifica', 'criteri', 'tracce', 'altro')),
            sottotipo TEXT, sottotipo_ordinale INTEGER, sottotipo_origine TEXT, tipo_fonte TEXT, protocollo TEXT, protocollo_originale TEXT,
            data_protocollo TEXT, url TEXT, accessibilita TEXT, prima_rilevazione TEXT NOT NULL, ultima_rilevazione TEXT NOT NULL,
            presente INTEGER NOT NULL DEFAULT 1, UNIQUE (scheda_id, id_esterno));
        INSERT INTO scheda (id, fonte, id_esterno, sezione, prima_rilevazione, ultima_rilevazione) VALUES (1, 'sol', 's1', 'x', 'o', 'o');
    """)
    righe = [(1, "a", "BANDO DESERTO", "altro", "D:jconon_attachment:call_deserto"), (2, "b", "Revoca bando", "altro", None),
             (3, "c", "Graduatoria", "graduatoria", "D:jconon_attachment:call_classification"),
             (4, "d", "Bando N. 367.1 deserto", "bando", None)]  # documento principale URP: resta bando
    for i, e, t, c, tp in righe:
        db.execute("INSERT INTO documento (id, scheda_id, id_esterno, titolo, categoria, tipo_fonte, prima_rilevazione, ultima_rilevazione) "
                   "VALUES (?, 1, ?, ?, ?, ?, 'o', 'o')", (i, e, t, c, tp))
    dbmod.inizializza(db)
    assert {r["id"]: r["categoria"] for r in db.execute("SELECT id, categoria FROM documento")} == {
        1: "deserto", 2: "revocato", 3: "graduatoria", 4: "bando"}
    assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE tbl_name = 'documento' AND type = 'index'")} >= {
        "idx_documento_protocollo", "idx_documento_categoria"}
    dbmod.inizializza(db)  # una seconda volta non cambia niente
    assert db.execute("SELECT COUNT(*) FROM documento").fetchone()[0] == 4


# ----------------------------------------------------------------- stato complessivo

def _deserto(id_esterno, protocollo, data, titolo="Concorso deserto", tipo="D:jconon_attachment:call_deserto"):
    return {**doc(id_esterno, "deserto", protocollo, data), "titolo": titolo, "tipo_fonte": tipo}


def test_deserto_su_sol_e_urp_con_titolo_generico(db):
    salva(db, "sol", [scheda("sol", "s1", "367.372 TEC SAC", "367.372", data="2026-01-10",
                             documenti=[_deserto("x1", "14107", "2026-06-17")])])
    salva(db, "urp", [scheda("urp", "/node/1", "367.372 TEC SAC", "367.372", data="2026-01-10",
                             documenti=[{**doc("u1", "altro", "14107", "2026-06-17"), "titolo": "Esito - Prot. 14107"}])])
    collegamento.collega(db)
    righe = [r for r in atti.elenco_atti(db, "2026-01-01", "2026-12-31") if r["atto"] == "deserto"]
    assert len(righe) == 1
    r = righe[0]
    assert (r["fonti"]["sol"]["stato"], r["fonti"]["urp"]["stato"]) == ("presente", "presente")
    assert (r["fonti"]["segreteria"]["stato"], r["fonti"]["segreteria"]["testo"]) == ("non_applicabile", "non nel file")
    assert not r["difforme"]


def test_deserto_solo_su_urp_e_mancante_su_sol(db):
    salva(db, "sol", [scheda("sol", "s1", "367.455 TEC SAC", "367.455", data="2026-01-10")])
    salva(db, "urp", [scheda("urp", "/node/1", "367.455 TEC SAC", "367.455", data="2026-01-10",
                             documenti=[{**doc("u1", "deserto", "505707", "2026-03-20"), "titolo": "Decreto esito negativo bando"}])])
    collegamento.collega(db)
    r = next(r for r in atti.elenco_atti(db, "2026-01-01", "2026-12-31") if r["atto"] == "deserto")
    assert (r["fonti"]["sol"]["stato"], r["fonti"]["urp"]["stato"]) == ("mancante", "presente")
    assert r["difforme"]


def test_altro_urp_senza_deserto_sol_non_compare(db):
    salva(db, "sol", [scheda("sol", "s1", "367.1 RIC", "367.1", data="2026-01-10")])
    salva(db, "urp", [scheda("urp", "/node/1", "367.1 RIC", "367.1", data="2026-01-10",
                             documenti=[doc("u1", "altro", "999", "2026-03-20")])])
    collegamento.collega(db)
    assert {r["atto"] for r in atti.elenco_atti(db, "2026-01-01", "2026-12-31")} == {"bando"}


def _concorso(id_esterno, codice, numero, scadenza, sotto=None, documenti=(), id_padre=None):
    s = scheda("sol", id_esterno, codice, numero, sotto=sotto, data="2024-01-10", documenti=documenti)
    s["dati_extra"] = json.dumps({"data_fine_invio_domande": f"{scadenza}T00:00:00Z"})
    s["id_padre"] = id_padre
    return s


def test_senza_esito(db):
    oggi = date(2026, 11, 20)
    salva(db, "sol", [
        _concorso("a", "367.391 CTER", "367.391", "2023-01-05"),  # scaduto, nessun esito: da verificare
        _concorso("b", "367.392 CTER", "367.392", "2023-01-05", documenti=[doc("g", "graduatoria", "1", "2023-06-01")]),
        _concorso("c", "367.393 CTER", "367.393", "2023-01-05", documenti=[_deserto("d", "2", "2023-06-01")]),
        _concorso("d", "367.394 CTER", "367.394", "2026-06-01"),  # scaduto da meno di 12 mesi: in corso
        _concorso("e", "367.395 CTER", "367.395", "2023-01-05"),  # graduatoria solo su URP
    ])
    salva(db, "urp", [scheda("urp", "/node/5", "367.395 CTER", "367.395", data="2024-01-10",
                             documenti=[doc("ug", "graduatoria", "5", "2023-06-01")])])
    collegamento.collega(db)
    assert [x["scheda"]["codice_originale"] for x in atti.senza_esito(db, oggi)] == ["367.391 CTER"]


def test_senza_esito_per_sede(db):
    """Bando con più sedi: la graduatoria URP di una sede («cod. 01») non vale per le altre."""
    oggi = date(2026, 11, 20)
    salva(db, "sol", [
        _concorso("p", "367.433 FA", "367.433", "2023-01-05"),
        _concorso("f1", "367.433 FA - CODICE 01", "367.433", "2023-01-05", sotto="1", id_padre="p"),
        _concorso("f2", "367.433 FA - CODICE 02", "367.433", "2023-01-05", sotto="2", id_padre="p"),
    ])
    salva(db, "urp", [scheda("urp", "/node/9", "367.433 FA", "367.433", data="2024-01-10",
                             documenti=[{**doc("ug", "graduatoria", "5", "2023-06-01"), "titolo": "Graduatoria - cod. 01"}])])
    collegamento.collega(db)
    assert [x["scheda"]["codice_originale"] for x in atti.senza_esito(db, oggi)] == ["367.433 FA - CODICE 02"]


def test_senza_esito_nello_stato_complessivo(db):
    salva(db, "sol", [_concorso("a", "367.391 CTER", "367.391", "2023-01-05")])
    collegamento.collega(db)
    assert not [r for r in atti.elenco_atti(db, "2026-01-01", "2026-12-31") if r["atto"] == "senza_esito"]
    r = next(r for r in atti.elenco_atti(db, "2026-01-01", "2026-12-31", con_senza_esito=True) if r["atto"] == "senza_esito")
    assert r["data"] == "2023-01-05" and not r["difforme"] and "nessuna graduatoria" in r["avviso"]
    assert r["fonti"]["sol"]["testo"] == "nessun esito"


# ----------------------------------------------------------------- esportazione

def test_xlsx_colonne_righe_e_niente_formule():
    contenuto = esporta.xlsx(["Codice", "Protocollo", "Note"], [["367.391", 196365, "=HYPERLINK(\"x\")"], ["367.455", None, True]])
    ws = openpyxl.load_workbook(io.BytesIO(contenuto)).active
    assert [c.value for c in ws[1]] == ["Codice", "Protocollo", "Note"]
    assert ws["B2"].value == 196365
    assert ws["C2"].value == "=HYPERLINK(\"x\")" and ws["C2"].data_type == "s"
    assert (ws["B3"].value, ws["C3"].value) == (None, "sì")


@pytest.mark.parametrize("colonne, righe", [([], []), (["A"], [["x", "y"]]), (["A"], [[{"x": 1}]]), (["A"], "testo")])
def test_xlsx_dati_non_validi(colonne, righe):
    with pytest.raises(esporta.DatiNonValidi):
        esporta.xlsx(colonne, righe)


def test_api_esporta_excel(db):
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint(lambda f: f))
    client = app.test_client()
    r = client.post("/api/esporta-excel", json={"nome": "deserti 2026", "colonne": ["Codice"], "righe": [["367.391"]]})
    assert r.status_code == 200
    assert "deserti 2026" in r.headers["Content-Disposition"]
    assert openpyxl.load_workbook(io.BytesIO(r.data)).active["A2"].value == "367.391"
    assert client.post("/api/esporta-excel", json={"colonne": [], "righe": []}).status_code == 400


# ----------------------------------------------------------------- controllo su SOL dei concorsi senza esito

def _v(**k):
    return {"esito": "completi", "domande": 3, "con_punteggi": 3, "vincitori": 0, "idonei": 0, "scorrimento": 0, "non_ammessi": 0, **k}


@pytest.mark.parametrize("verifica, attesa", [
    (None, "da_controllare"),
    (_v(esito="errore", domande=None, con_punteggi=None), "da_controllare"),
    (_v(esito="nessuna_domanda", domande=0, con_punteggi=0), "deserto"),
    (_v(non_ammessi=3), "deserto"),                         # tutti con punteggi, tutti non ammessi
    (_v(con_punteggi=0, esito="mancanti"), "non_determinabile"),  # punteggi non inseriti: non basta
    (_v(con_punteggi=2, non_ammessi=2, esito="parziali"), "non_determinabile"),
    (_v(non_ammessi=1), "non_determinabile"),               # completi ma qualcuno ammesso: graduatoria forse da inserire
    (_v(non_ammessi=None), "non_determinabile"),            # verifica precedente senza il conteggio
    (_v(idonei=1, non_ammessi=2), "graduatoria_mancante"),
])
def test_giudizio(verifica, attesa):
    assert atti.giudizio(verifica, "2022-01-01", "2023-01-05")["codice"] == attesa


def test_giudizio_copertura_segreteria():
    assert atti.giudizio(None, None, "2023-01-05")["segreteria"] == "file della segreteria non caricato"
    assert atti.giudizio(None, "2022-01-01", "2023-01-05")["segreteria"].startswith("nessuna graduatoria")
    assert "non copre" in atti.giudizio(None, "2026-01-01", "2023-01-05")["segreteria"]


def test_non_ammessi_contati():
    from monitoraggio import punteggi
    cand = [{"esito": None, "prove": {"1": {"punteggio": 10, "non_ammesso": True}, "2": {"punteggio": None, "non_ammesso": False}}},
            {"esito": None, "prove": {"1": {"punteggio": 25, "non_ammesso": False}}}]
    assert punteggi.conteggi_candidati(cand)["non_ammessi"] == 1


def test_senza_esito_escluso_se_graduatoria_nel_file_segreteria(db):
    from datetime import datetime
    from tests.test_atti import _carica_segreteria, _riga_bando, _riga_grad
    salva(db, "sol", [_concorso("a", "367.391 CTER", "367.391", "2023-01-05"),
                      _concorso("b", "367.392 CTER", "367.392", "2023-01-05")])
    collegamento.collega(db)
    _carica_segreteria(db, [_riga_bando("367.392", "1", "05/01/2022")], [_riga_grad("367.392 CTER", "0270086", datetime(2023, 6, 12))], [])
    righe = atti.senza_esito(db, date(2026, 11, 20))
    assert [x["scheda"]["codice_originale"] for x in righe] == ["367.391 CTER"]
    assert righe[0]["copertura_segreteria"] == "2023-06-12"


def test_probabile_deserto_nello_stato_complessivo(db):
    salva(db, "sol", [_concorso("a", "367.391 CTER", "367.391", "2023-01-05")])
    collegamento.collega(db)
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = 'a'").fetchone()[0]
    db.execute("INSERT INTO punteggi_verifica (scheda_id, verificato_il, domande, con_punteggi, vincitori, idonei, scorrimento, "
               "non_ammessi, esito) VALUES (?, '2026-11-20', 0, 0, 0, 0, 0, 0, 'nessuna_domanda')", (sid,))
    r = next(r for r in atti.elenco_atti(db, "2026-01-01", "2026-12-31", con_senza_esito=True) if r["atto"] == "senza_esito")
    assert r["probabile_deserto"] and r["esito_verifica"]["testo"] == "nessuna domanda valida su Selezioni Online"


def test_api_verifica_senza_esito_serve_sol(db):
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint(lambda f: f))
    r = app.test_client().post("/api/punteggi/verifica-senza-esito")
    assert r.status_code == 401
    assert app.test_client().get("/api/punteggi/avanzamento").get_json()["in_corso"] is False


# ----------------------------------------------------------------- scheda «Concorsi deserti» e richiesta ai referenti

def test_in_corso_con_documento_recente():
    oggi = date(2026, 11, 20)
    ultimo = {"data": "2026-09-01", "titolo": "Avviso di convocazione prova orale"}
    g = atti.giudizio(None, None, "2025-06-01", ultimo, oggi)
    assert g["codice"] == "in_corso" and "01/09/2026" in g["testo"] and g["dettaglio_sol"]
    assert atti.giudizio(None, None, "2025-06-01", {"data": "2025-12-01", "titolo": "x"}, oggi)["codice"] == "da_controllare"
    # SOL dimostra il deserto: un documento recente non lo cambia
    assert atti.giudizio(_v(domande=0, con_punteggi=0), None, "2025-06-01", ultimo, oggi)["codice"] == "deserto"


def test_senza_esito_ricorda_ultimo_documento(db):
    salva(db, "sol", [_concorso("a", "367.557 RIC ICB", "367.557", "2023-01-05",
                                documenti=[{**doc("c", "altro", "9", "2026-07-20"), "titolo": "Avviso convocazione prova orale"}])])
    collegamento.collega(db)
    x = atti.senza_esito(db, date(2026, 11, 20))[0]
    assert x["ultimo"]["data"] == "2026-07-20"


def test_stato_deserto_nelle_righe(db):
    salva(db, "sol", [_concorso("a", "367.391 CTER", "367.391", "2023-01-05"),
                      scheda("sol", "b", "367.449 CTER", "367.449", data="2026-01-10", documenti=[_deserto("d", "402409", "2026-03-25")])])
    collegamento.collega(db)
    righe = [r for r in atti.elenco_atti(db, "2000-01-01", None, con_senza_esito=True) if r.get("stato_deserto")]
    assert {(r["atto"], r["stato_deserto"]) for r in righe} == {("deserto", "certo"), ("senza_esito", "da_verificare")}


def _con_rdp(db, id_esterno, email):
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = ?", (id_esterno,)).fetchone()[0]
    db.execute("INSERT INTO referente (scheda_id, chiave, nome, cognome, email, attivo, prima_rilevazione, ultima_rilevazione) "
               "VALUES (?, 'k', 'Nome', 'Rdp', ?, 1, 'x', 'x')", (sid, email))
    return sid


def test_richiesta_ai_referenti(db, monkeypatch):
    from monitoraggio import deserti, posta
    salva(db, "sol", [_concorso("a", "367.391 CTER", "367.391", "2023-01-05")])
    collegamento.collega(db)
    sid = _con_rdp(db, "a", "rdp@cnr.it")
    a = deserti.anteprima(db, sid)
    assert a["destinatari"] == ["rdp@cnr.it"] and "367.391 CTER" in a["oggetto"] and "05/01/2023" in a["corpo"]
    inviate = []
    monkeypatch.setattr(posta, "invia", lambda d, o, c, modo=None, cc=None: inviate.append((d, o, modo, cc)) or modo == "prova")
    assert deserti.invia(db, sid, a["oggetto"], a["corpo"], "admin", "prova") == {"ok": True, "prova": True}
    assert inviate[0][0] == ["rdp@cnr.it"] and inviate[0][2] == "prova"
    assert deserti.ultime(db)[sid]["esito"] == "prova"
    with pytest.raises(ValueError):
        deserti.invia(db, sid, a["oggetto"], a["corpo"] + " RSSMRA80A01H501U", "admin", "prova")  # codice fiscale: bloccato
    with pytest.raises(ValueError):
        deserti.invia(db, sid, a["oggetto"], a["corpo"], "admin", "altro")


def test_richiesta_senza_rdp_o_concorso_con_esito(db):
    from monitoraggio import deserti
    salva(db, "sol", [_concorso("a", "367.391 CTER", "367.391", "2023-01-05"),
                      _concorso("b", "367.392 CTER", "367.392", "2023-01-05", documenti=[doc("g", "graduatoria", "1", "2023-06-01")])])
    collegamento.collega(db)
    ids = {r["id_esterno"]: r["id"] for r in db.execute("SELECT id, id_esterno FROM scheda")}
    with pytest.raises(ValueError, match="Nessuna email RdP"):
        deserti.invia(db, ids["a"], "o", "c", "admin", "prova")
    assert deserti.anteprima(db, ids["b"]) is None


def test_api_richiesta_deserto(db, monkeypatch):
    from monitoraggio import posta
    salva(db, "sol", [_concorso("a", "367.391 CTER", "367.391", "2023-01-05")])
    collegamento.collega(db)
    sid = _con_rdp(db, "a", "rdp@cnr.it")
    monkeypatch.setattr(posta, "invia", lambda d, o, c, modo=None, cc=None: True)
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint(lambda f: f))
    client = app.test_client()
    a = client.get(f"/api/deserti/richiesta/{sid}").get_json()
    assert a["destinatari"] == ["rdp@cnr.it"]
    r = client.post(f"/api/deserti/richiesta/{sid}", json={"oggetto": a["oggetto"], "corpo": a["corpo"], "modo": "prova"})
    assert r.status_code == 200 and r.get_json()["prova"] is True
    riga = next(x for x in client.get("/api/atti?dal=2000-01-01").get_json()["atti"] if x["atto"] == "senza_esito")
    assert riga["richiesta_deserto"]["esito"] == "prova" and riga["stato_deserto"] == "da_verificare"
    assert client.get("/api/deserti/richiesta/999999").status_code == 404


def test_richiesta_provvedimento_su_urp_ma_non_su_sol(db):
    """367.455: deserto su URP, su SOL manca: l'email chiede di caricarlo su Selezioni Online."""
    from monitoraggio import deserti
    salva(db, "sol", [scheda("sol", "s1", "367.455 TEC SAC", "367.455", data="2024-01-10")])
    salva(db, "urp", [scheda("urp", "/node/1", "367.455 TEC SAC", "367.455", data="2024-01-10",
                             documenti=[{**doc("u1", "deserto", "505707", "2024-12-20"), "titolo": "Decreto esito negativo bando"}])])
    collegamento.collega(db)
    sid = _con_rdp(db, "s1", "rdp@cnr.it")
    r = next(x for x in atti.elenco_atti(db, "2000-01-01", None, con_senza_esito=True) if x["atto"] == "deserto")
    assert r["stato_deserto"] == "certo" and r["scheda_sol_id"] == sid and r["difforme"]
    a = deserti.anteprima(db, sid)
    assert a["oggetto"] == "Concorso 367.455 TEC SAC: provvedimento di conclusione da caricare su Selezioni Online"
    assert "505707" in a["corpo"] and "allegato di tipo «deserto»" in a["corpo"] and a["stato"] == "certo"


def test_niente_da_chiedere_se_provvedimento_su_entrambe(db):
    from monitoraggio import deserti
    salva(db, "sol", [scheda("sol", "s1", "367.449 CTER", "367.449", data="2024-01-10", documenti=[_deserto("d", "402409", "2024-10-25")])])
    salva(db, "urp", [scheda("urp", "/node/1", "367.449 CTER", "367.449", data="2024-01-10",
                             documenti=[{**doc("u1", "deserto", "402409", "2024-10-25"), "titolo": "Conclusione con esito negativo"}])])
    collegamento.collega(db)
    sid = db.execute("SELECT id FROM scheda WHERE id_esterno = 's1'").fetchone()[0]
    assert deserti.anteprima(db, sid) is None


def test_richiesta_graduatoria_mancante(db):
    from monitoraggio import deserti
    salva(db, "sol", [_concorso("a", "367.391 CTER", "367.391", "2023-01-05")])
    collegamento.collega(db)
    sid = _con_rdp(db, "a", "rdp@cnr.it")
    db.execute("INSERT INTO punteggi_verifica (scheda_id, verificato_il, domande, con_punteggi, vincitori, idonei, scorrimento, "
               "non_ammessi, esito) VALUES (?, '2026-11-20', 3, 3, 1, 1, 0, 1, 'completi')", (sid,))
    assert deserti.anteprima(db, sid)["oggetto"] == "Concorso 367.391 CTER: graduatoria da pubblicare"
