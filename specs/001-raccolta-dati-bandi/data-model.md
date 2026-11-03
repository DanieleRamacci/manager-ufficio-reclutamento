# Data Model: Raccolta dati unificata

Database SQLite `monitoraggio.db` in `DATA_DIR` (predefinita `instance/`). Date in formato
ISO: `YYYY-MM-DD` per le date, `YYYY-MM-DDTHH:MM:SSZ` (UTC) per gli istanti.

## bando

Il bando come entità unica, indipendente dalla fonte.

| Campo | Tipo | Note |
| --- | --- | --- |
| id | integer PK | |
| codice_norm | text, unique, nullable | codice normalizzato (R5); null se non riconosciuto |
| numero_bando | text, nullable | es. `367.434` (R5), chiave principale del collegamento |
| codice_sotto | text, nullable | codice di sotto-bando, es. `14` (R5) |
| codice | text | codice "migliore" da mostrare (SOL se presente, altrimenti URP) |
| tipologia | text | `tempo_indeterminato`, `reclutamento_speciale`, `categorie_protette`, `mobilita`, `comando` |
| titolo | text | |
| profilo | text | da SOL |
| sede | text | da SOL |
| numero_posti | integer | da SOL |
| gruppo_rdp | text | da SOL (`jconon_call:rdp`), nominativi fuori scopo |
| data_pubblicazione | date | la più vecchia tra le schede |
| stato_collegamento | text | `entrambi`, `solo_urp`, `solo_sol`, `fuori_periodo_urp` |
| creato_il, aggiornato_il | timestamp | |

Regole:

- Un bando con `codice_norm` null viene collegato solo tramite protocollo della scheda.
- `stato_collegamento` viene ricalcolato a fine raccolta (vedi `collegamento`).

## scheda

La presenza di un bando su una fonte.

| Campo | Tipo | Note |
| --- | --- | --- |
| id | integer PK | |
| bando_id | FK → bando, nullable | null finché non collegata |
| fonte | text | `urp`, `sol` |
| id_esterno | text | URP: URL del nodo (`/node/27266`); SOL: `cmis:objectId` |
| sezione | text | URP: `tempo-indeterminato`, `bandi-pubblici-mobilita`, `categorie-riservatarie`; SOL: `cmis:objectTypeId` |
| codice_originale | text | come appare nella fonte |
| codice_norm | text | |
| numero_bando, codice_sotto | text | come in `bando` (R5) |
| titolo | text | |
| protocollo | text | normalizzato (R5) |
| protocollo_originale | text | |
| data_pubblicazione | date | URP: data del protocollo del bando; SOL: `data_pubblicazione_inpa` |
| data_pubbl_graduatoria | date | solo SOL (`jconon_call:data_pubbl_graduatoria`) |
| url | text | link alla scheda |
| dati_extra | text (JSON) | campi della fonte non mappati (estratto URP, campi `jconon_call:*`) |
| modificata_fonte_il | timestamp | SOL: `cmis:lastModificationDate` |
| prima_rilevazione, ultima_rilevazione | timestamp | |
| presente | boolean | false se non più trovata nell'ultima raccolta riuscita |

Vincoli: unique (`fonte`, `id_esterno`).

## documento

Un file pubblicato su una scheda.

| Campo | Tipo | Note |
| --- | --- | --- |
| id | integer PK | |
| scheda_id | FK → scheda | |
| id_esterno | text | URP: link del file; SOL: `cmis:objectId` |
| titolo | text | URP: titolo dell'allegato; SOL: nome file |
| categoria | text | `bando`, `graduatoria`, `scorrimento`, `rettifica`, `criteri`, `tracce`, `altro` (R4, livello 1) |
| sottotipo | text, nullable | solo per `scorrimento`: `subentro`, `ulteriore`, `utilizzo`, `non_specificato` (R4, livello 2) |
| sottotipo_ordinale | integer, nullable | es. 3 per "terzo scorrimento" |
| sottotipo_origine | text, nullable | `titolo` (indicativo); in futuro `riepilogo_ufficio`, `testo_pdf` |
| tipo_fonte | text | SOL: `cmis:objectTypeId`; URP: null |
| protocollo, protocollo_originale | text | |
| data_protocollo | date | |
| url | text | |
| accessibilita | text (JSON) | risultato del controllo PDF (R9), null se non eseguito |
| prima_rilevazione, ultima_rilevazione | timestamp | |
| presente | boolean | |

Vincoli: unique (`scheda_id`, `id_esterno`).

## raccolta

Un'esecuzione su una fonte.

| Campo | Tipo | Note |
| --- | --- | --- |
| id | integer PK | |
| fonte | text | `urp`, `sol` |
| modalita | text | `notturna`, `manuale`, `completa` |
| avviata_da | text | email dell'utente o `scheduler` |
| inizio, fine | timestamp | |
| esito | text | `in_corso`, `completata`, `completata_con_errori`, `fallita` |
| bandi_trovati, documenti_trovati, nuovi, aggiornati | integer | |
| totale_dichiarato | text (JSON) | totali dichiarati dalla fonte per sezione/tipo (SC-001) |
| messaggio | text | motivo del fallimento |

## raccolta_errore

| Campo | Tipo | Note |
| --- | --- | --- |
| id | integer PK | |
| raccolta_id | FK → raccolta | |
| riferimento | text | URL o id del bando |
| messaggio | text | |

## Transizioni di stato

```text
raccolta:  in_corso → completata
                    → completata_con_errori   (almeno un bando non letto)
                    → fallita                 (fonte non raggiungibile, elenco vuoto,
                                               totale raccolto diverso dal dichiarato)
```

- Solo una raccolta `in_corso` per fonte (FR-017).
- Con esito `fallita` le righe di `scheda` e `documento` non vengono modificate (FR-016).
- Con esito `completata`, le schede e i documenti non visti diventano `presente = false`;
  con `completata_con_errori` questo vale solo per le schede lette senza errori.

## collegamento (calcolato a fine raccolta)

1. Per ogni scheda senza `bando_id`: si cerca un bando con lo stesso `numero_bando` e
   `codice_sotto`, poi con lo stesso `codice_norm`; se non c'è, una scheda dell'altra fonte con lo stesso protocollo; altrimenti si crea un bando.
2. `stato_collegamento`: `entrambi` se il bando ha schede URP e SOL presenti; `solo_urp`;
   `solo_sol` se la data è nel periodo URP della sezione corrispondente, altrimenti
   `fuori_periodo_urp` (R6).
3. Per i documenti delle categorie `graduatoria`, `scorrimento` e `rettifica` si
   confrontano i protocolli tra
   le schede dello stesso bando: un protocollo presente su una sola scheda è segnalato come
   "manca su SOL" o "manca su URP".
