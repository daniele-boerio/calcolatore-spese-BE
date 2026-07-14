from dotenv import load_dotenv
import bcrypt
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import SessionLocal
from models import RefreshToken, User

load_dotenv()

logger = logging.getLogger(__name__)

# L'access token è volutamente a vita breve: se viene rubato (es. XSS) la finestra
# di abuso è di minuti, non di giorni. La sessione lunga la regge il refresh token,
# che sta in un cookie httpOnly e non è leggibile da JavaScript.
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 90))

REFRESH_COOKIE_NAME = "refresh_token"
# Il refresh token serve solo agli endpoint di sessione: limitando il path, il
# cookie non viene nemmeno allegato alle altre chiamate API.
REFRESH_COOKIE_PATH = "/auth"


def get_password_hash(password: str):
    # Trasforma la stringa in byte, genera il sale e fa l'hash
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(pwd_bytes, salt)
    # Restituisce l'hash come stringa per salvarlo nel DB
    return hashed_password.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str):
    password_byte = plain_password.encode("utf-8")
    hashed_byte = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_byte, hashed_byte)


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, os.getenv("SECRET_KEY"), algorithm=os.getenv("ALGORITHM")
    )
    return encoded_jwt


# --- REFRESH TOKEN (sessione persistente per dispositivo) ---------------------


def _hash_refresh_token(raw_token: str) -> str:
    """SHA-256 del token. In DB non finisce mai il valore in chiaro.

    Qui basta un hash veloce (non bcrypt): il token è già 256 bit di entropia
    casuale, quindi non è attaccabile a dizionario come una password.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_refresh_token(
    db: Session,
    user_id: int,
    user_agent: str | None = None,
    family_id: str | None = None,
) -> str:
    """Crea un refresh token e ne salva solo l'hash. Restituisce il valore in chiaro
    (l'unico momento in cui esiste), da mettere nel cookie httpOnly.

    `family_id` viene passato in fase di rotazione per restare nella stessa catena.
    """
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    db_token = RefreshToken(
        user_id=user_id,
        token_hash=_hash_refresh_token(raw_token),
        family_id=family_id or secrets.token_urlsafe(32),
        expires_at=now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        created_at=now,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(db_token)
    return raw_token


def revoke_token_family(db: Session, user_id: int, family_id: str) -> None:
    """Revoca tutti i token di una famiglia (usata quando si sospetta un furto)."""
    now = datetime.now(timezone.utc)
    (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id,
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .update({"revoked_at": now})
    )


def revoke_session(db: Session, raw_token: str) -> bool:
    """Revoca la sessione a cui appartiene `raw_token` (logout del dispositivo).

    Non solleva se il token è ignoto: un logout deve riuscire comunque.
    """
    db_token = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == _hash_refresh_token(raw_token))
        .first()
    )
    if not db_token:
        return False

    revoke_token_family(db, db_token.user_id, db_token.family_id)
    return True


def revoke_all_user_tokens(db: Session, user_id: int) -> None:
    """Disconnette l'utente da tutti i dispositivi."""
    now = datetime.now(timezone.utc)
    (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .update({"revoked_at": now})
    )


def _as_utc(value: datetime) -> datetime:
    """Le colonne DateTime sono naive: le trattiamo come UTC per confrontarle."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def consume_refresh_token(db: Session, raw_token: str) -> RefreshToken:
    """Valida un refresh token e lo marca come usato (rotazione).

    Se il token è già stato usato siamo davanti a un replay: qualcuno ha copiato il
    cookie. Non possiamo sapere se sia la vittima o l'attaccante a presentarlo, quindi
    revochiamo l'intera famiglia e obblighiamo entrambi a rifare il login.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session",
    )

    db_token = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == _hash_refresh_token(raw_token))
        .first()
    )

    if not db_token:
        raise invalid

    if db_token.revoked_at is not None:
        raise invalid

    if db_token.used_at is not None:
        # Reuse detection: token già ruotato → sessione compromessa.
        logger.warning(
            "Riuso di un refresh token già ruotato (user_id=%s, family=%s): "
            "revoco l'intera famiglia",
            db_token.user_id,
            db_token.family_id,
        )
        revoke_token_family(db, db_token.user_id, db_token.family_id)
        db.commit()
        raise invalid

    if _as_utc(db_token.expires_at) < datetime.now(timezone.utc):
        raise invalid

    db_token.used_at = datetime.now(timezone.utc)
    db.add(db_token)
    return db_token


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    """Cookie httpOnly: illeggibile da JavaScript, quindi non rubabile via XSS.

    FE e BE stanno su due sottodomini dello stesso sito (conti/conti-be.spassocasa.it),
    quindi `SameSite=Lax` è sufficiente e il cookie viaggia comunque. In locale
    (http) `Secure` va spento, altrimenti il browser scarta il cookie.
    """
    secure = os.getenv("COOKIE_SECURE", "true").lower() != "false"
    domain = os.getenv("COOKIE_DOMAIN") or None

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        domain=domain,
    )


def clear_refresh_cookie(response: Response) -> None:
    secure = os.getenv("COOKIE_SECURE", "true").lower() != "false"
    domain = os.getenv("COOKIE_DOMAIN") or None

    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        domain=domain,
    )


def get_refresh_token_from_request(request: Request) -> str:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session cookie",
        )
    return raw_token


# --- ACCESS TOKEN -------------------------------------------------------------


def get_db_session():
    """Sessione DB per le dipendenze definite qui (evita l'import di database.get_db
    dentro auth.py, che è importato da database-adjacent modules)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


security = HTTPBearer()


# Per evitare un'importazione circolare in auth.py, passiamo una dipendenza lazy o creiamo get_current_user_id nel router
def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials  # Estrae automaticamente la stringa dopo 'Bearer '

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        secret = os.getenv("SECRET_KEY")
        algo = os.getenv("ALGORITHM")

        payload = jwt.decode(token, secret, algorithms=[algo])

        user_id: int = payload.get("user_id")
        token_version: int = payload.get("token_version", 1)

        if user_id is None:
            logger.debug("user_id non trovato nel payload del token")
            raise credentials_exception

        # Creiamo una sessione DB al volo per verificare la validità del token rispetto alla password cambiata
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user or user.token_version != token_version:
                logger.debug("token obsoleto o utente non trovato")
                raise credentials_exception
        finally:
            db.close()

        return user_id

    except JWTError:
        logger.debug("Token JWT non valido", exc_info=True)
        raise credentials_exception


def get_admin_user_id(
    db: Session = Depends(get_db_session),
    current_user_id: int = Depends(get_current_user_id),
) -> int:
    """L'Open Banking è riservato a un solo utente (l'admin).

    Vive qui e non in un router perché la usano sia `open_banking` (flusso Enable
    Banking) sia `bank_connectors` (che salva le credenziali della banca): sono le
    uniche parti che maneggiano token bancari, e devono avere lo stesso cancello.
    L'admin è identificato da OPEN_BANKING_ADMIN_EMAIL; se la variabile non c'è, la
    funzionalità è chiusa per tutti.
    """
    admin_email = os.getenv("OPEN_BANKING_ADMIN_EMAIL")
    if not admin_email:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Open Banking admin is not configured",
        )
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user or user.email.lower() != admin_email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Open Banking is restricted to the admin user",
        )
    return current_user_id
