# Implementation Plan: File della segreteria come fonte di riferimento

**Branch**: `002-file-segreteria` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-file-segreteria/spec.md`

## Summary

Un modulo `monitoraggio/segreteria.py` legge il file Excel caricato dalla pagina "File
segreteria" (tre fogli riconosciuti per nome, colonne per intestazione), salva ogni
caricamento come versione con righe e atti nel database, produce il rapporto di caricamento e
le differenze con la versione precedente. La tabella degli atti della spec 001 (`atti.py`)
diventa a tre fonti: gli atti si uniscono per bando, categoria e protocollo, gli atti con
protocolli diversi ma stessa categoria e data si accorpano, il sottotipo del file prevale.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: Flask, openpyxl (nuova: lettura `.xlsx`; aggiunta a
`requirements.txt` e `requirements-monitoraggio.txt`)

**Storage**: SQLite `monitoraggio.db` (spec 001), tre tabelle nuove

**Testing**: pytest con un file Excel di prova generato nei test (dati inventati, nessun
nominativo reale)

**Target Platform**: come spec 001 (Docker su Coolify dietro SSO; server locale di prova)

**Project Type**: web application Flask

**Performance Goals**: caricamento e rapporto di un file di circa 1.000 righe in meno di 30 s

**Constraints**: nominativi solo nel database, mai nei log né nel repository; il file
caricato non viene scritto su disco nella cartella del codice

**Scale/Scope**: un file con tre fogli, qualche migliaio di righe, poche versioni al mese

## Constitution Check

| Principio | Verifica | Esito |
| --- | --- | --- |
| I. Fonti indipendenti | Gli atti del file sono una fonte a sé; il confronto non modifica né il file né URP/SOL; le differenze sono note da verificare | OK |
| II. Dati nel database | Righe e nominativi in tabelle del database; il file non viene salvato su disco; log solo con conteggi; test con dati inventati | OK |
| III. Sola lettura esterna | Nessuna chiamata esterna | OK |
| IV. Autorizzazione | Caricamento e consultazione con lo stesso decoratore di protezione (SSO in produzione) | OK |
| V. Tracciabilità | Versione con data, utente, nome file, rapporto; differenze tra versioni | OK |
| VI. Incrementale | Modulo nuovo; `atti.py` esteso, API e pagina esistenti invariate nel formato | OK |

## Project Structure

```text
monitoraggio/
├── segreteria.py          # lettura Excel, rapporto, atti, versioni, differenze, collegamento
├── atti.py                # tabella degli atti a tre fonti
├── db.py                  # tabelle segreteria_versione, segreteria_riga, segreteria_atto
├── web.py                 # /monitoraggio/segreteria e /api/segreteria/*
└── static/segreteria.html # caricamento, rapporto, versioni, atti del file

tests/
├── test_segreteria.py     # lettura, rapporto, atti, differenze, rifiuto file non validi
└── test_atti.py           # casi a tre fonti
```

**Structure Decision**: tutto nel pacchetto `monitoraggio/` della spec 001.

## Decisioni (research)

- **Riconoscimento colonne**: intestazioni normalizzate (minuscole, solo lettere e cifre);
  nomi duplicati (`N. Bando` e `N Bando`, due `Note`) si assegnano in ordine di posizione.
- **Numeri di bando come numero Excel**: `390.475` letto come numero diventa `"390.475"`
  formattando con tre decimali (un `367.500` numerico altrimenti diventerebbe `367.5`);
  `367529` intero diventa `367.529` con la normalizzazione della spec 001.
- **Sotto-bando**: da `Cod. 14` nel numero di bando, altrimenti dal numero iniziale della
  colonna `Sotto-bando` (`01 AR MI4` → `1`).
- **Raggruppamento in atti**: Bandi una riga = un atto; Graduatorie per (numero, sotto-bando,
  protocollo pubblico); Scorrimento per (numero, sotto-bando, protocollo).
- **Sottotipo dal file**: `Subentro` → `subentro`, `Scorrimento` → `ordinario`; righe miste
  nello stesso atto → `misto`; nessuna tipologia → vuoto e nota "tipologia da completare".
- **Fuori ambito**: bandi del foglio Bandi con tipo procedura che contiene "direttor" o
  "revoca" (configurabile con `SEGRETERIA_FUORI_AMBITO`); gli atti di Graduatorie e
  Scorrimento con lo stesso numero di bando ereditano il "fuori ambito".
- **Periodo coperto**: per ogni foglio, dalla data più vecchia del foglio nella versione in
  uso; prima la cella è "fuori periodo".
- **Accorpamento**: dopo l'unione per (categoria, protocollo), righe dello stesso bando con
  stessa categoria e data e fonti disgiunte si uniscono con nota "protocollo diverso".
- **Collegamento al bando**: per numero di bando; un atto del file senza bando corrispondente
  compare comunque in tabella (URP e SOL rossi).

## Complexity Tracking

Nessuna violazione della constitution.
