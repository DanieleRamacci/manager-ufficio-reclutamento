# Implementation Plan: Uso semplificato per chi consulta il monitoraggio

**Branch**: `009-uso-semplificato` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

## Summary

Sei interventi piccoli sull'app esistente (Flask + SQLite, pagine statiche in `monitoraggio/static`): accesso di 7 giorni con cookie persistente, segnalazioni "errore" e "falso positivo" con fonti, scheda "Tutti", PWA installabile senza cache dei dati, voci coordinatore per categorie protette e reclutamento speciale, avviso automatico agli RdP per ogni nuovo scorrimento.

## Technical Context

- **Language/Version**: Python 3.11, JavaScript nel browser senza build
- **Dependencies**: Flask 3.1, Flask-Session 0.5 (filesystem nel volume `DATA_DIR`); nessuna nuova dipendenza
- **Storage**: SQLite (`monitoraggio/db.py`), schema 27 → 28
- **Testing**: pytest (`tests/`)
- **Target**: Docker su Coolify, HTTPS; browser Chrome/Edge su Windows e Mac, Safari su Mac

## Constitution Check

| Principio | Esito |
|---|---|
| I. Fonti indipendenti | OK: segnalazioni e avvisi non modificano nessuna fonte; l'avviso scorrimenti legge URP e file segreteria senza derivare l'uno dall'altro |
| II. Dati nel database | OK: sessioni nel volume, segnalazioni e avvisi in SQLite; il service worker non salva dati; nessun dato a servizi esterni |
| III. Sola lettura | OK: nessuna scrittura verso SOL/URP |
| IV. Autorizzazione | OK: ruolo ricontrollato a ogni richiesta (già così in `utenti.protezioni` e `portale._serve_referente`); segnalazioni validate sul server contro le righe visibili |
| V. Tracciabilità | OK: esito di ogni avviso registrato |
| VI. Incrementale | OK: modifiche locali ai moduli esistenti, nuovo modulo `avvisi_scorrimenti.py` |

## Design

### 1. Accesso di 7 giorni (US1)
- `wsgi.py`, `__main__.py`: `SESSION_PERMANENT=True`, `PERMANENT_SESSION_LIFETIME=7 giorni`. Flask-Session dà al cookie una scadenza e salva la sessione su file nel volume: sopravvive a chiusura del browser e a riavvii.
- `accesso.DURATA_ACCESSO = 7 giorni`; `portale.DURATA_SESSIONE = 7 giorni` (l'anteprima dell'amministratore resta 8 ore con una costante propria).
- Link email invariati (15 min, monouso). Il ticket SOL resta in memoria e scade da sé: `login_required` controlla solo `accesso_fino`.

### 2. Segnalazioni (US2)
- Schema 28: `segnalazione` + colonne `tipo TEXT NOT NULL DEFAULT 'falso_positivo'` e `fonti TEXT NOT NULL DEFAULT '[]'`. Per un errore `rilievo = ''`: la chiave unica esistente (mese, chiave, atto, protocollo, data, rilievo, email) dà una segnalazione d'errore per riga e utente.
- `portale.segnala`: accetta `tipo` (`errore`/`falso_positivo`) e `fonti` ⊆ {sol, urp, segreteria}; per `errore` almeno una fonte e la riga deve essere tra quelle dell'RdP (anche senza rilievi).
- `consulta.monitoraggio` (area): per riga `errore_segnalabile` e `segnalazione_errore`; per rilievo la segnalazione include `fonti`.
- `consulta.html`: pulsante "Segnala errore" nella cella Difformità di ogni riga segnalabile; modulo comune con nota + tre spunte.
- `monitoraggi.html` scheda Segnalazioni: colonne Tipo e Fonti.

### 3. Scheda "Tutti" (US3)
- `monitoraggi.html`: prima scheda `["tutti", "Tutti", c.atti, c.difformita]`; `righeScheda` non filtra per tipo. La scheda iniziale resta "difformita".
- `consulta.html` (monitoraggio): prima scheda "Tutti"; scheda iniziale "tutti".
- Stato complessivo: la prima scheda ("Stato complessivo") mostra già tutti gli atti, sia per l'amministratore sia in consultazione: si rinomina in "Tutti gli atti" per chiarezza, senza cambiare il contenuto.

### 4. PWA (US4)
- `static/manifest.webmanifest` (nome, `start_url: "/"`, `display: standalone`, colori), `static/icona-192.png`, `icona-512.png`, `icona.svg`.
- `static/sw.js` servito da `/sw.js` (scope `/`): nessuna cache; in `fetch` di navigazione, se la rete fallisce, risponde con una pagina inline "Serve la connessione". Nessun dato salvato.
- `menu.js` (caricato da tutte le pagine): aggiunge `<link rel="manifest">`, `theme-color`, `apple-touch-icon` e registra il service worker. `accesso.html` e `referenti.html` li includono direttamente con un riquadro "Installa l'app" (Windows: Edge/Chrome → icona di installazione nella barra degli indirizzi; Mac: Chrome, oppure Safari → File → Aggiungi al Dock).
- Route pubbliche (senza login) per manifest, icone e sw.js.

### 5. Coordinatori (US5)
- `profili.py`: `CATEGORIE_PROTETTE = "Categorie protette"`, `RECLUTAMENTO_SPECIALE = "Reclutamento speciale"`; `voce()` → Mobilità per mobilità/comando, poi le due voci per le tipologie corrispondenti, altrimenti il profilo. `disponibili()` le aggiunge prima di «Mobilità»; `LIVELLI` ne dà la descrizione.
- I chiamanti (`portale`, `consulta`, `atti`) usano già `voce()`: nessun'altra modifica.

### 6. Avviso scorrimenti (US6)
- Nuovo modulo `avvisi_scorrimenti.py` e tabella `avviso_scorrimento` (schema 28): `chiave`, `bando_id`, `codice`, `protocollo`, `data`, `url_urp`, `destinatari`, `cc`, `esito` (`inviato`, `prova`, `senza_destinatari`, `errore`, `esistente`), `messaggio`, `quando`, `tentativi`; unica su (`chiave`, `protocollo`, `data`).
- Nuova attività pianificata `scorrimenti` in `attivita.py` (75 minuti dopo l'inizio, dopo il confronto fonti; disattivata finché un amministratore non la attiva) che chiama `avvisi_scorrimenti.esegui()`: se l'avviso è attivo e nessuna fonte è in attesa, prende gli atti `scorrimento` di `atti.elenco_atti` con URP e segreteria `presente`, nelle tipologie del monitoraggio; alla prima esecuzione dopo l'attivazione registra tutto come `esistente`; poi invia per quelli nuovi o in `errore`.
- Email con `posta.invia(rdp, oggetto, corpo, cc=[segreteria])`: rispetta prova/ufficiali; la copia fissa dell'ufficio si aggiunge da sé.
- Impostazioni: interruttore e orario dall'elenco delle attività; `avviso_scorrimenti_cc` (email segreteria) e `avviso_scorrimenti_iniziato` (prima esecuzione) nella tabella `impostazione`; API `/api/impostazioni/avvisi-scorrimenti` in `mensile_web.py`; sezione in `impostazioni.html` con la copia e l'elenco degli ultimi avvisi.

## Rischi
- Cookie persistente su computer condivisi: mitigato da "Esci" e dall'avviso nella pagina di accesso.
- Prima attivazione dell'avviso: la registrazione "esistente" evita un invio massivo.
- Service worker: con `skipWaiting` e senza cache non può servire versioni vecchie.
