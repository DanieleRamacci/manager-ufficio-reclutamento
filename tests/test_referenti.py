"""Referenti RdP da Selezioni Online (spec 003). Persone inventate."""
import pytest

from monitoraggio import collegamento, referenti
from monitoraggio.fonti import sol_rdp
from monitoraggio.fonti.http import FonteErrore
from tests.test_collegamento import salva, scheda


def persona(nome, cognome, user):
    return {"firstName": nome, "lastName": cognome, "userName": user, "email": f"{user}@cnr.it",
            "codicefiscale": "XXXXXX00X00X000X", "matricola": 12345, "emailesterno": f"{user}@esempio.it",
            "emailcertificatoperpuk": f"{user}@pec.esempio.it"}


def bando(object_id, codice, rdps):
    return {"cmis:objectId": object_id, "cmis:objectTypeId": "F:jconon_call_tind:folder_concorsi_pubblici",
            "jconon_call:codice": codice, "rdps": rdps}


def risposte(pagine):
    """pagine: lista di liste di item; restituisce la funzione per il client finto."""
    def risposta(url, params):
        n = int(params["page"])
        items = pagine[n] if n < len(pagine) else []
        return {"items": items, "page": n, "offset": int(params["offset"]), "count": sum(map(len, pagine)),
                "hasMoreItems": n < len(pagine) - 1}
    return risposta


def test_paginazione_e_token(client_finto, monkeypatch):
    monkeypatch.setattr(sol_rdp, "PAGINA", 2)
    client = client_finto(json_per_chiave=risposte([[bando("a", "1", []), bando("b", "2", [])], [bando("c", "3", [])]]))
    items = sol_rdp.bandi_con_rdp(client, "TOKEN")
    assert [i["cmis:objectId"] for i in items] == ["a", "b", "c"]
    assert all(h["Authorization"] == "Bearer TOKEN" for h in client.header)
    assert client.richieste[0][1]["detailRdP"] == "true" and client.richieste[0][1]["filterType"] == "all"


def test_solo_campi_ammessi():
    p = sol_rdp.persona(persona("Anna", "Esempio", "anna.esempio"))
    assert p == {"chiave": "anna.esempio", "nome": "Anna", "cognome": "Esempio", "email": "anna.esempio@cnr.it",
                 "username": "anna.esempio"}


def _schede_sol(db):
    salva(db, "sol", [scheda("sol", "obj-1", "367.601 FA ISTC", "367.601"),
                      scheda("sol", "obj-2", "367.602 RIC", "367.602")])
    collegamento.collega(db)


def per_codice(mappa):
    """Risposte per callCode: mappa codice -> lista di RdP, oppure un'eccezione."""
    def risposta(url, params):
        valore = mappa.get(params.get("callCode"), [])
        if isinstance(valore, Exception):
            return valore
        oggetto = {"367.601 FA ISTC": "obj-1", "367.602 RIC": "obj-2"}.get(params["callCode"], "altro")
        return {"items": [bando(oggetto, params["callCode"], valore)], "hasMoreItems": False}
    return risposta


ANNA, LUCA = persona("Anna", "Esempio", "anna.esempio"), persona("Luca", "Prova", "luca.prova")


def test_aggiorna_bando_per_bando(db, client_finto):
    _schede_sol(db)
    client = client_finto(json_per_chiave=per_codice({"367.601 FA ISTC": [ANNA, LUCA], "367.602 RIC": []}))
    r = referenti.aggiorna(db, "TOKEN", "utente@cnr.it", client=client)
    assert (r["esito"], r["bandi"], r["referenti"]) == ("completato", 2, 2)
    assert sorted(p["callCode"] for _, p in client.richieste) == ["367.601 FA ISTC", "367.602 RIC"]
    assert all(p["detailRdP"] == "true" for _, p in client.richieste)
    assert all(h["Authorization"] == "Bearer TOKEN" for h in client.header)
    per_bando = referenti.referenti_per_bando(db)
    bando_id = db.execute("SELECT bando_id FROM scheda WHERE id_esterno = 'obj-1'").fetchone()[0]
    assert [x["email"] for x in per_bando[bando_id]] == ["anna.esempio@cnr.it", "luca.prova@cnr.it"]
    # nessun dato non necessario nel database
    dump = "\n".join(db.iterdump())
    for vietato in ("XXXXXX00X00X000X", "12345", "@esempio.it"):
        assert vietato not in dump


def test_solo_bandi_attivi(db, client_finto):
    salva(db, "sol", [scheda("sol", "obj-1", "367.601 FA ISTC", "367.601"),
                      scheda("sol", "vecchio", "367.10 RIC", "367.10", data="2016-02-18")])
    collegamento.collega(db)
    client = client_finto(json_per_chiave=per_codice({"367.601 FA ISTC": [ANNA]}))
    referenti.aggiorna(db, "T", "u", client=client)
    assert [p["callCode"] for _, p in client.richieste] == ["367.601 FA ISTC"]


def test_errore_su_un_bando_non_blocca(db, client_finto):
    _schede_sol(db)
    client = client_finto(json_per_chiave=per_codice({"367.601 FA ISTC": [ANNA],
                                                      "367.602 RIC": FonteErrore("ReadTimeout su selezionionline")}))
    r = referenti.aggiorna(db, "T", "u", client=client)
    assert (r["esito"], r["bandi"]) == ("completato", 1)
    assert "1 bandi non letti: 367.602 RIC" in r["messaggio"]


def test_cambio_rdp(db, client_finto):
    _schede_sol(db)
    primo = client_finto(json_per_chiave=per_codice({"367.601 FA ISTC": [ANNA]}))
    referenti.aggiorna(db, "T", "u", client=primo)
    secondo = client_finto(json_per_chiave=per_codice({"367.601 FA ISTC": [LUCA]}))
    referenti.aggiorna(db, "T", "u", client=secondo)
    righe = {r["username"]: r["attivo"] for r in db.execute("SELECT username, attivo FROM referente")}
    assert righe == {"anna.esempio": 0, "luca.prova": 1}
    referenti.aggiorna(db, "T", "u", client=primo)
    righe = {r["username"]: r["attivo"] for r in db.execute("SELECT username, attivo FROM referente")}
    assert righe == {"anna.esempio": 1, "luca.prova": 0}


def test_accesso_negato_ferma_e_non_modifica(db, client_finto):
    _schede_sol(db)
    referenti.aggiorna(db, "T", "u", client=client_finto(json_per_chiave=per_codice({"367.601 FA ISTC": [ANNA]})))
    rotto = client_finto(json_per_chiave=lambda url, params: FonteErrore("HTTP 401 da selezionionline"))
    r = referenti.aggiorna(db, "T", "u", client=rotto)
    assert r["esito"] == "fallito" and "401" in r["messaggio"]
    assert len(rotto.richieste) == 1  # si ferma alla prima risposta 401
    assert db.execute("SELECT COUNT(*) FROM referente WHERE attivo = 1").fetchone()[0] == 1


def test_aggiornamento_concorrente_rifiutato(db):
    db.execute("INSERT INTO referenti_aggiornamento (utente, inizio, esito) VALUES ('u', '2999-01-01', 'in_corso')")
    with pytest.raises(referenti.AggiornamentoInCorso):
        referenti.aggiorna(db, "T", "u", client=object())


def test_senza_token_solo_se_attivato(db, client_finto, monkeypatch):
    _schede_sol(db)
    client = client_finto(json_per_chiave=per_codice({"367.601 FA ISTC": [ANNA]}))
    monkeypatch.delenv("RDP_SENZA_TOKEN", raising=False)
    with pytest.raises(ValueError):
        referenti.aggiorna(db, None, "u", client=client)
    monkeypatch.setenv("RDP_SENZA_TOKEN", "1")
    r = referenti.aggiorna(db, None, "u", client=client)
    assert r["esito"] == "completato" and r["utente"] == "u (senza token)"
    assert all("Authorization" not in h for h in client.header)


def test_senza_token_rifiutato_dalla_fonte(db, client_finto, monkeypatch):
    _schede_sol(db)
    monkeypatch.setenv("RDP_SENZA_TOKEN", "1")
    client = client_finto(json_per_chiave=lambda url, params: FonteErrore("HTTP 401 da selezionionline"))
    r = referenti.aggiorna(db, None, "u", client=client)
    assert r["esito"] == "fallito" and "serve l'accesso SSO" in r["messaggio"]
