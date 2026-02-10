from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Conto, Transazione, User
from schemas import ContoCreate, ContoOut, ContoUpdate
from schemas.transazione import TipoTransazione

router = APIRouter(prefix="/conti", tags=["Conti"])

# --- ENDPOINT CONTI ---


@router.post("", response_model=ContoOut)
def create_conto(
    conto: ContoCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    try:
        new_conto = Conto(**conto.model_dump(), user_id=current_user_id)
        db.add(new_conto)
        db.commit()
        db.refresh(new_conto)
        return new_conto
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the account",
        )


@router.get("", response_model=list[ContoOut])
def get_conti(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    return db.query(Conto).filter(Conto.user_id == current_user_id).all()


@router.put("/{conto_id}", response_model=ContoOut)
def update_conto(
    conto_id: int,
    conto_data: ContoUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_conto = (
        db.query(Conto)
        .filter(Conto.id == conto_id, Conto.user_id == current_user_id)
        .first()
    )

    if not db_conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or unauthorized",
        )

    try:
        update_data = conto_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_conto, key, value)

        db.commit()
        db.refresh(db_conto)
        return db_conto
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update account details",
        )


@router.delete("/{conto_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conto(
    conto_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_conto = (
        db.query(Conto)
        .filter(Conto.id == conto_id, Conto.user_id == current_user_id)
        .first()
    )

    if not db_conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        )

    try:
        db.delete(db_conto)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cannot delete account. It may be linked to existing transactions",
        )


@router.get("/currentMonthExpenses")
def get_current_month_expenses(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User session invalid or account not found",
        )

    today = date.today()
    first_day = today.replace(day=1)

    # 1. Total OUTGOING
    total_out = (
        db.query(func.sum(Transazione.importo))
        .join(Conto)
        .filter(
            Conto.user_id == current_user_id,
            Transazione.tipo == TipoTransazione.USCITA,
            Transazione.data >= first_day,
        )
        .scalar()
        or 0.0
    )

    # 2. Total REFUNDS
    total_refunds = (
        db.query(func.sum(Transazione.importo))
        .join(Conto)
        .filter(
            Conto.user_id == current_user_id,
            Transazione.tipo == TipoTransazione.RIMBORSO,
            Transazione.data >= first_day,
        )
        .scalar()
        or 0.0
    )

    net_expenses = max(0, total_out - total_refunds)

    percentage = None
    if user.total_budget and user.total_budget > 0:
        percentage = round((net_expenses / user.total_budget * 100), 1)

    return {
        "monthly_budget": {
            "totalBudget": user.total_budget,
            "expenses": round(net_expenses, 2),
            "percentage": percentage,
        }
    }


@router.get("/expensesByCategory")
def get_expenses_by_category(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    today = date.today()
    first_day = today.replace(day=1)

    # Fetch all transactions (Expenses and Refunds) for the month
    transazioni = (
        db.query(Transazione)
        .join(Conto)
        .filter(
            Conto.user_id == current_user_id,
            or_(
                Transazione.tipo == TipoTransazione.USCITA,
                Transazione.tipo == TipoTransazione.RIMBORSO,
            ),
            Transazione.data >= first_day,
        )
        .all()
    )

    stats = {}

    for t in transazioni:
        cat_nome = t.categoria.nome if t.categoria else "Uncategorized"

        if t.tipo == TipoTransazione.USCITA:
            stats[cat_nome] = stats.get(cat_nome, 0.0) + t.importo
        else:
            stats[cat_nome] = stats.get(cat_nome, 0.0) - t.importo

    return [
        {"label": cat, "value": round(val, 2)} for cat, val in stats.items() if val > 0
    ]
