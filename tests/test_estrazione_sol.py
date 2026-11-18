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
    assert per["367.562"]["trovato"] and per["367.562"]["candidati"] == 2 and per["367.562"]["problemi"] == []
    assert per["367.700"]["problemi"] == ["manca nell'estrazione"]
    assert per["367.524"]["problemi"] == ["manca nell'estrazione", "nell'estrazione non c'è nessuna graduatoria CTER"]
    assert [s["numero_bando"] for s in esito["solo_nel_file"]] == ["367.999"] and esito["fuori_periodo"] == 1
    assert esito["senza_graduatoria"] == 1 and not esito["allineato"]


def test_confronto_per_persona_con_la_segreteria():
    persone = {("367.562", "444208"): [{"nominativo": "Rossi Inventato", "chiave": vf.nome_chiave("Inventato Rossi"), "posizione": 1, "punteggio": "80/100"},
                                       {"nominativo": "Bianchi Inventato", "chiave": vf.nome_chiave("Bianchi Inventato"), "posizione": 3, "punteggio": "78.5"},
                                       {"nominativo": "Assente Inventato", "chiave": vf.nome_chiave("Assente Inventato"), "posizione": 4, "punteggio": "60"}]}
    problemi = es.confronta([_grad("367.562", "444208")], ESTRAZIONE, "2026-10-01", "2026-10-31", persone, PROFILI)["atti"][0]["problemi"]
    assert problemi == ["Assente Inventato: nel file della segreteria ma non nel file", "Bianchi Inventato: posizione 2 nel file, 3 nella segreteria"]


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
