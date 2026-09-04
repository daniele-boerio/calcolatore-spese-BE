"""Il conto che l'app apre da sé, e i due modi di rimetterci dentro tutto.

Chi apre l'app non deve essere costretto a modellare i propri conti prima di
registrare una spesa: se non ne ha nessuno gliene apriamo uno noi, marcato
`virtuale`. Da lì si può andare in due direzioni — unire tutti i conti in
quello di default (`/conti/consolida`), o portare i movimenti del virtuale su
un conto vero appena creato (`/conti/{id}/assorbi`).
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
from models import Conto, Transazione
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


def registra(client, nome="mario"):
    r = client.post(
        "/register",
        json={
            "username": nome,
            "email": f"{nome}@example.it",
            "password": "password123",
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth_headers(client):
    return registra(client)


def crea_conto(client, headers, nome, saldo):
    r = client.post(
        "/conti",
        json={
            "nome": nome,
            "saldo": saldo,
            "default": False,
            "ricarica_automatica": False,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def spesa(client, headers, conto_id, importo, **extra):
    payload = {
        "importo": importo,
        "tipo": "USCITA",
        "data": str(date.today()),
        "descrizione": f"Spesa {importo}",
        "conto_id": conto_id,
        **extra,
    }
    r = client.post("/transazioni", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# --- Apertura automatica ------------------------------------------------


def test_la_registrazione_apre_gia_il_conto(client, auth_headers):
    conti = client.get("/conti", headers=auth_headers).json()

    assert len(conti) == 1
    assert conti[0]["virtuale"] is True
    assert conti[0]["default"] is True
    assert float(conti[0]["saldo"]) == 0.0


def test_si_puo_registrare_una_spesa_senza_aver_creato_conti(client, auth_headers):
    conti = client.get("/conti", headers=auth_headers).json()

    # È il vicolo cieco che questo lavoro chiude: prima qui non c'era nessun
    # conto da passare e il POST falliva.
    spesa(client, auth_headers, conti[0]["id"], 12.5)

    assert client.get("/transazioni", headers=auth_headers).json() != []


def test_chi_ha_gia_un_conto_non_ne_riceve_un_altro(client, auth_headers):
    crea_conto(client, auth_headers, "Principale", 100)

    conti = client.get("/conti", headers=auth_headers).json()
    conti = client.get("/conti", headers=auth_headers).json()

    # Due chiamate: la creazione pigra non deve moltiplicare i conti.
    assert len(conti) == 2


# --- Consolidamento -----------------------------------------------------


def test_consolida_sposta_movimenti_e_somma_i_saldi(client, auth_headers):
    virtuale = client.get("/conti", headers=auth_headers).json()[0]
    altro = crea_conto(client, auth_headers, "Prepagata", 300)

    spesa(client, auth_headers, virtuale["id"], 10)
    spesa(client, auth_headers, altro["id"], 40)

    r = client.post("/conti/consolida", headers=auth_headers)
    assert r.status_code == 200, r.text

    conti = client.get("/conti", headers=auth_headers).json()
    assert len(conti) == 1
    assert conti[0]["id"] == virtuale["id"]
    # 0 − 10 + (300 − 40) = 250
    assert float(conti[0]["saldo"]) == 250.0

    movimenti = client.get("/transazioni", headers=auth_headers).json()
    assert len(movimenti) == 2
    assert {m["conto_id"] for m in movimenti} == {virtuale["id"]}


def test_consolida_toglie_la_destinazione_ai_giri_interni(client, auth_headers):
    virtuale = client.get("/conti", headers=auth_headers).json()[0]
    altro = crea_conto(client, auth_headers, "Salvadanaio", 0)

    r = client.post(
        "/transazioni",
        json={
            "importo": 50,
            "tipo": "RICARICA",
            "data": str(date.today()),
            "conto_id": virtuale["id"],
            "conto_destinazione_id": altro["id"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    assert client.post("/conti/consolida", headers=auth_headers).status_code == 200

    # I due estremi sono diventati lo stesso conto: la riga resta, il giro no.
    giro = client.get("/transazioni", headers=auth_headers).json()[0]
    assert giro["conto_id"] == virtuale["id"]
    assert giro["conto_destinazione_id"] is None


def test_consolida_e_idempotente(client, auth_headers):
    crea_conto(client, auth_headers, "Prepagata", 200)

    assert client.post("/conti/consolida", headers=auth_headers).status_code == 200
    saldo = client.get("/conti", headers=auth_headers).json()[0]["saldo"]

    # Secondo giro a vuoto: il saldo non deve raddoppiare.
    assert client.post("/conti/consolida", headers=auth_headers).status_code == 200
    conti = client.get("/conti", headers=auth_headers).json()

    assert len(conti) == 1
    assert conti[0]["saldo"] == saldo


def test_consolida_sposta_anche_le_transazioni_nascoste(client, auth_headers):
    virtuale = client.get("/conti", headers=auth_headers).json()[0]
    altro = crea_conto(client, auth_headers, "Prepagata", 0)
    movimento = spesa(client, auth_headers, altro["id"], 15)

    # Un conto cancellato nasconde le sue transazioni: se il consolidamento le
    # saltasse, un domani il restore le riporterebbe su un conto che non c'è.
    session = client.session_factory()
    try:
        riga = session.query(Transazione).get(int(movimento["id"]))
        riga.deleted_at = date.today()
        session.commit()
    finally:
        session.close()

    assert client.post("/conti/consolida", headers=auth_headers).status_code == 200

    session = client.session_factory()
    try:
        riga = session.query(Transazione).get(int(movimento["id"]))
        assert riga.conto_id == int(virtuale["id"])
    finally:
        session.close()


def test_consolida_non_tocca_i_conti_di_un_altro_utente(client, auth_headers):
    altri_headers = registra(client, "luigi")
    suo = crea_conto(client, altri_headers, "Suo", 500)

    crea_conto(client, auth_headers, "Mio", 100)
    assert client.post("/conti/consolida", headers=auth_headers).status_code == 200

    conti_altrui = client.get("/conti", headers=altri_headers).json()
    assert {c["id"] for c in conti_altrui} >= {suo["id"]}
    assert float(next(c for c in conti_altrui if c["id"] == suo["id"])["saldo"]) == 500.0


# --- Assorbimento del virtuale ------------------------------------------


def test_assorbi_porta_i_movimenti_sul_conto_vero(client, auth_headers):
    virtuale = client.get("/conti", headers=auth_headers).json()[0]
    spesa(client, auth_headers, virtuale["id"], 20)

    vero = crea_conto(client, auth_headers, "Principale", 1000)

    r = client.post(f"/conti/{vero['id']}/assorbi", headers=auth_headers)
    assert r.status_code == 200, r.text

    conti = client.get("/conti", headers=auth_headers).json()
    assert [c["id"] for c in conti] == [vero["id"]]
    # 1000 + (0 − 20)
    assert float(conti[0]["saldo"]) == 980.0

    movimenti = client.get("/transazioni", headers=auth_headers).json()
    assert {m["conto_id"] for m in movimenti} == {vero["id"]}


def test_il_virtuale_non_puo_assorbire_se_stesso(client, auth_headers):
    virtuale = client.get("/conti", headers=auth_headers).json()[0]

    r = client.post(f"/conti/{virtuale['id']}/assorbi", headers=auth_headers)
    assert r.status_code == 400, r.text


def test_assorbi_senza_virtuale_non_fa_niente(client, auth_headers):
    vero = crea_conto(client, auth_headers, "Principale", 100)
    primo = client.post(f"/conti/{vero['id']}/assorbi", headers=auth_headers)
    assert primo.status_code == 200, primo.text

    # Il virtuale c'era: dopo il primo assorbimento non c'è più, e il secondo
    # giro non deve travasare niente una seconda volta.
    r = client.post(f"/conti/{vero['id']}/assorbi", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert float(r.json()["saldo"]) == 100.0


def test_assorbi_su_un_conto_di_un_altro_utente_e_404(client, auth_headers):
    altri_headers = registra(client, "luigi")
    suo = crea_conto(client, altri_headers, "Suo", 10)

    r = client.post(f"/conti/{suo['id']}/assorbi", headers=auth_headers)
    assert r.status_code == 404, r.text


def test_il_conto_virtuale_e_marcato_solo_quando_lo_apre_lapp(client, auth_headers):
    creato = crea_conto(client, auth_headers, "Principale", 0)

    assert creato["virtuale"] is False

    session = client.session_factory()
    try:
        virtuali = session.query(Conto).filter(Conto.virtuale.is_(True)).all()
        assert len(virtuali) == 1
    finally:
        session.close()


# --- Rinuncia ai conti --------------------------------------------------


def test_rinuncia_porta_tutto_sul_conto_invisibile(client, auth_headers):
    """Il verso opposto di `assorbi`: i movimenti tornano a non avere un conto."""
    vero = crea_conto(client, auth_headers, "Principale", 1000)
    client.post(f"/conti/{vero['id']}/assorbi", headers=auth_headers)
    prepagata = crea_conto(client, auth_headers, "Prepagata", 300)

    spesa(client, auth_headers, vero["id"], 10)
    spesa(client, auth_headers, prepagata["id"], 40)

    r = client.post("/conti/rinuncia", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["virtuale"] is True

    conti = client.get("/conti", headers=auth_headers).json()
    assert len(conti) == 1
    assert conti[0]["virtuale"] is True
    assert conti[0]["default"] is True
    # 1000 − 10 + (300 − 40): il patrimonio non cambia, cambia solo dove sta.
    assert float(conti[0]["saldo"]) == 1250.0

    # Ed è questo il punto: i movimenti restano tutti visibili.
    movimenti = client.get("/transazioni", headers=auth_headers).json()
    assert len(movimenti) == 2
    assert {m["conto_id"] for m in movimenti} == {conti[0]["id"]}


def test_rinuncia_apre_il_conto_invisibile_se_non_c_e_piu(client, auth_headers):
    """Dopo un `assorbi` il virtuale non esiste: va riaperto, non cercato invano."""
    vero = crea_conto(client, auth_headers, "Principale", 50)
    client.post(f"/conti/{vero['id']}/assorbi", headers=auth_headers)
    spesa(client, auth_headers, vero["id"], 5)

    conti = client.get("/conti", headers=auth_headers).json()
    assert [c["virtuale"] for c in conti] == [False]

    r = client.post("/conti/rinuncia", headers=auth_headers)
    assert r.status_code == 200, r.text

    conti = client.get("/conti", headers=auth_headers).json()
    assert len(conti) == 1
    assert conti[0]["virtuale"] is True
    assert float(conti[0]["saldo"]) == 45.0

    movimento = client.get("/transazioni", headers=auth_headers).json()[0]
    assert movimento["conto_id"] == conti[0]["id"]


def test_rinuncia_e_idempotente(client, auth_headers):
    crea_conto(client, auth_headers, "Principale", 200)

    assert client.post("/conti/rinuncia", headers=auth_headers).status_code == 200
    saldo = client.get("/conti", headers=auth_headers).json()[0]["saldo"]

    # Secondo giro a vuoto: il saldo non deve raddoppiare.
    assert client.post("/conti/rinuncia", headers=auth_headers).status_code == 200
    conti = client.get("/conti", headers=auth_headers).json()

    assert len(conti) == 1
    assert conti[0]["saldo"] == saldo


def test_rinuncia_sposta_anche_le_transazioni_nascoste(client, auth_headers):
    vero = crea_conto(client, auth_headers, "Principale", 0)
    movimento = spesa(client, auth_headers, vero["id"], 15)

    session = client.session_factory()
    try:
        riga = session.query(Transazione).get(int(movimento["id"]))
        riga.deleted_at = date.today()
        session.commit()
    finally:
        session.close()

    assert client.post("/conti/rinuncia", headers=auth_headers).status_code == 200

    virtuale = client.get("/conti", headers=auth_headers).json()[0]
    session = client.session_factory()
    try:
        riga = session.query(Transazione).get(int(movimento["id"]))
        # Se un domani viene ripristinata non deve appendersi a un conto sparito.
        assert riga.conto_id == int(virtuale["id"])
    finally:
        session.close()


def test_rinuncia_non_tocca_i_conti_di_un_altro_utente(client, auth_headers):
    altri_headers = registra(client, "luigi")
    suo = crea_conto(client, altri_headers, "Suo", 500)

    crea_conto(client, auth_headers, "Mio", 100)
    assert client.post("/conti/rinuncia", headers=auth_headers).status_code == 200

    conti_altrui = client.get("/conti", headers=altri_headers).json()
    assert float(next(c for c in conti_altrui if c["id"] == suo["id"])["saldo"]) == 500.0
