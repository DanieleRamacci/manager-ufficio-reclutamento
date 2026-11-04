---

description: "Task list per la raccolta dati unificata di bandi, graduatorie e scorrimenti"
---

# Tasks: Raccolta dati unificata di bandi, graduatorie e scorrimenti

**Input**: Design documents from `/specs/001-raccolta-dati-bandi/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: richiesti dalla constitution (Flusso di Sviluppo: "La logica di normalizzazione e
confronto MUST avere test automatici (pytest) con casi reali anonimizzati"). I test usano
fixture salvate e non fanno richieste in rete.

**Organization**: task raggruppati per user story (US1–US4 di spec.md).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: eseguibile in parallelo (file diversi, nessuna dipendenza da task incompleti)
- **[Story]**: user story di riferimento (US1, US2, US3, US4)

## Path Conventions

Pacchetto `monitoraggio/` e cartella `tests/` nella radice del repository, accanto ad
`avvia_tool.py` (vedi plan.md, Project Structure).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: struttura del pacchetto, dipendenze di sviluppo, protezione del repository

- [X] T001 Creare il pacchetto `monitoraggio/` con `__init__.py`, `fonti/__init__.py` e un `__main__.py` che per ora stampa l'help dei comandi `raccogli`, `importa-json`, `stato` (contracts/api.md, "Comando da terminale") in `monitoraggio/__main__.py`
- [X] T002 [P] Creare requirements-dev.txt con `pytest` e `-r requirements.txt`; aggiungere `pytest.ini` con `testpaths = tests` in requirements-dev.txt e pytest.ini
- [X] T003 [P] Aggiornare .gitignore aggiungendo `*.db`, `*.db-journal`, `*.db-wal`, `/bandi-completi-urp.json`, `/bandi-concorsi-pubblici-sol.json`, `/bandi-mobilita.json`, `/bandi_temp.json`, `/bandi-con-rdp.json`, `/controllo_criteri_tracce_*.json`, `/controllo_criteri_tracce_*.csv`, `flask_session/` (Principio II) in .gitignore
- [X] T004 [P] Creare tests/conftest.py con una fixture `db` che imposta `DATA_DIR` su `tmp_path` e restituisce una connessione inizializzata, e una fixture `fixture_path(nome)` che punta a tests/fixtures/ in tests/conftest.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: configurazione, schema del database, normalizzazione, classificazione e client HTTP usati da tutte le storie

**⚠️ CRITICAL**: nessuna user story può partire prima della fine di questa fase

- [X] T005 [P] Implementare monitoraggio/config.py: lettura delle variabili d'ambiente della tabella "Configurazione" di contracts/api.md (`DATA_DIR` predefinita `instance/`, `RACCOLTA_NOTTURNA`=`1`, `RACCOLTA_ORARIO`=`02:30`, `RACCOLTA_COMPLETA_GIORNO`=`dom`, `RACCOLTA_PAUSA_URP`=`0.5`, `RACCOLTA_PAUSA_SOL`=`1.0`, `URP_SEZIONI`=`tempo-indeterminato,bandi-pubblici-mobilita,categorie-riservatarie`, `MONITORAGGIO_DAL`=`2026-01-01`), costanti `URP_BASE`=`https://www.urp.cnr.it`, URL delle sezioni senza barra finale (research R7), `SOL_SEARCH_URL`, `SOL_TREE_UUID`=`713d4376-4cbd-43b6-ad14-9401b5029c51`, mappa dei cinque tipi SOL → tipologia di research R2, `SOL_PAGE_SIZE`=100 (R1), finestra bandi attivi 36 mesi (R8) in monitoraggio/config.py
- [X] T006 Implementare monitoraggio/db.py: `connetti()` su `DATA_DIR/monitoraggio.db` (crea la cartella, `PRAGMA foreign_keys=ON`, `journal_mode=WAL`), `inizializza()` con le tabelle `bando`, `scheda`, `documento`, `raccolta`, `raccolta_errore` esattamente come in data-model.md, inclusi i vincoli "`codice_norm` text, unique, nullable", "unique (`fonte`, `id_esterno`)" su scheda, "unique (`scheda_id`, `id_esterno`)" su documento, `categoria` in (`bando`, `graduatoria`, `scorrimento`, `rettifica`, `criteri`, `tracce`, `altro`), `sottotipo` nullable in (`subentro`, `ulteriore`, `utilizzo`, `non_specificato`), `esito` in (`in_corso`, `completata`, `completata_con_errori`, `fallita`), e una tabella `schema_version` per migrazioni future (depends on T005) in monitoraggio/db.py
- [X] T007 [P] Scrivere i test di normalizzazione con i casi reali di research R5 e R12: `367.479 CTER IOM GE` e `367.479 CTER IOMGE` → stesso `codice_norm`; numero bando da `367.434 CA Cod. 14`, `367.434 CA. Cod 13`, `367.434 CA. Codice 16`, `367529`, `390.475`, `367.500 CTER ALLEGATI ALLEGATO 1 - STRUTT` (→ `367.500`); sotto-bando `Cod. 14`→`14`, `cod.05`→`5`; protocolli `0455701`→`455701`, `'157495 '`→`157495`, `- Protocollo 160039`→`160039`; date `12-05-2025`, `12/05/2025`, `2025-05-12T12:00:00Z` → `2025-05-12` in tests/test_normalizza.py
- [X] T008 [P] Implementare monitoraggio/normalizza.py: `codice_norm(testo)`, `numero_bando(testo)` (pattern `\d{3}\.\d+` oppure 6 cifre `367529`→`367.529`), `codice_sotto(testo)`, `protocollo(testo)`, `data_iso(testo)`, riusando `norm_space`, `parse_date_any` ed `estrai_codice_bando` di scraper-urp.py (righe 51–135) senza modificarli lì, fino a far passare tests/test_normalizza.py in monitoraggio/normalizza.py
- [X] T009 [P] Scrivere i test di classificazione con gli esempi reali di research R4: "Provvedimento subentro scorrimento graduatoria" → `scorrimento`/`subentro`; "Provvedimento ulteriore scorrimento graduatoria" → `scorrimento`/`ulteriore`; "Provvedimento terzo scorrimento graduatoria" → `scorrimento`/`ulteriore` con ordinale 3; "Assunzione di n. 2 unità di personale mediante utilizzo graduatoria" → `scorrimento`/`utilizzo`; "Scorrimento graduatoria" → `scorrimento`/`non_specificato`; "Rettifica nominativo graduatoria" → `rettifica`; "Graduatoria" → `graduatoria`; "Avviso convocazione prova idoneativa" → `altro`; SOL `call_recruitment_provision` con nome generico → `scorrimento`; SOL `call_classification` con nome "IR 003 2026 ICAR NA_Provv_scorrimento 455701" → `scorrimento`; SOL `call_correction_classification` con nome "..._Scorrimento Graduatoria_..." → `scorrimento`; criteri e tracce come in `classifica_documento_generico` di scraper-urp.py in tests/test_classifica.py
- [X] T010 [P] Implementare monitoraggio/classifica.py: `classifica(titolo, tipo_fonte=None) -> (categoria, sottotipo, ordinale)` con le regole ordinate del livello 1 e del livello 2 di research R4 definite come liste di pattern in testa al file (FR-006, FR-006a), fino a far passare tests/test_classifica.py in monitoraggio/classifica.py
- [X] T011 [P] Implementare monitoraggio/fonti/http.py: sessione `requests` con user agent `Mozilla/5.0 (compatible; CNR-BandiBot/1.0)`, timeout 30 s, pausa configurabile tra le richieste, retry con attesa crescente (3 tentativi) su errori di rete e HTTP 5xx/429, solo metodo GET (Principio III) in monitoraggio/fonti/http.py

**Checkpoint**: fondamenta pronte, le user story possono partire

---

## Phase 3: User Story 1 - Elenco completo e aggiornato dei bandi e dei loro documenti (Priority: P1) 🎯 MVP

**Goal**: raccolta completa da URP (tre sezioni) e SOL (cinque tipi, paginazione completa, allegati per bando) salvata nel database con prima e ultima rilevazione.

**Independent Test**: `python -m monitoraggio raccogli --fonte tutte --completa` con `DATA_DIR` temporanea; i conteggi per sezione e per tipo coincidono con i totali dichiarati dalle fonti (quickstart.md, punto 2).

### Fixture e test per User Story 1

- [X] T012 [P] [US1] Salvare fixture pubbliche URP: una pagina elenco per ciascuna delle tre sezioni (con l'header "Numero Documenti: 10 di N"), la pagina di dettaglio di un bando con allegati "Graduatoria", "Scorrimento graduatoria", "Utilizzo graduatoria", "Rettifica graduatoria", e una pagina elenco senza bandi, in tests/fixtures/urp/
- [X] T013 [P] [US1] Salvare fixture pubbliche SOL: una pagina di ricerca bandi con `totalNumItems` e `hasMoreItems=true`, l'ultima pagina con `hasMoreItems=false`, la risposta allegati `IN_FOLDER` di un bando con `call_classification` e `call_recruitment_provision`, e la risposta di errore `{"error":"Unknown type ..."}`, in tests/fixtures/sol/
- [X] T014 [P] [US1] Scrivere i test del parser URP: numero totale dall'header, link dei bandi, campi del bando (titolo, codice originale, numero bando, protocollo e data dall'estratto "Protocollo N del GG-MM-AAAA"), allegati con protocollo e data e categoria da classifica.py, elenco vuoto riconosciuto in tests/test_fonte_urp.py
- [X] T015 [P] [US1] Scrivere i test del client SOL: paginazione con `skipCount` fino a `hasMoreItems=false`, errore se il totale raccolto è diverso da `totalNumItems`, mappatura dei campi `jconon_call:*` (codice, profilo, sede, numero_posti, rdp, data_pubblicazione_inpa, data_pubbl_graduatoria, `cmis:lastModificationDate`), mappatura degli allegati (`cmis:objectTypeId`, `cmis:name`, `jconon_protocollo:numero`, `jconon_protocollo:data`) in tests/test_fonte_sol.py
- [X] T016 [P] [US1] Scrivere i test di raccolta su database temporaneo: prima raccolta inserisce bandi, schede e documenti; seconda raccolta identica non crea duplicati e aggiorna solo `ultima_rilevazione`; un documento sparito diventa `presente = false` senza essere cancellato; con esito `fallita` le righe di `scheda` e `documento` non cambiano (FR-016); seconda raccolta sulla stessa fonte mentre una è `in_corso` viene rifiutata (FR-017) in tests/test_raccolta.py

### Implementazione per User Story 1

- [X] T017 [US1] Implementare monitoraggio/fonti/urp.py: `elenco_sezione(sezione)` che segue `?page=N` fino a raccogliere il totale dichiarato e deduplica i link; `dettaglio_bando(url)` che riusa il parsing di `parse_bando` di scraper-urp.py (righe 338–420) restituendo un dizionario scheda con `id_esterno` = percorso `/node/NNNN`, `sezione`, `codice_originale`, `numero_bando`, `codice_sotto`, `protocollo`, `data_pubblicazione`, `dati_extra` (estratto) e la lista degli allegati classificati; nessun controllo PDF in questo modulo (depends on T008, T010, T011) in monitoraggio/fonti/urp.py
- [X] T018 [US1] Implementare monitoraggio/fonti/sol.py: `cerca_bandi(tipo)` con query CMIS per tipo e paginazione a 100 (research R1, R2), `allegati_bando(object_id)` con query `IN_FOLDER` su `jconon_attachment:document` (R3), conversione in dizionari scheda e documento con protocolli normalizzati; ignora i documenti `D:jconon_commissione:metadata` (depends on T008, T010, T011) in monitoraggio/fonti/sol.py
- [X] T019 [US1] Implementare monitoraggio/raccolta.py, parte registro e salvataggio: `avvia(fonte, modalita, avviata_da)` che crea la riga `raccolta` con esito `in_corso` solo se non ce n'è un'altra `in_corso` per la stessa fonte; upsert di `scheda` per (`fonte`, `id_esterno`) e di `documento` per (`scheda_id`, `id_esterno`) con `prima_rilevazione` impostata solo all'inserimento; registrazione di `raccolta_errore` per ogni bando non letto; chiusura con esito `completata`, `completata_con_errori` o `fallita` e conteggi `bandi_trovati`, `documenti_trovati`, `nuovi`, `aggiornati`, `totale_dichiarato` (depends on T006) in monitoraggio/raccolta.py
- [X] T020 [US1] Implementare in monitoraggio/raccolta.py la raccolta URP: per ogni sezione di `URP_SEZIONI` elenco e dettaglio, esito `fallita` se un elenco è vuoto o il totale raccolto è diverso dal dichiarato, marcatura `presente = false` delle schede e dei documenti non visti solo per esito `completata` (data-model.md, Transizioni di stato) (depends on T017, T019) in monitoraggio/raccolta.py
- [X] T021 [US1] Implementare in monitoraggio/raccolta.py la raccolta SOL: elenco completo dei cinque tipi; allegati per tutti i bandi in modalità `completa`, altrimenti solo per i bandi attivi (pubblicati negli ultimi 36 mesi, oppure senza documento `graduatoria`, oppure con `modificata_fonte_il` cambiata) come in research R8 (depends on T018, T019) in monitoraggio/raccolta.py
- [X] T022 [US1] Implementare monitoraggio/accessibilita.py spostando `_download_pdf`, `_pdf_has_text`, `_pdf_tag_info`, `valuta_accessibilita_pdf` da scraper-urp.py, e chiamarlo dalla raccolta URP solo per documenti nuovi o con `url` cambiato, salvando il risultato in `documento.accessibilita` (research R9) (depends on T020) in monitoraggio/accessibilita.py
- [X] T023 [US1] Collegare il comando `python -m monitoraggio raccogli [--fonte urp|sol|tutte] [--completa]` con codici di uscita 0/1/2 come da contracts/api.md (depends on T020, T021) in `monitoraggio/__main__.py`

**Checkpoint**: la raccolta completa da terminale funziona e popola il database

---

## Phase 4: User Story 2 - Stesso bando riconosciuto su URP e su SOL (Priority: P1)

**Goal**: collegare schede URP e SOL dello stesso bando e segnalare bandi e documenti presenti su una sola fonte, dal periodo di monitoraggio in poi.

**Independent Test**: dopo una raccolta, 30 bandi noti presenti su entrambe le fonti risultano `entrambi`; `367.479 CTER IOMGE` (URP) è collegato a `367.479 CTER IOM GE` (SOL); un bando SOL del 2016 è `fuori_periodo_urp` (quickstart.md, punto 4).

### Test per User Story 2

- [X] T024 [P] [US2] Scrivere i test di collegamento su database temporaneo: collegamento per numero bando e sotto-bando; poi per `codice_norm`; poi per protocollo; bando con più sotto-bandi SOL (367.500) non collegato al sotto-bando sbagliato; `stato_collegamento` `entrambi`, `solo_urp`, `solo_sol`, `fuori_periodo_urp` (FR-013a); graduatoria con stesso protocollo pubblico su URP e SOL non segnalata, graduatoria solo su URP segnalata come `graduatoria_mancante_sol`; nessuna segnalazione per documenti con data precedente a `MONITORAGGIO_DAL` (FR-013b) in tests/test_collegamento.py

### Implementazione per User Story 2

- [X] T025 [US2] Implementare monitoraggio/collegamento.py: `collega(conn)` con i passi 1–3 di data-model.md ("collegamento"), calcolo del periodo URP per sezione come data del bando più vecchio presente (research R6), aggiornamento di `bando.codice`, `tipologia`, `titolo`, `profilo`, `sede`, `numero_posti`, `gruppo_rdp`, `data_pubblicazione` preferendo i valori SOL, e funzione `segnalazioni(bando_id)` per le differenze sui documenti `graduatoria`, `scorrimento`, `rettifica` dal `MONITORAGGIO_DAL` in poi (depends on T019) in monitoraggio/collegamento.py
- [X] T026 [US2] Chiamare `collega()` alla fine di ogni raccolta riuscita o completata con errori, in monitoraggio/raccolta.py (depends on T025)
- [X] T027 [US2] Implementare nel Blueprint `GET /api/bandi` (filtri `tipologia`, `stato_collegamento`, `fonte`, `dal`, `al`, `q`) e `GET /api/bandi/<id>` con il formato di contracts/api.md, inclusi i conteggi dei documenti per categoria e per sottotipo di scorrimento e la lista `segnalazioni`, tutto con `login_required` (depends on T025) in monitoraggio/web.py

**Checkpoint**: il collegamento URP–SOL è disponibile da API

---

## Phase 5: User Story 3 - Sapere quanto sono aggiornati i dati (Priority: P2)

**Goal**: stato di ogni fonte (ultima raccolta, esito, conteggi, errori) visibile da terminale e da API.

**Independent Test**: con SOL non raggiungibile la raccolta risulta `fallita` con il motivo e i dati precedenti restano (quickstart.md, punto 5).

### Test per User Story 3

- [X] T028 [P] [US3] Scrivere i test di stato: `stato()` restituisce per fonte `ultima`, `ultima_riuscita`, `in_corso`; una fonte irraggiungibile (eccezione simulata nel client) produce esito `fallita` con `messaggio` valorizzato e lascia invariati i dati precedenti; un bando non leggibile produce `completata_con_errori` e una riga in `raccolta_errore` in tests/test_raccolta.py

### Implementazione per User Story 3

- [X] T029 [US3] Implementare `stato(conn)` ed `errori(conn, raccolta_id)` in monitoraggio/raccolta.py e il comando `python -m monitoraggio stato` che stampa per fonte data, esito, conteggi ed errori in `monitoraggio/__main__.py` (depends on T019)
- [X] T030 [US3] Implementare nel Blueprint `POST /api/raccolta/avvia` (avvio in un thread, risposta `202` o `409` "Raccolta già in corso per: ..."), `GET /api/raccolta/stato` (incluso `prossima_notturna`) e `GET /api/raccolta/<id>/errori`, con `login_required` e `avviata_da` = email dell'utente corrente, come da contracts/api.md (depends on T023, T029) in monitoraggio/web.py

**Checkpoint**: lo stato delle fonti è consultabile

---

## Phase 6: User Story 4 - Le pagine esistenti continuano a funzionare (Priority: P2)

**Goal**: `index.html`, `report-mese.html` e `mobilita-urp.html` funzionano invariate leggendo dal database; raccolta notturna e pulsante "Aggiorna dati"; storico JSON importato; file statici protetti.

**Independent Test**: dopo una raccolta le tre pagine mostrano gli stessi bandi e colonne di prima, con numeri uguali o maggiori; `GET /_static/.env` e `GET /_static/instance/monitoraggio.db` rispondono 404 o 403 (quickstart.md, punto 6).

### Test per User Story 4

- [X] T031 [P] [US4] Scrivere i test di compatibilità: le chiavi degli oggetti prodotti per `bandi-completi-urp.json` (oggetto per sezione, bandi con `url`, `titolo_bando`, `codice_bando`, `data_pubblicazione_bando`, `numero_protocollo`, `graduatoria_presente`, `data_pubblicazione_graduatoria`, `estratto`, `allegati` con `titolo`, `link`, `protocollo`, `data`, `data_iso`, `tipo_documento`, `tipo_graduatoria`, `access_check`, `scorrimento_utilizzo_presente`, `data_scorrimento_utilizzo`, `fonte`), `bandi-concorsi-pubblici-sol.json` e `bandi-mobilita.json` coincidono con quelle dei file storici presenti nella radice del repository; l'import dei JSON storici non sovrascrive dati più recenti in tests/test_compat.py

### Implementazione per User Story 4

- [ ] T032 [US4] Implementare monitoraggio/compat.py: `export_urp(conn)`, `export_sol(conn)`, `export_mobilita(conn)` che ricostruiscono i tre formati JSON di oggi dal database (contracts/api.md, "Compatibilità"; `tipo_graduatoria` = `graduatoria` o `scorrimento_utilizzo` derivato dalla categoria) e `importa_json(cartella)` che carica una volta i file storici, solo per le sezioni in ambito (`tempo-indeterminato`, mobilità, `categorie-riservatarie` e i tipi SOL di research R2; ignora `archivio-vecchio`, tempo determinato, borse, direttori), come raccolta con modalità `manuale` e `avviata_da` = `import` senza sovrascrivere righe con `ultima_rilevazione` più recente (FR-020) (depends on T019, T025) in monitoraggio/compat.py
- [ ] T033 [US4] Collegare il comando `python -m monitoraggio importa-json [--cartella PERCORSO]` (depends on T032) in `monitoraggio/__main__.py`
- [X] T034 [US4] Implementare monitoraggio/scheduler.py: thread daemon avviato una sola volta che ogni giorno all'ora `RACCOLTA_ORARIO` lancia la raccolta di entrambe le fonti con modalità `notturna`, e `completa` nel giorno `RACCOLTA_COMPLETA_GIORNO`; disattivato con `RACCOLTA_NOTTURNA=0`; usa il lock nel database di T019 così due processi non raccolgono insieme (depends on T023) in monitoraggio/scheduler.py
- [ ] T035 [US4] In avvia_tool.py: registrare il Blueprint di monitoraggio/web.py, inizializzare il database e avviare lo scheduler all'avvio; far delegare `POST /api/run` (body `{urp, sol, mob}`, dove `mob` equivale a `urp`) a `/api/raccolta/avvia` e `GET /api/status` a `/api/raccolta/stato` mantenendo i formati di risposta attuali (`urp`/`sol`/`mob` con `exists` e `mtime`, `running`) (depends on T030, T034) in avvia_tool.py
- [ ] T036 [US4] In avvia_tool.py, `protected_static`: servire `bandi-completi-urp.json`, `bandi-concorsi-pubblici-sol.json` e `bandi-mobilita.json` da monitoraggio/compat.py con header `Last-Modified` = fine dell'ultima raccolta riuscita della fonte; servire dalla cartella del codice solo `.html`, `.css`, `.js`, `.png`, `.jpg`, `.svg`, `.ico`, `version.json` e `docs_firme/` con il controllo di proprietà esistente; rispondere 404 per tutto il resto, compresi `.env`, `.py`, `*.db` e `instance/`; stessa lista consentita per la route generica `/<path:fname>` (research R11) (depends on T032) in avvia_tool.py
- [ ] T037 [US4] Sostituire il contenuto di scraper-urp.py, scraper-mobilita.py e scraper-sol-tutti-bandi.py con wrapper che chiamano `python -m monitoraggio raccogli --fonte urp|sol`, e rimuovere da avvia_tool.py le funzioni `run_scraper` e `kick_monitors` non più usate dopo T035 (depends on T035) in scraper-urp.py, scraper-mobilita.py, scraper-sol-tutti-bandi.py, avvia_tool.py

**Checkpoint**: tutte le user story funzionano nell'app

---

## Phase 6b: User Story 5 - Stato complessivo degli atti (Priority: P1)

**Goal**: tabella con una riga per atto e lo stato su ogni fonte (FR-021, FR-022, FR-024).

**Independent Test**: spec.md, User Story 5.

- [X] T045 [P] [US5] Test della tabella degli atti: atto su entrambe le fonti in una riga, scorrimento solo su URP con cella SOL "mancante", protocollo diverso in una riga con nota, bando solo SOL / solo URP, colonna segreteria "non_caricato" in tests/test_atti.py
- [X] T046 [US5] Implementare `elenco_atti(conn, dal, al)` con celle `presente`/`mancante`/`non_applicabile`/`non_caricato`, esclusione di documenti annullati e rettifiche non relative alla graduatoria, accoppiamento dei protocolli diversi per stessa categoria e data in monitoraggio/atti.py
- [X] T047 [US5] Esporre `GET /api/atti?dal=&al=` e `GET /api/riepilogo` nel Blueprint in monitoraggio/web.py
- [X] T048 [US5] Pagina di monitoraggio con stato delle fonti, tabella degli atti con filtri e colori, riepilogo mese per mese, elenco dei bandi e dettaglio in monitoraggio/static/riepilogo.html
- [X] T049 [US5] Comando `python -m monitoraggio web [--porta 8090]` (solo 127.0.0.1, senza login) con le pagine esistenti e i JSON di compatibilità serviti dal database in `monitoraggio/__main__.py` e monitoraggio/web.py

## Phase 6c: User Story 6 - Menu comune (Priority: P2)

**Goal**: lo stesso menu in alto in ogni pagina (FR-023).

**Independent Test**: spec.md, User Story 6.

- [X] T050 [US6] Definire le voci del menu in un unico punto, raggruppate in Monitoraggio (Riepilogo atti `/monitoraggio`, File segreteria `/monitoraggio/segreteria`, Report del mese `report-mese.html`), Controlli URP (Controllo bandi `index.html`, Accessibilità URP `access.html`, Verifica PDF `verifica-access.html`, Mobilità `mobilita-urp.html`, Stato avanzamento `stato-avanzamento.html`) e Strumenti (Redazione firme `redazione-firme.html`, Job firme `firme-jobs.html`, Strumento RdP `rdp-tool.html`, Ispeziona bando SOL `call-inspect.html`, Dettaglio graduatoria `graduatoria-detail.html`), con `GET /api/menu` che indica per ogni voce se è disponibile nell'ambiente in uso, in monitoraggio/web.py
- [X] T051 [US6] Creare il componente del menu che si disegna in cima alla pagina, evidenzia la voce corrente, segna le voci non disponibili e mostra lo stato delle raccolte da `/api/raccolta/stato`, in monitoraggio/static/menu.js
- [X] T052 [US6] Includere `<script src="/monitoraggio/menu.js"></script>` in monitoraggio/static/riepilogo.html e in tutte le pagine HTML dell'app (index.html, access.html, verifica-access.html, mobilita-urp.html, report-mese.html, stato-avanzamento.html, redazione-firme.html, firme-jobs.html, rdp-tool.html, call-inspect.html, graduatoria-detail.html, privacy.html, search.html), togliendo i menu scritti a mano dentro le pagine
- [X] T053 [US6] Test: ogni voce di `/api/menu` punta a un file o a una route esistente; nel server locale le voci degli strumenti firme risultano non disponibili in tests/test_web.py

## Phase 6d: Archivio storico URP per i bandi fuori periodo (FR-013c)

- [X] T054 [P] [US2] Salvare una fixture della pagina dell'archivio storico URP (`https://archivio.urp.cnr.it/page.php?level=3&pg=157&Org=4&db=1`) e scrivere i test del parser (codice bando, protocollo e data dal titolo, allegati con protocollo, data e categoria da classifica.py) in tests/test_fonte_urp_archivio.py
- [X] T055 [US2] Implementare `elenco_archivio(client)` riprendendo `parse_archivio_old_urp` di scraper-urp.py, con sezione `archivio` e tipologia ricavata dal testo, e includerlo nella raccolta URP (sezione configurabile in `URP_SEZIONI`) in monitoraggio/fonti/urp_archivio.py e monitoraggio/raccolta.py
- [ ] T056 [US2] Nel collegamento, calcolare il periodo URP includendo l'archivio e usare `fuori_periodo_urp` solo per i bandi più vecchi anche dell'archivio; test in tests/test_collegamento.py e monitoraggio/collegamento.py

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T038 Rimuovere dall'indice git i file di dati in radice (`git rm --cached bandi-completi-urp.json bandi-concorsi-pubblici-sol.json bandi-mobilita.json bandi_temp.json controllo_criteri_tracce_2020plus.json controllo_criteri_tracce_2024plus.csv` e le cartelle `flask_session/`, `instance/`, `docs_firme/` se tracciate), lasciandoli sul disco per `importa-json`; la pulizia della cronologia resta il TODO(REPO_VISIBILITY) della constitution
- [ ] T039 [P] Aggiornare README.md con: comandi `python -m monitoraggio`, variabili d'ambiente della raccolta, volume `DATA_DIR` per Coolify, esecuzione dei test in README.md
- [ ] T040 [P] Creare CLAUDE.md con il contesto operativo richiesto dalla Governance della constitution: scopo, fonti (URP, SOL, file di riepilogo), glossario (scorrimento, subentro, utilizzo, protocollo pubblico e privato), regole sui dati (Principio II), comandi di test e di raccolta in CLAUDE.md
- [ ] T041 Eseguire `pytest -q` sull'intera cartella tests/ e correggere i fallimenti in monitoraggio/
- [ ] T042 Eseguire il quickstart (specs/001-raccolta-dati-bandi/quickstart.md, punti 2–6) con dati reali e annotare in fondo al quickstart i totali osservati, le differenze rispetto ai totali dichiarati, la percentuale di bandi collegati (SC-003) e la durata delle raccolte completa e incrementale (SC-004)

### Esecuzione locale (analisi U1)

- [X] T043 [P] Creare requirements-monitoraggio.txt con le sole dipendenze del pacchetto `monitoraggio` (requests, beautifulsoup4, pdfminer.six, Flask, python-dotenv, pytest) per provare raccolta e test in locale senza torch e ultralytics; documentare in quickstart.md la creazione del venv con `uv venv --python 3.11` in requirements-monitoraggio.txt e specs/001-raccolta-dati-bandi/quickstart.md
- [ ] T044 Documentare in quickstart.md l'avvio locale dell'app completa con `docker compose up --build` e un `.env` locale (OIDC con `OIDC_REDIRECT_URI=http://localhost:8081/oidc-callback`, `DATA_DIR=/app/instance`), senza committare `.env` in specs/001-raccolta-dati-bandi/quickstart.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: nessuna dipendenza
- **Foundational (Phase 2)**: dopo il Setup; blocca tutte le user story
- **US1 (Phase 3)**: dopo la Phase 2
- **US2 (Phase 4)**: dopo T019 (registro e salvataggio di US1); i test T024 possono partire subito dopo la Phase 2
- **US3 (Phase 5)**: dopo T019 e T023
- **US4 (Phase 6)**: dopo US1, US2 (T025) e US3 (T030)
- **Polish (Phase 7)**: dopo tutte le user story

### Dentro ogni user story

- Fixture e test prima dell'implementazione, e devono fallire prima di essa
- Fonti (urp.py, sol.py) prima della raccolta, raccolta prima di comandi e API

### Parallel Opportunities

- Phase 1: T002, T003, T004 insieme
- Phase 2: T005, T007, T009, T011 insieme; poi T008 e T010 insieme
- US1: T012, T013, T014, T015, T016 insieme; T017 e T018 insieme
- US2, US3 e US4: i test T024, T028, T031 possono essere scritti in parallelo
- Polish: T039 e T040 insieme

## Parallel Example: User Story 1

```text
Task: "T012 Salvare fixture pubbliche URP in tests/fixtures/urp/"
Task: "T013 Salvare fixture pubbliche SOL in tests/fixtures/sol/"
Task: "T014 Test del parser URP in tests/test_fonte_urp.py"
Task: "T015 Test del client SOL in tests/test_fonte_sol.py"

Poi:
Task: "T017 monitoraggio/fonti/urp.py"
Task: "T018 monitoraggio/fonti/sol.py"
```

## Implementation Strategy

### MVP (User Story 1)

1. Phase 1 e Phase 2
2. Phase 3 (US1): raccolta completa da terminale nel database
3. **Stop e verifica**: conteggi contro i totali dichiarati (SC-001), campione di 10 bandi (SC-002)

### Consegna incrementale

1. US1 → database popolato e verificabile da terminale
2. US2 → collegamento URP–SOL e segnalazioni via API
3. US3 → stato delle fonti
4. US4 → app esistente alimentata dal database, raccolta notturna, file statici protetti; da qui
   l'app può andare su Coolify
5. Polish → repository pulito dai file di dati, documentazione

## Notes

- Ogni task chiude con test verdi relativi alla sua parte
- Nessun file di dati nella cartella del codice: i test usano `tmp_path`, le fixture contengono
  solo pagine e risposte pubbliche senza nominativi
- A fine fase si propone il commit sul branch `001-raccolta-dati-bandi`; commit e push solo
  dopo la revisione del responsabile del progetto (constitution, Flusso di Sviluppo)
- Prova in locale sul Mac dell'utente: le fasi 1–5 si verificano da terminale con un ambiente
  leggero (`requirements-monitoraggio.txt`, T043); l'app completa (fase 6) si prova con Docker
  e un `.env` locale (T044)
