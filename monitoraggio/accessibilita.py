"""Controllo di accessibilità dei PDF (spostato da scraper-urp.py, research R9).

Si esegue solo sui documenti nuovi o con link cambiato, e solo per criteri e tracce:
sono gli unici di cui le pagine mostrano l'accessibilità.
"""
import io
import json
import time

import requests

from . import config

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

CATEGORIE_CONTROLLATE = ("criteri", "tracce")


def _download_pdf(url: str, max_size_mb: float = 25.0) -> bytes | None:
    try:
        with requests.get(url, stream=True, timeout=30, headers={"User-Agent": config.USER_AGENT}) as r:
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


def controlla_documenti(conn, documento_ids: list[int]) -> int:
    """Valuta i PDF dei documenti indicati (solo criteri e tracce) e salva il risultato."""
    if not documento_ids:
        return 0
    segnaposto = ", ".join("?" * len(documento_ids))
    righe = conn.execute(
        f"SELECT id, url FROM documento WHERE id IN ({segnaposto}) AND categoria IN "
        f"({', '.join('?' * len(CATEGORIE_CONTROLLATE))}) AND url LIKE 'http%'",
        (*documento_ids, *CATEGORIE_CONTROLLATE)).fetchall()
    for riga in righe:
        risultato = valuta_accessibilita_pdf(riga["url"])
        conn.execute("UPDATE documento SET accessibilita = ? WHERE id = ?",
                     (json.dumps(risultato, ensure_ascii=False), riga["id"]))
        time.sleep(config.pausa_urp())
    return len(righe)
