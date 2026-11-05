"""Invio delle email (spec 006). Parte solo su azione esplicita di un amministratore.

In modalità di prova (menu Impostazioni) tutto va a un solo indirizzo, con i destinatari reali nel testo.
"""
import logging
import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from . import db

log = logging.getLogger(__name__)
_EMAIL = re.compile(r"[^@\s;,<>]+@[^@\s;,<>]+\.[^@\s;,<>]+")


class PostaErrore(Exception):
    pass


def configurata() -> bool:
    return bool(os.environ.get("SMTP_SERVER") and os.environ.get("MAIL_SENDER"))


def impostazioni_prova() -> dict:
    """Modalità di prova, scelta dagli amministratori e salvata nel database. Finché nessuno sceglie resta
    attiva: un'installazione nuova non deve scrivere ai destinatari veri."""
    conn = db.connetti()
    db.inizializza(conn)
    try:
        righe = {r["chiave"]: r for r in conn.execute(
            "SELECT * FROM impostazione WHERE chiave IN ('email_prova_attiva', 'email_prova_indirizzo')")}
    finally:
        conn.close()
    attiva = righe.get("email_prova_attiva")
    salvato = righe.get("email_prova_indirizzo")
    predefinito = (os.environ.get("MAIL_PROVA") or os.environ.get("MAIL_REPLY_TO") or "").strip() or None
    return {"attiva": attiva["valore"] != "0" if attiva else True,
            "indirizzo": (salvato["valore"] if salvato and salvato["valore"] else None) or predefinito,
            "modificata_da": attiva["modificata_da"] if attiva else None,
            "modificata_il": attiva["modificata_il"] if attiva else None}


def salva_prova(attiva: bool, indirizzo: str | None, autore: str | None) -> dict:
    indirizzo = (indirizzo or "").strip().lower() or None
    if indirizzo and indirizzi_non_validi([indirizzo]):
        raise ValueError(f"Indirizzo non valido: {indirizzo}")
    if attiva and not indirizzo and not impostazioni_prova()["indirizzo"]:
        raise ValueError("Per la modalità di prova serve un indirizzo")
    ora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db.connetti()
    db.inizializza(conn)
    try:
        voci = [("email_prova_attiva", "1" if attiva else "0")] + ([("email_prova_indirizzo", indirizzo)] if indirizzo else [])
        for chiave, valore in voci:
            conn.execute("INSERT INTO impostazione (chiave, valore, modificata_da, modificata_il) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore, modificata_da = excluded.modificata_da, "
                         "modificata_il = excluded.modificata_il", (chiave, valore, autore, ora))
    finally:
        conn.close()
    return impostazioni_prova()


def stato() -> dict:
    prova = impostazioni_prova()
    return {"configurata": configurata(), "prova": (prova["indirizzo"] or "indirizzo non impostato") if prova["attiva"] else None,
            "mittente": os.environ.get("MAIL_SENDER"), "risposta": os.environ.get("MAIL_REPLY_TO")}


def indirizzi_non_validi(indirizzi: list[str]) -> list[str]:
    return [i for i in indirizzi if not _EMAIL.fullmatch(i)]


def invia(destinatari: list[str], oggetto: str, corpo: str, sempre_reale: bool = False) -> bool:
    """Invia l'email. Ritorna True se è andata in modalità di prova; solleva PostaErrore se non parte.
    `sempre_reale`: per le email che devono arrivare alla persona, come i link di accesso."""
    if not configurata():
        raise PostaErrore("Invio email non configurato")
    if not destinatari:
        raise PostaErrore("Nessun destinatario")
    sbagliati = indirizzi_non_validi(destinatari)
    if sbagliati:
        raise PostaErrore("Indirizzi non validi: " + ", ".join(sbagliati))
    impostazioni = impostazioni_prova()
    in_prova = impostazioni["attiva"] and not sempre_reale
    if in_prova and not impostazioni["indirizzo"]:
        raise PostaErrore("Modalità di prova attiva senza indirizzo: impostalo in Impostazioni")
    prova = impostazioni["indirizzo"] if in_prova else None
    messaggio = EmailMessage()
    messaggio["From"] = os.environ["MAIL_SENDER"]
    messaggio["To"] = prova or ", ".join(destinatari)
    messaggio["Subject"] = f"[PROVA] {oggetto}" if prova else oggetto
    if os.environ.get("MAIL_REPLY_TO"):
        messaggio["Reply-To"] = os.environ["MAIL_REPLY_TO"]
    messaggio.set_content(f"[Modalità di prova. Destinatari reali: {', '.join(destinatari)}]\n\n{corpo}" if prova else corpo)
    try:
        with smtplib.SMTP(os.environ["SMTP_SERVER"], int(os.environ.get("SMTP_PORT") or 25), timeout=30) as smtp:
            if (os.environ.get("SMTP_STARTTLS") or "").lower() in ("1", "true", "yes"):
                smtp.starttls()
            smtp.send_message(messaggio)
    except (OSError, smtplib.SMTPException, ValueError) as e:
        log.warning("Invio email non riuscito: %s", type(e).__name__)
        raise PostaErrore(f"Il server di posta non ha accettato l'email ({type(e).__name__})") from e
    return bool(prova)
