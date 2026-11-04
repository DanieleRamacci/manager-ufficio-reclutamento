# Implementation Plan: Monitoraggio mensile con autorizzazioni e invio email

**Branch**: `006-monitoraggio-mensile` | **Spec**: [spec.md](spec.md)

## Approccio

Moduli nuovi, testabili e separati dalla raccolta (Principio VI): `utenti.py` (ruoli), `mensile.py` (monitoraggi, testo, solleciti), `excel_mese.py` (file dai modelli), `posta.py` (invio), `mensile_web.py` (route). Nessuna dipendenza nuova: `smtplib` e `openpyxl` ci sono già.

Le difformità restano calcolate dalla logica esistente della pagina (`riepilogo.html`, `solleciti.js`): aprendola con `?monitoraggio=AAAA-MM&mese=AAAA-MM` compaiono anteprima, invio e spunta. Una seconda implementazione lato server divergerebbe. Il server riceve testo e destinatari e li controlla.

## Constitution Check

- **I. Fonti indipendenti**: la colonna TIPOLOGIA resta testo libero; gli Excel non precompilano altre fonti con dati derivati.
- **II. Dati nel database**: i dati dei candidati restano in memoria e nei file generati; il registro invii salva destinatari e oggetto, non il testo. I modelli nel repository sono vuoti.
- **III. Sola lettura**: l'invio di email è approvato da questa spec, solo su azione esplicita.
- **IV. Autorizzazione**: ruolo verificato nel server a ogni richiesta; ogni modifica di utenti e ogni invio sono tracciati.
- **V. Tracciabilità**: la pagina del monitoraggio mostra lo stato delle fonti.
- **VI. Incrementale**: `crea_blueprint` riceve `solo_admin` e `ruolo_corrente`, predefiniti neutri per il server locale.

## Dati (schema 7)

`utente`, `utente_modifica`, `monitoraggio_mese`, `impostazione`, `sollecito`, `invio_email`.

## Configurazione

`SMTP_SERVER`, `SMTP_PORT`, `SMTP_STARTTLS`, `MAIL_SENDER`, `MAIL_REPLY_TO`, `MAIL_PROVA` (se presente, tutto va solo a quell'indirizzo).

## Scelta rispetto alla spec

Il periodo dei dati è un mese intero (`mese_dati`), perché la pagina delle difformità lavora per mese. Va bene per il flusso descritto; periodi arbitrari restano possibili con i filtri della vista.
