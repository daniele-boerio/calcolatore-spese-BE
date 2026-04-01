import secrets
import os
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas import ForgotPasswordRequest, ResetPasswordRequest

# Assumo che tu abbia una funzione per hashare le password, es. pwd_context.hash()
from auth import get_password_hash

router = APIRouter(prefix="/auth", tags=["Auth"])


def send_reset_email(email_to: str, reset_link: str):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    email_from = os.getenv("EMAIL_FROM", "noreply@example.com")

    # Se le configurazioni SMTP non sono presenti, fai il mock (utile in sviluppo)
    if not smtp_server or not smtp_username or not smtp_password:
        print("\n" + "=" * 50)
        print("!!! AVVISO: SMTP NON CONFIGURATO. MOCK EMAIL !!!")
        print(f"EMAIL SIMULATA INVIATA A: {email_to}")
        print("Oggetto: Reset della tua password")
        print(f"Clicca su questo link per resettare la password: \n{reset_link}")
        print("=" * 50 + "\n")
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
            print(f"Email di reset inviata con successo a {email_to}")
    except Exception as e:
        print(f"Errore durante l'invio dell'email a {email_to}: {e}")


@router.post("/forgot-password")
def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,  # Usiamo BackgroundTasks per non bloccare la risposta
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == request.email).first()

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
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    # 1. Cerca l'utente tramite il token
    user = db.query(User).filter(User.reset_token == request.token).first()

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
    user.hashed_password = get_password_hash(request.new_password)

    # Invalida i token di accesso esistenti incrementando la versione del token
    user.token_version = getattr(user, "token_version", 1) + 1

    # 4. Invalida il token per evitare che venga riutilizzato
    user.reset_token = None
    user.reset_token_expiration = None

    db.commit()

    return {"message": "Password aggiornata con successo. Ora puoi fare il login."}
