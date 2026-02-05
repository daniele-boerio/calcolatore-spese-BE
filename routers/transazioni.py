from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from schemas import (
    TransazioneCreate,
    TransazioneOut,
    TransazionePagination,
    TransazioneUpdate,
)
from schemas.transazione import TipoTransazione
from models import Conto, Transazione

router = APIRouter(prefix="/transazioni", tags=["Transazioni"])

# --- ENDPOINT TRANSAZIONI ---


@router.post("", response_model=TransazioneOut)
def create_transazione(
    transazione: TransazioneCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # 1. Recuperiamo il conto (security check + balance update)
    conto = (
        db.query(Conto)
        .filter(Conto.id == transazione.conto_id, Conto.user_id == current_user_id)
        .first()
    )

    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or not authorized",
        )

    # 2. Controllo RIMBORSO (Refund)
    if (
        transazione.tipo == TipoTransazione.RIMBORSO
        and transazione.parent_transaction_id
    ):
        parent_exists = (
            db.query(Transazione)
            .filter(
                Transazione.id == transazione.parent_transaction_id,
                Transazione.user_id == current_user_id,
            )
            .first()
        )

        if not parent_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The original transaction for this refund does not exist",
            )

    try:
        # 3. Creazione record
        new_trans = Transazione(**transazione.model_dump(), user_id=current_user_id)
        db.add(new_trans)

        # 4. Aggiornamento Saldo (Balance Update)
        modificatore = -1 if transazione.tipo == TipoTransazione.USCITA else 1
        conto.saldo += transazione.importo * modificatore

        db.commit()
        db.refresh(new_trans)
        return new_trans
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the transaction",
        )


@router.get("/paginated", response_model=TransazionePagination)
def get_transazioni(
    page: int = 1,
    size: int = 10,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    offset = (page - 1) * size
    query = db.query(Transazione).filter(Transazione.user_id == current_user_id)

    total = query.count()
    data = query.order_by(Transazione.data.desc()).offset(offset).limit(size).all()

    return {"total": total, "page": page, "size": size, "data": data}


@router.get("", response_model=list[TransazioneOut])
def get_recent_transazioni(
    n: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    return (
        db.query(Transazione)
        .filter(Transazione.user_id == current_user_id)
        .order_by(Transazione.data.desc())
        .limit(n)
        .all()
    )


@router.put("/{transazione_id}", response_model=TransazioneOut)
def update_transazione(
    transazione_id: int,
    transazione_data: TransazioneUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_trans = (
        db.query(Transazione)
        .filter(
            Transazione.id == transazione_id, Transazione.user_id == current_user_id
        )
        .first()
    )

    if not db_trans:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found"
        )

    conto = (
        db.query(Conto)
        .filter(Conto.id == db_trans.conto_id, Conto.user_id == current_user_id)
        .first()
    )

    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Associated account not found"
        )

    try:
        # A. REVERSION (Storno)
        if db_trans.tipo == TipoTransazione.USCITA:
            conto.saldo += db_trans.importo
        else:
            conto.saldo -= db_trans.importo

        # B. UPDATE DATA
        update_data = transazione_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_trans, key, value)

        # C. APPLY NEW BALANCE
        if db_trans.tipo == TipoTransazione.USCITA:
            conto.saldo -= db_trans.importo
        else:
            conto.saldo += db_trans.importo

        db.commit()
        db.refresh(db_trans)
        return db_trans
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update transaction and balance",
        )


@router.delete("/{transazione_id}")
def delete_transazione(
    transazione_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_trans = (
        db.query(Transazione)
        .filter(
            Transazione.id == transazione_id, Transazione.user_id == current_user_id
        )
        .first()
    )

    if not db_trans:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found"
        )

    conto = (
        db.query(Conto)
        .filter(Conto.id == db_trans.conto_id, Conto.user_id == current_user_id)
        .first()
    )

    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Associated account not found"
        )

    try:
        # Balance reversion
        if db_trans.tipo == TipoTransazione.USCITA:
            conto.saldo += db_trans.importo
        else:
            conto.saldo -= db_trans.importo

        db.delete(db_trans)
        db.commit()
        return {"message": "Transaction successfully deleted and balance updated"}
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the transaction",
        )


@router.get("/tag/{tag_id}", response_model=list[TransazioneOut])
def get_transazioni_by_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    return (
        db.query(Transazione)
        .filter(Transazione.tag_id == tag_id, Transazione.user_id == current_user_id)
        .order_by(Transazione.data.desc())
        .all()
    )
