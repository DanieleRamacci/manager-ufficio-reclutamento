"""Normalizzazione di codici bando, protocolli e date (research R5, R12)."""
import re
from datetime import date, datetime

_PREFISSI = re.compile(r"^\s*(?:codice\s+bando|bando\s*n\.?|bando)\s*[:\-]?\s*", re.I)
_NUMERO = re.compile(r"(?<![\d.])(\d{3})\.(\d{1,4})(?![\d.])")
_NUMERO_COMPATTO = re.compile(r"^\s*(\d{3})(\d{3})\s*$")
_SOTTO = [
    re.compile(r"\bcod(?:ice)?\.?\s*(\d{1,3}|[A-Z])\b(?!\s*bando)", re.I),
    re.compile(r"\btematica\s+([A-Z])\b", re.I),
]
_FORMATI_DATA = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d")


def norm_space(s: str | None) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip().replace("’", "'")
    # "367. 640" -> "367.640": lo spazio dopo il punto del numero bando è un refuso frequente
    return re.sub(r"(?<=\d)\.\s+(?=\d)", ".", s)


def codice_norm(testo: str | None) -> str | None:
    """'BANDO N. 367.479 CTER IOM GE' e '367.479 CTER IOMGE' -> '367.479CTERIOMGE'."""
    s = _PREFISSI.sub("", norm_space(testo)).upper()
    # tiene solo lettere, cifre e il punto tra due cifre (367.479)
    s = re.sub(r"(?<=\d)\.(?=\d)", "§", s)
    s = re.sub(r"[^0-9A-ZÀ-Ý§]", "", s).replace("§", ".")
    # comandi: "01-COMANDO-2025" su URP, "1-COMANDO-2025" su SOL
    s = re.sub(r"^0+(?=\d)", "", s)
    return s or None


def numero_bando(testo: str | int | None) -> str | None:
    """Numero del bando ('367.434'), anche se scritto '367434'."""
    if testo is None:
        return None
    s = norm_space(str(testo))
    m = _NUMERO_COMPATTO.match(s)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    m = _NUMERO.search(s)
    return f"{m.group(1)}.{m.group(2)}" if m else None


def codice_sotto(testo: str | None) -> str | None:
    """Codice di sotto-bando: 'Cod. 14' -> '14', 'cod.05' -> '5', 'Tematica C' -> 'C'."""
    s = norm_space(testo)
    for pattern in _SOTTO:
        m = pattern.search(s)
        if m:
            valore = m.group(1)
            return str(int(valore)) if valore.isdigit() else valore.upper()
    return None


def protocollo(testo: str | int | None) -> str | None:
    """Solo cifre, senza zeri iniziali: '0455701' -> '455701'."""
    if testo is None:
        return None
    m = re.search(r"\d+", str(testo))
    if not m:
        return None
    return m.group(0).lstrip("0") or "0"


def data_iso(valore) -> str | None:
    """Data in formato YYYY-MM-DD da stringhe italiane, ISO o oggetti date/datetime."""
    if valore is None:
        return None
    if isinstance(valore, datetime):
        return valore.date().isoformat()
    if isinstance(valore, date):
        return valore.isoformat()
    s = str(valore).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T", s)
    if m:
        return m.group(1)
    m = re.search(r"\d{2}[/\-.]\d{2}[/\-.]\d{4}|\d{4}-\d{2}-\d{2}", s)
    if not m:
        return None
    for formato in _FORMATI_DATA:
        try:
            return datetime.strptime(m.group(0), formato).date().isoformat()
        except ValueError:
            pass
    return None
