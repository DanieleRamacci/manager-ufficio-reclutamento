# Feature Specification: Monitoraggio mensile con autorizzazioni e invio email

**Feature Branch**: `006-monitoraggio-mensile`

**Created**: 2026-11-04

**Status**: Draft

**Input**: Richiesta dell'utente: accesso gestito con una tabella interna, pulsante "+ Crea monitoraggio" per ogni mese con vista degli atti, Excel rinominati, email di richiesta di compilazione e difformità con spunta di invio, invio delle email dall'app.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Autorizzare le persone dell'ufficio (Priority: P1)

L'amministratore decide chi può entrare nel sito e cosa può fare: avvia raccolte e verifiche solo lui, mentre le persone autorizzate in lettura vedono tutte le tabelle.

**Why this priority**: Il sito espone dati personali dei candidati; senza ruoli chiunque sia ammesso può anche avviare operazioni e inviare email.

**Independent Test**: Aggiungere un utente in lettura, verificare che veda le tabelle e non possa avviare una raccolta; toglierlo e verificare che la richiesta successiva venga rifiutata.

**Acceptance Scenarios**:

1. **Given** un amministratore, **When** aggiunge un nome utente con ruolo lettura, **Then** quell'utente può entrare e vedere tutte le tabelle e la modifica resta registrata con autore e data.
2. **Given** un utente in lettura, **When** prova ad avviare una raccolta, una verifica, un caricamento, un monitoraggio o un invio, **Then** l'operazione viene rifiutata e nell'interfaccia il comando non è disponibile.
3. **Given** un utente collegato, **When** l'amministratore lo toglie, **Then** la sua richiesta successiva viene rifiutata senza attendere la fine della sessione.
4. **Given** un amministratore iniziale indicato nella configurazione, **When** si tenta di toglierlo dalla pagina, **Then** l'operazione viene rifiutata, così nessuno può restare chiuso fuori.

---

### User Story 2 - Creare il monitoraggio del mese (Priority: P1)

L'amministratore preme "+ Crea monitoraggio" e sceglie il mese; l'anno è quello corrente, in automatico. Il mese dei dati è per impostazione il precedente. Si apre la pagina del monitoraggio con tutto ciò che serve: vista degli atti, Excel, email, difformità.

**Why this priority**: È il punto di partenza del lavoro mensile e raccoglie in un posto solo passaggi oggi separati.

**Independent Test**: Creare il monitoraggio di maggio 26 e verificare che il periodo proposto sia aprile 26 e che il pulsante apra la vista degli atti su quel periodo.

**Acceptance Scenarios**:

1. **Given** l'elenco dei monitoraggi, **When** l'amministratore sceglie maggio, **Then** viene creato il monitoraggio di maggio dell'anno corrente, con mese dei dati aprile, modificabile, e con i due Excel subito disponibili.
2. **Given** un monitoraggio già esistente per quel mese, **When** si tenta di crearne un altro, **Then** viene aperto quello esistente senza duplicarlo.
3. **Given** un monitoraggio, **When** un utente preme il pulsante della vista, **Then** vede la vista degli atti già esistente sul periodo dei dati.
4. **Given** un utente in lettura, **When** apre un monitoraggio, **Then** vede tutti i dati ma nessun comando di modifica o invio.

---

### User Story 3 - Scaricare gli Excel del mese (Priority: P1)

Dalla pagina del monitoraggio l'amministratore scarica i due file vuoti, già rinominati con mese e anno, per caricarli sulla cartella condivisa. Il file delle graduatorie si può scaricare anche compilato con i dati raccolti.

**Why this priority**: Oggi vanno preparati e rinominati a mano ogni mese.

**Independent Test**: Scaricare i due file di maggio 26 e controllare nomi, fogli, colonna TIPOLOGIA e contenuto del file graduatorie.

**Acceptance Scenarios**:

1. **Given** il monitoraggio di maggio 26, **When** si scarica il file degli scorrimenti, **Then** si chiama `MODELLO-scorrimenti-maggio-26.xlsx`, ha i fogli del modello e in ogni foglio la colonna TIPOLOGIA con la nota "indicare se scorrimento, subentro o per rinuncia dopo 6 mesi", senza menu a tendina.
2. **Given** lo stesso monitoraggio, **When** si scarica il file delle graduatorie, **Then** si chiama `MODELLO-Graduatorie-e-bandi-pubblicati-maggio-26.xlsx` ed è il modello vuoto; **When** si sceglie la versione con i dati, **Then** lo stesso file ha i fogli Bandi pubblicati, Mobilità pubblicate, Graduatorie pubblicate e Graduatorie mobilità compilati con il periodo.
3. **Given** una graduatoria senza numero di protocollo, **When** si apre il file con i dati, **Then** le sue righe sono evidenziate in giallo.
4. **Given** una verifica dei punteggi non eseguita in questa sessione, **When** si scarica il file con i dati, **Then** la pagina avvisa che i fogli delle graduatorie sono incompleti e invita a lanciare la verifica.

---

### User Story 4 - Inviare la richiesta di compilazione (Priority: P2)

L'amministratore incolla i link dei file condivisi, controlla il testo generato e lo invia ai destinatari impostati nell'app, oppure lo copia.

**Why this priority**: Evita di riscrivere ogni mese la stessa email, ma dipende dalla disponibilità dei file condivisi.

**Independent Test**: Inserire i due link, controllare che compaiano nel testo con mese e periodo corretti e inviare in modalità di prova.

**Acceptance Scenarios**:

1. **Given** il modello dell'email, **When** si apre il monitoraggio di maggio 26, **Then** il testo riporta maggio 26, il mese dei dati aprile, i nomi dei file, la cartella e i link inseriti.
2. **Given** un link non ancora inserito, **When** si prova a inviare, **Then** l'invio è bloccato e la pagina indica cosa manca.
3. **Given** i destinatari impostati, **When** l'amministratore conferma l'invio, **Then** l'email parte e resta registrato chi l'ha inviata, quando e a chi.
4. **Given** il testo modificato in un monitoraggio, **When** viene salvato, **Then** vale per quel mese; il modello generale si modifica a parte e vale per i mesi successivi.

---

### User Story 5 - Sollecitare gli RdP sulle difformità (Priority: P1)

Nella pagina del monitoraggio l'amministratore vede le difformità del periodo per bando, controlla l'anteprima e invia una email per bando agli RdP, oppure spunta che l'ha già inviata da fuori.

**Why this priority**: È l'obiettivo del monitoraggio: i rilievi devono arrivare ai responsabili e deve restare traccia di cosa è stato inviato.

**Independent Test**: In modalità di prova inviare il sollecito di un bando e verificare che risulti inviato; spuntarne a mano un altro.

**Acceptance Scenarios**:

1. **Given** un bando con difformità nel periodo, **When** l'amministratore apre l'anteprima, **Then** vede destinatari, oggetto e testo con i soli rilievi di quel bando, senza dati dei candidati.
2. **Given** l'anteprima, **When** preme Invia, **Then** l'email parte e il bando risulta "inviata" con data e autore; **When** l'invio fallisce, **Then** il bando non risulta inviato e compare l'errore.
3. **Given** un'email inviata da fuori, **When** l'amministratore la spunta, **Then** il bando risulta "inviata a mano" con data e autore; la spunta si può togliere.
4. **Given** un bando senza email degli RdP, **When** si apre l'anteprima, **Then** l'invio è bloccato e resta possibile la spunta manuale.
5. **Given** un sollecito già inviato, **When** l'amministratore preme di nuovo Invia, **Then** la pagina chiede conferma prima di inviarlo ancora.

---

### User Story 6 - Chiudere il monitoraggio (Priority: P1)

Finito il lavoro del mese, l'amministratore chiude il monitoraggio. Atti, difformità, solleciti e conteggi dei punteggi vengono salvati nel database e non cambiano più, anche se cambiano le fonti.

**Why this priority**: Un monitoraggio concluso è un documento di lavoro: deve restare consultabile così com'era e sopravvivere a ogni aggiornamento dell'applicazione.

**Independent Test**: Chiudere un mese, modificare i dati raccolti, rifare il deploy e verificare che la pagina mostri gli stessi dati e che invii e modifiche siano rifiutati.

**Acceptance Scenarios**:

1. **Given** un monitoraggio aperto, **When** l'amministratore lo chiude, **Then** tutte le righe del periodo con stati, protocolli, RdP, rilievi e solleciti vengono salvate in un'unica operazione, senza dati dei candidati.
2. **Given** un monitoraggio chiuso, **When** cambiano le fonti, **Then** la sua pagina mostra ancora i dati della chiusura.
3. **Given** un monitoraggio chiuso, **When** si tenta di modificarlo o di inviare email, **Then** l'operazione viene rifiutata finché non viene riaperto; apertura e chiusura restano registrate.
4. **Given** un server senza volume persistente, **When** si apre il sito, **Then** ogni pagina mostra un avviso che i dati andranno persi al prossimo deploy.

---

### Edge Cases

- Servizio email non configurato: la pagina lo segnala, restano copia del testo e spunta manuale.
- Modalità di prova attiva: tutte le email vanno a un solo indirizzo, con i destinatari reali indicati nel testo, e la pagina mostra chiaramente la modalità. Un invio di prova non segna il bando come inviato.
- Difformità che cambiano dopo l'invio: la registrazione dell'invio resta; la pagina mostra se dopo l'invio sono comparsi nuovi rilievi.
- Fonte non raggiunta nell'ultima raccolta: la pagina mostra lo stato delle fonti prima delle difformità.
- Riavvio del server: i dati dei candidati in memoria si perdono e la verifica va ripetuta; monitoraggi e invii restano.
- Destinatario con indirizzo non valido: l'invio è bloccato e l'indirizzo viene indicato.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Il sistema MUST gestire gli utenti con due ruoli: amministratore e lettura.
- **FR-002**: Gli amministratori MUST poter aggiungere, togliere e cambiare ruolo agli utenti da una pagina dedicata; ogni modifica MUST registrare autore e data.
- **FR-003**: Le persone indicate nella configurazione MUST essere sempre amministratori e non MUST poter essere tolte dalla pagina.
- **FR-004**: Autenticazione e ruolo MUST essere verificati nel server a ogni richiesta, con entrambi i metodi di accesso (ticket di Selezioni Online e SSO).
- **FR-005**: Raccolte, verifiche, caricamenti, creazione di monitoraggi, modifiche e invii MUST essere riservati agli amministratori.
- **FR-006**: Gli amministratori MUST poter creare un monitoraggio scegliendo il mese, nell'anno corrente, al massimo uno per mese, con mese dei dati modificabile e predefinito sul precedente.
- **FR-007**: La pagina del monitoraggio MUST offrire: accesso alla vista degli atti sul periodo dei dati, i due Excel, l'email di richiesta di compilazione e le difformità del periodo.
- **FR-008**: Il file degli scorrimenti MUST avere il nome `MODELLO-scorrimenti-<mese>-<aa>.xlsx` e, in ogni foglio del modello, la colonna TIPOLOGIA con la nota indicata e senza menu a tendina.
- **FR-009**: Il file delle graduatorie MUST avere il nome `MODELLO-Graduatorie-e-bandi-pubblicati-<mese>-<aa>.xlsx` ed essere vuoto; a richiesta MUST essere disponibile compilato con i dati del periodo nei quattro fogli del modello, con in giallo le graduatorie senza numero di protocollo.
- **FR-010**: I dati dei candidati MUST NOT essere salvati nel database: compaiono solo nei file generati, dalla verifica in memoria.
- **FR-011**: Il modello dell'email di richiesta MUST essere modificabile dagli amministratori, con segnaposto per mese, mese dei dati, nomi dei file, cartella e link dei file condivisi.
- **FR-012**: I destinatari dell'email di richiesta MUST essere impostabili dall'app.
- **FR-013**: Il sistema MUST preparare una email per ogni codice (sotto-bando) con difformità, indirizzata ai soli RdP di quel codice e contenente solo i suoi rilievi e il suo link. Nei bandi con più codici gli RdP sono diversi per codice: le email MUST NOT accorparli.
- **FR-014**: Le email MUST partire solo dopo un'azione esplicita di un amministratore, mai in automatico.
- **FR-015**: Ogni invio MUST registrare esito, data, autore, destinatari e oggetto; un bando MUST risultare inviato solo a invio riuscito.
- **FR-016**: Gli amministratori MUST poter spuntare o togliere a mano lo stato di invio, distinto dall'invio dall'app.
- **FR-017**: Le email MUST NOT contenere dati dei candidati.
- **FR-018**: Il sistema MUST inviare tramite il server di posta configurato, con mittente e indirizzo di risposta configurabili; senza configurazione l'invio MUST essere disattivato restando disponibili copia e spunta.
- **FR-019**: Gli amministratori MUST poter attivare e disattivare da una pagina Impostazioni la modalità di prova, che recapita tutto a un solo indirizzo senza segnare i bandi come inviati. La scelta MUST restare salvata nel database; finché nessuno sceglie, la modalità di prova MUST essere attiva. Disattivarla MUST richiedere una conferma. I link di accesso MUST arrivare sempre alla persona che li chiede.
- **FR-020**: La pagina di accesso MUST offrire il pulsante "Accedi come visualizzatore autorizzato": chi è autorizzato riceve nella propria casella un link monouso valido 15 minuti ed entra in sola lettura, anche se il suo ruolo è amministratore. Il sistema MUST NOT rivelare chi è autorizzato e MUST inviare il link solo all'indirizzo registrato.

- **FR-021**: Le viste delle graduatorie e degli scorrimenti del mese MUST permettere di filtrare per tipologia monitorata: tempo indeterminato (concorsi pubblici) e mobilità. Reclutamento speciale, comandi e categorie protette restano nella raccolta e nello Stato complessivo ma non fanno parte del monitoraggio mensile (decisioni dell'utente del 2026-11-05 e 2026-11-06). Le righe senza tipologia nota MUST restare visibili.

- **FR-022**: Gli amministratori MUST poter chiudere e riaprire un monitoraggio; la chiusura MUST salvare nel database una fotografia immutabile del mese, senza dati dei candidati, e MUST impedire modifiche e invii finché resta chiuso.
- **FR-023**: Il sistema MUST avvisare in modo evidente se i dati non sono su un volume persistente.

- **FR-024**: Gli amministratori MUST poter generare, per un monitoraggio chiuso, una nuova versione dai dati attuali, con un motivo facoltativo e senza riaprirlo. Ogni versione MUST restare consultabile con i suoi conteggi, e il sistema MUST segnalare se dopo l'ultima versione ci sono state raccolte o verifiche dei punteggi.

- **FR-025**: La pagina Impostazioni MUST riunire email, utenti e aggiornamenti.
- **FR-026**: Gli amministratori MUST poter vedere quando è stato completato ogni aggiornamento, con esito e conteggi, e MUST poter scegliere l'orario di quello giornaliero e il giorno di quello completo.
- **FR-027**: Il sistema MUST poter avvisare via email l'amministratore alla fine di un aggiornamento (solo i completi, tutti, oppure mai), segnalando anche quelli non riusciti; l'avviso arriva sempre all'indirizzo scelto, anche con le email di prova attive, e contiene solo conteggi.

### Key Entities

- **Utente**: nome utente, ruolo, email facoltativa, attivo, autore e data dell'ultima modifica.
- **Monitoraggio**: mese, periodo dei dati, link dei file condivisi, testo dell'email di richiesta, autore e data di creazione.
- **Impostazioni email**: modello del testo e destinatari della richiesta di compilazione.
- **Versione del monitoraggio**: mese, numero, autore, data, motivo; ogni versione ha le sue righe, i suoi punteggi e lo stato delle fonti.
- **Sollecito**: monitoraggio, bando, stato (inviata, inviata a mano), autore, data, destinatari, oggetto, rilievi al momento dell'invio.
- **Registro invii**: ogni tentativo di invio con esito e motivo dell'errore.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: La preparazione del monitoraggio mensile, dalla creazione ai file pronti, richiede meno di 5 minuti.
- **SC-002**: Il 100% delle operazioni riservate viene rifiutato per gli utenti in lettura.
- **SC-003**: Togliere un utente ha effetto sulla sua richiesta successiva.
- **SC-004**: Per ogni mese si può sapere in meno di un minuto quali bandi con difformità hanno ricevuto il sollecito, da chi e quando.
- **SC-005**: Nessuna email inviata contiene dati dei candidati.
- **SC-006**: Il sollecito di un bando si invia in meno di 30 secondi, senza riscrivere il testo.

## Assumptions

- Il mese del monitoraggio e il periodo dei dati sono distinti: il monitoraggio di maggio riguarda di norma i dati di aprile, come nell'email in uso.
- "Numero di graduatoria" nell'email in uso significa numero di protocollo della graduatoria, come nell'estrazione già esistente.
- I modelli non hanno intestazioni nei fogli del file graduatorie: si usano quelle dell'estrazione Punteggi di Selezioni Online per le graduatorie e codice, sede, struttura, posti, profilo, protocollo e data per i bandi.
- I file vengono generati al momento e non restano salvati nell'app. Il file degli scorrimenti lo compilano i colleghi. La colonna TIPOLOGIA non diventa un menu a tendina, così le fonti restano indipendenti.
- I link dei file condivisi vengono inseriti a mano dopo il caricamento su Drive: l'app non scrive sulla cartella condivisa.
- Il server di posta iniziale è `smtp.cnr.it`, porta 25, senza STARTTLS, mittente `noreply@monitoraggio.concorsi.cnr.it`, risposta a `daniele.ramacci@cnr.it`. Va provato dal server di produzione.
- L'invio di email è una scrittura verso un sistema esterno: questa spec la approva ai sensi del Principio III della constitution, limitatamente alle azioni esplicite qui descritte.
