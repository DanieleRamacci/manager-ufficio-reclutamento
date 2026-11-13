"""Atti del monitoraggio, messaggi ai referenti e allineamento delle fonti (specifiche grafiche, sezioni 3.2-3.5)."""
import re

from . import atti, compat, difformita, excel_mese, mensile, posta, punteggi, scorrimenti_compilato

MESI_LUNGHI = excel_mese.MESI


def titolo_mese(mese: str) -> str:
    anno, numero = mese.split("-")
    return f"{MESI_LUNGHI[int(numero) - 1]} {anno}"


def _data_it(iso: str | None) -> str:
    return "/".join(reversed(iso[:10].split("-"))) if iso else ""


def gruppo_tipologia(tipologia: str | None) -> str | None:
    return next((g for g, tipi in mensile.TIPOLOGIE_MONITORABILI.items() if tipologia in tipi), None)


def chiave(riga: dict) -> str:
    return riga.get("codice") or riga.get("numero_bando") or ""


def righe_mese(conn, monitoraggio: dict, tipologie: list[str] | None = None) -> list[dict]:
    """Atti del mese delle tipologie del monitoraggio, con i rilievi e lo stato della comunicazione."""
    dal, al = mensile.periodo_dati(monitoraggio)
    scelte = tipologie or mensile.tipologie_di(monitoraggio)
    inviate = mensile.solleciti(conn, monitoraggio["mese"])
    in_attesa = bool(atti.fonti_in_attesa(conn))
    righe = []
    for r in difformita.righe_correnti(conn, dal, al, tutti=True):
        gruppo = gruppo_tipologia(r.get("tipologia"))
        if gruppo and gruppo not in scelte:
            continue
        testi = difformita.rilievi(r) if r["atto"] in difformita.ATTI_SEGUITI and r.get("difforme") else []
        c = inviate.get(chiave(r)) or inviate.get(r.get("numero_bando") or "")
        righe.append({**r, "chiave": chiave(r), "n_gestione": mensile.numero_gestione(conn, chiave(r)) if chiave(r) else None,
                      "gruppo_tipologia": gruppo, "rilievi": testi, "con_difformita": bool(testi),
                      "sblocco_graduatoria": da_sbloccare({**r, "rilievi": testi}),
                      "comunicazione": {"stato": "in_attesa"} if in_attesa else {"stato": "in_regola"} if not testi else (
                          {k: c.get(k) for k in ("stato", "quando", "id", "canale")} if c else {"stato": "da_inviare"})})
    righe.sort(key=lambda r: (not r["con_difformita"], tuple(-ord(x) for x in (r.get("data") or ""))))
    scorrimenti_compilato.per_riga(conn, monitoraggio["mese"], righe)
    return righe


def conteggi(righe: list[dict]) -> dict:
    con_difformita = [r for r in righe if r["con_difformita"]]
    per_codice = {}
    for r in con_difformita:
        per_codice.setdefault(r["chiave"], r["comunicazione"]["stato"])
    return {"atti": len(righe), "difformita": len(con_difformita), "bandi": len(per_codice),
            "da_inviare": sum(s == "da_inviare" for s in per_codice.values()),
            "da_confermare": sum(s == "da_confermare" for s in per_codice.values()),
            "inviate": sum(s in ("inviata", "inviata_a_mano") for s in per_codice.values())}


def allineamento(conn, mese_dati: str) -> list[dict]:
    """Per ogni fonte: i dati arrivano fino alla fine del mese di riferimento?"""
    _, fine = punteggi.intervallo(mese_dati)
    fonti = []
    for fonte, nome in (("sol", "Selezioni Online"), ("urp", "URP")):
        ultima = compat.ultima_riuscita(conn, fonte)
        fonti.append({"fonte": fonte, "nome": nome, "aggiornata_il": ultima, "fino_al": (ultima or "")[:10] or None,
                      "allineata": bool(ultima and ultima[:10] >= fine)})
    v = conn.execute("SELECT id, caricata_il FROM segreteria_versione WHERE esito = 'in_uso' ORDER BY id DESC LIMIT 1").fetchone()
    fino = conn.execute("SELECT MAX(data) FROM segreteria_atto WHERE versione_id = ?", (v["id"],)).fetchone()[0] if v else None
    fonti.append({"fonte": "segreteria", "nome": "File segreteria", "aggiornata_il": v["caricata_il"] if v else None,
                  "fino_al": fino, "allineata": bool(fino and fino >= fine)})
    return fonti


def anteprima(conn, mese_dati: str) -> dict:
    """Cosa conterrebbe il monitoraggio di quel mese, prima di crearlo."""
    finto = {"mese": mensile.mese_successivo(mese_dati), "mese_dati": mese_dati, "tipologie": None}
    per_tipologia = {g: conteggi(righe_mese(conn, finto, [g])) for g in mensile.TIPOLOGIE_MONITORABILI}
    return {"id": mensile.id_monitoraggio(finto), "titolo": titolo_mese(mese_dati), "per_tipologia": per_tipologia,
            "allineamento": allineamento(conn, mese_dati), "fonti_in_attesa": atti.fonti_in_attesa(conn),
            "esistente": next((r["mese"] for r in conn.execute("SELECT mese FROM monitoraggio_mese WHERE mese_dati = ?", (mese_dati,))), None)}


# rilievi dei punteggi che indicano: graduatoria già su SOL ma dati da completare (caso A)
_RILIEVI_PUNTEGGI = ("mancano i punteggi", "esito (V/I", "non valorizzato sui candidati",
                     "punteggi su SOL solo per", "nessuna domanda inviata su SOL")

INTESTAZIONE_EMAIL = "Email generata dal sistema di monitoraggio dei bandi."
NOTA_GRADUATORIA = ("Per le graduatorie, il controllo riguarda la graduatoria pubblica con i soli vincitori, allegata su Selezioni Online "
                    "e pubblicata su URP, non quella riservata.")
ISTRUZIONE_A = ("Graduatoria pubblica con i soli vincitori già presente su Selezioni Online: inserite i punteggi e gli esiti (V/I/R/S) di ogni "
                "candidato, poi premete in alto il pulsante che valorizza automaticamente il numero di protocollo della "
                "graduatoria pubblica con i soli vincitori. Se il pulsante non funziona, rispondete a questa email segnalando che avete aggiornato i "
                "dati ma non riuscite a valorizzare il protocollo: provvederemo noi a sbloccare la graduatoria pubblica con i soli vincitori.")
ISTRUZIONE_B = ("Graduatoria pubblica con i soli vincitori non ancora su Selezioni Online: compilate prima i punteggi e gli esiti, poi caricate la "
                "graduatoria pubblica con i soli vincitori come allegato di tipo «graduatoria» indicando data e numero di protocollo; i campi si "
                "valorizzeranno in automatico.")
ISTRUZIONE_C = ("Provvedimento di assunzione idoneo / scorrimento: va inserito a mano su Selezioni Online, con la "
                "relativa data e numero di protocollo.")


def _graduatoria_su_sol(r: dict) -> bool:
    return (r.get("fonti") or {}).get("sol", {}).get("stato") != atti.MANCANTE


def da_sbloccare(riga: dict) -> bool:
    """La graduatoria è su SOL ma il protocollo non è valorizzato: potrebbe servire lo sblocco manuale."""
    return riga.get("atto") == "graduatoria" and _graduatoria_su_sol(riga) and any("non valorizzato sui candidati" in t for t in riga.get("rilievi") or [])


def istruzioni_email(righe: list[dict]) -> list[str]:
    """Le indicazioni su come procedere, solo per i casi presenti tra le difformità del messaggio."""
    out = []
    if any(r["atto"] == "graduatoria" and _graduatoria_su_sol(r)
           and any(any(k in t for k in _RILIEVI_PUNTEGGI) for t in r["rilievi"]) for r in righe):
        out.append(ISTRUZIONE_A)
    if any(r["atto"] == "graduatoria" and not _graduatoria_su_sol(r) for r in righe):
        out.append(ISTRUZIONE_B)
    if any(r["atto"] == "scorrimento" for r in righe):
        out.append(ISTRUZIONE_C)
    return out


def messaggio(conn, monitoraggio: dict, codice: str, righe_del_mese: list[dict] | None = None, sollecito: bool = False) -> dict | None:
    """Il messaggio standard per un codice: i soli rilievi e i soli RdP di quel codice, tolti quelli esclusi a mano.
    `righe_del_mese` evita di ricalcolare il mese quando si preparano più messaggi."""
    tutte = [r for r in (righe_mese(conn, monitoraggio) if righe_del_mese is None else righe_del_mese) if r["chiave"] == codice]
    if not tutte:
        return None
    righe = [r for r in tutte if r["con_difformita"]]
    r0 = (righe or tutte)[0]
    scelte = mensile.indirizzi_messaggio(conn, monitoraggio["mese"], codice)
    referenti, visti = [], set()
    for r in righe or tutte:
        for p in r.get("rdp") or []:
            email = (p.get("email") or "").strip().lower()
            if email and email not in visti:
                visti.add(email)
                referenti.append({"nome": " ".join(x for x in (p.get("nome"), p.get("cognome")) if x), "email": email,
                                  "escluso": email in scelte["esclusi"]})
    attivi = [p for p in referenti if not p["escluso"]]
    destinatari = [p["email"] for p in attivi]
    coordinatore = next((r["coordinatore"] for r in righe or tutte if r.get("coordinatore")), None)
    # gli RdP sono i destinatari; il coordinatore va in copia solo se l'amministratore lo spunta (se è anche RdP resta destinatario)
    gia_destinatario = bool(coordinatore and coordinatore["email"] in destinatari)
    incluso = bool(coordinatore and scelte["coordinatore"] and not gia_destinatario)
    in_copia = [*scelte["cc"], *([coordinatore["email"]] if incluso and coordinatore["email"] not in scelte["cc"] else [])]
    mese_testo = titolo_mese(monitoraggio["mese_dati"])
    n = sum(len(r["rilievi"]) for r in righe)
    voci = []
    for i, r in enumerate(righe, 1):
        tipo = {"graduatoria": "Graduatoria pubblica con i soli vincitori", "scorrimento": "Provvedimento di assunzione idoneo / scorrimento"}.get(r["atto"], r["atto"])
        testa = f"{i}) {tipo} del {_data_it(r.get('data'))}" + (f" – prot. {r['protocollo']}" if r.get("protocollo") else "")
        voci.append("\n".join([testa, *[f"   – {t}" for t in r["rilievi"]]]))
    saluto = f"Gentile {attivi[0]['nome']}," if len(attivi) == 1 and attivi[0]["nome"] else "Gentili tutte e tutti,"
    titolo = f" – {r0['titolo_bando']}" if r0.get("titolo_bando") else ""
    if sollecito:
        quando = r0["comunicazione"].get("quando")
        apertura = (f"vi chiedo gentilmente un riscontro in merito alle richieste di aggiornamento indicate nella email{f' del {_data_it(quando)}' if quando else ''}, relativa "
                    f"al monitoraggio mensile di {mese_testo} per il bando {codice}{titolo}. Dai dati attualmente disponibili, risultano ancora da aggiornare i seguenti punti:")
    else:
        apertura = (f"nell'ambito del monitoraggio mensile di {mese_testo}, per il bando {codice}{titolo} "
                    f"risultano le seguenti difformità tra le fonti:")
    corpo = f"{INTESTAZIONE_EMAIL}\n\n{saluto}\n\n{apertura}\n\n" + "\n\n".join(voci)
    con_graduatoria = any(r["atto"] == "graduatoria" for r in righe)
    if con_graduatoria:
        corpo += f"\n\n{NOTA_GRADUATORIA}"
    istruzioni = istruzioni_email(righe)
    if istruzioni:
        corpo += "\n\nCome procedere:\n" + "\n".join(f"- {x}" for x in istruzioni)
    copia = f" lasciando in copia il mio indirizzo ({posta.contatto_ufficio()})" if posta.contatto_ufficio() else ""
    aggiornamento = "l'aggiornamento della graduatoria pubblica con i soli vincitori e dei dati" if con_graduatoria else "l'aggiornamento dei dati"
    if sollecito:
        corpo += ("\n\nSe aveste già provveduto, vi preghiamo di scusarci: i nostri dati si aggiornano periodicamente e la correzione potrebbe "
                  "non essere ancora visibile. In caso di dubbi o difficoltà, siamo a disposizione per aiutarvi.")
    corpo += (f"\n\nUna volta completato {aggiornamento}, {'potete rispondere' if sollecito else 'vi chiedo di rispondere'} a questa "
              f"email{copia}, così posso ricontrollare i dati.{' Grazie per la collaborazione.' if sollecito else ''}\n\nCordiali saluti,\n{posta.impostazioni_email()['firma']}\n")
    if r0.get("link_codice"):
        corpo += f"\nScheda su Selezioni Online: {r0['link_codice']}\n"
    storico = mensile.registro_comunicazioni(conn, monitoraggio["mese"], codice)
    precedente = next((s for s in storico if s["stato"] == "inviata" and s.get("oggetto")), {}) if sollecito else {}
    oggetto = f"Monitoraggio {mese_testo}. Bando n° {codice}: Aggiornamento Dati{' Graduatoria Pubblica' if con_graduatoria else ''} – Rif. {r0.get('n_gestione')}"
    if sollecito:  # stesso oggetto dell'email inviata, come una risposta: resta nella stessa conversazione
        oggetto = "R: " + re.sub(r"^(?:R: |Promemoria – )+", "", precedente.get("oggetto") or oggetto)
    return {"chiave": codice, "n_gestione": r0.get("n_gestione"), "numero_bando": r0.get("numero_bando"), "titolo_bando": r0.get("titolo_bando"), "referenti": referenti,
            "destinatari": destinatari, "esclusi": scelte["esclusi"], "cc_ufficio": posta.copia_fissa(), "cc_aggiunti": scelte["cc"],
            "coordinatore": {**coordinatore, "incluso": incluso, "destinatario": gia_destinatario} if coordinatore else None, "cc_invio": in_copia,
            "cc": posta.copia_effettiva(destinatari, in_copia), "oggetto": oggetto, "message_id_precedente": precedente.get("message_id"),
            "corpo": corpo, "n_difformita": n, "stato": (righe or tutte)[0]["comunicazione"]["stato"],
            "storico": storico, "posta": posta.stato()}


def contiene_dati_candidati(*testi: str) -> bool:
    return any(re.search(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", t or "", re.I) for t in testi)


def da_comunicare(conn) -> int:
    """Per il badge del menu: codici con difformità aperte e nessun invio, nei monitoraggi in corso."""
    if atti.fonti_in_attesa(conn):
        return 0
    totale = 0
    for m in conn.execute("SELECT mese FROM monitoraggio_mese WHERE stato = 'aperto'").fetchall():
        inviate = mensile.solleciti(conn, m["mese"])
        codici = {r["codice"] or r["numero_bando"] for r in conn.execute("SELECT codice, numero_bando FROM difformita WHERE mese = ? AND stato = 'aperta'", (m["mese"],))}
        totale += sum(1 for c in codici if c not in inviate)
    return totale
