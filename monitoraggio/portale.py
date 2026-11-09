"""Area dei referenti: ogni RdP vede solo gli atti dei propri bandi e può segnalare un falso positivo.

Chi sei lo dimostra la casella: il link monouso parte solo verso un indirizzo già presente tra gli RdP attivi,
mai verso uno deciso da chi lo chiede. La sessione è separata da quella degli utenti del sito, quindi un referente
non entra in nessun'altra pagina. I dati escono da un elenco esplicito di campi: niente candidati né altri RdP.
"""
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_from_directory, session

from . import atti, comunicazioni, config, db, difformita, mensile, posta

log = logging.getLogger(__name__)

PAGINA = "/referenti"
DURATA_LINK = timedelta(minutes=15)
DURATA_SESSIONE = timedelta(hours=8)
ATTESA_TRA_EMAIL = timedelta(minutes=1)
FINESTRA_IP = timedelta(hours=1)
MAX_RICHIESTE_IP = 10
NOTA_MAX = 1000
_STATIC = Path(__file__).resolve().parent / "static"

_lock = threading.Lock()
_codici: dict[str, tuple[str, datetime]] = {}
_ultima_email: dict[str, datetime] = {}
_richieste_ip: dict[str, list[datetime]] = {}

bp = Blueprint("portale", __name__)


def _adesso() -> datetime:
    return datetime.now(timezone.utc)


def _conn():
    conn = db.connetti()
    db.inizializza(conn)
    return conn


def _in_background(fn, *argomenti) -> None:
    """L'invio non deve allungare la risposta: dal tempo si capirebbe se un indirizzo è di un referente."""
    threading.Thread(target=fn, args=argomenti, daemon=True, name="link-referente").start()


def _solo_se_attiva(fn):
    @wraps(fn)
    def _controllo(*args, **kwargs):
        if not posta.impostazioni_email()["portale_referenti"]:
            abort(404)
        return fn(*args, **kwargs)
    return _controllo


def _referente() -> str | None:
    email, fino = session.get("referente"), session.get("referente_fino")
    return email if email and fino and datetime.fromisoformat(fino) > _adesso() else None


def _serve_referente(fn):
    @wraps(fn)
    def _controllo(*args, **kwargs):
        if not _referente():
            return jsonify({"error": "Accesso scaduto: chiedi un nuovo link"}), 401
        return fn(*args, **kwargs)
    return _controllo


def _senza_cache(risposta):
    risposta.headers["Cache-Control"] = "no-store"
    risposta.headers["Referrer-Policy"] = "no-referrer"
    return risposta


def _e_referente(conn, email: str) -> bool:
    return conn.execute("SELECT 1 FROM referente WHERE attivo = 1 AND lower(trim(email)) = ? LIMIT 1", (email,)).fetchone() is not None


def _troppe_richieste(ip: str, ora: datetime) -> bool:
    with _lock:
        recenti = [t for t in _richieste_ip.get(ip, []) if ora - t < FINESTRA_IP]
        recenti.append(ora)
        _richieste_ip[ip] = recenti
        return len(recenti) > MAX_RICHIESTE_IP


def _spedisci(email: str, codice: str) -> None:
    try:
        posta.invia([email], "Accesso all'area referenti del monitoraggio bandi",
                    "Buongiorno,\n\nper vedere le difformità dei bandi di cui risulti referente apri questo link entro 15 minuti:\n"
                    f"{config.sito_url()}{PAGINA}?codice={codice}\n\n"
                    "Il link è personale e vale una sola volta. Se non l'hai chiesto tu, puoi ignorare questa email.\n", sempre_reale=True)
    except posta.PostaErrore:
        log.warning("Link dell'area referenti non inviato")


def _chiave_atto(riga: dict) -> tuple[str, str, str]:
    return riga["atto"], riga.get("protocollo") or "", riga.get("data") or ""


def _righe_di(conn, monitoraggio: dict, email: str) -> list[dict]:
    """Gli atti seguiti di cui è RdP, tolti quelli da cui un amministratore l'ha escluso. Se il codice non ha RdP propri
    l'elenco contiene quelli di tutti i codici del bando: non si sa di chi sia l'atto, quindi non si mostra."""
    esclusi = {r["chiave"]: json.loads(r["esclusi"])
               for r in conn.execute("SELECT chiave, esclusi FROM comunicazione_indirizzi WHERE mese = ?", (monitoraggio["mese"],))}
    return [r for r in comunicazioni.righe_mese(conn, monitoraggio)
            if r["atto"] in difformita.ATTI_SEGUITI and r.get("rdp_origine") != "tutti i codici"
            and email in {(p.get("email") or "").strip().lower() for p in r.get("rdp") or []}
            and email not in esclusi.get(r["chiave"], [])]


def _vista(conn, monitoraggio: dict, email: str) -> dict:
    fatte = {(s["chiave"], s["atto"], s["protocollo"], s["data"], s["rilievo"]): s
             for s in conn.execute("SELECT * FROM segnalazione WHERE mese = ? AND email = ?", (monitoraggio["mese"], email))}
    bandi = []
    for r in _righe_di(conn, monitoraggio, email):
        atto, protocollo, data = _chiave_atto(r)
        rilievi = []
        for testo in r["rilievi"]:
            s = fatte.get((r["chiave"], atto, protocollo, data, testo))
            rilievi.append({"testo": testo, "segnalazione": {"stato": s["stato"], "quando": s["quando"], "nota": s["nota"]} if s else None})
        bandi.append({"chiave": r["chiave"], "titolo_bando": r.get("titolo_bando"), "atto": atto, "protocollo": protocollo, "data": data,
                      "fonti": {f: (r.get("fonti") or {}).get(f, {}).get("stato") for f in ("sol", "urp", "segreteria")},
                      "link_sol": r.get("link_codice"), "rilievi": rilievi})
    bandi.sort(key=lambda b: (not b["rilievi"], b["chiave"]))
    return {"mese": monitoraggio["mese"], "titolo": comunicazioni.titolo_mese(monitoraggio["mese_dati"]), "bandi": bandi}


@bp.get(PAGINA)
@_solo_se_attiva
def pagina():
    return _senza_cache(send_from_directory(_STATIC, "referenti.html"))


@bp.post("/api/area-referenti/link")
@_solo_se_attiva
def chiedi_link():
    """Risponde sempre allo stesso modo, per non rivelare chi è referente."""
    risposta = jsonify({"ok": True})
    email = str((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
    ora = _adesso()
    if _troppe_richieste(request.remote_addr or "?", ora) or not email or posta.indirizzi_non_validi([email]):
        return risposta
    conn = _conn()
    try:
        riconosciuta = _e_referente(conn, email)
    finally:
        conn.close()
    if not riconosciuta:
        return risposta
    with _lock:
        if email in _ultima_email and ora - _ultima_email[email] < ATTESA_TRA_EMAIL:
            return risposta
        _ultima_email[email] = ora
        for vecchio in [k for k, v in _codici.items() if v[1] <= ora]:
            del _codici[vecchio]
        codice = secrets.token_urlsafe(32)
        _codici[codice] = (email, ora + DURATA_LINK)
    _in_background(_spedisci, email, codice)
    return risposta


@bp.post("/api/area-referenti/entra")
@_solo_se_attiva
def entra():
    """Solo su richiesta esplicita: i controlli di sicurezza della posta aprono i link da soli e li consumerebbero."""
    with _lock:
        voce = _codici.pop(str((request.get_json(silent=True) or {}).get("codice") or ""), None)
    if not voce or voce[1] <= _adesso():
        return jsonify({"error": "Il link è scaduto o è già stato usato: chiedine uno nuovo."}), 401
    conn = _conn()
    try:
        if not _e_referente(conn, voce[0]):
            return jsonify({"error": "Questo indirizzo non risulta più tra i referenti."}), 403
    finally:
        conn.close()
    session.clear()
    session["referente"] = voce[0]
    session["referente_fino"] = (_adesso() + DURATA_SESSIONE).isoformat()
    return jsonify({"ok": True})


@bp.post("/api/area-referenti/esci")
@_solo_se_attiva
def esci():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/api/area-referenti/bandi")
@_solo_se_attiva
@_serve_referente
def bandi():
    email = _referente()
    conn = _conn()
    try:
        if atti.fonti_in_attesa(conn):  # finché SOL e URP non concludono le difformità non sono affidabili
            return _senza_cache(jsonify({"email": email, "in_aggiornamento": True, "monitoraggi": []}))
        aperti = [mensile.leggi(conn, r["mese"]) for r in conn.execute("SELECT mese FROM monitoraggio_mese WHERE stato = 'aperto' ORDER BY mese DESC").fetchall()]
        return _senza_cache(jsonify({"email": email, "in_aggiornamento": False, "monitoraggi": [_vista(conn, m, email) for m in aperti]}))
    finally:
        conn.close()


@bp.post("/api/area-referenti/segnala")
@_solo_se_attiva
@_serve_referente
def segnala():
    """La riga si ricalcola sul server: si può segnalare solo una difformità presente tra i propri bandi."""
    email = _referente()
    corpo = request.get_json(silent=True) or {}
    testo = lambda campo: str(corpo.get(campo) or "").strip()  # noqa: E731
    nota = testo("nota")
    if not nota or len(nota) > NOTA_MAX:
        return jsonify({"error": f"Spiega il motivo in massimo {NOTA_MAX} caratteri"}), 400
    if comunicazioni.contiene_dati_candidati(nota):
        return jsonify({"error": "Il testo sembra contenere un codice fiscale: toglilo e riprova"}), 400
    conn = _conn()
    try:
        m = mensile.leggi(conn, testo("mese")) if mensile.mese_valido(testo("mese")) else None
        if not m or m["stato"] != "aperto" or atti.fonti_in_attesa(conn):
            return jsonify({"error": "Questo monitoraggio non accetta segnalazioni"}), 409
        cercata = (testo("atto"), testo("protocollo"), testo("data"))
        riga = next((r for r in _righe_di(conn, m, email) if r["chiave"] == testo("chiave") and _chiave_atto(r) == cercata), None)
        if not riga or testo("rilievo") not in riga["rilievi"]:
            return jsonify({"error": "Difformità non trovata tra i tuoi bandi: ricarica la pagina"}), 404
        ora = _adesso().strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("INSERT INTO segnalazione (mese, chiave, atto, protocollo, data, rilievo, nota, email, quando) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(mese, chiave, atto, protocollo, data, rilievo, email) DO UPDATE SET nota = excluded.nota, "
                     "quando = excluded.quando, stato = 'aperta', gestita_da = NULL, gestita_il = NULL",
                     (m["mese"], testo("chiave"), *cercata, testo("rilievo"), nota, email, ora))
        return jsonify({"ok": True})
    finally:
        conn.close()


# --- per gli amministratori
def conteggi(conn, mese: str) -> dict:
    r = conn.execute("SELECT COUNT(*) AS totali, COALESCE(SUM(stato = 'aperta'), 0) AS aperte FROM segnalazione WHERE mese = ?", (mese,)).fetchone()
    return {"totali": r["totali"], "aperte": r["aperte"]}


def elenco(conn, mese: str) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM segnalazione WHERE mese = ? ORDER BY stato = 'gestita', quando DESC, id DESC", (mese,))]


def imposta_gestita(conn, mese: str, id_segnalazione: int, gestita: bool, autore: str | None) -> bool:
    ora = _adesso().strftime("%Y-%m-%dT%H:%M:%SZ") if gestita else None
    return conn.execute("UPDATE segnalazione SET stato = ?, gestita_da = ?, gestita_il = ? WHERE id = ? AND mese = ?",
                        ("gestita" if gestita else "aperta", autore if gestita else None, ora, id_segnalazione, mese)).rowcount > 0
