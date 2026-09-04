"""Tre numeri che il BE calcola invece di memorizzare.

Il conteggio d'uso di un tag, il saldo del conto subito dopo una transazione e
il mese in cui un debito si chiude al ritmo tenuto finora. Nessuno dei tre è
una colonna: si ricavano ogni volta, così non possono restare indietro
rispetto ai dati da cui dipendono.
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
    # La registrazione apre già il conto virtuale: quello è il conto di lavoro.
    conti = client.get("/conti", headers=auth_headers).json()
    return conti[0]


def movimento(client, headers, conto_id, importo, tipo="USCITA", quando=None, **extra):
    payload = {
        "importo": importo,
        "tipo": tipo,
        "data": str(quando or date.today()),
        "conto_id": conto_id,
        **extra,
    }
    r = client.post("/transazioni", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# --- A5: conteggio d'uso dei tag ----------------------------------------


def test_i_tag_dicono_quante_transazioni_li_usano(client, auth_headers, conto):
    casa = client.post("/tags", json={"nome": "Casa"}, headers=auth_headers).json()
    client.post("/tags", json={"nome": "Vacanza"}, headers=auth_headers)

    movimento(client, auth_headers, conto["id"], 10, tag_id=casa["id"])
    movimento(client, auth_headers, conto["id"], 20, tag_id=casa["id"])

    tags = client.get("/tags", headers=auth_headers).json()
    conteggi = {tag["nome"]: tag["n_transazioni"] for tag in tags}

    assert conteggi == {"Casa": 2, "Vacanza": 0}


# --- A3: saldo dopo una transazione -------------------------------------


def test_il_saldo_dopo_guarda_solo_quello_che_e_successo_prima(
    client, auth_headers, conto
):
    ieri = date.today() - timedelta(days=1)

    prima = movimento(client, auth_headers, conto["id"], 100, quando=ieri)
    movimento(client, auth_headers, conto["id"], 30)

    r = client.get(f"/transazioni/{prima['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text

    # Saldo iniziale 0, meno 100: la spesa di oggi non conta ancora.
    assert float(r.json()["saldo_dopo"]) == -100.0


def test_il_saldo_dopo_conta_anche_i_giri_in_entrata(client, auth_headers, conto):
    altro = client.post(
        "/conti",
        json={
            "nome": "Secondo",
            "saldo": 500,
            "default": False,
            "ricarica_automatica": False,
        },
        headers=auth_headers,
    ).json()

    giro = movimento(
        client,
        auth_headers,
        altro["id"],
        200,
        tipo="RICARICA",
        conto_destinazione_id=conto["id"],
    )

    r = client.get(f"/transazioni/{giro['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    # Il saldo è quello del conto sorgente: 500 − 200.
    assert float(r.json()["saldo_dopo"]) == 300.0


def test_la_transazione_di_un_altro_utente_e_404(client, auth_headers, conto):
    mia = movimento(client, auth_headers, conto["id"], 10)

    r = client.post(
        "/register",
        json={
            "username": "luigi",
            "email": "luigi@example.it",
            "password": "password123",
        },
    )
    altri = {"Authorization": f"Bearer {r.json()['access_token']}"}

    assert client.get(f"/transazioni/{mia['id']}", headers=altri).status_code == 404


# --- A7: fine stimata di un debito --------------------------------------


def creaDebito(client, headers, ammontare, conto_id):
    r = client.post(
        "/debiti",
        json={"nome": "Prestito", "ammontare": ammontare, "conto_id": conto_id},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def paga(client, headers, debito_id, importo, quando):
    r = client.post(
        f"/debiti/{debito_id}/pay",
        json={"importo": importo, "data": str(quando)},
        headers=headers,
    )
    assert r.status_code == 200, r.text


def test_stima_la_fine_dal_ritmo_dei_pagamenti(client, auth_headers, conto):
    debito = creaDebito(client, auth_headers, 1200, conto["id"])

    oggi = date.today()
    paga(client, auth_headers, debito["id"], 100, oggi - timedelta(days=62))
    paga(client, auth_headers, debito["id"], 100, oggi - timedelta(days=31))
    paga(client, auth_headers, debito["id"], 100, oggi)

    debiti = client.get("/debiti", headers=auth_headers).json()
    stima = debiti[0]["fine_stimata"]

    # 300 versati in due mesi = 150 al mese; ne restano 900, cioè sei mesi.
    assert stima is not None
    assert len(stima) == 7 and stima[4] == "-"


def test_niente_stima_con_un_pagamento_solo(client, auth_headers, conto):
    debito = creaDebito(client, auth_headers, 1000, conto["id"])
    paga(client, auth_headers, debito["id"], 100, date.today())

    debiti = client.get("/debiti", headers=auth_headers).json()
    assert debiti[0]["fine_stimata"] is None


def test_niente_stima_su_un_debito_gia_chiuso(client, auth_headers, conto):
    debito = creaDebito(client, auth_headers, 200, conto["id"])

    oggi = date.today()
    paga(client, auth_headers, debito["id"], 100, oggi - timedelta(days=31))
    paga(client, auth_headers, debito["id"], 100, oggi)

    debiti = client.get("/debiti", headers=auth_headers).json()
    assert float(debiti[0]["residuo"]) == 0.0
    assert debiti[0]["fine_stimata"] is None


def test_niente_stima_se_i_pagamenti_stanno_nello_stesso_mese(
    client, auth_headers, conto
):
    debito = creaDebito(client, auth_headers, 1000, conto["id"])

    oggi = date.today()
    # Due pagamenti a un giorno di distanza non dicono un ritmo mensile.
    paga(client, auth_headers, debito["id"], 50, oggi)
    paga(client, auth_headers, debito["id"], 50, oggi)

    debiti = client.get("/debiti", headers=auth_headers).json()
    assert debiti[0]["fine_stimata"] is None
