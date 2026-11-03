# Feature Specification: Graduatorie e punteggi da Selezioni Online (sessione utente)

**Feature Branch**: `004-punteggi-sol` (spec scritta sul branch `001-raccolta-dati-bandi`)

**Created**: 2026-10-29

**Status**: Draft

**Input**: "Mettere in dashboard il link per fare il login e poi prendere il cookie; estrarre per il
mese corrente o precedente le graduatorie per cui è stato caricato un documento di graduatoria e
vedere se hanno messo i punteggi."

## Contesto

L'estrazione "Punteggi" di Selezioni Online (`GET /rest/call/applications.xls?type=score`) ha le
colonne del foglio "Graduatorie pubblicate" del file del mese (codice bando, sede, struttura,
posti, profilo, candidato, punteggio, graduatoria, esito, protocolli della graduatoria e
dell'assunzione idoneo). Richiede il login. Il login con il Keycloak di produzione non è ancora
disponibile per questa app (spec 003): in locale si usa la sessione del sito di Selezioni Online.
L'app non può leggere il cookie di un altro sito (sicurezza del browser, cookie `ticket` HttpOnly,
durata un'ora): apre una finestra di Chrome con profilo temporaneo, l'utente fa il login, l'app
legge il `ticket` da quella finestra e lo verifica con `POST /openapi/security/validate`.

## User Scenarios & Testing

### User Story 1 - Collegare Selezioni Online dalla dashboard (P1)

Dal menu "Collega Selezioni Online" si apre una finestra di Chrome sulla pagina di login di
Selezioni Online; dopo il login la finestra si chiude e il menu mostra "SOL collegato fino alle
HH:MM". "Scollega" dimentica la sessione.

**Acceptance**: ticket solo in memoria, mai su disco, nel database o nei log; scaduto dopo 55
minuti; finestra chiusa o login non completato in 5 minuti → errore mostrato nel menu; funzione
disponibile solo nel server locale.

### User Story 2 - Punteggi delle graduatorie del mese (P1)

Scelto il mese (corrente o precedente), l'app individua i bandi con graduatoria pubblicata nel
mese, legge con la sessione le domande e mostra per ogni graduatoria: domande, con punteggio,
in graduatoria, e lo stato "punteggi completi / mancanti".

### User Story 3 - Foglio "Graduatorie pubblicate" del file del mese (P2)

L'estrazione per candidato viene inserita nel foglio "Graduatorie pubblicate" del file
`Graduatorie-e-bandi-pubblicati-<mese>-<aa>.xlsx` generato dall'app (con i fogli Bandi, Mobilità e
Graduatorie mobilità), pronto per la cartella condivisa. I dati per candidato non vengono salvati
nel database: passano solo nel file generato.

## Requirements

- **FR-001**: Solo letture verso Selezioni Online con la sessione dell'utente; nessuna password
  inserita o salvata nell'app.
- **FR-002**: Il ticket MUST restare in memoria del processo locale e MUST NOT comparire in log,
  risposte API, database o file.
- **FR-003**: Il collegamento con finestra di login MUST essere disponibile solo nel server locale;
  in produzione si userà il login SSO (spec 003).
- **FR-004**: Il riepilogo per graduatoria MUST salvare solo conteggi (domande, con punteggio, in
  graduatoria), non dati dei candidati (constitution, Principio II).
- **FR-005**: Il file del mese MUST contenere i dati per candidato solo se richiesto dall'utente e
  MUST NOT essere salvato sul server.
- **FR-006**: L'obiettivo è avere Selezioni Online allineato alle fonti (URP, file della segreteria,
  allegati SOL). Ogni difformità MUST essere segnalata in rosso nella tabella degli atti, nella sezione
  punteggi e nella tendina dei candidati:
  - graduatoria nota da URP o dal file ma senza punteggi su SOL ("mancano i punteggi su SOL"), o con
    punteggi solo per una parte delle domande;
  - candidati con punteggi ma protocollo della graduatoria non valorizzato, oppure diverso o con data
    diversa da quello delle fonti; esito V/I/S mancante;
  - graduatoria non allegata su SOL;
  - scorrimenti: candidati S senza protocollo di assunzione idoneo; protocollo di assunzione idoneo
    che non compare in nessuna fonte o con data diversa; atto di scorrimento delle fonti nel periodo
    senza nessun candidato S con quel protocollo ("non registrato su SOL"); protocollo di assunzione
    idoneo valorizzato con esito diverso da S.
- **FR-007**: Per ogni graduatoria o scorrimento, anche se noto solo da URP o dal file della segreteria,
  MUST esserci il link alla pagina dei punteggi del concorso su SOL (`carica-punteggi?callId=`), anche
  nella tendina dei candidati e nel dettaglio del bando.
- **FR-008**: Nel database MUST finire solo conteggi e protocolli pubblici degli scorrimenti (numero di
  candidati S per protocollo), mai nominativi.

## Assumptions

- La sessione ottenuta dalla pagina di Selezioni Online vale per le API REST (`Cookie: ticket=...`).
- Il nome della cartella e dei file del mese segue il modello `Graduatorie-e-bandi-pubblicati-
  <mese>-<aa>.xlsx` (da confermare con l'utente).
