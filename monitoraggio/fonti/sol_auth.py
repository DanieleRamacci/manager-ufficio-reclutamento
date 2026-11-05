"""Selezioni Online con la sessione dell'utente (spec 004): domande e punteggi di un bando.

Stesse condizioni dell'estrazione "Punteggi" di SOL (PrintService.extractionApplicationForPunteggi):
domande confermate (stato C) e non escluse/rinunciate; quelle con i punteggi hanno l'aspetto
`jconon_application:aspect_punteggi`. I campi sono quelli di PrintService.getRecordCSVPunteggi.
"""
from .. import config
from .http import FonteErrore

FILTRO_DOMANDE = ("root.jconon_application:stato_domanda = 'C' "
                  "AND root.jconon_application:esclusione_rinuncia IS NULL")
PAGINA = 100

# campo dell'estrazione -> proprietà della domanda su SOL
CAMPI_CANDIDATO = {
    "cognome": "jconon_application:cognome",
    "nome": "jconon_application:nome",
    "data_nascita": "jconon_application:data_nascita",
    "codice_fiscale": "jconon_application:codice_fiscale",
    "username": "jconon_application:user",
    "email": "jconon_application:email_comunicazioni",
    "email_pec": "jconon_application:email_pec_comunicazioni",
    "totale_punteggio": "jconon_application:totale_punteggio",
    "graduatoria": "jconon_application:graduatoria",
    "esito": "jconon_application:esito_call",
    "note": "jconon_application:punteggio_note",
    "data_protocollo_graduatoria": "jconon_application:protocollo_data_graduatoria",
    "numero_protocollo_graduatoria": "jconon_application:protocollo_numero_graduatoria",
    "data_protocollo_assunzione_idoneo": "jconon_application:protocollo_data_assunzione_idoneo",
    "numero_protocollo_assunzione_idoneo": "jconon_application:protocollo_numero_assunzione_idoneo",
}

# punteggio N del bando (jconon_call:punteggio_N, con l'etichetta della prova) -> campi della domanda
# (modello jconon_application_folder.xml: "Punteggio 1" = punteggio_titoli, ...; PrintService per 6 e 7)
PUNTEGGI_PROVE = {
    1: ("jconon_application:punteggio_titoli", "jconon_application:fl_punteggio_titoli"),
    2: ("jconon_application:punteggio_scritto", "jconon_application:fl_punteggio_scritto"),
    3: ("jconon_application:punteggio_secondo_scritto", "jconon_application:fl_punteggio_secondo_scritto"),
    4: ("jconon_application:punteggio_colloquio", "jconon_application:fl_punteggio_colloquio"),
    5: ("jconon_application:punteggio_prova_pratica", "jconon_application:fl_punteggio_prova_pratica"),
    6: ("jconon_application:punteggio_6", None),
    7: ("jconon_application:punteggio_7", None),
}


def query_domande(call_id: str) -> str:
    return (f"SELECT root.cmis:objectId FROM jconon_application:folder root "
            f"WHERE {FILTRO_DOMANDE} AND IN_TREE(root, '{call_id}')")


def query_con_punteggi(call_id: str) -> str:
    return (f"SELECT root.cmis:objectId FROM jconon_application:folder root "
            f"JOIN jconon_application:aspect_punteggi p ON root.cmis:objectId = p.cmis:objectId "
            f"WHERE {FILTRO_DOMANDE} AND IN_TREE(root, '{call_id}')")


def _risposta(dati) -> dict:
    if not isinstance(dati, dict) or "error" in dati:
        errore = dati.get("error") if isinstance(dati, dict) else "risposta inattesa"
        raise FonteErrore(f"Selezioni Online: {errore}")
    return dati


def conta(client, query: str, intestazioni: dict) -> int:
    """Numero di risultati di una ricerca CMIS autenticata (senza scaricare gli elementi)."""
    dati = _risposta(client.get_json(config.sol_search_url(), {
        "ajax": "true", "maxItems": 1, "skipCount": 0, "calculateTotalNumItems": "true", "q": query,
    }, intestazioni))
    if "totalNumItems" not in dati:
        raise FonteErrore("Selezioni Online: totale non restituito")
    return int(dati["totalNumItems"])


def _cerca(client, query: str, intestazioni: dict) -> list[dict]:
    """Tutte le pagine di una ricerca autenticata, con gli oggetti completi (fetchCmisObject)."""
    items, skip, totale = [], 0, None
    while True:
        dati = _risposta(client.get_json(config.sol_search_url(), {
            "ajax": "true", "maxItems": PAGINA, "skipCount": skip, "fetchCmisObject": "true",
            "calculateTotalNumItems": "true", "q": query,
        }, intestazioni))
        pagina = dati.get("items") or []
        items.extend(pagina)
        totale = totale if totale is not None else dati.get("totalNumItems")
        # hasMoreItems non basta: SOL risponde false anche quando a fine pagina manca ancora qualcosa (es. 100 su 101)
        if not pagina or (len(items) >= totale if totale is not None else not dati.get("hasMoreItems")):
            if totale is not None and len(items) != totale:
                raise FonteErrore(f"Selezioni Online: trovati {len(items)} elementi su {totale} dichiarati")
            return items
        skip += len(pagina)


def candidato(item: dict) -> dict:
    c = {campo: item.get(prop) for campo, prop in CAMPI_CANDIDATO.items()}
    c["prove"] = {str(n): {"punteggio": item.get(campo), "non_ammesso": bool(item.get(flag)) if flag else False}
                  for n, (campo, flag) in PUNTEGGI_PROVE.items()}
    return c


def punteggi_bando(client, call_id: str, intestazioni: dict) -> dict:
    """Domande confermate e candidati con i punteggi (con esito e protocollo della graduatoria)."""
    domande = conta(client, query_domande(call_id), intestazioni)
    candidati = [candidato(i) for i in _cerca(client, query_con_punteggi(call_id), intestazioni)]
    if candidati and all(c["cognome"] is None and c["esito"] is None for c in candidati):
        raise FonteErrore("Selezioni Online non ha restituito i campi delle domande")
    return {"domande": domande, "con_punteggi": len(candidati), "candidati": candidati}
