"""Il refresh token regge la sessione lunga del dispositivo, quindi vale quanto una
password: qui verifichiamo le tre proprietà che lo rendono sicuro.

1. In DB non finisce mai in chiaro (solo lo SHA-256).
2. Ogni uso lo ruota: il token vecchio è bruciato.
3. Se un token già ruotato viene rigiocato, la sessione è stata copiata: revochiamo
   l'intera famiglia (reuse detection).
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import auth
from models import RefreshToken, User


def _make_user(db, username="u1", email="u1@example.it"):
    user = User(username=username, email=email, hashed_password="x")
    db.add(user)
    db.flush()
    return user


def test_il_token_in_chiaro_non_viene_mai_salvato(db_session):
    user = _make_user(db_session)

    raw = auth.issue_refresh_token(db_session, user.id)
    db_session.commit()

    stored = db_session.query(RefreshToken).one()
    assert stored.token_hash != raw
    assert stored.token_hash == auth._hash_refresh_token(raw)
    # Nessuna colonna contiene il valore in chiaro
    assert raw not in (stored.token_hash, stored.family_id)


def test_consume_ruota_il_token_e_brucia_il_vecchio(db_session):
    user = _make_user(db_session)
    raw1 = auth.issue_refresh_token(db_session, user.id)
    db_session.commit()

    consumed = auth.consume_refresh_token(db_session, raw1)
    raw2 = auth.issue_refresh_token(
        db_session, user.id, family_id=consumed.family_id
    )
    db_session.commit()

    # Il nuovo token resta nella stessa famiglia (stessa sessione, stesso dispositivo)
    new_token = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.token_hash == auth._hash_refresh_token(raw2))
        .one()
    )
    assert new_token.family_id == consumed.family_id
    assert new_token.used_at is None

    # Il vecchio è speso: non è più spendibile
    assert consumed.used_at is not None


def test_riuso_di_un_token_gia_ruotato_revoca_tutta_la_famiglia(db_session):
    """Lo scenario di furto: l'attaccante copia il cookie e lo rigioca dopo che la
    vittima ha già rinnovato. Non sappiamo chi sia chi, quindi cadono entrambi."""
    user = _make_user(db_session)
    raw1 = auth.issue_refresh_token(db_session, user.id)
    db_session.commit()

    first = auth.consume_refresh_token(db_session, raw1)
    raw2 = auth.issue_refresh_token(db_session, user.id, family_id=first.family_id)
    db_session.commit()

    # Replay del token già ruotato
    with pytest.raises(HTTPException) as exc:
        auth.consume_refresh_token(db_session, raw1)
    assert exc.value.status_code == 401

    # Anche il token "buono" della stessa famiglia è stato revocato
    with pytest.raises(HTTPException):
        auth.consume_refresh_token(db_session, raw2)

    attivi = (
        db_session.query(RefreshToken)
        .filter(
            RefreshToken.family_id == first.family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .count()
    )
    assert attivi == 0


def test_token_scaduto_rifiutato(db_session):
    user = _make_user(db_session)
    raw = auth.issue_refresh_token(db_session, user.id)
    db_session.commit()

    stored = db_session.query(RefreshToken).one()
    stored.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=1
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        auth.consume_refresh_token(db_session, raw)
    assert exc.value.status_code == 401


def test_token_sconosciuto_rifiutato(db_session):
    _make_user(db_session)
    with pytest.raises(HTTPException) as exc:
        auth.consume_refresh_token(db_session, "token-inventato")
    assert exc.value.status_code == 401


def test_logout_all_revoca_tutti_i_dispositivi(db_session):
    user = _make_user(db_session)
    raw_pc = auth.issue_refresh_token(db_session, user.id, user_agent="pc")
    raw_phone = auth.issue_refresh_token(db_session, user.id, user_agent="phone")
    db_session.commit()

    auth.revoke_all_user_tokens(db_session, user.id)
    db_session.commit()

    for raw in (raw_pc, raw_phone):
        with pytest.raises(HTTPException):
            auth.consume_refresh_token(db_session, raw)


def test_logout_revoca_solo_la_sessione_corrente(db_session):
    """Il logout su un dispositivo non deve buttare fuori gli altri."""
    user = _make_user(db_session)
    raw_pc = auth.issue_refresh_token(db_session, user.id, user_agent="pc")
    raw_phone = auth.issue_refresh_token(db_session, user.id, user_agent="phone")
    db_session.commit()

    assert auth.revoke_session(db_session, raw_pc) is True
    db_session.commit()

    with pytest.raises(HTTPException):
        auth.consume_refresh_token(db_session, raw_pc)

    # Il telefono resta loggato
    still_valid = auth.consume_refresh_token(db_session, raw_phone)
    assert still_valid.user_id == user.id
