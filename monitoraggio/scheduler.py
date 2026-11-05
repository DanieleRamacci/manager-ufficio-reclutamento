"""Raccolta pianificata (spec 001, T034): ogni giorno all'ora scelta in Impostazioni, completa nel giorno
scelto. All'avvio raccoglie subito le fonti mai lette, come faceva avvia_tool.py,
così un volume nuovo non resta vuoto. Il lock nel database evita raccolte sovrapposte."""
import logging
import threading
import time
from datetime import datetime

from . import collegamento, compat, config, db, impostazioni, notifiche
from .raccolta import RaccoltaInCorso, raccogli
from .web import prossima_notturna

log = logging.getLogger(__name__)
FONTI = ("urp", "sol")
CONTROLLO_ORARIO_S = 30
_avviato = threading.Event()


def modalita(giorno: datetime) -> str:
    return "completa" if giorno.weekday() == impostazioni.giorno_completa() else "notturna"


def _raccogli_fonte(fonte: str, modalita_raccolta: str, avviata_da: str, esiti: dict) -> None:
    conn = db.connetti()
    db.inizializza(conn)
    try:
        esiti[fonte] = raccogli(conn, fonte, modalita=modalita_raccolta, avviata_da=avviata_da,
                                dopo_scrittura=lambda c, f: collegamento.collega(c))
    except RaccoltaInCorso:
        log.info("Raccolta pianificata saltata: %s già in corso", fonte)
    except Exception:
        log.exception("Raccolta pianificata di %s non riuscita", fonte)
        esiti[fonte] = {"esito": "fallita", "messaggio": "Errore imprevisto"}
    finally:
        conn.close()


def esegui(fonti, modalita_raccolta: str, avviata_da: str) -> None:
    """Una fonte per thread: il controllo dei PDF di URP può durare ore e non deve far aspettare SOL."""
    esiti: dict = {}
    lavori = [threading.Thread(target=_raccogli_fonte, args=(f, modalita_raccolta, avviata_da, esiti), daemon=True)
              for f in fonti]
    for lavoro in lavori:
        lavoro.start()
    for lavoro in lavori:
        lavoro.join()
    notifiche.dopo_aggiornamento(esiti, modalita_raccolta)


def fonti_mai_lette() -> list[str]:
    conn = db.connetti()
    db.inizializza(conn)
    try:
        return [f for f in FONTI if compat.ultima_riuscita(conn, f) is None]
    finally:
        conn.close()


def _prossima() -> datetime:
    return datetime.fromisoformat(prossima_notturna(datetime.now().astimezone()))


def _ciclo() -> None:
    try:
        mancanti = fonti_mai_lette()
        if mancanti:
            esegui(mancanti, "notturna", "avvio")
    except Exception:
        log.exception("Raccolta iniziale non riuscita")
    prossima = _prossima()
    while True:
        time.sleep(CONTROLLO_ORARIO_S)  # a intervalli: l'orario si può cambiare dalle Impostazioni
        if datetime.now().astimezone() >= prossima:
            try:
                esegui(FONTI, modalita(prossima), "pianificata")
            except Exception:
                log.exception("Raccolta pianificata non riuscita")
        prossima = _prossima()


def avvia() -> bool:
    """Avvia il thread una sola volta. False se la raccolta notturna è disattivata o già avviata."""
    if not config.raccolta_notturna() or _avviato.is_set():
        return False
    _avviato.set()
    threading.Thread(target=_ciclo, daemon=True, name="raccolta-pianificata").start()
    return True
