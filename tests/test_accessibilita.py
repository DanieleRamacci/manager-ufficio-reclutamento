"""Accessibilità dei PDF: senza pikepdf nessun documento può risultare accessibile."""
import io

import pikepdf
from flask import Flask

from monitoraggio import accessibilita, web

TESTO = b"Graduatoria di merito del concorso pubblico " * 8


def pdf(testo=TESTO, taggato=False) -> bytes:
    documento = pikepdf.new()
    documento.add_blank_page()
    pagina = documento.pages[0]
    pagina.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(
        F1=pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)))
    if testo:
        pagina.Contents = documento.make_stream(b"BT /F1 8 Tf 10 700 Td (" + testo + b") Tj ET")
    if taggato:
        documento.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        documento.Root.StructTreeRoot = documento.make_indirect(
            pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        documento.Root.Lang = pikepdf.String("it-IT")
    buffer = io.BytesIO()
    documento.save(buffer)
    return buffer.getvalue()


def test_pdf_taggato_accessibile():
    r = accessibilita.valuta_file(pdf(taggato=True), "a.pdf")
    assert r["accessible"] is True and r["level"] == "accessibile" and r["score"] == 100
    assert r["is_tagged"] and r["has_struct_tree"] and r["lang"] == "it-IT"


def test_pdf_solo_testo_parziale():
    r = accessibilita.valuta_file(pdf(), "a.pdf")
    assert r["has_text"] and not r["accessible"] and r["level"] == "parziale"


def test_pdf_scansione_e_non_pdf():
    assert accessibilita.valuta_file(pdf(testo=None), "a.pdf")["note"].startswith("Sembra scansione")
    r = accessibilita.valuta_file(b"x", "a.docx")
    assert r["is_pdf"] is False and r["checked"] is False


def test_documento_da_url_taggato(monkeypatch):
    monkeypatch.setattr(accessibilita, "_download_pdf", lambda url: pdf(taggato=True))
    assert accessibilita.valuta_accessibilita_pdf("https://esempio/a.pdf")["accessible"] is True


def test_api_verifica_pdf(db):
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint_pagine_esistenti())
    c = app.test_client()
    assert c.get("/verifica-access.html").status_code == 200
    assert c.post("/api/check-access").status_code == 400
    r = c.post("/api/check-access", data={"file": (io.BytesIO(pdf(taggato=True)), "../bando 1.pdf")})
    assert r.get_json()["result"]["accessible"] is True and r.get_json()["result"]["filename"] == "bando_1.pdf"
    r = c.post("/api/check-access-batch", data={"files": [(io.BytesIO(pdf()), "a.pdf"), (io.BytesIO(b"x"), "b.txt")]})
    assert [x["level"] for x in r.get_json()["results"]] == ["parziale", "non_accessibile"]


def test_file_troppo_grande_non_valutato(db, monkeypatch):
    monkeypatch.setattr(web, "MAX_FILE_PDF", 10)
    app = Flask(__name__)
    app.register_blueprint(web.crea_blueprint_pagine_esistenti())
    r = app.test_client().post("/api/check-access", data={"file": (io.BytesIO(pdf(taggato=True)), "a.pdf")})
    assert r.get_json()["result"]["note"] == "File oltre 25 MB" and r.get_json()["result"]["checked"] is False


def test_sezioni_urp_per_le_pagine(db):
    from monitoraggio import collegamento, compat, config
    from tests.test_collegamento import doc, salva, scheda
    assert config.urp_url_sezione("borse-ricerca").endswith("/documenti/borse-di-ricerca")
    assert {"tempo-determinato", "borse-ricerca", "direttori-dipartimentiistituti"} <= set(config.urp_sezioni())
    salva(db, "urp", [scheda("urp", "/node/9", "BORSA 1", None, tipologia=None, sezione="borse-ricerca",
                             documenti=[doc("g1", "graduatoria", "111")])])
    collegamento.collega(db)
    assert [b["codice_bando"] for b in compat.export_urp(db)["borse-ricerca"]] == ["BORSA 1"]
    assert web.riepilogo_mensile(db)["mesi"] == []


def _documenti_urp(db):
    from tests.test_collegamento import doc, salva, scheda
    documenti = [{**doc("a", "altro", "1"), "url": "https://esempio/a.pdf"},
                 {**doc("b", "bando", "2"), "url": "https://esempio/b.pdf"},
                 {**doc("c", "criteri", "3"), "url": None}]
    salva(db, "urp", [scheda("urp", "/node/1", "X 1", None, documenti=documenti)])


def test_tutti_i_pdf_elencati_e_ripresa_dopo_un_riavvio(db, monkeypatch):
    _documenti_urp(db)
    monkeypatch.setattr(accessibilita.config, "pausa_urp", lambda: 0)
    monkeypatch.setattr(accessibilita, "valuta_accessibilita_pdf", lambda url: {"accessible": True})
    da_fare = accessibilita.documenti_da_valutare(db)
    assert len(da_fare) == 1  # né il documento principale né quello senza link
    assert accessibilita.controlla_documenti(db, da_fare) == 1
    assert accessibilita.documenti_da_valutare(db) == []


def test_un_solo_controllo_alla_volta(db):
    _documenti_urp(db)
    with accessibilita._controllo_in_corso:
        assert accessibilita.controlla_documenti(db, accessibilita.documenti_da_valutare(db)) == 0
