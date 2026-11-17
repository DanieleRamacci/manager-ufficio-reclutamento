"""Avviso automatico agli RdP per ogni nuovo scorrimento (spec 009, US6)."""
import pytest

from monitoraggio import atti, attivita, avvisi_scorrimenti as av, posta

URL = "https://www.urp.cnr.it/doc/scorrimento.pdf"


def _scorrimento(codice="380.12", protocollo="0012345", data="2026-11-10", rdp=("anna@cnr.it",), urp=atti.PRESENTE, seg=atti.PRESENTE,
                 tipologia="tempo_indeterminato", atto="scorrimento"):
    return {"atto": atto, "numero_bando": codice, "codice": codice, "bando_id": 1, "titolo_bando": "Bando di prova", "tipologia": tipologia,
            "protocollo": protocollo, "data": data, "rdp": [{"email": e, "nome": "Anna", "cognome": "Neri"} for e in rdp],
            "fonti": {"urp": {"stato": urp, "url": URL}, "segreteria": {"stato": seg}, "sol": {"stato": atti.MANCANTE}}}


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
    assert av.esegui()[0] == "ok" and inviati == []  # già registrato: niente email nemmeno dopo


def test_nuovo_scorrimento_avvisa_gli_rdp_una_volta_con_la_segreteria_in_copia(ambiente):
    righe, inviati = ambiente
    av.esegui()  # prima esecuzione, nessuno scorrimento
    av.salva_copia("Segreteria@cnr.it", "admin")
    righe.append(_scorrimento(rdp=("anna@cnr.it", "esterno@altroente.it")))
    assert av.esegui() == ("ok", "1 avvisi inviati")
    # solo l'RdP interno all'ufficio, non quello esterno
    assert len(inviati) == 1 and inviati[0]["a"] == ["anna@cnr.it"] and inviati[0]["cc"] == ["segreteria@cnr.it"]
    assert URL in inviati[0]["corpo"] and "380.12" in inviati[0]["oggetto"] and "10/11/2026" in inviati[0]["oggetto"]
    assert "verificare che lo scorrimento sia corretto" in inviati[0]["corpo"] and "richiederlo a chi si è occupato" in inviati[0]["corpo"]
    av.esegui()
    assert len(inviati) == 1  # una volta sola
    voce = av.stato()["avvisi"][0]
    assert voce["esito"] == "inviato" and voce["destinatari"] == ["anna@cnr.it"]


def test_serve_la_presenza_su_urp_e_nel_file_della_segreteria(ambiente):
    righe, inviati = ambiente
    av.esegui()
    righe += [_scorrimento(protocollo="1", seg=atti.MANCANTE), _scorrimento(protocollo="2", urp=atti.MANCANTE),
              _scorrimento(protocollo="3", tipologia="categorie_protette"), _scorrimento(protocollo="4", atto="graduatoria")]
    av.esegui()
    assert inviati == []
    righe[0]["fonti"]["segreteria"]["stato"] = atti.PRESENTE  # compare anche nel file
    av.esegui()
    assert len(inviati) == 1


def test_senza_rdp_e_invio_non_riuscito_restano_registrati(ambiente):
    righe, inviati = ambiente
    av.esegui()
    righe += [_scorrimento(protocollo="1", rdp=()), _scorrimento(protocollo="2", rdp=("errore@cnr.it",))]
    esito, dettaglio = av.esegui()
    assert esito == "errore" and "1 senza RdP dell'ufficio" in dettaglio and "1 non inviati" in dettaglio
    esiti = {a["protocollo"]: a for a in av.stato()["avvisi"]}
    assert esiti["1"]["esito"] == "senza_destinatari" and esiti["2"]["esito"] == "errore" and esiti["2"]["messaggio"]
    righe[1]["rdp"] = [{"email": "anna@cnr.it"}]  # corretto: al giro dopo si ritenta
    av.esegui()
    esiti = {a["protocollo"]: a for a in av.stato()["avvisi"]}
    assert esiti["2"]["esito"] == "inviato" and esiti["2"]["tentativi"] == 2 and len(inviati) == 1


def test_copia_non_valida_rifiutata(db):
    with pytest.raises(ValueError):
        av.salva_copia("non-una-email", "admin")


def test_attivita_disattivata_finche_non_la_si_attiva(db):
    voce = next(a for a in attivita.elenco() if a["chiave"] == "scorrimenti")
    assert voce["attiva"] is False


def test_solo_rdp_dell_ufficio_e_nessuna_email_con_elenco_vuoto(ambiente):
    righe, inviati = ambiente
    av.esegui()
    righe.append(_scorrimento(rdp=("esterno@altroente.it",)))
    assert av.esegui() == ("avviso", "0 avvisi inviati, 1 senza RdP dell'ufficio")
    assert inviati == [] and av.stato()["avvisi"][0]["messaggio"] == "Nessuno degli RdP fa parte dell'ufficio"
    assert av.esegui() == ("ok", "0 avvisi inviati")  # non si ripete ogni notte
    av.salva({"interni": "anna@cnr.it, esterno@altroente.it"}, "admin")  # entra nell'elenco: riceve lo scorrimento recente
    av.esegui()
    assert [x["a"] for x in inviati] == [["esterno@altroente.it"]]
    av.salva({"interni": ""}, "admin")
    righe.append(_scorrimento(protocollo="9"))
    assert av.esegui() == ("avviso", "Nessuna email inviata: l'elenco delle persone dell'ufficio è vuoto") and len(inviati) == 1


def test_elenco_dell_ufficio_rifiuta_indirizzi_non_validi(db):
    with pytest.raises(ValueError):
        av.salva({"interni": "anna@cnr.it\nnon valida"}, "admin")
    av.salva({"interni": "Anna@CNR.it\nbruno@cnr.it, anna@cnr.it"}, "admin")
    assert av.interni() == ["anna@cnr.it", "bruno@cnr.it"]
