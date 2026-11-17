"""Avviso automatico agli RdP per ogni nuovo scorrimento/utilizzo di graduatoria e per le sue difformità (spec 009, US6).

Dopo l'aggiornamento notturno, da quando la funzione è attiva (scelta dell'utente del 2026-11-17):
- uno scorrimento nuovo, presente nel file della segreteria o su URP, fa partire un'email agli RdP con le difformità
  che ha in quel momento e il link al documento su URP, in copia la segreteria;
- su uno scorrimento già avvisato, una difformità nuova (non ancora comunicata) fa partire un'email con le sole novità.
Nel database ogni scorrimento tiene le difformità già comunicate e ogni invio resta registrato: niente si ripete ogni notte.
Alla prima esecuzione quello che c'è già si registra come «esistente», senza email.
Gli invii seguono le impostazioni email (prova / ufficiali). Nessuna fonte viene modificata.
Solo gli RdP interni all'ufficio ricevono l'avviso (elenco nelle Impostazioni, scelta dell'utente del 2026-11-17): tra gli RdP
ci sono anche persone esterne. Con l'elenco vuoto non parte nessuna email.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from . import atti, comunicazioni, config, db, difformita, impostazioni, posta

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
    """Scorrimenti/utilizzi del monitoraggio presenti nel file della segreteria o su URP, con le difformità calcolate
    come nel monitoraggio (stessi testi delle email ai referenti)."""
    trovati = []
    for r in difformita.righe_correnti(conn, config.monitoraggio_dal().isoformat(), "9999-12-31"):
        fonti = r.get("fonti") or {}
        if r["atto"] == "scorrimento" and any((fonti.get(f) or {}).get("stato") == atti.PRESENTE for f in ("segreteria", "urp")):
            trovati.append({**r, "rilievi_avviso": difformita.rilievi(r) if r.get("difforme") else []})
    return trovati


def _rdp(r: dict) -> list[str]:
    """Gli RdP della riga; se il codice non ha RdP propri sono quelli di tutti i codici del bando."""
    return list(dict.fromkeys(e for e in ((p.get("email") or "").strip().lower() for p in r.get("rdp") or []) if e))


def _data_it(iso: str | None) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y") if iso and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) else (iso or "")


NOMI = {"sol": "Selezioni Online", "urp": "URP", "segreteria": "file di riepilogo della segreteria"}


def messaggio(r: dict, evento: str = "nuovo", rilievi: list[str] | None = None) -> tuple[str, str]:
    """`evento`: «nuovo» (scorrimento appena trovato, con tutte le difformità attuali) o «difformita» (solo le nuove)."""
    rilievi = r.get("rilievi_avviso", []) if rilievi is None else rilievi
    codice = comunicazioni.chiave(r)
    titolo = f" – {r['titolo_bando']}" if r.get("titolo_bando") else ""
    prot = f", prot. {r['protocollo']}" if r.get("protocollo") else ""
    atto = f"provvedimento del {_data_it(r.get('data'))}{prot}"
    link = ((r.get("fonti") or {}).get("urp") or {}).get("url")
    presente = [NOMI[f] for f in ("segreteria", "urp", "sol") if ((r.get("fonti") or {}).get(f) or {}).get("stato") == atti.PRESENTE]
    elenco = "".join(f"- {x}\n" for x in rilievi)
    if evento == "nuovo":
        oggetto = f"Bando n° {codice}: rilevato uno scorrimento di graduatoria del {_data_it(r.get('data'))}"
        apertura = (f"nell'aggiornamento dei dati del monitoraggio è stato rilevato uno scorrimento/utilizzo della graduatoria per il bando "
                    f"{codice}{titolo}: {atto}, presente su: {', '.join(presente)}.\n\n"
                    + (f"Dai dati attualmente disponibili risultano queste difformità:\n{elenco}\n" if rilievi else ""))
    else:
        oggetto = f"Bando n° {codice}: nuove difformità sullo scorrimento del {_data_it(r.get('data'))}"
        apertura = (f"per lo scorrimento/utilizzo della graduatoria del bando {codice}{titolo} ({atto}), già segnalato in precedenza, "
                    f"dai dati attualmente disponibili risultano queste nuove difformità:\n{elenco}\n")
    corpo = (f"Gentili tutte e tutti,\n\n{apertura}"
             + (f"Documento pubblicato su URP: {link}\n\n" if link else "")
             + "Vi chiediamo di verificare che lo scorrimento sia corretto e riportato su Selezioni Online e, se non disponete del "
             "provvedimento, di richiederlo a chi si è occupato dello scorrimento.\n\n"
             f"Cordiali saluti,\n{posta.impostazioni_email()['firma'] or ''}\n")
    return oggetto, corpo


def _registra_base(conn, r: dict, ora: str) -> None:
    conn.execute("INSERT OR IGNORE INTO avviso_scorrimento (chiave, bando_id, protocollo, data, url_urp, esito, rilevato_il, quando, rilievi) "
                 "VALUES (?, ?, ?, ?, ?, 'esistente', ?, ?, ?)",
                 (comunicazioni.chiave(r), r.get("bando_id"), r.get("protocollo") or "", r.get("data") or "",
                  ((r.get("fonti") or {}).get("urp") or {}).get("url"), ora, ora, json.dumps(r["rilievi_avviso"], ensure_ascii=False)))


def esegui() -> tuple[str, str]:
    """Ritorna (esito, dettaglio) per lo storico delle attività. Non solleva: un errore d'invio resta registrato."""
    conn = db.connetti()
    db.inizializza(conn)
    try:
        if atti.fonti_in_attesa(conn):
            return "avviso", "Fonti in aggiornamento: nessun avviso"
        trovati = scorrimenti_trovati(conn)
        ora = _adesso()
        if not impostazioni._leggi(INIZIATO):
            for r in trovati:
                _registra_base(conn, r, ora)
            impostazioni._scrivi(conn, INIZIATO, ora, "attività")
            return "ok", f"Prima esecuzione: {len(trovati)} scorrimenti già presenti registrati senza email"
        if not posta.configurata():
            return "avviso", "Invio email non configurato"
        ufficio = set(interni())
        if not ufficio:
            return "avviso", "Nessuna email inviata: l'elenco delle persone dell'ufficio è vuoto"
        copia = copia_segreteria()
        recente = (datetime.now(timezone.utc) - timedelta(days=GIORNI_RECUPERO)).strftime("%Y-%m-%dT%H:%M:%SZ")
        gia = {(a["chiave"], a["protocollo"], a["data"]): a for a in conn.execute("SELECT * FROM avviso_scorrimento")}
        # annunciati: già presenti all'attivazione o con l'email del nuovo scorrimento partita
        annunciati = {r["avviso_id"] for r in conn.execute(
            "SELECT DISTINCT avviso_id FROM avviso_scorrimento_invio WHERE evento = 'nuovo' AND esito IN ('inviato', 'prova')")}
        conteggi = {"nuovi": 0, "difformita": 0, "senza": 0, "errori": 0}
        for r in trovati:
            chiave = (comunicazioni.chiave(r), r.get("protocollo") or "", r.get("data") or "")
            prima = gia.get(chiave)
            attuali = r["rilievi_avviso"]
            comunicati = json.loads(prima["rilievi"]) if prima else []
            if prima is None or (prima["esito"] != "esistente" and prima["id"] not in annunciati):
                evento, da_dire = "nuovo", attuali  # mai annunciato: tutto lo stato attuale
                if prima is not None and ((prima["esito"] == "errore" and prima["tentativi"] >= MAX_TENTATIVI)
                                          or (prima["esito"] == "senza_destinatari" and prima["rilevato_il"] < recente)):
                    continue
            else:
                da_dire = [x for x in attuali if x not in comunicati]
                if not da_dire:
                    continue
                evento = "difformita"
            tutti = _rdp(r)
            destinatari = [e for e in tutti if e in ufficio]
            if not destinatari and prima is not None and prima["esito"] == "senza_destinatari" and evento == "nuovo":
                continue  # già registrato senza RdP dell'ufficio: si riprova in silenzio finché è recente
            esito, testo = "senza_destinatari", ("Nessuno degli RdP fa parte dell'ufficio" if tutti else "Nessuna email RdP per il bando")
            if destinatari:
                oggetto, corpo = messaggio(r, evento, da_dire)
                try:
                    esito, testo = ("prova" if posta.invia(destinatari, oggetto, corpo, cc=copia) else "inviato"), None
                except posta.PostaErrore as e:
                    esito, testo = "errore", str(e)
            conteggi["errori" if esito == "errore" else "senza" if esito == "senza_destinatari" else "nuovi" if evento == "nuovo" else "difformita"] += 1
            # le difformità comunicate: tutte quelle attuali se l'email è partita (o non c'era a chi mandarla per una difformità);
            # per un errore restano quelle di prima, così si ritenta
            if esito in ("inviato", "prova") or (esito == "senza_destinatari" and evento == "difformita"):
                comunicati_ora = list(dict.fromkeys([*comunicati, *attuali]))
            else:
                comunicati_ora = comunicati
            # l'esito della riga riguarda l'annuncio dello scorrimento; quelli delle difformità stanno negli invii
            esito_riga = prima["esito"] if evento == "difformita" else esito
            conn.execute("INSERT INTO avviso_scorrimento (chiave, bando_id, protocollo, data, url_urp, destinatari, cc, esito, messaggio, tentativi, rilevato_il, quando, rilievi) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?) ON CONFLICT(chiave, protocollo, data) DO UPDATE SET url_urp = excluded.url_urp, "
                         "destinatari = excluded.destinatari, cc = excluded.cc, esito = excluded.esito, messaggio = excluded.messaggio, "
                         "tentativi = avviso_scorrimento.tentativi + ?, quando = excluded.quando, rilievi = excluded.rilievi",
                         (chiave[0], r.get("bando_id"), chiave[1], chiave[2], ((r.get("fonti") or {}).get("urp") or {}).get("url"),
                          json.dumps(destinatari), json.dumps(copia), esito_riga, testo, ora, ora, json.dumps(comunicati_ora, ensure_ascii=False),
                          1 if evento == "nuovo" else 0))  # i tentativi contano solo per l'annuncio
            avviso_id = conn.execute("SELECT id FROM avviso_scorrimento WHERE chiave = ? AND protocollo = ? AND data = ?", chiave).fetchone()["id"]
            conn.execute("INSERT INTO avviso_scorrimento_invio (avviso_id, quando, evento, esito, destinatari, cc, rilievi, messaggio) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (avviso_id, ora, evento, esito, json.dumps(destinatari), json.dumps(copia), json.dumps(da_dire, ensure_ascii=False), testo))
        c = conteggi
        dettaglio = (f"{c['nuovi']} nuovi scorrimenti avvisati, {c['difformita']} avvisi di nuove difformità"
                     + (f", {c['senza']} senza RdP dell'ufficio" if c["senza"] else "") + (f", {c['errori']} non inviati" if c["errori"] else ""))
        inviati = c["nuovi"] + c["difformita"]
        return ("errore" if c["errori"] and not inviati else "avviso" if c["errori"] or c["senza"] else "ok"), dettaglio
    except Exception as e:  # l'avviso non deve mai bloccare gli aggiornamenti
        log.exception("Avviso scorrimenti non riuscito")
        return "errore", f"Errore imprevisto ({type(e).__name__})"
    finally:
        conn.close()


def elenco(limite: int = 50) -> list[dict]:
    """Gli invii registrati, dal più recente."""
    conn = db.connetti()
    db.inizializza(conn)
    try:
        return [{**dict(r), **{k: json.loads(r[k]) for k in ("destinatari", "cc", "rilievi")}} for r in conn.execute(
            "SELECT i.id, i.quando, i.evento, i.esito, i.destinatari, i.cc, i.rilievi, i.messaggio, a.chiave, a.protocollo, a.data, a.url_urp "
            "FROM avviso_scorrimento_invio i JOIN avviso_scorrimento a ON a.id = i.avviso_id ORDER BY i.id DESC LIMIT ?", (limite,))]
    finally:
        conn.close()


def stato() -> dict:
    return {"copia": copia_segreteria(), "interni": interni(), "iniziato_il": impostazioni._leggi(INIZIATO), "avvisi": elenco()}
