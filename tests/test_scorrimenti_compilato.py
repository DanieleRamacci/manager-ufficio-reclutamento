"""File scorrimenti compilato: bando, protocolli, tipologia e nominativi; il subentro si controlla lì (spec 011)."""
import io

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


def test_legge_bando_protocolli_subentro_e_nominativi():
    """Spec 011: i nominativi ora si leggono, per il confronto con il file della segreteria (solo amministratori)."""
    voci = sc.leggi(FILE)
    assert [(v["numero_bando"], v["protocolli"], v["subentro"], v["nominativi"]) for v in voci] == [
        ("367.614", ["354474"], False, ["Mario Inventato"]), ("367.434", ["356259"], True, ["Anna Inventata"]),
        ("367.999", ["400001"], False, ["Luca Inventato"])]


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



def _riga(numero, protocollo, chiave=None, gruppo_bando=1, subentro=False, data="2026-10-28"):
    return {"atto": "scorrimento", "chiave": chiave or f"{numero} X", "codice": chiave or f"{numero} X", "numero_bando": numero,
            "protocollo": protocollo, "data": data, "subentro_atteso": subentro, "fonti": {"segreteria": {"stato": "presente"}},
            "bando_id": gruppo_bando, "rdp": []}


PROFILI = ({1: "Collaboratore di amministrazione", 2: "Ricercatore", 3: "Collaboratore tecnico enti di ricerca"}, {})


def test_una_riga_per_nominativo_e_subtotali_ignorati():
    file = _file({"COLL.AMM": [["367.434 Cod. 13 ROMA", 1, "SCORRIMENTO", None, "Uno Inventato", None, "461293 DEL 28/10/2026", "Scorrimento"],
                               ["367.434 Cod. 13 ROMA", 1, "SCORRIMENTO", None, "Due Inventato", None, "461293 DEL 28/10/2026", "Scorrimento"],
                               ["CODICE 13 ROMA TOTALE", 2, None, None, None, None, None, None]]})
    letto = sc.leggi_file(file)
    assert len(letto["voci"]) == 2 and letto["fogli"] == ["COLL.AMM"]
    esito = sc.confronta([_riga("367.434", "461293")], letto["voci"], letto["fogli"], profili_bandi=PROFILI)
    assert esito["atti"][0]["trovato"] and esito["atti"][0]["nominativi"] == 2 and esito["atti"][0]["gravi"] == []
    assert esito["atti"][0]["tipo"] == "scorrimento" and esito["solo_nel_file"] == [] and esito["allineato"]


def test_ogni_scorrimento_del_monitoraggio_deve_esserci_anche_se_manca_il_foglio():
    """Come i CTER di ottobre: due scorrimenti dello stesso bando e una sola riga senza protocollo; e un RIC senza foglio RIC."""
    file = _file({"CTER 6": [["367.524 CTER - COD. 02 AR BO", 1, "Istituto", None, None, None, None, None]],
                  "COLL.AMM": [["367.434 Cod. 13", 1, None, None, "Uno Inventato", None, "461293 del 28/10/2026", "Scorrimento"]]})
    letto = sc.leggi_file(file)
    righe = [_riga("367.524", "488031", "367.524 CTER COD 02", 3), _riga("367.524", "488076", "367.524 CTER COD 05", 3),
             _riga("367.560", "488082", "367.560 RIC", 2), _riga("367.434", "461293", "367.434 CA", 1)]
    esito = sc.confronta(righe, letto["voci"], letto["fogli"], profili_bandi=PROFILI)
    per = {a["chiave"]: a for a in esito["atti"]}
    assert per["367.524 CTER COD 02"]["trovato"] and "protocollo del provvedimento non indicato" in per["367.524 CTER COD 02"]["problemi"]
    assert "tipologia non indicata" in per["367.524 CTER COD 02"]["problemi"]
    assert not per["367.524 CTER COD 05"]["trovato"] and per["367.524 CTER COD 05"]["gravi"] == ["manca nel file scorrimenti"]
    assert per["367.560 RIC"]["gravi"] == ["manca nel file scorrimenti", "nel file manca il foglio RIC"]
    assert esito["fogli_mancanti"] == [{"gruppo": "RIC", "nome": "Ricercatore", "scorrimenti": 1}] and not esito["allineato"]


def test_bando_scritto_male_si_riconosce_dal_protocollo():
    file = _file({"COLL.AMM": [["36.434 Cod. 10 BOLOGNA", 1, None, None, "Uno Inventato", None, "461290 DEL 28/10/2026", "Scorrimento"]]})
    letto = sc.leggi_file(file)
    esito = sc.confronta([_riga("367.434", "461290")], letto["voci"], letto["fogli"], profili_bandi=PROFILI)
    assert esito["atti"][0]["trovato"] and esito["atti"][0]["gravi"] == []
    assert esito["atti"][0]["minori"] == ["nel file il bando è scritto «36.434 Cod. 10 BOLOGNA»"]  # errore minore
    assert esito["solo_nel_file"] == []


def test_nominativi_tipologia_e_posizioni_confrontati_con_la_segreteria():
    from monitoraggio import verifica_file as vf
    file = _file({"COLL.AMM": [["367.434 Cod. 13", 3, None, None, "Rossi Mario", None, "461293 del 28/10/2026", "Scorrimento"],
                               ["367.434 Cod. 13", None, None, None, "Neri Anna", None, "461293 del 28/10/2026", "Scorrimento"]]})
    letto = sc.leggi_file(file)
    persone = {("367.434", "461293"): [{"nominativo": "MARIO ROSSI", "chiave": vf.nome_chiave("MARIO ROSSI"), "tipologia": "Subentro"},
                                       {"nominativo": "Bianchi Luca", "chiave": vf.nome_chiave("Bianchi Luca"), "tipologia": "Subentro"}]}
    a = sc.confronta([_riga("367.434", "461293")], letto["voci"], letto["fogli"], persone, PROFILI)["atti"][0]
    assert "tipologia «scorrimento» nel file, «subentro» nel file della segreteria" in a["gravi"]
    assert "Neri Anna: nel file scorrimenti ma non nel file della segreteria" in a["gravi"]
    assert "Bianchi Luca: nel file della segreteria ma non nel file scorrimenti" in a["gravi"]
    assert "3 posizioni dichiarate, 2 nominativi" in a["minori"]
    assert not any("Rossi" in p for p in a["gravi"] + a["minori"])  # stesso nome scritto in ordine e maiuscole diversi


def test_righe_del_file_che_non_sono_nel_monitoraggio():
    file = _file({"RIC": [["367.700 RIC", 1, None, None, "Uno Inventato", None, "500001 del 1/10/2026", "Scorrimento"]]})
    letto = sc.leggi_file(file)
    esito = sc.confronta([], letto["voci"], letto["fogli"], profili_bandi=PROFILI)
    assert [(s["bando"], s["protocolli"]) for s in esito["solo_nel_file"]] == [("367.700 RIC", ["500001"])] and not esito["allineato"]



def test_nomi_veri_da_sol_e_conteggio_per_bando():
    """I nomi veri degli assunti da scorrimento sono su Selezioni Online; un refuso è un errore minore. Se il file indica per un
    bando più scorrimenti di quelli che risultano dalla segreteria e da URP, lo si segnala."""
    file = _file({"COLL.AMM": [["367.434 Cod. 13", 1, None, None, "Rossi Mraio", None, "461293 del 28/10/2026", "Scorrimento"],
                               ["367.434 Cod. 14", 1, None, None, "Verdi Luca", None, "461295 del 28/10/2026", "Subentro"],
                               ["367.434 Cod. 15", 1, None, None, "Gialli Anna", None, "461297 del 28/10/2026", "Subentro"]]})
    letto = sc.leggi_file(file)
    sol = {"461293": [{"nominativo": "Rossi Mario"}, {"nominativo": "Bianchi Sara"}]}
    righe = [{**_riga("367.434", "461293"), "fonti": {"segreteria": {"stato": "presente"}}},
             {**_riga("367.434", "461295", "367.434 COD 14"), "fonti": {"urp": {"stato": "presente"}}}]
    esito = sc.confronta(righe, letto["voci"], letto["fogli"], {}, PROFILI, sol)
    a = esito["atti"][0]
    assert a["minori"] == ["nome scritto diverso: «Rossi Mario» su Selezioni Online, «Rossi Mraio» nel file scorrimenti"]
    assert a["gravi"] == ["Bianchi Sara: su Selezioni Online ma non nel file scorrimenti"]
    assert "su Selezioni Online lo scorrimento non è ancora indicato (esito S con questo protocollo)" in esito["atti"][1]["minori"]
    assert esito["conteggi_bando"] == [{"numero_bando": "367.434", "scorrimenti_file": 3, "scorrimenti_rif": 2, "subentri_file": 2, "subentri_rif": 0}]
    assert [b["tipo"] for b in esito["solo_nel_file"]] == ["subentro"] and not esito["allineato"]
