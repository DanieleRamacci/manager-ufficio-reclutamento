#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import threading
import subprocess
from datetime import datetime
from flask import Flask, jsonify, send_from_directory, abort, request
import fetch_bandi_rdp as svc


# === Config ===
PORT = int(os.environ.get("PORT", "8081"))
DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = "index.html"

# nomi file output (come nel tuo script originale)
URP_JSON = "bandi-completi-urp.json"
SOL_JSON = "bandi-concorsi-pubblici-sol.json"
MOB_JSON = "bandi-mobilita.json"

# nomi script (adatta se i file hanno un path differente)
SCR_URP = "scraper-urp.py"
SCR_SOL = "scraper-sol-tutti-bandi.py"
SCR_MOB = "scraper-mobilita.py"

# per evitare lanci concorrenti
run_lock = threading.Lock()
bg_threads = []

app = Flask(
    __name__,
    static_folder=DIR,        # serviamo i file direttamente dalla cartella corrente
    static_url_path="/_static"        # così /index.html e i .json sono raggiungibili
)

CACHE_TTL = int(os.environ.get("CACHE_TTL", "60"))
_cache = {"ts": 0, "data": []}

# -------- utilità --------
def _ts(path: str) -> str | None:
    p = os.path.join(DIR, path)
    if not os.path.exists(p):
        return None
    return datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")

def _exists(path: str) -> bool:
    return os.path.exists(os.path.join(DIR, path))

def run_scraper(script_name: str, block: bool = True) -> None:
    """Esegue uno script Python come nel tuo runner. Se block=False, parte in background."""
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
        # background fire-and-forget
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def startup_sequence():
    """Replica la tua main(): URP sincrono, poi SOL e Mobilità in background."""
    with run_lock:
        try:
            print("[BOOT] Avvio sequenza iniziale…", flush=True)
            # Step 1: URP (bloccante)
            run_scraper(SCR_URP, block=True)
            # Step 2: SOL + Mobilità in background
            run_scraper(SCR_SOL, block=False)
            run_scraper(SCR_MOB, block=False)
            print("[BOOT] Sequenza avviata. Server pronto.", flush=True)
        except Exception as e:
            print(f"[BOOT] Errore sequenza iniziale: {e}", flush=True)

def monitor_file(filepath: str, label: str):
    """Semplice monitor che stampa quando il file appare (opzionale)."""
    p = os.path.join(DIR, filepath)
    while not os.path.exists(p):
        time.sleep(2)
    print(f"✅ Dati {label} disponibili ({filepath}). Puoi aggiornare la pagina.", flush=True)

def kick_monitors():
    """Fa partire i monitor come thread daemon (opzionale)."""
    for fp, lb in [(SOL_JSON, "Selezioni Online"), (MOB_JSON, "Mobilità/Comandi")]:
        t = threading.Thread(target=monitor_file, args=(fp, lb), daemon=True)
        t.start()
        bg_threads.append(t)

# -------- routes --------


from flask import redirect, url_for

@app.route("/dashboard/")
def dashboard():
    # reindirizza alla home (index.html)
    return redirect(url_for("root"))

@app.route("/<path:fname>")
def serve_or_index(fname):
    # blocca le API
    if fname.startswith("api/"):
        abort(404)
    # se il file esiste nella cartella del progetto, servilo
    fullpath = os.path.join(DIR, fname)
    if os.path.isfile(fullpath):
        return send_from_directory(DIR, fname)
    # fallback: index.html (comportamento SPA)
    return send_from_directory(DIR, INDEX_FILE)

@app.get("/api/ping")
def ping():
    return {"ok": True}

@app.get("/api/routes")
def routes():
    # utile per vedere cosa è registrato davvero
    return {"routes": [str(r) for r in app.url_map.iter_rules()]}

@app.errorhandler(404)
def not_found(e):
    # mostra cosa esiste quando prendi un 404
    return jsonify({"error": "not found", "path": request.path,
                    "routes": [str(r) for r in app.url_map.iter_rules()]}), 404

@app.route("/rdp-tool.html")
def rdp_tool():
    return send_from_directory(DIR, "rdp-tool.html")


@app.route("/")
def root():
    # serve l'index (se non esiste, 404)
    if not os.path.exists(os.path.join(DIR, INDEX_FILE)):
        abort(404, description=f"{INDEX_FILE} non trovato")
    return send_from_directory(DIR, INDEX_FILE)


@app.get("/api/status")
def api_status():
    """Stato rapido: esistenza e timestamp degli output."""
    return jsonify({
        "urp":  {"exists": _exists(URP_JSON), "mtime": _ts(URP_JSON)},
        "sol":  {"exists": _exists(SOL_JSON), "mtime": _ts(SOL_JSON)},
        "mob":  {"exists": _exists(MOB_JSON), "mtime": _ts(MOB_JSON)},
        "running": run_lock.locked()
    })

@app.post("/api/run")
def api_run():
    """
    Rilancia gli scraper.
    Body JSON (opzionale): { "urp": true/false, "sol": true/false, "mob": true/false }
    - urp viene eseguito in modo bloccante (come all'avvio)
    - sol e mob in background
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


@app.route("/api/bandi-rdp", methods=["GET", "OPTIONS"])
@app.route("/api/bandi-rdp/", methods=["GET", "OPTIONS"])  # accetta anche lo slash finale
def api_bandi_rdp():
    if request.method == "OPTIONS":
        return ("", 204)

    # parametri (con default presi dal modulo se disponibili)
    filter_type = request.args.get("filterType", getattr(svc, "FILTER_TYPE", "all"))
    offset = int(request.args.get("offset", getattr(svc, "OFFSET", 20)))
    codice = (request.args.get("codice") or "").strip().lower()
    nocache = request.args.get("nocache")

    # cache keyed per parametri
    now = time.time()
    cache_key = (filter_type, offset, codice)
    if not nocache and CACHE_TTL > 0 and _cache.get("data") and _cache.get("key") == cache_key and (now - _cache.get("ts", 0)) < CACHE_TTL:
        return jsonify(_cache["data"])

    # fetch_calls compatibile con versioni che NON accettano parametri
    try:
        calls = svc.fetch_calls(offset=offset, filter_type=filter_type)
    except TypeError:
        calls = svc.fetch_calls()

    # filtro server-side opzionale
    if codice:
        calls = [c for c in calls if codice in str(c.get("codice", "")).lower()]

    # arricchimento
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


@app.route("/mobilita-urp.html")
def mobilita_urp_html():
    return send_from_directory(DIR, "mobilita-urp.html")


# -------- bootstrap --------

def main():
    # avvio sequenza iniziale su thread (per non bloccare il boot di Flask)
    t = threading.Thread(target=startup_sequence, daemon=True)
    t.start()
    bg_threads.append(t)
    # monitor opzionali
    kick_monitors()
    # avvio server Flask
    print(f"[INFO] Server Flask su http://localhost:{PORT}", flush=True)
    app.run(host="0.0.0.0", port=PORT, debug=False)

if __name__ == "__main__":
    main()
