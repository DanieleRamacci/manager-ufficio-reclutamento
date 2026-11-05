"""Impostazioni degli aggiornamenti, salvate nel database (spec 006): orario, giorno della raccolta completa,
avviso via email. Finché nessuno sceglie valgono le variabili d'ambiente."""
import os
import re
from datetime import datetime, timedelta, timezone

from . import config, db

MODI_AVVISO = ("mai", "completi", "tutti")
_ORARIO = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def _leggi(chiave: str, predefinito=None):
    conn = db.connetti()
    db.inizializza(conn)
    try:
        riga = conn.execute("SELECT valore FROM impostazione WHERE chiave = ?", (chiave,)).fetchone()
    finally:
        conn.close()
    return riga["valore"] if riga and riga["valore"] else predefinito


def _scrivi(conn, chiave: str, valore: str, autore: str | None) -> None:
    conn.execute("INSERT INTO impostazione (chiave, valore, modificata_da, modificata_il) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore, modificata_da = excluded.modificata_da, "
                 "modificata_il = excluded.modificata_il",
                 (chiave, valore, autore, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))


def orario_raccolta() -> tuple[int, int]:
    salvato = _leggi("raccolta_orario")
    if salvato:
        ore, minuti = salvato.split(":")
        return int(ore), int(minuti)
    return config.raccolta_orario()


def giorno_completa() -> int:
    salvato = _leggi("raccolta_giorno_completa")
    return config.GIORNI_SETTIMANA.index(salvato) if salvato else config.raccolta_completa_giorno()


def modo_avviso() -> str:
    return _leggi("avviso_modo", "completi")


def indirizzo_avviso() -> str | None:
    return _leggi("avviso_indirizzo") or (os.environ.get("MAIL_REPLY_TO") or "").strip() or None


def _prossima_completa(ora: datetime, h: int, m: int, giorno: int) -> str:
    prossima = ora.replace(hour=h, minute=m, second=0, microsecond=0)
    while prossima <= ora or prossima.weekday() != giorno:
        prossima += timedelta(days=1)
    return prossima.isoformat(timespec="minutes")


def stato_aggiornamenti() -> dict:
    from .accessibilita import documenti_da_valutare
    from .web import prossima_notturna

    h, m = orario_raccolta()
    giorno = giorno_completa()
    conn = db.connetti()
    db.inizializza(conn)
    try:
        storico = [dict(r) for r in conn.execute(
            "SELECT fonte, modalita, avviata_da, inizio, fine, esito, bandi_trovati, documenti_trovati, messaggio, "
            "(SELECT COUNT(*) FROM raccolta_errore e WHERE e.raccolta_id = r.id) AS errori "
            "FROM raccolta r ORDER BY r.id DESC LIMIT 20")]
        completi = conn.execute("SELECT fine FROM raccolta WHERE modalita = 'completa' AND fine IS NOT NULL "
                                "AND esito IN ('completata', 'completata_con_errori') ORDER BY fine DESC LIMIT 1").fetchone()
        da_controllare = len(documenti_da_valutare(conn))
    finally:
        conn.close()
    ora = datetime.now().astimezone()
    attiva = config.raccolta_notturna()
    return {"orario": f"{h:02d}:{m:02d}", "giorno_completa": config.GIORNI_SETTIMANA[giorno], "giorni": config.GIORNI_SETTIMANA,
            "attiva": attiva, "prossima": prossima_notturna(ora) if attiva else None,
            "prossima_completa": _prossima_completa(ora, h, m, giorno) if attiva else None,
            "ultimo_completo": completi["fine"] if completi else None, "pdf_da_controllare": da_controllare,
            "storico": storico, "avviso_modo": modo_avviso(), "avviso_indirizzo": indirizzo_avviso()}


def salva_aggiornamenti(dati: dict, autore: str | None) -> None:
    orario = dati.get("orario")
    if orario is not None and not _ORARIO.fullmatch(orario):
        raise ValueError("Orario non valido: usa il formato OO:MM")
    giorno = dati.get("giorno_completa")
    if giorno is not None and giorno not in config.GIORNI_SETTIMANA:
        raise ValueError("Giorno non valido")
    modo = dati.get("avviso_modo")
    if modo is not None and modo not in MODI_AVVISO:
        raise ValueError("Scelta dell'avviso non valida")
    indirizzo = (dati.get("avviso_indirizzo") or "").strip().lower()
    if indirizzo and not re.fullmatch(r"[^@\s;,<>]+@[^@\s;,<>]+\.[^@\s;,<>]+", indirizzo):
        raise ValueError(f"Indirizzo non valido: {indirizzo}")
    if modo in ("completi", "tutti") and not indirizzo and not indirizzo_avviso():
        raise ValueError("Per ricevere l'avviso serve un indirizzo")
    conn = db.connetti()
    db.inizializza(conn)
    try:
        for chiave, valore in (("raccolta_orario", orario), ("raccolta_giorno_completa", giorno),
                               ("avviso_modo", modo), ("avviso_indirizzo", indirizzo or None)):
            if valore is not None:
                _scrivi(conn, chiave, valore, autore)
    finally:
        conn.close()
