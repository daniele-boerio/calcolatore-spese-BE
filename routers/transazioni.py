from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas, auth

router = APIRouter(
    prefix="/transazioni",      # Tutti gli endpoint in questo file inizieranno con /transazioni
    tags=["Transazioni"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT TRANSAZIONI ---

@router.post("/transazione", response_model=schemas.TransazioneOut)
def create_transazione(trans: schemas.TransazioneCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    conto = db.query(models.Conto).filter(models.Conto.id == trans.conto_id, models.Conto.user_id == current_user_id).first()
    if not conto:
        raise HTTPException(status_code=404, detail="Conto non trovato")

    # Aggiornamento saldo
    if trans.tipo.upper() == "ENTRATA":
        conto.saldo += trans.importo
    else:
        conto.saldo -= trans.importo

    new_trans = models.Transazione(**trans.model_dump())
    db.add(new_trans)
    db.commit()
    db.refresh(new_trans)
    return new_trans

@router.get("/transazioni", response_model=list[schemas.TransazioneOut])
def get_transazioni(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Recuperiamo tutte le transazioni filtrando attraverso i conti dell'utente
    return db.query(models.Transazione).join(models.Conto).filter(
        models.Conto.user_id == current_user_id
    ).all()

@router.put("/transazione/{transazione_id}", response_model=schemas.TransazioneOut)
def update_transazione(
    transazione_id: int, 
    trans_data: schemas.TransazioneCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_trans = db.query(models.Transazione).join(models.Conto).filter(
        models.Transazione.id == transazione_id, 
        models.Conto.user_id == current_user_id
    ).first()

    if not db_trans:
        raise HTTPException(status_code=404, detail="Transazione non trovata")

    # 1. Storna il vecchio importo dal vecchio conto
    old_conto = db_trans.conto
    if db_trans.tipo.upper() == "ENTRATA":
        old_conto.saldo -= db_trans.importo
    else:
        old_conto.saldo += db_trans.importo

    # 2. Aggiorna i dati della transazione
    for key, value in trans_data.model_dump().items():
        setattr(db_trans, key, value)
    
    # 3. Applica il nuovo importo al (potenzialmente nuovo) conto
    new_conto = db.query(models.Conto).filter(models.Conto.id == db_trans.conto_id).first()
    if db_trans.tipo.upper() == "ENTRATA":
        new_conto.saldo += db_trans.importo
    else:
        new_conto.saldo -= db_trans.importo

    db.commit()
    db.refresh(db_trans)
    return db_trans

@router.delete("/transazione/{transazione_id}")
def delete_transazione(transazione_id: int, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    db_trans = db.query(models.Transazione).join(models.Conto).filter(
        models.Transazione.id == transazione_id, models.Conto.user_id == current_user_id
    ).first()

    if not db_trans:
        raise HTTPException(status_code=404, detail="Transazione non trovata")

    # Reversione saldo
    if db_trans.tipo.upper() == "ENTRATA":
        db_trans.conto.saldo -= db_trans.importo
    else:
        db_trans.conto.saldo += db_trans.importo

    db.delete(db_trans)
    db.commit()
    return {"message": "Eliminata"}

@router.get("/transazioni/tag/{tag_id}")
def get_transazioni_by_tag(
    tag_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    return db.query(models.Transazione).join(models.Transazione.tags).filter(
        models.Tag.id == tag_id,
        models.Tag.user_id == current_user_id
    ).all()