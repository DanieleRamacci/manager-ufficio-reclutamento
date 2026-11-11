"""Verifica del file scorrimenti compilato dai colleghi e ricaricato dall'amministratore.

Decisione dell'utente del 2026-11-11: un subentro non è una difformità del monitoraggio; va solo indicato nel file
scorrimenti, e lo si controlla quando il file compilato viene ricaricato. Dal file si leggono solo bando, protocolli e
tipologia: la colonna dei nominativi non si legge e il file non si conserva.

I colleghi scrivono le cose a modo loro (nel file di agosto 2026 «subentro» stava nella colonna della struttura e il
bando era «367614» o «367.434 Codice 13 Roma»), quindi il subentro si cerca in tutta la riga e il bando anche senza punto.
"""
import io
import json
import re
from datetime import datetime, timezone

import openpyxl

from .normalizza import norm_space, numero_bando, protocollo

_SUBENTRO = re.compile(r"subentr|rinunci", re.I)
_PROTOCOLLO = re.compile(r"(?<![\d/.-])0*(\d{5,7})(?![\d/.-])")


class FileNonValido(ValueError):
    pass


def _testo(valore) -> str:
    return norm_space(str(valore)) if valore is not None else ""


def _numero(valore) -> str | None:
    if isinstance(valore, (int, float)) and 100000 <= int(valore) <= 999999:
        cifre = str(int(valore))
        return f"{cifre[:3]}.{cifre[3:]}"
    testo = _testo(valore)
    m = re.match(r"^(\d{3})(\d{3})\b", testo)
    return numero_bando(testo) or (f"{m[1]}.{m[2]}" if m else None)


def leggi(contenuto: bytes) -> list[dict]:
    """Le righe compilate di tutti i fogli, senza i nominativi."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contenuto), read_only=True, data_only=True)
    except Exception as e:
        raise FileNonValido("Il file non è un Excel leggibile") from e
    voci = []
    for ws in wb.worksheets:
        colonne = None
        for n, valori in enumerate(ws.iter_rows(values_only=True), start=1):
            valori = valori or ()
            if colonne is None:
                testi = [_testo(v).upper() for v in valori]
                if any("BANDO" in t and "SCORRERE" in t for t in testi):
                    colonne = {t: i for i, t in enumerate(testi) if t}
                continue

            def prendi(nome, colonne=colonne, valori=valori):
                return next((valori[i] for t, i in colonne.items() if nome in t and i < len(valori)), None)

            bando = prendi("BANDO")
            if bando in (None, "") or _testo(bando).upper().startswith("TOTALE"):
                continue
            # i nominativi non si leggono mai
            leggibili = [_testo(valori[i]) for t, i in colonne.items() if "NOMINATIV" not in t and i < len(valori)]
            provvedimenti = " ".join(_testo(prendi(x)) for x in ("PROVVEDIMENTO DG", "PROVVEDIMENTO RECLUTAMENTO"))
            voci.append({"foglio": ws.title, "riga": n, "bando": _testo(bando), "numero_bando": _numero(bando),
                         "protocolli": sorted({protocollo(p) for p in _PROTOCOLLO.findall(provvedimenti)}),
                         "tipologia": _testo(prendi("TIPOLOGIA")), "subentro": any(_SUBENTRO.search(t) for t in leggibili)})
    wb.close()
    if not voci:
        raise FileNonValido("Nel file non c'è nessuna riga compilata sotto «BANDO SU CUI SCORRERE»")
    return voci


def salva(conn, mese: str, nome_file: str | None, voci: list[dict], utente: str | None) -> None:
    conn.execute("INSERT INTO scorrimenti_compilato (mese, nome_file, caricato_da, caricato_il, voci) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(mese) DO UPDATE SET nome_file = excluded.nome_file, caricato_da = excluded.caricato_da, "
                 "caricato_il = excluded.caricato_il, voci = excluded.voci",
                 (mese, nome_file, utente, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), json.dumps(voci, ensure_ascii=False)))


def caricato(conn, mese: str) -> dict | None:
    r = conn.execute("SELECT * FROM scorrimenti_compilato WHERE mese = ?", (mese,)).fetchone()
    return {**dict(r), "voci": json.loads(r["voci"])} if r else None


def _protocolli_riga(riga: dict) -> set[str]:
    return {str(p) for p in (riga.get("protocollo"), *(c.get("protocollo") for c in (riga.get("fonti") or {}).values())) if p}


def confronta(righe: list[dict], voci: list[dict]) -> dict:
    """Ogni scorrimento del mese con le righe del file che lo riguardano; e le righe del file senza un atto del mese."""
    usate, atti = set(), []
    for r in righe:
        if r["atto"] != "scorrimento":
            continue
        stesse = [i for i, v in enumerate(voci) if v["numero_bando"] and v["numero_bando"] == r.get("numero_bando")]
        per_protocollo = [i for i in stesse if _protocolli_riga(r) & set(voci[i]["protocolli"])]
        trovate = per_protocollo or [i for i in stesse if not voci[i]["protocolli"]]
        usate.update(trovate)
        atti.append({"chiave": r.get("chiave"), "codice": r.get("codice"), "numero_bando": r.get("numero_bando"), "protocollo": r.get("protocollo"),
                     "data": r.get("data"), "trovato": bool(trovate), "righe_file": [f"{voci[i]['foglio']}, riga {voci[i]['riga']}" for i in trovate],
                     "tipologia": "; ".join(t for t in dict.fromkeys(voci[i]["tipologia"] for i in trovate) if t),
                     "subentro_atteso": bool(r.get("subentro_atteso")), "subentro_indicato": any(voci[i]["subentro"] for i in trovate)})
    solo_file = [{k: v[k] for k in ("foglio", "riga", "bando", "protocolli")} for i, v in enumerate(voci) if i not in usate]
    return {"atti": atti, "solo_nel_file": solo_file}


def per_riga(conn, mese: str, righe: list[dict]) -> None:
    """Aggiunge a ogni scorrimento l'esito del file compilato, se è stato caricato."""
    file = caricato(conn, mese)
    if not file:
        return
    esito = confronta(righe, file["voci"])
    per_chiave = {(a["chiave"], a["protocollo"], a["data"]): a for a in esito["atti"]}
    for r in righe:
        a = per_chiave.get((r.get("chiave"), r.get("protocollo"), r.get("data"))) if r["atto"] == "scorrimento" else None
        if a:
            r["file_scorrimenti"] = {k: a[k] for k in ("trovato", "tipologia", "subentro_indicato", "righe_file")}
