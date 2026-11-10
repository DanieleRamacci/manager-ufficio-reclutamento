import pytest

from monitoraggio.classifica import classifica


@pytest.mark.parametrize("titolo, atteso", [
    ("Provvedimento subentro scorrimento graduatoria - Prot. AMMCNT n. 1/2026",
     ("scorrimento", "subentro", None)),
    ("Provvedimento ulteriore scorrimento graduatoria - Prot. AMMCNT n. 1/2026",
     ("scorrimento", "ulteriore", None)),
    ("Provvedimento terzo scorrimento graduatoria - prot. AMMCEN n. 1/2026",
     ("scorrimento", "ulteriore", 3)),
    ("Provvedimento secondo scorrimento graduatoria", ("scorrimento", "ulteriore", 2)),
    ("Assunzione di n. 2 unità di personale mediante utilizzo graduatoria",
     ("scorrimento", "utilizzo", None)),
    ("Utilizzo graduatoria - Prot. n. 1 del 01/01/2026", ("scorrimento", "utilizzo", None)),
    ("Scorrimento graduatoria", ("scorrimento", "non_specificato", None)),
    ("Assunzione idonei - Scorrimento graduatoria", ("scorrimento", "non_specificato", None)),
    ("Rettifica nominativo graduatoria", ("rettifica", None, None)),
    ("Errata corrige", ("rettifica", None, None)),
    ("Graduatoria", ("graduatoria", None, None)),
    ("Avviso convocazione prova idoneativa", ("altro", None, None)),
    ("Curriculum Strutturato", ("altro", None, None)),
    ("Criteri di valutazione", ("criteri", None, None)),
    ("Tracce prova scritta", ("tracce", None, None)),
    ("Prove orali", ("tracce", None, None)),
    ("Tracce prova colloquio", ("tracce", None, None)),
    ("Convocazione prova orale", ("altro", None, None)),
    ("Avviso convocazione prova scritta", ("altro", None, None)),
    ("Errata corrige bando", ("rettifica", None, None)),
    ("MODIFICA E PROROGA DEL TERMINE", ("altro", None, None)),
    ("Modifica graduatoria Bando n. 367.434 CA_ Cod. 07_signed.pdf", ("rettifica", None, None)),
    ("Rimodulazione Graduatoria 367.434 CA - Cod. 18 Potenza_signed (3).pdf", ("rettifica", None, None)),
    ("Riformulazione Graduatoria 367_434 cod.19 14933_Redacted.pdf", ("rettifica", None, None)),
    ("Modifica e proroga Bando 367.434 CA_signed.pdf", ("altro", None, None)),
])
def test_titoli_urp(titolo, atteso):
    assert classifica(titolo) == atteso


@pytest.mark.parametrize("nome, tipo, atteso", [
    ("Provvedimento 123_signed.pdf", "D:jconon_attachment:call_recruitment_provision",
     ("scorrimento", "non_specificato", None)),
    ("Utilizzo graduatoria bando 367.471 OTP SAC_signed (1).pdf",
     "D:jconon_attachment:call_recruitment_provision", ("scorrimento", "utilizzo", None)),
    ("IR 003 2026 ICAR NA_Provv_scorrimento 455701 26ott26_signed.pdf",
     "D:jconon_attachment:call_classification", ("scorrimento", "non_specificato", None)),
    ("Avviso 3-2025_Contratto di ricerca-ISP_Scorrimento Graduatoria_STAMP.pdf",
     "D:jconon_attachment:call_correction_classification",
     ("scorrimento", "non_specificato", None)),
    ("Graduatoria 367.36 DSU-IRISS-RIC.pdf", "D:jconon_attachment:call_classification",
     ("graduatoria", None, None)),
    ("367.36 decreto.pdf", "D:jconon_attachment:call_classification", ("graduatoria", None, None)),
    ("decreto.pdf", "D:jconon_attachment:call_correction_classification", ("rettifica", None, None)),
    ("Bando 367.36 DSU IRISS RIC_signed.pdf", "D:jconon_attachment:call_it", ("bando", None, None)),
    ("avviso.pdf", "D:jconon_attachment:call_mobility", ("bando", None, None)),
    ("AVVISO CONVOCAZIONE.pdf", "D:jconon_attachment:call_convocazioni_candidati",
     ("altro", None, None)),
])
def test_allegati_sol(nome, tipo, atteso):
    assert classifica(nome, tipo) == atteso


@pytest.mark.parametrize("titolo, categoria", [
    ("Pubblicazione nominativo vincitrice", "graduatoria"), ("Pubblicazione vincitori", "graduatoria"),
    ("Provvedimento assunzione di n. 1 vincitore", "altro"), ("Assunzione dei vincitori della selezione", "altro"),
])
def test_pubblicazione_dei_vincitori_e_la_graduatoria(titolo, categoria):
    assert classifica(titolo)[0] == categoria
