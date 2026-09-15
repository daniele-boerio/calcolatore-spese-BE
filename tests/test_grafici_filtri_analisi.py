"""I grafici dell'Analisi guardano lo stesso sottoinsieme delle altre viste.

`/charts/*` prendeva solo un intervallo di date: scegliere una categoria, una
sottocategoria o un tag in cima alla schermata cambiava le viste Mese e Anno e
lasciava i quattro grafici sull'anno intero. Qui si verifica che i filtri
arrivino, e che restino chiusi dentro l'utente che chiede.
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
    """Casa (Affitto 800, Bollette 120) e Spesa (250), con un tag su Affitto."""
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

    tag = client.post("/tags", json={"nome": "Fisse"}, headers=auth_headers)
    assert tag.status_code in (200, 201), tag.text
    tag_id = tag.json()["id"]

    def _categoria(nome):
        r = client.post(
            "/categorie",
            json={"nome": nome, "solo_entrata": False, "solo_uscita": True},
            headers=auth_headers,
        )
        assert r.status_code in (200, 201), r.text
        return r.json()["id"]

    casa = _categoria("Casa")
    spesa = _categoria("Spesa")

    r = client.post(
        f"/categorie/{casa}/sottocategorie",
        json=[
            {"nome": "Affitto", "categoria_id": casa},
            {"nome": "Bollette", "categoria_id": casa},
        ],
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text
    sotto = {s["nome"]: s["id"] for s in r.json()}

    oggi = date.today()

    def _spesa(importo, categoria_id, sottocategoria_id=None, tag=None):
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
                "tag_id": tag,
            },
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

    _spesa(800, casa, sotto["Affitto"], tag_id)
    _spesa(120, casa, sotto["Bollette"])
    _spesa(250, spesa)

    return {
        "casa": casa,
        "sottocategorie": sotto,
        "tag_id": tag_id,
        "anno": oggi.year,
        "mese": oggi.month,
    }


def _range(scenario):
    anno = scenario["anno"]
    return f"data_inizio={anno}-01-01&data_fine={anno}-12-31"


def _uscite_del_mese(body, mese):
    riga = next(r for r in body if r["label"] == str(mese))
    return riga["uscite"]


def test_income_expense_senza_filtri_vede_tutto(client, auth_headers, scenario):
    r = client.get(f"/charts/income-expense?{_range(scenario)}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _uscite_del_mese(r.json(), scenario["mese"]) == 1170.0


def test_income_expense_filtra_per_categoria(client, auth_headers, scenario):
    r = client.get(
        f"/charts/income-expense?{_range(scenario)}&categoria_id={scenario['casa']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    # Solo Casa: la spesa da 250 resta fuori.
    assert _uscite_del_mese(r.json(), scenario["mese"]) == 920.0


def test_income_expense_filtra_per_sottocategoria(client, auth_headers, scenario):
    r = client.get(
        f"/charts/income-expense?{_range(scenario)}"
        f"&categoria_id={scenario['casa']}"
        f"&sottocategoria_id={scenario['sottocategorie']['Bollette']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert _uscite_del_mese(r.json(), scenario["mese"]) == 120.0


def test_savings_filtra_per_tag(client, auth_headers, scenario):
    r = client.get(
        f"/charts/savings?{_range(scenario)}&tag_id={scenario['tag_id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    riga = next(x for x in r.json() if x["label"] == str(scenario["mese"]))
    # Nessuna entrata e solo l'affitto in uscita.
    assert riga["risparmio"] == -800.0


def test_composizione_senza_categoria_sono_le_categorie(client, auth_headers, scenario):
    r = client.get(
        f"/charts/expense-composition?{_range(scenario)}", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert [(x["categoria"], x["totale"]) for x in r.json()] == [
        ("Casa", 920.0),
        ("Spesa", 250.0),
    ]


def test_composizione_con_categoria_scende_alle_sottocategorie(
    client, auth_headers, scenario
):
    """Una fetta sola grande quanto la ciambella non direbbe niente."""
    r = client.get(
        f"/charts/expense-composition?{_range(scenario)}"
        f"&categoria_id={scenario['casa']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert [(x["categoria"], x["totale"]) for x in r.json()] == [
        ("Affitto", 800.0),
        ("Bollette", 120.0),
    ]


def test_category_trend_filtra_per_sottocategoria(client, auth_headers, scenario):
    r = client.get(
        f"/charts/category-trend?{_range(scenario)}"
        f"&categoria_id={scenario['casa']}"
        f"&sottocategoria_id={scenario['sottocategorie']['Affitto']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    riga = next(x for x in r.json() if x["label"] == str(scenario["mese"]))
    assert riga["spesa"] == 800.0


def test_i_filtri_non_aprono_i_dati_di_un_altro(client, scenario):
    """Un id altrui nel filtro non è una scorciatoia per leggere i suoi conti."""
    altri = _registra(client, "luigi")

    r = client.get(
        f"/charts/income-expense?{_range(scenario)}&categoria_id={scenario['casa']}",
        headers=altri,
    )
    assert r.status_code == 200, r.text
    assert _uscite_del_mese(r.json(), scenario["mese"]) == 0.0
