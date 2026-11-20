# Feature Specification: Concorsi deserti, bandi revocati, bandi senza esito ed esportazione Excel

**Feature Branch**: `012-concorsi-deserti-esporta`

**Created**: 2026-11-20

**Status**: Implementata; verifica nell'app con i dati reali pendente

**Input**: Richiesta dell'utente del 2026-11-20: recuperare i concorsi andati deserti da URP e Selezioni Online; nel monitoraggio e nello stato complessivo un filtro per i bandi andati deserti, anche per anno (es. 2026), sempre con il confronto tra URP, SOL e file della segreteria (che oggi non ha questi dati); capire se ci sono concorsi pubblici deserti a cui non è stato caricato il documento; poter estrarre la lista in Excel scegliendo le colonne, in modo generico per lo stato complessivo.

## Contesto (analisi del 2026-11-20, solo lettura delle fonti pubbliche)

- **Selezioni Online** ha un tipo di allegato apposito, `call_deserto` (297 documenti in tutto, ognuno con numero e data di protocollo). Il sistema già li scarica con gli allegati del bando ma li classifica "altro".
- **URP** non ha un tipo: il deserto si riconosce dal titolo ("conclusione del procedimento con esito negativo", "concorso deserto", "senza vincitori"...) ma spesso il titolo è generico ("Esito", "Esito concorso", "Conclusione procedura"): in 7 casi il deserto si riconosce solo perché il protocollo è lo stesso del documento di deserto su SOL.
- Concorsi pubblici a tempo indeterminato con scadenza dal 2022 (501 bandi o sedi su SOL): 420 con graduatoria, 19 con documento di deserto, 62 senza nessuno dei due. Di questi: 3 deserti su URP ma non su SOL (367.391, 367.455, 367.372 «Esito»), 4 revocati (367.390, 367.417, 367.438, 367.625), 4 con graduatoria solo su URP, gli altri in corso.
- Un caso da verificare: 367.433 FA, protocollo 211903, deserto su SOL e "Graduatoria – cod. 04" su URP.
- Il file della segreteria non ha oggi deserti né revoche.

## Decisioni (2026-11-20)

- I revocati sono un tipo a parte, con il loro filtro (non sono deserti).
- Un concorso pubblico è "senza esito" se le domande sono scadute da più di 12 mesi e su nessuna fonte c'è graduatoria, deserto o revoca.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deserti e revocati come atti (Priority: P1)

Il sistema classifica i documenti di deserto e di revoca e li mostra come atti nello stato complessivo e nel monitoraggio, confrontando SOL, URP e file della segreteria.

**Acceptance Scenarios**:

1. **Given** un allegato SOL di tipo `call_deserto`, **When** si classifica, **Then** è "deserto" qualunque sia il titolo.
2. **Given** un allegato URP con "esito negativo", "deserto/a", "senza vincitori/candidati/graduatoria", **When** si classifica, **Then** è "deserto"; "esito negativo prova…" no.
3. **Given** un allegato URP con titolo generico ("Esito"), **When** il suo protocollo è quello di un deserto SOL dello stesso bando, **Then** nello stato complessivo vale come deserto presente su URP.
4. **Given** "Revoca bando", "Provvedimento di revoca", "Decreto revoca bando", **When** si classifica, **Then** è "revocato"; la revoca di una nomina di commissione no.
5. **Given** un deserto su SOL e non su URP (o viceversa), **When** si guarda lo stato complessivo, **Then** la fonte mancante è "mancante" come per gli altri atti.
6. **Given** il file della segreteria senza questi atti, **When** si guarda la colonna segreteria, **Then** è "non nel file" (grigio, non difformità).

### User Story 2 - Filtri (Priority: P1)

Nello stato complessivo il tipo di atto ha "Concorsi deserti", "Bandi revocati" e "Senza esito da oltre 12 mesi"; c'è un filtro Anno che imposta il periodo. Nel monitoraggio (amministratore e area referenti) ci sono le schede "Deserti" e "Revocati".

### User Story 3 - Bandi senza esito (Priority: P2)

Lo stato complessivo elenca i concorsi pubblici (tempo indeterminato) con domande scadute da più di 12 mesi e senza graduatoria, deserto o revoca su SOL e URP, sede per sede, con il link a SOL e URP, per verificare se manca il documento.

### User Story 4 - Esporta in Excel (Priority: P1)

Dallo stato complessivo si scarica un file Excel delle righe filtrate scegliendo le colonne; la scelta resta memorizzata nel browser. È generico: funziona con qualunque filtro (deserti dell'anno, scorrimenti, difformità...).

### User Story 5 - Controllo su SOL dei concorsi senza esito (Priority: P1, richiesta del 2026-11-20)

L'amministratore, collegato a Selezioni Online, preme «Controlla su SOL i concorsi senza esito»: per ogni concorso senza esito si leggono domande e punteggi (nel database solo i conteggi). Il concorso è **probabile deserto** solo con una prova positiva, mai per la sola mancanza dei punteggi:

- nessuna domanda valida su SOL, oppure punteggi inseriti per tutti i candidati e tutti non ammessi ad almeno una prova;
- e nessuna graduatoria, deserto o revoca su SOL e URP, e nessuna graduatoria o scorrimento nel file della segreteria.

Se il file della segreteria parte dopo la scadenza delle domande (mesi in cui il file non esisteva) la riga lo dice: il file non conferma né smentisce. Punteggi mancanti o parziali: «non si può dire» (dati forse non inseriti). Vincitori o idonei su SOL senza graduatoria pubblicata: «graduatoria mancante». Filtro «Probabili deserti (controllati su SOL)»; l'esito del controllo va anche nell'Excel.

### User Story 6 - Scheda «Concorsi deserti» e richiesta ai referenti (Priority: P1, richiesta del 2026-11-20)

Nello stato complessivo (amministratore e area referenti) una scheda «Concorsi deserti», su tutti gli anni, mostra insieme tutti i casi con uno stato e un filtro per stato:

- **Deserto con provvedimento**: c'è il provvedimento su SOL e/o URP (certo);
- **Deserto senza provvedimento**: SOL lo dimostra (US5) ma il provvedimento manca;
- **Non deserto: manca la graduatoria**: vincitori o idonei su SOL senza graduatoria pubblicata;
- **Da verificare con i referenti**: nessun esito su nessuna fonte e SOL non basta per concludere;
- **Probabilmente in corso**: nessun esito ma documenti pubblicati negli ultimi 6 mesi (convocazioni, commissione...).

Dalla scheda l'amministratore scrive agli RdP del concorso (in copia la segreteria, come per gli avvisi degli scorrimenti): «è andato deserto o mancano i dati?», con anteprima modificabile, prova o invio reale e registro degli invii. Nel monitoraggio del mese la scheda «Concorsi deserti» è sempre visibile.

### User Story 7 - Sedi senza vincitori e esito segnato a mano (Priority: P1, richiesta del 2026-11-20)

Nei bandi con più codici la graduatoria è spesso unica per tutto il bando e dichiara al suo interno i codici andati deserti (es. 367.501: cod. 03 e 07 «conclusione con esito negativo»). Per ogni sede con una graduatoria (o uno scorrimento) del bando intero ma non sua, senza limite di tempo: se su Selezioni Online la sede non ha vincitori né idonei, la scheda «Concorsi deserti» mostra «Possibile deserto: sede senza vincitori» con il bando padre; se non è ancora controllata su SOL si conta a parte («N sedi da controllare») e il controllo su SOL la include. Con domande valide zero o tutti non ammessi resta «deserto senza provvedimento».

Dopo la risposta dei referenti l'amministratore segna a mano «Deserto» o «Non deserto», con una nota (tabella `esito_segnato`, schema 37): la segnatura vale sopra le regole, si vede con chi e quando, si può annullare. I PDF delle graduatorie non vengono letti dal sistema.

## Requirements *(mandatory)*

- **FR-001**: Nuove categorie di documento `deserto` e `revocato` (schema 34); i documenti già salvati vengono riclassificati.
- **FR-002**: Il tipo SOL `call_deserto` prevale sul titolo.
- **FR-003**: Lo stato complessivo confronta deserti e revoche su SOL, URP e segreteria come gli altri atti; un deserto URP con titolo generico si riconosce dal protocollo del deserto SOL dello stesso bando.
- **FR-004**: Righe "senza esito" (US3) solo nello stato complessivo, non nei monitoraggi mensili, indipendenti dal periodo scelto.
- **FR-005**: Esportazione Excel delle righe visibili con le colonne scelte; per i soli utenti con accesso alla pagina (Principio IV); nessun dato dei candidati (Principio II).
- **FR-007**: Controllo su SOL dei concorsi senza esito (US5): nuovo conteggio «non ammessi» nella verifica dei punteggi (schema 35), solo numeri.
- **FR-008**: Tabella `richiesta_deserto` (schema 36) per il registro delle richieste; nessun dato dei candidati nel testo (blocco del codice fiscale).
- **FR-006**: Nessuna scrittura sulle fonti (Principio III); nessuna correzione automatica: le difformità si mostrano (Principio I).

## Fuori ambito

- Deserti e revoche nel file della segreteria.
