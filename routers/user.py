import os
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from database import get_db
from routers.conti import get_current_month_expenses
import auth
from fastapi.security import OAuth2PasswordRequestForm
from models import User
from schemas import Token, UserCreate, UserBudgetUpdate, UserResponse
from rate_limit import limiter

router = APIRouter(tags=["User"])

# Hash bcrypt di una password fittizia. Serve a far pagare a un login con utente
# inesistente lo stesso costo di uno con utente reale: senza, il tempo di risposta
# rivela quali account esistono.
_DUMMY_PASSWORD_HASH = auth.get_password_hash("dummy-password-for-timing-safety")

# --- ENDPOINT UTENTI ---


@router.post("/register", response_model=Token)
@limiter.limit("5/hour")
def register_user(
    user: UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
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

        # Come il login: il nuovo utente parte già con la sessione del dispositivo
        raw_refresh = auth.issue_refresh_token(
            db, new_user.id, user_agent=request.headers.get("user-agent")
        )
        db.commit()
        auth.set_refresh_cookie(response, raw_refresh)

        access_token = auth.create_access_token(
            data={
                "user_id": new_user.id,
                "token_version": getattr(new_user, "token_version", 1),
            }
        )

        return {"access_token": access_token, "username": new_user.username}
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating your account. Please try again later",
        )


@router.post("/login", response_model=Token)
@limiter.limit("10/minute;50/hour")
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    if not form_data.username or not form_data.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required",
        )

    # Il campo si chiama "username" in OAuth2PasswordRequestForm, ma può contenere sia username che email
    login_identifier = form_data.username.lower()

    # Cerchiamo l'utente sia per username che per email usando or_
    from sqlalchemy import or_

    user = (
        db.query(User)
        .filter(or_(User.username == login_identifier, User.email == login_identifier))
        .first()
    )

    # Utente inesistente e password errata devono essere indistinguibili, sia nel
    # messaggio sia nel tempo di risposta: altrimenti /login diventa un oracolo per
    # scoprire quali email/username sono registrati. Se l'utente non c'è, verifichiamo
    # comunque la password contro un hash fittizio per pagare lo stesso costo bcrypt.
    if user:
        password_ok = auth.verify_password(form_data.password, user.hashed_password)
    else:
        auth.verify_password(form_data.password, _DUMMY_PASSWORD_HASH)
        password_ok = False

    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Sessione persistente del dispositivo: refresh token in cookie httpOnly
    raw_refresh = auth.issue_refresh_token(
        db, user.id, user_agent=request.headers.get("user-agent")
    )
    db.commit()
    auth.set_refresh_cookie(response, raw_refresh)

    # Inseriamo la token_version nel JWT per validarla successivamente
    access_token = auth.create_access_token(
        data={"user_id": user.id, "token_version": user.token_version}
    )

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

    admin_email = os.getenv("OPEN_BANKING_ADMIN_EMAIL")
    is_open_banking_admin = bool(
        admin_email and user.email.lower() == admin_email.strip().lower()
    )

    response = UserResponse.model_validate(user)
    response.is_open_banking_admin = is_open_banking_admin
    return response


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
        user.total_budget = budget_data.total_budget
        db.commit()

        # Restituiamo i dati aggiornati
        return get_current_month_expenses(db, current_user_id)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update monthly budget",
        )
