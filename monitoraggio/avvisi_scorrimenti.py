"""Avviso automatico agli RdP per ogni nuovo scorrimento/utilizzo di graduatoria (spec 009, US6).

Dopo l'aggiornamento notturno: uno scorrimento presente sia nel file della segreteria sia su URP, e non ancora avvisato,
fa partire un'email agli RdP del bando con il link al documento su URP, in copia la segreteria. Ogni scorrimento si
avvisa una volta sola; alla prima esecuzione quelli già presenti si registrano come «esistente», senza email.
Gli invii seguono le impostazioni email (prova / ufficiali). Nessuna fonte viene modificata.
Solo gli RdP interni all'ufficio ricevono l'avviso (elenco nelle Impostazioni, scelta dell'utente del 2026-11-17): tra gli RdP
ci sono anche persone esterne. Con l'elenco vuoto non parte nessuna email.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from . import atti, comunicazioni, config, db, impostazioni, posta

log = logging.getLogger(__name__)
INIZIATO = "avviso_scorrimenti_iniziato"
COPIA = "avviso_scorrimenti_cc"
INTERNI = "avviso_scorrimenti_interni"
MAX_TENTATIVI = 5
GIORNI_RECUPERO = 30  # chi entra nell'elenco dopo riceve solo gli scorrimenti recenti, non quelli di mesi fa


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def copia_segreteria() -> list[str]:
    return posta.lista_indirizzi(impostazioni._leggi(COPIA))


def interni() -> list[str]:
    """Le persone dell'ufficio: solo loro, se sono RdP del bando, ricevono l'avviso."""
    return posta.lista_indirizzi(impostazioni._leggi(INTERNI))


def _controlla(testo: str | None) -> list[str]:
    indirizzi = posta.lista_indirizzi((testo or "").replace("\n", ","))
    sbagliati = posta.indirizzi_non_validi(indirizzi)
    if sbagliati:
        raise ValueError("Indirizzi non validi: " + ", ".join(sbagliati))
    return indirizzi


def salva(dati: dict, autore: str | None) -> None:
    """`copia`: la segreteria in copia; `interni`: le persone dell'ufficio. Solo i campi presenti."""
    valori = {chiave: _controlla(dati[campo]) for campo, chiave in (("copia", COPIA), ("interni", INTERNI)) if campo in dati}
    conn = db.connetti()
    db.inizializza(conn)
    try:
        for chiave, indirizzi in valori.items():
            impostazioni._scrivi(conn, chiave, ", ".join(indirizzi), autore)
    finally:
        conn.close()


def salva_copia(testo: str | None, autore: str | None) -> list[str]:
    salva({"copia": testo}, autore)
    return copia_segreteria()


def scorrimenti_trovati(conn) -> list[dict]:
    """Scorrimenti/utilizzi presenti sia su URP sia nel file della segreteria, nelle tipologie del monitoraggio."""
    trovati = []
    for r in atti.elenco_atti(conn):
        fonti = r.get("fonti") or {}
        if (r["atto"] == "scorrimento" and config.nel_monitoraggio(r.get("tipologia"))
                and (fonti.get("urp") or {}).get("stato") == atti.PRESENTE
                and (fonti.get("segreteria") or {}).get("stato") == atti.PRESENTE):
            trovati.append(r)
    return trovati


def _rdp(r: dict) -> list[str]:
    """Gli RdP della riga; se il codice non ha RdP propri sono quelli di tutti i codici del bando."""
    return list(dict.fromkeys(e for e in ((p.get("email") or "").strip().lower() for p in r.get("rdp") or []) if e))


def _data_it(iso: str | None) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y") if iso and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) else (iso or "")


def messaggio(r: dict) -> tuple[str, str]:
    codice = comunicazioni.chiave(r)
    titolo = f" – {r['titolo_bando']}" if r.get("titolo_bando") else ""
    prot = f", prot. {r['protocollo']}" if r.get("protocollo") else ""
    link = (r.get("fonti", {}).get("urp") or {}).get("url")
    oggetto = f"Bando n° {codice}: rilevato uno scorrimento di graduatoria del {_data_it(r.get('data'))}"
    corpo = (f"Gentili tutte e tutti,\n\nnell'aggiornamento dei dati del monitoraggio è stato rilevato uno scorrimento/utilizzo della "
             f"graduatoria per il bando {codice}{titolo}: provvedimento del {_data_it(r.get('data'))}{prot}, presente sia su URP sia nel "
             f"file di riepilogo della segreteria.\n\n"
             + (f"Documento pubblicato su URP: {link}\n\n" if link else "")
             + "Vi chiediamo di verificare che lo scorrimento sia corretto e riportato su Selezioni Online e, se non disponete del "
             "provvedimento, di richiederlo a chi si è occupato dello scorrimento.\n\n"
             f"Cordiali saluti,\n{posta.impostazioni_email()['firma'] or ''}\n")
    return oggetto, corpo


def esegui() -> tuple[str, str]:
    """Ritorna (esito, dettaglio) per lo storico delle attività. Non solleva: un errore d'invio resta sulla riga."""
    conn = db.connetti()
    db.inizializza(conn)
    try:
        if atti.fonti_in_attesa(conn):
            return "avviso", "Fonti in aggiornamento: nessun avviso"
        trovati = scorrimenti_trovati(conn)
        ora = _adesso()
        gia = {(a["chiave"], a["protocollo"], a["data"]): a for a in conn.execute("SELECT * FROM avviso_scorrimento")}
        if not impostazioni._leggi(INIZIATO):
            for r in trovati:
                conn.execute("INSERT OR IGNORE INTO avviso_scorrimento (chiave, bando_id, protocollo, data, url_urp, esito, rilevato_il, quando) "
                             "VALUES (?, ?, ?, ?, ?, 'esistente', ?, ?)",
                             (comunicazioni.chiave(r), r.get("bando_id"), r.get("protocollo") or "", r.get("data") or "",
                              (r["fonti"].get("urp") or {}).get("url"), ora, ora))
            impostazioni._scrivi(conn, INIZIATO, ora, "attività")
            return "ok", f"Prima esecuzione: {len(trovati)} scorrimenti già presenti registrati senza email"
        if not posta.configurata():
            return "avviso", "Invio email non configurato"
        ufficio = set(interni())
        if not ufficio:
            return "avviso", "Nessuna email inviata: l'elenco delle persone dell'ufficio è vuoto"
        copia = copia_segreteria()
        recente = (datetime.now(timezone.utc) - timedelta(days=GIORNI_RECUPERO)).strftime("%Y-%m-%dT%H:%M:%SZ")
        inviati = errori = senza = 0
        for r in trovati:
            chiave = (comunicazioni.chiave(r), r.get("protocollo") or "", r.get("data") or "")
            prima = gia.get(chiave)
            if prima and (prima["esito"] not in ("errore", "senza_destinatari") or prima["tentativi"] >= MAX_TENTATIVI
                          or (prima["esito"] == "senza_destinatari" and prima["rilevato_il"] < recente)):
                continue
            tutti = _rdp(r)
            destinatari = [e for e in tutti if e in ufficio]
            if not destinatari and prima and prima["esito"] == "senza_destinatari":
                continue  # resta com'era: se un RdP entra nell'elenco entro 30 giorni riceve l'avviso
            esito, testo = "senza_destinatari", ("Nessuno degli RdP fa parte dell'ufficio" if tutti else "Nessuna email RdP per il bando")
            if destinatari:
                oggetto, corpo = messaggio(r)
                try:
                    in_prova = posta.invia(destinatari, oggetto, corpo, cc=copia)
                    esito, testo = ("prova" if in_prova else "inviato"), None
                except posta.PostaErrore as e:
                    esito, testo = "errore", str(e)
            inviati += esito in ("inviato", "prova")
            errori += esito == "errore"
            senza += esito == "senza_destinatari"
            conn.execute("INSERT INTO avviso_scorrimento (chiave, bando_id, protocollo, data, url_urp, destinatari, cc, esito, messaggio, tentativi, rilevato_il, quando) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?) ON CONFLICT(chiave, protocollo, data) DO UPDATE SET destinatari = excluded.destinatari, "
                         "cc = excluded.cc, esito = excluded.esito, messaggio = excluded.messaggio, tentativi = avviso_scorrimento.tentativi + 1, quando = excluded.quando",
                         (*chiave[:1], r.get("bando_id"), *chiave[1:], (r["fonti"].get("urp") or {}).get("url"), json.dumps(destinatari),
                          json.dumps(copia), esito, testo, ora, ora))
        dettaglio = f"{inviati} avvisi inviati" + (f", {senza} senza RdP dell'ufficio" if senza else "") + (f", {errori} non inviati" if errori else "")
        return ("errore" if errori and not inviati else "avviso" if errori or senza else "ok"), dettaglio
    except Exception as e:  # l'avviso non deve mai bloccare gli aggiornamenti
        log.exception("Avviso scorrimenti non riuscito")
        return "errore", f"Errore imprevisto ({type(e).__name__})"
    finally:
        conn.close()


def elenco(limite: int = 50) -> list[dict]:
    conn = db.connetti()
    db.inizializza(conn)
    try:
        return [{**dict(r), "destinatari": json.loads(r["destinatari"]), "cc": json.loads(r["cc"])}
                for r in conn.execute("SELECT * FROM avviso_scorrimento WHERE esito != 'esistente' ORDER BY quando DESC, id DESC LIMIT ?", (limite,))]
    finally:
        conn.close()


def stato() -> dict:
    return {"copia": copia_segreteria(), "interni": interni(), "iniziato_il": impostazioni._leggi(INIZIATO), "avvisi": elenco()}
