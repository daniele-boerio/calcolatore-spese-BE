"""Esecuzione manuale di una ricorrenza rimasta indietro.

Di norma le ricorrenze le registra lo scheduler notturno. Se non è passato
(macchina spenta, deploy a cavallo di mezzanotte) restano scadute: da
`POST /ricorrenze/{id}/esegui` si sbloccano a mano, senza poter anticipare
niente e senza fare doppioni con il task.
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
from models import Ricorrenza
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
        json={
            "username": "mario",
            "email": "mario@example.it",
            "password": "password123",
        },
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


def crea_ricorrenza(client, auth_headers, conto, giorni_fa: int, **overrides):
    payload = {
        "nome": "Affitto",
        "importo": 650,
        "tipo": "USCITA",
        "frequenza": "MENSILE",
        "prossima_esecuzione": str(date.today() - timedelta(days=giorni_fa)),
        "attiva": True,
        "conto_id": conto["id"],
        **overrides,
    }
    r = client.post("/ricorrenze", json=payload, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_registra_una_ricorrenza_scaduta(client, auth_headers, conto):
    ric = crea_ricorrenza(client, auth_headers, conto, giorni_fa=6)

    r = client.post(f"/ricorrenze/{ric['id']}/esegui", headers=auth_headers)
    assert r.status_code == 200, r.text

    # La transazione esiste e il saldo si è mosso.
    movimenti = client.get("/transazioni", headers=auth_headers).json()
    assert [t["descrizione"] for t in movimenti] == ["Ricorrente: Affitto"]
    assert float(movimenti[0]["importo"]) == 650.0

    conti = client.get("/conti", headers=auth_headers).json()
    assert float(conti[0]["saldo"]) == 350.0


def test_la_prossima_data_parte_da_quella_prevista(client, auth_headers, conto):
    # Registrando in ritardo, la prossima occorrenza non deve slittare: si
    # conta dalla data prevista, altrimenti l'affitto migra di giorno ogni
    # volta che lo scheduler salta una notte.
    prevista = date.today() - timedelta(days=6)
    ric = crea_ricorrenza(client, auth_headers, conto, giorni_fa=6)

    r = client.post(f"/ricorrenze/{ric['id']}/esegui", headers=auth_headers)
    assert r.status_code == 200, r.text

    session = client.session_factory()
    try:
        aggiornata = session.query(Ricorrenza).get(ric["id"])
        assert aggiornata.prossima_esecuzione.month == (prevista.month % 12) + 1
        assert aggiornata.prossima_esecuzione.day == prevista.day
    finally:
        session.close()


def test_non_anticipa_una_ricorrenza_futura(client, auth_headers, conto):
    ric = crea_ricorrenza(client, auth_headers, conto, giorni_fa=-5)

    r = client.post(f"/ricorrenze/{ric['id']}/esegui", headers=auth_headers)
    assert r.status_code == 400, r.text

    assert client.get("/transazioni", headers=auth_headers).json() == []


def test_non_esegue_una_sospesa(client, auth_headers, conto):
    ric = crea_ricorrenza(client, auth_headers, conto, giorni_fa=3, attiva=False)

    r = client.post(f"/ricorrenze/{ric['id']}/esegui", headers=auth_headers)
    assert r.status_code == 400, r.text


def test_rifiuta_se_il_conto_e_stato_eliminato(client, auth_headers, conto):
    ric = crea_ricorrenza(client, auth_headers, conto, giorni_fa=3)

    r = client.delete(f"/conti/{conto['id']}", headers=auth_headers)
    assert r.status_code in (200, 204), r.text

    # È il caso che genera davvero le scadute: il conto è nascosto, e una
    # transazione su un conto nascosto sarebbe un fantasma.
    r = client.post(f"/ricorrenze/{ric['id']}/esegui", headers=auth_headers)
    assert r.status_code == 400, r.text


def test_la_ricorrenza_di_un_altro_utente_non_si_tocca(client, auth_headers, conto):
    ric = crea_ricorrenza(client, auth_headers, conto, giorni_fa=3)

    r = client.post(
        "/register",
        json={
            "username": "luigi",
            "email": "luigi@example.it",
            "password": "password123",
        },
    )
    assert r.status_code == 200, r.text
    altri_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post(f"/ricorrenze/{ric['id']}/esegui", headers=altri_headers)
    assert r.status_code == 404, r.text
