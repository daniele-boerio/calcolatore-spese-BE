"""La tassonomia (categoria/sottocategoria/tag) arriva dal client come i conti, e
come i conti va verificata: senza il controllo di proprietà un utente può agganciare
le proprie transazioni alla tassonomia di un altro, e l'autocompilazione della
descrizione ne rivelerebbe il nome nella risposta API.

Verifichiamo l'invariante sul vero codice del router, chiamando le funzioni
endpoint direttamente (niente HTTP).
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from models import Categoria, Conto, Sottocategoria, Tag, User
from routers.transazioni import create_transazione
from schemas.transazione import TipoTransazione, TransazioneCreate


def _make_user(db, username, email):
    user = User(username=username, email=email, hashed_password="x")
    db.add(user)
    db.flush()
    return user


def _payload(conto_id, **kwargs):
    return TransazioneCreate(
        importo=Decimal("10.00"),
        tipo=TipoTransazione.USCITA,
        data=date(2026, 7, 14),
        conto_id=conto_id,
        **kwargs,
    )


@pytest.fixture()
def two_users(db_session):
    """u1 (attaccante, con un conto suo) e u2 (vittima, con la sua tassonomia)."""
    u1 = _make_user(db_session, "u1", "u1@example.it")
    u2 = _make_user(db_session, "u2", "u2@example.it")

    conto_u1 = Conto(nome="Conto U1", saldo=Decimal("100.00"), user_id=u1.id)
    cat_u2 = Categoria(nome="Categoria segreta di U2", user_id=u2.id)
    tag_u2 = Tag(nome="Tag segreto di U2", user_id=u2.id)
    db_session.add_all([conto_u1, cat_u2, tag_u2])
    db_session.flush()

    sotto_u2 = Sottocategoria(
        nome="Sottocategoria segreta di U2", categoria_id=cat_u2.id, user_id=u2.id
    )
    db_session.add(sotto_u2)
    db_session.flush()

    return u1, u2, conto_u1, cat_u2, sotto_u2, tag_u2


def test_create_rifiuta_categoria_di_un_altro_utente(db_session, two_users):
    u1, _u2, conto_u1, cat_u2, _sotto, _tag = two_users

    with pytest.raises(HTTPException) as exc:
        create_transazione(
            _payload(conto_u1.id, categoria_id=cat_u2.id),
            db=db_session,
            current_user_id=u1.id,
        )

    assert exc.value.status_code == 400
    assert "not authorized" in exc.value.detail.lower()


def test_create_rifiuta_sottocategoria_di_un_altro_utente(db_session, two_users):
    u1, _u2, conto_u1, _cat, sotto_u2, _tag = two_users

    with pytest.raises(HTTPException) as exc:
        create_transazione(
            _payload(conto_u1.id, sottocategoria_id=sotto_u2.id),
            db=db_session,
            current_user_id=u1.id,
        )

    assert exc.value.status_code == 400


def test_create_rifiuta_tag_di_un_altro_utente(db_session, two_users):
    u1, _u2, conto_u1, _cat, _sotto, tag_u2 = two_users

    with pytest.raises(HTTPException) as exc:
        create_transazione(
            _payload(conto_u1.id, tag_id=tag_u2.id),
            db=db_session,
            current_user_id=u1.id,
        )

    assert exc.value.status_code == 400


def test_autofill_descrizione_non_rivela_il_nome_della_tassonomia_altrui(
    db_session, two_users
):
    """Il leak concreto: senza descrizione, l'endpoint la autocompilava leggendo il
    nome della sottocategoria PER ID, senza filtro utente, e lo restituiva."""
    u1, _u2, conto_u1, _cat, sotto_u2, _tag = two_users

    with pytest.raises(HTTPException):
        create_transazione(
            _payload(conto_u1.id, sottocategoria_id=sotto_u2.id, descrizione=""),
            db=db_session,
            current_user_id=u1.id,
        )

    # La transazione non deve nemmeno esistere: nessun nome altrui è trapelato.
    from models import Transazione

    assert db_session.query(Transazione).count() == 0


def test_create_accetta_la_tassonomia_propria(db_session):
    """Contro-prova: il controllo non rompe il caso legittimo, e l'autofill continua
    a funzionare con la propria sottocategoria."""
    u1 = _make_user(db_session, "solo", "solo@example.it")

    conto = Conto(nome="Conto", saldo=Decimal("100.00"), user_id=u1.id)
    cat = Categoria(nome="Spesa", user_id=u1.id)
    db_session.add_all([conto, cat])
    db_session.flush()

    sotto = Sottocategoria(nome="Supermercato", categoria_id=cat.id, user_id=u1.id)
    db_session.add(sotto)
    db_session.flush()

    result = create_transazione(
        _payload(conto.id, categoria_id=cat.id, sottocategoria_id=sotto.id),
        db=db_session,
        current_user_id=u1.id,
    )

    assert result.id is not None
    # Descrizione vuota → autocompilata con la PROPRIA sottocategoria
    assert result.descrizione == "Supermercato"
