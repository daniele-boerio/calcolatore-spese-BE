"""Fixture condivise per i test.

Usa un DB SQLite in-memory ricreato per ogni test: veloce e isolato, senza
toccare il Postgres di sviluppo. I modelli non usano tipi PG-specifici né
`server_default`, quindi `create_all` gira pulito su SQLite.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
import models  # noqa: F401 — l'import registra i modelli su Base.metadata


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def api(monkeypatch):
    """Client HTTP sull'app vera, con un DB SQLite in memoria tutto suo.

    Anche i job dello scheduler (`services.SessionLocal`) puntano a questo DB,
    così un test può lanciare un task notturno e leggerne l'effetto via API.
    `api.registra(username)` crea un utente e ne restituisce gli header.
    """
    from fastapi.testclient import TestClient

    import auth
    import services
    from database import get_db
    from main import app
    from rate_limit import limiter

    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("COOKIE_SECURE", "false")
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
    monkeypatch.setattr(services, "SessionLocal", TestingSessionLocal)

    with TestClient(app) as c:
        c.session_factory = TestingSessionLocal

        def registra(username="mario"):
            r = c.post(
                "/register",
                json={
                    "username": username,
                    "email": f"{username}@example.it",
                    "password": "password123",
                },
            )
            assert r.status_code == 200, r.text
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        c.registra = registra
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
