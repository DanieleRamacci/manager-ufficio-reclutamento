# Quickstart: file della segreteria

## Prova in locale

```bash
cd ~/Desktop/Coding/agent-monitoraggio
export DATA_DIR=~/Desktop/CNR/dati-monitoraggio      # database fuori dal progetto
.venv/bin/python -m pytest                           # test con file Excel inventati
.venv/bin/python -m monitoraggio web                 # http://127.0.0.1:8090/monitoraggio
```

1. Menu → Monitoraggio → **File segreteria** → scegli il file `.xlsx` → **Carica file**.
2. Controlla il rapporto per foglio (righe, atti, fuori ambito, problemi con i numeri di riga).
3. Menu → Monitoraggio → **Riepilogo atti**: la colonna "File segreteria" è verde/rossa.

## Risultati del primo caricamento reale (2026-10-29, `Graduatorie_Bandi_CNR.xlsx`)

| Foglio | Righe | Atti | Fuori ambito | Problemi |
| --- | --- | --- | --- | --- |
| Bandi | 47 | 47 | 32 (Direttori, revoche) | nessuno |
| Graduatorie | 769 | 102 | 0 | 16 righe senza protocollo pubblico |
| Scorrimento | 175 | 51 | 0 | 50 righe senza tipologia |

Tabella degli atti dal 2026-01-01 dopo il caricamento: 254 atti, 109 presenti su tutte e tre
le fonti, 61 incompleti (46 mancanti su SOL, 13 nel file, 7 su URP). Tutti gli atti in ambito
del file sono collegati a un bando presente su URP o SOL (SC-003: 100%).

Osservazioni:

- 26 scorrimenti del bando 367.434 CA (protocolli del 28/10/2026) sono nel file ma non su SOL;
  su URP risultano "fuori periodo" perché il bando è precedente alle sezioni URP attuali:
  serve l'archivio storico URP (spec 001, FR-013c, T054–T056).
- 6 bandi pubblicati su URP e SOL nel 2026 non sono nel foglio Bandi.
- 5 graduatorie sono su URP e nel file ma non su SOL.
