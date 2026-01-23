from __future__ import annotations

import logging
import os
from datetime import datetime

from .extractors import extract_pii
from .normalize import normalize_text
from .ocr_engine import extract_ocr_from_images
from .report import save_report

log = logging.getLogger(__name__)


def _aggregate_unique(pages: list[dict]) -> dict:
    emails = set()
    phones = set()
    birth_dates = set()
    doc_numbers = set()

    for page in pages:
        pii = page.get("pii", {})
        for item in pii.get("emails", []):
            emails.add(item.get("value"))
        for item in pii.get("phones", []):
            phones.add(item.get("normalized") or item.get("value"))
        for item in pii.get("birth_dates", []):
            birth_dates.add(item.get("iso") or item.get("value"))
        for item in pii.get("doc_numbers", []):
            doc_numbers.add((item.get("type"), item.get("value")))

    return {
        "unique_emails": sorted(v for v in emails if v),
        "unique_phones": sorted(v for v in phones if v),
        "unique_birth_dates": sorted(v for v in birth_dates if v),
        "unique_doc_numbers": [
            {"type": doc_type, "value": value}
            for doc_type, value in sorted(doc_numbers)
            if doc_type and value
        ],
    }


def run_pii_pipeline(image_paths: list[str], out_dir: str, job_id: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)

    ocr_pages = extract_ocr_from_images(image_paths)
    pages: list[dict] = []

    for page in ocr_pages:
        raw = page.get("text_raw", "")
        normalized = normalize_text(raw)
        pii = extract_pii(raw.upper())

        pages.append({
            "page_index": page.get("page_index"),
            "image_path": page.get("image_path"),
            "text_raw": raw,
            "text_normalized": normalized,
            "pii": pii,
        })

    report = {
        "job_id": job_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "num_pages": len(pages),
        "pages": pages,
        "aggregates": _aggregate_unique(pages),
    }

    report_path = os.path.join(out_dir, f"pii_report_{job_id}.json")
    save_report(report, report_path)

    if os.environ.get("PII_OCR_DEBUG") == "1":
        for page in pages:
            idx = page.get("page_index")
            debug_path = os.path.join(out_dir, f"pii_debug_page_{idx}.txt")
            with open(debug_path, "w", encoding="utf-8") as handle:
                handle.write("RAW\n")
                handle.write(page.get("text_raw", ""))
                handle.write("\n\nNORMALIZED\n")
                handle.write(page.get("text_normalized", ""))

    log.info("PII report saved to %s", report_path)
    return report
