"""Parti comuni della verifica dei file del mese (spec 011): gruppi di concorsi, nominativi, persone della segreteria.

I nominativi servono al confronto per persona (scelta dell'utente del 2026-11-18): si leggono, si mostrano solo agli
amministratori e non vanno mai nei log.
"""
import difflib
import json
import re
import unicodedata

from . import profili, segreteria

# gruppi di concorsi, come i fogli del file scorrimenti; l'ordine è quello dei fogli e del file graduatorie
# DT: tutti i livelli dei tecnologi (fogli DT, PT, TEC); RIC: tutti i livelli dei ricercatori
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
                             ("OTP", "OTP"), ("RIC", "RIC"), ("PR", "RIC"), ("DR", "RIC"), ("DT", "DT"), ("PT", "DT"), ("TEC", "DT")):
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
    t = "".join(c for c in unicodedata.normalize("NFKD", str(testo or "")) if not unicodedata.combining(c))
    # apostrofi dritti e tipografici (DELL'ORSO / DELL’ORSO) e ogni altro segno valgono come spazio
    return " ".join(sorted(re.findall(r"[a-z]+", re.sub(r"[^A-Za-z]+", " ", t).lower())))


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


SIMILI = 0.85  # sopra questa somiglianza due nominativi sono la stessa persona scritta in modo diverso


def _altrove(chiave: str, altrove: dict | None, qui) -> list[str]:
    """Dove si trova la persona fuori dal bando che si sta controllando (etichette), se lo si sa."""
    return list(dict.fromkeys(etichetta for posto, etichetta in (altrove or {}).get(chiave, []) if not qui(posto)))


def confronta_persone(nel_file: list[dict], in_segreteria: list[dict] | None, con_punteggi: bool = False,
                      altrove_file: dict | None = None, altrove_segreteria: dict | None = None, qui=lambda posto: False) -> list[str]:
    """Differenze per persona tra il file e la segreteria. `nel_file`: {nominativo, posizione?, punteggio?}.
    `altrove_*`: per nominativo, dove compare nel resto del file o della segreteria ([(posto, etichetta)]); `qui(posto)` dice se
    il posto è il bando che si sta controllando. Chi manca ma è sotto un altro bando si segnala una volta sola, per bando."""
    if in_segreteria is None:
        return []
    problemi = []
    seg = {p["chiave"]: p for p in in_segreteria}
    fil = {nome_chiave(p["nominativo"]): p for p in nel_file}
    solo_file = [k for k in fil if k not in seg]
    solo_seg = [k for k in seg if k not in fil]
    for k in list(solo_file):  # refusi: la stessa persona scritta in modo diverso nei due file
        simile = max(solo_seg, key=lambda s: difflib.SequenceMatcher(None, k, s).ratio(), default=None)
        if simile and difflib.SequenceMatcher(None, k, simile).ratio() >= SIMILI:
            problemi.append(f"nome scritto diverso: «{fil[k]['nominativo']}» nel file, «{seg[simile]['nominativo']}» nel file della segreteria")
            solo_file.remove(k)
            solo_seg.remove(simile)
    for lista, mappa, altrove, testo_altrove, testo_solo in (
            (solo_seg, seg, altrove_file, "del file della segreteria per questo bando sono nel file sotto", "nel file della segreteria ma non nel file"),
            (solo_file, fil, altrove_segreteria, "del file per questo bando sono nel file della segreteria sotto", "nel file ma non nel file della segreteria")):
        per_posto: dict[str, list[str]] = {}
        for k in lista:
            posti = _altrove(k, altrove, qui)
            if posti:
                per_posto.setdefault(posti[0], []).append(mappa[k]["nominativo"])
            else:
                problemi.append(f"{mappa[k]['nominativo']}: {testo_solo}")
        for posto, nomi in per_posto.items():
            chi = "1 persona" if len(nomi) == 1 else f"{len(nomi)} persone"
            problemi.append(f"{chi} {testo_altrove} «{posto}»: bando o protocollo da verificare in uno dei due file ({', '.join(nomi)})")
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


def qui_per(numero: str | None, protocolli: set[str]):
    """Il controllo «è il bando che si sta verificando?» per un posto (numero, protocollo o tupla di protocolli)."""
    def qui(posto) -> bool:
        prot = posto[1]
        return posto[0] == numero and bool((set(prot) if isinstance(prot, (tuple, list)) else {prot}) & protocolli)
    return qui


def dove_in_segreteria(persone: dict | None) -> dict[str, list]:
    """Per nominativo, i (bando, protocollo) della segreteria in cui compare: [((numero, protocollo), etichetta)]."""
    dove: dict[str, list] = {}
    for (numero, prot), lista in (persone or {}).items():
        for p in lista:
            dove.setdefault(p["chiave"], []).append(((numero, prot), f"{numero} (prot. {prot})" if prot else str(numero)))
    return dove


def _intero(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return v
