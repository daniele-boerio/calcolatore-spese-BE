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
  `apply_filters_and_sort(query, model, filters)` helper. (Note: `PROJECT_SKILL.md`
  mentions a `services/` package — it does not exist; logic lives in `services.py`.)
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
  missing user filter is a data-leak bug — never omit it.
- **Ownership before mutation:** load the row scoped to the user, `404` if absent,
  then act. Validation failures → `HTTPException(status_code=400, ...)`.
- **Transactions:** wrap multi-step writes in `try / db.commit() / except: db.rollback()`,
  then re-raise a `500 HTTPException`. Use `db.flush()` when you need IDs/side effects
  before commit. Don't hold global sessions.
- **Money is `Decimal`** — convert with `Decimal(str(x))`, quantize to `Decimal("0.01")`
  (Pydantic `field_validator` does this in schemas). Never use `float` for amounts.
- Pydantic v2 only: `model_dump(exclude_unset=True)` for partial updates,
  `field_validator`, `ConfigDict(from_attributes=True)`. No v1 `.dict()` / `Config` class.

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

- Don't invent a test suite, `black`/`ruff`/`pytest`, or CI as if they exist — none is
  wired up today. If the task needs tests, add the dependency and say so explicitly.
- Don't rename domains or restructure modules without calling it out — the FE depends
  on these route shapes and the swagger contract.
- Routers currently log errors with `print(...)`; if you introduce real logging use the
  `logging` logger already set up in `services.py`, and mention the change.
