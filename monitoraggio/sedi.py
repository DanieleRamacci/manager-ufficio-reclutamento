"""Bandi con sotto-bandi su Selezioni Online: il legame con il padre si salva alla lettura dei bandi.

Il formato dei nomi cambia da bando a bando ("- 06 STEMS NA", "- TRIESTE Codice 05", "MI"), quindi il padre e i suoi
sotto-bandi si ricavano dal collegamento di SOL. Il testo serve solo a riconoscere la sede del file tra quelle del bando.
"""
import json
import re
import unicodedata
from collections import defaultdict

_PAROLE_IGNORATE = {"CODICE", "COD", "TEMATICA", "SEDE"}


def famiglie(conn) -> dict:
    """Per ogni bando con sotto-bandi: {"padre": scheda, "figli": [schede]}."""
    per_bando = defaultdict(list)
    for s in conn.execute("SELECT * FROM scheda WHERE fonte = 'sol' AND presente = 1 AND bando_id IS NOT NULL"):
        per_bando[s["bando_id"]].append(s)
    trovate = {}
    for bando_id, schede in per_bando.items():
        per_id = {s["id_esterno"]: s for s in schede}
        figli = [s for s in schede if s["id_padre"] in per_id]
        if figli:
            trovate[bando_id] = {"padre": per_id[figli[0]["id_padre"]], "figli": figli}
    return trovate


def _parole(testo) -> set[str]:
    semplice = unicodedata.normalize("NFKD", str(testo or "")).encode("ascii", "ignore").decode().upper()
    return {str(int(p)) if p.isdigit() else p for p in re.findall(r"[A-Z0-9]+", semplice) if p not in _PAROLE_IGNORATE}


def _parole_con_sede(scheda) -> set[str]:
    extra = json.loads(scheda["dati_extra"]) if scheda["dati_extra"] else {}
    return _parole(scheda["codice_originale"]) | _parole(extra.get("sede")) | _parole(extra.get("struttura_destinataria"))


def abbina(testo, figli: list):
    """Il sotto-bando a cui si riferisce il testo, solo se è uno: con zero o più di uno non si sceglie."""
    cercate = _parole(testo)
    if not cercate:
        return None
    for parole_di in (lambda s: _parole(s["codice_originale"]), _parole_con_sede):
        trovati = [s for s in figli if cercate <= parole_di(s)]
        if trovati:
            return trovati[0] if len(trovati) == 1 else None
    return None


def testi_sede(conn) -> dict[int, set[str]]:
    """Per ogni atto del file in uso, come è scritta la sede nella colonna Sotto-bando."""
    testi = defaultdict(set)
    for r in conn.execute("SELECT r.atto_id, r.valori FROM segreteria_riga r JOIN segreteria_versione v ON v.id = r.versione_id "
                          "WHERE v.esito = 'in_uso' AND r.atto_id IS NOT NULL"):
        for colonna, valore in json.loads(r["valori"]).items():
            if re.sub(r"[^a-z]", "", colonna.lower()) == "sottobando" and str(valore or "").strip():
                testi[r["atto_id"]].add(str(valore).strip())
    return testi


def del_gruppo(famiglia: dict | None, gruppo: dict) -> dict | None:
    """Le sedi a cui vale un atto: dal file, dal sotto-bando che ha il documento o, se il documento sta sul padre, tutte."""
    if not famiglia:
        return None
    figli, padre = famiglia["figli"], famiglia["padre"]
    trovati, non_abbinata = {}, False
    for testo in (gruppo.get("segreteria") or {}).get("testi_sede") or ():
        s = abbina(testo, figli)
        if s is None:
            non_abbinata = True
        else:
            trovati[s["id"]] = s
    documenti_sol = (gruppo.get("sol") or {}).get("schede_doc") or ()
    trovati.update({s["id"]: s for s in figli if s["id"] in documenti_sol})
    sotto = {v.get("codice_sotto") for v in gruppo.values() if v.get("codice_sotto")}
    trovati.update({s["id"]: s for s in figli if s["codice_sotto"] and s["codice_sotto"] in sotto})
    if not trovati and padre["id"] in documenti_sol:
        trovati = {s["id"]: s for s in figli}
    return {"padre": padre, "figli": list(trovati.values()), "da_abbinare": non_abbinata or not trovati}
