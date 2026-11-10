import json
from datetime import datetime

from monitoraggio import atti, collegamento, config, difformita, normalizza, segreteria, sedi
from tests.test_collegamento import doc, salva, scheda
from tests.test_segreteria import crea_excel


def _atti(db):
    return atti.elenco_atti(db, "2026-01-01", "2026-12-31")


def test_atto_presente_su_entrambe_compare_una_volta(db):
    salva(db, "sol", [scheda("sol", "s1", "367.601 FA ISTC", "367.601", data="2026-02-01",
                             documenti=[doc("x1", "graduatoria", "500", "2026-06-12")])])
    salva(db, "urp", [scheda("urp", "/node/1", "367.601 FA ISTC", "367.601", data="2026-02-01", protocollo="77",
                             documenti=[doc("u1", "graduatoria", "500", "2026-06-12"),
                                        doc("u2", "scorrimento", "600", "2026-07-01", "subentro")])])
    collegamento.collega(db)
    righe = {(r["atto"], r["protocollo"]): r for r in _atti(db)}
    assert set(righe) == {("bando", "77"), ("graduatoria", "500"), ("scorrimento", "600")}
    grad = righe[("graduatoria", "500")]
    assert (grad["fonti"]["sol"]["stato"], grad["fonti"]["urp"]["stato"]) == ("presente", "presente")
    assert grad["fonti"]["segreteria"]["stato"] == "non_caricato"
    assert not grad["incompleto"]
    scorr = righe[("scorrimento", "600")]
    assert (scorr["fonti"]["sol"]["stato"], scorr["fonti"]["urp"]["stato"], scorr["sottotipo"]) == (
        "mancante", "presente", "subentro")
    assert scorr["incompleto"]


def test_protocollo_diverso_una_riga(db):
    salva(db, "sol", [scheda("sol", "s1", "367.552 CTER", "367.552", documenti=[doc("x1", "graduatoria", "3084", "2026-07-07")])])
    salva(db, "urp", [scheda("urp", "/node/2", "367.552 CTER", "367.552", documenti=[doc("u1", "graduatoria", "308437", "2026-07-07")])])
    collegamento.collega(db)
    grad = [r for r in _atti(db) if r["atto"] == "graduatoria"]
    assert len(grad) == 1
    assert grad[0]["protocollo_diverso"] and "SOL 3084, URP 308437" in grad[0]["note"][0]


def test_bando_solo_sol_e_fuori_periodo(db):
    salva(db, "urp", [scheda("urp", "/node/3", "367.600 RIC", "367.600", data="2026-01-10")])
    salva(db, "sol", [scheda("sol", "s4", "367.700 RIC", "367.700", data="2026-02-01")])
    collegamento.collega(db)
    bandi = {r["codice"]: r for r in _atti(db) if r["atto"] == "bando"}
    assert bandi["367.700 RIC"]["fonti"]["urp"]["stato"] == "mancante"
    assert bandi["367.600 RIC"]["fonti"]["sol"]["stato"] == "mancante"


# ----------------------------------------------------------------- tre fonti (spec 002)

def _carica_segreteria(db, bandi, graduatorie, scorrimenti):
    segreteria.importa(db, crea_excel({"Bandi": bandi, "Graduatorie": graduatorie, "Scorrimento": scorrimenti}),
                       "f.xlsx", "test")


def _riga_bando(numero, prot, data, tipo="Concorso pubblico per titoli ed esami"):
    return ["f.pdf", numero, tipo, "Istituto", "Roma", "DSU", "Oggetto", "1 posto", "30 giorni", prot, data]


def _riga_grad(numero, prot, data):
    return [1, "g.pdf", numero, None, 1, "Nome Inventato", "80/90", None, None, "1", data, prot, data, None, None, 0]


def _riga_scorr(numero, prot, data, tipologia):
    return ["s.pdf", numero, None, 10, "Nome Inventato", None, prot, data, tipologia, None, None, None]


def _per_chiave(db):
    return {(r["atto"], r["protocollo"]): r for r in _atti(db)}


def test_tre_fonti_una_riga(db):
    salva(db, "sol", [scheda("sol", "s1", "367.601 FA ISTC", "367.601", data="2026-05-20",
                             documenti=[doc("x1", "graduatoria", "270086", "2026-06-12")])])
    salva(db, "urp", [scheda("urp", "/node/1", "367.601 FA ISTC", "367.601", data="2026-05-20", protocollo="201000",
                             documenti=[doc("u1", "graduatoria", "270086", "2026-06-12")])])
    collegamento.collega(db)
    _carica_segreteria(db, [_riga_bando("367.601", "0201000", "20/05/2026")],
                       [_riga_grad("367.601 FA ISTC", "0270086", datetime(2026, 6, 12))],
                       [_riga_scorr("367.601 FA ISTC", 297136, datetime(2026, 6, 30), "Subentro")])
    righe = _per_chiave(db)
    grad = righe[("graduatoria", "270086")]
    assert {f: c["stato"] for f, c in grad["fonti"].items()} == {"sol": "presente", "urp": "presente", "segreteria": "presente"}
    bando = righe[("bando", "201000")]
    assert bando["fonti"]["segreteria"]["stato"] == "presente"
    scorr = righe[("scorrimento", "297136")]
    assert {f: c["stato"] for f, c in scorr["fonti"].items()} == {"sol": "mancante", "urp": "mancante", "segreteria": "presente"}
    assert (scorr["sottotipo"], scorr["sottotipo_origine"]) == ("subentro", "segreteria")


def test_atto_urp_non_nel_file_e_periodo(db):
    salva(db, "urp", [scheda("urp", "/node/2", "367.700 RIC", "367.700", data="2026-01-10", documenti=[
        doc("u1", "graduatoria", "100", "2026-03-01"),     # prima del periodo del foglio Graduatorie
        doc("u2", "graduatoria", "200", "2026-07-01")])])  # dentro il periodo
    salva(db, "sol", [scheda("sol", "s2", "367.700 RIC", "367.700", data="2026-01-10")])
    collegamento.collega(db)
    _carica_segreteria(db, [_riga_bando("390.001", "1", "01/06/2026")],
                       [_riga_grad("367.999 X", "9", datetime(2026, 6, 1))], [])
    righe = _per_chiave(db)
    assert righe[("graduatoria", "100")]["fonti"]["segreteria"]["stato"] == "non_applicabile"
    assert righe[("graduatoria", "200")]["fonti"]["segreteria"]["stato"] == "mancante"
    # atto presente solo nel file, su un bando che non esiste su URP né SOL
    solo = righe[("graduatoria", "9")]
    assert solo["numero_bando"] == "367.999" and solo["fonti"]["sol"]["stato"] == "mancante"


def test_protocollo_diverso_tra_file_e_sol(db):
    salva(db, "sol", [scheda("sol", "s3", "367.552 CTER", "367.552", documenti=[doc("x1", "graduatoria", "3084", "2026-07-07")])])
    salva(db, "urp", [scheda("urp", "/node/3", "367.552 CTER", "367.552", documenti=[doc("u1", "graduatoria", "308437", "2026-07-07")])])
    collegamento.collega(db)
    _carica_segreteria(db, [], [_riga_grad("367.552 CTER", "0308437", datetime(2026, 7, 7))], [])
    grad = [r for r in _atti(db) if r["atto"] == "graduatoria"]
    assert len(grad) == 1
    assert {f: c["stato"] for f, c in grad[0]["fonti"].items()} == {"sol": "presente", "urp": "presente", "segreteria": "presente"}
    assert grad[0]["protocollo_diverso"]


def test_fuori_ambito_escluso_e_tipologia_da_completare(db):
    salva(db, "sol", [])
    _carica_segreteria(db, [_riga_bando("390.475", "308883", "07/07/2026", tipo="Selezione Direttore d'Istituto")],
                       [], [_riga_scorr("367.601 FA ISTC", 300000, datetime(2026, 7, 2), None)])
    righe = _per_chiave(db)
    assert ("bando", "308883") not in righe
    assert "tipologia da completare nel file" in righe[("scorrimento", "300000")]["note"]


def test_codice_sotto_e_graduatoria_senza_documento(db):
    roma = scheda("sol", "roma", "367.434 CA - ROMA Codice 13", "367.434", sotto="13")
    roma["data_pubbl_graduatoria"] = "2026-03-10"            # data impostata, nessun allegato di graduatoria
    napoli = scheda("sol", "napoli", "367.434 CA - NAPOLI Codice 14", "367.434", sotto="14",
                    documenti=[doc("g14", "graduatoria", "540538", "2026-02-01")])
    napoli["data_pubbl_graduatoria"] = "2026-02-01"
    salva(db, "sol", [roma, napoli])
    salva(db, "urp", [scheda("urp", "/node/1", "367.434 CA", "367.434", documenti=[
        {**doc("u1", "scorrimento", "79619", "2026-02-20", "utilizzo"), "titolo": "Utilizzo graduatoria Cod 14 Napoli"}])])
    collegamento.collega(db)
    righe = _atti(db)
    utilizzo = next(r for r in righe if r["protocollo"] == "79619")
    assert utilizzo["codice_sotto"] == "14"                  # ricavato dal titolo del documento URP
    grad = next(r for r in righe if r["protocollo"] == "540538")
    assert grad["codice_sotto"] == "14"
    senza = [r for r in righe if "data della graduatoria pubblica (oscurata) su SOL senza documento pubblico" in r["note"]]
    assert len(senza) == 1 and senza[0]["codice_sotto"] == "13" and senza[0]["fonti"]["sol"]["stato"] == "mancante"


def test_rdp_e_link_del_codice_specifico(db):
    madre = scheda("sol", "madre", "367.434 CA", "367.434")
    c13 = scheda("sol", "c13", "367.434 CA - ROMA Codice 13", "367.434", sotto="13",
                 documenti=[doc("g13", "graduatoria", "500", "2026-02-01")])
    c14 = scheda("sol", "c14", "367.434 CA - NAPOLI Codice 14", "367.434", sotto="14",
                 documenti=[doc("g14", "graduatoria", "501", "2026-02-02")])
    salva(db, "sol", [madre, c13, c14])
    collegamento.collega(db)
    ids = {r["id_esterno"]: r["id"] for r in db.execute("SELECT id, id_esterno FROM scheda")}
    for scheda_id, nome in ((ids["madre"], "Madre"), (ids["c13"], "Roma"), (ids["c14"], "Napoli")):
        db.execute("INSERT INTO referente (scheda_id, chiave, nome, cognome, email, attivo, prima_rilevazione, "
                   "ultima_rilevazione) VALUES (?, ?, ?, 'Rdp', ?, 1, 'x', 'x')", (scheda_id, nome, nome, f"{nome}@cnr.it"))
    righe = {r["protocollo"]: r for r in _atti(db)}
    assert [p["nome"] for p in righe["500"]["rdp"]] == ["Roma"] and righe["500"]["rdp_origine"] == "codice"
    assert [p["nome"] for p in righe["501"]["rdp"]] == ["Napoli"]
    assert righe["500"]["link_codice"] == "http://sol/c13"  # pagina SOL del codice 13


def test_conteggio_utilizzi_per_codice_nel_rilievo(db):
    from monitoraggio import difformita
    # due utilizzi per lo stesso bando: uno su SOL+URP (prot 100), uno solo su URP (prot 200)
    salva(db, "sol", [scheda("sol", "s1", "367.524 CTER", "367.524",
                             documenti=[doc("u1", "scorrimento", "100", "2026-07-31")])])
    salva(db, "urp", [scheda("urp", "/n/1", "367.524 CTER", "367.524",
                             documenti=[doc("u1u", "scorrimento", "100", "2026-07-31"), doc("u2", "scorrimento", "200", "2026-10-19")])])
    collegamento.collega(db)
    righe = {(r["atto"], r["protocollo"]): r for r in atti.elenco_atti(db, "2026-07-01", "2026-10-31")}
    mancante = righe[("scorrimento", "200")]
    assert mancante["utilizzi_sol_codice"] == 1  # su SOL c'è già l'utilizzo prot. 100 per questo codice
    testi = difformita.rilievi(mancante)
    assert any("(prot. 200) non risulta tra i dati attualmente disponibili da Selezioni Online "
               "(per questo codice su Selezioni Online risulta già 1 utilizzo)" in t for t in testi), testi
    # quello presente su SOL non porta il conteggio
    assert all("risulta già" not in t for t in difformita.rilievi(righe[("scorrimento", "100")]))



def test_nota_sottotipo_dice_cosa_fare():
    from monitoraggio.normalizza import nota_sottotipo
    assert "va indicata la tipologia «subentro»" in nota_sottotipo("ordinario", "subentro")
    assert "«scorrimento e subentro insieme»" in nota_sottotipo("misto", "subentro")
    assert "va indicata la tipologia «subentro»" in nota_sottotipo("subentro", "utilizzo") and "non compare" in nota_sottotipo("subentro", "utilizzo")


def _figlio(cod):
    s = scheda("sol", cod, f"367.535 CTER - {cod}", "367.535", sotto=str(int(cod[:2])) if cod[:2].isdigit() else None)
    s["id_padre"] = "madre"
    return s


def _sedi(db, conteggi, nel_file=None, doc_padre=False):
    """Una graduatoria unica per più sedi, come il 367.535: nel file una riga per sede con lo stesso protocollo."""
    grad = doc("g-sol", "graduatoria", "444208")
    salva(db, "sol", [scheda("sol", "madre", "367.535 CTER - Supporto", "367.535", documenti=[grad] if doc_padre else []), *[_figlio(c) for c in conteggi]])
    salva(db, "urp", [scheda("urp", "/node/1", "367.535 CTER", "367.535", documenti=[doc("g", "graduatoria", "444208")])])
    voci = list(conteggi) if nel_file is None else nel_file
    _carica_segreteria(db, [], [[1, "g.pdf", "367.535 CTER", cod, 1, "Nome Inventato", "80/90", None, None, "1", "2026-05-01", "444208", "2026-05-01", None, None, 0] for cod in voci], [])
    collegamento.collega(db)
    for cod, n in conteggi.items():
        sid = db.execute("SELECT id FROM scheda WHERE id_esterno = ?", (cod,)).fetchone()[0]
        db.execute("INSERT INTO punteggi_verifica (scheda_id, verificato_il, domande, con_punteggi, vincitori, idonei, scorrimento, "
                   "senza_protocollo, esito) VALUES (?, '2026-11-01T00:00:00Z', ?, ?, 1, 0, 0, ?, 'completi')", (sid, n, n, n))
    return [r for r in difformita.righe_correnti(db, "2026-05-01", "2026-05-31") if r["atto"] == "graduatoria"]


def _rilievi_candidati(r):
    return [n for n in r["note"] if "non valorizzato" in n]


def test_atto_unico_per_piu_sedi_dice_di_quale_sede_e_ogni_rilievo(db):
    righe = _sedi(db, {"01 ISMAR VE": 2, "06 STEMS NA": 5})
    assert len(righe) == 1
    r = righe[0]
    assert r["codice"] == "367.535 CTER - Supporto"  # la riga è del padre, non di una sede
    assert "ISMAR" not in r["titolo_bando"]
    testi = _rilievi_candidati(r)
    assert len(testi) == 2
    assert any(t.startswith("sede «367.535 CTER - 01 ISMAR VE»") and "(2 candidati)" in t for t in testi)
    assert any(t.startswith("sede «367.535 CTER - 06 STEMS NA»") and "(5 candidati)" in t for t in testi)
    assert r["fonti"]["sol"]["url"] == "http://sol/madre"
    assert r["url_punteggi"] is None
    assert r["punteggi"]["domande"] == 7 and r["punteggi"]["candidati"] is False
    assert r["sede_da_abbinare"] is False


def test_una_sola_sede_prende_il_link_di_quella_sede(db):
    r = _sedi(db, {"06 STEMS NA": 2})[0]
    assert r["codice"] == "367.535 CTER - 06 STEMS NA"
    assert "sede «" not in " ".join(r["note"])
    assert r["fonti"]["sol"]["url"] == "http://sol/06 STEMS NA"
    assert len(_rilievi_candidati(r)) == 1


def test_sede_scritta_in_altro_modo_nel_file(db):
    r = _sedi(db, {"01 ISMAR VE": 2, "06 STEMS NA": 5}, nel_file=["CODICE 06 STEMS NA"])[0]
    assert r["codice"] == "367.535 CTER - 06 STEMS NA"
    assert [("5 candidati" in t) for t in _rilievi_candidati(r)] == [True]


def test_sede_non_riconosciuta_non_si_sceglie_a_caso(db):
    r = _sedi(db, {"01 ISMAR VE": 2, "06 STEMS NA": 5}, nel_file=["SEDE INVENTATA"])[0]
    assert r["sede_da_abbinare"] is True
    assert r["codice"] == "367.535 CTER - Supporto"
    assert _rilievi_candidati(r) == []
    assert r["punteggi"] is None


def test_graduatoria_sul_padre_vale_per_tutte_le_sedi(db):
    r = _sedi(db, {"01 ISMAR VE": 2, "06 STEMS NA": 5}, nel_file=[], doc_padre=True)[0]
    assert r["fonti"]["sol"]["stato"] == atti.PRESENTE
    assert r["sede_da_abbinare"] is False
    assert len(_rilievi_candidati(r)) == 2
    assert "non allegata" not in " ".join(r["note"])


def test_abbina_solo_se_la_sede_e_una():
    figlio = lambda c, s=None: {"codice_originale": c, "dati_extra": json.dumps({"sede": s}) if s else None}  # noqa: E731
    figli = [figlio("367.434 CA - TRIESTE Codice 05"), figlio("367.434 CA - ROMA Codice 13"), figlio("367.498 RIC ISPA MI", "Istituto Alfa")]
    assert sedi.abbina("TRIESTE", figli) is figli[0]
    assert sedi.abbina("cod. 13", figli) is figli[1]
    assert sedi.abbina("MI", figli) is figli[2]
    assert sedi.abbina("alfa", figli) is figli[2]
    assert sedi.abbina("CA", figli) is None  # vale per due sedi
    assert sedi.abbina("NAPOLI", figli) is None


def test_codice_sede_dal_codice_sol():
    assert normalizza.codice_sede("367.535 CTER - 06 STEMS NA") == "6"
    assert normalizza.codice_sede("367.535 CTER - Supporto alla Ricerca") is None
    assert normalizza.codice_sede("367.565 RIC ITM") is None


def test_vecchio_rilievo_senza_sede_non_risulta_risolto():
    vecchio = "protocollo della graduatoria pubblica (oscurata) non valorizzato sui candidati su SOL (5 candidati)"
    attuali = [f"sede «A»: {vecchio}", "sede «B»: protocollo della graduatoria pubblica (oscurata) non valorizzato sui candidati su SOL (2 candidati)"]
    voci, badge = difformita._stato_rilievi({"rilievi_iniziali": json.dumps([vecchio]), "rilievi_attuali": json.dumps(attuali), "stato": difformita.APERTA})
    assert [v["testo"] for v in voci] == attuali
    assert not any(v["risolto"] or v["nuovo"] for v in voci)
    assert badge == "da_correggere"


def test_link_urp_alla_pagina_con_tutti_i_documenti(db):
    pagina = config.URP_ARCHIVIO_BASE + config.URP_ARCHIVIO_PAGINA
    assert config.pagina_documenti_urp("tempo-indeterminato", "http://urp/node/1", "x") == "http://urp/node/1"
    assert config.pagina_documenti_urp(config.URP_ARCHIVIO_SEZIONE, "http://a/b.pdf", "Codice Bando 367.434 CA") == f"{pagina}#:~:text=Codice%20Bando%20367.434%20CA"
    assert config.pagina_documenti_urp(config.URP_ARCHIVIO_SEZIONE, "http://a/b.pdf", "A-B") == f"{pagina}#:~:text=A%2DB"
    assert config.pagina_documenti_urp(config.URP_ARCHIVIO_SEZIONE, "http://a/b.pdf", None) == pagina
