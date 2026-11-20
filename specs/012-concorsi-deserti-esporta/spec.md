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

## Requirements *(mandatory)*

- **FR-001**: Nuove categorie di documento `deserto` e `revocato` (schema 34); i documenti già salvati vengono riclassificati.
- **FR-002**: Il tipo SOL `call_deserto` prevale sul titolo.
- **FR-003**: Lo stato complessivo confronta deserti e revoche su SOL, URP e segreteria come gli altri atti; un deserto URP con titolo generico si riconosce dal protocollo del deserto SOL dello stesso bando.
- **FR-004**: Righe "senza esito" (US3) solo nello stato complessivo, non nei monitoraggi mensili, indipendenti dal periodo scelto.
- **FR-005**: Esportazione Excel delle righe visibili con le colonne scelte; per i soli utenti con accesso alla pagina (Principio IV); nessun dato dei candidati (Principio II).
- **FR-006**: Nessuna scrittura sulle fonti (Principio III); nessuna correzione automatica: le difformità si mostrano (Principio I).

## Fuori ambito

- Controllo delle domande e dei punteggi per i bandi senza esito (serve la sessione SOL): spec successiva.
- Deserti e revoche nel file della segreteria.
