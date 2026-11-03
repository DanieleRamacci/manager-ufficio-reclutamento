<!--
Sync Impact Report
- Version change: template → 1.0.0
- Principi aggiunti:
  I. Fonti Indipendenti e Confrontabili
  II. Dati nel Database, Mai nel Repository (NON NEGOZIABILE)
  III. Sola Lettura verso i Sistemi Esterni
  IV. Autorizzazione Prima della Logica
  V. Dati Tracciabili e Aggiornati
  VI. Evoluzione Incrementale
- Sezioni aggiunte: Vincoli Tecnici e di Sicurezza, Flusso di Sviluppo, Governance
- Sezioni rimosse: nessuna
- Template da verificare: .specify/templates/plan-template.md (Constitution Check),
  spec-template.md e tasks-template.md non richiedono modifiche
- TODO rimandati:
  - TODO(REPO_VISIBILITY): il repository è pubblico e la cronologia contiene docs_firme/,
    instance/, flask_session/ e file JSON di dati; da rendere privato e ripulire in una fase
    successiva, scelta dell'utente del 2026-10-29 (vedi Principio II)
-->

# Manager Ufficio Reclutamento Constitution

## Core Principles

### I. Fonti Indipendenti e Confrontabili

Ogni dato su bandi, graduatorie, scorrimenti, utilizzi e rettifiche MUST essere salvato
insieme alla fonte da cui proviene (URP, Selezioni Online, file di riepilogo dell'ufficio,
Excel condiviso, email di protocollo). Una fonte MUST NOT essere usata per precompilare
o correggere un'altra: il confronto avviene sempre tra dati raccolti in modo indipendente.
Il confronto MUST basarsi sulle chiavi comuni (codice bando normalizzato e numero di
protocollo) e MUST segnalare le differenze senza sovrascrivere nessuna delle due versioni.
Il file di riepilogo dell'ufficio (alimentato dal protocollo) è la fonte di riferimento
del confronto, ma può contenere errori: le differenze rispetto a esso MUST essere mostrate
come segnalazioni da verificare, non come correzioni automatiche.

Rationale: lo scopo del monitoraggio è scoprire dove una fonte è incompleta o sbagliata;
se una fonte viene derivata da un'altra, le differenze spariscono e il controllo perde valore.

### II. Dati nel Database, Mai nel Repository (NON NEGOZIABILE)

Tutti i dati raccolti o caricati (bandi, allegati, graduatorie, punteggi, file
dell'ufficio, documenti, sessioni, token, export) MUST stare nel database o nel volume
persistente del server e MUST NOT essere scritti nella cartella del codice né committati
nel repository. Il percorso di database e volume MUST essere configurabile e il
`.gitignore` MUST coprirlo. La maggior parte dei dati è pubblica; i nominativi dei
candidati presenti in graduatorie e punteggi sono dati personali: possono essere salvati
nel database solo se una spec li richiede, MUST essere visibili solo a utenti autenticati
e MUST NOT comparire nei log. I dati personali MUST NOT essere inviati a servizi esterni,
inclusi strumenti di AI, salvo una spec che lo preveda.

Rationale: l'app gira in Docker su Coolify dietro SSO, quindi il database è protetto;
il repository invece è condiviso e conserva la cronologia per sempre.

### III. Sola Lettura verso i Sistemi Esterni

Le integrazioni con Selezioni Online, URP e altri sistemi CNR MUST essere in sola lettura.
Le chiamate autenticate MUST usare la sessione o le credenziali dell'utente che le avvia
o un accesso di servizio approvato, MUST rispettare pause tra le richieste e MUST NOT
salvare password nel codice o nel database. Ogni scrittura verso un sistema esterno
richiede una spec dedicata e approvata.

Rationale: il sistema osserva processi gestiti da altri uffici; non deve alterarli né
sovraccaricarli.

### IV. Autorizzazione Prima della Logica

Ogni endpoint che espone dati non pubblici MUST verificare autenticazione e ruolo prima di
leggere o restituire dati. Gli endpoint di debug e di test (es. `/_debug/*`, `*/test-live`)
MUST essere disattivati o protetti in produzione. La condivisione di risultati tra utenti
MUST essere esplicita e tracciata.

Rationale: l'app gira come servizio condiviso e unisce dati pubblici e dati riservati;
la separazione deve stare nel backend, non nell'interfaccia.

### V. Dati Tracciabili e Aggiornati

Ogni raccolta da una fonte MUST registrare data e ora di esecuzione, esito ed eventuali
errori. Le viste di monitoraggio MUST mostrare quanto è aggiornata ogni fonte e MUST
distinguere "dato assente nella fonte" da "fonte non raggiunta". Le raccolte MUST gestire
la paginazione completa delle fonti, senza limiti fissi che troncano i risultati.

Rationale: un monitoraggio basato su dati vecchi o parziali produce solleciti sbagliati;
chi legge il report deve sapere su cosa si basa.

### VI. Evoluzione Incrementale

Il codice esistente MUST essere migliorato per passi piccoli e verificabili, senza
riscritture complete. La nuova logica (raccolta, normalizzazione, confronto) MUST stare in
moduli dedicati e testabili fuori da `avvia_tool.py`; il codice esistente viene estratto
in moduli quando una spec lo tocca. Le funzionalità esistenti (redazione firme, mobilità,
strumenti RdP) MUST continuare a funzionare dopo ogni modifica.

Rationale: l'app è già in uso; una riscrittura bloccherebbe il lavoro dell'ufficio e
aumenterebbe il rischio di regressioni.

## Vincoli Tecnici e di Sicurezza

- Stack: Python 3.11, Flask, SQLite, pagine HTML servite dal backend; deploy con Docker su
  Coolify (come `chekin-cnr-concorsi`), immagine su GHCR, accesso protetto da SSO CNR.
  Nuove dipendenze pesanti MUST essere giustificate nel piano della spec.
- Configurazione e segreti MUST arrivare da variabili d'ambiente o da `.env` non versionato.
- Interfaccia, messaggi e documentazione per l'ufficio MUST essere in italiano.
- Le date MUST essere salvate in formato ISO (YYYY-MM-DD) e mostrate in formato italiano.
- I codici bando MUST essere normalizzati (spazi, maiuscole, punteggiatura) prima del
  confronto, conservando anche il valore originale.

## Flusso di Sviluppo

- Ogni modifica funzionale passa da Spec Kit: spec → piano → task → implementazione.
- Ogni spec lavora su un branch dedicato; il merge su `main` avviene dopo la revisione.
- La logica di normalizzazione e confronto MUST avere test automatici (pytest) con casi
  reali anonimizzati.
- Prima del merge MUST essere verificato a mano il flusso interessato nell'app in esecuzione.
- Commit e push avvengono solo dopo la revisione del responsabile del progetto.

## Governance

Questa constitution prevale sulle altre pratiche del progetto. Ogni piano Spec Kit MUST
includere un Constitution Check che verifica i principi; le eccezioni MUST essere motivate
nella sezione Complexity Tracking del piano. Le modifiche alla constitution richiedono
l'aggiornamento della versione: MAJOR per principi rimossi o ridefiniti, MINOR per principi
o sezioni nuove, PATCH per chiarimenti. Il contesto operativo per gli agenti di sviluppo
è in `CLAUDE.md`.

**Version**: 1.0.0 | **Ratified**: 2026-10-29 | **Last Amended**: 2026-10-29
