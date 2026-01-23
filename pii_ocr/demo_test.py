from __future__ import annotations

from pii_ocr.extractors import extract_pii
from pii_ocr.normalize import normalize_text


def run_demo_tests() -> None:
    samples = [
        "Email: mario.rossi@example.com Telefono: +39 333 1234567",
        "CARTA DI IDENTITA AB1234567 rilasciata il 01/02/1990",
        "Documento CIE AB12345CD",
        "Numero PATENTE A1B2C3D4E5",
        "PATENTE: 1234567890",  # invalid, only digits
    ]

    text = normalize_text("\n".join(samples))
    result = extract_pii(text)

    emails = [e["value"] for e in result["emails"]]
    phones = [p["normalized"] for p in result["phones"]]
    doc_types = [d["type"] for d in result["doc_numbers"]]
    doc_values = [d["value"] for d in result["doc_numbers"]]

    assert "MARIO.ROSSI@EXAMPLE.COM" in emails
    assert any(p.startswith("+39") for p in phones)
    assert "CI_CARTACEA" in doc_types
    assert "CIE" in doc_types
    assert "A1B2C3D4E5" in doc_values
    assert "1234567890" not in doc_values


if __name__ == "__main__":
    run_demo_tests()
    print("PII demo tests passed")

