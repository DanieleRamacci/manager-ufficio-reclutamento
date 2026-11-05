"""File della segreteria (spec 002): lettura del file Excel, rapporto, atti, versioni.

I valori delle righe (compresi i nominativi) vanno solo nel database: mai nei log, nei
messaggi di errore o nel rapporto, che contiene solo conteggi e numeri di riga.
"""
import hashlib
import io
import json
import logging
import os
import re
import zipfile
from datetime import date, datetime, timezone
from urllib.parse import unquote

from .normalizza import codice_sotto, data_iso, numero_bando, protocollo

log = logging.getLogger(__name__)

FOGLI = {"bandi": ["bandi"], "graduatorie": ["graduatorie", "graduatoria"], "scorrimento": ["scorrimento", "scorrimenti"]}

# per foglio: (chiave, alias dell'intestazione normalizzata). Un alias che finisce con "*" è un prefisso.
# Le intestazioni duplicate (N. Bando / N Bando, due Note) si assegnano in ordine di posizione.
COLONNE = {
    "bandi": [("file", "file"), ("bando", "bando"), ("tipo_procedura", "tipoprocedura"),
              ("istituto", "istitutoufficio"), ("sede", "sede"), ("dipartimento", "dipartimento*"),
              ("oggetto", "oggetto*"), ("posti", "fasciacompenso*"), ("termine", "termine*"),
              ("protocollo", "protcnrn"), ("data", "dataprotocollo")],
    "graduatorie": [("prog", "prog"), ("file", "file"), ("n_bando", "nbando"), ("sotto_bando", "sottobando"),
                    ("posizione", "posizione"), ("nominativo", "cognomeenome"), ("punteggio", "punteggio"),
                    ("esito", "esito"), ("note", "note"), ("prot_privato", "nprotocolloprivato"),
                    ("data_privato", "dataprotocolloprivato"), ("prot_pubblico", "nprotocollopubblico"),
                    ("data_pubblico", "dataprotocollopubblico"), ("stato_avanzamento", "presenzastatoavanzamento"),
                    ("n_bando_2", "nbando"), ("referente", "referente")],
    "scorrimento": [("file", "file"), ("n_bando", "nbando"), ("sotto_bando", "sottobando"), ("posizione", "posizione"),
                    ("nominativo", "cognomeenome"), ("note", "note"), ("protocollo", "nprotocollo"),
                    ("data", "dataprotocollo"), ("tipologia", "tipologiadiutilizzo*"), ("note_2", "note")],
}
OBBLIGATORIE = {
    "bandi": ["bando", "tipo_procedura", "protocollo", "data"],
    "graduatorie": ["n_bando", "prot_pubblico", "data_pubblico"],
    "scorrimento": ["n_bando", "protocollo", "data", "tipologia"],
}
# "Presenza stato avanzamento" va ignorata (spec 002, FR-010)
IGNORATE = {"stato_avanzamento"}


class FileNonValido(Exception):
    pass


def _fuori_ambito_patterns() -> list[str]:
    return [p.strip() for p in os.environ.get("SEGRETERIA_FUORI_AMBITO", "direttor,revoca").split(",") if p.strip()]


def _norm_intestazione(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def _alias_ok(intestazione: str, alias: str) -> bool:
    return intestazione.startswith(alias[:-1]) if alias.endswith("*") else intestazione == alias


def _valore_json(v):
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat(timespec="minutes")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _testo_bando(v) -> str | None:
    """Numero bando anche se Excel l'ha salvato come numero: 367.5 -> '367.500'."""
    if v is None or v == "":
        return None
    if isinstance(v, float):
        return f"{v:.3f}" if not v.is_integer() else str(int(v))
    return str(v).strip()


def _sotto_da_colonna(v) -> str | None:
    m = re.match(r"^\s*0*(\d+)\b", str(v or ""))
    return m.group(1) if m else None


def _nome_file(v) -> str | None:
    if not v:
        return None
    return unquote(re.split(r"[\\/]", str(v).rstrip("/\\"))[-1]) or None


def leggi_file(contenuto: bytes) -> tuple[dict[str, list[dict]], dict]:
    """Legge i tre fogli. Ritorna righe per foglio ({"_riga", "_valori", chiavi...}) e rapporto."""
    import openpyxl  # dipendenza solo di questa funzione

    if not contenuto or not zipfile.is_zipfile(io.BytesIO(contenuto)):
        raise FileNonValido("Il file non è un Excel .xlsx")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contenuto), data_only=True, read_only=True)
    except Exception as e:  # file corrotto o di altro tipo
        raise FileNonValido(f"Il file Excel non si può leggere ({type(e).__name__})") from None

    nomi = {re.sub(r"\s+", "", n.lower()): n for n in wb.sheetnames}
    righe: dict[str, list[dict]] = {}
    rapporto = {"fogli": {}}
    for foglio, alias in FOGLI.items():
        nome = next((nomi[a] for a in alias if a in nomi), None)
        info = {"trovato": nome is not None, "nome_foglio": nome, "righe": 0, "atti": 0, "colonne_mancanti": [],
                "colonne_non_riconosciute": [], "fuori_ambito": 0,
                "problemi": {"senza_bando": [], "senza_protocollo": [], "data_illeggibile": [],
                             "numero_discordante": [], "senza_tipologia": []}}
        rapporto["fogli"][foglio] = info
        if nome is None:
            continue
        it = wb[nome].iter_rows(values_only=True)
        intestazioni = list(next(it, []) or [])
        mappa, assegnate = {}, set()
        for i, h in enumerate(intestazioni):
            if h is None or str(h).strip() == "":
                continue
            n = _norm_intestazione(h)
            chiave = next((k for k, a in COLONNE[foglio] if k not in assegnate and _alias_ok(n, a)), None)
            if chiave:
                mappa[i] = chiave
                assegnate.add(chiave)
            else:
                info["colonne_non_riconosciute"].append(str(h))
        info["colonne_mancanti"] = [k for k in OBBLIGATORIE[foglio] if k not in assegnate]
        etichette = [str(h) if h is not None else f"colonna_{i + 1}" for i, h in enumerate(intestazioni)]
        lette = []
        for numero_riga, valori in enumerate(it, start=2):
            if not valori or all(v is None or str(v).strip() == "" for v in valori):
                continue
            riga = {"_riga": numero_riga,
                    "_valori": {etichette[i] if i < len(etichette) else f"colonna_{i + 1}": _valore_json(v)
                                for i, v in enumerate(valori) if v is not None}}
            for i, chiave in mappa.items():
                if chiave not in IGNORATE:
                    riga[chiave] = valori[i] if i < len(valori) else None
            lette.append(riga)
        info["righe"] = len(lette)
        righe[foglio] = lette
    wb.close()
    if not any(i["trovato"] for i in rapporto["fogli"].values()):
        raise FileNonValido("Nessuno dei fogli attesi (Bandi, Graduatorie, Scorrimento) è presente nel file")
    log.info("File segreteria letto: %s", {f: i["righe"] for f, i in rapporto["fogli"].items()})
    return righe, rapporto


def _data(v, problemi: list, numero_riga: int) -> str | None:
    if v is None or str(v).strip() == "":
        return None
    d = data_iso(v)
    if d is None:
        problemi.append(numero_riga)
    return d


def costruisci_atti(righe: dict[str, list[dict]], rapporto: dict) -> list[dict]:
    """Raggruppa le righe in atti; aggiunge al rapporto i problemi riga per riga."""
    atti: dict[tuple, dict] = {}
    fuori = _fuori_ambito_patterns()

    def atto(chiave, **campi):
        a = atti.get(chiave)
        if a is None:
            a = atti[chiave] = {"categoria": chiave[0], "numero_bando": chiave[1], "codice_sotto": chiave[2],
                                "protocollo": chiave[3], "persone": 0, "righe": [], "in_ambito": True,
                                "tipologie": set(), **campi}
        return a

    # --- Bandi: una riga = un atto
    info = rapporto["fogli"]["bandi"]
    numeri_fuori_ambito = set()
    for r in righe.get("bandi", []):
        p = info["problemi"]
        testo = _testo_bando(r.get("bando"))
        numero = numero_bando(testo)
        if not numero:
            p["senza_bando"].append(r["_riga"])
            continue
        prot = protocollo(r.get("protocollo"))
        if not prot:
            p["senza_protocollo"].append(r["_riga"])
        tipo = str(r.get("tipo_procedura") or "").strip()
        in_ambito = not any(f in tipo.lower() for f in fuori)
        if not in_ambito:
            numeri_fuori_ambito.add(numero)
            info["fuori_ambito"] += 1
        a = atto(("bando", numero, codice_sotto(testo), prot or f"riga-{r['_riga']}"),
                 codice_originale=testo, protocollo_originale=_valore_json(r.get("protocollo")),
                 data=_data(r.get("data"), p["data_illeggibile"], r["_riga"]), tipo_procedura=tipo or None,
                 titolo=" · ".join(str(x) for x in (r.get("istituto"), r.get("oggetto")) if x) or None)
        if not prot:
            a["protocollo"] = None
        a["in_ambito"] = in_ambito
        a["persone"] += 1
        a["righe"].append(r)

    # --- Graduatorie: per bando, sotto-bando e protocollo pubblico
    info = rapporto["fogli"]["graduatorie"]
    for r in righe.get("graduatorie", []):
        p = info["problemi"]
        testo = _testo_bando(r.get("n_bando"))
        numero = numero_bando(testo)
        secondo = numero_bando(_testo_bando(r.get("n_bando_2")))
        if not numero:
            numero = secondo
        if not numero:
            p["senza_bando"].append(r["_riga"])
            continue
        if secondo and secondo != numero:
            p["numero_discordante"].append(r["_riga"])
        prot = protocollo(r.get("prot_pubblico"))
        if not prot:
            p["senza_protocollo"].append(r["_riga"])
        sotto = codice_sotto(testo) or _sotto_da_colonna(r.get("sotto_bando"))
        a = atto(("graduatoria", numero, sotto, prot), codice_originale=testo,
                 protocollo_originale=_valore_json(r.get("prot_pubblico")),
                 data=_data(r.get("data_pubblico"), p["data_illeggibile"], r["_riga"]),
                 protocollo_privato=protocollo(r.get("prot_privato")),
                 data_privato=data_iso(r.get("data_privato")), titolo=_nome_file(r.get("file")))
        a["persone"] += 1
        a["righe"].append(r)

    # --- Scorrimento: per bando, sotto-bando e protocollo; sottotipo dalla tipologia
    info = rapporto["fogli"]["scorrimento"]
    for r in righe.get("scorrimento", []):
        p = info["problemi"]
        tipologia = str(r.get("tipologia") or "").strip().lower()
        if not tipologia:
            p["senza_tipologia"].append(r["_riga"])
        testo = _testo_bando(r.get("n_bando"))
        numero = numero_bando(testo)
        if not numero:
            p["senza_bando"].append(r["_riga"])
            continue
        prot = protocollo(r.get("protocollo"))
        if not prot:
            p["senza_protocollo"].append(r["_riga"])
        sotto = codice_sotto(testo) or _sotto_da_colonna(r.get("sotto_bando"))
        a = atto(("scorrimento", numero, sotto, prot), codice_originale=testo,
                 protocollo_originale=_valore_json(r.get("protocollo")),
                 data=_data(r.get("data"), p["data_illeggibile"], r["_riga"]), titolo=_nome_file(r.get("file")))
        if tipologia:
            a["tipologie"].add("subentro" if "subentr" in tipologia else "ordinario")
        a["persone"] += 1
        a["righe"].append(r)

    risultato = []
    for a in atti.values():
        tip = a.pop("tipologie")
        if a["categoria"] == "scorrimento":
            a["sottotipo"] = None if not tip else ("misto" if len(tip) > 1 else tip.pop())
        if a["categoria"] != "bando" and a["numero_bando"] in numeri_fuori_ambito:
            a["in_ambito"] = False
        risultato.append(a)
    for foglio, categoria in (("bandi", "bando"), ("graduatorie", "graduatoria"), ("scorrimento", "scorrimento")):
        rapporto["fogli"][foglio]["atti"] = sum(1 for a in risultato if a["categoria"] == categoria)
        if foglio != "bandi":
            rapporto["fogli"][foglio]["fuori_ambito"] = sum(
                1 for a in risultato if a["categoria"] == categoria and not a["in_ambito"])
    return risultato


# --------------------------------------------------------------------------- versioni

def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def versione_in_uso(conn) -> dict | None:
    riga = conn.execute("SELECT * FROM segreteria_versione WHERE esito = 'in_uso' ORDER BY id DESC LIMIT 1").fetchone()
    return _versione(riga) if riga else None


def _versione(riga) -> dict:
    v = dict(riga)
    v["rapporto"] = json.loads(v["rapporto"]) if v["rapporto"] else None
    return v


def versioni(conn, limite: int = 50) -> list[dict]:
    return [_versione(r) for r in conn.execute("SELECT * FROM segreteria_versione ORDER BY id DESC LIMIT ?", (limite,))]


FOGLIO_DI = {"bando": "bandi", "graduatoria": "graduatorie", "scorrimento": "scorrimento"}

CAMPI_ATTO = ["categoria", "numero_bando", "codice_sotto", "codice_originale", "protocollo", "protocollo_originale",
              "data", "protocollo_privato", "data_privato", "sottotipo", "persone", "tipo_procedura", "titolo", "in_ambito"]


def importa(conn, contenuto: bytes, nome_file: str | None, utente: str | None) -> dict:
    """Salva una nuova versione in uso. Se il file non è valido registra il rifiuto e rilancia FileNonValido."""
    ora = _adesso()
    impronta = hashlib.sha256(contenuto or b"").hexdigest()
    try:
        righe, rapporto = leggi_file(contenuto)
        atti = costruisci_atti(righe, rapporto)
    except FileNonValido as e:
        conn.execute("INSERT INTO segreteria_versione (caricata_il, utente, nome_file, impronta, esito, rapporto) "
                     "VALUES (?, ?, ?, ?, 'rifiutata', ?)", (ora, utente, nome_file, impronta,
                                                            json.dumps({"errore": str(e)}, ensure_ascii=False)))
        raise

    numeri_bando = {r["numero_bando"]: r["id"] for r in conn.execute(
        "SELECT numero_bando, MIN(id) AS id FROM bando WHERE numero_bando IS NOT NULL GROUP BY numero_bando")}
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE segreteria_versione SET esito = 'precedente' WHERE esito = 'in_uso'")
        cur = conn.execute(
            "INSERT INTO segreteria_versione (caricata_il, utente, nome_file, impronta, esito, rapporto, righe, atti) "
            "VALUES (?, ?, ?, ?, 'in_uso', ?, ?, ?)",
            (ora, utente, nome_file, impronta, json.dumps(rapporto, ensure_ascii=False),
             sum(len(r) for r in righe.values()), len(atti)))
        versione_id = cur.lastrowid
        legate = set()
        for a in atti:
            valori = [a.get(c) for c in CAMPI_ATTO]
            cur = conn.execute(
                f"INSERT INTO segreteria_atto (versione_id, {', '.join(CAMPI_ATTO)}, bando_id) "
                f"VALUES (?, {', '.join('?' * len(CAMPI_ATTO))}, ?)",
                (versione_id, *valori, numeri_bando.get(a["numero_bando"])))
            for r in a["righe"]:
                legate.add((a["categoria"], r["_riga"]))
                conn.execute("INSERT INTO segreteria_riga (versione_id, foglio, numero_riga, valori, atto_id) "
                             "VALUES (?, ?, ?, ?, ?)",
                             (versione_id, FOGLIO_DI[a["categoria"]], r["_riga"],
                              json.dumps(r["_valori"], ensure_ascii=False, default=str), cur.lastrowid))
        # righe senza bando: conservate senza atto, per consultarle
        for foglio, lista in righe.items():
            categoria = next(c for c, f in FOGLIO_DI.items() if f == foglio)
            for r in lista:
                if (categoria, r["_riga"]) not in legate:
                    conn.execute("INSERT INTO segreteria_riga (versione_id, foglio, numero_riga, valori) VALUES (?, ?, ?, ?)",
                                 (versione_id, foglio, r["_riga"], json.dumps(r["_valori"], ensure_ascii=False, default=str)))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    log.info("File segreteria caricato: versione %s, %s atti", versione_id, len(atti))
    return _versione(conn.execute("SELECT * FROM segreteria_versione WHERE id = ?", (versione_id,)).fetchone())


def atti_versione(conn, versione_id: int, categoria: str | None = None, mese: str | None = None) -> list[dict]:
    where, args = ["versione_id = ?"], [versione_id]
    if categoria:
        where.append("categoria = ?")
        args.append(categoria)
    if mese:
        where.append("substr(data, 1, 7) = ?")
        args.append(mese)
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM segreteria_atto WHERE {' AND '.join(where)} ORDER BY data DESC, numero_bando", args)]


def collega_urp(conn, atti: list[dict]) -> None:
    """Link su URP di ogni atto: il documento con lo stesso protocollo, altrimenti la pagina del bando."""
    documenti, pagine = {}, {}
    for d in conn.execute("SELECT s.numero_bando, d.protocollo, d.url FROM documento d JOIN scheda s ON s.id = d.scheda_id "
                          "WHERE s.fonte = 'urp' AND s.presente = 1 AND d.presente = 1 AND d.url IS NOT NULL AND d.protocollo IS NOT NULL"):
        documenti.setdefault((d["numero_bando"], d["protocollo"]), d["url"])
    for s in conn.execute("SELECT numero_bando, url FROM scheda WHERE fonte = 'urp' AND presente = 1 AND url IS NOT NULL "
                          "ORDER BY codice_sotto IS NOT NULL, id"):
        pagine.setdefault(s["numero_bando"], s["url"])
    for a in atti:
        a["url_documento_urp"] = documenti.get((a["numero_bando"], a["protocollo"]))
        a["url_pagina_urp"] = pagine.get(a["numero_bando"])


def righe_atto(conn, atto_id: int) -> list[dict]:
    return [{"numero_riga": r["numero_riga"], "foglio": r["foglio"], "valori": json.loads(r["valori"])}
            for r in conn.execute("SELECT * FROM segreteria_riga WHERE atto_id = ? ORDER BY numero_riga", (atto_id,))]


def differenze(conn, versione_id: int) -> dict:
    """Atti nuovi, spariti e modificati rispetto alla versione valida precedente."""
    prec = conn.execute("SELECT id FROM segreteria_versione WHERE id < ? AND esito != 'rifiutata' ORDER BY id DESC LIMIT 1",
                        (versione_id,)).fetchone()
    if not prec:
        return {"precedente": None, "nuovi": [], "spariti": [], "modificati": []}
    chiave = lambda a: (a["categoria"], a["numero_bando"], a["codice_sotto"], a["protocollo"])  # noqa: E731
    nuovi = {chiave(a): a for a in atti_versione(conn, versione_id)}
    vecchi = {chiave(a): a for a in atti_versione(conn, prec["id"])}
    campi = ["data", "persone", "sottotipo", "protocollo_privato", "data_privato", "in_ambito"]
    modificati = []
    for k in sorted(set(nuovi) & set(vecchi), key=str):
        diff = {c: [vecchi[k][c], nuovi[k][c]] for c in campi if vecchi[k][c] != nuovi[k][c]}
        if diff:
            modificati.append({"chiave": dict(zip(("categoria", "numero_bando", "codice_sotto", "protocollo"), k)),
                               "campi": diff})
    pulisci = lambda a: {c: a[c] for c in ("categoria", "numero_bando", "codice_sotto", "protocollo", "data", "persone")}  # noqa: E731
    return {"precedente": prec["id"],
            "nuovi": [pulisci(nuovi[k]) for k in sorted(set(nuovi) - set(vecchi), key=str)],
            "spariti": [pulisci(vecchi[k]) for k in sorted(set(vecchi) - set(nuovi), key=str)],
            "modificati": modificati}


_COLONNA_BANDO = {"bandi": "bando", "graduatorie": "nbando", "scorrimento": "nbando"}


def _rapporto(conn, versione_id: int) -> dict:
    riga = conn.execute("SELECT rapporto FROM segreteria_versione WHERE id = ?", (versione_id,)).fetchone()
    return json.loads(riga["rapporto"]) if riga and riga["rapporto"] else {}


def storico_versioni(conn) -> list[dict]:
    """Versioni dalla più recente, con il numero progressivo e il riassunto delle differenze."""
    voci = versioni(conn)
    valide = sorted(v["id"] for v in voci if v["esito"] != "rifiutata")
    for v in voci:
        v["numero"] = valide.index(v["id"]) + 1 if v["id"] in valide else None
        d = differenze(conn, v["id"]) if v["id"] in valide else None
        v["differenze"] = {"precedente": d["precedente"], "nuovi": len(d["nuovi"]), "spariti": len(d["spariti"]),
                           "modificati": len(d["modificati"])} if d else None
    return voci


def problemi_righe(conn, versione_id: int) -> dict[str, list[dict]]:
    """Per ogni foglio, l'elenco "riga N, bando, problema" dal rapporto del file."""
    rapporto = _rapporto(conn, versione_id)
    risultato: dict[str, list[dict]] = {}
    for nome, info in (rapporto.get("fogli") or {}).items():
        valori = {r["numero_riga"]: json.loads(r["valori"]) for r in conn.execute(
            "SELECT numero_riga, valori FROM segreteria_riga WHERE versione_id = ? AND foglio = ?", (versione_id, nome))}

        def bando(riga: int):
            return next((v for c, v in valori.get(riga, {}).items() if _norm_intestazione(c) == _COLONNA_BANDO[nome] and v), None)
        risultato[nome] = [{"riga": riga, "bando": bando(riga), "problema": problema}
                           for problema, righe in (info.get("problemi") or {}).items() for riga in righe]
        risultato[nome].sort(key=lambda p: p["riga"])
    return risultato
