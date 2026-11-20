"""Tabella unificata degli atti (spec 001 FR-021, spec 002 FR-013): ogni bando pubblicato,
graduatoria, scorrimento o rettifica compare una sola volta, con lo stato su ogni fonte
(Selezioni Online, URP, file della segreteria).
"""
import json
from collections import defaultdict
from datetime import date, timedelta

from . import config, profili, protocollo_email, punteggi, referenti, segreteria
from .collegamento import _da_confrontare
from . import sedi
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
# spec 012: atti che il file della segreteria non ha (ancora): la colonna segreteria non è una difformità
FUORI_FILE_SEGRETERIA = ("deserto", "revocato")
CATEGORIE_ATTI = ("graduatoria", "scorrimento", "rettifica", "deserto", "revocato")
ESITI = ("graduatoria", "scorrimento", "deserto", "revocato")  # un bando con uno di questi atti ha un esito
MESI_SENZA_ESITO = 12
TIPOLOGIE_SENZA_ESITO = ("tempo_indeterminato",)  # concorsi pubblici


def _scadenza(scheda) -> str | None:
    try:
        return (json.loads(scheda["dati_extra"] or "{}").get("data_fine_invio_domande") or "")[:10] or None
    except ValueError:
        return None


def _data_it(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def giudizio(v: dict | None, copertura_segreteria: str | None, scadenza: str) -> dict:
    """Spec 012: che cosa dice Selezioni Online di un concorso senza esito. «deserto» solo con una prova positiva
    (nessuna domanda valida, oppure punteggi di tutti i candidati e tutti non ammessi a una prova): punteggi mancanti
    o parziali possono essere dati non inseriti e non bastano."""
    if copertura_segreteria is None:
        segr = "file della segreteria non caricato"
    elif copertura_segreteria == "9999-12-31":
        segr = "il file della segreteria non ha graduatorie: non copre questo concorso"
    elif copertura_segreteria <= scadenza:
        segr = "nessuna graduatoria nemmeno nel file della segreteria"
    else:
        segr = f"il file della segreteria parte dal {_data_it(copertura_segreteria)}: non copre questo concorso"
    if not v:
        return {"codice": "da_controllare", "testo": "domande e punteggi non ancora controllati su Selezioni Online", "segreteria": segr}
    if v.get("esito") == "errore":
        return {"codice": "da_controllare", "testo": f"lettura da Selezioni Online non riuscita: {v.get('messaggio') or ''}".strip(), "segreteria": segr}
    domande, con_punteggi = v.get("domande") or 0, v.get("con_punteggi") or 0
    positivi = (v.get("vincitori") or 0) + (v.get("idonei") or 0) + (v.get("scorrimento") or 0)
    if domande == 0:
        return {"codice": "deserto", "testo": "nessuna domanda valida su Selezioni Online", "segreteria": segr}
    if positivi:
        return {"codice": "graduatoria_mancante", "segreteria": segr,
                "testo": f"su Selezioni Online {positivi} candidati risultano vincitori o idonei: il concorso ha un esito ma manca la graduatoria pubblicata"}
    if con_punteggi < domande:
        return {"codice": "non_determinabile", "segreteria": segr,
                "testo": f"punteggi inseriti su Selezioni Online per {con_punteggi} candidati su {domande}: non si può dire se è deserto (dati forse non inseriti)"}
    if v.get("non_ammessi") is not None and v["non_ammessi"] >= con_punteggi:
        return {"codice": "deserto", "segreteria": segr,
                "testo": f"nessuno dei {con_punteggi} candidati ha superato le prove (tutti non ammessi su Selezioni Online)"}
    return {"codice": "non_determinabile", "segreteria": segr,
            "testo": f"punteggi completi per {con_punteggi} candidati ma nessun vincitore o idoneo e non tutti non ammessi: graduatoria forse non ancora inserita"}


def senza_esito(conn, oggi: date | None = None) -> list[dict]:
    """Spec 012: concorsi pubblici (sede per sede) con le domande scadute da più di 12 mesi e senza graduatoria,
    scorrimento, deserto o revoca su Selezioni Online, su URP e nel file della segreteria: forse manca il documento."""
    limite = ((oggi or date.today()) - timedelta(days=round(MESI_SENZA_ESITO * 30.44))).isoformat()
    schede = conn.execute("SELECT * FROM scheda WHERE fonte = 'sol' AND presente = 1 AND bando_id IS NOT NULL "
                          f"AND tipologia IN ({', '.join('?' * len(TIPOLOGIE_SENZA_ESITO))})", TIPOLOGIE_SENZA_ESITO).fetchall()
    padri = {s["id_padre"] for s in schede if s["id_padre"]}
    per_esterno = {s["id_esterno"]: s for s in schede}
    esiti_sol: dict[int, list] = defaultdict(list)  # scheda -> codici di sede degli esiti (None = tutto il bando)
    esiti_urp: dict[int, list] = defaultdict(list)  # bando -> codici di sede degli esiti
    for d in conn.execute(
            "SELECT s.id AS scheda_id, s.bando_id, s.fonte, d.titolo FROM documento d JOIN scheda s ON s.id = d.scheda_id "
            f"WHERE d.presente = 1 AND s.presente = 1 AND d.categoria IN ({', '.join('?' * len(ESITI))})", ESITI):
        (esiti_sol[d["scheda_id"]] if d["fonte"] == "sol" else esiti_urp[d["bando_id"]]).append(codice_sotto(d["titolo"]))
    # file della segreteria (versione in uso): graduatorie e scorrimenti per numero di bando e sede
    versione = segreteria.versione_in_uso(conn)
    esiti_seg: dict[str, list] = defaultdict(list)
    copertura = None  # prima data delle graduatorie nel file: prima di questa il file non dice niente
    if versione:
        for a in segreteria.atti_versione(conn, versione["id"]):
            if a["categoria"] in ("graduatoria", "scorrimento"):
                esiti_seg[a["numero_bando"]].append(a["codice_sotto"])
            if a["categoria"] == "graduatoria" and a["data"] and a["in_ambito"]:
                copertura = min(copertura or a["data"], a["data"])
        copertura = copertura or "9999-12-31"
    righe = []
    for s in schede:
        scadenza = _scadenza(s)
        if s["id_esterno"] in padri or not scadenza or scadenza >= limite or s["data_pubbl_graduatoria"]:
            continue
        padre = per_esterno.get(s["id_padre"]) if s["id_padre"] else None
        sede = str(s["codice_sotto"] or "").lstrip("0")

        def vale(codici):  # un esito vale per la sede se è del bando intero o di quella sede
            return any(c is None or str(c).lstrip("0") == sede for c in codici)
        if esiti_sol.get(s["id"]) or (padre is not None and vale(esiti_sol.get(padre["id"], []))) \
                or vale(esiti_urp.get(s["bando_id"], [])) or vale(esiti_seg.get(s["numero_bando"], [])):
            continue
        righe.append({"scheda": s, "scadenza": scadenza, "copertura_segreteria": copertura if versione else None})
    return righe


def elenco_atti(conn, dal: str | None = None, al: str | None = None, con_senza_esito: bool = False) -> list[dict]:
    """`con_senza_esito`: aggiunge i concorsi senza esito (spec 012), solo per lo stato complessivo."""
    dal = dal or config.monitoraggio_dal().isoformat()
    al = al or "9999-12-31"
    bandi = {b["id"]: dict(b) for b in conn.execute("SELECT * FROM bando WHERE stato_collegamento IS NOT NULL")}
    per_numero = {}
    for b in bandi.values():
        if b["numero_bando"]:
            per_numero.setdefault(b["numero_bando"], b["id"])
    def pagina_urp(s):
        return config.pagina_documenti_urp(s["sezione"], s["url"], s["titolo"])
    schede = defaultdict(dict)
    sol_per_codice = defaultdict(dict)  # bando -> codice di sotto-bando -> scheda SOL di quel codice
    for s in conn.execute("SELECT * FROM scheda WHERE presente = 1 AND bando_id IS NOT NULL ORDER BY codice_sotto IS NOT NULL, id"):
        schede[s["bando_id"]].setdefault(s["fonte"], s)  # scheda principale per fonte (senza sotto-bando, se c'è)
        if s["fonte"] == "sol" and s["codice_sotto"]:
            sol_per_codice[s["bando_id"]].setdefault(s["codice_sotto"], s)

    famiglie = sedi.famiglie(conn)
    # chi coordina il profilo del bando (tabella dei profili dei coordinatori)
    _, profilo_bando, _ = profili.per_bando(conn)  # profilo senza livello, o «Mobilità»
    coordinatori = profili.titolari(conn)
    testi_sede = sedi.testi_sede(conn)

    deserti_sol = {(r["bando_id"], r["protocollo"]) for r in conn.execute(
        "SELECT s.bando_id, d.protocollo FROM documento d JOIN scheda s ON s.id = d.scheda_id "
        "WHERE s.fonte = 'sol' AND d.categoria = 'deserto' AND d.presente = 1 AND d.protocollo IS NOT NULL")}
    # --- URP e SOL: documenti per bando
    voci = defaultdict(lambda: defaultdict(dict))  # chiave bando -> fonte -> (categoria, protocollo) -> voce
    for d in conn.execute(
            "SELECT s.bando_id, s.fonte, s.url AS url_scheda, s.sezione AS sezione_scheda, s.titolo AS titolo_scheda, s.codice_sotto AS sotto_scheda, d.* "
            "FROM documento d JOIN scheda s ON s.id = d.scheda_id "
            "WHERE d.presente = 1 AND s.presente = 1 AND d.protocollo IS NOT NULL "
            f"AND (d.categoria IN ({', '.join('?' * len(CATEGORIE_ATTI))}) OR (d.categoria = 'altro' AND s.fonte = 'urp')) "
            "AND d.data_protocollo BETWEEN ? AND ?",
            (*CATEGORIE_ATTI, dal, al)):
        if d["categoria"] == "altro":
            # spec 012: su URP il deserto ha spesso un titolo generico («Esito», «Conclusione procedura»):
            # vale come deserto se ha il protocollo del documento di deserto SOL dello stesso bando
            if (d["bando_id"], d["protocollo"]) not in deserti_sol:
                continue
            d = {**dict(d), "categoria": "deserto"}
        if d["bando_id"] in bandi and _da_confrontare(d):
            # pagina del bando (o del sotto-bando) con tutti gli allegati
            url = config.pagina_documenti_urp(d["sezione_scheda"], d["url_scheda"], d["titolo_scheda"]) if d["fonte"] == "urp" else d["url_scheda"]
            # codice di sotto-bando: dalla scheda SOL o, per la pagina unica di URP, dal titolo ("Cod. 13")
            sotto = d["sotto_scheda"] or codice_sotto(d["titolo"])
            voce = voci[d["bando_id"]][d["fonte"]].setdefault((d["categoria"], d["protocollo"]), _voce(
                d["categoria"], d["data_protocollo"], d["protocollo"], url, d["sottotipo"],
                "titolo" if d["sottotipo"] else None, d["titolo"], {"codice_sotto": sotto, "url_documento": d["url"]}))
            voce.setdefault("schede_doc", set()).add(d["scheda_id"])  # padre o sotto-bando: il documento vale comunque per il bando

    # --- file della segreteria (versione in uso)
    versione = segreteria.versione_in_uso(conn)
    atti_seg = segreteria.atti_versione(conn, versione["id"]) if versione else []
    periodo = _periodo_segreteria(atti_seg)
    # spec 010: i protocolli approvati dalle email di Titulus valgono come righe del file, finché non ci sono davvero
    atti_seg = atti_seg + protocollo_email.atti_approvati(conn, {str(x["protocollo"]) for x in atti_seg if x.get("protocollo")})
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
        extra = {"persone": a["persone"], "protocollo_privato": a["protocollo_privato"], "codice_sotto": a["codice_sotto"],
                 "aggiunto_automaticamente": bool(a.get("aggiunto_automaticamente"))}
        gia = voci[chiave_bando]["segreteria"].get((a["categoria"], a["protocollo"]))
        voce = voci[chiave_bando]["segreteria"].setdefault((a["categoria"], a["protocollo"]), _voce(
            a["categoria"], a["data"], a["protocollo"], url_file_segreteria(atto=a["id"]) if a["id"] else "/monitoraggio/segreteria#protocollo",
            a["sottotipo"], "segreteria",
            a["titolo"], extra))
        if gia is not None:  # stesso atto per più sedi: il file ha una riga per ogni sede
            voce["persone"] = (voce.get("persone") or 0) + (a["persone"] or 0)
        voce.setdefault("testi_sede", set()).update(testi_sede.get(a["id"], ()))

    righe = []

    def cella(fonte, voce, applicabile_urp, categoria, data):
        if voce is not None:
            return {"stato": PRESENTE, "url": voce.get("url"), "protocollo": voce.get("protocollo"),
                    **({"automatico": True} if voce.get("aggiunto_automaticamente") else {})}
        if fonte == "segreteria":
            if categoria in FUORI_FILE_SEGRETERIA:
                return {"stato": NON_APPLICABILE, "testo": "non nel file"}
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
            rif = f" (prot. {r['protocollo']})" if r.get("protocollo") else ""
            n = r.get("utilizzi_sol_codice") or 0
            extra = (f" (per questo codice su SOL risulta{'no' if n > 1 else ''} già {n} utilizz{'i' if n > 1 else 'o'})") if n else ""
            if r.get("fonti", {}).get("sol", {}).get("stato") == PRESENTE:
                return [f"provvedimento di assunzione idoneo{rif} presente tra gli allegati SOL ma non risulta nei punteggi: nessun candidato S con questo protocollo{extra}"]
            return [f"provvedimento di assunzione idoneo{rif} non presente tra gli allegati SOL e nessun candidato S con questo protocollo nei punteggi{extra}"]
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
    # spec 012: concorsi senza esito, indipendenti dal periodo (la data è la scadenza delle domande)
    per_senza_esito = defaultdict(list)
    if con_senza_esito:
        for x in senza_esito(conn):
            per_senza_esito[x["scheda"]["bando_id"]].append(x)
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
                             url_file_segreteria(atto=seg_bando["id"]) if seg_bando["id"] else "/monitoraggio/segreteria#protocollo") if seg_bando else None
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
                              "urp": cella("urp", {"url": pagina_urp(sch["urp"]), "protocollo": sch["urp"]["protocollo"]}
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
                          "note": ["data della graduatoria pubblica con i soli vincitori su SOL senza documento pubblico"]})

        for x in per_senza_esito.get(chiave, []):
            s = x["scheda"]
            esito_verifica = giudizio(verifiche.get(s["id"]), x["copertura_segreteria"], x["scadenza"])
            urp = schede.get(chiave, {}).get("urp")
            righe.append({**base, "atto": "senza_esito", "sottotipo": None, "sottotipo_origine": None,
                          "codice_sotto": s["codice_sotto"], "data": x["scadenza"], "protocollo": None,
                          "titolo": s["codice_originale"], "persone": None,
                          "fonti": {"sol": {"stato": NON_APPLICABILE, "testo": "nessun esito", "url": s["url"]},
                                    "urp": {"stato": NON_APPLICABILE, "testo": "nessun esito", "url": pagina_urp(urp) if urp is not None else None},
                                    "segreteria": {"stato": NON_APPLICABILE, "testo": "nessuna graduatoria" if esito_verifica["segreteria"].startswith("nessuna")
                                                   else "file non caricato" if x["copertura_segreteria"] is None else "non copre il periodo"}},
                          "note": [], "_senza_esito": True, "scheda_sol_id": s["id"],
                          "esito_verifica": esito_verifica, "probabile_deserto": esito_verifica["codice"] == "deserto",
                          "avviso": f"domande scadute il {x['scadenza'][8:10]}/{x['scadenza'][5:7]}/{x['scadenza'][:4]}: nessuna graduatoria, "
                                    "deserto o revoca su Selezioni Online e su URP (verificare se manca il documento)"})

        # documenti
        for gruppo in _unisci(voci.get(chiave, {})):
            principale = gruppo.get("segreteria") or gruppo.get("sol") or gruppo.get("urp")
            categoria, data = principale["categoria"], principale["data"]
            note = []
            protocolli = {f: v["protocollo"] for f, v in gruppo.items()}
            if len(set(protocolli.values())) > 1:
                nomi = {"urp": "URP", "sol": "SOL", "segreteria": "file"}
                note.append("protocollo diverso: " + ", ".join(f"{nomi[f]} {protocolli[f]}" for f in FONTI if f in protocolli))
            sottotipo, origine, subentro_atteso = None, None, False
            if categoria == "scorrimento":
                dal_titolo = next((v["sottotipo"] for f, v in gruppo.items()
                                   if f != "segreteria" and v["sottotipo"] and v["sottotipo"] != "non_specificato"), None)
                if "segreteria" in gruppo:
                    sottotipo, origine = gruppo["segreteria"]["sottotipo"], "segreteria"
                    if sottotipo is None:
                        note.append("tipologia da completare nel file")
                else:
                    sottotipo = dal_titolo or "non_specificato"
                    origine = "titolo"
                # un subentro non è una difformità: va indicato nel file scorrimenti del mese (scorrimenti_compilato.py)
                subentro_atteso = "subentro" in (sottotipo, dal_titolo)
            righe.append({**base, "atto": categoria, "sottotipo": sottotipo, "sottotipo_origine": origine, "subentro_atteso": subentro_atteso,
                          "codice_sotto": next((gruppo[f]["codice_sotto"] for f in FONTI
                                                if f in gruppo and gruppo[f].get("codice_sotto")), None),
                          "data": data,
                          "protocollo": principale["protocollo"], "titolo": principale["titolo"],
                          "persone": gruppo.get("segreteria", {}).get("persone"),
                          "fonti": {f: cella(f, gruppo.get(f), urp_ok, categoria, data) for f in FONTI},
                          "note": note, "_protocolli": [p for p in protocolli.values() if p],
                          "_sedi": sedi.del_gruppo(famiglie.get(chiave), gruppo)})

    # utilizzi di scorrimento presenti su SOL per bando/codice, su tutto il periodo (non solo il mese):
    # così un utilizzo nuovo mancante non sembra un falso allarme quando SOL ne ha già altri per quel codice
    sol_utilizzi: dict = defaultdict(set)
    for d in conn.execute(
            "SELECT s.bando_id, s.codice_sotto AS sotto, d.titolo, d.protocollo FROM documento d "
            "JOIN scheda s ON s.id = d.scheda_id WHERE s.fonte = 'sol' AND s.presente = 1 AND d.presente = 1 "
            "AND d.categoria = 'scorrimento' AND d.protocollo IS NOT NULL AND s.bando_id IS NOT NULL"):
        sol_utilizzi[(d["bando_id"], d["sotto"] or codice_sotto(d["titolo"]))].add(d["protocollo"])
    for r in righe:
        if r["atto"] == "scorrimento":
            altri = sol_utilizzi.get((r["bando_id"], r.get("codice_sotto")), set()) - ({r["protocollo"]} if r.get("protocollo") else set())
            r["utilizzi_sol_codice"] = len(altri)

    for r in righe:
        if r["bando_id"] is not None:
            r["rdp"], r["rdp_origine"] = rdp_riga(r["bando_id"], r.get("codice_sotto"))
            profilo = profili.voce(r.get("tipologia"), profilo_bando.get(r["bando_id"]))  # la mobilità ha un coordinatore suo
            r["coordinatore"] = {"email": coordinatori[profilo], "profilo": profilo} if profilo in coordinatori else None
            r["link_codice"] = link_codice(r["bando_id"], r.get("codice_sotto"))
            sotto = sol_per_codice.get(r["bando_id"], {}).get(r.get("codice_sotto")) if r.get("codice_sotto") else None
            if sotto is not None:
                r["codice"] = sotto["codice_originale"]  # es. "367.434 CA - TRIESTE Codice 05", come su SOL
            info = r.pop("_sedi", None)
            unica = info["figli"][0] if info and len(info["figli"]) == 1 else None
            if info:
                riferita = unica or info["padre"]
                r.update(codice=riferita["codice_originale"], titolo_bando=riferita["titolo"], link_codice=unica["url"] if unica else None,
                         sedi_ids=[x["id"] for x in info["figli"]], sede_da_abbinare=info["da_abbinare"])
                if unica:
                    r["codice_sotto"] = unica["codice_sotto"]
                persone_sedi = {p.get("email") or f"{p.get('nome')} {p.get('cognome')}": p for x in info["figli"] for p in persone(rdp_scheda.get(x["id"], []))}
                if persone_sedi:
                    r["rdp"], r["rdp_origine"] = list(persone_sedi.values()), "codice" if unica else "bando"
            s = unica if info else scheda_sol(r["bando_id"], r.get("codice_sotto"))
            if r["atto"] in ("graduatoria", "scorrimento") and s is not None:
                r["punteggi"] = punteggi_riga(s)
                r["scheda_sol_id"] = s["id"]
                r["punteggi_da_verificare"] = r["punteggi"] is None
                r["url_punteggi"] = url_punteggi(s["id_esterno"])
                r["note"] += difformita_sol(r, s)
            else:
                r["punteggi"], r["url_punteggi"] = None, None
            if info and len(info["figli"]) > 1:  # atto unico per più sedi: una sotto-riga per sede, sotto quella del padre
                seguito = r["atto"] in ("graduatoria", "scorrimento")
                r["sedi"] = [{"scheda_id": x["id"], "codice": x["codice_originale"], "link_sol": x["url"], "url_punteggi": url_punteggi(x["id_esterno"]),
                              "punteggi": punteggi_riga(x) if seguito else None, "note": difformita_sol(r, x) if seguito else [],
                              "rdp": persone(rdp_scheda.get(x["id"], []))}
                             for x in sorted(info["figli"], key=lambda x: x["codice_originale"] or "")]
            # celle senza documento: link alla pagina della fonte, per verificare se l'atto manca davvero
            if not r["fonti"]["sol"].get("url"):
                principale = info["padre"] if info else schede.get(r["bando_id"], {}).get("sol")
                r["fonti"]["sol"]["url"] = r["link_codice"] or (principale["url"] if principale is not None else None)
            if not r["fonti"]["urp"].get("url") and "urp" in schede.get(r["bando_id"], {}):
                r["fonti"]["urp"]["url"] = pagina_urp(schede[r["bando_id"]]["urp"])
        else:
            r["rdp"], r["rdp_origine"], r["link_codice"], r["punteggi"], r["url_punteggi"] = [], None, None, None, None
            r["coordinatore"] = None
        if versione and not r["fonti"]["segreteria"].get("url") and r["atto"] in FOGLIO_SEGRETERIA:
            r["fonti"]["segreteria"]["url"] = url_file_segreteria(foglio=FOGLIO_SEGRETERIA[r["atto"]])
        r.pop("_protocolli", None)
        if r.pop("_senza_esito", False):  # non è una difformità tra fonti: è un elenco da verificare
            r.update(incompleto=False, difforme=False, protocollo_diverso=False)
            continue
        r["incompleto"] = any(c["stato"] == MANCANTE for c in r["fonti"].values())
        r["difforme"] = r["incompleto"] or bool(r["note"]) or any(s["note"] for s in r.get("sedi") or [])
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
