"""Avviso via email all'amministratore alla fine di un aggiornamento (spec 006). Solo conteggi."""
import logging

from . import config, impostazioni, posta

log = logging.getLogger(__name__)
NOMI = {"urp": "URP", "sol": "Selezioni Online"}


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
        if r.get("esito") != "fallita":
            riga += f", {r.get('bandi_trovati', 0)} bandi, {r.get('documenti_trovati', 0)} documenti"
        if r.get("errori"):
            riga += f", {r['errori']} errori"
        if r.get("messaggio"):
            riga += f" ({r['messaggio']})"
        righe.append(riga)
    corpo = (f"Aggiornamento {tipo} terminato.\n\n" + "\n".join(righe) +
             f"\n\nDettagli: {config.sito_url()}/monitoraggio/impostazioni#aggiornamenti\n")
    return oggetto, corpo


def dopo_aggiornamento(esiti: dict, modalita: str) -> bool:
    """Non blocca mai la raccolta: se l'avviso non parte resta solo una riga nel log."""
    try:
        modo = impostazioni.modo_avviso()
        if not esiti or modo == "mai" or (modo == "completi" and modalita != "completa"):
            return False
        indirizzo = impostazioni.indirizzo_avviso()
        if not indirizzo or not posta.configurata():
            return False
        oggetto, corpo = testo(esiti, modalita)
        posta.invia([indirizzo], oggetto, corpo, sempre_reale=True)
        return True
    except Exception:
        log.warning("Avviso di fine aggiornamento non inviato")
        return False
