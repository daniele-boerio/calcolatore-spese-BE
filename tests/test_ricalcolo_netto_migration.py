"""La migration a7b8c9d0e1f2 ripara i netti scollegati dai rimborsi.

Ricostruisce la riga rotta trovata in produzione (Traghetto Corsica: lordo 510,
quattro rimborsi da 102, netto fermo a 204) e verifica che il ricalcolo la
riporti a 102 senza toccare le righe sane.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base

# La stessa SQL che gira nella migration: importata, non ricopiata, così il test
# non può divergere dallo script che verrà eseguito in produzione.
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "mig_ricalcolo",
    Path(__file__).resolve().parent.parent
    / "alembic/versions/a7b8c9d0e1f2_ricalcola_importo_netto_dai_rimborsi.py",
)
_mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mig)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _tx(db, **kwargs):
    campi = {
        "data": date(2026, 3, 3),
        "conto_id": 1,
        "user_id": 1,
        "descrizione": "x",
        "tipo": "USCITA",
    }
    campi.update(kwargs)
    t = models.Transazione(**campi)
    db.add(t)
    db.flush()
    return t


def _ricalcola(db):
    db.commit()
    db.execute(text(_mig.RICALCOLO))
    db.commit()


def test_ripara_la_riga_di_produzione(db):
    """Traghetto Corsica: netto 204 con quattro rimborsi da 102 -> deve fare 102."""
    padre = _tx(db, importo=Decimal("510.00"), importo_netto=Decimal("204.00"))
    for _ in range(4):
        _tx(db, importo=Decimal("102.00"), importo_netto=Decimal("102.00"),
            tipo="RIMBORSO", parent_transaction_id=padre.id)

    _ricalcola(db)

    db.refresh(padre)
    assert padre.importo_netto == Decimal("102.00")


def test_non_tocca_le_righe_gia_corrette(db):
    padre = _tx(db, importo=Decimal("200.00"), importo_netto=Decimal("150.00"))
    _tx(db, importo=Decimal("50.00"), importo_netto=Decimal("50.00"),
        tipo="RIMBORSO", parent_transaction_id=padre.id)
    sola = _tx(db, importo=Decimal("80.00"), importo_netto=Decimal("80.00"))

    _ricalcola(db)

    db.refresh(padre)
    db.refresh(sola)
    assert padre.importo_netto == Decimal("150.00")
    assert sola.importo_netto == Decimal("80.00")


def test_conta_anche_i_rimborsi_soft_eliminati(db):
    """Archiviare un conto soft-elimina le sue transazioni ma non storna il netto.

    Il ricalcolo deve seguire la stessa regola di `adjust_parent_netto`, altrimenti
    il ripristino del conto (/conti/{id}/restore) troverebbe il padre già
    "scontato" una seconda volta.
    """
    padre = _tx(db, importo=Decimal("300.00"), importo_netto=Decimal("999.00"))
    _tx(db, importo=Decimal("100.00"), importo_netto=Decimal("100.00"),
        tipo="RIMBORSO", parent_transaction_id=padre.id)
    _tx(db, importo=Decimal("50.00"), importo_netto=Decimal("50.00"),
        tipo="RIMBORSO", parent_transaction_id=padre.id,
        deleted_at=datetime.now(timezone.utc))

    _ricalcola(db)

    db.refresh(padre)
    assert padre.importo_netto == Decimal("150.00")


def test_e_idempotente(db):
    padre = _tx(db, importo=Decimal("510.00"), importo_netto=Decimal("204.00"))
    for _ in range(4):
        _tx(db, importo=Decimal("102.00"), importo_netto=Decimal("102.00"),
            tipo="RIMBORSO", parent_transaction_id=padre.id)

    _ricalcola(db)
    _ricalcola(db)

    db.refresh(padre)
    assert padre.importo_netto == Decimal("102.00")
