from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas, auth

router = APIRouter(
    prefix="/transazioni",      # Tutti gli endpoint in questo file inizieranno con /transazioni
    tags=["Transazioni"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT TRANSAZIONI ---

@router.post("", response_model=schemas.TransazioneOut)
def create_transazione(transazione: schemas.TransazioneCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    
    # 1. Se è un RIMBORSO, verifichiamo che il padre esista e sia dell'utente
    if transazione.tipo == "RIMBORSO":
        if not transazione.parent_transaction_id:
            raise HTTPException(status_code=400, detail="ID transazione originale mancante")
        
        parent = db.query(models.Transazione).join(models.Conto).filter(
            models.Transazione.id == transazione.parent_transaction_id,
            models.Conto.user_id == current_user_id
        ).first()
        
        if not parent:
            raise HTTPException(status_code=404, detail="Spesa originale non trovata")

    # 2. Creazione (il model_dump include parent_transaction_id)
    new_trans = models.Transazione(**transazione.model_dump())
    db.add(new_trans)

    # 3. Gestione Saldo (Importante!)
    conto = db.query(models.Conto).filter(models.Conto.id == transazione.conto_id).first()
    
    if transazione.tipo == "USCITA":
        conto.saldo -= transazione.importo
    else:
        # Se è ENTRATA o RIMBORSO, aggiungiamo al saldo
        conto.saldo += transazione.importo

    db.commit()
    db.refresh(new_trans)
    return new_trans

@router.get("/{n}", response_model=list[schemas.TransazioneOut])
def get_recent_transazioni(
    n: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Recupera solo gli ultimi n record in ordine cronologico decrescente
    return db.query(models.Transazione).join(models.Conto).filter(
        models.Conto.user_id == current_user_id
    ).order_by(models.Transazione.data.desc()).limit(n).all()

@router.get("/paginated", response_model=schemas.TransazionePagination)
def get_transazioni(
    page: int = 1,
    size: int = 10,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    offset = (page - 1) * size
    
    # Query di base
    query = db.query(models.Transazione).join(models.Conto).filter(
        models.Conto.user_id == current_user_id
    )
    
    # Conteggio totale per la paginazione nel frontend
    total = query.count()
    
    # Recupero dati della pagina specifica
    data = query.order_by(models.Transazione.data.desc()).offset(offset).limit(size).all()
    
    return {
        "total": total,
        "page": page,
        "size": size,
        "data": data
    }

@router.put("/{transazione_id}", response_model=schemas.TransazioneOut)
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

@router.delete("/{transazione_id}")
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

@router.get("/tag/{tag_id}")
def get_transazioni_by_tag(
    tag_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    return db.query(models.Transazione).join(models.Transazione.tags).filter(
        models.Tag.id == tag_id,
        models.Tag.user_id == current_user_id
    ).all()