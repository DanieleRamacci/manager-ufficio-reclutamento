# Tasks: Graduatorie e punteggi da Selezioni Online

- [X] T001 [US1] Sessione SOL in memoria con finestra di login (Playwright, Chrome con profilo temporaneo), verifica del ticket, scadenza 55 minuti in monitoraggio/sol_sessione.py
- [X] T002 [US1] `POST /api/sol/accedi`, `GET /api/sol/sessione`, `POST /api/sol/esci` solo con `login_sol=True` (server locale) in monitoraggio/web.py e `monitoraggio/__main__.py`
- [X] T003 [US1] Voce "Collega Selezioni Online" / "SOL collegato fino alle…" / "Scollega" nel menu in monitoraggio/static/menu.js
- [X] T004 [US1] Test: endpoint non disponibili fuori dal locale, ticket mai nello stato pubblico, scadenza in tests/test_web.py
- [ ] T005 [US2] Verificare con la sessione reale le chiamate autenticate: ricerca delle domande di un bando e `applications.xls?type=score&queryType=application`; documentare in research.md
- [X] T006 [US2] Riepilogo punteggi per graduatoria del mese (solo conteggi) e pagina/sezione dedicata
- [ ] T007 [US3] Generazione del file del mese dal modello, con il foglio Graduatorie pubblicate dall'estrazione e i fogli Bandi/Mobilità dal database
- [X] T008 [US2] Elenco dei candidati con punteggi per le graduatorie del periodo (dal/al): esito V/I/S, posizione, punteggio, protocollo della graduatoria e dell'assunzione idoneo; "protocollo graduatoria mancante" se il protocollo non è valorizzato; candidati solo in memoria, conteggi nel database in monitoraggio/punteggi.py, monitoraggio/fonti/sol_auth.py
- [X] T009 [US3] Excel "Graduatorie pubblicate" con le colonne dell'estrazione Punteggi di SOL, righe senza protocollo evidenziate (`GET /api/punteggi/excel`) in monitoraggio/punteggi.py e monitoraggio/web.py
- [X] T010 [US2] Difformità di SOL rispetto alle fonti (FR-006) per graduatorie e scorrimenti, in rosso, con filtro "solo con difformità"; protocollo di riferimento da allegato SOL, URP o file; riepilogo scorrimenti per protocollo in `punteggi_verifica.scorrimenti_sol` (schema 6) in monitoraggio/punteggi.py, monitoraggio/atti.py, monitoraggio/static/riepilogo.html
- [X] T011 [US2] Link "Punteggi su SOL" (FR-007) in monitoraggio/fonti/sol.py, monitoraggio/web.py, monitoraggio/static/riepilogo.html; test in tests/test_punteggi.py
- [X] T012 [US2] Segnalare gli esiti V/I/S solo quando nessun esito è compilato, non quando sono presenti esiti parziali
