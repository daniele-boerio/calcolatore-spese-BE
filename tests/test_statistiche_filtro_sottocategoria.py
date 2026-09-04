"""Il filtro dell'Analisi arriva fino alla sottocategoria.

`/statistics/monthDetails` e `/statistics/yearDetails` filtravano per categoria
e per tag ma non per sottocategoria: scegliendo "Casa > Affitto" si vedeva
tutta "Casa". Qui si verifica che le card e i totali guardino lo stesso
sottoinsieme, e che restino chiusi dentro l'utente che chiede.
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


@pytest.fixture()
def scenario(client, auth_headers):
    """Categoria "Casa" con due sottocategorie: Affitto 800, Bollette 120."""
    conto = client.post(
        "/conti",
        json={
            "nome": "Principale",
            "saldo": 5000,
            "default": True,
            "ricarica_automatica": False,
        },
        headers=auth_headers,
    )
    assert conto.status_code == 200, conto.text
    conto_id = conto.json()["id"]

    r = client.post(
        "/categorie",
        json={"nome": "Casa", "solo_entrata": False, "solo_uscita": True},
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text
    categoria_id = r.json()["id"]

    r = client.post(
        f"/categorie/{categoria_id}/sottocategorie",
        json=[
            {"nome": "Affitto", "categoria_id": categoria_id},
            {"nome": "Bollette", "categoria_id": categoria_id},
        ],
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text
    sotto = {s["nome"]: s["id"] for s in r.json()}

    oggi = date.today()

    def _spesa(importo, sottocategoria_id):
        r = client.post(
            "/transazioni",
            json={
                "importo": importo,
                "tipo": "USCITA",
                "data": str(oggi),
                "descrizione": f"Spesa {importo}",
                "conto_id": conto_id,
                "categoria_id": categoria_id,
                "sottocategoria_id": sottocategoria_id,
            },
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        return r.json()["id"]

    _spesa(800, sotto["Affitto"])
    _spesa(120, sotto["Bollette"])

    return {
        "categoria_id": categoria_id,
        "sottocategorie": sotto,
        "anno": oggi.year,
        "mese": oggi.month,
    }


def test_month_details_filtra_per_sottocategoria(client, auth_headers, scenario):
    r = client.get(
        f"/statistics/monthDetails?year={scenario['anno']}&month={scenario['mese']}"
        f"&sottocategoria_id={scenario['sottocategorie']['Affitto']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Le bollette non entrano né nelle card né nel totale.
    assert body["totale_uscita"] == -800.0
    assert [c["totale"] for c in body["data"]] == [-800.0]
    nomi = [s["sottocategoria"] for c in body["data"] for s in c["sottocategorie"]]
    assert nomi == ["Affitto"]


def test_year_details_filtra_per_sottocategoria(client, auth_headers, scenario):
    r = client.get(
        f"/statistics/yearDetails?year={scenario['anno']}"
        f"&categoria_id={scenario['categoria_id']}"
        f"&sottocategoria_id={scenario['sottocategorie']['Bollette']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["totale_uscita"] == -120.0
    mese = next(m for m in body["data"] if m["month"] == scenario["mese"])
    assert mese.get("Bollette") == -120.0
    assert "Affitto" not in mese


def test_senza_filtro_si_vede_tutta_la_categoria(client, auth_headers, scenario):
    """Il controprova: senza sottocategoria i due movimenti ci sono entrambi."""
    r = client.get(
        f"/statistics/monthDetails?year={scenario['anno']}&month={scenario['mese']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["totale_uscita"] == -920.0


def test_sottocategoria_di_un_altro_utente_non_apre_niente(client, scenario):
    """Il filtro non è una scorciatoia per leggere i movimenti altrui."""
    altri = _registra(client, "luigi")

    r = client.get(
        f"/statistics/monthDetails?year={scenario['anno']}&month={scenario['mese']}"
        f"&sottocategoria_id={scenario['sottocategorie']['Affitto']}",
        headers=altri,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totale_uscita"] == 0.0
    assert body["data"] == []
