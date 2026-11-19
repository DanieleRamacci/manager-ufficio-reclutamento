# Feature Specification: Fonte "Protocollo" dalle email di Titulus

**Feature Branch**: `010-fonte-email-protocollo`

**Created**: 2026-11-16

**Status**: Prima versione in sviluppo (programma sul PC, decisione del 2026-11-19)

**Input**: Richiesta dell'utente: quando l'ufficio protocolla un documento con Titulus mette in copia una persona; le email arrivano in una casella CNR (Outlook/Exchange) e una regola le mette in una cartella dedicata. Il sistema legge quelle email, ne ricava numero di protocollo, data, oggetto, verso (entrata/uscita) e tipo di atto, e le cataloga come nuova fonte. Primo obiettivo: sapere tutto ciò che viene protocollato, entrato e uscito. Secondo: affiancarla al file di riepilogo della segreteria per vedere se il file è allineato e completo, cioè che non siano sfuggiti protocolli, e automatizzare la parte oggi fatta a mano.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Registro di tutto ciò che viene protocollato (Priority: P1)

Ogni email di Titulus nella cartella dedicata diventa una riga di un registro: numero di protocollo, data, verso (entrata o uscita), oggetto, link al documento su Titulus, data di arrivo dell'email. L'amministratore apre la pagina "Protocollo" e vede l'elenco completo, filtrabile per periodo, verso e testo.

**Why this priority**: è il primo livello di valore indicato dall'utente: sapere con certezza cosa entra e cosa esce, senza dipendere da quanto è stato riportato a mano.

**Independent Test**: Protocollare (o inoltrare) tre documenti di prova con la casella in copia; entro il successivo controllo della casella compaiono tre righe con numero, data, verso, oggetto e link corretti.

**Acceptance Scenarios**:

1. **Given** una nuova email di Titulus nella cartella, **When** il sistema controlla la casella, **Then** compare una riga con numero di protocollo, data, verso, oggetto e link a Titulus.
2. **Given** la stessa email letta due volte o arrivata in doppio, **When** il sistema la elabora, **Then** il registro ha una sola riga per numero di protocollo.
3. **Given** un'email nella cartella che non è di Titulus o da cui non si ricava il numero di protocollo, **When** viene letta, **Then** finisce in "Da controllare" con il motivo, senza entrare nel registro.
4. **Given** la casella non raggiungibile o le credenziali scadute, **When** il controllo fallisce, **Then** la pagina mostra "ultimo controllo riuscito il …" e l'errore, e l'amministratore riceve un avviso.
5. **Given** il registro, **When** si apre la pagina, **Then** si vede quando è stato fatto l'ultimo controllo riuscito e quante email sono state lette.

---

### User Story 2 - Classificare gli atti protocollati (Priority: P1)

Dall'oggetto il sistema propone per ogni protocollo la categoria (bando, graduatoria, scorrimento/utilizzo, rettifica, altro) e il codice bando. Quando la regola non basta, la riga resta "da classificare" e l'amministratore la sistema a mano in pochi clic; la correzione resta salvata e vale anche per i controlli successivi.

**Why this priority**: senza categoria e codice bando il registro non si può confrontare con il file della segreteria.

**Independent Test**: Un oggetto del tipo "Graduatoria finale bando 380.12 …" viene classificato "graduatoria", codice "380.12"; un oggetto ambiguo resta "da classificare" e, corretto a mano, non cambia più.

**Acceptance Scenarios**:

1. **Given** un oggetto che contiene tipo di atto e codice bando riconoscibili, **When** il protocollo entra nel registro, **Then** ha categoria e codice bando proposti, segnati come "automatici".
2. **Given** un oggetto ambiguo, **When** entra, **Then** è "da classificare" e conta nel numero mostrato in cima alla pagina.
3. **Given** una riga classificata a mano, **When** il sistema rilegge la casella, **Then** la classificazione manuale non viene sovrascritta.
4. **Given** un protocollo che non riguarda il reclutamento, **When** l'amministratore lo segna "non pertinente", **Then** esce dai confronti ma resta nel registro.
5. **Given** le regole di classificazione, **When** l'amministratore vede quante righe sono automatiche, manuali e da classificare, **Then** sa quanto lavoro manuale resta.

---

### User Story 3 - Il file della segreteria è completo? (Priority: P1)

Nella pagina del file della segreteria compare un confronto con il registro del protocollo per il periodo scelto: protocolli presenti nel registro e assenti dal file, protocolli nel file e assenti dal registro, e righe con dati diversi (data, codice bando, categoria). Nessun dato viene corretto in automatico.

**Why this priority**: è lo scopo operativo indicato dall'utente: verificare che non siano sfuggiti codici di protocollo nel file compilato a mano.

**Independent Test**: Con un file della segreteria a cui manca un protocollo presente nel registro, il confronto lo elenca come "manca nel file"; aggiunto nel file e ricaricato, sparisce dall'elenco.

**Acceptance Scenarios**:

1. **Given** un protocollo pertinente nel registro e assente dal file della segreteria, **When** si apre il confronto, **Then** è elencato in "Manca nel file della segreteria".
2. **Given** un protocollo nel file della segreteria che non è nel registro, **When** si apre il confronto, **Then** è elencato in "Non arrivato via email", con l'avvertenza che può dipendere dalla copia non messa al protocollo.
3. **Given** lo stesso protocollo con data o codice bando diversi tra file e registro, **When** si apre il confronto, **Then** è elencato con entrambe le versioni.
4. **Given** protocolli ancora "da classificare", **When** si apre il confronto, **Then** il confronto lo dice e indica quanti sono.
5. **Given** il periodo di un file della segreteria, **When** il registro ha un buco nei controlli della casella in quel periodo, **Then** il confronto lo segnala invece di dare tutto per mancante.

---

### User Story 4 - Meno lavoro manuale sul file della segreteria (Priority: P2)

Dalla lista "Manca nel file della segreteria" l'amministratore o la segreteria scaricano le righe mancanti già nel formato delle colonne del file (protocollo, data, categoria, codice bando, oggetto), da incollare nel file invece di ricopiarle a mano.

**Why this priority**: è il passo verso l'automazione chiesto dall'utente; viene dopo che registro e confronto sono affidabili.

**Independent Test**: Scaricare le righe mancanti di un mese, incollarle nel file, ricaricare il file: la lista "Manca nel file" diventa vuota per quel mese.

**Acceptance Scenarios**:

1. **Given** righe mancanti nel file, **When** l'utente sceglie "Scarica le righe mancanti", **Then** ottiene un file con le colonne nell'ordine del file della segreteria.
2. **Given** righe ancora da classificare, **When** scarica, **Then** sono escluse e il numero escluso è indicato.

### Edge Cases

- Lo stesso numero di protocollo usato in entrata e in uscita negli anni diversi: la chiave è numero + anno (o data), non il solo numero.
- Email di Titulus inoltrate o con risposta ("RE:", "I:"): si legge il messaggio originale; se non si riconosce, va in "Da controllare".
- Più documenti nello stesso protocollo o protocollo annullato/rettificato: la rettifica è una riga a sé; l'annullamento, se riconoscibile dall'oggetto, è segnato e non conta come atto.
- Cartella svuotata o email spostate da una persona: il registro conserva le righe già lette; il sistema non dipende dal fatto che le email restino nella cartella.
- Oggetto con nomi di candidati: l'oggetto è mostrato solo agli utenti autenticati con ruolo amministratore o segreteria e non compare nei log.
- Casella con molte email vecchie al primo collegamento: la prima lettura importa lo storico della cartella una volta, a pagine, senza limiti fissi.

## Approccio scelto il 2026-11-19

Scelte dell'utente: si parte dalla casella di una persona della segreteria, con un **programma installato sul PC** (Windows) che legge le email di Titulus arrivate in copia, invece di un accesso del server alla casella (che richiede l'informatica). Formato reale delle email:

```
Oggetto email: [CC]:Provvedimento nomina personale vigilanza 367.634 FA IMM
Il sistema di protocollo le ha assegnato il seguente documento in copia conoscenza:
N. 485664 del 20261111 (2026-CNR0A00-0485664)
Oggetto: Provvedimento nomina personale vigilanza 367.634 FA IMM
Per visualizzare:
 https://titulus-cnr.cineca.it/fe/#/documento/002686734-CNR0A00-…
```

- Il programma legge Outlook classico (senza password) o una cartella di email salvate (.eml/.msg); manda al sito solo numero, data, segnatura, oggetto, link Titulus, data di ricezione e identificativo del messaggio; si identifica con una **chiave personale** generata nella pagina «File segreteria» e revocabile. Non apre i documenti su Titulus.
- Nella pagina «File segreteria», scheda **«Documenti in uscita protocollo»**: una tabella con intestazione fissa; per ogni protocollo i dati, il link Titulus, la proposta (tipo di atto, scorrimento o subentro, bando) con la frase dell'oggetto da cui viene, i controlli e le azioni **Approva**, **Modifica**, **Scarta**.
- Controlli: stesso protocollo ricevuto più volte (anche con oggetto diverso), protocolli simili (uguali a meno di uno zero iniziale o di una cifra), protocollo già nel file della segreteria (con categoria diversa?), già su URP o SOL, bando non trovato.
- Approvato, l'atto (graduatoria, scorrimento, rettifica, bando) vale come riga del file della segreteria **«aggiunta automaticamente»** nel confronto, finché non compare nel file caricato; gli altri documenti (commissioni, vigilanza, autorizzazioni) restano solo registrati.

## Requirements *(mandatory)*

### Functional Requirements

**Lettura della casella**

- **FR-001**: Il sistema MUST leggere periodicamente (almeno ogni ora nei giorni lavorativi) una cartella dedicata di una casella CNR e su richiesta dell'amministratore.
- **FR-002**: L'accesso alla casella MUST essere in sola lettura: il sistema MUST NOT spostare, cancellare, segnare come lette o inviare email da quella casella; tiene traccia delle email già lette nel proprio database.
- **FR-003**: Le credenziali della casella MUST arrivare dalla configurazione del server e MUST NOT essere salvate nel codice o nel database.
- **FR-004**: Ogni controllo MUST registrare data e ora, esito, email lette, nuove righe ed errori (Principio V).
- **FR-005**: Il sistema MUST riconoscere le email di Titulus e ricavarne numero di protocollo, data di protocollo, verso (entrata/uscita), oggetto e link al documento; le altre MUST finire in "Da controllare" con il motivo.

**Registro e classificazione**

- **FR-006**: Il registro MUST avere una sola riga per protocollo (numero e anno) e MUST conservare l'oggetto originale e la data di arrivo dell'email.
- **FR-007**: Il sistema MUST proporre categoria (bando, graduatoria, scorrimento/utilizzo, rettifica, altro) e codice bando normalizzato a partire dall'oggetto, con regole visibili e modificabili dall'amministratore.
- **FR-008**: Gli amministratori MUST poter correggere categoria e codice bando e segnare un protocollo "non pertinente"; le correzioni manuali MUST prevalere su quelle automatiche e restare tracciate (chi, quando).
- **FR-009**: Il sistema MUST NOT aprire il link di Titulus né scaricare il documento in questa spec: il link è solo mostrato.
- **FR-010**: Il registro MUST essere visibile solo ad amministratori e segreteria.

**Confronto con il file della segreteria**

- **FR-011**: Per un periodo, il sistema MUST elencare: protocolli pertinenti nel registro e assenti dal file; protocolli nel file e assenti dal registro; protocolli presenti in entrambi con data, categoria o codice bando diversi.
- **FR-012**: Il confronto MUST basarsi sul numero di protocollo normalizzato e MUST NOT modificare né il file della segreteria né il registro (Principio I).
- **FR-013**: Il confronto MUST indicare quanti protocolli del periodo sono ancora da classificare e se nel periodo ci sono stati controlli della casella non riusciti.
- **FR-014**: Gli utenti con accesso MUST poter scaricare le righe mancanti nel file con le colonne del file della segreteria.

**Rapporto con il monitoraggio**

- **FR-015**: In questa spec la fonte "Protocollo" MUST NOT generare difformità, solleciti o email ai referenti; serve solo al confronto con il file della segreteria.

### Key Entities

- **Controllo della casella**: quando, esito, email lette, nuove righe, errore.
- **Email letta**: identificativo univoco del messaggio, data di arrivo, esito della lettura (registrata / da controllare / ignorata), motivo; nessun corpo completo salvato oltre a quanto serve.
- **Protocollo**: numero, anno, data, verso (entrata/uscita), oggetto, link Titulus, categoria e codice bando (con origine: automatica/manuale), pertinente sì/no, chi l'ha corretto e quando.
- **Regola di classificazione**: testo o schema da cercare nell'oggetto, categoria che assegna, ordine di priorità.
- **Differenza con il file della segreteria**: protocollo, tipo di differenza, valori nelle due fonti.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Il 100% delle email di Titulus arrivate nella cartella compare nel registro o in "Da controllare" entro 1 ora dall'arrivo nei giorni lavorativi.
- **SC-002**: Almeno l'80% dei protocolli pertinenti viene classificato automaticamente dopo il primo mese di regole.
- **SC-003**: Per un mese chiuso, l'amministratore sa in meno di 5 minuti quali protocolli mancano nel file della segreteria, invece di confrontarli a mano.
- **SC-004**: Il tempo per aggiornare il file della segreteria si riduce di almeno la metà usando le righe scaricate.
- **SC-005**: Nessuna email viene modificata, spostata o inviata dalla casella letta.

## Assumptions

- Casella: una casella CNR su Outlook/Exchange (scelta dell'utente del 2026-11-16), con una regola che mette le email di Titulus in una cartella dedicata. Il modo di accesso (protocollo di posta o interfaccia di Microsoft) e il tipo di credenziali (casella personale o di servizio, approvazione dell'informatica CNR) si decidono nel piano; una casella di servizio è preferibile a quella di una persona (Principio III).
- Contenuto delle email: le notifiche di Titulus contengono sempre numero di protocollo, oggetto e link al documento su Titulus; il formato esatto (oggetto, corpo, come si distingue entrata da uscita) si ricava nel piano da email reali anonimizzate.
- La classificazione è fatta con regole sull'oggetto; nessun testo viene inviato a servizi esterni di AI (Principio II). Un aiuto con AI richiede una spec dedicata.
- Il documento allegato su Titulus richiede l'accesso a Titulus: leggerlo è fuori da questa spec.
- Il file della segreteria resta la fonte di riferimento del monitoraggio (Principio I); il registro del protocollo serve a controllarne la completezza, non a sostituirlo.
- Uso nel monitoraggio come quarta fonte, con difformità e solleciti, solo in una spec successiva, dopo aver verificato la qualità del registro.
