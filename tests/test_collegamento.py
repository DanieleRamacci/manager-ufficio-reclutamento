import pytest

from monitoraggio import collegamento, raccolta

ORA = "2026-10-29T10:00:00.000000Z"


def scheda(fonte, id_esterno, codice, numero, sotto=None, data="2026-03-01", tipologia="tempo_indeterminato",
           protocollo=None, sezione=None, documenti=()):
    return {"id_esterno": id_esterno, "sezione": sezione or ("tempo-indeterminato" if fonte == "urp" else "F:tind"),
            "tipologia": tipologia, "codice_originale": codice, "codice_norm": codice.replace(" ", "").upper() if codice else None,
            "numero_bando": numero, "codice_sotto": sotto, "titolo": f"Bando {codice}", "protocollo": protocollo,
            "protocollo_originale": protocollo, "data_pubblicazione": data, "data_pubbl_graduatoria": None,
            "url": f"http://{fonte}/{id_esterno}", "dati_extra": None, "modificata_fonte_il": None,
            "documenti": list(documenti)}


def doc(id_esterno, categoria, protocollo, data="2026-05-01", sottotipo=None):
    return {"id_esterno": id_esterno, "titolo": categoria, "categoria": categoria, "sottotipo": sottotipo,
            "sottotipo_ordinale": None, "sottotipo_origine": None, "tipo_fonte": None, "protocollo": protocollo,
            "protocollo_originale": protocollo, "data_protocollo": data, "url": None}


def salva(db, fonte, schede):
    raccolta.scrivi(db, fonte, schede, [s["id_esterno"] for s in schede], ORA)


def stato(db, codice_originale):
    return db.execute(
        "SELECT b.stato_collegamento FROM bando b JOIN scheda s ON s.bando_id = b.id WHERE s.codice_originale = ?",
        (codice_originale,)).fetchone()[0]


def bando_di(db, fonte, id_esterno):
    return db.execute("SELECT bando_id FROM scheda WHERE fonte = ? AND id_esterno = ?", (fonte, id_esterno)).fetchone()[0]


def test_collega_per_numero_bando(db):
    salva(db, "sol", [scheda("sol", "s1", "367.479 CTER IOM GE", "367.479")])
    salva(db, "urp", [scheda("urp", "/node/1", "367.479 CTER IOMGE", "367.479")])
    collegamento.collega(db)
    assert bando_di(db, "urp", "/node/1") == bando_di(db, "sol", "s1")
    assert stato(db, "367.479 CTER IOMGE") == "entrambi"


def test_collega_per_codice_se_manca_il_numero(db):
    salva(db, "sol", [scheda("sol", "s1", "02-COMANDO-2024 DCGR", None, tipologia="comando")])
    salva(db, "urp", [scheda("urp", "/node/2", "02-COMANDO-2024 DCGR", None, tipologia="comando",
                             sezione="bandi-pubblici-mobilita")])
    collegamento.collega(db)
    assert bando_di(db, "urp", "/node/2") == bando_di(db, "sol", "s1")


def test_collega_per_protocollo(db):
    salva(db, "sol", [scheda("sol", "s1", "XYZ", None, protocollo="123")])
    salva(db, "urp", [scheda("urp", "/node/3", None, None, protocollo="123")])
    collegamento.collega(db)
    assert bando_di(db, "urp", "/node/3") == bando_di(db, "sol", "s1")


def test_sotto_bandi_sono_lo_stesso_bando(db):
    # SOL ha un bando per codice (365.199 FA - CODICE 01 ...), URP una pagina unica
    salva(db, "sol", [scheda("sol", "p", "365.199 FA", "365.199", tipologia="mobilita"),
                      scheda("sol", "c1", "365.199 FA - CODICE 01 VE", "365.199", sotto="1", tipologia="mobilita"),
                      scheda("sol", "c2", "365.199 FA - CODICE 02 BO", "365.199", sotto="2", tipologia="mobilita")])
    salva(db, "urp", [scheda("urp", "/node/4", "365.199 FA", "365.199", tipologia="mobilita",
                             sezione="bandi-pubblici-mobilita")])
    collegamento.collega(db)
    bandi = {bando_di(db, "sol", "p"), bando_di(db, "sol", "c1"), bando_di(db, "sol", "c2"), bando_di(db, "urp", "/node/4")}
    assert len(bandi) == 1
    b = db.execute("SELECT codice, stato_collegamento FROM bando WHERE id = ?", (bandi.pop(),)).fetchone()
    assert (b["codice"], b["stato_collegamento"]) == ("365.199 FA", "entrambi")


def test_documenti_dei_sotto_bandi_confrontati_insieme(db, monkeypatch):
    monkeypatch.setenv("MONITORAGGIO_DAL", "2026-01-01")
    salva(db, "sol", [scheda("sol", "c1", "367.434 CA COD 1", "367.434", sotto="1",
                             documenti=[doc("g1", "graduatoria", "500")]),
                      scheda("sol", "c2", "367.434 CA COD 2", "367.434", sotto="2",
                             documenti=[doc("g2", "graduatoria", "501")])])
    salva(db, "urp", [scheda("urp", "/node/8", "367.434 CA", "367.434",
                             documenti=[doc("u1", "graduatoria", "500"), doc("u2", "graduatoria", "501")])])
    collegamento.collega(db)
    assert collegamento.segnalazioni(db, bando_di(db, "urp", "/node/8")) == []


def test_stati_solo_e_fuori_periodo(db):
    salva(db, "urp", [scheda("urp", "/node/6", "367.600 RIC", "367.600", data="2024-01-10")])
    salva(db, "sol", [scheda("sol", "s7", "367.700 RIC", "367.700", data="2025-02-01"),
                      scheda("sol", "s8", "367.10 RIC", "367.10", data="2016-02-18")])
    collegamento.collega(db)
    assert stato(db, "367.600 RIC") == "solo_urp"
    assert stato(db, "367.700 RIC") == "solo_sol"
    assert stato(db, "367.10 RIC") == "fuori_periodo_urp"


def test_segnalazioni_documenti(db, monkeypatch):
    monkeypatch.setenv("MONITORAGGIO_DAL", "2026-01-01")
    salva(db, "urp", [scheda("urp", "/node/9", "367.900 RIC", "367.900", documenti=[
        doc("u1", "graduatoria", "3763", "2026-01-08"),
        doc("u2", "scorrimento", "175370", "2026-04-15", "utilizzo"),
        doc("u3", "graduatoria", "1111", "2025-06-01"),   # prima del monitoraggio: ignorata
    ])])
    salva(db, "sol", [scheda("sol", "s9", "367.900 RIC", "367.900", documenti=[
        doc("x1", "graduatoria", "3763", "2026-01-08"),
        doc("x2", "scorrimento", "999999", "2026-05-02"),
    ])])
    collegamento.collega(db)
    bando_id = bando_di(db, "urp", "/node/9")
    segn = {(s["tipo"], s["protocollo"]) for s in collegamento.segnalazioni(db, bando_id)}
    assert segn == {("scorrimento_mancante_sol", "175370"), ("scorrimento_mancante_urp", "999999")}


def test_rumore_escluso_e_protocollo_diverso(db, monkeypatch):
    monkeypatch.setenv("MONITORAGGIO_DAL", "2026-01-01")
    annullata = doc("u4", "graduatoria", "391189", "2026-09-15")
    annullata["titolo"] = "Graduatoria [ANNULLATO]"
    rett_commissione = doc("u5", "rettifica", "342575", "2026-07-28")
    rett_commissione["titolo"] = "Rettifica commissione"
    rett_graduatoria = doc("u6", "rettifica", "168736", "2026-04-13")
    rett_graduatoria["titolo"] = "Errata corrige graduatoria"
    salva(db, "urp", [scheda("urp", "/node/11", "367.601 FA ISTC", "367.601", documenti=[
        doc("u1", "graduatoria", "270086", "2026-06-12"), annullata, rett_commissione, rett_graduatoria])])
    salva(db, "sol", [scheda("sol", "s11", "367.601 FA ISTC", "367.601", documenti=[
        doc("x1", "graduatoria", "270066", "2026-06-12")])])
    collegamento.collega(db)
    segn = collegamento.segnalazioni(db, bando_di(db, "urp", "/node/11"))
    assert [(s["tipo"], s["protocollo"], s.get("protocollo_sol")) for s in segn] == [
        ("graduatoria_protocollo_diverso", "270086", "270066"),
        ("rettifica_mancante_sol", "168736", None),
    ]


def test_campi_bando_presi_da_sol(db):
    sol = scheda("sol", "s10", "367.910 RIC IASI", "367.910", data="2026-02-01")
    sol["dati_extra"] = '{"profilo": "Ricercatore", "sede": "Roma", "numero_posti": 2, "gruppo_rdp": "RDP_x"}'
    salva(db, "sol", [sol])
    salva(db, "urp", [scheda("urp", "/node/10", "367.910 RIC", "367.910", data="2026-01-30")])
    collegamento.collega(db)
    b = db.execute("SELECT * FROM bando WHERE id = ?", (bando_di(db, "sol", "s10"),)).fetchone()
    assert (b["codice"], b["profilo"], b["sede"], b["numero_posti"], b["gruppo_rdp"]) == (
        "367.910 RIC IASI", "Ricercatore", "Roma", 2, "RDP_x")
    assert b["data_pubblicazione"] == "2026-01-30"


def test_sezioni_urp_fuori_ambito_restano_fuori_dal_monitoraggio(db):
    salva(db, "urp", [scheda("urp", "/node/9", "BORSA 1", "367.900", tipologia=None, sezione="borse-ricerca",
                             documenti=[doc("g1", "graduatoria", "111")]),
                      scheda("urp", "/node/1", "367.479 CTER", "367.479", documenti=[doc("g2", "graduatoria", "222")])])
    collegamento.collega(db)
    assert bando_di(db, "urp", "/node/9") is None
    assert bando_di(db, "urp", "/node/1") is not None
    assert db.execute("SELECT COUNT(*) FROM bando").fetchone()[0] == 1


def test_archivio_si_collega_ai_bandi_esistenti_senza_crearne(db):
    salva(db, "sol", [scheda("sol", "s1", "367.434 CA", "367.434")])
    collegamento.collega(db)
    salva(db, "urp", [scheda("urp", "/vecchio/367_434.pdf", "367.434 CA", "367.434", tipologia=None, sezione="archivio-vecchio",
                             documenti=[doc("g1", "graduatoria", "509207", "2026-05-01")]),
                      scheda("urp", "/vecchio/100.pdf", "100.1 CTER", "100.1", tipologia=None, sezione="archivio-vecchio")])
    collegamento.collega(db)
    assert bando_di(db, "urp", "/vecchio/367_434.pdf") == bando_di(db, "sol", "s1")
    assert stato(db, "367.434 CA") == "entrambi"
    assert bando_di(db, "urp", "/vecchio/100.pdf") is None
    assert db.execute("SELECT COUNT(*) FROM bando").fetchone()[0] == 1


def test_archivio_letto_prima_di_sol_si_collega_dopo(db):
    salva(db, "urp", [scheda("urp", "/vecchio/367_434.pdf", "367.434 CA", "367.434", tipologia=None, sezione="archivio-vecchio")])
    collegamento.collega(db)
    assert bando_di(db, "urp", "/vecchio/367_434.pdf") is None
    salva(db, "sol", [scheda("sol", "s1", "367.434 CA", "367.434")])
    collegamento.collega(db)
    assert bando_di(db, "urp", "/vecchio/367_434.pdf") == bando_di(db, "sol", "s1")
