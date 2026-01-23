from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .validators import validate_date, validate_doc_number, validate_phone

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE_CANDIDATE_RE = re.compile(r"(?:\+|00)?\d[0-9\s\-\.()]{6,}\d")
_DATE_RE = re.compile(
    r"\b(0?[1-9]|[12][0-9]|3[01])\s*[\/\-.]\s*(0?[1-9]|1[0-2])\s*[\/\-.]\s*(\d{2}|\d{4})\b"
)
_CI_RE = re.compile(r"\b[A-Z]{2}\s*\d{5,7}\b")
_CIE_RE = re.compile(r"\b[A-Z]{2}\s*\d{5}\s*[A-Z](?:\s*[A-Z])?\b")
_PATENTE_RE = re.compile(r"\b[A-Z0-9]{10}\b")

_CONTEXT_KEYWORDS = [
    "CARTA D",
    "CARTA DI IDENT",
    "CARTA IDENT",
    "CARTA D IDENT",
    "CARTA DI IDENTITA",
    "DOCUMENTO D",
    "DOCUMENTO DI",
    "DOCUMENTO IDENT",
    "IDENTIT",
    "DOCUMENTO",
    "N.",
    "NUMERO",
    "NUMERO DOCUMENTO",
    "N DOCUMENTO",
]

_BIRTH_KEYWORDS = [
    "NATO IL",
    "NATA IL",
    "DATA DI NASCITA",
    "NATO A",
    "NATA A",
]

_PATENTE_KEYWORDS = [
    "PATENTE",
    "N PATENTE",
    "NUMERO PATENTE",
    "DRIVING LICENCE",
    "DRIVING LICENSE",
]


def find_with_context(
    pattern: re.Pattern,
    text: str,
    keywords: list[str],
    window: int = 30,
) -> list[tuple[re.Match, bool]]:
    matches: list[tuple[re.Match, bool]] = []
    text_upper = text.upper()
    for match in pattern.finditer(text):
        start, end = match.span()
        ctx_start = max(0, start - window)
        ctx_end = min(len(text), end + window)
        context = text_upper[ctx_start:ctx_end]
        has_kw = any(keyword in context for keyword in keywords)
        matches.append((match, has_kw))
    return matches


def _extract_emails(text: str) -> list[dict]:
    results: list[dict] = []
    for match in _EMAIL_RE.finditer(text):
        results.append({
            "value": match.group(0),
            "start": match.start(),
            "end": match.end(),
        })
    return results


def _extract_phones(text: str) -> list[dict]:
    results: list[dict] = []
    for match in _PHONE_CANDIDATE_RE.finditer(text):
        raw = match.group(0)
        normalized = validate_phone(raw)
        if not normalized:
            continue
        results.append({
            "value": raw,
            "start": match.start(),
            "end": match.end(),
            "normalized": normalized,
        })
    return results


def _extract_dates(text: str) -> list[dict]:
    results: list[dict] = []
    for match, has_kw in find_with_context(_DATE_RE, text, _BIRTH_KEYWORDS, window=40):
        raw = match.group(0)
        iso = validate_date(raw)
        if not iso:
            continue
        results.append({
            "value": raw,
            "start": match.start(),
            "end": match.end(),
            "iso": iso,
            "context": "birth" if has_kw else None,
            "expand_line": True if has_kw else False,
        })
    return results


def _extract_doc_numbers(text: str) -> list[dict]:
    results: list[dict] = []

    for match, has_kw in find_with_context(_CI_RE, text, _CONTEXT_KEYWORDS, window=50):
        raw_value = text[match.start():match.end()]
        value = re.sub(r"\s+", "", raw_value)
        if not validate_doc_number("CI_CARTACEA", value):
            continue
        confidence = "high" if has_kw else "medium"
        results.append({
            "type": "CI_CARTACEA",
            "value": value,
            "start": match.start(),
            "end": match.end(),
            "confidence": confidence,
        })

    for match, has_kw in find_with_context(_CIE_RE, text, _CONTEXT_KEYWORDS, window=50):
        raw_value = text[match.start():match.end()]
        value = re.sub(r"\s+", "", raw_value)
        if not validate_doc_number("CIE", value):
            continue
        confidence = "high" if has_kw else "medium"
        results.append({
            "type": "CIE",
            "value": value,
            "start": match.start(),
            "end": match.end(),
            "confidence": confidence,
        })

    for match, has_kw in find_with_context(_PATENTE_RE, text, _PATENTE_KEYWORDS, window=80):
        if not has_kw:
            continue
        value = text[match.start():match.end()]
        if not validate_doc_number("PATENTE", value):
            continue
        results.append({
            "type": "PATENTE",
            "value": value,
            "start": match.start(),
            "end": match.end(),
            "confidence": "medium",
        })

    return results


def extract_pii(text: str) -> dict:
    if not text:
        return {
            "emails": [],
            "phones": [],
            "birth_dates": [],
            "doc_numbers": [],
        }

    return {
        "emails": _extract_emails(text),
        "phones": _extract_phones(text),
        "birth_dates": _extract_dates(text),
        "doc_numbers": _extract_doc_numbers(text),
    }
