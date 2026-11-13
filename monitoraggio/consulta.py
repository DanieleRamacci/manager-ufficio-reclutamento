"""Consultazione per chi non è amministratore: Stato complessivo e Monitoraggi, solo in visualizzazione.

Decisioni dell'utente del 2026-11-11: solo gli amministratori hanno il menu completo e possono operare. I dirigenti
vedono tutti i bandi; la segreteria tutti i bandi e le difformità, ma i punteggi solo dei bandi di cui è RdP; gli utenti in lettura e gli RdP i bandi di cui sono RdP; i coordinatori anche i bandi dei profili
che coordinano (o tutta la mobilità, se coordinano «Mobilità»), con l'indicazione «come coordinatore» o «come RdP». Il filtro si fa qui e i campi che escono sono un
elenco chiuso. Nomi e punteggi dei candidati solo a chi vede tutto ed è entrato con Selezioni Online.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from flask import Blueprint, jsonify, redirect, request, send_from_directory

from . import atti, comunicazioni, config, difformita, mensile, portale, profili, punteggi, utenti

_STATIC = Path(__file__).resolve().parent / "static"
PAGINE_SITO = "/monitoraggio/consulta"
PAGINE_AREA = "/referenti"
FONTI = ("sol", "urp", "segreteria")


@dataclass
class Visitatore:
    email: str | None
    emails: set = field(default_factory=set)
    tutto: bool = False
    punteggi: bool = True          # vede i punteggi di tutti i bandi che vede (la segreteria no: solo dove è RdP)
    profili: list | None = None   # None: non è coordinatore
    candidati: bool = False
    area: bool = False
    anteprima: bool = False
    senza_bandi: bool = False      # in lettura ma non RdP: non dovrebbe entrare (si vede solo in anteprima)

    def descrizione(self) -> dict:
        return {"email": self.email, "tutto": self.tutto, "punteggi": self.punteggi, "coordinatore": self.profili is not None, "profili": self.profili or [],
                "candidati": self.candidati, "area": self.area, "anteprima": self.anteprima, "senza_bandi": self.senza_bandi}


def visitatore_sito(intestazioni_sol) -> Visitatore | None:
    ruolo = utenti.ruolo_corrente()
    anteprima = utenti.vista_come()
    chi = anteprima or utenti.corrente()
    if ruolo in (utenti.AMMINISTRATORE, utenti.DIRIGENTE):
        return Visitatore(chi, tutto=True, candidati=bool(intestazioni_sol()), anteprima=bool(anteprima))
    if ruolo == utenti.SEGRETERIA:  # tutti i bandi e le difformità; i punteggi solo dove è RdP
        return Visitatore(chi, emails=utenti.email_correnti(), tutto=True, punteggi=False, anteprima=bool(anteprima))
    if ruolo == utenti.LETTURA:
        emails = utenti.email_correnti()
        return Visitatore(chi, emails=emails, anteprima=bool(anteprima), senza_bandi=not utenti.referente_attivo(emails))
    return None


def visitatore_area(conn) -> Visitatore | None:
    email = portale.referente_corrente()
    if not email:
        return None
    return Visitatore(email, emails={email}, profili=portale.profili_coordinatore(conn, email), area=True,
                      anteprima=portale.in_anteprima())


def _profili_bandi(conn) -> tuple[dict, dict]:
    """La voce dell'elenco (profilo senza livello o «Mobilità») per bando e per numero del bando."""
    _, per_bando, per_numero = profili.per_bando(conn)
    return per_bando, per_numero


def _email(persona: dict) -> str:
    return (persona.get("email") or "").strip().lower()


def come(v: Visitatore, riga: dict, profili_bandi: tuple[dict, dict], esclusi=()) -> list[str]:
    """Perché il visitatore vede la riga; vuoto se non la vede (chi vede tutto con i punteggi non ha bisogno di motivi;
    la segreteria vede tutto ma le serve sapere dove è RdP)."""
    if v.tutto and v.punteggi:
        return []
    motivi = []
    per_bando, per_numero = profili_bandi
    profilo = per_bando.get(riga.get("bando_id")) or per_numero.get(riga.get("numero_bando"))
    if v.profili and profili.voce(riga.get("tipologia"), profilo) in v.profili:
        motivi.append("coordinatore")
    # se il codice non ha RdP propri l'elenco è di tutti i codici del bando: non si sa di chi sia l'atto
    if riga.get("rdp_origine") != "tutti i codici" and (v.emails & {_email(p) for p in riga.get("rdp") or []}) - set(esclusi):
        motivi.append("rdp")
    return motivi


def _punteggi_visibili(v: Visitatore, motivi: list[str]) -> bool:
    return v.punteggi or "rdp" in motivi


def _riga(r: dict, v: Visitatore, motivi: list[str]) -> dict:
    con_punteggi = _punteggi_visibili(v, motivi)
    p = (r.get("punteggi") or {}) if con_punteggi else {}
    scheda = p.get("scheda_id") if v.candidati else None
    sol = (r.get("fonti") or {}).get("sol") or {}
    return {
        **{k: r.get(k) for k in ("numero_bando", "codice", "titolo_bando", "tipologia", "atto", "sottotipo", "data", "protocollo")},
        "fonti": {k: {x: c.get(x) for x in ("stato", "protocollo", "url")} for k, c in (r.get("fonti") or {}).items() if k in FONTI},
        "protocollo_diverso": bool(r.get("protocollo_diverso")), "note": list(r.get("note") or []), "difforme": bool(r.get("difforme")),
        "rdp": [{k: x.get(k) for k in ("nome", "cognome", "email")} for x in r.get("rdp") or []],
        "link_sol": r.get("link_codice") or sol.get("url"),
        "url_punteggi": r.get("url_punteggi") if (v.tutto and v.punteggi) or "rdp" in motivi else None,
        "punteggi": {**{k: p.get(k) for k in ("domande", "con_punteggi", "esito", "verificato_il")}, "scheda_id": scheda} if p else None,
        "sede_da_abbinare": bool(r.get("sede_da_abbinare")), "come": motivi,
        "subentro_atteso": bool(r.get("subentro_atteso")), "file_scorrimenti": r.get("file_scorrimenti"), "coordinatore": r.get("coordinatore"),
        "sedi": [{"codice": s.get("codice"), "link_sol": s.get("link_sol"), "note": list(s.get("note") or []),
                  "url_punteggi": s.get("url_punteggi") if (v.tutto and v.punteggi) or "rdp" in motivi else None,
                  "punteggi": {**{k: (s.get("punteggi") or {}).get(k) for k in ("domande", "con_punteggi", "esito", "verificato_il")},
                               "scheda_id": s["scheda_id"] if v.candidati else None} if con_punteggi and (s.get("punteggi") or v.candidati) else None,
                  "rdp": [{k: x.get(k) for k in ("nome", "cognome", "email")} for x in s.get("rdp") or []]} for s in r.get("sedi") or []],
    }


def _in_attesa(conn) -> list[str]:
    return [f["nome"] for f in atti.fonti_in_attesa(conn)]


def stato(conn, v: Visitatore) -> dict:
    pb = _profili_bandi(conn)
    righe = []
    if not v.senza_bandi:
        for r in atti.elenco_atti(conn):
            motivi = come(v, r, pb)
            if v.tutto or motivi:
                righe.append(_riga(r, v, motivi))
    return {"visitatore": v.descrizione(), "dal": config.monitoraggio_dal().isoformat(), "in_attesa": _in_attesa(conn), "righe": righe}


def monitoraggi(conn, v: Visitatore) -> dict:
    return {"visitatore": v.descrizione(),
            "monitoraggi": [{"mese": m["mese"], "titolo": comunicazioni.titolo_mese(m["mese_dati"]), "stato": m["stato"],
                             "chiuso_il": m.get("chiuso_il")} for m in mensile.elenco(conn)]}


def _segnalazioni(conn, mese: str, email: str) -> dict:
    return {(s["chiave"], s["atto"], s["protocollo"], s["data"], s["rilievo"]): s
            for s in conn.execute("SELECT * FROM segnalazione WHERE mese = ? AND email = ?", (mese, email))}


def monitoraggio(conn, v: Visitatore, mese: str) -> dict | None:
    m = mensile.leggi(conn, mese) if mensile.mese_valido(mese) else None
    if not m:
        return None
    pb = _profili_bandi(conn)
    base = {"visitatore": v.descrizione(), "mese": m["mese"], "titolo": comunicazioni.titolo_mese(m["mese_dati"]), "stato": m["stato"],
            "monitoraggi": [{"mese": x["mese"], "titolo": comunicazioni.titolo_mese(x["mese_dati"]), "stato": x["stato"]}
                            for x in mensile.elenco(conn)],
            "in_attesa": _in_attesa(conn), "righe": [],
            "aggiornamenti": [{k: f[k] for k in ("nome", "aggiornata_il")} for f in comunicazioni.allineamento(conn, m["mese_dati"])]}
    if v.senza_bandi:
        return base
    if m["stato"] == "chiuso":  # mese chiuso: la versione salvata alla chiusura
        foto = mensile.fotografia(conn, mese)
        for r in foto["righe"]:
            motivi = come(v, r, pb)
            if not (v.tutto or motivi):
                continue
            stato_com = r["sollecito_stato"] or ("da_inviare" if r["difforme"] else "in_regola")
            base["righe"].append({
                **{k: r.get(k) for k in ("numero_bando", "codice", "titolo_bando", "tipologia", "atto", "sottotipo", "data", "protocollo")},
                "fonti": {k: {"stato": r[f"{k}_stato"], "protocollo": r[f"{k}_protocollo"], "url": None} for k in FONTI},
                "rdp": [{k: x.get(k) for k in ("nome", "cognome", "email")} for x in r["rdp"]],
                "rilievi": [{"testo": t, "risolto": False} for t in r["note"]] if r["difforme"] else [],
                "comunicazione": {"stato": stato_com, "quando": r["sollecito_quando"]}, "difforme": bool(r["difforme"]), "come": motivi})
        return {**base, "versione": foto["versione"]}
    esclusi = {r["chiave"]: json.loads(r["esclusi"])
               for r in conn.execute("SELECT chiave, esclusi FROM comunicazione_indirizzi WHERE mese = ?", (mese,))}
    tutte = comunicazioni.righe_mese(conn, m)
    difformita.registro_per_righe(conn, mese, tutte)
    fatte = _segnalazioni(conn, mese, v.email) if v.area else {}
    aperto = m["stato"] == "aperto" and not base["in_attesa"]
    for r in tutte:
        motivi = come(v, r, pb, esclusi.get(r.get("chiave"), []))
        if not (v.tutto or motivi):
            continue
        reg = r.get("registro")
        voci = [*(reg["rilievi"] if reg else []),
                *({"testo": t} for t in r.get("rilievi") or [] if not reg or not any(x["testo"] == t for x in reg["rilievi"]))]
        chiave_atto = (r.get("chiave"), r["atto"], r.get("protocollo") or "", r.get("data") or "")
        rilievi = []
        for x in voci:
            s = fatte.get((*chiave_atto, x["testo"]))
            rilievi.append({"testo": x["testo"], "risolto": bool(x.get("risolto")),
                            "segnalabile": v.area and "rdp" in motivi and aperto and x["testo"] in (r.get("rilievi") or []),
                            "segnalazione": {"stato": s["stato"], "quando": s["quando"], "nota": s["nota"]} if s else None})
        c = r.get("comunicazione") or {}
        base["righe"].append({**_riga(r, v, motivi), "chiave": r.get("chiave"), "n_gestione": r.get("n_gestione"), "rilievi": rilievi,
                              "badge": reg["badge"] if reg else None, "comunicazione": {"stato": c.get("stato"), "quando": c.get("quando")}})
    return base


def _rispondi(v: Visitatore | None, funzione, *argomenti):
    if v is None:
        return jsonify({"error": "Accesso non consentito"}), 403
    conn = portale._conn()
    try:
        dati = funzione(conn, v, *argomenti)
    finally:
        conn.close()
    if dati is None:
        return jsonify({"error": "Monitoraggio non trovato"}), 404
    risposta = jsonify(dati)
    risposta.headers["Cache-Control"] = "no-store"
    return risposta


def _pagina(nome: str):
    risposta = send_from_directory(_STATIC, nome)
    risposta.headers["Cache-Control"] = "no-store"
    return risposta


def crea_blueprint_consulta(protezione=lambda f: f, intestazioni_sol=lambda: None) -> Blueprint:
    """Le pagine nel sito, per dirigenti e utenti in lettura (e per gli amministratori, che vedono tutto)."""
    bp = Blueprint("consulta", __name__)

    def chi():
        return visitatore_sito(intestazioni_sol)

    @bp.get(f"{PAGINE_SITO}/stato")
    @bp.get(f"{PAGINE_SITO}/monitoraggi")
    @bp.get(f"{PAGINE_SITO}/monitoraggi/<mese>")
    @protezione
    def pagina(mese=None):
        return _pagina("consulta.html")

    @bp.get("/api/consulta/stato")
    @protezione
    def api_stato():
        return _rispondi(chi(), stato)

    @bp.get("/api/consulta/monitoraggi")
    @protezione
    def api_monitoraggi():
        return _rispondi(chi(), monitoraggi)

    @bp.get("/api/consulta/monitoraggi/<mese>")
    @protezione
    def api_monitoraggio(mese: str):
        return _rispondi(chi(), monitoraggio, mese)

    @bp.route("/api/consulta/candidati/<int:scheda_id>", methods=["GET", "POST"])
    @protezione
    def api_candidati(scheda_id: int):
        """Nomi e punteggi: solo a chi vede tutto ed è entrato con Selezioni Online. POST: li legge ora con il suo accesso."""
        v = chi()
        if not v or not v.candidati:
            return jsonify({"error": "Per vedere nomi e punteggi entra con le credenziali di Selezioni Online"}), 403
        conn = portale._conn()
        try:
            s = conn.execute("SELECT * FROM scheda WHERE id = ? AND fonte = 'sol'", (scheda_id,)).fetchone()
            if not s:
                return jsonify({"error": "Bando non trovato"}), 404
            if request.method == "POST" and punteggi.candidati(scheda_id) is None:
                try:
                    esito = punteggi.verifica_schede(conn, [s], "0000-01-01", "9999-12-31", intestazioni_sol())
                except punteggi.VerificaInCorso:
                    return jsonify({"error": "È in corso un'altra lettura dei punteggi: riprova tra poco"}), 409
                if esito.get("esito") == "fallita":
                    return jsonify({"error": esito.get("messaggio") or "Lettura da Selezioni Online non riuscita"}), 502
            dati = punteggi.pannello_candidati(conn, scheda_id)
        finally:
            conn.close()
        if not dati:
            return jsonify({"error": "Elenco non ancora letto da Selezioni Online", "caricabile": True}), 404
        risposta = jsonify(dati)
        risposta.headers["Cache-Control"] = "no-store"  # dati personali: niente cache del browser
        return risposta

    return bp


# --- area referenti: le stesse pagine, con l'accesso via email
bp_area = Blueprint("consulta_area", __name__)


@bp_area.get(f"{PAGINE_AREA}/stato")
@bp_area.get(f"{PAGINE_AREA}/monitoraggi")
@bp_area.get(f"{PAGINE_AREA}/monitoraggi/<mese>")
@portale.solo_se_attiva
def pagina_area(mese=None):
    return _pagina("consulta.html") if portale.referente_corrente() else redirect(PAGINE_AREA)


@bp_area.get(f"{PAGINE_AREA}/profili")
@portale.solo_se_attiva
def pagina_profili():
    return _pagina("profili.html") if portale.referente_corrente() else redirect(PAGINE_AREA)


def _visitatore_area():
    conn = portale._conn()
    try:
        return visitatore_area(conn)
    finally:
        conn.close()


@bp_area.get("/api/area-referenti/consulta/stato")
@portale.solo_se_attiva
@portale.serve_referente
def api_area_stato():
    return _rispondi(_visitatore_area(), stato)


@bp_area.get("/api/area-referenti/consulta/monitoraggi")
@portale.solo_se_attiva
@portale.serve_referente
def api_area_monitoraggi():
    return _rispondi(_visitatore_area(), monitoraggi)


@bp_area.get("/api/area-referenti/consulta/monitoraggi/<mese>")
@portale.solo_se_attiva
@portale.serve_referente
def api_area_monitoraggio(mese: str):
    return _rispondi(_visitatore_area(), monitoraggio, mese)
