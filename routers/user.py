from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from routers.conti import get_current_month_expenses
import auth
from fastapi.security import OAuth2PasswordRequestForm
from models import User
from schemas import Token, UserCreate, UserBudgetUpdate, UserResponse

router = APIRouter(
    tags=["User"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT UTENTI ---

@router.post("/register", response_model=Token)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    # Normalizziamo input in lowercase
    email_lower = user.email.lower()
    username_lower = user.username.lower()

    # 1. Controllo duplicati usando i valori normalizzati
    if db.query(User).filter(User.email == email_lower).first():
        raise HTTPException(status_code=400, detail="L'indirizzo email inserito è già associato a un account.")
    
    if db.query(User).filter(User.username == username_lower).first():
        raise HTTPException(status_code=400, detail="Lo username scelto non è disponibile.")
    
    # 2. Hash della password e creazione utente con dati lowercase
    hashed_pwd = auth.get_password_hash(user.password)
    new_user = User(
        email=email_lower, 
        username=username_lower, 
        hashed_password=hashed_pwd,
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    access_token = auth.create_access_token(data={"user_id": new_user.id})
    
    return {
        "access_token": access_token,
        "username": new_user.username # Restituisce il valore lowercase salvato
    }

@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Trasformiamo lo username in lowercase per il confronto nel DB
    username_lower = form_data.username.lower()
    
    user = db.query(User).filter(User.username == username_lower).first()
    
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

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(auth.get_current_user)):
    """
    Verifica la validità del token e restituisce i dati dell'utente loggato.
    Se il token è invalido o scaduto, 'get_current_user' solleverà 
    automaticamente un'eccezione 401.
    """
    return current_user

@router.put("/monthlyBudget")
def update_monthly_budget(
    budget_data: UserBudgetUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    user = db.query(User).filter(User.id == current_user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # Aggiorniamo il budget nel database
    user.total_budget = budget_data.totalBudget
    db.commit()
    
    # Restituiamo i dati aggiornati (richiamando la logica di calcolo)
    return get_current_month_expenses(db, current_user_id)