"""Registro delle difformità di ogni monitoraggio (spec 007): restano salvate dopo la correzione.

I rilievi sono gli stessi della pagina delle difformità (riepilogo.html, solleciti.js), così elenco, pagina
ed email dicono la stessa cosa. Niente dati dei candidati: solo protocolli e rilievi.
"""
import json
import logging
import re
import threading
from datetime import datetime, timezone

from . import atti, collegamento, compat, config, db, mensile, punteggi, raccolta
from .fonti.http import Client

log = logging.getLogger(__name__)
APERTA, CORRETTA, DA_CONTROLLARE = "aperta", "corretta", "da_controllare"
ATTI_SEGUITI = ("graduatoria", "scorrimento")
FONTI = {"sol": "Selezioni Online", "urp": "URP", "segreteria": "file di riepilogo della segreteria"}

_lock = threading.Lock()
_verifica: dict = {"in_corso": False}


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rilievi(riga: dict) -> list[str]:
    """Come rilievi() in solleciti.js."""
    atto = "la graduatoria" if riga["atto"] == "graduatoria" else "il provvedimento di assunzione idoneo (scorrimento/utilizzo della graduatoria)"
    testi = list(riga.get("note") or [])
    rif = f" (prot. {riga['protocollo']})" if riga.get("protocollo") else ""
    n_sol = riga.get("utilizzi_sol_codice") or 0
    for chiave, nome in FONTI.items():
        if (riga.get("fonti") or {}).get(chiave, {}).get("stato") == atti.MANCANTE:
            testo = f"{atto}{rif} non risulta tra i dati attualmente disponibili da {nome}"
            if chiave == "sol" and n_sol:
                testo += f" (per questo codice su Selezioni Online risulta{'no' if n_sol > 1 else ''} già {n_sol} utilizz{'i' if n_sol > 1 else 'o'})"
            testi.append(testo)
    return list(dict.fromkeys(t for t in testi if t))


def righe_correnti(conn, dal: str, al: str, tutti: bool = False) -> list[dict]:
    """Come righeGraduatoriaUnificate() in riepilogo.html: atti del periodo con i problemi dei punteggi.
    `tutti`: anche bandi e rettifiche, che il registro non segue."""
    righe = [r for r in atti.elenco_atti(conn, dal, al) if tutti or r["atto"] in ATTI_SEGUITI]
    righe = [r for r in righe if config.nel_monitoraggio(r.get("tipologia"))]
    if atti.fonti_in_attesa(conn):
        return righe
    for p in punteggi.elenco_periodo(conn, dal, al):
        if not dal <= (p.get("data") or "") <= al or not config.nel_monitoraggio(p.get("tipologia")):
            continue
        note = [n for n in (p.get("difformita") or []) if not re.search(r"scorrimento|assunzione idoneo", n, re.I)]
        stessa = lambda a: a["bando_id"] == p["bando_id"] if a.get("bando_id") and p.get("bando_id") else a.get("numero_bando") == p.get("numero_bando")  # noqa: E731
        candidate = [a for a in righe if a["atto"] == "graduatoria" and stessa(a)]
        esatte = [a for a in candidate if a.get("codice") == p.get("codice")
                  or (p.get("codice_sotto") and str(a.get("codice_sotto") or "") == str(p["codice_sotto"]))]
        con_data = [a for a in candidate if a.get("data") == p.get("data")]
        scelta = esatte if len(esatte) == 1 else con_data if len(con_data) == 1 else candidate if len(candidate) == 1 else []
        if scelta:
            a = scelta[0]
            a["codice"] = p.get("codice") or a.get("codice")
            esistenti = a.get("note") or []
            nuove = [n for n in note if not (n == "graduatoria non allegata su SOL"
                                             and any("senza documento pubblico" in x for x in esistenti))]
            a["note"] = list(dict.fromkeys([*esistenti, *nuove]))
            a["difforme"] = bool(a.get("difforme") or nuove)
        elif note:
            contesto = next((a for a in righe if stessa(a)), {})
            righe.append({"bando_id": p.get("bando_id"), "numero_bando": p.get("numero_bando"), "codice": p.get("codice"),
                          "tipologia": p.get("tipologia") or contesto.get("tipologia"), "titolo_bando": contesto.get("titolo_bando"), "atto": "graduatoria",
                          "data": p.get("data"), "protocollo": p.get("protocollo"), "note": list(dict.fromkeys(note)), "difforme": True,
                          "fonti": {"sol": {"stato": atti.PRESENTE if p.get("allegato_sol") else atti.MANCANTE, "protocollo": p.get("protocollo")}}})
    return righe


def _protocolli(riga: dict) -> set[str]:
    trovati = {str(c.get("protocollo")) for c in (riga.get("fonti") or {}).values() if c.get("protocollo")}
    return trovati | ({str(riga["protocollo"])} if riga.get("protocollo") else set())


def _fonti_affidabili(conn) -> bool:
    """Senza un'ultima raccolta riuscita per ogni fonte, un atto mancante può essere solo un guasto."""
    for fonte in ("urp", "sol"):
        ultima = conn.execute("SELECT esito FROM raccolta WHERE fonte = ? AND esito != 'in_corso' ORDER BY id DESC LIMIT 1",
                              (fonte,)).fetchone()
        if not ultima or ultima["esito"] == "fallita":
            return False
    return True


def _evento(conn, difformita_id: int, tipo: str, ora: str, origine: str, utente: str | None, dettaglio: str | None = None) -> None:
    conn.execute("INSERT INTO difformita_evento (difformita_id, quando, tipo, origine, utente, dettaglio) VALUES (?, ?, ?, ?, ?, ?)",
                 (difformita_id, ora, tipo, origine, utente, dettaglio))


def _corrisponde(e: dict, riga: dict, protocolli: set[str]) -> bool:
    if e["atto"] != riga["atto"] or (e["codice"] != riga.get("codice") and e["numero_bando"] != riga.get("numero_bando")):
        return False
    if set(json.loads(e["protocolli"] or "[]")) & protocolli:
        return True
    return not protocolli and e["data"] == riga.get("data")


def sincronizza(conn, mese: str, origine: str = "aggiornamento", utente: str | None = None) -> dict:
    """Allinea il registro ai dati attuali. Le versioni salvate alla chiusura non vengono toccate."""
    m = mensile.leggi(conn, mese)
    if not m or atti.fonti_in_attesa(conn):  # il registro resta com'è: riparte quando le raccolte finiscono
        return {}
    dal, al = mensile.periodo_dati(m)
    correnti = righe_correnti(conn, dal, al)
    affidabili = _fonti_affidabili(conn)
    ora = _adesso()
    variazioni = {"nuove": 0, "corrette": 0, "ricomparse": 0}
    conn.execute("BEGIN IMMEDIATE")
    try:
        registro = [dict(r) for r in conn.execute("SELECT * FROM difformita WHERE mese = ?", (mese,))]
        usate: set[int] = set()
        for riga in sorted(correnti, key=lambda r: not r.get("difforme")):  # prima le difformi
            protocolli = _protocolli(riga)
            e = next((x for x in registro if x["id"] not in usate and x["codice"] == riga.get("codice") and _corrisponde(x, riga, protocolli)), None) \
                or next((x for x in registro if x["id"] not in usate and _corrisponde(x, riga, protocolli)), None)
            testi = rilievi(riga)
            if e:
                usate.add(e["id"])
            if riga.get("difforme") and testi:
                testo = json.dumps(testi, ensure_ascii=False)
                if not e:
                    cur = conn.execute(
                        "INSERT INTO difformita (mese, numero_bando, codice, titolo_bando, tipologia, atto, data, protocollo, protocolli, "
                        "rilievi_iniziali, rilievi_attuali, stato, prima_rilevata_il, ultimo_controllo_il) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (mese, riga.get("numero_bando"), riga.get("codice"), riga.get("titolo_bando"), riga.get("tipologia"), riga["atto"],
                         riga.get("data"), riga.get("protocollo"), json.dumps(sorted(protocolli)), testo, testo, APERTA, ora, ora))
                    _evento(conn, cur.lastrowid, "rilevata", ora, origine, utente)
                    variazioni["nuove"] += 1
                    continue
                if e["stato"] != APERTA:
                    _evento(conn, e["id"], "ricomparsa", ora, origine, utente)
                    variazioni["ricomparse"] += 1
                elif e["rilievi_attuali"] != testo:
                    _evento(conn, e["id"], "cambiata", ora, origine, utente, testo)
                unione = sorted(set(json.loads(e["protocolli"] or "[]")) | protocolli)
                conn.execute("UPDATE difformita SET stato = ?, rilievi_attuali = ?, protocolli = ?, corretta_il = NULL, ultimo_controllo_il = ? WHERE id = ?",
                             (APERTA, testo, json.dumps(unione), ora, e["id"]))
            elif e:
                if affidabili and e["stato"] != CORRETTA:
                    conn.execute("UPDATE difformita SET stato = ?, rilievi_attuali = '[]', corretta_il = ?, ultimo_controllo_il = ? WHERE id = ?",
                                 (CORRETTA, ora, ora, e["id"]))
                    _evento(conn, e["id"], "corretta", ora, origine, utente)
                    variazioni["corrette"] += 1
                else:
                    conn.execute("UPDATE difformita SET ultimo_controllo_il = ? WHERE id = ?", (ora, e["id"]))
        for e in registro:
            if e["id"] in usate:
                continue
            if affidabili and e["stato"] == APERTA:  # l'atto non si trova più: non è una correzione accertata
                conn.execute("UPDATE difformita SET stato = ?, ultimo_controllo_il = ? WHERE id = ?", (DA_CONTROLLARE, ora, e["id"]))
                _evento(conn, e["id"], "non_trovata", ora, origine, utente)
        conn.execute("UPDATE monitoraggio_mese SET difformita_aggiornate_il = ? WHERE mese = ?", (ora, mese))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return {**variazioni, "fonti_affidabili": affidabili}


def sincronizza_tutti(origine: str = "aggiornamento") -> None:
    """Dopo ogni aggiornamento dei dati. Un errore qui non deve mai far fallire la raccolta."""
    conn = db.connetti()
    db.inizializza(conn)
    try:
        for r in conn.execute("SELECT mese FROM monitoraggio_mese").fetchall():
            sincronizza(conn, r["mese"], origine)
    except Exception:
        log.exception("Aggiornamento del registro delle difformità non riuscito")
    finally:
        conn.close()


def reimposta(conn, mese: str) -> None:
    """Il mese dei dati è cambiato: il registro riguardava un altro periodo."""
    conn.execute("DELETE FROM difformita_evento WHERE difformita_id IN (SELECT id FROM difformita WHERE mese = ?)", (mese,))
    conn.execute("DELETE FROM difformita WHERE mese = ?", (mese,))


def _voce(conn, e: dict, solleciti: dict) -> dict:
    iniziali, attuali = json.loads(e["rilievi_iniziali"]), json.loads(e["rilievi_attuali"])
    voci_rilievo = [{"testo": t, "risolto": t not in attuali and e["stato"] != DA_CONTROLLARE} for t in iniziali] + \
                   [{"testo": t, "risolto": False, "nuovo": True} for t in attuali if t not in iniziali]
    risolti = sum(r["risolto"] for r in voci_rilievo)
    if e["stato"] == CORRETTA:
        badge = "corretta"
    elif e["stato"] == DA_CONTROLLARE:
        badge = "da_controllare"
    else:
        badge = "parziale" if risolti else "da_correggere"
    sollecito = solleciti.get(e["codice"] or "") or solleciti.get(e["numero_bando"] or "")
    return {**{k: e[k] for k in ("id", "numero_bando", "codice", "titolo_bando", "tipologia", "atto", "data", "protocollo",
                                 "stato", "prima_rilevata_il", "corretta_il", "ultimo_controllo_il")},
            "n_gestione": mensile.numero_gestione(conn, e["codice"] or e["numero_bando"] or str(e["id"])),
            "badge": badge, "rilievi": voci_rilievo,
            "sollecito": {k: sollecito[k] for k in ("stato", "autore", "quando")} if sollecito else None,
            "storico": [dict(x) for x in conn.execute(
                "SELECT quando, tipo, origine, utente FROM difformita_evento WHERE difformita_id = ? ORDER BY id DESC", (e["id"],))]}


def elenco(conn, mese: str) -> dict:
    m = mensile.leggi(conn, mese)
    if m and not m.get("difformita_aggiornate_il"):
        sincronizza(conn, mese, "primo controllo")
        m = mensile.leggi(conn, mese)
    solleciti = mensile.solleciti(conn, mese)
    voci = [_voce(conn, dict(e), solleciti) for e in conn.execute(
        "SELECT * FROM difformita WHERE mese = ? ORDER BY stato = 'corretta', data DESC, codice", (mese,))]
    conteggi = {b: sum(v["badge"] == b for v in voci) for b in ("da_correggere", "parziale", "corretta", "da_controllare")}
    fonti = {f: compat.ultima_riuscita(conn, f) for f in ("urp", "sol")}
    return {"voci": voci, "totale": len(voci), "conteggi": conteggi, "ultimo_controllo": m.get("difformita_aggiornate_il") if m else None,
            "fonti": fonti, "fonti_affidabili": _fonti_affidabili(conn), "fonti_in_attesa": atti.fonti_in_attesa(conn), "verifica": stato_verifica()}


def stato_verifica() -> dict:
    with _lock:
        return dict(_verifica)


def _bandi_da_verificare(conn, mese: str, ids: list[int] | None) -> list[dict]:
    if ids is not None:
        segnaposto = ", ".join("?" * len(ids)) or "NULL"
        righe = conn.execute(f"SELECT numero_bando, codice FROM difformita WHERE mese = ? AND id IN ({segnaposto})", (mese, *ids))
    else:
        righe = conn.execute("SELECT numero_bando, codice FROM difformita WHERE mese = ? AND stato != 'corretta'", (mese,))
    unici = {}
    for r in righe.fetchall():
        unici.setdefault(r["numero_bando"] or r["codice"], {"numero_bando": r["numero_bando"], "codice": r["codice"]})
    return list(unici.values())


def avvia_verifica(mese: str, ids: list[int] | None, intestazioni: dict | None, utente: str | None) -> bool:
    """Rilegge le fonti per i bandi interessati in background. False se una verifica è già in corso."""
    with _lock:
        if _verifica.get("in_corso"):
            return False
        _verifica.clear()
        _verifica.update(in_corso=True, mese=mese, fatti=0, totale=0, errori=[], punteggi_riletti=False, risultato=None)
    threading.Thread(target=_esegui_verifica, args=(mese, ids, intestazioni, utente), daemon=True, name="verifica-difformita").start()
    return True


def _esegui_verifica(mese: str, ids, intestazioni, utente) -> None:
    conn = db.connetti()
    db.inizializza(conn)
    errori: list[str] = []
    risultato = None
    try:
        bandi = _bandi_da_verificare(conn, mese, ids)
        with _lock:
            _verifica["totale"] = len(bandi)
        client_sol, client_urp = Client(config.pausa_sol()), Client(config.pausa_urp())
        dal, al = mensile.periodo_dati(mensile.leggi(conn, mese))
        da_rileggere = set()
        for bando in bandi:
            errori += raccolta.aggiorna_bando(conn, bando["numero_bando"], bando["codice"], client_sol, client_urp)
            da_rileggere.add(bando["numero_bando"] or bando["codice"])
            with _lock:
                _verifica["fatti"] += 1
                _verifica["errori"] = list(errori)
        collegamento.collega(conn)
        riletti = False
        if intestazioni:
            schede = [s for s in punteggi.schede_periodo(conn, dal, al)
                      if s["numero_bando"] in da_rileggere or s["codice_originale"] in da_rileggere]
            esito = punteggi.verifica_schede(conn, schede, dal, al, intestazioni, client_sol)
            riletti = esito.get("esito") == "completata"
            if not riletti:
                errori.append(esito.get("messaggio") or "Verifica dei punteggi non riuscita")
        risultato = sincronizza(conn, mese, "verifica manuale", utente)
        with _lock:
            _verifica["punteggi_riletti"] = riletti
    except punteggi.VerificaInCorso:
        errori.append("Verifica dei punteggi già in corso: i punteggi non sono stati riletti")
        risultato = sincronizza(conn, mese, "verifica manuale", utente)
    except Exception as e:
        log.exception("Verifica delle difformità non riuscita")
        errori.append(f"Verifica non completata ({type(e).__name__})")
    finally:
        conn.close()
        with _lock:
            _verifica.update(in_corso=False, errori=errori, risultato=risultato, fine=_adesso())
