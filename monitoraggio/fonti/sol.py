"""Selezioni Online: ricerca pubblica dei bandi e dei loro allegati (research R1-R3)."""
import json
from urllib.parse import quote

from .. import config
from ..classifica import classifica
from ..normalizza import codice_norm, codice_sede, codice_sotto, data_iso, numero_bando, protocollo
from .http import FonteErrore

TIPO_COMMISSIONE = "D:jconon_commissione"
PREFISSO_ALLEGATO_BANDO = "D:jconon_attachment:call"


def query_bandi(tipo: str) -> str:
    return (f"SELECT * FROM jconon_call:folder root WHERE root.cmis:objectTypeId = '{tipo}' "
            f"AND IN_TREE (root,'{config.SOL_TREE_UUID}') "
            f"ORDER BY jconon_call:data_fine_invio_domande_index DESC")


def query_allegati(object_id: str) -> str:
    # IN_TREE e non IN_FOLDER: in alcuni bandi graduatorie e provvedimenti non sono nel primo livello della scheda
    return f"SELECT * FROM jconon_attachment:document root WHERE IN_TREE(root,'{object_id}')"


def _cerca(client, query: str) -> tuple[list[dict], int]:
    """Tutte le pagine di una ricerca CMIS, con controllo sul totale dichiarato."""
    items: dict[str, dict] = {}
    totale = None
    skip = 0
    while True:
        dati = client.get_json(config.sol_search_url(), {
            "guest": "true", "ajax": "true", "maxItems": config.SOL_PAGE_SIZE, "skipCount": skip,
            "fetchCmisObject": "true", "calculateTotalNumItems": "true", "q": query,
        })
        if not isinstance(dati, dict) or "error" in dati:
            errore = dati.get("error") if isinstance(dati, dict) else dati
            raise FonteErrore(f"Selezioni Online: {errore}")
        pagina = dati.get("items") or []
        if totale is None:
            totale = dati.get("totalNumItems")
        for item in pagina:
            items.setdefault(item.get("cmis:objectId"), item)
        # hasMoreItems non basta: SOL risponde false anche quando a fine pagina manca ancora qualcosa (es. 100 su 101)
        if not pagina or (len(items) >= totale if totale is not None else not dati.get("hasMoreItems")):
            break
        skip += len(pagina)
    if totale is not None and len(items) != totale:
        raise FonteErrore(f"Selezioni Online: trovati {len(items)} elementi su {totale} dichiarati")
    return list(items.values()), totale if totale is not None else len(items)


def cerca_bandi(client, tipo: str) -> tuple[list[dict], int]:
    return _cerca(client, query_bandi(tipo))


def url_bando(codice: str | None) -> str:
    return f"{config.SOL_BASE}/call-detail?callCode={quote(codice or '')}"


def url_punteggi(object_id: str) -> str:
    """Pagina di SOL dove l'RdP inserisce i punteggi del bando (richiede il login)."""
    return f"{config.SOL_BASE}/carica-punteggi?callId={quote(object_id)}"


def scheda_da_item(item: dict, tipo: str) -> dict:
    codice = (item.get("jconon_call:codice") or "").strip() or None
    punteggi = []
    for i in range(1, 11):
        nome = item.get(f"jconon_call:punteggio_{i}")
        if nome:
            punteggi.append({"n": i, "nome": nome, "min": item.get(f"jconon_call:punteggio_{i}_min"),
                             "max": item.get(f"jconon_call:punteggio_{i}_limite")})
    extra = {
        "tipo_sol": tipo,
        "profilo": item.get("jconon_call:profilo"),
        "sede": item.get("jconon_call:sede"),
        "struttura_destinataria": item.get("jconon_call:struttura_destinataria"),
        "numero_posti": item.get("jconon_call:numero_posti"),
        "gruppo_rdp": item.get("jconon_call:rdp"),
        "commissione": item.get("jconon_call:commissione"),
        "stato": item.get("jconon_call:stato"),
        "data_inizio_invio_domande": item.get("jconon_call:data_inizio_invio_domande"),
        "data_fine_invio_domande": item.get("jconon_call:data_fine_invio_domande"),
        "punteggi": punteggi,
        "node_ref": item.get("alfcmis:nodeRef"),
    }
    return {
        "id_esterno": item["cmis:objectId"],
        "id_padre": item.get("cmis:parentId"),
        "sezione": tipo,
        "tipologia": config.SOL_TIPI.get(tipo),
        "codice_originale": codice,
        "codice_norm": codice_norm(codice),
        "numero_bando": numero_bando(codice),
        "codice_sotto": codice_sotto(codice) or codice_sede(codice) or codice_sotto(item.get("cmis:name")),
        "titolo": item.get("cmis:name"),
        "protocollo": None,
        "protocollo_originale": None,
        "data_pubblicazione": data_iso(item.get("jconon_call:data_pubblicazione_inpa")),
        "data_pubbl_graduatoria": data_iso(item.get("jconon_call:data_pubbl_graduatoria")),
        "url": url_bando(codice),
        "dati_extra": json.dumps(extra, ensure_ascii=False, sort_keys=True),
        "modificata_fonte_il": item.get("cmis:lastModificationDate"),
        "documenti": None,  # riempito solo se gli allegati vengono letti in questa raccolta
    }


def documento_da_item(item: dict, url_scheda: str | None = None) -> dict:
    nome = item.get("cmis:name") or ""
    tipo = item.get("cmis:objectTypeId")
    cat, sotto, ordinale = classifica(nome, tipo)
    prot = (item.get("jconon_protocollo:numero") or "").strip() or None
    return {
        "id_esterno": item["cmis:objectId"],
        "titolo": nome,
        "categoria": cat,
        "sottotipo": sotto,
        "sottotipo_ordinale": ordinale,
        "sottotipo_origine": "titolo" if sotto else None,
        "tipo_fonte": tipo,
        "protocollo": protocollo(prot),
        "protocollo_originale": prot,
        "data_protocollo": data_iso(item.get("jconon_protocollo:data")),
        # il download diretto richiede il login: si rimanda alla pagina pubblica del bando
        "url": url_scheda,
    }


def togli_documenti_dei_figli(schede: list[dict], documenti_noti: dict[str, set[str]] | None = None) -> None:
    """Nei bandi con più codici i codici stanno dentro la scheda padre: leggendo l'albero del padre
    tornano anche i loro documenti, che appartengono al codice. `documenti_noti`: id dei documenti già
    salvati per le schede, per i codici non riletti in questa raccolta."""
    noti = documenti_noti or {}
    figli: dict[str, set[str]] = {}
    for s in schede:
        if s.get("id_padre"):
            letti = s.get("documenti")
            figli.setdefault(s["id_padre"], set()).update(
                {d["id_esterno"] for d in letti} if letti is not None else noti.get(s["id_esterno"], set()))
    for s in schede:
        if s.get("documenti") is not None and s["id_esterno"] in figli:
            s["documenti"] = [d for d in s["documenti"] if d["id_esterno"] not in figli[s["id_esterno"]]]


def _allegato_del_bando(item: dict) -> bool:
    """Solo i documenti del bando: l'albero della scheda contiene anche le domande dei candidati."""
    tipo = item.get("cmis:objectTypeId") or ""
    return tipo.startswith(PREFISSO_ALLEGATO_BANDO) and not tipo.startswith(TIPO_COMMISSIONE)


def allegati_bando(client, object_id: str, url_scheda: str | None = None) -> list[dict]:
    items, _ = _cerca(client, query_allegati(object_id))
    return [documento_da_item(it, url_scheda) for it in items if _allegato_del_bando(it)]
