import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Database vuoto in una cartella temporanea: i test non toccano instance/."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from monitoraggio import db as dbmod

    conn = dbmod.connetti()
    dbmod.inizializza(conn)
    yield conn
    conn.close()


@pytest.fixture
def fixture_path():
    def _path(nome: str) -> Path:
        return FIXTURES / nome

    return _path


class ClientFinto:
    """Client HTTP finto: risponde con le fixture registrate per URL (e parametri)."""

    def __init__(self, testi=None, json_per_chiave=None):
        self.testi = testi or {}
        self.json_per_chiave = json_per_chiave or (lambda url, params: None)
        self.richieste = []
        self.header = []

    def get_text(self, url, params=None):
        self.richieste.append((url, params))
        if url not in self.testi:
            raise RuntimeError(f"URL non previsto nel test: {url}")
        valore = self.testi[url]
        if isinstance(valore, Exception):
            raise valore
        return valore

    def get_json(self, url, params=None, headers=None):
        self.richieste.append((url, params))
        self.header.append(headers or {})
        risposta = self.json_per_chiave(url, params or {})
        if isinstance(risposta, Exception):
            raise risposta
        if risposta is None:
            raise RuntimeError(f"Richiesta non prevista nel test: {url} {params}")
        return risposta


@pytest.fixture
def client_finto():
    return ClientFinto
