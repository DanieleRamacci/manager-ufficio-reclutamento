"""Avviso automatico agli RdP per ogni nuovo scorrimento e per le sue nuove difformità (spec 009, US6)."""
import pytest

from monitoraggio import atti, attivita, avvisi_scorrimenti as av, difformita, posta

URL = "https://www.urp.cnr.it/doc/scorrimento.pdf"


def _scorrimento(codice="380.12", protocollo="0012345", data="2026-11-10", rdp=("anna@cnr.it",), urp=atti.PRESENTE,
                 seg=atti.PRESENTE, sol=atti.PRESENTE, atto="scorrimento"):
    fonti = {"urp": {"stato": urp, "url": URL}, "segreteria": {"stato": seg}, "sol": {"stato": sol}}
    return {"atto": atto, "numero_bando": codice, "codice": codice, "bando_id": 1, "titolo_bando": "Bando di prova",
            "tipologia": "tempo_indeterminato", "protocollo": protocollo, "data": data, "note": [],
            "difforme": atti.MANCANTE in (urp, seg, sol),
            "rdp": [{"email": e, "nome": "Anna", "cognome": "Neri"} for e in rdp], "fonti": fonti}


def _aggiorna_difforme(r):
    r["difforme"] = bool(r["note"]) or any(f["stato"] == atti.MANCANTE for f in r["fonti"].values())


@pytest.fixture
def ambiente(db, monkeypatch):
    righe, inviati = [], []
    monkeypatch.setattr(difformita, "righe_correnti", lambda conn, *a, **k: righe)
    monkeypatch.setattr(atti, "fonti_in_attesa", lambda conn: [])
    monkeypatch.setattr(posta, "configurata", lambda: True)

    def invia(destinatari, oggetto, corpo, cc=None, **k):
        if "errore@cnr.it" in destinatari:
            raise posta.PostaErrore("Il server di posta non ha accettato l'email")
        inviati.append({"a": destinatari, "oggetto": oggetto, "corpo": corpo, "cc": cc})
        return False
    monkeypatch.setattr(posta, "invia", invia)
    av.salva({"interni": "anna@cnr.it\nerrore@cnr.it"}, "admin")
    return righe, inviati


def test_prima_esecuzione_registra_gli_esistenti_senza_email(ambiente):
    righe, inviati = ambiente
    righe.append(_scorrimento(sol=atti.MANCANTE))
    esito, dettaglio = av.esegui()
    assert esito == "ok" and "1 scorrimenti già presenti" in dettaglio and inviati == []
    av.esegui()
    assert inviati == []  # già registrato con le sue difformità: niente email nemmeno dopo


def test_nuovo_scorrimento_con_le_sue_difformita_agli_rdp_dell_ufficio(ambiente):
    righe, inviati = ambiente
    av.esegui()  # attivazione, nessuno scorrimento
    av.salva_copia("Segreteria@cnr.it", "admin")
    righe.append(_scorrimento(rdp=("anna@cnr.it", "esterno@altroente.it"), sol=atti.MANCANTE))
    assert av.esegui() == ("ok", "1 nuovi scorrimenti avvisati, 0 avvisi di nuove difformità")
    e = inviati[0]
    assert e["a"] == ["anna@cnr.it"] and e["cc"] == ["segreteria@cnr.it"]  # l'RdP esterno no
    assert URL in e["corpo"] and "380.12" in e["oggetto"] and "10/11/2026" in e["oggetto"]
    assert "Selezioni Online" in e["corpo"] and "risultano queste difformità" in e["corpo"]
    assert "verificare che lo scorrimento sia corretto" in e["corpo"] and "richiederlo a chi si è occupato" in e["corpo"]
    for _ in range(3):
        av.esegui()
    assert len(inviati) == 1  # mai due volte la stessa cosa
    voce = av.stato()["avvisi"][0]
    assert voce["evento"] == "nuovo" and voce["esito"] == "inviato" and voce["destinatari"] == ["anna@cnr.it"] and voce["rilievi"]


def test_basta_una_fonte_tra_segreteria_e_urp(ambiente):
    righe, inviati = ambiente
    av.esegui()
    righe += [_scorrimento(protocollo="1", urp=atti.MANCANTE), _scorrimento(protocollo="2", seg=atti.MANCANTE),
              _scorrimento(protocollo="3", urp=atti.MANCANTE, seg=atti.MANCANTE), _scorrimento(protocollo="4", atto="graduatoria")]
    av.esegui()
    assert len(inviati) == 2 and all("prot." in x["corpo"] for x in inviati)


def test_nuova_difformita_su_uno_scorrimento_gia_avvisato(ambiente):
    righe, inviati = ambiente
    av.esegui()
    r = _scorrimento()
    righe.append(r)
    av.esegui()
    assert len(inviati) == 1 and "difformità" not in inviati[0]["oggetto"]
    r["fonti"]["sol"]["stato"] = atti.MANCANTE  # sparisce da SOL: difformità nuova
    _aggiorna_difforme(r)
    assert av.esegui() == ("ok", "0 nuovi scorrimenti avvisati, 1 avvisi di nuove difformità")
    assert "nuove difformità" in inviati[1]["oggetto"] and "Selezioni Online" in inviati[1]["corpo"]
    av.esegui()
    assert len(inviati) == 2  # la stessa difformità non si ripete
    r["fonti"]["sol"]["stato"] = atti.PRESENTE  # corretta: nessuna email
    _aggiorna_difforme(r)
    av.esegui()
    assert len(inviati) == 2
    assert [x["evento"] for x in av.stato()["avvisi"]] == ["difformita", "nuovo"]


def test_nuova_difformita_anche_sugli_scorrimenti_gia_presenti_all_attivazione(ambiente):
    righe, inviati = ambiente
    r = _scorrimento()
    righe.append(r)
    av.esegui()  # attivazione: registrato senza email
    r["note"] = ["protocollo diverso: URP 1, file 2"]
    _aggiorna_difforme(r)
    av.esegui()
    assert len(inviati) == 1 and "nuove difformità" in inviati[0]["oggetto"] and "protocollo diverso" in inviati[0]["corpo"]


def test_errore_su_una_difformita_non_ripete_l_annuncio(ambiente):
    righe, inviati = ambiente
    r = _scorrimento(rdp=("errore@cnr.it",))
    righe.append(r)
    av.esegui()  # attivazione
    r["note"] = ["nota nuova"]
    _aggiorna_difforme(r)
    assert av.esegui()[0] == "errore"
    r["rdp"] = [{"email": "anna@cnr.it"}]
    av.esegui()
    assert len(inviati) == 1 and "nuove difformità" in inviati[0]["oggetto"]  # si ritenta la difformità, non l'annuncio


def test_senza_rdp_dell_ufficio_errore_e_ritentativo(ambiente):
    righe, inviati = ambiente
    av.esegui()
    righe += [_scorrimento(protocollo="1", rdp=("esterno@altroente.it",)), _scorrimento(protocollo="2", rdp=("errore@cnr.it",))]
    esito, dettaglio = av.esegui()
    assert esito == "errore" and "1 senza RdP dell'ufficio" in dettaglio and "1 non inviati" in dettaglio
    esiti = {a["protocollo"]: a for a in av.stato()["avvisi"]}
    assert esiti["1"]["messaggio"] == "Nessuno degli RdP fa parte dell'ufficio" and esiti["2"]["esito"] == "errore"
    assert av.esegui()[1] == "0 nuovi scorrimenti avvisati, 0 avvisi di nuove difformità, 1 non inviati"  # si ritenta solo l'errore
    righe[1]["rdp"] = [{"email": "anna@cnr.it"}]
    av.esegui()
    assert len(inviati) == 1 and inviati[0]["a"] == ["anna@cnr.it"]
    av.salva({"interni": "anna@cnr.it, esterno@altroente.it"}, "admin")  # entra nell'elenco: riceve lo scorrimento recente
    av.esegui()
    assert [x["a"] for x in inviati] == [["anna@cnr.it"], ["esterno@altroente.it"]]
    av.esegui()
    assert len(inviati) == 2


def test_elenco_vuoto_nessuna_email(ambiente):
    righe, inviati = ambiente
    av.esegui()
    av.salva({"interni": ""}, "admin")
    righe.append(_scorrimento())
    assert av.esegui() == ("avviso", "Nessuna email inviata: l'elenco delle persone dell'ufficio è vuoto") and inviati == []


def test_elenco_dell_ufficio_rifiuta_indirizzi_non_validi(db):
    with pytest.raises(ValueError):
        av.salva({"interni": "anna@cnr.it\nnon valida"}, "admin")
    av.salva({"interni": "Anna@CNR.it\nbruno@cnr.it, anna@cnr.it"}, "admin")
    assert av.interni() == ["anna@cnr.it", "bruno@cnr.it"]
    with pytest.raises(ValueError):
        av.salva_copia("non-una-email", "admin")


def test_attivita_disattivata_finche_non_la_si_attiva(db):
    voce = next(a for a in attivita.elenco() if a["chiave"] == "scorrimenti")
    assert voce["attiva"] is False
