"""Controllo di accessibilità dei PDF (spostato da scraper-urp.py, research R9).

Si esegue su tutti i PDF elencati dalle pagine URP (access.html li conta tutti), una sola volta per
documento salvo link cambiato. Il primo giro dura ore: i documenti rimasti indietro per un riavvio
vengono ripresi alla raccolta successiva.
"""
import io
import json
import threading
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

_controllo_in_corso = threading.Lock()


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
            root = pdf.Root
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


def _livello_e_punteggio(has_text: bool, is_tagged: bool, has_struct: bool, lang: str | None) -> tuple[str, int]:
    if not has_text:
        return "non_accessibile", 0
    punti = 40 * is_tagged + 40 * has_struct + (20 if lang else 0)
    return ("accessibile", punti) if punti >= 60 else ("parziale", max(40, punti))


def valuta_file(dati: bytes, nome: str) -> dict:
    """Valuta un file caricato dalla pagina Verifica PDF; resta in memoria e non viene salvato."""
    out = {"filename": nome, "checked": False, "is_pdf": (nome or "").lower().endswith(".pdf"),
           "has_text": False, "is_tagged": False, "has_struct_tree": False, "lang": None, "has_title": False,
           "accessible": False, "level": "non_accessibile", "score": 0, "note": ""}
    if not out["is_pdf"]:
        out["note"] = "Non PDF – non valutabile"
        return out
    tag = _pdf_tag_info(dati)
    out.update(checked=True, has_text=_pdf_has_text(dati), is_tagged=tag["is_tagged"],
               has_struct_tree=tag["has_struct_tree"], lang=tag["lang"], has_title=bool(tag["title"]))
    out["level"], out["score"] = _livello_e_punteggio(out["has_text"], out["is_tagged"], out["has_struct_tree"], out["lang"])
    out["accessible"] = out["level"] == "accessibile"
    if not out["has_text"]:
        out["note"] = "Sembra scansione (nessun testo estraibile)"
    elif out["level"] == "parziale":
        out["note"] = "Testo presente ma mancano tag/struttura/lingua"
    return out


def documenti_da_valutare(conn) -> list[int]:
    """Documenti URP mai valutati. Il documento principale resta fuori: le pagine non lo elencano."""
    return [r["id"] for r in conn.execute(
        "SELECT d.id FROM documento d JOIN scheda s ON s.id = d.scheda_id WHERE s.fonte = 'urp' AND d.presente = 1 "
        "AND d.categoria != 'bando' AND d.accessibilita IS NULL AND d.url LIKE 'http%'")]


def controlla_documenti(conn, documento_ids: list[int]) -> int:
    """Valuta i PDF dei documenti indicati e salva il risultato. Un solo controllo alla volta."""
    if not documento_ids or not _controllo_in_corso.acquire(blocking=False):
        return 0
    controllati = 0
    try:
        for doc_id in documento_ids:
            riga = conn.execute("SELECT url FROM documento WHERE id = ? AND categoria != 'bando' AND url LIKE 'http%'",
                                (doc_id,)).fetchone()
            if not riga:
                continue
            risultato = valuta_accessibilita_pdf(riga["url"])
            conn.execute("UPDATE documento SET accessibilita = ? WHERE id = ?",
                         (json.dumps(risultato, ensure_ascii=False), doc_id))
            controllati += 1
            time.sleep(config.pausa_urp())
    finally:
        _controllo_in_corso.release()
    return controllati
