"""Il filtro per tag della pagina statistiche deve valere ovunque.

Selezionando un tag, le card (aggregati) e la lista di transazioni aperta
cliccando una card devono vedere lo stesso sottoinsieme: solo le transazioni
con quel tag. Il bug era che la lista ignorava il tag e mostrava tutta la
categoria.
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
def scenario(client, auth_headers, conto):
    """Una categoria "Casa" con due spese: una taggata "Vacanza", una no."""
    r = client.post(
        "/categorie",
        json={"nome": "Casa", "solo_entrata": False, "solo_uscita": True},
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text
    categoria_id = r.json()["id"]

    r = client.post("/tags", json={"nome": "Vacanza"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    tag_id = r.json()["id"]

    oggi = date.today()

    def _spesa(importo, tag):
        payload = {
            "importo": importo,
            "tipo": "USCITA",
            "data": str(oggi),
            "descrizione": f"Spesa {importo}",
            "conto_id": conto["id"],
            "categoria_id": categoria_id,
        }
        if tag is not None:
            payload["tag_id"] = tag
        r = client.post("/transazioni", json=payload, headers=auth_headers)
        assert r.status_code == 200, r.text
        return r.json()["id"]

    taggata = _spesa(100, tag_id)
    non_taggata = _spesa(40, None)

    return {
        "categoria_id": categoria_id,
        "tag_id": tag_id,
        "taggata": taggata,
        "non_taggata": non_taggata,
        "anno": oggi.year,
        "mese": oggi.month,
    }


def test_month_details_filtra_per_tag(client, auth_headers, scenario):
    r = client.get(
        f"/statistics/monthDetails?year={scenario['anno']}&month={scenario['mese']}"
        f"&tag_id={scenario['tag_id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totale_uscita"] == -100.0
    assert [c["totale"] for c in body["data"]] == [-100.0]


def test_year_details_filtra_per_tag(client, auth_headers, scenario):
    r = client.get(
        f"/statistics/yearDetails?year={scenario['anno']}&tag_id={scenario['tag_id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totale_uscita"] == -100.0
    mese = next(m for m in body["data"] if m["month"] == scenario["mese"])
    assert mese.get("Casa") == -100.0


def test_lista_transazioni_filtra_per_tag(client, auth_headers, scenario):
    """La lista che si apre cliccando una card deve rispettare il tag."""
    r = client.get(
        f"/transazioni/paginated?page=1&size=10"
        f"&categoria_id={scenario['categoria_id']}&tag_id={scenario['tag_id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert [t["id"] for t in body["data"]] == [scenario["taggata"]]
