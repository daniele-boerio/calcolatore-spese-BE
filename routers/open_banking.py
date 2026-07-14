import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import auth
from database import get_db
from models import Conto, User
from schemas import ContoOut
from schemas.open_banking import (
    InstitutionOut,
    BankAuthStart,
    BankAuthStartResponse,
    BankSessionConfirm,
    BankSessionConfirmResponse,
)
from services import (
    list_enable_banking_aspsps,
    start_enable_banking_auth,
    create_enable_banking_session,
)

router = APIRouter(prefix="/open-banking", tags=["OpenBanking"])


# Il gate admin vive in auth.py: lo condividono questo router e bank_connectors,
# così esiste un solo cancello per tutto ciò che tocca le banche.
get_admin_user_id = auth.get_admin_user_id


def get_conto(db: Session, conto_id: int, user_id: int) -> Conto:
    conto = (
        db.query(Conto).filter(Conto.id == conto_id, Conto.user_id == user_id).first()
    )
    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or not authorized",
        )
    return conto


@router.get("/institutions", response_model=list[InstitutionOut])
def get_institutions(
    country: str = "IT",
    current_user_id: int = Depends(get_admin_user_id),
):
    """Step 1 support: list the banks (ASPSPs) the user can pick from."""
    try:
        return list_enable_banking_aspsps(country)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch institutions: {str(e)}",
        )


@router.post("/auth", response_model=BankAuthStartResponse)
def start_bank_auth(
    payload: BankAuthStart,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_admin_user_id),
):
    """Step 2: start the Enable Banking authorization and return the bank URL.

    We generate a unique `state`, persist it on the conto and send it to Enable
    Banking; the bank echoes it back to the FE callback so we can match it.
    """
    conto = get_conto(db, payload.conto_id, current_user_id)

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    redirect_url = f"{frontend_url}/bank-callback"
    state = secrets.token_urlsafe(16)

    try:
        result = start_enable_banking_auth(
            payload.aspsp_name, payload.aspsp_country, redirect_url, state
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to start bank authorization: {str(e)}",
        )

    url = result.get("url")
    if not url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Bank authorization did not return a URL",
        )

    conto.bank_connector_provider = "ENABLEBANKING"
    conto.bank_connector_institution_id = payload.aspsp_name
    conto.bank_connector_auth_state = state
    conto.bank_connector_session_id = None
    conto.bank_connector_account_id = None
    conto.bank_connector_last_error = None
    db.add(conto)
    db.commit()

    return BankAuthStartResponse(url=url)


@router.post("/sessions", response_model=BankSessionConfirmResponse)
def confirm_bank_session(
    payload: BankSessionConfirm,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_admin_user_id),
):
    """Step 6: the handshake. Match the callback `state` to the pending conto,
    exchange the `code` for a session and store the linked account uid."""
    conto = (
        db.query(Conto)
        .filter(
            Conto.bank_connector_auth_state == payload.state,
            Conto.user_id == current_user_id,
        )
        .first()
    )
    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending bank link found for this state",
        )

    try:
        session = create_enable_banking_session(payload.code)
    except Exception as e:
        conto.bank_connector_last_error = str(e)
        db.add(conto)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create bank session: {str(e)}",
        )

    accounts = session.get("accounts") or []
    if not accounts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bank link completed but no accounts were returned",
        )

    account_uid = accounts[0].get("uid")
    if not account_uid:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Bank session did not return an account id",
        )

    conto.bank_connector_account_id = account_uid
    conto.bank_connector_session_id = session.get("session_id")
    conto.bank_connector_auth_state = None
    conto.bank_connector_last_error = None
    db.add(conto)
    db.commit()

    return BankSessionConfirmResponse(
        conto_id=conto.id,
        account_id=account_uid,
        status="LINKED",
    )


@router.delete("/link/{conto_id}", response_model=ContoOut)
def disconnect_bank(
    conto_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_admin_user_id),
):
    """Scollega il conto dalla banca: azzera tutti i riferimenti al connettore
    così il conto torna 'non collegato' (e si può eventualmente ricollegare)."""
    conto = get_conto(db, conto_id, current_user_id)

    conto.bank_connector_provider = None
    conto.bank_connector_institution_id = None
    conto.bank_connector_account_id = None
    conto.bank_connector_session_id = None
    conto.bank_connector_auth_state = None
    conto.bank_connector_last_error = None
    db.add(conto)
    db.commit()
    db.refresh(conto)

    return conto
