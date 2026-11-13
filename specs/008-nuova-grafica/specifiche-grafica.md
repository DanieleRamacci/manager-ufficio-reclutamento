# Specifiche grafiche – App "Ufficio reclutamento · Monitoraggio bandi"

Documento per Claude Code. Descrive la nuova interfaccia da applicare all'app esistente.
Il prototipo di riferimento è `Monitoraggio Bandi.dc.html` (allegato): è un mock con dati finti, serve per layout, testi, colori e comportamenti. **Non copiare i dati finti né la logica di generazione**: collega tutto alle fonti e alle API che l'app ha già.

## Istruzioni per Claude Code

1. Leggi prima la struttura dell'app esistente (routing, template/componenti, CSS, modelli dati).
2. Applica la grafica e la struttura delle pagine descritte qui, riusando lo stack attuale (non introdurre framework nuovi se non servono).
3. Mantieni invariati i calcoli già presenti (confronto fonti, difformità, punteggi SOL, lettura file Excel). Dove una funzione descritta qui non esiste ancora (monitoraggi, registro comunicazioni, impostazioni email, aggiornamenti notturni), crea modello dati e API minimi, indicati in fondo.
4. Implementa **tutto** in un'unica sessione, senza fermarti a chiedere conferma tra una pagina e l'altra: fondamenta visive, struttura globale, tutte le pagine della sezione 3 nell'ordine indicato, modello dati della sezione 4 con relative API e migrazioni. Alla fine verifica che l'app si avvii e che ogni pagina si apra senza errori, poi riassumi cosa hai cambiato e cosa resta da collegare (ad es. l'invio reale delle email dalla casella dell'ufficio).
5. Le azioni riservate agli amministratori (creare monitoraggi, inviare email, avviare raccolte, gestire utenti) vanno nascoste o disabilitate per il ruolo Lettura, anche lato server.

---

## 1. Fondamenta visive

### Font
- Testo: **IBM Plex Sans** 400/500/600/700 (Google Fonts), fallback `system-ui, sans-serif`.
- Numeri di protocollo, ID, codici fiscali, n. gestione: **IBM Plex Mono** 400/500.
- Corpo 14px. Tabelle 12.5–13.5px. Intestazioni di colonna 12px, peso 600, colore secondario.
- Titoli di pagina 22px/600; titoli di card 16–18px/600.
- Numeri in tabella e KPI con `font-variant-numeric: tabular-nums`.

### Colori (definirli come variabili CSS)
| Token | Valore | Uso |
|---|---|---|
| `--bg` | `#f3f4f6` | sfondo pagina |
| `--surface` | `#ffffff` | card, tabelle |
| `--surface-2` | `#fafbfc` | intestazioni tabella, riquadri KPI |
| `--border` | `#e3e6eb` | bordi card |
| `--border-soft` | `#eef0f3` | righe tabella, separatori |
| `--input-border` | `#c9ced6` | input, select, pulsanti secondari |
| `--text` | `#1b2230` | testo principale |
| `--text-2` | `#3d4554` | testo secondario forte |
| `--muted` | `#5b6472` | etichette |
| `--muted-2` | `#7a8290` | note, sottotitoli |
| `--nav` | `#1f3a5f` | barra superiore, pulsante filtro attivo |
| `--primary` | `#1f5fbf` (hover `#174c9c`) | azioni principali, link |
| `--ok` / `--ok-bg` | `#1e7b45` / `#e9f5ee` | presente, inviata, in regola |
| `--ko` / `--ko-bg` | `#b42318` / `#fbe7e5` | mancante, da inviare, errore |
| `--warn` / `--warn-bg` | `#9a6200` / `#fdf3dc` | protocollo diverso, da confermare, avviso |
| `--test` / `--test-bg` | `#5a3a8c` / `#efe9f7` | email di prova |
| `--na` | `#6b7280` / `#9aa1ab` | fuori periodo, non previsto, chiuso |

Colori delle tipologie (chip):
- Tempo indeterminato: sfondo `#e8edf5`, testo `#1f3a5f`
- Mobilità: `#efe9f7` / `#5a3a8c`
- Tempo determinato: `#e6f2f2` / `#1d5f5f`

### Forme e spaziature
- Card: sfondo bianco, bordo 1px `--border`, raggio 10px, padding 14–18px.
- Input/select/pulsanti: altezza 34px, raggio 7px, bordo `--input-border`.
- Pillole di stato: raggio 999px, padding 2px 8–9px, 12px peso 600.
- Etichette difformità: raggio 5–6px, 11.5–12px.
- Contenuto centrale: `max-width: 1680px`, padding 16px 24px, gap verticale 14px tra le card.
- Tabelle larghe dentro un contenitore `overflow-x: auto` con `min-width` sulla tabella (le pagine devono funzionare anche su schermi piccoli, senza scroll orizzontale della pagina).

### Densità
Prevedi una classe/opzione "compatta" che riduce il padding verticale delle celle da 10px a 6px.

---

## 2. Struttura globale

### Barra superiore (colore `--nav`, testo bianco)
- A sinistra "Ufficio reclutamento" (700).
- Voci di navigazione: **Stato complessivo · Monitoraggi · Comunicazioni · File segreteria · Impostazioni**. Voce attiva con sfondo `rgba(255,255,255,.16)`, le altre opacità .78.
- Su "Monitoraggi" un badge rosso con il numero di bandi ancora da comunicare nei monitoraggi in corso.
- A destra lo stato delle fonti: pallino verde + nome + ultimo aggiornamento (es. "Selezioni Online 05/11 02:30", "URP 05/11 02:41", "File segreteria 04/11 18:30"), poi utente ed "Esci" come oggi.
- La barra va a capo su schermi stretti (`flex-wrap`).

### Celle "fonte" (riutilizzate in più tabelle)
Tre colonne affiancate: **Selezioni Online · URP · File segreteria**, testo centrato, sfondo pieno della cella:
| Stato | Etichetta | Sotto | Sfondo / testo |
|---|---|---|---|
| presente | "presente" | protocollo in mono | `--ok-bg` / `--ok` |
| mancante | "mancante" | – | `--ko-bg` / `--ko` |
| protocollo diverso | "protocollo diverso" | protocollo trovato | `--warn-bg` / `--warn` |
| fuori periodo | "fuori periodo" | – | bianco / `--na` |
| non previsto | "non previsto" | – | bianco / `#9aa1ab` |

Ogni riga di atto ha un bordo sinistro di 3px: rosso `#d6453a` se ha difformità, verde `#2f9a5c` se in regola.

### Colonna RdP (compatta)
- **Niente avatar o iniziali.** Nomi completi **uno sotto l'altro**, 12.5px, al massimo **2 visibili**, troncati con ellissi.
- Sotto, link piccolo (11.5px, `--primary`): "+N altri · email" (o "email" se sono ≤ 2).
- Al clic la cella si espande in linea e mostra tutti i nomi, ognuno con l'email (mailto) sotto, più "Copia indirizzi" (copia tutte le email separate da `; `) e "chiudi".

### Blocco candidati / punteggi SOL
- Nella cella "Atto": pulsante piccolo "N candidati ▾" e link "Punteggi su SOL ↗".
- Il clic apre, sotto la riga, un pannello grigio chiaro (`#f8f9fb`) con:
  - riepilogo "N candidati con punteggi su N domande · V x · I y · S z · scorrimento: protocollo …", etichette rosse per i problemi (es. "10 senza protocollo graduatoria") e link in grassetto "Apri i punteggi su Selezioni Online ↗";
  - tabella: Pos., Cognome, Nome, Nascita, Codice fiscale (mono), Email, Email PEC, Scritta /40, Orale /30, Curriculum /24, Titoli /6, Totale (grassetto), Esito (V/I/S + parola), Prot. graduatoria (cella rossa se mancante).

### Finestre e notifiche
- Overlay `rgba(20,28,40,.4)`, finestra bianca centrata, raggio 12px, ombra `0 20px 60px rgba(0,0,0,.25)`, intestazione e piè con bordo.
- Toast in basso al centro, sfondo `#1b2230`, testo bianco, 2.5 secondi.

---

## 3. Pagine

### 3.1 Stato complessivo
1. **Barra rapida** (card): pulsanti "Stato complessivo", "Graduatorie del mese (n)", "Scorrimenti del mese (n)" (quello attivo è pieno `--nav` con testo bianco), poi "Mese" (input month) e "Tipologia" (select). I conteggi seguono mese e tipologia scelti.
2. **Card tabella**
   - Titolo dinamico: "Stato complessivo degli atti (X di Y · Z con difformità)" oppure "Graduatorie di novembre 2026 (…)".
   - Legenda a destra: verde presente, rosso mancante, ambra protocollo diverso, grigio non applicabile.
   - Filtri: Mese + "Tutto il periodo", Dal/Al, tipo di atto, fonte con difformità, ☐ solo con difformità, ☐ protocollo diverso, RdP, ricerca "Bando, codice, protocollo", link "Azzera filtri".
   - Colonne: Data · N. bando · Codice (+ titolo sotto) · Tipologia · Atto (+ chip "scorrimento", "N persone nel file segreteria", etichette rosse SOL, candidati) · Protocollo · SOL · URP · Segreteria · RdP · Note/difformità.
  - Note/difformità: pillole testo "Fonte: problema" (sfondo `#f1f3f8`, testo rosso; ambra per protocollo diverso). Sulle graduatorie e sugli scorrimenti difformi del mese, mostrare anche i comandi di sollecito e il loro stato, come nelle schede mensili.

### 3.2 Monitoraggi – elenco
- Intestazione "Monitoraggi mensili" + spiegazione + pulsante primario **"+ Nuovo monitoraggio"**.
- **Pannello creazione** (card con bordo `--primary` e alone `0 0 0 3px #e7effb`), mostra l'ID in mono (es. `MON-10.2026`):
  1. Mese di riferimento (input month, default mese precedente).
  2. Tipologie da includere: chip selezionabili ✓/+, con il numero di atti del mese per tipologia; selezione multipla.
  3. Allineamento fonti per quel mese: una riga per fonte, "allineata" (verde) o "dati parziali" (ambra) con "dati fino al gg/mm/aaaa · agg. …". Pulsante "Verifica allineamento" che registra data e ora del controllo.
  - Piè: riepilogo "N atti · N con difformità · N bandi da comunicare", avviso se il mese ha già un monitoraggio (con link "Apri"), pulsante "Crea e apri monitoraggio" (disabilitato se mese già presente o nessuna tipologia).
- **Tabella monitoraggi**, filtri: anno, stato, tipologia, ☐ con comunicazioni da inviare.
  Colonne: ID (mono) · Mese di riferimento · Tipologie (chip colorati) · Creato il · Fonti ("3/3 allineate" verde o ambra) · Atti · Difformità (rosso) · Comunicazioni ai referenti ("x/y bandi inviate · n da confermare" + barra verde di avanzamento) · Stato (pillola "in corso" blu `#e7effb/#1f5fbf`, "chiuso" grigio) · "Apri →". Tutta la riga è cliccabile.

### 3.3 Monitoraggi – dettaglio
- Briciole: "← Monitoraggi / MON-10.2026".
- **Card intestazione**:
  - "Monitoraggio ottobre 2026" + pillola stato + "creato il …".
  - Chip tipologie (cliccabili per includere/escludere finché è in corso).
  - Pulsanti "Riverifica fonti" e "Chiudi monitoraggio"/"Riapri monitoraggio".
  - Stato di allineamento delle tre fonti + "ultima verifica …".
  - 4 KPI su sfondo `--surface-2`: Atti nel mese · Atti con difformità (+ bandi coinvolti) · Comunicazioni da inviare · Comunicazioni inviate (x/y).
- **Schede** (segmented control su sfondo `#eef0f3`, scheda attiva bianca con ombra leggera), ciascuna con conteggio e badge rosso delle difformità:
  **Tutte le difformità** (prima, aperta di default) · Bandi pubblicati · Graduatorie · Scorrimenti · Subentri · Comunicazioni.
- Filtri a destra: tipologia (tra quelle del monitoraggio), stato comunicazione (da inviare / da confermare / inviate), ☐ solo con difformità, ricerca "Bando, protocollo, RdP".
- **Banda di avviso** (sfondo `#fff8e8`): "N bandi con difformità ancora da comunicare" + pulsante "Invia tutti dalla casella dell'ufficio…" (apre conferma con l'elenco bandi → destinatari → n. difformità).
- **Tabella atti**: Data · Bando (n. + profilo/sede, titolo sotto) · Tipologia · N. gest. (mono) · Atto (+ persone, candidati) · Prot. · SOL · URP · Segreteria · **Difformità rilevate** (righe "**SOL** testo", "**URP** testo"… in rosso/ambra, oppure "Nessuna difformità" verde) · RdP (compatto) · **Comunicazione**.
  - Righe con difformità prima, poi per data decrescente.
  - Cella Comunicazione: pillola stato ("da inviare" rossa, "copiata · da confermare" ambra, "inviata gg/mm" verde, "in regola" grigia) + pulsante contorno "Messaggio" + ☐ "inviata" + ID comunicazione piccolo in mono grigio + storico espandibile con numero, tipo, data, stato e oggetto di ogni comunicazione inviata.
  - Le stesse schede per atto, mese e tipologia sono disponibili nelle viste consultive e nell'area referenti; lì non compaiono comandi per inviare o modificare comunicazioni.
- Scheda **Comunicazioni**: stessa tabella del registro (3.4) filtrata sul monitoraggio.

### 3.4 Messaggio ai referenti (finestra)
- Uno per **bando** per monitoraggio, con tutte le difformità del bando nel mese.
- Intestazione: titolo "Comunicazione difformità · bando 367.544", ID in mono, pillola stato.
- Campi: Da "Ufficio Reclutamento <casella mittente> · casella dell'ufficio", Cc (se impostata), A = chip con "Nome <email>" di tutti i RdP, Oggetto.
- Commutatore **Anteprima / Modifica testo**. Anteprima: riquadro con `white-space: pre-wrap`. Modifica: input oggetto + textarea.
- Storico dei tentativi (data · canale · stato · ID).
- Piè: "Copia messaggio" · "Apri nel mio client email" (mailto) · ☐ "Email inviata" · a destra "Invia prova" (contorno viola, se abilitata) e "Invia dalla casella dell'ufficio" (primario, se abilitata; altrimenti link "Email ufficiali disattivate · impostazioni").
- Testo standard:
  ```
  Gentile <Nome Cognome>,            (oppure "Gentili referenti," se più RdP)

  nell'ambito del monitoraggio mensile di <mese anno> (rif. <ID>), per il bando <codice> – <titolo> risultano le seguenti difformità tra le fonti:

  1) <Atto> del <data> – prot. <protocollo>
     – <Fonte>: <problema>

  Vi chiediamo di provvedere all'inserimento o alla correzione sulle piattaforme indicate, utilizzando lo stesso numero di protocollo, e di darne riscontro rispondendo a questa email.

  Cordiali saluti,
  <firma dalle impostazioni>
  ```
  Oggetto: `[<ID>] Monitoraggio <mese anno> – bando <codice>: N difformità` (con `[PROVA] ` davanti per le prove).

### 3.5 Comunicazioni (registro)
- Intestazione con spiegazione dell'ID; a destra pillole "Email ufficiali attive/disattivate", "Prova attiva/disattivata" e pulsante "Impostazioni email" (porta a Impostazioni → Email).
- Filtri: monitoraggio, stato (inviate, da confermare, prove), canale (Casella ufficio, Copia manuale, Client email, Segnata a mano, Email di prova), ricerca "ID, bando, referente".
- Colonne: ID comunicazione (mono) · Data · Monitoraggio · N. bando · N. gestione · Destinatari ("L. Bianchi +2", tooltip con tutti) · Oggetto (troncato) · Difformità · Canale · Stato (pillola) · Apri. Il clic apre la finestra in sola lettura.

### 3.6 File segreteria
1. **Card caricamento**: titolo, spiegazione, input file .xlsx + "Carica file" (disabilitato senza file), link a destra "Vedi il file come in Excel".
2. **Card versione in uso**: "Versione in uso · nome file · caricato … da … · N atti da N righe". Tre riquadri (Bandi, Graduatorie, Scorrimento) con righe/atti/fuori ambito e "nessun problema" verde oppure etichetta ambra (es. "43 righe senza protocollo") apribile con ▶ in un elenco "riga N · bando · problema". Riga di confronto con la versione precedente e **storico versioni** (vN, nome, data, utente, differenze, pillola "in uso").
3. **Vista Excel** (opzionale, apribile): griglia con numeri di riga e intestazioni A–H in grigio, intestazione fissa, celle problematiche colorate (rosso protocollo mancante, giallo tipologia mancante), linguette dei fogli in basso.
4. **Atti del file**: filtri tipo, mese, ☑ solo in ambito, ☐ solo non trovati su URP/SOL, ricerca. Colonne: Data · N. bando · Codice nel file (+ nome PDF sotto) · Atto (+ chip) · Protocollo · Protocollo privato (+ data) · Persone · Su URP/SOL (pillola "bando trovato" verde / "non trovato" rossa / "fuori ambito" grigia; riga fuori ambito con opacità .6).

### 3.7 Impostazioni
Layout: menu laterale (card, voci con sottotitolo grigio, voce attiva sfondo `#eef4fd`) + contenuto. Il menu va sopra al contenuto su schermi stretti.

**Utenti**
- Testo: "Gli amministratori avviano raccolte e verifiche, creano i monitoraggi e inviano le email. Chi ha il ruolo di lettura vede tutte le tabelle, compresi i dati dei candidati. Le modifiche hanno effetto subito."
- Riquadro "Aggiungi una persona": Nome utente di Selezioni Online · Email, se diversa da nome.cognome@cnr.it (placeholder che si aggiorna con il nome utente) · Ruolo (Lettura/Amministratore) · Aggiungi. Errori in rosso sotto (nome vuoto, già presente).
- Tabella: Nome utente ("(tu)" accanto al proprio) · Email · Ruolo (select modificabile) · Aggiunto il · Ultimo accesso · Rimuovi (non per sé stessi).

**Email**
- Due riquadri affiancati, bordo colorato se attivi:
  - ☐ **Email di prova abilitate** (bordo viola) + indirizzo di prova.
  - ☐ **Email ufficiali abilitate** (bordo verde) + casella mittente + copia conoscenza facoltativa.
- Riquadro di stato che riassume la combinazione (es. "Attive solo le email di prova: tutti gli invii vanno a …, nessuna email arriva ai referenti").
- Textarea firma.
- Regole: le prove vanno solo all'indirizzo di prova, con `[PROVA]` nell'oggetto, si registrano con stato "prova" e **non** cambiano lo stato della comunicazione del bando. Con le ufficiali disattivate l'invio dalla casella (anche multiplo) è bloccato lato server.

**Aggiornamenti notturni**
- Titolo + "Prossima esecuzione: stanotte alle HH:MM (attività)".
- Tabella attività: ☐ Attiva · Attività (nome + descrizione) · Orario (input time) · Ultima esecuzione (pillola esito ok/avviso/errore + data + dettaglio) · Durata · "Esegui ora". Riga disattivata con opacità .55.
- Attività: Raccolta Selezioni Online · Raccolta URP · Aggiornamento referenti (RdP) · Confronto fonti e difformità · Riepilogo email agli amministratori (facoltativa).
- **Storico esecuzioni**: filtro per attività, ☐ solo con avvisi o errori; colonne Data/ora · Attività · Esito · Durata · Dettaglio.

---

## 4. Modello dati da aggiungere (se non esiste)

```
monitoraggio
  id            "MON-MM.AAAA"
  mese          "AAAA-MM"
  tipologie     ["TI","MOB","TD"]          # una o più
  stato         "in corso" | "chiuso"
  creato_il, creato_da
  verifica_fonti_il                         # ultima verifica allineamento

comunicazione
  id            "MON-MM.AAAA/<n. bando>/<n. gestione>"   (+ "-2", "-3" per reinvii)
  monitoraggio_id, n_bando, n_gestione
  destinatari   [email RdP]
  oggetto, corpo, n_difformita
  canale        "Casella ufficio" | "Copia manuale" | "Client email" | "Segnata a mano" | "Email di prova"
  stato         "inviata" | "da confermare" | "prova"
  data, utente

stato comunicazione di un bando nel monitoraggio = ultima comunicazione non di prova:
  nessuna → "da inviare"; "da confermare" → copiata; "inviata" → inviata.
  Spunta "inviata": conferma l'ultima, oppure crea una voce "Segnata a mano".
  "Copia messaggio" e "Apri nel client email" creano una voce "da confermare".

utente          username_sol, email, ruolo ("Lettura"|"Amministratore"), aggiunto_il, ultimo_accesso
impostazioni_email  prova_attiva, indirizzo_prova, ufficiali_attive, mittente, cc, firma
attivita_notturna   chiave, nome, orario, attiva, ultima_esecuzione, esito, durata, dettaglio
esecuzione          attivita, data, esito, durata, dettaglio
versione_file_segreteria  n, nome_file, caricato_il, caricato_da, riepilogo_fogli, differenze
```

Atti del monitoraggio = atti con data nel mese e tipologia tra quelle del monitoraggio. Un bando va comunicato se almeno un suo atto del mese ha difformità.
