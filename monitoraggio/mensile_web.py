"""Pagine e API del monitoraggio mensile e degli utenti (spec 006)."""
import io
import logging
import threading
from pathlib import Path

from flask import Blueprint, jsonify, redirect, request, send_file, send_from_directory, session

from . import atti, attivita, comunicazioni, config, db, difformita, excel_mese, impostazioni, mensile, portale, posta, punteggi, referenti, sol_sessione, utenti

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
    ultimo_candidati: dict[str, dict] = {}

    def _dati_mese(conn, m: dict, versione: int | None = None) -> dict:
        dal, al = mensile.periodo_dati(m)
        return {**m, "etichetta": mensile.etichetta(m["mese_dati"]), "etichetta_dati": mensile.etichetta(m["mese_dati"]),
                "dal": dal, "al": al, "link_vista": mensile.link_vista(m),
                "segnalazioni": portale.conteggi(conn, m["mese"]),
                "file_scorrimenti": excel_mese.nome_scorrimenti(m["mese_dati"]), "file_graduatorie": excel_mese.nome_graduatorie(m["mese_dati"]),
                "graduatorie_senza_elenco": excel_mese.graduatorie_senza_elenco(conn, dal, al),
                "email": mensile.email_compilazione(conn, m), "posta": posta.stato(),
                "solleciti": list(mensile.solleciti(conn, m["mese"]).values()), "invii": mensile.invii(conn, m["mese"]),
                "fotografia": mensile.fotografia(conn, m["mese"], versione), "id": mensile.id_monitoraggio(m),
                "titolo": comunicazioni.titolo_mese(m["mese_dati"]), "tipologie": mensile.tipologie_di(m),
                "allineamento": comunicazioni.allineamento(conn, m["mese_dati"]), "fonti_in_attesa": atti.fonti_in_attesa(conn)}

    def _fonti_non_pronte(conn):
        """Risposta 409 se SOL o URP non hanno concluso l'aggiornamento: niente invii, chiusure o verifiche."""
        attesa = atti.fonti_in_attesa(conn)
        return (jsonify({"error": atti.testo_attesa(attesa), "fonti_in_attesa": attesa}), 409) if attesa else None

    def _trova(conn, mese: str):
        return mensile.leggi(conn, mese) if mensile.mese_valido(mese) else None

    # --- pagine
    @bp.get("/monitoraggio/app.css")
    def foglio_stile():
        return send_from_directory(STATIC, "app.css")

    @bp.get("/monitoraggio/app.js")
    @protezione
    def script_comune():
        return send_from_directory(STATIC, "app.js")

    @bp.get("/monitoraggio/comunicazioni")
    @protezione
    def pagina_comunicazioni():
        return send_from_directory(STATIC, "comunicazioni.html")

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
        if "attiva" in corpo and not isinstance(corpo["attiva"], bool):
            return jsonify({"error": "Indica se la modalità di prova è attiva"}), 400
        try:
            if "attiva" in corpo:
                posta.salva_prova(corpo["attiva"], corpo.get("indirizzo"), utente_corrente())
            else:
                posta.salva_email(corpo, utente_corrente())
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
            return jsonify({"utenti": utenti.elenco(conn), "registro": utenti.registro(conn), "coordinatori": portale.elenco_coordinatori(conn),
                            "link_aree": {"utenti": f"{config.sito_url()}/login", "referenti": f"{config.sito_url()}{portale.PAGINA}",
                                          "referenti_attiva": posta.impostazioni_email()["portale_referenti"]}})
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

    @bp.post("/api/utenti/<nome>/vista")
    @protezione
    @solo_admin
    def api_vista_come(nome: str):
        """Anteprima del sito come un utente in lettura: valgono le sue regole, ma nessuna azione viene eseguita."""
        nome = utenti.normalizza(nome)
        if utenti.ruolo(nome) != utenti.LETTURA:
            return jsonify({"error": "L'anteprima serve per gli utenti in lettura: un amministratore vede quello che vedi tu"}), 400
        conn = _conn()
        try:
            utenti.traccia_anteprima(conn, nome, utente_corrente(), "anteprima")
        finally:
            conn.close()
        session["vista_come"] = nome
        return jsonify({"ok": True})

    @bp.post(utenti.ESCI_ANTEPRIMA)
    @protezione
    def api_vista_esci():
        session.pop("vista_come", None)
        return jsonify({"ok": True})

    @bp.post("/api/area-referenti/anteprima")
    @protezione
    @solo_admin
    def api_anteprima_area():
        """Anteprima dell'area referenti come un RdP o un coordinatore: vede i suoi bandi, non può segnalare né salvare."""
        email = str((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
        conn = _conn()
        try:
            if not email or not portale.puo_entrare(conn, email):
                return jsonify({"error": "Questo indirizzo non risulta tra i referenti attivi né tra i coordinatori"}), 404
            utenti.traccia_anteprima(conn, email, utente_corrente(), "anteprima_area")
        finally:
            conn.close()
        portale.avvia_anteprima(email)
        return jsonify({"ok": True, "url": portale.PAGINA})

    @bp.post("/api/coordinatori")
    @protezione
    @solo_admin
    def api_coordinatore_aggiungi():
        conn = _conn()
        try:
            return jsonify({"ok": True, "email": portale.aggiungi_coordinatore(conn, (request.get_json(silent=True) or {}).get("email"), utente_corrente())})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        finally:
            conn.close()

    @bp.delete("/api/coordinatori/<email>")
    @protezione
    @solo_admin
    def api_coordinatore_togli(email: str):
        conn = _conn()
        try:
            return jsonify({"ok": True}) if portale.togli_coordinatore(conn, email, utente_corrente()) else (jsonify({"error": "Coordinatore non trovato"}), 404)
        finally:
            conn.close()

    @bp.post("/api/coordinatori/<email>/invia-accesso")
    @protezione
    @solo_admin
    def api_coordinatore_invia(email: str):
        if not posta.impostazioni_email()["portale_referenti"]:
            return jsonify({"error": "Attiva prima l'area referenti in Impostazioni, altrimenti il link non funziona"}), 409
        conn = _conn()
        try:
            return jsonify({"ok": True}) if portale.invia_accesso_coordinatore(conn, email, utente_corrente()) else (jsonify({"error": "Coordinatore non trovato"}), 404)
        except posta.PostaErrore as e:
            return jsonify({"error": str(e)}), 502
        finally:
            conn.close()

    @bp.post("/api/utenti/<nome>/invia-accesso")
    @protezione
    @solo_admin
    def api_utenti_invia_accesso(nome: str):
        conn = _conn()
        try:
            email = utenti.invia_accesso(conn, nome, utente_corrente())
            return jsonify({"ok": True, "email": email}) if email else (jsonify({"error": "Utente non trovato"}), 404)
        except posta.PostaErrore as e:
            return jsonify({"error": str(e)}), 502
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
            voci = []
            for m in mensile.elenco(conn):
                completo = mensile.leggi(conn, m["mese"])
                voci.append({**m, "id": mensile.id_monitoraggio(m), "titolo": comunicazioni.titolo_mese(m["mese_dati"]),
                             "tipologie": mensile.tipologie_di(m), "conteggi": comunicazioni.conteggi(comunicazioni.righe_mese(conn, completo)),
                             "fonti_allineate": sum(f["allineata"] for f in comunicazioni.allineamento(conn, m["mese_dati"]))})
            return jsonify({"monitoraggi": voci, "fonti_in_attesa": atti.fonti_in_attesa(conn)})
        finally:
            conn.close()

    @bp.get("/api/monitoraggi/anteprima")
    @protezione
    @solo_admin
    def api_monitoraggi_anteprima():
        mese = request.args.get("mese")
        if not mensile.mese_valido(mese):
            return jsonify({"error": "Mese non valido"}), 400
        conn = _conn()
        try:
            return jsonify(comunicazioni.anteprima(conn, mese))
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
            riferimento = corpo.get("mese_riferimento")
            if riferimento:
                if not mensile.mese_valido(riferimento):
                    raise ValueError("Mese non valido")
                esistente = conn.execute("SELECT mese FROM monitoraggio_mese WHERE mese_dati = ?", (riferimento,)).fetchone()
                if esistente:
                    return jsonify({"ok": True, "mese": esistente["mese"], "creato": False})
                mese = mensile.mese_successivo(riferimento)
                m = mensile.crea(conn, mese, riferimento, utente_corrente(), corpo.get("tipologie"))
            else:
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
            bloccata = _fonti_non_pronte(conn)
            if bloccata:
                return bloccata
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
            bloccata = _fonti_non_pronte(conn)
            if bloccata:
                return bloccata
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

    # --- atti e comunicazioni del mese
    @bp.get("/api/monitoraggi/<mese>/atti")
    @protezione
    def api_monitoraggio_atti(mese: str):
        conn = _conn()
        try:
            m = _trova(conn, mese)
            if not m:
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            righe = comunicazioni.righe_mese(conn, m)
            difformita.registro_per_righe(conn, m["mese"], righe)
            return jsonify({"righe": righe, "conteggi": comunicazioni.conteggi(righe), "fonti_in_attesa": atti.fonti_in_attesa(conn)})
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/verifica-fonti")
    @protezione
    @solo_admin
    def api_verifica_fonti(mese: str):
        conn = _conn()
        try:
            m = _trova(conn, mese)
            if not m:
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            conn.execute("UPDATE monitoraggio_mese SET verifica_fonti_il = ? WHERE mese = ?", (mensile._adesso(), mese))
            return jsonify(_dati_mese(conn, mensile.leggi(conn, mese)))
        finally:
            conn.close()

    def _schede_atti(conn, m: dict) -> list[int]:
        return [r["scheda_sol_id"] for r in comunicazioni.righe_mese(conn, m) if r.get("scheda_sol_id")]

    def _stato_candidati(conn, m: dict, **extra) -> dict:
        schede = _schede_atti(conn, m)
        return {"in_corso": punteggi.in_corso(), **punteggi.avanzamento(), "atti": len(schede),
                "con_elenco": sum(1 for s in schede if punteggi.candidati(s) is not None),
                "ultimo": ultimo_candidati.get(m["mese"]), **extra}

    @bp.get("/api/monitoraggi/<mese>/candidati")
    @protezione
    def api_candidati_stato(mese: str):
        conn = _conn()
        try:
            m = _trova(conn, mese)
            return jsonify(_stato_candidati(conn, m)) if m else (jsonify({"error": "Monitoraggio non trovato"}), 404)
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/candidati")
    @protezione
    @solo_admin
    def api_candidati_carica(mese: str):
        """Legge da SOL gli elenchi che mancano per gli atti del mese. Restano solo in memoria (constitution, Principio II)."""
        conn = _conn()
        try:
            m = _trova(conn, mese)
            if not m:
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            dal, al = mensile.periodo_dati(m)
            ids = {*_schede_atti(conn, m), *(s["id"] for s in excel_mese.graduatorie_periodo(conn, dal, al))}
            mancanti = [i for i in ids if punteggi.candidati(i) is None]
            if punteggi.in_corso() or not mancanti:
                return jsonify(_stato_candidati(conn, m))
            intestazioni = intestazioni_sol() or None
            if not intestazioni:
                return jsonify({"error": "Per vedere i candidati collega prima Selezioni Online con Collega-SOL"}), 401
            segnaposti = ", ".join("?" * len(mancanti))
            schede = conn.execute(f"SELECT * FROM scheda WHERE id IN ({segnaposti})", mancanti).fetchall()

            def lavoro():
                c = _conn()
                try:
                    r = punteggi.verifica_schede(c, schede, dal, al, intestazioni)
                    ultimo_candidati[mese] = {k: r.get(k) for k in ("esito", "messaggio", "errore")}
                except punteggi.VerificaInCorso:
                    pass
                except Exception as e:
                    logging.getLogger(__name__).exception("Caricamento dei candidati non riuscito")
                    ultimo_candidati[mese] = {"esito": "fallita", "messaggio": f"Caricamento non riuscito ({type(e).__name__})"}
                finally:
                    c.close()
                difformita.sincronizza_tutti("verifica dei punteggi")
            threading.Thread(target=lavoro, daemon=True, name="candidati-mese").start()
            return jsonify(_stato_candidati(conn, m, avviata=True)), 202
        finally:
            conn.close()

    @bp.get("/api/monitoraggi/<mese>/comunicazioni/<path:codice>/messaggio")
    @protezione
    def api_messaggio(mese: str, codice: str):
        conn = _conn()
        try:
            m = _trova(conn, mese)
            messaggio = comunicazioni.messaggio(conn, m, codice, sollecito=request.args.get("sollecito") == "1") if m else None
            return jsonify({**messaggio, "id_monitoraggio": mensile.id_monitoraggio(m), "chiuso": m["stato"] == "chiuso"}) if messaggio \
                else (jsonify({"error": "Comunicazione non trovata"}), 404)
        finally:
            conn.close()

    @bp.put("/api/monitoraggi/<mese>/comunicazioni/<path:codice>/indirizzi")
    @protezione
    @solo_admin
    def api_messaggio_indirizzi(mese: str, codice: str):
        """Referenti tolti e persone aggiunte in copia per questo messaggio: valgono anche per «Invia tutte»."""
        conn = _conn()
        try:
            m = _trova(conn, mese)
            if not m:
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            mensile.verifica_aperto(conn, mese)
            righe = comunicazioni.righe_mese(conn, m)
            if not any(r["chiave"] == codice for r in righe):
                return jsonify({"error": "Comunicazione non trovata"}), 404
            mensile.salva_indirizzi_messaggio(conn, mese, codice, request.get_json(silent=True) or {}, utente_corrente())
            return jsonify({**comunicazioni.messaggio(conn, m, codice, righe), "id_monitoraggio": mensile.id_monitoraggio(m), "chiuso": False})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    def _invia_messaggio(conn, m: dict, codice: str, modo: str, oggetto: str | None = None, corpo: str | None = None, conferma: bool = False,
                         righe: list[dict] | None = None, sollecito: bool = False):
        messaggio = comunicazioni.messaggio(conn, m, codice, righe, sollecito=sollecito)
        if not messaggio:
            return {"error": "Comunicazione non trovata"}, 404
        if not messaggio["n_difformita"]:
            return {"error": "Nessuna difformità da comunicare per questo bando"}, 400
        oggetto, testo = (oggetto or messaggio["oggetto"]).strip(), corpo or messaggio["corpo"]
        if comunicazioni.contiene_dati_candidati(oggetto, testo):
            return {"error": "Il testo sembra contenere un codice fiscale: invio bloccato"}, 400
        if not messaggio["destinatari"]:
            return {"error": "Tutti i referenti sono stati tolti da questa email: rimettine almeno uno" if messaggio["referenti"]
                    else "Nessuna email RdP disponibile per questo bando"}, 400
        if sollecito and messaggio["stato"] not in ("inviata", "inviata_a_mano", "da_confermare"):
            return {"error": "Si può sollecitare solo una comunicazione già inviata"}, 400
        if modo == "ufficiale" and messaggio["stato"] in ("inviata", "inviata_a_mano") and not conferma and not sollecito:
            return {"error": "Comunicazione già inviata", "gia_inviata": True}, 409
        try:
            message_id = posta.nuovo_message_id()
            prova = posta.invia(messaggio["destinatari"], oggetto, testo, modo=modo, cc=messaggio["cc_aggiunti"], message_id=message_id,
                                in_risposta_a=messaggio["message_id_precedente"] if sollecito else None)
        except posta.PostaErrore as e:
            mensile.registra_invio(conn, "sollecito", m["mese"], codice, utente_corrente(), messaggio["destinatari"], oggetto, "errore", str(e))
            return {"error": str(e)}, 502
        mensile.registra_invio(conn, "sollecito", m["mese"], codice, utente_corrente(), messaggio["destinatari"], oggetto, "prova" if prova else "inviata")
        id_c = mensile.registra_comunicazione(conn, m["mese"], codice, messaggio["numero_bando"], "Email di prova" if prova else "Casella ufficio",
                                              "prova" if prova else "inviata", utente_corrente(), messaggio["destinatari"],
                                              f"[PROVA] {oggetto}" if prova else oggetto, testo, messaggio["n_difformita"], messaggio["cc"], message_id)
        return {"ok": True, "prova": prova, "id": id_c}, 200

    @bp.post("/api/monitoraggi/<mese>/comunicazioni/<path:codice>/invia")
    @protezione
    @solo_admin
    def api_messaggio_invia(mese: str, codice: str):
        corpo = request.get_json(silent=True) or {}
        modo = corpo.get("modo")
        if modo not in ("prova", "ufficiale"):
            return jsonify({"error": "Indica se è una prova o un invio ufficiale"}), 400
        conn = _conn()
        try:
            bloccata = _fonti_non_pronte(conn)
            if bloccata:
                return bloccata
            m = _trova(conn, mese)
            if not m:
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            mensile.verifica_aperto(conn, mese)
            esito, codice_http = _invia_messaggio(conn, m, codice, modo, corpo.get("oggetto"), corpo.get("corpo"), bool(corpo.get("conferma")), sollecito=bool(corpo.get("sollecito")))
            return jsonify(esito), codice_http
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/comunicazioni/<path:codice>/traccia")
    @protezione
    @solo_admin
    def api_messaggio_traccia(mese: str, codice: str):
        corpo = request.get_json(silent=True) or {}
        if corpo.get("canale") not in ("Copia manuale", "Client email"):
            return jsonify({"error": "Canale non valido"}), 400
        conn = _conn()
        try:
            m = _trova(conn, mese)
            messaggio = comunicazioni.messaggio(conn, m, codice) if m else None
            if not messaggio:
                return jsonify({"error": "Comunicazione non trovata"}), 404
            mensile.verifica_aperto(conn, mese)
            id_c = mensile.registra_comunicazione(conn, mese, codice, messaggio["numero_bando"], corpo["canale"], "da confermare", utente_corrente(),
                                                  messaggio["destinatari"], corpo.get("oggetto") or messaggio["oggetto"],
                                                  corpo.get("corpo") or messaggio["corpo"], messaggio["n_difformita"], messaggio["cc"])
            return jsonify({"ok": True, "id": id_c})
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    @bp.get("/api/monitoraggi/<mese>/segnalazioni")
    @protezione
    def api_segnalazioni(mese: str):
        conn = _conn()
        try:
            return jsonify({"segnalazioni": portale.elenco(conn, mese)}) if _trova(conn, mese) else (jsonify({"error": "Monitoraggio non trovato"}), 404)
        finally:
            conn.close()

    @bp.put("/api/monitoraggi/<mese>/segnalazioni/<int:id_segnalazione>")
    @protezione
    @solo_admin
    def api_segnalazione_gestita(mese: str, id_segnalazione: int):
        conn = _conn()
        try:
            mensile.verifica_aperto(conn, mese)
            if not portale.imposta_gestita(conn, mese, id_segnalazione, bool((request.get_json(silent=True) or {}).get("gestita")), utente_corrente()):
                return jsonify({"error": "Segnalazione non trovata"}), 404
            return jsonify({"ok": True})
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    @bp.post("/api/monitoraggi/<mese>/comunicazioni-invia-tutti")
    @protezione
    @solo_admin
    def api_messaggi_invia_tutti(mese: str):
        conn = _conn()
        try:
            bloccata = _fonti_non_pronte(conn)
            if bloccata:
                return bloccata
            m = _trova(conn, mese)
            if not m:
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            mensile.verifica_aperto(conn, mese)
            if not posta.impostazioni_email()["ufficiali_attive"]:
                return jsonify({"error": "Le email ufficiali sono disattivate"}), 409
            righe = comunicazioni.righe_mese(conn, m)
            codici = list(dict.fromkeys(r["chiave"] for r in righe if r["con_difformita"] and r["comunicazione"]["stato"] == "da_inviare"))
            inviate, errori = 0, []
            for codice in codici:
                esito, codice_http = _invia_messaggio(conn, m, codice, "ufficiale", righe=righe)
                if codice_http == 200:
                    inviate += 1
                else:
                    errori.append({"codice": codice, "errore": esito.get("error")})
            return jsonify({"ok": not errori, "inviate": inviate, "errori": errori})
        except mensile.MeseChiuso as e:
            return jsonify({"error": str(e)}), 409
        finally:
            conn.close()

    @bp.get("/api/comunicazioni")
    @protezione
    def api_registro_comunicazioni():
        conn = _conn()
        try:
            mese = request.args.get("mese") or None
            return jsonify({"comunicazioni": mensile.registro_comunicazioni(conn, mese), "posta": posta.stato(),
                            "monitoraggi": [{"mese": x["mese"], "id": mensile.id_monitoraggio(x)} for x in mensile.elenco(conn)]})
        finally:
            conn.close()

    # --- attività notturne
    @bp.get("/api/impostazioni/attivita")
    @protezione
    @solo_admin
    def api_attivita():
        solo_problemi = request.args.get("problemi") == "1"
        return jsonify({"attivita": attivita.elenco(), "prossima": attivita.prossima_esecuzione(),
                        "storico": attivita.storico(request.args.get("attivita") or None, solo_problemi),
                        **{k: v for k, v in impostazioni.stato_aggiornamenti().items()
                           if k in ("giorno_completa", "giorni", "avviso_modo", "avviso_indirizzo", "ultimo_completo", "pdf_da_controllare")}})

    @bp.put("/api/impostazioni/attivita/<chiave>")
    @protezione
    @solo_admin
    def api_attivita_salva(chiave: str):
        corpo = request.get_json(silent=True) or {}
        try:
            attivita.salva(chiave, corpo.get("orario"), corpo.get("attiva"))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True, "attivita": attivita.elenco(), "prossima": attivita.prossima_esecuzione()})

    @bp.post("/api/impostazioni/attivita/<chiave>/esegui")
    @protezione
    @solo_admin
    def api_attivita_esegui(chiave: str):
        if chiave not in attivita.ATTIVITA:
            return jsonify({"error": "Attività sconosciuta"}), 404
        token = intestazioni_sol() or None if chiave == "referenti" else None
        if chiave == "referenti" and not token and not referenti.senza_token_ammesso():
            return jsonify({"error": "Per leggere i referenti collega prima Selezioni Online con Collega-SOL: "
                                     "dopo un riavvio del server il collegamento va rifatto"}), 401
        if not attivita.esegui(chiave, utente_corrente() or "manuale", token, "manuale" if chiave in ("sol", "urp") else None):
            return jsonify({"error": "Attività già in corso"}), 409
        return jsonify({"ok": True}), 202

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
            bloccata = _fonti_non_pronte(conn)
            if bloccata:
                return bloccata
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
                contenuto, nome = excel_mese.excel_scorrimenti(), excel_mese.nome_scorrimenti(m["mese_dati"])
            elif tipo == "graduatorie":
                contenuto, nome = excel_mese.excel_graduatorie_vuoto(), excel_mese.nome_graduatorie(m["mese_dati"])
            else:
                contenuto, nome = excel_mese.excel_graduatorie(conn, *mensile.periodo_dati(m)), excel_mese.nome_graduatorie(m["mese_dati"])
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

    def _invia(conn, tipo, mese, numero_bando, destinatari, oggetto, corpo, cc=None):
        try:
            prova = posta.invia(destinatari, oggetto, corpo, cc=cc)
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
            return jsonify({"etichetta": mensile.etichetta(m["mese_dati"]), "etichetta_dati": mensile.etichetta(m["mese_dati"]),
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
            bloccata = _fonti_non_pronte(conn)
            if bloccata:
                return bloccata
            if not _trova(conn, mese):
                return jsonify({"error": "Monitoraggio non trovato"}), 404
            mensile.verifica_aperto(conn, mese)
            if not numero or not oggetto or not testo.strip():
                return jsonify({"error": "Bando, oggetto e testo sono obbligatori"}), 400
            scelte = mensile.indirizzi_messaggio(conn, mese, numero)  # chi è stato tolto dal messaggio non lo riceve neanche da qui
            destinatari = [d for d in destinatari if d not in scelte["esclusi"]]
            if not destinatari:
                return jsonify({"error": "Nessuna email RdP disponibile per questo bando"}), 400
            estranei = sorted(set(destinatari) - mensile.email_rdp(conn, numero))
            if estranei:
                return jsonify({"error": "Non sono RdP di questo bando: " + ", ".join(estranei)}), 400
            if mensile.contiene_dati_candidati(testo) or mensile.contiene_dati_candidati(oggetto):
                return jsonify({"error": "Il testo sembra contenere un codice fiscale: invio bloccato"}), 400
            if numero in mensile.solleciti(conn, mese) and not corpo.get("conferma"):
                return jsonify({"error": "Sollecito già segnato come inviato", "gia_inviato": True}), 409
            return _invia(conn, "sollecito", mese, numero, destinatari, oggetto, testo, cc=scelte["cc"])
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
