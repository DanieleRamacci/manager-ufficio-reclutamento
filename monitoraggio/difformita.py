"""Registro delle difformità di ogni monitoraggio (spec 007): restano salvate dopo la correzione.

I rilievi sono gli stessi della pagina delle difformità (riepilogo.html, solleciti.js), così elenco, pagina
ed email dicono la stessa cosa. Niente dati dei candidati: solo protocolli e rilievi.
"""
import json
import logging
import re
import threading
from datetime import datetime, timezone

from . import atti, collegamento, compat, config, db, mensile, punteggi, raccolta, sedi
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
    atto = "la graduatoria pubblica (oscurata)" if riga["atto"] == "graduatoria" else "il provvedimento di assunzione idoneo (scorrimento/utilizzo della graduatoria)"
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
    famiglie = sedi.famiglie(conn)
    figli = {s["id"]: f for f in famiglie.values() for s in f["figli"]}
    padri = {f["padre"]["id"] for f in famiglie.values()}
    per_riga: dict = {}  # le verifiche dei punteggi finite su ogni riga: un atto unico può valere per più sedi
    for p in punteggi.elenco_periodo(conn, dal, al):
        if p.get("scheda_id") in padri or not dal <= (p.get("data") or "") <= al or not config.nel_monitoraggio(p.get("tipologia")):
            continue  # il padre non ha candidati: i punteggi stanno sui sotto-bandi
        note = [n for n in (p.get("difformita") or []) if not re.search(r"scorrimento|assunzione idoneo", n, re.I)]
        stessa = lambda a: a["bando_id"] == p["bando_id"] if a.get("bando_id") and p.get("bando_id") else a.get("numero_bando") == p.get("numero_bando")  # noqa: E731
        candidate = [a for a in righe if a["atto"] == "graduatoria" and stessa(a)]
        esatte = [a for a in candidate if a.get("codice") == p.get("codice")
                  or (p.get("codice_sotto") and str(a.get("codice_sotto") or "") == str(p["codice_sotto"]))]
        con_data = [a for a in candidate if a.get("data") == p.get("data")]
        scelta = esatte if len(esatte) == 1 else con_data if len(con_data) == 1 else candidate if len(candidate) == 1 else []
        if p.get("scheda_id") in figli:  # un sotto-bando va solo sulla riga dell'atto che vale per quella sede
            proprie = [a for a in candidate if p["scheda_id"] in (a.get("sedi_ids") or ())]
            scelta = [a for a in proprie if a.get("data") == p.get("data")][:1] or (proprie if len(proprie) == 1 else [])
        if scelta:
            per_riga.setdefault(id(scelta[0]), (scelta[0], []))[1].append((p, note))
        elif note:
            contesto = next((a for a in righe if stessa(a)), {})
            righe.append({"bando_id": p.get("bando_id"), "numero_bando": p.get("numero_bando"), "codice": p.get("codice"),
                          "tipologia": p.get("tipologia") or contesto.get("tipologia"), "titolo_bando": contesto.get("titolo_bando"), "atto": "graduatoria",
                          "data": p.get("data"), "protocollo": p.get("protocollo"), "note": list(dict.fromkeys(note)), "difforme": True,
                          "fonti": {"sol": {"stato": atti.PRESENTE if p.get("allegato_sol") else atti.MANCANTE, "protocollo": p.get("protocollo")}}})
    for a, verifiche in per_riga.values():
        _applica_verifiche(a, verifiche, famiglie.get(a.get("bando_id")))
    return righe


NON_ALLEGATA = "graduatoria pubblica (oscurata) non allegata su SOL"
_SEDE_NEL_CODICE = re.compile(r"\s+-\s+\d{2}\b.*$")
_PREFISSO_SEDE = re.compile(r"^sede «[^»]*»: ")


def _applica_verifiche(a: dict, verifiche: list[tuple[dict, list[str]]], famiglia: dict | None) -> None:
    """Una sola sede: la riga prende codice, link e RdP di quella sede. Più sedi (una graduatoria unica per tutte):
    la riga vale per il bando e ogni rilievo dice di quale sede è, altrimenti i conteggi sembrano in contraddizione."""
    # la scheda madre di un bando a più sedi non ha candidati: conta solo se non ci sono sedi
    ids_figli = {s["id"] for s in famiglia["figli"]} if famiglia else set()
    reali = [v for v in verifiche if v[0].get("scheda_id") in ids_figli or (not famiglia and _SEDE_NEL_CODICE.search(v[0].get("codice") or ""))] or verifiche
    sedi = list(dict.fromkeys(p.get("codice") for p, _ in reali if p.get("codice")))
    piu_sedi = len(sedi) > 1 or len(a.get("sedi_ids") or ()) > 1
    esistenti = a.get("note") or []
    if piu_sedi:  # le note della scheda principale sono le stesse di una sede: restano solo quelle con il nome della sede
        dalle_sedi = {n for _, note in verifiche for n in note}
        esistenti = [x for x in esistenti if x not in dalle_sedi]
    nuove = []
    for p, note in verifiche:
        for n in note:
            if n == NON_ALLEGATA:
                if not (a["fonti"]["sol"]["stato"] == atti.MANCANTE or any("senza documento pubblico" in x for x in esistenti)):
                    nuove.append(n)
            else:
                nuove.append(f"sede «{p['codice']}»: {n}" if piu_sedi and p.get("codice") else n)
    a["note"] = list(dict.fromkeys([*esistenti, *nuove]))
    a["difforme"] = bool(a.get("difforme") or nuove)
    if a.get("titolo_bando") and (piu_sedi or (sedi and sedi[0] not in a["titolo_bando"])):
        a["titolo_bando"] = _SEDE_NEL_CODICE.sub("", a["titolo_bando"])
    sol = a["fonti"]["sol"]
    if piu_sedi:
        if not famiglia:
            a["codice"] = re.split(r"\s+-\s+", sedi[0])[0]
        esiti = [p.get("esito") for p, _ in reali]
        if esiti and all(e and e != "errore" for e in esiti):  # il controllo vale se è stato fatto su tutte le sedi
            somma = lambda k: sum(p.get(k) or 0 for p, _ in reali)  # noqa: E731
            a["punteggi"] = {"domande": somma("domande"), "con_punteggi": somma("con_punteggi"), "esito": next((e for e in esiti if e != "completi"), "completi"),
                             "verificato_il": min(p.get("verificato_il") or "" for p, _ in reali), "scheda_id": None, "candidati": False}
            a["punteggi_da_verificare"] = False
        else:
            a["punteggi"], a["punteggi_da_verificare"] = None, True
        persone = {(r.get("email") or f"{r.get('nome')} {r.get('cognome')}"): r for p, _ in verifiche for r in p.get("rdp") or []}
        if persone:
            a["rdp"], a["rdp_origine"] = list(persone.values()), "bando"
        a["link_codice"], a["url_punteggi"] = None, None
        if sol.get("stato") != atti.PRESENTE and famiglia:
            sol["url"] = famiglia["padre"]["url"]
    elif reali:
        p = reali[0][0]
        a["codice"] = p.get("codice") or a.get("codice")
        if p.get("rdp"):
            a["rdp"], a["rdp_origine"] = p["rdp"], "codice"
        a["url_punteggi"] = p.get("url_punteggi") or a.get("url_punteggi")
        if p.get("url"):
            a["link_codice"] = p["url"]
            if sol.get("stato") != atti.PRESENTE:
                sol["url"] = p["url"]


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
                testo = json.dumps([*testi, *_rilievi_da_tenere(e, riga, testi, affidabili)], ensure_ascii=False)
                unione = sorted(set(json.loads(e["protocolli"] or "[]")) | protocolli)
                conn.execute("UPDATE difformita SET stato = ?, rilievi_attuali = ?, protocolli = ?, corretta_il = NULL, ultimo_controllo_il = ? WHERE id = ?",
                             (APERTA, testo, json.dumps(unione), ora, e["id"]))
            elif e:
                tenuti = _rilievi_da_tenere(e, riga, [], affidabili) if e["stato"] == APERTA else []
                if tenuti:
                    conn.execute("UPDATE difformita SET rilievi_attuali = ?, ultimo_controllo_il = ? WHERE id = ?",
                                 (json.dumps(tenuti, ensure_ascii=False), ora, e["id"]))
                elif affidabili and e["stato"] != CORRETTA:
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


def _chiave_rilievo(testo: str) -> str:
    """Lo stesso problema con un testo un po' diverso (protocollo, conteggi) non è un problema risolto più uno nuovo."""
    if testo.startswith("nota per il monitoraggio"):
        return "nota per il monitoraggio"
    testo = re.sub(r"\s*\((?:prot\.[^)]*|[^)]*candidati[^)]*|per questo codice[^)]*)\)", "", testo)
    return testo.replace("graduatoria pubblica (oscurata) non allegata su SOL",
                         "la graduatoria pubblica (oscurata) non risulta tra i dati attualmente disponibili da Selezioni Online")


def _presente(riga: dict, fonte: str) -> bool:
    return (riga.get("fonti") or {}).get(fonte, {}).get("stato") == atti.PRESENTE


def _correzione_accertata(testo: str, riga: dict) -> bool:
    """Un rilievo sparito conta come corretto solo con una prova: una lettura fallita o un file non caricato lo fanno sparire senza esserlo."""
    if "non risulta tra i dati" in testo:
        return next((_presente(riga, f) for f, nome in FONTI.items() if testo.endswith(f"da {nome}") or f"da {nome} (" in testo), False)
    if "non allegata su SOL" in testo or "senza documento pubblico" in testo:
        return _presente(riga, "sol")
    if testo.startswith("protocollo diverso"):
        return len({c.get("protocollo") for c in (riga.get("fonti") or {}).values() if c.get("stato") == atti.PRESENTE and c.get("protocollo")}) == 1
    if testo.startswith(("tipologia da completare", "nota per il monitoraggio")):
        return _presente(riga, "segreteria")
    if re.search(r"punteggi|candidati|esito \(|domand|assunzione idoneo", testo, re.I):
        return (riga.get("punteggi") or {}).get("esito") not in (None, "errore")
    return False


def _rilievi_da_tenere(e: dict, riga: dict, testi: list[str], affidabili: bool) -> list[str]:
    """I rilievi passati non più rilevati ma senza prova di correzione: restano aperti."""
    tenuti, viste = [], {_chiave_rilievo(t) for t in testi}
    viste |= {_PREFISSO_SEDE.sub("", k) for k in viste}  # il vecchio testo senza sede è lo stesso rilievo
    for t in [*json.loads(e["rilievi_attuali"]), *json.loads(e["rilievi_iniziali"])]:
        chiave = _chiave_rilievo(t)
        if chiave not in viste and not (affidabili and _correzione_accertata(t, riga)):
            viste.add(chiave)
            tenuti.append(t)
    return tenuti


def _stato_rilievi(e: dict) -> tuple[list[dict], str]:
    """I rilievi di una voce del registro, con quelli risolti spuntati, e il suo stato per la pagina."""
    iniziali, attuali = json.loads(e["rilievi_iniziali"]), json.loads(e["rilievi_attuali"])
    correnti = {_chiave_rilievo(t): t for t in attuali}
    per_sede = {_PREFISSO_SEDE.sub("", k) for k in correnti if _PREFISSO_SEDE.match(k)}
    voci_rilievo, viste = [], set()
    for t in iniziali:
        chiave = _chiave_rilievo(t)
        if chiave in per_sede:  # ora detto sede per sede: non è risolto, lo mostrano le voci delle sedi
            continue
        if chiave not in viste:
            viste.add(chiave)
            voci_rilievo.append({"testo": correnti[chiave], "risolto": False} if chiave in correnti
                                else {"testo": t, "risolto": e["stato"] != DA_CONTROLLARE})
    for t in attuali:
        if _chiave_rilievo(t) not in viste:
            viste.add(_chiave_rilievo(t))
            voci_rilievo.append({"testo": t, "risolto": False, "nuovo": _PREFISSO_SEDE.sub("", _chiave_rilievo(t)) not in {_chiave_rilievo(i) for i in iniziali}})
    risolti = sum(r["risolto"] for r in voci_rilievo)
    if e["stato"] == CORRETTA:
        badge = "corretta"
    elif e["stato"] == DA_CONTROLLARE:
        badge = "da_controllare"
    else:
        badge = "parziale" if risolti else "da_correggere"
    return voci_rilievo, badge


def registro_per_righe(conn, mese: str, righe: list[dict]) -> None:
    """Aggiunge alle righe del monitoraggio la loro voce del registro, abbinata come in sincronizza()."""
    m = mensile.leggi(conn, mese)
    if m and not m.get("difformita_aggiornate_il"):
        sincronizza(conn, mese, "primo controllo")
    registro = [dict(r) for r in conn.execute("SELECT * FROM difformita WHERE mese = ?", (mese,))]
    usate: set[int] = set()
    for riga in sorted((r for r in righe if r["atto"] in ATTI_SEGUITI), key=lambda r: not r.get("difforme")):
        protocolli = _protocolli(riga)
        e = next((x for x in registro if x["id"] not in usate and x["codice"] == riga.get("codice") and _corrisponde(x, riga, protocolli)), None) \
            or next((x for x in registro if x["id"] not in usate and _corrisponde(x, riga, protocolli)), None)
        if e:
            usate.add(e["id"])
            voci, badge = _stato_rilievi(e)
            riga["registro"] = {"id": e["id"], "badge": badge, "corretta_il": e["corretta_il"], "rilievi": voci}


def _rdp_per_bando(conn) -> tuple[dict, dict]:
    per_codice, per_bando = {}, {}
    for r in conn.execute("SELECT s.codice_originale, s.numero_bando, r.nome, r.cognome, r.email FROM referente r JOIN scheda s ON s.id = r.scheda_id "
                          "WHERE r.attivo = 1 AND s.fonte = 'sol' ORDER BY r.cognome, r.nome"):
        persona = {"nome": r["nome"], "cognome": r["cognome"], "email": r["email"]}
        for mappa, chiave in ((per_codice, r["codice_originale"]), (per_bando, r["numero_bando"])):
            if persona not in mappa.setdefault(chiave, []):
                mappa[chiave].append(persona)
    return per_codice, per_bando


def _voce(conn, e: dict, solleciti: dict, rdp: tuple[dict, dict]) -> dict:
    voci_rilievo, badge = _stato_rilievi(e)
    sollecito = solleciti.get(e["codice"] or "") or solleciti.get(e["numero_bando"] or "")
    return {**{k: e[k] for k in ("id", "numero_bando", "codice", "titolo_bando", "tipologia", "atto", "data", "protocollo",
                                 "stato", "prima_rilevata_il", "corretta_il", "ultimo_controllo_il")},
            "n_gestione": mensile.numero_gestione(conn, e["codice"] or e["numero_bando"] or str(e["id"])),
            "badge": badge, "rilievi": voci_rilievo, "rdp": rdp[0].get(e["codice"]) or rdp[1].get(e["numero_bando"]) or [],
            "sollecito": {k: sollecito[k] for k in ("stato", "autore", "quando")} if sollecito else None,
            "storico": [dict(x) for x in conn.execute(
                "SELECT quando, tipo, origine, utente FROM difformita_evento WHERE difformita_id = ? ORDER BY id DESC", (e["id"],))]}


def elenco(conn, mese: str) -> dict:
    m = mensile.leggi(conn, mese)
    if m and not m.get("difformita_aggiornate_il"):
        sincronizza(conn, mese, "primo controllo")
        m = mensile.leggi(conn, mese)
    solleciti = mensile.solleciti(conn, mese)
    rdp = _rdp_per_bando(conn)
    voci = [_voce(conn, dict(e), solleciti, rdp) for e in conn.execute(
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
