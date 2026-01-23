from __future__ import annotations

import argparse
import os

from PIL import Image, ImageDraw

from pii_ocr.table_detect import (
    detect_tables,
    get_document_column_boxes_for_page,
    get_table_header_boxes_for_page,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug table/column detection")
    parser.add_argument("image", nargs="+", help="Image path(s) to analyze")
    parser.add_argument("--lang", default=os.environ.get("PII_OCR_LANG", "ita"), help="OCR language")
    parser.add_argument("--config", default=os.environ.get("PII_OCR_CONFIG", "--oem 3 --psm 6"), help="OCR config")
    parser.add_argument("--out", default="table_debug", help="Output folder for debug images")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)

    for path in args.image:
        print(f"\n== {path} ==")
        tables = detect_tables(path)
        print(f"Tabelle trovate: {len(tables)}")
        for idx, tb in enumerate(tables, start=1):
            print(f"  - table {idx}: bbox=({tb['x1']},{tb['y1']})-({tb['x2']},{tb['y2']}), rotation={tb.get('rotation')}, source={tb.get('rotation_source')}, score={tb.get('rotation_score')}")

        cols = get_document_column_boxes_for_page(path, lang=args.lang, config=args.config)
        headers = get_table_header_boxes_for_page(path, lang=args.lang, config=args.config)
        print(f"Colonne NUMERO DOCUMENTO: {len(cols)}")
        for c in cols:
            print(f"  - {c.get('label')} ({c['x1']},{c['y1']})-({c['x2']},{c['y2']}), rot={c.get('rotation')}")
        print(f"Header trovati: {len(headers)}")
        for h in headers:
            print(f"  - {h.get('label')} ({h['x1']},{h['y1']})-({h['x2']},{h['y2']})")

        try:
            img = Image.open(path).convert("RGB")
        except Exception:
            continue
        draw = ImageDraw.Draw(img)

        for tb in tables:
            draw.rectangle([tb["x1"], tb["y1"], tb["x2"], tb["y2"]], outline=(123, 44, 191), width=3)
        for h in headers:
            draw.rectangle([h["x1"], h["y1"], h["x2"], h["y2"]], outline=(123, 44, 191), width=2)
        for c in cols:
            draw.rectangle([c["x1"], c["y1"], c["x2"], c["y2"]], outline=(11, 125, 218), width=3)

        out_path = os.path.join(args.out, os.path.basename(path))
        img.save(out_path)
        print(f"Debug image saved: {out_path}")


if __name__ == "__main__":
    main()

