"""Profili di Selezioni Online seguiti dai coordinatori.

Decisioni dell'utente del 2026-11-11: i profili sono quelli di SOL (campo profilo del bando), ogni profilo ha al più un
coordinatore; chi vuole un profilo già preso lo chiede, l'avviso arriva a entrambi, chi lo ha può cederlo e
l'amministratore decide in ultima istanza.
"""
import json
import logging
from datetime import datetime, timezone

from . import config, posta

log = logging.getLogger(__name__)
APERTA, ACCOLTA, RESPINTA = "aperta", "accolta", "respinta"


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def disponibili(conn) -> list[str]:
    """I profili dei bandi del monitoraggio, come li scrive Selezioni Online."""
    trovati = set()
    for s in conn.execute("SELECT tipologia, dati_extra FROM scheda WHERE fonte = 'sol' AND presente = 1 AND dati_extra IS NOT NULL"):
        profilo = json.loads(s["dati_extra"]).get("profilo")
        if profilo and config.nel_monitoraggio(s["tipologia"]):
            trovati.add(profilo)
    return sorted(trovati)


def titolari(conn) -> dict[str, str]:
    return {r["profilo"]: r["email"] for r in conn.execute("SELECT profilo, email FROM profilo_coordinato")}


def di(conn, email: str) -> list[str]:
    return [r["profilo"] for r in conn.execute("SELECT profilo FROM profilo_coordinato WHERE email = ? ORDER BY profilo", (email,))]


def prendi(conn, email: str, profilo: str) -> str | None:
    """Assegna il profilo se è libero. Ritorna chi lo ha già, se è un altro."""
    titolare = titolari(conn).get(profilo)
    if titolare and titolare != email:
        return titolare
    conn.execute("INSERT OR IGNORE INTO profilo_coordinato (profilo, email, dal) VALUES (?, ?, ?)", (profilo, email, _adesso()))
    return None


def lascia(conn, email: str, profilo: str) -> bool:
    return conn.execute("DELETE FROM profilo_coordinato WHERE profilo = ? AND email = ?", (profilo, email)).rowcount > 0


def assegna(conn, profilo: str, email: str | None) -> None:
    """Scelta dell'amministratore: vale anche se il profilo era di un altro."""
    conn.execute("DELETE FROM profilo_coordinato WHERE profilo = ?", (profilo,))
    if email:
        conn.execute("INSERT INTO profilo_coordinato (profilo, email, dal) VALUES (?, ?, ?)", (profilo, email, _adesso()))
    conn.execute("UPDATE profilo_richiesta SET stato = ?, gestita_il = ? WHERE profilo = ? AND stato = ? AND richiedente = ?",
                 (ACCOLTA, _adesso(), profilo, APERTA, email or ""))


def togli_coordinatore(conn, email: str) -> None:
    conn.execute("DELETE FROM profilo_coordinato WHERE email = ?", (email,))
    conn.execute("UPDATE profilo_richiesta SET stato = ?, gestita_il = ? WHERE stato = ? AND richiedente = ?",
                 (RESPINTA, _adesso(), APERTA, email))


def richieste(conn, solo_aperte: bool = True) -> list[dict]:
    filtro = "WHERE stato = 'aperta' " if solo_aperte else ""
    return [dict(r) for r in conn.execute(f"SELECT * FROM profilo_richiesta {filtro}ORDER BY id DESC")]


def richiedi(conn, email: str, profilo: str) -> dict:
    """Una sola richiesta aperta per persona e profilo; l'avviso parte solo alla prima."""
    gia = conn.execute("SELECT * FROM profilo_richiesta WHERE profilo = ? AND richiedente = ? AND stato = ?",
                       (profilo, email, APERTA)).fetchone()
    if gia:
        return {**dict(gia), "nuova": False}
    titolare = titolari(conn).get(profilo)
    cur = conn.execute("INSERT INTO profilo_richiesta (profilo, richiedente, titolare, quando) VALUES (?, ?, ?, ?)",
                       (profilo, email, titolare, _adesso()))
    return {"id": cur.lastrowid, "profilo": profilo, "richiedente": email, "titolare": titolare, "stato": APERTA, "nuova": True}


def cedi(conn, richiesta_id: int, email: str) -> dict | None:
    """Chi ha il profilo lo cede a chi l'ha chiesto."""
    r = conn.execute("SELECT * FROM profilo_richiesta WHERE id = ? AND stato = ?", (richiesta_id, APERTA)).fetchone()
    if not r or titolari(conn).get(r["profilo"]) != email:
        return None
    assegna(conn, r["profilo"], r["richiedente"])
    conn.execute("UPDATE profilo_richiesta SET stato = ?, gestita_da = ?, gestita_il = ? WHERE id = ?", (ACCOLTA, email, _adesso(), richiesta_id))
    return dict(r)


def chiudi(conn, richiesta_id: int, accolta: bool, autore: str | None) -> dict | None:
    """Decisione dell'amministratore su una richiesta aperta."""
    r = conn.execute("SELECT * FROM profilo_richiesta WHERE id = ? AND stato = ?", (richiesta_id, APERTA)).fetchone()
    if not r:
        return None
    if accolta:
        assegna(conn, r["profilo"], r["richiedente"])
    conn.execute("UPDATE profilo_richiesta SET stato = ?, gestita_da = ?, gestita_il = ? WHERE id = ?",
                 (ACCOLTA if accolta else RESPINTA, autore, _adesso(), richiesta_id))
    return dict(r)


def avvisa_richiesta(richiesta: dict) -> bool:
    """Avvisa entrambi: chi chiede e chi ha già il profilo."""
    destinatari = [x for x in (richiesta["titolare"], richiesta["richiedente"]) if x]
    corpo = (f"Buongiorno,\n\n{richiesta['richiedente']} ha chiesto di coordinare il profilo «{richiesta['profilo']}», "
             f"che oggi risulta coordinato da {richiesta['titolare'] or 'nessuno'}.\n\n"
             "Un profilo può avere un solo coordinatore. Chi lo coordina oggi può cederlo dalla pagina dei profili dell'area referenti:\n"
             f"{config.sito_url()}/referenti/profili\n\n"
             "In caso contrario decide l'Ufficio reclutamento.\n")
    try:
        posta.invia(destinatari, f"Richiesta del profilo «{richiesta['profilo']}» nel monitoraggio bandi", corpo, sempre_reale=True)
        return True
    except posta.PostaErrore:
        log.warning("Avviso della richiesta di profilo non inviato")
        return False


def avvisa_cessione(richiesta: dict) -> None:
    destinatari = [x for x in (richiesta["titolare"], richiesta["richiedente"]) if x]
    try:
        posta.invia(destinatari, f"Profilo «{richiesta['profilo']}» ora coordinato da {richiesta['richiedente']}",
                    f"Buongiorno,\n\nil profilo «{richiesta['profilo']}» è ora coordinato da {richiesta['richiedente']}.\n", sempre_reale=True)
    except posta.PostaErrore:
        log.warning("Avviso della cessione del profilo non inviato")
