import secrets
import os
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
    BackgroundTasks,
)
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas import ForgotPasswordRequest, ResetPasswordRequest, Token
from rate_limit import limiter

import auth as auth_utils

# Assumo che tu abbia una funzione per hashare le password, es. pwd_context.hash()
from auth import get_password_hash

router = APIRouter(prefix="/auth", tags=["Auth"])

logger = logging.getLogger(__name__)


def send_reset_email(email_to: str, reset_link: str):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    email_from = os.getenv("EMAIL_FROM", "noreply@example.com")

    # Se le configurazioni SMTP non sono presenti, fai il mock (utile in sviluppo)
    if not smtp_server or not smtp_username or not smtp_password:
        logger.warning(
            "SMTP non configurato: email di reset SIMULATA (MOCK) per %s. "
            "Link di reset: %s",
            email_to,
            reset_link,
        )
        return

    try:
        msg = EmailMessage()
        msg.set_content(
            f"Ciao,\n\nHai richiesto il reset della tua password.\nClicca su questo link per impostarne una nuova:\n{reset_link}\n\nIl link scadrà tra 30 minuti.\n\nSe non hai richiesto tu il reset, ignora questa email."
        )
        msg["Subject"] = "Reset della tua password"
        msg["From"] = email_from
        msg["To"] = email_to

        with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
            logger.info("Email di reset inviata con successo a %s", email_to)
    except Exception as e:
        logger.error("Errore durante l'invio dell'email a %s: %s", email_to, e)


@router.post("/forgot-password")
@limiter.limit("3/hour")
def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,  # Usiamo BackgroundTasks per non bloccare la risposta
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == payload.email).first()

    # BEST PRACTICE DI SICUREZZA:
    # Anche se l'utente non esiste, restituiamo sempre "OK".
    # Così evitiamo che un malintenzionato scopra quali email sono registrate.
    if user:
        # 1. Genera un token sicuro e imposta la scadenza (es. 30 minuti)
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expiration = datetime.utcnow() + timedelta(minutes=30)

        db.commit()

        # 2. Costruisci il link dinamico puntando al frontend
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        # Rimuoviamo l'eventuale slash finale per evitare url doppi
        frontend_url = frontend_url.rstrip("/")
        reset_link = f"{frontend_url}/reset-password?token={token}"

        # 3. Invia l'email in background
        background_tasks.add_task(send_reset_email, user.email, reset_link)

    return {
        "message": "Se l'email è registrata, riceverai a breve un link per resettare la password."
    }


@router.post("/reset-password")
@limiter.limit("5/hour")
def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    # 1. Cerca l'utente tramite il token
    user = db.query(User).filter(User.reset_token == payload.token).first()

    # 2. Verifica se il token esiste ed è ancora valido
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Token invalido."
        )

    if user.reset_token_expiration < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Il token è scaduto. Richiedi un nuovo reset.",
        )

    # 3. Aggiorna la password (ricordati di farne l'hashing!)
    user.hashed_password = get_password_hash(payload.new_password)

    # Invalida i token di accesso esistenti incrementando la versione del token
    user.token_version = getattr(user, "token_version", 1) + 1

    # Chi cambia password si aspetta che le sessioni aperte altrove cadano:
    # senza questo, un refresh token rubato sopravvivrebbe al reset.
    auth_utils.revoke_all_user_tokens(db, user.id)

    # 4. Invalida il token per evitare che venga riutilizzato
    user.reset_token = None
    user.reset_token_expiration = None

    db.commit()

    return {"message": "Password aggiornata con successo. Ora puoi fare il login."}


@router.post("/refresh", response_model=Token)
@limiter.limit("60/minute")
def refresh_access_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Rinnova l'access token a partire dal cookie httpOnly.

    Il refresh token viene ruotato a ogni uso: quello vecchio è bruciato e ne
    viene emesso uno nuovo nella stessa famiglia. È quello che tiene l'utente
    loggato sul dispositivo senza mai riesporre le credenziali.
    """
    raw_token = auth_utils.get_refresh_token_from_request(request)

    db_token = auth_utils.consume_refresh_token(db, raw_token)

    user = db.query(User).filter(User.id == db_token.user_id).first()
    if not user:
        auth_utils.clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    new_raw_token = auth_utils.issue_refresh_token(
        db,
        user.id,
        user_agent=request.headers.get("user-agent"),
        family_id=db_token.family_id,
    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Errore durante la rotazione del refresh token")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not refresh the session",
        )

    auth_utils.set_refresh_cookie(response, new_raw_token)

    access_token = auth_utils.create_access_token(
        data={"user_id": user.id, "token_version": user.token_version}
    )
    return {"access_token": access_token, "username": user.username}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Chiude la sessione di QUESTO dispositivo (revoca la famiglia del cookie)."""
    raw_token = request.cookies.get(auth_utils.REFRESH_COOKIE_NAME)

    if raw_token and auth_utils.revoke_session(db, raw_token):
        db.commit()

    # Il cookie va rimosso comunque: un logout non deve mai fallire.
    auth_utils.clear_refresh_cookie(response)
    return {"message": "Logged out"}


@router.post("/logout-all")
def logout_all_devices(
    response: Response,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth_utils.get_current_user_id),
):
    """Disconnette l'utente da tutti i dispositivi."""
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    auth_utils.revoke_all_user_tokens(db, current_user_id)
    # Bruciamo anche gli access token già emessi, che altrimenti resterebbero
    # validi fino alla loro scadenza naturale.
    user.token_version = (user.token_version or 1) + 1
    db.commit()

    auth_utils.clear_refresh_cookie(response)
    return {"message": "Logged out from all devices"}
