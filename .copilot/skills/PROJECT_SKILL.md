# Project Skill: Calcolatore Spese — Linee guida e best practice

Scopo: raccogliere le convenzioni, le pratiche e la checklist per aggiungere nuove feature in questo progetto.

Panoramica architettura

- App: `main.py` espone l'API (FastAPI presumibilmente).
- Router: cartella `routers/` contiene gli endpoint per dominio.
- Schemi: `schemas/` con Pydantic per validazione/serializzazione.
- Modelli: `models.py` con SQLAlchemy; `database.py` gestisce la sessione DB.
- Business logic: `services.py` (funzioni riutilizzabili).
- Migrazioni: Alembic (`alembic/`).

Regole di stile e pratiche consigliate

- Python: mantenere compatibilità con Python 3.10+ e usare type hints ovunque.
- Formattazione: usare `black` + `isort` per import ordering.
- Linting: `flake8` o `ruff` per problemi rapidi.
- Tipi e controllo: `mypy` opzionale per controlli statici.
- Logging: usare il modulo `logging` centralizzato (config in `main.py` o file dedicato).
- Error handling: restituisci `HTTPException` con codice e messaggio chiaro per gli endpoint.
- DB: usare sessioni e context manager; non mantenere sessioni globali.
- Transazioni: raggruppare più operazioni in transazioni quando necessario e fare rollback su eccezione.

Convenzioni sul codice

- Nomi: file e moduli in snake_case; classi in PascalCase.
- Routers: ogni router in `routers/<dominio>.py`, esporta un `APIRouter` con prefisso e tags.
- Schemi: schemi distinti per `Create`, `Read` e `Update` quando utile (es. `CategoriaCreate`, `CategoriaRead`).
- Servizi: logica non-HTTP dentro `services.py` o moduli dedicati; i router devono orchestrare Requests -> Schemas -> Services -> Responses.

Checklist per aggiungere una nuova feature

1. Aggiungi/aggiorna gli schemi in `schemas/`.
2. Se serve, aggiungi/modifica modelli in `models.py` e crea una migration Alembic.
3. Implementa la logica in `services.py` o in un nuovo modulo `services/<feature>.py`.
4. Esporre gli endpoint in `routers/<feature>.py` e registralo in `main.py` se necessario.
5. Aggiungi test unitari e/o di integrazione in `tests/` (consigliato `pytest`).
6. Aggiorna `README` e i changelog interni.
7. Verifica che `alembic revision --autogenerate` generi migration coerenti; applica su DB di sviluppo.
8. Esegui `black --check` e `flake8` prima di aprire PR.

Suggerimenti per le migrazioni

- Non modificare manualmente le migration generate salvo casi particolari; annota il motivo nella migration.
- Testare le migrazioni su DB temporanei (es. sqlite in memoria o container).

CI & Quality

- Raccomandato: pipeline CI che esegue: `black --check`, `isort --check`, `flake8`, `pytest`, `alembic upgrade --sql` (opzionale).
- Aggiungere `pre-commit` con hook per `black`, `isort` e lint.

Esempi di comandi utili

- Installare dipendenze: `pip install -r requirements.txt`
- Creare migration: `alembic revision -m "descrizione" --autogenerate`
- Applicare migration: `alembic upgrade head`
- Eseguire tests: `pytest -q`

Linee guida per PR

- Titolo chiaro: `<area>: breve descrizione`.
- Descrizione: perché, cosa cambia, istruzioni per testare, eventuali migration generate.
- Assicurarsi che i test passino e che la pipeline CI sia verde.

Contatti e riferimenti

- Guarda `README` per informazioni di avvio rapido.

-- fine
