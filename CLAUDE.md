# BE — FastAPI + SQLAlchemy + PostgreSQL

API for the Calcolatore Spese app. Sync SQLAlchemy ORM, Pydantic v2 schemas,
Alembic migrations, JWT bearer auth, APScheduler background jobs.

## Layout

- `main.py` — app, CORS, router registration, APScheduler cron jobs.
- `routers/<dominio>.py` — one `APIRouter(prefix="/<dominio>", tags=["<Dominio>"])`
  per domain; the HTTP layer (validate → orchestrate → respond).
- `schemas/<dominio>.py` — Pydantic v2 models: `…Base`, `…Create`, `…Update`,
  `…Out`. Re-exported from `schemas/__init__.py`.
- `models.py` — SQLAlchemy models (single module).
- `services.py` — **single** module of reusable logic + scheduler tasks + the shared
  `apply_filters_and_sort(query, model, filters)` helper. There is no `services/`
  package.
- `rate_limit.py` — shared slowapi `limiter` for rate-limited endpoints.
- `tests/` — pytest on in-memory SQLite (`db_session` fixture in `tests/conftest.py`);
  tests call endpoint functions directly, the auth flow uses `TestClient`.

## Running things (Windows: `python` is not on PATH, use the venv)

Always `python -m <tool>`: the `.exe` launchers in `venv/Scripts` exit silently
because the project path contains a space.

```bash
venv/Scripts/python.exe -m pytest -q
venv/Scripts/python.exe -m alembic revision -m "desc" --autogenerate
venv/Scripts/python.exe -m alembic upgrade head
venv/Scripts/python.exe -m uvicorn main:app --reload
```
- `database.py` — engine + `SessionLocal` + the `get_db()` dependency.
- `auth.py` — `get_current_user_id` dependency; bearer JWT.

## Endpoint conventions (match the existing routers exactly)

```python
@router.post("", response_model=XxxOut)
def create_xxx(
    payload: XxxCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    ...
```

- **Every query is user-scoped:** `.filter(Model.user_id == current_user_id)`. A
  missing user filter is a data-leak bug — never omit it. That includes lookups of
  related rows (destination conto, parent transaction, categoria/sottocategoria/tag —
  see `resolve_tassonomia` in `routers/transazioni.py`).
- **Soft-delete:** `Conto` and `Transazione` carry `deleted_at`. Reads and aggregates
  filter `deleted_at.is_(None)`; deleting a conto is a reversible soft-delete, never
  a hard cascade.
- **Ownership before mutation:** load the row scoped to the user, `404` if absent,
  then act. Validation failures → `HTTPException(status_code=400, ...)`.
- **Transactions:** wrap multi-step writes in `try / db.commit() / except: db.rollback()`,
  then re-raise a `500 HTTPException`. Use `db.flush()` when you need IDs/side effects
  before commit. Don't hold global sessions.
- **Money is `Decimal`** — convert with `Decimal(str(x))`, quantize to `Decimal("0.01")`
  (Pydantic `field_validator` does this in schemas). Never use `float` for amounts.
- Pydantic v2 only: `model_dump(exclude_unset=True)` for partial updates,
  `field_validator`, `ConfigDict(from_attributes=True)`. No v1 `.dict()` / `Config` class.

## Balances (`Conto.saldo`)

- The balance is updated incrementally by many paths. **Never** write
  `conto.saldo += ...` for a transaction: call
  `services.applica_effetto_saldo(db, transazione, user_id, segno)` (segno=-1 to
  revert). It uses `effetto_sul_conto`, the same rule used to read history back.
- `Conto.saldo_base` = balance minus the effect of active transactions. Transaction
  operations must leave it unchanged; `task_verifica_saldi` (nightly) and
  `GET /conti/verifica-saldi` report accounts where it moved,
  `POST /conti/{id}/correggi-saldo` fixes them.
- Code that sets a balance **by hand** (create/edit account, consolidate, absorb,
  delete/restore an account) must call `allinea_saldo_base` /
  `allinea_saldi_base_utente` before commit, or the check raises a false alarm.
- `tests/test_saldi_e_idempotenza.py` walks every balance path and asserts the check
  stays clean: extend it when you add a new one.

## Idempotency and scheduled jobs

- `POST /transazioni` honours the `Idempotency-Key` header (unique per user): a
  repeated key returns the transaction already created. New create endpoints that
  the offline queue may retry should do the same.
- Jobs that write money (recurrences, auto top-up) re-select each row with
  `.with_for_update(skip_locked=True)` and re-check it is still due before acting,
  then commit per row: two scheduler processes cannot double-execute.
- Recurrences are executed with their **due date**, catching up every missed
  occurrence; they stop at `data_fine` / `rate_rimanenti` / when the linked debt is
  paid off. `importo_variabile` ones are never auto-executed.

## FastAPI performance notes (apply when relevant)

- For aggregates over a filtered query, push work to SQL with `func.sum(...)` /
  `.with_entities(...)` and call `.order_by(None)` before aggregating (the pattern in
  `routers/transazioni.py` avoids a Postgres GROUP BY error). Don't sum in Python.
- Paginate with `.offset((page-1)*size).limit(size)`; compute `total` with `.count()`
  on the *filtered* query — don't load all rows to count them.
- Watch N+1: when returning related entities, prefer `selectinload`/`joinedload` over
  per-row lookups in a loop.
- Endpoints are sync (`def`, not `async def`) and run in the threadpool — keep them
  that way unless you deliberately move to async SQLAlchemy. Don't mix blocking ORM
  calls into `async def` handlers.

## Migrations

- Schema change → `alembic revision -m "desc" --autogenerate`, then **read the
  generated script** before applying (`alembic upgrade head`). Note non-obvious edits.
- Migrating a model without a migration is incomplete work — flag it.

## Don't

- `pytest` **is** wired up now (`pytest.ini` + `tests/`, in-memory SQLite via
  `tests/conftest.py`); run it after BE changes (CI runs it too: `.github/workflows/ci.yml`). Still absent:
  `black`/`ruff` and pre-commit —
  don't claim those exist; add the dependency explicitly if you introduce them.
- Don't rename domains or restructure modules without calling it out — the FE depends
  on these route shapes and the swagger contract.
- Routers log through the `logging` logger (`logger = logging.getLogger(__name__)`),
  not `print(...)`; keep new error logging on that logger (use `logger.exception(...)`
  inside `except` blocks so the traceback is captured).
