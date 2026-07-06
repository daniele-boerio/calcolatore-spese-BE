from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, case
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Conto, Transazione, User, Ricorrenza
from schemas import ContoCreate, ContoOut, ContoUpdate, ContoFilters
from schemas.transazione import TipoTransazione
from services import apply_filters_and_sort
import calendar
from decimal import Decimal

router = APIRouter(prefix="/conti", tags=["Conti"])

# --- ENDPOINT CONTI ---


def reset_default_account(db: Session, user_id: int):
    """Imposta a False il campo default per tutti i conti dell'utente."""
    db.query(Conto).filter(Conto.user_id == user_id, Conto.default).update(
        {"default": False}
    )


@router.post("", response_model=ContoOut)
def create_conto(
    conto: ContoCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # Se è indicato un conto sorgente (ricarica automatica), dev'essere dell'utente
    if conto.conto_sorgente_id is not None:
        sorgente = (
            db.query(Conto)
            .filter(
                Conto.id == conto.conto_sorgente_id,
                Conto.user_id == current_user_id,
                Conto.deleted_at.is_(None),
            )
            .first()
        )
        if not sorgente:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source account not found or unauthorized",
            )

    try:
        if conto.default:
            reset_default_account(db, current_user_id)

        new_conto = Conto(**conto.model_dump(), user_id=current_user_id)
        db.add(new_conto)
        db.commit()
        db.refresh(new_conto)
        return new_conto
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the account",
        )


@router.get("", response_model=list[ContoOut])
def get_conti(
    filters: ContoFilters = Depends(),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    query = db.query(Conto).filter(Conto.user_id == current_user_id)

    query = apply_filters_and_sort(
        query,
        Conto,
        filters=filters,
    )

    return query.all()


@router.put("/{conto_id}", response_model=ContoOut)
def update_conto(
    conto_id: int,
    conto_data: ContoUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_conto = (
        db.query(Conto)
        .filter(
            Conto.id == conto_id,
            Conto.user_id == current_user_id,
            Conto.deleted_at.is_(None),
        )
        .first()
    )

    if not db_conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or unauthorized",
        )

    update_data = conto_data.model_dump(exclude_unset=True)

    # Se si imposta un conto sorgente, dev'essere dell'utente (e non sé stesso).
    # Fatto FUORI dal try: gli HTTPException qui non vanno mascherati come 500.
    if update_data.get("conto_sorgente_id") is not None:
        if update_data["conto_sorgente_id"] == conto_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account cannot be its own source",
            )
        sorgente = (
            db.query(Conto)
            .filter(
                Conto.id == update_data["conto_sorgente_id"],
                Conto.user_id == current_user_id,
                Conto.deleted_at.is_(None),
            )
            .first()
        )
        if not sorgente:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source account not found or unauthorized",
            )

    try:
        if update_data.get("default") is True:
            reset_default_account(db, current_user_id)

        for key, value in update_data.items():
            setattr(db_conto, key, value)

        db.commit()
        db.refresh(db_conto)
        return db_conto
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update account details",
        )


@router.delete("/{conto_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conto(
    conto_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_conto = (
        db.query(Conto)
        .filter(
            Conto.id == conto_id,
            Conto.user_id == current_user_id,
            Conto.deleted_at.is_(None),
        )
        .first()
    )

    if not db_conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        )

    try:
        now = datetime.now(timezone.utc)

        # SOFT-DELETE: nascondiamo il conto e le sue transazioni, senza cancellarle.
        # Restano nel DB e sono ripristinabili con POST /conti/{id}/restore.
        # (Storicamente qui c'era un DELETE fisico che, via ON DELETE CASCADE,
        # distruggeva IRREVERSIBILMENTE tutte le transazioni del conto: un click
        # accidentale bruciava lo storico. Ora niente più.)
        #
        # Non tocchiamo ricorrenze né i riferimenti conto_sorgente: gli scheduler
        # saltano i conti con deleted_at valorizzato, quindi tutto resta coerente e
        # completamente reversibile al restore.
        db.query(Transazione).filter(
            Transazione.conto_id == conto_id,
            Transazione.user_id == current_user_id,
            Transazione.deleted_at.is_(None),
        ).update({"deleted_at": now}, synchronize_session=False)

        db_conto.deleted_at = now

        db.commit()
        return None
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the account",
        )


@router.post("/{conto_id}/restore", response_model=ContoOut)
def restore_conto(
    conto_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    """Ripristina un conto in soft-delete (e le transazioni nascoste insieme a esso).

    Rete di sicurezza per le cancellazioni accidentali: non c'è una UI dedicata,
    si invoca direttamente (es. dalla pagina /docs o via curl).
    """
    db_conto = (
        db.query(Conto)
        .filter(
            Conto.id == conto_id,
            Conto.user_id == current_user_id,
            Conto.deleted_at.isnot(None),
        )
        .first()
    )

    if not db_conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deleted account not found",
        )

    try:
        # Ripristiniamo SOLO le transazioni nascoste nello stesso istante in cui il
        # conto è stato cancellato (stesso timestamp), così non "resuscitiamo"
        # righe nascoste da un'altra operazione.
        deleted_marker = db_conto.deleted_at
        db.query(Transazione).filter(
            Transazione.conto_id == conto_id,
            Transazione.user_id == current_user_id,
            Transazione.deleted_at == deleted_marker,
        ).update({"deleted_at": None}, synchronize_session=False)

        db_conto.deleted_at = None

        db.commit()
        db.refresh(db_conto)
        return db_conto
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while restoring the account",
        )


@router.get("/currentMonthExpenses")
def get_current_month_expenses(
    include_future_recurring: bool = Query(
        False,
        description="Include future active recurring expenses within the current month",
    ),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    user = db.query(User).filter(User.id == current_user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User session invalid or account not found",
        )

    # Calcolo del range del mese corrente
    today = date.today()
    first_day = today.replace(day=1)
    # monthrange restituisce (giorno_settimana_inizio, numero_giorni_nel_mese)
    _, last_day_num = calendar.monthrange(today.year, today.month)
    last_day = today.replace(day=last_day_num)

    amount_expr = func.coalesce(Transazione.importo_netto, Transazione.importo)

    total_out = db.query(func.sum(amount_expr)).join(Conto, Transazione.conto_id == Conto.id).filter(
        Conto.user_id == current_user_id,
        Transazione.deleted_at.is_(None),
        Transazione.tipo == TipoTransazione.USCITA,
        Transazione.data >= first_day,
        Transazione.data <= last_day,
    ).scalar() or Decimal("0")

    total_in = db.query(func.sum(amount_expr)).join(Conto, Transazione.conto_id == Conto.id).filter(
        Conto.user_id == current_user_id,
        Transazione.deleted_at.is_(None),
        Transazione.tipo == TipoTransazione.ENTRATA,
        Transazione.data >= first_day,
        Transazione.data <= last_day,
    ).scalar() or Decimal("0")

    total_other = db.query(func.sum(amount_expr)).join(Conto, Transazione.conto_id == Conto.id).filter(
        Conto.user_id == current_user_id,
        Transazione.deleted_at.is_(None),
        Transazione.tipo != TipoTransazione.USCITA,
        Transazione.tipo != TipoTransazione.ENTRATA,
        Transazione.tipo != TipoTransazione.RIMBORSO,
        # I giroconti (RICARICA) non sono entrate/uscite reali: esclusi
        Transazione.tipo != TipoTransazione.RICARICA,
        # Gli accantonamenti vengono gestiti a parte (sottratti dal risparmio)
        Transazione.tipo != TipoTransazione.ACCANTONAMENTO,
        Transazione.data >= first_day,
        Transazione.data <= last_day,
    ).scalar() or Decimal("0")

    # Accantonamenti del mese: non sono spese, ma riducono il risparmio mensile
    total_accantonamento = db.query(func.sum(amount_expr)).join(Conto, Transazione.conto_id == Conto.id).filter(
        Conto.user_id == current_user_id,
        Transazione.deleted_at.is_(None),
        Transazione.tipo == TipoTransazione.ACCANTONAMENTO,
        Transazione.data >= first_day,
        Transazione.data <= last_day,
    ).scalar() or Decimal("0")

    # Risparmio del mese: entrate - uscite - accantonamenti
    remaining_amount = total_in + total_other - total_out - total_accantonamento

    if include_future_recurring:
        recurring_out = db.query(func.sum(Ricorrenza.importo)).filter(
            Ricorrenza.user_id == current_user_id,
            Ricorrenza.tipo == TipoTransazione.USCITA,
            Ricorrenza.attiva,
            Ricorrenza.prossima_esecuzione >= today,
            Ricorrenza.prossima_esecuzione <= last_day,
        ).scalar() or Decimal("0")

        recurring_in = db.query(func.sum(Ricorrenza.importo)).filter(
            Ricorrenza.user_id == current_user_id,
            Ricorrenza.tipo == TipoTransazione.ENTRATA,
            Ricorrenza.attiva,
            Ricorrenza.prossima_esecuzione >= today,
            Ricorrenza.prossima_esecuzione <= last_day,
        ).scalar() or Decimal("0")

        remaining_amount += recurring_in - recurring_out

    percentage = None
    if user.total_budget and user.total_budget > Decimal("0"):
        # Calcolo percentuale del risparmio rispetto all'obiettivo
        percentage = round(float(remaining_amount / user.total_budget * 100), 1)

    return {
        "monthly_budget": {
            "total_budget": user.total_budget,
            "remaining": remaining_amount,
            "percentage": percentage,
            "period": {"start": first_day, "end": last_day},
        }
    }


@router.get("/expensesByCategory")
def get_expenses_by_category(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    today = date.today()
    first_day = today.replace(day=1)

    # Calcolo dell'ultimo giorno del mese corrente
    _, last_day_num = calendar.monthrange(today.year, today.month)
    last_day = today.replace(day=last_day_num)

    # Fetch all transactions (Expenses and Refunds) specificamente per questo mese
    transazioni = (
        db.query(Transazione)
        .join(Conto, Transazione.conto_id == Conto.id)
        .filter(
            Conto.user_id == current_user_id,
            Transazione.deleted_at.is_(None),
            Transazione.tipo == TipoTransazione.USCITA,
            Transazione.data >= first_day,
            Transazione.data <= last_day,  # Filtro per escludere transazioni future
        )
        .all()
    )

    stats = {}

    for t in transazioni:
        cat_nome = t.categoria.nome if t.categoria else "Uncategorized"
        # Inizializza con Decimal("0")
        stats[cat_nome] = stats.get(cat_nome, Decimal("0")) + (
            t.importo_netto or Decimal("0")
        )

    # Nella return, lasciamo che Pydantic o il casting gestiscano la pulizia
    return [
        {"label": cat, "value": val.quantize(Decimal("0.01"))}
        for cat, val in stats.items()
        if val > 0
    ]
