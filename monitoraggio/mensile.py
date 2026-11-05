"""Monitoraggio del mese (spec 006): periodo dei dati, testo della richiesta, solleciti per bando."""
import json
import re
from datetime import date, datetime, timezone

from . import excel_mese, posta

SEGNAPOSTI = ("mese", "mese_dati", "cartella", "file_scorrimenti", "link_scorrimenti", "file_graduatorie", "link_graduatorie")
_CODICE_FISCALE = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.I)

OGGETTO_PREDEFINITO = "Monitoraggio {mese}: predisposizione dei dati"
TESTO_PREDEFINITO = """Buongiorno a tutte e tutti,
come di consueto vi chiedo di predisporre i dati per il monitoraggio per il mese di {mese}.

Per ottimizzare il lavoro e coordinarci in accordo con Chiara e Gaetano ho predisposto due file Excel condivisi che vi allego qui con il link e che trovate anche dentro la cartella {cartella}.

La richiesta è di inserire all'interno dei seguenti file, ognuno per la sua linea di attività o in base ai concorsi per cui siete referenti, i seguenti dati:

- scorrimenti: {file_scorrimenti}
  {link_scorrimenti}
  i dati relativi agli scorrimenti del mese di {mese_dati}.

- graduatoria: {file_graduatorie}
  {link_graduatorie}
  di verificare che i dati presenti siano aggiornati perché estratti da Selezioni Online e, a meno di graduatorie non caricate su Selezioni Online, non serve inserire dentro il file ma solo verificare che i bandi siano presenti tutti; nel caso andrà aggiornato Selezioni Online.

Vi chiedo gentilmente, prima di inviare dati a me, di coordinarvi con Chiara e Gaetano per la finalizzazione del monitoraggio e di lavorare solo sui file condivisi.

Inoltre all'interno del file Graduatorie e bandi pubblicati, nella tab graduatorie sono evidenziate in giallo le graduatorie pubblicate sprovviste di numero di graduatoria.
Per altro sono a disposizione.

Ciao,
Daniele
"""


class MeseEsistente(Exception):
    pass


class MeseChiuso(Exception):
    pass


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mese_valido(valore: str | None) -> bool:
    return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", valore or ""))


def mese_precedente(mese: str) -> str:
    anno, numero = map(int, mese.split("-"))
    return f"{anno - 1}-12" if numero == 1 else f"{anno}-{numero - 1:02d}"


def etichetta(mese: str) -> str:
    """'2026-05' -> 'maggio 26'."""
    return excel_mese.etichetta_file(mese).replace("-", " ")


def elenco(conn) -> list[dict]:
    inviati = {r["mese"]: r["n"] for r in conn.execute("SELECT mese, COUNT(*) AS n FROM sollecito GROUP BY mese")}
    return [{**dict(r), "etichetta": etichetta(r["mese"]), "etichetta_dati": etichetta(r["mese_dati"]),
             "solleciti_inviati": inviati.get(r["mese"], 0)}
            for r in conn.execute("SELECT mese, mese_dati, creato_da, creato_il, stato, chiuso_da, chiuso_il "
                                  "FROM monitoraggio_mese ORDER BY mese DESC")]


def mese_anno_corrente(numero, oggi: date | None = None) -> str:
    """Il mese scelto nell'anno corrente: l'anno non si sceglie."""
    if not isinstance(numero, int) or not 1 <= numero <= 12:
        raise ValueError("Mese non valido")
    return f"{(oggi or date.today()).year}-{numero:02d}"


def crea(conn, mese: str, mese_dati: str | None, autore: str | None) -> dict:
    if not mese_valido(mese) or (mese_dati and not mese_valido(mese_dati)):
        raise ValueError("Mese non valido")
    if conn.execute("SELECT 1 FROM monitoraggio_mese WHERE mese = ?", (mese,)).fetchone():
        raise MeseEsistente(mese)
    conn.execute("INSERT INTO monitoraggio_mese (mese, mese_dati, creato_da, creato_il) VALUES (?, ?, ?, ?)",
                 (mese, mese_dati or mese_precedente(mese), autore, _adesso()))
    _evento(conn, mese, "creato", autore)
    return leggi(conn, mese)


def _evento(conn, mese: str, azione: str, autore: str | None) -> None:
    conn.execute("INSERT INTO monitoraggio_evento (mese, azione, autore, quando) VALUES (?, ?, ?, ?)",
                 (mese, azione, autore, _adesso()))


def verifica_aperto(conn, mese: str) -> None:
    riga = conn.execute("SELECT stato FROM monitoraggio_mese WHERE mese = ?", (mese,)).fetchone()
    if riga and riga["stato"] == "chiuso":
        raise MeseChiuso("Il monitoraggio è chiuso: riaprilo per modificarlo")


def chiudi(conn, mese: str, autore: str | None) -> dict:
    """Salva la fotografia del mese nel database, tutta insieme o per niente. Solo conteggi e stati:
    i dati dei candidati restano fuori (constitution, Principio II)."""
    from . import atti, compat, punteggi

    verifica_aperto(conn, mese)
    monitoraggio = leggi(conn, mese)
    dal, al = periodo_dati(monitoraggio)
    righe = atti.elenco_atti(conn, dal, al)
    inviati = solleciti(conn, mese)
    conteggi = punteggi.elenco_periodo(conn, dal, al)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for tabella in ("monitoraggio_riga", "monitoraggio_punteggi", "monitoraggio_fonte"):
            conn.execute(f"DELETE FROM {tabella} WHERE mese = ?", (mese,))
        for r in righe:
            f = r["fonti"]
            inviato = inviati.get(r.get("codice") or "") or inviati.get(r.get("numero_bando") or "") or {}
            conn.execute(
                "INSERT INTO monitoraggio_riga (mese, numero_bando, codice, titolo_bando, tipologia, atto, sottotipo, data, "
                "protocollo, sol_stato, sol_protocollo, urp_stato, urp_protocollo, segreteria_stato, segreteria_protocollo, "
                "rdp, note, difforme, sollecito_stato, sollecito_autore, sollecito_quando) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (mese, r.get("numero_bando"), r.get("codice"), r.get("titolo_bando"), r.get("tipologia"), r["atto"],
                 r.get("sottotipo"), r.get("data"), r.get("protocollo"), f["sol"].get("stato"), f["sol"].get("protocollo"),
                 f["urp"].get("stato"), f["urp"].get("protocollo"), f["segreteria"].get("stato"), f["segreteria"].get("protocollo"),
                 json.dumps(r.get("rdp") or [], ensure_ascii=False), json.dumps(r.get("note") or [], ensure_ascii=False),
                 int(bool(r.get("difforme"))), inviato.get("stato"), inviato.get("autore"), inviato.get("quando")))
        for p in conteggi:
            conn.execute(
                "INSERT INTO monitoraggio_punteggi (mese, numero_bando, codice, protocollo, data, domande, con_punteggi, vincitori, "
                "idonei, scorrimento, senza_protocollo, esito, verificato_il, difformita) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (mese, p.get("numero_bando"), p.get("codice"), p.get("protocollo"), p.get("data"), p.get("domande"),
                 p.get("con_punteggi"), p.get("vincitori"), p.get("idonei"), p.get("scorrimento"), p.get("senza_protocollo"),
                 p.get("esito"), p.get("verificato_il"), json.dumps(p.get("difformita") or [], ensure_ascii=False)))
        for fonte in ("urp", "sol"):
            conn.execute("INSERT INTO monitoraggio_fonte (mese, fonte, ultima_raccolta) VALUES (?, ?, ?)",
                         (mese, fonte, compat.ultima_riuscita(conn, fonte)))
        conn.execute("UPDATE monitoraggio_mese SET stato = 'chiuso', chiuso_da = ?, chiuso_il = ? WHERE mese = ?",
                     (autore, _adesso(), mese))
        _evento(conn, mese, "chiuso", autore)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return leggi(conn, mese)


def riapri(conn, mese: str, autore: str | None) -> dict:
    """Riapre il mese: la fotografia resta finché una nuova chiusura non la sostituisce."""
    conn.execute("UPDATE monitoraggio_mese SET stato = 'aperto', chiuso_da = NULL, chiuso_il = NULL WHERE mese = ?", (mese,))
    _evento(conn, mese, "riaperto", autore)
    return leggi(conn, mese)


def fotografia(conn, mese: str) -> dict:
    righe = [{**dict(r), "rdp": json.loads(r["rdp"] or "[]"), "note": json.loads(r["note"] or "[]")}
             for r in conn.execute("SELECT * FROM monitoraggio_riga WHERE mese = ? ORDER BY data DESC, codice", (mese,))]
    return {"righe": righe, "totale": len(righe), "difformi": sum(1 for r in righe if r["difforme"]),
            "inviate": sum(1 for r in righe if r["difforme"] and r["sollecito_stato"]),
            "punteggi": [{**dict(r), "difformita": json.loads(r["difformita"] or "[]")}
                         for r in conn.execute("SELECT * FROM monitoraggio_punteggi WHERE mese = ? ORDER BY codice", (mese,))],
            "fonti": [dict(r) for r in conn.execute("SELECT fonte, ultima_raccolta FROM monitoraggio_fonte WHERE mese = ?", (mese,))],
            "eventi": [dict(r) for r in conn.execute("SELECT azione, autore, quando FROM monitoraggio_evento WHERE mese = ? "
                                                     "ORDER BY id DESC", (mese,))]}


def leggi(conn, mese: str) -> dict | None:
    riga = conn.execute("SELECT * FROM monitoraggio_mese WHERE mese = ?", (mese,)).fetchone()
    return dict(riga) if riga else None


def aggiorna(conn, mese: str, campi: dict) -> dict | None:
    ammessi = {k: v for k, v in campi.items() if k in ("mese_dati", "link_scorrimenti", "link_graduatorie", "oggetto", "testo")}
    if "mese_dati" in ammessi and not mese_valido(ammessi["mese_dati"]):
        raise ValueError("Mese dei dati non valido")
    for colonna, valore in ammessi.items():
        conn.execute(f"UPDATE monitoraggio_mese SET {colonna} = ? WHERE mese = ?",
                     ((valore or "").strip() or None, mese))
    return leggi(conn, mese)


def impostazione(conn, chiave: str, predefinito=None):
    riga = conn.execute("SELECT valore FROM impostazione WHERE chiave = ?", (chiave,)).fetchone()
    return riga["valore"] if riga and riga["valore"] is not None else predefinito


def imposta(conn, chiave: str, valore, autore: str | None) -> None:
    conn.execute("INSERT INTO impostazione (chiave, valore, modificata_da, modificata_il) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore, modificata_da = excluded.modificata_da, "
                 "modificata_il = excluded.modificata_il", (chiave, valore, autore, _adesso()))


def impostazioni_email(conn) -> dict:
    return {"oggetto": impostazione(conn, "email_oggetto", OGGETTO_PREDEFINITO),
            "testo": impostazione(conn, "email_testo", TESTO_PREDEFINITO),
            "destinatari": json.loads(impostazione(conn, "email_destinatari", "[]"))}


def salva_impostazioni_email(conn, dati: dict, autore: str | None) -> dict:
    if "destinatari" in dati:
        destinatari = dividi_indirizzi(dati["destinatari"])
        sbagliati = posta.indirizzi_non_validi(destinatari)
        if sbagliati:
            raise ValueError("Indirizzi non validi: " + ", ".join(sbagliati))
        imposta(conn, "email_destinatari", json.dumps(destinatari), autore)
    if "oggetto" in dati:
        imposta(conn, "email_oggetto", (dati["oggetto"] or "").strip() or None, autore)
    if "testo" in dati:
        imposta(conn, "email_testo", (dati["testo"] or "").strip() or None, autore)
    return impostazioni_email(conn)


def dividi_indirizzi(valore) -> list[str]:
    parti = valore if isinstance(valore, list) else re.split(r"[;,\n]+", valore or "")
    return list(dict.fromkeys(p.strip().lower() for p in parti if p and p.strip()))


def valori_segnaposto(monitoraggio: dict) -> dict:
    mese = monitoraggio["mese"]
    anno, numero = mese.split("-")
    return {"mese": etichetta(mese), "mese_dati": excel_mese.MESI[int(monitoraggio["mese_dati"].split("-")[1]) - 1],
            "cartella": f"UFFICIO CONCORSI -> MONITORAGGIO -> {anno} -> {excel_mese.MESI[int(numero) - 1].upper()}",
            "file_scorrimenti": excel_mese.nome_scorrimenti(mese), "link_scorrimenti": monitoraggio.get("link_scorrimenti") or "",
            "file_graduatorie": excel_mese.nome_graduatorie(mese), "link_graduatorie": monitoraggio.get("link_graduatorie") or ""}


def _sostituisci(testo: str, valori: dict) -> str:
    for nome, valore in valori.items():
        testo = testo.replace("{" + nome + "}", valore)
    return testo


def email_compilazione(conn, monitoraggio: dict) -> dict:
    """Testo pronto, destinatari e cosa manca per poterlo inviare."""
    generale = impostazioni_email(conn)
    oggetto = monitoraggio.get("oggetto") or generale["oggetto"]
    testo = monitoraggio.get("testo") or generale["testo"]
    valori = valori_segnaposto(monitoraggio)
    mancanti = [etichetta_campo for nome, etichetta_campo in
                (("link_scorrimenti", "link del file degli scorrimenti"), ("link_graduatorie", "link del file delle graduatorie"))
                if "{" + nome + "}" in testo and not valori[nome]]
    if not generale["destinatari"]:
        mancanti.append("destinatari")
    return {"oggetto": _sostituisci(oggetto, valori), "corpo": _sostituisci(testo, valori),
            "modello_oggetto": oggetto, "modello_testo": testo, "personalizzato": bool(monitoraggio.get("testo")),
            "destinatari": generale["destinatari"], "mancanti": mancanti}


def registra_invio(conn, tipo: str, mese: str | None, numero_bando: str | None, utente: str | None,
                   destinatari: list[str], oggetto: str, esito: str, errore: str | None = None) -> None:
    conn.execute("INSERT INTO invio_email (tipo, mese, numero_bando, utente, quando, destinatari, oggetto, esito, errore) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (tipo, mese, numero_bando, utente, _adesso(), ", ".join(destinatari), oggetto, esito, errore))


def invii(conn, mese: str, limite: int = 200) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT tipo, numero_bando, utente, quando, destinatari, oggetto, esito, errore FROM invio_email WHERE mese = ? "
        "ORDER BY id DESC LIMIT ?", (mese, limite))]


def solleciti(conn, mese: str) -> dict[str, dict]:
    return {r["numero_bando"]: dict(r) for r in conn.execute("SELECT * FROM sollecito WHERE mese = ?", (mese,))}


def segna(conn, mese: str, numero_bando: str, stato: str, autore: str | None, destinatari: list[str] | None = None,
          oggetto: str | None = None) -> None:
    conn.execute("INSERT INTO sollecito (mese, numero_bando, stato, autore, quando, destinatari, oggetto) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(mese, numero_bando) DO UPDATE SET stato = excluded.stato, "
                 "autore = excluded.autore, quando = excluded.quando, destinatari = excluded.destinatari, oggetto = excluded.oggetto",
                 (mese, numero_bando, stato, autore, _adesso(), ", ".join(destinatari or []), oggetto))


def togli_segno(conn, mese: str, numero_bando: str) -> None:
    conn.execute("DELETE FROM sollecito WHERE mese = ? AND numero_bando = ?", (mese, numero_bando))


def email_rdp(conn, bando: str) -> set[str]:
    """Gli RdP del bando a cui appartiene il codice, indipendenti da ciò che manda il browser. La pagina
    sceglie quelli del codice; i referenti del bando servono per gli atti senza codice."""
    righe = conn.execute(
        "SELECT r.email FROM referente r JOIN scheda s ON s.id = r.scheda_id WHERE r.attivo = 1 AND r.email IS NOT NULL "
        "AND (s.codice_originale = :b OR s.numero_bando = :b OR s.bando_id IN (SELECT bando_id FROM scheda "
        "WHERE (codice_originale = :b OR numero_bando = :b) AND bando_id IS NOT NULL))", {"b": bando})
    return {r["email"].strip().lower() for r in righe}


def contiene_dati_candidati(testo: str) -> bool:
    return bool(_CODICE_FISCALE.search(testo or ""))


def periodo_dati(monitoraggio: dict) -> tuple[str, str]:
    from .punteggi import intervallo
    return intervallo(monitoraggio["mese_dati"])


def link_vista(monitoraggio: dict) -> str:
    return f"/monitoraggio?monitoraggio={monitoraggio['mese']}&mese={monitoraggio['mese_dati']}"
