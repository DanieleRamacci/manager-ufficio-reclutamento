"""Verifica del file scorrimenti compilato dai colleghi e ricaricato dall'amministratore.

Decisione dell'utente del 2026-11-11: un subentro non è una difformità del monitoraggio; va solo indicato nel file
scorrimenti, e lo si controlla quando il file compilato viene ricaricato.
Spec 011 (scelta dell'utente del 2026-11-18): la verifica parte da ciò che risulta nel monitoraggio e controlla che ci
sia tutto, anche un intero foglio del gruppo di concorsi; confronta i nominativi con il file della segreteria. I
nominativi si leggono e restano nel database del monitoraggio, visibili solo agli amministratori e mai nei log.

I colleghi scrivono le cose a modo loro (nel file di agosto 2026 «subentro» stava nella colonna della struttura e il
bando era «367614» o «367.434 Codice 13 Roma»), quindi il subentro si cerca in tutta la riga e il bando anche senza punto.
Nel file c'è una riga per nominativo: le righe dello stesso bando e degli stessi protocolli formano un solo scorrimento.
"""
import io
import json
import re
from datetime import datetime, timezone

import openpyxl

from . import verifica_file
from .normalizza import norm_space, numero_bando, protocollo

_SUBENTRO = re.compile(r"subentr|rinunci", re.I)
_CESSAZIONE = re.compile(r"cessaz|6\s*mesi|sei\s*mesi", re.I)
_PROTOCOLLO = re.compile(r"(?<![\d/.-])0*(\d{5,7})(?![\d/.-])")


class FileNonValido(ValueError):
    pass


def _testo(valore) -> str:
    return norm_space(str(valore)) if valore is not None else ""


def _numero(valore) -> str | None:
    if isinstance(valore, (int, float)) and 100000 <= int(valore) <= 999999:
        cifre = str(int(valore))
        return f"{cifre[:3]}.{cifre[3:]}"
    testo = _testo(valore)
    m = re.match(r"^(\d{3})(\d{3})\b", testo)
    return numero_bando(testo) or (f"{m[1]}.{m[2]}" if m else None)


def tipo_di(testo: str | None) -> str | None:
    """La tipologia scritta nel file: subentro, cessazione dopo i 6 mesi, scorrimento; None se vuota."""
    if not testo or not testo.strip():
        return None
    return "subentro" if _SUBENTRO.search(testo) else "cessazione" if _CESSAZIONE.search(testo) else "scorrimento"


def leggi_file(contenuto: bytes) -> dict:
    """Le righe compilate di tutti i fogli e i nomi dei fogli (anche vuoti)."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contenuto), read_only=True, data_only=True)
    except Exception as e:
        raise FileNonValido("Il file non è un Excel leggibile") from e
    voci, fogli = [], []
    for ws in wb.worksheets:
        colonne = None
        for n, valori in enumerate(ws.iter_rows(values_only=True), start=1):
            valori = valori or ()
            if colonne is None:
                testi = [_testo(v).upper() for v in valori]
                if any("BANDO" in t and "SCORRERE" in t for t in testi):
                    colonne = {t: i for i, t in enumerate(testi) if t}
                    fogli.append(ws.title)
                continue

            def prendi(nome, colonne=colonne, valori=valori):
                return next((valori[i] for t, i in colonne.items() if nome in t and i < len(valori)), None)

            bando = prendi("BANDO")
            if bando in (None, "") or "TOTALE" in _testo(bando).upper():  # anche i subtotali «CODICE 13 ROMA TOTALE»
                continue
            leggibili = [_testo(valori[i]) for t, i in colonne.items() if "NOMINATIV" not in t and i < len(valori)]
            provvedimenti = " ".join(_testo(prendi(x)) for x in ("PROVVEDIMENTO DG", "PROVVEDIMENTO RECLUTAMENTO"))
            posizioni = prendi("POSIZION")
            voci.append({"foglio": ws.title, "riga": n, "bando": _testo(bando), "numero_bando": _numero(bando),
                         "protocolli": sorted({protocollo(p) for p in _PROTOCOLLO.findall(provvedimenti)}),
                         "tipologia": _testo(prendi("TIPOLOGIA")), "subentro": any(_SUBENTRO.search(t) for t in leggibili),
                         "nominativi": verifica_file.dividi_nominativi(prendi("NOMINATIV")),
                         "posizioni": int(posizioni) if isinstance(posizioni, (int, float)) or str(posizioni or "").strip().isdigit() else None})
    wb.close()
    if not voci:
        raise FileNonValido("Nel file non c'è nessuna riga compilata sotto «BANDO SU CUI SCORRERE»")
    return {"voci": voci, "fogli": fogli}


def leggi(contenuto: bytes) -> list[dict]:
    return leggi_file(contenuto)["voci"]


def salva(conn, mese: str, nome_file: str | None, voci: list[dict], utente: str | None,
          fogli: list[str] | None = None, contenuto: bytes | None = None) -> None:
    conn.execute("INSERT INTO scorrimenti_compilato (mese, nome_file, caricato_da, caricato_il, voci, fogli, contenuto) VALUES (?, ?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT(mese) DO UPDATE SET nome_file = excluded.nome_file, caricato_da = excluded.caricato_da, "
                 "caricato_il = excluded.caricato_il, voci = excluded.voci, fogli = excluded.fogli, contenuto = excluded.contenuto",
                 (mese, nome_file, utente, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), json.dumps(voci, ensure_ascii=False),
                  json.dumps(fogli) if fogli is not None else None, contenuto))


def caricato(conn, mese: str) -> dict | None:
    r = conn.execute("SELECT mese, nome_file, caricato_da, caricato_il, voci, fogli FROM scorrimenti_compilato WHERE mese = ?", (mese,)).fetchone()
    return {**dict(r), "voci": json.loads(r["voci"]), "fogli": json.loads(r["fogli"]) if r["fogli"] else None} if r else None


def contenuto_file(conn, mese: str) -> tuple[str, bytes] | None:
    r = conn.execute("SELECT nome_file, contenuto FROM scorrimenti_compilato WHERE mese = ?", (mese,)).fetchone()
    return (r["nome_file"], r["contenuto"]) if r and r["contenuto"] else None


def _protocolli_riga(riga: dict) -> set[str]:
    return {str(p) for p in (riga.get("protocollo"), *(c.get("protocollo") for c in (riga.get("fonti") or {}).values())) if p}


def _blocchi(voci: list[dict]) -> list[dict]:
    """Le righe dello stesso bando, foglio e protocolli sono un solo scorrimento (una riga per nominativo)."""
    blocchi: dict[tuple, dict] = {}
    for i, v in enumerate(voci):
        chiave = (v.get("numero_bando") or v["bando"], v["foglio"], tuple(v["protocolli"]))
        b = blocchi.setdefault(chiave, {"numero_bando": v.get("numero_bando"), "bando": v["bando"], "foglio": v["foglio"],
                                        "protocolli": list(v["protocolli"]), "indici": [], "righe": [], "tipologie": [],
                                        "nominativi": [], "posizioni": None, "subentro": False})
        b["indici"].append(i)
        b["righe"].append(v["riga"])
        if v.get("tipologia"):
            b["tipologie"].append(v["tipologia"])
        b["nominativi"] += v.get("nominativi") or []
        if v.get("posizioni") is not None:
            b["posizioni"] = (b["posizioni"] or 0) + v["posizioni"]
        b["subentro"] = b["subentro"] or bool(v.get("subentro"))
    return list(blocchi.values())


def _dove(b: dict) -> str:
    righe = b["righe"]
    return f"{b['foglio']}, riga {righe[0]}" if len(righe) == 1 else f"{b['foglio']}, righe {righe[0]}–{righe[-1]}"


def confronta(righe: list[dict], voci: list[dict], fogli: list[str] | None = None, persone: dict | None = None,
              profili_bandi: tuple[dict, dict] | None = None) -> dict:
    """Ogni scorrimento del monitoraggio con il suo blocco del file, e ogni blocco del file senza uno scorrimento.
    `fogli`: i fogli del file (per dire quale gruppo manca); `persone`: i nominativi della segreteria per (bando, protocollo)."""
    blocchi = _blocchi(voci)
    usati: set[int] = set()
    gruppi_file = {verifica_file.gruppo_di_foglio(f) for f in (fogli if fogli is not None else {v["foglio"] for v in voci})}
    atti, mancano_fogli = [], {}
    altrove_file: dict[str, list] = {}  # dove compare ogni persona nel file, per dire «è sotto un altro bando»
    for b in blocchi:
        for n in b["nominativi"]:
            altrove_file.setdefault(verifica_file.nome_chiave(n), []).append(
                ((b["numero_bando"], tuple(b["protocolli"])), f"{b['bando']}" + (f" (prot. {', '.join(b['protocolli'])})" if b["protocolli"] else "")))
    altrove_seg = verifica_file.dove_in_segreteria(persone)
    for r in righe:
        if r["atto"] != "scorrimento":
            continue
        gruppo = verifica_file.gruppo_della_riga(r, profili_bandi) if profili_bandi else None
        stessi = [i for i, b in enumerate(blocchi) if b["numero_bando"] and b["numero_bando"] == r.get("numero_bando")]
        per_protocollo = [i for i in stessi if _protocolli_riga(r) & set(blocchi[i]["protocolli"])]
        # un blocco senza protocollo vale per un solo scorrimento: quelli in più dello stesso bando risultano mancanti
        senza_protocollo = [i for i in stessi if not blocchi[i]["protocolli"] and i not in usati][:1]
        trovati = per_protocollo or senza_protocollo
        problemi = []
        if not trovati:  # bando scritto male nel file («36.434» per «367.434»): vale il protocollo, e lo si segnala
            trovati = [i for i, b in enumerate(blocchi) if i not in usati and _protocolli_riga(r) & set(b["protocolli"])]
            if trovati:
                problemi.append(f"nel file il bando è scritto «{blocchi[trovati[0]]['bando']}»")
        usati.update(trovati)
        tipologia = "; ".join(dict.fromkeys(t for i in trovati for t in blocchi[i]["tipologie"]))
        subentro_indicato = any(blocchi[i]["subentro"] for i in trovati)
        if not trovati:
            problemi.append("manca nel file")
            if gruppo and gruppo != verifica_file.ALTRO and gruppo not in gruppi_file:
                problemi.append(f"nel file manca il foglio {gruppo}")
                mancano_fogli[gruppo] = mancano_fogli.get(gruppo, 0) + 1
        else:
            if not tipologia:
                problemi.append("tipologia non indicata")
            if not any(blocchi[i]["protocolli"] for i in trovati):
                problemi.append("protocollo del provvedimento non indicato")
            if r.get("subentro_atteso") and not subentro_indicato:
                problemi.append("subentro non indicato")
            fogli_trovati = {verifica_file.gruppo_di_foglio(blocchi[i]["foglio"]) for i in trovati}
            if gruppo and gruppo != verifica_file.ALTRO and gruppo not in fogli_trovati:
                problemi.append(f"nel foglio {', '.join(blocchi[i]['foglio'] for i in trovati)} invece che nel foglio {gruppo}")
            nel_file = [{"nominativo": n} for i in trovati for n in blocchi[i]["nominativi"]]
            seg = None
            if persone is not None:
                seg = [p for prot in _protocolli_riga(r) for p in persone.get((r.get("numero_bando"), prot), [])] or None
                tipo_file = tipo_di(tipologia)
                tipi_seg = {verifica_file_tipo(p) for p in seg or [] if verifica_file_tipo(p)}
                if tipo_file and tipi_seg and tipo_file not in tipi_seg:
                    problemi.append(f"tipologia «{tipo_file}» nel file, «{', '.join(sorted(tipi_seg))}» nel file della segreteria")
                problemi += verifica_file.confronta_persone(nel_file, seg, altrove_file=altrove_file, altrove_segreteria=altrove_seg,
                                                            qui=verifica_file.qui_per(r.get("numero_bando"), _protocolli_riga(r)))
            dichiarate = sum(blocchi[i]["posizioni"] or 0 for i in trovati) if any(blocchi[i]["posizioni"] is not None for i in trovati) else None
            if dichiarate is not None and nel_file and dichiarate != len(nel_file):
                problemi.append(f"{dichiarate} posizioni dichiarate, {len(nel_file)} nominativi")
        atti.append({"chiave": r.get("chiave"), "codice": r.get("codice"), "numero_bando": r.get("numero_bando"), "protocollo": r.get("protocollo"),
                     "data": r.get("data"), "tipologia_bando": r.get("tipologia"), "gruppo": gruppo, "trovato": bool(trovati),
                     "righe_file": [_dove(blocchi[i]) for i in trovati], "tipologia": tipologia,
                     "subentro_atteso": bool(r.get("subentro_atteso")), "subentro_indicato": subentro_indicato,
                     "nominativi": len([n for i in trovati for n in blocchi[i]["nominativi"]]), "problemi": problemi,
                     "rdp": [{k: p.get(k) for k in ("nome", "cognome", "email")} for p in r.get("rdp") or []]})
    solo_file = [{"foglio": b["foglio"], "riga": b["righe"][0], "righe": _dove(b), "bando": b["bando"], "protocolli": b["protocolli"],
                  "nominativi": len(b["nominativi"])} for i, b in enumerate(blocchi) if i not in usati]
    return {"atti": atti, "solo_nel_file": solo_file, "fogli": sorted(gruppi_file - {verifica_file.ALTRO}),
            "fogli_mancanti": [{"gruppo": g, "nome": verifica_file.GRUPPI.get(g, g), "scorrimenti": n} for g, n in mancano_fogli.items()],
            "allineato": not solo_file and all(not a["problemi"] for a in atti)}


def verifica_file_tipo(persona: dict) -> str | None:
    """La tipologia di una persona nel file della segreteria."""
    return tipo_di(str(persona.get("tipologia") or "")) or ({"subentro": "subentro", "ordinario": "scorrimento"}.get(persona.get("sottotipo") or ""))


def per_riga(conn, mese: str, righe: list[dict]) -> None:
    """Aggiunge a ogni scorrimento l'esito del file compilato, se è stato caricato."""
    file = caricato(conn, mese)
    if not file:
        return
    esito = confronta(righe, file["voci"], file["fogli"])
    per_chiave = {(a["chiave"], a["protocollo"], a["data"]): a for a in esito["atti"]}
    for r in righe:
        a = per_chiave.get((r.get("chiave"), r.get("protocollo"), r.get("data"))) if r["atto"] == "scorrimento" else None
        if a:
            r["file_scorrimenti"] = {k: a[k] for k in ("trovato", "tipologia", "subentro_indicato", "righe_file")}
