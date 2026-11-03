# Contract: viste mensili e testo di sollecito

## Endpoint riusati

### `GET /monitoraggio/solleciti.js`

- Serve il modulo di composizione del testo esclusivamente tramite la route Flask protetta da `@protezione`, come la pagina del riepilogo.
- La risposta non contiene dati per conto proprio: la bozza viene composta nel browser a partire dalla riga già restituita da `/api/atti`.

### `GET /api/atti?dal=YYYY-MM-DD&al=YYYY-MM-DD`

- Resta protetto dal middleware `@protezione`.
- Restituisce le righe complete della tabella unificata, compresi fonte, protocollo, note, flag `difforme`, RdP ed eventuali link.
- Il client calcola il mese scelto e usa `dal`/`al` per recuperare quel periodo.
- La scheda graduatorie unisce i rilievi punteggi e conserva i record per il dettaglio dei candidati; entrambe le schede mensili mostrano solo `difforme === true` per la categoria richiesta e mantengono tutte le colonne attuali.

### `GET /api/punteggi?mese=YYYY-MM`

- Resta protetto dal middleware esistente.
- Fornisce i risultati punteggi da associare alle graduatorie mensili per bando, data e codice quando disponibile.
- Le difformità non legate agli scorrimenti sono aggiunte alle note della graduatoria corrispondente; i record punteggi restano associati anche se non presentano anomalie, per consentire l'apertura dei candidati.
- La tabella graduatorie mostra riepilogo e comando per aprire i candidati; non esiste una tabella mensile punteggi separata.

### `GET /api/raccolta/stato`

- Resta protetto dal middleware esistente.
- La pagina riusa gli esiti e le date delle raccolte per segnalare che un'origine non è stata raggiunta o è in corso.

## Confronto degli scorrimenti

- Gli allegati SOL di tipo `call_recruitment_provision` e i titoli “Provvedimento di assunzione idoneo” sono classificati come atti di scorrimento.
- La verifica punteggi confronta il numero/data del provvedimento con quelli indicati per i candidati con esito `S`.
- Se l'allegato risulta presente ma non esiste un candidato `S` con quel protocollo, la nota deve indicare che la difformità riguarda i punteggi. La cella SOL continua a indicare la presenza dell'allegato.
- Se la cella SOL è mancante, la nota distingue l'assenza dell'allegato e segnala anche l'eventuale mancanza del protocollo nei punteggi.

## Testo copiabile

La pagina compone in memoria un testo nel formato:

```text
Destinatari (da incollare nel campo A):
indirizzo1@ente.it; indirizzo2@ente.it

Oggetto:
<numero bando> — Monitoraggio mensile <mese>

Link al bando su Selezioni Online:
<URL scheda SOL>

Testo:
Buongiorno gentili tutte e tutti,

nell'ambito del monitoraggio mensile di <mese>, nella scheda Selezioni Online del bando <numero bando>, abbiamo rilevato le seguenti difformità:
- <atto, data, protocollo e rilievo>

Vi chiediamo cortesemente di verificare quanto indicato e di comunicarci l'avvenuta correzione.

Grazie.
```

- Gli indirizzi RdP sono copiabili separatamente dal messaggio completo.
- Il messaggio completo raggruppa graduatorie e scorrimenti difformi per numero di bando, includendo tutti i codici/sedi, nel mese selezionato.

- Il testo usa solo i dati dell'atto e le note delle difformità; niente dati personali dei candidati.
- Non viene aggiunta una bozza a database né viene effettuata una richiesta email.
- La copia negli appunti è un'azione esplicita; se il browser la nega, il testo resta visibile e selezionabile.
