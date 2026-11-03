"""Le chiavi dei JSON ricostruiti dal database devono coincidere con quelle dei file storici."""
import json

import pytest

from monitoraggio import compat
from tests.conftest import ROOT
from tests.test_collegamento import doc, salva, scheda


def chiavi_storiche(nome):
    path = ROOT / nome
    if not path.exists():
        pytest.skip(f"{nome} non presente nella cartella del progetto")
    return json.loads(path.read_text(encoding="utf-8"))


def popola(db):
    urp = scheda("urp", "/node/1", "367.601 FA ISTC", "367.601", documenti=[doc("u1", "graduatoria", "500")])
    urp["dati_extra"] = json.dumps({"estratto": "testo", "titolo_bando": "Codice Bando 367.601 FA ISTC"})
    mob = scheda("urp", "/node/2", "365.199 FA", "365.199", sezione="bandi-pubblici-mobilita", tipologia="mobilita")
    salva(db, "urp", [urp, mob])
    salva(db, "sol", [scheda("sol", "s1", "367.601 FA ISTC", "367.601", documenti=[doc("x1", "graduatoria", "500")])])


def test_urp(db):
    storico = chiavi_storiche("bandi-completi-urp.json")
    popola(db)
    nuovo = compat.export_urp(db)
    bando_storico = storico["tempo-indeterminato"][0]
    bando = nuovo["tempo-indeterminato"][0]
    assert set(bando_storico) <= set(bando)
    allegato_storico = next(a for b in storico["tempo-indeterminato"] for a in b["allegati"] if a.get("access_check"))
    assert set(allegato_storico) <= set(bando["allegati"][0])
    assert bando["graduatoria_presente"] is True
    assert "bandi-pubblici-mobilita" not in nuovo


def test_sol(db):
    storico = chiavi_storiche("bandi-concorsi-pubblici-sol.json")
    popola(db)
    nuovo = compat.export_sol(db)
    assert set(storico[0]) <= set(nuovo[0])
    assert nuovo[0]["graduatoria_allegato"] is True and nuovo[0]["tipologia"] == "concorsi_pubblici"


def test_mobilita(db):
    storico = chiavi_storiche("bandi-mobilita.json")
    popola(db)
    nuovo = compat.export_mobilita(db)
    assert set(storico[0]) <= set(nuovo[0])
    assert nuovo[0]["tipologia"] == "mobilità"
