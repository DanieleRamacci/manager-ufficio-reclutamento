"""Monitoraggio del mese (spec 006): periodo dei dati, testo della richiesta, solleciti per bando."""
import json
import re
from datetime import date, datetime, timezone

from . import config, excel_mese, posta

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


class MeseAperto(Exception):
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
    inviati = {m: sum(c["stato"] != "da_confermare" for c in solleciti(conn, m).values())
               for m in [r["mese"] for r in conn.execute("SELECT mese FROM monitoraggio_mese")]}
    return [{**dict(r), "etichetta": etichetta(r["mese_dati"]), "etichetta_dati": etichetta(r["mese_dati"]),
             "solleciti_inviati": inviati.get(r["mese"], 0)}
            for r in conn.execute("SELECT mese, mese_dati, creato_da, creato_il, stato, chiuso_da, chiuso_il, tipologie, verifica_fonti_il "
                                  "FROM monitoraggio_mese ORDER BY mese DESC")]


def mese_anno_corrente(numero, oggi: date | None = None) -> str:
    """Il mese scelto nell'anno corrente: l'anno non si sceglie."""
    if not isinstance(numero, int) or not 1 <= numero <= 12:
        raise ValueError("Mese non valido")
    return f"{(oggi or date.today()).year}-{numero:02d}"


def mese_successivo(mese: str) -> str:
    anno, numero = map(int, mese.split("-"))
    return f"{anno + 1}-01" if numero == 12 else f"{anno}-{numero + 1:02d}"


TIPOLOGIE_MONITORABILI = config.TIPOLOGIE_MONITORATE


def tipologie_di(monitoraggio: dict) -> list[str]:
    return json.loads(monitoraggio.get("tipologie") or '["TI", "MOB"]')


def crea(conn, mese: str, mese_dati: str | None, autore: str | None, tipologie: list[str] | None = None) -> dict:
    if not mese_valido(mese) or (mese_dati and not mese_valido(mese_dati)):
        raise ValueError("Mese non valido")
    if tipologie is not None and (not tipologie or set(tipologie) - set(TIPOLOGIE_MONITORABILI)):
        raise ValueError("Scegli almeno una tipologia")
    if conn.execute("SELECT 1 FROM monitoraggio_mese WHERE mese = ?", (mese,)).fetchone():
        raise MeseEsistente(mese)
    conn.execute("INSERT INTO monitoraggio_mese (mese, mese_dati, creato_da, creato_il, tipologie) VALUES (?, ?, ?, ?, ?)",
                 (mese, mese_dati or mese_precedente(mese), autore, _adesso(), json.dumps(tipologie or ["TI", "MOB"])))
    _evento(conn, mese, "creato", autore)
    return leggi(conn, mese)


def _evento(conn, mese: str, azione: str, autore: str | None) -> None:
    conn.execute("INSERT INTO monitoraggio_evento (mese, azione, autore, quando) VALUES (?, ?, ?, ?)",
                 (mese, azione, autore, _adesso()))


def verifica_aperto(conn, mese: str) -> None:
    riga = conn.execute("SELECT stato FROM monitoraggio_mese WHERE mese = ?", (mese,)).fetchone()
    if riga and riga["stato"] == "chiuso":
        raise MeseChiuso("Il monitoraggio è chiuso: riaprilo per modificarlo")


def _genera_versione(conn, mese: str, autore: str | None, motivo: str | None, azioni) -> int:
    """Salva una nuova versione del mese, tutta insieme o per niente, senza toccare le precedenti. Solo
    conteggi e stati: i dati dei candidati restano fuori (constitution, Principio II)."""
    from . import atti, compat, punteggi

    monitoraggio = leggi(conn, mese)
    dal, al = periodo_dati(monitoraggio)
    righe = [r for r in atti.elenco_atti(conn, dal, al) if config.nel_monitoraggio(r.get("tipologia"))]
    inviati = solleciti(conn, mese)
    conteggi = [p for p in punteggi.elenco_periodo(conn, dal, al) if config.nel_monitoraggio(p.get("tipologia"))]
    conn.execute("BEGIN IMMEDIATE")
    try:
        versione = conn.execute("SELECT COALESCE(MAX(versione), 0) + 1 FROM monitoraggio_versione WHERE mese = ?",
                                (mese,)).fetchone()[0]
        conn.execute("INSERT INTO monitoraggio_versione (mese, versione, creata_da, creata_il, motivo) VALUES (?, ?, ?, ?, ?)",
                     (mese, versione, autore, _adesso(), (motivo or "").strip() or None))
        for r in righe:
            f = r["fonti"]
            inviato = inviati.get(r.get("codice") or "") or inviati.get(r.get("numero_bando") or "") or {}
            if inviato.get("stato") == "da_confermare":
                inviato = {}
            conn.execute(
                "INSERT INTO monitoraggio_riga (mese, versione, numero_bando, codice, titolo_bando, tipologia, atto, sottotipo, data, "
                "protocollo, sol_stato, sol_protocollo, urp_stato, urp_protocollo, segreteria_stato, segreteria_protocollo, "
                "rdp, note, difforme, sollecito_stato, sollecito_autore, sollecito_quando) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (mese, versione, r.get("numero_bando"), r.get("codice"), r.get("titolo_bando"), r.get("tipologia"), r["atto"],
                 r.get("sottotipo"), r.get("data"), r.get("protocollo"), f["sol"].get("stato"), f["sol"].get("protocollo"),
                 f["urp"].get("stato"), f["urp"].get("protocollo"), f["segreteria"].get("stato"), f["segreteria"].get("protocollo"),
                 json.dumps(r.get("rdp") or [], ensure_ascii=False), json.dumps(r.get("note") or [], ensure_ascii=False),
                 int(bool(r.get("difforme"))), inviato.get("stato"), inviato.get("autore"), inviato.get("quando")))
        for p in conteggi:
            conn.execute(
                "INSERT INTO monitoraggio_punteggi (mese, versione, numero_bando, codice, protocollo, data, domande, con_punteggi, "
                "vincitori, idonei, scorrimento, senza_protocollo, esito, verificato_il, difformita) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (mese, versione, p.get("numero_bando"), p.get("codice"), p.get("protocollo"), p.get("data"), p.get("domande"),
                 p.get("con_punteggi"), p.get("vincitori"), p.get("idonei"), p.get("scorrimento"), p.get("senza_protocollo"),
                 p.get("esito"), p.get("verificato_il"), json.dumps(p.get("difformita") or [], ensure_ascii=False)))
        for fonte in ("urp", "sol"):
            conn.execute("INSERT INTO monitoraggio_fonte (mese, versione, fonte, ultima_raccolta) VALUES (?, ?, ?, ?)",
                         (mese, versione, fonte, compat.ultima_riuscita(conn, fonte)))
        azioni()
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return versione


def chiudi(conn, mese: str, autore: str | None, motivo: str | None = None) -> dict:
    verifica_aperto(conn, mese)

    def segna_chiuso():
        conn.execute("UPDATE monitoraggio_mese SET stato = 'chiuso', chiuso_da = ?, chiuso_il = ? WHERE mese = ?",
                     (autore, _adesso(), mese))
        _evento(conn, mese, "chiuso", autore)
    _genera_versione(conn, mese, autore, motivo, segna_chiuso)
    return leggi(conn, mese)


def nuova_versione(conn, mese: str, autore: str | None, motivo: str | None = None) -> dict:
    """Rigenera un mese chiuso dai dati attuali, per esempio dopo una correzione su Selezioni Online."""
    if leggi(conn, mese)["stato"] != "chiuso":
        raise MeseAperto("Il monitoraggio è aperto: per salvarlo usa Chiudi")
    _genera_versione(conn, mese, autore, motivo, lambda: None)
    return leggi(conn, mese)


def riapri(conn, mese: str, autore: str | None) -> dict:
    """Riapre il mese: le versioni salvate restano."""
    conn.execute("UPDATE monitoraggio_mese SET stato = 'aperto', chiuso_da = NULL, chiuso_il = NULL WHERE mese = ?", (mese,))
    _evento(conn, mese, "riaperto", autore)
    return leggi(conn, mese)


def _dati_piu_recenti(conn, dal: str, al: str, creata_il: str) -> list[str]:
    """Cosa è cambiato dopo una versione, per suggerire di generarne una nuova."""
    da_segnalare = []
    if conn.execute("SELECT 1 FROM raccolta WHERE esito IN ('completata', 'completata_con_errori') AND fine > ?",
                    (creata_il,)).fetchone():
        da_segnalare.append("raccolta dei dati")
    from . import punteggi
    schede = [s["id"] for s in punteggi.schede_periodo(conn, dal, al)]
    if schede and conn.execute(f"SELECT 1 FROM punteggi_verifica WHERE verificato_il > ? AND scheda_id IN "
                               f"({', '.join('?' * len(schede))})", (creata_il, *schede)).fetchone():
        da_segnalare.append("verifica dei punteggi")
    return da_segnalare


def fotografia(conn, mese: str, versione: int | None = None) -> dict:
    versioni = []
    for v in conn.execute("SELECT * FROM monitoraggio_versione WHERE mese = ? ORDER BY versione DESC", (mese,)):
        conteggio = conn.execute(
            "SELECT COUNT(*) AS totale, COALESCE(SUM(difforme), 0) AS difformi, "
            "COALESCE(SUM(difforme = 1 AND sollecito_stato IS NOT NULL), 0) AS inviate "
            "FROM monitoraggio_riga WHERE mese = ? AND versione = ?", (mese, v["versione"])).fetchone()
        versioni.append({**dict(v), **dict(conteggio), "punteggi_verificati": conn.execute(
            "SELECT COUNT(*) FROM monitoraggio_punteggi WHERE mese = ? AND versione = ? AND verificato_il IS NOT NULL",
            (mese, v["versione"])).fetchone()[0]})
    ultima = versioni[0]["versione"] if versioni else None
    scelta = versione if any(v["versione"] == versione for v in versioni) else ultima
    chiave = (mese, scelta)
    righe = [{**dict(r), "rdp": json.loads(r["rdp"] or "[]"), "note": json.loads(r["note"] or "[]")}
             for r in conn.execute("SELECT * FROM monitoraggio_riga WHERE mese = ? AND versione = ? ORDER BY data DESC, codice", chiave)]
    monitoraggio = leggi(conn, mese)
    dati_piu_recenti = _dati_piu_recenti(conn, *periodo_dati(monitoraggio), versioni[0]["creata_il"]) if versioni else []
    return {"versione": scelta, "ultima": ultima, "versioni": versioni, "dati_piu_recenti": dati_piu_recenti,
            "righe": righe, "totale": len(righe), "difformi": sum(1 for r in righe if r["difforme"]),
            "inviate": sum(1 for r in righe if r["difforme"] and r["sollecito_stato"]),
            "punteggi": [{**dict(r), "difformita": json.loads(r["difformita"] or "[]")} for r in conn.execute(
                "SELECT * FROM monitoraggio_punteggi WHERE mese = ? AND versione = ? ORDER BY codice", chiave)],
            "fonti": [dict(r) for r in conn.execute(
                "SELECT fonte, ultima_raccolta FROM monitoraggio_fonte WHERE mese = ? AND versione = ?", chiave)],
            "eventi": [dict(r) for r in conn.execute("SELECT azione, autore, quando FROM monitoraggio_evento WHERE mese = ? "
                                                     "ORDER BY id DESC", (mese,))]}


def leggi(conn, mese: str) -> dict | None:
    riga = conn.execute("SELECT * FROM monitoraggio_mese WHERE mese = ?", (mese,)).fetchone()
    return dict(riga) if riga else None


def aggiorna(conn, mese: str, campi: dict) -> dict | None:
    ammessi = {k: v for k, v in campi.items() if k in ("mese_dati", "link_scorrimenti", "link_graduatorie", "oggetto", "testo", "tipologie")}
    if "mese_dati" in ammessi and not mese_valido(ammessi["mese_dati"]):
        raise ValueError("Mese dei dati non valido")
    if "tipologie" in ammessi:
        if not ammessi["tipologie"] or set(ammessi["tipologie"]) - set(TIPOLOGIE_MONITORABILI):
            raise ValueError("Scegli almeno una tipologia")
        ammessi["tipologie"] = json.dumps(ammessi["tipologie"])
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
    """Nomi, cartella e testi seguono il mese del monitoraggio: quello di riferimento dei dati."""
    mese = monitoraggio["mese_dati"]
    anno, numero = mese.split("-")
    return {"mese": etichetta(mese), "mese_dati": excel_mese.MESI[int(numero) - 1],
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


def _ultime_comunicazioni(conn, mese: str) -> dict[str, dict]:
    ultime: dict[str, dict] = {}
    for r in conn.execute("SELECT * FROM comunicazione WHERE mese = ? AND stato != 'prova' ORDER BY data, rowid", (mese,)):
        ultime[r["chiave"]] = dict(r)
    return ultime


def solleciti(conn, mese: str) -> dict[str, dict]:
    """Stato per codice: l'ultima comunicazione non di prova (specifiche grafiche, sezione 4)."""
    risultato = {}
    for chiave, c in _ultime_comunicazioni(conn, mese).items():
        if c["stato"] == "annullata":
            continue
        stato = "da_confermare" if c["stato"] == "da confermare" else "inviata_a_mano" if c["canale"] == "Segnata a mano" else "inviata"
        risultato[chiave] = {"mese": mese, "numero_bando": chiave, "stato": stato, "autore": c["utente"], "quando": c["data"],
                             "destinatari": ", ".join(json.loads(c["destinatari"] or "[]")), "oggetto": c["oggetto"],
                             "canale": c["canale"], "id": c["id"]}
    return risultato


def id_monitoraggio(monitoraggio: dict) -> str:
    """'MON-10.2026' dal mese di riferimento dei dati."""
    anno, numero = monitoraggio["mese_dati"].split("-")
    return f"MON-{numero}.{anno}"


def numero_gestione(conn, chiave: str) -> str:
    """Numero interno del codice, assegnato alla prima occorrenza e sempre uguale: '0430'."""
    cerca = "SELECT numero FROM gestione WHERE chiave = ?"
    riga = conn.execute(cerca, (chiave,)).fetchone()
    if not riga:  # scrive solo la prima volta: le letture non aspettano una raccolta in corso
        conn.execute("INSERT OR IGNORE INTO gestione (chiave, creato_il) VALUES (?, ?)", (chiave, _adesso()))
        riga = conn.execute(cerca, (chiave,)).fetchone()
    return f"{riga[0]:04d}"


def nuovo_id_comunicazione(conn, monitoraggio: dict, chiave: str, numero_bando: str | None) -> str:
    base = "/".join((id_monitoraggio(monitoraggio), numero_bando or chiave, numero_gestione(conn, chiave)))
    usati = conn.execute("SELECT COUNT(*) FROM comunicazione WHERE id = ? OR id LIKE ?", (base, base + "-%")).fetchone()[0]
    return f"{base}-{usati + 1}" if usati else base


def registra_comunicazione(conn, mese: str, chiave: str, numero_bando: str | None, canale: str, stato: str, utente: str | None,
                           destinatari: list[str] | None = None, oggetto: str | None = None, corpo: str | None = None,
                           n_difformita: int | None = None, cc: list[str] | None = None) -> str:
    id_c = nuovo_id_comunicazione(conn, leggi(conn, mese), chiave, numero_bando)
    conn.execute("INSERT INTO comunicazione (id, mese, chiave, numero_bando, codice, destinatari, cc, oggetto, corpo, n_difformita, canale, stato, data, utente) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (id_c, mese, chiave, numero_bando, chiave, json.dumps(destinatari or []), json.dumps(cc or []), oggetto, corpo, n_difformita, canale, stato, _adesso(), utente))
    return id_c


def indirizzi_messaggio(conn, mese: str, chiave: str) -> dict:
    """Le scelte per il messaggio di un codice: referenti tolti e persone aggiunte in copia."""
    r = conn.execute("SELECT esclusi, cc FROM comunicazione_indirizzi WHERE mese = ? AND chiave = ?", (mese, chiave)).fetchone()
    return {"esclusi": json.loads(r["esclusi"]), "cc": json.loads(r["cc"])} if r else {"esclusi": [], "cc": []}


def salva_indirizzi_messaggio(conn, mese: str, chiave: str, dati: dict, autore: str | None) -> None:
    def elenco(campo):
        valore = dati.get(campo) or []
        return dividi_indirizzi(",".join(str(x) for x in valore) if isinstance(valore, list) else str(valore))
    esclusi, cc = elenco("esclusi"), elenco("cc")
    sbagliati = posta.indirizzi_non_validi(cc)
    if sbagliati:
        raise ValueError("Indirizzi in copia non validi: " + ", ".join(sbagliati))
    conn.execute("INSERT INTO comunicazione_indirizzi (mese, chiave, esclusi, cc, modificata_da, modificata_il) VALUES (?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT(mese, chiave) DO UPDATE SET esclusi = excluded.esclusi, cc = excluded.cc, "
                 "modificata_da = excluded.modificata_da, modificata_il = excluded.modificata_il",
                 (mese, chiave, json.dumps(esclusi), json.dumps(cc), autore, _adesso()))


def segna(conn, mese: str, numero_bando: str, stato: str, autore: str | None, destinatari: list[str] | None = None,
          oggetto: str | None = None) -> None:
    """Spunta "inviata": conferma l'ultima copiata, altrimenti aggiunge una voce "Segnata a mano"."""
    ultima = _ultime_comunicazioni(conn, mese).get(numero_bando)
    if stato != "inviata" and ultima and ultima["stato"] == "da confermare":
        conn.execute("UPDATE comunicazione SET stato = 'inviata', data = ?, utente = ? WHERE id = ?", (_adesso(), autore, ultima["id"]))
        return
    registra_comunicazione(conn, mese, numero_bando, numero_bando.split(" ")[0], "Casella ufficio" if stato == "inviata" else "Segnata a mano",
                           "inviata", autore, destinatari, oggetto)


def togli_segno(conn, mese: str, numero_bando: str) -> None:
    """La spunta tolta resta nel registro come voce annullata."""
    ultima = _ultime_comunicazioni(conn, mese).get(numero_bando)
    if ultima and ultima["stato"] != "annullata":
        registra_comunicazione(conn, mese, numero_bando, ultima["numero_bando"], "Segnata a mano", "annullata", ultima["utente"])


def registro_comunicazioni(conn, mese: str | None = None, chiave: str | None = None) -> list[dict]:
    condizioni, argomenti = ["1 = 1"], []
    if mese:
        condizioni.append("c.mese = ?")
        argomenti.append(mese)
    if chiave:
        condizioni.append("c.chiave = ?")
        argomenti.append(chiave)
    righe = conn.execute(f"SELECT c.*, m.mese_dati, g.numero AS gestione FROM comunicazione c JOIN monitoraggio_mese m ON m.mese = c.mese "
                         f"LEFT JOIN gestione g ON g.chiave = c.chiave WHERE {' AND '.join(condizioni)} ORDER BY c.data DESC, c.rowid DESC", argomenti)
    return [{**dict(r), "destinatari": json.loads(r["destinatari"] or "[]"), "cc": json.loads(r["cc"] or "[]"), "monitoraggio": id_monitoraggio({"mese_dati": r["mese_dati"]}),
             "n_gestione": f"{r['gestione']:04d}" if r["gestione"] else None} for r in righe]


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
