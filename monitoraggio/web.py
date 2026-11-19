"""API e pagina di riepilogo del monitoraggio (contracts/api.md).

`crea_blueprint(protezione)` riceve il decoratore di autenticazione: in avvia_tool.py è
`login_required` (SSO); il server locale di prova (`python -m monitoraggio web`) ascolta solo
su 127.0.0.1 e non usa login.
"""
import io
import json
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, jsonify, redirect, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from . import accessibilita, atti, collegamento, compat, comunicazioni, config, db, difformita, impostazioni, notifiche, protocollo_email, punteggi, referenti, segreteria, sol_sessione, utenti

# esito dell'ultima verifica dei punteggi (solo conteggi, in memoria)
ULTIMA_VERIFICA: dict = {}
from .fonti.sol import url_punteggi
from .raccolta import RaccoltaInCorso, avvia, errori, raccogli, stato

STATIC = Path(__file__).resolve().parent / "static"
MAX_FILE_SEGRETERIA = 15 * 1024 * 1024
MAX_FILE_PDF = 25 * 1024 * 1024

# Menu comune di tutte le pagine (spec 001, FR-023): definito solo qui.
# "pagina" = file HTML nella cartella del progetto; "route" = pagina servita da questo modulo.
MENU = [
    {"gruppo": "Monitoraggio", "voci": [
        {"titolo": "Monitoraggi mensili", "url": "/monitoraggio/mensili", "route": True},
        {"titolo": "Riepilogo atti", "url": "/monitoraggio", "route": True},
        {"titolo": "File segreteria", "url": "/monitoraggio/segreteria", "route": True},
        {"titolo": "Comunicazioni", "url": "/monitoraggio/comunicazioni", "route": True},
        {"titolo": "Report del mese", "url": "/report-mese.html", "pagina": "report-mese.html"},
        {"titolo": "Impostazioni", "url": "/monitoraggio/impostazioni", "route": True, "solo_admin": True},
    ]},
    {"gruppo": "Controlli URP", "voci": [
        {"titolo": "Controllo bandi", "url": "/index.html", "pagina": "index.html"},
        {"titolo": "Accessibilità URP", "url": "/access.html", "pagina": "access.html"},
        {"titolo": "Verifica PDF", "url": "/verifica-access.html", "pagina": "verifica-access.html"},
        {"titolo": "Mobilità", "url": "/mobilita-urp.html", "pagina": "mobilita-urp.html"},
        {"titolo": "Stato avanzamento", "url": "/stato-avanzamento.html", "pagina": "stato-avanzamento.html"},
        {"titolo": "Ricerca libera", "url": "/search.html", "pagina": "search.html"},
    ]},
    {"gruppo": "Strumenti", "voci": [
        {"titolo": "Redazione firme", "url": "/redazione-firme.html", "pagina": "redazione-firme.html"},
        {"titolo": "Job firme", "url": "/firme-jobs.html", "pagina": "firme-jobs.html"},
        {"titolo": "Strumento RdP", "url": "/rdp-tool.html", "pagina": "rdp-tool.html"},
        {"titolo": "Ispeziona bando SOL", "url": "/call-inspect.html", "pagina": "call-inspect.html"},
        {"titolo": "Dettaglio graduatoria", "url": "/graduatoria-detail.html", "pagina": "graduatoria-detail.html"},
    ]},
]


def menu(pagine_disponibili: set[str] | None = None) -> list[dict]:
    """Il menu con, per ogni voce, se è disponibile nell'ambiente in uso.

    `pagine_disponibili`: pagine servite (None = tutte quelle presenti nella cartella del progetto).
    """
    gruppi = []
    for gruppo in MENU:
        voci = []
        for voce in gruppo["voci"]:
            pagina = voce.get("pagina")
            disponibile = voce.get("route", False) or (
                (config.ROOT / pagina).exists() and (pagine_disponibili is None or pagina in pagine_disponibili))
            voci.append({"titolo": voce["titolo"], "url": voce["url"], "disponibile": bool(disponibile),
                         "solo_admin": voce.get("solo_admin", False)})
        gruppi.append({"gruppo": gruppo["gruppo"], "voci": voci})
    return gruppi


def _conn():
    conn = db.connetti()
    db.inizializza(conn)
    return conn


def prossima_notturna(ora: datetime | None = None) -> str | None:
    if not config.raccolta_notturna():
        return None
    ora = ora or datetime.now().astimezone()
    h, m = impostazioni.orario_raccolta()
    prossima = ora.replace(hour=h, minute=m, second=0, microsecond=0)
    if prossima <= ora:
        prossima += timedelta(days=1)
    return prossima.isoformat(timespec="minutes")


def _esegui_in_background(fonti: list[str], modalita: str, avviata_da: str | None, ids: dict[str, int]) -> None:
    """Esegue le raccolte già registrate (ids) una dopo l'altra, con una connessione propria."""
    def lavoro():
        conn = _conn()
        esiti = {}
        try:
            for fonte in fonti:
                esiti[fonte] = raccogli(conn, fonte, modalita=modalita, avviata_da=avviata_da, raccolta_id=ids[fonte],
                                        dopo_scrittura=lambda c, f: collegamento.collega(c))
        finally:
            conn.close()
        difformita.sincronizza_tutti()
        notifiche.dopo_aggiornamento(esiti, modalita)
    threading.Thread(target=lavoro, daemon=True, name="raccolta-manuale").start()


def avvia_raccolta(fonti: list[str], completa: bool, avviata_da: str | None) -> tuple[dict, int]:
    """Registra subito le raccolte (così un secondo clic riceve 409) e le esegue in background."""
    conn = _conn()
    modalita = "completa" if completa else "manuale"
    ids, occupate = {}, []
    try:
        for fonte in fonti:
            try:
                ids[fonte] = avvia(conn, fonte, modalita, avviata_da)
            except RaccoltaInCorso:
                occupate.append(fonte)
        if occupate:
            for rid in ids.values():
                conn.execute("DELETE FROM raccolta WHERE id = ?", (rid,))
            return {"ok": False, "msg": f"Raccolta già in corso per: {', '.join(occupate)}"}, 409
    finally:
        conn.close()
    _esegui_in_background(fonti, modalita, avviata_da, ids)
    return {"ok": True, "raccolte": [{"id": i, "fonte": f} for f, i in ids.items()]}, 202


def _conteggi_documenti(conn) -> dict[int, dict]:
    risultato: dict[int, dict] = defaultdict(lambda: {
        "graduatoria": 0, "rettifica": 0,
        "scorrimento": {"totale": 0, "subentro": 0, "ulteriore": 0, "utilizzo": 0, "non_specificato": 0}})
    for r in conn.execute(
            "SELECT s.bando_id, d.categoria, d.sottotipo, COUNT(DISTINCT COALESCE(d.protocollo, d.id)) AS n "
            "FROM documento d JOIN scheda s ON s.id = d.scheda_id WHERE d.presente = 1 AND s.presente = 1 "
            "AND d.categoria IN ('graduatoria', 'scorrimento', 'rettifica') GROUP BY 1, 2, 3"):
        voce = risultato[r["bando_id"]]
        if r["categoria"] == "scorrimento":
            voce["scorrimento"]["totale"] += r["n"]
            voce["scorrimento"][r["sottotipo"] or "non_specificato"] += r["n"]
        else:
            voce[r["categoria"]] += r["n"]
    return risultato


def elenco_bandi(conn, filtri: dict) -> list[dict]:
    where, args = ["b.stato_collegamento IS NOT NULL"], []
    for campo in ("tipologia", "stato_collegamento"):
        if filtri.get(campo):
            where.append(f"b.{campo} = ?")
            args.append(filtri[campo])
    if filtri.get("dal"):
        where.append("b.data_pubblicazione >= ?")
        args.append(filtri["dal"])
    if filtri.get("al"):
        where.append("b.data_pubblicazione <= ?")
        args.append(filtri["al"])
    if filtri.get("q"):
        where.append("(b.codice LIKE ? OR b.titolo LIKE ?)")
        args += [f"%{filtri['q']}%"] * 2
    if filtri.get("fonte"):
        where.append("EXISTS (SELECT 1 FROM scheda x WHERE x.bando_id = b.id AND x.fonte = ? AND x.presente = 1)")
        args.append(filtri["fonte"])
    bandi = [dict(r) for r in conn.execute(
        f"SELECT b.* FROM bando b WHERE {' AND '.join(where)} ORDER BY b.data_pubblicazione DESC, b.codice", args)]
    if not bandi:
        return []
    schede = defaultdict(list)
    for s in conn.execute("SELECT bando_id, fonte, url, sezione, titolo, protocollo, codice_originale FROM scheda WHERE presente = 1"):
        schede[s["bando_id"]].append({**dict(s), "url": config.pagina_documenti_urp(s["sezione"], s["url"], s["titolo"]) if s["fonte"] == "urp" else s["url"]})
    conteggi = _conteggi_documenti(conn)
    stati = {b["id"]: b["stato_collegamento"] for b in bandi}
    segn = collegamento.calcola_segnalazioni(collegamento.documenti_confrontati(conn), stati)
    dal = config.monitoraggio_dal().isoformat()
    for b in bandi:
        b["schede"] = [{k: s[k] for k in ("fonte", "url", "protocollo", "codice_originale")} for s in schede[b["id"]]]
        b["documenti"] = conteggi[b["id"]]
        tipi = sorted({s["tipo"] for s in segn.get(b["id"], [])})
        if b["stato_collegamento"] in ("solo_urp", "solo_sol") and (b["data_pubblicazione"] or "") >= dal:
            tipi.insert(0, f"bando_{b['stato_collegamento']}")
        b["segnalazioni"] = tipi
    return bandi


def dettaglio_bando(conn, bando_id: int) -> dict | None:
    riga = conn.execute("SELECT * FROM bando WHERE id = ?", (bando_id,)).fetchone()
    if not riga:
        return None
    bando = dict(riga)
    bando["schede"] = []
    for s in conn.execute("SELECT * FROM scheda WHERE bando_id = ? ORDER BY fonte", (bando_id,)):
        scheda = dict(s)
        scheda["dati_extra"] = json.loads(scheda["dati_extra"]) if scheda["dati_extra"] else None
        scheda["url_punteggi"] = url_punteggi(s["id_esterno"]) if s["fonte"] == "sol" else None
        if s["fonte"] == "urp":
            scheda["url"] = config.pagina_documenti_urp(s["sezione"], s["url"], s["titolo"])
        scheda["documenti"] = [dict(d) for d in conn.execute(
            "SELECT id, titolo, categoria, sottotipo, sottotipo_ordinale, sottotipo_origine, tipo_fonte, protocollo, "
            "protocollo_originale, data_protocollo, url, presente, prima_rilevazione FROM documento "
            "WHERE scheda_id = ? ORDER BY data_protocollo, id", (s["id"],))]
        bando["schede"].append(scheda)
    bando["segnalazioni"] = collegamento.segnalazioni(conn, bando_id)
    bando["referenti"] = referenti.referenti_per_bando(conn, solo_attivi=False).get(bando_id, [])
    per_scheda = referenti.referenti_per_scheda(conn, solo_attivi=False)
    for scheda in bando["schede"]:
        scheda["referenti"] = per_scheda.get(scheda["id"], [])
    return bando


def riepilogo_mensile(conn) -> dict:
    """Conteggi per mese dal periodo di monitoraggio: bandi pubblicati e documenti per fonte."""
    dal = config.monitoraggio_dal().isoformat()
    mesi: dict[str, Counter] = defaultdict(Counter)
    for r in conn.execute(
            "SELECT substr(data_pubblicazione, 1, 7) AS mese, tipologia, COUNT(*) AS n FROM bando "
            "WHERE stato_collegamento IS NOT NULL AND data_pubblicazione >= ? GROUP BY 1, 2", (dal,)):
        mesi[r["mese"]][f"bandi_{r['tipologia']}"] += r["n"]
        mesi[r["mese"]]["bandi"] += r["n"]
    for r in conn.execute(
            "SELECT substr(d.data_protocollo, 1, 7) AS mese, s.fonte, d.categoria, d.sottotipo, "
            "COUNT(DISTINCT COALESCE(d.protocollo, d.id)) AS n FROM documento d JOIN scheda s ON s.id = d.scheda_id "
            "WHERE d.presente = 1 AND s.bando_id IS NOT NULL AND d.data_protocollo >= ? "
            "AND d.categoria IN ('graduatoria', 'scorrimento', 'rettifica') GROUP BY 1, 2, 3, 4", (dal,)):
        mesi[r["mese"]][f"{r['categoria']}_{r['fonte']}"] += r["n"]
        if r["categoria"] == "scorrimento":
            mesi[r["mese"]][f"scorrimento_{r['sottotipo']}_{r['fonte']}"] += r["n"]
    stati = Counter(r["stato_collegamento"] for r in conn.execute(
        "SELECT stato_collegamento FROM bando WHERE stato_collegamento IS NOT NULL"))
    return {"dal": dal, "mesi": [{"mese": m, **dict(c)} for m, c in sorted(mesi.items(), reverse=True)],
            "stati_collegamento": dict(stati)}


def crea_blueprint(protezione=lambda f: f, utente_corrente=lambda: None,
                   pagine_disponibili: set[str] | None = None, token_utente=lambda: None,
                   login_url: str | None = None, logout_url: str | None = None,
                   login_sol: bool = False, sessione_sol=None, solo_admin=lambda f: f,
                   ruolo_corrente=lambda: "amministratore", avviso_dati=lambda: None) -> Blueprint:
    """`token_utente()`: token SSO valido dell'utente collegato (rinnovato se serve) o None.
    `login_sol`: abilita il collegamento a Selezioni Online con finestra di login (solo prova locale);
    altrimenti le chiamate a SOL usano il ticket ottenuto dal token SSO dell'utente.
    `sessione_sol`: ticket dell'utente (monitoraggio/accesso.py), al posto di quanto sopra.
    `solo_admin` e `ruolo_corrente`: ruoli degli utenti (monitoraggio/utenti.py); nel server locale non si usano."""
    bp = Blueprint("monitoraggio", __name__)

    def _intestazioni_sol() -> dict:
        if sessione_sol:
            return sessione_sol.intestazioni() or {}
        if login_sol:
            return sol_sessione.intestazioni()
        token = token_utente()
        ticket = sol_sessione.ticket_da_token(token) if token else None
        return {"Cookie": f"ticket={ticket}"} if ticket else {}

    @bp.post("/api/sol/accedi")
    @protezione
    def api_sol_accedi():
        if not login_sol:
            return jsonify({"error": "Collegamento a Selezioni Online non disponibile in questo ambiente"}), 404
        if not sol_sessione.avvia_login():
            return jsonify({"ok": False, "msg": "Finestra di login già aperta"}), 409
        return jsonify({"ok": True, "msg": "Si apre una finestra di Chrome: fai il login su Selezioni Online"}), 202

    def _periodo():
        """Periodo dalla richiesta: `dal`/`al` (AAAA-MM-GG) oppure `mese` (AAAA-MM)."""
        sorgente = (request.get_json(silent=True) or {}) if request.method == "POST" else request.args
        mese, dal, al = (sorgente.get("mese") or ""), (sorgente.get("dal") or ""), (sorgente.get("al") or "")
        if re.fullmatch(r"\d{4}-\d{2}", mese):
            return punteggi.intervallo(mese)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dal) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", al) and dal <= al:
            return dal, al
        return None

    @bp.post("/api/punteggi/verifica")
    @protezione
    @solo_admin
    def api_punteggi_verifica():
        periodo = _periodo()
        if not periodo:
            return jsonify({"error": "Periodo non valido (mese AAAA-MM oppure dal/al AAAA-MM-GG)"}), 400
        if punteggi.in_corso():
            return jsonify({"ok": False, "msg": "Verifica dei punteggi già in corso"}), 409
        intestazioni = _intestazioni_sol()
        if not intestazioni:
            messaggio = "Collega prima Selezioni Online dal menu" if login_sol or sessione_sol \
                else "Selezioni Online non ha concesso la sessione: esci e rifai l'accesso SSO"
            return jsonify({"error": messaggio}), 401
        dal, al = periodo

        def lavoro():
            c = _conn()
            try:
                ULTIMA_VERIFICA.update(dal=dal, al=al, **punteggi.verifica(c, dal, al, intestazioni))
            except punteggi.VerificaInCorso:
                pass
            finally:
                c.close()
            difformita.sincronizza_tutti("verifica dei punteggi")
        ULTIMA_VERIFICA.clear()
        ULTIMA_VERIFICA.update(dal=dal, al=al, esito="in_corso")
        threading.Thread(target=lavoro, daemon=True, name="punteggi").start()
        return jsonify({"ok": True, "msg": f"Verifica dei punteggi dal {dal} al {al} avviata"}), 202

    @bp.get("/api/punteggi")
    @protezione
    def api_punteggi():
        periodo = _periodo()
        if not periodo:
            return jsonify({"error": "Periodo non valido (mese AAAA-MM oppure dal/al AAAA-MM-GG)"}), 400
        conn = _conn()
        try:
            return jsonify({"dal": periodo[0], "al": periodo[1], "in_corso": punteggi.in_corso(),
                            "ultima": dict(ULTIMA_VERIFICA), "righe": punteggi.elenco_periodo(conn, *periodo)})
        finally:
            conn.close()

    @bp.get("/api/punteggi/candidati/<int:scheda_id>")
    @protezione
    def api_punteggi_candidati(scheda_id: int):
        conn = _conn()
        try:
            dati = punteggi.pannello_candidati(conn, scheda_id)
        finally:
            conn.close()
        if not dati:
            return jsonify({"error": "Elenco non disponibile: rifai la verifica dei punteggi con Selezioni Online collegato"}), 404
        risposta = jsonify(dati)
        risposta.headers["Cache-Control"] = "no-store"  # dati personali: niente cache del browser
        return risposta

    @bp.get("/api/punteggi/excel")
    @protezione
    def api_punteggi_excel():
        periodo = _periodo()
        if not periodo:
            return jsonify({"error": "Periodo non valido"}), 400
        conn = _conn()
        try:
            contenuto = punteggi.excel_graduatorie(conn, *periodo)
        finally:
            conn.close()
        nome = f"Graduatorie-pubblicate-{periodo[0]}-{periodo[1]}.xlsx"
        return contenuto, 200, {
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Content-Disposition": f'attachment; filename="{nome}"', "Cache-Control": "no-store"}

    @bp.get("/api/sol/sessione")
    @protezione
    def api_sol_sessione():
        if sessione_sol:
            return jsonify(sessione_sol.stato())
        if not login_sol:  # niente collegamento separato: vale l'accesso SSO dell'utente
            return jsonify({**sol_sessione.stato(), "disponibile": False, "collegato": bool(token_utente())})
        return jsonify({**sol_sessione.stato(), "disponibile": True})

    @bp.post("/api/sol/esci")
    @protezione
    def api_sol_esci():
        (sessione_sol or sol_sessione).dimentica()
        punteggi.dimentica_candidati()  # con la sessione si dimenticano anche i dati dei candidati
        return jsonify({"ok": True})

    @bp.post("/api/referenti/aggiorna")
    @protezione
    @solo_admin
    def api_referenti_aggiorna():
        token = token_utente()
        if not token and not referenti.senza_token_ammesso():
            return jsonify({"error": "Per leggere i referenti collega prima Selezioni Online",
                            "login": login_url}), 401
        conn = _conn()
        try:
            ultimo = referenti.stato(conn)
        finally:
            conn.close()
        if ultimo and ultimo["esito"] == "in_corso":
            return jsonify({"ok": False, "msg": "Aggiornamento dei referenti già in corso"}), 409
        utente = utente_corrente()

        def lavoro():
            c = _conn()
            try:
                referenti.aggiorna(c, token, utente)
            except referenti.AggiornamentoInCorso:
                pass
            finally:
                c.close()
        threading.Thread(target=lavoro, daemon=True, name="referenti").start()
        return jsonify({"ok": True, "msg": "Aggiornamento dei referenti avviato"}), 202

    @bp.get("/api/referenti/stato")
    @protezione
    def api_referenti_stato():
        conn = _conn()
        try:
            return jsonify({"ultimo": referenti.stato(conn), "collegato": token_utente() is not None,
                            "senza_token": referenti.senza_token_ammesso(), "login": login_url})
        finally:
            conn.close()

    @bp.get("/monitoraggio")
    @bp.get("/monitoraggio/")
    @protezione
    def pagina():
        return send_from_directory(STATIC, "riepilogo.html")

    @bp.get("/monitoraggio/menu.js")
    @protezione
    def menu_js():
        risposta = send_from_directory(STATIC, "menu.js")
        risposta.headers["Cache-Control"] = "no-cache"
        return risposta

    @bp.get("/monitoraggio/solleciti.js")
    @protezione
    def solleciti_js():
        risposta = send_from_directory(STATIC, "solleciti.js")
        risposta.headers["Cache-Control"] = "no-cache"
        return risposta

    @bp.get("/api/menu")
    @protezione
    def api_menu():
        ruolo = ruolo_corrente()
        gruppi = [{**g, "voci": [v for v in g["voci"] if not v["solo_admin"] or ruolo == "amministratore"]}
                  for g in menu(pagine_disponibili)]
        conn = _conn()
        try:
            da_comunicare = comunicazioni.da_comunicare(conn)
            fonti = {f["fonte"]: f["aggiornata_il"] for f in comunicazioni.allineamento(conn, config.monitoraggio_dal().isoformat()[:7])}
        finally:
            conn.close()
        return jsonify({"gruppi": gruppi, "utente": utente_corrente(), "ruolo": ruolo, "vista_come": utenti.vista_come(), "avviso_dati": avviso_dati(),
                        "da_comunicare": da_comunicare, "fonti": fonti, "login": login_url, "logout": logout_url})

    @bp.post("/api/raccolta/avvia")
    @protezione
    @solo_admin
    def api_avvia():
        corpo = request.get_json(silent=True) or {}
        fonti = [f for f in (corpo.get("fonti") or ["urp", "sol"]) if f in ("urp", "sol")]
        risposta, codice = avvia_raccolta(fonti or ["urp", "sol"], bool(corpo.get("completa")), utente_corrente())
        return jsonify(risposta), codice

    @bp.get("/api/raccolta/stato")
    @protezione
    def api_stato():
        conn = _conn()
        try:
            return jsonify({"fonti": stato(conn), "prossima_notturna": prossima_notturna()})
        finally:
            conn.close()

    @bp.get("/api/raccolta/<int:raccolta_id>/errori")
    @protezione
    def api_errori(raccolta_id: int):
        conn = _conn()
        try:
            return jsonify({"raccolta_id": raccolta_id, "errori": errori(conn, raccolta_id)})
        finally:
            conn.close()

    @bp.get("/api/bandi")
    @protezione
    def api_bandi():
        conn = _conn()
        try:
            filtri = {k: request.args.get(k) for k in ("tipologia", "stato_collegamento", "fonte", "dal", "al", "q")}
            bandi = elenco_bandi(conn, filtri)
            return jsonify({"totale": len(bandi), "bandi": bandi})
        finally:
            conn.close()

    @bp.get("/api/bandi/<int:bando_id>")
    @protezione
    def api_bando(bando_id: int):
        conn = _conn()
        try:
            bando = dettaglio_bando(conn, bando_id)
            return (jsonify(bando), 200) if bando else (jsonify({"error": "Bando non trovato"}), 404)
        finally:
            conn.close()

    @bp.get("/api/riepilogo-rdp")
    @protezione
    def api_riepilogo_rdp():
        """RdP e metadati dei bandi, letti dal database del nuovo flusso."""
        conn = _conn()
        try:
            per_bando = referenti.referenti_per_bando(conn)
            righe = []
            for b in conn.execute("SELECT * FROM bando WHERE stato_collegamento IS NOT NULL"):
                righe.append({
                    "codice": b["codice"],
                    "rdp_group": b["gruppo_rdp"] or "",
                    "rdp_members": [" ".join(x for x in (p["nome"], p["cognome"]) if x)
                                    for p in per_bando.get(b["id"], [])],
                    "call_status": b["stato_collegamento"] or "",
                    "call_structure": b["sede"] or "",
                    "call_profile": b["profilo"] or "",
                    "call_num_posti": b["numero_posti"] or "",
                    "call_date_start": "",
                    "call_date_end": "",
                })
            return jsonify(righe)
        finally:
            conn.close()

    @bp.get("/api/riepilogo")
    @protezione
    def api_riepilogo():
        conn = _conn()
        try:
            return jsonify(riepilogo_mensile(conn))
        finally:
            conn.close()

    # ------------------------------------------------------------- file della segreteria (spec 002)

    @bp.get("/monitoraggio/segreteria")
    @protezione
    def pagina_segreteria():
        return send_from_directory(STATIC, "segreteria.html")

    @bp.post("/api/segreteria/carica")
    @protezione
    def api_segreteria_carica():
        if ruolo_corrente() not in ("amministratore", "segreteria"):  # la segreteria carica i propri file
            return jsonify({"error": "Operazione riservata agli amministratori e alla segreteria"}), 403
        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify({"error": "Nessun file selezionato"}), 400
        if not file.filename.lower().endswith(".xlsx"):
            return jsonify({"error": "Serve un file Excel .xlsx"}), 400
        contenuto = file.read(MAX_FILE_SEGRETERIA + 1)
        if len(contenuto) > MAX_FILE_SEGRETERIA:
            return jsonify({"error": "File troppo grande (massimo 15 MB)"}), 413
        conn = _conn()
        try:
            versione = segreteria.importa(conn, contenuto, file.filename, utente_corrente())
            difformita.sincronizza_tutti("file della segreteria")
            return jsonify({"versione": versione, "differenze": segreteria.differenze(conn, versione["id"])}), 201
        except segreteria.FileNonValido as e:
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    # --- spec 010: protocolli dalle email di Titulus («Documenti in uscita protocollo» nella pagina della segreteria)
    def _puo_decidere():
        return ruolo_corrente() in ("amministratore", "segreteria")

    @bp.get("/api/segreteria/protocollo")
    @protezione
    def api_protocollo_elenco():
        conn = _conn()
        try:
            risposta = jsonify({"protocolli": protocollo_email.elenco(conn), "categorie": protocollo_email.CATEGORIE,
                                "sottotipi": protocollo_email.SOTTOTIPI, "nel_file": list(protocollo_email.NEL_FILE),
                                "chiavi": protocollo_email.chiavi(conn, None if ruolo_corrente() == "amministratore" else utente_corrente()),
                                "puo_decidere": _puo_decidere()})
            risposta.headers["Cache-Control"] = "no-store"
            return risposta
        finally:
            conn.close()

    @bp.put("/api/segreteria/protocollo/<int:id_riga>")
    @protezione
    def api_protocollo_modifica(id_riga: int):
        if not _puo_decidere():
            return jsonify({"error": "Operazione riservata agli amministratori e alla segreteria"}), 403
        conn = _conn()
        try:
            protocollo_email.modifica(conn, id_riga, request.get_json(silent=True) or {})
            return jsonify({"ok": True})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @bp.post("/api/segreteria/protocollo/<int:id_riga>/stato")
    @protezione
    def api_protocollo_stato(id_riga: int):
        if not _puo_decidere():
            return jsonify({"error": "Operazione riservata agli amministratori e alla segreteria"}), 403
        conn = _conn()
        try:
            protocollo_email.decidi(conn, id_riga, str((request.get_json(silent=True) or {}).get("stato") or ""), utente_corrente())
            return jsonify({"ok": True})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except LookupError as e:
            return jsonify({"error": str(e)}), 404
        finally:
            conn.close()

    @bp.post("/api/segreteria/protocollo/chiavi")
    @protezione
    def api_protocollo_nuova_chiave():
        if not _puo_decidere():
            return jsonify({"error": "Operazione riservata agli amministratori e alla segreteria"}), 403
        conn = _conn()
        try:
            chiave = protocollo_email.crea_chiave(conn, utente_corrente(), str((request.get_json(silent=True) or {}).get("nome") or ""))
            risposta = jsonify({"chiave": chiave})  # si vede una volta sola: nel database c'è solo l'impronta
            risposta.headers["Cache-Control"] = "no-store"
            return risposta, 201
        finally:
            conn.close()

    @bp.delete("/api/segreteria/protocollo/chiavi/<int:id_chiave>")
    @protezione
    def api_protocollo_revoca_chiave(id_chiave: int):
        if not _puo_decidere():
            return jsonify({"error": "Operazione riservata agli amministratori e alla segreteria"}), 403
        conn = _conn()
        try:
            fatto = protocollo_email.revoca(conn, id_chiave, None if ruolo_corrente() == "amministratore" else utente_corrente())
            return (jsonify({"ok": True}), 200) if fatto else (jsonify({"error": "Chiave non trovata"}), 404)
        finally:
            conn.close()

    @bp.get("/monitoraggio/segreteria/programma-protocollo")
    @protezione
    def programma_protocollo():
        nome, contenuto = protocollo_email.programma_zip(request.host_url.rstrip("/"))
        return send_file(io.BytesIO(contenuto), mimetype="application/zip", as_attachment=True, download_name=nome)

    @bp.post("/api/programma-protocollo/ricevi")
    def api_programma_ricevi():
        """Dal programma sul PC: niente sessione, vale la chiave personale (header Authorization: Bearer mp_...)."""
        intestazione = request.headers.get("Authorization", "")
        chiave = intestazione[7:].strip() if intestazione.startswith("Bearer ") else None
        if request.content_length and request.content_length > 2 * 1024 * 1024:
            return jsonify({"error": "Invio troppo grande"}), 413
        conn = _conn()
        try:
            chi = protocollo_email.utente_della_chiave(conn, chiave)
            if not chi:
                return jsonify({"error": "Chiave non valida o revocata: generane una nuova nella pagina File segreteria"}), 401
            corpo = request.get_json(silent=True) or {}
            return jsonify(protocollo_email.ricevi(conn, corpo.get("voci") or [], chi, str(corpo.get("casella") or "")))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @bp.get("/api/segreteria/versioni")
    @protezione
    def api_segreteria_versioni():
        conn = _conn()
        try:
            return jsonify({"versioni": segreteria.storico_versioni(conn)})
        finally:
            conn.close()

    @bp.get("/api/segreteria/versioni/<int:versione_id>/problemi")
    @protezione
    def api_segreteria_problemi(versione_id: int):
        conn = _conn()
        try:
            return jsonify(segreteria.problemi_righe(conn, versione_id))
        finally:
            conn.close()

    @bp.get("/api/segreteria/versioni/<int:versione_id>/differenze")
    @protezione
    def api_segreteria_differenze(versione_id: int):
        conn = _conn()
        try:
            return jsonify(segreteria.differenze(conn, versione_id))
        finally:
            conn.close()

    @bp.get("/api/segreteria/atti")
    @protezione
    def api_segreteria_atti():
        conn = _conn()
        try:
            versione_id = request.args.get("versione", type=int)
            if not versione_id:
                in_uso = segreteria.versione_in_uso(conn)
                if not in_uso:
                    return jsonify({"versione": None, "atti": []})
                versione_id = in_uso["id"]
            atti_file = segreteria.atti_versione(conn, versione_id, request.args.get("categoria") or None,
                                                 request.args.get("mese") or None)
            collegati = {r["numero_bando"]: r["stato_collegamento"] for r in conn.execute(
                "SELECT numero_bando, stato_collegamento FROM bando WHERE numero_bando IS NOT NULL")}
            for a in atti_file:
                a["stato_collegamento"] = collegati.get(a["numero_bando"])
            segreteria.collega_urp(conn, atti_file)
            return jsonify({"versione": versione_id, "atti": atti_file})
        finally:
            conn.close()

    @bp.get("/monitoraggio/segreteria/file")
    @protezione
    def pagina_file_segreteria():
        # indirizzo della vecchia vista del file, ancora nei collegamenti salvati
        return redirect("/monitoraggio/segreteria" + (f"?{request.query_string.decode()}" if request.query_string else ""))

    @bp.get("/api/segreteria/atti/<int:atto_id>/righe")
    @protezione
    def api_segreteria_righe(atto_id: int):
        conn = _conn()
        try:
            return jsonify({"atto_id": atto_id, "righe": segreteria.righe_atto(conn, atto_id)})
        finally:
            conn.close()

    @bp.get("/api/atti")
    @protezione
    def api_atti():
        conn = _conn()
        try:
            righe = atti.elenco_atti(conn, request.args.get("dal") or None, request.args.get("al") or None)
            per_atto = comunicazioni.per_atto(conn, request.args.get("dal") or None, request.args.get("al") or None)
            for r in righe:  # la comunicazione come nel monitoraggio (spec 009): stato, protocollo dell'email, storico
                r["comunicazione"] = comunicazioni.comunicazione_di(per_atto, r)
                # senza monitoraggio si può comunque scrivere: il monitoraggio del mese si crea al primo invio
                r["chiave"] = comunicazioni.chiave(r)
                r["comunicabile"] = r["atto"] in difformita.ATTI_SEGUITI and config.nel_monitoraggio(r.get("tipologia")) and bool(r.get("data"))
            return jsonify({"dal": request.args.get("dal") or config.monitoraggio_dal().isoformat(),
                            "totale": len(righe), "atti": righe, "fonti_in_attesa": atti.fonti_in_attesa(conn)})
        finally:
            conn.close()

    return bp


# pagine esistenti che il server locale sa servire: le altre (firme, RdP, ispezione SOL)
# dipendono dalle route di avvia_tool.py e in locale risultano "non disponibili"
PAGINE_LOCALI = {"index.html", "access.html", "mobilita-urp.html", "report-mese.html",
                 "search.html", "stato-avanzamento.html", "verifica-access.html"}


def crea_blueprint_pagine_esistenti(protezione=lambda f: f, solo_admin=lambda f: f) -> Blueprint:
    """Solo per il server locale: le pagine di oggi (index.html, mobilita-urp.html, report-mese.html)
    con i JSON e le API /api/status e /api/run ricostruiti dal database. In avvia_tool.py le stesse
    risposte arrivano dalle sue route (T035, T036)."""
    bp = Blueprint("pagine_esistenti", __name__)
    pagine = PAGINE_LOCALI

    @bp.get("/_static/<path:nome>")
    @protezione
    def json_compat(nome: str):
        if nome not in compat.EXPORT:
            return jsonify({"error": "non trovato"}), 404
        fonte, funzione = compat.EXPORT[nome]
        conn = _conn()
        try:
            risposta = jsonify(funzione(conn))
            fine = compat.ultima_riuscita(conn, fonte)
        finally:
            conn.close()
        if fine:
            risposta.headers["Last-Modified"] = datetime.fromisoformat(fine.replace("Z", "+00:00")).strftime(
                "%a, %d %b %Y %H:%M:%S GMT")
        risposta.headers["Cache-Control"] = "no-store"
        return risposta

    @bp.get("/api/status")
    @protezione
    def status_compat():
        conn = _conn()
        try:
            s = stato(conn)
            fine = {f: compat.ultima_riuscita(conn, f) for f in ("urp", "sol")}
        finally:
            conn.close()
        voce = lambda f: {"exists": fine[f] is not None, "mtime": fine[f]}  # noqa: E731
        return jsonify({"urp": voce("urp"), "sol": voce("sol"), "mob": voce("urp"),
                        "running": any(s[f]["in_corso"] for f in s)})

    @bp.post("/api/run")
    @protezione
    @solo_admin
    def run_compat():
        corpo = request.get_json(silent=True) or {}
        fonti = [f for f, chiavi in (("urp", ("urp", "mob")), ("sol", ("sol",))) if any(corpo.get(k, True) for k in chiavi)]
        risposta, codice = avvia_raccolta(fonti, False, "pagina")
        return jsonify({"ok": risposta["ok"], "msg": "Run avviata" if risposta["ok"] else "Una run è già in corso"}), \
            (200 if codice == 202 else codice)

    def _valuta_caricato(file) -> dict:
        nome = secure_filename(file.filename or "documento.pdf")
        dati = file.read(MAX_FILE_PDF + 1)
        if len(dati) > MAX_FILE_PDF:
            return {**accessibilita.valuta_file(b"", "non-valutato"), "filename": nome, "note": "File oltre 25 MB"}
        return accessibilita.valuta_file(dati, nome)

    @bp.post("/api/check-access")
    @protezione
    def check_access():
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "Parametro 'file' assente"}), 400
        return jsonify({"ok": True, "result": _valuta_caricato(request.files["file"])})

    @bp.post("/api/check-access-batch")
    @protezione
    def check_access_batch():
        file = request.files.getlist("files")
        if not file:
            return jsonify({"ok": False, "error": "Parametro 'files' assente"}), 400
        return jsonify({"ok": True, "results": [_valuta_caricato(f) for f in file]})

    @bp.get("/<nome>")
    @protezione
    def pagina_esistente(nome: str):
        if nome not in pagine:
            return jsonify({"error": "non trovato"}), 404
        return send_from_directory(config.ROOT, nome)

    return bp
