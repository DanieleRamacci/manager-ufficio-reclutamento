# Feature Specification: Tracciamento delle difformità del monitoraggio

**Feature Branch**: `011-tracciamento-difformita`

**Created**: 2026-11-05

**Status**: Implementata; verifica nell'app pendente

**Input**: Richiesta dell'utente: una difformità non deve sparire quando viene corretta. Deve restare salvata in modo comprensibile, mostrare un badge "corretta" dopo l'aggiornamento notturno e potersi riverificare subito con un pulsante, su una o su tutte.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Seguire una difformità fino alla correzione (Priority: P1)

Nel monitoraggio ogni difformità resta in elenco con i rilievi originali e un badge: da correggere, parzialmente corretta, corretta, oppure da controllare.

**Independent Test**: Registrare una difformità, correggerla nella fonte, aggiornare e verificare che risulti corretta con data, senza sparire.

**Acceptance Scenarios**:

1. **Given** una difformità rilevata, **When** viene corretta e i dati si aggiornano, **Then** resta in elenco come corretta, con data e con i rilievi originali.
2. **Given** una difformità con due rilievi, **When** ne viene risolto uno, **Then** risulta parzialmente corretta e mostra quale rilievo è risolto.
3. **Given** una difformità corretta, **When** ricompare, **Then** torna da correggere e lo storico lo registra.
4. **Given** un atto che non si trova più in nessuna fonte, **When** si aggiorna, **Then** la difformità risulta da controllare, non corretta.
5. **Given** l'ultima raccolta di una fonte non riuscita, **When** si aggiorna, **Then** nessuna difformità viene segnata come corretta.

### User Story 2 - Verificare subito (Priority: P1)

L'amministratore non aspetta la notte: preme Verifica su una difformità o Verifica tutte.

**Acceptance Scenarios**:

1. **Given** una difformità, **When** preme Verifica, **Then** il sistema rilegge SOL e URP per quel bando, e i punteggi se Selezioni Online è collegato, e aggiorna il badge.
2. **Given** Selezioni Online non collegato, **When** verifica, **Then** il risultato dice che i punteggi non sono stati riletti.
3. **Given** un monitoraggio chiuso, **When** si verifica, **Then** il badge si aggiorna e le versioni salvate non cambiano.

## Requirements *(mandatory)*

- **FR-001**: Il sistema MUST salvare nel database ogni difformità di ogni monitoraggio con i rilievi iniziali e attuali, leggibili, senza dati dei candidati.
- **FR-002**: Lo stato MUST aggiornarsi da solo dopo ogni raccolta, verifica dei punteggi e caricamento del file della segreteria, anche per i mesi chiusi.
- **FR-003**: Il sistema MUST segnare corretta una difformità solo se l'atto è presente e non è più difforme, e solo se le ultime raccolte delle fonti sono riuscite.
- **FR-004**: Gli amministratori MUST poter riverificare una difformità o tutte quelle aperte, con avanzamento visibile.
- **FR-005**: Ogni passaggio di stato MUST restare nello storico con data e origine.
- **FR-006**: I rilievi MUST essere quelli mostrati dalla pagina delle difformità e usati nelle email.

## Assumptions

- La verifica rilegge solo gli allegati del bando interessato: un bando nuovo o una nuova pagina URP si vede con l'aggiornamento generale.
- Una correzione dei punteggi si vede solo dopo una verifica dei punteggi, che richiede Selezioni Online collegato.
