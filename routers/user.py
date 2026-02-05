from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from routers.conti import get_current_month_expenses
import auth
from fastapi.security import OAuth2PasswordRequestForm
from models import User
from schemas import Token, UserCreate, UserBudgetUpdate, UserResponse

router = APIRouter(tags=["User"])

# --- ENDPOINT UTENTI ---


@router.post("/register", response_model=Token)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    # Controllo campi obbligatori
    if not user.username or not user.password or not user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing fields. Please provide username, email, and password",
        )

    # Normalizzazione input
    email_lower = user.email.lower()
    username_lower = user.username.lower()

    # 1. Controllo duplicati
    if db.query(User).filter(User.email == email_lower).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The email address you entered is already associated with an account",
        )

    if db.query(User).filter(User.username == username_lower).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The username you selected is not available",
        )

    # 2. Creazione Utente
    try:
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

        return {"access_token": access_token, "username": new_user.username}
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating your account. Please try again later",
        )


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    if not form_data.username or not form_data.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required",
        )

    username_lower = form_data.username.lower()
    user = db.query(User).filter(User.username == username_lower).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not found. Please verify your username",
        )

    if not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect password. Try again",
        )

    access_token = auth.create_access_token(data={"user_id": user.id})

    return {"access_token": access_token, "username": user.username}


@router.get("/me", response_model=UserResponse)
def get_me(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Your session may have expired",
        )

    return user


@router.put("/monthlyBudget")
def update_monthly_budget(
    budget_data: UserBudgetUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User account not found"
        )

    try:
        # Aggiornamento budget
        user.total_budget = budget_data.totalBudget
        db.commit()

        # Restituiamo i dati aggiornati
        return get_current_month_expenses(db, current_user_id)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update monthly budget",
        )
