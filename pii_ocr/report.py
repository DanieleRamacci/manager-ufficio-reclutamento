from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def save_report(report: dict, out_path: str) -> None:
    try:
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.error("Failed to write report %s: %s", out_path, exc)
        raise

