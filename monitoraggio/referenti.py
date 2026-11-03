"""Referenti RdP dei bandi (spec 003): salvataggio per scheda SOL, attivo/non attivo, registro."""
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import config
from .fonti import sol_rdp
from .fonti.http import Client

log = logging.getLogger(__name__)
LOCK_SCADENZA_ORE = 1


class AggiornamentoInCorso(Exception):
    pass


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _avvia(conn, utente: str | None) -> int:
    scadenza = (datetime.now(timezone.utc) - timedelta(hours=LOCK_SCADENZA_ORE)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE referenti_aggiornamento SET esito = 'fallito', fine = ?, messaggio = 'Interrotto' "
                     "WHERE esito = 'in_corso' AND inizio < ?", (_adesso(), scadenza))
        if conn.execute("SELECT 1 FROM referenti_aggiornamento WHERE esito = 'in_corso'").fetchone():
            raise AggiornamentoInCorso("Aggiornamento dei referenti già in corso")
        cur = conn.execute("INSERT INTO referenti_aggiornamento (utente, inizio, esito) VALUES (?, ?, 'in_corso')",
                           (utente, _adesso()))
        conn.execute("COMMIT")
        return cur.lastrowid
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _chiudi(conn, agg_id: int, esito: str, bandi: int = 0, referenti: int = 0, messaggio: str | None = None) -> dict:
    conn.execute("UPDATE referenti_aggiornamento SET fine = ?, esito = ?, bandi = ?, referenti = ?, messaggio = ? "
                 "WHERE id = ?", (_adesso(), esito, bandi, referenti, messaggio, agg_id))
    return dict(conn.execute("SELECT * FROM referenti_aggiornamento WHERE id = ?", (agg_id,)).fetchone())


def senza_token_ammesso() -> bool:
    """Lettura senza login: eccezione temporanea solo se attivata esplicitamente (FR-001a)."""
    return os.environ.get("RDP_SENZA_TOKEN", "0") == "1"


def schede_da_aggiornare(conn, tutti: bool = False) -> list:
    """Schede SOL di cui leggere gli RdP: i bandi attivi nel monitoraggio (pubblicati dal
    MONITORAGGIO_DAL o con atti da quella data su una fonte o nel file della segreteria)."""
    if tutti:
        return conn.execute("SELECT id, id_esterno, codice_originale FROM scheda WHERE fonte = 'sol' AND presente = 1 "
                            "AND codice_originale IS NOT NULL").fetchall()
    dal = config.monitoraggio_dal().isoformat()
    return conn.execute(
        "SELECT s.id, s.id_esterno, s.codice_originale FROM scheda s JOIN bando b ON b.id = s.bando_id "
        "WHERE s.fonte = 'sol' AND s.presente = 1 AND s.codice_originale IS NOT NULL AND ("
        "  b.data_pubblicazione >= :dal"
        "  OR EXISTS (SELECT 1 FROM documento d JOIN scheda x ON x.id = d.scheda_id"
        "             WHERE x.bando_id = b.id AND d.presente = 1 AND d.data_protocollo >= :dal)"
        "  OR EXISTS (SELECT 1 FROM segreteria_atto a JOIN segreteria_versione v ON v.id = a.versione_id"
        "             WHERE v.esito = 'in_uso' AND a.numero_bando = b.numero_bando AND a.data >= :dal))",
        {"dal": dal}).fetchall()


def _accesso_negato(messaggio: str) -> bool:
    return "HTTP 401" in messaggio or "HTTP 403" in messaggio


def aggiorna(conn, token: str | None, utente: str | None, client=None, tutti: bool = False) -> dict:
    """Legge gli RdP con il token dell'utente, bando per bando, e li salva per le schede SOL."""
    if not token and not senza_token_ammesso():
        raise ValueError("Serve il token SSO dell'utente")
    agg_id = _avvia(conn, utente if token else f"{utente or 'locale'} (senza token)")
    client = client or Client(config.pausa_sol())
    letti, errori = {}, []
    for s in schede_da_aggiornare(conn, tutti):
        try:
            letti[s["id"]] = sol_rdp.rdp_bando(client, token, s["codice_originale"], s["id_esterno"])
        except Exception as e:
            messaggio = str(e)
            if _accesso_negato(messaggio):
                log.warning("Aggiornamento referenti: accesso negato da Selezioni Online")
                if not token:
                    messaggio = "Selezioni Online non risponde più senza login: serve l'accesso SSO (" + messaggio + ")"
                return _chiudi(conn, agg_id, "fallito", messaggio=messaggio)
            errori.append(s["codice_originale"])
    if errori and not letti:
        return _chiudi(conn, agg_id, "fallito", messaggio=f"Nessun bando letto ({len(errori)} errori)")

    ora = _adesso()
    bandi = totale = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for scheda_id, rdps in letti.items():
            if rdps is None:
                continue  # bando non trovato su SOL con quel codice
            bandi += 1
            visti = set()
            for rdp in rdps:
                p = sol_rdp.persona(rdp)
                if not p["chiave"] or p["chiave"] in visti:
                    continue
                visti.add(p["chiave"])
                totale += 1
                conn.execute(
                    "INSERT INTO referente (scheda_id, chiave, nome, cognome, email, username, attivo, prima_rilevazione, "
                    "ultima_rilevazione) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?) "
                    "ON CONFLICT (scheda_id, chiave) DO UPDATE SET nome = excluded.nome, cognome = excluded.cognome, "
                    "email = excluded.email, username = excluded.username, attivo = 1, "
                    "ultima_rilevazione = excluded.ultima_rilevazione",
                    (scheda_id, p["chiave"], p["nome"], p["cognome"], p["email"], p["username"], ora, ora))
            conn.execute("UPDATE referente SET attivo = 0 WHERE scheda_id = ? AND ultima_rilevazione < ?", (scheda_id, ora))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    log.info("Referenti aggiornati: %s bandi, %s referenti, %s errori", bandi, totale, len(errori))
    messaggio = f"{len(errori)} bandi non letti: {', '.join(errori[:10])}" if errori else None
    return _chiudi(conn, agg_id, "completato", bandi, totale, messaggio)


def referenti_per_scheda(conn, solo_attivi: bool = True) -> dict[int, list[dict]]:
    """RdP per scheda SOL: nei bandi con più codici (es. 367.434) ogni codice ha i suoi RdP."""
    risultato = defaultdict(list)
    for r in conn.execute(
            "SELECT scheda_id, nome, cognome, email, username, attivo, ultima_rilevazione FROM referente"
            + (" WHERE attivo = 1" if solo_attivi else "") + " ORDER BY cognome, nome"):
        voce = dict(r)
        risultato[voce.pop("scheda_id")].append(voce)
    return risultato


def referenti_per_bando(conn, solo_attivi: bool = True) -> dict[int, list[dict]]:
    risultato = defaultdict(list)
    for r in conn.execute(
            "SELECT s.bando_id, r.nome, r.cognome, r.email, r.username, r.attivo, r.ultima_rilevazione "
            "FROM referente r JOIN scheda s ON s.id = r.scheda_id WHERE s.bando_id IS NOT NULL"
            + (" AND r.attivo = 1" if solo_attivi else "") + " ORDER BY r.cognome, r.nome"):
        voce = dict(r)
        bando_id = voce.pop("bando_id")
        if voce["email"] not in {x["email"] for x in risultato[bando_id]} or not voce["email"]:
            risultato[bando_id].append(voce)
    return risultato


def stato(conn) -> dict | None:
    riga = conn.execute("SELECT * FROM referenti_aggiornamento ORDER BY id DESC LIMIT 1").fetchone()
    return dict(riga) if riga else None
