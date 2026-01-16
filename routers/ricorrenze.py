from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models, schemas, auth

router = APIRouter(prefix="/ricorrenze", tags=["Ricorrenze"])

@router.post("/", response_model=schemas.RicorrenzaOut)
def create_ricorrenza(
    ricorrenza: schemas.RicorrenzaCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Verifica che il conto appartenga all'utente
    conto = db.query(models.Conto).filter(models.Conto.id == ricorrenza.conto_id, models.Conto.user_id == current_user_id).first()
    if not conto:
        raise HTTPException(status_code=404, detail="Conto non trovato")

    new_ric = models.Ricorrenza(**ricorrenza.model_dump(), user_id=current_user_id)
    db.add(new_ric)
    db.commit()
    db.refresh(new_ric)
    return new_ric

@router.get("/", response_model=List[schemas.RicorrenzaOut])
def get_ricorrenze(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    return db.query(models.Ricorrenza).filter(models.Ricorrenza.user_id == current_user_id).all()

@router.put("/{ricorrenza_id}", response_model=schemas.RicorrenzaOut)
def update_ricorrenza(
    ricorrenza_id: int,
    ric_data: schemas.RicorrenzaUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_ric = db.query(models.Ricorrenza).filter(models.Ricorrenza.id == ricorrenza_id, models.Ricorrenza.user_id == current_user_id).first()
    if not db_ric:
        raise HTTPException(status_code=404, detail="Ricorrenza non trovata")

    update_dict = ric_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(db_ric, key, value)

    db.commit()
    db.refresh(db_ric)
    return db_ric

@router.delete("/{ricorrenza_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ricorrenza(
    ricorrenza_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_ric = db.query(models.Ricorrenza).filter(models.Ricorrenza.id == ricorrenza_id, models.Ricorrenza.user_id == current_user_id).first()
    if not db_ric:
        raise HTTPException(status_code=404, detail="Ricorrenza non trovata")

    db.delete(db_ric)
    db.commit()
    return None