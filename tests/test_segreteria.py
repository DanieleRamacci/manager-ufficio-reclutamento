"""File della segreteria: lettura, rapporto, atti, versioni (spec 002). Dati inventati."""
import io
from datetime import datetime

import openpyxl
import pytest

from monitoraggio import segreteria

INTESTAZIONI = {
    "Bandi": ["File", "Bando", "Tipo procedura", "Istituto/Ufficio", "Sede",
              "Dipartimento afferenza / Ufficio richiedente", "Oggetto / Tematica",
              "Fascia compenso (Direttori) / Posti-Livello (CTER)", "Termine presentazione domanda",
              "Prot. CNR n.", "Data protocollo"],
    "Graduatorie": ["Prog.", "File", "N. Bando", "Sotto-bando", "Posizione", "Cognome e Nome", "Punteggio",
                    "Esito", "Note", "N. Protocollo Privato", "Data Protocollo Privato", "N. Protocollo Pubblico",
                    "Data Protocollo Pubblico", "Presenza stato avanzamento", "N Bando", "Referente"],
    "Scorrimento": ["File", "N. Bando", "Sotto-bando", "Posizione", "Cognome e Nome", "Note", "N. Protocollo",
                    "Data Protocollo", "Tipologia di Utilizzo della Graduatoria", None, "Note", None],
}

BANDI = [
    ["Bando_390_475.pdf", 390.475, "Selezione Direttore d'Istituto", "Istituto X", "Roma", "DSU", "Direzione",
     "Fascia 1", "30 giorni", "0308883", "07/07/2026"],
    ["Bando_367_601.pdf", "367.601", "Concorso pubblico per titoli ed esami", "Istituto Y", "Bari", "DSB", "Ricerca",
     "1 posto", "30 giorni", "0201000", datetime(2026, 5, 20)],
    ["Bando_367_500.pdf", 367.5, "Concorso pubblico per titoli ed esami (CTER)", "Istituto Z", "Pisa", "DIITET",
     "Supporto", "2 posti", "30 giorni", 201555, "21/05/2026"],
]

GRADUATORIE = [
    [1, "https://x/Graduatoria_367601.pdf", "367.601 FA ISTC", None, 1, "Rossi Mario", "88,00/90", None, None,
     "0270001", "11/06/2026", "0270086", datetime(2026, 6, 12), "X", 367601, 0],
    [2, "https://x/Graduatoria_367601.pdf", "367.601 FA ISTC", None, 2, "Bianchi Anna", "80,00/90", None, None,
     "0270001", "11/06/2026", "0270086", datetime(2026, 6, 12), "X", 367601, 0],
    [3, "https://x/Grad_367434_13.pdf", "367.434 CA Cod. 13", "13 Roma", 1, "Verdi Luca", "70/90", None, None,
     "0280000", "18/06/2026", "0281000", "19/06/2026", None, 367434, 0],
    [4, "https://x/Grad_x.pdf", "367.700 RIC", None, 1, "Neri Paola", "60/90", None, None,
     None, None, None, "data sbagliata", None, 367701, 0],
]

SCORRIMENTI = [
    ["Utilizzo graduatorie\\a.pdf", "367.434 CA. Cod 13", "Roma", 100, "Gialli Pietro", None, "0281920",
     datetime(2026, 6, 19), "Scorrimento", None, None, None],
    ["Utilizzo graduatorie\\a.pdf", "367.434 CA. Cod 13", "Roma", 101, "Blu Sara", None, "0281920",
     datetime(2026, 6, 19), "Subentro", None, "Rinuncia nei 6 mesi", None],
    ["Utilizzo graduatorie\\b.pdf", "367.601 FA ISTC", None, 3, "Viola Elena", None, 297136,
     datetime(2026, 6, 30), "Subentro", None, None, None],
    ["Utilizzo graduatorie\\c.pdf", "367.601 FA ISTC", None, 4, "Rosa Marco", None, 300000,
     datetime(2026, 7, 2), None, None, None, None],
    ["Utilizzo graduatorie\\d.pdf", None, None, 5, "Senza Bando", None, 300001, datetime(2026, 7, 3), None, None, None,
     None],
]


def crea_excel(fogli=None, colonne_tolte=()) -> bytes:
    fogli = fogli or {"Bandi": BANDI, "Graduatorie": GRADUATORIE, "Scorrimento": SCORRIMENTI}
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, righe in fogli.items():
        ws = wb.create_sheet(nome)
        intestazioni = [None if h in colonne_tolte else h for h in INTESTAZIONI[nome]]
        ws.append(intestazioni)
        for r in righe:
            ws.append(r)
        if nome == "Scorrimento":
            ws.auto_filter.ref = "A1:H2"  # filtro su poche righe: vanno lette tutte comunque
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_lettura_e_atti():
    righe, rapporto = segreteria.leggi_file(crea_excel())
    assert {f: len(r) for f, r in righe.items()} == {"bandi": 3, "graduatorie": 4, "scorrimento": 5}
    atti = segreteria.costruisci_atti(righe, rapporto)
    per_chiave = {(a["categoria"], a["numero_bando"], a["codice_sotto"], a["protocollo"]): a for a in atti}

    # numeri di bando letti come numero Excel: 390.475 e 367.5 (=367.500)
    assert ("bando", "390.475", None, "308883") in per_chiave
    assert ("bando", "367.500", None, "201555") in per_chiave
    assert per_chiave[("bando", "390.475", None, "308883")]["in_ambito"] is False  # direttori
    assert per_chiave[("bando", "367.601", None, "201000")]["data"] == "2026-05-20"

    grad = per_chiave[("graduatoria", "367.601", None, "270086")]
    assert (grad["persone"], grad["protocollo_privato"], grad["data"], grad["data_privato"]) == (2, "270001", "2026-06-12", "2026-06-11")
    assert ("graduatoria", "367.434", "13", "281000") in per_chiave

    scorr = per_chiave[("scorrimento", "367.434", "13", "281920")]
    assert (scorr["persone"], scorr["sottotipo"]) == (2, "misto")
    assert per_chiave[("scorrimento", "367.601", None, "297136")]["sottotipo"] == "subentro"
    assert per_chiave[("scorrimento", "367.601", None, "300000")]["sottotipo"] is None


def test_rapporto():
    righe, rapporto = segreteria.leggi_file(crea_excel())
    segreteria.costruisci_atti(righe, rapporto)
    g, s = rapporto["fogli"]["graduatorie"], rapporto["fogli"]["scorrimento"]
    assert g["problemi"]["senza_protocollo"] == [5]       # riga Excel 5 (la 4ª di dati)
    assert g["problemi"]["data_illeggibile"] == [5]
    assert g["problemi"]["numero_discordante"] == [5]     # 367.700 contro 367701
    assert s["problemi"]["senza_tipologia"] == [5, 6]
    assert s["problemi"]["senza_bando"] == [6]
    assert rapporto["fogli"]["bandi"]["fuori_ambito"] == 1
    assert g["colonne_mancanti"] == []


def test_colonna_mancante_segnalata():
    _, rapporto = segreteria.leggi_file(crea_excel(colonne_tolte=("Tipologia di Utilizzo della Graduatoria",)))
    assert "tipologia" in rapporto["fogli"]["scorrimento"]["colonne_mancanti"]


def test_foglio_mancante_non_blocca():
    righe, rapporto = segreteria.leggi_file(crea_excel({"Bandi": BANDI}))
    assert set(righe) == {"bandi"}
    assert rapporto["fogli"]["graduatorie"]["trovato"] is False


@pytest.mark.parametrize("contenuto", [b"non sono un excel", b""])
def test_file_non_valido(contenuto):
    with pytest.raises(segreteria.FileNonValido):
        segreteria.leggi_file(contenuto)


def test_nessun_foglio_riconosciuto():
    wb = openpyxl.Workbook()
    wb.active.title = "Foglio1"
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(segreteria.FileNonValido, match="Nessuno dei fogli"):
        segreteria.leggi_file(buf.getvalue())


def test_importa_versioni_e_differenze(db):
    v1 = segreteria.importa(db, crea_excel(), "file.xlsx", "utente@cnr.it")
    assert v1["esito"] == "in_uso" and v1["atti"] > 0
    # stesso file: nessuna differenza
    v2 = segreteria.importa(db, crea_excel(), "file.xlsx", "utente@cnr.it")
    assert segreteria.differenze(db, v2["id"]) == {"precedente": v1["id"], "nuovi": [], "spariti": [], "modificati": []}
    assert db.execute("SELECT esito FROM segreteria_versione WHERE id = ?", (v1["id"],)).fetchone()[0] == "precedente"
    # un nuovo scorrimento e una data corretta
    scorr = SCORRIMENTI + [["x", "367.601 FA ISTC", None, 6, "Nuovo Nome", None, 310000, datetime(2026, 7, 9), "Scorrimento",
                            None, None, None]]
    grad = [r[:] for r in GRADUATORIE]
    grad[0][12] = grad[1][12] = datetime(2026, 6, 13)
    v3 = segreteria.importa(db, crea_excel({"Bandi": BANDI, "Graduatorie": grad, "Scorrimento": scorr}), "f.xlsx", "u")
    diff = segreteria.differenze(db, v3["id"])
    assert [(a["categoria"], a["protocollo"]) for a in diff["nuovi"]] == [("scorrimento", "310000")]
    assert [(m["chiave"]["protocollo"], m["campi"]) for m in diff["modificati"]] == [
        ("270086", {"data": ["2026-06-12", "2026-06-13"]})]


def test_importa_rifiuta_senza_cambiare_versione(db):
    v1 = segreteria.importa(db, crea_excel(), "file.xlsx", "u")
    with pytest.raises(segreteria.FileNonValido):
        segreteria.importa(db, b"rotto", "rotto.xlsx", "u")
    assert segreteria.versione_in_uso(db)["id"] == v1["id"]
    assert db.execute("SELECT COUNT(*) FROM segreteria_versione WHERE esito = 'rifiutata'").fetchone()[0] == 1


def test_nominativi_solo_nel_database(db, caplog):
    caplog.set_level("DEBUG")
    v = segreteria.importa(db, crea_excel(), "file.xlsx", "u")
    assert "Rossi Mario" not in caplog.text
    righe = segreteria.righe_atto(db, db.execute(
        "SELECT id FROM segreteria_atto WHERE versione_id = ? AND protocollo = '270086'", (v["id"],)).fetchone()[0])
    assert {r["valori"]["Cognome e Nome"] for r in righe} == {"Rossi Mario", "Bianchi Anna"}
