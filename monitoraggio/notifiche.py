"""Avviso via email all'amministratore quando SOL e URP hanno concluso, con gli errori riscontrati (spec 006)."""
import logging

from . import config, db, impostazioni, posta, raccolta

log = logging.getLogger(__name__)
NOMI = {"urp": "URP", "sol": "Selezioni Online"}
MAX_ERRORI = 20  # per fonte: l'elenco completo resta nella pagina degli aggiornamenti


def testo(esiti: dict, modalita: str) -> tuple[str, str]:
    non_riuscite = [f for f, r in esiti.items() if r.get("esito") == "fallita"]
    con_errori = [f for f, r in esiti.items() if r.get("esito") == "completata_con_errori"]
    tipo = "completo" if modalita == "completa" else "dei dati"
    if non_riuscite:
        oggetto = f"Monitoraggio: aggiornamento {tipo} NON riuscito"
    elif con_errori:
        oggetto = f"Monitoraggio: aggiornamento {tipo} completato con errori"
    else:
        oggetto = f"Monitoraggio: aggiornamento {tipo} completato"
    righe = []
    for fonte, r in esiti.items():
        riga = f"- {NOMI.get(fonte, fonte)}: {str(r.get('esito', '')).replace('_', ' ')}"
        if r.get("esito") not in ("fallita", "non_eseguita"):
            riga += f", {r.get('bandi_trovati', 0)} bandi, {r.get('documenti_trovati', 0)} documenti"
        if r.get("errori"):
            riga += f", {r['errori']} errori"
        if r.get("messaggio"):
            riga += f" ({r['messaggio']})"
        if r.get("fine"):
            riga += f", conclusa il {str(r['fine'])[:16].replace('T', ' ')} UTC"
        righe.append(riga)
    for fonte, r in esiti.items():
        dettagli = r.get("dettagli") or []
        if dettagli:
            righe += ["", f"Errori di {NOMI.get(fonte, fonte)}:"]
            righe += [f"- {e['riferimento']}: {e['messaggio']}" for e in dettagli[:MAX_ERRORI]]
            if len(dettagli) > MAX_ERRORI:
                righe.append(f"- e altri {len(dettagli) - MAX_ERRORI}: l'elenco completo è nella pagina degli aggiornamenti")
    corpo = (f"Aggiornamento {tipo} terminato: SOL e URP hanno concluso.\n\n" + "\n".join(righe) +
             f"\n\nDettagli: {config.sito_url()}/monitoraggio/impostazioni#aggiornamenti\n")
    return oggetto, corpo


def _fonti_concluse(esiti: dict) -> dict | None:
    """L'ultimo esito di SOL e URP con gli errori; None se una delle due è ancora in corso: l'avviso lo manda l'ultima."""
    conn = db.connetti()
    db.inizializza(conn)
    try:
        stato = raccolta.stato(conn)
        if any(s["in_corso"] for s in stato.values()):
            return None
        fonti = {}
        for fonte in ("sol", "urp"):
            ultima = stato[fonte]["ultima"]
            fonti[fonte] = ({**ultima, "dettagli": raccolta.errori(conn, ultima["id"])} if ultima
                            else esiti.get(fonte) or {"esito": "non_eseguita"})
        return fonti
    finally:
        conn.close()


def dopo_aggiornamento(esiti: dict, modalita: str) -> bool:
    """Non blocca mai la raccolta: se l'avviso non parte resta solo una riga nel log."""
    try:
        modo = impostazioni.modo_avviso()
        if not esiti or modo == "mai" or (modo == "completi" and modalita != "completa"):
            return False
        indirizzo = impostazioni.indirizzo_avviso()
        if not indirizzo or not posta.configurata():
            return False
        fonti = _fonti_concluse(esiti)
        if fonti is None:
            return False
        oggetto, corpo = testo(fonti, modalita)
        posta.invia([indirizzo], oggetto, corpo, sempre_reale=True)
        return True
    except Exception:
        log.warning("Avviso di fine aggiornamento non inviato")
        return False
