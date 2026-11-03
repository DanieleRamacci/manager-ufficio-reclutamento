"""Collegamento tra le schede URP e SOL dello stesso bando (data-model.md, "collegamento").

Le schede non vengono mai modificate: si assegna solo il bando a cui appartengono.
"""
import json
from datetime import datetime, timezone

from . import config

# per il periodo coperto da URP: a quale sezione URP corrisponde ogni tipologia (research R6)
GRUPPO_URP = {
    "tempo_indeterminato": "tempo-indeterminato",
    "reclutamento_speciale": "tempo-indeterminato",
    "categorie_protette": "categorie-riservatarie",
    "mobilita": "bandi-pubblici-mobilita",
    "comando": "bandi-pubblici-mobilita",
}
CATEGORIE_CONFRONTATE = ("graduatoria", "scorrimento", "rettifica")


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _trova_bando(conn, s) -> int | None:
    # Un numero di bando è un solo bando: i sotto-bandi (SOL "365.199 FA - CODICE 01 VE",
    # "367.500 ... Tematica C") sono schede dello stesso bando, mentre URP ha spesso una
    # pagina unica. Il codice di sotto-bando resta sulla scheda.
    if s["numero_bando"]:
        riga = conn.execute("SELECT id FROM bando WHERE numero_bando = ? ORDER BY id LIMIT 1",
                            (s["numero_bando"],)).fetchone()
        if riga:
            return riga["id"]
    if s["codice_norm"]:
        riga = conn.execute("SELECT id FROM bando WHERE codice_norm = ?", (s["codice_norm"],)).fetchone()
        if riga:
            return riga["id"]
    if s["protocollo"]:
        riga = conn.execute("SELECT bando_id FROM scheda WHERE protocollo = ? AND fonte != ? AND bando_id IS NOT NULL",
                            (s["protocollo"], s["fonte"])).fetchone()
        if riga:
            return riga["bando_id"]
    return None


def _crea_bando(conn, s, ora: str) -> int:
    codice_norm = s["codice_norm"]
    if codice_norm and conn.execute("SELECT 1 FROM bando WHERE codice_norm = ?", (codice_norm,)).fetchone():
        codice_norm = None  # stesso codice su un altro bando ambiguo: niente vincolo di unicità
    cur = conn.execute(
        "INSERT INTO bando (codice_norm, numero_bando, codice_sotto, codice, tipologia, titolo, data_pubblicazione, "
        "creato_il, aggiornato_il) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (codice_norm, s["numero_bando"], None, s["codice_originale"], s["tipologia"], s["titolo"],
         s["data_pubblicazione"], ora, ora))
    return cur.lastrowid


def _periodo_urp(conn) -> dict[str, str]:
    """Data del bando più vecchio presente in ogni sezione URP."""
    return {r["sezione"]: r["inizio"] for r in conn.execute(
        "SELECT sezione, MIN(data_pubblicazione) AS inizio FROM scheda WHERE fonte = 'urp' AND presente = 1 "
        "GROUP BY sezione")}


def _aggiorna_bandi(conn, ora: str) -> None:
    periodo = _periodo_urp(conn)
    schede_per_bando: dict[int, list] = {}
    for s in conn.execute("SELECT * FROM scheda WHERE bando_id IS NOT NULL AND presente = 1"):
        schede_per_bando.setdefault(s["bando_id"], []).append(s)
    for bando_id, schede in schede_per_bando.items():
        # scheda SOL principale: quella senza sotto-bando, se c'è
        sol = next((s for s in schede if s["fonte"] == "sol" and not s["codice_sotto"]), None) \
            or next((s for s in schede if s["fonte"] == "sol"), None)
        urp = next((s for s in schede if s["fonte"] == "urp"), None)
        principale = sol if sol and (not sol["codice_sotto"] or not urp) else (urp or sol)
        extra = json.loads(sol["dati_extra"]) if sol and sol["dati_extra"] else {}
        date = [s["data_pubblicazione"] for s in schede if s["data_pubblicazione"]]
        data = min(date) if date else None
        if sol and urp:
            stato = "entrambi"
        elif urp:
            stato = "solo_urp"
        else:
            inizio = periodo.get(GRUPPO_URP.get(sol["tipologia"], ""))
            stato = "solo_sol" if inizio and data and data >= inizio else "fuori_periodo_urp"
        conn.execute(
            "UPDATE bando SET codice = ?, tipologia = ?, titolo = ?, profilo = ?, sede = ?, numero_posti = ?, "
            "gruppo_rdp = ?, data_pubblicazione = ?, stato_collegamento = ?, aggiornato_il = ? WHERE id = ?",
            (principale["codice_originale"], principale["tipologia"], principale["titolo"], extra.get("profilo"),
             extra.get("sede"), extra.get("numero_posti"), extra.get("gruppo_rdp"), data, stato, ora, bando_id))
    conn.execute(
        "UPDATE bando SET stato_collegamento = NULL WHERE id NOT IN "
        "(SELECT bando_id FROM scheda WHERE presente = 1 AND bando_id IS NOT NULL)")


def collega(conn) -> None:
    ora = _adesso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        # prima SOL (codici più puliti), poi URP
        schede = conn.execute(
            "SELECT * FROM scheda WHERE bando_id IS NULL AND NOT (fonte = 'urp' AND tipologia IS NULL) "
            "ORDER BY CASE fonte WHEN 'sol' THEN 0 ELSE 1 END, id").fetchall()
        for s in schede:
            bando_id = _trova_bando(conn, s) or _crea_bando(conn, s, ora)
            conn.execute("UPDATE scheda SET bando_id = ? WHERE id = ?", (bando_id, s["id"]))
        _aggiorna_bandi(conn, ora)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def documenti_confrontati(conn, bando_ids: list[int] | None = None):
    """Documenti delle categorie confrontate, dal periodo di monitoraggio in poi."""
    dal = config.monitoraggio_dal().isoformat()
    filtro, args = "", [dal, *CATEGORIE_CONFRONTATE]
    if bando_ids is not None:
        filtro = f" AND s.bando_id IN ({', '.join('?' * len(bando_ids))})"
        args += bando_ids
    return conn.execute(
        "SELECT s.bando_id, s.fonte, d.categoria, d.sottotipo, d.protocollo, d.data_protocollo, d.titolo, d.tipo_fonte "
        "FROM documento d JOIN scheda s ON s.id = d.scheda_id "
        f"WHERE d.presente = 1 AND s.presente = 1 AND d.data_protocollo >= ? "
        f"AND d.categoria IN ({', '.join('?' * len(CATEGORIE_CONFRONTATE))}){filtro}", args).fetchall()


def _da_confrontare(d) -> bool:
    titolo = (d["titolo"] or "").lower()
    if "annullat" in titolo:
        return False
    if d["categoria"] == "rettifica":
        # solo le rettifiche della graduatoria (non commissione, calendario, criteri...)
        return "graduatori" in titolo or (d["tipo_fonte"] or "").endswith("call_correction_classification")
    return True


def calcola_segnalazioni(documenti, stati: dict[int, str]) -> dict[int, list[dict]]:
    """Per ogni bando presente su entrambe le fonti: documenti presenti su una sola fonte.

    Se un documento manca su una fonte ma sull'altra c'è un documento della stessa categoria
    e della stessa data con un altro protocollo, è lo stesso atto con un protocollo sbagliato:
    si segnala "protocollo diverso" invece di due mancanze.
    """
    per_bando: dict[int, dict[str, dict]] = {}
    for d in documenti:
        if stati.get(d["bando_id"]) != "entrambi" or not d["protocollo"] or not _da_confrontare(d):
            continue
        per_bando.setdefault(d["bando_id"], {"urp": {}, "sol": {}})[d["fonte"]].setdefault(d["protocollo"], d)
    risultato: dict[int, list[dict]] = {}
    for bando_id, fonti in per_bando.items():
        mancanti = {f: [d for p, d in fonti[f].items() if p not in fonti[a]] for f, a in (("urp", "sol"), ("sol", "urp"))}
        for u in list(mancanti["urp"]):
            gemello = next((s for s in mancanti["sol"]
                            if s["categoria"] == u["categoria"] and s["data_protocollo"] == u["data_protocollo"]), None)
            if gemello:
                mancanti["urp"].remove(u)
                mancanti["sol"].remove(gemello)
                risultato.setdefault(bando_id, []).append({
                    "tipo": f"{u['categoria']}_protocollo_diverso", "categoria": u["categoria"],
                    "sottotipo": u["sottotipo"], "protocollo": u["protocollo"], "protocollo_sol": gemello["protocollo"],
                    "data": u["data_protocollo"], "titolo": u["titolo"], "presente_su": "entrambi"})
        for fonte, altra in (("urp", "sol"), ("sol", "urp")):
            for d in mancanti[fonte]:
                risultato.setdefault(bando_id, []).append({
                    "tipo": f"{d['categoria']}_mancante_{altra}", "categoria": d["categoria"],
                    "sottotipo": d["sottotipo"], "protocollo": d["protocollo"], "data": d["data_protocollo"],
                    "titolo": d["titolo"], "presente_su": fonte})
    return risultato


def segnalazioni(conn, bando_id: int) -> list[dict]:
    riga = conn.execute("SELECT stato_collegamento FROM bando WHERE id = ?", (bando_id,)).fetchone()
    stati = {bando_id: riga["stato_collegamento"] if riga else None}
    return calcola_segnalazioni(documenti_confrontati(conn, [bando_id]), stati).get(bando_id, [])
