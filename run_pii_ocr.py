#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import logging
import os
import uuid
from datetime import datetime

import fitz  # PyMuPDF
from PIL import Image

from pii_ocr.pipeline import run_pii_pipeline

log = logging.getLogger(__name__)


def pdf_to_images(pdf_path: str, out_dir: str, dpi: int = 200) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)

    image_paths: list[str] = []
    for page_index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat)
        mode = "RGB"
        if pix.alpha:
            mode = "RGBA"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        if mode == "RGBA":
            img = img.convert("RGB")
        out_path = os.path.join(out_dir, f"page_{page_index}.png")
        img.save(out_path, "PNG")
        image_paths.append(out_path)

    doc.close()
    return image_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PII OCR pipeline")
    parser.add_argument("--pdf", nargs="*", help="Input PDF path(s)")
    parser.add_argument("--images", nargs="*", help="Input image paths")
    parser.add_argument("--out-dir", default="pii_out", help="Output directory")
    parser.add_argument("--job-id", default=None, help="Optional job id")
    parser.add_argument("--dpi", type=int, default=200, help="DPI for PDF conversion")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    if not args.pdf and not args.images:
        log.error("Provide --pdf or --images")
        return 2

    job_id = args.job_id or uuid.uuid4().hex[:12]
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    image_paths: list[str] = []
    if args.pdf:
        for pdf_path in args.pdf:
            pdf_base = os.path.splitext(os.path.basename(pdf_path))[0]
            pdf_out = os.path.join(out_dir, f"images_{pdf_base}_{job_id}")
            log.info("Converting PDF %s to images", pdf_path)
            image_paths.extend(pdf_to_images(pdf_path, pdf_out, dpi=args.dpi))

    if args.images:
        image_paths.extend(args.images)

    if not image_paths:
        log.error("No images to process")
        return 2

    log.info("Running PII OCR pipeline on %d images", len(image_paths))
    run_pii_pipeline(image_paths, out_dir, job_id)
    log.info("Done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

