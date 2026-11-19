"""Riepilogo e revisione del monitoraggio (spec 011).

Flusso dell'utente del 2026-11-18: l'amministratore carica l'estrazione delle graduatorie da Selezioni Online e il file
scorrimenti compilato; il sistema verifica che ci sia tutto partendo da ciò che risulta nel monitoraggio; l'amministratore
vede ciò che non torna e chiede la verifica agli RdP del bando; mandandolo in revisione, coordinatori e persone dell'ufficio
ricevono il link e i totali (quanti atti risultano a noi e quanti ce ne sono nei file), senza dati personali.
"""
import json
import logging
from collections import Counter
from datetime import datetime, timezone

from . import avvisi_scorrimenti, comunicazioni, config, estrazione_sol, excel_mese, mensile, portale, posta, scorrimenti_compilato, verifica_file

log = logging.getLogger(__name__)
MOBILITA = ("mobilita", "comando")
NOMI_FILE = {"scorrimenti": "scorrimenti", "graduatorie": "graduatorie"}
CATEGORIE = (("bandi", "Bandi pubblicati"), ("graduatorie", "Bandi con graduatoria"), ("scorrimenti", "Scorrimenti"), ("subentri", "di cui subentri (tra gli scorrimenti)"),
             ("rettifiche", "Rettifiche di graduatoria"))  # le rettifiche si contano a parte (scelta dell'utente del 2026-11-18)


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ verifiche dei due file

def verifica_scorrimenti(conn, m: dict, righe: list[dict] | None = None) -> dict:
    file = scorrimenti_compilato.caricato(conn, m["mese"])
    if not file:
        return {"caricato": None}
    righe = comunicazioni.righe_mese(conn, m) if righe is None else righe
    estratte = estrazione_sol.tutte(conn, m["mese"])  # i nomi veri degli assunti da scorrimento sono su Selezioni Online
    esito = scorrimenti_compilato.confronta(righe, file["voci"], file["fogli"], verifica_file.persone_segreteria(conn, "scorrimento"),
                                            verifica_file.profili_per_bando(conn), estrazione_sol.scorrimenti_sol(estratte) if estratte else None)
    return {"caricato": {k: file[k] for k in ("nome_file", "caricato_da", "caricato_il")}, **esito}


def verifica_graduatorie(conn, m: dict, righe: list[dict] | None = None) -> dict:
    """Le due estrazioni da Selezioni Online (concorsi e mobilità) insieme, contro tutte le graduatorie del monitoraggio."""
    caricate = {tipo: estrazione_sol.caricata(conn, m["mese"], tipo) for tipo in estrazione_sol.TABELLE}
    info = {tipo: {k: e[k] for k in ("nome_file", "caricato_da", "caricato_il")} if e else None for tipo, e in caricate.items()}
    if not any(caricate.values()):
        return {"caricato": None, "caricati": info}
    righe = comunicazioni.righe_mese(conn, m) if righe is None else righe
    esito = estrazione_sol.confronta(righe, [v for e in caricate.values() if e for v in e["righe"]], *mensile.periodo_dati(m),
                                     verifica_file.persone_segreteria(conn, "graduatoria"), verifica_file.profili_per_bando(conn))
    return {"caricato": info["concorsi"] or info["mobilita"], "caricati": info, **esito}


# ------------------------------------------------------------------ totali

def _mobilita(r: dict) -> bool:
    return r.get("tipologia") in MOBILITA


def _vuoto() -> dict:
    # persone: quante persone negli atti (file della segreteria) e quante nei file caricati; uno scorrimento può averne molte
    return {"attesi": 0, "nei_file": 0, "persone_attese": 0, "persone_nei_file": 0}


def totali(conn, m: dict, righe: list[dict] | None = None, scorrimenti: dict | None = None, graduatorie: dict | None = None) -> dict:
    """Quanti atti risultano nel monitoraggio e quanti ce ne sono nei file caricati, per categoria, concorsi/mobilità e gruppo."""
    righe = comunicazioni.righe_mese(conn, m) if righe is None else righe
    scorrimenti = verifica_scorrimenti(conn, m, righe) if scorrimenti is None else scorrimenti
    graduatorie = verifica_graduatorie(conn, m, righe) if graduatorie is None else graduatorie
    pb = verifica_file.profili_per_bando(conn)
    trovati_s = {(a["chiave"], a["protocollo"], a["data"]): a for a in scorrimenti.get("atti", []) if a["trovato"]}
    trovate_g = {a["chiave"]: a for a in graduatorie.get("atti", []) if a["trovato"]}
    tabella = {k: {"categoria": nome, "concorsi": _vuoto(), "mobilita": _vuoto(), "totale": _vuoto(), "per_gruppo": {}, "mancanti": []}
               for k, nome in CATEGORIE}
    tabella["bandi"]["nei_file_da"] = "dal sistema (Selezioni Online)"
    tabella["rettifiche"]["nei_file_da"] = "non sono nei file del monitoraggio"

    def conta(categoria: str, r: dict, nel_file: bool, persone_file: int = 0) -> None:
        voce, gruppo = tabella[categoria], verifica_file.gruppo_della_riga(r, pb)
        g = voce["per_gruppo"].setdefault(gruppo, _vuoto())
        for parte in (voce["mobilita" if _mobilita(r) else "concorsi"], voce["totale"], g):
            parte["attesi"] += 1
            parte["nei_file"] += int(nel_file)
            parte["persone_attese"] += r.get("persone") or 0
            parte["persone_nei_file"] += persone_file
        if not nel_file and categoria in ("graduatorie", "scorrimenti", "subentri"):  # quali atti mancano: per controllarli nel monitoraggio
            voce["mancanti"].append({"codice": r.get("codice") or r.get("numero_bando"), "protocollo": r.get("protocollo"), "data": r.get("data"),
                                     "mobilita": _mobilita(r)})

    gia_g = set()
    tipologie = Counter()
    for r in righe:
        chiave = (r.get("chiave"), r.get("protocollo"), r.get("data"))
        if r["atto"] == "bando":
            conta("bandi", r, True)  # i bandi pubblicati del file graduatorie vengono dal sistema
        elif r["atto"] == "graduatoria" and r.get("chiave") not in gia_g:
            gia_g.add(r.get("chiave"))
            ag = trovate_g.get(r.get("chiave"))
            conta("graduatorie", r, bool(ag), ag["candidati"] if ag else 0)
        elif r["atto"] == "rettifica":
            conta("rettifiche", r, False)
        elif r["atto"] == "scorrimento":
            a = trovati_s.get(chiave)
            conta("scorrimenti", r, bool(a), a["nominativi"] if a else 0)
            subentro = r.get("sottotipo") == "subentro" or r.get("subentro_atteso")
            if subentro:
                conta("subentri", r, bool(a and a["subentro_indicato"]), a["nominativi"] if a and a["subentro_indicato"] else 0)
            tipologie[(scorrimenti_compilato.tipo_di(a["tipologia"]) or "non indicata") if a else "non nel file"] += 1
    for voce in tabella.values():
        voce["per_gruppo"] = [{"gruppo": g, "nome": verifica_file.GRUPPI.get(g, "Altri profili"), **v}
                              for g, v in sorted(voce["per_gruppo"].items(), key=lambda x: [*verifica_file.GRUPPI, verifica_file.ALTRO].index(x[0]))]
    if not scorrimenti.get("caricato"):
        for k in ("scorrimenti", "subentri"):
            tabella[k]["nei_file_da"] = "file scorrimenti non caricato"
            tabella[k]["mancanti"] = []
    if not graduatorie.get("caricato"):
        tabella["graduatorie"]["nei_file_da"] = "estrazione da Selezioni Online non caricata"
        tabella["graduatorie"]["mancanti"] = []
    for k in ("bandi", "rettifiche"):
        tabella[k]["senza_persone"] = True
    return {"categorie": [tabella[k] for k, _ in CATEGORIE], "scorrimenti_per_tipologia": dict(tipologie)}


def da_verificare(scorrimenti: dict, graduatorie: dict) -> list[dict]:
    """L'elenco di ciò che non torna (gravi), per file e bando (solo per gli amministratori: può contenere nominativi)."""
    voci = []
    for file, esito in (("scorrimenti", scorrimenti), ("graduatorie", graduatorie)):
        if not esito.get("caricato"):
            continue
        for a in esito.get("atti", []):
            if a.get("gravi"):
                voci.append({"file": file, "chiave": a["chiave"], "codice": a.get("codice") or a.get("numero_bando"), "protocollo": a.get("protocollo"),
                             "data": a.get("data"), "gruppo": a.get("gruppo"), "problemi": a["gravi"], "rdp": a.get("rdp") or []})
        for s in esito.get("solo_nel_file", []):
            voci.append({"file": file, "chiave": None, "codice": s["bando"], "protocollo": ", ".join(s.get("protocolli") or [s.get("protocollo") or ""]).strip(", "),
                         "data": s.get("data"), "gruppo": None, "problemi": [f"nel file ({s.get('righe') or ''}) ma non nel monitoraggio: da verificare"], "rdp": []})
        for c in esito.get("conteggi_bando", []):
            voci.append({"file": file, "chiave": None, "codice": c["numero_bando"], "protocollo": "", "data": None, "gruppo": None, "rdp": [],
                         "problemi": [f"il file indica {c['scorrimenti_file']} scorrimenti (di cui {c['subentri_file']} subentri), dalla segreteria e da URP "
                                      f"ne risultano {c['scorrimenti_rif']} (di cui {c['subentri_rif']} subentri)"]})
    return voci


def errori_minori(scorrimenti: dict, graduatorie: dict) -> list[dict]:
    """Nomi scritti diversi, posizioni e punteggi, foglio, bando scritto male, dati SOL non aggiornati: a parte."""
    return [{"file": file, "chiave": a["chiave"], "codice": a.get("codice") or a.get("numero_bando"), "protocollo": a.get("protocollo"),
             "data": a.get("data"), "minori": a["minori"]}
            for file, esito in (("scorrimenti", scorrimenti), ("graduatorie", graduatorie)) if esito.get("caricato")
            for a in esito.get("atti", []) if a.get("minori")]


def _elenco_per_tipologia(s: dict, fatte: dict) -> list[dict]:
    """Gli scorrimenti divisi per tipologia: quelli che ci sono, quelli che mancano (rossi), quelli solo nel file (arancioni)."""
    gruppi = {k: {"tipo": k, "nome": n, "righe": []} for k, n in scorrimenti_compilato.TIPOLOGIE.items()}
    for a in s.get("atti", []):
        stato = "manca" if not a["trovato"] else "da_verificare" if a["gravi"] else "ok"
        gruppi[a["tipo"] if a["tipo"] in gruppi else "non indicata"]["righe"].append(
            {"stato": stato, "chiave": a["chiave"], "codice": a.get("codice") or a.get("numero_bando"), "protocollo": a.get("protocollo"),
             "data": a.get("data"), "gruppo": a.get("gruppo"), "righe_file": a["righe_file"], "nominativi": a["nominativi"],
             "persone_segreteria": a["persone_segreteria"], "persone_sol": a["persone_sol"], "gravi": a["gravi"], "minori": a["minori"],
             "rdp": a.get("rdp") or [], "richiesta": fatte.get(("scorrimenti", a["chiave"]))})
    for b in s.get("solo_nel_file", []):
        gruppi[b["tipo"] if b["tipo"] in gruppi else "non indicata"]["righe"].append(
            {"stato": "solo_file", "chiave": None, "codice": b["bando"], "protocollo": ", ".join(b["protocolli"]), "data": None, "gruppo": None,
             "righe_file": [b["righe"]], "nominativi": b["nominativi"], "persone_segreteria": 0, "persone_sol": 0,
             "gravi": ["nel file ma non nel monitoraggio: da verificare"], "minori": [], "rdp": [], "richiesta": None})
    ordine = {"manca": 0, "da_verificare": 1, "solo_file": 2, "ok": 3}
    for g in gruppi.values():
        g["righe"].sort(key=lambda x: (ordine[x["stato"]], x["codice"] or ""))
        g["conteggi"] = {k: sum(1 for x in g["righe"] if x["stato"] == k) for k in ordine}
        g["conteggi"]["totale"] = len(g["righe"])
    return [g for g in gruppi.values() if g["righe"]]


def _elenco_graduatorie(g: dict, fatte: dict) -> list[dict]:
    righe = [{"stato": "manca" if not a["trovato"] else "da_verificare" if a["gravi"] else "ok", "chiave": a["chiave"],
              "codice": a.get("codice") or a.get("numero_bando"), "protocollo": a.get("protocollo"), "data": a.get("data"), "gruppo": a.get("gruppo"),
              "candidati": a["candidati"], "persone_segreteria": a["persone_segreteria"], "gravi": a["gravi"], "minori": a["minori"],
              "rdp": a.get("rdp") or [], "richiesta": fatte.get(("graduatorie", a["chiave"]))} for a in g.get("atti", [])]
    righe += [{"stato": "solo_file", "chiave": None, "codice": s["bando"], "protocollo": s["protocollo"], "data": s["data"], "gruppo": None,
               "candidati": s["candidati"], "persone_segreteria": 0, "gravi": ["su Selezioni Online ma non nel monitoraggio: da verificare"],
               "minori": [], "rdp": [], "richiesta": None} for s in g.get("solo_nel_file", [])]
    ordine = {"manca": 0, "da_verificare": 1, "solo_file": 2, "ok": 3}
    righe.sort(key=lambda x: (ordine[x["stato"]], x["codice"] or ""))
    return righe


# ------------------------------------------------------------------ richiesta di verifica agli RdP

def _righe_del_bando(righe: list[dict], chiave: str) -> list[dict]:
    return [r for r in righe if r.get("chiave") == chiave]


def richiesta(conn, m: dict, file: str, chiave: str) -> dict | None:
    """Anteprima dell'email agli RdP del bando con ciò che non torna nel file e il link per aggiornarlo."""
    righe = comunicazioni.righe_mese(conn, m)
    esito = verifica_scorrimenti(conn, m, righe) if file == "scorrimenti" else verifica_graduatorie(conn, m, righe)
    problemi = [(a, p) for a in esito.get("atti", []) if a["chiave"] == chiave for p in a["problemi"]]
    del_bando = _righe_del_bando(righe, chiave)
    if not del_bando:
        return None
    destinatari = list(dict.fromkeys((p.get("email") or "").strip().lower() for r in del_bando for p in r.get("rdp") or [] if p.get("email")))
    link = m.get(f"link_{file}") or ""
    nome_file = (excel_mese.nome_scorrimenti if file == "scorrimenti" else excel_mese.nome_graduatorie)(m["mese_dati"])
    titolo = f" – {del_bando[0]['titolo_bando']}" if del_bando[0].get("titolo_bando") else ""
    mese_testo = comunicazioni.titolo_mese(m["mese_dati"])
    def voce(a: dict, p: str) -> str:
        prot = f" (prot. {a['protocollo']})" if a.get("protocollo") else ""
        return f"- atto del {comunicazioni._data_it(a.get('data'))}{prot}: {p}"
    elenco = "\n".join(voce(a, p) for a, p in problemi)
    corpo = (f"{comunicazioni.INTESTAZIONE_EMAIL}\n\nGentili tutte e tutti,\n\nnel controllo del file {NOMI_FILE[file]} del monitoraggio di {mese_testo}, "
             f"per il bando {chiave}{titolo} risulta quanto segue:\n\n{elenco or '- (nessuna differenza rilevata)'}\n\n"
             f"Vi chiediamo di verificare e, se necessario, di aggiornare il file{f': {link}' if link else ''}.\n\n"
             "Potrebbe trattarsi anche di un nostro errore: in questo caso vi chiediamo di segnalarcelo rispondendo a questa email.\n\n"
             f"Cordiali saluti,\n{posta.impostazioni_email()['firma'] or ''}\n")
    oggetto = f"Monitoraggio {mese_testo}. Bando n° {chiave}: verifica del file {NOMI_FILE[file]}"
    storico = [dict(r) for r in conn.execute("SELECT quando, esito, utente FROM richiesta_verifica WHERE mese = ? AND file = ? AND chiave = ? ORDER BY id DESC",
                                             (m["mese"], file, chiave))]
    return {"file": file, "chiave": chiave, "destinatari": destinatari, "oggetto": oggetto, "corpo": corpo, "link": link, "nome_file": nome_file,
            "problemi": len(problemi), "storico": storico, "posta": posta.stato()}


MODI = (None, "prova", "ufficiale")  # come nel pannello del messaggio: prova o casella dell'ufficio; None = regola generale


def invia_richiesta(conn, m: dict, file: str, chiave: str, oggetto: str, corpo: str, utente: str | None, modo: str | None = None) -> dict:
    if modo not in MODI:
        raise ValueError("Modo di invio non valido")
    anteprima = richiesta(conn, m, file, chiave)
    if anteprima is None:
        raise ValueError("Bando non trovato in questo monitoraggio")
    if not anteprima["destinatari"]:
        raise ValueError("Nessuna email RdP per questo bando")
    if comunicazioni.contiene_dati_candidati(oggetto, corpo):
        raise ValueError("Il testo sembra contenere un codice fiscale: invio bloccato")
    prova = posta.invia(anteprima["destinatari"], oggetto, corpo, modo=modo)
    conn.execute("INSERT INTO richiesta_verifica (mese, file, chiave, destinatari, oggetto, esito, utente, quando) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (m["mese"], file, chiave, json.dumps(anteprima["destinatari"]), oggetto, "prova" if prova else "inviata", utente, _adesso()))
    return {"ok": True, "prova": prova}


def richieste(conn, mese: str) -> dict[tuple, dict]:
    """L'ultima richiesta di verifica per (file, bando)."""
    ultime = {}
    for r in conn.execute("SELECT file, chiave, esito, quando FROM richiesta_verifica WHERE mese = ? ORDER BY id", (mese,)):
        ultime[(r["file"], r["chiave"])] = dict(r)
    return ultime


# ------------------------------------------------------------------ riepilogo e revisione

def riepilogo(conn, m: dict, con_dettagli: bool = True) -> dict:
    """Per l'amministratore (`con_dettagli`): totali, esito dei file e ciò che non torna. Per gli altri: solo i totali."""
    righe = comunicazioni.righe_mese(conn, m)
    s, g = verifica_scorrimenti(conn, m, righe), verifica_graduatorie(conn, m, righe)
    base = {"mese": m["mese"], "titolo": comunicazioni.titolo_mese(m["mese_dati"]), "totali": totali(conn, m, righe, s, g),
            "revisione": {"il": m.get("revisione_il"), "da": m.get("revisione_da")},
            "file": {nome: {"caricato": e.get("caricato"), "caricati": e.get("caricati"), "allineato": e.get("allineato") if e.get("caricato") else None}
                     for nome, e in (("scorrimenti", s), ("graduatorie", g))}}
    if not con_dettagli:
        return base
    voci = da_verificare(s, g)
    fatte = richieste(conn, m["mese"])
    for v in voci:
        v["richiesta"] = fatte.get((v["file"], v["chiave"])) if v["chiave"] else None
    for nome, e in (("scorrimenti", s), ("graduatorie", g)):
        base["file"][nome].update({"da_verificare": len([v for v in voci if v["file"] == nome]),
                                   "mancanti": e.get("fogli_mancanti") or e.get("gruppi_mancanti") or [],
                                   "fuori_periodo": e.get("fuori_periodo")})
    return {**base, "da_verificare": voci, "minori": errori_minori(s, g),
            "scorrimenti_per_tipologia": _elenco_per_tipologia(s, fatte) if s.get("caricato") else [],
            "graduatorie": _elenco_graduatorie(g, fatte) if g.get("caricato") else [],
            "conteggi_bando": s.get("conteggi_bando") or [], "testo": m.get("testo_revisione") or testo_predefinito(m),
            "testo_personalizzato": bool(m.get("testo_revisione")),
            "link": {"scorrimenti": m.get("link_scorrimenti") or "", "graduatorie": m.get("link_graduatorie") or ""}}


def testo_predefinito(m: dict) -> str:
    mese_testo = comunicazioni.titolo_mese(m["mese_dati"])
    return (f"Gentili colleghe e colleghi,\n\nil monitoraggio di {mese_testo} è in revisione. Vi chiediamo di verificarne lo stato dalla "
            "pagina del monitoraggio e di segnalarci eventuali correzioni. Qui sotto trovate i totali di ciò che risulta a noi e di ciò "
            "che è indicato nei file del monitoraggio.")


def salva_testo(conn, mese: str, testo: str | None) -> None:
    conn.execute("UPDATE monitoraggio_mese SET testo_revisione = ? WHERE mese = ?", ((testo or "").strip() or None, mese))


def tabella_testo(tot: dict) -> str:
    """I totali in testo semplice per l'email: categoria, concorsi, mobilità, per gruppo."""
    righe = []
    for c in tot["categorie"]:
        pers = lambda n, c=c: "" if c.get("senza_persone") or not n else f" ({n} {'persona' if n == 1 else 'persone'})"  # noqa: E731
        nei = lambda v, c=c: "" if c.get("nei_file_da") and c["categoria"] != "Bandi pubblicati" else f" · nei file {v['nei_file']}{pers(v['persone_nei_file'])}"  # noqa: E731
        righe.append(f"{c['categoria']}: {c['totale']['attesi']}{pers(c['totale']['persone_attese'])}{nei(c['totale'])} "
                     f"(concorsi {c['concorsi']['attesi']}, mobilità {c['mobilita']['attesi']})")
        for g in c["per_gruppo"]:
            righe.append(f"   – {g['nome']}: {g['attesi']}{nei(g)}")
        if c.get("mancanti"):
            righe.append("   mancano nei file: " + ", ".join(x["codice"] or "" for x in c["mancanti"]))
    if tot["scorrimenti_per_tipologia"]:
        righe.append("Scorrimenti per tipologia: " + ", ".join(f"{k} {v}" for k, v in sorted(tot["scorrimenti_per_tipologia"].items())))
    return "\n".join(righe)


def destinatari_revisione(conn) -> list[str]:
    return list(dict.fromkeys([*(c["email"] for c in portale.elenco_coordinatori(conn)), *avvisi_scorrimenti.interni()]))


def manda_in_revisione(conn, m: dict, utente: str | None, modo: str | None = None) -> dict:
    if modo not in MODI:
        raise ValueError("Modo di invio non valido")
    mensile.verifica_aperto(conn, m["mese"])
    destinatari = destinatari_revisione(conn)
    if not destinatari:
        raise ValueError("Nessun destinatario: aggiungi i coordinatori o l'elenco delle persone dell'ufficio (Impostazioni)")
    r = riepilogo(conn, m, con_dettagli=False)
    mese_testo = comunicazioni.titolo_mese(m["mese_dati"])
    corpo = (f"{(m.get('testo_revisione') or testo_predefinito(m)).strip()}\n\n"
             f"Pagina del monitoraggio: {config.sito_url()}{portale.PAGINA}/monitoraggi/{m['mese']}\n"
             f"(per chi accede al sito: {config.sito_url()}/monitoraggio/consulta/monitoraggi/{m['mese']})\n\n"
             f"Totali del monitoraggio di {mese_testo}\n{tabella_testo(r['totali'])}\n\n"
             f"Cordiali saluti,\n{posta.impostazioni_email()['firma'] or ''}\n")
    prova = posta.invia(destinatari, f"Monitoraggio {mese_testo}: in revisione", corpo, modo=modo)
    if not prova:  # una prova non manda davvero il monitoraggio in revisione
        conn.execute("UPDATE monitoraggio_mese SET revisione_il = ?, revisione_da = ? WHERE mese = ?", (_adesso(), utente, m["mese"]))
    return {"ok": True, "prova": prova, "destinatari": destinatari}


def link_file(m: dict) -> dict:
    return {"scorrimenti": m.get("link_scorrimenti") or "", "graduatorie": m.get("link_graduatorie") or ""}
