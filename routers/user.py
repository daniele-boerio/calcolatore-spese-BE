from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas, auth
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime
from sqlalchemy import func, or_, and_

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
def get_current_month_expenses(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    user = db.query(models.User).filter(models.User.id == current_user_id).first()
    today = datetime.now()
    first_day = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 1. Somma di tutte le USCITE del mese
    total_out = db.query(func.sum(models.Transazione.importo)).join(models.Conto).filter(
        models.Conto.user_id == current_user_id,
        models.Transazione.tipo == "USCITA",
        models.Transazione.data >= first_day
    ).scalar() or 0.0

    # Somma RIMBORSI (Sottraggono dalle uscite)
    total_refunds = db.query(func.sum(models.Transazione.importo)).join(models.Conto).filter(
        models.Conto.user_id == current_user_id,
        models.Transazione.tipo == "RIMBORSO",
        models.Transazione.data >= first_day
    ).scalar() or 0.0

    # Spesa reale = Uscite - Rimborsi
    net_expenses = max(0, total_out - total_refunds)

    percentage = round((net_expenses / user.total_budget * 100), 1) if user.total_budget else None

    return {
        "monthly_budget": {
            "totalBudget": user.total_budget,
            "expenses": net_expenses, # Restituiamo il valore netto
            "percentage": percentage
        }
    }

@router.get("/expensesByCategory")
def get_expenses_by_category(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    today = datetime.now()
    first_day = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 1. Carichiamo le uscite normali
    uscite_per_cat = db.query(
        models.Categoria.nome.label("category"),
        func.sum(models.Transazione.importo).label("amount")
    ).join(models.Transazione).join(models.Conto).filter(
        models.Conto.user_id == current_user_id,
        models.Transazione.tipo == "USCITA",
        models.Transazione.data >= first_day
    ).group_by(models.Categoria.nome).all()

    stats = {row.category: float(row.amount) for row in uscite_per_cat}

    # 2. Carichiamo i rimborsi e troviamo a quale categoria del parent appartengono
    rimborsi = db.query(
        models.Transazione.importo,
        models.Transazione.parent_transaction_id
    ).join(models.Conto).filter(
        models.Conto.user_id == current_user_id,
        models.Transazione.tipo == "RIMBORSO",
        models.Transazione.data >= first_day,
        models.Transazione.parent_transaction_id != None
    ).all()

    for r in rimborsi:
        # Recuperiamo il parent per sapere la categoria da stornare
        parent = db.query(models.Transazione).filter(models.Transazione.id == r.parent_transaction_id).first()
        if parent and parent.categoria:
            cat_nome = parent.categoria.nome
            if cat_nome in stats:
                stats[cat_nome] -= float(r.importo)

    return [{"label": cat, "value": round(val, 2)} for cat, val in stats.items() if val > 0]