"""Il tag dell'ultima transazione creata precompila il form della successiva.

Il default vive sull'account (`users.last_tag_id`), non nel browser, così segue
l'utente fra dispositivi. Qui fissiamo le due metà della funzione: salvare con
un tag lo imposta, salvare senza lo azzera.
"""

from datetime import date

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
        c.session_factory = TestingSessionLocal
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def auth_headers(client):
    r = client.post(
        "/register",
        json={"username": "mario", "email": "mario@example.it", "password": "password123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def conto(client, auth_headers):
    r = client.post(
        "/conti",
        json={"nome": "Principale", "saldo": 1000, "default": True,
              "ricarica_automatica": False},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def conto_secondario(client, auth_headers):
    r = client.post(
        "/conti",
        json={"nome": "Secondario", "saldo": 500, "default": False,
              "ricarica_automatica": False},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def tag_id(client, auth_headers):
    r = client.post("/tags", json={"nome": "Vacanza"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _last_tag(client, auth_headers):
    r = client.get("/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["last_tag_id"]


def _crea(client, auth_headers, conto, **extra):
    payload = {
        "importo": 10,
        "tipo": "USCITA",
        "data": str(date.today()),
        "descrizione": "Spesa",
        "conto_id": conto["id"],
    }
    payload.update(extra)
    r = client.post("/transazioni", json=payload, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_utente_nuovo_non_ha_default(client, auth_headers):
    assert _last_tag(client, auth_headers) is None


def test_creare_con_un_tag_lo_rende_il_default(client, auth_headers, conto, tag_id):
    _crea(client, auth_headers, conto, tag_id=tag_id)

    assert _last_tag(client, auth_headers) == tag_id


def test_creare_senza_tag_azzera_il_default(client, auth_headers, conto, tag_id):
    """La metà "se lo tolgo me lo toglie per il futuro"."""
    _crea(client, auth_headers, conto, tag_id=tag_id)
    assert _last_tag(client, auth_headers) == tag_id

    _crea(client, auth_headers, conto)

    assert _last_tag(client, auth_headers) is None


def test_l_ultimo_tag_vince(client, auth_headers, conto, tag_id):
    r = client.post("/tags", json={"nome": "Lavoro"}, headers=auth_headers)
    altro_tag = r.json()["id"]

    _crea(client, auth_headers, conto, tag_id=tag_id)
    _crea(client, auth_headers, conto, tag_id=altro_tag)

    assert _last_tag(client, auth_headers) == altro_tag


def test_il_giroconto_non_tocca_il_default(
    client, auth_headers, conto, conto_secondario, tag_id
):
    """La RICARICA non ha il campo tag: non deve spegnere la precompilazione."""
    _crea(client, auth_headers, conto, tag_id=tag_id)

    _crea(
        client,
        auth_headers,
        conto,
        tipo="RICARICA",
        conto_destinazione_id=conto_secondario["id"],
    )

    assert _last_tag(client, auth_headers) == tag_id


def test_il_rimborso_non_tocca_il_default(client, auth_headers, conto, tag_id):
    """Il rimborso eredita il tag del padre: non è una scelta dell'utente."""
    r = client.post("/tags", json={"nome": "Lavoro"}, headers=auth_headers)
    altro_tag = r.json()["id"]

    padre = _crea(client, auth_headers, conto, tag_id=altro_tag)
    _crea(client, auth_headers, conto, tag_id=tag_id)
    assert _last_tag(client, auth_headers) == tag_id

    _crea(
        client,
        auth_headers,
        conto,
        tipo="RIMBORSO",
        parent_transaction_id=padre["id"],
    )

    assert _last_tag(client, auth_headers) == tag_id


def test_il_default_e_per_utente(client, conto, tag_id, auth_headers):
    """Il default di mario non deve comparire nel /me di un altro utente."""
    _crea(client, auth_headers, conto, tag_id=tag_id)

    r = client.post(
        "/register",
        json={"username": "luigi", "email": "luigi@example.it", "password": "password123"},
    )
    assert r.status_code == 200, r.text
    altro = {"Authorization": f"Bearer {r.json()['access_token']}"}

    assert _last_tag(client, altro) is None
    assert _last_tag(client, auth_headers) == tag_id
