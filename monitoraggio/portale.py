"""Area dei referenti: ogni RdP vede solo gli atti dei propri bandi e può segnalare un falso positivo.

Chi sei lo dimostra la casella: il link monouso parte solo verso un indirizzo già presente tra gli RdP attivi,
mai verso uno deciso da chi lo chiede. La sessione è separata da quella degli utenti del sito, quindi un referente
non entra in nessun'altra pagina. I dati escono da un elenco esplicito di campi: niente altri RdP e niente dati dei candidati.
Chi è RdP trova il link ai punteggi su Selezioni Online, dove entra con le proprie credenziali.

I coordinatori usano la stessa pagina: scelgono i profili che seguono e vedono le difformità di quei bandi in sola consultazione,
con il link ai punteggi solo per i bandi di cui sono anche RdP. Stanno in una tabella propria, non tra gli utenti del sito.
"""
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_from_directory, session

from . import atti, comunicazioni, config, db, difformita, mensile, posta, utenti

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


def _anteprima() -> str | None:
    """Un amministratore vede l'area come un referente o un coordinatore, senza poter fare nulla a suo nome."""
    email, fino = session.get("anteprima_referente"), session.get("anteprima_fino")
    if not (email and fino and datetime.fromisoformat(fino) > _adesso()):
        return None
    amministratore = utenti.ruolo(session.get("user")) == utenti.AMMINISTRATORE and not session.get("solo_lettura")
    return email if amministratore and not session.get("vista_come") else None


def avvia_anteprima(email: str) -> None:
    session["anteprima_referente"] = email
    session["anteprima_fino"] = (_adesso() + DURATA_SESSIONE).isoformat()


def puo_entrare(conn, email: str) -> bool:
    return _puo_entrare(conn, email.strip().lower())


def _non_in_anteprima(fn):
    @wraps(fn)
    def _controllo(*args, **kwargs):
        if _anteprima():
            return jsonify({"error": "Anteprima dell'amministratore: questa azione non viene eseguita."}), 403
        return fn(*args, **kwargs)
    return _controllo


def _solo_se_attiva(fn):
    @wraps(fn)
    def _controllo(*args, **kwargs):
        if not posta.impostazioni_email()["portale_referenti"] and not _anteprima():
            abort(404)
        return fn(*args, **kwargs)
    return _controllo


def _referente() -> str | None:
    if _anteprima():
        return _anteprima()
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


def _profili_coordinatore(conn, email: str) -> list[str] | None:
    """I profili scelti dal coordinatore; None se non è un coordinatore. Letto a ogni richiesta: toglierlo ha effetto subito."""
    riga = conn.execute("SELECT profili FROM coordinatore WHERE email = ?", (email,)).fetchone()
    return json.loads(riga["profili"]) if riga else None


def _puo_entrare(conn, email: str) -> bool:
    return (_profili_coordinatore(conn, email) is not None
            or conn.execute("SELECT 1 FROM referente WHERE attivo = 1 AND lower(trim(email)) = ? LIMIT 1", (email,)).fetchone() is not None)


def _profili_schede(conn) -> tuple[dict, dict, list[str]]:
    """Il profilo di Selezioni Online per scheda e per bando, e l'elenco dei profili tra cui scegliere."""
    per_scheda, per_bando = {}, {}
    for s in conn.execute("SELECT id, bando_id, tipologia, dati_extra FROM scheda WHERE fonte = 'sol' AND presente = 1 AND dati_extra IS NOT NULL"):
        profilo = json.loads(s["dati_extra"]).get("profilo")
        if profilo and config.nel_monitoraggio(s["tipologia"]):
            per_scheda[s["id"]] = profilo
            per_bando.setdefault(s["bando_id"], profilo)
    return per_scheda, per_bando, sorted({*per_scheda.values()})


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


def _righe_di(conn, monitoraggio: dict, email: str, tutte: list[dict] | None = None) -> list[dict]:
    """Gli atti seguiti di cui è RdP, tolti quelli da cui un amministratore l'ha escluso. Se il codice non ha RdP propri
    l'elenco contiene quelli di tutti i codici del bando: non si sa di chi sia l'atto, quindi non si mostra."""
    esclusi = {r["chiave"]: json.loads(r["esclusi"])
               for r in conn.execute("SELECT chiave, esclusi FROM comunicazione_indirizzi WHERE mese = ?", (monitoraggio["mese"],))}
    return [r for r in (comunicazioni.righe_mese(conn, monitoraggio) if tutte is None else tutte)
            if r["atto"] in difformita.ATTI_SEGUITI and r.get("rdp_origine") != "tutti i codici"
            and email in {(p.get("email") or "").strip().lower() for p in r.get("rdp") or []}
            and email not in esclusi.get(r["chiave"], [])]


def _vista(conn, monitoraggio: dict, email: str, profili: list[str], schede_profilo: tuple[dict, dict]) -> dict:
    fatte = {(s["chiave"], s["atto"], s["protocollo"], s["data"], s["rilievo"]): s
             for s in conn.execute("SELECT * FROM segnalazione WHERE mese = ? AND email = ?", (monitoraggio["mese"], email))}
    tutte = comunicazioni.righe_mese(conn, monitoraggio)
    mie = _righe_di(conn, monitoraggio, email, tutte)
    gia = {id(r) for r in mie}
    per_scheda, per_bando = schede_profilo
    profilo_di = lambda r: per_scheda.get(r.get("scheda_sol_id")) or per_bando.get(r.get("bando_id"))  # noqa: E731
    seguite = [r for r in tutte if profili and r["atto"] in difformita.ATTI_SEGUITI and id(r) not in gia and profilo_di(r) in profili]
    bandi = []
    for r in [*mie, *seguite]:
        atto, protocollo, data = _chiave_atto(r)
        rdp = id(r) in gia
        rilievi = []
        for testo in r["rilievi"]:
            s = fatte.get((r["chiave"], atto, protocollo, data, testo))
            rilievi.append({"testo": testo, "segnalazione": {"stato": s["stato"], "quando": s["quando"], "nota": s["nota"]} if s else None})
        bandi.append({"chiave": r["chiave"], "titolo_bando": r.get("titolo_bando"), "atto": atto, "protocollo": protocollo, "data": data,
                      "fonti": {f: (r.get("fonti") or {}).get(f, {}).get("stato") for f in ("sol", "urp", "segreteria")},
                      "link_sol": r.get("link_codice"), "rilievi": rilievi, "rdp": rdp, "profilo": profilo_di(r),
                      "verifica_punteggi": (r.get("punteggi") or {}).get("verificato_il"),
                      "link_punteggi": r.get("url_punteggi") if rdp else None})
    bandi.sort(key=lambda b: (not b["rilievi"], b["chiave"]))
    aggiornamenti = [{k: f[k] for k in ("fonte", "nome", "aggiornata_il")} for f in comunicazioni.allineamento(conn, monitoraggio["mese_dati"])]
    return {"mese": monitoraggio["mese"], "titolo": comunicazioni.titolo_mese(monitoraggio["mese_dati"]), "aggiornamenti": aggiornamenti, "bandi": bandi}


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
        riconosciuta = _puo_entrare(conn, email)
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
        if not _puo_entrare(conn, voce[0]):
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
    if _anteprima():  # resta collegato come amministratore
        session.pop("anteprima_referente", None)
        session.pop("anteprima_fino", None)
        return jsonify({"ok": True, "anteprima": True})
    session.clear()
    return jsonify({"ok": True})


@bp.get("/api/area-referenti/bandi")
@_solo_se_attiva
@_serve_referente
def bandi():
    email = _referente()
    conn = _conn()
    try:
        scelti = _profili_coordinatore(conn, email)
        per_scheda, per_bando, disponibili = _profili_schede(conn)
        base = {"email": email, "anteprima": bool(_anteprima()), "coordinatore": scelti is not None, "profili": scelti or [],
                "profili_disponibili": disponibili if scelti is not None else []}
        if atti.fonti_in_attesa(conn):  # finché SOL e URP non concludono le difformità non sono affidabili
            return _senza_cache(jsonify({**base, "in_aggiornamento": True, "monitoraggi": []}))
        aperti = [mensile.leggi(conn, r["mese"]) for r in conn.execute("SELECT mese FROM monitoraggio_mese WHERE stato = 'aperto' ORDER BY mese DESC").fetchall()]
        return _senza_cache(jsonify({**base, "in_aggiornamento": False,
                                     "monitoraggi": [_vista(conn, m, email, scelti or [], (per_scheda, per_bando)) for m in aperti]}))
    finally:
        conn.close()


@bp.post("/api/area-referenti/profili")
@_solo_se_attiva
@_serve_referente
@_non_in_anteprima
def salva_profili():
    """I profili restano salvati per il coordinatore: li ritrova a ogni accesso."""
    email = _referente()
    scelti = (request.get_json(silent=True) or {}).get("profili")
    conn = _conn()
    try:
        if _profili_coordinatore(conn, email) is None:
            return jsonify({"error": "Riservato ai coordinatori"}), 403
        if not isinstance(scelti, list) or not set(map(str, scelti)) <= set(_profili_schede(conn)[2]):
            return jsonify({"error": "Profili non validi: ricarica la pagina"}), 400
        conn.execute("UPDATE coordinatore SET profili = ? WHERE email = ?", (json.dumps(sorted(set(map(str, scelti)))), email))
        return jsonify({"ok": True})
    finally:
        conn.close()


@bp.post("/api/area-referenti/segnala")
@_solo_se_attiva
@_serve_referente
@_non_in_anteprima
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
def elenco_coordinatori(conn) -> list[dict]:
    return [{**dict(r), "profili": json.loads(r["profili"])} for r in conn.execute("SELECT * FROM coordinatore ORDER BY email")]


def _traccia(conn, email: str, azione: str, autore: str | None, ruolo: str | None = None) -> None:
    conn.execute("INSERT INTO utente_modifica (username, azione, ruolo, autore, quando) VALUES (?, ?, ?, ?, ?)",
                 (email, azione, ruolo, autore, _adesso().strftime("%Y-%m-%dT%H:%M:%SZ")))


def aggiungi_coordinatore(conn, nome_o_email: str | None, autore: str | None) -> str:
    valore = (nome_o_email or "").strip().lower()
    email = valore if "@" in valore or not valore else utenti.email_di(valore)
    if not email or posta.indirizzi_non_validi([email]):
        raise ValueError("Scrivi nome.cognome o un indirizzo email valido")
    conn.execute("INSERT OR IGNORE INTO coordinatore (email, aggiunto_da, aggiunto_il) VALUES (?, ?, ?)",
                 (email, autore, _adesso().strftime("%Y-%m-%dT%H:%M:%SZ")))
    _traccia(conn, email, "imposta", autore, "coordinatore")
    return email


def togli_coordinatore(conn, email: str, autore: str | None) -> bool:
    email = email.strip().lower()
    tolti = conn.execute("DELETE FROM coordinatore WHERE email = ?", (email,)).rowcount
    if tolti:
        _traccia(conn, email, "togli", autore)
    return bool(tolti)


def invia_accesso_coordinatore(conn, email: str, autore: str | None) -> bool:
    email = email.strip().lower()
    if _profili_coordinatore(conn, email) is None:
        return False
    posta.invia([email], "Accesso al monitoraggio bandi",
                "Buongiorno,\n\npuoi vedere lo stato dei bandi dei profili che coordini. Apri questo link e inserisci questo "
                f"indirizzo email: riceverai un link personale di accesso.\n{config.sito_url()}{PAGINA}\n", sempre_reale=True)
    _traccia(conn, email, "invito_accesso", autore)
    return True


def conteggi(conn, mese: str) -> dict:
    r = conn.execute("SELECT COUNT(*) AS totali, COALESCE(SUM(stato = 'aperta'), 0) AS aperte FROM segnalazione WHERE mese = ?", (mese,)).fetchone()
    return {"totali": r["totali"], "aperte": r["aperte"]}


def elenco(conn, mese: str) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM segnalazione WHERE mese = ? ORDER BY stato = 'gestita', quando DESC, id DESC", (mese,))]


def imposta_gestita(conn, mese: str, id_segnalazione: int, gestita: bool, autore: str | None) -> bool:
    ora = _adesso().strftime("%Y-%m-%dT%H:%M:%SZ") if gestita else None
    return conn.execute("UPDATE segnalazione SET stato = ?, gestita_da = ?, gestita_il = ? WHERE id = ? AND mese = ?",
                        ("gestita" if gestita else "aperta", autore if gestita else None, ora, id_segnalazione, mese)).rowcount > 0
