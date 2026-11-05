"""Pagine e API del monitoraggio mensile e degli utenti (spec 006)."""
import io
from pathlib import Path

from flask import Blueprint, jsonify, redirect, request, send_file, send_from_directory

from . import db, difformita, excel_mese, impostazioni, mensile, posta, sol_sessione, utenti

STATIC = Path(__file__).resolve().parent / "static"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _conn():
    conn = db.connetti()
    db.inizializza(conn)
    return conn


def crea_blueprint_mensile(protezione=lambda f: f, solo_admin=lambda f: f, utente_corrente=lambda: None,
                           intestazioni_sol=sol_sessione.intestazioni) -> Blueprint:
    """`intestazioni_sol()`: header per leggere i punteggi su SOL con l'accesso dell'utente, o vuoto se non è collegato."""
    bp = Blueprint("mensile", __name__)

    def _dati_mese(conn, m: dict, versione: int | None = None) -> dict:
        dal, al = mensile.periodo_dati(m)
        return {**m, "etichetta": mensile.etichetta(m["mese"]), "etichetta_dati": mensile.etichetta(m["mese_dati"]),
                "dal": dal, "al": al, "link_vista": mensile.link_vista(m),
                "file_scorrimenti": excel_mese.nome_scorrimenti(m["mese"]), "file_graduatorie": excel_mese.nome_graduatorie(m["mese"]),
                "graduatorie_senza_elenco": excel_mese.graduatorie_senza_elenco(conn, dal, al),
                "email": mensile.email_compilazione(conn, m), "posta": posta.stato(),
                "solleciti": list(mensile.solleciti(conn, m["mese"]).values()), "invii": mensile.invii(conn, m["mese"]),
                "fotografia": mensile.fotografia(conn, m["mese"], versione)}

    def _trova(conn, mese: str):
        return mensile.leggi(conn, mese) if mensile.mese_valido(mese) else None

    # --- pagine
    @bp.get("/monitoraggio/mensile.css")
    @protezione
    def foglio_stile():
        return send_from_directory(STATIC, "mensile.css")

    @bp.get("/monitoraggio/mensili")
    @bp.get("/monitoraggio/mensili/<mese>")
    @protezione
    def pagina_mensili(mese=None):
        return send_from_directory(STATIC, "monitoraggi.html")

    @bp.get("/monitoraggio/impostazioni")
    @protezione
    @solo_admin
    def pagina_impostazioni():
        return send_from_directory(STATIC, "impostazioni.html")

    @bp.get("/api/impostazioni/posta")
    @protezione
    @solo_admin
    def api_impostazioni_posta():
        return jsonify({**posta.stato(), "prova_impostazioni": posta.impostazioni_prova()})

    @bp.put("/api/impostazioni/posta")
    @protezione
    @solo_admin
    def api_impostazioni_posta_salva():
        corpo = request.get_json(silent=True) or {}
        if not isinstance(corpo.get("attiva"), bool):
            return jsonify({"error": "Indica se la modalità di prova è attiva"}), 400
        try:
            posta.salva_prova(corpo["attiva"], corpo.get("indirizzo"), utente_corrente())
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({**posta.stato(), "prova_impostazioni": posta.impostazioni_prova()})

    @bp.get("/api/impostazioni/aggiornamenti")
    @protezione
    @solo_admin
    def api_impostazioni_aggiornamenti():
        return jsonify(impostazioni.stato_aggiornamenti())

    @bp.put("/api/impostazioni/aggiornamenti")
    @protezione
    @solo_admin
    def api_impostazioni_aggiornamenti_salva():
        try:
            impostazioni.salva_aggiornamenti(request.get_json(silent=True) or {}, utente_corrente())
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(impostazioni.stato_aggiornamenti())

    @bp.get("/monitoraggio/utenti")
    @protezione
    @solo_admin
    def pagina_utenti():
        return redirect("/monitoraggio/impostazioni#utenti")

    # --- utenti
    @bp.get("/api/utenti")
    @protezione
    @solo_admin
    def api_utenti():
        conn = _conn()
        try:
            return jsonify({"utenti": utenti.elenco(conn), "registro": utenti.registro(conn)})
        finally:
            conn.close()

    @bp.post("/api/utenti")
    @protezione
    @solo_admin
    def api_utenti_imposta():
        corpo = request.get_json(silent=True) or {}
        conn = _conn()
        try:
            nome = utenti.imposta(conn, corpo.get("username"), corpo.get("ruolo"), utente_corrente(), corpo.get("email"))
            return jsonify({"ok": True, "username": nome})
        except utenti.UtenteProtetto as e:
            return jsonify({"error": str(e)}), 409
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @bp.delete("/api/utenti/<nome>")
    @protezione
    @solo_admin
    def api_utenti_togli(nome: str):
        conn = _conn()
        try:
            if not utenti.togli(conn, nome, utente_corrente()):
                return jsonify({"error": "Utente non trovato"}), 404
            return jsonify({"ok": True})
        except utenti.UtenteProtetto as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    # --- monitoraggi
    @bp.get("/api/monitoraggi")
    @protezione
    def api_monitoraggi():
        conn = _conn()
        try:
            return jsonify({"monitoraggi": mensile.elenco(conn)})
        finally:
            conn.close()

    @bp.post("/api/monitoraggi")
    @protezione
    @solo_admin
    def api_monitoraggi_crea():
        corpo = request.get_json(silent=True) or {}
        conn = _conn()
        mese = None
        try:
            mese = mensile.mese_anno_corrente(corpo.get("numero_mese"))
            m = mensile.crea(conn, mese, corpo.get("mese_dati"), utente_corrente())
            difformita.sincronizza(conn, mese, "creazione del monitoraggio", utente_corrente())
            return jsonify({"ok": True, "mese": m["mese"], "creato": True}), 201
        except mensile.MeseEsistente:
            return jsonify({"ok": True, "mese": mese, "creato": False})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @bp.get("/api/monitoraggi/<mese>")
    @protezione
    def api_monitoraggio(mese: str):
        conn = _conn()
        try:
            m = _trova(conn, mese)
            versione = request.args.get("versione", type=int)
            return jsonify(_dati_mese(conn, m, versione)) if m else (jsonify({"error": "Monitoraggio non trovato"}), 404)
        finally:
            conn.close()

    @bp.put("/api/monitoraggi/<mese>")
    @protezione
    @solo_admin
    def api_monitoraggio_aggiorna(mese: str):
        conn = _conn()
        try:
            if not _trova(conn, mese):
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            mensile.verifica_aperto(conn, mese)
            corpo = request.get_json(silent=True) or {}
            cambia_periodo = "mese_dati" in corpo and corpo["mese_dati"] != _trova(conn, mese)["mese_dati"]
            m = mensile.aggiorna(conn, mese, corpo)
            if cambia_periodo:
                difformita.reimposta(conn, mese)
                difformita.sincronizza(conn, mese, "cambio del mese dei dati", utente_corrente())
            return jsonify(_dati_mese(conn, m))
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/chiudi")
    @protezione
    @solo_admin
    def api_monitoraggio_chiudi(mese: str):
        conn = _conn()
        try:
            if not _trova(conn, mese):
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            return jsonify(_dati_mese(conn, mensile.chiudi(conn, mese, utente_corrente())))
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/nuova-versione")
    @protezione
    @solo_admin
    def api_monitoraggio_nuova_versione(mese: str):
        conn = _conn()
        try:
            if not _trova(conn, mese):
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            motivo = (request.get_json(silent=True) or {}).get("motivo")
            return jsonify(_dati_mese(conn, mensile.nuova_versione(conn, mese, utente_corrente(), motivo)))
        except mensile.MeseAperto as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/riapri")
    @protezione
    @solo_admin
    def api_monitoraggio_riapri(mese: str):
        conn = _conn()
        try:
            if not _trova(conn, mese):
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            return jsonify(_dati_mese(conn, mensile.riapri(conn, mese, utente_corrente())))
        finally:
            conn.close()

    # --- registro delle difformità
    @bp.get("/api/monitoraggi/<mese>/difformita")
    @protezione
    def api_difformita(mese: str):
        conn = _conn()
        try:
            if not _trova(conn, mese):
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            return jsonify(difformita.elenco(conn, mese))
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/difformita/verifica")
    @protezione
    @solo_admin
    def api_difformita_verifica(mese: str):
        corpo = request.get_json(silent=True) or {}
        ids = corpo.get("ids")
        if ids is not None and not (isinstance(ids, list) and all(isinstance(i, int) for i in ids)):
            return jsonify({"error": "Difformità non valide"}), 400
        conn = _conn()
        try:
            if not _trova(conn, mese):
                return jsonify({"error": "Monitoraggio non trovato"}), 404
        finally:
            conn.close()
        if not difformita.avvia_verifica(mese, ids, intestazioni_sol() or None, utente_corrente()):
            return jsonify({"error": "Una verifica è già in corso"}), 409
        return jsonify({"ok": True, "verifica": difformita.stato_verifica()}), 202

    @bp.get("/api/monitoraggi/<mese>/excel/<tipo>")
    @protezione
    @solo_admin
    def api_monitoraggio_excel(mese: str, tipo: str):
        conn = _conn()
        try:
            m = _trova(conn, mese)
            if not m or tipo not in ("scorrimenti", "graduatorie", "graduatorie-con-dati"):
                return jsonify({"error": "File non trovato"}), 404
            if tipo == "scorrimenti":
                contenuto, nome = excel_mese.excel_scorrimenti(), excel_mese.nome_scorrimenti(mese)
            elif tipo == "graduatorie":
                contenuto, nome = excel_mese.excel_graduatorie_vuoto(), excel_mese.nome_graduatorie(mese)
            else:
                contenuto, nome = excel_mese.excel_graduatorie(conn, *mensile.periodo_dati(m)), excel_mese.nome_graduatorie(mese)
        finally:
            conn.close()
        risposta = send_file(io.BytesIO(contenuto), mimetype=XLSX, as_attachment=True, download_name=nome)
        risposta.headers["Cache-Control"] = "no-store"  # può contenere dati personali dei candidati
        return risposta

    # --- email di richiesta
    @bp.get("/api/impostazioni/email")
    @protezione
    @solo_admin
    def api_impostazioni_email():
        conn = _conn()
        try:
            return jsonify(mensile.impostazioni_email(conn))
        finally:
            conn.close()

    @bp.put("/api/impostazioni/email")
    @protezione
    @solo_admin
    def api_impostazioni_email_salva():
        conn = _conn()
        try:
            return jsonify(mensile.salva_impostazioni_email(conn, request.get_json(silent=True) or {}, utente_corrente()))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/email-compilazione/invia")
    @protezione
    @solo_admin
    def api_invia_compilazione(mese: str):
        conn = _conn()
        try:
            m = _trova(conn, mese)
            if not m:
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            mensile.verifica_aperto(conn, mese)
            email = mensile.email_compilazione(conn, m)
            if email["mancanti"]:
                return jsonify({"error": "Manca: " + ", ".join(email["mancanti"])}), 400
            return _invia(conn, "compilazione", mese, None, email["destinatari"], email["oggetto"], email["corpo"])
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    def _invia(conn, tipo, mese, numero_bando, destinatari, oggetto, corpo):
        try:
            prova = posta.invia(destinatari, oggetto, corpo)
        except posta.PostaErrore as e:
            mensile.registra_invio(conn, tipo, mese, numero_bando, utente_corrente(), destinatari, oggetto, "errore", str(e))
            return jsonify({"error": str(e)}), 502
        mensile.registra_invio(conn, tipo, mese, numero_bando, utente_corrente(), destinatari, oggetto, "prova" if prova else "inviata")
        if tipo == "sollecito" and not prova:
            mensile.segna(conn, mese, numero_bando, "inviata", utente_corrente(), destinatari, oggetto)
        return jsonify({"ok": True, "prova": prova})

    # --- solleciti per bando
    @bp.get("/api/monitoraggi/<mese>/solleciti")
    @protezione
    def api_solleciti(mese: str):
        conn = _conn()
        try:
            m = _trova(conn, mese)
            if not m:
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            return jsonify({"etichetta": mensile.etichetta(mese), "etichetta_dati": mensile.etichetta(m["mese_dati"]),
                            "stato": m["stato"], "mese_dati": m["mese_dati"], "solleciti": mensile.solleciti(conn, mese), "posta": posta.stato()})
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/solleciti/invia")
    @protezione
    @solo_admin
    def api_sollecito_invia(mese: str):
        corpo = request.get_json(silent=True) or {}
        numero = str(corpo.get("numero_bando") or "").strip()
        oggetto, testo = str(corpo.get("oggetto") or "").strip(), str(corpo.get("corpo") or "")
        destinatari = mensile.dividi_indirizzi(corpo.get("destinatari") or [])
        conn = _conn()
        try:
            if not _trova(conn, mese):
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            mensile.verifica_aperto(conn, mese)
            if not numero or not oggetto or not testo.strip():
                return jsonify({"error": "Bando, oggetto e testo sono obbligatori"}), 400
            if not destinatari:
                return jsonify({"error": "Nessuna email RdP disponibile per questo bando"}), 400
            estranei = sorted(set(destinatari) - mensile.email_rdp(conn, numero))
            if estranei:
                return jsonify({"error": "Non sono RdP di questo bando: " + ", ".join(estranei)}), 400
            if mensile.contiene_dati_candidati(testo) or mensile.contiene_dati_candidati(oggetto):
                return jsonify({"error": "Il testo sembra contenere un codice fiscale: invio bloccato"}), 400
            if numero in mensile.solleciti(conn, mese) and not corpo.get("conferma"):
                return jsonify({"error": "Sollecito già segnato come inviato", "gia_inviato": True}), 409
            return _invia(conn, "sollecito", mese, numero, destinatari, oggetto, testo)
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    @bp.put("/api/monitoraggi/<mese>/solleciti/<path:numero>")
    @protezione
    @solo_admin
    def api_sollecito_spunta(mese: str, numero: str):
        inviata = bool((request.get_json(silent=True) or {}).get("inviata"))
        conn = _conn()
        try:
            if not _trova(conn, mese):
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            mensile.verifica_aperto(conn, mese)
            if inviata:
                mensile.segna(conn, mese, numero, "inviata_a_mano", utente_corrente())
            else:
                mensile.togli_segno(conn, mese, numero)
            return jsonify({"ok": True, "solleciti": mensile.solleciti(conn, mese)})
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    return bp
