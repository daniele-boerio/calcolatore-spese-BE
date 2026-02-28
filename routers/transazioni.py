from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from schemas import (
    TransazioneCreate,
    TransazioneOut,
    TransazionePagination,
    TransazioneUpdate,
    TransazioneFilters,
)
from schemas.transazione import TipoTransazione
from models import Conto, Transazione

from services import apply_filters_and_sort
from datetime import datetime, timezone
from models import Categoria, Sottocategoria

router = APIRouter(prefix="/transazioni", tags=["Transazioni"])

# --- ENDPOINT TRANSAZIONI ---


# Funzione di utilità per aggiornare le date delle categorie
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


# Funzione di utilità per aggiornare le date dei conti
def update_conto_usage(db: Session, conto_id: int):
    now = datetime.now(timezone.utc)
    if conto_id:
        db.query(Conto).filter(Conto.id == conto_id).update({"lastImport": now})


@router.post("", response_model=TransazioneOut)
def create_transazione(
    transazione: TransazioneCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # 1. Recuperiamo il conto (security check + balance update)
    conto = (
        db.query(Conto)
        .filter(Conto.id == transazione.conto_id, Conto.user_id == current_user_id)
        .first()
    )

    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or not authorized",
        )

    # 2. Controllo RIMBORSO (Refund)
    if (
        transazione.tipo == TipoTransazione.RIMBORSO
        and transazione.parent_transaction_id
    ):
        parent_exists = (
            db.query(Transazione)
            .filter(
                Transazione.id == transazione.parent_transaction_id,
                Transazione.user_id == current_user_id,
            )
            .first()
        )

        if not parent_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The original transaction for this refund does not exist",
            )

    try:
        # 3. Creazione record
        new_trans = Transazione(**transazione.model_dump(), user_id=current_user_id)
        db.add(new_trans)

        # 4. Aggiornamento Saldo (Balance Update)
        modificatore = -1 if transazione.tipo == TipoTransazione.USCITA else 1
        conto.saldo += transazione.importo * modificatore

        # AGGIORNAMENTO lastImport
        update_category_usage(
            db, transazione.categoria_id, transazione.sottocategoria_id
        )

        update_conto_usage(db, transazione.conto_id)

        db.commit()
        db.refresh(new_trans)
        return new_trans
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the transaction",
        )


@router.get("/paginated", response_model=TransazionePagination)
def get_transazioni(
    page: int = 1,
    size: int = 10,
    filters: TransazioneFilters = Depends(),  # Aggiunto qui
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    offset = (page - 1) * size

    # 1. Query base
    query = db.query(Transazione).filter(Transazione.user_id == current_user_id)

    # 2. Applichiamo filtri e ordinamento (importo_min, tipo, sort_by, ecc.)
    query = apply_filters_and_sort(query, Transazione, filters)

    # 3. Contiamo il totale DOPO i filtri
    total = query.count()

    # 4. Applichiamo i limiti per la pagina specifica
    data = query.offset(offset).limit(size).all()

    return {"total": total, "page": page, "size": size, "data": data}


@router.get("", response_model=list[TransazioneOut])
def get_recent_transazioni(
    n: int,
    filters: TransazioneFilters = Depends(),  # Aggiunto qui
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    query = db.query(Transazione).filter(Transazione.user_id == current_user_id)

    # Applichiamo i filtri (se presenti) e l'ordinamento
    # Se sort_by non viene inviato, TransazioneFilters userà il default (es. data desc)
    if not filters:
        filters = TransazioneFilters()  # Default filters if none are provided
        filters.sort_by = "creationDate"
        filters.sort_order = "desc"
    query = apply_filters_and_sort(query, Transazione, filters)

    return query.limit(n).all()


@router.put("/{transazione_id}", response_model=TransazioneOut)
def update_transazione(
    transazione_id: int,
    transazione_data: TransazioneUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # 1. Recupero la transazione originale
    db_trans = (
        db.query(Transazione)
        .filter(
            Transazione.id == transazione_id, Transazione.user_id == current_user_id
        )
        .first()
    )

    if not db_trans:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # 2. Recupero il CONTO DI ORIGINE (quello vecchio)
    conto_vecchio = (
        db.query(Conto)
        .filter(Conto.id == db_trans.conto_id, Conto.user_id == current_user_id)
        .first()
    )

    try:
        # A. STORNO dal vecchio conto
        mod_vecchio = 1 if db_trans.tipo == TipoTransazione.USCITA else -1
        if conto_vecchio:
            conto_vecchio.saldo += db_trans.importo * mod_vecchio

        # B. AGGIORNAMENTO DATI
        update_data = transazione_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_trans, key, value)

        # Sincronizziamo i cambiamenti temporanei per assicurarci che db_trans.conto_id sia aggiornato
        db.flush()

        # C. Recupero il CONTO DI DESTINAZIONE (potrebbe essere lo stesso o uno nuovo)
        conto_nuovo = (
            db.query(Conto)
            .filter(Conto.id == db_trans.conto_id, Conto.user_id == current_user_id)
            .first()
        )

        if not conto_nuovo:
            raise HTTPException(
                status_code=404, detail="New associated account not found"
            )

        # D. APPLICAZIONE al nuovo conto
        mod_nuovo = -1 if db_trans.tipo == TipoTransazione.USCITA else 1
        conto_nuovo.saldo += db_trans.importo * mod_nuovo

        # E. AGGIORNAMENTO lastImport (usiamo i nuovi ID se sono cambiati)
        update_category_usage(db, db_trans.categoria_id, db_trans.sottocategoria_id)
        update_conto_usage(db, db_trans.conto_id)

        db.commit()
        db.refresh(db_trans)
        return db_trans

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update transaction: {str(e)}",
        )


@router.delete("/{transazione_id}")
def delete_transazione(
    transazione_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_trans = (
        db.query(Transazione)
        .filter(
            Transazione.id == transazione_id, Transazione.user_id == current_user_id
        )
        .first()
    )

    if not db_trans:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found"
        )

    conto = (
        db.query(Conto)
        .filter(Conto.id == db_trans.conto_id, Conto.user_id == current_user_id)
        .first()
    )

    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Associated account not found"
        )

    try:
        # Balance reversion
        if db_trans.tipo == TipoTransazione.USCITA:
            conto.saldo += db_trans.importo
        else:
            conto.saldo -= db_trans.importo

        db.delete(db_trans)
        db.commit()
        return {"message": "Transaction successfully deleted and balance updated"}
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the transaction",
        )
