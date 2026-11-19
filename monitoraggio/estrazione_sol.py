"""Estrazione delle graduatorie da Selezioni Online (spec 011): l'export «Punteggi» (.xls, o .xlsx se risalvato).

Un foglio, una riga per candidato, le stesse colonne del foglio graduatorie che il sistema genera (punteggi.INTESTAZIONI_EXCEL)
più Matricola e Data Ultima Modifica. Si confronta con le graduatorie del monitoraggio partendo da ciò che risulta a noi, e
per persona con il foglio Graduatorie del file della segreteria; poi compila il file graduatorie del mese.
Contiene dati personali: resta nel database del monitoraggio, solo per gli amministratori, mai nei log (FR-005).
"""
import io
import json
import zipfile
from datetime import datetime, timezone

from . import verifica_file
from .normalizza import data_iso, norm_space, numero_bando, protocollo
from .punteggi import INTESTAZIONI_EXCEL

COLONNE = {  # chiave interna -> intestazione dell'export (confronto senza spazi né maiuscole)
    "codice_bando": "Codice bando", "profilo": "Profilo/Livello", "cognome": "Cognome", "nome": "Nome",
    "punteggio": "Totale Punteggi", "posizione": "Graduatoria", "esito": "Esito", "note": "Note",
    "data_graduatoria": "Data Protocollo Graduatoria", "protocollo_graduatoria": "Numero Protocollo Graduatoria",
    "data_assunzione": "Data Protocollo Assunzione Idoneo", "protocollo_assunzione": "Numero Protocollo Assunzione Idoneo",
}
OBBLIGATORIE = ("Codice bando", "Cognome", "Nome", "Totale Punteggi", "Numero Protocollo Graduatoria")
_DATE = {"Data di nascita", "Data Protocollo Graduatoria", "Data Protocollo Assunzione Idoneo", "Data Ultima Modifica"}


class FileNonValido(ValueError):
    pass


def _n(testo) -> str:
    return "".join(str(testo or "").lower().split())


def _righe_xls(contenuto: bytes) -> list[list]:
    import xlrd  # solo per l'export .xls di Selezioni Online

    try:
        wb = xlrd.open_workbook(file_contents=contenuto)
    except Exception as e:
        raise FileNonValido("Il file non è un Excel leggibile") from e
    sh = wb.sheet_by_index(0)
    righe = []
    for i in range(sh.nrows):
        riga = []
        for j in range(sh.ncols):
            c = sh.cell(i, j)
            if c.ctype == xlrd.XL_CELL_DATE:
                riga.append(xlrd.xldate_as_datetime(c.value, wb.datemode))
            elif c.ctype == xlrd.XL_CELL_NUMBER and float(c.value).is_integer():
                riga.append(int(c.value))
            else:
                riga.append(c.value)
        righe.append(riga)
    return righe


def _righe_xlsx(contenuto: bytes) -> list[list]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(contenuto), read_only=True, data_only=True)
    except Exception as e:
        raise FileNonValido("Il file non è un Excel leggibile") from e
    righe = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    wb.close()
    return righe


def _testo(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return norm_space(str(v))


def leggi(contenuto: bytes) -> list[dict]:
    righe = _righe_xlsx(contenuto) if zipfile.is_zipfile(io.BytesIO(contenuto)) else _righe_xls(contenuto)
    testa = next((i for i, r in enumerate(righe[:20]) if any(_n(v) == _n("Codice bando") for v in r)), None)
    if testa is None:
        raise FileNonValido("Non è l'export «Punteggi» di Selezioni Online: manca la colonna «Codice bando»")
    intestazioni = [_testo(v) for v in righe[testa]]
    indice = {_n(h): i for i, h in enumerate(intestazioni) if h}
    mancanti = [h for h in OBBLIGATORIE if _n(h) not in indice]
    if mancanti:
        raise FileNonValido("Mancano le colonne: " + ", ".join(mancanti))
    lette = []
    for numero, r in enumerate(righe[testa + 1:], start=testa + 2):
        valore = lambda h, r=r: r[indice[_n(h)]] if _n(h) in indice and indice[_n(h)] < len(r) else None  # noqa: E731
        if not _testo(valore("Codice bando")):
            continue
        colonne = {h: (_testo(valore(h)) if h in _DATE else valore(h) if isinstance(valore(h), (int, float)) else _testo(valore(h)))
                   for h in INTESTAZIONI_EXCEL}
        voce = {k: _testo(valore(h)) for k, h in COLONNE.items()}
        voce.update({"riga": numero, "numero_bando": numero_bando(voce["codice_bando"]),
                     "protocollo_graduatoria": protocollo(voce["protocollo_graduatoria"]) if voce["protocollo_graduatoria"] else "",
                     "protocollo_assunzione": protocollo(voce["protocollo_assunzione"]) if voce["protocollo_assunzione"] else "",
                     "data_graduatoria": data_iso(voce["data_graduatoria"]) or "", "data_assunzione": data_iso(voce["data_assunzione"]) or "",
                     "nominativo": f"{voce['cognome']} {voce['nome']}".strip(), "colonne": colonne})
        lette.append(voce)
    if not lette:
        raise FileNonValido("Nell'export non c'è nessun candidato")
    return lette


TABELLE = {"concorsi": "estrazione_graduatorie", "mobilita": "estrazione_mobilita"}  # due export distinti: concorsi e mobilità


def salva(conn, mese: str, nome_file: str | None, righe: list[dict], utente: str | None, tipo: str = "concorsi") -> None:
    conn.execute(f"INSERT INTO {TABELLE[tipo]} (mese, nome_file, caricato_da, caricato_il, righe) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(mese) DO UPDATE SET nome_file = excluded.nome_file, caricato_da = excluded.caricato_da, "
                 "caricato_il = excluded.caricato_il, righe = excluded.righe",
                 (mese, nome_file, utente, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), json.dumps(righe, ensure_ascii=False, default=str)))


def caricata(conn, mese: str, tipo: str = "concorsi") -> dict | None:
    r = conn.execute(f"SELECT * FROM {TABELLE[tipo]} WHERE mese = ?", (mese,)).fetchone()
    return {**dict(r), "righe": json.loads(r["righe"])} if r else None


def tutte(conn, mese: str) -> list[dict]:
    """Le righe delle due estrazioni insieme (concorsi e mobilità): servono a confrontare tutte le graduatorie del mese."""
    return [v for tipo in TABELLE for v in ((caricata(conn, mese, tipo) or {}).get("righe") or [])]


def _protocolli_riga(riga: dict) -> set[str]:
    return {str(p) for p in (riga.get("protocollo"), *(c.get("protocollo") for c in (riga.get("fonti") or {}).values())) if p}


def graduatorie(righe_estrazione: list[dict]) -> dict[tuple, dict]:
    """Le graduatorie dell'estrazione per (numero bando, protocollo della graduatoria): solo chi è in graduatoria."""
    gruppi: dict[tuple, dict] = {}
    for v in righe_estrazione:
        if not v["protocollo_graduatoria"]:
            continue
        g = gruppi.setdefault((v["numero_bando"], v["protocollo_graduatoria"]), {
            "numero_bando": v["numero_bando"], "protocollo": v["protocollo_graduatoria"], "data": v["data_graduatoria"],
            "codici": [], "profilo": v["profilo"], "candidati": []})
        if v["codice_bando"] not in g["codici"]:
            g["codici"].append(v["codice_bando"])
        g["candidati"].append(v)
    return gruppi


NOMI_FONTI = {"sol": "Selezioni Online", "urp": "URP", "segreteria": "file della segreteria"}


def _dove_risulta(r: dict) -> str:
    fonti = [NOMI_FONTI[f] for f in ("segreteria", "urp", "sol") if ((r.get("fonti") or {}).get(f) or {}).get("stato") == "presente"]
    return f" (risulta: {', '.join(fonti)})" if fonti else ""


def confronta(righe: list[dict], righe_estrazione: list[dict], dal: str, al: str, persone: dict | None = None,
              profili_bandi: tuple[dict, dict] | None = None) -> dict:
    """Ogni graduatoria del monitoraggio con quella dell'estrazione, e ogni graduatoria dell'estrazione del periodo senza
    una graduatoria del monitoraggio. Le graduatorie dell'estrazione con data fuori dal periodo si contano a parte.
    I nomi veri sono quelli di Selezioni Online (scelta dell'utente del 2026-11-18): la segreteria si confronta con l'estrazione."""
    gruppi = graduatorie(righe_estrazione)
    nel_periodo = {k: g for k, g in gruppi.items() if not g["data"] or dal <= g["data"] <= al}
    usati: set[tuple] = set()
    gruppi_estrazione = {verifica_file.gruppo_di_profilo(v["profilo"]) for v in righe_estrazione}
    atti, mancano_gruppi = [], {}
    altrove_sol: dict[str, list] = {}  # dove compare ogni persona nell'estrazione, per dire «è sotto un altro bando»
    for v in righe_estrazione:
        if v["protocollo_graduatoria"]:
            altrove_sol.setdefault(verifica_file.nome_chiave(v["nominativo"]), []).append(
                ((v["numero_bando"], v["protocollo_graduatoria"]), f"{v['codice_bando']} (prot. {v['protocollo_graduatoria']})"))
    altrove_seg = verifica_file.dove_in_segreteria(persone)
    for r in righe:
        if r["atto"] != "graduatoria":
            continue
        gruppo = verifica_file.gruppo_della_riga(r, profili_bandi) if profili_bandi else None
        trovate = [k for k in gruppi if k[0] == r.get("numero_bando") and k[1] in _protocolli_riga(r)]
        usati.update(trovate)
        gravi, minori = [], []
        candidati = [c for k in trovate for c in gruppi[k]["candidati"]]
        seg = [p for prot in _protocolli_riga(r) for p in (persone or {}).get((r.get("numero_bando"), prot), [])] or None
        if not trovate:
            gravi.append(f"manca nell'estrazione da Selezioni Online{_dove_risulta(r)}")
            if gruppo and gruppo != verifica_file.ALTRO and gruppo not in gruppi_estrazione:
                gravi.append(f"nell'estrazione non c'è nessuna graduatoria {gruppo}")
                mancano_gruppi[gruppo] = mancano_gruppi.get(gruppo, 0) + 1
        elif persone is not None:
            esito = verifica_file.confronta_persone(
                [{"nominativo": c["nominativo"], "posizione": c["posizione"], "punteggio": c["punteggio"]} for c in candidati], seg,
                "su Selezioni Online", "nel file della segreteria", con_punteggi=True, altrove_prima=altrove_sol, altrove_seconda=altrove_seg,
                qui=verifica_file.qui_per(r.get("numero_bando"), _protocolli_riga(r)))
            gravi += esito["gravi"]
            minori += esito["minori"]
        atti.append({"chiave": r.get("chiave"), "codice": r.get("codice"), "numero_bando": r.get("numero_bando"), "protocollo": r.get("protocollo"),
                     "data": r.get("data"), "tipologia_bando": r.get("tipologia"), "gruppo": gruppo, "trovato": bool(trovate),
                     "candidati": len(candidati), "persone_segreteria": len(seg or []), "gravi": gravi, "minori": minori, "problemi": gravi,
                     "rdp": [{k: p.get(k) for k in ("nome", "cognome", "email")} for p in r.get("rdp") or []]})
    solo = [{"bando": ", ".join(g["codici"]), "numero_bando": g["numero_bando"], "protocollo": g["protocollo"], "data": g["data"],
             "candidati": len(g["candidati"]), "righe": f"righe {min(c['riga'] for c in g['candidati'])}–{max(c['riga'] for c in g['candidati'])}"}
            for k, g in nel_periodo.items() if k not in usati]
    return {"atti": atti, "solo_nel_file": solo, "fuori_periodo": len([k for k in gruppi if k not in nel_periodo and k not in usati]),
            "gruppi": sorted(gruppi_estrazione - {verifica_file.ALTRO}),
            "gruppi_mancanti": [{"gruppo": g, "nome": verifica_file.GRUPPI.get(g, g), "graduatorie": n} for g, n in mancano_gruppi.items()],
            "senza_graduatoria": len([v for v in righe_estrazione if not v["protocollo_graduatoria"]]),
            "allineato": not solo and all(not a["gravi"] for a in atti)}


def scorrimenti_sol(righe_estrazione: list[dict]) -> dict[str, list[dict]]:
    """Gli assunti da scorrimento su Selezioni Online (esito S con protocollo di assunzione idoneo), per protocollo."""
    per: dict[str, list[dict]] = {}
    for v in righe_estrazione:
        if v["protocollo_assunzione"]:
            per.setdefault(v["protocollo_assunzione"], []).append({"nominativo": v["nominativo"], "codice_bando": v["codice_bando"],
                                                                   "numero_bando": v["numero_bando"], "data": v["data_assunzione"]})
    return per


def righe_excel(righe_estrazione: list[dict], dal: str, al: str, mobilita: set[str]) -> tuple[list, list]:
    """Le righe del file graduatorie: i candidati dei bandi con una graduatoria nel periodo, per gruppo di concorsi, bando e
    punteggio decrescente. Restano anche i candidati non entrati in graduatoria (senza protocollo né esito), dopo gli altri dello
    stesso bando, come nell'export di Selezioni Online (scelta dell'utente del 2026-11-19).
    `mobilita`: numeri di bando di mobilità o comando, che vanno nel foglio a parte."""
    ordine = {g: i for i, g in enumerate([*verifica_file.GRUPPI, verifica_file.ALTRO])}
    nel_periodo = lambda v: v["protocollo_graduatoria"] and (not v["data_graduatoria"] or dal <= v["data_graduatoria"] <= al)  # noqa: E731
    con_graduatoria = {v["codice_bando"] for v in righe_estrazione if nel_periodo(v)}
    scelte = [v for v in righe_estrazione if nel_periodo(v) or (not v["protocollo_graduatoria"] and v["codice_bando"] in con_graduatoria)]
    scelte.sort(key=lambda v: (ordine[verifica_file.gruppo_di_profilo(v["profilo"])], v["codice_bando"], not v["protocollo_graduatoria"],
                               -(verifica_file.punteggio_numero(v["punteggio"]) or 0), verifica_file.punteggio_numero(v["posizione"]) or 9999))
    riga = lambda v: ([v["colonne"].get(h) for h in INTESTAZIONI_EXCEL], False)  # noqa: E731
    return ([riga(v) for v in scelte if v["numero_bando"] not in mobilita], [riga(v) for v in scelte if v["numero_bando"] in mobilita])
