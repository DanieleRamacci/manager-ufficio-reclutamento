import pytest

from monitoraggio import raccolta
from monitoraggio.fonti import urp
from monitoraggio.fonti.http import FonteErrore


def documento(id_esterno, titolo, categoria="graduatoria", protocollo="100", url=None):
    return {"id_esterno": id_esterno, "titolo": titolo, "categoria": categoria, "sottotipo": None,
            "sottotipo_ordinale": None, "sottotipo_origine": None, "tipo_fonte": None,
            "protocollo": protocollo, "protocollo_originale": protocollo, "data_protocollo": "2026-02-01",
            "url": url or f"https://www.urp.cnr.it/system/files?file={id_esterno}"}


def scheda(nodo, documenti, titolo="Bando"):
    return {"id_esterno": f"/node/{nodo}", "sezione": "tempo-indeterminato", "tipologia": "tempo_indeterminato",
            "codice_originale": f"367.{nodo} RIC", "codice_norm": f"367.{nodo}RIC", "numero_bando": f"367.{nodo}",
            "codice_sotto": None, "titolo": titolo, "protocollo": "1", "protocollo_originale": "1",
            "data_pubblicazione": "2026-01-10", "data_pubbl_graduatoria": None,
            "url": f"https://www.urp.cnr.it/node/{nodo}", "dati_extra": None, "modificata_fonte_il": None,
            "documenti": documenti}


class FontiFinte:
    """Sostituisce elenco e dettaglio URP con dati in memoria."""

    def __init__(self, monkeypatch, schede, errori=None, elenco_errore=None):
        self.schede = {s["url"]: s for s in schede}
        self.errori = errori or set()
        self.elenco_errore = elenco_errore
        monkeypatch.setattr(raccolta.config, "urp_sezioni", lambda: ["tempo-indeterminato"])
        monkeypatch.setattr(raccolta.config, "urp_sezioni_pagine", lambda: ["tempo-indeterminato"])
        monkeypatch.setattr(raccolta.config, "controllo_pdf", lambda: False)
        monkeypatch.setattr(urp, "elenco_sezione", self.elenco)
        monkeypatch.setattr(urp, "dettaglio_bando", self.dettaglio)

    def elenco(self, client, sezione):
        if self.elenco_errore:
            raise self.elenco_errore
        return list(self.schede) + list(self.errori), len(self.schede) + len(self.errori)

    def dettaglio(self, client, url, sezione):
        if url in self.errori:
            raise FonteErrore(f"HTTP 500 da {url}")
        return self.schede[url]


def conta(db, tabella, where="1=1"):
    return db.execute(f"SELECT COUNT(*) FROM {tabella} WHERE {where}").fetchone()[0]


def test_prima_raccolta_inserisce(db, monkeypatch):
    FontiFinte(monkeypatch, [scheda(1, [documento("a", "Graduatoria")]), scheda(2, [])])
    r = raccolta.raccogli(db, "urp", client=object())
    assert r["esito"] == "completata"
    assert (r["bandi_trovati"], r["documenti_trovati"]) == (2, 1)
    assert conta(db, "scheda") == 2 and conta(db, "documento") == 1


def test_seconda_raccolta_non_duplica(db, monkeypatch):
    FontiFinte(monkeypatch, [scheda(1, [documento("a", "Graduatoria")])])
    raccolta.raccogli(db, "urp", client=object())
    prima = db.execute("SELECT prima_rilevazione FROM documento").fetchone()[0]
    r = raccolta.raccogli(db, "urp", client=object())
    assert (r["nuovi"], r["aggiornati"]) == (0, 0)
    assert conta(db, "scheda") == 1 and conta(db, "documento") == 1
    assert db.execute("SELECT prima_rilevazione FROM documento").fetchone()[0] == prima


def test_modifica_conta_come_aggiornato(db, monkeypatch):
    FontiFinte(monkeypatch, [scheda(1, [documento("a", "Graduatoria")])])
    raccolta.raccogli(db, "urp", client=object())
    FontiFinte(monkeypatch, [scheda(1, [documento("a", "Graduatoria", protocollo="200")])])
    r = raccolta.raccogli(db, "urp", client=object())
    assert r["aggiornati"] == 1
    assert db.execute("SELECT protocollo FROM documento").fetchone()[0] == "200"


def test_documento_sparito_non_cancellato(db, monkeypatch):
    FontiFinte(monkeypatch, [scheda(1, [documento("a", "Graduatoria"), documento("b", "Scorrimento")])])
    raccolta.raccogli(db, "urp", client=object())
    FontiFinte(monkeypatch, [scheda(1, [documento("a", "Graduatoria")])])
    raccolta.raccogli(db, "urp", client=object())
    assert conta(db, "documento") == 2
    assert conta(db, "documento", "id_esterno = 'b' AND presente = 0") == 1
    assert conta(db, "documento", "id_esterno = 'a' AND presente = 1") == 1


def test_fallita_non_modifica_i_dati(db, monkeypatch):
    FontiFinte(monkeypatch, [scheda(1, [documento("a", "Graduatoria")])])
    raccolta.raccogli(db, "urp", client=object())
    FontiFinte(monkeypatch, [], elenco_errore=FonteErrore("Elenco vuoto per tempo-indeterminato"))
    r = raccolta.raccogli(db, "urp", client=object())
    assert r["esito"] == "fallita" and "Elenco vuoto" in r["messaggio"]
    assert conta(db, "scheda", "presente = 1") == 1 and conta(db, "documento", "presente = 1") == 1


def test_bando_non_leggibile_completata_con_errori(db, monkeypatch):
    FontiFinte(monkeypatch, [scheda(1, [])], errori={"https://www.urp.cnr.it/node/99"})
    r = raccolta.raccogli(db, "urp", client=object())
    assert r["esito"] == "completata_con_errori"
    errori = db.execute("SELECT riferimento, messaggio FROM raccolta_errore").fetchall()
    assert [tuple(e) for e in errori] == [("https://www.urp.cnr.it/node/99", "HTTP 500 da https://www.urp.cnr.it/node/99")]


def test_stato_per_fonte(db, monkeypatch):
    FontiFinte(monkeypatch, [scheda(1, [])])
    raccolta.raccogli(db, "urp", client=object())
    FontiFinte(monkeypatch, [], elenco_errore=FonteErrore("URP non raggiungibile"))
    raccolta.raccogli(db, "urp", client=object())
    s = raccolta.stato(db)
    assert s["urp"]["ultima"]["esito"] == "fallita"
    assert s["urp"]["ultima"]["messaggio"] == "URP non raggiungibile"
    assert s["urp"]["ultima_riuscita"]["esito"] == "completata"
    assert s["urp"]["in_corso"] is None
    assert s["sol"] == {"ultima": None, "ultima_riuscita": None, "in_corso": None}


def test_errori_della_raccolta(db, monkeypatch):
    FontiFinte(monkeypatch, [scheda(1, [])], errori={"https://www.urp.cnr.it/node/99"})
    r = raccolta.raccogli(db, "urp", client=object())
    assert raccolta.errori(db, r["id"]) == [
        {"riferimento": "https://www.urp.cnr.it/node/99", "messaggio": "HTTP 500 da https://www.urp.cnr.it/node/99"}]


def test_riclassifica(db, monkeypatch):
    FontiFinte(monkeypatch, [scheda(1, [documento("a", "Modifica graduatoria cod. 07", categoria="graduatoria")])])
    raccolta.raccogli(db, "urp", client=object())
    assert raccolta.riclassifica(db) == 1
    assert db.execute("SELECT categoria FROM documento").fetchone()[0] == "rettifica"
    assert raccolta.riclassifica(db) == 0


def test_raccolta_concorrente_rifiutata(db):
    raccolta.avvia(db, "urp", "manuale", "test")
    with pytest.raises(raccolta.RaccoltaInCorso):
        raccolta.avvia(db, "urp", "manuale", "test")
    # un'altra fonte può partire
    raccolta.avvia(db, "sol", "manuale", "test")


def test_lock_scaduto_viene_liberato(db):
    db.execute("INSERT INTO raccolta (fonte, modalita, inizio, esito) VALUES ('urp', 'manuale', '2000-01-01T00:00:00Z', 'in_corso')")
    raccolta.avvia(db, "urp", "manuale", "test")
    assert conta(db, "raccolta", "esito = 'fallita' AND messaggio LIKE 'Interrotta%'") == 1


def test_archivio_irraggiungibile_non_cancella_i_bandi(db, monkeypatch):
    from monitoraggio.fonti import urp
    from monitoraggio.fonti.http import FonteErrore
    from tests.test_collegamento import ORA, scheda
    monkeypatch.setattr(raccolta.config, "urp_sezioni", lambda: [])
    salvata = scheda("urp", "/vecchio.pdf", "X 1", None, tipologia=None, sezione="archivio-vecchio")
    raccolta.scrivi(db, "urp", [salvata], ["/vecchio.pdf"], ORA)

    def fallisce(client):
        raise FonteErrore("HTTP 404")
    monkeypatch.setattr(urp, "elenco_archivio", fallisce)
    schede, ids, errori, _ = raccolta._leggi_urp(db, None)
    assert schede == [] and ids == ["/vecchio.pdf"] and errori == [("archivio-vecchio", "HTTP 404")]
