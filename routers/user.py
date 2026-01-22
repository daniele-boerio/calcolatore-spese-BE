from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from database import get_db
import models, schemas, auth
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime
from sqlalchemy import func, case

from schemas.transazione import TipoTransazione

router = APIRouter(
    tags=["User"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT UTENTI ---

@router.post("/register", response_model=schemas.Token)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # 1. Controllo duplicati
    if db.query(models.User).filter(models.User.email == user.email).first():
        raise HTTPException(status_code=400, detail="L'indirizzo email inserito è già associato a un account.")
    
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Lo username scelto non è disponibile.")
    
    # 2. Hash della password e creazione utente
    hashed_pwd = auth.get_password_hash(user.password)
    new_user = models.User(
        email=user.email, 
        username=user.username, 
        hashed_password=hashed_pwd
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # 3. Generazione Token per login automatico
    access_token = auth.create_access_token(data={"user_id": new_user.id})
    
    return {
        "access_token": access_token,
        "username": new_user.username
    }

@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Cerchiamo l'utente direttamente tramite lo username
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Account non trovato. Verifica lo username inserito."
        )
    
    if not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Password errata. Riprova."
        )
    
    access_token = auth.create_access_token(data={"user_id": user.id})
    
    return {
        "access_token": access_token,
        "username": user.username
    }

@router.get("/currentMonthExpenses")
def get_current_month_expenses(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    user = db.query(models.User).filter(models.User.id == current_user_id).first()
    
    # Calcolo dell'intervallo temporale (inizio mese corrente)
    today = datetime.now()
    first_day = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 1. Calcoliamo il totale delle USCITE
    total_out = db.query(func.sum(models.Transazione.importo))\
        .join(models.Conto)\
        .filter(
            models.Conto.user_id == current_user_id,
            models.Transazione.tipo == TipoTransazione.USCITA,
            models.Transazione.data >= first_day
        ).scalar() or 0.0

    # 2. Calcoliamo il totale dei RIMBORSI
    # Nota: qui non ci interessa a quale categoria appartengano, 
    # perché il rimborso è un recupero di liquidità totale sul mese.
    total_refunds = db.query(func.sum(models.Transazione.importo))\
        .join(models.Conto)\
        .filter(
            models.Conto.user_id == current_user_id,
            models.Transazione.tipo == TipoTransazione.RIMBORSO,
            models.Transazione.data >= first_day
        ).scalar() or 0.0

    # Spesa netta reale
    net_expenses = max(0, total_out - total_refunds)

    # Calcolo percentuale rispetto al budget totale dell'utente
    percentage = None
    if user.total_budget and user.total_budget > 0:
        percentage = round((net_expenses / user.total_budget * 100), 1)

    return {
        "monthly_budget": {
            "totalBudget": user.total_budget,
            "expenses": round(net_expenses, 2),
            "percentage": percentage
        }
    }

@router.get("/expensesByCategory")
def get_expenses_by_category(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    today = datetime.now()
    first_day = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Recuperiamo le USCITE del mese
    # Usando joinedload(models.Transazione.rimborsi) carichiamo i rimborsi in un'unica query (ottimizzazione)
    uscite = db.query(models.Transazione).options(
        joinedload(models.Transazione.rimborsi)
    ).join(models.Conto).filter(
        models.Conto.user_id == current_user_id,
        models.Transazione.tipo == TipoTransazione.USCITA,
        models.Transazione.data >= first_day
    ).all()

    stats = {}

    for u in uscite:
        cat_nome = u.categoria.nome if u.categoria else "Senza Categoria"
        
        # Calcoliamo il totale dei rimborsi per QUESTA specifica transazione
        # Accediamo a u.rimborsi grazie alla relationship nel modello
        totale_rimborsi = sum(r.importo for r in u.rimborsi)
        
        # Il valore netto per questa transazione
        importo_netto = u.importo - totale_rimborsi
        
        if cat_nome not in stats:
            stats[cat_nome] = 0.0
        stats[cat_nome] += importo_netto

    # Formattazione per il frontend
    return [
        {"label": cat, "value": round(val, 2)} 
        for cat, val in stats.items() if val > 0
    ]