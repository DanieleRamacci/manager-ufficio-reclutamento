"""Esecuzione delle raccolte: registro, lock per fonte, salvataggio (data-model.md).

Prima si legge tutto dalla fonte, poi si scrive in un'unica transazione: se la lettura
fallisce i dati della raccolta precedente restano invariati (FR-016).
"""
import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

from . import config
from .fonti import sol, urp
from .fonti.http import Client, FonteErrore

log = logging.getLogger(__name__)

LOCK_SCADENZA_ORE = 6

CAMPI_SCHEDA = [
    "sezione", "tipologia", "codice_originale", "codice_norm", "numero_bando", "codice_sotto",
    "titolo", "protocollo", "protocollo_originale", "data_pubblicazione", "data_pubbl_graduatoria",
    "url", "dati_extra", "modificata_fonte_il",
]
CAMPI_DOCUMENTO = [
    "titolo", "categoria", "sottotipo", "sottotipo_ordinale", "sottotipo_origine", "tipo_fonte",
    "protocollo", "protocollo_originale", "data_protocollo", "url",
]


class RaccoltaInCorso(Exception):
    def __init__(self, fonte: str):
        super().__init__(f"Raccolta già in corso per: {fonte}")
        self.fonte = fonte


def _istante(momento: datetime) -> str:
    # con i microsecondi: due raccolte nello stesso secondo restano distinguibili
    return momento.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def adesso() -> str:
    return _istante(datetime.now(timezone.utc))


# --------------------------------------------------------------------------- registro

def avvia(conn: sqlite3.Connection, fonte: str, modalita: str, avviata_da: str | None) -> int:
    """Registra una raccolta in corso; rifiuta se ce n'è già una per la stessa fonte (FR-017)."""
    ora = adesso()
    scadenza = _istante(datetime.now(timezone.utc) - timedelta(hours=LOCK_SCADENZA_ORE))
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE raccolta SET esito = 'fallita', fine = ?, messaggio = 'Interrotta: processo terminato "
            "prima della fine' WHERE fonte = ? AND esito = 'in_corso' AND inizio < ?",
            (ora, fonte, scadenza))
        if conn.execute("SELECT 1 FROM raccolta WHERE fonte = ? AND esito = 'in_corso'", (fonte,)).fetchone():
            raise RaccoltaInCorso(fonte)
        cur = conn.execute(
            "INSERT INTO raccolta (fonte, modalita, avviata_da, inizio, esito) VALUES (?, ?, ?, ?, 'in_corso')",
            (fonte, modalita, avviata_da, ora))
        conn.execute("COMMIT")
        return cur.lastrowid
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def chiudi(conn, raccolta_id: int, esito: str, conteggi: dict | None = None,
           totale_dichiarato: dict | None = None, messaggio: str | None = None) -> None:
    c = conteggi or {}
    conn.execute(
        "UPDATE raccolta SET fine = ?, esito = ?, bandi_trovati = ?, documenti_trovati = ?, nuovi = ?, "
        "aggiornati = ?, totale_dichiarato = ?, messaggio = ? WHERE id = ?",
        (adesso(), esito, c.get("bandi_trovati", 0), c.get("documenti_trovati", 0), c.get("nuovi", 0),
         c.get("aggiornati", 0), json.dumps(totale_dichiarato) if totale_dichiarato else None, messaggio,
         raccolta_id))


def registra_errori(conn, raccolta_id: int, errori: list[tuple[str, str]]) -> None:
    conn.executemany("INSERT INTO raccolta_errore (raccolta_id, riferimento, messaggio) VALUES (?, ?, ?)",
                     [(raccolta_id, rif, msg) for rif, msg in errori])


def riepilogo(conn, raccolta_id: int) -> dict:
    riga = dict(conn.execute("SELECT * FROM raccolta WHERE id = ?", (raccolta_id,)).fetchone())
    riga["errori"] = conn.execute("SELECT COUNT(*) FROM raccolta_errore WHERE raccolta_id = ?",
                                  (raccolta_id,)).fetchone()[0]
    riga["totale_dichiarato"] = json.loads(riga["totale_dichiarato"]) if riga["totale_dichiarato"] else None
    return riga


def stato(conn) -> dict:
    """Per ogni fonte: ultima raccolta, ultima riuscita, raccolta in corso (FR-015, SC-006)."""
    risultato = {}
    for fonte in ("urp", "sol"):
        def una(where: str):
            riga = conn.execute(f"SELECT id FROM raccolta WHERE fonte = ? AND {where} ORDER BY id DESC LIMIT 1",
                                (fonte,)).fetchone()
            return riepilogo(conn, riga["id"]) if riga else None
        risultato[fonte] = {
            "ultima": una("esito != 'in_corso'"),
            "ultima_riuscita": una("esito IN ('completata', 'completata_con_errori')"),
            "in_corso": una("esito = 'in_corso'"),
        }
    return risultato


def errori(conn, raccolta_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT riferimento, messaggio FROM raccolta_errore WHERE raccolta_id = ? ORDER BY id", (raccolta_id,))]


def riclassifica(conn) -> int:
    """Riapplica le regole di classifica.py ai documenti salvati (dopo una modifica delle regole).
    Il documento principale URP resta "bando". Ritorna il numero di documenti cambiati."""
    from .classifica import classifica

    cambiati = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for d in conn.execute("SELECT id, titolo, tipo_fonte, categoria, sottotipo, sottotipo_ordinale FROM documento").fetchall():
            if d["categoria"] == "bando" and d["tipo_fonte"] is None:
                continue
            cat, sotto, ordinale = classifica(d["titolo"], d["tipo_fonte"])
            if (cat, sotto, ordinale) != (d["categoria"], d["sottotipo"], d["sottotipo_ordinale"]):
                conn.execute("UPDATE documento SET categoria = ?, sottotipo = ?, sottotipo_ordinale = ?, "
                             "sottotipo_origine = ? WHERE id = ?", (cat, sotto, ordinale, "titolo" if sotto else None, d["id"]))
                cambiati += 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return cambiati


# --------------------------------------------------------------------------- salvataggio

def _upsert(conn, tabella: str, chiavi: dict, campi: list[str], valori: dict, ora: str) -> tuple[int, str, dict | None]:
    """Inserisce o aggiorna una riga; ritorna (id, 'nuovo'|'aggiornato'|'invariato', valori precedenti)."""
    where = " AND ".join(f"{k} = ?" for k in chiavi)
    riga = conn.execute(f"SELECT id, {', '.join(campi)} FROM {tabella} WHERE {where}",
                        tuple(chiavi.values())).fetchone()
    if riga is None:
        colonne = list(chiavi) + campi + ["prima_rilevazione", "ultima_rilevazione", "presente"]
        args = list(chiavi.values()) + [valori.get(c) for c in campi] + [ora, ora, 1]
        cur = conn.execute(f"INSERT INTO {tabella} ({', '.join(colonne)}) VALUES ({', '.join('?' * len(colonne))})",
                           args)
        return cur.lastrowid, "nuovo", None
    precedente = dict(riga)
    if any(precedente[c] != valori.get(c) for c in campi):
        assegnazioni = ", ".join(f"{c} = ?" for c in campi)
        conn.execute(f"UPDATE {tabella} SET {assegnazioni}, ultima_rilevazione = ?, presente = 1 WHERE id = ?",
                     [valori.get(c) for c in campi] + [ora, riga["id"]])
        return riga["id"], "aggiornato", precedente
    conn.execute(f"UPDATE {tabella} SET ultima_rilevazione = ?, presente = 1 WHERE id = ?", (ora, riga["id"]))
    return riga["id"], "invariato", precedente


def scrivi(conn, fonte: str, schede: list[dict], id_in_elenco: list[str], ora: str) -> tuple[dict, list[int]]:
    """Salva schede e documenti in un'unica transazione.

    `schede`: schede lette (con `documenti` = None se gli allegati non sono stati letti).
    `id_in_elenco`: id esterni presenti negli elenchi della fonte, anche se il dettaglio
    non è stato letto per un errore: non vanno marcati come assenti.
    Ritorna i conteggi e gli id dei documenti nuovi o con link cambiato (per il controllo PDF).
    """
    conteggi = {"bandi_trovati": len(id_in_elenco), "documenti_trovati": 0, "nuovi": 0, "aggiornati": 0}
    da_controllare: list[int] = []

    def conta(stato: str) -> None:
        if stato == "nuovo":
            conteggi["nuovi"] += 1
        elif stato == "aggiornato":
            conteggi["aggiornati"] += 1

    conn.execute("BEGIN IMMEDIATE")
    try:
        for scheda in schede:
            scheda_id, stato, _ = _upsert(conn, "scheda", {"fonte": fonte, "id_esterno": scheda["id_esterno"]},
                                          CAMPI_SCHEDA, scheda, ora)
            conta(stato)
            if scheda.get("documenti") is None:
                continue
            for doc in scheda["documenti"]:
                doc_id, stato_doc, prec = _upsert(conn, "documento", {"scheda_id": scheda_id, "id_esterno": doc["id_esterno"]},
                                                  CAMPI_DOCUMENTO, doc, ora)
                conteggi["documenti_trovati"] += 1
                conta(stato_doc)
                if stato_doc == "nuovo" or (prec and prec["url"] != doc.get("url")):
                    da_controllare.append(doc_id)
            conn.execute("UPDATE documento SET presente = 0 WHERE scheda_id = ? AND ultima_rilevazione < ?",
                         (scheda_id, ora))
        # schede presenti negli elenchi ma non lette per un errore: restano presenti
        conn.executemany("UPDATE scheda SET ultima_rilevazione = ?, presente = 1 WHERE fonte = ? AND id_esterno = ?",
                         [(ora, fonte, i) for i in id_in_elenco])
        conn.execute("UPDATE scheda SET presente = 0 WHERE fonte = ? AND ultima_rilevazione < ?", (fonte, ora))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return conteggi, da_controllare


# --------------------------------------------------------------------------- fonti

def _leggi_urp(conn, client) -> tuple[list[dict], list[str], list[tuple[str, str]], dict]:
    schede, id_in_elenco, errori, dichiarati = [], [], [], {}
    for sezione in config.urp_sezioni():
        links, totale = urp.elenco_sezione(client, sezione)
        dichiarati[sezione] = totale
        for link in links:
            id_in_elenco.append(link.replace(config.URP_BASE, ""))
            try:
                schede.append(urp.dettaglio_bando(client, link, sezione))
            except Exception as e:  # un bando illeggibile non blocca gli altri
                errori.append((link, str(e)))
    if config.URP_ARCHIVIO_SEZIONE in config.urp_sezioni_pagine():
        try:
            archivio = urp.elenco_archivio(client)
            schede.extend(archivio)
            id_in_elenco.extend(s["id_esterno"] for s in archivio)
            dichiarati[config.URP_ARCHIVIO_SEZIONE] = len(archivio)
        except Exception as e:  # archivio irraggiungibile o cambiato: i bandi già salvati restano presenti
            errori.append((config.URP_ARCHIVIO_SEZIONE, str(e)))
            id_in_elenco.extend(r["id_esterno"] for r in conn.execute(
                "SELECT id_esterno FROM scheda WHERE fonte = 'urp' AND sezione = ?", (config.URP_ARCHIVIO_SEZIONE,)))
    return schede, id_in_elenco, errori, dichiarati


def _bandi_sol_da_aggiornare(conn, schede: list[dict], completa: bool) -> set[str]:
    """Bandi di cui rileggere gli allegati (research R8)."""
    if completa:
        return {s["id_esterno"] for s in schede}
    noti = {r["id_esterno"]: r for r in conn.execute(
        "SELECT s.id_esterno, s.modificata_fonte_il, "
        "EXISTS (SELECT 1 FROM documento d WHERE d.scheda_id = s.id AND d.categoria = 'graduatoria') AS ha_graduatoria "
        "FROM scheda s WHERE s.fonte = 'sol'")}
    soglia = (date.today() - timedelta(days=30 * config.SOL_MESI_ATTIVI)).isoformat()
    attivi = set()
    for s in schede:
        nota = noti.get(s["id_esterno"])
        if (nota is None or nota["modificata_fonte_il"] != s["modificata_fonte_il"]
                or not nota["ha_graduatoria"] or (s["data_pubblicazione"] or "") >= soglia):
            attivi.add(s["id_esterno"])
    return attivi


def _leggi_sol(conn, client, completa: bool) -> tuple[list[dict], list[str], list[tuple[str, str]], dict]:
    schede, errori, dichiarati = [], [], {}
    for tipo in config.SOL_TIPI:
        items, totale = sol.cerca_bandi(client, tipo)
        dichiarati[tipo] = totale
        schede.extend(sol.scheda_da_item(item, tipo) for item in items)
    da_aggiornare = _bandi_sol_da_aggiornare(conn, schede, completa)
    log.info("SOL: %d bandi, allegati da leggere per %d", len(schede), len(da_aggiornare))
    for scheda in schede:
        if scheda["id_esterno"] not in da_aggiornare:
            continue
        try:
            scheda["documenti"] = sol.allegati_bando(client, scheda["id_esterno"], scheda["url"])
        except Exception as e:
            errori.append((scheda["url"], str(e)))
    return schede, [s["id_esterno"] for s in schede], errori, dichiarati


# --------------------------------------------------------------------------- esecuzione

def raccogli(conn, fonte: str, *, client=None, modalita: str = "manuale", avviata_da: str | None = "cli",
             dopo_scrittura=None, raccolta_id: int | None = None) -> dict:
    """Esegue una raccolta completa su una fonte e ne restituisce il riepilogo.

    `dopo_scrittura(conn, fonte)` viene chiamata dopo il salvataggio (es. collegamento tra fonti).
    `raccolta_id`: raccolta già registrata con avvia() (es. dall'API, per rispondere subito).
    """
    if raccolta_id is None:
        raccolta_id = avvia(conn, fonte, modalita, avviata_da)
    dichiarati = None
    try:
        if fonte == "urp":
            client = client or Client(config.pausa_urp())
            schede, id_in_elenco, errori, dichiarati = _leggi_urp(conn, client)
        elif fonte == "sol":
            client = client or Client(config.pausa_sol())
            schede, id_in_elenco, errori, dichiarati = _leggi_sol(conn, client, modalita == "completa")
        else:
            raise ValueError(f"Fonte sconosciuta: {fonte}")
        if not schede:
            raise FonteErrore(f"Nessun bando letto da {fonte}")
        ora = conn.execute("SELECT inizio FROM raccolta WHERE id = ?", (raccolta_id,)).fetchone()[0]
        conteggi, da_controllare = scrivi(conn, fonte, schede, id_in_elenco, ora)
        registra_errori(conn, raccolta_id, errori)
        if dopo_scrittura:
            dopo_scrittura(conn, fonte)
        esito = "completata_con_errori" if errori else "completata"
        chiudi(conn, raccolta_id, esito, conteggi, dichiarati)
    except Exception as e:
        log.exception("Raccolta %s fallita", fonte)
        chiudi(conn, raccolta_id, "fallita", totale_dichiarato=dichiarati, messaggio=str(e))
        return riepilogo(conn, raccolta_id)

    if fonte == "urp" and config.controllo_pdf():
        from .accessibilita import controlla_documenti, documenti_da_valutare
        controlla_documenti(conn, sorted({*da_controllare, *documenti_da_valutare(conn)}))
    return riepilogo(conn, raccolta_id)
