"""Protocolli letti dalle email di Titulus in copia (spec 010, approccio del 2026-11-19).

Un programma sul PC della segreteria legge le email «Il sistema di protocollo le ha assegnato il seguente documento in copia
conoscenza» e manda qui solo numero, data, segnatura, oggetto, link Titulus, data di ricezione e identificativo del messaggio,
con una chiave personale. Qui si propone il tipo di atto leggendo l'oggetto (con la frase da cui viene), si fanno i controlli
e la segreteria approva, corregge o scarta. Un atto approvato vale nel confronto come riga del file della segreteria
«aggiunta automaticamente», finché non compare nel file caricato. I documenti su Titulus non si aprono mai.
"""
import hashlib
import io
import json
import re
import secrets
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import segreteria
from .normalizza import codice_sotto, norm_space, numero_bando, protocollo

CATEGORIE = {"graduatoria": "Graduatoria", "scorrimento": "Scorrimento / utilizzo graduatoria", "rettifica": "Rettifica graduatoria",
             "bando": "Bando", "autorizzazione": "Autorizzazione del DG agli scorrimenti", "rinuncia": "Rinuncia",
             "commissione": "Commissione", "altro": "Altro documento"}
NEL_FILE = ("graduatoria", "scorrimento", "rettifica", "bando")  # quelli che diventano righe del file della segreteria
SOTTOTIPI = {"ordinario": "scorrimento", "subentro": "subentro (per rinuncia)", "cessazione": "cessazione dopo i 6 mesi"}
MAX_VOCI = 500
_NUMERO = re.compile(r"N\.\s*(\d{1,7})\s+del\s+(\d{8})\s*\(([^)\s]+)\)")


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ lettura e classificazione

def leggi_email(oggetto_email: str | None, corpo: str) -> dict | None:
    """I dati di un'email di Titulus; None se non è un'email di protocollo."""
    m = _NUMERO.search(corpo or "")
    if not m:
        return None
    o = re.search(r"Oggetto:\s*(.+)", corpo)
    link = re.search(r"https://titulus[^\s<>\"']+", corpo)
    return {"numero": m.group(1), "data": m.group(2), "segnatura": m.group(3),
            "oggetto": norm_space(o.group(1)) if o else norm_space(re.sub(r"^\s*\[CC\]\s*:?\s*", "", oggetto_email or "")),
            "link": link.group(0) if link else None}


_REGOLE = [  # (categoria, sottotipo, espressione sull'oggetto); vince la prima
    ("rettifica", None, r"rettific\w*|errata\s+corrige"),
    ("autorizzazione", None, r"autorizz\w*\s+(?:\w+\s+){0,3}(?:scorriment\w*|utilizz\w*)|assegnazione\s+di\s+n\.?\s*\d+\s+unit\w*.{0,80}utilizz\w*"),
    ("scorrimento", "subentro", r"(?:scorriment\w*|utilizz\w*\s+(?:della\s+|delle\s+)?graduatori\w*).{0,120}rinunci\w*|rinunci\w*.{0,120}(?:scorriment\w*|utilizz\w*)|subentr\w*"),
    ("scorrimento", "cessazione", r"(?:scorriment\w*|utilizz\w*).{0,120}cessazion\w*"),
    ("scorrimento", "ordinario", r"scorriment\w*|utilizz\w*\s+(?:della\s+|delle\s+)?graduatori\w*|assunzion\w*.{0,80}mediante\s+(?:l['’]\s*)?utilizz\w*"),
    ("graduatoria", None, r"approvazion\w*\s+(?:della\s+)?graduatori\w*|graduatoria\s+(?:finale|di\s+merito)|nomina\s+(?:del\s+|dei\s+|della\s+)?vincitor\w*"),
    ("rinuncia", None, r"rinunci\w*"),
    ("commissione", None, r"commission\w*"),
    ("bando", None, r"(?:emanazion\w*|indizion\w*)\s.{0,60}bando|^bando\b|bando\s+di\s+concorso"),
]


def classifica(oggetto: str) -> dict:
    """La proposta dall'oggetto, con la frase da cui viene: è solo una proposta, la segreteria la conferma o la corregge."""
    for categoria, sottotipo, espressione in _REGOLE:
        m = re.search(espressione, oggetto or "", re.I)
        if m:
            return {"categoria": categoria, "sottotipo": sottotipo, "numero_bando": numero_bando(oggetto), "codice_sotto": codice_sotto(oggetto),
                    "motivo": f"nell'oggetto: «{norm_space(m.group(0))[:90]}»"}
    return {"categoria": "altro", "sottotipo": None, "numero_bando": numero_bando(oggetto), "codice_sotto": codice_sotto(oggetto),
            "motivo": "nell'oggetto non c'è una parola che indichi graduatoria, scorrimento, rettifica o bando"}


def _data_iso(aaaammgg: str) -> str:
    return f"{aaaammgg[:4]}-{aaaammgg[4:6]}-{aaaammgg[6:8]}"


def ricevi(conn, voci: list[dict], utente: str, casella: str | None) -> dict:
    """Le email mandate dal programma. Stesso protocollo da più caselle o più volte: una riga, con tutte le ricezioni;
    se l'oggetto è diverso lo si conserva per mostrarlo."""
    if not isinstance(voci, list) or len(voci) > MAX_VOCI:
        raise ValueError(f"Servono al massimo {MAX_VOCI} email per invio")
    nuove = aggiornate = 0
    for v in voci:
        numero, data = str(v.get("numero") or "").strip(), str(v.get("data") or "").strip()
        oggetto = norm_space(str(v.get("oggetto") or ""))[:500]
        link = str(v.get("link") or "").strip()
        if not re.fullmatch(r"\d{1,7}", numero) or not re.fullmatch(r"20\d{6}", data) or not oggetto:
            continue
        if link and not link.startswith("https://titulus"):
            link = ""
        numero = protocollo(numero)
        ricezione = {"casella": str(v.get("casella") or casella or "")[:120], "utente": utente, "il": str(v.get("ricevuta_il") or "")[:32],
                     "messaggio": hashlib.sha256(str(v.get("id_messaggio") or "").encode()).hexdigest()[:16]}
        riga = conn.execute("SELECT * FROM protocollo_email WHERE numero = ? AND anno = ?", (numero, data[:4])).fetchone()
        if riga is None:
            proposta = classifica(oggetto)
            conn.execute("INSERT INTO protocollo_email (numero, anno, data, segnatura, oggetto, link, ricevute, prima_ricezione, categoria, sottotipo, "
                         "numero_bando, codice_sotto, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (numero, data[:4], _data_iso(data), str(v.get("segnatura") or "")[:60], oggetto, link or None, json.dumps([ricezione]),
                          _adesso(), proposta["categoria"], proposta["sottotipo"], proposta["numero_bando"], proposta["codice_sotto"], None))
            nuove += 1
            continue
        ricevute = json.loads(riga["ricevute"])
        if any(r["messaggio"] == ricezione["messaggio"] for r in ricevute):
            continue  # la stessa email già mandata
        ricevute.append(ricezione)
        diversi = json.loads(riga["oggetti_diversi"])
        if oggetto != riga["oggetto"] and oggetto not in diversi:
            diversi.append(oggetto)
        conn.execute("UPDATE protocollo_email SET ricevute = ?, oggetti_diversi = ?, link = COALESCE(link, ?) WHERE id = ?",
                     (json.dumps(ricevute), json.dumps(diversi), link or None, riga["id"]))
        aggiornate += 1
    return {"nuove": nuove, "gia_presenti": aggiornate}


# ------------------------------------------------------------------ controlli

def _simili(a: str, b: str) -> bool:
    """Uguali a meno di una cifra (anche la prima) o di una cifra in più o in meno: possibile errore di battitura."""
    if a == b:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if abs(len(a) - len(b)) == 1:
        corto, lungo = sorted((a, b), key=len)
        return any(lungo[:i] + lungo[i + 1:] == corto for i in range(len(lungo)))
    return False


def elenco(conn) -> list[dict]:
    righe = [dict(r) for r in conn.execute("SELECT * FROM protocollo_email ORDER BY data DESC, CAST(numero AS INTEGER) DESC")]
    versione = segreteria.versione_in_uso(conn)
    nel_file = {}
    if versione:
        for a in conn.execute("SELECT categoria, numero_bando, codice_sotto, protocollo, data, sottotipo FROM segreteria_atto WHERE versione_id = ? "
                              "AND protocollo IS NOT NULL", (versione["id"],)):
            nel_file.setdefault(str(a["protocollo"]), []).append(dict(a))
    fonti = {}
    for d in conn.execute("SELECT d.protocollo, d.categoria, s.fonte FROM documento d JOIN scheda s ON s.id = d.scheda_id "
                          "WHERE d.presente = 1 AND d.protocollo IS NOT NULL"):
        fonti.setdefault(str(d["protocollo"]), set()).add((d["fonte"], d["categoria"]))
    bandi = {r["numero_bando"] for r in conn.execute("SELECT numero_bando FROM bando WHERE numero_bando IS NOT NULL")}
    per_anno: dict[str, list[str]] = {}
    for r in righe:
        per_anno.setdefault(r["anno"], []).append(r["numero"])
    for r in righe:
        r["ricevute"] = json.loads(r["ricevute"])
        r["oggetti_diversi"] = json.loads(r["oggetti_diversi"])
        proposta = classifica(r["oggetto"])
        r["motivo"] = proposta["motivo"]
        r["proposta_originale"] = {k: proposta[k] for k in ("categoria", "sottotipo", "numero_bando", "codice_sotto")}
        controlli = []
        if len({x["casella"] or x["utente"] for x in r["ricevute"]}) > 1 or len(r["ricevute"]) > 1:
            controlli.append({"livello": "info", "testo": f"stesso protocollo ricevuto {len(r['ricevute'])} volte"})
        for o in r["oggetti_diversi"]:
            controlli.append({"livello": "attenzione", "testo": f"stesso protocollo con un altro oggetto: «{o}»"})
        for n in per_anno.get(r["anno"], []):
            if _simili(r["numero"], n):
                controlli.append({"livello": "attenzione", "testo": f"protocollo simile già ricevuto: {n} (errore di battitura?)"})
        seg = nel_file.get(r["numero"], [])
        r["nel_file_segreteria"] = bool(seg)
        for a in seg:
            diverso = r["categoria"] in NEL_FILE and a["categoria"] != r["categoria"]
            controlli.append({"livello": "attenzione" if diverso else "ok",
                              "testo": f"già nel file della segreteria come {a['categoria']} del bando {a['numero_bando']} del {a['data']}"
                                       + (f" ({a['sottotipo']})" if a.get("sottotipo") else "") + (": categoria diversa" if diverso else "")})
        if r["categoria"] in NEL_FILE and not seg:
            controlli.append({"livello": "manca", "testo": "non è nel file della segreteria"})
        for fonte, categoria in sorted(fonti.get(r["numero"], ())):
            controlli.append({"livello": "ok", "testo": f"presente su {'URP' if fonte == 'urp' else 'Selezioni Online'} come {categoria}"})
        if r["categoria"] in NEL_FILE and r["numero_bando"] and r["numero_bando"] not in bandi:
            controlli.append({"livello": "attenzione", "testo": f"bando {r['numero_bando']} non trovato nel sistema"})
        if r["categoria"] in NEL_FILE and not r["numero_bando"]:
            controlli.append({"livello": "attenzione", "testo": "numero del bando non riconosciuto nell'oggetto: indicalo con Modifica"})
        r["controlli"] = controlli
    return righe


# ------------------------------------------------------------------ decisioni

def modifica(conn, id_riga: int, dati: dict) -> None:
    categoria = dati.get("categoria")
    if categoria not in CATEGORIE:
        raise ValueError("Tipo di documento non valido")
    sottotipo = dati.get("sottotipo") or None
    if categoria == "scorrimento" and sottotipo not in SOTTOTIPI:
        raise ValueError("Per uno scorrimento indica scorrimento, subentro o cessazione")
    if categoria != "scorrimento":
        sottotipo = None
    nb = numero_bando(str(dati.get("numero_bando") or "")) if dati.get("numero_bando") else None
    if dati.get("numero_bando") and not nb:
        raise ValueError("Numero del bando non valido (es. 367.434)")
    conn.execute("UPDATE protocollo_email SET categoria = ?, sottotipo = ?, numero_bando = ?, codice_sotto = ?, note = ? WHERE id = ?",
                 (categoria, sottotipo, nb, (str(dati.get("codice_sotto") or "").strip() or None), (str(dati.get("note") or "").strip()[:500] or None), id_riga))


def decidi(conn, id_riga: int, stato: str, utente: str | None) -> None:
    if stato not in ("approvato", "scartato", "da_verificare"):
        raise ValueError("Stato non valido")
    riga = conn.execute("SELECT * FROM protocollo_email WHERE id = ?", (id_riga,)).fetchone()
    if not riga:
        raise LookupError("Protocollo non trovato")
    if stato == "approvato" and riga["categoria"] in NEL_FILE and not riga["numero_bando"]:
        raise ValueError("Per approvarlo serve il numero del bando: usa Modifica")
    conn.execute("UPDATE protocollo_email SET stato = ?, deciso_da = ?, deciso_il = ? WHERE id = ?",
                 (stato, utente if stato != "da_verificare" else None, _adesso() if stato != "da_verificare" else None, id_riga))


def atti_approvati(conn, gia_nel_file: set[str]) -> list[dict]:
    """Gli atti approvati che non sono ancora nel file caricato, nella forma delle righe del file della segreteria."""
    return [{"id": None, "categoria": r["categoria"], "numero_bando": r["numero_bando"], "codice_sotto": r["codice_sotto"],
             "protocollo": r["numero"], "data": r["data"], "persone": 0, "protocollo_privato": None, "in_ambito": 1,
             "sottotipo": {"subentro": "subentro"}.get(r["sottotipo"], "ordinario") if r["categoria"] == "scorrimento" else None,
             "titolo": r["oggetto"], "aggiunto_automaticamente": True,
             "codice_originale": r["numero_bando"] + (f" Cod. {r['codice_sotto']}" if r["codice_sotto"] else ""), "url": None, "esito": None}
            for r in conn.execute("SELECT * FROM protocollo_email WHERE stato = 'approvato' AND categoria IN ('graduatoria', 'scorrimento', 'rettifica', 'bando')")
            if r["numero"] not in gia_nel_file]


# ------------------------------------------------------------------ chiavi del programma

def _impronta(chiave: str) -> str:
    return hashlib.sha256(chiave.encode()).hexdigest()


def crea_chiave(conn, utente: str, nome: str | None) -> str:
    chiave = "mp_" + secrets.token_urlsafe(24)
    conn.execute("INSERT INTO chiave_programma (utente, nome, impronta, creata_il) VALUES (?, ?, ?, ?)",
                 (utente, (nome or "").strip()[:80] or None, _impronta(chiave), _adesso()))
    return chiave


def chiavi(conn, utente: str | None = None) -> list[dict]:
    sql, par = "SELECT id, utente, nome, creata_il, usata_il, revocata_il FROM chiave_programma", ()
    if utente:
        sql, par = sql + " WHERE utente = ?", (utente,)
    return [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", par)]


def revoca(conn, id_chiave: int, utente: str | None) -> bool:
    sql, par = "UPDATE chiave_programma SET revocata_il = ? WHERE id = ? AND revocata_il IS NULL", [_adesso(), id_chiave]
    if utente:
        sql += " AND utente = ?"
        par.append(utente)
    return conn.execute(sql, par).rowcount > 0


def chiave_valida(conn, chiave: str | None) -> dict | None:
    """La chiave attiva (id e utente del sito), o None."""
    if not chiave or not chiave.startswith("mp_"):
        return None
    r = conn.execute("SELECT id, utente FROM chiave_programma WHERE impronta = ? AND revocata_il IS NULL", (_impronta(chiave),)).fetchone()
    if not r:
        return None
    conn.execute("UPDATE chiave_programma SET usata_il = ? WHERE id = ?", (_adesso(), r["id"]))
    return dict(r)


def utente_della_chiave(conn, chiave: str | None) -> str | None:
    c = chiave_valida(conn, chiave)
    return c["utente"] if c else None


# ------------------------------------------------------------------ PC su cui gira il programma

def contatto(conn, chiave_id: int, pc: dict | None) -> dict:
    """Registra il contatto di un PC e dice se può mandare dati: un PC nuovo resta in attesa finché un amministratore
    non lo abilita (scelta dell'utente del 2026-11-19)."""
    pc = pc if isinstance(pc, dict) else {}
    nome = norm_space(str(pc.get("nome") or "PC senza nome"))[:80]
    utente_win = norm_space(str(pc.get("utente") or ""))[:80]
    caselle = [norm_space(str(x))[:120] for x in (pc.get("caselle") or []) if str(x).strip()][:20]
    ora = _adesso()
    riga = conn.execute("SELECT * FROM programma_pc WHERE chiave_id = ? AND nome_pc = ? AND utente_windows = ?", (chiave_id, nome, utente_win)).fetchone()
    if riga is None:
        conn.execute("INSERT INTO programma_pc (chiave_id, nome_pc, utente_windows, versione, caselle, primo_contatto, ultimo_contatto, contatti) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, 1)", (chiave_id, nome, utente_win, str(pc.get("versione") or "")[:20], json.dumps(caselle), ora, ora))
        riga = conn.execute("SELECT * FROM programma_pc WHERE chiave_id = ? AND nome_pc = ? AND utente_windows = ?", (chiave_id, nome, utente_win)).fetchone()
    else:
        conn.execute("UPDATE programma_pc SET ultimo_contatto = ?, contatti = contatti + 1, versione = ?, caselle = ? WHERE id = ?",
                     (ora, str(pc.get("versione") or riga["versione"] or "")[:20], json.dumps(caselle) if caselle else riga["caselle"], riga["id"]))
    return {"id": riga["id"], "stato": riga["stato"], "nome": nome}


def conta_email(conn, id_pc: int, n: int) -> None:
    conn.execute("UPDATE programma_pc SET email_ricevute = email_ricevute + ? WHERE id = ?", (n, id_pc))


def elenco_pc(conn) -> list[dict]:
    return [{**dict(r), "caselle": json.loads(r["caselle"])} for r in conn.execute(
        "SELECT p.*, c.utente AS utente_sito, c.nome AS nome_chiave, c.revocata_il FROM programma_pc p JOIN chiave_programma c ON c.id = p.chiave_id "
        "ORDER BY p.stato = 'in_attesa' DESC, p.ultimo_contatto DESC")]


def decidi_pc(conn, id_pc: int, abilitato: bool, utente: str | None) -> bool:
    return conn.execute("UPDATE programma_pc SET stato = ?, deciso_da = ?, deciso_il = ? WHERE id = ?",
                        ("abilitato" if abilitato else "disabilitato", utente, _adesso(), id_pc)).rowcount > 0


# ------------------------------------------------------------------ programma per Windows

_PROGRAMMA = Path(__file__).resolve().parent / "static" / "protocollo_cnr.py"
_AVVIO = r"""@echo off
chcp 65001 >nul
title Monitoraggio bandi - email di protocollo
set "CARTELLA=%LOCALAPPDATA%\MonitoraggioProtocollo"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Serve Python 3: installalo da https://www.python.org/downloads/ spuntando "Add python.exe to PATH", poi riavvia questo file.
  pause
  exit /b 1
)
if not exist "%CARTELLA%\venv\Scripts\python.exe" (
  echo Prima installazione: preparo l'ambiente in %CARTELLA% ...
  %PY% -m venv "%CARTELLA%\venv" || (echo Non riesco a creare l'ambiente Python. & pause & exit /b 1)
  "%CARTELLA%\venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check pywin32 extract-msg
)
"%CARTELLA%\venv\Scripts\python.exe" "%~dp0protocollo_cnr.py" {argomenti}
echo.
pause
"""
_AUTOMATICO_ON = r"""@echo off
chcp 65001 >nul
title Monitoraggio bandi - attiva l'avvio automatico
set "CARTELLA=%LOCALAPPDATA%\MonitoraggioProtocollo"
if not exist "%CARTELLA%\venv\Scripts\pythonw.exe" (
  echo Avvia prima una volta «Leggi-e-invia.bat»: prepara l'ambiente e salva la chiave.
  pause
  exit /b 1
)
if not exist "%APPDATA%\MonitoraggioProtocollo\config.json" (
  echo Manca la chiave: avvia prima una volta «Leggi-e-invia.bat» e incollala.
  pause
  exit /b 1
)
copy /Y "%~dp0protocollo_cnr.py" "%CARTELLA%\protocollo_cnr.py" >nul
schtasks /Create /F /SC MINUTE /MO 15 /TN "Monitoraggio bandi - protocollo" /TR "\"%CARTELLA%\venv\Scripts\pythonw.exe\" \"%CARTELLA%\protocollo_cnr.py\" --registro \"%CARTELLA%\registro.txt\"" >nul
if errorlevel 1 (
  echo Non sono riuscito a creare l'attività pianificata.
) else (
  echo Fatto: ogni 15 minuti il programma legge la posta e manda i protocolli, senza finestre, finché sei collegato al PC.
  echo Il registro è in %CARTELLA%\registro.txt
  echo Se aggiorni il programma, rilancia questo file.
)
pause
"""
_AUTOMATICO_OFF = r"""@echo off
chcp 65001 >nul
schtasks /Delete /F /TN "Monitoraggio bandi - protocollo" >nul 2>nul
echo Avvio automatico disattivato.
pause
"""
_LEGGIMI = """MONITORAGGIO BANDI - LETTURA DELLE EMAIL DI PROTOCOLLO (TITULUS)

Cosa fa
  Legge le email «Il sistema di protocollo le ha assegnato il seguente documento ...» arrivate nella tua casella e manda al sito
  del monitoraggio solo numero e data di protocollo, segnatura, oggetto, link Titulus e data di ricezione. Non apre i documenti,
  non modifica né sposta le email. Sul sito trovi tutto in «File segreteria» > «Documenti in uscita protocollo».

Una volta sola
  1. Installa Python 3 da https://www.python.org/downloads/ e spunta «Add python.exe to PATH».
  2. Estrai questo zip in una cartella, ad esempio Documenti\Protocollo-monitoraggio (non lasciarlo dentro lo zip).
  3. Sul sito, «File segreteria» > «Documenti in uscita protocollo» > «Genera chiave»: copia la chiave (inizia con mp_).

Primo test
  4. Doppio clic su «Prova-senza-inviare.bat»: elenca le email di protocollo che trova, senza mandare niente.
     La prima volta prepara l'ambiente (1-2 minuti).
  5. Se l'elenco è giusto: doppio clic su «Leggi-e-invia.bat», incolla la chiave quando la chiede (la ricorda per le volte dopo).
     La prima volta il programma dice che il PC è «in attesa di abilitazione»: chiedi a un amministratore di abilitarlo
     (Impostazioni > Programma protocollo), poi rilancia «Leggi-e-invia.bat».
  6. Sul sito ricarica la scheda: trovi i protocolli da verificare, approvare, correggere o scartare.

Tenerlo attivo senza cliccare ogni volta
  Dopo il primo «Leggi-e-invia.bat» riuscito, doppio clic UNA VOLTA su «Avvio-automatico-attiva.bat»: crea un'attività
  pianificata di Windows che ogni 15 minuti legge la posta e manda i protocolli, senza finestre, finché sei collegato al PC
  (serve Outlook aperto). Il registro di cosa fa è in %LOCALAPPDATA%\MonitoraggioProtocollo\registro.txt.
  «Avvio-automatico-disattiva.bat» la toglie. Se scarichi una versione nuova del programma, rilancia «Avvio-automatico-attiva.bat».
  In alternativa «Controllo-continuo.bat» ripete la lettura ogni 10 minuti finché la sua finestra resta aperta.

Outlook
  Funziona con Outlook «classico» (legge Posta in arrivo e sottocartelle degli ultimi 60 giorni, senza password).
  Legge TUTTE le caselle collegate al profilo (personale, generale della segreteria, ...): ogni protocollo dice da quale
  casella arriva; se arriva in due caselle resta una riga sola con le due ricezioni. Per sceglierle, dal Prompt dei comandi:
     Leggi-e-invia.bat --elenca-caselle            (mostra le caselle che vede)
     Leggi-e-invia.bat --caselle "segreteria"      (legge solo quelle con «segreteria» nel nome; la scelta resta salvata)
     Leggi-e-invia.bat --caselle tutte             (torna a leggerle tutte)
  Una casella condivisa aperta solo come «cartella di un altro utente» non è visibile: va aggiunta al profilo di Outlook.
  Se una regola sposta le email di protocollo in una cartella fuori da Posta in arrivo, avvia con --tutte-le-cartelle
  (dal Prompt dei comandi: Leggi-e-invia.bat --tutte-le-cartelle).
  Con il «nuovo Outlook» o la posta dal browser non si può leggere direttamente: salva le email di protocollo (trascinale) in
  una cartella e avvia dal Prompt dei comandi:
     Leggi-e-invia.bat --cartella "C:\percorso\della\cartella"

Sicurezza
  La chiave è personale: se la perdi o cambi PC, revocala dal sito e generane una nuova. È salvata in
  %APPDATA%\MonitoraggioProtocollo\config.json.
"""


def programma_zip(server: str) -> tuple[str, bytes]:
    """Lo zip per Windows: il programma con l'indirizzo del sito, tre avvii .bat e le istruzioni (righe in formato Windows)."""
    crlf = lambda s: s.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")  # noqa: E731
    contenuto = io.BytesIO()
    with zipfile.ZipFile(contenuto, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Protocollo-monitoraggio/protocollo_cnr.py", _PROGRAMMA.read_text(encoding="utf-8").replace("__SERVER__", server))
        for nome, argomenti in (("Prova-senza-inviare", "--prova %*"), ("Leggi-e-invia", "%*"), ("Controllo-continuo", "--continuo %*")):
            z.writestr(f"Protocollo-monitoraggio/{nome}.bat", crlf(_AVVIO.replace("{argomenti}", argomenti)))
        z.writestr("Protocollo-monitoraggio/Avvio-automatico-attiva.bat", crlf(_AUTOMATICO_ON))
        z.writestr("Protocollo-monitoraggio/Avvio-automatico-disattiva.bat", crlf(_AUTOMATICO_OFF))
        z.writestr("Protocollo-monitoraggio/LEGGIMI.txt", crlf(_LEGGIMI))
    return "Protocollo-monitoraggio.zip", contenuto.getvalue()
