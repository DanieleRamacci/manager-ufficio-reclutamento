import pytest

from monitoraggio import config
from monitoraggio.fonti import urp
from monitoraggio.fonti.http import FonteErrore


def leggi(fixture_path, nome):
    return fixture_path(f"urp/{nome}").read_text(encoding="utf-8")


def test_parse_elenco(fixture_path):
    links, corrente, totale = urp.parse_elenco(leggi(fixture_path, "elenco_categorie-riservatarie_p0.html"))
    assert (corrente, totale) == (10, 13)
    assert len(links) == 10
    assert all(link.startswith("https://www.urp.cnr.it/node/") for link in links)


def test_parse_elenco_vuoto(fixture_path):
    links, _, totale = urp.parse_elenco(leggi(fixture_path, "elenco_vuoto.html"))
    assert links == [] and totale == 13


def test_url_pagina_ordinata_per_titolo():
    url = urp.url_pagina("tempo-indeterminato", 3)
    assert url == f"{config.urp_url_sezione('tempo-indeterminato')}?order=title&sort=asc&page=3"


def test_elenco_sezione_segue_le_pagine(fixture_path, client_finto):
    client = client_finto(testi={
        urp.url_pagina("categorie-riservatarie", 0): leggi(fixture_path, "elenco_categorie-riservatarie_p0.html"),
        urp.url_pagina("categorie-riservatarie", 1): leggi(fixture_path, "elenco_categorie-riservatarie_p1.html"),
    })
    links, totale = urp.elenco_sezione(client, "categorie-riservatarie")
    assert totale == 13
    assert len(links) == 13 == len(set(links))


def test_elenco_sezione_vuoto_e_errore(fixture_path, client_finto):
    client = client_finto(testi={urp.url_pagina("categorie-riservatarie", 0): leggi(fixture_path, "elenco_vuoto.html")})
    with pytest.raises(FonteErrore):
        urp.elenco_sezione(client, "categorie-riservatarie")


def test_elenco_con_duplicati_tra_pagine_e_errore(fixture_path, client_finto):
    # la stessa pagina due volte: 10 bandi unici su 13 dichiarati
    pagina = leggi(fixture_path, "elenco_categorie-riservatarie_p0.html")
    client = client_finto(testi={urp.url_pagina("categorie-riservatarie", 0): pagina,
                                 urp.url_pagina("categorie-riservatarie", 1): pagina,
                                 urp.url_pagina("categorie-riservatarie", 2): leggi(fixture_path, "elenco_vuoto.html")})
    with pytest.raises(FonteErrore, match="10 bandi su 13"):
        urp.elenco_sezione(client, "categorie-riservatarie")


def test_parse_dettaglio_scorrimento(fixture_path):
    url = "https://www.urp.cnr.it/node/763"
    scheda = urp.parse_dettaglio(leggi(fixture_path, "bando_763.html"), url, "tempo-indeterminato")
    assert scheda["id_esterno"] == "/node/763"
    assert scheda["sezione"] == "tempo-indeterminato"
    assert scheda["tipologia"] == "tempo_indeterminato"
    assert scheda["codice_originale"] == "367.444 DT SAC"
    assert scheda["numero_bando"] == "367.444"
    assert scheda["protocollo"] == "2772"
    assert scheda["data_pubblicazione"] == "2024-01-08"

    per_titolo = {d["titolo"]: d for d in scheda["documenti"]}
    grad = per_titolo["Graduatoria"]
    assert (grad["categoria"], grad["protocollo"], grad["data_protocollo"]) == ("graduatoria", "278067", "2024-08-01")
    scorr = per_titolo["Scorrimento graduatoria"]
    assert (scorr["categoria"], scorr["sottotipo"], scorr["protocollo"]) == ("scorrimento", "non_specificato", "427762")
    assert scorr["sottotipo_origine"] == "titolo"
    assert per_titolo["Rettifica"]["categoria"] == "rettifica"
    assert per_titolo["Criteri"]["categoria"] == "criteri"
    assert per_titolo["Avviso prova colloquio"]["protocollo"] is None
    # il documento principale del bando è salvato come categoria "bando"
    bando = [d for d in scheda["documenti"] if d["categoria"] == "bando"]
    assert len(bando) == 1 and bando[0]["protocollo"] == "2772"


def test_parse_dettaglio_utilizzo(fixture_path):
    scheda = urp.parse_dettaglio(leggi(fixture_path, "bando_7004.html"), "https://www.urp.cnr.it/node/7004",
                                 "tempo-indeterminato")
    assert scheda["codice_originale"] == "367.459 FA SAC"
    utilizzo = [d for d in scheda["documenti"] if d["titolo"] == "Utilizzo graduatoria"][0]
    assert (utilizzo["categoria"], utilizzo["sottotipo"], utilizzo["protocollo"]) == ("scorrimento", "utilizzo", "32006")
    convoc = [d for d in scheda["documenti"] if d["titolo"] == "Convocazione prova orale"][0]
    assert convoc["categoria"] == "altro"


@pytest.mark.parametrize("testo, atteso", [
    ("BANDO N. 367.444 DT SAC - E' stato esercitato il diritto di accesso", "367.444 DT SAC"),
    ("BANDO 367. 640 CTER ADR PALERMO", "367.640 CTER ADR PALERMO"),
    ("Codice Bando 367.443 CTER", "367.443 CTER"),
    ("Allegati bando", None),
    ("AVVISO “02-COMANDO-2024 DCGR”", "02-COMANDO-2024 DCGR"),
    ("AVVISO “01- COMANDO-2025 ISSIRFA”", "01- COMANDO-2025 ISSIRFA"),
    ("Avviso 01-COMANDO-2025-IREA", "01-COMANDO-2025-IREA"),
    ("ADRRM2-01-COMANDO-2026", "ADRRM2-01-COMANDO-2026"),
    ("Curriculum strutturato", None),
])
def test_codice_da_testo(testo, atteso):
    assert urp._codice_da_testo(testo) == atteso


def test_mobilita_comando(fixture_path):
    html = leggi(fixture_path, "bando_7004.html").replace("CONCORSO PUBBLICO", "AVVISO DI COMANDO")
    scheda = urp.parse_dettaglio(html, "https://www.urp.cnr.it/node/1", "bandi-pubblici-mobilita")
    assert scheda["tipologia"] == "comando"
