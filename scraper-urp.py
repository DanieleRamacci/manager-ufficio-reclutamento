# scraper-urp.py
import os
import sys
import io
import re
import json
import time
import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ====== opzionali (se presenti migliorano l'analisi PDF) ======
try:
    from pdfminer.high_level import extract_text
    PDFMINER_AVAILABLE = True
except Exception:
    PDFMINER_AVAILABLE = False

try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except Exception:
    PIKEPDF_AVAILABLE = False

# ========= Costanti =========
BASE_URL = "https://www.urp.cnr.it"
CATEGORIE = {
    "tempo-indeterminato": f"{BASE_URL}/documenti/tempo-indeterminato/",
    "tempo-determinato": f"{BASE_URL}/documenti/tempo-determinato/",
    "categorie-riservatarie": f"{BASE_URL}/documenti/categorie-riservatarie/",
    "direttori-dipartimentiistituti": f"{BASE_URL}/documenti/direttori-dipartimentiistituti/",
    "avviamento-numerico-selezione-ans-categorie-riservatarie": f"{BASE_URL}/documenti/avviamento-numerico-selezione-ans-categorie-riservatarie/",
    "borse-ricerca": f"{BASE_URL}/documenti/borse-di-ricerca/" 

}
OLD_ARCHIVE_URL = "https://archivio.urp.cnr.it/page.php?level=3&pg=157&Org=4&db=1"
OLD_BASE_URL = "https://archivio.urp.cnr.it/"

USER_AGENT = "Mozilla/5.0 (compatible; CNR-BandiBot/1.0)"

# === Tipologie documento ===
TIPO_CRITERI = "criteri"
TIPO_TRACCE_SCRITTA = "tracce_prova_scritta"


# =========================
# Helper / Normalizzazione
# =========================
def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().replace("’", "'")


def parse_date_any(s: str) -> str | None:
    """
    Accetta 'dd/mm/yyyy', 'dd-mm-yyyy', 'dd.mm.yyyy', 'yyyy-mm-dd' -> 'yyyy-mm-dd'.
    """
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            d = datetime.datetime.strptime(s, fmt).date()
            return d.isoformat()
        except ValueError:
            pass
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    return None


def year_or_none(iso_date: str | None) -> int | None:
    return int(iso_date[:4]) if iso_date and re.match(r"^\d{4}-\d{2}-\d{2}$", iso_date) else None


def estrai_prot_e_date(testo: str) -> tuple[str | None, str | None, str | None]:
    """
    Ritorna (protocollo, data_protocollo_iso, data_pubblicazione_iso)
    da frasi tipo:
      'Prot. 162867 del 15/05/2024 - Pubb. sito URP-CNR in data 15/05/2024'
    """
    txt = norm_space(testo)
    m_prot = re.search(r"\bProt(?:\.|ocoll[io])?\s*[:\-]?\s*(\d+)", txt, flags=re.I)
    protocollo = m_prot.group(1) if m_prot else None

    m_dp = re.search(r"\bdel\s+(\d{2}[\/\-\.\ ]\d{2}[\/\-\.\ ]\d{4})", txt, flags=re.I)
    data_protocollo_iso = parse_date_any(m_dp.group(1)) if m_dp else None

    m_pub = re.search(r"(?:Pubb\.[^0-9]{0,20}data|in data)\s+(\d{2}[\/\-\.\ ]\d{2}[\/\-\.\ ]\d{4})", txt, flags=re.I)
    data_pubblicazione_iso = parse_date_any(m_pub.group(1)) if m_pub else None

    return protocollo, data_protocollo_iso, data_pubblicazione_iso


def estrai_codice_bando(*texts: str) -> str | None:
    """
    Prova a catturare un 'codice bando' dal titolo/estratti.
    Gestisce:
      - 'BANDO N. 380.1 TEC ...'  ->  '380.1 TEC'
      - 'Codice Bando 367.443 CTER ...' -> '367.443 CTER'
    Ritorna solo la parte di codice (es. '367.443 CTER'), se trovata.
    """
    joined = " // ".join([t for t in texts if t])[:2000]
    t = norm_space(joined).lower()

    # 1) "bando n. XXX ..." => cattura fino a fine parola codice (comprende segmento alfabetico successivo)
    m = re.search(r"\bbando\s*n\.?\s*([0-9]{3}\.[0-9]+(?:\s+[a-zà-ù]+)?)", t, flags=re.I)
    if m:
        return m.group(1).upper()

    # 2) "codice bando XXX ..." simile
    m = re.search(r"\bcodice\s+bando\s+([0-9]{3}\.[0-9]+(?:\s+[a-zà-ù]+)?)", t, flags=re.I)
    if m:
        return m.group(1).upper()

    # 3) fallback: cerca pattern 000.000 + eventuale sigla
    m = re.search(r"\b([0-9]{3}\.[0-9]+(?:\s+[a-zà-ù]+)?)\b", t, flags=re.I)
    if m:
        return m.group(1).upper()

    return None


# =========================
# Classificatori documento
# =========================
def classifica_graduatoria(titolo: str) -> str | None:
    t = norm_space(titolo.lower())
    if (
        re.search(r"\b(scorriment[oi]|utilizz[oa])\b.*\bgraduatori\w*\b", t)
        or re.search(r"\bgraduatori\w*\b.*\b(scorriment[oi]|utilizz[oa])\b", t)
        or re.search(r"\butilizzo graduatori\w*\b", t)
        or re.search(r"\bscorrimento graduatori\w*\b", t)
    ):
        return "scorrimento_utilizzo"
    if re.search(r"\bgraduatori\w*\b", t):
        return "graduatoria"
    return None


def classifica_documento_generico(titolo: str) -> str | None:
    """
    Riconosce:
      - criteri
      - tracce/prove: scritta, teorico-pratica, orale (tutte normalizzate a 'tracce_prova_scritta')
    Aggiungi qui sotto nuove frasi chiave quando servono.
    """
    t = re.sub(r"\s+", " ", (titolo or "").lower())

    # --- CRITERI ---
    if re.search(r"\bcriteri(di)?\b", t):
        return TIPO_CRITERI

    # --- TRACCE / PROVE (SCRITTA, TEORICO-PRATICA, ORALE) ---
    PAT_TRACCE = [
        r"\btracc\w+.*(scrit|prova scritta)\b",
        r"\b(prova scritta)\b.*tracc\w+",
        r"\b(prova|prove)\s+teorico[\-\s]?pratic\w*\b",
        r"\btracc\w+.*teorico[\-\s]?pratic\w*\b",
        r"\b(prova|prove)\s+oral\w*\b",              # “prove orale/i”
        r"\btracc\w+.*oral\w*\b",
        r"\btracc\w+\b",                              # fallback generico "tracce ..."
    ]
    for pat in PAT_TRACCE:
        if re.search(pat, t, flags=re.I):
            return TIPO_TRACCE_SCRITTA

    return None

# =========================
# PDF utils (download + analisi)
# =========================
def _download_pdf(url: str, max_size_mb: float = 25.0) -> bytes | None:
    try:
        with requests.get(url, stream=True, timeout=30, headers={"User-Agent": USER_AGENT}) as r:
            r.raise_for_status()
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "pdf" not in ctype and not url.lower().endswith(".pdf"):
                return None
            max_bytes = int(max_size_mb * 1024 * 1024)
            buf = io.BytesIO()
            for chunk in r.iter_content(8192):
                if not chunk:
                    continue
                buf.write(chunk)
                if buf.tell() > max_bytes:
                    return None
            return buf.getvalue()
    except Exception:
        return None


def _pdf_has_text(pdf_bytes: bytes) -> bool:
    if not PDFMINER_AVAILABLE:
        return False
    try:
        txt = extract_text(io.BytesIO(pdf_bytes)) or ""
        return len(txt.strip()) >= 200  # soglia robusta
    except Exception:
        return False


def _pdf_tag_info(pdf_bytes: bytes) -> dict:
    info = {"is_tagged": False, "has_struct_tree": False, "lang": None, "title": None}
    if not PIKEPDF_AVAILABLE:
        return info
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            root = pdf.root
            markinfo = root.get("/MarkInfo", None)
            if isinstance(markinfo, pikepdf.Dictionary):
                info["is_tagged"] = bool(markinfo.get("/Marked", False))
            info["has_struct_tree"] = "/StructTreeRoot" in root
            if "/Lang" in root:
                try:
                    info["lang"] = str(root["/Lang"])
                except Exception:
                    info["lang"] = None
            try:
                meta = pdf.open_metadata()
                t = (meta.get("dc:title") or meta.get("pdf:Title") or "").strip()
                info["title"] = t or None
            except Exception:
                pass
    except Exception:
        pass
    return info


def valuta_accessibilita_pdf(url: str) -> dict:
    """
    Scarica e valuta un PDF. Euristica 'accessible':
      - deve esserci testo estraibile
      - e almeno uno tra: PDF taggato, struttura o lingua impostata
    """
    out = {
        "checked": False,
        "is_pdf": False,
        "has_text": False,
        "is_tagged": False,
        "has_struct_tree": False,
        "lang": None,
        "has_title": False,
        "accessible": False,
        "note": ""
    }
    pdf = _download_pdf(url)
    if not pdf:
        out["note"] = "Non scaricabile o non PDF / troppo grande"
        return out

    out["checked"] = True
    out["is_pdf"] = True
    out["has_text"] = _pdf_has_text(pdf)
    tag = _pdf_tag_info(pdf)
    out["is_tagged"] = tag["is_tagged"]
    out["has_struct_tree"] = tag["has_struct_tree"]
    out["lang"] = tag["lang"]
    out["has_title"] = bool(tag["title"])

    out["accessible"] = bool(out["has_text"] and (out["is_tagged"] or out["has_struct_tree"] or out["lang"]))
    if not out["has_text"]:
        out["note"] = "Sembra scansione (nessun testo estraibile)"
    elif not out["accessible"]:
        out["note"] = "Testo presente ma mancano tag/struttura/lingua"
    return out


# =========================
# URP Nuovo
# =========================
def get_numero_documenti(soup):
    text_block = soup.find("div", class_="view-header")
    if not text_block:
        return 0, 0
    testo = text_block.get_text(strip=True)
    match = re.search(r"Numero Documenti:\s*(\d+)\s+di\s+(\d+)", testo)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0


def get_bandi_links_from_page(url_base, pagina):
    url = f"{url_base}?page={pagina}"
    print(f"[+] Scarico pagina: {url}")
    response = requests.get(url, headers={"User-Agent": USER_AGENT})
    soup = BeautifulSoup(response.text, "html.parser")
    numero_corrente, numero_totale = get_numero_documenti(soup)
    bandi = soup.select("a.link-apri-documento")
    links = [BASE_URL + b["href"] for b in bandi]
    return links, numero_corrente, numero_totale


def get_bando_title_from_field_documento(soup):
    """
    URP nuovo: estrae il titolo 'umano' dal campo documento principale.
    Cerca <a> in .field--name-field-documento che contenga 'bando'.
    """
    links = soup.select('.field--name-field-documento a')
    if not links:
        return None

    def to_title(txt):
        txt = norm_space(txt or "")
        m = re.search(r'\bbando\s*n?\.?\s*(.+)$', txt, flags=re.I)
        return f"Codice Bando {m.group(1).strip()}" if m else txt

    for a in links:
        cand = a.get_text(strip=True) or a.get('title') or a.get('href') or ''
        if re.search(r'\bbando\b', cand, flags=re.I):
            return to_title(cand)
    return to_title(links[0].get_text(strip=True))


def parse_bando(url):
    scorr_uti_presente = False
    data_scorr_uti = None

    response = requests.get(url, headers={"User-Agent": USER_AGENT})
    soup = BeautifulSoup(response.text, "html.parser")

    # Estratto
    estratto_tag = soup.select_one("div.region--content")
    estratto = estratto_tag.get_text(separator="\n", strip=True) if estratto_tag else ""

    # Allegati
    allegati_container = soup.select("div.eva-allegati .views-view-responsive-grid__item-inner")

    # Titolo
    titolo_bando = get_bando_title_from_field_documento(soup)
    if not titolo_bando:
        h1 = soup.select_one("h1, .page-title, .title")
        titolo_bando = h1.get_text(strip=True) if h1 else ""

    # Codice bando (aiuta UI)
    codice_bando = estrai_codice_bando(titolo_bando, estratto)

    # Protocollo + data pubblicazione bando dall'estratto
    match = re.search(r"Protocollo\s+(\d+)\s+del\s+(\d{2}-\d{2}-\d{4})", estratto)
    numero_protocollo = match.group(1) if match else None
    data_pubblicazione_bando = match.group(2) if match else None

    allegati = []
    graduatoria_presente = False
    data_pubblicazione_graduatoria = None

    for item in allegati_container:
        titolo_tag = item.select_one("span.views-field-field-allegato a")
        protocollo_tag = item.select_one("span.views-field-field-protocollo-numero")
        data_tag = item.select_one("span.views-field-field-protocollo-data")

        titolo = titolo_tag.text.strip() if titolo_tag else ""
        link = BASE_URL + titolo_tag["href"] if titolo_tag and "href" in titolo_tag.attrs else ""
        protocollo = protocollo_tag.text.strip().replace("- Protocollo ", "") if protocollo_tag else None
        data = data_tag.text.strip().replace("del ", "") if data_tag else None
        data_iso = parse_date_any(data) if data else None

        tipo_doc = classifica_documento_generico(titolo)
        tipo_grad = classifica_graduatoria(titolo)

        # >>> verifica accessibilità su QUALSIASI PDF (non solo criteri/tracce)
        access = {}
        if link and (link.lower().endswith(".pdf") or "system/files" in link.lower()):
            access = valuta_accessibilita_pdf(link)

        allegati.append({
            "titolo": titolo,
            "link": link,
            "protocollo": protocollo,
            "data": data,
            "data_iso": data_iso,
            "tipo_documento": tipo_doc,
            "tipo_graduatoria": tipo_grad,
            "access_check": access
        })

        if tipo_grad == "graduatoria":
            graduatoria_presente = True
            data_pubblicazione_graduatoria = data_iso or data
        elif tipo_grad == "scorrimento_utilizzo":
            scorr_uti_presente = True
            data_scorr_uti = data_iso or data

    return {
        "url": url,
        "titolo_bando": titolo_bando,
        "codice_bando": codice_bando,
        "data_pubblicazione_bando": data_pubblicazione_bando,
        "numero_protocollo": numero_protocollo,
        "graduatoria_presente": graduatoria_presente,
        "data_pubblicazione_graduatoria": data_pubblicazione_graduatoria,
        "estratto": estratto[:1000],
        "allegati": allegati,
        "scorrimento_utilizzo_presente": scorr_uti_presente,
        "data_scorrimento_utilizzo": data_scorr_uti,
        "fonte": "urp_nuovo"
    }


def scrape_categoria(nome_categoria, url_base):
    print(f"[>>] Inizio scraping categoria: {nome_categoria}")
    page = 0
    tutti_i_dati = []
    numero_totale_documenti = None

    while True:
        links, numero_corrente, numero_totale = get_bandi_links_from_page(url_base, page)
        if numero_totale_documenti is None:
            numero_totale_documenti = numero_totale
        if not links:
            break

        for link in links:
            dati = parse_bando(link)
            tutti_i_dati.append(dati)
            time.sleep(0.5)

        if len(tutti_i_dati) >= numero_totale_documenti:
            break
        page += 1

    return tutti_i_dati


# =========================
# Archivio Vecchio
# =========================
def parse_archivio_old_urp():
    print(f"[>>] Scarico archivio vecchio: {OLD_ARCHIVE_URL}")
    response = requests.get(OLD_ARCHIVE_URL, headers={"User-Agent": USER_AGENT})
    soup = BeautifulSoup(response.text, "html.parser")
    bandi = []

    for dt in soup.find_all("dt"):
        a_tag = dt.find("a")
        dd = dt.find_next_sibling("dd")
        if not a_tag or not dd:
            continue

        url = urljoin(OLD_BASE_URL, a_tag.get("href", "").lstrip("/"))
        titolo = a_tag.get_text(strip=True)  # spesso contiene 'Codice Bando ...'

        # Estratto (per aiuto regex + preview)
        estratto = dd.get_text(separator="\n", strip=True)

        # Protocollo + data (dal titolo bando)
        match_proto = re.search(
            r"Prot(?:\.|ocoll[io])\s*(\d+)\s+del\s+(\d{2}[\/\-]\d{2}[\/\-]\d{4})",
            titolo,
            flags=re.I
        )
        numero_protocollo = match_proto.group(1) if match_proto else None
        data_pubblicazione = parse_date_any(match_proto.group(2)) if match_proto else None

        # Codice bando (aiuta UI)
        codice_bando = estrai_codice_bando(titolo, estratto)

        allegati = []
        graduatoria_presente = False
        data_pubblicazione_graduatoria = None

        for li in dd.find_all("li"):
            testo = li.get_text(" ", strip=True)
            link_tag = li.find("a")
            link = urljoin(OLD_BASE_URL, link_tag["href"].lstrip("/")) if link_tag and link_tag.get("href") else ""

            protocollo, data_prot_iso, data_pubbl_iso = estrai_prot_e_date(testo)
            tipo_doc = classifica_documento_generico(testo)
            tipo_grad = classifica_graduatoria(testo)

            # NOVITÀ: verifica accessibilità per ogni PDF (archivio vecchio)
            access = {}
            if link.lower().endswith(".pdf"):
                access = valuta_accessibilita_pdf(link)

            allegati.append({
                "titolo": testo,
                "link": link,
                "protocollo": protocollo,
                "data": data_prot_iso or data_pubbl_iso,
                "data_iso": data_prot_iso or data_pubbl_iso,
                "tipo_documento": tipo_doc,
                "tipo_graduatoria": tipo_grad,
                "access_check": access,  # <<< aggiunto
            })
            if tipo_grad == "graduatoria" or "graduatoria" in testo.lower():
                graduatoria_presente = True
                data_pubblicazione_graduatoria = data_pubbl_iso or data_prot_iso

        bandi.append({
            "url": url,
            "titolo_bando": titolo,
            "codice_bando": codice_bando,
            "data_pubblicazione_bando": data_pubblicazione,
            "numero_protocollo": numero_protocollo,
            "graduatoria_presente": graduatoria_presente,
            "data_pubblicazione_graduatoria": data_pubblicazione_graduatoria,
            "estratto": estratto[:1000],
            "allegati": allegati,
            "fonte": "urp_archivio"
        })

    return bandi


# =========================
# Tabella di controllo
# =========================
def _pick_first_doc(allegati, tipo_chiave: str):
    for a in allegati or []:
        if a.get("tipo_documento") == tipo_chiave:
            return a
    return None


def record_controllo_per_bando(bando: dict) -> dict:
    allegati = bando.get("allegati", []) or []
    doc_criteri = _pick_first_doc(allegati, TIPO_CRITERI)
    doc_tracce = _pick_first_doc(allegati, TIPO_TRACCE_SCRITTA)

    def _acc(a):
        if not a:
            return ""
        ac = a.get("access_check") or {}
        v = ac.get("accessible", "")
        s = str(v).strip().lower()
        if v is True or s in ("✓", "si", "sì", "true", "1"):
            return "✓"
        if v is False or s in ("✗", "no", "false", "0"):
            return "✗"
        return ""

    rec = {
        "Titolo_bando": bando.get("titolo_bando") or "",
        "Link_bando": bando.get("url") or "",
        "Criteri_presenti": "✓" if doc_criteri else "✗",
        "Link_Criteri": doc_criteri.get("link") if doc_criteri else "",
        "Data_pubbl_Criteri": (doc_criteri.get("data_iso") or doc_criteri.get("data")) if doc_criteri else "",
        "Criteri_accessibile": _acc(doc_criteri),
        "Criteri_note": (doc_criteri.get("access_check") or {}).get("note", "") if doc_criteri else "",
        "Criteri_link_doc": doc_criteri.get("link") if doc_criteri else "",

        "Tracce_presenti": "✓" if doc_tracce else "✗",
        "Link_Tracce": doc_tracce.get("link") if doc_tracce else "",
        "Data_pubbl_Tracce": (doc_tracce.get("data_iso") or doc_tracce.get("data")) if doc_tracce else "",
        "Tracce_accessibile": _acc(doc_tracce),
        "Tracce_note": (doc_tracce.get("access_check") or {}).get("note", "") if doc_tracce else "",
        "Tracce_link_doc": doc_tracce.get("link") if doc_tracce else "",

        "Fonte": bando.get("fonte") or "",
    }

    # Per filtro anno: Criteri/Tracce, altrimenti data bando.
    candidates = [
        rec["Data_pubbl_Criteri"] or None,
        rec["Data_pubbl_Tracce"] or None,
        bando.get("data_pubblicazione_bando")
    ]
    candidates = [parse_date_any(c) if c and not re.match(r"^\d{4}-\d{2}-\d{2}$", c) else c for c in candidates]
    existing = [c for c in candidates if c]
    rec["_best_date_iso"] = max(existing) if existing else None
    rec["_best_year"] = year_or_none(rec["_best_date_iso"])
    return rec


def build_tabella_controllo(dati_finali: dict, anno_minimo: int = 2020) -> list[dict]:
    rows = []

    # nuovo URP: categorie
    for nome_categoria, bandi in dati_finali.items():
        if nome_categoria == "archivio-vecchio":
            continue
        if not isinstance(bandi, list):
            continue
        for b in bandi:
            rows.append(record_controllo_per_bando(b))

    # archivio vecchio
    for b in dati_finali.get("archivio-vecchio", []):
        rows.append(record_controllo_per_bando(b))

    # filtro per anno
    filtered = []
    for r in rows:
        y = r.get("_best_year")
        if y is None:
            continue
        if y >= anno_minimo:
            filtered.append(r)

    # ordina per data desc, poi titolo
    filtered.sort(key=lambda x: (x.get("_best_date_iso") or "", x.get("Titolo_bando") or ""), reverse=True)

    # pulisci campi interni
    for r in filtered:
        r.pop("_best_date_iso", None)
        r.pop("_best_year", None)

    return filtered


def salva_json_controllo(rows: list[dict], path: str = "controllo_criteri_tracce_2020plus.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"[OK] Tabella controllo salvata: {path}")


# =========================
# Backfill access_check su JSON esistente
# =========================
def backfill_accessibility_on_json(path: str = "bandi-completi-urp.json") -> None:
    """Legge il JSON e popola access_check mancante/vuoto per TUTTI gli allegati PDF (nuovo+vecchio)."""
    if not os.path.exists(path):
        print(f"[ERR] File non trovato: {path}")
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    changed = 0

    def _fix_allegati(lista):
        nonlocal changed
        for b in lista:
            allegati = b.get("allegati") or []
            for a in allegati:
                ac = a.get("access_check", {})
                need = (not isinstance(ac, dict)) or (ac == {}) or ("checked" not in ac)
                url = a.get("link") or ""
                if need and url and (url.lower().endswith(".pdf") or "system/files" in url.lower()):
                    a["access_check"] = valuta_accessibilita_pdf(url)
                    changed += 1
            # prova a riempire codice_bando se mancante
            if not b.get("codice_bando"):
                b["codice_bando"] = estrai_codice_bando(b.get("titolo_bando"), b.get("estratto"))

    if isinstance(data, dict):
        for key, lista in data.items():
            if isinstance(lista, list):
                _fix_allegati(lista)
    elif isinstance(data, list):
        _fix_allegati(data)

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[OK] Backfill accessibility completato. Allegati aggiornati: {changed}")
    else:
        print("[OK] Nessun allegato da aggiornare: access_check già presente.")


# === MAIN ===
if __name__ == "__main__":
    if "--refresh-accessibility" in sys.argv:
        backfill_accessibility_on_json("bandi-completi-urp.json")
        sys.exit(0)

    dati_finali = {}

    # Scrape URP nuovo per ogni categoria
    for nome_categoria, url_categoria in CATEGORIE.items():
        dati_finali[nome_categoria] = scrape_categoria(nome_categoria, url_categoria)

    # Scrape archivio vecchio
    dati_finali["archivio-vecchio"] = parse_archivio_old_urp()

    # Salva JSON completo
    with open("bandi-completi-urp.json", "w", encoding="utf-8") as f:
        json.dump(dati_finali, f, ensure_ascii=False, indent=2)
    print("[OK] File salvato: bandi-completi-urp.json")

    # Costruisci e salva tabella controllo (>= 2020) in JSON
    rows = build_tabella_controllo(dati_finali, anno_minimo=2020)
    salva_json_controllo(rows, "controllo_criteri_tracce_2020plus.json")

    # Mini report
    tot = len(rows)
    mancanti_criteri = sum(1 for r in rows if r["Criteri_presenti"] == "✗")
    mancanti_tracce = sum(1 for r in rows if r["Tracce_presenti"] == "✗")
    print(f"[REPORT] Righe (>=2020): {tot} | Criteri mancanti: {mancanti_criteri} | Tracce mancanti: {mancanti_tracce}")
