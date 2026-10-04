"""Migrazione dei movimenti da una categoria/sottocategoria a un'altra.

Oltre a categoria e sottocategoria, l'origine si può restringere a un tag e la
destinazione può lasciare il tag com'è, impostarne un altro o toglierlo.
"""

from datetime import date


def _setup(api, headers):
    conto = api.post(
        "/conti", json={"nome": "Principale", "saldo": 1000}, headers=headers
    ).json()

    def categoria(nome):
        return api.post(
            "/categorie",
            json={"nome": nome, "solo_entrata": False, "solo_uscita": True},
            headers=headers,
        ).json()

    def tag(nome):
        return api.post("/tags", json={"nome": nome}, headers=headers).json()

    return conto, categoria, tag


def _tx(api, headers, conto, categoria, tag=None):
    r = api.post(
        "/transazioni",
        json={
            "importo": 10,
            "tipo": "USCITA",
            "data": str(date.today()),
            "conto_id": conto["id"],
            "categoria_id": categoria["id"],
            "tag_id": tag["id"] if tag else None,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _get(api, headers, tx):
    return api.get(f"/transazioni/{tx['id']}", headers=headers).json()


def _migra(api, headers, **payload):
    return api.post("/categorie/migrate", json=payload, headers=headers)


def test_senza_vincoli_sposta_tutto_e_lascia_i_tag(api):
    headers = api.registra()
    conto, categoria, tag = _setup(api, headers)
    vecchia, nuova = categoria("Svago"), categoria("Tempo libero")
    vacanza = tag("Vacanza")
    con_tag = _tx(api, headers, conto, vecchia, vacanza)
    senza_tag = _tx(api, headers, conto, vecchia)

    r = _migra(
        api, headers, old_categoria_id=vecchia["id"], new_categoria_id=nuova["id"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["transazioni_aggiornate"] == 2

    assert _get(api, headers, con_tag)["categoria_id"] == nuova["id"]
    assert _get(api, headers, con_tag)["tag_id"] == vacanza["id"]
    assert _get(api, headers, senza_tag)["tag_id"] is None


def test_il_tag_di_origine_restringe_lo_spostamento(api):
    headers = api.registra()
    conto, categoria, tag = _setup(api, headers)
    vecchia, nuova = categoria("Ristoranti"), categoria("Viaggi")
    vacanza, lavoro = tag("Vacanza"), tag("Lavoro")
    in_vacanza = _tx(api, headers, conto, vecchia, vacanza)
    al_lavoro = _tx(api, headers, conto, vecchia, lavoro)
    senza_tag = _tx(api, headers, conto, vecchia)

    r = _migra(
        api,
        headers,
        old_categoria_id=vecchia["id"],
        new_categoria_id=nuova["id"],
        old_tag_id=vacanza["id"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["transazioni_aggiornate"] == 1

    assert _get(api, headers, in_vacanza)["categoria_id"] == nuova["id"]
    assert _get(api, headers, al_lavoro)["categoria_id"] == vecchia["id"]
    assert _get(api, headers, senza_tag)["categoria_id"] == vecchia["id"]


def test_la_destinazione_puo_cambiare_tag(api):
    headers = api.registra()
    conto, categoria, tag = _setup(api, headers)
    vecchia, nuova = categoria("Spesa"), categoria("Casa")
    vecchio_tag, nuovo_tag = tag("2025"), tag("2026")
    tx = _tx(api, headers, conto, vecchia, vecchio_tag)

    r = _migra(
        api,
        headers,
        old_categoria_id=vecchia["id"],
        new_categoria_id=nuova["id"],
        old_tag_id=vecchio_tag["id"],
        tag_action="set",
        new_tag_id=nuovo_tag["id"],
    )
    assert r.status_code == 200, r.text

    salvata = _get(api, headers, tx)
    assert salvata["categoria_id"] == nuova["id"]
    assert salvata["tag_id"] == nuovo_tag["id"]


def test_la_destinazione_puo_togliere_il_tag(api):
    headers = api.registra()
    conto, categoria, tag = _setup(api, headers)
    vecchia, nuova = categoria("Spesa"), categoria("Casa")
    vacanza = tag("Vacanza")
    tx = _tx(api, headers, conto, vecchia, vacanza)

    r = _migra(
        api,
        headers,
        old_categoria_id=vecchia["id"],
        new_categoria_id=nuova["id"],
        old_tag_id=vacanza["id"],
        tag_action="clear",
    )
    assert r.status_code == 200, r.text
    assert _get(api, headers, tx)["tag_id"] is None


def test_anche_le_ricorrenze_seguono_il_vincolo_sul_tag(api):
    headers = api.registra()
    conto, categoria, tag = _setup(api, headers)
    vecchia, nuova = categoria("Abbonamenti"), categoria("Svago")
    streaming, palestra = tag("Streaming"), tag("Palestra")

    def ricorrenza(t):
        return api.post(
            "/ricorrenze",
            json={
                "nome": t["nome"],
                "importo": 10,
                "tipo": "USCITA",
                "frequenza": "MENSILE",
                "prossima_esecuzione": str(date.today()),
                "conto_id": conto["id"],
                "categoria_id": vecchia["id"],
                "tag_id": t["id"],
            },
            headers=headers,
        ).json()

    ric_streaming = ricorrenza(streaming)
    ric_palestra = ricorrenza(palestra)

    r = _migra(
        api,
        headers,
        old_categoria_id=vecchia["id"],
        new_categoria_id=nuova["id"],
        old_tag_id=streaming["id"],
    )
    assert r.json()["ricorrenze_aggiornate"] == 1

    per_id = {r["id"]: r for r in api.get("/ricorrenze", headers=headers).json()}
    assert per_id[ric_streaming["id"]]["categoria_id"] == nuova["id"]
    assert per_id[ric_palestra["id"]]["categoria_id"] == vecchia["id"]


def test_set_senza_tag_e_rifiutato(api):
    headers = api.registra()
    _, categoria, _ = _setup(api, headers)
    a, b = categoria("A"), categoria("B")

    r = _migra(
        api, headers, old_categoria_id=a["id"], new_categoria_id=b["id"], tag_action="set"
    )
    assert r.status_code == 422


def test_non_si_usa_il_tag_di_un_altro_utente(api):
    mario = api.registra("mario")
    luigi = api.registra("luigi")
    _, categoria, _ = _setup(api, mario)
    a, b = categoria("A"), categoria("B")
    tag_altrui = api.post("/tags", json={"nome": "Suo"}, headers=luigi).json()

    for payload in (
        {"old_tag_id": tag_altrui["id"]},
        {"tag_action": "set", "new_tag_id": tag_altrui["id"]},
    ):
        r = _migra(
            api,
            mario,
            old_categoria_id=a["id"],
            new_categoria_id=b["id"],
            **payload,
        )
        assert r.status_code == 404, (payload, r.text)
