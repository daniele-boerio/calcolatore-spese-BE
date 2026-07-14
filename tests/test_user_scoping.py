"""Ogni query del BE è user-scoped: un utente non deve mai vedere i dati di un
altro (vedi BE/CLAUDE.md). Qui verifichiamo l'invariante sul vero codice del
router `GET /conti`, chiamando la funzione endpoint direttamente con una
sessione di test (niente HTTP: le funzioni FastAPI sono normali funzioni).
"""

from decimal import Decimal

from models import User, Conto
from schemas.conto import ContoFilters
from routers.conti import get_conti


def _no_filters() -> ContoFilters:
    # I default di ContoFilters sono oggetti Query(...): passiamo None espliciti
    # così `model_dump()` risulta vuoto (nessun filtro applicato).
    return ContoFilters(
        sort_by=None,
        nome=None,
        saldo_min=None,
        saldo_max=None,
        ricarica_automatica=None,
    )


def _make_user(db, username, email):
    user = User(username=username, email=email, hashed_password="x")
    db.add(user)
    db.flush()  # popola user.id senza commit
    return user


def test_get_conti_returns_only_current_user_accounts(db_session):
    u1 = _make_user(db_session, "u1", "u1@example.it")
    u2 = _make_user(db_session, "u2", "u2@example.it")

    db_session.add_all(
        [
            Conto(nome="Conto U1 A", saldo=Decimal("10.00"), user_id=u1.id),
            Conto(nome="Conto U1 B", saldo=Decimal("5.00"), user_id=u1.id),
            Conto(nome="Conto U2", saldo=Decimal("99.00"), user_id=u2.id),
        ]
    )
    db_session.commit()

    result = get_conti(
        filters=_no_filters(), db=db_session, current_user_id=u1.id
    )

    assert {c.nome for c in result} == {"Conto U1 A", "Conto U1 B"}
    # Nessuna riga di un altro utente deve trapelare.
    assert all(c.user_id == u1.id for c in result)


def test_get_conti_empty_when_user_has_no_accounts(db_session):
    owner = _make_user(db_session, "owner", "owner@example.it")
    other = _make_user(db_session, "other", "other@example.it")

    db_session.add(
        Conto(nome="Solo dell'altro", saldo=Decimal("1.00"), user_id=other.id)
    )
    db_session.commit()

    result = get_conti(
        filters=_no_filters(), db=db_session, current_user_id=owner.id
    )

    assert result == []


def test_get_conti_excludes_soft_deleted_accounts(db_session):
    from datetime import datetime, timezone

    user = _make_user(db_session, "u", "u@example.it")
    db_session.add_all(
        [
            Conto(nome="Attivo", saldo=Decimal("1.00"), user_id=user.id),
            Conto(
                nome="Cancellato",
                saldo=Decimal("2.00"),
                user_id=user.id,
                deleted_at=datetime.now(timezone.utc),
            ),
        ]
    )
    db_session.commit()

    result = get_conti(
        filters=_no_filters(), db=db_session, current_user_id=user.id
    )

    assert {c.nome for c in result} == {"Attivo"}
