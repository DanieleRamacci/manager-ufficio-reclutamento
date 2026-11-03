# Tasks: Solleciti mensili delle difformità

**Input**: Design documents from `/specs/005-solleciti-mensili/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/atti.md`, `quickstart.md`

**Tests**: Non sono richiesti test automatici in questa iterazione. La verifica funzionale è descritta in `quickstart.md`.

**Organization**: Task raggruppati per user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: attività in file distinti senza dipendenze incompiute
- **[Story]**: user story di `spec.md`
- Ogni task indica il file da modificare

## Phase 1: Setup

**Purpose**: preparare la navigazione delle nuove viste senza nuove dipendenze o tabelle.

- [x] T001 [P] Aggiungere la barra delle schede e il selettore del mese con mese corrente predefinito in `monitoraggio/static/riepilogo.html`.
- [x] T002 [P] Creare `monitoraggio/static/solleciti.js` come modulo browser senza persistenza, aggiungere la route Flask protetta per servirlo e comporre/copiare i testi di sollecito in `monitoraggio/static/solleciti.js` e `monitoraggio/web.py`.

## Phase 2: Foundational

**Purpose**: riusare una sola forma di riga e gli stati fonte esistenti in tutte le viste.

- [x] T003 Rifattorizzare la tabella atti in `monitoraggio/static/riepilogo.html` in un renderer riusabile con destinazione e filtri, preservando filtri, colonne, link e comportamento dell'overview esistente.
- [x] T004 Conservare in `monitoraggio/static/riepilogo.html` gli esiti di `/api/raccolta/stato` e mostrare nelle viste mensili avvisi per raccolte in corso/fallite, senza chiamarle assenze confermate.

**Checkpoint**: il renderer comune e l'indicatore di freschezza sono pronti.

## Phase 3: User Story 1 - Consultare le difformità mensili delle graduatorie (Priority: P1)

**Goal**: tabella delle graduatorie del mese con sole righe difformi.

**Independent Test**: dal selettore mese, visualizzare un mese con righe regolari e anomale; la scheda graduatorie deve mostrare solo le anomale con le colonne e le fonti dell'overview.

### Implementation

- [x] T005 [US1] Caricare `GET /api/atti?dal=&al=` per il mese selezionato e mostrare nella scheda graduatorie solo righe difformi, unendo le anomalie dei punteggi per bando/data/codice e mantenendo il record punteggi per la sottotabella candidati, in `monitoraggio/static/riepilogo.html`.
- [x] T006 [US1] Posizionare le schede “Stato complessivo”, “Graduatorie del mese” e “Scorrimenti del mese” immediatamente prima della sezione corrente e collegare i pannelli in `monitoraggio/static/riepilogo.html`.

## Phase 4: User Story 2 - Consultare le difformità mensili degli scorrimenti (Priority: P1)

**Goal**: tabella degli scorrimenti del mese con sole righe difformi.

**Independent Test**: selezionare un mese con scorrimenti regolari e anomali; mostrare solo gli scorrimenti difformi con la stessa struttura e note della tabella overview.

### Implementation

- [x] T007 [US2] Collegare la scheda scorrimenti al mese selezionato e filtrare solo righe `atto === "scorrimento" && difforme` usando il renderer comune in `monitoraggio/static/riepilogo.html`.
- [x] T008 [US2] Assicurare che le note distinguano un provvedimento presente tra gli allegati SOL da un protocollo assente nei punteggi, mantenendo i confronti esistenti senza duplicare la logica in `monitoraggio/atti.py` e `monitoraggio/static/riepilogo.html`.

## Phase 5: User Story 3 - Copiare il testo di sollecito con gli indirizzi RdP (Priority: P1)

**Goal**: un messaggio per numero bando che raggruppa tutte le difformità del mese tra codici/sedi, con indirizzi RdP copiabili separatamente, oggetto, link SOL e testo completo copiabile, non inviato.

**Independent Test**: copiare un testo da una riga difforme con RdP e uno senza email; controllare destinatari, note e assenza di dati candidati/invio.

### Implementation

- [x] T009 [US3] Comporre in `monitoraggio/static/solleciti.js` un messaggio italiano per numero bando con tutti gli atti anomali del mese di ogni codice/sede, destinatari RdP deduplicati, oggetto, link SOL e rilievi; non includere dati dei candidati.
- [x] T010 [US3] Inserire nelle sole righe anomale della tabella unificata i comandi “Copia destinatari RdP” e “Copia messaggio completo”, interrompere il click di riga e mostrare conferme/errori in `monitoraggio/static/riepilogo.html`.
- [x] T011 [US3] Aggiungere il fallback con testo visibile e selezionabile quando l'accesso agli appunti non è disponibile, senza creare richieste di invio o salvataggi server, in `monitoraggio/static/solleciti.js` e `monitoraggio/static/riepilogo.html`.

## Phase 6: Polish & Cross-Cutting

- [ ] T012 Aggiornare `specs/005-solleciti-mensili/quickstart.md` con il flusso finale della tabella unificata e completare la verifica manuale delle viste, dei dettagli punteggi, dei destinatari, della freschezza e del mancato invio.
- [x] T013 Aggiornare gli stati dei task completati in `specs/005-solleciti-mensili/tasks.md` e verificare che `spec.md`, contratto e implementazione concordino.

## Dependencies & Execution Order

### Phase Dependencies

- Setup precede Foundational.
- Foundational blocca tutte le user story perché fornisce la tabella e gli stati fonte condivisi.
- US1 e US2 condividono lo stesso mese/renderer, quindi US1 stabilisce il caricamento e US2 riusa i componenti.
- US3 dipende dal renderer (T003) e dall'ordinamento delle righe anomale (T005/T007).
- Polish segue tutte le storie.

### Parallel Opportunities

- T001 e T002 possono procedere insieme: file distinti.
- La composizione del testo (T009) può essere sviluppata mentre si completa una delle viste, una volta definiti i campi del contratto.

## Implementation Strategy

1. Completare Setup e Foundational senza modificare database o API.
2. Consegnare prima la vista graduatorie (MVP), quindi la vista scorrimenti riusando lo stesso renderer.
3. Aggiungere il testo di sollecito e la copia manuale; non attivare invio email.
4. Seguire la verifica manuale in `quickstart.md` e lasciare a una fase successiva la scelta di `mailto:` o Microsoft Graph.
