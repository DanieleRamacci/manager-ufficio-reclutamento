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


def nome_scritto(testo) -> str:
    """Il nominativo normalizzato ma nell'ordine in cui è scritto."""
    t = "".join(c for c in unicodedata.normalize("NFKD", str(testo or "")) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z]+", re.sub(r"[^A-Za-z]+", " ", t).lower()))


SIMILI = 0.85  # sopra questa somiglianza due nominativi sono la stessa persona scritta in modo diverso


def _altrove(chiave: str, altrove: dict | None, qui) -> list[str]:
    """Dove si trova la persona fuori dal bando che si sta controllando (etichette), se lo si sa."""
    return list(dict.fromkeys(etichetta for posto, etichetta in (altrove or {}).get(chiave, []) if not qui(posto)))


def confronta_persone(prima: list[dict], seconda: list[dict] | None, nome_prima: str, nome_seconda: str, con_punteggi: bool = False,
                      altrove_prima: dict | None = None, altrove_seconda: dict | None = None, qui=lambda posto: False) -> dict:
    """Differenze per persona tra due fonti (es. «su SOL» e «nel file della segreteria»); la prima dà i nomi veri.
    Ritorna {"gravi": [...], "minori": [...]}: chi manca è grave; nomi scritti diversi, posizioni e punteggi sono minori.
    `altrove_*`: per nominativo, dove compare nel resto della fonte ([(posto, etichetta)]); `qui(posto)` dice se il posto è il
    bando che si sta controllando: chi manca ma è sotto un altro bando si segnala una volta sola, per bando."""
    esito = {"gravi": [], "minori": []}
    if seconda is None:
        return esito
    pa = {nome_chiave(p["nominativo"]): p for p in prima}
    pb = {(p.get("chiave") or nome_chiave(p["nominativo"])): p for p in seconda}
    solo_a = [k for k in pa if k not in pb]
    solo_b = [k for k in pb if k not in pa]
    def somiglianza(x: str, y: str) -> float:
        """Sulle parole in ordine e così come sono scritte: «DELL'ANNA ADDA» / «DELL’ANNA NADA» va confrontato com'è."""
        return max(difflib.SequenceMatcher(None, x, y).ratio(),
                   difflib.SequenceMatcher(None, nome_scritto(pa[x]["nominativo"]), nome_scritto(pb[y]["nominativo"])).ratio())
    for k in list(solo_a):  # refusi: la stessa persona scritta in modo diverso; vale il nome della prima fonte
        simile = max(solo_b, key=lambda s: somiglianza(k, s), default=None)
        if simile and somiglianza(k, simile) >= SIMILI:
            esito["minori"].append(f"nome scritto diverso: «{pa[k]['nominativo']}» {nome_prima}, «{pb[simile]['nominativo']}» {nome_seconda}")
            solo_a.remove(k)
            solo_b.remove(simile)
    for lista, mappa, altrove, presente, assente in ((solo_b, pb, altrove_prima, nome_seconda, nome_prima),
                                                       (solo_a, pa, altrove_seconda, nome_prima, nome_seconda)):
        per_posto: dict[str, list[str]] = {}
        for k in lista:
            posti = _altrove(k, altrove, qui)
            if posti:
                per_posto.setdefault(posti[0], []).append(mappa[k]["nominativo"])
            else:
                esito["gravi"].append(f"{mappa[k]['nominativo']}: {presente} ma non {assente}")
        for posto, nomi in per_posto.items():
            chi = "1 persona" if len(nomi) == 1 else f"{len(nomi)} persone"
            esito["gravi"].append(f"{chi} {presente} per questo bando {'è' if len(nomi) == 1 else 'sono'} {assente} sotto «{posto}»: "
                                  f"bando o protocollo da verificare ({', '.join(nomi)})")
    if con_punteggi:
        for k, a in pa.items():
            b = pb.get(k)
            if not b:
                continue
            if b.get("posizione") not in (None, "") and a.get("posizione") not in (None, "") and str(_intero(b["posizione"])) != str(_intero(a["posizione"])):
                esito["minori"].append(f"{a['nominativo']}: posizione {_intero(a['posizione'])} {nome_prima}, {_intero(b['posizione'])} {nome_seconda}")
            x, y = punteggio_numero(a.get("punteggio")), punteggio_numero(b.get("punteggio"))
            if x is not None and y is not None and abs(x - y) > 0.001:
                esito["minori"].append(f"{a['nominativo']}: punteggio {a['punteggio']} {nome_prima}, {b['punteggio']} {nome_seconda}")
    return esito


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
