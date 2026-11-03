# Quickstart: referenti RdP

## 1. Richiesta ai Sistemi Informativi (una volta)

Sul client Keycloak `selezioni` (realm `CNR` su `https://sso.cnr.it/auth`) vanno registrati
gli indirizzi di ritorno di questa app:

- produzione (Coolify): `https://<dominio-app>/oidc-callback`
- prova locale: `http://localhost:8090/oidc-callback` (oppure un indirizzo ngrok, come chekin)

e serve il client secret (se il client è confidenziale), da tenere solo nei segreti di Coolify e
nel `.env` locale.

Da segnalare nella stessa richiesta: il 2026-10-29
`https://selezionionline.cnr.it/jconon/openapi/v1/call?filterType=all&detailRdP=true` rispondeva
anche senza login, con codice fiscale, matricola ed email personali degli RdP.

## 2. `.env` locale (nella cartella del progetto, già escluso da git)

```bash
OIDC_CLIENT_ID=selezioni
OIDC_CLIENT_SECRET=...            # dai Sistemi Informativi, non va mai committato
OIDC_REDIRECT_URI=http://localhost:8090/oidc-callback
# OIDC_BASE_URL=https://sso.cnr.it/auth/realms/CNR/protocol/openid-connect   (predefinito)
# JCONON_BASE_URL=https://selezionionline.cnr.it/jconon                      (predefinito)
FLASK_SECRET_KEY=...              # una stringa casuale lunga
```

## 3. Prova

```bash
export DATA_DIR=~/Desktop/CNR/dati-monitoraggio
.venv/bin/python -m monitoraggio web
```

1. Il terminale stampa "Login SSO attivo".
2. Nel menu, **Accedi con SSO** → login CNR → si torna su Riepilogo atti con il proprio nome nel menu.
3. **Aggiorna referenti** → dopo circa un minuto compare "RdP letti …" e la colonna RdP si riempie.
4. Filtro **RdP** + **solo incompleti**: gli atti da sollecitare per persona.

Atteso: nessun codice fiscale, matricola o email personale nel database
(`sqlite3 $DATA_DIR/monitoraggio.db "SELECT * FROM referente LIMIT 5"` mostra solo nome, cognome,
email istituzionale e username).
