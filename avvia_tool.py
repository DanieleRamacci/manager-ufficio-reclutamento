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


from flask import (
    Flask, jsonify, send_from_directory, abort, request,
    redirect, url_for, session
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





# ========= Utils =========


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
