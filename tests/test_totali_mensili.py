"""Coerenza dei totali del mese fra i vari endpoint che li calcolano.

Lo stesso mese veniva riassunto da tre posti diversi (budget, statistiche,
grafico a torta) con tre formule diverse. Qui fissiamo che diano lo stesso
numero, incluso il caso delle transazioni "legacy" con `importo_netto` a NULL
(create prima della migration 9cd85e955956, che non ha fatto il backfill).
"""

from datetime import date

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
    # Il budget del limiter è per-processo e condiviso con gli altri test: senza
    # questo, /register va in 429 quando la suite gira intera.
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
            "saldo": 1000,
            "default": True,
            "ricarica_automatica": False,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _inserisci(client, conto, **kwargs):
    """Scrive una transazione direttamente a DB (per poter forzare importo_netto)."""
    db = client.session_factory()
    try:
        db.add(
            models.Transazione(
                data=date.today(),
                conto_id=conto["id"],
                user_id=db.get(models.Conto, conto["id"]).user_id,
                **kwargs,
            )
        )
        db.commit()
    finally:
        db.close()


def test_put_monthly_budget_risponde_con_il_budget_ricalcolato(client, auth_headers):
    """Regressione: la chiamata posizionale a get_current_month_expenses dava 500."""
    r = client.put("/monthlyBudget", json={"total_budget": 500}, headers=auth_headers)

    assert r.status_code == 200, r.text
    monthly = r.json()["monthly_budget"]
    assert float(monthly["total_budget"]) == 500
    assert monthly["remaining"] is not None


def _crea_categoria(client, auth_headers, nome, solo_uscita):
    r = client.post(
        "/categorie",
        json={
            "nome": nome,
            "solo_entrata": not solo_uscita,
            "solo_uscita": solo_uscita,
        },
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_totali_coerenti_anche_con_importo_netto_null(client, auth_headers, conto):
    """Budget, statistiche e torta devono vedere lo stesso mese allo stesso modo."""
    cat_uscita = _crea_categoria(client, auth_headers, "Casa", solo_uscita=True)
    cat_entrata = _crea_categoria(client, auth_headers, "Stipendio", solo_uscita=False)

    # Transazione "legacy": importo_netto mai popolato dalla migration
    _inserisci(client, conto, importo=100, importo_netto=None, tipo="USCITA",
               categoria_id=cat_uscita)
    # Transazione moderna
    _inserisci(client, conto, importo=50, importo_netto=50, tipo="USCITA",
               categoria_id=cat_uscita)
    _inserisci(client, conto, importo=300, importo_netto=300, tipo="ENTRATA",
               categoria_id=cat_entrata)

    today = date.today()
    budget = client.get("/conti/currentMonthExpenses", headers=auth_headers).json()
    stats = client.get(
        f"/statistics/monthDetails?year={today.year}&month={today.month}",
        headers=auth_headers,
    ).json()
    pie = client.get("/conti/expensesByCategory", headers=auth_headers).json()

    # Risparmio = 300 entrate - 150 uscite
    assert float(budget["monthly_budget"]["remaining"]) == 150.0
    assert stats["totale_uscita"] == -150.0
    assert stats["totale_entrata"] == 300.0
    assert stats["totale"] == 150.0
    assert sum(item["value"] for item in pie) == 150.0

    # Le card per categoria devono sommare al totale in intestazione
    somma_card = sum(c["totale"] for c in stats["data"] if c["totale"] < 0)
    assert somma_card == stats["totale_uscita"]


def test_rimborso_riduce_uscite_e_alza_il_risparmio(client, auth_headers, conto):
    """Il rimborso non è una riga a sé: scala il netto della spesa padre."""
    r = client.post(
        "/transazioni",
        json={"importo": 100, "tipo": "USCITA", "data": str(date.today()),
              "descrizione": "Spesa", "conto_id": conto["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    padre_id = r.json()["id"]

    prima = client.get("/conti/currentMonthExpenses", headers=auth_headers).json()
    assert float(prima["monthly_budget"]["remaining"]) == -100.0

    r = client.post(
        "/transazioni",
        json={"importo": 30, "tipo": "RIMBORSO", "data": str(date.today()),
              "descrizione": "Reso", "conto_id": conto["id"],
              "parent_transaction_id": padre_id},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    today = date.today()
    dopo = client.get("/conti/currentMonthExpenses", headers=auth_headers).json()
    stats = client.get(
        f"/statistics/monthDetails?year={today.year}&month={today.month}",
        headers=auth_headers,
    ).json()
    pie = client.get("/conti/expensesByCategory", headers=auth_headers).json()

    assert float(dopo["monthly_budget"]["remaining"]) == -70.0
    assert stats["totale_uscita"] == -70.0
    assert sum(item["value"] for item in pie) == 70.0


def test_giroconto_non_sporca_i_totali(client, auth_headers, conto):
    """Le RICARICA sono movimenti interni: né spesa, né card fantasma a 0."""
    r = client.post(
        "/conti",
        json={"nome": "Secondario", "saldo": 0, "default": False,
              "ricarica_automatica": False},
        headers=auth_headers,
    )
    destinazione = r.json()

    r = client.post(
        "/transazioni",
        json={"importo": 200, "tipo": "RICARICA", "data": str(date.today()),
              "descrizione": "Giroconto", "conto_id": conto["id"],
              "conto_destinazione_id": destinazione["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    today = date.today()
    budget = client.get("/conti/currentMonthExpenses", headers=auth_headers).json()
    stats = client.get(
        f"/statistics/monthDetails?year={today.year}&month={today.month}",
        headers=auth_headers,
    ).json()

    assert float(budget["monthly_budget"]["remaining"]) == 0.0
    assert stats["totale_uscita"] == 0.0
    assert stats["data"] == []


def test_accantonamento_riduce_il_risparmio_una_volta_sola(client, auth_headers, conto):
    _inserisci(client, conto, importo=500, importo_netto=500, tipo="ENTRATA")

    r = client.post(
        "/transazioni",
        json={"importo": 200, "tipo": "ACCANTONAMENTO", "data": str(date.today()),
              "descrizione": "Fondo emergenza", "conto_id": conto["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    today = date.today()
    budget = client.get("/conti/currentMonthExpenses", headers=auth_headers).json()
    stats = client.get(
        f"/statistics/monthDetails?year={today.year}&month={today.month}",
        headers=auth_headers,
    ).json()

    assert float(budget["monthly_budget"]["remaining"]) == 300.0
    assert stats["totale_accantonamento"] == 200.0
    assert stats["totale"] == 300.0


def _ricorrenza_futura(client, conto, importo, tipo="USCITA"):
    """Ricorrenza attiva che scatta entro fine mese, ma non ancora scattata."""
    db = client.session_factory()
    try:
        db.add(
            models.Ricorrenza(
                nome="Affitto",
                importo=importo,
                tipo=tipo,
                frequenza="MENSILE",
                # Oggi rientra sempre nella finestra [oggi, fine mese], anche
                # l'ultimo giorno del mese.
                prossima_esecuzione=date.today(),
                attiva=True,
                conto_id=conto["id"],
                user_id=db.get(models.Conto, conto["id"]).user_id,
            )
        )
        db.commit()
    finally:
        db.close()


def test_put_monthly_budget_rispetta_le_ricorrenti_future(client, auth_headers, conto):
    """La PUT risponde con la card ricalcolata: deve guardare lo stesso flag della GET.

    Senza, salvare il tetto di spesa con la spunta accesa rimandava indietro una
    card calcolata "senza ricorrenti future", e il risparmio del mese tornava su.
    """
    _ricorrenza_futura(client, conto, importo=200)

    senza = client.put(
        "/monthlyBudget",
        json={"total_budget": 500},
        headers=auth_headers,
    )
    con = client.put(
        "/monthlyBudget?include_future_recurring=true",
        json={"total_budget": 500},
        headers=auth_headers,
    )

    assert senza.status_code == 200, senza.text
    assert con.status_code == 200, con.text

    risparmio_senza = float(senza.json()["monthly_budget"]["remaining"])
    risparmio_con = float(con.json()["monthly_budget"]["remaining"])

    # L'uscita ricorrente non ancora scattata pesa solo quando la si include.
    assert risparmio_con == risparmio_senza - 200
