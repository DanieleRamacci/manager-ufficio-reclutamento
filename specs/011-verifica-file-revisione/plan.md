# Implementation Plan: Verifica dei file Excel del mese e revisione del monitoraggio

**Branch**: `011-verifica-file-revisione` | **Date**: 2026-11-18 | **Spec**: [spec.md](spec.md)

## Flusso (dall'utente, 2026-11-18)

1. L'amministratore scarica da Selezioni Online l'export «Punteggi» delle graduatorie del mese e il file scorrimenti compilato; li carica nella scheda «Riepilogo e revisione» del monitoraggio.
2. Il sistema verifica che ci sia tutto partendo da ciò che risulta nel database: ogni scorrimento e ogni graduatoria del monitoraggio deve essere nel file; se manca un intero foglio (es. RIC) o un intero gruppo di concorsi lo dice esplicitamente; ciò che è nel file e non nel database è segnalato.
3. L'amministratore vede l'elenco di ciò che non torna e chiede la verifica agli RdP del bando; coordinatori e persone dell'ufficio, dopo la revisione, vedono solo i totali: quanti bandi, graduatorie, scorrimenti e subentri risultano a noi e quanti ce ne sono nei file caricati.

## Technical Context

Python 3.11, Flask, SQLite (schema 29 → 30), pagine statiche. Nuova dipendenza: `xlrd==2.0.1` per l'export `.xls` di SOL (già in requirements.txt dell'app completa).

## Constitution Check

| Principio | Esito |
|---|---|
| I. Fonti indipendenti | OK: i file caricati si confrontano con il database senza correggerlo |
| II. Dati nel database | OK: estrazione e file scorrimenti nel database (dati personali, solo amministratori, mai nei log); deroga alla decisione del 2026-11-11 autorizzata dall'utente (FR-005) |
| III. Sola lettura | OK |
| IV. Autorizzazione | OK: verifiche, elenco e richieste solo amministratori; i totali in consultazione senza dati personali |
| V. Tracciabilità | OK: chi e quando per caricamenti, richieste e revisione |
| VI. Incrementale | OK: nuovo modulo `verifica_file.py`, `estrazione_sol.py`, `revisione.py`; `scorrimenti_compilato.py` esteso |

## Design

- **Gruppi di concorsi**: RIC (Ricercatore), DT (Tecnologo), CTER, FUNZ (Funzionario di amministrazione), COLL.AMM (Collaboratore di amministrazione), OTP (Operatore tecnico), OP.AMM (Operatore di amministrazione); dal profilo senza livello (`profili.famiglia`) e dal nome del foglio del file scorrimenti.
- **Scorrimenti** (`scorrimenti_compilato.py`): lettura anche di nominativi, N. posizioni e fogli presenti; le righe del file si raggruppano per bando e protocolli (una riga per nominativo); uno scorrimento del database si abbina al blocco con lo stesso bando e protocollo, oppure consuma un blocco dello stesso bando senza protocollo (mai due scorrimenti sullo stesso blocco senza protocollo). Controlli: manca nel file, foglio del gruppo mancante, foglio diverso dal profilo, tipologia vuota, protocollo mancante, subentro non indicato, tipologia diversa dalla segreteria, nominativi mancanti o in più rispetto alla segreteria, posizioni dichiarate diverse dai nominativi; blocchi nel file e non nel database.
- **Estrazione SOL** (`estrazione_sol.py`): lettura .xls/.xlsx per nome di colonna; graduatorie raggruppate per bando e protocollo della graduatoria; confronto in entrambe le direzioni con le graduatorie del monitoraggio (quelle con data della graduatoria fuori dal mese sono contate a parte); per persona con il foglio Graduatorie della segreteria (nominativi, posizione, punteggio); gruppo di concorsi assente; file graduatorie generato con i nominativi ordinati per gruppo, bando, punteggio decrescente, concorsi e mobilità in fogli separati.
- **Riepilogo** (`revisione.py`): totali attesi (database) e nei file per bandi, bandi con graduatoria, scorrimenti, subentri; concorsi/mobilità; per gruppo; scorrimenti per tipologia. Elenco unico di ciò che non torna con «Chiedi verifica» per bando e file.
- **Revisione**: `monitoraggio_mese.revisione_il/revisione_da/testo_revisione`; lo stato resta «aperto» (nessun cambio ai controlli esistenti); l'email va a coordinatori e persone dell'ufficio (elenco della spec 009) con link e totali.
- **Area referenti**: in consultazione, per i monitoraggi aperti, i link OneDrive; dopo la revisione, i totali.
