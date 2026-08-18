"""Svuotare una tendina in modifica deve davvero azzerare il campo.

Il FE normalizza il "clear" delle Dropdown a `null` proprio per questo: il PUT
applica `model_dump(exclude_unset=True)`, quindi una chiave assente lascia il
valore com'era, mentre una chiave a `null` lo azzera. Se questo endpoint
passasse a `exclude_none=True` il clear tornerebbe muto — e lo scopriremmo qui.
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
        json={"username": "mario", "email": "mario@example.it", "password": "password123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def transazione_completa(client, auth_headers):
    """Una transazione con conto, categoria, sottocategoria e tag valorizzati."""
    conto = client.post(
        "/conti",
        json={"nome": "Principale", "saldo": 1000, "default": True,
              "ricarica_automatica": False},
        headers=auth_headers,
    ).json()

    cat = client.post(
        "/categorie",
        json={"nome": "Casa", "solo_entrata": False, "solo_uscita": True},
        headers=auth_headers,
    ).json()

    r = client.post(
        f"/categorie/{cat['id']}/sottocategorie",
        json=[{"nome": "Bollette", "categoria_id": cat["id"],
               "solo_entrata": False, "solo_uscita": True}],
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text
    sub = r.json()[0]

    tag = client.post("/tags", json={"nome": "Vacanza"}, headers=auth_headers).json()

    r = client.post(
        "/transazioni",
        json={
            "importo": 50,
            "tipo": "USCITA",
            "data": str(date.today()),
            "descrizione": "Spesa",
            "conto_id": conto["id"],
            "categoria_id": cat["id"],
            "sottocategoria_id": sub["id"],
            "tag_id": tag["id"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    tx = r.json()
    assert tx["tag_id"] and tx["categoria_id"] and tx["sottocategoria_id"]
    return tx


@pytest.mark.parametrize("campo", ["tag_id", "categoria_id", "sottocategoria_id"])
def test_null_esplicito_azzera_il_campo(
    client, auth_headers, transazione_completa, campo
):
    tx = transazione_completa

    r = client.put(
        f"/transazioni/{tx['id']}",
        json={
            "importo": tx["importo"],
            "tipo": tx["tipo"],
            "data": tx["data"],
            "descrizione": tx["descrizione"],
            "conto_id": tx["conto_id"],
            campo: None,
        },
        headers=auth_headers,
    )

    assert r.status_code == 200, r.text
    assert r.json()[campo] is None


def test_campo_assente_lascia_il_valore(client, auth_headers, transazione_completa):
    """L'altra faccia: senza la chiave il PUT non deve toccare il campo.

    È ciò che rende necessaria la normalizzazione lato FE — `undefined` sparisce
    da JSON.stringify e finisce esattamente in questo ramo.
    """
    tx = transazione_completa

    r = client.put(
        f"/transazioni/{tx['id']}",
        json={
            "importo": tx["importo"],
            "tipo": tx["tipo"],
            "data": tx["data"],
            "descrizione": "Solo la descrizione",
            "conto_id": tx["conto_id"],
        },
        headers=auth_headers,
    )

    assert r.status_code == 200, r.text
    assert r.json()["tag_id"] == tx["tag_id"]
