from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, subqueryload
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
from sqlalchemy import func

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
        trans_data = transazione.model_dump()
        # Inizializziamo importo_netto uguale all'importo (sarà ridotto se ci sono rimborsi futuri,
        # o se questa è un rimborso, non tocca il proprio netto ma quello del padre)
        trans_data["importo_netto"] = transazione.importo

        new_trans = Transazione(**trans_data, user_id=current_user_id)
        db.add(new_trans)

        # Se è un RIMBORSO, aggiorniamo l'importo_netto della transazione PADRE
        if (
            transazione.tipo == TipoTransazione.RIMBORSO
            and transazione.parent_transaction_id
        ):
            # parent_exists l'abbiamo già recuperato nel check sopra, ma qui lo riprendiamo o usiamo quello
            # Per sicurezza lo riprendiamo dalla sessione o usiamo la query di prima se l'avessimo salvata
            parent_trans = (
                db.query(Transazione)
                .filter(Transazione.id == transazione.parent_transaction_id)
                .first()
            )
            if parent_trans:
                if parent_trans.importo_netto is None:
                    parent_trans.importo_netto = parent_trans.importo
                parent_trans.importo_netto -= transazione.importo
                db.add(parent_trans)  # Segniamo come modified

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
    filters: TransazioneFilters = Depends(),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    offset = (page - 1) * size

    # 1. Query base filtrata
    base_query = db.query(Transazione).filter(Transazione.user_id == current_user_id)
    base_query = apply_filters_and_sort(base_query, Transazione, filters)

    # 2. Calcolo Totale Record (count ignora l'order_by automaticamente)
    total = base_query.count()

    # 3. Calcolo Totale Entrate
    # Rimuoviamo l'ordinamento con .order_by(None) per evitare il GroupingError
    total_entrata = (
        base_query.filter(Transazione.tipo == TipoTransazione.ENTRATA)
        .order_by(None)  # <--- FONDAMENTALE PER POSTGRES
        .with_entities(func.sum(Transazione.importo))
        .scalar()
        or 0.0
    )

    # 4. Calcolo Totale Uscite
    total_uscita = (
        base_query.filter(
            (Transazione.tipo == TipoTransazione.USCITA)
            | (Transazione.tipo == TipoTransazione.RIMBORSO)
        )
        .order_by(None)  # <--- FONDAMENTALE PER POSTGRES
        .with_entities(func.sum(Transazione.importo))
        .scalar()
        or 0.0
    )

    # 5. Recupero dati paginati (qui l'ordinamento serve e rimane quello di base_query)
    data = base_query.offset(offset).limit(size).all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "total_entrata": round(total_entrata, 2),
        "total_uscita": round(total_uscita, 2),
        "data": data,
    }


@router.get("", response_model=list[TransazioneOut])
def get_recent_transazioni(
    n: int = None,
    filters: TransazioneFilters = Depends(),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    query = db.query(Transazione).filter(Transazione.user_id == current_user_id)

    # Applichiamo i filtri (se presenti) e l'ordinamento
    # Se sort_by non viene inviato, TransazioneFilters userà il default (es. data desc)
    if not filters:
        filters = TransazioneFilters()  # Default filters if none are provided
        filters.sort_by = "lastUpdate"
        filters.sort_order = "desc"
    query = apply_filters_and_sort(query, Transazione, filters)

    if n:
        query = query.limit(n)

    return query.all()


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

    # Salviamo i vecchi valori per il calcolo delle differenze
    old_importo = db_trans.importo

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

        # --- LOGICA AGGIORNAMENTO IMPORTO NETTO ---
        new_importo = db_trans.importo
        diff_importo = new_importo - old_importo

        # Caso 1: Ho modificato l'importo della transazione stessa -> aggiorno il suo netto
        # (se importo_netto è None, lo inizializzo)
        if db_trans.importo_netto is None:
            db_trans.importo_netto = new_importo
        else:
            # Se l'importo aumenta di 10, anche il netto aumenta di 10 (a parità di rimborsi)
            db_trans.importo_netto += diff_importo

        # Caso 2: Se questa transazione è un RIMBORSO, devo aggiornare il netto del PADRE
        if db_trans.tipo == TipoTransazione.RIMBORSO and db_trans.parent_transaction_id:
            parent = (
                db.query(Transazione)
                .filter(Transazione.id == db_trans.parent_transaction_id)
                .first()
            )
            if parent:
                if parent.importo_netto is None:
                    parent.importo_netto = parent.importo
                # Se il rimborso aumenta (diff > 0), il netto del padre diminuisce
                parent.importo_netto -= diff_importo
        # ------------------------------------------

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

    # Se sto cancellando un RIMBORSO, devo ripristinare l'importo netto del PADRE
    # Nota: lo facciamo prima del commit finale, ma dopo aver verificato che la transazione esiste
    if db_trans.tipo == TipoTransazione.RIMBORSO and db_trans.parent_transaction_id:
        parent = (
            db.query(Transazione)
            .filter(Transazione.id == db_trans.parent_transaction_id)
            .first()
        )
        if parent:
            if parent.importo_netto is None:
                parent.importo_netto = parent.importo
            # Cancellando il rimborso, il padre "recupera" quel valore nel netto
            parent.importo_netto += db_trans.importo

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
