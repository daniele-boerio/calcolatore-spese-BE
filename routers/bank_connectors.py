from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session
from database import get_db
import auth
from schemas.bank_transaction import (
    BankConnectorConfigCreate,
    BankConnectorConfigOut,
    BankConnectorConfigUpdate,
    BankConnectorSyncResponse,
    BankStatementImportResponse,
    BankTransactionProposalOut,
    BankTransactionProposalImport,
)
from schemas.transazione import TransazioneOut
from models import Conto, BankTransactionProposal, Categoria, Sottocategoria
from services import (
    fetch_bank_transactions_for_conto,
    create_bank_transaction_proposal,
    import_bank_transaction_proposal,
    discard_bank_transaction_proposal,
    parse_bank_statement_pdf,
    parse_bank_statement_spreadsheet,
    encrypt_token,
)
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

router = APIRouter(prefix="/conti/{conto_id}/bank-connector", tags=["BankConnector"])


def get_conto(db: Session, conto_id: int, user_id: int) -> Conto:
    conto = (
        db.query(Conto)
        .filter(
            Conto.id == conto_id,
            Conto.user_id == user_id,
            Conto.deleted_at.is_(None),
        )
        .first()
    )
    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or not authorized",
        )
    return conto


@router.get("", response_model=BankConnectorConfigOut)
def get_bank_connector_config(
    conto_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    conto = get_conto(db, conto_id, current_user_id)
    return BankConnectorConfigOut(
        provider=conto.bank_connector_provider,
        account_id=conto.bank_connector_account_id,
        institution_id=conto.bank_connector_institution_id,
        last_sync=conto.bank_connector_last_sync,
        last_error=conto.bank_connector_last_error,
    )


@router.post("", response_model=BankConnectorConfigOut)
def configure_bank_connector(
    conto_id: int,
    config: BankConnectorConfigCreate,
    db: Session = Depends(get_db),
    # Salvare le credenziali di una banca è riservato all'utente admin, come il
    # resto dell'Open Banking: senza questo gate qualsiasi account registrato
    # potrebbe collegare un conto bancario.
    current_user_id: int = Depends(auth.get_admin_user_id),
):
    conto = get_conto(db, conto_id, current_user_id)

    if config.provider == "NORDIGEN":
        if not config.account_id or not config.client_id or not config.secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nordigen configuration requires account_id, client_id and secret",
            )

    conto.bank_connector_provider = config.provider
    conto.bank_connector_account_id = config.account_id
    conto.bank_connector_institution_id = config.institution_id
    conto.bank_connector_client_id = config.client_id
    conto.bank_connector_secret = config.secret
    conto.bank_connector_access_token = encrypt_token(config.access_token)
    conto.bank_connector_refresh_token = encrypt_token(config.refresh_token)
    conto.bank_connector_last_error = None

    db.add(conto)
    db.commit()
    db.refresh(conto)

    return BankConnectorConfigOut(
        provider=conto.bank_connector_provider,
        account_id=conto.bank_connector_account_id,
        institution_id=conto.bank_connector_institution_id,
        last_sync=conto.bank_connector_last_sync,
        last_error=conto.bank_connector_last_error,
    )


@router.post("/sync", response_model=BankConnectorSyncResponse)
def sync_bank_connector(
    conto_id: int,
    db: Session = Depends(get_db),
    # Usa i token bancari salvati: stesso cancello del configure.
    current_user_id: int = Depends(auth.get_admin_user_id),
):
    conto = get_conto(db, conto_id, current_user_id)

    if not conto.bank_connector_provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bank connector is not configured for this account",
        )

    try:
        candidates = fetch_bank_transactions_for_conto(db, conto)
    except Exception as e:
        conto.bank_connector_last_error = str(e)
        db.add(conto)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch bank transactions: {str(e)}",
        )

    new_proposals = 0
    for candidate in candidates:
        proposal = create_bank_transaction_proposal(
            db, current_user_id, conto, candidate
        )
        if proposal:
            new_proposals += 1

    now = datetime.now(timezone.utc)
    conto.bank_connector_last_sync = now
    conto.bank_connector_last_error = None
    db.add(conto)
    db.commit()

    return BankConnectorSyncResponse(
        new_proposals=new_proposals, last_sync=now, until=now
    )


_STATEMENT_EXTS = (".pdf", ".xlsx", ".xls", ".csv")


@router.post("/import-statement", response_model=BankStatementImportResponse)
def import_bank_statement(
    conto_id: int,
    file: UploadFile = File(...),
    data_da: Optional[date] = Form(None),
    data_a: Optional[date] = Form(None),
    balance_column: bool = Form(False),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    """Importa un estratto conto (PDF, Excel .xlsx o CSV): ne estrae i movimenti
    (opzionalmente nel range data_da..data_a) e crea proposte PENDING, come una
    sincronizzazione bancaria. L'utente le rivede poi dal dialog delle proposte,
    assegnando categoria/sottocategoria/conto/tag prima di confermarle.

    Excel/CSV usano un parser a colonne (affidabile); il PDF un parser euristico
    (`balance_column` è rilevante solo per il PDF).
    """
    conto = get_conto(db, conto_id, current_user_id)

    filename = (file.filename or "").lower()
    if not filename.endswith(_STATEMENT_EXTS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The file must be a PDF, Excel (.xlsx) or CSV",
        )

    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty",
        )

    try:
        if filename.endswith(".pdf"):
            movimenti = parse_bank_statement_pdf(
                file_bytes,
                data_da=data_da,
                data_a=data_a,
                balance_column=balance_column,
            )
        else:
            movimenti = parse_bank_statement_spreadsheet(
                file_bytes,
                filename,
                data_da=data_da,
                data_a=data_a,
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not read the statement file: {str(e)}",
        )

    parsed = len(movimenti)
    new_proposals = 0
    try:
        for candidate in movimenti:
            # create_bank_transaction_proposal deduplica su (data, importo,
            # descrizione): reimportare lo stesso estratto non crea doppioni.
            if create_bank_transaction_proposal(
                db, current_user_id, conto, candidate
            ):
                new_proposals += 1
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save statement proposals: {str(e)}",
        )

    return BankStatementImportResponse(
        parsed=parsed,
        new_proposals=new_proposals,
        skipped=parsed - new_proposals,
    )


@router.get("/proposals", response_model=list[BankTransactionProposalOut])
def get_bank_transaction_proposals(
    conto_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    get_conto(db, conto_id, current_user_id)

    proposals = (
        db.query(BankTransactionProposal)
        .filter(
            BankTransactionProposal.conto_id == conto_id,
            BankTransactionProposal.user_id == current_user_id,
            BankTransactionProposal.status == "PENDING",
        )
        .order_by(BankTransactionProposal.creationDate.desc())
        .all()
    )
    return proposals


def update_category_usage(
    db: Session, categoria_id: int = None, sottocategoria_id: int = None
):
    now = datetime.now(timezone.utc)
    if categoria_id:
        db.query(Categoria).filter(Categoria.id == categoria_id).update(
            {"lastImport": now}
        )
    if sottocategoria_id:
        db.query(Sottocategoria).filter(Sottocategoria.id == sottocategoria_id).update(
            {"lastImport": now}
        )


@router.post("/proposals/{proposal_id}/import", response_model=TransazioneOut)
def import_bank_transaction_proposal_endpoint(
    conto_id: int,
    proposal_id: int,
    import_data: BankTransactionProposalImport,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    conto = get_conto(db, conto_id, current_user_id)
    proposal = (
        db.query(BankTransactionProposal)
        .filter(
            BankTransactionProposal.id == proposal_id,
            BankTransactionProposal.conto_id == conto_id,
            BankTransactionProposal.user_id == current_user_id,
        )
        .first()
    )

    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proposal not found",
        )

    if proposal.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PENDING proposals can be imported",
        )

    try:
        new_trans = import_bank_transaction_proposal(
            db, proposal, import_data, current_user_id
        )
        update_category_usage(
            db, import_data.categoria_id, import_data.sottocategoria_id
        )
        conto.lastImport = datetime.now(timezone.utc)
        db.add(conto)
        db.commit()
        db.refresh(new_trans)
        return new_trans
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import proposal: {str(e)}",
        )


@router.post("/proposals/{proposal_id}/discard")
def discard_bank_transaction_proposal_endpoint(
    conto_id: int,
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    get_conto(db, conto_id, current_user_id)
    proposal = (
        db.query(BankTransactionProposal)
        .filter(
            BankTransactionProposal.id == proposal_id,
            BankTransactionProposal.conto_id == conto_id,
            BankTransactionProposal.user_id == current_user_id,
        )
        .first()
    )

    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proposal not found",
        )

    if proposal.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PENDING proposals can be discarded",
        )

    discard_bank_transaction_proposal(db, proposal)
    db.commit()
    return {"message": "Proposal discarded"}
