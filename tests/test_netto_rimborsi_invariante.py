"""Invariante: importo_netto del padre == lordo - somma dei rimborsi vivi.

Le card delle statistiche mostrano `-importo_netto` della spesa, mentre la lista
che si apre cliccandole mostra le righe grezze (spesa + rimborsi). I due numeri
devono tornare: se l'invariante si rompe, la card e la lista si contraddicono.

Scenario di riferimento: Traghetto Corsica 510 con quattro rimborsi da 102.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import models
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
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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
        json={"username": "mario", "email": "m@e.it", "password": "password123"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def setup(client, auth_headers):
    conto = client.post(
        "/conti",
        json={"nome": "BBVA", "saldo": 5000, "default": True,
              "ricarica_automatica": False},
        headers=auth_headers,
    ).json()
    cat = client.post(
        "/categorie",
        json={"nome": "Trasporti", "solo_entrata": False, "solo_uscita": True},
        headers=auth_headers,
    ).json()
    return {"conto": conto, "categoria": cat}


def _spesa(client, auth_headers, setup, importo, giorno=3, mese=3):
    r = client.post(
        "/transazioni",
        json={"importo": importo, "tipo": "USCITA", "data": str(date(2026, mese, giorno)),
              "descrizione": "Traghetto Corsica", "conto_id": setup["conto"]["id"],
              "categoria_id": setup["categoria"]["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _rimborso(client, auth_headers, setup, padre, importo, giorno=4, mese=3):
    r = client.post(
        "/transazioni",
        json={"importo": importo, "tipo": "RIMBORSO", "data": str(date(2026, mese, giorno)),
              "descrizione": "Rimborso Traghetto", "conto_id": setup["conto"]["id"],
              "parent_transaction_id": padre["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _netto(client, tx_id):
    db = client.session_factory()
    try:
        return db.get(models.Transazione, int(tx_id)).importo_netto
    finally:
        db.close()


def _card_marzo(client, auth_headers):
    """Il totale che finisce sulla card Trasporti di marzo."""
    r = client.get("/statistics/yearDetails?year=2026", headers=auth_headers)
    assert r.status_code == 200, r.text
    marzo = next(m for m in r.json()["data"] if m["month"] == 3)
    return marzo.get("Trasporti", 0)


def test_scenario_dello_screenshot(client, auth_headers, setup):
    """510 di spesa, quattro rimborsi da 102: la card deve dire -102."""
    padre = _spesa(client, auth_headers, setup, 510)
    for giorno in (3, 4, 4, 6):
        _rimborso(client, auth_headers, setup, padre, 102, giorno=giorno)

    assert _netto(client, padre["id"]) == Decimal("102.00")
    assert _card_marzo(client, auth_headers) == -102.0


def test_modificare_un_rimborso_aggiorna_il_padre(client, auth_headers, setup):
    padre = _spesa(client, auth_headers, setup, 510)
    rimborso = _rimborso(client, auth_headers, setup, padre, 102)

    r = client.put(
        f"/transazioni/{rimborso['id']}",
        json={"importo": 200, "tipo": "RIMBORSO", "data": rimborso["data"],
              "descrizione": "Rimborso", "conto_id": setup["conto"]["id"],
              "parent_transaction_id": padre["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    assert _netto(client, padre["id"]) == Decimal("310.00")


def test_cancellare_un_rimborso_ripristina_il_padre(client, auth_headers, setup):
    padre = _spesa(client, auth_headers, setup, 510)
    rimborso = _rimborso(client, auth_headers, setup, padre, 102)

    assert client.delete(
        f"/transazioni/{rimborso['id']}", headers=auth_headers
    ).status_code == 200

    assert _netto(client, padre["id"]) == Decimal("510.00")


def test_modificare_il_padre_non_perde_i_rimborsi(client, auth_headers, setup):
    """Ritoccare la spesa (anche solo la descrizione) non deve riazzerare il netto."""
    padre = _spesa(client, auth_headers, setup, 510)
    for _ in range(4):
        _rimborso(client, auth_headers, setup, padre, 102)
    assert _netto(client, padre["id"]) == Decimal("102.00")

    r = client.put(
        f"/transazioni/{padre['id']}",
        json={"importo": 510, "tipo": "USCITA", "data": padre["data"],
              "descrizione": "Traghetto Corsica (andata)",
              "conto_id": setup["conto"]["id"],
              "categoria_id": setup["categoria"]["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    assert _netto(client, padre["id"]) == Decimal("102.00")
    assert _card_marzo(client, auth_headers) == -102.0


def test_rimborso_datato_in_un_altro_mese(client, auth_headers, setup):
    """Il rimborso sconta il mese del PADRE, non il proprio.

    Non è un bug del calcolo ma è la trappola di lettura: la lista di marzo può
    mostrare un rimborso il cui effetto è finito sulla card di febbraio.
    """
    padre = _spesa(client, auth_headers, setup, 510, mese=2)
    _rimborso(client, auth_headers, setup, padre, 102, mese=3)

    assert _card_marzo(client, auth_headers) == 0
    r = client.get("/statistics/yearDetails?year=2026", headers=auth_headers)
    febbraio = next(m for m in r.json()["data"] if m["month"] == 2)
    assert febbraio.get("Trasporti") == -408.0
