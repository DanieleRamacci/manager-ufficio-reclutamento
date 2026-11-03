"""Raccolta pianificata (spec 001, T034): ogni giorno all'ora `RACCOLTA_ORARIO`, completa nel giorno
`RACCOLTA_COMPLETA_GIORNO`. All'avvio raccoglie subito le fonti mai lette, come faceva avvia_tool.py,
così un volume nuovo non resta vuoto. Il lock nel database evita raccolte sovrapposte."""
import logging
import threading
import time
from datetime import datetime

from . import collegamento, compat, config, db
from .raccolta import RaccoltaInCorso, raccogli
from .web import prossima_notturna

log = logging.getLogger(__name__)
FONTI = ("urp", "sol")
_avviato = threading.Event()


def modalita(giorno: datetime) -> str:
    return "completa" if giorno.weekday() == config.raccolta_completa_giorno() else "notturna"


def esegui(fonti, modalita_raccolta: str, avviata_da: str) -> None:
    conn = db.connetti()
    db.inizializza(conn)
    try:
        for fonte in fonti:
            try:
                raccogli(conn, fonte, modalita=modalita_raccolta, avviata_da=avviata_da,
                         dopo_scrittura=lambda c, f: collegamento.collega(c))
            except RaccoltaInCorso:
                log.info("Raccolta pianificata saltata: %s già in corso", fonte)
    finally:
        conn.close()


def fonti_mai_lette() -> list[str]:
    conn = db.connetti()
    db.inizializza(conn)
    try:
        return [f for f in FONTI if compat.ultima_riuscita(conn, f) is None]
    finally:
        conn.close()


def _ciclo() -> None:
    try:
        mancanti = fonti_mai_lette()
        if mancanti:
            esegui(mancanti, "notturna", "avvio")
    except Exception:
        log.exception("Raccolta iniziale non riuscita")
    while True:
        ora = datetime.now().astimezone()
        prossima = datetime.fromisoformat(prossima_notturna(ora))
        time.sleep((prossima - ora).total_seconds())
        try:
            esegui(FONTI, modalita(prossima), "pianificata")
        except Exception:
            log.exception("Raccolta pianificata non riuscita")


def avvia() -> bool:
    """Avvia il thread una sola volta. False se la raccolta notturna è disattivata o già avviata."""
    if not config.raccolta_notturna() or _avviato.is_set():
        return False
    _avviato.set()
    threading.Thread(target=_ciclo, daemon=True, name="raccolta-pianificata").start()
    return True
