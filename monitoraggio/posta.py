"""Invio delle email (spec 006). Parte solo su azione esplicita di un amministratore.

In modalità di prova (menu Impostazioni) tutto va a un solo indirizzo, con i destinatari reali nel testo.
"""
import logging
import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

from . import config, db

log = logging.getLogger(__name__)
_EMAIL = re.compile(r"[a-z0-9._%+'-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.I)


class PostaErrore(Exception):
    pass


def _impostazioni() -> dict:
    conn = db.connetti()
    db.inizializza(conn)
    try:
        return {r["chiave"]: r for r in conn.execute("SELECT * FROM impostazione WHERE chiave LIKE 'email_%'")}
    finally:
        conn.close()


def impostazioni_email() -> dict:
    """Due interruttori indipendenti: le prove vanno solo all'indirizzo di prova, le ufficiali ai destinatari veri.
    Finché nessuno sceglie restano attive solo le prove: un'installazione nuova non scrive ai referenti."""
    v = _impostazioni()
    valore = lambda k: v[k]["valore"] if k in v and v[k]["valore"] else None  # noqa: E731
    predefinito = (os.environ.get("MAIL_PROVA") or os.environ.get("MAIL_REPLY_TO") or "").strip() or None
    prova = v["email_prova_attiva"]["valore"] != "0" if "email_prova_attiva" in v else True
    ufficiali = v["email_ufficiali_attive"]["valore"] == "1" if "email_ufficiali_attive" in v else not prova
    return {"prova_attiva": prova, "indirizzo_prova": valore("email_prova_indirizzo") or predefinito, "ufficiali_attive": ufficiali,
            "mittente": valore("email_mittente") or (os.environ.get("MAIL_SENDER") or "").strip() or None,
            "cc": valore("email_cc"), "firma": valore("email_firma") or "Ufficio Reclutamento",
            "cartella_onedrive": valore("email_cartella_onedrive"),
            "portale_referenti": "email_portale_referenti" in v and v["email_portale_referenti"]["valore"] == "1",
            "modificata_da": v["email_prova_attiva"]["modificata_da"] if "email_prova_attiva" in v else None,
            "modificata_il": v["email_prova_attiva"]["modificata_il"] if "email_prova_attiva" in v else None}


def configurata() -> bool:
    return bool(os.environ.get("SMTP_SERVER") and impostazioni_email()["mittente"])


def impostazioni_prova() -> dict:
    e = impostazioni_email()
    return {"attiva": e["prova_attiva"], "indirizzo": e["indirizzo_prova"], "modificata_da": e["modificata_da"], "modificata_il": e["modificata_il"]}


def _scrivi(voci: list[tuple[str, str | None]], autore: str | None) -> None:
    ora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db.connetti()
    db.inizializza(conn)
    try:
        for chiave, valore in voci:
            conn.execute("INSERT INTO impostazione (chiave, valore, modificata_da, modificata_il) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore, modificata_da = excluded.modificata_da, "
                         "modificata_il = excluded.modificata_il", (chiave, valore, autore, ora))
    finally:
        conn.close()


def salva_email(dati: dict, autore: str | None) -> dict:
    attuali = impostazioni_email()
    prova = dati.get("prova_attiva", attuali["prova_attiva"])
    ufficiali = dati.get("ufficiali_attive", attuali["ufficiali_attive"])
    if not isinstance(prova, bool) or not isinstance(ufficiali, bool):
        raise ValueError("Indica quali email sono abilitate")
    voci = [("email_prova_attiva", "1" if prova else "0"), ("email_ufficiali_attive", "1" if ufficiali else "0")]
    for campo, chiave in (("indirizzo_prova", "email_prova_indirizzo"), ("mittente", "email_mittente")):
        if campo in dati:
            indirizzo = (dati[campo] or "").strip().lower()
            if indirizzo and indirizzi_non_validi([indirizzo]):
                raise ValueError(f"Indirizzo non valido: {indirizzo}")
            voci.append((chiave, indirizzo or None))
    if "cc" in dati:
        indirizzi = lista_indirizzi(dati["cc"])
        sbagliati = indirizzi_non_validi(indirizzi)
        if sbagliati:
            raise ValueError("Indirizzi in copia non validi: " + ", ".join(sbagliati))
        voci.append(("email_cc", ", ".join(indirizzi) or None))
    if "firma" in dati:
        voci.append(("email_firma", (dati["firma"] or "").strip() or None))
    if "cartella_onedrive" in dati:
        cartella = (dati["cartella_onedrive"] or "").strip()
        if cartella and not cartella.lower().startswith("https://"):
            raise ValueError("L'indirizzo della cartella OneDrive deve iniziare con https://")
        voci.append(("email_cartella_onedrive", cartella or None))
    if "portale_referenti" in dati:
        if not isinstance(dati["portale_referenti"], bool):
            raise ValueError("Indica se l'area referenti è attiva")
        voci.append(("email_portale_referenti", "1" if dati["portale_referenti"] else "0"))
    nuovi = dict(voci)
    if prova and not (nuovi.get("email_prova_indirizzo") or (attuali["indirizzo_prova"] if "indirizzo_prova" not in dati else None)):
        raise ValueError("Per le email di prova serve un indirizzo")
    if ufficiali and not (nuovi.get("email_mittente") or (attuali["mittente"] if "mittente" not in dati else None)):
        raise ValueError("Per le email ufficiali serve la casella mittente")
    _scrivi(voci, autore)
    return impostazioni_email()


def salva_prova(attiva: bool, indirizzo: str | None, autore: str | None) -> dict:
    """Con un solo interruttore: prova oppure invio reale."""
    salva = {"prova_attiva": attiva, "ufficiali_attive": not attiva}
    if indirizzo:
        salva["indirizzo_prova"] = indirizzo
    salva_email(salva, autore)
    return impostazioni_prova()


def stato() -> dict:
    e = impostazioni_email()
    return {**{k: e[k] for k in ("prova_attiva", "ufficiali_attive", "indirizzo_prova", "mittente", "cc", "firma", "portale_referenti", "cartella_onedrive")},
            "configurata": configurata(), "prova": (e["indirizzo_prova"] or "indirizzo non impostato") if e["prova_attiva"] else None,
            "risposta": os.environ.get("MAIL_REPLY_TO")}


def lista_indirizzi(testo: str | None) -> list[str]:
    """Più indirizzi separati da virgola o punto e virgola, normalizzati e senza doppioni."""
    visti, fuori = set(), []
    for a in re.split(r"[;,]", testo or ""):
        a = a.strip().lower()
        if a and a not in visti:
            visti.add(a)
            fuori.append(a)
    return fuori


def testo_area_referenti() -> str | None:
    """Il paragrafo sull'area referenti per le email, solo se l'area è attiva."""
    if not impostazioni_email()["portale_referenti"]:
        return None
    return (f"Se siete referenti di un bando, potete vedere le difformità che vi riguardano e segnalare eventuali falsi positivi "
            f"su {config.sito_url()}/referenti: inserite l'indirizzo email con cui risultate referenti su Selezioni Online e "
            f"riceverete un link personale di accesso.")


def contatto_ufficio() -> str | None:
    """Indirizzo dell'ufficio, sempre in copia alle email ufficiali e a cui rispondono i referenti."""
    return (os.environ.get("MAIL_REPLY_TO") or "").strip().lower() or None


def copia_fissa() -> list[str]:
    """Sempre in copia alle email ufficiali: il contatto dell'ufficio e gli indirizzi delle Impostazioni."""
    contatto = contatto_ufficio()
    return list(dict.fromkeys([*([contatto] if contatto else []), *lista_indirizzi(impostazioni_email()["cc"])]))


def copia_effettiva(destinatari: list[str], aggiunti: list[str] | None = None) -> list[str]:
    """Chi riceve davvero in copia: gli indirizzi fissi e quelli del singolo messaggio, senza chi è già tra i destinatari."""
    return [a for a in dict.fromkeys([*copia_fissa(), *(aggiunti or [])]) if a not in destinatari]


def indirizzi_non_validi(indirizzi: list[str]) -> list[str]:
    return [i for i in indirizzi if not _EMAIL.fullmatch(i)]


def invia(destinatari: list[str], oggetto: str, corpo: str, sempre_reale: bool = False, modo: str | None = None,
          cc: list[str] | None = None) -> bool:
    """Invia l'email. Ritorna True se è andata in prova; solleva PostaErrore se non parte. `modo`: "prova" o "ufficiale";
    senza, vale la prova se è attiva. `sempre_reale`: per le email che devono arrivare alla persona, come i link di accesso.
    `cc`: indirizzi in copia aggiunti per questo messaggio, oltre a quelli fissi."""
    if not configurata():
        raise PostaErrore("Invio email non configurato")
    if not destinatari:
        raise PostaErrore("Nessun destinatario")
    sbagliati = indirizzi_non_validi([*destinatari, *(cc or [])])
    if sbagliati:
        raise PostaErrore("Indirizzi non validi: " + ", ".join(sbagliati))
    e = impostazioni_email()
    modo = "reale" if sempre_reale else modo or ("prova" if e["prova_attiva"] else "ufficiale")
    if modo == "prova" and not e["prova_attiva"]:
        raise PostaErrore("Le email di prova sono disattivate")
    if modo == "prova" and not e["indirizzo_prova"]:
        raise PostaErrore("Email di prova senza indirizzo: impostalo in Impostazioni")
    if modo == "ufficiale" and not e["ufficiali_attive"]:
        raise PostaErrore("Le email ufficiali sono disattivate")
    prova = e["indirizzo_prova"] if modo == "prova" else None
    copia = copia_effettiva(destinatari, cc) if modo != "reale" else []
    oggetto = " ".join(oggetto.split())  # un a capo nell'intestazione farebbe fallire la costruzione dell'email
    messaggio = EmailMessage()
    messaggio["From"] = e["mittente"]
    messaggio["To"] = prova or ", ".join(destinatari)
    messaggio["Subject"] = f"[PROVA] {oggetto}" if prova else oggetto
    if os.environ.get("MAIL_REPLY_TO"):
        messaggio["Reply-To"] = os.environ["MAIL_REPLY_TO"]
    if modo == "ufficiale" and copia:
        messaggio["Cc"] = ", ".join(copia)
    in_copia = f". In copia: {', '.join(copia)}" if copia else ""
    messaggio.set_content(f"[Modalità di prova. Destinatari reali: {', '.join(destinatari)}{in_copia}]\n\n{corpo}" if prova else corpo)
    try:
        with smtplib.SMTP(os.environ["SMTP_SERVER"], int(os.environ.get("SMTP_PORT") or 25), timeout=30) as smtp:
            if (os.environ.get("SMTP_STARTTLS") or "").lower() in ("1", "true", "yes"):
                smtp.starttls()
            smtp.send_message(messaggio)
    except (OSError, smtplib.SMTPException, ValueError) as e:
        log.warning("Invio email non riuscito: %s", type(e).__name__)
        raise PostaErrore(f"Il server di posta non ha accettato l'email ({type(e).__name__})") from e
    return bool(prova)
