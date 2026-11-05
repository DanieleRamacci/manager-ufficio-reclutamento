"""Aggiornamenti notturni (specifiche grafiche, 3.7): ogni attività ha il suo orario e il suo storico."""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from . import collegamento, config, db, difformita, impostazioni, notifiche, posta, referenti
from .raccolta import RaccoltaInCorso, raccogli

log = logging.getLogger(__name__)

ATTIVITA = {
    "sol": {"nome": "Raccolta Selezioni Online", "descrizione": "Elenco dei bandi e allegati", "scarto": 0, "attiva": True},
    "urp": {"nome": "Raccolta URP", "descrizione": "Bandi, allegati, archivio e controllo dei PDF", "scarto": 15, "attiva": True},
    "referenti": {"nome": "Aggiornamento referenti (RdP)", "descrizione": "Richiede un accesso: da lanciare con Esegui ora", "scarto": 45, "attiva": False},
    "confronto": {"nome": "Confronto fonti e difformità", "descrizione": "Aggiorna i badge delle correzioni", "scarto": 60, "attiva": True},
    "riepilogo": {"nome": "Riepilogo email agli amministratori", "descrizione": "Esito della notte all'indirizzo dell'avviso", "scarto": 90, "attiva": False},
}
_in_corso: set[str] = set()
_lock = threading.Lock()
_lotto: dict = {"attese": set(), "esiti": {}}


def _conn():
    conn = db.connetti()
    db.inizializza(conn)
    return conn


def _orario_predefinito(chiave: str) -> str:
    h, m = impostazioni.orario_raccolta()
    t = datetime(2000, 1, 1, h, m) + timedelta(minutes=ATTIVITA[chiave]["scarto"])
    return t.strftime("%H:%M")


def elenco() -> list[dict]:
    conn = _conn()
    try:
        salvate = {r["chiave"]: r for r in conn.execute("SELECT * FROM attivita")}
        risultato = []
        for chiave, a in ATTIVITA.items():
            s = salvate.get(chiave)
            ultima = conn.execute("SELECT * FROM esecuzione WHERE attivita = ? ORDER BY id DESC LIMIT 1", (chiave,)).fetchone()
            risultato.append({"chiave": chiave, "nome": a["nome"], "descrizione": a["descrizione"],
                              "orario": s["orario"] if s and s["orario"] else _orario_predefinito(chiave),
                              "attiva": bool(s["attiva"]) if s and s["attiva"] is not None else a["attiva"],
                              "in_corso": chiave in _in_corso, "ultima": dict(ultima) if ultima else None})
        return risultato
    finally:
        conn.close()


def salva(chiave: str, orario: str | None, attiva: bool | None) -> None:
    if chiave not in ATTIVITA:
        raise ValueError("Attività sconosciuta")
    if orario is not None:
        impostazioni.controlla_orario(orario)
    conn = _conn()
    try:
        conn.execute("INSERT INTO attivita (chiave, orario, attiva) VALUES (?, ?, ?) ON CONFLICT(chiave) DO UPDATE SET "
                     "orario = COALESCE(excluded.orario, orario), attiva = COALESCE(excluded.attiva, attiva)",
                     (chiave, orario, None if attiva is None else int(attiva)))
    finally:
        conn.close()


def storico(attivita: str | None = None, solo_problemi: bool = False, limite: int = 100) -> list[dict]:
    condizioni, argomenti = ["esito != 'in_corso'"], []
    if attivita:
        condizioni.append("attivita = ?")
        argomenti.append(attivita)
    if solo_problemi:
        condizioni.append("esito IN ('avviso', 'errore')")
    conn = _conn()
    try:
        return [{**dict(r), "nome": ATTIVITA.get(r["attivita"], {}).get("nome", r["attivita"])} for r in conn.execute(
            f"SELECT * FROM esecuzione WHERE {' AND '.join(condizioni)} ORDER BY id DESC LIMIT ?", (*argomenti, limite))]
    finally:
        conn.close()


def prossima_esecuzione(ora: datetime | None = None) -> dict | None:
    ora = ora or datetime.now().astimezone()
    candidate = [(prossima_di(a["orario"], ora), a["nome"]) for a in elenco() if a["attiva"]]
    if not candidate or not config.raccolta_notturna():
        return None
    quando, nome = min(candidate)
    return {"quando": quando.isoformat(timespec="minutes"), "attivita": nome}


def prossima_di(orario: str, ora: datetime) -> datetime:
    h, m = map(int, orario.split(":"))
    prossima = ora.replace(hour=h, minute=m, second=0, microsecond=0)
    return prossima if prossima > ora else prossima + timedelta(days=1)


def _esegui_raccolta(fonte: str, avviata_da: str, modalita: str | None) -> tuple[str, str]:
    giorno_completo = datetime.now().astimezone().weekday() == impostazioni.giorno_completa()
    modo = modalita or ("completa" if giorno_completo else "notturna")
    conn = _conn()
    try:
        r = raccogli(conn, fonte, modalita=modo, avviata_da=avviata_da, dopo_scrittura=lambda c, f: collegamento.collega(c))
    finally:
        conn.close()
    difformita.sincronizza_tutti()
    _fine_raccolta(fonte, r, modo)
    testo = f"{r.get('bandi_trovati', 0)} bandi, {r.get('documenti_trovati', 0)} documenti" + (f", {r['errori']} errori" if r.get("errori") else "")
    if r["esito"] == "fallita":
        return "errore", r.get("messaggio") or "Raccolta non riuscita"
    return ("avviso" if r["esito"] == "completata_con_errori" else "ok"), testo


def _fine_raccolta(fonte: str, esito: dict, modalita: str) -> None:
    """Un solo avviso quando sono finite tutte le raccolte avviate insieme."""
    with _lock:
        _lotto["esiti"][fonte] = esito
        _lotto["attese"].discard(fonte)
        if _lotto["attese"]:
            return
        esiti, _lotto["esiti"] = _lotto["esiti"], {}
    notifiche.dopo_aggiornamento(esiti, modalita)


def _esegui_referenti(token) -> tuple[str, str]:
    if not token and not referenti.senza_token_ammesso():
        return "avviso", "Non eseguita: serve Selezioni Online collegato. Usa Esegui ora dopo Collega-SOL"
    conn = _conn()
    try:
        r = referenti.aggiorna(conn, token, "attività")
    finally:
        conn.close()
    if r.get("esito") == "fallito":
        return "errore", r.get("messaggio") or "Aggiornamento non riuscito"
    return "ok", f"{r.get('referenti', 0)} referenti su {r.get('bandi', 0)} bandi"


def _esegui_riepilogo() -> tuple[str, str]:
    indirizzo = impostazioni.indirizzo_avviso()
    if not indirizzo or not posta.configurata():
        return "avviso", "Manca l'indirizzo o il server di posta"
    righe = [f"- {e['nome']}: {e['esito']} ({e['dettaglio'] or ''})" for e in storico(limite=8)]
    posta.invia([indirizzo], "Monitoraggio: riepilogo degli aggiornamenti", "\n".join(righe) +
                f"\n\nDettagli: {config.sito_url()}/monitoraggio/impostazioni\n", sempre_reale=True)
    return "ok", f"Inviato a {indirizzo}"


def esegui(chiave: str, avviata_da: str = "pianificata", token=None, modalita: str | None = None) -> bool:
    """Avvia l'attività in background. False se è già in corso."""
    with _lock:
        if chiave in _in_corso:
            return False
        _in_corso.add(chiave)
        if chiave in ("sol", "urp"):
            _lotto["attese"].add(chiave)
    threading.Thread(target=_lavoro, args=(chiave, avviata_da, token, modalita), daemon=True, name=f"attivita-{chiave}").start()
    return True


def _lavoro(chiave: str, avviata_da: str, token, modalita) -> None:
    inizio = time.monotonic()
    quando = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _conn()
    id_e = conn.execute("INSERT INTO esecuzione (attivita, data, esito) VALUES (?, ?, 'in_corso')", (chiave, quando)).lastrowid
    try:
        if chiave in ("sol", "urp"):
            esito, dettaglio = _esegui_raccolta(chiave, avviata_da, modalita)
        elif chiave == "referenti":
            esito, dettaglio = _esegui_referenti(token)
        elif chiave == "confronto":
            difformita.sincronizza_tutti("confronto notturno")
            esito, dettaglio = "ok", "Difformità aggiornate"
        else:
            esito, dettaglio = _esegui_riepilogo()
    except RaccoltaInCorso:
        esito, dettaglio = "avviso", "Già in corso"
        with _lock:
            _lotto["attese"].discard(chiave)
    except Exception as e:
        log.exception("Attività %s non riuscita", chiave)
        esito, dettaglio = "errore", f"Errore imprevisto ({type(e).__name__})"
        with _lock:
            _lotto["attese"].discard(chiave)
    finally:
        with _lock:
            _in_corso.discard(chiave)
    conn.execute("UPDATE esecuzione SET esito = ?, durata_s = ?, dettaglio = ? WHERE id = ?",
                 (esito, int(time.monotonic() - inizio), dettaglio, id_e))
    conn.close()


def dovute(ora: datetime, precedenti: dict[str, datetime]) -> list[str]:
    """Attività il cui orario è arrivato; aggiorna `precedenti` con la prossima di ciascuna."""
    da_eseguire = []
    for a in elenco():
        attesa = precedenti.get(a["chiave"])
        if attesa is not None and ora >= attesa and a["attiva"]:
            da_eseguire.append(a["chiave"])
        precedenti[a["chiave"]] = prossima_di(a["orario"], ora)
    return da_eseguire
