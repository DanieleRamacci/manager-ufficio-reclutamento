# Quickstart: verificare la raccolta dati

## Prerequisiti

- Python 3.11 e le dipendenze di `requirements.txt` e `requirements-dev.txt`.
- Accesso a internet verso `www.urp.cnr.it` e `selezionionline.cnr.it`.
- Per l'app: `.env` con la configurazione SSO già usata oggi.

### Ambiente locale leggero (Mac, senza torch/ultralytics)

Per raccolta e test basta un ambiente con le sole dipendenze del pacchetto `monitoraggio`:

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-monitoraggio.txt
.venv/bin/python -m pytest
```

Il database di prova va tenuto fuori dalla cartella del codice, impostando `DATA_DIR`.
Per una prima verifica veloce dei conteggi si può saltare il controllo dei PDF con
`RACCOLTA_CONTROLLO_PDF=0`. L'app completa (`avvia_tool.py`) richiede invece
`requirements.txt` oppure Docker (vedi punto 6).

## 1. Test automatici

```bash
pytest tests/ -q
```

Atteso: tutti i test passano. I test usano pagine e risposte salvate in `tests/fixtures/`
(dati pubblici) e non fanno richieste in rete.

## 2. Prima raccolta da terminale

```bash
export DATA_DIR=/tmp/monitoraggio-prova
python -m monitoraggio raccogli --fonte tutte --completa
python -m monitoraggio stato
```

Atteso:
- esito `completata` (o `completata_con_errori` con l'elenco degli errori) per URP e SOL;
- bandi URP uguali alla somma dei totali dichiarati dalle sezioni (circa 201 + 27 + 13);
- bandi SOL uguali alla somma dei totali dichiarati per tipo (circa 792 + 71 + 142 + 190 + 8);
- nessun file creato nella cartella del codice (`git status` non mostra file nuovi).

## 3. Raccolta incrementale

```bash
python -m monitoraggio raccogli --fonte tutte
```

Atteso: termina in meno di 15 minuti; `nuovi` e `aggiornati` piccoli; nessun bando duplicato.

## 4. Verifiche a campione

- 10 bandi URP con graduatoria o scorrimento: tipo, protocollo e data dei documenti uguali al
  sito (SC-002).
- 30 bandi presenti su entrambe le fonti: `stato_collegamento = entrambi` (SC-003).
- Il bando `367.479 CTER IOMGE` (URP) è collegato a `367.479 CTER IOM GE` (SOL).
- Un bando SOL del 2016 risulta `fuori_periodo_urp`, non `solo_sol`.

## 5. Fonte non raggiungibile

Con una URL SOL errata (es. variabile di test che punta a un host inesistente):

```bash
python -m monitoraggio raccogli --fonte sol
```

Atteso: esito `fallita` con il motivo; i dati SOL precedenti restano invariati.

## 6. App

```bash
python avvia_tool.py
```

- Aprire `index.html`, `report-mese.html`, `mobilita-urp.html`: mostrano bandi e documenti
  come prima, con numeri uguali o maggiori.
- Premere "Aggiorna dati": parte la raccolta; un secondo clic durante la raccolta mostra
  "Raccolta già in corso".
- `GET /_static/.env` e `GET /_static/instance/monitoraggio.db` rispondono `404` o `403`.
