#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scarica i bandi da /openapi/v1/call (payload con chiave 'items') e,
per ciascun bando, recupera i membri del gruppo RDP con:
  /rest/proxy?url=service/cnr/groups/children&ajax=true&fullName=GROUP_<jconon_call:rdp>

Scrive: bandi-con-rdp.json

ENV:
  BASE_URL    (default: https://cool-jconon.test.si.cnr.it)
  AUTH_B64    (Basic base64, es. admin:admin => YWRtaW46YWRtaW4=)
  USERNAME    (alternativa a AUTH_B64)
  PASSWORD    (alternativa a AUTH_B64)
  OFFSET      (default: 20)  # numero di elementi per pagina (coerente con il payload)
  FILTER_TYPE (default: active)
"""

import os
import json
import time
import base64
import sys
from urllib.parse import urlencode, quote
import urllib.request
import urllib.error
import re

BASE_URL    = os.environ.get("BASE_URL", "https://selezionionline.cnr.it/jconon/")
AUTH_B64    = os.environ.get("AUTH_B64", "")
USERNAME    = os.environ.get("USERNAME", "daniele.ramacci")
PASSWORD    = os.environ.get("PASSWORD", "abcCBA123$salulinkcnr")
OFFSET      = int(os.environ.get("OFFSET", "20"))  # nel tuo esempio offset=20
FILTER_TYPE = os.environ.get("FILTER_TYPE", "all")
OUT_PATH    = "bandi-con-rdp.json"


def fetch_group_fullname(short_name: str) -> str:
    """
    Chiama:
      /rest/proxy?url=service/cnr/groups/group&ajax=true&shortName=<RDP_...>
    e restituisce il fullName (es. GROUP_RDP_999.999_<uuid>).
    """
    short_name = (short_name or "").strip()
    if not short_name:
        return ""

    headers = {"accept": "application/json"}
    ah = _auth_header()
    if ah:
        headers["Authorization"] = ah

    url = (f"{BASE_URL}/rest/proxy"
           f"?url=service/cnr/groups/group&ajax=true&shortName={quote(short_name)}")
    raw = _http_get(url, headers=headers)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        # fallback: se non funziona, provo con GROUP_<short_name>
        return f"GROUP_{short_name}" if not short_name.startswith("GROUP_") else short_name

    # vari formati possibili
    if isinstance(data, dict):
        full = data.get("fullName") or (data.get("attr") or {}).get("id")
        if full:
            return full
    elif isinstance(data, list) and data:
        first = data[0]
        full = first.get("fullName") or (first.get("attr") or {}).get("id")
        if full:
            return full

    return f"GROUP_{short_name}" if not short_name.startswith("GROUP_") else short_name


def _auth_header() -> str:
    if AUTH_B64:
        return f"Basic {AUTH_B64}"
    if USERNAME or PASSWORD:
        token = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"
    return ""

def _http_get(url: str, headers: dict | None = None, retry: int = 2, sleep: float = 0.6) -> bytes:
    last_err = None
    for _ in range(retry + 1):
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            time.sleep(sleep)
    raise last_err  # type: ignore[misc]

def _extract_uuid_from_nodeRef(node_ref: str) -> str:
    # es: "workspace://SpacesStore/41c09ab3-69eb-4988-9f8f-43c2004ffbca"
    if not node_ref:
        return ""
    m = re.search(r"/([0-9a-fA-F-]{36})$", node_ref)
    return m.group(1) if m else ""
def fetch_calls(offset: int | None = None, filter_type: str | None = None) -> list[dict]:
    """
    Legge /openapi/v1/call con paginazione.
    Parametri opzionali:
      - offset: numero di elementi per pagina (default = OFFSET del modulo)
      - filter_type: 'active' | 'all' | ...
    Restituisce [{uuid, codice, titolo, rdp_raw}, ...]
    """
    results: list[dict] = []
    page = 0

    headers = {"accept": "application/json"}
    ah = _auth_header()
    if ah:
        headers["Authorization"] = ah

    off = OFFSET if offset is None else int(offset)
    ft = FILTER_TYPE if filter_type is None else str(filter_type)

    while True:
        qs = urlencode({"page": page, "offset": off, "filterType": ft})
        # Nota: BASE_URL finisce con '/', l'URL seguente ha una sola '/':
        url = f"{BASE_URL}openapi/v1/call?{qs}"
        raw = _http_get(url, headers=headers)
        data = json.loads(raw.decode("utf-8"))

        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            break

        for it in items:
            node_ref = it.get("alfcmis:nodeRef", "")
            object_id = it.get("cmis:objectId", "")
            uuid = _extract_uuid_from_nodeRef(node_ref) or str(object_id)
            codice = str(it.get("jconon_call:codice") or "").strip()
            titolo = str(it.get("cmis:name") or it.get("jconon_call:descrizione_ridotta") or "").strip()
            rdp_raw = str(it.get("jconon_call:rdp") or "").strip()
            results.append({"uuid": uuid, "codice": codice, "titolo": titolo, "rdp_raw": rdp_raw})

        if not data.get("hasMoreItems"):
            break
        page += 1

    return results


def build_group_fullname(rdp_raw: str) -> str:
    """
    Dal campo jconon_call:rdp (es. 'RDP_999.999_<uuid>') ottiene il nome gruppo completo:
      'GROUP_' + rdp_raw  => 'GROUP_RDP_999.999_<uuid>'
    """
    rdp_raw = (rdp_raw or "").strip()
    if not rdp_raw:
        return ""
    if rdp_raw.startswith("GROUP_"):
        return rdp_raw
    return f"GROUP_{rdp_raw}"

def fetch_rdp_members(group_fullname: str) -> list[str]:
    """
    /rest/proxy?url=service/cnr/groups/children&ajax=true&fullName=<GROUP_RDP_...>
    Restituisce una lista di nomi membri.
    """
    if not group_fullname:
        return []

    headers = {"accept": "application/json"}
    ah = _auth_header()
    if ah:
        headers["Authorization"] = ah

    url = (
        f"{BASE_URL}/rest/proxy"
        f"?url=service/cnr/groups/children&ajax=true&fullName={quote(group_fullname)}"
    )
    raw = _http_get(url, headers=headers)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return []

    # nei tuoi payload è una lista con oggetti {attr:…, data: "NOME"}
    rows = data if isinstance(data, list) else []
    members: list[str] = []
    for r in rows:
        val = r.get("data") or (r.get("attr") or {}).get("userName") or ""
        if val:
            members.append(val.strip())
    return members


