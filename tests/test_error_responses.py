"""Cosa vede il client quando qualcosa esplode davvero.

Un 500 "muto" (text/plain, senza header CORS) è indistinguibile, dal browser, da
un backend irraggiungibile: il frontend può solo mostrare un errore generico e la
causa si perde. Questi test bloccano il contratto opposto — errore = JSON con
`detail` leggibile, `error_id` per ritrovare la traceback nei log, e header CORS
presenti — che dipende dall'ORDINE dei middleware in `main.py`.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
from database import Base, get_db
from main import app
from rate_limit import limiter

ORIGIN = "http://localhost:5173"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    # Il budget del limiter è per-processo e condiviso con gli altri test: qui
    # il rate limiting non c'entra nulla, e ci serve poterlo ignorare.
    monkeypatch.setattr(limiter, "enabled", False)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(auth, "SessionLocal", TestingSessionLocal)

    # raise_server_exceptions=False: vogliamo ispezionare la RISPOSTA d'errore,
    # non far ri-sollevare l'eccezione dal TestClient.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _make_login_explode(monkeypatch):
    """Fa fallire /login in un punto NON coperto da try/except del router."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("qualcosa di imprevisto")

    monkeypatch.setattr(auth, "verify_password", boom)


def test_errore_non_gestito_risponde_json_con_error_id(client, monkeypatch):
    _make_login_explode(monkeypatch)

    resp = client.post("/login", data={"username": "mario", "password": "x"})

    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/json")

    body = resp.json()
    # Il riferimento è ciò che rende segnalabile un errore: compare identico nei log
    assert body["error_id"]
    assert body["error_id"] in body["detail"]
    # ...e il messaggio dice almeno DOVE è successo, non solo "errore"
    assert "/login" in body["detail"]


def test_errore_non_gestito_mantiene_gli_header_cors(client, monkeypatch):
    """Regressione sull'ordine dei middleware.

    Se il gestore degli errori finisce FUORI da CORSMiddleware, la risposta 500
    arriva senza `access-control-allow-origin`: il browser la scarta e il
    frontend non può leggere né `detail` né `error_id`.
    """
    _make_login_explode(monkeypatch)

    resp = client.post(
        "/login",
        data={"username": "mario", "password": "x"},
        headers={"Origin": ORIGIN},
    )

    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == ORIGIN


def test_login_distingue_credenziali_ok_da_sessione_non_creata(client, monkeypatch):
    """Se le credenziali sono valide ma la sessione non parte, il messaggio deve dirlo."""
    user = auth_user(client)

    def boom(*_args, **_kwargs):
        raise RuntimeError("insert fallita")

    monkeypatch.setattr(auth, "issue_refresh_token", boom)

    resp = client.post(
        "/login", data={"username": user["username"], "password": user["password"]}
    )

    assert resp.status_code == 500
    detail = resp.json()["detail"].lower()
    assert "credentials are valid" in detail
    assert "session" in detail


def auth_user(client):
    """Crea un utente direttamente sul DB di test, senza passare da /register
    (che ha un rate limit orario condiviso con gli altri test)."""
    from models import User

    db = next(iter(app.dependency_overrides[get_db]()))
    user = User(
        username="mario",
        email="mario@example.it",
        hashed_password=auth.get_password_hash("password123"),
    )
    db.add(user)
    db.commit()
    db.close()
    return {"username": "mario", "password": "password123"}
