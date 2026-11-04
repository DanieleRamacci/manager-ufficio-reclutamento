# Research: Raccolta dati unificata di bandi, graduatorie e scorrimenti

Verifiche eseguite il 2026-10-29 sulle API pubbliche di SOL, sulle pagine URP e sul codice
sorgente di SOL (`cool-jconon`, copia locale in `~/Desktop/CNR/cool-jconon`).

## R1. Paginazione SOL

- **Decision**: interrogare `GET /jconon/rest/search` (con `guest=true`) a pagine di 100
  (`maxItems=100`, `skipCount` incrementale) finché `hasMoreItems` è `false`, controllando che
  il totale raccolto sia uguale a `totalNumItems`.
- **Rationale**: con `maxItems=1000` il server non risponde con JSON valido; con 100 e
  `skipCount=780` risponde correttamente (12 elementi, `hasMoreItems=false`). Lo script attuale
  usa una sola pagina da 200 e perde 592 bandi su 792.
- **Alternatives considered**: una sola richiesta grande (rifiutata dal server); l'endpoint
  `openapi/v1/call` usato in `fetch_bandi_rdp.py` (richiede autenticazione, fuori scopo).

## R2. Tipi di bando SOL da raccogliere

- **Decision**: una query per tipo, con `IN_TREE(root,'713d4376-4cbd-43b6-ad14-9401b5029c51')`:

  | Tipo SOL (`cmis:objectTypeId`) | Tipologia | Totale al 2026-10-29 |
  | --- | --- | --- |
  | `F:jconon_call_tind:folder_concorsi_pubblici` | tempo indeterminato | 792 |
  | `F:jconon_call_tind:folder_reclutamento_speciale` | tempo indeterminato, reclutamento speciale | 71 |
  | `F:jconon_call_tind:folder_categorie_protette` | tempo indeterminato, categorie protette | 142 |
  | `F:jconon_call_mobility:folder` | mobilità | 190 |
  | `F:jconon_call_comandi_distacchi:folder` | comando/distacco | 8 |

- **Rationale**: tipi presi dal modello dati di `cool-jconon` e verificati con l'API.
  `F:jconon_call_mobility_open:folder` esiste nel codice ma il server risponde
  "Unknown type", quindi non si usa. `F:jconon_call_tind:folder` restituisce 0.
- **Alternatives considered**: una query unica su tutti i tipi (rende più difficile
  attribuire la tipologia e verificare i totali per tipo).

## R3. Documenti dei bandi SOL

- **Decision**: per ogni bando, una query
  `SELECT * FROM jconon_attachment:document root WHERE IN_TREE(root,'<objectId del bando>')`.
  Ogni allegato restituisce tipo (`cmis:objectTypeId`), nome file, `jconon_protocollo:numero`,
  `jconon_protocollo:data`, `cmis:creationDate`, `cmis:lastModificationDate`.
- **Rationale**: dati strutturati, con protocollo e data, invece della lettura dell'HTML di
  `call-detail` usata oggi (`check_graduatoria_allegata`), che restituisce solo sì/no.
  Le query globali per tipo (es. tutte le `call_classification`, 4011 documenti) funzionano ma
  non restituiscono il bando di appartenenza, quindi non bastano per il collegamento.
- **Alternatives considered**: lettura dell'HTML di `call-detail` (fragile, senza protocollo);
  query globali per tipo più query per bando (rimandata: utile come ottimizzazione futura per
  trovare velocemente i documenti nuovi).

## R4. Classificazione dei documenti

- **Decision**: classificazione in due livelli (indicazione dell'ufficio, 2026-10-29).

  **Livello 1, categoria** (certa: si basa su titolo, nome file e tipo SOL). Le regole si
  applicano in quest'ordine, vince la prima che corrisponde:

  | Ordine | Categoria | Parole chiave in titolo/nome file | SOL: tipi allegato |
  | --- | --- | --- | --- |
  | 1 | `rettifica` | "rettifica", "errata corrige" | `call_correction_classification` (salvo parole di scorrimento nel nome), `call_errata_corrige` |
  | 2 | `scorrimento` | "scorriment", "subentr", "utilizzo ... graduatori", "assunzione ... idone" | `call_recruitment_provision` ("Provvedimento assunzione idoneo/i") |
  | 3 | `graduatoria` | "graduatori" | `call_classification` |
  | 4 | `bando` | documento principale | `call_it`, `call_mobility` |
  | 5 | `criteri`, `tracce` | regole attuali di `scraper-urp.py` | per nome file |
  | 6 | `altro` | il resto | il resto |

  **Livello 2, sottotipo** (solo per la categoria `scorrimento`, solo indicativo: si ricava
  dalle parole presenti nel titolo, quindi vale solo quando il titolo lo dice):

  | Sottotipo | Parole chiave | Note |
  | --- | --- | --- |
  | `subentro` | "subentr", "rinunci" | subentro dopo rinuncia del vincitore o di un idoneo già assunto |
  | `ulteriore` | "ulterior", "secondo", "terzo", "quarto", "nuovo scorrimento" | conserva l'ordinale se presente (2, 3, ...) |
  | `utilizzo` | "utilizzo ... graduatori" | uso della graduatoria, anche da un'altra struttura |
  | `non_specificato` | nessuna delle precedenti | il caso più comune: il titolo dice solo "scorrimento" |

  Esempi reali: "Provvedimento subentro scorrimento graduatoria" → `scorrimento`/`subentro`;
  "Provvedimento ulteriore scorrimento graduatoria" → `scorrimento`/`ulteriore`;
  "Provvedimento terzo scorrimento graduatoria" → `scorrimento`/`ulteriore` (ordinale 3);
  "Assunzione di n. 2 unità di personale mediante utilizzo graduatoria" →
  `scorrimento`/`utilizzo`; "Scorrimento graduatoria" → `scorrimento`/`non_specificato`;
  "Avviso convocazione prova idoneativa" → `altro` ("idone" da solo non basta);
  `call_classification` con nome file "..._Provv_scorrimento_..." → `scorrimento`.

- **Limite dichiarato**: un subentro può essere pubblicato con un titolo generico
  ("Scorrimento graduatoria"), oppure nascere mesi dopo, quando una persona assunta con
  scorrimento rinuncia. Dal solo titolo non è riconoscibile: il sottotipo viene salvato con
  l'origine (`titolo`) e mostrato come indicazione. La conferma del sottotipo arriverà dal
  file di riepilogo dell'ufficio (spec 003), ed eventualmente dalla lettura del testo dei PDF
  (spec successiva).

- **Rationale**: su SOL gli RdP caricano anche scorrimenti con il tipo "Graduatoria" (es.
  `call_classification` con nome file "..._Provv_scorrimento_...") e scorrimenti con il tipo
  "Modifiche e/o rettifiche graduatoria". Solo il tipo non basta.
- **Alternatives considered**: solo il tipo SOL (classifica male gli scorrimenti); solo il
  titolo (perde l'informazione strutturata quando il nome del file è generico).
- **Confermato dall'ufficio (2026-10-29)**: `call_recruitment_provision` ("Provvedimento
  assunzione idoneo/i") è uno scorrimento effettivo; il subentro è un sottotipo dello
  scorrimento.

## R5. Normalizzazione di codici e protocolli

- **Decision**:
  - Codice bando: maiuscole, rimozione dei prefissi ("BANDO N.", "CODICE BANDO"), rimozione di
    spazi, trattini e punti finali tranne il punto del numero (es. `367.479 CTER IOM GE` e
    `367.479 CTER IOMGE` diventano entrambi `367.479CTERIOMGE`).
  - Protocollo: solo cifre, senza zeri iniziali (SOL `0455701` = URP `455701`).
  - Oltre al codice normalizzato completo si salvano due chiavi strutturate, usate per prime
    nel collegamento: **numero bando** (`367.434`, anche scritto `367434`) e **codice di
    sotto-bando** se presente (`Cod. 14`, `Cod 14`, `Codice 14`, `cod.05` diventano `14`, `5`).
    Le sigle (`CA`, `CTER`, `RIC IASI`) restano solo come conferma, perché sono scritte in modi
    diversi.
- **Rationale**: le differenze osservate tra le fonti sono spazi tra le sigle e zeri iniziali.
  Il file di riepilogo dell'ufficio (verificato il 2026-10-29) usa formati ancora più vari:
  foglio Bandi solo `390.475`, foglio Graduatorie `367.529 FA IGB` più una colonna `367529`,
  foglio Scorrimento `367.434 CA Cod. 14`, `367.434 CA. Cod 13`, `367.434 CA. Codice 16`.
  Numero bando più sotto-bando è l'unica chiave comune a tutte le fonti.
- **Alternatives considered**: somiglianza testuale (fuzzy). Rimandata: si usa come
  segnalazione "possibile corrispondenza" in una spec successiva, non come collegamento
  automatico.

## R6. Periodo coperto da URP

- **Decision**: per ogni sezione URP si calcola la data del bando più vecchio presente
  nell'elenco; un bando SOL più vecchio di quella data è "fuori dal periodo URP".
- **Rationale**: URP elenca 201 bandi a tempo indeterminato contro 792 di SOL (FR-013a).

## R7. URP: elenco e dettaglio

- **Decision**: per URP si legge ogni volta l'elenco completo (pagine `?page=N`, circa 25
  pagine in tutto) e il dettaglio di tutti i bandi (circa 241). Le URL delle sezioni sono
  senza barra finale (con la barra il server risponde 301).
- **Rationale**: le pagine URP non indicano in modo affidabile la data di modifica; 241
  pagine con una pausa di 0,5 s richiedono circa 3 minuti, compatibile con SC-004.
  Le sezioni hanno: tempo indeterminato 201, mobilità 27, categorie riservatarie 13 bandi.

## R8. Aggiornamento incrementale SOL

- **Decision**: la raccolta notturna rilegge l'elenco di tutti i bandi (13 pagine da 100) e
  gli allegati dei bandi "attivi": pubblicati negli ultimi 36 mesi, oppure senza graduatoria,
  oppure con `cmis:lastModificationDate` cambiata. Una volta a settimana (configurabile)
  rilegge gli allegati di tutti i bandi. Il pulsante "Aggiorna dati" permette di scegliere la
  raccolta completa.
- **Rationale**: aggiungere un allegato non cambia necessariamente la data di modifica del
  bando, quindi la data di modifica da sola non basta. Con una pausa di 1 s, circa 1.200 bandi
  richiedono circa 20 minuti (completa) e i bandi attivi molto meno.

## R9. Controllo di accessibilità dei PDF

- **Decision**: il controllo esistente (testo estraibile, tag, lingua) viene eseguito solo sui
  documenti URP nuovi o con link cambiato, e il risultato viene salvato sul documento.
- **Rationale**: oggi ogni raccolta riscarica tutti i PDF; è la parte più lenta.
  `pikepdf` non è in `requirements.txt`, quindi oggi la verifica dei tag non è attiva; resta
  opzionale come adesso.

## R10. Salvataggio, esecuzione e compatibilità

- **Decision**:
  - Database SQLite separato `monitoraggio.db` nella cartella dati configurabile
    (`DATA_DIR`, predefinita `instance/`, già montata come volume in `docker-compose.yml`).
  - Raccolta notturna con un thread interno all'app (orario da `RACCOLTA_ORARIO`, predefinito
    02:30) e comando da terminale per esecuzioni manuali o pianificate da Coolify.
  - Compatibilità: le richieste a `/_static/bandi-completi-urp.json`,
    `/_static/bandi-concorsi-pubblici-sol.json` e `/_static/bandi-mobilita.json` vengono
    servite dal database nello stesso formato di oggi, così le pagine esistenti funzionano
    senza modifiche.
- **Rationale**: l'app gira come un unico processo (`python avvia_tool.py`) e ha già un
  `run_lock`; un database separato evita di toccare le tabelle dei job firme.
- **Alternatives considered**: APScheduler (dipendenza in più senza vantaggi per un solo
  job); Postgres come in `chekin-cnr-concorsi` (non necessario per questi volumi).

## R12. Protocollo pubblico e privato delle graduatorie

- **Fatti** (ufficio e verifica del 2026-10-29):
  - URP pubblica la graduatoria con il **protocollo pubblico**.
  - L'allegato graduatoria pubblico su SOL ha lo stesso protocollo pubblico: verificato su
    6 bandi, 5 identici a meno degli zeri iniziali (`0003763` = `3763`); nel sesto (367.500)
    il bando ha più sotto-bandi su SOL.
  - Il **protocollo privato** (graduatoria completa di vincitori e idonei) da qualche
    settimana è caricato su SOL come documento separato ad accesso riservato: non compare
    nelle ricerche pubbliche (`guest=true`), quindi si potrà leggere solo con il login. È anche
    nel foglio Graduatorie del file di riepilogo (colonna "N. Protocollo Privato") e
    probabilmente nei dati delle candidature (`jconon_application:protocollo_numero_graduatoria`).
- **Decision**: in questa spec URP e SOL si collegano sul protocollo pubblico. Il protocollo
  privato sarà usato nella spec del file di riepilogo (che contiene entrambi) e in quella dei
  punteggi SOL (login).
- I protocolli SOL possono avere spazi finali (`'157495 '`): la normalizzazione li rimuove.
- Il codice estratto oggi dal testo URP è spesso sporco (es. `367.500 CTER ALLEGATI
  ALLEGATO 1 - STRUTT`): conferma che il collegamento deve partire dal numero bando (R5).

## R13. Periodo di monitoraggio

- **Decision**: le segnalazioni (documenti mancanti su una fonte, bandi non collegati) si
  calcolano solo per bandi e documenti con data dal **2026-01-01** in poi (configurabile con
  `MONITORAGGIO_DAL`). I dati precedenti vengono comunque raccolti, perché graduatorie
  approvate prima del 2026 possono avere scorrimenti nel 2026.
- **Rationale**: il controllo dell'ufficio è partito nel 2026 e il file di riepilogo parte da
  quell'anno (decisione dell'utente del 2026-10-29).

## R11. Rischio di sicurezza trovato

- `protected_static` e la route generica `/<path:fname>` servono qualsiasi file della
  cartella del codice a un utente autenticato, compresi `.env` e i database in `instance/`.
- **Decision**: in questa spec, poiché si modifica `protected_static`, si limita ciò che si
  può servire a pagine e risorse statiche (`.html`, `.css`, `.js`, immagini), ai tre JSON di
  compatibilità e a `docs_firme/` con il controllo di proprietà già esistente; `.env`, `.py`,
  database e tutto `instance/` vengono rifiutati (Principio IV).
