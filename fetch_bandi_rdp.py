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
import html
from urllib.parse import urlencode, quote, urlparse, parse_qs
import urllib.request
import urllib.error
import re
import requests
from bs4 import BeautifulSoup
try:
    import xlrd  # type: ignore
except Exception:
    xlrd = None

DEFAULT_JCONON_BASE_URL = "https://selezionionline.cnr.it/jconon"
BASE_URL    = os.environ.get("JCONON_BASE_URL") or os.environ.get("BASE_URL", DEFAULT_JCONON_BASE_URL)
AUTH_B64    = os.environ.get("JCONON_AUTH_B64") or os.environ.get("AUTH_B64", "")
USERNAME    = os.environ.get("JCONON_USERNAME") or os.environ.get("USERNAME", "")
PASSWORD    = os.environ.get("JCONON_PASSWORD") or os.environ.get("PASSWORD", "")
ALF_TICKET  = os.environ.get("JCONON_ALF_TICKET") or os.environ.get("X_ALFRESCO_TICKET", "")
JCONON_COOKIE = os.environ.get("JCONON_COOKIE", "")
OIDC_TOKEN_URL = os.environ.get("OIDC_TOKEN_URL", "")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
OIDC_SCOPE = os.environ.get("OIDC_SCOPE", "openid profile email roles")
OFFSET      = int(os.environ.get("OFFSET", "20"))  # nel tuo esempio offset=20
FILTER_TYPE = os.environ.get("FILTER_TYPE", "all")
OUT_PATH    = "bandi-con-rdp.json"
_SESSION_CACHE = {"session": None, "ts": 0.0, "alf_ticket": "", "cookie": ""}
_TOKEN_CACHE = {"access_token": "", "exp": 0.0}


def _clean_secret(v: str) -> str:
    s = (v or "").strip()
    if len(s) >= 2 and ((s[0] == "'" and s[-1] == "'") or (s[0] == '"' and s[-1] == '"')):
        return s[1:-1]
    return s


def _base_url() -> str:
    """
    Restituisce la base URL JCONON senza slash finale.
    Se BASE_URL punta al server locale dell'app (localhost/127.0.0.1),
    usa il default esterno per evitare loop/login HTML.
    """
    base = str(BASE_URL or "").strip().rstrip("/")
    if re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", base, flags=re.IGNORECASE):
        return DEFAULT_JCONON_BASE_URL
    return base or DEFAULT_JCONON_BASE_URL


def _loads_json(raw: bytes, context: str) -> dict | list:
    text = (raw or b"").decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError(f"Risposta vuota da {context}")
    try:
        return json.loads(text)
    except Exception as e:
        preview = text[:200].replace("\n", " ")
        raise ValueError(
            f"Risposta non JSON da {context}. Possibile redirect/login. Preview: {preview}"
        ) from e


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

    url = (f"{_base_url()}/rest/proxy"
           f"?url=service/cnr/groups/group&ajax=true&shortName={quote(short_name)}")
    raw = _http_get(url, headers=headers)
    try:
        data = _loads_json(raw, "groups/group")
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
    bh = _bearer_header()
    if bh:
        return bh
    if AUTH_B64:
        return f"Basic {AUTH_B64}"
    pwd = _clean_secret(PASSWORD)
    if USERNAME or pwd:
        token = base64.b64encode(f"{USERNAME}:{pwd}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"
    return ""


def _bearer_header(force_refresh: bool = False) -> str:
    """
    Tenta OAuth2 password grant usando OIDC_* del progetto.
    Se non disponibile/fallisce, ritorna stringa vuota e resta attivo il fallback Basic.
    """
    now = time.time()
    if (not force_refresh) and _TOKEN_CACHE.get("access_token") and now < float(_TOKEN_CACHE.get("exp") or 0) - 30:
        return f"Bearer {_TOKEN_CACHE['access_token']}"

    token_url = (OIDC_TOKEN_URL or "").strip()
    client_id = (OIDC_CLIENT_ID or "").strip()
    user_candidates = _candidate_usernames()
    pwd = (PASSWORD or "").strip()
    if not token_url or not client_id or not pwd or not user_candidates:
        return ""

    for u in user_candidates:
        data = {
            "grant_type": "password",
            "client_id": client_id,
            "username": u,
            "password": pwd,
            "scope": OIDC_SCOPE,
        }
        if OIDC_CLIENT_SECRET:
            data["client_secret"] = OIDC_CLIENT_SECRET
        try:
            r = requests.post(token_url, data=data, timeout=20)
            if r.status_code >= 400:
                continue
            j = r.json() if r.content else {}
            tok = str(j.get("access_token") or "").strip()
            if tok:
                exp_in = int(j.get("expires_in") or 300)
                _TOKEN_CACHE["access_token"] = tok
                _TOKEN_CACHE["exp"] = now + max(60, exp_in)
                return f"Bearer {tok}"
        except Exception:
            continue
    return ""


def _extra_auth_headers() -> dict:
    """
    Header auth aggiuntivi usati da alcune installazioni JCONON/Alfresco.
    """
    h = {}
    t = (ALF_TICKET or _SESSION_CACHE.get("alf_ticket") or "").strip()
    if t:
        h["X-alfresco-ticket"] = t
    ck = (JCONON_COOKIE or _SESSION_CACHE.get("cookie") or "").strip()
    if ck:
        h["Cookie"] = ck
    return h


def _extract_ticket_and_cookie(resp: requests.Response) -> tuple[str, str]:
    ticket = ""
    cookie = ""
    try:
        data = resp.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        for k in ("ticket", "alfrescoTicket", "alfresco_ticket"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                ticket = v.strip()
                break
        if not ticket and isinstance(data.get("data"), dict):
            for k in ("ticket", "alfrescoTicket", "alfresco_ticket"):
                v = data["data"].get(k)
                if isinstance(v, str) and v.strip():
                    ticket = v.strip()
                    break

    if not ticket:
        for hk in ("X-alfresco-ticket", "x-alfresco-ticket", "X-Alfresco-Ticket"):
            hv = resp.headers.get(hk)
            if hv and hv.strip():
                ticket = hv.strip()
                break

    # prova a costruire un cookie header dalla response/session
    try:
        parts = []
        for c in resp.cookies:
            if c.name and c.value:
                parts.append(f"{c.name}={c.value}")
            if ("alfresco" in c.name.lower() or "ticket" in c.name.lower()) and not ticket:
                ticket = c.value
        cookie = "; ".join(parts)
    except Exception:
        cookie = ""

    return ticket, cookie

def _candidate_usernames() -> list[str]:
    vals: list[str] = []
    u = (USERNAME or "").strip()
    if u:
        vals.append(u)
        if "@" in u:
            vals.append(u.split("@", 1)[0])
    # dedup mantenendo ordine
    out: list[str] = []
    seen = set()
    for x in vals:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _auth_header_candidates() -> list[str]:
    vals: list[str] = []
    bh = _bearer_header()
    if bh:
        vals.append(bh)
    if AUTH_B64:
        vals.append(f"Basic {AUTH_B64}")
    pwd = _clean_secret(PASSWORD)
    for u in _candidate_usernames():
        token = base64.b64encode(f"{u}:{pwd}".encode("utf-8")).decode("ascii")
        vals.append(f"Basic {token}")
    # dedup
    out: list[str] = []
    seen = set()
    for v in vals:
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _new_logged_session() -> requests.Session:
    """
    Crea una sessione autenticata verso JCONON.
    Strategia:
      1) header Basic (se presente)
      2) tentativo login applicativo /openapi/security/login (cookie sessione)
    """
    s = requests.Session()
    s.headers.update({"accept": "application/json"})
    ah = _auth_header()
    if ah:
        s.headers["Authorization"] = ah
    extra = _extra_auth_headers()
    if extra:
        s.headers.update(extra)

    login_url = f"{_base_url()}/openapi/security/login"
    users = _candidate_usernames()
    pwd = (PASSWORD or "").strip()
    if not users or not pwd:
        return s

    payload_variants = []
    for u in users:
        payload_variants.extend([
            {"username": u, "password": pwd},
            {"userid": u, "password": pwd},
            {"user": u, "password": pwd},
            {"email": u, "password": pwd},
        ])

    # prova sia JSON che form-urlencoded
    for p in payload_variants:
        try:
            r = s.post(login_url, json=p, timeout=20)
            if r.status_code < 400:
                t, ck = _extract_ticket_and_cookie(r)
                if t:
                    s.headers["X-alfresco-ticket"] = t
                    _SESSION_CACHE["alf_ticket"] = t
                if ck:
                    _SESSION_CACHE["cookie"] = ck
                return s
        except Exception:
            pass
        try:
            r = s.post(login_url, data=p, timeout=20)
            if r.status_code < 400:
                t, ck = _extract_ticket_and_cookie(r)
                if t:
                    s.headers["X-alfresco-ticket"] = t
                    _SESSION_CACHE["alf_ticket"] = t
                if ck:
                    _SESSION_CACHE["cookie"] = ck
                return s
        except Exception:
            pass
    return s


def _get_session(force_refresh: bool = False) -> requests.Session:
    now = time.time()
    cached = _SESSION_CACHE.get("session")
    ts = float(_SESSION_CACHE.get("ts") or 0)
    if (not force_refresh) and cached is not None and (now - ts) < 900:
        return cached  # type: ignore[return-value]
    s = _new_logged_session()
    _SESSION_CACHE["session"] = s
    _SESSION_CACHE["ts"] = now
    return s


def _http_get_with_session(url: str, retry: int = 1, sleep: float = 0.6) -> bytes:
    last_err = None
    for i in range(retry + 1):
        s = _get_session(force_refresh=(i > 0))
        auth_candidates = _auth_header_candidates() or [""]
        for ah in auth_candidates:
            try:
                if ah:
                    s.headers["Authorization"] = ah
                elif "Authorization" in s.headers:
                    del s.headers["Authorization"]
                r = s.get(url, timeout=30, allow_redirects=True)
                if r.status_code < 400:
                    return r.content
                last_err = urllib.error.HTTPError(url, r.status_code, r.reason, hdrs=None, fp=None)
                # se non è 401/403, inutile provare altre credenziali
                if r.status_code not in (401, 403):
                    break
            except Exception as e:
                last_err = e
        time.sleep(sleep)
    raise last_err  # type: ignore[misc]


def _http_get(url: str, headers: dict | None = None, retry: int = 2, sleep: float = 0.6) -> bytes:
    last_err = None
    for _ in range(retry + 1):
        req_headers = dict(headers or {})
        req_headers.update(_extra_auth_headers())
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_err = e
            # su 401/403 prova fallback con sessione autenticata (cookie login)
            if e.code in (401, 403):
                try:
                    return _http_get_with_session(url, retry=1, sleep=sleep)
                except Exception as e2:
                    last_err = e2
        except Exception as e:
            last_err = e
            time.sleep(sleep)
    raise last_err  # type: ignore[misc]


def _http_get_anonymous(url: str, retry: int = 1, sleep: float = 0.6) -> bytes:
    """
    GET senza alcun header di autenticazione.
    Utile come fallback per endpoint pubblici/guest che possono rifiutare auth errata.
    """
    last_err = None
    for _ in range(retry + 1):
        req = urllib.request.Request(url, headers={"accept": "application/json"})
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
        url = f"{_base_url()}/openapi/v1/call?{qs}"
        try:
            raw = _http_get(url, headers=headers)
        except urllib.error.HTTPError as e:
            # fallback guest: alcune configurazioni rispondono 401 se presenti credenziali non valide
            if e.code == 401:
                raw = _http_get_anonymous(url, retry=1)
            else:
                raise
        data = _loads_json(raw, "openapi/v1/call")

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

    def _extract_member_name(row: dict) -> str:
        attr = row.get("attr") if isinstance(row.get("attr"), dict) else {}
        # priorita' a nome leggibile, poi username/chiavi tecniche
        for k in ("data", "displayName", "display_name", "itemName", "groupName", "group_name", "name"):
            v = row.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for k in ("displayName", "userName", "shortName", "itemName", "id"):
            v = attr.get(k) if isinstance(attr, dict) else ""
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    # alcune installazioni sono sensibili al formato fullName/spazi
    candidates = []
    raw = (group_fullname or "").strip()
    if raw:
        candidates.append(raw)
        if raw.startswith("GROUP_"):
            candidates.append(raw.replace("+", " "))
            candidates.append(raw.replace(" ", "+"))

    members: list[str] = []
    for cand in candidates:
        try:
            url = (
                f"{_base_url()}/rest/proxy"
                f"?url=service/cnr/groups/children&ajax=true&fullName={quote(cand)}"
            )
            raw_resp = _http_get(url, headers=headers)
            data = _loads_json(raw_resp, "groups/children")
            rows = data if isinstance(data, list) else []
            tmp: list[str] = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                name = _extract_member_name(r)
                if name:
                    tmp.append(name)
            if tmp:
                # dedup mantenendo ordine
                seen = set()
                for x in tmp:
                    if x in seen:
                        continue
                    seen.add(x)
                    members.append(x)
                return members
        except Exception:
            continue
    return members


def fetch_call_detail(call_id: str) -> dict:
    """
    /openapi/v1/call/{id}
    Restituisce il payload dettaglio del bando.
    """
    call_id = (call_id or "").strip()
    if not call_id:
        return {}

    headers = {"accept": "application/json"}
    ah = _auth_header()
    if ah:
        headers["Authorization"] = ah

    url = f"{_base_url()}/openapi/v1/call/{quote(call_id)}"
    try:
        try:
            raw = _http_get(url, headers=headers)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raw = _http_get_anonymous(url, retry=1)
            else:
                raise
        data = _loads_json(raw, f"openapi/v1/call/{call_id}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _normalize_call_id(call_id: str) -> str:
    raw = (call_id or "").strip()
    if not raw:
        return ""
    if "SpacesStore/" in raw and "/" in raw:
        return raw.rsplit("/", 1)[-1].strip()
    return raw


def _json_from_response_text(text: str):
    t = (text or "").strip()
    if not t:
        return None
    try:
        return json.loads(t)
    except Exception:
        return None


def _post_json_with_auth(url: str, payload_variants: list[dict] | None = None, timeout: int = 30):
    payload_variants = payload_variants or [{}]
    auths = _auth_header_candidates() or [""]
    last_err = None
    for ah in auths:
        s = _get_session()
        headers = {"accept": "application/json"}
        headers.update(_extra_auth_headers())
        if ah:
            headers["Authorization"] = ah
        for payload in payload_variants:
            try:
                r = s.post(url, json=payload, headers=headers, timeout=timeout)
                if r.status_code < 400:
                    return _json_from_response_text(r.text)
                last_err = urllib.error.HTTPError(url, r.status_code, r.reason, hdrs=None, fp=None)
            except Exception as e:
                last_err = e
                continue
    raise last_err if last_err else RuntimeError("POST fallita")


def fetch_exam_sessions(call_id: str):
    """
    GET /openapi/v1/call/exam-sessions/{id}
    Ritorna lista sessioni (best effort).
    """
    cid = _normalize_call_id(call_id)
    if not cid:
        return []
    url = f"{_base_url()}/openapi/v1/call/exam-sessions/{quote(cid)}"
    try:
        raw = _http_get(url, headers={"accept": "application/json"})
        data = _loads_json(raw, f"call/exam-sessions/{cid}")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                return data.get("items")
            return [data]
    except Exception:
        return []
    return []


def fetch_exam_session_candidates(session_id: str):
    """
    POST /openapi/v1/call/exam-sessions/{id}
    Ritorna lista candidati (best effort).
    """
    sid = (session_id or "").strip()
    if not sid:
        return []
    url = f"{_base_url()}/openapi/v1/call/exam-sessions/{quote(sid)}"
    payloads = [
        {},
        {"page": 0, "offset": 200},
        {"maxItems": 200, "skipCount": 0},
    ]
    try:
        data = _post_json_with_auth(url, payload_variants=payloads, timeout=30)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                return data.get("items")
            if isinstance(data.get("results"), list):
                return data.get("results")
            return [data]
    except Exception:
        return []
    return []


def fetch_call_candidates(call_id: str) -> dict:
    """
    Estrae candidati del bando via exam sessions.
    Ritorna:
      { "sessions": [...], "candidates": [...], "count": N }
    """
    sessions = fetch_exam_sessions(call_id)
    all_candidates = []
    seen = set()
    for s in sessions:
        sid = str(
            (s.get("id") if isinstance(s, dict) else "")
            or (s.get("sessionId") if isinstance(s, dict) else "")
            or ""
        ).strip()
        if not sid:
            continue
        rows = fetch_exam_session_candidates(sid)
        for r in rows:
            if not isinstance(r, dict):
                continue
            # chiave dedup best effort
            key = (
                str(r.get("codiceFiscale") or r.get("taxCode") or "").strip(),
                str(r.get("cognome") or r.get("lastName") or "").strip(),
                str(r.get("nome") or r.get("firstName") or "").strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            all_candidates.append(r)
    return {
        "sessions": sessions,
        "candidates": all_candidates,
        "count": len(all_candidates),
    }


def fetch_call_scores(call_id: str) -> dict:
    """
    GET /carica-punteggi?callId=<uuid>
    Estrae i punteggi dalla pagina (HTML table) o JSON se disponibile.
    """
    cid = _normalize_call_id(call_id)
    if not cid:
        return {"available": False, "rows": [], "count": 0}

    xls_url = f"{_base_url()}/rest/call/applications-punteggi.xls?ajax=true&callId={quote(cid)}"
    html_url = f"{_base_url()}/carica-punteggi?callId={quote(cid)}"
    auths = _auth_header_candidates() or [""]
    last_err = ""

    def _rows_from_html_table(text: str) -> list[dict]:
        soup = BeautifulSoup(text or "", "html.parser")
        tables = soup.select("table")
        all_rows = []
        for t in tables:
            headers_txt = [th.get_text(" ", strip=True) for th in t.select("thead th")]
            if not headers_txt:
                first = t.select_one("tr")
                if first:
                    headers_txt = [x.get_text(" ", strip=True) for x in first.select("th,td")]
            for tr in t.select("tbody tr"):
                td_nodes = tr.select("td")
                vals = [td.get_text(" ", strip=True) for td in td_nodes]
                if not vals:
                    continue
                if headers_txt and len(headers_txt) == len(vals):
                    row = {headers_txt[i] or f"col_{i+1}": vals[i] for i in range(len(vals))}
                else:
                    row = {f"col_{i+1}": v for i, v in enumerate(vals)}
                # Estrai parametri utili da eventuali link nella riga (download-xls)
                hrefs = []
                for td in td_nodes:
                    for a in td.select("a[href]"):
                        href = (a.get("href") or "").strip()
                        if href:
                            hrefs.append(href)
                if hrefs:
                    row["__hrefs"] = " | ".join(hrefs)
                    for href in hrefs:
                        try:
                            qs = parse_qs(urlparse(href).query)
                            obj = (qs.get("objectId") or [""])[0].strip()
                            fn = (qs.get("fileName") or [""])[0].strip()
                            if obj and not (row.get("objectId") or row.get("objectid")):
                                row["objectId"] = obj
                            if fn and not (row.get("fileName") or row.get("filename")):
                                row["fileName"] = fn
                        except Exception:
                            continue
                all_rows.append(row)
        return all_rows

    def _rows_from_spreadsheet_xml(text: str) -> list[dict]:
        # Supporto minimale per SpreadsheetML (excel xml)
        if "Workbook" not in text or "<Row" not in text:
            return []
        row_blocks = re.findall(r"<Row[^>]*>(.*?)</Row>", text, flags=re.IGNORECASE | re.DOTALL)
        matrix = []
        for rb in row_blocks:
            cells = re.findall(r"<Cell[^>]*>(.*?)</Cell>", rb, flags=re.IGNORECASE | re.DOTALL)
            vals = []
            for c in cells:
                m = re.search(r"<Data[^>]*>(.*?)</Data>", c, flags=re.IGNORECASE | re.DOTALL)
                if m:
                    v = re.sub(r"<[^>]+>", "", m.group(1))
                    vals.append(html.unescape(v).strip())
                else:
                    vv = re.sub(r"<[^>]+>", "", c)
                    vals.append(html.unescape(vv).strip())
            if any(v.strip() for v in vals):
                matrix.append(vals)
        if not matrix:
            return []
        headers_txt = matrix[0]
        rows = []
        for vals in matrix[1:]:
            if headers_txt and len(vals) == len(headers_txt):
                rows.append({headers_txt[i] or f"col_{i+1}": vals[i] for i in range(len(vals))})
            else:
                rows.append({f"col_{i+1}": v for i, v in enumerate(vals)})
        return rows

    def _extract_rows_from_response(r: requests.Response) -> list[dict]:
        text_utf = ""
        try:
            text_utf = r.content.decode("utf-8")
        except Exception:
            try:
                text_utf = r.content.decode("latin-1")
            except Exception:
                text_utf = ""
        text = (text_utf or "").strip()
        if not text:
            return []
        # JSON
        if text.startswith("{") or text.startswith("["):
            j = _json_from_response_text(text)
            if isinstance(j, list):
                return [x for x in j if isinstance(x, dict)]
            if isinstance(j, dict):
                if isinstance(j.get("items"), list):
                    return [x for x in j.get("items") if isinstance(x, dict)]
                return [j]
        # HTML table
        if "<table" in text.lower():
            rows = _rows_from_html_table(text)
            if rows:
                return rows
        # SpreadsheetML XML
        if "<workbook" in text.lower() or "<worksheet" in text.lower():
            rows = _rows_from_spreadsheet_xml(text)
            if rows:
                return rows
        return []

    def _rows_from_binary_xls(data: bytes) -> list[dict]:
        if not data or xlrd is None:
            return []
        try:
            wb = xlrd.open_workbook(file_contents=data)
            if wb.nsheets < 1:
                return []
            sh = wb.sheet_by_index(0)
            if sh.nrows < 1:
                return []
            headers_txt = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
            rows = []
            for rix in range(1, sh.nrows):
                vals = [sh.cell_value(rix, c) for c in range(sh.ncols)]
                # normalizza numeri interi
                norm_vals = []
                for v in vals:
                    if isinstance(v, float) and v.is_integer():
                        norm_vals.append(str(int(v)))
                    else:
                        norm_vals.append(str(v).strip())
                if not any(x for x in norm_vals):
                    continue
                if headers_txt and len(headers_txt) == len(norm_vals):
                    row = {headers_txt[i] or f"col_{i+1}": norm_vals[i] for i in range(len(norm_vals))}
                else:
                    row = {f"col_{i+1}": v for i, v in enumerate(norm_vals)}
                rows.append(row)
            return rows
        except Exception:
            return []

    def _looks_like_export_descriptor(rows: list[dict]) -> bool:
        if not rows:
            return False
        sample = rows[0] if isinstance(rows[0], dict) else {}
        keys = {str(k).lower() for k in sample.keys()}
        if "objectid" in keys and ("filename" in keys or "namebando" in keys):
            return True
        # fallback: presenza href download-xls con objectId
        vals = " ".join([str(v) for v in sample.values()]).lower()
        return ("download-xls" in vals and "objectid=" in vals) or ("objectid=" in vals and "filename=" in vals)

    def _download_export_xls(s: requests.Session, ah: str, desc_row: dict) -> list[dict]:
        object_id = str(desc_row.get("objectId") or desc_row.get("objectid") or "").strip()
        file_name = str(desc_row.get("fileName") or desc_row.get("filename") or "").strip()
        if not object_id:
            href_blob = str(desc_row.get("__hrefs") or "")
            for part in href_blob.split(" | "):
                part = part.strip()
                if not part:
                    continue
                try:
                    qs = parse_qs(urlparse(part).query)
                    object_id = object_id or (qs.get("objectId") or [""])[0].strip()
                    file_name = file_name or (qs.get("fileName") or [""])[0].strip()
                except Exception:
                    continue
        if not object_id:
            return []
        params = {
            "objectId": object_id,
            "fileName": file_name,
            "exportData": "true",
            "mimeType": "application/vnd.ms-excel;charset=UTF-8",
        }
        dl_url = f"{_base_url()}/rest/call/download-xls?{urlencode(params)}"
        headers = {"accept": "application/vnd.ms-excel,text/html,application/json,*/*"}
        headers.update(_extra_auth_headers())
        if ah:
            headers["Authorization"] = ah
        try:
            rr = s.get(dl_url, headers=headers, timeout=60, allow_redirects=True)
            if rr.status_code >= 400:
                return []
            return _extract_rows_from_response(rr)
        except Exception:
            return []

    for endpoint_url in (xls_url, html_url):
        for ah in auths:
            s = _get_session()
            headers = {"accept": "text/html,application/json,application/vnd.ms-excel,*/*"}
            headers.update(_extra_auth_headers())
            if ah:
                headers["Authorization"] = ah
            try:
                r = s.get(endpoint_url, headers=headers, timeout=45, allow_redirects=True)
                if r.status_code >= 400:
                    last_err = f"HTTP {r.status_code} su {endpoint_url}"
                    continue
                rows = _extract_rows_from_response(r)
                if not rows:
                    rows = _rows_from_binary_xls(r.content)
                if rows:
                    # Se l'endpoint restituisce solo descrittore export (objectId/fileName),
                    # scarica il vero XLS e parsea le righe candidati.
                    if _looks_like_export_descriptor(rows):
                        merged = []
                        for d in rows:
                            ext = _download_export_xls(s, ah, d)
                            if ext:
                                merged.extend(ext)
                        if merged:
                            return {
                                "available": True,
                                "rows": merged,
                                "count": len(merged),
                                "source": f"{endpoint_url} -> download-xls",
                            }
                    return {"available": True, "rows": rows, "count": len(rows), "source": endpoint_url}
                last_err = f"Nessuna riga leggibile su {endpoint_url}"
            except Exception as e:
                last_err = str(e)
                continue

    # Fallback: vecchia pagina punteggi (se diversa dalle due sopra)
    url = html_url
    for ah in auths:
        s = _get_session()
        headers = {"accept": "text/html,application/json"}
        headers.update(_extra_auth_headers())
        if ah:
            headers["Authorization"] = ah
        try:
            r = s.get(url, headers=headers, timeout=30, allow_redirects=True)
            if r.status_code >= 400:
                last_err = f"HTTP {r.status_code}"
                continue

            ctype = (r.headers.get("content-type") or "").lower()
            text = r.text or ""

            # Caso JSON
            if "application/json" in ctype or text.strip().startswith("{") or text.strip().startswith("["):
                try:
                    data = r.json()
                    rows = []
                    if isinstance(data, list):
                        rows = [x for x in data if isinstance(x, dict)]
                    elif isinstance(data, dict):
                        if isinstance(data.get("items"), list):
                            rows = [x for x in data.get("items") if isinstance(x, dict)]
                        else:
                            rows = [data]
                    return {"available": bool(rows), "rows": rows, "count": len(rows)}
                except Exception:
                    pass

            # Caso HTML
            all_rows = _rows_from_html_table(text)
            if not all_rows:
                all_rows = _rows_from_binary_xls(r.content)
            if all_rows:
                return {"available": True, "rows": all_rows, "count": len(all_rows), "source": url}

            # Fallback: nessuna tabella ma pagina valida
            return {
                "available": False,
                "rows": [],
                "count": 0,
                "html_preview": text[:400],
            }
        except Exception as e:
            last_err = str(e)
            continue

    return {"available": False, "rows": [], "count": 0, "error": last_err}
