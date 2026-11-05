"""Tabella unificata degli atti (spec 001 FR-021, spec 002 FR-013): ogni bando pubblicato,
graduatoria, scorrimento o rettifica compare una sola volta, con lo stato su ogni fonte
(Selezioni Online, URP, file della segreteria).
"""
from collections import defaultdict

from . import config, punteggi, referenti, segreteria
from .collegamento import _da_confrontare
from .fonti.sol import url_punteggi
from .normalizza import codice_sotto

FONTI = ("sol", "urp", "segreteria")
PRESENTE, MANCANTE, NON_APPLICABILE, NON_CARICATO = "presente", "mancante", "non_applicabile", "non_caricato"
IN_ATTESA = "in_attesa"


def _voce(categoria, data, protocollo, url=None, sottotipo=None, sottotipo_origine=None, titolo=None, extra=None) -> dict:
    return {"categoria": categoria, "data": data, "protocollo": protocollo, "url": url, "sottotipo": sottotipo,
            "sottotipo_origine": sottotipo_origine, "titolo": titolo, **(extra or {})}


def _unisci(per_fonte: dict[str, dict[tuple, dict]]) -> list[dict[str, dict]]:
    """Unisce le voci delle fonti per (categoria, protocollo); poi accorpa le voci della stessa
    categoria e data presenti su fonti diverse con protocolli diversi (stesso atto, protocollo
    sbagliato su una fonte)."""
    per_chiave: dict[tuple, dict[str, dict]] = {}
    for fonte, voci in per_fonte.items():
        for chiave, voce in voci.items():
            per_chiave.setdefault(chiave, {})[fonte] = voce
    unite: list[dict[str, dict]] = []
    for gruppo in per_chiave.values():
        qualsiasi = next(iter(gruppo.values()))
        bersaglio = next((u for u in unite
                          if not set(u) & set(gruppo)
                          and next(iter(u.values()))["categoria"] == qualsiasi["categoria"]
                          and next(iter(u.values()))["data"] == qualsiasi["data"] and qualsiasi["data"]), None)
        if bersaglio is not None:
            bersaglio.update(gruppo)
        else:
            unite.append(dict(gruppo))
    return unite


def _periodo_segreteria(atti_seg: list[dict]) -> dict[str, str]:
    """Data più vecchia per categoria nel file: prima di questa il file non copre (FR-014)."""
    periodo: dict[str, str] = {}
    for a in atti_seg:
        if a["data"] and a["in_ambito"]:
            periodo[a["categoria"]] = min(periodo.get(a["categoria"], a["data"]), a["data"])
    return periodo


def fonti_in_attesa(conn) -> list[dict]:
    """SOL e URP la cui ultima raccolta non è conclusa: finché ce n'è una, le fonti non si possono confrontare."""
    attesa = []
    for fonte, nome in (("sol", "Selezioni Online"), ("urp", "URP")):
        ultima = conn.execute("SELECT esito FROM raccolta WHERE fonte = ? ORDER BY id DESC LIMIT 1", (fonte,)).fetchone()
        if not ultima:
            attesa.append({"fonte": fonte, "nome": nome, "motivo": "non ancora eseguita"})
        elif ultima["esito"] == "in_corso":
            attesa.append({"fonte": fonte, "nome": nome, "motivo": "in corso"})
        elif ultima["esito"] not in ("completata", "completata_con_errori"):
            attesa.append({"fonte": fonte, "nome": nome, "motivo": "non conclusa, da rilanciare"})
    return attesa


def testo_attesa(attesa: list[dict]) -> str:
    voci = ", ".join(f"{f['nome']} ({f['motivo']})" for f in attesa)
    return f"Difformità sospese: le fonti non si possono ancora confrontare. Aggiornamento da concludere: {voci}."


def url_file_segreteria(atto: int | None = None, foglio: str | None = None) -> str:
    return f"/monitoraggio/segreteria?atto={atto}" if atto else f"/monitoraggio/segreteria?foglio={foglio or 'bandi'}"


FOGLIO_SEGRETERIA = {"bando": "bandi", "graduatoria": "graduatorie", "scorrimento": "scorrimento"}


def elenco_atti(conn, dal: str | None = None, al: str | None = None) -> list[dict]:
    dal = dal or config.monitoraggio_dal().isoformat()
    al = al or "9999-12-31"
    bandi = {b["id"]: dict(b) for b in conn.execute("SELECT * FROM bando WHERE stato_collegamento IS NOT NULL")}
    per_numero = {}
    for b in bandi.values():
        if b["numero_bando"]:
            per_numero.setdefault(b["numero_bando"], b["id"])
    schede = defaultdict(dict)
    sol_per_codice = defaultdict(dict)  # bando -> codice di sotto-bando -> scheda SOL di quel codice
    for s in conn.execute("SELECT * FROM scheda WHERE presente = 1 AND bando_id IS NOT NULL ORDER BY codice_sotto IS NOT NULL, id"):
        schede[s["bando_id"]].setdefault(s["fonte"], s)  # scheda principale per fonte (senza sotto-bando, se c'è)
        if s["fonte"] == "sol" and s["codice_sotto"]:
            sol_per_codice[s["bando_id"]].setdefault(s["codice_sotto"], s)

    # --- URP e SOL: documenti per bando
    voci = defaultdict(lambda: defaultdict(dict))  # chiave bando -> fonte -> (categoria, protocollo) -> voce
    for d in conn.execute(
            "SELECT s.bando_id, s.fonte, s.url AS url_scheda, s.codice_sotto AS sotto_scheda, d.* "
            "FROM documento d JOIN scheda s ON s.id = d.scheda_id "
            "WHERE d.presente = 1 AND s.presente = 1 AND d.protocollo IS NOT NULL "
            "AND d.categoria IN ('graduatoria', 'scorrimento', 'rettifica') AND d.data_protocollo BETWEEN ? AND ?",
            (dal, al)):
        if d["bando_id"] in bandi and _da_confrontare(d):
            url = d["url_scheda"]  # pagina del bando (o del sotto-bando) con tutti gli allegati
            # codice di sotto-bando: dalla scheda SOL o, per la pagina unica di URP, dal titolo ("Cod. 13")
            sotto = d["sotto_scheda"] or codice_sotto(d["titolo"])
            voci[d["bando_id"]][d["fonte"]].setdefault((d["categoria"], d["protocollo"]), _voce(
                d["categoria"], d["data_protocollo"], d["protocollo"], url, d["sottotipo"],
                "titolo" if d["sottotipo"] else None, d["titolo"], {"codice_sotto": sotto, "url_documento": d["url"]}))

    # --- file della segreteria (versione in uso)
    versione = segreteria.versione_in_uso(conn)
    atti_seg = segreteria.atti_versione(conn, versione["id"]) if versione else []
    periodo = _periodo_segreteria(atti_seg)
    bandi_seg: dict = {}         # chiave bando -> atto "bando" del file
    solo_file: dict = {}         # numero bando senza bando su URP/SOL -> dati per la riga
    for a in atti_seg:
        if not a["in_ambito"] or not a["data"] or not (dal <= a["data"] <= al) and a["categoria"] != "bando":
            continue
        chiave_bando = per_numero.get(a["numero_bando"]) or f"file:{a['numero_bando']}"
        if isinstance(chiave_bando, str):
            solo_file.setdefault(chiave_bando, a)
        if a["categoria"] == "bando":
            bandi_seg.setdefault(chiave_bando, a)
            continue
        extra = {"persone": a["persone"], "protocollo_privato": a["protocollo_privato"], "codice_sotto": a["codice_sotto"]}
        voci[chiave_bando]["segreteria"].setdefault((a["categoria"], a["protocollo"]), _voce(
            a["categoria"], a["data"], a["protocollo"], url_file_segreteria(atto=a["id"]), a["sottotipo"], "segreteria",
            a["titolo"], extra))

    righe = []

    def cella(fonte, voce, applicabile_urp, categoria, data):
        if voce is not None:
            return {"stato": PRESENTE, "url": voce.get("url"), "protocollo": voce.get("protocollo")}
        if fonte == "segreteria":
            if not versione:
                return {"stato": NON_CARICATO}
            inizio = periodo.get(categoria)
            if categoria == "rettifica" or not inizio or (data or "") < inizio:
                return {"stato": NON_APPLICABILE}
        if fonte == "urp" and not applicabile_urp:
            return {"stato": NON_APPLICABILE}
        return {"stato": MANCANTE}

    rdp = referenti.referenti_per_bando(conn)
    rdp_scheda = referenti.referenti_per_scheda(conn)
    verifiche = punteggi.ultime_verifiche(conn)

    def scheda_sol(chiave, sotto):
        """Scheda SOL del codice del sotto-bando, altrimenti la principale."""
        s = sol_per_codice.get(chiave, {}).get(sotto) if sotto else None
        return s if s is not None else schede.get(chiave, {}).get("sol")

    def punteggi_riga(s):
        """Ultima verifica dei punteggi della scheda SOL."""
        v = verifiche.get(s["id"]) if s is not None else None
        if not v:
            return None
        return {**{k: v[k] for k in ("domande", "con_punteggi", "esito", "verificato_il")},
                "scheda_id": s["id"], "candidati": punteggi.candidati(s["id"]) is not None}

    def difformita_sol(r, s):
        """Difformità di SOL rispetto alle fonti, dall'ultima verifica dei punteggi (graduatorie e scorrimenti)."""
        v = verifiche.get(s["id"]) if s is not None else None
        if not v:
            return []
        if r["atto"] == "graduatoria":
            return punteggi.difformita(v)
        sol = v.get("scorrimenti_sol")
        stato = punteggi.stato_scorrimento({"data": r["data"], "protocolli": set(r.get("_protocolli") or [])}, sol)
        if stato["registrato"] is False:
            if r.get("fonti", {}).get("sol", {}).get("stato") == PRESENTE:
                return ["provvedimento di assunzione idoneo presente tra gli allegati SOL ma non risulta nei punteggi: nessun candidato S con questo protocollo"]
            return ["provvedimento di assunzione idoneo non presente tra gli allegati SOL e nessun candidato S con questo protocollo nei punteggi"]
        d = []
        if stato["data_diversa"]:
            d.append("data assunzione idoneo diversa su SOL")
        if sol and sol["protocolli"].get("", {}).get("n"):
            d.append(f"protocollo assunzione idoneo non valorizzato su SOL ({sol['protocolli']['']['n']} candidati S)")
        return d

    def persone(lista):
        return [{k: r[k] for k in ("nome", "cognome", "email")} for r in lista]

    def rdp_riga(chiave, sotto):
        """RdP del codice specifico se l'atto è di un sotto-bando, altrimenti della scheda principale."""
        s = sol_per_codice.get(chiave, {}).get(sotto) if sotto else None
        if s is not None and rdp_scheda.get(s["id"]):
            return persone(rdp_scheda[s["id"]]), "codice"
        principale = schede.get(chiave, {}).get("sol")
        if principale is not None and rdp_scheda.get(principale["id"]):
            return persone(rdp_scheda[principale["id"]]), "bando"
        return persone(rdp.get(chiave, [])), "tutti i codici"

    def link_codice(chiave, sotto):
        s = sol_per_codice.get(chiave, {}).get(sotto) if sotto else None
        return s["url"] if s is not None else None
    # schede SOL con la data della graduatoria ma nessun documento di graduatoria tra gli allegati pubblici
    con_graduatoria = {r[0] for r in conn.execute(
        "SELECT DISTINCT scheda_id FROM documento WHERE presente = 1 AND categoria = 'graduatoria'")}
    senza_documento = defaultdict(list)
    for s in conn.execute(
            "SELECT * FROM scheda WHERE fonte = 'sol' AND presente = 1 AND bando_id IS NOT NULL "
            "AND data_pubbl_graduatoria BETWEEN ? AND ?", (dal, al)):
        if s["id"] not in con_graduatoria:
            senza_documento[s["bando_id"]].append(s)
    chiavi_bando = list(bandi) + [k for k in solo_file if k not in bandi]
    for chiave in chiavi_bando:
        b = bandi.get(chiave)
        if b:
            base = {"bando_id": chiave, "numero_bando": b["numero_bando"], "codice": b["codice"],
                    "tipologia": b["tipologia"], "titolo_bando": b["titolo"], "stato_collegamento": b["stato_collegamento"]}
            urp_ok = b["stato_collegamento"] != "fuori_periodo_urp"
        else:
            a = solo_file[chiave]
            base = {"bando_id": None, "numero_bando": a["numero_bando"], "codice": a["codice_originale"],
                    "tipologia": None, "titolo_bando": a["titolo"], "stato_collegamento": "solo_segreteria"}
            urp_ok = True
        sch = schede.get(chiave, {})

        # riga "bando pubblicato"
        seg_bando = bandi_seg.get(chiave)
        data_bando = (b["data_pubblicazione"] if b else None) or (seg_bando["data"] if seg_bando else None)
        if (b or seg_bando) and dal <= (data_bando or "") <= al:
            voce_seg = _voce("bando", seg_bando["data"], seg_bando["protocollo"],
                             url_file_segreteria(atto=seg_bando["id"])) if seg_bando else None
            note = []
            if seg_bando and "urp" in sch and seg_bando["protocollo"] and sch["urp"]["protocollo"] \
                    and seg_bando["protocollo"] != sch["urp"]["protocollo"]:
                note.append(f"protocollo diverso: URP {sch['urp']['protocollo']}, file {seg_bando['protocollo']}")
            righe.append({**base, "atto": "bando", "sottotipo": None, "sottotipo_origine": None, "codice_sotto": None,
                          "data": data_bando,
                          "protocollo": (sch["urp"]["protocollo"] if "urp" in sch else None) or (seg_bando or {}).get("protocollo"),
                          "titolo": base["titolo_bando"], "persone": None,
                          "fonti": {
                              "sol": cella("sol", {"url": sch["sol"]["url"]} if "sol" in sch else None, urp_ok, "bando", data_bando),
                              "urp": cella("urp", {"url": sch["urp"]["url"], "protocollo": sch["urp"]["protocollo"]}
                                           if "urp" in sch else None, urp_ok, "bando", data_bando),
                              "segreteria": cella("segreteria", voce_seg, urp_ok, "bando", data_bando)},
                          "note": note})

        # graduatorie con la data su SOL ma senza documento pubblico
        for s in senza_documento.get(chiave, []):
            righe.append({**base, "atto": "graduatoria", "sottotipo": None, "sottotipo_origine": None,
                          "codice_sotto": s["codice_sotto"], "data": s["data_pubbl_graduatoria"], "protocollo": None,
                          "titolo": s["codice_originale"], "persone": None,
                          "fonti": {"sol": {"stato": MANCANTE, "url": s["url"]}, "urp": {"stato": NON_APPLICABILE},
                                    "segreteria": {"stato": NON_APPLICABILE}},
                          "note": ["data graduatoria su SOL senza documento pubblico"]})

        # documenti
        for gruppo in _unisci(voci.get(chiave, {})):
            principale = gruppo.get("segreteria") or gruppo.get("sol") or gruppo.get("urp")
            categoria, data = principale["categoria"], principale["data"]
            note = []
            protocolli = {f: v["protocollo"] for f, v in gruppo.items()}
            if len(set(protocolli.values())) > 1:
                nomi = {"urp": "URP", "sol": "SOL", "segreteria": "file"}
                note.append("protocollo diverso: " + ", ".join(f"{nomi[f]} {protocolli[f]}" for f in FONTI if f in protocolli))
            sottotipo, origine = None, None
            if categoria == "scorrimento":
                dal_titolo = next((v["sottotipo"] for f, v in gruppo.items()
                                   if f != "segreteria" and v["sottotipo"] and v["sottotipo"] != "non_specificato"), None)
                if "segreteria" in gruppo:
                    sottotipo, origine = gruppo["segreteria"]["sottotipo"], "segreteria"
                    if sottotipo is None:
                        note.append("tipologia da completare nel file")
                    elif dal_titolo and (dal_titolo == "subentro") != (sottotipo == "subentro"):
                        note.append(f"sottotipo diverso: file {sottotipo}, titolo {dal_titolo}")
                else:
                    sottotipo = dal_titolo or "non_specificato"
                    origine = "titolo"
            righe.append({**base, "atto": categoria, "sottotipo": sottotipo, "sottotipo_origine": origine,
                          "codice_sotto": next((gruppo[f]["codice_sotto"] for f in FONTI
                                                if f in gruppo and gruppo[f].get("codice_sotto")), None),
                          "data": data,
                          "protocollo": principale["protocollo"], "titolo": principale["titolo"],
                          "persone": gruppo.get("segreteria", {}).get("persone"),
                          "fonti": {f: cella(f, gruppo.get(f), urp_ok, categoria, data) for f in FONTI},
                          "note": note, "_protocolli": [p for p in protocolli.values() if p]})

    for r in righe:
        if r["bando_id"] is not None:
            r["rdp"], r["rdp_origine"] = rdp_riga(r["bando_id"], r.get("codice_sotto"))
            r["link_codice"] = link_codice(r["bando_id"], r.get("codice_sotto"))
            sotto = sol_per_codice.get(r["bando_id"], {}).get(r.get("codice_sotto")) if r.get("codice_sotto") else None
            if sotto is not None:
                r["codice"] = sotto["codice_originale"]  # es. "367.434 CA - TRIESTE Codice 05", come su SOL
            s = scheda_sol(r["bando_id"], r.get("codice_sotto"))
            if r["atto"] in ("graduatoria", "scorrimento") and s is not None:
                r["punteggi"] = punteggi_riga(s)
                r["url_punteggi"] = url_punteggi(s["id_esterno"])
                r["note"] += difformita_sol(r, s)
            else:
                r["punteggi"], r["url_punteggi"] = None, None
            # celle senza documento: link alla pagina della fonte, per verificare se l'atto manca davvero
            if not r["fonti"]["sol"].get("url"):
                principale = schede.get(r["bando_id"], {}).get("sol")
                r["fonti"]["sol"]["url"] = r["link_codice"] or (principale["url"] if principale is not None else None)
            if not r["fonti"]["urp"].get("url") and "urp" in schede.get(r["bando_id"], {}):
                r["fonti"]["urp"]["url"] = schede[r["bando_id"]]["urp"]["url"]
        else:
            r["rdp"], r["rdp_origine"], r["link_codice"], r["punteggi"], r["url_punteggi"] = [], None, None, None, None
        if versione and not r["fonti"]["segreteria"].get("url") and r["atto"] in FOGLIO_SEGRETERIA:
            r["fonti"]["segreteria"]["url"] = url_file_segreteria(foglio=FOGLIO_SEGRETERIA[r["atto"]])
        r.pop("_protocolli", None)
        r["incompleto"] = any(c["stato"] == MANCANTE for c in r["fonti"].values())
        r["difforme"] = r["incompleto"] or bool(r["note"])
        r["protocollo_diverso"] = any(n.startswith("protocollo diverso") for n in r["note"])
    attesa = {f["fonte"] for f in fonti_in_attesa(conn)}
    if attesa:  # con una fonte incompleta un atto "mancante" non vuol dire niente
        for r in righe:
            for chiave, cella_fonte in r["fonti"].items():
                if chiave in attesa or cella_fonte["stato"] == MANCANTE:
                    cella_fonte["stato"] = IN_ATTESA
            r.update(note=[], incompleto=False, difforme=False, protocollo_diverso=False)
    righe.sort(key=lambda r: (r["data"] or "", r["codice"] or ""), reverse=True)
    return righe
