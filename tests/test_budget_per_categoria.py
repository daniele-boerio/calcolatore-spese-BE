"""Il budget di spesa desiderato vive sulla categoria.

È il fratello per categoria di `users.monthly_spending_budget`: quanto si
vorrebbe spendere in un mese su "Casa", su "Spesa". Qui si verifica che il
campo faccia il giro intero — creazione, lettura, modifica, rimozione — e che
resti chiuso dentro l'utente che lo scrive.
"""

from decimal import Decimal

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


def _registra(client, username):
    r = client.post(
        "/register",
        json={
            "username": username,
            "email": f"{username}@example.it",
            "password": "password123",
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth_headers(client):
    return _registra(client, "mario")


def _crea(client, headers, nome, budget=None):
    payload = {"nome": nome, "solo_entrata": False, "solo_uscita": True}
    if budget is not None:
        payload["budget_mensile"] = budget

    r = client.post("/categorie", json=payload, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_si_crea_con_il_budget(client, auth_headers):
    creata = _crea(client, auth_headers, "Casa", 500)
    assert Decimal(str(creata["budget_mensile"])) == Decimal("500.00")


def test_senza_budget_resta_nullo(client, auth_headers):
    """Nessun budget deciso non è "budget a zero": sono due cose diverse."""
    creata = _crea(client, auth_headers, "Svago")
    assert creata["budget_mensile"] is None


def test_zero_e_un_budget_vero(client, auth_headers):
    """"Non spenderci niente" si deve poter dire, e non è come non dire niente."""
    creata = _crea(client, auth_headers, "Fumo", 0)
    assert Decimal(str(creata["budget_mensile"])) == Decimal("0.00")


def test_si_aggiunge_e_si_toglie_dopo(client, auth_headers):
    categoria = _crea(client, auth_headers, "Spesa")

    r = client.put(
        f"/categorie/{categoria['id']}",
        json={"budget_mensile": 320.5},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["budget_mensile"])) == Decimal("320.50")

    # Mandarlo a null lo toglie: la categoria torna senza tetto.
    r = client.put(
        f"/categorie/{categoria['id']}",
        json={"budget_mensile": None},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["budget_mensile"] is None


def test_una_modifica_che_non_lo_nomina_lo_lascia_stare(client, auth_headers):
    """`exclude_unset`: rinominare una categoria non le azzera il budget."""
    categoria = _crea(client, auth_headers, "Casa", 500)

    r = client.put(
        f"/categorie/{categoria['id']}",
        json={"nome": "Casa e bollette"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Casa e bollette"
    assert Decimal(str(r.json()["budget_mensile"])) == Decimal("500.00")


def test_la_lista_porta_il_budget(client, auth_headers):
    _crea(client, auth_headers, "Casa", 500)

    r = client.get("/categorie", headers=auth_headers)
    assert r.status_code == 200, r.text
    casa = next(c for c in r.json() if c["nome"] == "Casa")
    assert Decimal(str(casa["budget_mensile"])) == Decimal("500.00")


def test_il_budget_di_un_altro_non_si_tocca(client, auth_headers):
    """La categoria è di chi la crea, e il suo budget pure."""
    categoria = _crea(client, auth_headers, "Casa", 500)
    altri = _registra(client, "luigi")

    r = client.put(
        f"/categorie/{categoria['id']}",
        json={"budget_mensile": 9999},
        headers=altri,
    )
    assert r.status_code == 404, r.text

    r = client.get("/categorie", headers=auth_headers)
    casa = next(c for c in r.json() if c["nome"] == "Casa")
    assert Decimal(str(casa["budget_mensile"])) == Decimal("500.00")
