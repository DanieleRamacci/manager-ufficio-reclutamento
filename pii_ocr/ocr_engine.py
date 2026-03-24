from __future__ import annotations

import logging
import os
from typing import List, Dict

from PIL import Image
import pytesseract
from pytesseract import Output

log = logging.getLogger(__name__)


def _rotate_image_for_ocr(img: Image.Image, rotation: int) -> Image.Image:
    if rotation == 0:
        return img
    return img.rotate(-rotation, expand=True)


def _map_bbox_to_original(
    bbox: dict,
    rotation: int,
    orig_w: int,
    orig_h: int,
    rot_w: int,
    rot_h: int,
) -> dict:
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


def extract_ocr_from_images(image_paths: list[str], lang: str | None = None, config: str | None = None) -> list[dict]:
    results: list[dict] = []
    for page_index, image_path in enumerate(image_paths):
        try:
            img = Image.open(image_path)
        except Exception as exc:
            log.warning("OCR image open failed: %s (%s)", image_path, exc)
            results.append({
                "page_index": page_index,
                "image_path": image_path,
                "text_raw": "",
                "tokens": [],
                "width": None,
                "height": None,
            })
            continue

        width, height = img.size

        rotation = 0
        auto_rotate = os.environ.get("PII_OCR_AUTOROTATE", "1").lower() in ("1", "true", "on", "yes")
        if auto_rotate:
            try:
                osd = pytesseract.image_to_osd(img)
                for line in osd.splitlines():
                    if line.lower().startswith("rotate:"):
                        rotation = int(line.split(":")[1].strip())
                        break
            except Exception as exc:
                log.debug("OSD failed: %s", exc)

        ocr_img = _rotate_image_for_ocr(img, rotation)
        rot_w, rot_h = ocr_img.size

        lang = lang or os.environ.get("PII_OCR_LANG", "ita")
        config = config or os.environ.get("PII_OCR_CONFIG", "--oem 1 --psm 6")
        try:
            data = pytesseract.image_to_data(
                ocr_img,
                output_type=Output.DICT,
                lang=lang,
                config=config,
            )
        except Exception as exc:
            log.warning("OCR failed: %s (%s)", image_path, exc)
            data = None

        tokens: list[dict] = []
        text_parts: list[str] = []
        offset = 0
        prev_line = None

        if data:
            count = len(data.get("text", []))
            for i in range(count):
                word = (data["text"][i] or "").strip()
                if not word:
                    continue

                line_id = (data.get("block_num", [0])[i],
                           data.get("par_num", [0])[i],
                           data.get("line_num", [0])[i])

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

                bbox = {
                    "x1": left,
                    "y1": top,
                    "x2": left + w,
                    "y2": top + h,
                }
                if rotation:
                    bbox = _map_bbox_to_original(bbox, rotation, width, height, rot_w, rot_h)

                tokens.append({
                    "text": word,
                    "start": start,
                    "end": offset,
                    "line_id": line_id,
                    "bbox": bbox,
                })

                prev_line = line_id

        text_raw = "".join(text_parts)
        lines: list[dict] = []
        if tokens:
            line_map: dict = {}
            for token in tokens:
                lid = token.get("line_id")
                entry = line_map.get(lid)
                if not entry:
                    line_map[lid] = {
                        "text": token["text"],
                        "bbox": dict(token["bbox"]),
                        "line_id": lid,
                    }
                else:
                    entry["text"] += " " + token["text"]
                    entry["bbox"]["x1"] = min(entry["bbox"]["x1"], token["bbox"]["x1"])
                    entry["bbox"]["y1"] = min(entry["bbox"]["y1"], token["bbox"]["y1"])
                    entry["bbox"]["x2"] = max(entry["bbox"]["x2"], token["bbox"]["x2"])
                    entry["bbox"]["y2"] = max(entry["bbox"]["y2"], token["bbox"]["y2"])
            lines = list(line_map.values())

        results.append({
            "page_index": page_index,
            "image_path": image_path,
            "text_raw": text_raw,
            "tokens": tokens,
            "width": width,
            "height": height,
            "lines": lines,
            "rotation": rotation,
        })

    return results


def extract_text_from_images(image_paths: list[str]) -> list[dict]:
    results: list[dict] = []
    for page in extract_ocr_from_images(image_paths):
        results.append({
            "page_index": page.get("page_index"),
            "image_path": page.get("image_path"),
            "text_raw": page.get("text_raw", ""),
        })
    return results
