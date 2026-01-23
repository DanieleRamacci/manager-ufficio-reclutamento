from __future__ import annotations

from typing import List, Dict
import re
import unicodedata


def _match_to_box(start: int, end: int, tokens: list[dict]) -> dict | None:
    selected = [t for t in tokens if t.get("end", 0) > start and t.get("start", 0) < end]
    if not selected:
        return None

    x1 = min(t["bbox"]["x1"] for t in selected)
    y1 = min(t["bbox"]["y1"] for t in selected)
    x2 = max(t["bbox"]["x2"] for t in selected)
    y2 = max(t["bbox"]["y2"] for t in selected)

    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _expand_to_line(start: int, end: int, tokens: list[dict]) -> dict | None:
    selected = [t for t in tokens if t.get("end", 0) > start and t.get("start", 0) < end]
    if not selected:
        return None
    line_id = selected[0].get("line_id")
    if line_id is None:
        return None
    line_tokens = [t for t in tokens if t.get("line_id") == line_id]
    if not line_tokens:
        return None
    x1 = min(t["bbox"]["x1"] for t in line_tokens)
    y1 = min(t["bbox"]["y1"] for t in line_tokens)
    x2 = max(t["bbox"]["x2"] for t in line_tokens)
    y2 = max(t["bbox"]["y2"] for t in line_tokens)
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def build_pii_boxes(pii: dict, tokens: list[dict], width: int, height: int) -> list[dict]:
    boxes: list[dict] = []

    def add_box(item: dict, label: str, confidence: str | None = None) -> None:
        box = None
        if item.get("expand_line"):
            box = _expand_to_line(item["start"], item["end"], tokens)
        if not box:
            box = _match_to_box(item["start"], item["end"], tokens)
        if not box:
            return
        x = box["x1"] / width
        y = box["y1"] / height
        w = (box["x2"] - box["x1"]) / width
        h = (box["y2"] - box["y1"]) / height
        boxes.append({
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "label": label,
            "confidence": confidence or "high",
            "source": "pii",
        })

    for item in pii.get("emails", []):
        add_box(item, "EMAIL", "high")
    for item in pii.get("phones", []):
        add_box(item, "PHONE", "high")
    for item in pii.get("birth_dates", []):
        add_box(item, "DATE", "high")
    for item in pii.get("doc_numbers", []):
        add_box(item, item.get("type", "DOC"), item.get("confidence"))

    return boxes


DOC_HEADER_STRONG = [
    "NUMERO DOCUMENTO",
    "N DOCUMENTO",
    "N. DOCUMENTO",
    "NUMERO DOC",
    "DOCUMENTO DI IDENTITA",
    "DOCUMENTO IDENTITA",
    "DOCUMENTO DI IDENTITÀ",
    "DOCUMENTO IDENTITÀ",
    "TIPOLOGIA DOCUMENTO",
]

DOC_HEADER_WEAK = ["DOCUMENTO", "IDENTITA", "IDENTITÀ", "DOC"]

SIGN_HEADER_STRONG = ["FIRMA", "FIRME", "SOTTOSCRIZIONE"]

NAME_HEADERS = ["COGNOME", "NOME"]

DOC_TABLE_KEYWORDS = [
    "DOCUMENTO DI IDENTITA",
    "DOCUMENTO IDENTITA",
    "DOCUMENTO DI IDENTITÀ",
    "DOCUMENTO IDENTITÀ",
    "NUMERO DOCUMENTO",
    "N DOCUMENTO",
    "N. DOCUMENTO",
    "NUMERO DOC",
    "TIPOLOGIA DOCUMENTO",
    "TIPOLOGIA",
    "CARTA DI IDENTITA",
    "CARTA D IDENTITA",
    "CARTA DI IDENTITÀ",
    "CARTA D IDENTITÀ",
    "PATENTE",
    "CIE",
]

GENERIC_HEADER_KEYWORDS = [
    "COGNOME",
    "NOME",
    "FIRMA",
    "DOCUMENTO",
    "IDENTITA",
    "IDENTITÀ",
    "DATA DI NASCITA",
    "NATO IL",
    "NATA IL",
    "CODICE FISCALE",
    "TELEFONO",
    "EMAIL",
]

DOC_COLUMN_HEADERS = [
    "NUMERO DOCUMENTO",
    "N DOCUMENTO",
    "N. DOCUMENTO",
    "NUMERO DOC",
    "DOCUMENTO DI IDENTITA",
    "DOCUMENTO IDENTITA",
    "DOCUMENTO DI IDENTITÀ",
    "DOCUMENTO IDENTITÀ",
]

_COLUMN_HEADERS = DOC_COLUMN_HEADERS + [
    "DATA DI NASCITA",
    "NATO IL",
    "NATA IL",
    "CODICE FISCALE",
    "EMAIL",
    "TELEFONO",
]

_TABLE_HEADER_KEYWORDS = DOC_TABLE_KEYWORDS + GENERIC_HEADER_KEYWORDS


def normalize_for_keywords(text: str) -> str:
    if not text:
        return ""
    t = text.upper()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.replace("0", "O").replace("1", "I")
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _line_in_table(line: dict, table_boxes: list[dict], width: int, height: int) -> bool:
    if not table_boxes:
        return False
    lb = line.get("bbox") or {}
    lx1 = int(lb.get("x1", 0))
    ly1 = int(lb.get("y1", 0))
    lx2 = int(lb.get("x2", 0))
    ly2 = int(lb.get("y2", 0))
    for tb in table_boxes:
        tx1 = int(tb.get("x", 0) * width)
        ty1 = int(tb.get("y", 0) * height)
        tx2 = int((tb.get("x", 0) + tb.get("w", 0)) * width)
        ty2 = int((tb.get("y", 0) + tb.get("h", 0)) * height)
        if lx1 >= tx1 and lx2 <= tx2 and ly1 >= ty1 and ly2 <= ty2:
            return True
    return False


def _map_point_to_original(x: int, y: int, rotation: int, orig_w: int, orig_h: int) -> tuple[int, int]:
    if rotation == 90:
        return y, orig_h - x - 1
    if rotation == 180:
        return orig_w - x - 1, orig_h - y - 1
    if rotation == 270:
        return orig_w - y - 1, x
    return x, y


def _map_point_to_rotated(x: int, y: int, rotation: int, orig_w: int, orig_h: int) -> tuple[int, int]:
    if rotation == 90:
        return orig_h - y - 1, x
    if rotation == 180:
        return orig_w - x - 1, orig_h - y - 1
    if rotation == 270:
        return y, orig_w - x - 1
    return x, y


def _map_bbox_to_rotated(bbox: dict, rotation: int, orig_w: int, orig_h: int) -> dict:
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
    points = [
        _map_point_to_rotated(x1, y1, rotation, orig_w, orig_h),
        _map_point_to_rotated(x2, y1, rotation, orig_w, orig_h),
        _map_point_to_rotated(x1, y2, rotation, orig_w, orig_h),
        _map_point_to_rotated(x2, y2, rotation, orig_w, orig_h),
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {
        "x1": max(0, min(xs)),
        "y1": max(0, min(ys)),
        "x2": max(xs),
        "y2": max(ys),
    }


def _map_bbox_to_original(bbox: dict, rotation: int, orig_w: int, orig_h: int) -> dict:
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
    points = [
        _map_point_to_original(x1, y1, rotation, orig_w, orig_h),
        _map_point_to_original(x2, y1, rotation, orig_w, orig_h),
        _map_point_to_original(x1, y2, rotation, orig_w, orig_h),
        _map_point_to_original(x2, y2, rotation, orig_w, orig_h),
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {
        "x1": max(0, min(xs)),
        "y1": max(0, min(ys)),
        "x2": max(xs),
        "y2": max(ys),
    }


def _has_table_like_column(header_line: dict, lines: list[dict], width: int, height: int) -> bool:
    bbox = header_line.get("bbox") or {}
    x1 = max(0, int(bbox.get("x1", 0)))
    y1 = max(0, int(bbox.get("y1", 0)))
    x2 = min(width, int(bbox.get("x2", width)))
    y2 = min(height, int(bbox.get("y2", height)))

    if x2 <= x1 or y2 <= y1:
        return False
    if (x2 - x1) / max(1, width) > 0.45:
        return False

    header_height = max(1, y2 - y1)
    col_top = min(height, y2 + 2)

    candidates = []
    for line in lines or []:
        lb = line.get("bbox") or {}
        ly1 = int(lb.get("y1", 0))
        ly2 = int(lb.get("y2", 0))
        if ly1 <= col_top:
            continue
        lx1 = int(lb.get("x1", 0))
        lx2 = int(lb.get("x2", 0))
        overlap = min(x2, lx2) - max(x1, lx1)
        if overlap <= 0:
            continue
        overlap_ratio = overlap / max(1, min(x2 - x1, lx2 - lx1))
        if overlap_ratio < 0.6:
            continue
        candidates.append((ly1, ly2))

    if len(candidates) < 3:
        return False

    candidates.sort()
    distinct_rows = 1
    last_y = candidates[0][0]
    for y_start, _ in candidates[1:]:
        if y_start - last_y > header_height * 0.8:
            distinct_rows += 1
            last_y = y_start

    return distinct_rows >= 3


def build_column_boxes(lines: list[dict], width: int, height: int, table_boxes: list[dict] | None = None) -> list[dict]:
    boxes: list[dict] = []
    if table_boxes is not None and not table_boxes:
        return boxes
    for line in lines or []:
        text = normalize_for_keywords(line.get("text") or "")
        if not text:
            continue
        header = None
        for key in _COLUMN_HEADERS:
            if normalize_for_keywords(key) in text:
                header = key
                break
        if not header:
            continue

        bbox = line.get("bbox") or {}
        x1 = max(0, int(bbox.get("x1", 0)))
        y1 = max(0, int(bbox.get("y1", 0)))
        x2 = min(width, int(bbox.get("x2", width)))
        y2 = min(height, int(bbox.get("y2", height)))

        if x2 <= x1 or y2 <= y1:
            continue

        if table_boxes is not None and not _line_in_table(line, table_boxes, width, height):
            continue

        if not _has_table_like_column(line, lines, width, height):
            continue

        col_top = min(height, y2 + 2)
        if col_top >= height:
            continue

        col_box = {
            "x": x1 / width,
            "y": col_top / height,
            "w": (x2 - x1) / width,
            "h": (height - col_top) / height,
            "label": f"COLUMN:{header}",
            "confidence": "high",
            "source": "pii",
            "kind": "column",
        }

        # merge overlapping columns (same x-range)
        merged = False
        for existing in boxes:
            if existing.get("kind") != "column":
                continue
            ex_left = existing["x"]
            ex_right = existing["x"] + existing["w"]
            new_left = col_box["x"]
            new_right = col_box["x"] + col_box["w"]
            overlap = min(ex_right, new_right) - max(ex_left, new_left)
            if overlap > 0 and overlap / max(existing["w"], col_box["w"]) > 0.8:
                existing["x"] = min(ex_left, new_left)
                existing["w"] = max(ex_right, new_right) - existing["x"]
                existing["y"] = min(existing["y"], col_box["y"])
                existing["h"] = max(existing["y"] + existing["h"], col_box["y"] + col_box["h"]) - existing["y"]
                merged = True
                break
        if not merged:
            boxes.append(col_box)

    return boxes


def build_column_boxes_with_rotation(
    lines: list[dict],
    width: int,
    height: int,
    table_boxes: list[dict] | None,
    rotation: int,
) -> list[dict]:
    if rotation not in (90, 180, 270):
        return build_column_boxes(lines, width, height, table_boxes)

    rot_w = height if rotation in (90, 270) else width
    rot_h = width if rotation in (90, 270) else height

    rotated_lines: list[dict] = []
    for line in lines or []:
        lb = line.get("bbox") or {}
        rb = _map_bbox_to_rotated(lb, rotation, width, height)
        rotated_lines.append({
            "text": line.get("text"),
            "bbox": rb,
            "line_id": line.get("line_id"),
        })

    rotated_tables: list[dict] | None = None
    if table_boxes is not None:
        rotated_tables = []
        for tb in table_boxes:
            tb_px = {
                "x1": int(tb.get("x", 0) * width),
                "y1": int(tb.get("y", 0) * height),
                "x2": int((tb.get("x", 0) + tb.get("w", 0)) * width),
                "y2": int((tb.get("y", 0) + tb.get("h", 0)) * height),
            }
            rb = _map_bbox_to_rotated(tb_px, rotation, width, height)
            rotated_tables.append({
                "x": rb["x1"] / rot_w,
                "y": rb["y1"] / rot_h,
                "w": (rb["x2"] - rb["x1"]) / rot_w,
                "h": (rb["y2"] - rb["y1"]) / rot_h,
            })

    col_boxes_rot = build_column_boxes(rotated_lines, rot_w, rot_h, rotated_tables)

    col_boxes: list[dict] = []
    for cb in col_boxes_rot:
        cb_px = {
            "x1": int(cb["x"] * rot_w),
            "y1": int(cb["y"] * rot_h),
            "x2": int((cb["x"] + cb["w"]) * rot_w),
            "y2": int((cb["y"] + cb["h"]) * rot_h),
        }
        ob = _map_bbox_to_original(cb_px, rotation, width, height)
        col_boxes.append({
            "x": ob["x1"] / width,
            "y": ob["y1"] / height,
            "w": (ob["x2"] - ob["x1"]) / width,
            "h": (ob["y2"] - ob["y1"]) / height,
            "label": cb.get("label"),
            "confidence": cb.get("confidence"),
            "source": cb.get("source"),
            "kind": cb.get("kind"),
        })

    return col_boxes


def build_column_value_boxes(column_boxes: list[dict], tokens: list[dict], width: int, height: int) -> list[dict]:
    from .validators import validate_doc_number

    boxes: list[dict] = []
    for col in column_boxes or []:
        label = normalize_for_keywords(col.get("label", ""))
        if not (any(normalize_for_keywords(h) in label for h in DOC_COLUMN_HEADERS) or "DOCUMENTO" in label):
            continue

        col_x1 = int(col["x"] * width)
        col_x2 = int((col["x"] + col["w"]) * width)
        col_y1 = int(col["y"] * height)

        line_map: dict = {}
        for t in tokens:
            bb = t.get("bbox") or {}
            tx1 = int(bb.get("x1", 0))
            tx2 = int(bb.get("x2", 0))
            ty1 = int(bb.get("y1", 0))
            ty2 = int(bb.get("y2", 0))
            if ty2 < col_y1:
                continue
            if tx2 < col_x1 or tx1 > col_x2:
                continue
            line_id = t.get("line_id")
            line_map.setdefault(line_id, []).append(t)

        for _, line_tokens in line_map.items():
            if not line_tokens:
                continue
            line_tokens.sort(key=lambda t: (t["bbox"]["x1"], t["bbox"]["y1"]))
            raw = "".join(t["text"] for t in line_tokens)
            cleaned = "".join(ch for ch in raw.upper() if ch.isalnum())
            if len(cleaned) < 7 or len(cleaned) > 12:
                continue

            letters = sum(1 for ch in cleaned if ch.isalpha())
            digits = sum(1 for ch in cleaned if ch.isdigit())
            if letters < 2 or digits < 3:
                continue

            is_valid = (
                validate_doc_number("CIE", cleaned)
                or validate_doc_number("CI_CARTACEA", cleaned)
                or validate_doc_number("PATENTE", cleaned)
            )

            if not is_valid:
                continue

            x1 = min(t["bbox"]["x1"] for t in line_tokens)
            y1 = min(t["bbox"]["y1"] for t in line_tokens)
            x2 = max(t["bbox"]["x2"] for t in line_tokens)
            y2 = max(t["bbox"]["y2"] for t in line_tokens)

            boxes.append({
                "x": x1 / width,
                "y": y1 / height,
                "w": (x2 - x1) / width,
                "h": (y2 - y1) / height,
                "label": "DOC_IN_COLUMN",
                "confidence": "high",
                "source": "pii_column",
            })

    return boxes


def build_column_from_doc_tokens(tokens: list[dict], width: int, height: int, min_count: int = 3) -> list[dict]:
    from .validators import validate_doc_number

    doc_boxes: list[dict] = []
    line_map: dict = {}
    for t in tokens:
        line_id = t.get("line_id")
        line_map.setdefault(line_id, []).append(t)

    for _, line_tokens in line_map.items():
        if not line_tokens:
            continue
        line_tokens.sort(key=lambda t: (t["bbox"]["x1"], t["bbox"]["y1"]))
        raw = "".join(t["text"] for t in line_tokens)
        cleaned = "".join(ch for ch in raw.upper() if ch.isalnum())
        if len(cleaned) < 7 or len(cleaned) > 12:
            continue
        letters = sum(1 for ch in cleaned if ch.isalpha())
        digits = sum(1 for ch in cleaned if ch.isdigit())
        if letters < 2 or digits < 3:
            continue
        if not (validate_doc_number("CIE", cleaned) or validate_doc_number("CI_CARTACEA", cleaned) or validate_doc_number("PATENTE", cleaned)):
            continue

        x1 = min(t["bbox"]["x1"] for t in line_tokens)
        y1 = min(t["bbox"]["y1"] for t in line_tokens)
        x2 = max(t["bbox"]["x2"] for t in line_tokens)
        y2 = max(t["bbox"]["y2"] for t in line_tokens)
        doc_boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})

    if len(doc_boxes) < min_count:
        return []

    x1 = min(b["x1"] for b in doc_boxes)
    x2 = max(b["x2"] for b in doc_boxes)
    y1 = min(b["y1"] for b in doc_boxes)

    return [{
        "x": x1 / width,
        "y": y1 / height,
        "w": (x2 - x1) / width,
        "h": (height - y1) / height,
        "label": "COLUMN:NUMERO DOCUMENTO",
        "confidence": "medium",
        "source": "pii",
        "kind": "column",
    }]


def build_table_header_boxes(lines: list[dict], width: int, height: int) -> list[dict]:
    boxes: list[dict] = []
    header_cells = build_header_cells(lines, width, height, header_ratio=0.25)
    for cell in header_cells:
        text = normalize_for_keywords(cell.get("text") or "")
        if not text:
            continue
        matched = None
        for key in _TABLE_HEADER_KEYWORDS:
            if normalize_for_keywords(key) in text:
                matched = key
                break
        if not matched:
            continue
        bbox = cell.get("bbox") or {}
        x1 = int(bbox.get("x1", 0))
        y1 = int(bbox.get("y1", 0))
        x2 = int(bbox.get("x2", 0))
        y2 = int(bbox.get("y2", 0))
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append({
            "x": x1 / width,
            "y": y1 / height,
            "w": (x2 - x1) / width,
            "h": (y2 - y1) / height,
            "label": f"HEADER:{matched}",
            "confidence": "high",
            "source": "table_header",
        })
    return boxes


def _line_overlap_ratio(a: dict, b: dict) -> float:
    ax1, ax2 = a["x1"], a["x2"]
    bx1, bx2 = b["x1"], b["x2"]
    overlap = min(ax2, bx2) - max(ax1, bx1)
    if overlap <= 0:
        return 0.0
    aw = max(1, ax2 - ax1)
    bw = max(1, bx2 - bx1)
    return overlap / max(1, min(aw, bw))


def build_header_cells(
    lines: list[dict],
    width: int,
    height: int,
    header_ratio: float = 0.25,
    band: str = "top",
) -> list[dict]:
    header_lines = []
    x_limit = max(1, int(width * header_ratio))
    y_limit = max(1, int(height * header_ratio))
    for line in lines or []:
        bb = line.get("bbox") or {}
        x_mid = (int(bb.get("x1", 0)) + int(bb.get("x2", 0))) // 2
        y_mid = (int(bb.get("y1", 0)) + int(bb.get("y2", 0))) // 2
        if band == "top" and y_mid <= y_limit:
            header_lines.append(line)
        elif band == "bottom" and y_mid >= (height - y_limit):
            header_lines.append(line)
        elif band == "left" and x_mid <= x_limit:
            header_lines.append(line)
        elif band == "right" and x_mid >= (width - x_limit):
            header_lines.append(line)

    groups: list[dict] = []
    for line in header_lines:
        bb = line.get("bbox") or {}
        line_box = {
            "x1": int(bb.get("x1", 0)),
            "y1": int(bb.get("y1", 0)),
            "x2": int(bb.get("x2", 0)),
            "y2": int(bb.get("y2", 0)),
        }
        best_group = None
        best_overlap = 0.0
        for group in groups:
            overlap = _line_overlap_ratio(line_box, group["bbox"])
            if overlap >= 0.6 and overlap > best_overlap:
                best_overlap = overlap
                best_group = group
        if not best_group:
            groups.append({
                "lines": [line],
                "bbox": dict(line_box),
            })
        else:
            best_group["lines"].append(line)
            gb = best_group["bbox"]
            gb["x1"] = min(gb["x1"], line_box["x1"])
            gb["y1"] = min(gb["y1"], line_box["y1"])
            gb["x2"] = max(gb["x2"], line_box["x2"])
            gb["y2"] = max(gb["y2"], line_box["y2"])

    cells: list[dict] = []
    for group in groups:
        group_lines = group["lines"]
        group_lines.sort(key=lambda l: (l["bbox"]["y1"], l["bbox"]["x1"]))
        text = " ".join((l.get("text") or "").strip() for l in group_lines if (l.get("text") or "").strip())
        cells.append({
            "text": text,
            "bbox": group["bbox"],
            "band": band,
        })

    return cells


def _fuzzy_partial_ratio(a: str, b: str) -> int:
    try:
        from rapidfuzz import fuzz

        return int(fuzz.partial_ratio(a, b))
    except Exception:
        import difflib

        if not a or not b:
            return 0
        if len(a) > len(b):
            a, b = b, a
        best = 0.0
        a_len = len(a)
        for i in range(0, len(b) - a_len + 1):
            window = b[i : i + a_len]
            ratio = difflib.SequenceMatcher(None, a, window).ratio()
            if ratio > best:
                best = ratio
        return int(best * 100)


def _classify_header_cell(cell_text: str) -> dict:
    norm = normalize_for_keywords(cell_text)
    strong_hits = [k for k in DOC_HEADER_STRONG if normalize_for_keywords(k) in norm]
    weak_hits = [k for k in DOC_HEADER_WEAK if normalize_for_keywords(k) in norm]
    sign_hits = [k for k in SIGN_HEADER_STRONG if normalize_for_keywords(k) in norm]
    name_hits = [k for k in NAME_HEADERS if normalize_for_keywords(k) in norm]

    fuzzy_target = normalize_for_keywords("DOCUMENTO IDENTITA").replace(" ", "")
    fuzzy_text = norm.replace(" ", "")
    fuzzy_score = _fuzzy_partial_ratio(fuzzy_target, fuzzy_text)

    doc_match = None
    if strong_hits:
        doc_match = "strong"
    elif weak_hits:
        doc_match = "weak"
    elif fuzzy_score >= 75:
        doc_match = "fuzzy"

    return {
        "norm": norm,
        "strong_hits": strong_hits,
        "weak_hits": weak_hits,
        "sign_hits": sign_hits,
        "name_hits": name_hits,
        "fuzzy_score": fuzzy_score,
        "doc_match": doc_match,
    }


def _doc_score_for_cell(cell_bbox: dict, tokens: list[dict], header_bottom: int) -> tuple[int, list[str]]:
    from .validators import validate_doc_number

    x1 = int(cell_bbox["x1"])
    x2 = int(cell_bbox["x2"])
    matches: set[str] = set()

    line_map: dict = {}
    for t in tokens:
        bb = t.get("bbox") or {}
        cx = (int(bb.get("x1", 0)) + int(bb.get("x2", 0))) // 2
        cy = (int(bb.get("y1", 0)) + int(bb.get("y2", 0))) // 2
        if cy <= header_bottom:
            continue
        if cx < x1 or cx > x2:
            continue
        line_map.setdefault(t.get("line_id"), []).append(t)

        raw_token = (t.get("text") or "").upper()
        cleaned = "".join(ch for ch in raw_token if ch.isalnum())
        if validate_doc_number("CIE", cleaned) or validate_doc_number("CI_CARTACEA", cleaned) or validate_doc_number("PATENTE", cleaned):
            matches.add(cleaned)

    for _, line_tokens in line_map.items():
        if not line_tokens:
            continue
        line_tokens.sort(key=lambda t: (t["bbox"]["x1"], t["bbox"]["y1"]))
        raw = "".join(t["text"] for t in line_tokens)
        cleaned = "".join(ch for ch in raw.upper() if ch.isalnum())
        if validate_doc_number("CIE", cleaned) or validate_doc_number("CI_CARTACEA", cleaned) or validate_doc_number("PATENTE", cleaned):
            matches.add(cleaned)

    return len(matches), sorted(matches)


def _doc_column_from_tokens(tokens: list[dict], width: int, min_count: int = 2) -> dict | None:
    from .validators import validate_doc_number

    groups: list[dict] = []
    threshold = max(8, int(width * 0.05))

    for t in tokens:
        raw = (t.get("text") or "").upper()
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if not cleaned:
            continue
        if not (
            validate_doc_number("CIE", cleaned)
            or validate_doc_number("CI_CARTACEA", cleaned)
            or validate_doc_number("PATENTE", cleaned)
        ):
            continue

        bb = t.get("bbox") or {}
        cx = (int(bb.get("x1", 0)) + int(bb.get("x2", 0))) // 2
        cy = (int(bb.get("y1", 0)) + int(bb.get("y2", 0))) // 2
        group = None
        for g in groups:
            if abs(cx - g["cx"]) <= threshold:
                group = g
                break
        if not group:
            group = {
                "cx": cx,
                "x1": int(bb.get("x1", 0)),
                "x2": int(bb.get("x2", 0)),
                "y1": int(bb.get("y1", 0)),
                "count": 0,
            }
            groups.append(group)

        group["count"] += 1
        group["x1"] = min(group["x1"], int(bb.get("x1", 0)))
        group["x2"] = max(group["x2"], int(bb.get("x2", 0)))
        group["y1"] = min(group["y1"], int(bb.get("y1", 0)))

    if not groups:
        return None
    best = max(groups, key=lambda g: g["count"])
    if best["count"] < min_count:
        return None

    return {
        "x1": best["x1"],
        "x2": best["x2"],
        "y1": best["y1"],
        "count": best["count"],
    }


def detect_document_and_signature_columns(
    lines: list[dict],
    tokens: list[dict],
    width: int,
    height: int,
    header_ratio: float = 0.25,
    min_doc_score: int = 2,
) -> tuple[list[dict], dict]:
    header_cells = build_header_cells(lines, width, height, header_ratio=header_ratio, band="top")
    if not header_cells:
        header_cells = []

    extra_cells: list[dict] = []
    if header_cells:
        has_any = any(c.get("text") for c in header_cells)
    else:
        has_any = False
    if not has_any:
        extra_cells.extend(build_header_cells(lines, width, height, header_ratio=header_ratio, band="left"))
        extra_cells.extend(build_header_cells(lines, width, height, header_ratio=header_ratio, band="right"))
        extra_cells.extend(build_header_cells(lines, width, height, header_ratio=header_ratio, band="bottom"))
        header_cells = header_cells + extra_cells
    debug_cells = []

    for cell in header_cells:
        info = _classify_header_cell(cell.get("text", ""))
        header_bottom = int(cell["bbox"]["y2"])
        doc_score, doc_matches = _doc_score_for_cell(cell["bbox"], tokens, header_bottom)
        debug_cells.append({
            "text": cell.get("text", ""),
            "norm": info["norm"],
            "bbox": cell["bbox"],
            "band": cell.get("band"),
            "strong_hits": info["strong_hits"],
            "weak_hits": info["weak_hits"],
            "sign_hits": info["sign_hits"],
            "name_hits": info["name_hits"],
            "fuzzy_score": info["fuzzy_score"],
            "doc_match": info["doc_match"],
            "doc_score": doc_score,
            "doc_matches": doc_matches,
        })
        cell["doc_match"] = info["doc_match"]
        cell["fuzzy_score"] = info["fuzzy_score"]
        cell["doc_score"] = doc_score
        cell["sign_match"] = bool(info["sign_hits"])

    doc_cell = None
    doc_fallback = None
    strong_cells = [c for c in header_cells if c.get("doc_match") == "strong"]
    if strong_cells:
        doc_cell = max(strong_cells, key=lambda c: (c.get("doc_score", 0), c.get("fuzzy_score", 0)))
        doc_source = "header_strong"
    else:
        weak_cells = [c for c in header_cells if c.get("doc_match") in ("weak", "fuzzy")]
        if weak_cells:
            doc_cell = max(weak_cells, key=lambda c: (c.get("doc_score", 0), c.get("fuzzy_score", 0)))
            doc_source = "header_weak"
        else:
            scored = [c for c in header_cells if c.get("doc_score", 0) >= min_doc_score]
            if scored:
                doc_cell = max(scored, key=lambda c: c.get("doc_score", 0))
                doc_source = "doc_score"
            else:
                doc_source = "none"
                doc_fallback = _doc_column_from_tokens(tokens, width, min_count=min_doc_score)
                if doc_fallback:
                    doc_cell = {
                        "bbox": {
                            "x1": doc_fallback["x1"],
                            "x2": doc_fallback["x2"],
                            "y2": doc_fallback["y1"],
                        }
                    }
                    doc_source = "doc_score_fallback"

    sign_cell = None
    sign_cells = [c for c in header_cells if c.get("sign_match")]
    if sign_cells:
        sign_cell = max(sign_cells, key=lambda c: c["bbox"]["x2"] - c["bbox"]["x1"])

    columns: list[dict] = []
    if doc_cell:
        pad = int(width * 0.01)
        x1 = max(0, doc_cell["bbox"]["x1"] - pad)
        x2 = min(width, doc_cell["bbox"]["x2"] + pad)
        y1 = min(height, doc_cell["bbox"]["y2"] + 1)
        columns.append({
            "x": x1 / width,
            "y": y1 / height,
            "w": (x2 - x1) / width,
            "h": (height - y1) / height,
            "label": "COLUMN:DOCUMENTO",
            "confidence": "high" if doc_source != "doc_score" else "medium",
            "source": doc_source,
            "kind": "column",
        })

    if sign_cell:
        pad = int(width * 0.01)
        x1 = max(0, sign_cell["bbox"]["x1"] - pad)
        x2 = min(width, sign_cell["bbox"]["x2"] + pad)
        y1 = min(height, sign_cell["bbox"]["y2"] + 1)
        columns.append({
            "x": x1 / width,
            "y": y1 / height,
            "w": (x2 - x1) / width,
            "h": (height - y1) / height,
            "label": "COLUMN:FIRMA",
            "confidence": "high",
            "source": "header_sign",
            "kind": "column",
        })

    debug = {
        "header_cells": debug_cells,
        "doc_source": doc_source if doc_cell else "none",
        "sign_found": bool(sign_cell),
        "columns": [c.get("label") for c in columns],
        "doc_fallback": doc_fallback,
    }

    return columns, debug
