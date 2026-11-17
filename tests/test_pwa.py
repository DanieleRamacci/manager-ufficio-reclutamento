"""App installabile (spec 009): file raggiungibili senza accesso, nessuna cache dei dati, pagina iniziale per ruolo."""
import json
from datetime import datetime, timedelta, timezone

from flask import Flask
from flask_session import Session

from monitoraggio import portale, pwa


def _client(tmp_path):
    app = Flask(__name__)
    app.config.update(SECRET_KEY="x", SESSION_TYPE="filesystem", SESSION_FILE_DIR=str(tmp_path / "s"))
    Session(app)
    app.register_blueprint(pwa.bp)
    return app.test_client()


def test_manifest_icone_e_service_worker_senza_accesso(tmp_path):
    c = _client(tmp_path)
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.mimetype == "application/manifest+json"
    manifest = json.loads(m.data)
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/app" and manifest["scope"] == "/"
    for icona in manifest["icons"]:
        r = c.get(icona["src"])
        assert r.status_code == 200 and r.mimetype == "image/png"
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and sw.mimetype == "text/javascript"
    assert sw.headers["Service-Worker-Allowed"] == "/" and "no-cache" in sw.headers["Cache-Control"]
    assert c.get("/pwa.js").status_code == 200 and c.get("/icona-apple.png").status_code == 200


def test_il_service_worker_non_salva_dati(tmp_path):
    testo = _client(tmp_path).get("/sw.js").get_data(as_text=True)
    assert "cache.put" not in testo and "caches.open" not in testo and "addAll" not in testo
    assert "Serve la connessione" in testo


def test_pagina_iniziale_dell_app_per_ruolo(tmp_path):
    c = _client(tmp_path)
    assert c.get("/app").headers["Location"] == "/"  # nessun accesso: la radice manda al login
    with c.session_transaction() as s:
        s["referente"] = "anna@cnr.it"
        s["referente_fino"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert c.get("/app").headers["Location"] == portale.PAGINA
    with c.session_transaction() as s:
        s["user"] = "mario.rossi"
        s["accesso_fino"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert c.get("/app").headers["Location"] == "/"
