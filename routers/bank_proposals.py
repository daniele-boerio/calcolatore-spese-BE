from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import auth
from database import get_db
from models import BankTransactionProposal
from schemas.bank_transaction import BankTransactionProposalOut

# Endpoint "flat": il FE con UNA sola chiamata sa se ci sono proposte pendenti
# su QUALSIASI conto dell'utente (per il controllo automatico al landing).
router = APIRouter(prefix="/bank-proposals", tags=["BankConnector"])


@router.get("", response_model=list[BankTransactionProposalOut])
def get_all_pending_proposals(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    return (
        db.query(BankTransactionProposal)
        .filter(
            BankTransactionProposal.user_id == current_user_id,
            BankTransactionProposal.status == "PENDING",
        )
        .order_by(BankTransactionProposal.data.desc())
        .all()
    )
