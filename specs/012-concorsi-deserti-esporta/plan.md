# Implementation Plan: Concorsi deserti, revocati, senza esito ed esportazione Excel

**Spec**: [spec.md](spec.md)

## Approccio

1. `classifica.py`: regole `deserto` e `revocato` prima delle altre; `call_deserto` → `deserto` sempre.
2. `db.py`: schema 34, si ricrea `documento` con il nuovo CHECK e si riclassificano i documenti (solo i cambi verso o da deserto/revocato).
3. `atti.py`: le categorie confrontate includono `deserto` e `revocato`; documenti URP "altro" con il protocollo di un deserto SOL dello stesso bando valgono come deserto; colonna segreteria non applicabile; righe `senza_esito` con parametro `con_senza_esito` (solo `/api/atti` e area referenti stato).
4. `/api/esporta-excel` (amministrazione) e `/api/area-referenti/esporta-excel`: ricevono colonne e righe già filtrate dalla pagina e restituiscono un .xlsx (openpyxl).
5. `app.js`: `App.esportaExcel(colonne, righe, nome, url)` con finestra di scelta delle colonne (memorizzata in localStorage).
6. Pagine: `riepilogo.html` (tipi, Anno, Esporta), `consulta.html` (stato: Anno, tipi, Esporta; mese: schede Deserti/Revocati), `monitoraggi.html` (schede Deserti/Revocati); `scomposizioneAtti` conta deserti e revocati.

## Costituzione

I (fonti indipendenti, nessuna correzione), II (export senza dati dei candidati), III (sola lettura), IV (export dietro login), V (nessun dato modificato), VI (modifica incrementale).
