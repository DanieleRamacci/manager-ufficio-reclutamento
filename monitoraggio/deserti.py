"""Spec 012: richiesta agli RdP per un concorso senza esito (è andato deserto o mancano solo i dati?).

Stesso schema delle richieste di verifica della spec 011: anteprima modificabile, invio di prova o reale,
registro degli invii. Nessun dato dei candidati nel testo (solo il codice del concorso e le date).
"""
import json
from datetime import datetime, timezone

from . import atti, comunicazioni, posta, referenti
from .avvisi_scorrimenti import copia_segreteria

MODI = (None, "prova", "ufficiale")


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ultime(conn) -> dict[int, dict]:
    """Ultima richiesta per scheda SOL."""
    return {r["scheda_id"]: dict(r) for r in conn.execute("SELECT scheda_id, esito, quando, utente FROM richiesta_deserto ORDER BY id")}


def _scheda(conn, scheda_id: int) -> dict | None:
    """La riga «senza esito» della scheda, se il concorso è ancora senza esito."""
    return next((x for x in atti.senza_esito(conn) if x["scheda"]["id"] == scheda_id), None)


def _destinatari(conn, s) -> list[str]:
    """RdP del codice, altrimenti del bando padre, altrimenti del bando."""
    per_scheda = referenti.referenti_per_scheda(conn)
    padre = conn.execute("SELECT id FROM scheda WHERE fonte = 'sol' AND id_esterno = ?", (s["id_padre"],)).fetchone() if s["id_padre"] else None
    persone = per_scheda.get(s["id"]) or (per_scheda.get(padre["id"]) if padre else None) or referenti.referenti_per_bando(conn).get(s["bando_id"]) or []
    return list(dict.fromkeys((p.get("email") or "").strip().lower() for p in persone if p.get("email")))


def anteprima(conn, scheda_id: int) -> dict | None:
    x = _scheda(conn, scheda_id)
    if x is None:
        return None
    s = x["scheda"]
    codice = s["codice_originale"] or s["numero_bando"]
    corpo = (f"{comunicazioni.INTESTAZIONE_EMAIL}\n\nGentili tutte e tutti,\n\n"
             f"per il concorso {codice} le domande sono scadute il {atti._data_it(x['scadenza'])}, ma né su Selezioni Online né sul sito URP "
             "risultano la graduatoria o un provvedimento di conclusione della procedura (concorso deserto, esito negativo o revoca).\n\n"
             "Vi chiediamo di indicarci, rispondendo a questa email:\n"
             "- se il concorso è andato deserto o si è concluso con esito negativo: in questo caso vi chiediamo di caricare il provvedimento "
             "su Selezioni Online (come allegato di tipo «deserto»);\n"
             "- se invece la procedura è ancora in corso o si è conclusa con una graduatoria e mancano solo i dati: in questo caso vi chiediamo "
             "di aggiornare Selezioni Online.\n\n"
             "Potrebbe trattarsi anche di un nostro errore: in questo caso vi chiediamo di segnalarcelo.\n\n"
             f"Cordiali saluti,\n{posta.impostazioni_email()['firma'] or ''}\n")
    storico = [dict(r) for r in conn.execute("SELECT quando, esito, utente FROM richiesta_deserto WHERE scheda_id = ? ORDER BY id DESC", (scheda_id,))]
    return {"scheda_id": scheda_id, "codice": codice, "destinatari": _destinatari(conn, s), "cc": copia_segreteria(),
            "oggetto": f"Concorso {codice}: è andato deserto o mancano i dati?", "corpo": corpo, "storico": storico, "posta": posta.stato()}


def invia(conn, scheda_id: int, oggetto: str, corpo: str, utente: str | None, modo: str | None = None) -> dict:
    if modo not in MODI:
        raise ValueError("Modo di invio non valido")
    a = anteprima(conn, scheda_id)
    if a is None:
        raise ValueError("Il concorso non risulta più senza esito")
    if not a["destinatari"]:
        raise ValueError("Nessuna email RdP per questo concorso: aggiorna i referenti da Selezioni Online")
    if not (oggetto or "").strip() or not (corpo or "").strip():
        raise ValueError("Oggetto e testo sono obbligatori")
    if comunicazioni.contiene_dati_candidati(oggetto, corpo):
        raise ValueError("Il testo sembra contenere un codice fiscale: invio bloccato")
    prova = posta.invia(a["destinatari"], oggetto, corpo, modo=modo, cc=a["cc"] or None)
    conn.execute("INSERT INTO richiesta_deserto (scheda_id, codice, destinatari, oggetto, esito, utente, quando) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (scheda_id, a["codice"], json.dumps(a["destinatari"]), oggetto, "prova" if prova else "inviata", utente, _adesso()))
    return {"ok": True, "prova": prova}
