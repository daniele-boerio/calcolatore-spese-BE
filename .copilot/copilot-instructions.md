# Copilot / Agent Instructions per questo repository

Quando scrivi o modifichi codice qui, segui queste regole:

- Mantieni la logica nei moduli esistenti: `services.py` per la business logic, `routers/` per l'API layer.
- Usa gli schemi in `schemas/` per tutte le interfacce input/output.
- Aggiungi type hints e preferisci soluzioni esplicite e testabili.
- Quando serve una modifica al DB: genera una migration Alembic ed elenca i passaggi per applicarla in PR.
- Fornisci test unitari con `pytest` per la nuova logica; per gli endpoint, scrivi test di integrazione minimal.
- Ogni query è filtrata per utente (`Model.user_id == current_user_id`); su conti e transazioni escludi i record con `deleted_at` valorizzato.
- I soldi restano `Decimal`, mai `float`.
- I test girano con `venv/Scripts/python.exe -m pytest -q` (`python` non è nel PATH).
- Non cambiare convenzioni di progetto (naming, struttura) senza segnalarlo nella PR e aggiornare `skills/PROJECT_SKILL.md` e `CLAUDE.md`.

Esempio di flusso per una feature

1. Aggiungere schema `schemas/<feature>.py` o aggiornare esistenti.
2. Aggiungere/modificare modello in `models.py` (se necessario).
3. Creare migration Alembic con `--autogenerate` e verificare manualmente il risultato.
4. Implementare la logica in `services.py` (modulo unico, non esiste un package `services/`).
5. Esporre endpoint in `routers/<feature>.py`.
6. Aggiungere tests e aggiornare `README` se opportuno.

Commit and PR

- Ogni PR deve includere: descrizione, istruzioni per test, migration (se esistente), e note di breaking change.

-- fine
