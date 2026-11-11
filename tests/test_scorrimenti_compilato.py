"""File scorrimenti compilato: si leggono bando, protocolli e tipologia, mai i nominativi; il subentro si controlla lì."""
import io
import json

import openpyxl
import pytest

from monitoraggio import scorrimenti_compilato as sc

INTESTAZIONI = ["BANDO SU CUI SCORRERE", "N. POSIZIONI", "STRUTTURA RICHIEDENTE", "PROT. RICHIESTA", "NOMINATIVI SCORRIMENTI",
                "PROVVEDIMENTO DG", "PROVVEDIMENTO RECLUTAMENTO", "TIPOLOGIA"]


def _file(fogli: dict) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, righe in fogli.items():
        ws = wb.create_sheet(nome)
        ws.append([f"SCORRIMENTI – {nome}"])
        ws.append(INTESTAZIONI)
        for r in righe:
            ws.append(r)
        ws.append(["TOTALE UNITÀ"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# come nel file di agosto 2026: bando senza punto, subentro scritto nella colonna della struttura
FILE = _file({
    "CTER 6": [[367614, 2, "Istituto ISTC", None, "Mario Inventato", None, "0354474 del 4/8/2026", "disponibilità di risorse"]],
    "Camm 7": [["367.434 Codice 13 Roma", 1, "subentro", None, "Anna Inventata", "356259 in data 06/08/2026", None, None],
               ["367.999 altro", 1, "Istituto", None, "Luca Inventato", None, "0400001 del 1/8/2026", None]],
})


def test_legge_bando_protocolli_e_subentro_ma_non_i_nominativi():
    voci = sc.leggi(FILE)
    assert [(v["numero_bando"], v["protocolli"], v["subentro"]) for v in voci] == [
        ("367.614", ["354474"], False), ("367.434", ["356259"], True), ("367.999", ["400001"], False)]
    assert "Inventat" not in json.dumps(voci)


def test_file_senza_righe_o_non_excel():
    with pytest.raises(sc.FileNonValido):
        sc.leggi(_file({"CTER 6": []}))
    with pytest.raises(sc.FileNonValido):
        sc.leggi(b"non un excel")


def test_confronto_con_gli_scorrimenti_del_mese():
    righe = [{"atto": "scorrimento", "chiave": "367.434 CA", "codice": "367.434 CA", "numero_bando": "367.434", "protocollo": "356259",
              "data": "2026-08-06", "subentro_atteso": True, "fonti": {}},
             {"atto": "scorrimento", "chiave": "367.614 CTER", "codice": "367.614 CTER", "numero_bando": "367.614", "protocollo": "354474",
              "data": "2026-08-04", "subentro_atteso": True, "fonti": {}},
             {"atto": "scorrimento", "chiave": "367.700 RIC", "codice": "367.700 RIC", "numero_bando": "367.700", "protocollo": "1",
              "data": "2026-08-01", "subentro_atteso": False, "fonti": {}}]
    esito = sc.confronta(righe, sc.leggi(FILE))
    assert [(a["trovato"], a["subentro_indicato"]) for a in esito["atti"]] == [(True, True), (True, False), (False, False)]
    assert [v["bando"] for v in esito["solo_nel_file"]] == ["367.999 altro"]


def test_esito_sulle_righe_del_monitoraggio(db):
    righe = [{"atto": "scorrimento", "chiave": "367.434 CA", "numero_bando": "367.434", "protocollo": "356259", "data": "2026-08-06",
              "subentro_atteso": True, "fonti": {}}]
    sc.per_riga(db, "2026-09", righe)
    assert "file_scorrimenti" not in righe[0]  # nessun file caricato
    sc.salva(db, "2026-09", "f.xlsx", sc.leggi(FILE), "capo.ufficio")
    sc.per_riga(db, "2026-09", righe)
    assert righe[0]["file_scorrimenti"]["subentro_indicato"] is True
