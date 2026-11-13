---

description: "Task list per i referenti RdP"
---

# Tasks: Referenti RdP dei bandi da Selezioni Online

**Tests**: richiesti dalla constitution; risposte SOL simulate con persone inventate.

## Phase 1: Fondamenta

- [X] T001 Schema versione 3: tabelle `referente` (scheda_id, nome, cognome, email, username, attivo, prima_rilevazione, ultima_rilevazione, unique scheda_id+chiave persona) e `referenti_aggiornamento` (utente, inizio, fine, esito `in_corso`/`completato`/`fallito`, bandi, referenti, messaggio) in monitoraggio/db.py
- [X] T002 `get_json(url, params, headers)` nel client HTTP e nel client finto dei test in monitoraggio/fonti/http.py e tests/conftest.py
- [X] T003 `token_valido(margine=30)`: rinnova il token con `refresh_token` quando scade; predefiniti OIDC per `sso.cnr.it` realm `CNR` client `selezioni` in auth.py

## Phase 2: User Story 1 - RdP per bando (P1) 🎯 MVP

- [X] T004 [P] [US1] Test: paginazione, estrazione dei soli campi ammessi (niente codice fiscale, matricola, email personali), errore 401, bandi non monitorati ignorati, fallimento a metà senza scritture in tests/test_referenti.py
- [X] T005 [US1] `bandi_con_rdp(client, token)` e `persona(rdp)` in monitoraggio/fonti/sol_rdp.py
- [X] T006 [US1] `aggiorna(conn, token, utente, client=None)` con lock, scrittura in transazione, registro; `referenti_per_bando(conn)` e `stato(conn)` in monitoraggio/referenti.py
- [X] T007 [US1] `POST /api/referenti/aggiorna` (401 senza token), `GET /api/referenti/stato`; `crea_blueprint(token_utente=...)` in monitoraggio/web.py
- [X] T008 [US1] Login SSO nel server locale quando `OIDC_CLIENT_SECRET` è impostato (Flask-Session in `DATA_DIR`, endpoint `root`), utente e Accedi/Esci nel menu in monitoraggio/__main__.py, monitoraggio/web.py, monitoraggio/static/menu.js

## Phase 3: User Story 2 - Filtro per RdP (P1)

- [X] T009 [US2] Campo `rdp` (nomi ed email attivi) nelle righe di `elenco_atti` e nel dettaglio bando in monitoraggio/atti.py e monitoraggio/web.py
- [X] T010 [US2] Colonna RdP, filtro per RdP e pulsante "Aggiorna referenti" con stato in monitoraggio/static/riepilogo.html

## Phase 4: User Story 3 - Cambi di RdP (P2)

- [X] T011 [US3] Test e implementazione di attivo/non attivo al cambio e al ritorno di un RdP in tests/test_referenti.py e monitoraggio/referenti.py

## Phase 5: Polish

- [X] T012 Documentare in quickstart.md la configurazione `.env` locale (senza segreti) e la richiesta ai Sistemi Informativi (redirect da registrare sul client `selezioni`) in specs/003-referenti-rdp/quickstart.md
- [X] T013 Schede per atto e filtri mese/tipologia nella consultazione dell'area referenti
