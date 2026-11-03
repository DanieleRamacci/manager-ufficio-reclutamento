"""Comando da terminale (contracts/api.md, "Comando da terminale").

    python -m monitoraggio raccogli [--fonte urp|sol|tutte] [--completa]
    python -m monitoraggio importa-json [--cartella PERCORSO]
    python -m monitoraggio stato
    python -m monitoraggio web [--porta 8090]     # solo prova locale, su 127.0.0.1, senza login
"""
import argparse
import logging
import sys

from . import collegamento, config, db
from .raccolta import RaccoltaInCorso, errori, raccogli, stato

USCITA = {"completata": 0, "completata_con_errori": 1, "fallita": 2}


def _stampa_riepilogo(r: dict) -> None:
    print(f"[{r['fonte'].upper()}] esito={r['esito']} bandi={r['bandi_trovati']} "
          f"documenti={r['documenti_trovati']} nuovi={r['nuovi']} aggiornati={r['aggiornati']} "
          f"errori={r['errori']} inizio={r['inizio']} fine={r['fine']}")
    if r.get("totale_dichiarato"):
        print(f"    totali dichiarati dalla fonte: {r['totale_dichiarato']}")
    if r.get("messaggio"):
        print(f"    messaggio: {r['messaggio']}")


def cmd_raccogli(args) -> int:
    conn = db.connetti()
    db.inizializza(conn)
    fonti = ["urp", "sol"] if args.fonte == "tutte" else [args.fonte]
    codice = 0
    for fonte in fonti:
        try:
            r = raccogli(conn, fonte, modalita="completa" if args.completa else "manuale", avviata_da="cli",
                         dopo_scrittura=lambda c, f: collegamento.collega(c))
        except RaccoltaInCorso as e:
            print(e)
            codice = max(codice, 2)
            continue
        _stampa_riepilogo(r)
        codice = max(codice, USCITA[r["esito"]])
    return codice


def cmd_riclassifica(args) -> int:
    from .raccolta import riclassifica

    conn = db.connetti()
    db.inizializza(conn)
    print(f"Documenti riclassificati: {riclassifica(conn)}")
    return 0


def cmd_stato(args) -> int:
    conn = db.connetti()
    db.inizializza(conn)
    for fonte, s in stato(conn).items():
        if s["in_corso"]:
            print(f"[{fonte.upper()}] raccolta in corso dal {s['in_corso']['inizio']}")
        if not s["ultima"]:
            print(f"[{fonte.upper()}] nessuna raccolta eseguita")
            continue
        _stampa_riepilogo(s["ultima"])
        for e in errori(conn, s["ultima"]["id"])[:20]:
            print(f"    errore: {e['riferimento']}: {e['messaggio']}")
        if s["ultima_riuscita"] and s["ultima_riuscita"]["id"] != s["ultima"]["id"]:
            print(f"    ultima riuscita: {s['ultima_riuscita']['fine']}")
    righe = conn.execute("SELECT stato_collegamento, COUNT(*) FROM bando WHERE stato_collegamento IS NOT NULL "
                         "GROUP BY 1").fetchall()
    if righe:
        print("Bandi per stato di collegamento: " + ", ".join(f"{r[0]}={r[1]}" for r in righe))
    return 0


def _login_sso(app):
    """Login SSO nel server locale, se configurato in .env (spec 003, FR-010).

    Ritorna (token_utente, utente_corrente, login_url, logout_url) oppure None.
    """
    import os
    import secrets

    from dotenv import load_dotenv

    load_dotenv()
    if not (os.environ.get("OIDC_CLIENT_SECRET") and os.environ.get("OIDC_REDIRECT_URI")):
        return None
    from flask import session
    from flask_session import Session

    import auth  # auth.py del progetto: lo stesso login dell'app completa

    cartella = config.data_dir() / "flask_session"
    cartella.mkdir(parents=True, exist_ok=True)
    app.config.update(SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
                      SESSION_TYPE="filesystem", SESSION_FILE_DIR=str(cartella), SESSION_PERMANENT=False)
    Session(app)
    app.register_blueprint(auth.auth_bp)
    return auth.token_valido, lambda: session.get("user_email"), "/login?next=/monitoraggio", "/logout"


def cmd_web(args) -> int:
    from flask import Flask, redirect

    from .web import PAGINE_LOCALI, crea_blueprint, crea_blueprint_pagine_esistenti

    app = Flask(__name__)
    sso = _login_sso(app)
    if sso:
        token_utente, utente, login_url, logout_url = sso
        print("Login SSO attivo (Keycloak di Selezioni Online): per i referenti usa 'Accedi' nel menu")
    else:
        token_utente, utente, login_url, logout_url = (lambda: None), (lambda: "locale"), None, None
        print("Login SSO non configurato: i referenti RdP non si possono aggiornare (vedi specs/003-referenti-rdp/quickstart.md)")
    app.register_blueprint(crea_blueprint(utente_corrente=utente, pagine_disponibili=PAGINE_LOCALI,
                                          token_utente=token_utente, login_url=login_url, logout_url=logout_url,
                                          login_sol=True))
    app.register_blueprint(crea_blueprint_pagine_esistenti())
    app.add_url_rule("/", "root", lambda: redirect("/monitoraggio"))  # "root": usato da auth.py dopo il login
    conn = db.connetti()
    db.inizializza(conn)
    collegamento.collega(conn)  # allinea i bandi se le raccolte sono state fatte prima del collegamento
    conn.close()
    print(f"Prova locale senza login: http://127.0.0.1:{args.porta}/monitoraggio (Ctrl+C per uscire)")
    app.run(host="127.0.0.1", port=args.porta, debug=False)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m monitoraggio", description="Monitoraggio bandi CNR")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("raccogli", help="raccoglie i dati da URP e/o Selezioni Online")
    p.add_argument("--fonte", choices=["urp", "sol", "tutte"], default="tutte")
    p.add_argument("--completa", action="store_true", help="rilegge gli allegati di tutti i bandi SOL")
    p.set_defaults(func=cmd_raccogli)

    p = sub.add_parser("importa-json", help="importa una volta i file JSON storici")
    p.add_argument("--cartella", default=".")
    p.set_defaults(func=lambda a: print("Non ancora disponibile (T033)") or 2)

    p = sub.add_parser("stato", help="mostra lo stato delle raccolte")
    p.set_defaults(func=cmd_stato)

    p = sub.add_parser("riclassifica", help="riapplica le regole di classificazione ai documenti salvati")
    p.set_defaults(func=cmd_riclassifica)

    p = sub.add_parser("web", help="pagina di riepilogo in locale (127.0.0.1, senza login)")
    p.add_argument("--porta", type=int, default=8090)
    p.set_defaults(func=cmd_web)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
