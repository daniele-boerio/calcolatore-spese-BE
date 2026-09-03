"""Tetto di spesa mensile, distinto dall'obiettivo di risparmio.

`total_budget` è quanto l'utente punta a mettere da parte; `monthly_spending_budget`
è quanto si concede di spendere. Sono due numeri diversi impostati da due controlli
diversi, e l'hero della Home legge il secondo.
"""

from datetime import date, timedelta

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
        json={
            "nome": "Principale",
            "saldo": 5000,
            "default": True,
            "ricarica_automatica": False,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _spesa(client, auth_headers, conto, importo):
    r = client.post(
        "/transazioni",
        json={
            "importo": importo,
            "tipo": "USCITA",
            "descrizione": "spesa",
            "data": date.today().isoformat(),
            "conto_id": conto["id"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text


def _budget(client, auth_headers):
    r = client.get("/conti/currentMonthExpenses", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_senza_tetto_impostato_lo_speso_c_e_lo_stesso(client, auth_headers, conto):
    """L'hero mostra le spese del mese anche prima che l'utente scelga un tetto."""
    _spesa(client, auth_headers, conto, 42.30)

    spending = _budget(client, auth_headers)["spending"]

    assert float(spending["spent"]) == 42.30
    assert spending["budget"] is None
    assert spending["remaining"] is None
    assert spending["percentage"] is None


def test_percentuale_e_residuo_sul_tetto_di_spesa(client, auth_headers, conto):
    client.put(
        "/monthlyBudget",
        json={"monthly_spending_budget": 1200},
        headers=auth_headers,
    )
    _spesa(client, auth_headers, conto, 900)

    spending = _budget(client, auth_headers)["spending"]

    assert float(spending["budget"]) == 1200
    assert float(spending["spent"]) == 900
    assert float(spending["remaining"]) == 300
    assert spending["percentage"] == 75.0


def test_lo_sforamento_resta_negativo(client, auth_headers, conto):
    """Superato il tetto il residuo va sotto zero: l'hero lo mostra, non lo azzera."""
    client.put(
        "/monthlyBudget",
        json={"monthly_spending_budget": 100},
        headers=auth_headers,
    )
    _spesa(client, auth_headers, conto, 150)

    spending = _budget(client, auth_headers)["spending"]

    assert float(spending["remaining"]) == -50
    assert spending["percentage"] == 150.0


def test_i_due_budget_non_si_azzerano_a_vicenda(client, auth_headers):
    """Si impostano da due controlli separati: un PUT parziale tocca solo il suo."""
    client.put("/monthlyBudget", json={"total_budget": 500}, headers=auth_headers)
    client.put(
        "/monthlyBudget",
        json={"monthly_spending_budget": 1200},
        headers=auth_headers,
    )

    body = _budget(client, auth_headers)

    assert float(body["monthly_budget"]["total_budget"]) == 500
    assert float(body["spending"]["budget"]) == 1200


def test_il_null_esplicito_cancella_il_tetto(client, auth_headers):
    client.put(
        "/monthlyBudget",
        json={"monthly_spending_budget": 1200},
        headers=auth_headers,
    )
    client.put(
        "/monthlyBudget",
        json={"monthly_spending_budget": None},
        headers=auth_headers,
    )

    assert _budget(client, auth_headers)["spending"]["budget"] is None


def test_il_previsto_sono_le_ricorrenti_non_ancora_scattate(
    client, auth_headers, conto
):
    """Il secondo segmento della barra: uscite ricorrenti attese entro fine mese."""
    domani = date.today() + timedelta(days=1)
    # A fine mese non c'è un domani dentro lo stesso mese: il test perderebbe senso.
    if domani.month != date.today().month:
        pytest.skip("ultimo giorno del mese")

    r = client.post(
        "/ricorrenze",
        json={
            "nome": "Affitto",
            "importo": 650,
            "tipo": "USCITA",
            "frequenza": "MENSILE",
            "prossima_esecuzione": domani.isoformat(),
            "attiva": True,
            "conto_id": conto["id"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    spending = _budget(client, auth_headers)["spending"]

    assert float(spending["projected"]) == 650
    # Il previsto non è ancora speso: i due numeri restano separati.
    assert float(spending["spent"]) == 0


def test_il_profilo_espone_il_tetto(client, auth_headers):
    client.put(
        "/monthlyBudget",
        json={"monthly_spending_budget": 1200},
        headers=auth_headers,
    )

    r = client.get("/me", headers=auth_headers)

    assert r.status_code == 200, r.text
    assert float(r.json()["monthly_spending_budget"]) == 1200
