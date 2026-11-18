# Feature Specification: Verifica dei file Excel del mese e revisione del monitoraggio

**Feature Branch**: `011-verifica-file-revisione`

**Created**: 2026-11-18

**Status**: Implementata; verifica con i file reali di ottobre nell'app pendente

**Input**: Richiesta dell'utente del 2026-11-18: la verifica del file Excel deve confrontare in entrambe le direzioni ciò che il monitoraggio del mese ha nel database con ciò che c'è nel file, anche candidato per candidato; dalla tabella di ciò che non torna si deve poter scrivere agli RdP del bando chiedendo di verificare e correggere il file, con il link OneDrive; lo stesso per l'estrazione delle graduatorie da Selezioni Online, che poi va a compilare il file graduatorie; il monitoraggio si deve poter mandare "in revisione", con una pagina di riepilogo con i totali, i due file Excel da vedere e scaricare e il testo modificabile, e con un'email ai coordinatori e alle persone dell'ufficio; i link ai file su OneDrive devono comparire nell'area referenti e coordinatori.

## Contesto

Oggi il caricamento del file scorrimenti compilato controlla, per ogni scorrimento del monitoraggio, se il bando è nel file (stesso numero di bando e protocollo, oppure stesso bando se la riga non ha protocollo), la tipologia scritta e il subentro atteso; elenca le righe del file senza uno scorrimento del mese. Non legge i nominativi. Il file graduatorie viene generato dal sistema e non viene verificato.

Dal file scorrimenti di ottobre 2026 (struttura letta il 2026-11-18, senza nominativi): un foglio per gruppo di concorsi (CTER 6, FUNZ 5, COLL.AMM, OTP, DT, RIC), intestazione alla riga 2 con BANDO SU CUI SCORRERE, N. POSIZIONI, STRUTTURA RICHIEDENTE, PROT. RICHIESTA, NOMINATIVI SCORRIMENTI, PROVVEDIMENTO DG, PROVVEDIMENTO RECLUTAMENTO, TIPOLOGIA; il bando scritto in molti modi («367.434 Cod. 13 ROMA», «367434 Cod. 14 NAPOLI», «367.524 CTER - COD. 02 AR BO»); il protocollo nel testo («461293 DEL 28/10/2026»); una riga per nominativo; righe «TOTALE UNITÀ».

L'estrazione delle graduatorie da Selezioni Online è l'export «Punteggi» (.xls; struttura letta il 2026-11-18, senza dati personali): un foglio «Punteggi», una riga per candidato, colonne Codice bando, Sede di lavoro, Struttura di riferimento, N. Posti, Profilo/Livello, Username, Cognome, Nome, Data di nascita, Codice Fiscale, Matricola, Email, Email PEC, Numero Protocollo (della domanda), Totale Punteggi, Graduatoria (posizione), Esito (V vincitore, I idoneo, S assunto da scorrimento, R), Note, Data e Numero Protocollo Graduatoria, Data e Numero Protocollo Assunzione Idoneo, Data Ultima Modifica. Sono le stesse colonne del foglio graduatorie che il sistema genera oggi dai punteggi letti da SOL. Nell'esempio: 200 candidati di 22 bandi di tre profili.

L'utente segnala che nella verifica non vede molti scorrimenti del mese che sono nel monitoraggio ma non nel file, per esempio dei CTER: la verifica deve mostrarli tutti.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Verifica completa del file scorrimenti (Priority: P1)

L'amministratore carica il file scorrimenti compilato. Il sistema mostra una tabella unica di ciò che non torna tra il monitoraggio del mese e il file, in entrambe le direzioni e anche per persona, con il riferimento a foglio e riga.

**Why this priority**: è lo strumento di controllo del mese; oggi alcune mancanze non si vedono.

**Independent Test**: Con un monitoraggio che ha 5 scorrimenti e un file che ne riporta 3 (uno senza tipologia, uno con un nominativo che non è nel file della segreteria) più una riga di un bando non presente nel monitoraggio, la tabella elenca: 2 scorrimenti mancanti nel file, 1 tipologia vuota, 1 nominativo non presente, 1 riga in più nel file.

**Acceptance Scenarios**:

1. **Given** uno scorrimento nel monitoraggio, **When** non c'è nel file, **Then** compare come "manca nel file" con bando, protocollo, data, profilo e RdP.
2. **Given** due scorrimenti dello stesso bando, **When** il file ha una sola riga per quel bando, **Then** una sola riga del file vale per un solo scorrimento: l'altro risulta mancante.
3. **Given** una riga del file trovata, **When** manca la tipologia, il protocollo del provvedimento o il subentro atteso, **Then** ogni mancanza è indicata a parte.
4. **Given** una riga del file, **When** il bando o il protocollo non corrispondono a nessuno scorrimento del monitoraggio, **Then** compare come "nel file ma non nel monitoraggio, da verificare".
5. **Given** uno scorrimento trovato, **When** i nominativi del file e quelli del file della segreteria per lo stesso bando e protocollo sono diversi, **Then** la tabella indica il nominativo mancante o in più e il numero di posizioni dichiarato e reale.
6. **Given** una tipologia nel file diversa da quella del file della segreteria (scorrimento, subentro, cessazione dopo i 6 mesi), **When** si verifica, **Then** è indicata come diversa.
7. **Given** il file ricaricato dopo le correzioni, **When** tutto torna, **Then** la tabella dice "allineato" e il riepilogo lo riporta.

---

### User Story 2 - Richiesta di correzione agli RdP del bando (Priority: P1)

Dalla tabella di ciò che non torna, per ogni bando l'amministratore apre un'email agli RdP di quel bando con l'elenco delle cose che non tornano e il link al file su OneDrive, chiedendo di verificare e, se serve, di correggere il file, con la precisazione che la difformità potrebbe essere un errore nostro.

**Why this priority**: è il modo per chiudere le mancanze senza scrivere a mano ogni email.

**Independent Test**: Su un bando con due mancanze, "Chiedi verifica" apre l'anteprima con destinatari RdP, le due mancanze, il link del file scorrimenti; inviata in prova, resta registrata con data.

**Acceptance Scenarios**:

1. **Given** un bando con mancanze, **When** l'amministratore preme "Chiedi verifica", **Then** vede l'anteprima con gli RdP del bando come destinatari, le mancanze di quel bando, il link OneDrive del file e il testo modificabile.
2. **Given** l'invio, **When** parte, **Then** segue le impostazioni email (prova / ufficiali) e resta registrato per il bando con data, destinatari ed elenco delle mancanze.
3. **Given** una richiesta già inviata, **When** si riapre la tabella, **Then** il bando mostra "richiesta inviata il …".
4. **Given** i nominativi nella tabella, **When** si prepara l'email, **Then** l'email li può contenere solo se l'amministratore li lascia nel testo; i nominativi non compaiono mai nei log.

---

### User Story 3 - Verifica dell'estrazione delle graduatorie e compilazione del file graduatorie (Priority: P1)

L'amministratore carica l'estrazione delle graduatorie del mese scaricata da Selezioni Online. Il sistema la confronta con le graduatorie del monitoraggio (entrambe le direzioni e per persona, come gli scorrimenti) e, con i dati che tornano, compila il file graduatorie con i nominativi ordinati per punteggio e divisi per gruppi di concorsi.

**Why this priority**: il file graduatorie oggi dipende dalla lettura dei punteggi; l'estrazione dà i nominativi completi del mese.

**Independent Test**: Con un'estrazione che contiene 3 delle 4 graduatorie del monitoraggio, la verifica segnala la graduatoria mancante; il file graduatorie generato ha i nominativi delle 3, ordinati per punteggio decrescente, nel foglio del loro gruppo.

**Acceptance Scenarios**:

1. **Given** una graduatoria nel monitoraggio, **When** non c'è nell'estrazione, **Then** compare come "manca nell'estrazione".
2. **Given** una graduatoria nell'estrazione, **When** non è nel monitoraggio, **Then** compare come "nell'estrazione ma non nel monitoraggio, da verificare".
3. **Given** una graduatoria in entrambe, **When** nominativi, posizioni, punteggi o protocolli non coincidono con il file della segreteria, **Then** la differenza è indicata per persona.
4. **Given** l'estrazione verificata, **When** l'amministratore genera il file graduatorie, **Then** i nominativi sono ordinati per punteggio e divisi per gruppi di concorsi.
5. **Given** le mancanze, **When** l'amministratore chiede la verifica agli RdP, **Then** vale lo stesso flusso della User Story 2 con il link del file graduatorie.

---

### User Story 4 - Riepilogo del monitoraggio, sempre aggiornato (Priority: P1)

Nel monitoraggio c'è una pagina di riepilogo, disponibile anche prima della chiusura, che mostra lo stato di ciò che si sta verificando e che andrà nel monitoraggio: i totali, l'esito delle verifiche dei due file, i due file Excel da vedere e scaricare e il testo di accompagnamento modificabile.

**Why this priority**: dà la panoramica del mese in un solo posto.

**Independent Test**: Il riepilogo di ottobre mostra i totali per categoria e per profilo, i due file scaricabili e il testo; modificando il testo, la modifica resta salvata.

**Acceptance Scenarios**:

1. **Given** un monitoraggio, **When** si apre il riepilogo, **Then** si vedono: bandi pubblicati, graduatorie (numero di bandi con graduatoria), scorrimenti, subentri, ciascuno in totale, per profilo e separato tra concorsi e mobilità; per gli scorrimenti anche per tipologia (scorrimento, subentro, cessazione dopo i 6 mesi).
2. **Given** le verifiche dei file, **When** si apre il riepilogo, **Then** c'è l'esito di ciascun file (allineato / N cose da verificare / non caricato).
3. **Given** i due file Excel, **When** l'amministratore li apre dal riepilogo, **Then** può vederne il contenuto nella pagina e scaricarli.
4. **Given** il testo di accompagnamento, **When** l'amministratore lo modifica, **Then** resta salvato per quel monitoraggio e si può riportare al testo generale.

---

### User Story 5 - Mandare il monitoraggio in revisione (Priority: P1)

L'amministratore manda il monitoraggio "in revisione" anche se non tutto è allineato. Parte un'email ai coordinatori e alle persone dell'ufficio con il link alla pagina del monitoraggio e le tabelle dei totali, perché verifichino lo stato. Poi il monitoraggio si chiude come oggi.

**Why this priority**: è il passaggio di controllo condiviso prima dell'invio del monitoraggio.

**Independent Test**: Mandato in revisione con le email in prova, arriva un'email con il link e le tabelle dei totali; il monitoraggio risulta "in revisione" e si può ancora aggiornare e chiudere.

**Acceptance Scenarios**:

1. **Given** un monitoraggio in corso, **When** l'amministratore lo manda in revisione, **Then** lo stato diventa "in revisione" e resta modificabile.
2. **Given** l'invio della revisione, **When** parte, **Then** va ai coordinatori e alle persone dell'ufficio (elenco delle Impostazioni), con il link alla pagina del monitoraggio e le tabelle: graduatorie (numero di bandi con graduatoria) per profilo, scorrimenti in totale e per profilo con la tipologia, mobilità (graduatorie e scorrimenti), bandi pubblicati.
3. **Given** un coordinatore o un referente dell'ufficio, **When** apre il link, **Then** vede il riepilogo del monitoraggio con i totali nella sua area.
4. **Given** un monitoraggio in revisione, **When** l'amministratore lo chiude, **Then** si chiude come oggi.

---

### User Story 6 - Link ai file Excel nell'area referenti e coordinatori (Priority: P2)

Nell'area referenti e coordinatori, per ogni monitoraggio in corso o in revisione, ci sono i link al file scorrimenti e al file graduatorie su OneDrive.

**Independent Test**: Con i link salvati nel monitoraggio di ottobre, un RdP che entra nell'area vede i due link e li apre su OneDrive.

**Acceptance Scenarios**:

1. **Given** un monitoraggio in corso con i link salvati, **When** un referente o un coordinatore apre l'area, **Then** vede i due link.
2. **Given** un monitoraggio chiuso, **When** apre l'area, **Then** i link non ci sono.
3. **Given** un link mancante, **When** apre l'area, **Then** quel file è indicato "non ancora disponibile".

### Edge Cases

- Bando scritto in modi diversi nel file («367434», «367.434 Cod. 13 ROMA», «367.524 CTER - COD. 02 AR BO»): si riconosce numero di bando e sede.
- Righe «TOTALE UNITÀ» e righe vuote: ignorate.
- Più nominativi nella stessa cella o una riga per nominativo: entrambi riconosciuti.
- Nominativi scritti con maiuscole, accenti o ordine nome/cognome diversi: confronto normalizzato; nei casi dubbi "da verificare", non "mancante".
- File della segreteria non caricato per il mese: il confronto per persona dice "file della segreteria non disponibile".
- Estrazione SOL di un altro mese: segnalata prima del confronto.

## Requirements *(mandatory)*

### Functional Requirements

**Verifica file scorrimenti**

- **FR-001**: Il sistema MUST confrontare ogni scorrimento del monitoraggio con le righe del file e ogni riga del file con gli scorrimenti del monitoraggio; una riga del file MUST valere per un solo scorrimento.
- **FR-002**: Per ogni scorrimento trovato MUST indicare a parte: tipologia vuota, protocollo del provvedimento mancante, subentro atteso non indicato, tipologia diversa dal file della segreteria.
- **FR-003**: Il sistema MUST confrontare i nominativi del file con quelli del file della segreteria per lo stesso bando e protocollo, e il numero di posizioni dichiarato con quello reale.
- **FR-004**: La tabella di ciò che non torna MUST riportare per ogni voce: bando, protocollo, data, profilo, RdP, cosa non torna, foglio e riga del file.

**Dati personali** (scelta dell'utente del 2026-11-18, sostituisce per questa verifica la decisione del 2026-11-11 di non leggere i nominativi)

- **FR-005**: I nominativi del file scorrimenti e dell'estrazione SOL MUST essere letti e mostrati solo agli amministratori, MUST NOT comparire nei log e MUST NOT essere inviati a servizi esterni; nelle email ai referenti compaiono solo se l'amministratore li lascia nel testo.

**Richiesta di correzione**

- **FR-006**: Per ogni bando con mancanze MUST esserci "Chiedi verifica": email agli RdP del bando con le mancanze, il link OneDrive del file e la richiesta di verificare e correggere, precisando che la difformità può essere un errore dell'ufficio; testo modificabile; invii secondo le impostazioni email; ogni richiesta registrata con data, destinatari e mancanze.

**Estrazione graduatorie SOL**

- **FR-007**: Il sistema MUST accettare l'estrazione delle graduatorie scaricata da Selezioni Online e confrontarla con le graduatorie del monitoraggio come per gli scorrimenti (FR-001, FR-003, FR-004).
- **FR-008**: Il file graduatorie MUST poter essere generato con i nominativi dell'estrazione ordinati per punteggio e divisi per gruppi di concorsi.

**Riepilogo e revisione**

- **FR-009**: Il monitoraggio MUST avere una pagina di riepilogo, disponibile prima della chiusura, con i totali di FR-010, l'esito delle verifiche dei file, i due file Excel da vedere e scaricare e il testo di accompagnamento modificabile.
- **FR-010**: I totali MUST essere: bandi pubblicati, bandi con graduatoria, scorrimenti, subentri; in totale, per profilo e separati tra concorsi e mobilità; gli scorrimenti anche per tipologia.
- **FR-011**: Il monitoraggio MUST poter passare "in revisione" in qualsiasi momento prima della chiusura; in revisione resta modificabile e si chiude come oggi.
- **FR-012**: Mandandolo in revisione MUST partire un'email ai coordinatori e alle persone dell'ufficio con il link alla pagina del monitoraggio e le tabelle dei totali; l'invio resta registrato.
- **FR-013**: Coordinatori e referenti MUST vedere il riepilogo con i totali del monitoraggio in revisione nella loro area.

**Area referenti**

- **FR-014**: L'area referenti e coordinatori MUST mostrare i link OneDrive dei file scorrimenti e graduatorie per ogni monitoraggio in corso o in revisione.

### Key Entities

- **Verifica di un file**: monitoraggio, tipo (scorrimenti / estrazione graduatorie), nome del file, chi e quando, esito per voce.
- **Voce da verificare**: bando, atto, protocollo, data, tipo di differenza, dettaglio, foglio e riga.
- **Richiesta di verifica**: monitoraggio, bando, file, destinatari, mancanze, data, esito dell'invio.
- **Revisione**: monitoraggio, data, chi, destinatari, esito dell'invio.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Il 100% degli scorrimenti del monitoraggio assenti nel file compare nella tabella (nessun caso "non visto" come i CTER segnalati).
- **SC-002**: L'amministratore manda la richiesta di verifica di un bando in meno di 1 minuto dalla tabella.
- **SC-003**: Il riepilogo del mese si apre con tutti i totali senza calcoli a mano.
- **SC-004**: Mandare in revisione richiede un solo passaggio e l'email arriva a tutti i coordinatori e alle persone dell'ufficio.

## Precisazioni dell'utente del 2026-11-18

- I nomi veri sono quelli dell'estrazione «Punteggi» di Selezioni Online; da lì vengono anche gli assunti da scorrimento (esito S con protocollo di assunzione idoneo), che possono mancare se su SOL non è stato aggiornato (resta rosso nel monitoraggio).
- Gli errori minori (nomi scritti in modo diverso, posizioni e punteggi diversi, foglio o bando scritto male, dati SOL non aggiornati) stanno a parte; le differenze di punteggio per ora contano poco, quelle di protocollo vanno bene e non si segnalano.
- Gli scorrimenti si mostrano divisi per tipologia, con le righe rosse se mancano nel file, quelle presenti e il totale; si segnala un bando per cui il file indica più scorrimenti o subentri di quelli che risultano dal file della segreteria e da URP.
- Una graduatoria che risulta nel file della segreteria (o nel monitoraggio) e manca nell'estrazione SOL è rossa.
- C'è anche l'estrazione delle graduatorie di mobilità (stesso export, caricato a parte): si verifica come le altre e va nel foglio «Graduatorie mobilità» del file da scaricare.

## Assumptions

- Il file della segreteria è il riferimento per il confronto per persona (scelta dell'utente), insieme a URP per la presenza dell'atto.
- Le "persone dell'ufficio" sono l'elenco delle Impostazioni già usato dall'avviso scorrimenti (spec 009); i coordinatori sono quelli dell'area referenti.
- I gruppi di concorsi sono quelli dei fogli del file scorrimenti (CTER, FUNZ, COLL.AMM, OTP, DT, RIC), ricavati dal profilo; la mobilità a parte.
- L'estrazione SOL è l'export «Punteggi» descritto nel Contesto. Si salva nel database del monitoraggio (dati personali visibili solo agli amministratori, FR-005) perché serve a generare il file graduatorie e il riepilogo; un nuovo caricamento sostituisce il precedente. Gli esiti S con il protocollo di assunzione idoneo servono anche a controllare gli scorrimenti.
- I link OneDrive sono quelli già salvati nel monitoraggio; l'accesso ai file resta regolato da OneDrive.
