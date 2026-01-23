from __future__ import annotations

import re
from typing import Optional

import dateparser
import phonenumbers

_CI_RE = re.compile(r"^[A-Z]{2}\d{5,7}$")
_CIE_RE = re.compile(r"^[A-Z]{2}\d{5}[A-Z]{1,2}$")
_PATENTE_RE = re.compile(r"^[A-Z0-9]{10}$")


def validate_phone(raw: str, default_region: str = "IT") -> Optional[str]:
    if not raw:
        return None
    try:
        number = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException:
        return None

    if not phonenumbers.is_possible_number(number):
        return None
    if not phonenumbers.is_valid_number(number):
        return None

    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def validate_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    dt = dateparser.parse(
        raw,
        settings={
            "DATE_ORDER": "DMY",
            "PREFER_DATES_FROM": "past",
        },
    )
    if not dt:
        return None
    return dt.date().isoformat()


def _apply_ocr_fixes(value: str, letter_positions: set[int], digit_positions: set[int]) -> str:
    chars = list(value.upper())
    for idx in digit_positions:
        if idx < len(chars) and chars[idx] == "O":
            chars[idx] = "0"
    for idx in letter_positions:
        if idx < len(chars) and chars[idx] == "0":
            chars[idx] = "O"
    return "".join(chars)


def validate_doc_number(doc_type: str, value: str) -> bool:
    if not value:
        return False

    upper = re.sub(r"\s+", "", value.upper())

    if doc_type == "CI_CARTACEA":
        if _CI_RE.match(upper):
            return True
        fixed = _apply_ocr_fixes(upper, {0, 1}, set(range(2, len(upper))))
        return _CI_RE.match(fixed) is not None

    if doc_type == "CIE":
        if _CIE_RE.match(upper):
            return True
        fixed = _apply_ocr_fixes(upper, {0, 1, 7, 8}, set(range(2, 7)))
        return _CIE_RE.match(fixed) is not None

    if doc_type == "PATENTE":
        if _PATENTE_RE.match(upper) is None:
            return False
        if upper.isdigit() or upper.isalpha():
            return False
        return True

    return False
