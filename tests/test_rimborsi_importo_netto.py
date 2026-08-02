"""`importo_netto` del padre attraverso tutto il ciclo di vita di un rimborso.

`importo_netto` è la spesa reale di una transazione dopo i rimborsi ricevuti, ed
è ciò che alimenta budget, statistiche e grafici. Se va alla deriva, ogni totale
dell'app va alla deriva con lui — in silenzio, perché nessuna schermata mostra
il netto accanto al lordo.

La vecchia implementazione applicava al padre solo la *differenza* di importo del
rimborso. Regge finché `tipo` e `parent_transaction_id` non cambiano; qui
copriamo anche i casi in cui cambiano, più lo scoping per utente.
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


def _crea_conto(client, headers, nome="Principale", saldo=1000):
    r = client.post(
        "/conti",
        json={
            "nome": nome,
            "saldo": saldo,
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


def _netto(client, transazione_id):
    db = client.session_factory()
    try:
        return db.get(models.Transazione, transazione_id).importo_netto
    finally:
        db.close()


def _saldo(client, conto_id):
    db = client.session_factory()
    try:
        return db.get(models.Conto, conto_id).saldo
    finally:
        db.close()


# --- creazione ---------------------------------------------------------------


def test_creare_un_rimborso_scala_il_netto_del_padre(client, utente):
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)

    _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    assert _netto(client, padre["id"]) == 70


def test_piu_rimborsi_si_sommano_sul_padre(client, utente):
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)

    for importo in (30, 20, 10):
        _crea_transazione(
            client, headers, conto,
            importo=importo, tipo="RIMBORSO", parent_transaction_id=padre["id"],
        )

    assert _netto(client, padre["id"]) == 40


def test_rimborso_su_padre_con_netto_null_parte_dal_lordo(client, utente):
    """Le righe pre-migration hanno netto NULL: il primo rimborso non deve esplodere."""
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)

    db = client.session_factory()
    try:
        db.get(models.Transazione, padre["id"]).importo_netto = None
        db.commit()
    finally:
        db.close()

    _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    assert _netto(client, padre["id"]) == 70


# --- modifica ----------------------------------------------------------------


def test_modificare_l_importo_del_rimborso_riallinea_il_padre(client, utente):
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)
    rimborso = _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    r = client.put(
        f"/transazioni/{rimborso['id']}",
        json={"importo": 50, "tipo": "RIMBORSO", "conto_id": conto["id"],
              "parent_transaction_id": padre["id"], "data": str(date.today())},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    assert _netto(client, padre["id"]) == 50


def test_rimborso_che_diventa_uscita_restituisce_il_netto_al_padre(client, utente):
    """Il caso che andava alla deriva: il padre restava scontato per sempre."""
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)
    rimborso = _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )
    assert _netto(client, padre["id"]) == 70

    r = client.put(
        f"/transazioni/{rimborso['id']}",
        json={"importo": 30, "tipo": "USCITA", "conto_id": conto["id"],
              "data": str(date.today())},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # Il rimborso non esiste più: il padre torna a valere il suo lordo
    assert _netto(client, padre["id"]) == 100


def test_uscita_che_diventa_rimborso_scala_l_intero_importo(client, utente):
    """Simmetrico del precedente: va scontato tutto, non la sola differenza."""
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)
    altra = _crea_transazione(client, headers, conto, importo=40)

    r = client.put(
        f"/transazioni/{altra['id']}",
        json={"importo": 40, "tipo": "RIMBORSO", "conto_id": conto["id"],
              "parent_transaction_id": padre["id"], "data": str(date.today())},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    assert _netto(client, padre["id"]) == 60


def test_spostare_un_rimborso_su_un_altro_padre(client, utente):
    """Il vecchio padre va ripristinato, il nuovo scontato per intero."""
    headers, conto = utente
    padre_a = _crea_transazione(client, headers, conto, importo=100)
    padre_b = _crea_transazione(client, headers, conto, importo=200)
    rimborso = _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre_a["id"],
    )
    assert _netto(client, padre_a["id"]) == 70

    r = client.put(
        f"/transazioni/{rimborso['id']}",
        json={"importo": 30, "tipo": "RIMBORSO", "conto_id": conto["id"],
              "parent_transaction_id": padre_b["id"], "data": str(date.today())},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    assert _netto(client, padre_a["id"]) == 100
    assert _netto(client, padre_b["id"]) == 170


def test_spostare_un_rimborso_cambiandone_anche_l_importo(client, utente):
    headers, conto = utente
    padre_a = _crea_transazione(client, headers, conto, importo=100)
    padre_b = _crea_transazione(client, headers, conto, importo=200)
    rimborso = _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre_a["id"],
    )

    r = client.put(
        f"/transazioni/{rimborso['id']}",
        json={"importo": 75, "tipo": "RIMBORSO", "conto_id": conto["id"],
              "parent_transaction_id": padre_b["id"], "data": str(date.today())},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    assert _netto(client, padre_a["id"]) == 100
    assert _netto(client, padre_b["id"]) == 125


def test_modificare_il_padre_conserva_lo_sconto_dei_rimborsi(client, utente):
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)
    _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    r = client.put(
        f"/transazioni/{padre['id']}",
        json={"importo": 150, "tipo": "USCITA", "conto_id": conto["id"],
              "data": str(date.today())},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # 150 di lordo meno i 30 già rimborsati
    assert _netto(client, padre["id"]) == 120


def test_una_transazione_non_puo_essere_padre_di_se_stessa(client, utente):
    headers, conto = utente
    trans = _crea_transazione(client, headers, conto, importo=100)

    r = client.put(
        f"/transazioni/{trans['id']}",
        json={"importo": 100, "tipo": "RIMBORSO", "conto_id": conto["id"],
              "parent_transaction_id": trans["id"], "data": str(date.today())},
        headers=headers,
    )

    assert r.status_code == 400
    assert _netto(client, trans["id"]) == 100


# --- cancellazione -----------------------------------------------------------


def test_cancellare_il_rimborso_ripristina_il_netto_del_padre(client, utente):
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)
    rimborso = _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    r = client.delete(f"/transazioni/{rimborso['id']}", headers=headers)
    assert r.status_code == 200, r.text

    assert _netto(client, padre["id"]) == 100


def test_cancellare_il_padre_porta_via_i_rimborsi_e_lascia_il_saldo_giusto(
    client, utente
):
    headers, conto = utente
    saldo_iniziale = _saldo(client, conto["id"])

    padre = _crea_transazione(client, headers, conto, importo=100)
    _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    r = client.delete(f"/transazioni/{padre['id']}", headers=headers)
    assert r.status_code == 200, r.text

    db = client.session_factory()
    try:
        assert db.query(models.Transazione).count() == 0
    finally:
        db.close()
    assert _saldo(client, conto["id"]) == saldo_iniziale


# --- coerenza con i totali esposti -------------------------------------------


def test_il_ciclo_completo_lascia_i_totali_del_mese_coerenti(client, utente):
    """Create -> update -> delete: alla fine budget e statistiche devono tornare."""
    headers, conto = utente
    padre = _crea_transazione(client, headers, conto, importo=100)
    rimborso = _crea_transazione(
        client, headers, conto,
        importo=30, tipo="RIMBORSO", parent_transaction_id=padre["id"],
    )

    client.put(
        f"/transazioni/{rimborso['id']}",
        json={"importo": 60, "tipo": "RIMBORSO", "conto_id": conto["id"],
              "parent_transaction_id": padre["id"], "data": str(date.today())},
        headers=headers,
    )
    client.delete(f"/transazioni/{rimborso['id']}", headers=headers)

    today = date.today()
    budget = client.get("/conti/currentMonthExpenses", headers=headers).json()
    stats = client.get(
        f"/statistics/monthDetails?year={today.year}&month={today.month}",
        headers=headers,
    ).json()
    pie = client.get("/conti/expensesByCategory", headers=headers).json()

    assert _netto(client, padre["id"]) == 100
    assert float(budget["monthly_budget"]["remaining"]) == -100.0
    assert stats["totale_uscita"] == -100.0
    assert sum(item["value"] for item in pie) == 100.0


# --- isolamento fra utenti ---------------------------------------------------


def test_non_si_puo_toccare_il_netto_della_transazione_di_un_altro_utente(client):
    """Le query sul padre erano senza filtro utente: bastava passarne l'id."""
    headers_a = _registra(client, "anna", "anna@example.it")
    conto_a = _crea_conto(client, headers_a, nome="Conto A")
    vittima = _crea_transazione(client, headers_a, conto_a, importo=100)

    headers_b = _registra(client, "bruno", "bruno@example.it")
    conto_b = _crea_conto(client, headers_b, nome="Conto B")

    # B prova a creare un rimborso agganciato alla transazione di A
    r = client.post(
        "/transazioni",
        json={"importo": 30, "tipo": "RIMBORSO", "data": str(date.today()),
              "descrizione": "Furto", "conto_id": conto_b["id"],
              "parent_transaction_id": vittima["id"]},
        headers=headers_b,
    )
    assert r.status_code == 400

    # ...e ci riprova via PUT su una propria transazione
    propria = _crea_transazione(client, headers_b, conto_b, importo=30)
    client.put(
        f"/transazioni/{propria['id']}",
        json={"importo": 30, "tipo": "RIMBORSO", "conto_id": conto_b["id"],
              "parent_transaction_id": vittima["id"], "data": str(date.today())},
        headers=headers_b,
    )

    assert _netto(client, vittima["id"]) == 100


def test_cancellare_non_intacca_il_netto_altrui(client):
    headers_a = _registra(client, "anna", "anna@example.it")
    conto_a = _crea_conto(client, headers_a, nome="Conto A")
    vittima = _crea_transazione(client, headers_a, conto_a, importo=100)

    headers_b = _registra(client, "bruno", "bruno@example.it")
    conto_b = _crea_conto(client, headers_b, nome="Conto B")
    propria = _crea_transazione(client, headers_b, conto_b, importo=30)

    # Aggancio forzato a DB, come se il PUT fosse riuscito a scriverlo
    db = client.session_factory()
    try:
        riga = db.get(models.Transazione, propria["id"])
        riga.tipo = "RIMBORSO"
        riga.parent_transaction_id = vittima["id"]
        db.commit()
    finally:
        db.close()

    r = client.delete(f"/transazioni/{propria['id']}", headers=headers_b)
    assert r.status_code == 200, r.text

    assert _netto(client, vittima["id"]) == 100
