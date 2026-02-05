from dotenv import load_dotenv
import bcrypt
import os
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()


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
    expire = datetime.utcnow() + timedelta(
        minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, os.getenv("SECRET_KEY"), algorithm=os.getenv("ALGORITHM")
    )
    return encoded_jwt


security = HTTPBearer()


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

        # Ora il print DEVE apparire perché HTTPBearer è meno restrittivo all'ingresso
        payload = jwt.decode(token, secret, algorithms=[algo])
        print(f"DEBUG - PAYLOAD DECODIFICATO: {payload}")

        user_id: int = payload.get("user_id")
        if user_id is None:
            print("DEBUG - user_id non trovato nel payload")
            raise credentials_exception

        return user_id

    except JWTError as e:
        print(f"DEBUG - Errore JWT: {str(e)}")
        raise credentials_exception
