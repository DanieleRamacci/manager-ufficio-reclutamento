"""Selezioni Online: RdP dei bandi da openapi/v1/call con il token SSO dell'utente (spec 003).

Come in chekin-cnr-concorsi: `Authorization: Bearer <token>`, nessuna credenziale salvata.
In alternativa `token` può essere già l'header col ticket di SOL (monitoraggio/accesso.py).
"""
import os

from .http import FonteErrore

PAGINA = 100
MAX_PAGINE = 200


def _intestazioni(token) -> dict:
    if isinstance(token, dict):
        return token
    return {"Authorization": f"Bearer {token}"} if token else {}


def base_url() -> str:
    return os.environ.get("JCONON_BASE_URL", "https://selezionionline.cnr.it/jconon").rstrip("/")


def bandi_con_rdp(client, token: str | dict | None) -> list[dict]:
    """Tutti i bandi con la lista `rdps`, letti pagina per pagina.

    `token` None = lettura senza login: eccezione temporanea solo per la prova locale finché
    l'API risponde senza autenticazione (spec 003, FR-001a).
    """
    items: list[dict] = []
    intestazioni = _intestazioni(token)
    for pagina in range(MAX_PAGINE):
        dati = client.get_json(f"{base_url()}/openapi/v1/call",
                               {"page": pagina, "offset": PAGINA, "filterType": "all", "detailRdP": "true",
                                "detailCommission": "false"},
                               intestazioni)
        lotto = dati.get("items") if isinstance(dati, dict) else None
        if not isinstance(lotto, list):
            raise FonteErrore("Selezioni Online: risposta inattesa da openapi/v1/call")
        items.extend(lotto)
        if len(lotto) < PAGINA or not dati.get("hasMoreItems", True):
            return items
    raise FonteErrore("Selezioni Online: troppe pagine da openapi/v1/call")


def rdp_bando(client, token: str | dict | None, codice: str, object_id: str | None = None) -> list[dict] | None:
    """RdP di un solo bando (richiesta per `callCode`, circa 1 s contro 0,3 s a bando per le
    pagine con dettaglio RdP, che oltre 50 bandi superano i 30 s). None se il bando non c'è."""
    intestazioni = _intestazioni(token)
    dati = client.get_json(f"{base_url()}/openapi/v1/call",
                           {"page": 0, "offset": 10, "filterType": "all", "callCode": codice,
                            "detailRdP": "true", "detailCommission": "false"}, intestazioni)
    items = dati.get("items") if isinstance(dati, dict) else None
    if not isinstance(items, list):
        raise FonteErrore("Selezioni Online: risposta inattesa da openapi/v1/call")
    item = next((i for i in items if object_id and i.get("cmis:objectId") == object_id), None) \
        or next((i for i in items if (i.get("jconon_call:codice") or "").strip() == codice), None)
    return None if item is None else (item.get("rdps") or [])


def persona(rdp: dict) -> dict:
    """Solo i dati necessari (spec 003, FR-004): niente codice fiscale, matricola, email personali."""
    email = (rdp.get("email") or "").strip().lower() or None
    username = (rdp.get("userName") or "").strip() or None
    return {"chiave": username or email or f"{rdp.get('firstName', '')} {rdp.get('lastName', '')}".strip().lower(),
            "nome": (rdp.get("firstName") or "").strip() or None,
            "cognome": (rdp.get("lastName") or "").strip() or None,
            "email": email, "username": username}
