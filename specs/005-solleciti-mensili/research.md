# Research: Solleciti mensili delle difformità

## Stato attuale dell'app

- `GET /api/atti?dal=&al=` restituisce le righe della tabella unificata, incluse `fonti`, `note`, `difforme`, `rdp` e links. È già protetto con `@protezione` in `monitoraggio/web.py`.
- `atti.elenco_atti` calcola `difforme` a partire da fonti mancanti e note esistenti, e integra le difformità dei punteggi SOL. La nuova pagina non deve duplicare questa logica.
- La pagina `monitoraggio/static/riepilogo.html` contiene già la tabella e la selezione di date; il renderer può essere riusato per le tre schede.
- `GET /api/raccolta/stato` distingue ultima raccolta, raccolta in corso ed esito. La pagina deve usare questo stato per contestualizzare le righe basate su una fonte non raggiunta.
- I referenti associati alle righe sono già restituiti con nome e email; per il testo usare soltanto gli indirizzi RdP disponibili per il codice/sotto-codice della riga.
- `classifica.py` mappa il tipo SOL `call_recruitment_provision` e i titoli come “Provvedimento di assunzione idoneo” alla categoria interna `scorrimento`. `punteggi.scorrimenti_candidati` estrae i protocolli/data di assunzione idoneo dei candidati con esito `S`; `stato_scorrimento` confronta questi valori con i protocolli e le date di allegati SOL, URP e file segreteria. La riga ora distingue il documento presente negli allegati ma assente nei punteggi dalla mancanza dell'allegato SOL.

## Invio email futuro

### Decisione per questa feature

V1 prepara un testo semplice copiabile con indirizzi, oggetto e corpo. Nessun invio, nessuna bozza salvata lato server, nessun accesso a Outlook.

### Alternative per una fase successiva

1. **`mailto:`** — semplice; apre il client di posta predefinito con destinatari, oggetto e testo. Non garantisce che venga aperto Outlook; la persona rivede e invia manualmente. Va rispettata la codifica URI e la lunghezza massima supportata dai client.
2. **Microsoft Graph con accesso delegato** — l'utente si autentica con Microsoft Entra; l'app potrebbe creare una bozza da rivedere o inviare con il suo account. Richiede registrazione dell'app, URI di reindirizzamento HTTPS, consenso agli scope delegati e rispetto delle policy dell'organizzazione. È più integrato ma ha costo di configurazione e gestione dell'autenticazione.
3. **App Outlook per ChatGPT** — non offre alla dashboard Flask un token Microsoft o un'API riutilizzabile; non risolve da sola l'invio dal prodotto locale.

**Raccomandazione**: prima validare il testo copiato e il processo manuale. Se serve poi un avvio più comodo, valutare un link `mailto:`; per la gestione integrata, preferire in seguito la creazione di una bozza Graph delegata e lasciare all'utente il controllo dell'invio.

**Fonti**: [RFC 6068 — The 'mailto' URI Scheme](https://www.rfc-editor.org/rfc/rfc6068), [Microsoft Graph permissions reference](https://learn.microsoft.com/graph/permissions-reference?view=graph-rest-1.0), [Microsoft identity platform authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow), [Create and send Outlook messages with Microsoft Graph](https://learn.microsoft.com/en-us/graph/outlook-create-send-messages), [Outlook email and calendar apps in ChatGPT](https://help.openai.com/en/articles/12512241-outlook-email-and-calendar-apps-in-chatgpt).

## Decisions

- Reuse existing APIs and row-level discrepancy logic; no new schema or API endpoint.
- Keep the draft transient and browser-side.
- Do not include candidate-level details in the copied message.
- Use one message per discrepant row, with the email recipients associated to that row.
