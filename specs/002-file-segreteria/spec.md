# Feature Specification: File della segreteria come fonte di riferimento

**Feature Branch**: `002-file-segreteria` (da creare dopo il merge della 001; la spec è scritta sul branch `001-raccolta-dati-bandi`)

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "File della segreteria come fonte di riferimento. L'utente carica dall'app (pagina "File segreteria" raggiungibile dal menu comune) il file Excel di riepilogo dell'ufficio (es. Graduatorie_Bandi_CNR.xlsx) [...] La colonna "File segreteria" della tabella degli atti della spec 001 mostra per ogni atto presente/mancante, e compaiono anche gli atti presenti solo nel file. [...] Il monitoraggio parte dal 2026-01-01. In futuro il file potrà arrivare automaticamente da SharePoint (fuori scopo ora)." (testo completo nella richiesta del 2026-10-29)

## Contesto

La segreteria dell'ufficio reclutamento tiene un file Excel con tutti i bandi pubblicati,
le graduatorie e gli scorrimenti, alimentato dal protocollo. È la fonte più attendibile, ma
può contenere errori. La spec 001 confronta URP e Selezioni Online; questa spec aggiunge il
file della segreteria come terza fonte e come riferimento del confronto, in modo che la
tabella degli atti mostri per ogni atto se è presente su tutte e tre le fonti.

Il file (verificato il 2026-10-29 su `Graduatorie_Bandi_CNR.xlsx`) ha tre fogli con una riga
per persona:

| Foglio | Righe | Contenuto | Colonne usate per il confronto |
| --- | --- | --- | --- |
| Bandi | 47 | un bando per riga (anche selezioni di Direttori d'Istituto) | Bando, Tipo procedura, Prot. CNR n., Data protocollo |
| Graduatorie | 769 | una riga per candidato in graduatoria, 84 bandi | N. Bando, Sotto-bando, N. Protocollo Pubblico e Data, N. Protocollo Privato e Data |
| Scorrimento | 175 | una riga per persona assunta con scorrimento o subentro | N. Bando, Sotto-bando, N. Protocollo, Data Protocollo, Tipologia di Utilizzo della Graduatoria |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Caricare il file e capire subito se è leggibile (Priority: P1)

L'addetta apre dal menu la pagina "File segreteria", sceglie il file Excel aggiornato e lo
carica. Il sistema lo legge e mostra un rapporto: quante righe e quanti atti ha trovato per
foglio, quali fogli o colonne non ha riconosciuto, quali righe non hanno numero di bando o
protocollo, quali date non sono leggibili, quanti scorrimenti non hanno la tipologia.

**Why this priority**: senza caricamento non c'è la terza fonte; senza rapporto non si sa se
fidarsi del confronto.

**Independent Test**: si carica `Graduatorie_Bandi_CNR.xlsx` e si verifica che il rapporto
indichi 47 bandi, 84 bandi con graduatoria, 175 righe di scorrimento e le righe senza
tipologia (50 nella versione del 2026-10-29).

**Acceptance Scenarios**:

1. **Given** il file con i tre fogli, **When** l'addetta lo carica, **Then** il sistema
   salva una nuova versione con data, ora e utente e mostra il rapporto di caricamento.
2. **Given** un file senza il foglio "Scorrimento" o con una colonna rinominata, **When**
   viene caricato, **Then** il rapporto indica il foglio o la colonna mancante e i fogli
   leggibili vengono comunque usati.
3. **Given** un file che non è un Excel o non ha nessuno dei tre fogli, **When** viene
   caricato, **Then** il caricamento è rifiutato con un messaggio chiaro e la versione
   precedente resta quella in uso.
4. **Given** righe con date scritte come testo ("03/06/2026") e altre come date, **When**
   il file viene caricato, **Then** entrambe vengono lette correttamente.

---

### User Story 2 - La segreteria come terza colonna della tabella degli atti (Priority: P1)

Nella tabella degli atti (spec 001) la colonna "File segreteria" mostra per ogni bando
pubblicato, graduatoria e scorrimento se l'atto è presente nel file (verde) o no (rosso).
Gli atti presenti solo nel file compaiono anch'essi, con URP e/o Selezioni Online in rosso.

**Why this priority**: è l'obiettivo dell'ufficio: vedere in una tabella sola cosa manca e
dove, usando il file della segreteria come riferimento.

**Independent Test**: dopo il caricamento, una graduatoria con lo stesso protocollo
pubblico nel file, su URP e su SOL compare in una riga con tre celle verdi; uno scorrimento
del file non presente su SOL compare con la cella SOL rossa.

**Acceptance Scenarios**:

1. **Given** una graduatoria con protocollo pubblico 254181 nel file e su URP e SOL,
   **When** si apre la tabella, **Then** la riga ha tre celle verdi.
2. **Given** uno scorrimento del file (es. bando 367.434 Cod. 13, protocollo 281920) che
   non compare su SOL, **When** si apre la tabella, **Then** la riga esiste e la cella SOL
   è rossa.
3. **Given** una graduatoria pubblicata su URP che non è nel file, **When** si apre la
   tabella, **Then** la cella "File segreteria" è rossa.
4. **Given** un atto con data precedente al periodo coperto dal foglio del file, **When**
   si apre la tabella, **Then** la cella "File segreteria" è grigia ("fuori periodo"), non
   rossa.
5. **Given** un atto con lo stesso numero di bando e la stessa data ma protocollo diverso
   tra file e un'altra fonte, **When** si apre la tabella, **Then** compare in una sola riga
   con la nota "protocollo diverso" e i numeri delle fonti.

---

### User Story 3 - Sottotipo affidabile degli scorrimenti (Priority: P2)

Per gli scorrimenti presenti nel file, il sottotipo (scorrimento o subentro) viene preso
dalla colonna "Tipologia di Utilizzo della Graduatoria" e mostrato come dato certo; quello
ricavato dal titolo dei documenti (spec 001) resta solo come indicazione quando il file non
lo dice. Le righe senza tipologia sono segnalate come "da completare".

**Why this priority**: il subentro non si riconosce dal titolo del documento; il file è
l'unica fonte che lo dice.

**Independent Test**: uno scorrimento con tipologia "Subentro" nel file e titolo generico su
URP compare in tabella con sottotipo "subentro" senza l'indicazione "dal titolo".

**Acceptance Scenarios**:

1. **Given** uno scorrimento con tipologia "Subentro" nel file, **When** si apre la tabella,
   **Then** il sottotipo è "subentro" con origine "file segreteria".
2. **Given** uno scorrimento senza tipologia nel file, **When** si apre la tabella, **Then**
   il sottotipo è "non specificato" e la riga riporta la nota "tipologia da completare nel
   file".
3. **Given** il sottotipo del file diverso da quello ricavato dal titolo, **When** si apre
   la tabella, **Then** vale quello del file e la differenza è riportata nella nota.

---

### User Story 4 - Consultare i dati del file per atto (Priority: P2)

Nella pagina "File segreteria" l'addetta vede i dati della versione in uso raggruppati per
atto (bando pubblicato, graduatoria, scorrimento), con filtri per mese e tipo, il numero di
persone per atto e, aprendo l'atto, l'elenco delle righe del file (posizione, nominativo,
punteggio, note).

**Why this priority**: serve per controllare il file stesso e per verificare un'anomalia
senza aprire Excel.

**Independent Test**: si filtra ottobre 2026 e tipo "scorrimento" e si verifica che compaiano
gli atti del foglio Scorrimento di quel mese con il numero di persone giusto.

**Acceptance Scenarios**:

1. **Given** una versione caricata, **When** si apre la pagina, **Then** compaiono gli atti
   con numero di bando, sotto-bando, protocollo, data, tipo e numero di persone.
2. **Given** un atto, **When** lo si apre, **Then** compaiono le righe del file con
   posizione, nominativo, punteggio o tipologia e note.
3. **Given** un bando del foglio Bandi di tipo "Selezione Direttore d'Istituto", **When**
   si apre la pagina, **Then** il bando è consultabile ma marcato "fuori ambito" e non entra
   nel confronto.

---

### User Story 5 - Vedere cosa è cambiato rispetto al caricamento precedente (Priority: P3)

Dopo ogni caricamento l'addetta vede gli atti nuovi, quelli spariti e quelli modificati
(es. protocollo o data cambiati, persone aggiunte) rispetto alla versione precedente.

**Why this priority**: aiuta a capire cosa ha aggiunto la segreteria dall'ultimo controllo,
ma il confronto tra fonti funziona anche senza.

**Independent Test**: si carica una versione, poi una seconda con uno scorrimento in più e
una data corretta; il riepilogo delle differenze mostra un atto nuovo e un atto modificato.

**Acceptance Scenarios**:

1. **Given** due versioni caricate, **When** si apre l'ultima, **Then** sono elencati atti
   nuovi, spariti e modificati con il dettaglio della modifica.
2. **Given** lo stesso file caricato due volte, **When** si apre l'ultima versione, **Then**
   il riepilogo indica "nessuna differenza".

---

### Edge Cases

- Il numero di bando è scritto in modi diversi: `390.475`, `390475`, `367.529 FA IGB`,
  `367.434 CA Cod. 14`, `367.434 CA. Codice 16`: si normalizza come nella spec 001 (numero
  bando più eventuale sotto-bando).
- Il foglio Graduatorie ha sia il numero con punto (`N. Bando`) sia quello senza
  (`N Bando`): se discordano vale `N. Bando` e la riga viene segnalata.
- Protocolli con zeri iniziali o salvati come numero (`0254181`, `254181`): stessa
  normalizzazione della spec 001.
- Protocollo privato e pubblico della stessa graduatoria sono diversi: il confronto con URP
  e SOL usa il pubblico; il privato viene conservato e mostrato.
- Il foglio Scorrimento ha un filtro automatico che copre solo parte delle righe: vanno
  lette tutte le righe, non solo quelle filtrate.
- Celle unite e colonne senza intestazione (es. note in colonne finali): ignorate senza
  bloccare il caricamento, e indicate nel rapporto.
- Lo stesso protocollo compare in più righe (una per persona): diventa un solo atto con il
  numero di persone.
- Un atto del file riguarda un bando che non esiste su URP né su SOL (es. un bando appena
  protocollato): compare in tabella con URP e SOL rossi.
- Il file viene caricato mentre è in corso una raccolta: il caricamento procede, la tabella
  si aggiorna a fine operazione.

## Requirements *(mandatory)*

### Functional Requirements

#### Caricamento e versioni

- **FR-001**: Il sistema MUST permettere a un utente autenticato di caricare un file Excel
  dalla pagina "File segreteria", raggiungibile dal menu comune (spec 001, FR-023).
- **FR-002**: Ogni caricamento riuscito MUST creare una nuova versione con data, ora, utente
  e nome del file; la versione più recente è quella usata nel confronto.
- **FR-003**: Un caricamento che non contiene nessuno dei tre fogli riconosciuti, o che non
  è un file Excel, MUST essere rifiutato senza cambiare la versione in uso.
- **FR-004**: Il sistema MUST riconoscere fogli e colonne dal nome (senza distinzione tra
  maiuscole e minuscole e spazi), non dalla posizione, e MUST elencare nel rapporto fogli e
  colonne attesi ma non trovati.
- **FR-005**: Il rapporto di caricamento MUST indicare per foglio: righe lette, atti
  ricavati, righe senza numero di bando, righe senza protocollo, date non leggibili, numeri
  di bando discordanti tra `N. Bando` e `N Bando`, scorrimenti senza tipologia.
- **FR-006**: Le versioni precedenti MUST restare consultabili; il sistema MUST mostrare le
  differenze tra una versione e la precedente (atti nuovi, spariti, modificati).

#### Lettura dei fogli

- **FR-007**: Dal foglio Bandi il sistema MUST ricavare un atto "bando pubblicato" per riga,
  con numero di bando, tipo di procedura, istituto, sede, oggetto, protocollo e data.
- **FR-008**: Dal foglio Graduatorie il sistema MUST ricavare un atto "graduatoria" per ogni
  combinazione di bando, sotto-bando e protocollo pubblico, conservando protocollo e data
  privati e il numero di persone.
- **FR-009**: Dal foglio Scorrimento il sistema MUST ricavare un atto "scorrimento" per ogni
  combinazione di bando, sotto-bando e protocollo, con sottotipo dalla colonna "Tipologia di
  Utilizzo della Graduatoria" (Scorrimento → scorrimento, Subentro → subentro, vuoto → non
  specificato) e il numero di persone.
- **FR-010**: La colonna "Presenza stato avanzamento" MUST essere ignorata.
- **FR-011**: I bandi con tipo di procedura fuori ambito (es. "Selezione Direttore
  d'Istituto", revoche) MUST essere salvati e consultabili ma esclusi dal confronto; l'elenco
  dei tipi in ambito MUST essere configurabile.

#### Confronto

- **FR-012**: Gli atti del file MUST essere collegati ai bandi della spec 001 tramite numero
  di bando (e sotto-bando quando presente) e, per graduatorie e scorrimenti, tramite
  protocollo pubblico, con la stessa normalizzazione della spec 001.
- **FR-013**: La tabella degli atti (spec 001, FR-021) MUST mostrare nella colonna "File
  segreteria" lo stato presente/mancante per ogni atto, e MUST includere gli atti presenti
  solo nel file.
- **FR-014**: Un atto MUST risultare "mancante" nel file solo se la sua data rientra nel
  periodo coperto dal foglio corrispondente (dalla data più vecchia del foglio in poi);
  prima di quel periodo la cella è "fuori periodo".
- **FR-015**: Quando file e un'altra fonte hanno lo stesso bando, lo stesso tipo di atto e la
  stessa data ma protocolli diversi, il sistema MUST mostrarli come un unico atto con la nota
  "protocollo diverso" e i numeri delle fonti.
- **FR-016**: Per gli scorrimenti presenti nel file, il sottotipo del file MUST prevalere su
  quello ricavato dal titolo e MUST essere indicato come dato del file; le differenze tra i
  due MUST essere riportate nella nota della riga.
- **FR-017**: Il file è la fonte di riferimento ma può contenere errori: le differenze MUST
  essere mostrate come segnalazioni da verificare, senza modificare i dati di nessuna fonte
  (constitution, Principio I).

#### Consultazione e dati personali

- **FR-018**: La pagina "File segreteria" MUST mostrare gli atti della versione in uso con
  filtri per mese e tipo, il numero di persone per atto e, aprendo un atto, le righe del
  file con posizione, nominativo, punteggio o tipologia e note.
- **FR-019**: Nominativi e punteggi MUST essere salvati solo nel database, visibili solo a
  utenti autenticati, e MUST NOT comparire nei log, nei messaggi di errore o nel repository
  (constitution, Principio II). Il file caricato MUST NOT essere salvato nella cartella del
  codice.

### Key Entities

- **Versione del file**: un caricamento, con data, ora, utente, nome del file, rapporto di
  caricamento ed esito.
- **Riga del file**: una riga di un foglio della versione, con i valori originali delle
  colonne (compresi nominativi) e i valori normalizzati usati per il confronto.
- **Atto della segreteria**: bando pubblicato, graduatoria o scorrimento ricavato dalle righe
  di una versione (bando, sotto-bando, protocollo, data, sottotipo, numero di persone,
  in ambito sì/no), collegato al bando della spec 001.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Il caricamento del file attuale (circa 1.000 righe) e il rapporto di
  caricamento sono pronti in meno di 30 secondi.
- **SC-002**: Il 100% delle righe del file con numero di bando e protocollo viene
  trasformato in un atto; il resto è elencato nel rapporto.
- **SC-003**: Almeno il 95% degli atti in ambito del file con data dal 2026-01-01 risulta
  collegato a un bando presente su URP o SOL; i restanti sono visibili in tabella come
  presenti solo nel file.
- **SC-004**: Dalla tabella degli atti l'addetta ottiene in meno di un minuto l'elenco degli
  scorrimenti del mese presenti nel file ma non pubblicati su URP o SOL.
- **SC-005**: Nessun nominativo compare nei log dell'app né nei file del repository dopo un
  caricamento.

## Assumptions

- Il file viene caricato a mano dall'addetta quando serve (es. prima di un controllo); la
  lettura automatica da SharePoint è fuori scopo.
- Il protocollo del foglio Scorrimento è quello pubblico, lo stesso pubblicato su URP e SOL
  (da verificare con i dati al primo caricamento).
- Il protocollo "Prot. CNR n." del foglio Bandi è il protocollo del bando, lo stesso di URP.
- Tipi di procedura in ambito: concorsi pubblici (anche CTER, Tecnologo, per titoli e
  colloquio), bandi di mobilità; fuori ambito: selezioni di Direttori, revoche. L'elenco si
  può modificare.
- Qualunque utente autenticato dell'app può caricare il file e vedere i nominativi; ruoli
  più restrittivi sono fuori scopo per ora.
- La struttura dei fogli resta quella del 2026-10-29; colonne nuove vengono conservate e
  ignorate nel confronto.

## Out of Scope

- Lettura automatica del file da SharePoint o OneDrive.
- Modifica del file dall'app o invio di correzioni alla segreteria.
- Confronto dei nominativi e dei punteggi del file con quelli di Selezioni Online (richiede
  il login SOL, spec successiva).
- Solleciti automatici via email.
