from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import auth
from models import Ricorrenza, Conto
from schemas import RicorrenzaOut, RicorrenzaCreate, RicorrenzaUpdate, RicorrenzaFilters
from services import apply_filters_and_sort

router = APIRouter(prefix="/ricorrenze", tags=["Ricorrenze"])


@router.post("", response_model=RicorrenzaOut)
def create_ricorrenza(
    ricorrenza: RicorrenzaCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # 1. Verify that the account belongs to the user
    conto = (
        db.query(Conto)
        .filter(Conto.id == ricorrenza.conto_id, Conto.user_id == current_user_id)
        .first()
    )

    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or unauthorized",
        )

    try:
        new_ric = Ricorrenza(**ricorrenza.model_dump(), user_id=current_user_id)
        db.add(new_ric)
        db.commit()
        db.refresh(new_ric)
        return new_ric
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the recurring transaction",
        )


@router.get("", response_model=List[RicorrenzaOut])
def get_ricorrenze(
    filters: RicorrenzaFilters = Depends(),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    query = db.query(Ricorrenza).filter(Ricorrenza.user_id == current_user_id)

    query = apply_filters_and_sort(
        query,
        Ricorrenza,
        filters=filters,
    )

    return query.all()


@router.put("/{ricorrenza_id}", response_model=RicorrenzaOut)
def update_ricorrenza(
    ricorrenza_id: int,
    ric_data: RicorrenzaUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_ric = (
        db.query(Ricorrenza)
        .filter(Ricorrenza.id == ricorrenza_id, Ricorrenza.user_id == current_user_id)
        .first()
    )

    if not db_ric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring transaction not found",
        )

    try:
        update_dict = ric_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(db_ric, key, value)

        db.commit()
        db.refresh(db_ric)
        return db_ric
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update the recurring transaction",
        )


@router.delete("/{ricorrenza_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ricorrenza(
    ricorrenza_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_ric = (
        db.query(Ricorrenza)
        .filter(Ricorrenza.id == ricorrenza_id, Ricorrenza.user_id == current_user_id)
        .first()
    )

    if not db_ric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring transaction not found",
        )

    try:
        db.delete(db_ric)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the recurring transaction",
        )
