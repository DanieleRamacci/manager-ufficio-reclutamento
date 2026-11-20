"""Spec 012: richiesta agli RdP per un concorso della scheda «Concorsi deserti».

Il testo dipende dallo stato del concorso: provvedimento da caricare su una fonte, deserto senza provvedimento,
graduatoria da pubblicare, oppure «è andato deserto o mancano i dati?». Stesso schema delle richieste di verifica
della spec 011: anteprima modificabile, invio di prova o reale, registro degli invii. Nessun dato dei candidati.
"""
import json
from datetime import datetime, timezone

from . import atti, comunicazioni, posta, referenti
from .avvisi_scorrimenti import copia_segreteria

MODI = (None, "prova", "ufficiale")
NOMI_FONTI = {"sol": "Selezioni Online", "urp": "sito URP"}


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ultime(conn) -> dict[int, dict]:
    """Ultima richiesta per scheda SOL."""
    return {r["scheda_id"]: dict(r) for r in conn.execute("SELECT scheda_id, esito, quando, utente FROM richiesta_deserto ORDER BY id")}


def _riga(conn, scheda_id: int) -> dict | None:
    """La riga della scheda «Concorsi deserti» per questa scheda SOL (per i deserti con provvedimento, quella con
    una fonte mancante, se c'è)."""
    righe = [r for r in atti.elenco_atti(conn, "2000-01-01", None, con_senza_esito=True)
             if r.get("stato_deserto") and r.get("scheda_sol_id") == scheda_id]
    return next((r for r in righe if r["difforme"]), None) or (righe[0] if righe else None)


def _destinatari(conn, scheda_id: int) -> list[str]:
    """RdP del codice, altrimenti del bando padre, altrimenti del bando."""
    s = conn.execute("SELECT * FROM scheda WHERE id = ?", (scheda_id,)).fetchone()
    if s is None:
        return []
    per_scheda = referenti.referenti_per_scheda(conn)
    padre = conn.execute("SELECT id FROM scheda WHERE fonte = 'sol' AND id_esterno = ?", (s["id_padre"],)).fetchone() if s["id_padre"] else None
    persone = per_scheda.get(s["id"]) or (per_scheda.get(padre["id"]) if padre else None) or referenti.referenti_per_bando(conn).get(s["bando_id"]) or []
    return list(dict.fromkeys((p.get("email") or "").strip().lower() for p in persone if p.get("email")))


def _testo(r: dict) -> tuple[str, str] | None:
    """(oggetto, richiesta) secondo lo stato; None se non c'è niente da chiedere."""
    codice = r.get("codice") or r.get("numero_bando")
    stato = r["stato_deserto"]
    if stato == "certo":
        mancanti = [NOMI_FONTI[f] for f in ("sol", "urp") if r["fonti"][f]["stato"] == "mancante"]
        if not mancanti:
            return None
        presenti = [NOMI_FONTI[f] for f in ("sol", "urp") if r["fonti"][f]["stato"] == "presente"]
        prot = f" (prot. {r['protocollo']} del {atti._data_it(r.get('data'))})" if r.get("protocollo") else ""
        su_sol = " su Selezioni Online come allegato di tipo «deserto»" if "Selezioni Online" in mancanti else ""
        return (f"Concorso {codice}: provvedimento di conclusione da caricare su {' e '.join(mancanti)}",
                f"il provvedimento di conclusione del concorso {codice}{prot} risulta su {' e '.join(presenti) or 'una sola fonte'} "
                f"ma non su {' e '.join(mancanti)}.\n\nVi chiediamo di caricarlo{su_sol}, così che le fonti siano allineate.")
    scadenza = f"le domande sono scadute il {atti._data_it(r.get('data'))}"
    if stato == "senza_provvedimento":
        return (f"Concorso {codice}: provvedimento di concorso deserto da caricare",
                f"per il concorso {codice} {scadenza} e su Selezioni Online {((r.get('esito_verifica') or {}).get('testo') or 'il concorso risulta deserto')}, "
                "ma né su Selezioni Online né sul sito URP risulta il provvedimento di conclusione (concorso deserto o esito negativo).\n\n"
                "Vi chiediamo di caricare il provvedimento su Selezioni Online (come allegato di tipo «deserto»), oppure di segnalarci se la situazione è diversa.")
    if stato == "graduatoria_mancante":
        return (f"Concorso {codice}: graduatoria da pubblicare",
                f"per il concorso {codice} {scadenza} e su Selezioni Online risultano vincitori o idonei, "
                "ma la graduatoria non risulta pubblicata né su Selezioni Online né sul sito URP.\n\n"
                "Vi chiediamo di caricare la graduatoria su Selezioni Online (allegato di tipo graduatoria, con il protocollo) "
                "e di completare i dati della graduatoria.")
    return (f"Concorso {codice}: è andato deserto o mancano i dati?",
            f"per il concorso {codice} {scadenza}, ma né su Selezioni Online né sul sito URP "
            "risultano la graduatoria o un provvedimento di conclusione della procedura (concorso deserto, esito negativo o revoca).\n\n"
            "Vi chiediamo di indicarci, rispondendo a questa email:\n"
            "- se il concorso è andato deserto o si è concluso con esito negativo: in questo caso vi chiediamo di caricare il provvedimento "
            "su Selezioni Online (come allegato di tipo «deserto»);\n"
            "- se invece la procedura è ancora in corso o si è conclusa con una graduatoria: in questo caso vi chiediamo "
            "di aggiornare Selezioni Online (punteggi, graduatoria e relativi allegati).")


def anteprima(conn, scheda_id: int) -> dict | None:
    r = _riga(conn, scheda_id)
    testo = _testo(r) if r else None
    if testo is None:
        return None
    oggetto, richiesta = testo
    corpo = (f"{comunicazioni.INTESTAZIONE_EMAIL}\n\nGentili tutte e tutti,\n\n{richiesta}\n\n"
             "Potrebbe trattarsi anche di un nostro errore: in questo caso vi chiediamo di segnalarcelo rispondendo a questa email.\n\n"
             f"Cordiali saluti,\n{posta.impostazioni_email()['firma'] or ''}\n")
    storico = [dict(x) for x in conn.execute("SELECT quando, esito, utente FROM richiesta_deserto WHERE scheda_id = ? ORDER BY id DESC", (scheda_id,))]
    return {"scheda_id": scheda_id, "codice": r.get("codice") or r.get("numero_bando"), "stato": r["stato_deserto"],
            "destinatari": _destinatari(conn, scheda_id), "cc": copia_segreteria(),
            "oggetto": oggetto, "corpo": corpo, "storico": storico, "posta": posta.stato()}


def invia(conn, scheda_id: int, oggetto: str, corpo: str, utente: str | None, modo: str | None = None) -> dict:
    if modo not in MODI:
        raise ValueError("Modo di invio non valido")
    a = anteprima(conn, scheda_id)
    if a is None:
        raise ValueError("Per questo concorso non c'è niente da chiedere ai referenti")
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
