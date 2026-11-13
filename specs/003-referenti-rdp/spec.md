# Feature Specification: Referenti RdP dei bandi da Selezioni Online

**Feature Branch**: `003-referenti-rdp` (spec scritta sul branch `001-raccolta-dati-bandi`)

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "Per ogni bando i referenti (RdP) presi da Selezioni Online come
fatto in chekin-cnr-concorsi. La chiamata usa il token SSO dell'utente collegato (Authorization:
Bearer), quello del login Keycloak CNR; niente password personali nel codice. Usare il Keycloak
di Selezioni Online in produzione (client `selezioni`), come per il check-in."

## Contesto

Per sollecitare chi non ha caricato graduatorie, punteggi o scorrimenti, l'ufficio deve sapere
chi è il responsabile del procedimento (RdP) di ogni bando. Selezioni Online espone gli RdP di
ogni bando nell'API `openapi/v1/call` con il dettaglio RdP; `chekin-cnr-concorsi` la usa con il
token SSO dell'utente collegato. Il vecchio metodo di questo progetto (`fetch_bandi_rdp.py`,
gruppi via `/rest/proxy` con credenziali fisse) è stato abbandonato in chekin per l'uso di
credenziali personali e non va riusato.

Verifica del 2026-10-29: l'API risponde anche senza login e restituisce per ogni RdP anche
codice fiscale, matricola ed email personali. È un problema di Selezioni Online da segnalare ai
Sistemi Informativi; questa spec non si basa sull'accesso anonimo e salva solo i dati necessari.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Vedere gli RdP di ogni bando (Priority: P1)

L'addetta, collegata con il proprio account SSO, preme "Aggiorna referenti": il sistema legge
da Selezioni Online gli RdP di tutti i bandi monitorati e li mostra nella tabella degli atti e
nel dettaglio del bando (nome, cognome, email istituzionale).

**Why this priority**: è l'informazione che serve per sapere a chi scrivere.

**Independent Test**: con un utente collegato si aggiornano i referenti; un bando con due RdP
su Selezioni Online mostra due nomi nella tabella degli atti.

**Acceptance Scenarios**:

1. **Given** un utente collegato con SSO, **When** preme "Aggiorna referenti", **Then** il
   sistema legge gli RdP con il suo token e li salva per ogni bando SOL monitorato.
2. **Given** un utente non collegato, **When** preme "Aggiorna referenti", **Then** riceve il
   messaggio di fare il login e nessuna chiamata parte.
3. **Given** il token scaduto ma rinnovabile, **When** si aggiornano i referenti, **Then** il
   token viene rinnovato in automatico senza nuovo login.
4. **Given** Selezioni Online non raggiungibile o che rifiuta il token, **When** si aggiornano
   i referenti, **Then** l'aggiornamento risulta fallito con il motivo e i referenti già
   salvati restano.

---

### User Story 2 - Filtrare gli atti per RdP (Priority: P1)

Nella tabella degli atti l'addetta sceglie un RdP e vede solo gli atti dei suoi bandi, per
esempio quelli incompleti, così sa cosa chiedergli.

**Why this priority**: trasforma l'elenco delle anomalie in un elenco di solleciti per persona.

**Independent Test**: con il filtro RdP e "solo incompleti" compaiono solo gli atti incompleti
dei bandi di quella persona.

**Acceptance Scenarios**:

1. **Given** referenti aggiornati, **When** si sceglie un RdP nel filtro, **Then** compaiono
   solo gli atti dei bandi in cui è RdP.
2. **Given** un bando con più RdP, **When** si filtra per uno di loro, **Then** il bando compare.
3. **Given** l'area referenti, **When** si consulta lo Stato complessivo o un monitoraggio, **Then** sono disponibili i filtri per mese, tipologia e le schede per tipo di atto.

---

### User Story 3 - Cambi di RdP tracciati (Priority: P2)

Se su Selezioni Online cambia l'RdP di un bando, al successivo aggiornamento il nuovo RdP
risulta attivo e il precedente non più attivo, con la data in cui è stato rilevato.

**Why this priority**: evita di sollecitare la persona sbagliata e conserva la storia.

**Independent Test**: dopo due aggiornamenti con RdP diversi per lo stesso bando, il primo è
"non più attivo" e il secondo "attivo".

**Acceptance Scenarios**:

1. **Given** un RdP non più restituito per un bando, **When** si aggiorna, **Then** è marcato
   non più attivo, non cancellato.
2. **Given** un RdP tornato dopo un periodo di assenza, **When** si aggiorna, **Then** torna
   attivo.

### Edge Cases

- Un bando senza RdP su Selezioni Online: nessun referente e indicazione "RdP non indicato".
- Un RdP senza email istituzionale: salvato con nome e username, segnalato come "email mancante".
- L'API restituisce bandi non monitorati (borse, tempo determinato): ignorati.
- L'aggiornamento si interrompe a metà paginazione: risulta fallito e non modifica i referenti.
- Due aggiornamenti contemporanei: il secondo viene rifiutato.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Il sistema MUST leggere gli RdP dei bandi da Selezioni Online con il token SSO
  dell'utente collegato; MUST NOT usare password o credenziali personali salvate nel codice o in
  configurazione.
- **FR-001a** *(eccezione temporanea, decisione dell'utente del 2026-10-29)*: finché il login
  con il Keycloak di produzione non è disponibile per questa app e l'API di SOL risponde senza
  autenticazione, la lettura MAY avvenire senza token, solo se attivata esplicitamente
  (`RDP_SENZA_TOKEN=1`) e solo per la prova locale. Valgono gli stessi limiti sui dati (FR-004);
  ogni lettura è registrata come "senza token"; se SOL rifiuta la richiesta anonima, la lettura
  fallisce con l'invito ad accedere con SSO. Da disattivare con l'integrazione su Coolify.
- **FR-002**: Il login MUST usare il Keycloak di produzione di Selezioni Online (realm `CNR` su
  `sso.cnr.it`, client `selezioni`), configurabile da ambiente; il client secret MUST stare solo
  nella configurazione del server.
- **FR-003**: Il sistema MUST rinnovare in automatico il token scaduto quando è disponibile il
  token di rinnovo.
- **FR-004**: Dei dati degli RdP il sistema MUST salvare solo nome, cognome, email istituzionale e
  username; MUST NOT salvare codice fiscale, matricola, email personale o PEC.
- **FR-005**: I referenti MUST essere collegati alla scheda SOL del bando (identificativo del
  bando su SOL) e quindi al bando della spec 001.
- **FR-006**: Un referente non più restituito MUST diventare "non più attivo" con la data di
  ultima rilevazione; uno restituito di nuovo MUST tornare attivo.
- **FR-007**: Ogni aggiornamento MUST essere registrato con utente, inizio, fine, esito, bandi e
  referenti trovati e messaggio di errore; un aggiornamento fallito MUST NOT modificare i
  referenti salvati; MUST essere impedito l'avvio di due aggiornamenti contemporanei.
- **FR-008**: La tabella degli atti MUST mostrare gli RdP attivi di ogni bando e MUST offrire un
  filtro per RdP; il dettaglio del bando MUST mostrare gli RdP con email.
- **FR-009**: L'aggiornamento MUST essere avviabile dalla pagina di monitoraggio da un utente
  collegato; senza login MUST rispondere con l'invito ad accedere.
- **FR-010**: Il server locale di prova MUST offrire lo stesso login SSO quando la configurazione
  OIDC è presente; senza configurazione le altre funzioni restano disponibili.

### Key Entities

- **Referente**: persona RdP di un bando su SOL: nome, cognome, email istituzionale, username,
  attivo sì/no, prima e ultima rilevazione.
- **Aggiornamento referenti**: un'esecuzione, con utente, tempi, esito, conteggi e messaggio.

## Success Criteria *(mandatory)*

- **SC-001**: Dopo un aggiornamento, il 100% dei bandi SOL monitorati che hanno un RdP su SOL
  mostra almeno un referente.
- **SC-002**: Dalla tabella degli atti l'addetta ottiene gli atti incompleti di un RdP con due
  filtri.
- **SC-003**: Nessun codice fiscale, matricola o email personale è presente nel database.
- **SC-004**: Un aggiornamento completo termina in meno di 3 minuti.

## Assumptions

- Il client `selezioni` del Keycloak di produzione accetterà l'indirizzo di ritorno di questa app
  (da registrare a cura dei Sistemi Informativi, come per chekin) e il client secret sarà
  fornito come segreto del server.
- L'utente dell'ufficio reclutamento, con il proprio token, vede gli RdP di tutti i bandi.
- La raccolta notturna non ha un utente collegato e non aggiorna i referenti; un'utenza di
  servizio in sola lettura resta un'opzione futura se servisse.

## Out of Scope

- Verifica dei punteggi e della graduatoria privata su SOL (stesso login, spec successiva).
- Invio di solleciti via email.
- Commissari dei bandi.
