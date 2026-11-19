"""Estrazione delle graduatorie da Selezioni Online (spec 011): lettura, confronto con il monitoraggio, file graduatorie."""
import io

import openpyxl
import pytest

from monitoraggio import estrazione_sol as es, verifica_file as vf
from monitoraggio.punteggi import INTESTAZIONI_EXCEL

TESTA = INTESTAZIONI_EXCEL[:11] + ["Matricola"] + INTESTAZIONI_EXCEL[11:] + ["Data Ultima Modifica"]


def _candidato(codice, profilo, cognome, punteggio, posizione, protocollo="0444208", data="20/10/2026", esito="I"):
    valori = {"Codice bando": codice, "Profilo/Livello": profilo, "Cognome": cognome, "Nome": "Inventato", "Totale Punteggi": punteggio,
              "Graduatoria": posizione, "Esito": esito, "Numero Protocollo Graduatoria": protocollo, "Data Protocollo Graduatoria": data}
    return [valori.get(h) for h in TESTA]


def _file(righe) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Punteggi"
    ws.append(TESTA)
    for r in righe:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ESTRAZIONE = es.leggi(_file([
    _candidato("367.562 RIC ISSMC", "Ricercatore III livello", "Bianchi", "78,5", "2"),
    _candidato("367.562 RIC ISSMC", "Ricercatore III livello", "Rossi", "80", "1", esito="V"),
    _candidato("367.562 RIC ISSMC", "Ricercatore III livello", "Verdi", "40", "", protocollo="", data=""),  # non in graduatoria
    _candidato("367.999 RIC", "Ricercatore III livello", "Neri", "70", "1", protocollo="0500001"),  # non nel monitoraggio
    _candidato("367.100 RIC", "Ricercatore III livello", "Gialli", "70", "1", protocollo="0300001", data="19/06/2026"),  # fuori periodo
]))


def _grad(numero, protocollo, bando_id=1):
    return {"atto": "graduatoria", "chiave": f"{numero} X", "codice": f"{numero} X", "numero_bando": numero, "protocollo": protocollo,
            "data": "2026-10-20", "fonti": {}, "bando_id": bando_id, "rdp": [{"email": "rdp@cnr.it"}]}


PROFILI = ({1: "Ricercatore", 2: "Collaboratore tecnico enti di ricerca"}, {})


def test_legge_l_export_punteggi():
    r = next(x for x in ESTRAZIONE if x["cognome"] == "Rossi")
    assert (r["numero_bando"], r["protocollo_graduatoria"], r["data_graduatoria"], r["nominativo"]) == ("367.562", "444208", "2026-10-20", "Rossi Inventato")
    assert r["colonne"]["Codice bando"] == "367.562 RIC ISSMC" and set(r["colonne"]) == set(INTESTAZIONI_EXCEL)
    with pytest.raises(es.FileNonValido):
        es.leggi(b"non un excel")
    with pytest.raises(es.FileNonValido):
        es.leggi(_file([]))


def test_confronto_in_entrambe_le_direzioni_e_gruppi_mancanti():
    righe = [_grad("367.562", "444208"), _grad("367.700", "455052"), _grad("367.524", "448313", bando_id=2)]
    esito = es.confronta(righe, ESTRAZIONE, "2026-10-01", "2026-10-31", profili_bandi=PROFILI)
    per = {a["numero_bando"]: a for a in esito["atti"]}
    assert per["367.562"]["trovato"] and per["367.562"]["candidati"] == 2 and per["367.562"]["gravi"] == []
    assert per["367.700"]["gravi"] == ["manca nell'estrazione da Selezioni Online"]
    assert per["367.524"]["gravi"] == ["manca nell'estrazione da Selezioni Online", "nell'estrazione non c'è nessuna graduatoria CTER"]
    assert [s["numero_bando"] for s in esito["solo_nel_file"]] == ["367.999"] and esito["fuori_periodo"] == 1
    assert esito["senza_graduatoria"] == 1 and not esito["allineato"]


def test_confronto_per_persona_con_la_segreteria():
    persone = {("367.562", "444208"): [{"nominativo": "Rossi Inventato", "chiave": vf.nome_chiave("Inventato Rossi"), "posizione": 1, "punteggio": "80/100"},
                                       {"nominativo": "Bianchi Inventato", "chiave": vf.nome_chiave("Bianchi Inventato"), "posizione": 3, "punteggio": "78.5"},
                                       {"nominativo": "Assente Inventato", "chiave": vf.nome_chiave("Assente Inventato"), "posizione": 4, "punteggio": "60"}]}
    a = es.confronta([_grad("367.562", "444208")], ESTRAZIONE, "2026-10-01", "2026-10-31", persone, PROFILI)["atti"][0]
    assert a["gravi"] == ["Assente Inventato: nel file della segreteria ma non su Selezioni Online"]
    assert a["minori"] == ["Bianchi Inventato: posizione 2 su Selezioni Online, 3 nel file della segreteria"]  # minore


def test_file_graduatorie_ordinato_per_gruppo_e_punteggio():
    estrazione = es.leggi(_file([
        _candidato("367.524 CTER", "Collaboratore tecnico enti di ricerca VI livello", "Cter", "90", "1", protocollo="0448313"),
        _candidato("367.562 RIC ISSMC", "Ricercatore III livello", "Bianchi", "78,5", "2"),
        _candidato("367.562 RIC ISSMC", "Ricercatore III livello", "Rossi", "80", "1"),
        _candidato("367.610 MOB", "Ricercatore III livello", "Mobile", "50", "1", protocollo="0449999"),
    ]))
    concorsi, mobilita = es.righe_excel(estrazione, "2026-10-01", "2026-10-31", {"367.610"})
    cognome = INTESTAZIONI_EXCEL.index("Cognome")
    assert [v[cognome] for v, _ in concorsi] == ["Rossi", "Bianchi", "Cter"]  # prima i RIC, per punteggio; poi i CTER
    assert [v[cognome] for v, _ in mobilita] == ["Mobile"]


def test_nominativi_apostrofi_refusi_e_persone_sotto_un_altro_bando():
    """Dai file reali di ottobre: DELL'ORSO/DELL’ORSO è la stessa persona; MATTIA/MATTAI è un refuso; la graduatoria di un altro
    bando copiata sotto questo nel file della segreteria si segnala in una riga sola."""
    assert vf.nome_chiave("DELL'ORSO ISABELLA") == vf.nome_chiave("Dell’Orso Isabella") == vf.nome_chiave("ISABELLA DELL ORSO")
    assert vf.gruppo_di_foglio("PT") == vf.gruppo_di_foglio("DT") == "DT" and vf.gruppo_di_foglio("CTER 6") == "CTER"
    estrazione = es.leggi(_file([
        _candidato("367.562 RIC ISSMC", "Ricercatore III livello", "Boscherini", "80", "1", protocollo="0445338"),
        _candidato("367.483 RIC IEIIT PD", "Ricercatore III livello", "Altro", "70", "1", protocollo="0448313"),
        _candidato("367.483 RIC IEIIT PD", "Ricercatore III livello", "Ancora", "69", "2", protocollo="0448313"),
    ]))
    persona = lambda n, pos: {"nominativo": n, "chiave": vf.nome_chiave(n), "posizione": pos, "punteggio": None}  # noqa: E731
    persone = {("367.562", "445338"): [persona("Boscherini Inventatp", 1), persona("Altro Inventato", 1), persona("Ancora Inventato", 2)]}
    righe = [{"atto": "graduatoria", "chiave": "367.562 RIC", "numero_bando": "367.562", "protocollo": "445338", "data": "2026-10-20",
              "fonti": {}, "bando_id": 1, "rdp": []}]
    a = es.confronta(righe, estrazione, "2026-10-01", "2026-10-31", persone, PROFILI)["atti"][0]
    assert a["minori"] == ["nome scritto diverso: «Boscherini Inventato» su Selezioni Online, «Boscherini Inventatp» nel file della segreteria"]
    assert a["gravi"] == ["2 persone nel file della segreteria per questo bando sono su Selezioni Online sotto «367.483 RIC IEIIT PD (prot. 448313)»: "
                          "bando o protocollo da verificare (Altro Inventato, Ancora Inventato)"]



def test_nel_file_restano_i_candidati_non_in_graduatoria_dopo_gli_altri():
    estrazione = es.leggi(_file([
        _candidato("367.562 RIC ISSMC", "Ricercatore III livello", "Fuori", "40", "", protocollo="", data="", esito=""),
        _candidato("367.562 RIC ISSMC", "Ricercatore III livello", "Dentro", "80", "1", protocollo="0445338"),
        _candidato("367.999 RIC ALTRO", "Ricercatore III livello", "Altrobando", "50", "", protocollo="", data=""),  # bando senza graduatoria
    ]))
    concorsi, _ = es.righe_excel(estrazione, "2026-10-01", "2026-10-31", set())
    cognome = INTESTAZIONI_EXCEL.index("Cognome")
    assert [v[cognome] for v, _ in concorsi] == ["Dentro", "Fuori"]
