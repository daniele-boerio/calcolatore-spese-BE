"""Ricorrenze: recupero degli arretrati, fine, rate, importo variabile, debiti.

Lo scheduler notturno registra ogni occorrenza scaduta con la sua data
prevista; le ricorrenze possono finire (data o numero di rate), aspettare
l'importo vero (bollette) o pagare un debito.
"""

from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from models import Ricorrenza
from services import task_transazioni_ricorrenti


def _conto(api, headers, saldo=1000):
    r = api.post(
        "/conti",
        json={"nome": "Principale", "saldo": saldo, "default": True},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _ricorrenza(api, headers, conto, prossima: date, **overrides):
    payload = {
        "nome": "Affitto",
        "importo": 100,
        "tipo": "USCITA",
        "frequenza": "MENSILE",
        "prossima_esecuzione": str(prossima),
        "attiva": True,
        "conto_id": conto["id"],
        **overrides,
    }
    r = api.post("/ricorrenze", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _movimenti(api, headers):
    return api.get("/transazioni", headers=headers).json()


def _saldo(api, headers):
    return Decimal(api.get("/conti", headers=headers).json()[0]["saldo"])


def _ricorrenza_db(api, ric_id):
    session = api.session_factory()
    try:
        return session.query(Ricorrenza).get(ric_id)
    finally:
        session.close()


def test_il_task_usa_la_data_prevista_non_quella_di_oggi(api):
    headers = api.registra()
    conto = _conto(api, headers)
    prevista = date.today() - timedelta(days=3)
    _ricorrenza(api, headers, conto, prevista, frequenza="ANNUALE")

    task_transazioni_ricorrenti()

    [movimento] = _movimenti(api, headers)
    assert movimento["data"] == str(prevista)


def test_il_task_recupera_tutte_le_occorrenze_arretrate(api):
    # Server spento per tre mesi: al risveglio le rate sono tre, ognuna nel
    # suo mese, non una per notte.
    headers = api.registra()
    conto = _conto(api, headers)
    prima = date.today() - relativedelta(months=2) - timedelta(days=1)
    ric = _ricorrenza(api, headers, conto, prima)

    task_transazioni_ricorrenti()

    date_registrate = sorted(m["data"] for m in _movimenti(api, headers))
    assert date_registrate == [
        str(prima),
        str(prima + relativedelta(months=1)),
        str(prima + relativedelta(months=2)),
    ]
    assert _saldo(api, headers) == Decimal("700.00")
    assert _ricorrenza_db(api, ric["id"]).prossima_esecuzione > date.today()


def test_lanciare_il_task_due_volte_non_duplica(api):
    headers = api.registra()
    conto = _conto(api, headers)
    _ricorrenza(api, headers, conto, date.today())

    task_transazioni_ricorrenti()
    task_transazioni_ricorrenti()

    assert len(_movimenti(api, headers)) == 1


def test_una_ricorrenza_di_rimborso_alza_il_saldo(api):
    # Stessa regola dei movimenti inseriti a mano: prima la ricorrenza
    # sottraeva tutto quello che non era un'entrata.
    headers = api.registra()
    conto = _conto(api, headers)
    _ricorrenza(api, headers, conto, date.today(), tipo="RIMBORSO", nome="Rimborso")

    task_transazioni_ricorrenti()

    assert _saldo(api, headers) == Decimal("1100.00")


def test_le_rate_finiscono_e_la_ricorrenza_si_sospende(api):
    headers = api.registra()
    conto = _conto(api, headers)
    prima = date.today() - relativedelta(months=4)
    ric = _ricorrenza(api, headers, conto, prima, rate_rimanenti=2)

    task_transazioni_ricorrenti()

    assert len(_movimenti(api, headers)) == 2
    salvata = _ricorrenza_db(api, ric["id"])
    assert salvata.rate_rimanenti == 0
    assert salvata.attiva is False


def test_dopo_la_data_di_fine_non_scatta_piu(api):
    headers = api.registra()
    conto = _conto(api, headers)
    prima = date.today() - relativedelta(months=3)
    ric = _ricorrenza(
        api,
        headers,
        conto,
        prima,
        data_fine=str(prima + relativedelta(months=1)),
    )

    task_transazioni_ricorrenti()

    assert len(_movimenti(api, headers)) == 2
    assert _ricorrenza_db(api, ric["id"]).attiva is False


def test_la_data_di_fine_non_puo_precedere_la_prossima(api):
    headers = api.registra()
    conto = _conto(api, headers)
    r = api.post(
        "/ricorrenze",
        json={
            "nome": "X",
            "importo": 10,
            "tipo": "USCITA",
            "frequenza": "MENSILE",
            "prossima_esecuzione": str(date.today()),
            "data_fine": str(date.today() - timedelta(days=1)),
            "conto_id": conto["id"],
        },
        headers=headers,
    )
    assert r.status_code == 400


def test_importo_variabile_aspetta_l_importo_vero(api):
    headers = api.registra()
    conto = _conto(api, headers)
    ric = _ricorrenza(
        api, headers, conto, date.today(), nome="Luce", importo_variabile=True
    )

    task_transazioni_ricorrenti()
    assert _movimenti(api, headers) == []

    senza = api.post(f"/ricorrenze/{ric['id']}/esegui", headers=headers)
    assert senza.status_code == 400

    con = api.post(
        f"/ricorrenze/{ric['id']}/esegui",
        json={"importo": "87.40"},
        headers=headers,
    )
    assert con.status_code == 200, con.text

    [movimento] = _movimenti(api, headers)
    assert Decimal(movimento["importo"]) == Decimal("87.40")
    assert _saldo(api, headers) == Decimal("912.60")


def test_la_rata_di_un_debito_ne_scala_il_residuo_e_si_ferma_a_zero(api):
    headers = api.registra()
    conto = _conto(api, headers)
    debito = api.post(
        "/debiti",
        json={"nome": "Prestito", "ammontare": 250, "residuo": 250},
        headers=headers,
    ).json()
    prima = date.today() - relativedelta(months=5)
    ric = _ricorrenza(
        api, headers, conto, prima, nome="Rata", debito_id=debito["id"]
    )

    task_transazioni_ricorrenti()

    # 100 + 100 + 50: la terza rata chiude il debito, poi stop
    movimenti = _movimenti(api, headers)
    assert len(movimenti) == 3
    assert all(m["debito_id"] == debito["id"] for m in movimenti)
    [salvato] = api.get("/debiti", headers=headers).json()
    assert Decimal(salvato["residuo"]) == Decimal("0.00")
    assert _ricorrenza_db(api, ric["id"]).attiva is False


def test_la_fine_del_debito_segue_il_piano_della_rata(api):
    headers = api.registra()
    conto = _conto(api, headers)
    debito = api.post(
        "/debiti",
        json={"nome": "Auto", "ammontare": 1000, "residuo": 1000},
        headers=headers,
    ).json()
    prossima = date.today() + timedelta(days=5)
    ric = _ricorrenza(
        api, headers, conto, prossima, importo=250, debito_id=debito["id"]
    )

    [salvato] = api.get("/debiti", headers=headers).json()
    ultima = prossima + relativedelta(months=3)  # 4 rate da 250
    assert salvato["fine_stimata"] == f"{ultima.year}-{ultima.month:02d}"
    assert salvato["ricorrenza_id"] == ric["id"]


def test_non_si_aggancia_il_debito_o_la_categoria_di_un_altro(api):
    mario = api.registra("mario")
    luigi = api.registra("luigi")
    conto = _conto(api, mario)

    debito_altrui = api.post(
        "/debiti", json={"nome": "Suo", "ammontare": 10}, headers=luigi
    ).json()
    categoria_altrui = api.post(
        "/categorie", json={"nome": "Sua"}, headers=luigi
    ).json()

    for campo, valore in (
        ("debito_id", debito_altrui["id"]),
        ("categoria_id", categoria_altrui["id"]),
    ):
        r = api.post(
            "/ricorrenze",
            json={
                "nome": "X",
                "importo": 10,
                "tipo": "USCITA",
                "frequenza": "MENSILE",
                "prossima_esecuzione": str(date.today()),
                "conto_id": conto["id"],
                campo: valore,
            },
            headers=mario,
        )
        assert r.status_code == 400, (campo, r.text)
