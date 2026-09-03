"""Il filtro "solo senza categoria" della schermata Movimenti.

Serve a trovare cosa resta da sistemare dopo un import: le transazioni a cui
nessuno ha ancora messo una categoria. È un filtro sul NULL, non sul valore,
quindi non poteva passare dalle regole per nome di `apply_filters_and_sort`.
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
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def auth_headers(client):
    r = client.post(
        "/register",
        json={
            "username": "mario",
            "email": "mario@example.it",
            "password": "password123",
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def scenario(client, auth_headers):
    """Un conto con due spese categorizzate e una no."""
    r = client.post(
        "/conti",
        json={
            "nome": "Principale",
            "saldo": 1000,
            "default": True,
            "ricarica_automatica": False,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    conto_id = r.json()["id"]

    r = client.post(
        "/categorie",
        json={"nome": "Casa", "solo_entrata": False, "solo_uscita": True},
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text
    categoria_id = r.json()["id"]

    def _spesa(importo, categoria):
        payload = {
            "importo": importo,
            "tipo": "USCITA",
            "data": str(date.today()),
            "descrizione": f"Spesa {importo}",
            "conto_id": conto_id,
        }
        if categoria is not None:
            payload["categoria_id"] = categoria

        r = client.post("/transazioni", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        return r.json()["id"]

    return {
        "categorizzate": [_spesa(100, categoria_id), _spesa(40, categoria_id)],
        "orfana": _spesa(12, None),
    }


def test_filtra_solo_le_transazioni_senza_categoria(client, auth_headers, scenario):
    r = client.get(
        "/transazioni/paginated?page=1&size=50&senza_categoria=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["total"] == 1
    assert [t["id"] for t in body["data"]] == [scenario["orfana"]]


def test_i_totali_seguono_il_filtro(client, auth_headers, scenario):
    # Il conteggio e i totali aggregati partono dalla stessa query filtrata:
    # se divergessero, l'intestazione della lista mentirebbe.
    r = client.get(
        "/transazioni/paginated?page=1&size=50&senza_categoria=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert float(r.json()["total_uscita"]) == 12.0


def test_false_non_filtra_niente(client, auth_headers, scenario):
    # Il toggle spento non deve nascondere le transazioni categorizzate.
    r = client.get(
        "/transazioni/paginated?page=1&size=50&senza_categoria=false",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 3


def test_senza_il_parametro_torna_tutto(client, auth_headers, scenario):
    r = client.get("/transazioni/paginated?page=1&size=50", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 3


def test_vale_anche_sulla_lista_recente(client, auth_headers, scenario):
    # `/transazioni` passa dallo stesso helper: il filtro deve valere anche lì.
    r = client.get("/transazioni?senza_categoria=true", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert [t["id"] for t in r.json()] == [scenario["orfana"]]
