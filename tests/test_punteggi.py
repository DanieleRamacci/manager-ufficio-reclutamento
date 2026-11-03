"""Punteggi delle graduatorie su SOL con la sessione dell'utente (spec 004): risposte simulate, persone inventate."""
import io

import openpyxl
import pytest

from monitoraggio import collegamento, punteggi
from monitoraggio.fonti import sol_auth
from monitoraggio.fonti.http import FonteErrore
from tests.test_collegamento import doc, salva, scheda


def _graduatorie(db):
    a = scheda("sol", "call-a", "367.601 FA ISTC", "367.601", documenti=[doc("ga", "graduatoria", "100", "2026-10-05")])
    a["dati_extra"] = '{"sede": "Bari", "struttura_destinataria": "ISTC", "numero_posti": 1, "profilo": "Funzionario"}'
    b = scheda("sol", "call-b", "367.602 RIC", "367.602", documenti=[doc("gb", "graduatoria", "101", "2026-10-20")])
    c = scheda("sol", "call-c", "367.603 RIC", "367.603", documenti=[doc("gc", "graduatoria", "102", "2026-09-30")])
    d = scheda("sol", "call-d", "367.604 RIC", "367.604")
    d["data_pubbl_graduatoria"] = "2026-10-15"
    salva(db, "sol", [a, b, c, d])
    collegamento.collega(db)


def candidato(cognome, esito, posizione, protocollo="0396898"):
    return {"jconon_application:cognome": cognome, "jconon_application:nome": "Nome",
            "jconon_application:codice_fiscale": "XXXXXX00X00X000X", "jconon_application:esito_call": esito,
            "jconon_application:graduatoria": posizione, "jconon_application:totale_punteggio": 80.5,
            "jconon_application:protocollo_numero_graduatoria": protocollo,
            "jconon_application:protocollo_data_graduatoria": "2026-10-05T12:00:00Z"}


def risposte(dati):
    """dati: call_id -> (domande, [candidati]) oppure eccezione."""
    def risposta(url, params):
        q = params["q"]
        call = q.split("IN_TREE(root, '")[1].split("'")[0]
        valore = dati[call]
        if isinstance(valore, Exception):
            return valore
        domande, lista = valore
        if "aspect_punteggi" not in q:
            return {"items": [], "totalNumItems": domande}
        skip, n = int(params["skipCount"]), int(params["maxItems"])
        return {"items": lista[skip:skip + n], "totalNumItems": len(lista), "hasMoreItems": skip + n < len(lista)}
    return risposta


def test_query_come_estrazione_sol():
    q = sol_auth.query_con_punteggi("abc")
    assert "stato_domanda = 'C'" in q and "esclusione_rinuncia IS NULL" in q
    assert "JOIN jconon_application:aspect_punteggi" in q and "IN_TREE(root, 'abc')" in q
    assert "aspect_punteggi" not in sol_auth.query_domande("abc")


def test_schede_del_periodo(db):
    _graduatorie(db)
    assert {s["id_esterno"] for s in punteggi.schede_periodo(db, "2026-10-01", "2026-10-31")} == {"call-a", "call-b", "call-d"}
    assert {s["id_esterno"] for s in punteggi.schede_periodo(db, "2026-09-25", "2026-10-06")} == {"call-a", "call-c"}


@pytest.mark.parametrize("domande, con, senza, atteso", [
    (0, 0, 0, "nessuna_domanda"), (12, 0, 0, "mancanti"), (12, 5, 0, "parziali"), (12, 12, 0, "completi"),
    (12, 12, 12, "protocollo_mancante"), (12, 12, 3, "protocollo_mancante")])
def test_esito(domande, con, senza, atteso):
    assert punteggi.esito(domande, con, senza) == atteso


def test_verifica_candidati_ed_excel(db, client_finto, monkeypatch):
    monkeypatch.setattr(sol_auth, "PAGINA", 2)
    punteggi.dimentica_candidati()
    _graduatorie(db)
    lista_a = [candidato("Rossi", "V", 1), candidato("Bianchi", "I", 2), candidato("Verdi", "S", 3)]
    lista_b = [candidato("Neri", "V", 1, protocollo=None), candidato("Gialli", "I", 2, protocollo="")]
    client = client_finto(json_per_chiave=risposte({"call-a": (3, lista_a), "call-b": (2, lista_b),
                                                    "call-d": FonteErrore("ReadTimeout su selezionionline")}))
    r = punteggi.verifica(db, "2026-10-01", "2026-10-31", {"Cookie": "ticket=T"}, client=client)
    assert (r["esito"], r["completi"], r["protocollo_mancante"], r["errore"]) == ("completata", 1, 1, 1)
    righe = {x["codice"]: x for x in punteggi.elenco_periodo(db, "2026-10-01", "2026-10-31")}
    a, b = righe["367.601 FA ISTC"], righe["367.602 RIC"]
    assert (a["con_punteggi"], a["vincitori"], a["idonei"], a["scorrimento"], a["esito"]) == (3, 1, 1, 1, "completi")
    assert (b["senza_protocollo"], b["esito"]) == (2, "protocollo_mancante")
    assert a["candidati_disponibili"] and not righe["367.604 RIC"]["candidati_disponibili"]
    assert [c["cognome"] for c in punteggi.candidati(a["scheda_id"])["candidati"]] == ["Rossi", "Bianchi", "Verdi"]

    # nel database solo conteggi, niente nominativi né codici fiscali
    dump = "\n".join(db.iterdump())
    assert "Rossi" not in dump and "XXXXXX00X00X000X" not in dump

    wb = openpyxl.load_workbook(io.BytesIO(punteggi.excel_graduatorie(db, "2026-10-01", "2026-10-31")))
    ws = wb["Graduatorie pubblicate"]
    assert ws["A1"].value == "Codice bando" and ws.max_row == 6
    righe_excel = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
    assert righe_excel[0][:7] == ["367.601 FA ISTC", "Bari", "ISTC", 1, "Funzionario", None, "ROSSI"]
    assert ws.cell(row=5, column=1).fill.fgColor.rgb.endswith("FFF3C4")  # protocollo mancante evidenziato


def test_sessione_non_valida_ferma(db, client_finto):
    _graduatorie(db)
    client = client_finto(json_per_chiave=lambda url, params: FonteErrore("HTTP 401 da selezionionline"))
    r = punteggi.verifica(db, "2026-10-01", "2026-10-31", {"Cookie": "ticket=T"}, client=client)
    assert r["esito"] == "fallita" and "ricollega" in r["messaggio"]
    assert len(client.richieste) == 1


def test_graduatorie_note_da_urp_o_file_senza_allegato_sol(db):
    from tests.test_atti import _carica_segreteria, _riga_grad
    from datetime import datetime
    # SOL senza allegato di graduatoria; la graduatoria è su URP (367.537) o solo nel file (367.565)
    salva(db, "sol", [scheda("sol", "s537", "367.537 CTER", "367.537"), scheda("sol", "s565", "367.565 RIC ITM", "367.565")])
    salva(db, "urp", [scheda("urp", "/node/1", "367.537 CTER", "367.537", documenti=[doc("u1", "graduatoria", "460242", "2026-10-28")])])
    collegamento.collega(db)
    _carica_segreteria(db, [], [_riga_grad("367.565 RIC ITM", "0454343", datetime(2026, 10, 26))], [])
    schede = {s["id_esterno"] for s in punteggi.schede_periodo(db, "2026-10-01", "2026-10-31")}
    assert schede == {"s537", "s565"}
    righe = {r["codice"]: r for r in punteggi.elenco_periodo(db, "2026-10-01", "2026-10-31")}
    assert (righe["367.537 CTER"]["protocollo"], righe["367.537 CTER"]["allegato_sol"]) == ("460242", False)
    assert righe["367.565 RIC ITM"]["protocollo"] == "454343"


def scorr(cognome, posizione, protocollo, data="2026-10-12T10:00:00Z"):
    c = candidato(cognome, "S", posizione)
    c["jconon_application:protocollo_numero_assunzione_idoneo"] = protocollo
    c["jconon_application:protocollo_data_assunzione_idoneo"] = data
    return c


def test_difformita_graduatoria(db, client_finto):
    """Punteggi mancanti, protocollo non valorizzato, esito mancante, protocollo e data diversi dalla graduatoria."""
    salva(db, "sol", [scheda("sol", "m", "367.611 RIC", "367.611", documenti=[doc("gm", "graduatoria", "200", "2026-10-05")]),
                      scheda("sol", "p", "367.612 RIC", "367.612", documenti=[doc("gp", "graduatoria", "396898", "2026-10-05")])])
    collegamento.collega(db)
    altro = candidato("Blu", "V", 1, protocollo="111")
    altro["jconon_application:protocollo_data_graduatoria"] = "2026-10-06T12:00:00Z"
    lista_p = [candidato("Rossi", "V", 1), candidato("Neri", "I", 2, protocollo=""), candidato("Gialli", None, 3), altro]
    client = client_finto(json_per_chiave=risposte({"m": (4, []), "p": (4, lista_p)}))
    punteggi.verifica(db, "2026-10-01", "2026-10-31", {"Cookie": "ticket=T"}, client=client)
    righe = {r["codice"]: r for r in punteggi.elenco_periodo(db, "2026-10-01", "2026-10-31")}
    assert righe["367.611 RIC"]["difformita"] == ["mancano i punteggi su SOL"]
    assert righe["367.611 RIC"]["url_punteggi"].endswith("/carica-punteggi?callId=m")
    d = righe["367.612 RIC"]["difformita"]
    assert "protocollo graduatoria non valorizzato su SOL (1 candidati)" in d
    assert "esito (V/I/S) mancante su SOL (1 candidati)" in d
    assert "protocollo graduatoria diverso su SOL (1 candidati)" in d
    assert "data protocollo graduatoria diversa su SOL (1 candidati)" in d


def test_scorrimenti_candidati_s(db, client_finto):
    """Candidati S: protocollo e data dell'assunzione idoneo confrontati con gli scorrimenti delle fonti."""
    from tests.test_atti import _carica_segreteria, _riga_scorr
    from datetime import datetime
    salva(db, "sol", [scheda("sol", "k", "367.620 CTER", "367.620",
                             documenti=[doc("g", "graduatoria", "300", "2026-03-01"), doc("s1", "scorrimento", "500", "2026-10-12")])])
    salva(db, "urp", [scheda("urp", "/node/9", "367.620 CTER", "367.620",
                             documenti=[doc("u1", "scorrimento", "600", "2026-10-20")])])
    collegamento.collega(db)
    _carica_segreteria(db, [], [], [_riga_scorr("367.620", "0000500", datetime(2026, 10, 12), "Scorrimento")])
    lista = [candidato("Rossi", "V", 1, protocollo="300"),
             scorr("Verdi", 2, "0000500"),                                  # torna con SOL e file
             scorr("Bianchi", 3, "500", data="2026-10-13T10:00:00Z"),        # data diversa
             scorr("Neri", 4, None),                                         # protocollo non valorizzato
             scorr("Gialli", 5, "700")]                                      # non presente nelle fonti
    for c in lista[:1]:
        c["jconon_application:protocollo_data_graduatoria"] = "2026-03-01T12:00:00Z"
    client = client_finto(json_per_chiave=risposte({"k": (5, lista)}))
    punteggi.verifica(db, "2026-10-01", "2026-10-31", {"Cookie": "ticket=T"}, client=client)
    r = punteggi.elenco_periodo(db, "2026-10-01", "2026-10-31")[0]
    d = r["difformita"]
    assert "protocollo assunzione idoneo non valorizzato su SOL (1 candidati S)" in d
    assert "scorrimento prot. 700 su SOL non presente nelle altre fonti (1 candidati S)" in d
    assert any(x.startswith("data assunzione idoneo prot. 500 diversa su SOL") for x in d)
    # lo scorrimento 600 di URP non ha nessun candidato S su SOL
    assert any(x.startswith("scorrimento prot. 600 del 20/10/2026 non registrato su SOL") for x in d)
    stati = {tuple(s["protocolli"]): s for s in r["scorrimenti"]}
    assert stati[("500",)]["registrato"] and stati[("500",)]["candidati"] == 2 and stati[("500",)]["fonti"] == ["segreteria", "sol"]
    assert stati[("600",)]["registrato"] is False

    # nella tabella degli atti: difformità nelle note, link ai punteggi di SOL
    from monitoraggio import atti
    righe = {(a["atto"], a["protocollo"]): a for a in atti.elenco_atti(db, "2026-10-01", "2026-10-31")}
    assert righe[("scorrimento", "600")]["note"][-1].startswith(
        "provvedimento di assunzione idoneo non presente tra gli allegati SOL")
    assert righe[("scorrimento", "600")]["difforme"]
    assert "data assunzione idoneo diversa su SOL" in righe[("scorrimento", "500")]["note"]
    assert righe[("scorrimento", "500")]["url_punteggi"].endswith("callId=k")
    dump = "\n".join(db.iterdump())
    assert "Verdi" not in dump and "XXXXXX00X00X000X" not in dump
