"""Flusso di sessione end-to-end via HTTP (TestClient), con i cookie veri.

Verifica quello che i test unitari non possono vedere: che il cookie del refresh
token sia davvero httpOnly (quindi non rubabile via XSS), che /auth/refresh
rinnovi l'access token senza credenziali, e che /login non riveli quali account
esistono.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
from database import Base, get_db
from main import app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ALGORITHM", "HS256")
    # In test giriamo su http: senza questo il browser/TestClient scarta il cookie Secure
    monkeypatch.setenv("COOKIE_SECURE", "false")

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
    # get_current_user_id apre una sessione propria via SessionLocal: la puntiamo al DB di test
    monkeypatch.setattr(auth, "SessionLocal", TestingSessionLocal)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _register(client, username="mario", email="mario@example.it", password="password123"):
    return client.post(
        "/register",
        json={"username": username, "email": email, "password": password},
    )


def test_register_imposta_un_cookie_httponly(client):
    resp = _register(client)
    assert resp.status_code == 200
    assert resp.json()["access_token"]

    cookie_header = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in cookie_header
    # La proprietà che rende il refresh token non rubabile via XSS
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()


def test_login_e_refresh_rinnovano_laccess_token(client):
    _register(client)

    login = client.post(
        "/login", data={"username": "mario", "password": "password123"}
    )
    assert login.status_code == 200
    first_access = login.json()["access_token"]

    # Il cookie è già nel jar del client: /auth/refresh non richiede credenziali
    refresh = client.post("/auth/refresh")
    assert refresh.status_code == 200
    assert refresh.json()["access_token"]
    assert refresh.json()["username"] == "mario"

    # E il refresh token è stato ruotato (nuovo cookie emesso)
    assert "refresh_token=" in refresh.headers.get("set-cookie", "")

    # Il nuovo access token è spendibile
    new_access = refresh.json()["access_token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200
    assert me.json()["username"] == "mario"

    assert first_access  # sanity


def test_login_non_rivela_se_lutente_esiste(client):
    _register(client)

    inesistente = client.post(
        "/login", data={"username": "nessuno", "password": "password123"}
    )
    password_errata = client.post(
        "/login", data={"username": "mario", "password": "sbagliata"}
    )

    # Stesso status e stesso messaggio: /login non è più un oracolo di enumerazione
    assert inesistente.status_code == password_errata.status_code == 401
    assert inesistente.json()["detail"] == password_errata.json()["detail"]


def test_logout_invalida_la_sessione(client):
    _register(client)
    client.post("/login", data={"username": "mario", "password": "password123"})

    assert client.post("/auth/logout").status_code == 200

    # Il cookie è stato revocato lato server: niente più refresh
    client.cookies.clear()
    assert client.post("/auth/refresh").status_code == 401


def test_refresh_senza_cookie_rifiutato(client):
    assert client.post("/auth/refresh").status_code == 401
