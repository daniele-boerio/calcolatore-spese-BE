from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas, auth

router = APIRouter(
    prefix="/conti",      # Tutti gli endpoint in questo file inizieranno con /conti
    tags=["Conti"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT CONTI ---

@router.post("/", response_model=schemas.ContoOut)
def create_conto(conto: schemas.ContoCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    new_conto = models.Conto(**conto.model_dump(), user_id=current_user_id)
    db.add(new_conto)
    db.commit()
    db.refresh(new_conto)
    return new_conto

@router.get("/", response_model=list[schemas.ContoOut])
def get_conti(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    return db.query(models.Conto).filter(models.Conto.user_id == current_user_id).all()

@router.put("/{conto_id}", response_model=schemas.ContoOut)
def update_conto(
    conto_id: int, 
    conto_data: schemas.ContoUpdate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Cerchiamo il conto verificando che appartenga all'utente
    db_conto = db.query(models.Conto).filter(
        models.Conto.id == conto_id, 
        models.Conto.user_id == current_user_id
    ).first()

    if not db_conto:
        raise HTTPException(status_code=404, detail="Conto non trovato o non autorizzato")

    # Aggiorniamo solo i campi inviati (escludendo quelli None)
    update_data = conto_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_conto, key, value)

    db.commit()
    db.refresh(db_conto)
    return db_conto

@router.delete("/{conto_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conto(
    conto_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_conto = db.query(models.Conto).filter(
        models.Conto.id == conto_id, 
        models.Conto.user_id == current_user_id
    ).first()

    if not db_conto:
        raise HTTPException(status_code=404, detail="Conto non trovato")

    # Nota: se elimini un conto, le transazioni collegate verranno eliminate 
    # se hai impostato il 'cascade delete' nei modelli.
    db.delete(db_conto)
    db.commit()
    return None