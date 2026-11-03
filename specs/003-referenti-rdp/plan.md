# Implementation Plan: Referenti RdP dei bandi da Selezioni Online

**Branch**: `003-referenti-rdp` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

## Summary

`auth.py` acquista il rinnovo del token (`token_valido`). Un nuovo client
`monitoraggio/fonti/sol_rdp.py` legge `GET {SOL}/openapi/v1/call?filterType=all&detailRdP=true`
paginato con `Authorization: Bearer <token>`; `monitoraggio/referenti.py` salva i referenti per
scheda SOL (solo nome, cognome, email istituzionale, username) con attivo/non attivo e registra
ogni aggiornamento. La tabella degli atti mostra gli RdP e ha il filtro per RdP. Il server locale
registra il login SSO se la configurazione OIDC è presente.

## Technical Context

- **Dipendenze**: nessuna nuova per l'app; per il server locale con login, `Flask-Session` (già
  in `requirements.txt`) e `PyJWT` aggiunti a `requirements-monitoraggio.txt` (i token Keycloak
  superano i 4 KB di un cookie).
- **Configurazione** (ambiente): `OIDC_CLIENT_ID` (predefinito `selezioni`), `OIDC_CLIENT_SECRET`,
  `OIDC_REDIRECT_URI`, `OIDC_AUTH_URL`, `OIDC_TOKEN_URL`, `OIDC_USERINFO_URL` (predefiniti per
  `https://sso.cnr.it/auth/realms/CNR`), `JCONON_BASE_URL` (predefinito
  `https://selezionionline.cnr.it/jconon`).
- **Paginazione**: `page`/`offset=100` finché la pagina è più corta di `offset` o
  `hasMoreItems` è falso; tutte le pagine prima di scrivere (FR-007).
- **Storage**: tabelle `referente` e `referenti_aggiornamento` (schema versione 3).

## Constitution Check

| Principio | Verifica | Esito |
| --- | --- | --- |
| I. Fonti indipendenti | I referenti sono un dato di SOL, solo letto | OK |
| II. Dati nel database | Solo i campi necessari (FR-004); sessioni lato server in `DATA_DIR`, fuori dal repository | OK |
| III. Sola lettura, nessuna password | GET con il token dell'utente; client secret solo in ambiente | OK |
| IV. Autorizzazione | Aggiornamento solo con utente collegato; pagine protette come le altre | OK |
| V. Tracciabilità | Tabella degli aggiornamenti con utente ed esito | OK |
| VI. Incrementale | `fetch_bandi_rdp.py` resta per ora e verrà rimosso con l'integrazione | OK |

## Project Structure

```text
auth.py                       # + token_valido(): rinnovo con refresh_token
monitoraggio/fonti/http.py    # get_json con header (Bearer)
monitoraggio/fonti/sol_rdp.py # lettura paginata di openapi/v1/call con detailRdP
monitoraggio/referenti.py     # salvataggio, attivo/non attivo, registro aggiornamenti, lock
monitoraggio/db.py            # schema 3
monitoraggio/atti.py          # campo rdp nelle righe
monitoraggio/web.py           # /api/referenti/aggiorna, /api/referenti/stato, menu con utente
monitoraggio/__main__.py      # login SSO nel server locale se OIDC configurato
monitoraggio/static/*.html    # colonna e filtro RdP, pulsante "Aggiorna referenti"
tests/test_referenti.py
```
