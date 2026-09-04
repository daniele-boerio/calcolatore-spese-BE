"""La foto mensile del patrimonio.

Il saldo dei conti si ricostruirebbe dalle transazioni, il valore dei titoli
no: lo storico degli investimenti tiene le operazioni, non i prezzi giorno per
giorno. Per dire "rispetto al mese scorso" la foto va scattata quando il mese
è ancora quello.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import services
from database import Base, get_db
from main import app
from models import PatrimonioSnapshot
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
    # Il task apre la sessione da sé: gliela facciamo aprire su questo DB.
    monkeypatch.setattr(services, "SessionLocal", TestingSessionLocal)

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


def test_la_serie_parte_vuota(client, auth_headers):
    # Nessuna foto ancora scattata: niente confronto da mostrare, e nessun
    # numero inventato.
    assert client.get("/conti/patrimonio", headers=auth_headers).json() == []


def test_il_job_fotografa_i_conti(client, auth_headers):
    client.post(
        "/conti",
        json={
            "nome": "Principale",
            "saldo": 1500,
            "default": False,
            "ricarica_automatica": False,
        },
        headers=auth_headers,
    )

    services.task_snapshot_patrimonio()

    serie = client.get("/conti/patrimonio", headers=auth_headers).json()
    oggi = date.today()

    assert len(serie) == 1
    assert serie[0]["label"] == f"{oggi.year}-{oggi.month:02d}"
    assert float(serie[0]["conti"]) == 1500.0
    assert float(serie[0]["totale"]) == 1500.0


def test_rigirare_il_job_riscrive_la_stessa_foto(client, auth_headers):
    services.task_snapshot_patrimonio()
    services.task_snapshot_patrimonio()

    session = client.session_factory()
    try:
        # Una foto sola per mese: il job gira ogni notte e non deve accumulare.
        assert session.query(PatrimonioSnapshot).count() == 1
    finally:
        session.close()


def test_la_foto_segue_il_saldo(client, auth_headers):
    conto = client.get("/conti", headers=auth_headers).json()[0]
    services.task_snapshot_patrimonio()

    client.post(
        "/transazioni",
        json={
            "importo": 40,
            "tipo": "USCITA",
            "data": str(date.today()),
            "conto_id": conto["id"],
        },
        headers=auth_headers,
    )
    services.task_snapshot_patrimonio()

    serie = client.get("/conti/patrimonio", headers=auth_headers).json()
    assert float(serie[-1]["conti"]) == -40.0


def test_ogni_utente_vede_solo_le_sue_foto(client, auth_headers):
    r = client.post(
        "/register",
        json={
            "username": "luigi",
            "email": "luigi@example.it",
            "password": "password123",
        },
    )
    altri = {"Authorization": f"Bearer {r.json()['access_token']}"}

    client.post(
        "/conti",
        json={
            "nome": "Suo",
            "saldo": 900,
            "default": False,
            "ricarica_automatica": False,
        },
        headers=altri,
    )

    services.task_snapshot_patrimonio()

    mie = client.get("/conti/patrimonio", headers=auth_headers).json()
    sue = client.get("/conti/patrimonio", headers=altri).json()

    assert float(mie[0]["conti"]) == 0.0
    assert float(sue[0]["conti"]) == 900.0


def test_la_serie_arriva_dal_mese_piu_vecchio(client, auth_headers):
    session = client.session_factory()
    try:
        user_id = session.query(PatrimonioSnapshot).count()  # forza il flush
        del user_id

        from models import User

        me = session.query(User).filter(User.username == "mario").first()

        session.add_all(
            [
                PatrimonioSnapshot(
                    user_id=me.id,
                    anno=2026,
                    mese=7,
                    conti=Decimal("100"),
                    titoli=Decimal("0"),
                ),
                PatrimonioSnapshot(
                    user_id=me.id,
                    anno=2026,
                    mese=8,
                    conti=Decimal("200"),
                    titoli=Decimal("50"),
                ),
            ]
        )
        session.commit()
    finally:
        session.close()

    serie = client.get("/conti/patrimonio", headers=auth_headers).json()

    assert [riga["label"] for riga in serie] == ["2026-07", "2026-08"]
    assert float(serie[1]["totale"]) == 250.0
