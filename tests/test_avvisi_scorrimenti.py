"""Avviso automatico agli RdP per ogni nuovo scorrimento pubblicato (spec 009, US6): solo lo scorrimento, non le difformità."""
import pytest

from monitoraggio import atti, attivita, avvisi_scorrimenti as av, posta

URL = "https://www.urp.cnr.it/doc/scorrimento.pdf"


def _scorrimento(codice="380.12", protocollo="0012345", data="2026-11-10", rdp=("anna@cnr.it",), urp=atti.PRESENTE,
                 seg=atti.PRESENTE, sol=atti.MANCANTE, atto="scorrimento", tipologia="tempo_indeterminato"):
    return {"atto": atto, "numero_bando": codice, "codice": codice, "bando_id": 1, "titolo_bando": "Bando di prova",
            "tipologia": tipologia, "protocollo": protocollo, "data": data, "note": ["una difformità"], "difforme": True,
            "rdp": [{"email": e, "nome": "Anna", "cognome": "Neri"} for e in rdp],
            "fonti": {"urp": {"stato": urp, "url": URL}, "segreteria": {"stato": seg}, "sol": {"stato": sol}}}


@pytest.fixture
def ambiente(db, monkeypatch):
    righe, inviati = [], []
    monkeypatch.setattr(atti, "elenco_atti", lambda conn, *a, **k: righe)
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
    righe.append(_scorrimento())
    esito, dettaglio = av.esegui()
    assert esito == "ok" and "1 scorrimenti già presenti" in dettaglio and inviati == []
    av.esegui()
    assert inviati == []


def test_nuovo_scorrimento_avvisa_gli_rdp_dell_ufficio_una_volta(ambiente):
    righe, inviati = ambiente
    av.esegui()  # attivazione
    av.salva_copia("Segreteria@cnr.it", "admin")
    r = _scorrimento(rdp=("anna@cnr.it", "esterno@altroente.it"))
    righe.append(r)
    assert av.esegui() == ("ok", "1 avvisi inviati")
    e = inviati[0]
    assert e["a"] == ["anna@cnr.it"] and e["cc"] == ["segreteria@cnr.it"]  # l'RdP esterno no
    assert "dal file di riepilogo della segreteria e da URP la pubblicazione di uno scorrimento" in e["corpo"]
    assert URL in e["corpo"] and "380.12" in e["oggetto"] and "10/11/2026" in e["corpo"] and "prot. 0012345" in e["corpo"]
    assert "Se lo scorrimento non vi è stato notificato" in e["corpo"] and "richiedere il provvedimento di scorrimento" in e["corpo"]
    assert "difformità" not in e["corpo"].lower()  # le difformità restano nell'email manuale
    r["note"] = ["altra difformità"]
    for _ in range(3):
        av.esegui()
    assert len(inviati) == 1  # una volta sola, anche se cambiano le difformità
    voce = av.stato()["avvisi"][0]
    assert voce["esito"] == "inviato" and voce["destinatari"] == ["anna@cnr.it"]


def test_dice_da_quale_fonte_e_mette_il_link_solo_se_su_urp(ambiente):
    righe, inviati = ambiente
    av.esegui()
    righe += [_scorrimento(protocollo="1", urp=atti.MANCANTE), _scorrimento(protocollo="2", seg=atti.MANCANTE),
              _scorrimento(protocollo="3", urp=atti.MANCANTE, seg=atti.MANCANTE), _scorrimento(protocollo="4", atto="graduatoria"),
              _scorrimento(protocollo="5", tipologia="categorie_protette")]
    av.esegui()
    corpi = {x["corpo"].split("prot. ")[1].split(".")[0]: x["corpo"] for x in inviati}
    assert set(corpi) == {"1", "2"}
    assert "abbiamo rilevato dal file di riepilogo della segreteria la pubblicazione" in corpi["1"] and URL not in corpi["1"]
    assert "abbiamo rilevato da URP la pubblicazione" in corpi["2"] and URL in corpi["2"]


def test_senza_rdp_dell_ufficio_errore_e_ritentativo(ambiente):
    righe, inviati = ambiente
    av.esegui()
    righe += [_scorrimento(protocollo="1", rdp=("esterno@altroente.it",)), _scorrimento(protocollo="2", rdp=("errore@cnr.it",))]
    esito, dettaglio = av.esegui()
    assert esito == "errore" and dettaglio == "0 avvisi inviati, 1 senza RdP dell'ufficio, 1 non inviati"
    esiti = {a["protocollo"]: a for a in av.stato()["avvisi"]}
    assert esiti["1"]["messaggio"] == "Nessuno degli RdP fa parte dell'ufficio" and esiti["2"]["esito"] == "errore"
    assert av.esegui()[1] == "0 avvisi inviati, 1 non inviati"  # si ritenta solo l'errore
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
