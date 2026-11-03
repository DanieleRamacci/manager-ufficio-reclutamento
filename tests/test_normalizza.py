from datetime import datetime

import pytest

from monitoraggio import normalizza as n


@pytest.mark.parametrize("a, b", [
    ("367.479 CTER IOM GE", "367.479 CTER IOMGE"),
    ("BANDO N. 367.479 CTER IOMGE", "367.479 cter iom ge"),
    ("Codice Bando 367.479 CTER IOM-GE", "367.479 CTER IOM GE"),
    ("367. 479 CTER IOMGE", "367.479 CTER IOMGE"),
])
def test_codice_norm_uguale_tra_fonti(a, b):
    assert n.codice_norm(a) == n.codice_norm(b) == "367.479CTERIOMGE"


@pytest.mark.parametrize("a, b", [
    ("02-COMANDO-2024 DCGR", "“02-COMANDO-2024 DCGR”"),
    ("01- COMANDO-2025 ISSIRFA", "01-COMANDO-2025-ISSIRFA"),
    ("01-COMANDO-2025-ISM", "1-COMANDO-2025 ISM"),
])
def test_codice_norm_comandi(a, b):
    assert n.codice_norm(a) == n.codice_norm(b)


def test_codice_norm_vuoto():
    assert n.codice_norm("") is None
    assert n.codice_norm(None) is None


@pytest.mark.parametrize("testo, atteso", [
    ("367.434 CA Cod. 14", "367.434"),
    ("367.434 CA. Cod 13", "367.434"),
    ("367.434 CA. Codice 16", "367.434"),
    ("367529", "367.529"),
    ("390.475", "390.475"),
    ("367.500 CTER ALLEGATI ALLEGATO 1 - STRUTT", "367.500"),
    ("BANDO 365.1 DISBA ISA RIC", "365.1"),
    ("367. 640 CTER ADR PALERMO", "367.640"),
    ("02-COMANDO-2024 DCGR", None),
    ("Protocollo 160039 del 12-05-2025", None),
    (None, None),
])
def test_numero_bando(testo, atteso):
    assert n.numero_bando(testo) == atteso


@pytest.mark.parametrize("testo, atteso", [
    ("367.434 CA Cod. 14", "14"),
    ("367.434 CA. Cod 13", "13"),
    ("367.434 CA. Codice 16", "16"),
    ("367.501 Cod.05", "5"),
    ("367.500 cod.A", "A"),
    ("367.500 CTER SAC - Tematica C - Supporto progetti", "C"),
    ("Codice Bando 367.443 CTER", None),
    ("367.479 CTER IOMGE", None),
])
def test_codice_sotto(testo, atteso):
    assert n.codice_sotto(testo) == atteso


@pytest.mark.parametrize("testo, atteso", [
    ("0455701", "455701"),
    ("157495 ", "157495"),
    ("- Protocollo 160039", "160039"),
    (160039, "160039"),
    ("", None),
    (None, None),
])
def test_protocollo(testo, atteso):
    assert n.protocollo(testo) == atteso


@pytest.mark.parametrize("valore, atteso", [
    ("12-05-2025", "2025-05-12"),
    ("12/05/2025", "2025-05-12"),
    ("12.05.2025", "2025-05-12"),
    ("del 12-05-2025", "2025-05-12"),
    ("2025-05-12T12:00:00Z", "2025-05-12"),
    ("2025-05-12", "2025-05-12"),
    (datetime(2026, 6, 3), "2026-06-03"),
    ("non è una data", None),
    (None, None),
])
def test_data_iso(valore, atteso):
    assert n.data_iso(valore) == atteso
