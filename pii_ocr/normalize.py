import re


def normalize_text(text: str) -> str:
    """
    Normalize OCR text conservatively.

    - Uppercase
    - Normalize newlines
    - Collapse repeated spaces
    """
    if not text:
        return ""

    normalized = text.upper()
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[\t ]+", " ", normalized)
    normalized = re.sub(r"\n{2,}", "\n", normalized)
    return normalized.strip()

