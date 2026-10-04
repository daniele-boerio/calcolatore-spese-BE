"""Saldi che tornano con i movimenti, e POST ripetute che non duplicano.

La verifica dei saldi confronta la "base" di ogni conto (saldo meno l'effetto
dei movimenti attivi) con quella fotografata: un'operazione sui movimenti non
deve mai spostarla. Il test più importante qui è quello che passa da tutti i
percorsi che muovono un saldo e controlla che alla fine la verifica sia vuota.
"""

from datetime import date, timedelta
from decimal import Decimal

from models import Conto
from services import task_ricarica_automatica_conti, task_transazioni_ricorrenti


def _conto(api, headers, nome="Principale", saldo=1000, **extra):
    r = api.post(
        "/conti",
        json={"nome": nome, "saldo": saldo, **extra},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _tx(api, headers, conto, idempotency_key=None, **overrides):
    payload = {
        "importo": 50,
        "tipo": "USCITA",
        "data": str(date.today()),
        "conto_id": conto["id"],
        **overrides,
    }
    extra = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
    r = api.post("/transazioni", json=payload, headers={**headers, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _saldi(api, headers):
    return {
        c["id"]: Decimal(c["saldo"])
        for c in api.get("/conti", headers=headers).json()
        if c.get("deleted_at") is None
    }


def _verifica(api, headers):
    r = api.get("/conti/verifica-saldi", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# --- Idempotenza --------------------------------------------------------------


def test_la_stessa_chiave_non_crea_un_doppione(api):
    headers = api.registra()
    conto = _conto(api, headers)

    prima = _tx(api, headers, conto, idempotency_key="abc-123")
    seconda = _tx(api, headers, conto, idempotency_key="abc-123")

    assert prima["id"] == seconda["id"]
    assert len(api.get("/transazioni", headers=headers).json()) == 1
    # Il saldo si è mosso una volta sola
    assert _saldi(api, headers)[conto["id"]] == Decimal("950.00")


def test_chiavi_diverse_creano_transazioni_diverse(api):
    headers = api.registra()
    conto = _conto(api, headers)

    _tx(api, headers, conto, idempotency_key="uno")
    _tx(api, headers, conto, idempotency_key="due")
    _tx(api, headers, conto)  # senza chiave: comportamento di sempre

    assert len(api.get("/transazioni", headers=headers).json()) == 3


def test_la_chiave_e_per_utente(api):
    mario = api.registra("mario")
    luigi = api.registra("luigi")

    tx_mario = _tx(api, mario, _conto(api, mario), idempotency_key="stessa")
    tx_luigi = _tx(api, luigi, _conto(api, luigi), idempotency_key="stessa")

    assert tx_mario["id"] != tx_luigi["id"]


# --- Verifica dei saldi ---------------------------------------------------------


def test_ogni_percorso_che_muove_un_saldo_lascia_la_verifica_pulita(api):
    headers = api.registra()
    a = _conto(api, headers, "A", 1000)
    b = _conto(api, headers, "B", 200)
    _verifica(api, headers)  # fotografa il punto di partenza

    uscita = _tx(api, headers, a, importo=120)
    _tx(api, headers, a, importo=300, tipo="ENTRATA")
    _tx(api, headers, a, importo=40, tipo="RIMBORSO", parent_transaction_id=uscita["id"])
    _tx(api, headers, a, importo=70, tipo="RICARICA", conto_destinazione_id=b["id"])
    _tx(api, headers, a, importo=25, tipo="ACCANTONAMENTO", conto_destinazione_id=b["id"])
    _tx(api, headers, b, importo=15, tipo="ACCANTONAMENTO")

    # Modifiche: importo, tipo, conto
    da_modificare = _tx(api, headers, a, importo=10)
    r = api.put(
        f"/transazioni/{da_modificare['id']}",
        json={
            "importo": 33,
            "tipo": "ENTRATA",
            "data": str(date.today()),
            "conto_id": b["id"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # Eliminazioni, anche del padre di un rimborso
    da_eliminare = _tx(api, headers, b, importo=5)
    assert api.delete(f"/transazioni/{da_eliminare['id']}", headers=headers).status_code == 200
    assert api.delete(f"/transazioni/{uscita['id']}", headers=headers).status_code == 200

    # Split
    da_dividere = _tx(api, headers, a, importo=90)
    r = api.post(
        f"/transazioni/{da_dividere['id']}/split",
        json={"parts": [{"importo": 60}, {"importo": 30}]},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # Pagamento di un debito
    debito = api.post(
        "/debiti", json={"nome": "Prestito", "ammontare": 500}, headers=headers
    ).json()
    r = api.post(
        f"/debiti/{debito['id']}/pay",
        json={"importo": 80, "conto_id": a["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # Ricorrenza e ricarica automatica eseguite dallo scheduler
    api.post(
        "/ricorrenze",
        json={
            "nome": "Abbonamento",
            "importo": 9.99,
            "tipo": "USCITA",
            "frequenza": "MENSILE",
            "prossima_esecuzione": str(date.today()),
            "conto_id": a["id"],
        },
        headers=headers,
    )
    task_transazioni_ricorrenti()

    api.put(
        f"/conti/{b['id']}",
        json={
            "ricarica_automatica": True,
            "soglia_minima": 10000,
            "budget_obiettivo": 10050,
            "conto_sorgente_id": a["id"],
            "frequenza_controllo": "MENSILE",
            "prossimo_controllo": str(date.today()),
        },
        headers=headers,
    )
    session = api.session_factory()
    try:
        # Rende la ricarica possibile: è il saldo della sorgente a deciderlo
        session.query(Conto).get(a["id"]).saldo += Decimal("20000")
        session.commit()
    finally:
        session.close()
    # (quella correzione è "a mano", quindi va presa come nuovo punto fermo)
    api.put(
        f"/conti/{a['id']}",
        json={"saldo": str(_saldi(api, headers)[a["id"]] + Decimal("0.01"))},
        headers=headers,
    )
    task_ricarica_automatica_conti()

    assert _verifica(api, headers) == []


def test_uno_spostamento_senza_movimento_viene_segnalato_e_corretto(api):
    headers = api.registra()
    conto = _conto(api, headers)
    _tx(api, headers, conto, importo=100)
    _verifica(api, headers)

    # Un bug che muove il saldo senza un movimento
    session = api.session_factory()
    try:
        session.query(Conto).get(conto["id"]).saldo -= Decimal("12.34")
        session.commit()
    finally:
        session.close()

    [riga] = _verifica(api, headers)
    assert riga["conto_id"] == conto["id"]
    assert Decimal(riga["saldo"]) == Decimal("887.66")
    assert Decimal(riga["saldo_atteso"]) == Decimal("900.00")

    r = api.post(f"/conti/{conto['id']}/correggi-saldo", headers=headers)
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["saldo"]) == Decimal("900.00")
    assert _verifica(api, headers) == []


def test_correggere_il_saldo_a_mano_e_il_nuovo_punto_fermo(api):
    headers = api.registra()
    conto = _conto(api, headers)
    _tx(api, headers, conto, importo=100)
    _verifica(api, headers)

    r = api.put(f"/conti/{conto['id']}", json={"saldo": 1234}, headers=headers)
    assert r.status_code == 200, r.text

    assert _verifica(api, headers) == []


def test_eliminare_e_ripristinare_un_conto_non_crea_falsi_allarmi(api):
    headers = api.registra()
    a = _conto(api, headers, "A", 1000)
    b = _conto(api, headers, "B", 0)
    _tx(api, headers, a, importo=70, tipo="RICARICA", conto_destinazione_id=b["id"])
    _verifica(api, headers)

    assert api.delete(f"/conti/{a['id']}", headers=headers).status_code == 204
    assert _verifica(api, headers) == []

    assert api.post(f"/conti/{a['id']}/restore", headers=headers).status_code == 200
    assert _verifica(api, headers) == []


def test_la_verifica_e_per_utente(api):
    mario = api.registra("mario")
    luigi = api.registra("luigi")
    conto_luigi = _conto(api, luigi)
    _verifica(api, luigi)

    session = api.session_factory()
    try:
        session.query(Conto).get(conto_luigi["id"]).saldo += Decimal("1")
        session.commit()
    finally:
        session.close()

    assert _verifica(api, mario) == []
    assert (
        api.post(f"/conti/{conto_luigi['id']}/correggi-saldo", headers=mario).status_code
        == 404
    )


# --- Export CSV ---------------------------------------------------------------


def test_export_csv_rispetta_filtri_e_formato(api):
    headers = api.registra()
    conto = _conto(api, headers)
    oggi = date.today()
    _tx(api, headers, conto, importo=12.5, descrizione="Pizza")
    _tx(api, headers, conto, importo=99, descrizione="=HYPERLINK(\"x\")")
    _tx(
        api,
        headers,
        conto,
        importo=5,
        descrizione="Vecchia",
        data=str(oggi - timedelta(days=400)),
    )

    r = api.get(
        "/transazioni/export",
        params={"data_inizio": str(oggi - timedelta(days=30))},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]

    testo = r.content.decode("utf-8")
    assert testo.startswith("﻿")
    righe = testo.lstrip("﻿").strip().split("\r\n")

    assert righe[0].split(";")[:3] == ["Data", "Tipo", "Importo"]
    assert len(righe) == 3  # intestazione + 2: "Vecchia" è fuori periodo
    corpo = "\n".join(righe[1:])
    assert "12,50" in corpo
    assert "Principale" in corpo
    # Una formula diventa testo, non viene eseguita all'apertura
    assert "'=HYPERLINK" in corpo


def test_export_csv_e_per_utente(api):
    mario = api.registra("mario")
    luigi = api.registra("luigi")
    _tx(api, luigi, _conto(api, luigi), descrizione="Segreto")

    r = api.get("/transazioni/export", headers=mario)
    assert r.status_code == 200
    assert "Segreto" not in r.content.decode("utf-8")


def test_senza_data_la_transazione_prende_quella_di_oggi(api):
    # Il default si calcola a ogni richiesta, non una volta all'avvio.
    headers = api.registra()
    conto = _conto(api, headers)
    r = api.post(
        "/transazioni",
        json={"importo": 5, "tipo": "USCITA", "conto_id": conto["id"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"] == str(date.today())
