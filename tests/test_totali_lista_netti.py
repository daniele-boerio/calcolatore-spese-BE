"""I totali della lista paginata sono al netto dei rimborsi, come tutti gli altri.

`importo_effettivo` è dichiarata in services.py "UNICA fonte di verità per tutti
gli aggregati", e budget, statistiche e grafici la rispettano. I totali di
`/transazioni/paginated` no: sommavano il lordo. Una spesa da 100 rimborsata di
30 risultava così "100" in cima ai Movimenti e "70" sulla Home — lo stesso mese,
due cifre diverse sotto la stessa parola, e nessuna delle due sbagliata di per
sé.

Il rimborso vive due volte: come riga sua e come sconto sul netto del padre. Un
totale che lo somma da entrambe le parti lo conta due volte, ed è il motivo per
cui `total_rimborsi` resta un'informazione e non un addendo del saldo.
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


def _registra(client, username, email):
    r = client.post(
        "/register",
        json={"username": username, "email": email, "password": "password123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _crea_conto(client, headers):
    r = client.post(
        "/conti",
        json={
            "nome": "Principale",
            "saldo": 1000,
            "default": True,
            "ricarica_automatica": False,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def utente(client):
    headers = _registra(client, "mario", "mario@example.it")
    return headers, _crea_conto(client, headers)


def _crea_transazione(client, headers, conto, **overrides):
    payload = {
        "importo": 100,
        "tipo": "USCITA",
        "data": str(date.today()),
        "descrizione": "Spesa",
        "conto_id": conto["id"],
    }
    payload.update(overrides)
    r = client.post("/transazioni", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _totali(client, headers, query=""):
    r = client.get(f"/transazioni/paginated?page=1&size=50{query}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    return (
        float(body["total_entrata"]),
        float(body["total_uscita"]),
        float(body["total_rimborsi"]),
    )


def test_le_uscite_sono_al_netto_del_rimborso(client, utente):
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)
    _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    _entrate, uscite, rimborsi = _totali(client, headers)

    assert uscite == 70
    # Il rimborso resta leggibile a parte: è quanto è tornato indietro.
    assert rimborsi == 30


def test_senza_rimborsi_il_netto_coincide_col_lordo(client, utente):
    headers, conto = utente
    _crea_transazione(client, headers, conto, importo=100)
    _crea_transazione(client, headers, conto, importo=40)

    _entrate, uscite, rimborsi = _totali(client, headers)

    assert uscite == 140
    assert rimborsi == 0


def test_le_entrate_non_le_tocca_nessun_rimborso(client, utente):
    headers, conto = utente
    _crea_transazione(client, headers, conto, importo=500, tipo="ENTRATA")
    padre = _crea_transazione(client, headers, conto, importo=100)
    _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    entrate, uscite, _rimborsi = _totali(client, headers)

    assert entrate == 500
    # Il saldo che il FE scrive in testa alla lista: entrate meno uscite, senza
    # rimettere il rimborso, che sta già dentro alle uscite.
    assert entrate - uscite == 430


def test_il_filtro_per_tipo_vede_lo_stesso_netto_della_home(client, utente):
    # È il link che la Home apre toccando "Uscite": deve mostrare la stessa
    # cifra che l'utente ha appena letto sulla card.
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)
    _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    _entrate, uscite, _rimborsi = _totali(client, headers, "&tipo=USCITA")

    budget = client.get("/conti/currentMonthExpenses", headers=headers)
    assert budget.status_code == 200, budget.text

    assert uscite == float(budget.json()["spending"]["spent"])
