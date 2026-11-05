# Feature Specification: Raccolta dati unificata di bandi, graduatorie e scorrimenti

**Feature Branch**: `001-raccolta-dati-bandi`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "Raccolta dati unificata per il monitoraggio di bandi a tempo indeterminato e mobilità. Riscrivere e migliorare gli scraper esistenti (scraper-urp.py, scraper-mobilita.py, scraper-sol-tutti-bandi.py) perché raccolgano in modo completo da URP (urp.cnr.it, sezioni tempo-indeterminato e bandi-pubblici-mobilita) e da Selezioni Online (API pubblica jconon/rest/search, con paginazione completa: oggi si ferma a 200 bandi su circa 792) tutti i dati necessari: bandi pubblicati (codice bando, protocollo, data, titolo, profilo, sede, posti, gruppo RdP), graduatorie pubblicate, scorrimenti/utilizzi di graduatoria e rettifiche, ciascuno con numero di protocollo e data. I dati vanno salvati in un database SQLite sul volume persistente del server (non più file JSON nella cartella del codice o nel repository), registrando per ogni dato la fonte e per ogni raccolta data, esito ed errori. Il codice bando va normalizzato per il match tra URP e SOL. L'app esistente (pagine index.html, report-mese.html, mobilita-urp.html) deve continuare a funzionare leggendo dal database. Fuori scopo per questa spec (spec successive): verifica punteggi su SOL con login, lettura del file di riepilogo di Valentina come fonte di riferimento, confronto con le email di protocollo in CC, dashboard di monitoraggio complessiva."

## Contesto

L'ufficio reclutamento deve sapere ogni mese quali bandi sono stati pubblicati, quali
graduatorie sono uscite e quali scorrimenti o utilizzi di graduatoria sono stati fatti, e
verificare che ogni documento sia presente sia sul sito URP sia su Selezioni Online (SOL).
Oggi i dati vengono raccolti da tre script separati che salvano file nella cartella del
codice, si fermano a una parte dei bandi SOL (200 su circa 792) e non collegano in modo
affidabile lo stesso bando tra le due fonti. Questa spec costruisce la base dati su cui
lavoreranno le spec successive (punteggi SOL, file di riepilogo dell'ufficio, email di
protocollo, dashboard di monitoraggio).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Elenco completo e aggiornato dei bandi e dei loro documenti (Priority: P1)

L'addetta dell'ufficio avvia l'aggiornamento (o lo trova già eseguito in automatico) e
ottiene, per ogni bando a tempo indeterminato e di mobilità pubblicato su URP e su SOL, i
dati del bando e l'elenco dei documenti pubblicati: graduatorie, scorrimenti, utilizzi di
graduatoria e rettifiche, ognuno con numero di protocollo e data.

**Why this priority**: senza un elenco completo e affidabile nessun controllo successivo
ha senso; oggi tre quarti dei bandi SOL non vengono letti.

**Independent Test**: si avvia una raccolta completa e si confronta il numero di bandi
raccolti con il numero indicato dalle pagine URP ("Numero Documenti: X di Y") e dal totale
restituito da SOL; si verificano a campione 10 bandi controllando a mano protocolli e date
dei documenti sul sito.

**Acceptance Scenarios**:

1. **Given** SOL dichiara 792 bandi di concorso pubblico, **When** la raccolta termina,
   **Then** nel sistema ci sono 792 bandi SOL, non un numero fisso inferiore.
2. **Given** la pagina URP di un bando contiene gli allegati "Graduatoria",
   "Scorrimento graduatoria", "Provvedimento subentro scorrimento graduatoria", "Utilizzo
   graduatoria" e "Rettifica graduatoria", **When** la raccolta termina, **Then** ogni
   allegato è salvato con categoria (graduatoria, scorrimento, rettifica), numero di
   protocollo e data; i tre scorrimenti hanno sottotipo rispettivamente "non specificato",
   "subentro" e "utilizzo".
2a. **Given** su SOL un allegato di tipo "Provvedimento assunzione idoneo/i", **When** la
   raccolta termina, **Then** è classificato nella categoria scorrimento.
3. **Given** un bando di mobilità pubblicato su URP e su SOL, **When** la raccolta termina,
   **Then** il bando è salvato con tipologia "mobilità" o "comando", codice, protocollo, data
   e documenti, con le due schede collegate e lo stesso livello di dettaglio dei bandi a
   tempo indeterminato.
4. **Given** un bando SOL, **When** la raccolta termina, **Then** sono salvati codice,
   titolo, profilo, sede, numero di posti, gruppo RdP, data di pubblicazione, data di
   pubblicazione della graduatoria e l'elenco dei documenti pubblicati sulla pagina del bando.

---

### User Story 2 - Stesso bando riconosciuto su URP e su SOL (Priority: P1)

Per ogni bando il sistema collega la scheda URP e la scheda SOL anche quando il codice è
scritto in modo diverso (es. "367.479 CTER IOMGE" su URP e "367.479 CTER IOM GE" su SOL),
così l'addetta vede subito i bandi presenti in una sola fonte e i documenti che mancano su
SOL rispetto a URP.

**Why this priority**: il confronto tra URP e SOL è la funzione già usata dall'ufficio per
trovare documenti non pubblicati su SOL; deve funzionare su dati completi.

**Independent Test**: su un insieme di 30 bandi noti (presenti su entrambe le fonti) si
verifica che tutti siano collegati; si verifica che un bando presente solo su URP sia
indicato come "solo URP".

**Acceptance Scenarios**:

1. **Given** lo stesso bando su URP e su SOL con codici che differiscono solo per spazi,
   punteggiatura o maiuscole, **When** si consultano i dati, **Then** i due record risultano
   collegati allo stesso bando.
2. **Given** un bando con graduatoria pubblicata su URP ma senza graduatoria su SOL,
   **When** si consultano i dati, **Then** il bando è indicato come "graduatoria mancante su
   SOL".
3. **Given** un codice URP che non corrisponde a nessun bando SOL, **When** si consultano i
   dati, **Then** il bando è indicato come "solo URP" e conserva il codice originale.

---

### User Story 3 - Sapere quanto sono aggiornati i dati (Priority: P2)

L'addetta vede quando è stata eseguita l'ultima raccolta per ciascuna fonte, se è andata a
buon fine, quanti bandi e documenti ha trovato e quali errori ci sono stati.

**Why this priority**: un monitoraggio su dati vecchi o parziali porta a solleciti sbagliati.

**Independent Test**: si simula l'irraggiungibilità di SOL durante una raccolta e si
verifica che lo stato mostri "SOL: raccolta fallita" con data e messaggio, mentre i dati
precedenti restano consultabili.

**Acceptance Scenarios**:

1. **Given** una raccolta completata, **When** si consulta lo stato, **Then** per ogni fonte
   sono indicati data e ora, esito, numero di bandi e documenti trovati.
2. **Given** una fonte non raggiungibile, **When** la raccolta termina, **Then** l'esito è
   "fallita" con il motivo, e i dati della raccolta precedente restano disponibili e marcati
   con la loro data.
3. **Given** un singolo bando la cui pagina non si apre, **When** la raccolta termina,
   **Then** l'esito è "completata con errori" e il bando è elencato tra gli errori.

---

### User Story 4 - Le pagine esistenti continuano a funzionare (Priority: P2)

Le pagine già in uso (controllo URP/SOL in `index.html`, report mensile, mobilità URP)
mostrano gli stessi contenuti di oggi, ma alimentati dai nuovi dati.

**Why this priority**: l'app è già in uso; la nuova raccolta non deve interrompere il lavoro.

**Independent Test**: si aprono le tre pagine dopo una raccolta e si verifica che mostrino
gli stessi bandi e colonne di prima, con numeri uguali o maggiori.

**Acceptance Scenarios**:

1. **Given** una raccolta completata, **When** si apre la pagina di controllo URP/SOL,
   **Then** compaiono i bandi con lo stato dei documenti come prima.
2. **Given** una raccolta completata, **When** si apre la pagina mobilità, **Then**
   compaiono i bandi di mobilità con i loro documenti.

---

### User Story 5 - Stato complessivo degli atti in una sola tabella (Priority: P1)

*Aggiunta il 2026-10-29 su richiesta dell'utente, dopo la prima prova con dati reali.*

L'addetta apre la pagina di monitoraggio e vede una tabella con una riga per ogni atto
(bando pubblicato, graduatoria, scorrimento, rettifica della graduatoria), a partire dai dati
di SOL: numero di bando, codice, tipologia, protocollo, data e, per ogni fonte (Selezioni
Online, URP, file della segreteria), se l'atto è presente. Un atto presente su più fonti
compare una sola volta; le fonti dove manca sono evidenziate in rosso.

**Why this priority**: è la vista che risponde alla domanda dell'ufficio ("cosa manca e
dove"); senza di essa i dati raccolti si consultano solo da terminale.

**Independent Test**: dopo una raccolta si apre la tabella dal 2026-01-01; un atto con lo
stesso protocollo su URP e SOL compare in una riga con due celle verdi; una graduatoria solo
su URP compare in una riga con la cella SOL rossa; il filtro "solo incompleti" mostra solo
righe con almeno una cella rossa.

**Acceptance Scenarios**:

1. **Given** una graduatoria con lo stesso protocollo pubblico su URP e SOL, **When** si
   apre la tabella, **Then** compare in una sola riga con le celle URP e SOL verdi.
2. **Given** uno scorrimento presente solo su URP, **When** si apre la tabella, **Then** la
   cella SOL è rossa e la riga risulta incompleta.
3. **Given** lo stesso atto con protocolli diversi sulle due fonti (stessa categoria e
   data), **When** si apre la tabella, **Then** compare in una sola riga con la nota
   "protocollo diverso" e i due numeri.
4. **Given** un bando fuori dal periodo coperto da URP, **When** si apre la tabella,
   **Then** la cella URP è grigia ("fuori periodo") e non rossa.
5. **Given** il file della segreteria non ancora caricato, **When** si apre la tabella,
   **Then** la colonna della segreteria è grigia ("non caricato").

---

### User Story 6 - Menu comune per navigare tra gli strumenti (Priority: P2)

*Aggiunta il 2026-10-29 su richiesta dell'utente.*

In alto in ogni pagina dell'app c'è lo stesso menu, che porta a tutte le sezioni e a tutti
gli strumenti disponibili (monitoraggio, file della segreteria, controlli URP e
accessibilità, mobilità, report, redazione firme, strumenti RdP), con la voce della pagina
corrente evidenziata e lo stato delle raccolte sempre visibile.

**Why this priority**: oggi ogni pagina ha un menu diverso o nessun menu, e alcuni strumenti
si raggiungono solo conoscendo l'indirizzo.

**Independent Test**: si apre ciascuna pagina dell'app e si verifica che il menu sia lo
stesso, che ogni voce porti alla pagina giusta e che la voce corrente sia evidenziata.

**Acceptance Scenarios**:

1. **Given** una qualsiasi pagina dell'app, **When** si apre, **Then** in alto compare il
   menu comune con le sezioni raggruppate.
2. **Given** il server locale di prova, **When** si apre il menu, **Then** gli strumenti non
   disponibili in locale (es. redazione firme) sono indicati come non disponibili invece di
   portare a una pagina di errore.
3. **Given** una raccolta in corso, **When** si guarda il menu, **Then** è indicato che la
   raccolta è in corso.

---

### Edge Cases

- Un bando ha più graduatorie o più scorrimenti: ognuno è salvato come documento separato
  con il proprio protocollo e data.
- Un allegato ha titolo ambiguo (es. "Rettifica nominativo graduatoria"): è classificato
  come rettifica, non come nuova graduatoria.
- Un allegato non ha protocollo o data: è salvato comunque, con il campo vuoto e segnalato.
- Lo stesso bando compare due volte nell'elenco URP (paginazione che cambia durante la
  raccolta): viene salvato una sola volta.
- Un documento che c'era nella raccolta precedente non compare più: non viene cancellato,
  viene marcato come "non più presente" con la data dell'ultima rilevazione.
- Il codice bando non è ricavabile dal testo URP: il bando resta salvato, indicato come
  "codice non riconosciuto" e collegabile tramite protocollo.
- Una raccolta viene avviata mentre un'altra è in corso: la seconda viene rifiutata con un
  messaggio chiaro.
- La struttura delle pagine URP cambia e non si trovano più bandi: la raccolta è marcata
  come fallita invece di salvare un elenco vuoto.

## Requirements *(mandatory)*

### Functional Requirements

#### Raccolta

- **FR-001**: Il sistema MUST raccogliere tutti i bandi delle sezioni URP "tempo
  indeterminato" (circa 201), "bandi pubblici mobilità" (circa 27) e "categorie
  riservatarie" (circa 13), seguendo tutte le pagine dell'elenco.
- **FR-002**: Il sistema MUST raccogliere da SOL, seguendo tutte le pagine dei risultati e
  senza un limite fisso, tutti i bandi a tempo indeterminato (concorsi pubblici circa 792,
  reclutamento speciale circa 71, categorie protette circa 142), di mobilità (circa 190) e
  di comando/distacco (circa 8).
- **FR-003**: Le altre sezioni URP (tempo determinato, direttori,
  avviamento numerico, borse di ricerca, archivio storico) e le borse di ricerca SOL MUST NOT
  essere raccolte in questa versione; l'elenco delle sezioni raccolte MUST essere
  configurabile per poterle aggiungere in seguito.
- **FR-004**: Per ogni bando il sistema MUST salvare, quando disponibili: codice originale,
  codice normalizzato, titolo, tipologia (tempo indeterminato, mobilità, comando, altre
  sezioni), numero di protocollo, data di pubblicazione, profilo, sede, numero di posti,
  gruppo RdP, link alla scheda.
- **FR-005**: Per ogni documento pubblicato su un bando (URP e SOL) il sistema MUST salvare
  titolo, tipo, numero di protocollo, data e link.
- **FR-006**: Il sistema MUST classificare ogni documento in una categoria principale: bando,
  graduatoria, scorrimento, rettifica, criteri, tracce, altro. La categoria scorrimento
  comprende ogni assunzione di idonei dalla graduatoria, compresi il tipo SOL
  "Provvedimento assunzione idoneo/i", i subentri e gli utilizzi. I criteri di
  classificazione MUST essere modificabili senza cambiare il resto della raccolta.
- **FR-006a**: Per gli scorrimenti il sistema MUST indicare un sottotipo quando il titolo lo
  dice esplicitamente: subentro (dopo la rinuncia del vincitore o di un idoneo già assunto),
  ulteriore scorrimento (con l'ordinale se presente), utilizzo; altrimenti "non
  specificato". Il sottotipo MUST essere mostrato come indicazione ricavata dal titolo, non
  come dato certo, perché un subentro può essere pubblicato con un titolo generico.
- **FR-007**: Il sistema MUST registrare per ogni bando e documento la data di prima e di
  ultima rilevazione, così da sapere quando è comparso.
- **FR-008**: Il sistema MUST attendere tra una richiesta e l'altra verso le fonti esterne
  ed eseguire solo letture.
- **FR-009**: La raccolta MUST essere eseguita in automatico ogni notte e MUST poter essere
  avviata a mano dall'app con un pulsante "Aggiorna dati", per tutte le fonti o per una sola.
- **FR-010**: Le raccolte successive alla prima MUST aggiornare i dati esistenti senza
  duplicarli. Per SOL MUST rileggere gli allegati solo dei bandi attivi, nuovi o modificati,
  oltre a un ricontrollo periodico completo; per URP, che ha poche pagine, il dettaglio dei
  bandi può essere riletto per intero a ogni raccolta. Il controllo dei PDF MUST essere
  eseguito solo sui documenti nuovi o modificati.

#### Collegamento tra fonti

- **FR-011**: Il sistema MUST normalizzare il codice bando (spazi, maiuscole, punteggiatura,
  prefissi come "BANDO N.") conservando il valore originale.
- **FR-012**: Il sistema MUST collegare la scheda URP e la scheda SOL dello stesso bando
  tramite numero bando e codice di sotto-bando, poi tramite codice normalizzato e, in
  mancanza, tramite numero di protocollo. Per i documenti il collegamento usa il protocollo
  pubblico, l'unico presente su URP e nelle ricerche pubbliche di SOL.
- **FR-013**: Il sistema MUST indicare per ogni bando se è presente su URP, su SOL o su
  entrambi, e per graduatorie e scorrimenti se il documento è presente su una sola fonte.
- **FR-013a**: Un bando SOL MUST essere segnalato come "manca su URP" solo se la sua data di
  pubblicazione rientra nel periodo coperto dagli elenchi URP raccolti; i bandi più vecchi
  MUST essere indicati come "fuori dal periodo URP", non come anomalie.
- **FR-013c** *(aggiunto il 2026-10-29 su indicazione dell'utente)*: Per i bandi SOL più
  vecchi del periodo coperto dalle sezioni URP attuali, il sistema MUST cercare la scheda
  nell'archivio storico URP (`archivio.urp.cnr.it`, già letto dal vecchio `scraper-urp.py`)
  e collegarla come scheda URP del bando: così la cella URP della tabella degli atti è verde o
  rossa anche per questi bandi; resta grigia ("fuori periodo") solo se il bando è più vecchio
  anche dell'archivio. Questo vale anche per gli scorrimenti del 2026 di graduatorie
  approvate negli anni precedenti.
- **FR-013b**: Le segnalazioni MUST riguardare solo bandi e documenti con data dal
  2026-01-01 in poi (data di inizio del monitoraggio, configurabile); i dati precedenti
  MUST comunque essere raccolti e consultabili.

#### Salvataggio e stato

- **FR-014**: Tutti i dati raccolti MUST essere salvati nel database dell'app sul volume
  persistente del server; la raccolta MUST NOT scrivere file di dati nella cartella del
  codice.
- **FR-015**: Il sistema MUST registrare ogni raccolta con fonte, inizio, fine, esito
  (completata, completata con errori, fallita), conteggi ed elenco degli errori.
- **FR-016**: Una raccolta fallita MUST NOT cancellare o svuotare i dati della raccolta
  precedente.
- **FR-017**: Il sistema MUST impedire due raccolte contemporanee sulla stessa fonte.
- **FR-018**: Le pagine esistenti (controllo URP/SOL, report mensile, mobilità URP) MUST
  leggere dal database i dati che oggi leggono dai file JSON e mostrare almeno le
  informazioni che mostrano oggi. Le interrogazioni dirette a SOL già presenti nel report
  mensile (`/api/sol/graduatorie`, `/api/bandi-rdp`) restano invariate in questa spec.
- **FR-019**: L'accesso ai dati raccolti e l'avvio delle raccolte MUST essere riservati agli
  utenti autenticati.
- **FR-020**: Al primo avvio il sistema MUST poter importare i file JSON esistenti, così da
  non perdere lo storico già raccolto.

#### Consultazione e navigazione (aggiunte il 2026-10-29)

- **FR-021**: Il sistema MUST offrire una tabella degli atti (bandi pubblicati, graduatorie,
  scorrimenti, rettifiche della graduatoria) in cui ogni atto compare una sola volta, con
  numero di bando, codice, tipologia, atto e sottotipo, protocollo, data e una colonna per
  ogni fonte (Selezioni Online, URP, file della segreteria) con stato "presente" (verde, con
  link e protocollo della fonte), "mancante" (rosso), "fuori periodo" o "non caricato"
  (grigio).
- **FR-022**: La tabella degli atti MUST permettere di filtrare per intervallo di date
  (predefinito dal 2026-01-01), tipo di atto, tipologia, fonte su cui l'atto manca, solo
  atti incompleti, solo atti con protocollo diverso, e ricerca per numero di bando, codice o
  protocollo; dalla riga MUST aprirsi il dettaglio del bando con i documenti delle fonti
  affiancati.
- **FR-023**: Ogni pagina dell'app MUST mostrare in alto lo stesso menu di navigazione,
  definito in un unico punto, con le sezioni raggruppate (Monitoraggio, Controlli URP,
  Strumenti), la voce corrente evidenziata e lo stato delle raccolte; le voci non disponibili
  nell'ambiente in uso MUST essere indicate come tali.
- **FR-024**: Per le prove in locale MUST esistere un server di prova avviabile con un
  comando, raggiungibile solo dal computer su cui gira (127.0.0.1), che mostra la pagina di
  monitoraggio e le pagine esistenti alimentate dal database; in produzione le stesse
  pagine sono protette dall'SSO (FR-019).

### Key Entities

- **Bando**: un concorso o avviso, identificato dal codice normalizzato; ha tipologia,
  titolo, protocollo, date, profilo, sede, posti, gruppo RdP.
- **Scheda fonte**: la presenza di un bando su una fonte (URP o SOL) con i dati come
  appaiono lì, il codice originale e il link; un bando può avere una scheda URP, una SOL o
  entrambe.
- **Documento**: un file pubblicato su una scheda, con categoria (graduatoria, scorrimento,
  rettifica, criteri, tracce, altro), sottotipo indicativo per gli scorrimenti, protocollo,
  data, link, date di prima e ultima
  rilevazione.
- **Raccolta**: un'esecuzione su una fonte, con inizio, fine, esito, conteggi ed errori.
- **Atto** (vista calcolata, non salvata): un bando pubblicato o un documento di categoria
  graduatoria, scorrimento o rettifica della graduatoria, identificato da bando, categoria e
  protocollo, con lo stato su ogni fonte.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Il numero di bandi raccolti per ogni sezione coincide con il totale dichiarato
  dalla fonte (100% dei bandi SOL a tempo indeterminato e di mobilità; oggi circa il 25% dei
  concorsi pubblici e nessun bando SOL di mobilità, reclutamento speciale o categorie
  protette).
- **SC-002**: Su un campione di 50 documenti verificati a mano, almeno 49 hanno tipo,
  protocollo e data corretti.
- **SC-003**: Almeno il 95% dei bandi presenti su entrambe le fonti risulta collegato
  automaticamente; i restanti sono elencati come "non collegati" per una verifica manuale.
- **SC-004**: Un aggiornamento giornaliero (solo bandi nuovi o modificati) termina in meno
  di 15 minuti.
- **SC-005**: Dopo l'aggiornamento non resta nessun file di dati nella cartella del codice e
  nessun file di dati viene proposto per il commit.
- **SC-006**: L'addetta sa in meno di 10 secondi, dall'app, quando sono stati aggiornati i
  dati di ogni fonte e se ci sono stati errori.
- **SC-007**: Dalla tabella degli atti l'addetta ottiene l'elenco degli atti del mese che
  mancano su almeno una fonte con al massimo due filtri (mese e "solo incompleti").
- **SC-008**: Ogni pagina dell'app è raggiungibile dal menu comune con al massimo due clic.

## Assumptions

- L'ambito è limitato a tempo indeterminato (compresi reclutamento speciale e categorie
  protette/riservatarie) e mobilità/comandi (decisione dell'utente del 2026-10-29). Il monitoraggio
  mensile esclude le categorie protette, che restano raccolte (decisione dell'utente del 2026-11-05).
- Gli elenchi URP contengono meno bandi di SOL (201 contro 792 per il tempo indeterminato):
  URP mostra un periodo più breve, quindi molti bandi SOL vecchi non hanno una scheda URP
  e non sono anomalie (vedi FR-013a). Il controllo esistente di criteri, tracce e accessibilità dei PDF continua a
  funzionare, ma solo sui bandi di queste sezioni.
- I dati raccolti in questa spec sono pubblici; nominativi e punteggi dei candidati non
  fanno parte di questa spec (spec successiva con login SOL).
- I bandi di mobilità sono pubblicati anche su SOL (verificato il 2026-10-29: 190 bandi di
  mobilità e 8 di comando/distacco nell'API pubblica), quindi la mobilità ha sia la scheda
  URP sia la scheda SOL e partecipa al collegamento tra fonti come il tempo indeterminato.
- Il controllo di accessibilità dei PDF esistente viene mantenuto, ma eseguito solo sui
  documenti nuovi o modificati, per non rallentare la raccolta giornaliera.
- L'orario della raccolta notturna è configurabile.
- Le pagine esistenti possono cambiare il modo in cui ricevono i dati, purché mostrino gli
  stessi contenuti.
- L'app viene eseguita in Docker su Coolify con un volume persistente per il database,
  come `chekin-cnr-concorsi`.

## Out of Scope

- Verifica dei punteggi su SOL e nominativi RdP (richiede login): spec successiva.
- Caricamento e lettura del file della segreteria (spec 002): in questa spec la colonna
  della tabella degli atti è prevista ma resta "non caricato".
- Lettura delle email di protocollo in CC.
- Grafici e indicatori della dashboard oltre alla tabella degli atti e al riepilogo mensile.
- Pulizia della cronologia del repository dai file di dati già committati.
