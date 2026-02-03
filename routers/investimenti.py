from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Investimento, StoricoInvestimento
from schemas.investimento import (
    InvestimentoCreate, InvestimentoOut, InvestimentoUpdate,
    StoricoInvestimentoCreate, StoricoInvestimentoOut, StoricoInvestimentoUpdate
)

router = APIRouter(
    prefix="/investimenti",
    tags=["Investimenti"]
)

# 1. GET ALL - Recupera tutti gli investimenti dell'utente
@router.get("", response_model=list[InvestimentoOut])
def get_investimenti(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    return db.query(Investimento).filter(Investimento.user_id == current_user_id).all()

# 2. GET SINGLE - Recupera i dettagli di un singolo investimento
@router.get("/{id}", response_model=InvestimentoOut)
def get_investimento(id: int, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    invest = db.query(Investimento).filter(Investimento.id == id, Investimento.user_id == current_user_id).first()
    if not invest:
        raise HTTPException(status_code=404, detail="Investimento non trovato")
    return invest

# 3. POST - Crea investimento + Operazione Iniziale
@router.post("", response_model=InvestimentoOut)
def create_investimento(payload: InvestimentoCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    # Controllo duplicati ISIN
    existing = db.query(Investimento).filter(Investimento.isin == payload.isin, Investimento.user_id == current_user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="ISIN già presente in portafoglio")

    # Creazione anagrafica titolo
    new_invest = Investimento(
        isin=payload.isin,
        ticker=payload.ticker,
        nome_titolo=payload.nome_titolo,
        user_id=current_user_id
    )
    db.add(new_invest)
    db.flush() # Per ottenere l'ID prima del commit finale

    # Creazione operazione iniziale
    op_iniziale = StoricoInvestimento(
        investimento_id=new_invest.id,
        data=payload.data_iniziale,
        quantita=payload.quantita_iniziale,
        prezzo_unitario=payload.prezzo_carico_iniziale
    )
    db.add(op_iniziale)
    db.commit()
    db.refresh(new_invest)
    return new_invest

# 4. PATCH - Modifica anagrafica (Nome, ISIN, Ticker)
@router.patch("/{id}", response_model=InvestimentoOut)
def patch_investimento(id: int, payload: InvestimentoUpdate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    db_invest = db.query(Investimento).filter(Investimento.id == id, Investimento.user_id == current_user_id).first()
    if not db_invest:
        raise HTTPException(status_code=404, detail="Investimento non trovato")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_invest, key, value)
    
    db.commit()
    db.refresh(db_invest)
    return db_invest

# 5. DELETE - Elimina investimento e tutto lo storico (cascade)
@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_investimento(id: int, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    db_invest = db.query(Investimento).filter(Investimento.id == id, Investimento.user_id == current_user_id).first()
    if not db_invest:
        raise HTTPException(status_code=404, detail="Investimento non trovato")
    db.delete(db_invest)
    db.commit()
    return None

# --- OPERAZIONI (STORICO) ---

# 6. POST - Aggiunta operazione (Acquisto/Vendita)
@router.post("/{id}/operazione", response_model=StoricoInvestimentoOut)
def add_operazione(
    id: int, 
    payload: StoricoInvestimentoCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # 1. Verifica che l'investimento appartenga all'utente
    invest = db.query(Investimento).filter(
        Investimento.id == id, 
        Investimento.user_id == current_user_id
    ).first()
    
    if not invest:
        raise HTTPException(status_code=404, detail="Investimento non trovato")

    # 2. Crea l'operazione associando l'ID dell'URL
    # Calcoliamo anche il valore_attuale se non passato dal FE
    new_op = StoricoInvestimento(
        **payload.model_dump(),
        investimento_id=id,  # Preso dall'URL
        valore_attuale=payload.quantita * payload.prezzo_unitario
    )
    
    db.add(new_op)
    db.commit()
    db.refresh(new_op)
    return new_op

# 7. PUT - Modifica un'operazione esistente
@router.put("/{id}/operazione/{op_id}", response_model=StoricoInvestimentoOut)
def update_operazione(
    id: int, 
    op_id: int, 
    payload: StoricoInvestimentoUpdate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_op = db.query(StoricoInvestimento).join(Investimento).filter(
        StoricoInvestimento.id == op_id,
        StoricoInvestimento.investimento_id == id,
        Investimento.user_id == current_user_id
    ).first()

    if not db_op:
        raise HTTPException(status_code=404, detail="Operazione non trovata per questo investimento")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_op, key, value)
    
    # Ricalcoliamo il valore attuale nel caso siano cambiati quantità o prezzo
    db_op.valore_attuale = db_op.quantita * db_op.prezzo_unitario
    
    db.commit()
    db.refresh(db_op)
    return db_op

# 8. DELETE - Elimina un'operazione
@router.delete("/{id}/operazione/{op_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_operazione(
    id: int, 
    op_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_op = db.query(StoricoInvestimento).join(Investimento).filter(
        StoricoInvestimento.id == op_id,
        StoricoInvestimento.investimento_id == id,
        Investimento.user_id == current_user_id
    ).first()

    if not db_op:
        raise HTTPException(status_code=404, detail="Operazione non trovata")
        
    db.delete(db_op)
    db.commit()
    return None