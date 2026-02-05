from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Investimento, StoricoInvestimento
from schemas.investimento import (
    InvestimentoCreate,
    InvestimentoOut,
    InvestimentoUpdate,
    StoricoInvestimentoCreate,
    StoricoInvestimentoOut,
    StoricoInvestimentoUpdate,
)

router = APIRouter(prefix="/investimenti", tags=["Investimenti"])


# 1. GET ALL - All user investments
@router.get("", response_model=list[InvestimentoOut])
def get_investimenti(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    return db.query(Investimento).filter(Investimento.user_id == current_user_id).all()


# 2. GET SINGLE - Specific investment details
@router.get("/{id}", response_model=InvestimentoOut)
def get_investimento(
    id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    invest = (
        db.query(Investimento)
        .filter(Investimento.id == id, Investimento.user_id == current_user_id)
        .first()
    )
    if not invest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found"
        )
    return invest


# 3. POST - Create investment + Initial Operation
@router.post("", response_model=InvestimentoOut)
def create_investimento(
    payload: InvestimentoCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # Check for duplicate ISIN
    existing = (
        db.query(Investimento)
        .filter(
            Investimento.isin == payload.isin, Investimento.user_id == current_user_id
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ISIN already exists in your portfolio",
        )

    try:
        # Create security info
        new_invest = Investimento(
            isin=payload.isin,
            ticker=payload.ticker,
            nome_titolo=payload.nome_titolo,
            user_id=current_user_id,
        )
        db.add(new_invest)
        db.flush()

        # Create initial operation
        op_iniziale = StoricoInvestimento(
            investimento_id=new_invest.id,
            data=payload.data_iniziale,
            quantita=payload.quantita_iniziale,
            prezzo_unitario=payload.prezzo_carico_iniziale,
            valore_attuale=payload.quantita_iniziale * payload.prezzo_carico_iniziale,
        )
        db.add(op_iniziale)
        db.commit()
        db.refresh(new_invest)
        return new_invest
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create investment. Please check your data",
        )


# 4. PATCH - Update security details
@router.patch("/{id}", response_model=InvestimentoOut)
def patch_investimento(
    id: int,
    payload: InvestimentoUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_invest = (
        db.query(Investimento)
        .filter(Investimento.id == id, Investimento.user_id == current_user_id)
        .first()
    )
    if not db_invest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found"
        )

    try:
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_invest, key, value)

        db.commit()
        db.refresh(db_invest)
        return db_invest
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update investment details",
        )


# 5. DELETE - Delete investment and history
@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_investimento(
    id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_invest = (
        db.query(Investimento)
        .filter(Investimento.id == id, Investimento.user_id == current_user_id)
        .first()
    )
    if not db_invest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found"
        )

    try:
        db.delete(db_invest)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the investment",
        )


# --- OPERATIONS (HISTORY) ---


# 6. POST - Add new Buy/Sell operation
@router.post("/{id}/operazione", response_model=StoricoInvestimentoOut)
def add_operazione(
    id: int,
    payload: StoricoInvestimentoCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    invest = (
        db.query(Investimento)
        .filter(Investimento.id == id, Investimento.user_id == current_user_id)
        .first()
    )

    if not invest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investment not found or unauthorized",
        )

    try:
        new_op = StoricoInvestimento(
            **payload.model_dump(),
            investimento_id=id,
            valore_attuale=payload.quantita * payload.prezzo_unitario,
        )
        db.add(new_op)
        db.commit()
        db.refresh(new_op)
        return new_op
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add transaction to history",
        )


# 7. PUT - Edit existing operation
@router.put("/{id}/operazione/{op_id}", response_model=StoricoInvestimentoOut)
def update_operazione(
    id: int,
    op_id: int,
    payload: StoricoInvestimentoUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_op = (
        db.query(StoricoInvestimento)
        .join(Investimento)
        .filter(
            StoricoInvestimento.id == op_id,
            StoricoInvestimento.investimento_id == id,
            Investimento.user_id == current_user_id,
        )
        .first()
    )

    if not db_op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operation not found for this investment",
        )

    try:
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_op, key, value)

        db_op.valore_attuale = db_op.quantita * db_op.prezzo_unitario

        db.commit()
        db.refresh(db_op)
        return db_op
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update history record",
        )


# 8. DELETE - Remove operation
@router.delete("/{id}/operazione/{op_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_operazione(
    id: int,
    op_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_op = (
        db.query(StoricoInvestimento)
        .join(Investimento)
        .filter(
            StoricoInvestimento.id == op_id,
            StoricoInvestimento.investimento_id == id,
            Investimento.user_id == current_user_id,
        )
        .first()
    )

    if not db_op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Operation not found"
        )

    try:
        db.delete(db_op)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the history record",
        )
