"""Punteggi delle graduatorie pubblicate su Selezioni Online in un periodo (spec 004).

Per ogni scheda SOL con graduatoria nel periodo si leggono, con la sessione dell'utente, le domande
e i candidati con i punteggi (esito V vincitore, I idoneo, S scorrimento; protocollo della
graduatoria). Nel database vanno solo i conteggi; l'elenco dei candidati resta in memoria per la
sessione e finisce solo nella pagina e nell'Excel scaricato (constitution, Principio II).
"""
import calendar
import io
import json
import logging
import threading
from datetime import datetime, timezone

from . import config, referenti
from .fonti import sol_auth
from .fonti.http import Client, FonteErrore
from .fonti.sol import url_punteggi
from .normalizza import data_iso, protocollo

log = logging.getLogger(__name__)
_in_corso = threading.Lock()
_candidati: dict[int, dict] = {}   # scheda_id -> {"verificato_il", "candidati"} (solo in memoria)

ESITI_CANDIDATO = {"V": "vincitori", "I": "idonei", "S": "scorrimento"}


class VerificaInCorso(Exception):
    pass


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def intervallo(mese: str) -> tuple[str, str]:
    anno, m = map(int, mese.split("-"))
    return f"{mese}-01", f"{mese}-{calendar.monthrange(anno, m)[1]:02d}"


def esito(domande: int, con_punteggi: int, senza_protocollo: int = 0) -> str:
    if domande == 0:
        return "nessuna_domanda"
    if con_punteggi == 0:
        return "mancanti"
    if senza_protocollo:
        # graduatoria caricata tra gli allegati ma punteggi non completati (manca il protocollo)
        return "protocollo_mancante"
    return "completi" if con_punteggi >= domande else "parziali"


def conteggi_candidati(candidati: list[dict], protocollo_rif: str | None = None, data_rif: str | None = None) -> dict:
    """Conteggi per esito e difformità rispetto alla graduatoria nota (protocollo e data di riferimento)."""
    c = {"vincitori": 0, "idonei": 0, "scorrimento": 0, "senza_protocollo": 0, "senza_esito": 0,
         "protocollo_diverso": 0, "data_diversa": 0}
    rif = protocollo(protocollo_rif)
    for x in candidati:
        esito_x = (x.get("esito") or "").strip().upper()
        if not esito_x:
            c["senza_esito"] += 1
        elif ESITI_CANDIDATO.get(esito_x):
            c[ESITI_CANDIDATO[esito_x]] += 1
        prot = protocollo(x.get("numero_protocollo_graduatoria"))
        if not prot:
            c["senza_protocollo"] += 1
        elif rif and prot != rif:
            c["protocollo_diverso"] += 1
        data = data_iso(x.get("data_protocollo_graduatoria"))
        if prot and data and data_rif and data != data_rif:
            c["data_diversa"] += 1
    return c


def scorrimenti_candidati(candidati: list[dict]) -> dict:
    """Protocolli di assunzione idoneo registrati su SOL: {protocollo: {"n", "date"}}, "" = candidati S senza
    protocollo; "non_s" conta chi ha il protocollo di assunzione ma esito diverso da S. Niente nominativi."""
    per_prot: dict[str, dict] = {}
    non_s = 0
    for x in candidati:
        prot = protocollo(x.get("numero_protocollo_assunzione_idoneo")) or ""
        s = (x.get("esito") or "").strip().upper() == "S"
        if not s:
            non_s += bool(prot)
            continue
        voce = per_prot.setdefault(prot, {"n": 0, "date": []})
        voce["n"] += 1
        data = data_iso(x.get("data_protocollo_assunzione_idoneo"))
        if data and data not in voce["date"]:
            voce["date"].append(data)
    return {"protocolli": per_prot, "non_s": non_s}


def scorrimenti_noti(conn, s) -> list[dict]:
    """Atti di scorrimento del codice secondo le fonti (allegati SOL, URP, file della segreteria) dal inizio del
    monitoraggio, raggruppati per data: {"data", "protocolli", "fonti"}."""
    from .normalizza import codice_sotto

    dal = config.monitoraggio_dal().isoformat()
    gruppi: dict[str, dict] = {}

    def aggiungi(data, prot, fonte):
        if prot:
            g = gruppi.setdefault(data or "", {"data": data, "protocolli": set(), "fonti": set()})
            g["protocolli"].add(prot)
            g["fonti"].add(fonte)

    for d in conn.execute("SELECT protocollo, data_protocollo FROM documento WHERE scheda_id = ? AND presente = 1 "
                          "AND categoria = 'scorrimento' AND data_protocollo >= ?", (s["id"], dal)):
        aggiungi(d["data_protocollo"], d["protocollo"], "sol")
    if s["bando_id"] is not None:
        for d in conn.execute(
                "SELECT d.protocollo, d.data_protocollo, d.titolo FROM documento d JOIN scheda x ON x.id = d.scheda_id "
                "WHERE x.bando_id = ? AND x.fonte = 'urp' AND d.presente = 1 AND d.categoria = 'scorrimento' "
                "AND d.data_protocollo >= ?", (s["bando_id"], dal)):
            sotto = codice_sotto(d["titolo"])
            if not (sotto and s["codice_sotto"] and sotto != s["codice_sotto"]):
                aggiungi(d["data_protocollo"], d["protocollo"], "urp")
    for a in conn.execute(
            "SELECT a.protocollo, a.data, a.codice_sotto FROM segreteria_atto a JOIN segreteria_versione v "
            "ON v.id = a.versione_id WHERE v.esito = 'in_uso' AND a.in_ambito = 1 AND a.categoria = 'scorrimento' "
            "AND a.numero_bando = ? AND a.data >= ?", (s["numero_bando"], dal)):
        if not (a["codice_sotto"] and s["codice_sotto"] and a["codice_sotto"] != s["codice_sotto"]):
            aggiungi(a["data"], a["protocollo"], "segreteria")
    return sorted(gruppi.values(), key=lambda g: g["data"] or "")


def stato_scorrimento(gruppo: dict, sol: dict | None) -> dict:
    """Confronto di un atto di scorrimento delle fonti con i candidati S su SOL."""
    if sol is None:
        return {"registrato": None, "candidati": None, "data_diversa": False}
    trovati = [sol["protocolli"][p] for p in gruppo["protocolli"] if p in sol["protocolli"]]
    date = {d for v in trovati for d in v["date"]}
    return {"registrato": bool(trovati), "candidati": sum(v["n"] for v in trovati),
            "data_diversa": bool(gruppo["data"] and date and date != {gruppo["data"]})}


def difformita_scorrimenti(sol: dict | None, noti: list[dict], dal: str, al: str) -> list[str]:
    """Difformità degli scorrimenti: candidati S su SOL senza protocollo o con protocollo/data che non
    tornano con le fonti; scorrimenti delle fonti nel periodo senza nessun candidato S su SOL."""
    if sol is None:
        return []
    d = []
    prot_noti = {p: g for g in noti for p in g["protocolli"]}
    if sol["protocolli"].get("", {}).get("n"):
        d.append(f"protocollo assunzione idoneo non valorizzato su SOL ({sol['protocolli']['']['n']} candidati S)")
    for p, v in sorted(sol["protocolli"].items()):
        if not p:
            continue
        if p not in prot_noti:
            if any(x >= config.monitoraggio_dal().isoformat() for x in v["date"]) or not v["date"]:
                d.append(f"scorrimento prot. {p} su SOL non presente nelle altre fonti ({v['n']} candidati S)")
        elif prot_noti[p]["data"] and v["date"] and set(v["date"]) != {prot_noti[p]["data"]}:
            d.append(f"data assunzione idoneo prot. {p} diversa su SOL: "
                     f"{', '.join(_data_it(x) for x in v['date'])} invece di {_data_it(prot_noti[p]['data'])}")
    for g in noti:
        if dal <= (g["data"] or "") <= al and not stato_scorrimento(g, sol)["registrato"]:
            d.append(f"scorrimento prot. {'/'.join(sorted(g['protocolli']))} del {_data_it(g['data'])} "
                     f"non registrato su SOL (nessun candidato S con questo protocollo)")
    if sol.get("non_s"):
        d.append(f"protocollo assunzione idoneo valorizzato ma esito diverso da S ({sol['non_s']} candidati)")
    return d


def difformita(v: dict | None) -> list[str]:
    """Difformità di SOL rispetto alle fonti, dalla verifica dei punteggi (da segnalare in rosso)."""
    if not v or not v.get("esito"):
        return []
    if v["esito"] == "errore":
        return ["verifica dei punteggi su SOL non riuscita"]
    d = []
    if v["esito"] == "nessuna_domanda":
        d.append("nessuna domanda inviata su SOL")
    elif v["esito"] == "mancanti":
        d.append("mancano i punteggi su SOL")
    elif v["esito"] == "parziali":
        d.append(f"punteggi su SOL solo per {v['con_punteggi']} domande su {v['domande']}")
    if v.get("senza_protocollo"):
        d.append(f"protocollo graduatoria non valorizzato su SOL ({v['senza_protocollo']} candidati)")
    if v.get("senza_esito"):
        d.append(f"esito (V/I/S) mancante su SOL ({v['senza_esito']} candidati)")
    if v.get("protocollo_diverso"):
        d.append(f"protocollo graduatoria diverso su SOL ({v['protocollo_diverso']} candidati)")
    if v.get("data_diversa"):
        d.append(f"data protocollo graduatoria diversa su SOL ({v['data_diversa']} candidati)")
    return d


def schede_periodo(conn, dal: str, al: str) -> list:
    """Schede SOL delle graduatorie del periodo, da qualunque fonte le conosciamo:
    allegato di graduatoria su SOL o data della graduatoria su SOL, documento di graduatoria su URP,
    riga di graduatoria nel file della segreteria (versione in uso). Per i bandi con più codici si
    prende la scheda del codice indicato dal documento o dal file, se c'è. Allo stesso modo entrano le schede
    con uno scorrimento nel periodo, per controllare i candidati S."""
    from .normalizza import codice_sotto

    schede = {}
    for s in conn.execute(
            "SELECT DISTINCT s.* FROM scheda s WHERE s.fonte = 'sol' AND s.presente = 1 AND ("
            "  s.data_pubbl_graduatoria BETWEEN :dal AND :al OR EXISTS (SELECT 1 FROM documento d WHERE d.scheda_id = s.id "
            "  AND d.presente = 1 AND d.categoria IN ('graduatoria', 'scorrimento') AND d.data_protocollo BETWEEN :dal AND :al))",
            {"dal": dal, "al": al}):
        schede[s["id"]] = s

    sol = conn.execute("SELECT * FROM scheda WHERE fonte = 'sol' AND presente = 1 AND bando_id IS NOT NULL").fetchall()
    per_bando = {}
    for s in sol:
        per_bando.setdefault(s["bando_id"], []).append(s)
    per_numero = {s["numero_bando"]: s["bando_id"] for s in sol if s["numero_bando"]}

    def aggiungi(bando_id, sotto):
        candidate = per_bando.get(bando_id, [])
        scelte = [s for s in candidate if sotto and s["codice_sotto"] == sotto] or \
                 [s for s in candidate if not s["codice_sotto"]] or candidate[:1]
        for s in scelte[:1]:
            schede.setdefault(s["id"], s)

    # graduatorie e scorrimenti su URP nel periodo
    for d in conn.execute(
            "SELECT s.bando_id, d.titolo FROM documento d JOIN scheda s ON s.id = d.scheda_id WHERE s.fonte = 'urp' "
            "AND d.presente = 1 AND d.categoria IN ('graduatoria', 'scorrimento') AND d.data_protocollo BETWEEN ? AND ? "
            "AND s.bando_id IS NOT NULL", (dal, al)):
        aggiungi(d["bando_id"], codice_sotto(d["titolo"]))
    # graduatorie e scorrimenti nel file della segreteria nel periodo
    for a in conn.execute(
            "SELECT a.numero_bando, a.codice_sotto FROM segreteria_atto a JOIN segreteria_versione v ON v.id = a.versione_id "
            "WHERE v.esito = 'in_uso' AND a.in_ambito = 1 AND a.categoria IN ('graduatoria', 'scorrimento') "
            "AND a.data BETWEEN ? AND ?",
            (dal, al)):
        if a["numero_bando"] in per_numero:
            aggiungi(per_numero[a["numero_bando"]], a["codice_sotto"])
    return sorted(schede.values(), key=lambda s: (s["numero_bando"] or "", int(s["codice_sotto"]) if (s["codice_sotto"] or "").isdigit() else 0))


def riferimento(conn, s, dal: str, al: str) -> dict:
    """Protocollo e data della graduatoria secondo le fonti (allegato SOL, URP, file della segreteria): quella del
    periodo, altrimenti l'ultima nota (scheda entrata per uno scorrimento)."""
    grad = None
    for da, a in ((dal, al), ("0000-00-00", "9999-99-99")):
        grad = conn.execute("SELECT protocollo, data_protocollo, titolo FROM documento WHERE scheda_id = ? AND presente = 1 "
                            "AND categoria = 'graduatoria' AND data_protocollo BETWEEN ? AND ? ORDER BY data_protocollo DESC",
                            (s["id"], da, a)).fetchone()
        if not grad:
            grad = conn.execute(
                "SELECT d.protocollo, d.data_protocollo, d.titolo FROM documento d JOIN scheda x ON x.id = d.scheda_id "
                "WHERE x.bando_id = ? AND x.fonte = 'urp' AND d.presente = 1 AND d.categoria = 'graduatoria' "
                "AND d.data_protocollo BETWEEN ? AND ? ORDER BY d.data_protocollo DESC", (s["bando_id"], da, a)).fetchone()
        if not grad:
            grad = conn.execute(
                "SELECT a.protocollo, a.data AS data_protocollo, a.titolo FROM segreteria_atto a JOIN segreteria_versione v "
                "ON v.id = a.versione_id WHERE v.esito = 'in_uso' AND a.categoria = 'graduatoria' AND a.numero_bando = ? "
                "AND (a.codice_sotto IS ? OR ? IS NULL) AND a.data BETWEEN ? AND ? ORDER BY a.data DESC",
                (s["numero_bando"], s["codice_sotto"], s["codice_sotto"], da, a)).fetchone()
        if grad or s["data_pubbl_graduatoria"]:
            break
    allegato = conn.execute("SELECT 1 FROM documento WHERE scheda_id = ? AND presente = 1 AND categoria = 'graduatoria'",
                            (s["id"],)).fetchone() is not None
    return {"protocollo": grad["protocollo"] if grad else None,
            "data": grad["data_protocollo"] if grad else s["data_pubbl_graduatoria"],
            "titolo": grad["titolo"] if grad else None, "allegato_sol": allegato}


def schede_del_mese(conn, mese: str) -> list:
    return schede_periodo(conn, *intervallo(mese))


def verifica(conn, dal: str, al: str, intestazioni: dict, client=None) -> dict:
    """Legge domande e candidati con punteggi per le graduatorie del periodo."""
    if not _in_corso.acquire(blocking=False):
        raise VerificaInCorso("Verifica dei punteggi già in corso")
    try:
        client = client or Client(config.pausa_sol())
        schede = schede_periodo(conn, dal, al)
        totali = {"graduatorie": len(schede), "completi": 0, "parziali": 0, "mancanti": 0, "protocollo_mancante": 0,
                  "nessuna_domanda": 0, "errore": 0}
        for s in schede:
            ora = _adesso()
            rif = riferimento(conn, s, dal, al)
            c = dict.fromkeys(("vincitori", "idonei", "scorrimento", "senza_protocollo", "senza_esito",
                               "protocollo_diverso", "data_diversa"))
            scorr = None
            try:
                n = sol_auth.punteggi_bando(client, s["id_esterno"], intestazioni)
                c = conteggi_candidati(n["candidati"], rif["protocollo"], rif["data"])
                scorr = scorrimenti_candidati(n["candidati"])
                e, msg = esito(n["domande"], n["con_punteggi"], c["senza_protocollo"]), None
                _candidati[s["id"]] = {"verificato_il": ora, "candidati": n["candidati"]}
            except FonteErrore as err:
                if "HTTP 401" in str(err) or "HTTP 403" in str(err):
                    return {**totali, "esito": "fallita",
                            "messaggio": "Selezioni Online non riconosce la sessione: ricollega Selezioni Online"}
                n, e, msg = {"domande": None, "con_punteggi": None}, "errore", str(err)
            totali[e] += 1
            conn.execute(
                "INSERT INTO punteggi_verifica (scheda_id, verificato_il, domande, con_punteggi, vincitori, idonei, "
                "scorrimento, senza_protocollo, senza_esito, protocollo_diverso, data_diversa, scorrimenti_sol, esito, "
                "messaggio) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (s["id"], ora, n["domande"], n["con_punteggi"], c["vincitori"], c["idonei"], c["scorrimento"],
                 c["senza_protocollo"], c["senza_esito"], c["protocollo_diverso"], c["data_diversa"],
                 json.dumps(scorr) if scorr is not None else None, e, msg))
        log.info("Verifica punteggi %s-%s: %s", dal, al, totali)
        return {**totali, "esito": "completata", "messaggio": None}
    finally:
        _in_corso.release()


def in_corso() -> bool:
    return _in_corso.locked()


def candidati(scheda_id: int) -> dict | None:
    return _candidati.get(scheda_id)


def dimentica_candidati() -> None:
    _candidati.clear()


def ultime_verifiche(conn) -> dict[int, dict]:
    """Ultima verifica per scheda SOL (con "scorrimenti_sol" già decodificato)."""
    righe = {}
    for r in conn.execute(
            "SELECT v.* FROM punteggi_verifica v JOIN (SELECT scheda_id, MAX(id) AS id FROM punteggi_verifica GROUP BY scheda_id) u "
            "ON u.id = v.id"):
        v = dict(r)
        v["scorrimenti_sol"] = json.loads(v["scorrimenti_sol"]) if v.get("scorrimenti_sol") else None
        righe[r["scheda_id"]] = v
    return righe


def elenco_periodo(conn, dal: str, al: str) -> list[dict]:
    """Graduatorie del periodo con l'ultima verifica dei punteggi e gli RdP del codice."""
    verifiche = ultime_verifiche(conn)
    rdp = referenti.referenti_per_scheda(conn)
    righe = []
    for s in schede_periodo(conn, dal, al):
        rif = riferimento(conn, s, dal, al)
        v = verifiche.get(s["id"]) or {}
        noti = scorrimenti_noti(conn, s)
        sol_scorr = v.get("scorrimenti_sol")
        righe.append({
            "bando_id": s["bando_id"], "scheda_id": s["id"], "numero_bando": s["numero_bando"],
            "codice_sotto": s["codice_sotto"], "codice": s["codice_originale"], "url": s["url"],
            "url_punteggi": url_punteggi(s["id_esterno"]),
            "protocollo": rif["protocollo"], "data": rif["data"], "documento": rif["titolo"], "allegato_sol": rif["allegato_sol"],
            **{k: v.get(k) for k in ("domande", "con_punteggi", "vincitori", "idonei", "scorrimento", "senza_protocollo",
                                     "senza_esito", "protocollo_diverso", "data_diversa", "esito", "verificato_il",
                                     "messaggio")},
            "difformita": difformita(v) + ([] if rif["allegato_sol"] else ["graduatoria non allegata su SOL"])
                          + difformita_scorrimenti(sol_scorr, noti, dal, al),
            "scorrimenti": [{"data": g["data"], "protocolli": sorted(g["protocolli"]), "fonti": sorted(g["fonti"]),
                             **stato_scorrimento(g, sol_scorr)} for g in noti if dal <= (g["data"] or "") <= al],
            "candidati_disponibili": s["id"] in _candidati,
            "rdp": [{k: r[k] for k in ("nome", "cognome", "email")} for r in rdp.get(s["id"], [])],
        })
    return righe


def elenco_mese(conn, mese: str) -> list[dict]:
    return elenco_periodo(conn, *intervallo(mese))


# --------------------------------------------------------------------------- Excel

INTESTAZIONI_EXCEL = [
    "Codice bando", "Sede di lavoro", "Struttura di riferimento", "N. Posti", "Profilo/Livello", "Username",
    "Cognome", "Nome", "Data di nascita", "Codice Fiscale", "Email", "Email PEC", "Totale Punteggi", "Graduatoria",
    "Esito", "Note", "Data Protocollo Graduatoria", "Numero Protocollo Graduatoria",
    "Data Protocollo Assunzione Idoneo", "Numero Protocollo Assunzione Idoneo",
]


def _data_it(v) -> str:
    d = data_iso(v)
    return "/".join(reversed(d.split("-"))) if d else ""


GIALLO_EXCEL = "FFF3C4"


def righe_excel_scheda(s) -> list[tuple[list, bool]]:
    """Righe per candidato di una scheda, dall'ultima verifica in memoria, e se manca il protocollo."""
    dati = _candidati.get(s["id"])
    if not dati:
        return []
    extra = json.loads(s["dati_extra"]) if s["dati_extra"] else {}
    righe = []
    for x in sorted(dati["candidati"], key=lambda c: (c.get("graduatoria") is None, c.get("graduatoria") or 0)):
        righe.append(([s["codice_originale"], extra.get("sede"), extra.get("struttura_destinataria"),
                       extra.get("numero_posti"), extra.get("profilo"), x.get("username"),
                       (x.get("cognome") or "").upper(), (x.get("nome") or "").upper(),
                       _data_it(x.get("data_nascita")), x.get("codice_fiscale"), x.get("email"), x.get("email_pec"),
                       x.get("totale_punteggio"), x.get("graduatoria"), x.get("esito"), x.get("note"),
                       _data_it(x.get("data_protocollo_graduatoria")), x.get("numero_protocollo_graduatoria"),
                       _data_it(x.get("data_protocollo_assunzione_idoneo")), x.get("numero_protocollo_assunzione_idoneo")],
                      not str(x.get("numero_protocollo_graduatoria") or "").strip()))
    return righe


def excel_graduatorie(conn, dal: str, al: str) -> bytes:
    """Foglio "Graduatorie pubblicate" con le colonne dell'estrazione Punteggi di SOL."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Graduatorie pubblicate"
    ws.append(INTESTAZIONI_EXCEL)
    for c in ws[1]:
        c.font = Font(bold=True)
    giallo = PatternFill("solid", fgColor=GIALLO_EXCEL)
    for s in schede_periodo(conn, dal, al):
        for valori, senza_protocollo in righe_excel_scheda(s):
            ws.append(valori)
            if senza_protocollo:
                for c in ws[ws.max_row]:
                    c.fill = giallo  # protocollo della graduatoria mancante
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
