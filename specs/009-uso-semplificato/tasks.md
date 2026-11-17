# Tasks: Uso semplificato per chi consulta il monitoraggio

- [X] T001 [US1] Sessione permanente di 7 giorni in monitoraggio/wsgi.py e monitoraggio/__main__.py; `DURATA_ACCESSO` in monitoraggio/accesso.py e `DURATA_SESSIONE` in monitoraggio/portale.py a 7 giorni (anteprima 8 ore); testi della pagina di accesso
- [X] T002 [US1] Test: durata dell'accesso e cookie persistente in tests/test_accesso.py e tests/test_portale.py
- [X] T003 [US2] Schema 28: colonne `tipo` e `fonti` in `segnalazione` (monitoraggio/db.py)
- [X] T004 [US2] `portale.segnala` con tipo e fonti, validazione; `consulta.monitoraggio` con stato della segnalazione d'errore per riga
- [X] T005 [US2] consulta.html: pulsante "Segnala errore" per riga, modulo con nota e tre fonti anche per il falso positivo
- [X] T006 [US2] monitoraggi.html e `portale.elenco`: tipo e fonti nella scheda Segnalazioni
- [X] T007 [US2] Test delle segnalazioni d'errore in tests/test_portale.py
- [X] T008 [US3] Scheda "Tutti" in monitoraggi.html e consulta.html; "Tutti gli atti" nello Stato complessivo (riepilogo.html, consulta.html)
- [X] T009 [US4] Manifest, icone, sw.js e route pubbliche; registrazione in menu.js, accesso.html, referenti.html; aiuto "Installa l'app"
- [X] T010 [US4] Test: manifest e sw.js raggiungibili senza login, sw.js senza cache
- [X] T011 [US5] Voci "Categorie protette" e "Reclutamento speciale" in monitoraggio/profili.py; test in tests/test_portale.py
- [X] T012 [US6] Schema 28: tabella `avviso_scorrimento`; modulo monitoraggio/avvisi_scorrimenti.py; attività «scorrimenti» (disattivata all'inizio) in monitoraggio/attivita.py, dopo il confronto delle fonti
- [X] T013 [US6] Copia alla segreteria ed elenco avvisi: monitoraggio/mensile_web.py, static/impostazioni.html (interruttore e orario dall'elenco delle attività)
- [X] T014 [US6] Test dell'avviso: nuovi, già avvisati, prima attivazione, senza destinatari, errore e ritentativo
- [X] T015 Suite completa di test e verifica dei conflitti con origin/main
- [X] T017 Stato complessivo: colonna Comunicazione come nel monitoraggio (comunicazioni.per_atto, App.partiComunicazione) con spunta "inviata" e "Messaggio" che apre lo stesso pannello del monitoraggio; tolti copia e invio vecchi
- [ ] T016 Verifica manuale nell'app in esecuzione (dopo il rilascio su Coolify)
