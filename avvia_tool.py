#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import threading
import concurrent.futures
import subprocess
import json
import sqlite3
from datetime import datetime, timedelta
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

# Limit thread oversubscription (main process)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

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
job_queue: "queue.Queue[str]" = queue.Queue()
DOC_TTL_SECONDS = int(os.environ.get("FIRME_DOC_TTL_SECONDS", "86400"))
DB_PATH = os.path.join(os.path.dirname(__file__), "instance", "jobs.db")
_admin_env = os.environ.get("FIRME_ADMIN_EMAILS", "")
if not _admin_env:
    _admin_env = "danbiele.ramacci@cnr.it,daniele.ramacci@cnr.it"
_admin_raw = [e.strip().lower() for e in _admin_env.split(",") if e.strip()]
ADMIN_EMAILS = set()
for e in _admin_raw:
    ADMIN_EMAILS.add(e)
    if "@" in e:
        ADMIN_EMAILS.add(e.split("@", 1)[0])


def _current_user_id() -> str | None:
    return session.get("user_email") or session.get("user")


def _current_user_email() -> str | None:
    return session.get("user_email") or None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "on", "yes")


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _default_runtime_config() -> dict:
    return {
        "parallel_workers": min(32, max(1, _env_int("FIRME_PARALLEL_WORKERS", 2))),
        "dpi": _env_int("FIRME_DPI", 200),
        "yolo_imgsz": _env_int("FIRME_YOLO_IMGSZ", 640),
        "yolo_conf": _env_float("FIRME_YOLO_CONF", 0.25),
        "yolo_iou": _env_float("FIRME_YOLO_IOU", 0.45),
        "pii_enabled_default": _env_bool("PII_ENABLED_DEFAULT", True),
        "table_mode_default": _env_str("TABLE_MODE_DEFAULT", "full"),
        "ocr_lang": _env_str("PII_OCR_LANG", "ita"),
        "ocr_config": _env_str("PII_OCR_CONFIG", "--oem 3 --psm 6"),
    }


_runtime_lock = threading.Lock()
FIRME_RUNTIME_CONFIG = _default_runtime_config()


def _normalize_user_id(value: str | None) -> tuple[str, str]:
    if not value:
        return "", ""
    v = value.strip().lower()
    local = v.split("@", 1)[0] if "@" in v else v
    return v, local


def _is_admin(email: str | None) -> bool:
    if not email:
        return False
    full, local = _normalize_user_id(email)
    return full in ADMIN_EMAILS or (local and local in ADMIN_EMAILS)


def _db_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = {row["name"] for row in cur.fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _init_db() -> None:
    conn = _db_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            owner_email TEXT NOT NULL,
            status TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            progress_done INTEGER DEFAULT 0,
            progress_total INTEGER DEFAULT 0,
            timing_pages INTEGER DEFAULT 0,
            timing_total REAL DEFAULT 0,
            created_at REAL,
            updated_at REAL,
            error TEXT
        )
        """
    )
    _ensure_column(conn, "jobs", "pii_enabled", "pii_enabled INTEGER DEFAULT 1")
    _ensure_column(conn, "jobs", "pii_debug", "pii_debug INTEGER DEFAULT 0")
    _ensure_column(conn, "jobs", "table_mode", "table_mode TEXT DEFAULT 'full'")
    _ensure_column(conn, "jobs", "pdf_to_img_total", "pdf_to_img_total REAL DEFAULT 0")
    _ensure_column(conn, "jobs", "timing_yolo_firme_total", "timing_yolo_firme_total REAL DEFAULT 0")
    _ensure_column(conn, "jobs", "timing_yolo_table_total", "timing_yolo_table_total REAL DEFAULT 0")
    _ensure_column(conn, "jobs", "timing_ocr_total", "timing_ocr_total REAL DEFAULT 0")
    _ensure_column(conn, "jobs", "job_dpi", "job_dpi INTEGER DEFAULT 0")
    _ensure_column(conn, "jobs", "job_imgsz", "job_imgsz INTEGER DEFAULT 0")
    _ensure_column(conn, "jobs", "job_conf", "job_conf REAL DEFAULT 0")
    _ensure_column(conn, "jobs", "job_iou", "job_iou REAL DEFAULT 0")
    _ensure_column(conn, "jobs", "job_ocr_lang", "job_ocr_lang TEXT DEFAULT ''")
    _ensure_column(conn, "jobs", "job_ocr_config", "job_ocr_config TEXT DEFAULT ''")
    _ensure_column(conn, "jobs", "job_label", "job_label TEXT DEFAULT ''")
    _ensure_column(conn, "jobs", "job_note", "job_note TEXT DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_acl (
            job_id TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT DEFAULT 'viewer',
            PRIMARY KEY(job_id, email)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_documents (
            doc_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            filename TEXT,
            pages_count INTEGER DEFAULT 0,
            analyzed_at REAL,
            redacted_at REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_pages (
            job_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            page_index INTEGER NOT NULL,
            data_json TEXT,
            PRIMARY KEY(job_id, doc_id, page_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            exported_at REAL,
            exported_by TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS firme_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at REAL,
            updated_by TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _db_job_user_can_access(job_id: str, email: str | None) -> bool:
    if not email:
        return False
    if _is_admin(email):
        return True
    conn = _db_conn()
    row = conn.execute("SELECT owner_email FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if not row:
        conn.close()
        return False
    owner_full, owner_local = _normalize_user_id(row["owner_email"])
    user_full, user_local = _normalize_user_id(email)
    if owner_full == user_full or (owner_local and owner_local == user_local):
        conn.close()
        return True
    acl = conn.execute(
        "SELECT email FROM job_acl WHERE job_id = ?",
        (job_id,),
    ).fetchall()
    conn.close()
    for a in acl:
        a_full, a_local = _normalize_user_id(a["email"])
        if a_full == user_full or (a_local and a_local == user_local):
            return True
    return False


def _db_get_job(job_id: str) -> dict | None:
    conn = _db_conn()
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _db_update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    keys = list(fields.keys())
    values = [fields[k] for k in keys]
    sets = ", ".join(f"{k} = ?" for k in keys)
    conn = _db_conn()
    conn.execute(f"UPDATE jobs SET {sets} WHERE job_id = ?", (*values, job_id))
    conn.commit()
    conn.close()


def _db_set_progress(job_id: str, done: int, total: int) -> None:
    _db_update_job(job_id, progress_done=int(done), progress_total=int(total))


def _db_insert_job(
    job_id: str,
    owner_email: str,
    status: str,
    redaction_status: str,
    job_label: str = "",
    job_note: str = "",
) -> None:
    now = time.time()
    conn = _db_conn()
    conn.execute(
        """
        INSERT INTO jobs(job_id, owner_email, status, redaction_status, job_label, job_note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, owner_email, status, redaction_status, job_label, job_note, now, now),
    )
    conn.commit()
    conn.close()


def _db_insert_job_acl(job_id: str, email: str, role: str = "viewer") -> None:
    conn = _db_conn()
    conn.execute(
        "INSERT OR IGNORE INTO job_acl(job_id, email, role) VALUES (?, ?, ?)",
        (job_id, email, role),
    )
    conn.commit()
    conn.close()


def _db_insert_document(doc_id: str, job_id: str, filename: str) -> None:
    conn = _db_conn()
    conn.execute(
        "INSERT INTO job_documents(doc_id, job_id, filename) VALUES (?, ?, ?)",
        (doc_id, job_id, filename),
    )
    conn.commit()
    conn.close()


def _db_update_document(doc_id: str, **fields) -> None:
    if not fields:
        return
    keys = list(fields.keys())
    values = [fields[k] for k in keys]
    sets = ", ".join(f"{k} = ?" for k in keys)
    conn = _db_conn()
    conn.execute(f"UPDATE job_documents SET {sets} WHERE doc_id = ?", (*values, doc_id))
    conn.commit()
    conn.close()


def _db_upsert_page(job_id: str, doc_id: str, page_index: int, data: dict) -> None:
    payload = json.dumps(data)
    conn = _db_conn()
    conn.execute(
        """
        INSERT INTO job_pages(job_id, doc_id, page_index, data_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(job_id, doc_id, page_index) DO UPDATE SET data_json = excluded.data_json
        """,
        (job_id, doc_id, int(page_index), payload),
    )
    conn.commit()
    conn.close()


def _db_list_jobs(email: str, include_all: bool = False) -> list[dict]:
    conn = _db_conn()
    if include_all:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute(
            """
            SELECT DISTINCT j.*
            FROM jobs j
            LEFT JOIN job_acl a ON a.job_id = j.job_id
            WHERE lower(j.owner_email) = lower(?)
               OR lower(a.email) = lower(?)
            ORDER BY j.created_at DESC
            """,
            (email, email),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _db_get_job_documents(job_id: str) -> list[dict]:
    conn = _db_conn()
    rows = conn.execute(
        "SELECT * FROM job_documents WHERE job_id = ? ORDER BY rowid ASC",
        (job_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _db_get_job_pages(job_id: str, doc_id: str) -> list[dict]:
    conn = _db_conn()
    rows = conn.execute(
        "SELECT page_index, data_json FROM job_pages WHERE job_id = ? AND doc_id = ? ORDER BY page_index ASC",
        (job_id, doc_id),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["data_json"]))
        except Exception:
            out.append({})
    return out


def _db_get_job_acl(job_id: str) -> list[str]:
    conn = _db_conn()
    rows = conn.execute(
        "SELECT email FROM job_acl WHERE job_id = ? ORDER BY email ASC",
        (job_id,),
    ).fetchall()
    conn.close()
    return [r["email"] for r in rows]


def _load_runtime_config_from_db() -> None:
    defaults = _default_runtime_config()
    cfg = dict(defaults)
    try:
        conn = _db_conn()
        rows = conn.execute("SELECT key, value FROM firme_config").fetchall()
        conn.close()
        for r in rows:
            key = r["key"]
            val = r["value"]
            if key not in cfg:
                continue
            if isinstance(cfg[key], bool):
                cfg[key] = str(val).lower() in ("1", "true", "on", "yes")
            elif isinstance(cfg[key], int):
                try:
                    cfg[key] = int(float(val))
                except Exception:
                    pass
            elif isinstance(cfg[key], float):
                try:
                    cfg[key] = float(val)
                except Exception:
                    pass
            else:
                cfg[key] = str(val)
    except Exception:
        cfg = defaults
    with _runtime_lock:
        FIRME_RUNTIME_CONFIG.update(cfg)


def _save_runtime_config_to_db(updated_by: str | None = None) -> None:
    with _runtime_lock:
        items = dict(FIRME_RUNTIME_CONFIG)
    conn = _db_conn()
    now = time.time()
    for k, v in items.items():
        conn.execute(
            """
            INSERT INTO firme_config(key, value, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by
            """,
            (k, str(v), now, updated_by or ""),
        )
    conn.commit()
    conn.close()


def _get_runtime_config() -> dict:
    with _runtime_lock:
        return dict(FIRME_RUNTIME_CONFIG)


def _update_runtime_config(patch: dict, updated_by: str | None = None) -> dict:
    with _runtime_lock:
        FIRME_RUNTIME_CONFIG.update(patch)
    _save_runtime_config_to_db(updated_by)
    return _get_runtime_config()


def _db_delete_job(job_id: str) -> None:
    conn = _db_conn()
    conn.execute("DELETE FROM job_pages WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_documents WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_acl WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_exports WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    conn.commit()
    conn.close()


def _assemble_job_documents(job_id: str) -> list[dict]:
    documents = []
    for doc in _db_get_job_documents(job_id):
        pages = _db_get_job_pages(job_id, doc["doc_id"])
        documents.append({
            "doc_id": doc["doc_id"],
            "filename": doc.get("filename"),
            "pages": pages,
        })
    return documents


def _get_system_stats(job: dict | None = None) -> dict:
    stats: dict = {
        "cpu_count": os.cpu_count() or 1,
        "load_avg": None,
        "mem_total_gb": None,
        "mem_free_gb": None,
        "swap_used_gb": None,
    }
    if hasattr(os, "getloadavg"):
        try:
            stats["load_avg"] = list(os.getloadavg())
        except Exception:
            stats["load_avg"] = None
    meminfo_path = "/proc/meminfo"
    if os.path.exists(meminfo_path):
        try:
            data = {}
            with open(meminfo_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    parts = line.split(":")
                    if len(parts) < 2:
                        continue
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    data[key] = int(val)
            if "MemTotal" in data:
                stats["mem_total_gb"] = round(data["MemTotal"] / 1024 / 1024, 2)
            if "MemAvailable" in data:
                stats["mem_free_gb"] = round(data["MemAvailable"] / 1024 / 1024, 2)
            if "SwapTotal" in data and "SwapFree" in data:
                swap_used = max(0, data["SwapTotal"] - data["SwapFree"])
                stats["swap_used_gb"] = round(swap_used / 1024 / 1024, 2)
        except Exception:
            pass
    if job:
        timing_pages = int(job.get("timing_pages") or 0)
        timing_total = float(job.get("timing_total") or 0.0)
        if timing_pages > 0:
            stats["avg_page_sec"] = timing_total / timing_pages
        else:
            stats["avg_page_sec"] = None
        progress_total = int(job.get("progress_total") or 0)
        progress_done = int(job.get("progress_done") or 0)
        remaining = max(0, progress_total - progress_done)
        if stats.get("avg_page_sec") is not None:
            stats["eta_sec"] = remaining * stats["avg_page_sec"]
        else:
            stats["eta_sec"] = None
    return stats


def _read_cgroup_value(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except Exception:
        return None


def _get_cgroup_limits() -> dict:
    limits: dict[str, float | None] = {"cpu_limit": None, "mem_limit_gb": None}
    cpu_max = _read_cgroup_value("/sys/fs/cgroup/cpu.max")
    if cpu_max and cpu_max != "max":
        try:
            quota_str, period_str = cpu_max.split()
            quota = int(quota_str)
            period = int(period_str)
            if quota > 0 and period > 0:
                limits["cpu_limit"] = round(quota / period, 2)
        except Exception:
            pass
    mem_max = _read_cgroup_value("/sys/fs/cgroup/memory.max")
    if mem_max and mem_max != "max":
        try:
            mem_bytes = int(mem_max)
            if mem_bytes > 0:
                limits["mem_limit_gb"] = round(mem_bytes / 1024 / 1024 / 1024, 2)
        except Exception:
            pass
    return limits


def _get_metrics_snapshot() -> dict:
    conn = _db_conn()
    rows = conn.execute(
        """
        SELECT status, progress_done, progress_total, timing_pages, timing_total,
               pdf_to_img_total, timing_yolo_firme_total, timing_yolo_table_total, timing_ocr_total
        FROM jobs
        """
    ).fetchall()
    conn.close()

    total_jobs = len(rows)
    running = sum(1 for r in rows if r["status"] in ("queued", "running"))
    done = sum(1 for r in rows if r["status"] == "done")
    error = sum(1 for r in rows if r["status"] == "error")
    pages_done = sum(int(r["progress_done"] or 0) for r in rows)
    pages_total = sum(int(r["progress_total"] or 0) for r in rows)
    timing_pages = sum(int(r["timing_pages"] or 0) for r in rows)
    timing_total = sum(float(r["timing_total"] or 0.0) for r in rows)
    pdf_to_img_total = sum(float(r["pdf_to_img_total"] or 0.0) for r in rows)
    timing_yolo_firme_total = sum(float(r["timing_yolo_firme_total"] or 0.0) for r in rows)
    timing_yolo_table_total = sum(float(r["timing_yolo_table_total"] or 0.0) for r in rows)
    timing_ocr_total = sum(float(r["timing_ocr_total"] or 0.0) for r in rows)

    avg_page_sec = (timing_total / timing_pages) if timing_pages else None
    remaining = max(0, pages_total - pages_done)
    eta_sec = (avg_page_sec * remaining) if avg_page_sec is not None else None

    bottleneck_hint = None
    total_cost = pdf_to_img_total + timing_yolo_firme_total + timing_yolo_table_total + timing_ocr_total
    if total_cost > 0:
        share_pdf = pdf_to_img_total / total_cost
        share_ocr = timing_ocr_total / total_cost
        share_yolo = (timing_yolo_firme_total + timing_yolo_table_total) / total_cost
        if share_pdf >= 0.4:
            bottleneck_hint = "pdf_to_img domina: riduci DPI o abilita streaming"
        elif share_ocr >= 0.4:
            bottleneck_hint = "ocr domina: ottimizza OCR (lang/config)"
        elif share_yolo >= 0.4:
            bottleneck_hint = "yolo domina: riduci imgsz/conf o valuta fuse"

    runtime_cfg = _get_runtime_config()
    limits = _get_cgroup_limits()

    return {
        "total_jobs": total_jobs,
        "running_jobs": running,
        "done_jobs": done,
        "error_jobs": error,
        "pages_done": pages_done,
        "pages_total": pages_total,
        "avg_page_sec": avg_page_sec,
        "eta_sec": eta_sec,
        "workers_configured": int(runtime_cfg.get("parallel_workers") or 2),
        "table_detector": os.environ.get("PII_TABLE_DETECTOR", "morph"),
        "pii_ocr_lang": runtime_cfg.get("ocr_lang") or os.environ.get("PII_OCR_LANG", "ita"),
        "pdf_to_img_total": pdf_to_img_total,
        "timing_yolo_firme_total": timing_yolo_firme_total,
        "timing_yolo_table_total": timing_yolo_table_total,
        "timing_ocr_total": timing_ocr_total,
        "bottleneck_hint": bottleneck_hint,
        "cpu_limit": limits.get("cpu_limit"),
        "mem_limit_gb": limits.get("mem_limit_gb"),
    }


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
    owner = _read_doc_owner(doc_id)
    if owner:
        owner_full, owner_local = _normalize_user_id(owner)
        user_full, user_local = _normalize_user_id(user_id)
        if owner_full == user_full or (owner_local and owner_local == user_local):
            return True
    try:
        conn = _db_conn()
        row = conn.execute("SELECT job_id FROM job_documents WHERE doc_id = ?", (doc_id,)).fetchone()
        conn.close()
        if not row:
            return False
        return _db_job_user_can_access(row["job_id"], user_id)
    except Exception:
        return False


def _update_job(job_id: str, **kwargs) -> None:
    _db_update_job(job_id, **kwargs)


def _set_job_progress(job_id: str, done: int, total: int) -> None:
    _db_set_progress(job_id, done, total)


def _box_intersects_norm(a: dict, b: dict) -> bool:
    ax1, ay1 = float(a.get("x", 0)), float(a.get("y", 0))
    ax2, ay2 = ax1 + float(a.get("w", 0)), ay1 + float(a.get("h", 0))
    bx1, by1 = float(b.get("x", 0)), float(b.get("y", 0))
    bx2, by2 = bx1 + float(b.get("w", 0)), by1 + float(b.get("h", 0))
    return not (ax2 <= bx1 or ax1 >= bx2 or ay2 <= by1 or ay1 >= by2)


def _detect_signatures_from_bgr(
    img_bgr: np.ndarray,
    imgsz: int | None = None,
    conf: float | None = None,
    iou: float | None = None,
) -> list[dict]:
    if img_bgr is None:
        return []
    h, w = img_bgr.shape[:2]
    if _YOLO_FIRME_WORKER is None:
        results = yolo_firme.predict(source=img_bgr, save=False, imgsz=imgsz, conf=conf, iou=iou)[0]
    else:
        results = _YOLO_FIRME_WORKER.predict(source=img_bgr, save=False, imgsz=imgsz, conf=conf, iou=iou)[0]
    boxes_out: list[dict] = []
    for box in results.boxes:
        x1, y1, x2, y2 = map(float, box.xyxy[0])
        conf = float(box.conf[0])
        box_w = x2 - x1
        box_h = y2 - y1
        x_norm = max(0.0, min(1.0, x1 / w))
        y_norm = max(0.0, min(1.0, y1 / h))
        w_norm = max(0.0, min(1.0 - x_norm, box_w / w))
        h_norm = max(0.0, min(1.0 - y_norm, box_h / h))
        boxes_out.append({
            "x": x_norm,
            "y": y_norm,
            "w": w_norm,
            "h": h_norm,
            "score": conf,
        })
    return boxes_out


def _detect_signatures_worker(image_path: str) -> list[dict]:
    img = cv2.imread(image_path)
    if img is None:
        return []
    return _detect_signatures_from_bgr(img)


def _process_page_task(doc_id: str, doc_dir: str, i: int, image_path: str, job_conf: dict) -> tuple[str, int, dict]:
    image_filename = f"page_{i}.png"
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        raise RuntimeError(f"Impossibile leggere immagine: {image_path}")
    height, width = img_bgr.shape[:2]

    t_yolo_start = time.perf_counter()
    auto_boxes = _detect_signatures_from_bgr(
        img_bgr,
        imgsz=job_conf.get("yolo_imgsz"),
        conf=job_conf.get("yolo_conf"),
        iou=job_conf.get("yolo_iou"),
    )
    t_yolo_firme = time.perf_counter() - t_yolo_start
    norm_boxes = [{
        "x": float(b["x"]),
        "y": float(b["y"]),
        "w": float(b["w"]),
        "h": float(b.get("h", 0.0)),
        "score": float(b.get("score", 1.0))
    } for b in auto_boxes]

    pii_boxes = []
    pii_reject_boxes = []
    table_boxes = []
    t_yolo_tabelle = 0.0
    t_ocr = 0.0
    if job_conf.get("pii_enabled"):
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
            if job_conf.get("ocr_lang"):
                os.environ["PII_OCR_LANG"] = str(job_conf.get("ocr_lang"))
            if job_conf.get("ocr_config"):
                os.environ["PII_OCR_CONFIG"] = str(job_conf.get("ocr_config"))
            t_ocr_start = time.perf_counter()
            ocr_pages = extract_ocr_from_images([image_path])
            if ocr_pages:
                ocr_page = ocr_pages[0]
                text_raw = ocr_page.get("text_raw", "")
                tokens = ocr_page.get("tokens", [])
                ocr_w = ocr_page.get("width") or width
                ocr_h = ocr_page.get("height") or height
                pii = extract_pii(text_raw.upper())
                pii_boxes = build_pii_boxes(pii, tokens, ocr_w, ocr_h)

                t_table_start = time.perf_counter()
                table_raw = detect_tables(image_path)
                t_yolo_tabelle = time.perf_counter() - t_table_start
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

                if job_conf.get("table_mode") != "columns" and table_boxes:
                    for tb in table_boxes:
                        has_sig = any(_box_intersects_norm(tb, b) for b in norm_boxes)
                        has_sensitive = any(
                            _box_intersects_norm(tb, b)
                            for b in pii_boxes
                            if b.get("source") not in ("table_header",)
                        )
                        if has_sig or has_sensitive:
                            pii_boxes.append({
                                "x": tb["x"],
                                "y": tb["y"],
                                "w": tb["w"],
                                "h": tb["h"],
                                "label": "TABLE_REDACT",
                                "confidence": "high",
                                "source": "table_redact",
                            })

                pii_reject_boxes = []
                if job_conf.get("pii_debug") and column_boxes:
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
            t_ocr = time.perf_counter() - t_ocr_start
        except Exception as e:
            print(f"[PII][WARN] OCR fallito per pagina {i}: {e}", flush=True)

    timing_total = t_yolo_firme + t_yolo_tabelle + t_ocr
    print(
        f"[TIMING] doc_id={doc_id} page={i} "
        f"yolo_firme={t_yolo_firme:.3f}s yolo_tabelle={t_yolo_tabelle:.3f}s "
        f"ocr={t_ocr:.3f}s total={timing_total:.3f}s",
        flush=True,
    )

    page_info = {
        "index": i,
        "image_url": f"/_static/docs_firme/{doc_id}/{image_filename}",
        "width": width,
        "height": height,
        "auto_boxes": norm_boxes,
        "pii_boxes": pii_boxes,
        "pii_reject_boxes": pii_reject_boxes if job_conf.get("pii_debug") else [],
        "table_boxes": table_boxes if job_conf.get("pii_enabled") else [],
        "manual_boxes": [],
        "timing_yolo_firme": t_yolo_firme,
        "timing_yolo_tabelle": t_yolo_tabelle,
        "timing_ocr": t_ocr,
        "timing_total": timing_total,
    }
    return doc_id, i, page_info

# cache minima per /api/bandi-rdp
CACHE_TTL = int(os.environ.get("CACHE_TTL", "60"))
_cache = {"ts": 0, "key": None, "data": []}


# ========= App =========
app = Flask(__name__, static_folder=None, static_url_path=None)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')

# Sessione server-side su filesystem (consigliato per evitare cookie giganti)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(__file__), 'instance', 'flask_session')
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # True se usi HTTPS
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
session_ttl = int(os.environ.get("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 7)))
app.permanent_session_lifetime = timedelta(seconds=session_ttl)

Session(app)

# registra le route di autenticazione (/login, /oidc-callback, /logout, /api/userinfo)
app.register_blueprint(auth_bp)

_init_db()
_load_runtime_config_from_db()



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
try:
    torch.set_num_threads(1)
    if hasattr(torch, "set_num_interop_threads"):
        torch.set_num_interop_threads(1)
except Exception:
    pass

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

_YOLO_FIRME_WORKER = None


def _init_process_worker(model_path: str) -> None:
    global _YOLO_FIRME_WORKER
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    try:
        import torch
        torch.set_num_threads(1)
        if hasattr(torch, "set_num_interop_threads"):
            torch.set_num_interop_threads(1)
    except Exception:
        pass
    try:
        _YOLO_FIRME_WORKER = YOLO(model_path)
    except Exception as exc:
        print(f"[FIRME][ERR] Worker YOLO init failed: {exc}", flush=True)
    try:
        from pii_ocr import table_detect as _td
        mode = os.environ.get("PII_TABLE_DETECTOR", "morph").lower()
        if mode.startswith("yolo") or mode == "auto":
            _td.init_table_model()
    except Exception as exc:
        print(f"[PII][WARN] Worker table model init failed: {exc}", flush=True)


class FirmePoolManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor: concurrent.futures.ProcessPoolExecutor | None = None
        self._size = 0

    def ensure_size(self, size: int) -> None:
        size = max(1, min(48, int(size)))
        with self._lock:
            if self._executor is not None and self._size == size:
                return
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None
            self._executor = concurrent.futures.ProcessPoolExecutor(
                max_workers=size,
                initializer=_init_process_worker,
                initargs=(model_firme_path,),
            )
            self._size = size

    def get_executor(self, size: int) -> concurrent.futures.ProcessPoolExecutor:
        self.ensure_size(size)
        assert self._executor is not None
        return self._executor


_pool_manager = FirmePoolManager()


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


def pdf_page_count(pdf_path: str) -> int:
    try:
        doc = fitz.open(pdf_path)
        count = doc.page_count
        doc.close()
        return count
    except Exception:
        return 0


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
        job = _db_get_job(job_id)
        if not job:
            continue
        _update_job(job_id, status="running")
        try:
            total_pages = 0
            done_pages = 0
            documents_meta = _db_get_job_documents(job_id)
            for doc in documents_meta:
                total_pages += pdf_page_count(os.path.join(DOCS_FIRME_ROOT, doc["doc_id"], "original.pdf"))
            _set_job_progress(job_id, done_pages, total_pages)

            runtime_cfg = _get_runtime_config()
            job_conf = {
                "pii_enabled": bool(job.get("pii_enabled", 1)),
                "pii_debug": bool(job.get("pii_debug", 0)),
                "table_mode": job.get("table_mode", "full"),
                "parallel_workers": int(runtime_cfg.get("parallel_workers") or 2),
                "dpi": int(job.get("job_dpi") or runtime_cfg.get("dpi") or 200),
                "yolo_imgsz": int(job.get("job_imgsz") or runtime_cfg.get("yolo_imgsz") or 640),
                "yolo_conf": float(job.get("job_conf") or runtime_cfg.get("yolo_conf") or 0.25),
                "yolo_iou": float(job.get("job_iou") or runtime_cfg.get("yolo_iou") or 0.45),
                "ocr_lang": (job.get("job_ocr_lang") or runtime_cfg.get("ocr_lang") or "").strip(),
                "ocr_config": (job.get("job_ocr_config") or runtime_cfg.get("ocr_config") or "").strip(),
            }

            timing_pages = int(job.get("timing_pages") or 0)
            timing_total = float(job.get("timing_total") or 0.0)
            timing_yolo_firme_total = float(job.get("timing_yolo_firme_total") or 0.0)
            timing_yolo_table_total = float(job.get("timing_yolo_table_total") or 0.0)
            timing_ocr_total = float(job.get("timing_ocr_total") or 0.0)
            pdf_to_img_total = float(job.get("pdf_to_img_total") or 0.0)

            max_workers = max(1, min(48, int(job_conf.get("parallel_workers") or 1)))
            executor = _pool_manager.get_executor(max_workers) if max_workers > 1 else None

            def _handle_page_result(page_info: dict) -> None:
                nonlocal timing_pages, timing_total, timing_yolo_firme_total, timing_yolo_table_total, timing_ocr_total, pdf_to_img_total, done_pages
                _db_upsert_page(job_id, doc_id, page_info["index"], page_info)
                if page_info.get("timing_total"):
                    timing_pages += 1
                    timing_total += float(page_info["timing_total"])
                    timing_yolo_firme_total += float(page_info.get("timing_yolo_firme") or 0.0)
                    timing_yolo_table_total += float(page_info.get("timing_yolo_tabelle") or 0.0)
                    timing_ocr_total += float(page_info.get("timing_ocr") or 0.0)
                _db_update_job(
                    job_id,
                    timing_pages=timing_pages,
                    timing_total=timing_total,
                    timing_yolo_firme_total=timing_yolo_firme_total,
                    timing_yolo_table_total=timing_yolo_table_total,
                    timing_ocr_total=timing_ocr_total,
                    pdf_to_img_total=pdf_to_img_total,
                )
                done_pages += 1
                _set_job_progress(job_id, done_pages, total_pages)

            for doc in documents_meta:
                doc_id = doc["doc_id"]
                doc_dir = os.path.join(DOCS_FIRME_ROOT, doc_id)
                pdf_path = os.path.join(doc_dir, "original.pdf")

                t_conv_total = 0.0
                futures: dict[concurrent.futures.Future, int] = {}
                try:
                    pdf_doc = fitz.open(pdf_path)
                except Exception as exc:
                    raise RuntimeError(f"Impossibile aprire PDF {pdf_path}: {exc}") from exc
                try:
                    page_count = pdf_doc.page_count
                    zoom = float(job_conf.get("dpi") or 200) / 72
                    mat = fitz.Matrix(zoom, zoom)

                    for i in range(page_count):
                        t_conv_start = time.perf_counter()
                        page = pdf_doc.load_page(i)
                        pix = page.get_pixmap(matrix=mat, alpha=False)
                        image_filename = f"page_{i}.png"
                        image_path = os.path.join(doc_dir, image_filename)
                        pix.save(image_path)
                        t_conv = time.perf_counter() - t_conv_start
                        t_conv_total += t_conv
                        pdf_to_img_total += t_conv

                        if executor:
                            fut = executor.submit(_process_page_task, doc_id, doc_dir, i, image_path, job_conf)
                            futures[fut] = i
                            if len(futures) >= max_workers * 4:
                                done = next(concurrent.futures.as_completed(futures))
                                _, _, page_info = done.result()
                                futures.pop(done, None)
                                _handle_page_result(page_info)
                        else:
                            _, _, page_info = _process_page_task(doc_id, doc_dir, i, image_path, job_conf)
                            _handle_page_result(page_info)
                finally:
                    pdf_doc.close()
                if t_conv_total > 0:
                    print(
                        f"[TIMING] doc_id={doc_id} step=pdf_to_img pages={page_count} seconds={t_conv_total:.3f}",
                        flush=True,
                    )

                if executor:
                    for fut in concurrent.futures.as_completed(list(futures.keys())):
                        _, _, page_info = fut.result()
                        _handle_page_result(page_info)
                    futures.clear()

                _db_update_document(
                    doc_id,
                    pages_count=page_count,
                    analyzed_at=time.time(),
                )

            _update_job(job_id, status="done")
        except Exception as exc:
            _update_job(job_id, status="error", error=str(exc))
        finally:
            job_queue.task_done()


_worker_thread = threading.Thread(target=_worker_loop, daemon=True)
_worker_thread.start()


def _cleanup_doc_dirs():
    while True:
        try:
            if os.environ.get("FIRME_CLEANUP_ENABLED", "0").lower() not in ("1", "true", "on", "yes"):
                time.sleep(600)
                continue
            now = time.time()
            active_doc_ids = set()
            conn = _db_conn()
            rows = conn.execute(
                "SELECT doc_id FROM job_documents d JOIN jobs j ON j.job_id = d.job_id WHERE j.status IN ('queued','running')"
            ).fetchall()
            conn.close()
            for r in rows:
                active_doc_ids.add(r["doc_id"])
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
    return _detect_signatures_from_bgr(img)

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
    resp = send_from_directory(DIR, "redazione-firme.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/firme-jobs.html")
@login_required
def firme_jobs_html():
    resp = send_from_directory(DIR, "firme-jobs.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.get("/api/firme/jobs")
@login_required
def api_firme_jobs():
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "Utente non autenticato"}), 403
    include_all = _is_admin(user_id)
    jobs_list = _db_list_jobs(user_id, include_all=include_all)
    out = []
    for j in jobs_list:
        acl_list = _db_get_job_acl(j.get("job_id")) if include_all else []
        owner_email = j.get("owner_email") or ""
        if acl_list and owner_email:
            owner_full, owner_local = _normalize_user_id(owner_email)
            acl_list = [
                a for a in acl_list
                if _normalize_user_id(a)[0] != owner_full and _normalize_user_id(a)[1] != owner_local
            ]
        avg_page = None
        eta = None
        if j.get("timing_pages"):
            avg_page = float(j.get("timing_total") or 0.0) / max(1, int(j.get("timing_pages") or 0))
        if avg_page is not None and j.get("progress_total"):
            remaining = max(0, int(j.get("progress_total") or 0) - int(j.get("progress_done") or 0))
            eta = remaining * avg_page
        out.append({
            "job_id": j.get("job_id"),
            "owner_email": owner_email,
            "job_label": j.get("job_label") or "",
            "job_note": j.get("job_note") or "",
            "authorized": acl_list,
            "status": j.get("status"),
            "redaction_status": j.get("redaction_status"),
            "progress": {"done": j.get("progress_done", 0), "total": j.get("progress_total", 0)},
            "created_at": j.get("created_at"),
            "updated_at": j.get("updated_at"),
            "avg_page_sec": avg_page,
            "eta_sec": eta,
        })
    return jsonify({"jobs": out, "is_admin": include_all})


@app.post("/api/firme/jobs/<job_id>/meta")
@login_required
def api_firme_job_meta(job_id: str):
    user_id = _current_user_id()
    if not _db_job_user_can_access(job_id, user_id):
        return jsonify({"error": "Accesso negato"}), 403
    payload = request.json or {}
    label = (payload.get("job_label") or "").strip()
    note = (payload.get("job_note") or "").strip()
    if len(label) > 120:
        return jsonify({"error": "Etichetta troppo lunga (max 120)"}), 400
    if len(note) > 200:
        return jsonify({"error": "Nota troppo lunga (max 200)"}), 400
    _db_update_job(job_id, job_label=label, job_note=note)
    return jsonify({"ok": True, "job_label": label, "job_note": note})


@app.get("/api/firme/jobs/<job_id>")
@login_required
def api_firme_job_detail(job_id: str):
    user_id = _current_user_id()
    job = _db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job non trovato"}), 404
    if not _db_job_user_can_access(job_id, user_id):
        return jsonify({"error": "Accesso negato"}), 403
    documents = _assemble_job_documents(job_id)
    return jsonify({
        "job": {
            "job_id": job_id,
            "status": job.get("status"),
            "redaction_status": job.get("redaction_status"),
            "progress": {"done": job.get("progress_done", 0), "total": job.get("progress_total", 0)},
        },
        "documents": documents,
    })


@app.post("/api/firme/jobs/<job_id>/save")
@login_required
def api_firme_job_save(job_id: str):
    user_id = _current_user_id()
    if not _db_job_user_can_access(job_id, user_id):
        return jsonify({"error": "Accesso negato"}), 403
    payload = request.json or {}
    docs = payload.get("documents") or []
    for doc in docs:
        doc_id = doc.get("doc_id")
        pages = doc.get("pages") or []
        if not doc_id:
            continue
        for page in pages:
            page_idx = page.get("index")
            if page_idx is None:
                page_idx = page.get("page_index")
            if page_idx is None:
                continue
            page["index"] = page_idx
            _db_upsert_page(job_id, doc_id, page_idx, page)
    _db_update_job(job_id, redaction_status="in_progress")
    return jsonify({"ok": True})


@app.post("/api/firme/jobs/<job_id>/delete")
@login_required
def api_firme_job_delete(job_id: str):
    user_id = _current_user_id()
    job = _db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job non trovato"}), 404
    if not user_id:
        return jsonify({"error": "Utente non autenticato"}), 403
    if not (_is_admin(user_id) or (job.get("owner_email") or "").lower() == user_id.lower()):
        return jsonify({"error": "Accesso negato"}), 403
    for doc in _db_get_job_documents(job_id):
        doc_dir = os.path.join(DOCS_FIRME_ROOT, doc["doc_id"])
        if os.path.isdir(doc_dir):
            shutil.rmtree(doc_dir, ignore_errors=True)
    _db_delete_job(job_id)
    return jsonify({"ok": True})


@app.post("/api/firme/jobs/<job_id>/share")
@login_required
def api_firme_job_share(job_id: str):
    user_id = _current_user_id()
    if not _is_admin(user_id):
        return jsonify({"error": "Accesso negato"}), 403
    payload = request.json or {}
    email = (payload.get("email") or "").strip()
    role = (payload.get("role") or "viewer").strip()
    if not email:
        return jsonify({"error": "Email mancante"}), 400
    _db_insert_job_acl(job_id, email, role)
    return jsonify({"ok": True})


@app.route("/api/firme/jobs/<job_id>/unshare", methods=["POST", "DELETE"])
@login_required
def api_firme_job_unshare(job_id: str):
    user_id = _current_user_id()
    if not _is_admin(user_id):
        return jsonify({"error": "Accesso negato"}), 403
    payload = request.json or {}
    email = (payload.get("email") or "").strip()
    if not email:
        return jsonify({"error": "Email mancante"}), 400
    conn = _db_conn()
    conn.execute(
        "DELETE FROM job_acl WHERE job_id = ? AND lower(email) = lower(?)",
        (job_id, email),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.get("/api/system/stats")
@login_required
def api_system_stats():
    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "Utente non autenticato"}), 403
    return jsonify(_get_system_stats())


@app.get("/api/system/metrics")
@login_required
def api_system_metrics():
    user_id = _current_user_id()
    if not _is_admin(user_id):
        return jsonify({"error": "Accesso negato"}), 403
    data = _get_metrics_snapshot()
    data.update(_get_system_stats())
    return jsonify(data)


@app.get("/api/system/report.txt")
@login_required
def api_system_report():
    user_id = _current_user_id()
    if not _is_admin(user_id):
        return jsonify({"error": "Accesso negato"}), 403
    metrics = _get_metrics_snapshot()
    stats = _get_system_stats()
    lines = []
    lines.append(f"timestamp: {datetime.utcnow().isoformat()}Z")
    lines.append(f"workers_configured: {metrics.get('workers_configured')}")
    lines.append(f"total_jobs: {metrics.get('total_jobs')}")
    lines.append(f"running_jobs: {metrics.get('running_jobs')}")
    lines.append(f"done_jobs: {metrics.get('done_jobs')}")
    lines.append(f"error_jobs: {metrics.get('error_jobs')}")
    lines.append(f"pages_done: {metrics.get('pages_done')}")
    lines.append(f"pages_total: {metrics.get('pages_total')}")
    lines.append(f"avg_page_sec: {metrics.get('avg_page_sec')}")
    lines.append(f"eta_sec: {metrics.get('eta_sec')}")
    lines.append(f"table_detector: {metrics.get('table_detector')}")
    lines.append(f"pii_ocr_lang: {metrics.get('pii_ocr_lang')}")
    lines.append(f"cpu_count: {stats.get('cpu_count')}")
    lines.append(f"load_avg: {stats.get('load_avg')}")
    lines.append(f"mem_total_gb: {stats.get('mem_total_gb')}")
    lines.append(f"mem_free_gb: {stats.get('mem_free_gb')}")
    lines.append(f"swap_used_gb: {stats.get('swap_used_gb')}")
    lines.append(f"cpu_limit: {metrics.get('cpu_limit')}")
    lines.append(f"mem_limit_gb: {metrics.get('mem_limit_gb')}")
    lines.append(f"pdf_to_img_total: {metrics.get('pdf_to_img_total')}")
    lines.append(f"timing_yolo_firme_total: {metrics.get('timing_yolo_firme_total')}")
    lines.append(f"timing_yolo_table_total: {metrics.get('timing_yolo_table_total')}")
    lines.append(f"timing_ocr_total: {metrics.get('timing_ocr_total')}")
    lines.append(f"bottleneck_hint: {metrics.get('bottleneck_hint')}")
    payload = "\n".join(str(l) for l in lines) + "\n"
    return send_file(
        io.BytesIO(payload.encode("utf-8")),
        mimetype="text/plain",
        as_attachment=True,
        download_name="parallelization-report.txt",
    )


def _validate_runtime_config_payload(payload: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    patch: dict = {}

    def _set_int(key: str, min_v: int, max_v: int) -> None:
        if key not in payload:
            return
        try:
            val = int(payload[key])
        except Exception:
            errors.append(f"{key} deve essere un intero")
            return
        if val < min_v or val > max_v:
            errors.append(f"{key} fuori range ({min_v}-{max_v})")
            return
        patch[key] = val

    def _set_float(key: str, min_v: float, max_v: float) -> None:
        if key not in payload:
            return
        try:
            val = float(payload[key])
        except Exception:
            errors.append(f"{key} deve essere un numero")
            return
        if val < min_v or val > max_v:
            errors.append(f"{key} fuori range ({min_v}-{max_v})")
            return
        patch[key] = val

    _set_int("parallel_workers", 1, 48)
    _set_int("dpi", 72, 400)
    _set_int("yolo_imgsz", 320, 1280)
    _set_float("yolo_conf", 0.0, 1.0)
    _set_float("yolo_iou", 0.0, 1.0)

    if "pii_enabled_default" in payload:
        val = payload["pii_enabled_default"]
        patch["pii_enabled_default"] = str(val).strip().lower() in ("1", "true", "on", "yes")
    if "table_mode_default" in payload:
        mode = str(payload["table_mode_default"]).strip().lower()
        if mode not in ("full", "columns"):
            errors.append("table_mode_default deve essere 'full' o 'columns'")
        else:
            patch["table_mode_default"] = mode
    if "ocr_lang" in payload:
        patch["ocr_lang"] = str(payload["ocr_lang"]).strip()
    if "ocr_config" in payload:
        patch["ocr_config"] = str(payload["ocr_config"]).strip()

    return patch, errors


@app.get("/api/firme/config")
@login_required
def api_firme_config_get():
    user_id = _current_user_id()
    if not _is_admin(user_id):
        return jsonify({"error": "Accesso negato"}), 403
    data = _get_runtime_config()
    stats = _get_system_stats()
    limits = _get_cgroup_limits()
    data.update({
        "cpu_count": stats.get("cpu_count"),
        "mem_total_gb": stats.get("mem_total_gb"),
        "mem_free_gb": stats.get("mem_free_gb"),
        "swap_used_gb": stats.get("swap_used_gb"),
        "load_avg": stats.get("load_avg"),
        "cpu_limit": limits.get("cpu_limit"),
        "mem_limit_gb": limits.get("mem_limit_gb"),
        "table_detector": os.environ.get("PII_TABLE_DETECTOR", "morph"),
    })
    return jsonify(data)


@app.post("/api/firme/config")
@login_required
def api_firme_config_post():
    user_id = _current_user_id()
    if not _is_admin(user_id):
        return jsonify({"error": "Accesso negato"}), 403
    payload = request.json or {}
    patch, errors = _validate_runtime_config_payload(payload)
    if errors:
        return jsonify({"error": "Configurazione non valida", "details": errors}), 400
    updated = _update_runtime_config(patch, updated_by=user_id)
    if "parallel_workers" in patch:
        _pool_manager.ensure_size(int(updated["parallel_workers"]))
    return jsonify(updated)


@app.post("/api/firme/config/reset")
@login_required
def api_firme_config_reset():
    user_id = _current_user_id()
    if not _is_admin(user_id):
        return jsonify({"error": "Accesso negato"}), 403
    defaults = _default_runtime_config()
    updated = _update_runtime_config(defaults, updated_by=user_id)
    _pool_manager.ensure_size(int(updated["parallel_workers"]))
    return jsonify(updated)

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

    runtime_cfg = _get_runtime_config()
    pii_flag = (request.form.get("pii") or "").strip().lower()
    pii_debug_flag = (request.form.get("pii_debug", "0") or "").strip().lower()
    table_mode = (request.form.get("table_mode") or "").strip().lower()
    job_label = (request.form.get("job_label") or "").strip()
    job_note = (request.form.get("job_note") or "").strip()
    pii_debug = pii_debug_flag in ("1", "true", "on", "yes")
    if pii_flag:
        pii_enabled = pii_flag in ("1", "true", "on", "yes")
    else:
        pii_enabled = bool(runtime_cfg.get("pii_enabled_default", True))
    if not table_mode:
        table_mode = str(runtime_cfg.get("table_mode_default", "full")).lower()

    user_id = _current_user_id()
    if not user_id:
        return jsonify({"error": "Utente non autenticato"}), 403

    job_id = str(uuid.uuid4())
    for pdf_file in files:
        if not pdf_file.filename:
            continue
        doc_id = str(uuid.uuid4())
        doc_dir = os.path.join(DOCS_FIRME_ROOT, doc_id)
        os.makedirs(doc_dir, exist_ok=True)
        pdf_path = os.path.join(doc_dir, "original.pdf")
        pdf_file.save(pdf_path)
        owner_email = _current_user_email() or user_id
        _write_doc_owner(doc_id, owner_email, job_id)
        _db_insert_document(doc_id, job_id, pdf_file.filename)

    owner_email = _current_user_email() or user_id
    _db_insert_job(job_id, owner_email, "queued", "not_started", job_label=job_label, job_note=job_note)

    def _parse_int_field(name: str) -> int:
        raw = (request.form.get(name) or "").strip()
        if not raw:
            return 0
        try:
            return int(raw)
        except Exception:
            return 0

    def _parse_float_field(name: str) -> float:
        raw = (request.form.get(name) or "").strip()
        if not raw:
            return 0.0
        try:
            return float(raw)
        except Exception:
            return 0.0

    job_dpi = _parse_int_field("dpi")
    job_imgsz = _parse_int_field("yolo_imgsz")
    job_conf = _parse_float_field("yolo_conf")
    job_iou = _parse_float_field("yolo_iou")
    job_ocr_lang = (request.form.get("ocr_lang") or "").strip()
    job_ocr_config = (request.form.get("ocr_config") or "").strip()
    _db_update_job(
        job_id,
        pii_enabled=1 if pii_enabled else 0,
        pii_debug=1 if pii_debug else 0,
        table_mode=table_mode if table_mode in ("full", "columns") else "full",
        job_dpi=job_dpi,
        job_imgsz=job_imgsz,
        job_conf=job_conf,
        job_iou=job_iou,
        job_ocr_lang=job_ocr_lang,
        job_ocr_config=job_ocr_config,
    )
    _db_insert_job_acl(job_id, user_id, role="owner")

    job_queue.put(job_id)
    return jsonify({"job_id": job_id, "status": "queued"})


@app.get("/api/firme/status/<job_id>")
@login_required
def api_firme_status(job_id: str):
    user_id = _current_user_id()
    job = _db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job non trovato"}), 404
    if not _db_job_user_can_access(job_id, user_id):
        return jsonify({"error": "Accesso negato"}), 403
    return jsonify({
        "job_id": job_id,
        "status": job.get("status"),
        "progress": {"done": job.get("progress_done", 0), "total": job.get("progress_total", 0)},
        "error": job.get("error"),
    })


@app.get("/api/firme/result/<job_id>")
@login_required
def api_firme_result(job_id: str):
    user_id = _current_user_id()
    job = _db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job non trovato"}), 404
    if not _db_job_user_can_access(job_id, user_id):
        return jsonify({"error": "Accesso negato"}), 403
    if job.get("status") != "done":
        return jsonify({"error": "Job non completato", "status": job.get("status")}), 400
    documents = []
    for doc in _db_get_job_documents(job_id):
        pages = _db_get_job_pages(job_id, doc["doc_id"])
        documents.append({
            "doc_id": doc["doc_id"],
            "filename": doc.get("filename"),
            "pages": pages,
        })
    return jsonify({"documents": documents})

# download PDF oscurati già generati (da immagini redatte salvate su disco)
@app.get("/api/firme/jobs/<job_id>/download")
@login_required
def api_firme_job_download(job_id: str):
    user_id = _current_user_id()
    job = _db_get_job(job_id)
    if not job:
        return jsonify({"error": "Job non trovato"}), 404
    if not _db_job_user_can_access(job_id, user_id):
        return jsonify({"error": "Accesso negato"}), 403
    if job.get("redaction_status") != "done":
        return jsonify({"error": "PDF oscurato non disponibile"}), 400

    docs = _db_get_job_documents(job_id)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for doc in docs:
            doc_id = doc.get("doc_id")
            if not doc_id:
                continue
            doc_dir = os.path.join(DOCS_FIRME_ROOT, doc_id)
            if not os.path.isdir(doc_dir):
                continue
            redacted_files = []
            for name in os.listdir(doc_dir):
                if not (name.startswith("redacted_page_") and name.endswith(".png")):
                    continue
                try:
                    idx = int(name[len("redacted_page_"):-4])
                except Exception:
                    continue
                redacted_files.append((idx, name))
            if not redacted_files:
                continue
            redacted_files.sort(key=lambda x: x[0])
            redacted_paths = [os.path.join(doc_dir, name) for _, name in redacted_files]
            pdf_buffer = io.BytesIO()
            try:
                pdf_buffer.write(img2pdf.convert(redacted_paths))
            except Exception as e:
                print(f"[FIRME][ERR] img2pdf.convert failed for doc_id={doc_id}: {e}", flush=True)
                continue
            pdf_buffer.seek(0)

            filename = (doc.get("filename") or f"documento_{doc_id}.pdf").strip()
            safe_name = secure_filename(filename)
            if not safe_name.lower().endswith(".pdf"):
                safe_name += ".pdf"
            zipf.writestr(safe_name, pdf_buffer.read())

    zip_buffer.seek(0)
    if zip_buffer.getbuffer().nbytes == 0:
        return jsonify({"error": "Nessun PDF oscurato disponibile per il download"}), 400

    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"pdf_oscurati_{job_id}.zip"
    )

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
      - mantiene i dati per permettere successive revisioni
      - restituisce lo ZIP come download

    I file restano sul server finché l'utente non elimina il job.
    """
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "JSON mancante in /api/firme/confirm"}), 400

        docs_data = data.get("documents", [])
        job_id = data.get("job_id")
        if not docs_data:
            return jsonify({"error": "Nessun documento da elaborare"}), 400

        print(f"[FIRME] Conferma redazione per {len(docs_data)} documenti", flush=True)
        user_id = _current_user_id()
        if not user_id:
            return jsonify({"error": "Utente non autenticato"}), 403

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
                if not job_id:
                    conn = _db_conn()
                    row = conn.execute("SELECT job_id FROM job_documents WHERE doc_id = ?", (doc_id,)).fetchone()
                    conn.close()
                    if row:
                        job_id = row["job_id"]

                doc_dir = os.path.join(DOCS_FIRME_ROOT, doc_id)
                if not os.path.isdir(doc_dir):
                    print(f"[FIRME][WARN] Cartella documento non trovata: {doc_dir}", flush=True)
                    continue

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
                    if job_id:
                        stored_page = dict(page_info)
                        stored_page["index"] = page_index
                        stored_page["manual_boxes"] = [
                            {"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"]}
                            for b in boxes
                        ]
                        edited = page_info.get("edited_boxes")
                        if isinstance(edited, list):
                            stored_page["edited_boxes"] = edited
                        _db_upsert_page(job_id, doc_id, page_index, stored_page)

                if not redacted_image_paths:
                    print(f"[FIRME][WARN] Nessuna pagina redatta per doc_id={doc_id}", flush=True)
                    continue

                # Ordina le pagine per index numerico
                redacted_image_paths.sort(
                    key=lambda p: int(os.path.basename(p).split("_")[-1].split(".")[0])
                )

                try:
                    t_write_start = time.perf_counter()
                    pdf_buffer = io.BytesIO()
                    pdf_buffer.write(img2pdf.convert(redacted_image_paths))
                    pdf_buffer.seek(0)
                    t_write = time.perf_counter() - t_write_start
                    print(
                        f"[TIMING] doc_id={doc_id} step=write_pdf pages={len(redacted_image_paths)} seconds={t_write:.3f}",
                        flush=True,
                    )
                except Exception as e:
                    print(f"[FIRME][ERR] Errore in img2pdf.convert per doc_id={doc_id}: {e}", flush=True)
                    continue

                safe_name = os.path.basename(filename)
                if not safe_name.lower().endswith(".pdf"):
                    safe_name += ".pdf"

                print(f"[FIRME] Aggiungo al ZIP: {safe_name} ({len(redacted_image_paths)} pagine)", flush=True)
                zipf.writestr(safe_name, pdf_buffer.read())

        zip_buffer.seek(0)

        if job_id:
            _db_update_job(job_id, redaction_status="done")
            conn = _db_conn()
            conn.execute(
                "INSERT INTO job_exports(job_id, exported_at, exported_by) VALUES (?, ?, ?)",
                (job_id, time.time(), user_id),
            )
            conn.commit()
            conn.close()
        for doc_entry in docs_data:
            doc_id = doc_entry.get("doc_id")
            if doc_id:
                _db_update_document(doc_id, redacted_at=time.time())

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


# ======== Debug temporaneo (rimuovere dopo diagnosi) ========
@app.get("/_debug/route-check")
def debug_route_check():
    """Diagnostica minimale per capire versioni/route/file in prod."""
    try:
        version_path = os.path.join(DIR, "version.json")
        version_info = None
        if os.path.exists(version_path):
            try:
                with open(version_path, "r", encoding="utf-8") as f:
                    version_info = json.load(f)
            except Exception as exc:
                version_info = {"error": str(exc)}

        expected_files = [
            "index.html",
            "firme-jobs.html",
            "redazione-firme.html",
            "stato-avanzamento.html",
        ]
        files = {name: os.path.isfile(os.path.join(DIR, name)) for name in expected_files}

        routes = []
        for rule in app.url_map.iter_rules():
            routes.append({"rule": str(rule), "methods": sorted(list(rule.methods or []))})

        return jsonify({
            "ok": True,
            "time": datetime.utcnow().isoformat() + "Z",
            "cwd": DIR,
            "index_file": INDEX_FILE,
            "files": files,
            "version": version_info,
            "routes": routes,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# Static/JSON protetti (invece di static_folder pubblico)
@app.route("/_static/<path:fname>", methods=["GET", "HEAD"])
@login_required
def protected_static(fname):
    if fname.startswith("docs_firme/"):
        parts = fname.split("/")
        if len(parts) >= 2:
            doc_id = parts[1]
            user_id = _current_user_id()
            if _is_admin(user_id):
                return send_from_directory(DIR, fname)
            if not _is_doc_owned_by_user(doc_id, user_id):
                abort(403)
    return send_from_directory(DIR, fname)


# Catch-all: non fare fallback a index (mostra errori reali)
@app.route("/<path:fname>")
@login_required
def serve_or_404(fname):
    # harden: assicurati che sia una stringa
    if not isinstance(fname, str):
        abort(400)

    # blocca API
    if fname.startswith("api/"):
        abort(404)

    fullpath = os.path.join(DIR, fname)
    if os.path.isfile(fullpath):
        return send_from_directory(DIR, fname)

    # nessun fallback: errore esplicito
    abort(404, description=f"Risorsa non trovata: {fname}")

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
