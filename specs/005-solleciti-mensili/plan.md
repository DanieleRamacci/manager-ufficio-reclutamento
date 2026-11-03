# Implementation Plan: Solleciti mensili delle difformità

**Branch**: `005-solleciti-mensili` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-solleciti-mensili/spec.md`

## Summary

Aggiungere alla pagina di riepilogo tre schede: stato complessivo esistente, graduatorie difformi del mese e scorrimenti difformi del mese. Le due viste mensili riusano i record già prodotti da `atti.elenco_atti`, mantenendo colonne, celle delle fonti e note. Per ogni numero di bando il browser raggruppa le difformità mensili di tutte le sedi/codici in un messaggio con email RdP copiabili separatamente, oggetto, link SOL e testo; non vengono creati record, email o bozze lato server.

## Technical Context

**Language/Version**: Python 3.11, JavaScript ES2020 e HTML/CSS statici

**Primary Dependencies**: Flask e API già presenti; nessuna nuova dipendenza

**Storage**: Nessun nuovo dato persistito. Lettura delle fonti già presenti nel database SQLite

**Testing**: Verifica manuale dei flussi descritti in `quickstart.md`; non si aggiungono test automatici in questa iterazione

**Target Platform**: Server Flask locale e produzione dietro SSO CNR; browser desktop

**Project Type**: Applicazione web server-rendered con JavaScript lato client

**Performance Goals**: Cambio scheda e filtro di un mese devono riusare la risposta esistente o una singola richiesta `GET /api/atti`; la copia deve completarsi in un'azione dopo la preparazione del testo

**Constraints**: Messaggi in italiano; nessun invio email; nessun salvataggio di testi o dati candidati; non mostrare assenza certa quando una fonte non è stata raggiunta

**Scale/Scope**: Una pagina (`monitoraggio/static/riepilogo.html`), riuso delle API esistenti (`/api/atti`, `/api/raccolta/stato`), una route protetta per servire il modulo JS, nessuna migrazione DB

## Clarification Outcome

La specifica non ha decisioni bloccanti: mese corrente predefinito; un testo per numero di bando con tutte le difformità mensili di codici e sedi; invio manuale; riepilogo limitato alle difformità che il sistema attuale già rileva. Il confronto scorrimenti distingue la presenza dell'allegato SOL dal protocollo di assunzione idoneo nei punteggi. Le anomalie dei punteggi della graduatoria sono unite nella stessa tabella mensile e la sottotabella candidati è disponibile da ogni graduatoria quando i dati sono caricati. L'invio Outlook resta una valutazione successiva.

## Constitution Check

- **I. Fonti indipendenti**: PASS — la vista presenta separatamente gli stati SOL, URP e segreteria e riusa le note del confronto esistente; non corregge una fonte con i dati di un'altra.
- **II. Dati nel database, mai nel repository**: PASS — il testo è composto solo nel browser su richiesta, non è persistito né include nominativi, codici fiscali o punteggi dei candidati.
- **III. Sola lettura verso sistemi esterni**: PASS — nessun invio; le sole operazioni sono letture delle API applicative e copia locale negli appunti.
- **IV. Autorizzazione prima della logica**: PASS — gli endpoint e la route del modulo JS sono protetti con `@protezione`; non si aggiungono endpoint pubblici.
- **V. Dati tracciabili e aggiornati**: PASS — si riusa lo stato delle raccolte e si distinguono fonti in corso/fallite dai dati confermati mancanti.
- **VI. Evoluzione incrementale**: PASS — intervento limitato alla vista esistente e a un piccolo modulo di supporto per il testo, senza riscrivere `avvia_tool.py`.

## Project Structure

### Documentation (this feature)

```text
specs/005-solleciti-mensili/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/atti.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code

```text
monitoraggio/
├── atti.py                         # origine dei record e delle difformità riusati
├── web.py                          # API esistenti e route protetta del modulo JS
└── static/
    ├── riepilogo.html              # schede, filtro mensile, tabella riusabile
    └── solleciti.js                # composizione/copia del testo senza persistenza
```

**Structure Decision**: La dashboard attuale serve già le righe della tabella e i referenti RdP. Le nuove schede filtrano questi dati nel client e chiedono `GET /api/atti?dal=...&al=...` e `GET /api/punteggi?mese=...` quando cambia il mese. L'API continua a essere la fonte unica di verità per stati e note.

## Implementation Notes

1. Tenere il selettore di mese comune alle due viste anomale, con selezione iniziale del mese corrente.
2. Servire `solleciti.js` con una route protetta in `monitoraggio/web.py` e rendere la tabella degli atti un renderer riusabile, così overview e viste di sollecito mantengono le stesse colonne e gli stessi link.
3. Filtrare per categoria (`graduatoria`/`scorrimento`) e `difforme`; unire alla graduatoria le note punteggi e conservare la scheda per il dettaglio candidati, senza aggiungere una tabella separata.
4. In `monitoraggio/static/solleciti.js`, raggruppare gli atti anomali mensili per numero di bando e per tutti i relativi codici/sedi; rendere gli indirizzi RdP copiabili da soli e comporre il messaggio completo con oggetto, URL SOL e tutti i rilievi.
5. Escludere esplicitamente nominativi, punteggi e altri campi delle righe candidato; non conservare la bozza.
6. Se una fonte non è raggiungibile, mostrare lo stato della raccolta e non descrivere la mancata lettura come atto mancante.

## Future Outlook Decision (not part of this release)

La prima versione resta sulla copia manuale. La ricerca in `research.md` confronta `mailto:` con una futura integrazione Microsoft Graph delegata. La decisione su autenticazione Microsoft, creazione bozza o invio resta fuori da questa implementazione.

## Complexity Tracking

Nessuna violazione della Constitution. Non sono introdotti componenti o dipendenze aggiuntive.
