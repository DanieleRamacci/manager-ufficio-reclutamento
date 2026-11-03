---

description: "Task list per il file della segreteria"
---

# Tasks: File della segreteria come fonte di riferimento

**Input**: spec.md, plan.md, data-model.md in `/specs/002-file-segreteria/`

**Tests**: richiesti dalla constitution; i test usano un file Excel generato con dati inventati.

## Phase 1: Setup

- [X] T001 Aggiungere `openpyxl` a requirements.txt e requirements-monitoraggio.txt
- [X] T002 Aggiungere le tabelle `segreteria_versione`, `segreteria_riga`, `segreteria_atto` (data-model.md) e portare `SCHEMA_VERSION` a 2 con migrazione dalla 1 in monitoraggio/db.py

## Phase 2: User Story 1 - Caricare il file e il rapporto (P1) 🎯 MVP

- [X] T003 [P] [US1] Test: lettura dei tre fogli da un Excel di prova (intestazioni per nome, duplicati `N. Bando`/`N Bando` e `Note`, numero bando numerico `390.475` e `367529`, date testo e data), rapporto (righe senza bando o protocollo, date illeggibili, numeri discordanti, scorrimenti senza tipologia, colonne mancanti), rifiuto di un file non Excel o senza fogli riconosciuti in tests/test_segreteria.py
- [X] T004 [US1] Implementare `leggi_file(contenuto) -> (righe per foglio, rapporto)` e `costruisci_atti(righe)` (raggruppamenti, sottotipo, fuori ambito) in monitoraggio/segreteria.py
- [X] T005 [US1] Implementare `importa(conn, contenuto, nome_file, utente)`: versione, righe, atti in un'unica transazione, versione precedente a `precedente`, collegamento ai bandi per numero; nessun valore delle righe nei log in monitoraggio/segreteria.py
- [X] T006 [US1] API `POST /api/segreteria/carica` (multipart, max 15 MB, solo `.xlsx`), `GET /api/segreteria/versioni` in monitoraggio/web.py
- [X] T007 [US1] Pagina `/monitoraggio/segreteria`: caricamento, rapporto dell'ultimo caricamento, elenco versioni in monitoraggio/static/segreteria.html

## Phase 3: User Story 2 - Terza colonna della tabella degli atti (P1)

- [X] T008 [P] [US2] Test a tre fonti: atto su tutte e tre in una riga, scorrimento solo nel file con SOL e URP rossi, graduatoria URP non nel file con cella segreteria rossa, atto prima del periodo del foglio con cella grigia, protocollo diverso tra file e SOL accorpato, atto del file fuori ambito escluso in tests/test_atti.py
- [X] T009 [US2] Estendere `elenco_atti` alla fonte `segreteria` (versione in uso), con unione per (categoria, protocollo), accorpamento per categoria e data con fonti disgiunte, periodo per foglio, atti solo nel file anche senza bando collegato in monitoraggio/atti.py

## Phase 4: User Story 3 - Sottotipo dal file (P2)

- [X] T010 [US3] Nella tabella degli atti: sottotipo del file prevalente con origine `segreteria`, nota "tipologia da completare nel file" se vuoto, nota se diverso da quello del titolo; aggiornare le etichette in monitoraggio/atti.py e monitoraggio/static/riepilogo.html

## Phase 5: User Story 4 - Consultare i dati del file (P2)

- [X] T011 [US4] API `GET /api/segreteria/atti?categoria=&mese=` e `GET /api/segreteria/atti/<id>/righe` in monitoraggio/web.py
- [X] T012 [US4] Elenco atti del file con filtri per mese e tipo, "fuori ambito" evidenziato, dettaglio con le righe (posizione, nominativo, punteggio o tipologia, note) in monitoraggio/static/segreteria.html

## Phase 6: User Story 5 - Differenze tra versioni (P3)

- [X] T013 [P] [US5] Test differenze: atto nuovo, sparito, modificato (data, persone, sottotipo); stesso file due volte = nessuna differenza in tests/test_segreteria.py
- [X] T014 [US5] `differenze(conn, versione_id)` e `GET /api/segreteria/versioni/<id>/differenze`, mostrate nella pagina dopo il caricamento in monitoraggio/segreteria.py, monitoraggio/web.py, monitoraggio/static/segreteria.html

## Phase 7: Polish

- [X] T015 Eseguire `pytest` e caricare il file reale nel server locale; annotare in quickstart.md i conteggi del rapporto e degli atti collegati (SC-002, SC-003) in specs/002-file-segreteria/quickstart.md

## Dependencies

- T001–T002 prima di tutto; T003–T007 (US1) prima di US2–US5; US3 dipende da T009.
