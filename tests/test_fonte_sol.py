import json

import pytest

from monitoraggio.fonti import sol
from monitoraggio.fonti.http import FonteErrore

COMANDI = "F:jconon_call_comandi_distacchi:folder"


def carica(fixture_path, nome):
    return json.loads(fixture_path(f"sol/{nome}").read_text(encoding="utf-8"))


def client_pagine(client_finto, pagine, page_size=5):
    def risposta(url, params):
        return pagine.get(int(params["skipCount"]))
    client = client_finto(json_per_chiave=risposta)
    return client


def test_cerca_bandi_paginazione(fixture_path, client_finto, monkeypatch):
    monkeypatch.setattr(sol.config, "SOL_PAGE_SIZE", 5)
    client = client_pagine(client_finto, {0: carica(fixture_path, "comandi_p0.json"),
                                          5: carica(fixture_path, "comandi_p1.json")})
    items, totale = sol.cerca_bandi(client, COMANDI)
    assert totale == 8 and len(items) == 8
    assert [int(p["skipCount"]) for _, p in client.richieste] == [0, 5]
    assert "IN_TREE" in client.richieste[0][1]["q"] and COMANDI in client.richieste[0][1]["q"]


def test_cerca_bandi_totale_diverso_e_errore(fixture_path, client_finto, monkeypatch):
    monkeypatch.setattr(sol.config, "SOL_PAGE_SIZE", 5)
    ultima = carica(fixture_path, "comandi_p1.json")
    ultima["items"] = ultima["items"][:1]
    client = client_pagine(client_finto, {0: carica(fixture_path, "comandi_p0.json"), 5: ultima})
    with pytest.raises(FonteErrore, match="dichiarati"):
        sol.cerca_bandi(client, COMANDI)


def test_tipo_sconosciuto_e_errore(fixture_path, client_finto):
    client = client_finto(json_per_chiave=lambda url, params: carica(fixture_path, "errore_tipo.json"))
    with pytest.raises(FonteErrore, match="Unknown type"):
        sol.cerca_bandi(client, "F:jconon_call_mobility_open:folder")


def test_scheda_da_item(fixture_path):
    item = carica(fixture_path, "bando_367473.json")["items"][0]
    scheda = sol.scheda_da_item(item, "F:jconon_call_tind:folder_concorsi_pubblici")
    assert scheda["id_esterno"] == item["cmis:objectId"]
    assert scheda["codice_originale"] == "367.473 OTP IN"
    assert scheda["numero_bando"] == "367.473"
    assert scheda["tipologia"] == "tempo_indeterminato"
    assert scheda["data_pubblicazione"] == item["jconon_call:data_pubblicazione_inpa"][:10]
    assert scheda["data_pubbl_graduatoria"] == (item.get("jconon_call:data_pubbl_graduatoria") or "")[:10] or None
    assert scheda["modificata_fonte_il"] == item["cmis:lastModificationDate"]
    extra = json.loads(scheda["dati_extra"])
    assert extra["profilo"] == item.get("jconon_call:profilo")
    assert extra["gruppo_rdp"] == item.get("jconon_call:rdp")
    assert "callCode=" in scheda["url"]


def test_allegati_bando(fixture_path, client_finto):
    client = client_finto(json_per_chiave=lambda url, params: carica(fixture_path, "allegati_367473.json"))
    documenti = sol.allegati_bando(client, "id-bando")
    assert "IN_TREE(root,'id-bando')" in client.richieste[0][1]["q"]
    per_tipo = {d["tipo_fonte"].split(":")[-1]: d for d in documenti}
    assert "metadata" not in per_tipo  # membri di commissione ignorati
    grad = per_tipo["call_classification"]
    assert (grad["categoria"], grad["protocollo"], grad["protocollo_originale"], grad["data_protocollo"]) == (
        "graduatoria", "3763", "0003763", "2026-01-08")
    utilizzo = per_tipo["call_recruitment_provision"]
    assert (utilizzo["categoria"], utilizzo["sottotipo"], utilizzo["protocollo"]) == ("scorrimento", "utilizzo", "175370")
    assert per_tipo["call_it"]["categoria"] == "bando"
    assert per_tipo["call_errata_corrige"]["categoria"] == "rettifica"


def test_allegati_solo_del_bando_anche_in_sottocartella(client_finto):
    from monitoraggio.fonti import sol as modulo
    voce = lambda tipo, nome: {"cmis:objectId": nome, "cmis:name": nome, "cmis:objectTypeId": tipo,  # noqa: E731
                               "jconon_protocollo:numero": "0461293", "jconon_protocollo:data": "2026-10-28"}
    client = client_finto(json_per_chiave=lambda url, params: {"totalNumItems": 3, "hasMoreItems": False, "items": [
        voce("D:jconon_attachment:call_recruitment_provision", "provvedimento"),
        voce("D:jconon_commissione:metadata", "commissione"),
        voce("D:jconon_attachment:curriculum_vitae", "curriculum-candidato")]})
    docs = modulo.allegati_bando(client, "id-bando")
    assert [d["titolo"] for d in docs] == ["provvedimento"]
    assert docs[0]["categoria"] == "scorrimento" and docs[0]["protocollo"] == "461293"
