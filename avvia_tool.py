#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import threading
import subprocess
from datetime import datetime
from flask import Flask
from flask_session import Session
import uuid
import queue

import fitz  # PyMuPDF
from PIL import Image, ImageDraw
import img2pdf

import cv2
import numpy as np
from huggingface_hub import login, hf_hub_download
from ultralytics import YOLO
import io
import shutil
import zipfile


from flask import (
    Flask, jsonify, send_from_directory, abort, request,
    redirect, url_for, session, send_file
)
from dotenv import load_dotenv

# auth: blueprint + decorator
from auth import auth_bp, login_required

# (opzionale) servizi RDP se li usi
import fetch_bandi_rdp as svc





# ========= Config =========
load_dotenv()
PORT = int(os.environ.get("PORT", "8081"))
DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = "index.html"

# output scraper
URP_JSON = "bandi-completi-urp.json"
SOL_JSON = "bandi-concorsi-pubblici-sol.json"
MOB_JSON = "bandi-mobilita.json"

# script scraper
SCR_URP = "scraper-urp.py"
SCR_SOL = "scraper-sol-tutti-bandi.py"
SCR_MOB = "scraper-mobilita.py"

# sync di esecuzione scraper
run_lock = threading.Lock()
bg_threads = []

# ========= Async job queue for firma/PII analysis =========
jobs_lock = threading.Lock()
jobs: dict[str, dict] = {}
job_queue: "queue.Queue[str]" = queue.Queue()
DOC_TTL_SECONDS = int(os.environ.get("FIRME_DOC_TTL_SECONDS", "86400"))


def _current_user_id() -> str | None:
    return session.get("user") or session.get("user_email")


def _doc_owner_path(doc_id: str) -> str:
    return os.path.join(DOCS_FIRME_ROOT, doc_id, "owner.txt")


def _write_doc_owner(doc_id: str, user_id: str, job_id: str) -> None:
    try:
        with open(_doc_owner_path(doc_id), "w", encoding="utf-8") as handle:
            handle.write(f"{user_id}\n{job_id}\n")
    except Exception as exc:
        print(f"[FIRME][WARN] Impossibile scrivere owner per doc_id={doc_id}: {exc}", flush=True)


def _read_doc_owner(doc_id: str) -> str | None:
    try:
        with open(_doc_owner_path(doc_id), "r", encoding="utf-8") as handle:
            return handle.readline().strip() or None
    except Exception:
        return None


def _is_doc_owned_by_user(doc_id: str, user_id: str | None) -> bool:
    if not user_id:
        return False
    return _read_doc_owner(doc_id) == user_id


def _update_job(job_id: str, **kwargs) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job.update(kwargs)


def _set_job_progress(job_id: str, done: int, total: int) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job["progress"] = {"done": done, "total": total}

# cache minima per /api/bandi-rdp
CACHE_TTL = int(os.environ.get("CACHE_TTL", "60"))
_cache = {"ts": 0, "key": None, "data": []}


# ========= App =========
app = Flask(__name__, static_folder=None, static_url_path=None)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')

# Sessione server-side su filesystem (consigliato per evitare cookie giganti)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(__file__), 'instance', 'flask_session')
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # True se usi HTTPS
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

Session(app)

# registra le route di autenticazione (/login, /oidc-callback, /logout, /api/userinfo)
app.register_blueprint(auth_bp)



APP_VERSION = "2025-12-01-urpmgr-borse-v2"
print(f"[Oscuramento] Avvio versione: {APP_VERSION}")

# ========= Utils =========
# ========= Config firme / modello YOLO =========

# cartella dove salvare PDF e immagini per la redazione firme
DOCS_FIRME_ROOT = os.path.join(DIR, "docs_firme")
os.makedirs(DOCS_FIRME_ROOT, exist_ok=True)

# Token Hugging Face (meglio in .env: HUGGINGFACE_TOKEN=hf_...)
HUGGINGFACE_TOKEN = os.environ.get("HUGGINGFACE_TOKEN")

if not HUGGINGFACE_TOKEN:
    raise RuntimeError("Imposta HUGGINGFACE_TOKEN nel file .env con il tuo token Hugging Face")

try:
    import torch
except Exception as exc:
    print(f"[FIRME][ERR] PyTorch non importabile: {exc}", flush=True)
    raise SystemExit(1)

print(f"[FIRME] PyTorch versione: {torch.__version__}", flush=True)

def _parse_torch_version(ver: str) -> tuple[int, int, int]:
    parts = (ver.split("+")[0]).split(".")
    nums = []
    for p in parts[:3]:
        try:
            nums.append(int("".join(ch for ch in p if ch.isdigit())))
        except Exception:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]

major, minor, _ = _parse_torch_version(torch.__version__)
if (major, minor) >= (2, 6):
    print(
        "[FIRME][WARN] PyTorch >= 2.6 può bloccare il load dei checkpoint YOLO (weights_only=True). "
        "Usa torch==2.5.1 oppure abilita PII_TORCH_UNSAFE_LOAD=1 solo con checkpoint trusted.",
        flush=True,
    )

print("[FIRME] Login a Hugging Face e caricamento modello YOLO...", flush=True)
login(HUGGINGFACE_TOKEN)

MODEL_FIRME_REPO = "tech4humans/yolov8s-signature-detector"
MODEL_FIRME_FILENAME = "yolov8s.pt"

model_firme_path = hf_hub_download(
    repo_id=MODEL_FIRME_REPO,
    filename=MODEL_FIRME_FILENAME
)

# Compat shim for older ultralytics layouts: expose conv/block/head submodules.
# Some checkpoints reference ultralytics.nn.modules.conv/* which may not exist in older versions.
try:
    import sys
    import types
    import ultralytics.nn.modules as ul_modules

    for sub in ("conv", "block", "head"):
        mod_name = f"ultralytics.nn.modules.{sub}"
        if mod_name not in sys.modules:
            alias = types.ModuleType(mod_name)
            alias.__dict__.update(ul_modules.__dict__)
            sys.modules[mod_name] = alias
except Exception as exc:
    print(f"[FIRME][WARN] Ultralytics module shim failed: {exc}", flush=True)

if os.environ.get("PII_TORCH_UNSAFE_LOAD", "0").lower() in ("1", "true", "on", "yes"):
    # PyTorch 2.6+ safe globals: allow ultralytics model classes for weights loading
    # NOTE: Only safe to allowlist if the checkpoint is trusted.
    try:
        import importlib
        from ultralytics.nn.tasks import DetectionModel

        safe = [DetectionModel]
        applied = False

        # Common torch.nn modules used in YOLO models
        try:
            import torch.nn as nn

            for obj in vars(nn).values():
                if isinstance(obj, type):
                    safe.append(obj)
        except Exception:
            pass

        # Ensure Sequential is allowlisted (explicitly required by torch error)
        try:
            from torch.nn.modules.container import Sequential

            safe.append(Sequential)
        except Exception:
            pass

        # Ultralytics modules (conv/block/head) used in checkpoints
        for mod_name in (
            "ultralytics.nn.modules",
            "ultralytics.nn.modules.conv",
            "ultralytics.nn.modules.block",
            "ultralytics.nn.modules.head",
        ):
            try:
                mod = importlib.import_module(mod_name)
                for obj in vars(mod).values():
                    if isinstance(obj, type):
                        safe.append(obj)
            except Exception:
                continue

        if hasattr(torch.serialization, "add_safe_globals"):
            torch.serialization.add_safe_globals(safe)
            applied = True
        if applied:
            print("[FIRME][WARN] PyTorch unsafe allowlist attiva (solo checkpoint trusted).", flush=True)
        else:
            print("[FIRME][WARN] PyTorch safe-globals allowlist non disponibile.", flush=True)
    except Exception as exc:
        print(f"[FIRME][WARN] Safe-globals setup failed: {exc}", flush=True)

yolo_firme = YOLO(model_firme_path)
print("[FIRME] Modello YOLO firme caricato.", flush=True)


def pdf_to_pil_images(pdf_path: str, dpi: int = 200) -> list[Image.Image]:
    """
    Converte un PDF in una lista di immagini PIL usando PyMuPDF (fitz),
    senza dipendenze esterne tipo poppler.
    """
    doc = fitz.open(pdf_path)
    images = []
    zoom = dpi / 72  # 72 dpi è la base di fitz
    mat = fitz.Matrix(zoom, zoom)

    for page in doc:
        pix = page.get_pixmap(matrix=mat)
        mode = "RGB"
        if pix.alpha:
            mode = "RGBA"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        if mode == "RGBA":
            img = img.convert("RGB")
        images.append(img)

    doc.close()
    return images


def _analyze_documents(
    documents_meta: list[dict],
    pii_enabled: bool,
    pii_debug: bool,
) -> list[dict]:
    pii_available = False
    if pii_enabled:
        try:
            from pii_ocr.ocr_engine import extract_ocr_from_images
            from pii_ocr.extractors import extract_pii
            from pii_ocr.boxes import build_pii_boxes
            pii_available = True
        except Exception as e:
            print(f"[PII][WARN] OCR non disponibile: {e}", flush=True)
            pii_enabled = False

    documents = []
    for doc_entry in documents_meta:
        doc_id = doc_entry["doc_id"]
        pdf_path = doc_entry["pdf_path"]
        filename = doc_entry["filename"]
        doc_dir = doc_entry["doc_dir"]

        try:
            pages = pdf_to_pil_images(pdf_path, dpi=200)
        except Exception as e:
            print(f"[FIRME][ERR] PDF->immagini (doc_id={doc_id}): {e}", flush=True)
            raise

        pages_info = []
        for i, img in enumerate(pages):
            image_filename = f"page_{i}.png"
            image_path = os.path.join(doc_dir, image_filename)
            img.save(image_path, "PNG")

            width, height = img.size

            auto_boxes = detect_signatures(image_path)
            norm_boxes = [{
                "x": float(b["x"]),
                "y": float(b["y"]),
                "w": float(b["w"]),
                "h": float(b["h"]),
                "score": float(b.get("score", 1.0))
            } for b in auto_boxes]

            pii_boxes = []
            pii_reject_boxes = []
            table_boxes = []
            if pii_enabled and pii_available:
                try:
                    from pii_ocr.boxes import build_column_value_boxes
                    from pii_ocr.table_detect import (
                        detect_tables,
                        get_table_column_boxes_for_page,
                        get_document_column_boxes_for_page,
                        get_table_header_boxes_for_page,
                    )
                    from pii_ocr.validators import validate_doc_number
                    ocr_pages = extract_ocr_from_images([image_path])
                    if ocr_pages:
                        ocr_page = ocr_pages[0]
                        text_raw = ocr_page.get("text_raw", "")
                        tokens = ocr_page.get("tokens", [])
                        lines = ocr_page.get("lines", [])
                        ocr_w = ocr_page.get("width") or width
                        ocr_h = ocr_page.get("height") or height
                        pii = extract_pii(text_raw.upper())
                        pii_boxes = build_pii_boxes(pii, tokens, ocr_w, ocr_h)

                        table_raw = detect_tables(image_path)
                        table_boxes = [{
                            "x": tb["x1"] / ocr_w,
                            "y": tb["y1"] / ocr_h,
                            "w": (tb["x2"] - tb["x1"]) / ocr_w,
                            "h": (tb["y2"] - tb["y1"]) / ocr_h,
                            "label": "TABLE",
                            "confidence": "high",
                            "source": "table",
                        } for tb in table_raw]

                        lang = os.environ.get("PII_OCR_LANG", "ita")
                        config = os.environ.get("PII_OCR_CONFIG", "--oem 3 --psm 6")

                        table_header_boxes = []
                        header_page = get_table_header_boxes_for_page(image_path, lang=lang, config=config)
                        for hb in header_page:
                            table_header_boxes.append({
                                "x": hb["x1"] / ocr_w,
                                "y": hb["y1"] / ocr_h,
                                "w": (hb["x2"] - hb["x1"]) / ocr_w,
                                "h": (hb["y2"] - hb["y1"]) / ocr_h,
                                "label": hb.get("label"),
                                "confidence": hb.get("confidence"),
                                "source": "table_header",
                                "kind": "header",
                            })

                        table_column_boxes = []
                        table_cols_page = get_table_column_boxes_for_page(image_path, lang=lang, config=config)
                        for cb in table_cols_page:
                            table_column_boxes.append({
                                "x": cb["x1"] / ocr_w,
                                "y": cb["y1"] / ocr_h,
                                "w": (cb["x2"] - cb["x1"]) / ocr_w,
                                "h": (cb["y2"] - cb["y1"]) / ocr_h,
                                "label": cb.get("label"),
                                "confidence": cb.get("confidence"),
                                "source": cb.get("source", "pii_column"),
                                "kind": "table_column",
                            })

                        column_boxes = []
                        col_page = get_document_column_boxes_for_page(image_path, lang=lang, config=config)
                        for cb in col_page:
                            column_boxes.append({
                                "x": cb["x1"] / ocr_w,
                                "y": cb["y1"] / ocr_h,
                                "w": (cb["x2"] - cb["x1"]) / ocr_w,
                                "h": (cb["y2"] - cb["y1"]) / ocr_h,
                                "label": cb.get("label"),
                                "confidence": cb.get("confidence"),
                                "source": cb.get("source", "pii"),
                                "kind": "column",
                            })

                        column_value_boxes = build_column_value_boxes(column_boxes, tokens, ocr_w, ocr_h)

                        pii_boxes.extend(table_header_boxes)
                        pii_boxes.extend(table_column_boxes)
                        pii_boxes.extend(column_boxes)
                        pii_boxes.extend(column_value_boxes)

                        pii_reject_boxes = []
                        if pii_debug and column_boxes:
                            for col in column_boxes:
                                col_x1 = int(col["x"] * ocr_w)
                                col_x2 = int((col["x"] + col["w"]) * ocr_w)
                                col_y1 = int(col["y"] * ocr_h)
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
                                    raw_token = (t.get("text") or "").upper()
                                    cleaned = "".join(ch for ch in raw_token if ch.isalnum())
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
                                    if is_valid:
                                        continue

                                    pii_reject_boxes.append({
                                        "x": tx1 / ocr_w,
                                        "y": ty1 / ocr_h,
                                        "w": (tx2 - tx1) / ocr_w,
                                        "h": (ty2 - ty1) / ocr_h,
                                        "label": "REJECTED_DOC",
                                        "confidence": "low",
                                        "source": "pii_reject",
                                    })
                except Exception as e:
                    print(f"[PII][WARN] OCR fallito per pagina {i}: {e}", flush=True)

            pages_info.append({
                "index": i,
                "image_url": f"/_static/docs_firme/{doc_id}/{image_filename}",
                "width": width,
                "height": height,
                "auto_boxes": norm_boxes,
                "pii_boxes": pii_boxes,
                "pii_reject_boxes": pii_reject_boxes if pii_debug else [],
                "table_boxes": table_boxes if pii_enabled and pii_available else []
            })

        documents.append({
            "doc_id": doc_id,
            "filename": filename,
            "pages": pages_info
        })

    return documents


def _worker_loop():
    while True:
        job_id = job_queue.get()
        if not job_id:
            continue
        with jobs_lock:
            job = jobs.get(job_id)
        if not job:
            continue
        _update_job(job_id, status="running")
        try:
            total_pages = 0
            done_pages = 0
            for doc in job["documents_meta"]:
                pages = pdf_to_pil_images(doc["pdf_path"], dpi=200)
                total_pages += len(pages)
            _set_job_progress(job_id, done_pages, total_pages)

            documents = []
            for doc in job["documents_meta"]:
                doc_id = doc["doc_id"]
                pdf_path = doc["pdf_path"]
                filename = doc["filename"]
                doc_dir = doc["doc_dir"]

                pages = pdf_to_pil_images(pdf_path, dpi=200)
                pages_info = []
                for i, img in enumerate(pages):
                    image_filename = f"page_{i}.png"
                    image_path = os.path.join(doc_dir, image_filename)
                    img.save(image_path, "PNG")

                    width, height = img.size
                    auto_boxes = detect_signatures(image_path)
                    norm_boxes = [{
                        "x": float(b["x"]),
                        "y": float(b["y"]),
                        "w": float(b["w"]),
                        "h": float(b["h"]),
                        "score": float(b.get("score", 1.0))
                    } for b in auto_boxes]

                    pii_boxes = []
                    pii_reject_boxes = []
                    table_boxes = []
                    if job["pii_enabled"]:
                        try:
                            from pii_ocr.ocr_engine import extract_ocr_from_images
                            from pii_ocr.extractors import extract_pii
                            from pii_ocr.boxes import build_pii_boxes, build_column_value_boxes
                            from pii_ocr.table_detect import (
                                detect_tables,
                                get_table_column_boxes_for_page,
                                get_document_column_boxes_for_page,
                                get_table_header_boxes_for_page,
                            )
                            from pii_ocr.validators import validate_doc_number
                            ocr_pages = extract_ocr_from_images([image_path])
                            if ocr_pages:
                                ocr_page = ocr_pages[0]
                                text_raw = ocr_page.get("text_raw", "")
                                tokens = ocr_page.get("tokens", [])
                                ocr_w = ocr_page.get("width") or width
                                ocr_h = ocr_page.get("height") or height
                                pii = extract_pii(text_raw.upper())
                                pii_boxes = build_pii_boxes(pii, tokens, ocr_w, ocr_h)

                                table_raw = detect_tables(image_path)
                                table_boxes = [{
                                    "x": tb["x1"] / ocr_w,
                                    "y": tb["y1"] / ocr_h,
                                    "w": (tb["x2"] - tb["x1"]) / ocr_w,
                                    "h": (tb["y2"] - tb["y1"]) / ocr_h,
                                    "label": "TABLE",
                                    "confidence": "high",
                                    "source": "table",
                                } for tb in table_raw]

                                lang = os.environ.get("PII_OCR_LANG", "ita")
                                config = os.environ.get("PII_OCR_CONFIG", "--oem 3 --psm 6")

                                table_header_boxes = []
                                header_page = get_table_header_boxes_for_page(image_path, lang=lang, config=config)
                                for hb in header_page:
                                    table_header_boxes.append({
                                        "x": hb["x1"] / ocr_w,
                                        "y": hb["y1"] / ocr_h,
                                        "w": (hb["x2"] - hb["x1"]) / ocr_w,
                                        "h": (hb["y2"] - hb["y1"]) / ocr_h,
                                        "label": hb.get("label"),
                                        "confidence": hb.get("confidence"),
                                        "source": "table_header",
                                        "kind": "header",
                                    })

                                table_column_boxes = []
                                table_cols_page = get_table_column_boxes_for_page(image_path, lang=lang, config=config)
                                for cb in table_cols_page:
                                    table_column_boxes.append({
                                        "x": cb["x1"] / ocr_w,
                                        "y": cb["y1"] / ocr_h,
                                        "w": (cb["x2"] - cb["x1"]) / ocr_w,
                                        "h": (cb["y2"] - cb["y1"]) / ocr_h,
                                        "label": cb.get("label"),
                                        "confidence": cb.get("confidence"),
                                        "source": cb.get("source", "pii_column"),
                                        "kind": "table_column",
                                    })

                                column_boxes = []
                                col_page = get_document_column_boxes_for_page(image_path, lang=lang, config=config)
                                for cb in col_page:
                                    column_boxes.append({
                                        "x": cb["x1"] / ocr_w,
                                        "y": cb["y1"] / ocr_h,
                                        "w": (cb["x2"] - cb["x1"]) / ocr_w,
                                        "h": (cb["y2"] - cb["y1"]) / ocr_h,
                                        "label": cb.get("label"),
                                        "confidence": cb.get("confidence"),
                                        "source": cb.get("source", "pii"),
                                        "kind": "column",
                                    })

                                column_value_boxes = build_column_value_boxes(column_boxes, tokens, ocr_w, ocr_h)

                                pii_boxes.extend(table_header_boxes)
                                pii_boxes.extend(table_column_boxes)
                                pii_boxes.extend(column_boxes)
                                pii_boxes.extend(column_value_boxes)

                                pii_reject_boxes = []
                                if job["pii_debug"] and column_boxes:
                                    for col in column_boxes:
                                        col_x1 = int(col["x"] * ocr_w)
                                        col_x2 = int((col["x"] + col["w"]) * ocr_w)
                                        col_y1 = int(col["y"] * ocr_h)
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
                                            raw_token = (t.get("text") or "").upper()
                                            cleaned = "".join(ch for ch in raw_token if ch.isalnum())
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
                                            if is_valid:
                                                continue

                                            pii_reject_boxes.append({
                                                "x": tx1 / ocr_w,
                                                "y": ty1 / ocr_h,
                                                "w": (tx2 - tx1) / ocr_w,
                                                "h": (ty2 - ty1) / ocr_h,
                                                "label": "REJECTED_DOC",
                                                "confidence": "low",
                                                "source": "pii_reject",
                                            })
                        except Exception as e:
                            print(f"[PII][WARN] OCR fallito per pagina {i}: {e}", flush=True)

                    pages_info.append({
                        "index": i,
                        "image_url": f"/_static/docs_firme/{doc_id}/{image_filename}",
                        "width": width,
                        "height": height,
                        "auto_boxes": norm_boxes,
                        "pii_boxes": pii_boxes,
                        "pii_reject_boxes": pii_reject_boxes if job["pii_debug"] else [],
                        "table_boxes": table_boxes if job["pii_enabled"] else []
                    })

                    done_pages += 1
                    _set_job_progress(job_id, done_pages, total_pages)

                documents.append({
                    "doc_id": doc_id,
                    "filename": filename,
                    "pages": pages_info
                })

            _update_job(job_id, status="done", documents=documents)
        except Exception as exc:
            _update_job(job_id, status="error", error=str(exc))
        finally:
            job_queue.task_done()


_worker_thread = threading.Thread(target=_worker_loop, daemon=True)
_worker_thread.start()


def _cleanup_doc_dirs():
    while True:
        try:
            now = time.time()
            active_doc_ids = set()
            with jobs_lock:
                for job in jobs.values():
                    if job.get("status") in ("queued", "running"):
                        for doc in job.get("documents_meta", []):
                            active_doc_ids.add(doc.get("doc_id"))
            for doc_id in os.listdir(DOCS_FIRME_ROOT):
                doc_dir = os.path.join(DOCS_FIRME_ROOT, doc_id)
                if not os.path.isdir(doc_dir):
                    continue
                if doc_id in active_doc_ids:
                    continue
                owner_file = _doc_owner_path(doc_id)
                if not os.path.exists(owner_file):
                    continue
                age = now - os.path.getmtime(owner_file)
                if age > DOC_TTL_SECONDS:
                    shutil.rmtree(doc_dir, ignore_errors=True)
        except Exception as exc:
            print(f"[FIRME][WARN] Cleanup docs_firme failed: {exc}", flush=True)
        time.sleep(600)


_cleanup_thread = threading.Thread(target=_cleanup_doc_dirs, daemon=True)
_cleanup_thread.start()
def detect_signatures(image_path: str) -> list[dict]:
    """
    Usa il modello YOLO 'yolo_firme' per rilevare firme su una immagine.

    Restituisce box NORMALIZZATE:
    [
      {"x": x_norm, "y": y_norm, "w": w_norm, "h": h_norm, "score": conf},
      ...
    ]
    dove x,y sono top-left, w,h dimensioni, tutto in [0,1].
    """
    img = cv2.imread(image_path)
    if img is None:
        print(f"[FIRME][WARN] Impossibile leggere immagine: {image_path}", flush=True)
        return []

    h, w = img.shape[:2]

    results = yolo_firme.predict(source=img, save=False)[0]

    boxes_out: list[dict] = []
    for box in results.boxes:
        x1, y1, x2, y2 = map(float, box.xyxy[0])
        conf = float(box.conf[0])

        box_w = x2 - x1
        box_h = y2 - y1

        x_norm = x1 / w
        y_norm = y1 / h
        w_norm = box_w / w
        h_norm = box_h / h

        # clamp per sicurezza
        x_norm = max(0.0, min(1.0, x_norm))
        y_norm = max(0.0, min(1.0, y_norm))
        w_norm = max(0.0, min(1.0 - x_norm, w_norm))
        h_norm = max(0.0, min(1.0 - y_norm, h_norm))

        boxes_out.append({
            "x": x_norm,
            "y": y_norm,
            "w": w_norm,
            "h": h_norm,
            "score": conf
        })

    return boxes_out

# --- ACCESS CHECK UTILS (riuso leggero dello scraper) ---
import io
try:
    from pdfminer.high_level import extract_text as _pdf_extract_text
    PDFMINER_AVAILABLE = True
except Exception:
    PDFMINER_AVAILABLE = False

try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except Exception:
    PIKEPDF_AVAILABLE = False


def _pdf_has_text_bytes(pdf_bytes: bytes) -> bool:
    if not PDFMINER_AVAILABLE:
        return False
    try:
        txt = _pdf_extract_text(io.BytesIO(pdf_bytes)) or ""
        return len(txt.strip()) >= 200
    except Exception:
        return False

def _pdf_tag_info_bytes(pdf_bytes: bytes) -> dict:
    info = {"is_tagged": False, "has_struct_tree": False, "lang": None, "title": None}
    if not PIKEPDF_AVAILABLE:
        return info
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            root = pdf.root
            markinfo = root.get("/MarkInfo", None)
            if isinstance(markinfo, pikepdf.Dictionary):
                info["is_tagged"] = bool(markinfo.get("/Marked", False))
            info["has_struct_tree"] = "/StructTreeRoot" in root
            if "/Lang" in root:
                try:
                    info["lang"] = str(root["/Lang"])
                except Exception:
                    info["lang"] = None
            try:
                meta = pdf.open_metadata()
                t = (meta.get("dc:title") or meta.get("pdf:Title") or "").strip()
                info["title"] = t or None
            except Exception:
                pass
    except Exception:
        pass
    return info

def _level_and_score(has_text: bool, is_tagged: bool, has_struct: bool, lang: str|None) -> tuple[str, int]:
    # stessa semantica che usi lato UI
    if not has_text:
        return "non_accessibile", 0
    pts = 0
    if is_tagged:      pts += 40
    if has_struct:     pts += 40
    if lang:           pts += 20
    # accessibile se >=60 e ha_text
    if pts >= 60:
        return "accessibile", pts
    return "parziale", max(40, pts)  # parziale con almeno 40 se c'è testo

def evaluate_uploaded(bytes_data: bytes, filename: str) -> dict:
    lower = (filename or "").lower()
    is_pdf = lower.endswith(".pdf")
    out = {
        "filename": filename,
        "checked": False,
        "is_pdf": is_pdf,
        "has_text": False,
        "is_tagged": False,
        "has_struct_tree": False,
        "lang": None,
        "has_title": False,
        "accessible": False,
        "level": "non_accessibile",
        "score": 0,
        "note": ""
    }
    if not is_pdf:
        out["note"] = "Non PDF – non valutabile"
        return out

    out["checked"] = True
    has_text = _pdf_has_text_bytes(bytes_data)
    tag = _pdf_tag_info_bytes(bytes_data)
    out["has_text"] = has_text
    out["is_tagged"] = bool(tag.get("is_tagged"))
    out["has_struct_tree"] = bool(tag.get("has_struct_tree"))
    out["lang"] = tag.get("lang")
    out["has_title"] = bool(tag.get("title"))

    level, score = _level_and_score(out["has_text"], out["is_tagged"], out["has_struct_tree"], out["lang"])
    out["level"] = level
    out["score"] = score
    out["accessible"] = (level == "accessibile")
    if not out["has_text"]:
        out["note"] = "Sembra scansione (nessun testo estraibile)"
    elif level == "parziale":
        out["note"] = "Testo presente ma mancano tag/struttura/lingua"
    return out


def _ts(path: str) -> str | None:
    p = os.path.join(DIR, path)
    if not os.path.exists(p):
        return None
    return datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")


def _exists(path: str) -> bool:
    return os.path.exists(os.path.join(DIR, path))


def run_scraper(script_name: str, block: bool = True) -> None:
    """Esegue uno script Python. Se block=False, parte in background."""
    print(f"[INFO] Esecuzione script: {script_name}", flush=True)
    cmd = [sys.executable, os.path.join(DIR, script_name)]
    if block:
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"[SUCCESS] Completato: {script_name}", flush=True)
            if result.stdout:
                print(result.stdout, flush=True)
            if result.stderr:
                print(result.stderr, flush=True)
        except subprocess.CalledProcessError as e:
            print(f"[ERRORE] {script_name} fallito:\n{e.stderr}", flush=True)
            raise
    else:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def startup_sequence():
    """URP sincrono, poi SOL + Mobilità in background."""
    with run_lock:
        try:
            print("[BOOT] Avvio sequenza iniziale…", flush=True)
            run_scraper(SCR_URP, block=True)
            run_scraper(SCR_SOL, block=False)
            run_scraper(SCR_MOB, block=False)
            print("[BOOT] Sequenza avviata. Server pronto.", flush=True)
        except Exception as e:
            print(f"[BOOT] Errore sequenza iniziale: {e}", flush=True)


def monitor_file(filepath: str, label: str):
    """Logga quando il file compare (solo info)."""
    p = os.path.join(DIR, filepath)
    while not os.path.exists(p):
        time.sleep(2)
    print(f"✅ Dati {label} disponibili ({filepath}).", flush=True)


def kick_monitors():
    """Avvia monitor (opzionale)."""
    for fp, lb in [(SOL_JSON, "Selezioni Online"), (MOB_JSON, "Mobilità/Comandi")]:
        t = threading.Thread(target=monitor_file, args=(fp, lb), daemon=True)
        t.start()
        bg_threads.append(t)


# ========= Routes protette (HTML/JSON/static) =========
@app.route("/redazione-firme.html")
@login_required
def redazione_firme_html():
    return send_from_directory(DIR, "redazione-firme.html")

@app.route("/api/firme/analyze", methods=["POST"])
@login_required
def api_firme_analyze():
    """
    Accetta uno o più PDF (campo 'pdf') e restituisce:
    {
      "documents": [
        {
          "doc_id": "...",
          "filename": "nome.pdf",
          "pages": [
            {
              "index": 0,
              "image_url": "...",
              "width": ...,
              "height": ...,
              "auto_boxes": [ {x,y,w,h,score}, ... ]
            },
            ...
          ]
        },
        ...
      ]
    }
    """
    files = request.files.getlist("pdf")
    if not files:
        return jsonify({"error": "Nessun file PDF inviato"}), 400

    pii_flag = (request.form.get("pii", "1") or "").strip().lower()
    pii_debug_flag = (request.form.get("pii_debug", "0") or "").strip().lower()
    pii_debug = pii_debug_flag in ("1", "true", "on", "yes")
    pii_enabled = pii_flag in ("1", "true", "on", "yes")

    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "Utente non autenticato"}), 403

    job_id = str(uuid.uuid4())
    documents_meta = []

    for pdf_file in files:
        if not pdf_file.filename:
            continue
        doc_id = str(uuid.uuid4())
        doc_dir = os.path.join(DOCS_FIRME_ROOT, doc_id)
        os.makedirs(doc_dir, exist_ok=True)
        pdf_path = os.path.join(doc_dir, "original.pdf")
        pdf_file.save(pdf_path)
        _write_doc_owner(doc_id, user_id, job_id)
        documents_meta.append({
            "doc_id": doc_id,
            "filename": pdf_file.filename,
            "doc_dir": doc_dir,
            "pdf_path": pdf_path,
        })

    with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "user": user_id,
            "pii_enabled": pii_enabled,
            "pii_debug": pii_debug,
            "documents_meta": documents_meta,
            "documents": None,
            "progress": {"done": 0, "total": 0},
            "error": None,
            "created_at": time.time(),
        }

    job_queue.put(job_id)
    return jsonify({"job_id": job_id, "status": "queued"})


@app.get("/api/firme/status/<job_id>")
@login_required
def api_firme_status(job_id: str):
    user_id = _current_user_id()
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job non trovato"}), 404
    if job.get("user") != user_id:
        return jsonify({"error": "Accesso negato"}), 403
    return jsonify({
        "job_id": job_id,
        "status": job.get("status"),
        "progress": job.get("progress", {"done": 0, "total": 0}),
        "error": job.get("error"),
    })


@app.get("/api/firme/result/<job_id>")
@login_required
def api_firme_result(job_id: str):
    user_id = _current_user_id()
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job non trovato"}), 404
    if job.get("user") != user_id:
        return jsonify({"error": "Accesso negato"}), 403
    if job.get("status") != "done":
        return jsonify({"error": "Job non completato", "status": job.get("status")}), 400
    return jsonify({"documents": job.get("documents") or []})

#aggiunto log

@app.post("/api/firme/confirm")
@login_required
def api_firme_confirm():
    """
    Riceve:
    {
      "documents": [
        {
          "doc_id": "...",
          "filename": "nome.pdf",
          "pages": [
            {
              "page_index": 0,
              "boxes": [ {"x":..,"y":..,"w":..,"h":..}, ... ]
            },
            ...
          ]
        },
        ...
      ]
    }

    Per ogni documento:
      - legge le immagini page_X.png
      - applica i rettangoli neri (irreversibili)
      - crea un PDF oscurato in memoria
    Poi:
      - crea un unico ZIP in memoria con tutti i PDF oscurati
      - cancella TUTTE le cartelle docs_firme/<doc_id>
      - restituisce lo ZIP come download

    Nessun file PDF o immagine rimane sul server dopo la risposta.
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "JSON mancante in /api/firme/confirm"}), 400

        docs_data = data.get("documents", [])
        if not docs_data:
            return jsonify({"error": "Nessun documento da elaborare"}), 400

        print(f"[FIRME] Conferma redazione per {len(docs_data)} documenti", flush=True)
        user_id = _current_user_id()
        if not user_id:
            return jsonify({"error": "Utente non autenticato"}), 403

        doc_dirs = []  # cartelle da cancellare alla fine

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            for doc_entry in docs_data:
                doc_id = doc_entry.get("doc_id")
                pages_data = doc_entry.get("pages", [])
                filename = (doc_entry.get("filename") or f"documento_{doc_id}.pdf").strip()

                if not doc_id:
                    print("[FIRME][WARN] doc_id mancante in una voce di documents", flush=True)
                    continue
                if not _is_doc_owned_by_user(doc_id, user_id):
                    return jsonify({"error": "Accesso negato al documento"}), 403

                doc_dir = os.path.join(DOCS_FIRME_ROOT, doc_id)
                if not os.path.isdir(doc_dir):
                    print(f"[FIRME][WARN] Cartella documento non trovata: {doc_dir}", flush=True)
                    continue

                doc_dirs.append(doc_dir)

                redacted_image_paths = []

                for page_info in pages_data:
                    page_index = page_info.get("page_index")
                    boxes = page_info.get("boxes", [])

                    if page_index is None:
                        print(f"[FIRME][WARN] page_index mancante per doc_id={doc_id}", flush=True)
                        continue

                    image_path = os.path.join(doc_dir, f"page_{page_index}.png")
                    if not os.path.exists(image_path):
                        print(f"[FIRME][WARN] Immagine pagina non trovata: {image_path}", flush=True)
                        continue

                    img = Image.open(image_path)
                    width, height = img.size
                    draw = ImageDraw.Draw(img)

                    # Oscuriamo tutte le box (se presenti)
                    for b in boxes:
                        x_norm = float(b["x"])
                        y_norm = float(b["y"])
                        w_norm = float(b["w"])
                        h_norm = float(b["h"])

                        x1 = int(x_norm * width)
                        y1 = int(y_norm * height)
                        x2 = int((x_norm + w_norm) * width)
                        y2 = int((y_norm + h_norm) * height)

                        draw.rectangle([x1, y1, x2, y2], fill="black")

                    redacted_image_path = os.path.join(doc_dir, f"redacted_page_{page_index}.png")
                    img.save(redacted_image_path, "PNG")
                    redacted_image_paths.append(redacted_image_path)

                if not redacted_image_paths:
                    print(f"[FIRME][WARN] Nessuna pagina redatta per doc_id={doc_id}", flush=True)
                    continue

                # Ordina le pagine per index numerico
                redacted_image_paths.sort(
                    key=lambda p: int(os.path.basename(p).split("_")[-1].split(".")[0])
                )

                try:
                    pdf_buffer = io.BytesIO()
                    pdf_buffer.write(img2pdf.convert(redacted_image_paths))
                    pdf_buffer.seek(0)
                except Exception as e:
                    print(f"[FIRME][ERR] Errore in img2pdf.convert per doc_id={doc_id}: {e}", flush=True)
                    continue

                safe_name = os.path.basename(filename)
                if not safe_name.lower().endswith(".pdf"):
                    safe_name += ".pdf"

                print(f"[FIRME] Aggiungo al ZIP: {safe_name} ({len(redacted_image_paths)} pagine)", flush=True)
                zipf.writestr(safe_name, pdf_buffer.read())

        zip_buffer.seek(0)

        # Cancella tutte le cartelle temporanee
        for d in doc_dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
                print(f"[FIRME] Eliminata cartella temporanea: {d}", flush=True)
            except Exception as e:
                print(f"[FIRME][WARN] Impossibile eliminare {d}: {e}", flush=True)

        # Se non abbiamo scritto niente nello ZIP -> errore esplicito
        if zip_buffer.getbuffer().nbytes == 0:
            print("[FIRME][ERR] ZIP vuoto: nessun PDF oscurato generato", flush=True)
            return jsonify({"error": "Nessun PDF oscurato generato (nessuna pagina utile)."}), 400

        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name="pdf_oscurati.zip"
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Errore interno durante la generazione ZIP: {e}"}), 500


@app.route("/dashboard/")
@login_required
def dashboard():
    # redirect alla home
    return redirect(url_for("root"))


@app.route("/")
@login_required
def root():
    path = os.path.join(DIR, INDEX_FILE)
    if not os.path.exists(path):
        abort(404, description=f"{INDEX_FILE} non trovato")
    return send_from_directory(DIR, INDEX_FILE)


@app.route("/index.html")
@login_required
def index_html():
    return send_from_directory(DIR, "index.html")

@app.route("/stato-avanzamento.html")
@login_required
def stato_avanzamento_html():
    return send_from_directory(DIR, "stato-avanzamento.html")


@app.route("/access.html")
@login_required
def access_html():
    return send_from_directory(DIR, "access.html")


@app.route("/mobilita-urp.html")
@login_required
def mobilita_urp_html():
    return send_from_directory(DIR, "mobilita-urp.html")


@app.route("/rdp-tool.html")
@login_required
def rdp_tool():
    return send_from_directory(DIR, "rdp-tool.html")


# Static/JSON protetti (invece di static_folder pubblico)
@app.route("/_static/<path:fname>", methods=["GET", "HEAD"])
@login_required
def protected_static(fname):
    if fname.startswith("docs_firme/"):
        parts = fname.split("/")
        if len(parts) >= 2:
            doc_id = parts[1]
            user_id = _current_user_id()
            if not _is_doc_owned_by_user(doc_id, user_id):
                abort(403)
    return send_from_directory(DIR, fname)


# Catch-all SPA PROTETTO (tutto ciò che non è /api/*)
@app.route("/<path:fname>")
def serve_or_index(fname):
    # harden: assicurati che sia una stringa
    if not isinstance(fname, str):
        abort(400)

    # blocca API
    if fname.startswith("api/"):
        abort(404)

    fullpath = os.path.join(DIR, fname)
    if os.path.isfile(fullpath):
        return send_from_directory(DIR, fname)

    # fallback SPA
    return send_from_directory(DIR, INDEX_FILE)

# ========= API =========

@app.get("/api/ping")
def ping():
    return {"ok": True}


@app.get("/api/status")
@login_required
def api_status():
    return jsonify({
        "urp":  {"exists": _exists(URP_JSON), "mtime": _ts(URP_JSON)},
        "sol":  {"exists": _exists(SOL_JSON), "mtime": _ts(SOL_JSON)},
        "mob":  {"exists": _exists(MOB_JSON), "mtime": _ts(MOB_JSON)},
        "running": run_lock.locked()
    })


@app.post("/api/run")
@login_required
def api_run():
    """
    Rilancia gli scraper.
    Body opzionale: { "urp": true/false, "sol": true/false, "mob": true/false }
    - urp: bloccante
    - sol, mob: background
    """
    cfg = request.get_json(silent=True) or {}
    do_urp = bool(cfg.get("urp", True))
    do_sol = bool(cfg.get("sol", True))
    do_mob = bool(cfg.get("mob", True))

    if run_lock.locked():
        return jsonify({"ok": False, "msg": "Una run è già in corso"}), 409

    def _runner():
        with run_lock:
            try:
                if do_urp:
                    run_scraper(SCR_URP, block=True)
                if do_sol:
                    run_scraper(SCR_SOL, block=False)
                if do_mob:
                    run_scraper(SCR_MOB, block=False)
                kick_monitors()
            except Exception as e:
                print(f"[RUN] Errore run manuale: {e}", flush=True)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    bg_threads.append(t)
    return jsonify({"ok": True, "msg": "Run avviata"})


# API RDP (se usi fetch_bandi_rdp)
@app.route("/api/bandi-rdp", methods=["GET", "OPTIONS"])
@app.route("/api/bandi-rdp/", methods=["GET", "OPTIONS"])
@login_required
def api_bandi_rdp():
    if request.method == "OPTIONS":
        return ("", 204)

    filter_type = request.args.get("filterType", getattr(svc, "FILTER_TYPE", "all"))
    offset = int(request.args.get("offset", getattr(svc, "OFFSET", 20)))
    codice = (request.args.get("codice") or "").strip().lower()
    nocache = request.args.get("nocache")

    now = time.time()
    cache_key = (filter_type, offset, codice)
    if (not nocache and CACHE_TTL > 0 and
        _cache.get("data") and _cache.get("key") == cache_key and
        (now - _cache.get("ts", 0)) < CACHE_TTL):
        return jsonify(_cache["data"])

    try:
        calls = svc.fetch_calls(offset=offset, filter_type=filter_type)
    except TypeError:
        calls = svc.fetch_calls()

    if codice:
        calls = [c for c in calls if codice in str(c.get("codice", "")).lower()]

    enriched = []
    for c in calls:
        full = svc.fetch_group_fullname(c.get("rdp_raw", ""))
        members = svc.fetch_rdp_members(full) if full else []
        enriched.append({
            "uuid": c.get("uuid", ""),
            "codice": c.get("codice", ""),
            "titolo": c.get("titolo", ""),
            "rdp_group": full,
            "rdp_members": members
        })

    _cache["ts"] = now
    _cache["key"] = cache_key
    _cache["data"] = enriched
    return jsonify(enriched)




from werkzeug.utils import secure_filename

@app.post("/api/check-access")
@login_required
def api_check_access_single():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Parametro 'file' assente"}), 400
    f = request.files["file"]
    name = secure_filename(f.filename or "documento.pdf")
    data = f.read()
    res = evaluate_uploaded(data, name)
    return jsonify({"ok": True, "result": res})

@app.post("/api/check-access-batch")
@login_required
def api_check_access_batch():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "Parametro 'files' assente"}), 400
    out = []
    for f in files:
        name = secure_filename(f.filename or "documento.pdf")
        data = f.read()
        out.append(evaluate_uploaded(data, name))
    return jsonify({"ok": True, "results": out})


# ========= Bootstrap =========
def main():
    t = threading.Thread(target=startup_sequence, daemon=True)
    t.start()
    bg_threads.append(t)

    kick_monitors()

    print(f"[INFO] Server Flask su http://localhost:{PORT}", flush=True)
    app.run(host="0.0.0.0", port=PORT, debug=False)





if __name__ == "__main__":
    main()
