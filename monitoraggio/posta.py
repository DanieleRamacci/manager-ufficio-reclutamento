"""Invio delle email (spec 006). Parte solo su azione esplicita di un amministratore.

Con MAIL_PROVA tutto va a quell'indirizzo, con i destinatari reali indicati nel testo.
"""
import logging
import os
import re
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)
_EMAIL = re.compile(r"[^@\s;,<>]+@[^@\s;,<>]+\.[^@\s;,<>]+")


class PostaErrore(Exception):
    pass


def configurata() -> bool:
    return bool(os.environ.get("SMTP_SERVER") and os.environ.get("MAIL_SENDER"))


def indirizzo_prova() -> str | None:
    return (os.environ.get("MAIL_PROVA") or "").strip() or None


def stato() -> dict:
    return {"configurata": configurata(), "prova": indirizzo_prova(),
            "mittente": os.environ.get("MAIL_SENDER"), "risposta": os.environ.get("MAIL_REPLY_TO")}


def indirizzi_non_validi(indirizzi: list[str]) -> list[str]:
    return [i for i in indirizzi if not _EMAIL.fullmatch(i)]


def invia(destinatari: list[str], oggetto: str, corpo: str) -> bool:
    """Invia l'email. Ritorna True se è andata in modalità di prova; solleva PostaErrore se non parte."""
    if not configurata():
        raise PostaErrore("Invio email non configurato")
    if not destinatari:
        raise PostaErrore("Nessun destinatario")
    sbagliati = indirizzi_non_validi(destinatari)
    if sbagliati:
        raise PostaErrore("Indirizzi non validi: " + ", ".join(sbagliati))
    prova = indirizzo_prova()
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
