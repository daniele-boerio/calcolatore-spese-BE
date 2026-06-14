from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from schemas import DebitoCreate, DebitoOut, DebitoUpdate
from schemas.transazione import TransazioneOut, TipoTransazione
from models import Debito, Conto, Transazione
from decimal import Decimal
from datetime import date, datetime, timezone

router = APIRouter(prefix="/debiti", tags=["Debiti"])


@router.get("", response_model=list[DebitoOut])
def list_debiti(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    return db.query(Debito).filter(Debito.user_id == current_user_id).all()


@router.post("", response_model=DebitoOut)
def create_debito(debito: DebitoCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    # Se conto_id è passato, verifichiamo che esista e appartenga all'utente
    if debito.conto_id:
        conto = db.query(Conto).filter(Conto.id == debito.conto_id, Conto.user_id == current_user_id).first()
        if not conto:
            raise HTTPException(status_code=404, detail="Associated account not found")

    residuo_val = debito.residuo if debito.residuo is not None else debito.ammontare

    new = Debito(
        nome=debito.nome,
        ammontare=debito.ammontare,
        residuo=residuo_val,
        descrizione=debito.descrizione,
        conto_id=debito.conto_id,
        user_id=current_user_id,
    )
    try:
        db.add(new)
        db.commit()
        db.refresh(new)
        return new
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{debito_id}", response_model=DebitoOut)
def update_debito(debito_id: int, data: DebitoUpdate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    db_debito = db.query(Debito).filter(Debito.id == debito_id, Debito.user_id == current_user_id).first()
    if not db_debito:
        raise HTTPException(status_code=404, detail="Debito not found")

    update_data = data.model_dump(exclude_unset=True)
    # If conto_id provided, validate ownership
    if "conto_id" in update_data and update_data.get("conto_id"):
        conto = db.query(Conto).filter(Conto.id == update_data.get("conto_id"), Conto.user_id == current_user_id).first()
        if not conto:
            raise HTTPException(status_code=404, detail="Associated account not found")

    try:
        for k, v in update_data.items():
            setattr(db_debito, k, v)

        # Ensure residuo is not greater than ammontare
        if db_debito.residuo is not None and db_debito.ammontare is not None:
            if db_debito.residuo > db_debito.ammontare:
                db_debito.residuo = db_debito.ammontare

        db.add(db_debito)
        db.commit()
        db.refresh(db_debito)
        return db_debito
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{debito_id}")
def delete_debito(debito_id: int, force: bool = False, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    db_debito = db.query(Debito).filter(Debito.id == debito_id, Debito.user_id == current_user_id).first()
    if not db_debito:
        raise HTTPException(status_code=404, detail="Debito not found")

    if db_debito.residuo and db_debito.residuo > Decimal("0") and not force:
        raise HTTPException(status_code=400, detail="Debito has remaining amount; use force=true to delete")

    try:
        db.delete(db_debito)
        db.commit()
        return {"message": "Debito deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


from pydantic import BaseModel
from typing import Optional


class DebitoPay(BaseModel):
    importo: Decimal
    conto_id: Optional[int] = None
    data: Optional[date] = None
    descrizione: Optional[str] = None


@router.post("/{debito_id}/pay", response_model=TransazioneOut)
def pay_debito(debito_id: int, body: DebitoPay, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    db_debito = db.query(Debito).filter(Debito.id == debito_id, Debito.user_id == current_user_id).first()
    if not db_debito:
        raise HTTPException(status_code=404, detail="Debito not found")

    # Determine target account
    conto_id = body.conto_id if body.conto_id is not None else db_debito.conto_id
    if not conto_id:
        raise HTTPException(status_code=400, detail="No account specified for payment")

    conto = db.query(Conto).filter(Conto.id == conto_id, Conto.user_id == current_user_id).first()
    if not conto:
        raise HTTPException(status_code=404, detail="Associated account not found")

    if body.importo <= Decimal("0"):
        raise HTTPException(status_code=400, detail="Invalid importo")

    try:
        # Create transaction (payment reduces debt and reduces account balance)
        trans = Transazione(
            importo=body.importo,
            tipo=TipoTransazione.USCITA,
            data=body.data if body.data is not None else date.today(),
            descrizione=body.descrizione,
            conto_id=conto.id,
            user_id=current_user_id,
            debito_id=db_debito.id,
            importo_netto=body.importo,
        )

        # Adjust debt residuo (do not go below zero)
        new_residuo = (db_debito.residuo - body.importo) if db_debito.residuo is not None else None
        if new_residuo is not None and new_residuo < Decimal("0"):
            new_residuo = Decimal("0.00")

        if new_residuo is not None:
            db_debito.residuo = new_residuo

        # Update account balance (USCITA decreases)
        conto.saldo += body.importo * Decimal("-1")

        db.add(trans)
        db.add(db_debito)
        db.add(conto)
        db.commit()
        db.refresh(trans)
        return trans
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
