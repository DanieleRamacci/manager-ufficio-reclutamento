"""Atti del monitoraggio, messaggi ai referenti e allineamento delle fonti (specifiche grafiche, sezioni 3.2-3.5)."""
import re

from . import atti, compat, difformita, excel_mese, mensile, posta, punteggi

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
                      "comunicazione": {"stato": "in_attesa"} if in_attesa else {"stato": "in_regola"} if not testi else (
                          {k: c.get(k) for k in ("stato", "quando", "id", "canale")} if c else {"stato": "da_inviare"})})
    righe.sort(key=lambda r: (not r["con_difformita"], tuple(-ord(x) for x in (r.get("data") or ""))))
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


def messaggio(conn, monitoraggio: dict, codice: str) -> dict | None:
    """Il messaggio standard per un codice: i soli rilievi e i soli RdP di quel codice."""
    righe = [r for r in righe_mese(conn, monitoraggio) if r["chiave"] == codice and r["con_difformita"]]
    tutte = [r for r in righe_mese(conn, monitoraggio) if r["chiave"] == codice]
    if not tutte:
        return None
    r0 = (righe or tutte)[0]
    referenti, visti = [], set()
    for r in righe or tutte:
        for p in r.get("rdp") or []:
            email = (p.get("email") or "").strip().lower()
            if email and email not in visti:
                visti.add(email)
                referenti.append({"nome": " ".join(x for x in (p.get("nome"), p.get("cognome")) if x), "email": email})
    id_m = mensile.id_monitoraggio(monitoraggio)
    mese_testo = titolo_mese(monitoraggio["mese_dati"])
    n = sum(len(r["rilievi"]) for r in righe)
    voci = []
    for i, r in enumerate(righe, 1):
        tipo = {"graduatoria": "Graduatoria", "scorrimento": "Provvedimento di assunzione idoneo / scorrimento"}.get(r["atto"], r["atto"])
        testa = f"{i}) {tipo} del {_data_it(r.get('data'))}" + (f" – prot. {r['protocollo']}" if r.get("protocollo") else "")
        voci.append("\n".join([testa, *[f"   – {t}" for t in r["rilievi"]]]))
    saluto = f"Gentile {referenti[0]['nome']}," if len(referenti) == 1 and referenti[0]["nome"] else "Gentili tutte e tutti,"
    titolo = f" – {r0['titolo_bando']}" if r0.get("titolo_bando") else ""
    corpo = (f"{saluto}\n\nnell'ambito del monitoraggio mensile di {mese_testo} (rif. {id_m}), per il bando {codice}{titolo} "
             f"risultano le seguenti difformità tra le fonti:\n\n" + "\n\n".join(voci) +
             "\n\nVi chiediamo di provvedere all'inserimento o alla correzione sulle piattaforme indicate, utilizzando lo stesso "
             "numero di protocollo, e di darne riscontro rispondendo a questa email.\n\nCordiali saluti,\n"
             f"{posta.impostazioni_email()['firma']}\n")
    if r0.get("link_codice"):
        corpo += f"\nScheda su Selezioni Online: {r0['link_codice']}\n"
    return {"chiave": codice, "n_gestione": r0.get("n_gestione"), "numero_bando": r0.get("numero_bando"), "titolo_bando": r0.get("titolo_bando"), "referenti": referenti,
            "destinatari": [p["email"] for p in referenti], "oggetto": f"Monitoraggio {mese_testo}. Bando n° {codice}: Aggiornamento Dati – Rif. {r0.get('n_gestione')}",
            "corpo": corpo, "n_difformita": n, "stato": (righe or tutte)[0]["comunicazione"]["stato"],
            "storico": mensile.registro_comunicazioni(conn, monitoraggio["mese"], codice), "posta": posta.stato()}


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
