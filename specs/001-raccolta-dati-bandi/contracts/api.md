# Contratti: API HTTP e comando da terminale

Tutte le route richiedono un utente autenticato (`login_required`, FR-019). Le risposte sono
JSON UTF-8.

## Raccolta

### `POST /api/raccolta/avvia`

Avvia una raccolta in background.

Request body (tutti opzionali):

```json
{ "fonti": ["urp", "sol"], "completa": false }
```

- `fonti`: predefinito entrambe.
- `completa`: `true` rilegge gli allegati di tutti i bandi SOL (R8).

Risposte:

- `202` `{ "ok": true, "raccolte": [{ "id": 12, "fonte": "urp" }, ...] }`
- `409` `{ "ok": false, "msg": "Raccolta già in corso per: sol" }` (FR-017)

### `GET /api/raccolta/stato`

Ultima raccolta per fonte e raccolte in corso (FR-015, SC-006).

```json
{
  "fonti": {
    "urp": {
      "ultima": { "id": 12, "modalita": "manuale", "inizio": "2026-10-29T09:00:00Z",
                  "fine": "2026-10-29T09:03:10Z", "esito": "completata",
                  "bandi_trovati": 241, "documenti_trovati": 1830, "nuovi": 3,
                  "aggiornati": 5, "errori": 0 },
      "ultima_riuscita": { "id": 12, "fine": "2026-10-29T09:03:10Z" },
      "in_corso": null
    },
    "sol": { "...": "..." }
  },
  "prossima_notturna": "2026-10-30T02:30:00+01:00"
}
```

### `GET /api/raccolta/<id>/errori`

```json
{ "raccolta_id": 12, "errori": [{ "riferimento": "https://www.urp.cnr.it/node/1", "messaggio": "HTTP 500" }] }
```

## Dati

### `GET /api/bandi`

Elenco dei bandi collegati. Parametri opzionali: `tipologia`, `stato_collegamento`,
`fonte`, `dal`, `al` (date di pubblicazione), `q` (testo libero su codice e titolo).

```json
{
  "totale": 1203,
  "bandi": [{
    "id": 1, "codice": "367.479 CTER IOM GE", "codice_norm": "367.479CTERIOMGE",
    "tipologia": "tempo_indeterminato", "titolo": "...", "data_pubblicazione": "2025-05-12",
    "stato_collegamento": "entrambi",
    "schede": [{ "fonte": "urp", "url": "...", "protocollo": "160039" },
               { "fonte": "sol", "url": "...", "protocollo": "160039" }],
    "documenti": {
      "graduatoria": 1, "rettifica": 0,
      "scorrimento": { "totale": 3, "subentro": 1, "ulteriore": 1, "utilizzo": 0, "non_specificato": 1 }
    },
    "segnalazioni": ["graduatoria_mancante_sol"]
  }]
}
```

### `GET /api/bandi/<id>`

Il bando con tutte le schede e tutti i documenti (campi di `data-model.md`).

### `GET /api/atti?dal=YYYY-MM-DD&al=YYYY-MM-DD`

Tabella degli atti (FR-021): una riga per atto, `dal` predefinito `MONITORAGGIO_DAL`.

```json
{ "dal": "2026-01-01", "totale": 226, "atti": [{
    "bando_id": 1, "numero_bando": "367.601", "codice": "367.601 FA ISTC", "tipologia": "tempo_indeterminato",
    "atto": "graduatoria", "sottotipo": null, "data": "2026-06-12", "protocollo": "270086",
    "fonti": { "sol": { "stato": "presente", "url": "...", "protocollo": "270066" },
               "urp": { "stato": "presente", "url": "...", "protocollo": "270086" },
               "segreteria": { "stato": "non_caricato" } },
    "note": ["protocollo diverso: URP 270086, SOL 270066"], "incompleto": false, "protocollo_diverso": true }] }
```

Stati di cella: `presente`, `mancante`, `non_applicabile` (fuori dal periodo URP), `non_caricato`.

### `GET /api/riepilogo`

Conteggi per mese dal `MONITORAGGIO_DAL`: bandi pubblicati per tipologia, graduatorie,
scorrimenti (anche per sottotipo) e rettifiche per fonte; numero di bandi per stato di collegamento.

## Compatibilità con le pagine esistenti

Servite da `protected_static` leggendo il database, nello stesso formato dei file di oggi,
con header `Last-Modified` uguale alla fine dell'ultima raccolta riuscita della fonte:

| URL | Formato | Usata da |
| --- | --- | --- |
| `/_static/bandi-completi-urp.json` | oggetto `{ sezione: [bando URP, ...] }` come `scraper-urp.py` | `index.html` |
| `/_static/bandi-concorsi-pubblici-sol.json` | lista come `scraper-sol-tutti-bandi.py` (`codice`, `titolo`, `data_pubblicazione_inpa`, `data_pubblicazione_graduatoria`, `graduatoria_allegato`, `graduatoria_presente`, `tipologia`) | `index.html`, `report-mese.html` |
| `/_static/bandi-mobilita.json` | lista come `scraper-mobilita.py` | `mobilita-urp.html` |

`POST /api/run` e `GET /api/status` restano disponibili e diventano alias di
`/api/raccolta/avvia` e `/api/raccolta/stato` con i formati di oggi.

## Comando da terminale

```text
python -m monitoraggio raccogli [--fonte urp|sol|tutte] [--completa]
python -m monitoraggio importa-json [--cartella PERCORSO]
python -m monitoraggio stato
python -m monitoraggio web [--porta 8090]   # prova locale: solo 127.0.0.1, senza login
```

- Codice di uscita `0` se l'esito è `completata`, `1` per `completata_con_errori`,
  `2` per `fallita` o raccolta già in corso.
- `importa-json` importa una volta i file JSON storici (FR-020) e non sovrascrive dati più
  recenti già presenti.

## Configurazione (variabili d'ambiente)

| Variabile | Predefinito | Uso |
| --- | --- | --- |
| `DATA_DIR` | `instance/` | cartella del database `monitoraggio.db` |
| `RACCOLTA_NOTTURNA` | `1` | `0` disattiva la raccolta notturna |
| `RACCOLTA_ORARIO` | `02:30` | ora locale della raccolta notturna |
| `RACCOLTA_COMPLETA_GIORNO` | `dom` | giorno della raccolta completa settimanale |
| `RACCOLTA_PAUSA_URP` | `0.5` | secondi tra le richieste URP |
| `RACCOLTA_PAUSA_SOL` | `1.0` | secondi tra le richieste SOL |
| `URP_SEZIONI` | `tempo-indeterminato,bandi-pubblici-mobilita,categorie-riservatarie` | FR-003 |
