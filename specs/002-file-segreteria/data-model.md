# Data Model: File della segreteria

Tabelle aggiunte a `monitoraggio.db` (schema versione 2).

## segreteria_versione

| Campo | Tipo | Note |
| --- | --- | --- |
| id | integer PK | |
| caricata_il | timestamp | |
| utente | text | email dell'utente autenticato |
| nome_file | text | nome originale del file |
| impronta | text | SHA-256 del file, per riconoscere ricaricamenti identici |
| esito | text | `in_uso`, `precedente`, `rifiutata` |
| rapporto | text (JSON) | per foglio: righe, atti, colonne mancanti, problemi (vedi spec FR-005) |
| righe, atti | integer | totali |

Solo una versione è `in_uso`: un caricamento riuscito porta la precedente a `precedente`.

## segreteria_riga

| Campo | Tipo | Note |
| --- | --- | --- |
| id | integer PK | |
| versione_id | FK | |
| foglio | text | `bandi`, `graduatorie`, `scorrimento` |
| numero_riga | integer | riga nel foglio Excel |
| valori | text (JSON) | tutte le colonne con i valori originali (compresi i nominativi) |
| atto_id | FK → segreteria_atto, nullable | null se la riga non ha bando |

## segreteria_atto

| Campo | Tipo | Note |
| --- | --- | --- |
| id | integer PK | |
| versione_id | FK | |
| categoria | text | `bando`, `graduatoria`, `scorrimento` |
| numero_bando | text | normalizzato (spec 001, R5) |
| codice_sotto | text, nullable | |
| codice_originale | text | come nel file |
| protocollo, protocollo_originale | text | pubblico per le graduatorie |
| data | date | |
| protocollo_privato, data_privato | text, date | solo graduatorie |
| sottotipo | text, nullable | solo scorrimenti: `ordinario`, `subentro`, `misto`, null = da completare |
| persone | integer | righe del file nell'atto |
| tipo_procedura, titolo | text | dal foglio Bandi |
| in_ambito | boolean | false per Direttori e revoche |
| bando_id | FK → bando, nullable | collegamento ai bandi della spec 001 |

Indici: (versione_id, categoria, numero_bando), (versione_id, protocollo).
