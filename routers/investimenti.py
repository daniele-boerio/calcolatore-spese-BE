from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas, auth

router = APIRouter(
    prefix="/investimenti",      # Tutti gli endpoint in questo file inizieranno con /investimenti
    tags=["Investimenti"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT INVESTIMENTI ---

@router.post("", response_model=schemas.InvestimentoOut)
def create_investimento(investimento: schemas.InvestimentoCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    # Evitiamo duplicati dello stesso ISIN per lo stesso utente
    existing = db.query(models.Investimento).filter(
        models.Investimento.isin == investimento.isin, 
        models.Investimento.user_id == current_user_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"Il titolo con ISIN {investimento.isin} è già presente nel tuo portafoglio.")

    new_invest = models.Investimento(**investimento.model_dump(), user_id=current_user_id)
    db.add(new_invest)
    db.commit()
    db.refresh(new_invest)
    return new_invest

@router.get("", response_model=list[schemas.InvestimentoOut])
def get_investimenti(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    # Recupera tutti i titoli posseduti dall'utente
    return db.query(models.Investimento).filter(models.Investimento.user_id == current_user_id).all()

@router.post("/operazione", response_model=schemas.StoricoInvestimentoOut)
def add_operazione_investimento(
    operazione: schemas.StoricoInvestimentoCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Controllo sicurezza: l'investimento appartiene all'utente loggato?
    investimento = db.query(models.Investimento).filter(
        models.Investimento.id == operazione.investimento_id,
        models.Investimento.user_id == current_user_id
    ).first()
    
    if not investimento:
        raise HTTPException(status_code=404, detail="Investimento non trovato o non autorizzato")

    new_record = models.StoricoInvestimento(**operazione.model_dump())
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return new_record

@router.put("/operazione/{operazione_id}", response_model=schemas.StoricoInvestimentoOut)
def update_operazione_investimento(
    operazione_id: int,
    operazione_data: schemas.StoricoInvestimentoCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Verifichiamo che l'operazione esista e che l'investimento collegato appartenga all'utente
    db_operazione = db.query(models.StoricoInvestimento).join(models.Investimento).filter(
        models.StoricoInvestimento.id == operazione_id,
        models.Investimento.user_id == current_user_id
    ).first()

    if not db_operazione:
        raise HTTPException(status_code=404, detail="Operazione non trovata o non autorizzata")

    # Aggiorniamo i dati
    for key, value in operazione_data.model_dump().items():
        setattr(db_operazione, key, value)

    db.commit()
    db.refresh(db_operazione)
    return db_operazione

@router.delete("/operazione/{operazione_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_operazione_investimento(
    operazione_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_operazione = db.query(models.StoricoInvestimento).join(models.Investimento).filter(
        models.StoricoInvestimento.id == operazione_id,
        models.Investimento.user_id == current_user_id
    ).first()

    if not db_operazione:
        raise HTTPException(status_code=404, detail="Operazione non trovata")

    db.delete(db_operazione)
    db.commit()
    return None

@router.put("/{investimento_id}", response_model=schemas.InvestimentoOut)
def update_investimento(
    investimento_id: int,
    investimento_data: schemas.InvestimentoCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_investimento = db.query(models.Investimento).filter(
        models.Investimento.id == investimento_id,
        models.Investimento.user_id == current_user_id
    ).first()

    if not db_investimento:
        raise HTTPException(status_code=404, detail="Investimento non trovato")

    for key, value in investimento_data.model_dump().items():
        setattr(db_investimento, key, value)

    db.commit()
    db.refresh(db_investimento)
    return db_investimento

@router.delete("/{investimento_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_investimento(
    investimento_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_investimento = db.query(models.Investimento).filter(
        models.Investimento.id == investimento_id,
        models.Investimento.user_id == current_user_id
    ).first()

    if not db_investimento:
        raise HTTPException(status_code=404, detail="Investimento non trovato")

    # Grazie al cascade="all, delete-orphan" impostato nel modello, 
    # cancellando l'investimento verranno cancellate automaticamente 
    # anche tutte le sue operazioni nello storico.
    db.delete(db_investimento)
    db.commit()
    return None