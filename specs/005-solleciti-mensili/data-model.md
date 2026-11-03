# Data Model: Solleciti mensili delle difformità

Questa feature non aggiunge tabelle. Legge le righe già costruite da `atti.elenco_atti`.

## MonthlyDiscrepancyView

Rappresentazione effimera di una scheda per il mese scelto. Le difformità graduatoria e punteggi sono mostrate insieme, con una sottotabella candidati espandibile su ogni graduatoria.

| Campo | Origine | Regola |
| --- | --- | --- |
| `mese` | Selettore UI | `YYYY-MM`; inizialmente mese corrente |
| `categoria` | UI | `graduatoria` oppure `scorrimento` |
| `righe` | `GET /api/atti?dal=...&al=...` + `GET /api/punteggi?mese=...` | Righe atti difformi; le anomalie punteggi sono unite alle graduatorie per bando/data/codice e il record punteggi resta associato per la sottotabella, anche quando non ha difformità |
| `stato_fonti` | `GET /api/raccolta/stato` | In corso, ultima riuscita o fallita per URP e SOL |

Non persistito; ricostruito quando cambia mese o quando si aggiornano le raccolte.

## FollowUpDraft

Messaggio temporaneo preparato nel browser raggruppando gli atti anomali dello stesso numero bando, per tutti i relativi codici/sedi, nel mese selezionato.

| Campo | Origine | Regola |
| --- | --- | --- |
| `destinatari` | `righe[].rdp[].email` | Email non vuote e senza duplicati; copia separata e inseribili nel campo destinatari |
| `oggetto` | Numero bando e mese | Inizia con il numero del bando |
| `link` | URL della scheda SOL sulle righe | Collegamento al concorso, quando disponibile |
| `corpo` | Atti, protocolli, fonti, note e mese | Elenca tutte le difformità del codice e chiede verifica/correzione |
| `copia_esito` | Azione utente | Messaggio visivo di copia riuscita o testo selezionabile in caso di errore |

Il messaggio è composto nel browser raggruppando le righe anomale dello stesso numero bando nel mese selezionato. Indirizzi RdP e messaggio completo hanno azioni di copia separate. Non viene salvato, inviato o registrato nei log; i dati di candidati non fanno parte del modello.

## Fonti correlate

- **Atto**: riga per bando/atto già unificata da SOL, URP e file segreteria.
- **RdP**: referenti già associati al bando e, ove disponibile, al sotto-codice.
- **Collection freshness**: stato delle raccolte esistente per indicare se una fonte può essere considerata aggiornata.
