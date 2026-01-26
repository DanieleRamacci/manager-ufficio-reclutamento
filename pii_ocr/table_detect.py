from __future__ import annotations

import os
import logging
import re
from typing import List, Optional

import cv2
import numpy as np
import pytesseract
from pytesseract import Output
from PIL import Image

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None

try:
    from ultralyticsplus import YOLO as YOLOPlus
except Exception:
    YOLOPlus = None

from .boxes import (
    DOC_TABLE_KEYWORDS,
    GENERIC_HEADER_KEYWORDS,
    DOC_HEADER_STRONG,
    DOC_HEADER_WEAK,
    SIGN_HEADER_STRONG,
    normalize_for_keywords,
    detect_document_and_signature_columns,
    build_table_header_boxes,
)
from .extractors import extract_pii
from .validators import validate_doc_number

_CF_RE = re.compile(r"\\b[A-Z]{6}\\d{2}[A-Z]\\d{2}[A-Z]\\d{3}[A-Z]\\b")

log = logging.getLogger(__name__)

HEADER_KEYWORDS = DOC_TABLE_KEYWORDS + GENERIC_HEADER_KEYWORDS

ROI_NAMES = ("top", "bottom", "left", "right")

_YOLO_TABLE_MODEL: Optional[object] = None
_YOLO_TABLE_MODEL_NAME: Optional[str] = None


def _keyword_score(text: str) -> int:
    if not text:
        return 0
    norm = normalize_for_keywords(text)
    hits = []
    for key in HEADER_KEYWORDS:
        key_norm = normalize_for_keywords(key)
        if not key_norm:
            continue
        if key_norm in norm:
            hits.append(key)
    return len(set(hits))


def _ocr_roi_text(roi_bgr: np.ndarray, lang: str, config: str) -> str:
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    roi_thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    try:
        return pytesseract.image_to_string(roi_thresh, lang=lang, config=config)
    except Exception:
        return ""


def _extract_rois(rot_bgr: np.ndarray) -> dict[str, np.ndarray]:
    h, w = rot_bgr.shape[:2]
    band_h = max(1, int(h * 0.22))
    band_w = max(1, int(w * 0.22))
    return {
        "top": rot_bgr[:band_h, :],
        "bottom": rot_bgr[h - band_h : h, :],
        "left": rot_bgr[:, :band_w],
        "right": rot_bgr[:, w - band_w : w],
    }


def _rotate_image(img: np.ndarray, rotation: int) -> np.ndarray:
    if rotation == 0:
        return img
    if rotation == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if rotation == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if rotation == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _map_bbox_to_original(bbox: dict, rotation: int, orig_w: int, orig_h: int) -> dict:
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]

    def map_point(x: int, y: int) -> tuple[int, int]:
        if rotation == 90:
            return y, orig_h - x - 1
        if rotation == 180:
            return orig_w - x - 1, orig_h - y - 1
        if rotation == 270:
            return orig_w - y - 1, x
        return x, y

    points = [
        map_point(x1, y1),
        map_point(x2, y1),
        map_point(x1, y2),
        map_point(x2, y2),
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {
        "x1": max(0, min(xs)),
        "y1": max(0, min(ys)),
        "x2": min(orig_w, max(xs)),
        "y2": min(orig_h, max(ys)),
    }


def _map_bbox_to_rotated(bbox: dict, rotation: int, orig_w: int, orig_h: int) -> dict:
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]

    def map_point(x: int, y: int) -> tuple[int, int]:
        if rotation == 90:
            return orig_h - y - 1, x
        if rotation == 180:
            return orig_w - x - 1, orig_h - y - 1
        if rotation == 270:
            return y, orig_w - x - 1
        return x, y

    points = [
        map_point(x1, y1),
        map_point(x2, y1),
        map_point(x1, y2),
        map_point(x2, y2),
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {
        "x1": max(0, min(xs)),
        "y1": max(0, min(ys)),
        "x2": max(xs),
        "y2": max(ys),
    }


def _detect_rotation_osd(pil_img: Image.Image) -> int:
    try:
        osd = pytesseract.image_to_osd(pil_img)
        for line in osd.splitlines():
            if line.lower().startswith("rotate:"):
                return int(line.split(":")[1].strip())
    except Exception as exc:
        log.debug("OSD failed: %s", exc)
    return 0


def _load_yolo_table_model() -> Optional[object]:
    global _YOLO_TABLE_MODEL, _YOLO_TABLE_MODEL_NAME
    model_name = os.environ.get("PII_TABLE_YOLO_MODEL", "foduucom/table-detection-and-extraction")
    if _YOLO_TABLE_MODEL is not None and _YOLO_TABLE_MODEL_NAME == model_name:
        return _YOLO_TABLE_MODEL
    model = None
    try:
        # Prefer ultralyticsplus for HF models
        if YOLOPlus is not None and "/" in model_name and not model_name.endswith(".pt"):
            model = YOLOPlus(model_name)
        elif YOLO is not None:
            model = YOLO(model_name)
        else:
            model = None
        if model is None:
            return None
        _YOLO_TABLE_MODEL = model
        _YOLO_TABLE_MODEL_NAME = model_name
        return model
    except Exception as exc:
        log.warning("YOLO table model load failed: %s", exc)
        _YOLO_TABLE_MODEL = None
        _YOLO_TABLE_MODEL_NAME = None
        return None


def _detect_column_boxes_in_rotated_table(rot_crop: np.ndarray) -> list[dict]:
    rot_h, rot_w = rot_crop.shape[:2]
    if rot_h <= 0 or rot_w <= 0:
        return []

    gray = cv2.cvtColor(rot_crop, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    kernel_h = max(10, int(rot_h * 0.6))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_h))
    vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel, iterations=1)
    vertical = cv2.dilate(vertical, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

    cnts = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]

    lines: list[dict] = []
    max_line_w = max(5, int(rot_w * 0.02))
    min_line_h = int(rot_h * 0.5)
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if h < min_line_h:
            continue
        if w > max_line_w:
            continue
        lines.append({"x1": x, "x2": x + w})

    if not lines:
        return []

    lines.sort(key=lambda l: l["x1"])
    merged: list[dict] = []
    for ln in lines:
        if not merged or ln["x1"] > merged[-1]["x2"] + 2:
            merged.append(dict(ln))
        else:
            merged[-1]["x2"] = max(merged[-1]["x2"], ln["x2"])

    min_col_w = max(15, int(rot_w * 0.05))
    cols: list[dict] = []
    prev = 0
    for ln in merged:
        if ln["x1"] - prev >= min_col_w:
            cols.append({"x1": prev, "x2": ln["x1"], "y1": 0, "y2": rot_h})
        prev = ln["x2"]
    if rot_w - prev >= min_col_w:
        cols.append({"x1": prev, "x2": rot_w, "y1": 0, "y2": rot_h})

    return cols


def _column_header_text(
    lines: list[dict],
    col_x1: int,
    col_x2: int,
    width: int,
    height: int,
    header_ratio: float = 0.25,
) -> str:
    if width <= 0 or height <= 0:
        return ""
    top_y = int(height * header_ratio)
    parts: list[str] = []
    for line in lines or []:
        lb = line.get("bbox") or {}
        lx1 = int(lb.get("x1", 0))
        lx2 = int(lb.get("x2", 0))
        ly1 = int(lb.get("y1", 0))
        ly2 = int(lb.get("y2", 0))
        if lx2 < col_x1 or lx1 > col_x2:
            continue

        in_top = ly2 <= top_y
        if not in_top:
            continue

        text = (line.get("text") or "").strip()
        if text:
            parts.append(text)

    return " ".join(parts)


def _label_from_header_text(text: str) -> str | None:
    norm = normalize_for_keywords(text)
    if not norm:
        return None

    if any(normalize_for_keywords(k) in norm for k in SIGN_HEADER_STRONG):
        return "COLUMN:FIRMA"

    if any(normalize_for_keywords(k) in norm for k in DOC_HEADER_STRONG):
        return "COLUMN:DOCUMENTO"
    if any(normalize_for_keywords(k) in norm for k in DOC_HEADER_WEAK):
        return "COLUMN:DOCUMENTO"

    if "CODICE FISCALE" in norm:
        return "COLUMN:CODICE_FISCALE"
    if "DATA DI NASCITA" in norm or "NATO IL" in norm or "NATA IL" in norm:
        return "COLUMN:DATA_NASCITA"
    if "EMAIL" in norm or "E MAIL" in norm or "MAIL" in norm:
        return "COLUMN:EMAIL"
    if "TELEFONO" in norm or "TEL" in norm or "CELL" in norm:
        return "COLUMN:TELEFONO"

    return None


def _column_text_from_tokens(tokens: list[dict], col_x1: int, col_x2: int) -> str:
    line_map: dict = {}
    for t in tokens or []:
        bb = t.get("bbox") or {}
        tx1 = int(bb.get("x1", 0))
        tx2 = int(bb.get("x2", 0))
        if tx2 < col_x1 or tx1 > col_x2:
            continue
        line_id = t.get("line_id")
        line_map.setdefault(line_id, []).append(t)

    lines: list[str] = []
    for _, line_tokens in line_map.items():
        line_tokens.sort(key=lambda t: (t["bbox"]["x1"], t["bbox"]["y1"]))
        raw = " ".join(t.get("text", "") for t in line_tokens if t.get("text"))
        if raw:
            lines.append(raw)
    return "\n".join(lines)


def _column_has_sensitive_data(
    col_x1: int,
    col_x2: int,
    lines: list[dict],
    tokens: list[dict],
    width: int,
    height: int,
) -> tuple[bool, str | None, str | None]:
    header_text = _column_header_text(lines, col_x1, col_x2, width, height, header_ratio=0.25)
    header_label = _label_from_header_text(header_text)
    if header_label:
        return True, header_label, "header"

    column_text = _column_text_from_tokens(tokens, col_x1, col_x2)
    if column_text:
        pii = extract_pii(column_text.upper())
        if pii.get("doc_numbers"):
            return True, "COLUMN:DOCUMENTO", "data"
        if pii.get("emails"):
            return True, "COLUMN:EMAIL", "data"
        if pii.get("phones"):
            return True, "COLUMN:TELEFONO", "data"
        if pii.get("birth_dates"):
            return True, "COLUMN:DATA_NASCITA", "data"

        cleaned = re.sub(r"\\s+", "", column_text.upper())
        if _CF_RE.search(cleaned):
            return True, "COLUMN:CODICE_FISCALE", "data"

        # fallback: validate doc numbers per line
        for line in column_text.splitlines():
            cleaned_line = "".join(ch for ch in line.upper() if ch.isalnum())
            if len(cleaned_line) < 7 or len(cleaned_line) > 12:
                continue
            if (
                validate_doc_number("CIE", cleaned_line)
                or validate_doc_number("CI_CARTACEA", cleaned_line)
                or validate_doc_number("PATENTE", cleaned_line)
            ):
                return True, "COLUMN:DOCUMENTO", "data"

    return False, None, None


def detect_table_rotation_by_headers(
    crop_bgr: np.ndarray,
    lang: str,
    config: str,
    debug_tag: str | None = None,
    debug_dir: str | None = None,
) -> tuple[int, int, str, dict]:
    best_rotation = 0
    best_score = -1
    best_text = ""
    best_alpha = -1
    debug_summary: dict = {"rotations": {}}

    debug_enabled = os.environ.get("PII_OCR_DEBUG", "0") == "1"
    if debug_enabled:
        if not debug_dir:
            debug_dir = os.environ.get("PII_OCR_DEBUG_DIR", "pii_ocr_debug")
        os.makedirs(debug_dir, exist_ok=True)

    config_a = "--oem 3 --psm 6"
    config_b = "--oem 3 --psm 11"

    for rotation in (0, 90, 180, 270):
        rot = _rotate_image(crop_bgr, rotation)
        rois = _extract_rois(rot)

        rotation_best_score = -1
        rotation_best_text = ""
        rotation_best_alpha = -1

        for roi_name, roi_img in rois.items():
            text_a = _ocr_roi_text(roi_img, lang=lang, config=config_a)
            text_b = _ocr_roi_text(roi_img, lang=lang, config=config_b)

            score_a = _keyword_score(text_a)
            score_b = _keyword_score(text_b)
            hits_a = [
                k for k in HEADER_KEYWORDS
                if normalize_for_keywords(k) in normalize_for_keywords(text_a)
            ]
            hits_b = [
                k for k in HEADER_KEYWORDS
                if normalize_for_keywords(k) in normalize_for_keywords(text_b)
            ]

            if score_a >= score_b:
                roi_text = text_a
                roi_score = score_a
            else:
                roi_text = text_b
                roi_score = score_b

            alpha_count = sum(1 for ch in roi_text.upper() if ch.isalpha())
            if roi_score > rotation_best_score or (
                roi_score == rotation_best_score and alpha_count > rotation_best_alpha
            ):
                rotation_best_score = roi_score
                rotation_best_text = roi_text.upper()
                rotation_best_alpha = alpha_count

            if debug_enabled:
                tag = debug_tag or "table"
                base = f"{tag}_rot{rotation}_{roi_name}"
                cv2.imwrite(os.path.join(debug_dir, f"{base}.png"), roi_img)
                with open(os.path.join(debug_dir, f"{base}_A.txt"), "w", encoding="utf-8") as handle:
                    handle.write(text_a)
                with open(os.path.join(debug_dir, f"{base}_B.txt"), "w", encoding="utf-8") as handle:
                    handle.write(text_b)
                with open(os.path.join(debug_dir, f"{base}_scores.txt"), "w", encoding="utf-8") as handle:
                    norm_a = normalize_for_keywords(text_a)
                    norm_b = normalize_for_keywords(text_b)
                    handle.write(f"score_a={score_a}\\nscore_b={score_b}\\n")
                    handle.write(f"hits_a={hits_a}\\n")
                    handle.write(f"hits_b={hits_b}\\n")
                    handle.write(f"norm_text_a={norm_a[:200]}\\n")
                    handle.write(f"norm_text_b={norm_b[:200]}\\n")

                rot_entry = debug_summary["rotations"].setdefault(str(rotation), {})
                rot_entry[roi_name] = {
                    "score_a": score_a,
                    "score_b": score_b,
                    "best_score": roi_score,
                    "hits_a": hits_a,
                    "hits_b": hits_b,
                }

        if rotation_best_score > best_score or (
            rotation_best_score == best_score and rotation_best_alpha > best_alpha
        ):
            best_rotation = rotation
            best_score = rotation_best_score
            best_text = rotation_best_text
            best_alpha = rotation_best_alpha

    if best_score < 0:
        best_score = 0

    if debug_enabled:
        tag = debug_tag or "table"
        log.info(
            "[PII_OCR_DEBUG] rotation selected=%s score=%s tag=%s",
            best_rotation,
            best_score,
            tag,
        )
        debug_summary["selected_rotation"] = best_rotation
        debug_summary["selected_score"] = best_score
        if debug_dir:
            summary_path = os.path.join(debug_dir, f"{tag}_summary.json")
            try:
                import json

                with open(summary_path, "w", encoding="utf-8") as handle:
                    json.dump(debug_summary, handle, ensure_ascii=False, indent=2)
            except Exception:
                pass

    return best_rotation, best_score, best_text, debug_summary


def _assign_table_rotation(
    img: np.ndarray,
    image_path: str,
    boxes: list[dict],
    detector: str,
) -> list[dict]:
    debug_enabled = os.environ.get("PII_OCR_DEBUG", "0") == "1"
    debug_dir_root = os.environ.get("PII_OCR_DEBUG_DIR", "pii_ocr_debug")
    debug_report = []
    out: list[dict] = []

    for idx, bbox in enumerate(boxes, start=1):
        table_rotation = 0
        rotation_source = "none"
        rotation_score = 0
        debug_tag = f"{os.path.basename(image_path)}_table{idx:02d}"
        table_debug_dir = None

        if os.environ.get("PII_OCR_AUTOROTATE", "1").lower() in ("1", "true", "on", "yes"):
            try:
                crop = img[bbox["y1"]:bbox["y2"], bbox["x1"]:bbox["x2"]]
                if crop.size > 0:
                    lang = os.environ.get("PII_OCR_LANG", "ita")
                    config = os.environ.get("PII_OCR_CONFIG", "--oem 3 --psm 6")
                    if debug_enabled:
                        table_debug_dir = os.path.join(debug_dir_root, debug_tag)
                        os.makedirs(table_debug_dir, exist_ok=True)
                        cv2.imwrite(os.path.join(table_debug_dir, "table_crop.png"), crop)
                    rot_hdr, score, _, _ = detect_table_rotation_by_headers(
                        crop,
                        lang=lang,
                        config=config,
                        debug_tag=debug_tag,
                        debug_dir=table_debug_dir,
                    )
                    if score >= 1:
                        table_rotation = rot_hdr
                        rotation_source = "headers"
                        rotation_score = score
                    else:
                        pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                        table_rotation = _detect_rotation_osd(pil_crop)
                        rotation_source = "osd" if table_rotation else "none"
                        rotation_score = 0
            except Exception as exc:
                log.debug("Rotation detect failed for table crop: %s", exc)

        entry = {
            **bbox,
            "rotation": table_rotation,
            "rotation_source": rotation_source,
            "rotation_score": rotation_score,
            "detector": detector,
        }
        if bbox.get("detector_score") is not None:
            entry["detector_score"] = bbox.get("detector_score")
        if bbox.get("detector_class") is not None:
            entry["detector_class"] = bbox.get("detector_class")

        out.append(entry)

        if debug_enabled:
            debug_report.append({
                "table_index": idx,
                "bbox": bbox,
                "rotation": table_rotation,
                "rotation_source": rotation_source,
                "rotation_score": rotation_score,
                "detector": detector,
                "detector_score": bbox.get("detector_score"),
                "detector_class": bbox.get("detector_class"),
                "debug_dir": os.path.join(debug_dir_root, debug_tag),
            })

    if debug_enabled and debug_report:
        os.makedirs(debug_dir_root, exist_ok=True)
        report_path = os.path.join(debug_dir_root, f"{os.path.basename(image_path)}_report.json")
        try:
            import json

            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(debug_report, handle, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return out


def detect_tables_morph(image_path: str) -> list[dict]:
    img = cv2.imread(image_path)
    if img is None:
        return []

    orig_h, orig_w = img.shape[:2]

    rotation = 0
    if os.environ.get("PII_OCR_AUTOROTATE", "1").lower() in ("1", "true", "on", "yes"):
        pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        rotation = _detect_rotation_osd(pil_img)

    work = _rotate_image(img, rotation)
    h, w = work.shape[:2]

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))

    remove_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel, iterations=2)
    remove_vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel, iterations=2)

    table_mask = cv2.bitwise_or(remove_horizontal, remove_vertical)

    cnts = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]

    min_w = int(w * 0.2)
    min_h = int(h * 0.2)
    min_area = int(w * h * 0.05)

    boxes: list[dict] = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw < min_w or ch < min_h:
            continue
        if cw * ch < min_area:
            continue

        bbox = {"x1": x, "y1": y, "x2": x + cw, "y2": y + ch}
        if rotation:
            bbox = _map_bbox_to_original(bbox, rotation, orig_w, orig_h)
        boxes.append(bbox)

    return _assign_table_rotation(img, image_path, boxes, detector="morph")


def detect_tables_yolo(image_path: str) -> list[dict]:
    img = cv2.imread(image_path)
    if img is None:
        return []

    orig_h, orig_w = img.shape[:2]
    rotation = 0
    if os.environ.get("PII_OCR_AUTOROTATE", "1").lower() in ("1", "true", "on", "yes"):
        pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        rotation = _detect_rotation_osd(pil_img)

    work = _rotate_image(img, rotation)
    h, w = work.shape[:2]

    model = _load_yolo_table_model()
    if model is None:
        return []

    try:
        conf = float(os.environ.get("PII_TABLE_YOLO_CONF", "0.25"))
    except ValueError:
        conf = 0.25
    try:
        iou = float(os.environ.get("PII_TABLE_YOLO_IOU", "0.45"))
    except ValueError:
        iou = 0.45

    min_w = int(w * 0.2)
    min_h = int(h * 0.2)
    min_area = int(w * h * 0.05)

    rgb = cv2.cvtColor(work, cv2.COLOR_BGR2RGB)
    try:
        results = model.predict(rgb, conf=conf, iou=iou, verbose=False)
    except Exception as exc:
        log.warning("YOLO table detect failed: %s", exc)
        return []

    boxes: list[dict] = []
    for result in results:
        if result.boxes is None:
            continue
        for b in result.boxes:
            try:
                xyxy = b.xyxy[0].tolist()
                x1, y1, x2, y2 = [int(v) for v in xyxy]
                conf_val = float(b.conf.item()) if hasattr(b, "conf") else None
                cls_id = int(b.cls.item()) if hasattr(b, "cls") else None
            except Exception:
                continue

            if (x2 - x1) < min_w or (y2 - y1) < min_h:
                continue
            if (x2 - x1) * (y2 - y1) < min_area:
                continue

            bbox = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
            if rotation:
                bbox = _map_bbox_to_original(bbox, rotation, orig_w, orig_h)

            class_name = None
            try:
                if hasattr(model, "names") and cls_id is not None:
                    class_name = model.names.get(cls_id)
            except Exception:
                class_name = None

            boxes.append({
                **bbox,
                "detector_score": conf_val,
                "detector_class": class_name,
            })

    return _assign_table_rotation(img, image_path, boxes, detector="yolo")


def detect_tables(image_path: str) -> list[dict]:
    mode = os.environ.get("PII_TABLE_DETECTOR", "morph").lower().strip()
    if mode in ("yolo", "yolov8", "yolo8"):
        boxes = detect_tables_yolo(image_path)
        if boxes or mode == "yolo":
            return boxes
        return detect_tables_morph(image_path)
    if mode in ("morph", "opencv"):
        return detect_tables_morph(image_path)

    # auto: try yolo then fallback
    boxes = detect_tables_yolo(image_path)
    if boxes:
        return boxes
    return detect_tables_morph(image_path)


def ocr_table_region(image_path: str, table: dict, lang: str, config: str) -> dict:
    img = cv2.imread(image_path)
    if img is None:
        return {"tokens": [], "lines": [], "width": 0, "height": 0, "origin_x": 0, "origin_y": 0}

    x1 = int(table.get("x1", 0))
    y1 = int(table.get("y1", 0))
    x2 = int(table.get("x2", 0))
    y2 = int(table.get("y2", 0))
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return {"tokens": [], "lines": [], "width": 0, "height": 0, "origin_x": 0, "origin_y": 0}

    rotation = int(table.get("rotation", 0) or 0)
    crop_h, crop_w = crop.shape[:2]
    rot_crop = _rotate_image(crop, rotation)

    data = pytesseract.image_to_data(
        rot_crop,
        output_type=Output.DICT,
        lang=lang,
        config=config,
    )

    tokens: list[dict] = []
    line_map: dict = {}
    text_parts: list[str] = []
    offset = 0
    prev_line = None

    count = len(data.get("text", []))
    for i in range(count):
        word = (data["text"][i] or "").strip()
        if not word:
            continue

        line_id = (
            data.get("block_num", [0])[i],
            data.get("par_num", [0])[i],
            data.get("line_num", [0])[i],
        )

        if prev_line is None:
            pass
        elif line_id != prev_line:
            text_parts.append("\n")
            offset += 1
        else:
            text_parts.append(" ")
            offset += 1

        start = offset
        text_parts.append(word)
        offset += len(word)

        left = int(data.get("left", [0])[i])
        top = int(data.get("top", [0])[i])
        w = int(data.get("width", [0])[i])
        h = int(data.get("height", [0])[i])
        bbox_rot = {"x1": left, "y1": top, "x2": left + w, "y2": top + h}

        # map bbox from rotated crop to original crop
        if rotation:
            bbox_rot = _map_bbox_to_original(bbox_rot, rotation, crop_w, crop_h)

        tokens.append({
            "text": word,
            "start": start,
            "end": offset,
            "line_id": line_id,
            "bbox": bbox_rot,
        })

        entry = line_map.get(line_id)
        if not entry:
            line_map[line_id] = {
                "text": word,
                "bbox": dict(bbox_rot),
                "line_id": line_id,
            }
        else:
            entry["text"] += " " + word
            entry["bbox"]["x1"] = min(entry["bbox"]["x1"], bbox_rot["x1"])
            entry["bbox"]["y1"] = min(entry["bbox"]["y1"], bbox_rot["y1"])
            entry["bbox"]["x2"] = max(entry["bbox"]["x2"], bbox_rot["x2"])
            entry["bbox"]["y2"] = max(entry["bbox"]["y2"], bbox_rot["y2"])

        prev_line = line_id

    return {
        "tokens": tokens,
        "lines": list(line_map.values()),
        "width": crop_w,
        "height": crop_h,
        "origin_x": x1,
        "origin_y": y1,
        "crop_width": crop_w,
        "crop_height": crop_h,
        "rotation": rotation,
    }


def get_table_column_boxes_for_page(image_path: str, lang: str, config: str) -> list[dict]:
    boxes: list[dict] = []
    tables = detect_tables(image_path)
    img = cv2.imread(image_path)
    if img is None:
        return boxes

    for tb in tables:
        x1 = int(tb.get("x1", 0))
        y1 = int(tb.get("y1", 0))
        x2 = int(tb.get("x2", 0))
        y2 = int(tb.get("y2", 0))
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        ocr = ocr_table_region(image_path, tb, lang=lang, config=config)
        lines = ocr.get("lines", [])
        tokens = ocr.get("tokens", [])
        crop_w = int(ocr.get("width", 0) or 0)
        crop_h = int(ocr.get("height", 0) or 0)
        if crop_w <= 0 or crop_h <= 0:
            continue

        rotation = int(tb.get("rotation", 0) or 0)
        rot_crop = _rotate_image(crop, rotation)
        cols_rot = _detect_column_boxes_in_rotated_table(rot_crop)

        # Map OCR lines/tokens into rotated space for header detection on rotated tables
        if rotation in (90, 180, 270):
            rot_w = crop_h if rotation in (90, 270) else crop_w
            rot_h = crop_w if rotation in (90, 270) else crop_h

            lines_work = []
            for line in lines:
                lb = line.get("bbox") or {}
                rb = _map_bbox_to_rotated(lb, rotation, crop_w, crop_h)
                lines_work.append({
                    "text": line.get("text"),
                    "bbox": rb,
                })

            tokens_work = []
            for t in tokens:
                bb = t.get("bbox") or {}
                rb = _map_bbox_to_rotated(bb, rotation, crop_w, crop_h)
                tokens_work.append({
                    "text": t.get("text"),
                    "bbox": rb,
                    "line_id": t.get("line_id"),
                })
            work_w, work_h = rot_w, rot_h
        else:
            lines_work = lines
            tokens_work = tokens
            work_w, work_h = crop_w, crop_h

        for idx, cb in enumerate(cols_rot, start=1):
            bbox = dict(cb)
            if rotation:
                bbox = _map_bbox_to_original(bbox, rotation, crop_w, crop_h)

            sensitive, label, reason = _column_has_sensitive_data(
                cb["x1"] if rotation else bbox["x1"],
                cb["x2"] if rotation else bbox["x2"],
                lines_work,
                tokens_work,
                work_w,
                work_h,
            )
            if not sensitive:
                continue
            boxes.append({
                "x1": x1 + bbox["x1"],
                "y1": y1 + bbox["y1"],
                "x2": x1 + bbox["x2"],
                "y2": y1 + bbox["y2"],
                "label": label or f"TABLE_COLUMN_{idx}",
                "confidence": "high" if reason == "header" else "medium",
                "source": "pii_column",
                "reason": reason,
            })

    return boxes


def get_document_column_boxes_for_page(image_path: str, lang: str, config: str) -> list[dict]:
    boxes: list[dict] = []
    tables = detect_tables(image_path)
    debug_enabled = os.environ.get("PII_OCR_DEBUG", "0") == "1"
    debug_dir_root = os.environ.get("PII_OCR_DEBUG_DIR", "pii_ocr_debug")
    base_name = os.path.basename(image_path)

    for idx, tb in enumerate(tables, start=1):
        ocr = ocr_table_region(image_path, tb, lang=lang, config=config)
        lines = ocr.get("lines", [])
        tokens = ocr.get("tokens", [])
        crop_w = int(ocr.get("width", 0) or 0)
        crop_h = int(ocr.get("height", 0) or 0)
        origin_x = int(ocr.get("origin_x", 0) or 0)
        origin_y = int(ocr.get("origin_y", 0) or 0)
        if crop_w <= 0 or crop_h <= 0:
            continue

        col_boxes, debug = detect_document_and_signature_columns(
            lines,
            tokens,
            crop_w,
            crop_h,
            header_ratio=0.25,
            min_doc_score=2,
        )

        if debug_enabled:
            table_debug_dir = os.path.join(debug_dir_root, f"{base_name}_table{idx:02d}")
            os.makedirs(table_debug_dir, exist_ok=True)
            debug_path = os.path.join(table_debug_dir, "header_cells.json")
            try:
                import json

                with open(debug_path, "w", encoding="utf-8") as handle:
                    json.dump(debug, handle, ensure_ascii=False, indent=2)
            except Exception:
                pass

        table_bottom = crop_h
        for cb in col_boxes:
            x1 = origin_x + int(cb["x"] * crop_w)
            y1 = origin_y + int(cb["y"] * crop_h)
            x2 = origin_x + int((cb["x"] + cb["w"]) * crop_w)
            y2 = origin_y + int((cb["y"] + cb["h"]) * crop_h)
            y2 = min(origin_y + table_bottom, y2)
            boxes.append({
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "label": cb.get("label", "COLUMN:DOCUMENTO"),
                "confidence": cb.get("confidence", "high"),
                "source": cb.get("source"),
            })

    return boxes


def get_table_header_boxes_for_page(image_path: str, lang: str, config: str) -> list[dict]:
    boxes: list[dict] = []
    tables = detect_tables(image_path)
    for tb in tables:
        ocr = ocr_table_region(image_path, tb, lang=lang, config=config)
        lines = ocr.get("lines", [])
        crop_w = int(ocr.get("width", 0) or 0)
        crop_h = int(ocr.get("height", 0) or 0)
        origin_x = int(ocr.get("origin_x", 0) or 0)
        origin_y = int(ocr.get("origin_y", 0) or 0)
        if crop_w <= 0 or crop_h <= 0:
            continue
        headers = build_table_header_boxes(lines, crop_w, crop_h)
        for hb in headers:
            x1 = origin_x + int(hb["x"] * crop_w)
            y1 = origin_y + int(hb["y"] * crop_h)
            x2 = origin_x + int((hb["x"] + hb["w"]) * crop_w)
            y2 = origin_y + int((hb["y"] + hb["h"]) * crop_h)
            boxes.append({
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "label": hb.get("label"),
                "confidence": hb.get("confidence"),
            })
    return boxes
