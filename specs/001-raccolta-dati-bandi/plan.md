# Implementation Plan: Raccolta dati unificata di bandi, graduatorie e scorrimenti

**Branch**: `001-raccolta-dati-bandi` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-raccolta-dati-bandi/spec.md`

## Summary

Sostituire i tre script di raccolta (`scraper-urp.py`, `scraper-mobilita.py`,
`scraper-sol-tutti-bandi.py`), che scrivono file JSON nella cartella del codice, con un
pacchetto `monitoraggio/` che raccoglie da URP (tempo indeterminato, mobilità, categorie
riservatarie) e da SOL (cinque tipi di bando, paginazione completa, allegati strutturati con
protocollo) e salva tutto in un database SQLite sul volume persistente. Il pacchetto collega
le schede URP e SOL dello stesso bando tramite codice e protocollo normalizzati, registra
ogni raccolta con esito ed errori, gira ogni notte e su richiesta dal pulsante "Aggiorna
dati". Le pagine esistenti continuano a funzionare perché i tre URL JSON di oggi vengono
serviti dal database nello stesso formato.

## Technical Context

**Language/Version**: Python 3.11 (immagine `python:3.11-slim`)

**Primary Dependencies**: Flask 3.1, requests, beautifulsoup4, pdfminer.six (già presenti);
pytest solo per lo sviluppo (nuovo `requirements-dev.txt`)

**Storage**: SQLite, file `monitoraggio.db` in `DATA_DIR` (predefinita `instance/`, volume
persistente)

**Testing**: pytest con fixture HTML/JSON salvate da URP e SOL (dati pubblici), nessuna
richiesta in rete nei test

**Target Platform**: container Linux su Coolify, dietro SSO CNR

**Project Type**: web application Flask monolitica con pagine HTML statiche

**Performance Goals**: raccolta notturna incrementale < 15 minuti; raccolta completa
< 40 minuti (circa 1.200 bandi SOL con 1 s di pausa più circa 240 pagine URP)

**Constraints**: sola lettura e pause tra le richieste (FR-008); nessun file di dati nella
cartella del codice (FR-014); compatibilità con `index.html`, `report-mese.html`,
`mobilita-urp.html` senza modifiche alle pagine

**Scale/Scope**: circa 1.200 bandi SOL, circa 241 bandi URP, alcune migliaia di documenti;
pochi utenti dell'ufficio

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Verifica | Esito |
| --- | --- | --- |
| I. Fonti indipendenti e confrontabili | Schede separate per fonte (`scheda.fonte`); il collegamento non modifica i dati delle schede; differenze solo come segnalazioni | OK |
| II. Dati nel database, mai nel repository | Database in `DATA_DIR`; i JSON di oggi diventano viste dal database; `.gitignore` aggiornato per `*.db` e per i JSON di dati; nessun dato personale raccolto in questa spec | OK |
| III. Sola lettura verso i sistemi esterni | Solo GET verso URP e API pubbliche SOL; pause configurabili; nessuna credenziale | OK |
| IV. Autorizzazione prima della logica | Tutte le route nuove con `login_required`; `protected_static` limitato a una lista di tipi consentiti (R11) | OK, con correzione di un rischio esistente |
| V. Dati tracciabili e aggiornati | Tabelle `raccolta` e `raccolta_errore`; confronto tra totale raccolto e dichiarato; `Last-Modified` dei JSON di compatibilità dalla raccolta | OK |
| VI. Evoluzione incrementale | Nuovo codice in `monitoraggio/`; `avvia_tool.py` cambia solo nelle route di raccolta e nel servizio dei file statici; pagine HTML invariate | OK |

**Re-check dopo la Phase 1**: nessuna violazione. La correzione di `protected_static` amplia
leggermente lo scope della spec ma è richiesta dal Principio IV, perché la route viene
comunque modificata.

## Project Structure

### Documentation (this feature)

```text
specs/001-raccolta-dati-bandi/
├── plan.md              # questo file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/api.md     # Phase 1
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
monitoraggio/
├── __init__.py
├── __main__.py          # comando: raccogli, importa-json, stato
├── config.py            # variabili d'ambiente, sezioni URP, tipi SOL, pause
├── db.py                # connessione, schema, migrazioni semplici
├── normalizza.py        # codice bando, protocollo, date
├── classifica.py        # tipo documento da titolo/nome file e tipo SOL (R4)
├── fonti/
│   ├── __init__.py
│   ├── http.py          # sessione requests con user agent, pause, retry
│   ├── urp.py           # elenco sezioni + dettaglio bando (da scraper-urp.py)
│   └── sol.py           # ricerca paginata + allegati per bando
├── accessibilita.py     # controllo PDF (da scraper-urp.py), solo documenti nuovi
├── raccolta.py          # esecuzione per fonte: lock, registro, upsert, presente/assente
├── collegamento.py      # collegamento URP–SOL e stato_collegamento
├── compat.py            # export nei formati JSON di oggi + import dei JSON storici
├── scheduler.py         # thread della raccolta notturna
└── web.py               # Blueprint Flask: /api/raccolta/*, /api/bandi*

tests/
├── conftest.py          # database temporaneo in tmp_path
├── fixtures/            # HTML URP e JSON SOL salvati (pubblici)
├── test_normalizza.py
├── test_classifica.py
├── test_fonte_urp.py
├── test_fonte_sol.py
├── test_raccolta.py
├── test_collegamento.py
└── test_compat.py

avvia_tool.py            # registra il Blueprint, avvia lo scheduler, /api/run e
                         # /api/status delegano a monitoraggio, protected_static legge
                         # i tre JSON dal database e rifiuta i file non consentiti
scraper-urp.py           # diventano wrapper di `python -m monitoraggio raccogli`
scraper-mobilita.py      #   per compatibilità; da rimuovere in una spec successiva
scraper-sol-tutti-bandi.py
```

**Structure Decision**: pacchetto Python `monitoraggio/` accanto ad `avvia_tool.py`, come
previsto dal Principio VI (nuova logica fuori dal file da 4.000 righe). Le pagine HTML
restano dove sono e non vengono modificate in questa spec.

## Fasi di implementazione

1. **Fondamenta**: `config`, `db` (schema da `data-model.md`), `normalizza`, `classifica`,
   test unitari con casi reali (`367.479 CTER IOMGE`, protocolli `0455701`, titoli
   "Provv_scorrimento", "Rettifica nominativo graduatoria").
2. **Fonte SOL**: ricerca paginata per tipo, allegati per bando, confronto con
   `totalNumItems`; test con fixture JSON.
3. **Fonte URP**: elenco e dettaglio delle tre sezioni, riuso del parsing esistente; test con
   fixture HTML.
4. **Raccolta e collegamento**: registro raccolte, lock per fonte, upsert con prima/ultima
   rilevazione, `presente`, collegamento e periodo URP; test su database temporaneo.
5. **Compatibilità e app**: export nei tre formati JSON, import dei JSON storici, Blueprint,
   `/api/run` e `/api/status`, `protected_static` ristretto, scheduler notturno.
6. **Pulizia del repository**: `.gitignore` per `*.db` e per i JSON di dati; `git rm --cached`
   dei JSON di dati in radice (la cronologia resta da ripulire, TODO della constitution).
7. **Verifica**: quickstart completo, confronto delle pagine prima e dopo.

## Rischi

| Rischio | Mitigazione |
| --- | --- |
| La struttura HTML di URP cambia | Raccolta `fallita` se l'elenco è vuoto o il totale non torna; i dati precedenti restano |
| SOL rallenta o limita le richieste | Pause configurabili, retry con attesa crescente, raccolta incrementale |
| Classificazione sbagliata degli scorrimenti | Regole in `classifica.py` con test su titoli reali; tipo SOL conservato in `tipo_fonte` per rivedere |
| Le pagine esistenti si aspettano campi non riprodotti | Test di compatibilità che confrontano le chiavi dei JSON prodotti con quelle dei file storici |
| Raccolta notturna eseguita due volte con più processi | Lock per fonte nel database (`raccolta.esito = in_corso`), non solo in memoria |

## Complexity Tracking

Nessuna violazione della constitution da giustificare.
