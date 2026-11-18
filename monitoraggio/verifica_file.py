"""Parti comuni della verifica dei file del mese (spec 011): gruppi di concorsi, nominativi, persone della segreteria.

I nominativi servono al confronto per persona (scelta dell'utente del 2026-11-18): si leggono, si mostrano solo agli
amministratori e non vanno mai nei log.
"""
import json
import re
import unicodedata

from . import profili, segreteria

# gruppi di concorsi, come i fogli del file scorrimenti; l'ordine è quello dei fogli e del file graduatorie
GRUPPI = {"RIC": "Ricercatore", "DT": "Tecnologo", "CTER": "Collaboratore tecnico enti di ricerca",
          "FUNZ": "Funzionario di amministrazione", "COLL.AMM": "Collaboratore di amministrazione",
          "OTP": "Operatore tecnico", "OP.AMM": "Operatore di amministrazione"}
_DA_PROFILO = {v: k for k, v in GRUPPI.items()}
ALTRO = "ALTRO"


def gruppo_di_profilo(profilo: str | None) -> str:
    return _DA_PROFILO.get(profili.famiglia(profilo) or "", ALTRO)


def gruppo_di_foglio(nome: str | None) -> str:
    """«CTER 6» -> CTER, «COLL.AMM» -> COLL.AMM, «FUNZ 5» -> FUNZ, «Ricercatori» -> RIC."""
    t = re.sub(r"[^A-Z]", "", unicodedata.normalize("NFKD", nome or "").upper())
    for prefisso, gruppo in (("COLLAMM", "COLL.AMM"), ("OPAMM", "OP.AMM"), ("OAMM", "OP.AMM"), ("CTER", "CTER"), ("FUNZ", "FUNZ"),
                             ("OTP", "OTP"), ("RIC", "RIC"), ("DT", "DT"), ("TECN", "DT")):
        if t.startswith(prefisso):
            return gruppo
    return ALTRO


def profili_per_bando(conn) -> tuple[dict, dict]:
    """Il profilo senza livello (non la voce dei coordinatori) per bando e per numero del bando, da Selezioni Online."""
    per_bando, per_numero = {}, {}
    for s in conn.execute("SELECT bando_id, numero_bando, dati_extra FROM scheda WHERE fonte = 'sol' AND presente = 1 AND dati_extra IS NOT NULL"):
        nome = profili.famiglia(json.loads(s["dati_extra"]).get("profilo"))
        if nome:
            per_bando.setdefault(s["bando_id"], nome)
            per_numero.setdefault(s["numero_bando"], nome)
    return per_bando, per_numero


def gruppo_della_riga(riga: dict, profili_bandi: tuple[dict, dict]) -> str:
    per_bando, per_numero = profili_bandi
    profilo = per_bando.get(riga.get("bando_id")) or per_numero.get(riga.get("numero_bando"))
    return _DA_PROFILO.get(profilo or "", ALTRO)


def nome_chiave(testo) -> str:
    """Nominativo confrontabile: senza accenti, maiuscole, punteggiatura e ordine tra nome e cognome."""
    t = unicodedata.normalize("NFKD", str(testo or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(sorted(re.findall(r"[a-z]+", t)))


def dividi_nominativi(testo) -> list[str]:
    """Più nominativi nella stessa cella: a capo, punto e virgola o barra."""
    return [n.strip() for n in re.split(r"[\n;/]+", str(testo or "")) if n.strip() and re.search(r"[A-Za-zÀ-ÿ]{2}", n)]


def _norm(testo) -> str:
    return segreteria._norm_intestazione(testo)


def _cerca(valori: dict, *alias: str):
    for etichetta, v in valori.items():
        n = _norm(etichetta)
        if any(n == a or (a.endswith("*") and n.startswith(a[:-1])) for a in alias):
            return v
    return None


def persone_segreteria(conn, categoria: str) -> dict[tuple, list[dict]] | None:
    """Le persone del file della segreteria in uso per (numero bando, protocollo) di graduatorie o scorrimenti.
    None se il file non è caricato."""
    versione = segreteria.versione_in_uso(conn)
    if not versione:
        return None
    persone: dict[tuple, list[dict]] = {}
    for r in conn.execute("SELECT a.numero_bando, a.protocollo, a.sottotipo, r.foglio, r.numero_riga, r.valori FROM segreteria_riga r "
                          "JOIN segreteria_atto a ON a.id = r.atto_id WHERE r.versione_id = ? AND a.categoria = ?", (versione["id"], categoria)):
        valori = json.loads(r["valori"])
        nominativo = _cerca(valori, "cognomeenome")
        if not nominativo:
            continue
        persone.setdefault((r["numero_bando"], str(r["protocollo"] or "")), []).append({
            "nominativo": str(nominativo).strip(), "chiave": nome_chiave(nominativo), "riga": r["numero_riga"],
            "posizione": _cerca(valori, "posizione"), "punteggio": _cerca(valori, "punteggio"),
            "tipologia": _cerca(valori, "tipologiadiutilizzo*"), "sottotipo": r["sottotipo"]})
    return persone


def punteggio_numero(v) -> float | None:
    """«78/100», «80,9», 85 -> numero; None se non si legge."""
    m = re.search(r"\d+(?:[.,]\d+)?", str(v if v is not None else ""))
    return float(m.group().replace(",", ".")) if m else None


def confronta_persone(nel_file: list[dict], in_segreteria: list[dict] | None, con_punteggi: bool = False) -> list[str]:
    """Differenze per persona tra il file e la segreteria. `nel_file`: {nominativo, posizione?, punteggio?}."""
    if in_segreteria is None:
        return []
    problemi = []
    seg = {p["chiave"]: p for p in in_segreteria}
    fil = {nome_chiave(p["nominativo"]): p for p in nel_file}
    for k, p in fil.items():
        if k not in seg:
            problemi.append(f"{p['nominativo']}: nel file ma non nel file della segreteria")
    for k, p in seg.items():
        if k not in fil:
            problemi.append(f"{p['nominativo']}: nel file della segreteria ma non nel file")
    if con_punteggi:
        for k, p in fil.items():
            s = seg.get(k)
            if not s:
                continue
            if s.get("posizione") not in (None, "") and p.get("posizione") not in (None, "") and str(_intero(s["posizione"])) != str(_intero(p["posizione"])):
                problemi.append(f"{p['nominativo']}: posizione {_intero(p['posizione'])} nel file, {_intero(s['posizione'])} nella segreteria")
            a, b = punteggio_numero(p.get("punteggio")), punteggio_numero(s.get("punteggio"))
            if a is not None and b is not None and abs(a - b) > 0.001:
                problemi.append(f"{p['nominativo']}: punteggio {p['punteggio']} nel file, {s['punteggio']} nella segreteria")
    return problemi


def _intero(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return v
