"""Cambio username dal profilo.

Le stesse regole della registrazione — minuscolo e unico — e il token che
resta valido, perché l'identità di una sessione è l'id, non il nome.
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


@pytest.fixture()
def client(monkeypatch):
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

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def registra(client, nome):
    r = client.post(
        "/register",
        json={
            "username": nome,
            "email": f"{nome}@example.it",
            "password": "password123",
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth_headers(client):
    return registra(client, "mario")


def test_cambia_username(client, auth_headers):
    r = client.put("/me", json={"username": "supermario"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "supermario"

    # Il token di prima continua a valere: l'identità è l'id, non il nome.
    assert client.get("/me", headers=auth_headers).json()["username"] == "supermario"


def test_normalizza_in_minuscolo(client, auth_headers):
    r = client.put("/me", json={"username": "  SuperMario "}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "supermario"


def test_rifiuta_uno_username_gia_preso(client, auth_headers):
    registra(client, "luigi")

    r = client.put("/me", json={"username": "luigi"}, headers=auth_headers)
    assert r.status_code == 400, r.text
    assert client.get("/me", headers=auth_headers).json()["username"] == "mario"


def test_riconfermare_il_proprio_username_non_e_un_conflitto(client, auth_headers):
    r = client.put("/me", json={"username": "mario"}, headers=auth_headers)
    assert r.status_code == 200, r.text


def test_rifiuta_uno_username_vuoto(client, auth_headers):
    r = client.put("/me", json={"username": "   "}, headers=auth_headers)
    assert r.status_code == 400, r.text


def test_serve_essere_autenticati(client):
    r = client.put("/me", json={"username": "chiunque"})
    assert r.status_code in (401, 403), r.text
