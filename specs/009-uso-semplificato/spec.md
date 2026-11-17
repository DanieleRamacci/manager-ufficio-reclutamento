# Feature Specification: Uso semplificato per chi consulta il monitoraggio

**Feature Branch**: `009-uso-semplificato`

**Created**: 2026-11-16

**Status**: Implementata; verifica nell'app pendente

**Input**: Richiesta dell'utente: rendere più semplice il lavoro di chi usa il monitoraggio. Accesso che dura giorni invece di dover rigenerare spesso il link; pulsante per segnalare un errore su ogni riga, anche senza difformità, con nota e indicazione della fonte sbagliata; una scheda con tutti gli atti prima di quella delle difformità; app installabile sul desktop (PWA), su Mac e su Windows; bandi di categorie protette e reclutamento speciale tolti al coordinatore del profilo, ma lasciati nel sistema.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Restare collegati per giorni (Priority: P1)

Un visualizzatore, un referente o un amministratore entra una volta e resta collegato per 7 giorni, anche se chiude il browser o l'app installata e riaccende il computer. Non deve chiedere un nuovo link ogni volta che apre il monitoraggio.

**Why this priority**: oggi l'accesso si perde alla chiusura del browser e dopo 8–12 ore; ogni volta serve un nuovo link via email. È il disagio più frequente.

**Independent Test**: Entrare con il link email, chiudere completamente il browser, riaprirlo il giorno dopo sulla pagina del monitoraggio: si è ancora dentro, senza nuovo link.

**Acceptance Scenarios**:

1. **Given** un visualizzatore entrato con il link email, **When** chiude il browser e lo riapre entro 7 giorni, **Then** vede il monitoraggio senza dover rientrare.
2. **Given** un referente entrato nell'area referenti, **When** torna entro 7 giorni, **Then** vede i propri bandi senza nuovo link.
3. **Given** un accesso aperto da più di 7 giorni, **When** l'utente apre una pagina, **Then** viene mandato alla pagina di accesso e, dopo essere rientrato, torna alla pagina che aveva chiesto.
4. **Given** un utente collegato, **When** preme "Esci", **Then** l'accesso finisce subito su quel browser.
5. **Given** un utente collegato a cui un amministratore toglie l'autorizzazione, **When** apre una pagina, **Then** non vede più i dati, anche se i 7 giorni non sono passati.
6. **Given** un amministratore collegato da ieri, **When** usa una funzione che legge Selezioni Online, **Then** gli viene chiesto di ricollegare Selezioni Online, ma non di rientrare nel sito.

---

### User Story 2 - Segnalare un errore su qualsiasi riga (Priority: P1)

Nell'area referenti e nelle pagine di consultazione, ogni riga di atto ha un pulsante "Segnala errore", anche quando non ci sono difformità (per esempio un dato mostrato come presente ma sbagliato). Sui rilievi delle righe difformi resta il pulsante "Segnala falso positivo". In entrambi i casi l'utente scrive una nota e spunta in quale delle tre fonti i dati non sono corretti: Selezioni Online, URP, file di riepilogo della segreteria.

**Why this priority**: oggi si può segnalare solo un falso positivo; un errore su una riga "in regola" non ha modo di arrivare all'ufficio, e non si sa quale fonte va corretta.

**Independent Test**: Da referente, su una riga senza difformità premere "Segnala errore", scrivere una nota, spuntare "URP", inviare; da amministratore vederla nella scheda Segnalazioni del monitoraggio con tipo "errore" e fonte "URP".

**Acceptance Scenarios**:

1. **Given** una riga senza difformità tra i propri bandi, **When** il referente preme "Segnala errore", scrive la nota, spunta una o più fonti e invia, **Then** la segnalazione è salvata e la riga mostra "segnalato il <data>".
2. **Given** un rilievo di una riga difforme, **When** il referente preme "Segnala falso positivo", **Then** il modulo ha la stessa nota obbligatoria e le stesse spunte delle fonti.
3. **Given** un modulo senza nota, **When** l'utente invia, **Then** l'invio è rifiutato con un messaggio che chiede il motivo.
4. **Given** una segnalazione "errore" senza nessuna fonte spuntata, **When** l'utente invia, **Then** l'invio è rifiutato con un messaggio che chiede di indicare almeno una fonte.
5. **Given** una segnalazione già inviata, **When** l'utente la riapre, **Then** vede la nota e le fonti spuntate e può modificarle; la segnalazione torna "da vedere".
6. **Given** una segnalazione inviata, **When** l'amministratore apre la scheda Segnalazioni del monitoraggio, **Then** vede tipo (errore o falso positivo), atto, fonti indicate, nota, autore e data, e può segnarla gestita.
7. **Given** un monitoraggio chiuso o con fonti in aggiornamento, **When** l'utente apre la pagina, **Then** i pulsanti di segnalazione non sono attivi e il motivo è indicato.
8. **Given** un visualizzatore in sola lettura senza bandi propri, **When** apre la pagina, **Then** vede i pulsanti solo se il ruolo gli consente di segnalare (come oggi per il falso positivo).

---

### User Story 3 - Vedere tutti gli atti in una scheda (Priority: P2)

Nello Stato complessivo e nel dettaglio di un Monitoraggio, sia nelle pagine dell'amministratore sia in quelle di consultazione, la prima scheda è "Tutti": elenca tutti gli atti senza filtro per tipo o difformità. Seguono le schede esistenti ("Tutte le difformità", "Bandi pubblicati", "Graduatorie pubbliche", …).

**Why this priority**: per controllare un bando oggi bisogna sapere in quale scheda cercarlo; una vista unica è il punto di partenza naturale.

**Independent Test**: Aprire un monitoraggio: la prima scheda è "Tutti (N)", con N uguale al numero totale di atti, e mostra anche le righe senza difformità.

**Acceptance Scenarios**:

1. **Given** il dettaglio di un monitoraggio, **When** si apre, **Then** le schede iniziano con "Tutti (N)", seguita da "Tutte le difformità".
2. **Given** la scheda "Tutti", **When** si usano i filtri esistenti (tipologia, testo, RdP, solo con difformità), **Then** funzionano come nelle altre schede.
3. **Given** lo Stato complessivo, **When** si apre, **Then** la prima scheda è "Tutti" con tutti gli atti del periodo, prima delle schede del mese.
4. **Given** la prima apertura di una pagina, **When** si carica, **Then** il monitoraggio dell'amministratore apre la scheda delle difformità come oggi, mentre le pagine di consultazione aprono "Tutti".

---

### User Story 4 - Installare l'app sul computer (Priority: P2)

Un utente apre il monitoraggio nel browser e lo installa come app: compare un'icona sul desktop (o nel Dock / nel menu Start) che apre il monitoraggio in una finestra propria, senza barra degli indirizzi. Funziona su Windows e su Mac.

**Why this priority**: chi consulta il monitoraggio ogni giorno lo ritrova come un programma, senza cercare il link.

**Independent Test**: Su Windows con Edge o Chrome, aprire il sito, scegliere "Installa app", chiudere il browser, aprire l'icona dal desktop: si apre il monitoraggio già collegato.

**Acceptance Scenarios**:

1. **Given** Chrome o Edge su Windows o Mac, **When** l'utente apre il sito, **Then** il browser propone l'installazione e l'app compare tra i programmi (menu Start / desktop su Windows, Launchpad / Dock su Mac).
2. **Given** Safari su Mac, **When** l'utente usa "Aggiungi al Dock", **Then** l'app si apre in una finestra propria con il nome e l'icona del monitoraggio.
3. **Given** l'app installata e un accesso valido, **When** l'utente la apre, **Then** arriva sulla pagina iniziale del suo ruolo senza rientrare (Chrome/Edge condividono l'accesso con il browser).
4. **Given** il computer senza rete, **When** l'utente apre l'app, **Then** vede un messaggio chiaro "Serve la connessione" e nessun dato salvato.
5. **Given** una nuova versione del sito, **When** l'utente riapre l'app, **Then** vede la versione nuova senza reinstallare.
6. **Given** una pagina con le istruzioni di installazione, **When** l'utente la apre, **Then** trova i passi per Windows (Edge/Chrome) e Mac (Chrome/Safari).

---

### User Story 5 - Coordinatori: categorie protette e reclutamento speciale fuori dal profilo (Priority: P1)

Un bando di categorie protette o di reclutamento speciale ha un profilo (per esempio Collaboratore tecnico enti di ricerca), ma non è gestito dal coordinatore di quel profilo: non fa parte dei bandi pubblici del profilo. Oggi finisce comunque al coordinatore del profilo. Questi bandi passano a due voci a sé, "Categorie protette" e "Reclutamento speciale", che funzionano come "Mobilità": ognuna ha al più un coordinatore e copre i bandi di quel tipo di ogni profilo. I bandi restano nel sistema: stato complessivo, monitoraggio e area dei loro RdP non cambiano.

**Why this priority**: oggi il coordinatore CTER vede e riceve atti che non gestisce; le comunicazioni vanno alla persona sbagliata.

**Independent Test**: Con un bando di categorie protette di profilo CTER, il coordinatore di "Collaboratore tecnico enti di ricerca" non lo vede più tra i suoi bandi; il coordinatore che prende "Categorie protette" lo vede; il bando resta nello stato complessivo e il suo RdP lo vede come prima.

**Acceptance Scenarios**:

1. **Given** un bando di categorie protette di profilo CTER, **When** il coordinatore del profilo CTER apre l'area, **Then** il bando non compare tra i suoi.
2. **Given** lo stesso bando, **When** un coordinatore ha preso la voce "Categorie protette", **Then** il bando compare tra i suoi.
3. **Given** un bando di reclutamento speciale, **When** si guardano i coordinatori, **Then** vale lo stesso con la voce "Reclutamento speciale".
4. **Given** nessuno ha preso la voce "Categorie protette", **When** si apre lo stato complessivo o l'area dell'RdP, **Then** il bando c'è come prima; nessun coordinatore lo vede.
5. **Given** l'elenco delle voci tra cui un coordinatore sceglie, **When** lo apre, **Then** trova "Categorie protette" e "Reclutamento speciale" con la descrizione "tutti i bandi di questo tipo, di ogni profilo", prenotabili e cedibili come "Mobilità".
6. **Given** un bando di categorie protette di mobilità, **When** si assegna la voce, **Then** vale "Mobilità" (la mobilità resta prioritaria, come oggi).
7. **Given** le comunicazioni ai referenti con il coordinatore in copia, **When** riguardano un bando di categorie protette o di reclutamento speciale, **Then** in copia va il coordinatore della voce corrispondente, non quello del profilo.

---

### User Story 6 - Avviso automatico ai referenti per ogni nuovo scorrimento (Priority: P1)

Dopo ogni aggiornamento notturno, quando viene pubblicato uno scorrimento/utilizzo di graduatoria nuovo, trovato nel file della segreteria e/o su URP, il sistema scrive agli RdP del bando che fanno parte dell'ufficio: "abbiamo rilevato dal file della segreteria e da URP (oppure solo da uno dei due) la pubblicazione di uno scorrimento", con data, protocollo e link al documento su URP, e chiede, se lo scorrimento non è stato loro notificato, di richiedere il provvedimento a chi se n'è occupato. In copia va l'indirizzo della segreteria indicato nelle Impostazioni. L'email automatica riguarda solo lo scorrimento: le difformità, compreso lo scorrimento mancante su Selezioni Online, restano nell'email manuale del monitoraggio (scelta dell'utente del 2026-11-17).

**Why this priority**: oggi gli RdP scoprono gli scorrimenti solo con il monitoraggio mensile.

**Independent Test**: Con l'avviso attivo e le email in prova, caricare un file della segreteria con uno scorrimento nuovo; dopo l'aggiornamento notturno arriva all'indirizzo di prova un'email per gli RdP dell'ufficio; all'aggiornamento successivo non ne arriva una seconda.

**Acceptance Scenarios**:

1. **Given** un nuovo scorrimento nel file della segreteria e su URP, **When** finisce l'aggiornamento notturno, **Then** parte un'email agli RdP dell'ufficio che dice "dal file della segreteria e da URP", con il link URP, in copia la segreteria.
2. **Given** un nuovo scorrimento solo nel file della segreteria (o solo su URP), **When** finisce l'aggiornamento, **Then** l'email dice da quale fonte è stato rilevato; il link URP c'è solo se è su URP.
3. **Given** uno scorrimento già avvisato, **When** finiscono gli aggiornamenti successivi, **Then** non parte un'altra email, anche se cambiano le sue difformità.
4. **Given** l'avviso appena attivato, **When** gira il primo aggiornamento, **Then** gli scorrimenti già presenti vengono registrati come "già esistenti" senza email.
5. **Given** un bando con RdP interni ed esterni all'ufficio, **When** parte l'avviso, **Then** lo ricevono solo gli interni; se nessuno è interno l'avviso resta registrato "nessun RdP dell'ufficio".
6. **Given** le email in modalità di prova, **When** parte un avviso, **Then** arriva solo all'indirizzo di prova con i destinatari reali nel testo.
7. **Given** un invio non riuscito, **When** si apre l'elenco degli avvisi, **Then** risulta "non inviato" con il motivo e viene ritentato all'aggiornamento successivo.
8. **Given** l'avviso disattivato o l'elenco delle persone dell'ufficio vuoto, **When** finisce l'aggiornamento, **Then** non parte nessuna email.

### Edge Cases

- Computer condiviso: l'accesso di 7 giorni resta valido finché non si preme "Esci"; la pagina di accesso lo ricorda.
- Utente cancellato o con ruolo cambiato durante i 7 giorni: vale il ruolo attuale a ogni richiesta, non quello del momento dell'accesso.
- Riavvio del server: gli accessi aperti restano validi (sono salvati nel volume dei dati, non in memoria); il collegamento a Selezioni Online invece va rifatto.
- App installata in Safari: Safari tiene un accesso separato da quello del browser, quindi la prima volta l'utente entra dall'interno dell'app; il link email si apre nel browser predefinito e non nell'app [vedi Assumptions].
- Segnalazione su una riga che nel frattempo è cambiata (protocollo o data diversi): rifiutata con "ricarica la pagina", come oggi.
- Nota con dati dei candidati (es. codice fiscale): rifiutata, come oggi.
- Due segnalazioni dello stesso utente sulla stessa riga e stesso tipo: la seconda aggiorna la prima.

## Requirements *(mandatory)*

### Functional Requirements

**Accesso**

- **FR-001**: L'accesso al sito (visualizzatore con link email, utente con ticket di Selezioni Online, referente dell'area referenti) MUST durare 7 giorni dall'ingresso e MUST sopravvivere alla chiusura del browser e dell'app installata.
- **FR-002**: Il link di accesso inviato via email MUST restare monouso e valido 15 minuti.
- **FR-003**: Autorizzazione e ruolo MUST essere ricontrollati a ogni richiesta: togliere un utente MUST chiudere il suo accesso alla richiesta successiva.
- **FR-004**: "Esci" MUST chiudere subito l'accesso su quel browser o app.
- **FR-005**: Il collegamento a Selezioni Online MUST continuare a scadere secondo Selezioni Online; la sua scadenza MUST NOT far uscire l'utente dal sito.
- **FR-006**: Gli accessi aperti MUST restare validi dopo un riavvio o un nuovo rilascio del server.

**Segnalazioni**

- **FR-007**: Nell'area referenti e nelle pagine di consultazione del monitoraggio, ogni riga di atto segnalabile MUST avere un pulsante "Segnala errore", anche senza difformità.
- **FR-008**: Ogni rilievo di una riga difforme MUST mantenere il pulsante "Segnala falso positivo".
- **FR-009**: Entrambe le segnalazioni MUST richiedere una nota (massimo 1000 caratteri, senza dati dei candidati) e MUST offrire tre spunte: Selezioni Online, URP, file di riepilogo della segreteria.
- **FR-010**: Una segnalazione "errore" MUST avere almeno una fonte spuntata; per un "falso positivo" le spunte sono facoltative.
- **FR-011**: Il server MUST accettare una segnalazione solo per una riga che l'utente può vedere e solo per un monitoraggio aperto con fonti non in aggiornamento.
- **FR-012**: La scheda Segnalazioni del monitoraggio (amministratore) MUST mostrare per ogni segnalazione: tipo, bando, atto, protocollo, rilievo (se falso positivo), fonti indicate, nota, autore, data, stato; MUST permettere di segnarla gestita o riaprirla.
- **FR-013**: Le segnalazioni già salvate MUST restare visibili come "falso positivo" senza fonti indicate.

**Schede**

- **FR-014**: Nello Stato complessivo e nel dettaglio di un Monitoraggio, sia per l'amministratore sia in consultazione, la prima scheda MUST essere "Tutti" con il numero di atti e l'elenco di tutti gli atti, seguita dalle schede esistenti nell'ordine attuale.
- **FR-015**: I filtri esistenti MUST valere anche nella scheda "Tutti".

**App installabile**

- **FR-016**: Il sito MUST essere installabile come app da Chrome ed Edge su Windows e Mac e aggiungibile al Dock da Safari su Mac, con nome, icona e colore del monitoraggio, e aprirsi in una finestra propria sulla pagina iniziale del ruolo.
- **FR-017**: L'app MUST NOT salvare sul dispositivo pagine o dati del monitoraggio per l'uso offline; senza rete MUST mostrare un messaggio "Serve la connessione".
- **FR-018**: Un aggiornamento del sito MUST arrivare all'app alla riapertura, senza reinstallare.
- **FR-019**: La pagina di accesso MUST avere un breve aiuto "Installa l'app" con i passi per Windows e Mac.

**Coordinatori**

- **FR-020**: I bandi di categorie protette e di reclutamento speciale MUST NOT essere attribuiti al coordinatore del loro profilo.
- **FR-021**: Il sistema MUST offrire due voci esclusive, "Categorie protette" e "Reclutamento speciale", con le stesse regole di "Mobilità" (al più un coordinatore, richiesta, cessione, decisione dell'amministratore), che coprono i bandi di quel tipo di ogni profilo.
- **FR-022**: Un bando di mobilità o comando MUST restare sotto "Mobilità" qualunque sia la sua tipologia di riserva.
- **FR-023**: Il cambio MUST valere ovunque si usa il coordinatore di un bando: area coordinatori, consultazione, copia nelle comunicazioni.
- **FR-024**: Il cambio MUST NOT togliere i bandi dallo stato complessivo, dai monitoraggi né dall'area dei loro RdP.

**Avviso scorrimenti**

- **FR-025**: Alla fine di ogni aggiornamento pianificato il sistema MUST individuare gli scorrimenti/utilizzi, nelle tipologie del monitoraggio, presenti nel file della segreteria e/o su URP e non ancora avvisati.
- **FR-026**: Per ciascuno MUST inviare un'email ai soli RdP del bando (o del codice) che fanno parte dell'ufficio, secondo l'elenco nelle Impostazioni (con l'elenco vuoto non parte nessuna email; chi entra nell'elenco dopo riceve solo gli scorrimenti rilevati negli ultimi 30 giorni), che dice da quale fonte è stata rilevata la pubblicazione (file della segreteria, URP o entrambi), con bando, data, protocollo e link al documento URP, e chiede di richiedere il provvedimento se non è stato notificato; in copia la segreteria delle Impostazioni e la copia fissa dell'ufficio. L'email MUST NOT contenere le difformità, che restano nell'email manuale del monitoraggio.
- **FR-027**: Ogni scorrimento MUST essere avvisato al più una volta; ogni invio MUST restare registrato con esito (inviato, in prova, senza destinatari, non inviato) e data; gli scorrimenti presenti all'attivazione si registrano come esistenti.
- **FR-028**: L'avviso MUST essere disattivato finché un amministratore non lo attiva; alla prima attivazione gli scorrimenti già presenti MUST essere registrati senza email.
- **FR-029**: Gli invii MUST seguire le impostazioni email esistenti (prova / ufficiali); un errore di invio MUST NOT bloccare l'aggiornamento.
- **FR-030**: L'amministratore MUST vedere l'elenco degli avvisi con esito, nelle Impostazioni.

**Comunicazioni nello stato complessivo**

- **FR-031**: Lo stato complessivo MUST mostrare per ogni graduatoria e scorrimento la comunicazione del suo monitoraggio come nella pagina del monitoraggio (stato, protocollo dell'email, storico degli invii) con la spunta "inviata" e il pulsante "Messaggio" che apre lo stesso pannello del monitoraggio (anteprima, modifica, destinatari, copia, invio); anche per gli atti di un mese senza monitoraggio si può aprire il messaggio o segnare l'invio: il monitoraggio di quel mese si crea alla prima azione, dopo conferma (richiesta dell'utente del 2026-11-17). MUST NOT avere un secondo flusso di invio separato: tolti "Copia destinatari RdP", "Copia messaggio completo", "Anteprima e invio" e la spunta (richiesta dell'utente del 2026-11-17).

### Key Entities

- **Accesso**: chi è entrato, ruolo, modo di ingresso (link email, ticket SOL, area referenti), inizio e scadenza a 7 giorni.
- **Segnalazione**: monitoraggio, bando e atto (protocollo e data), tipo (errore / falso positivo), rilievo (solo falso positivo), fonti indicate (zero o più tra SOL, URP, segreteria), nota, autore, data, stato (da vedere / gestita), chi l'ha gestita e quando.
- **Avviso scorrimento**: bando, codice, data e protocollo dello scorrimento, link URP, destinatari, copia, esito, data dell'esito, messaggio d'errore.
- **Voce del bando**: la voce dell'elenco dei coordinatori a cui appartiene un bando: "Mobilità" per mobilità e comandi, "Categorie protette", "Reclutamento speciale", altrimenti il profilo senza livello.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un utente che usa il monitoraggio ogni giorno chiede al massimo un link di accesso a settimana per dispositivo.
- **SC-002**: Un referente invia una segnalazione di errore su una riga in meno di 1 minuto.
- **SC-003**: Il 100% delle segnalazioni "errore" ricevute indica almeno una fonte da correggere.
- **SC-004**: Un utente installa l'app su Windows o su Mac seguendo l'aiuto in meno di 2 minuti, e la apre dal desktop già collegato (Chrome/Edge).
- **SC-005**: Dopo la disinstallazione dell'app o l'uscita, sul dispositivo non resta nessun dato del monitoraggio.

## Assumptions

- La durata di 7 giorni è stata scelta dall'utente il 2026-11-16; vale per tutti i ruoli.
- Il ticket di Selezioni Online scade dopo circa un'ora e non è sotto il controllo del sito: resta il collegamento SOL come oggi.
- Safari su Mac tiene l'app del Dock separata dal browser: l'utente entra una volta dall'app chiedendo il link email e incollandolo/aprendolo nella finestra dell'app; Chrome ed Edge, consigliati su Windows e Mac, condividono l'accesso con il browser.
- Il programma "Collega-SOL" scaricabile oggi è solo per Mac; una versione per Windows non fa parte di questa spec (accesso degli amministratori con ticket SOL incollato a mano resta disponibile su Windows).
- I pulsanti di segnalazione restano nelle pagine di consultazione e nell'area referenti, non nelle pagine dell'amministratore (scelta dell'utente del 2026-11-16).
- Nel monitoraggio dell'amministratore la scheda aperta di default resta quella delle difformità; "Tutti" è la prima nell'elenco.
- Coordinatori (scelta dell'utente del 2026-11-16): categorie protette e reclutamento speciale non fanno parte dei bandi pubblici del profilo; hanno ciascuno una voce propria come "Mobilità". La tipologia del bando è quella già letta dalle fonti (sezione URP o cartella di Selezioni Online).
- Il sito è servito in HTTPS (Coolify), requisito per l'installazione dell'app.
