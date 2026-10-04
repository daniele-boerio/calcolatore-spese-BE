# Project Skill: Calcolatore Spese — Linee guida e best practice

Scopo: raccogliere le convenzioni, le pratiche e la checklist per aggiungere nuove feature in questo progetto.

Panoramica architettura

- App: `main.py` espone l'API FastAPI, registra i router e i job APScheduler.
- Router: cartella `routers/` contiene gli endpoint per dominio.
- Schemi: `schemas/` con Pydantic per validazione/serializzazione.
- Modelli: `models.py` con SQLAlchemy; `database.py` gestisce la sessione DB.
- Business logic: `services.py` (modulo unico: funzioni riutilizzabili, task schedulati, `apply_filters_and_sort`).
- Rate limiting: `rate_limit.py` (slowapi `limiter` condiviso).
- Test: `tests/` con pytest su SQLite in memoria (fixture `db_session` in `tests/conftest.py`).
- Migrazioni: Alembic (`alembic/`).

Regole di stile e pratiche consigliate

- Python: mantenere compatibilità con Python 3.10+ e usare type hints ovunque.
- Formatter, linter, mypy e pre-commit **non** sono configurati: non darli per scontati; se ne introduci uno, aggiungi la dipendenza esplicitamente. La CI (GitHub Actions) lancia `pytest` e controlla che ci sia una sola head Alembic.
- Saldi: i movimenti muovono i saldi solo con `services.applica_effetto_saldo`; chi imposta un saldo a mano chiama `allinea_saldo_base` (vedi `CLAUDE.md`).
- Logging: `logger = logging.getLogger(__name__)` e `logger.exception(...)` nei blocchi `except`; mai `print`.
- Sicurezza: ogni query filtrata per `user_id`; conti e transazioni sono soft-delete (`deleted_at`), le letture li escludono.
- Soldi: sempre `Decimal` (`Decimal(str(x))`, quantize a `0.01`), mai `float`.
- Error handling: restituisci `HTTPException` con codice e messaggio chiaro per gli endpoint.
- DB: usare sessioni e context manager; non mantenere sessioni globali.
- Transazioni: raggruppare più operazioni in transazioni quando necessario e fare rollback su eccezione.

Convenzioni sul codice

- Nomi: file e moduli in snake_case; classi in PascalCase.
- Routers: ogni router in `routers/<dominio>.py`, esporta un `APIRouter` con prefisso e tags.
- Schemi: `…Base`, `…Create`, `…Update`, `…Out` (es. `TransazioneCreate`, `TransazioneOut`), Pydantic v2, riesportati da `schemas/__init__.py`.
- Servizi: logica non-HTTP dentro `services.py`; i router devono orchestrare Requests -> Schemas -> Services -> Responses.

Checklist per aggiungere una nuova feature

1. Aggiungi/aggiorna gli schemi in `schemas/`.
2. Se serve, aggiungi/modifica modelli in `models.py` e crea una migration Alembic.
3. Implementa la logica in `services.py`.
4. Esporre gli endpoint in `routers/<feature>.py` e registralo in `main.py` se necessario.
5. Aggiungi test in `tests/` (pytest, fixture `db_session`) e lanciali.
6. Aggiorna `README` e i changelog interni.
7. Verifica che `alembic revision --autogenerate` generi migration coerenti; applica su DB di sviluppo.
8. Se l'endpoint cambia forma, riesporta lo swagger in `FE/calcolatore_spese_swagger.json` e aggiorna `interfaces.ts`/`api_calls.ts` nel FE.

Suggerimenti per le migrazioni

- Non modificare manualmente le migration generate salvo casi particolari; annota il motivo nella migration.
- Testare le migrazioni su DB temporanei (es. sqlite in memoria o container).

CI & Quality

- Gate: `pytest`, lanciato anche dalla CI (`.github/workflows/ci.yml`). Pre-commit non esiste ancora.

Esempi di comandi utili

- Installare dipendenze: `venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-dev.txt`
- Creare migration: `venv/Scripts/python.exe -m alembic revision -m "descrizione" --autogenerate`
- Applicare migration: `venv/Scripts/python.exe -m alembic upgrade head`
- Eseguire tests: `venv/Scripts/python.exe -m pytest -q`

Linee guida per PR

- Titolo chiaro: `<area>: breve descrizione`.
- Descrizione: perché, cosa cambia, istruzioni per testare, eventuali migration generate.
- Assicurarsi che i test passino.

Contatti e riferimenti

- Guarda `README` per informazioni di avvio rapido.

-- fine
