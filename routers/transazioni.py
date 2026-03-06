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
from sqlalchemy import func
from decimal import Decimal

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
    # 1. Recuperiamo il conto
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

    # Inizializziamo variabili per il padre
    parent_trans = None

    # 2. Controllo RIMBORSO (Refund)
    if (
        transazione.tipo == TipoTransazione.RIMBORSO
        and transazione.parent_transaction_id
    ):
        parent_trans = (
            db.query(Transazione)
            .filter(
                Transazione.id == transazione.parent_transaction_id,
                Transazione.user_id == current_user_id,
            )
            .first()
        )

        if not parent_trans:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The original transaction for this refund does not exist",
            )

    try:
        # 3. Creazione record
        trans_data = transazione.model_dump()

        if parent_trans:
            trans_data["categoria_id"] = parent_trans.categoria_id
            trans_data["sottocategoria_id"] = parent_trans.sottocategoria_id
            trans_data["tag_id"] = parent_trans.tag_id

        # Inizializziamo importo_netto per la transazione corrente
        trans_data["importo_netto"] = transazione.importo

        new_trans = Transazione(**trans_data, user_id=current_user_id)
        db.add(new_trans)

        # --- LOGICA CORRETTA PER AGGIORNARE IL PADRE ---
        if parent_trans:
            # 1. Inizializza se null
            if parent_trans.importo_netto is None:
                parent_trans.importo_netto = parent_trans.importo

            # 2. Sottrai il Decimal
            parent_trans.importo_netto -= Decimal(str(transazione.importo))

            # 3. FONDAMENTALE: Forza SQLAlchemy a tracciare la modifica
            db.add(parent_trans)

        # 4. Aggiornamento Saldo (Balance Update)
        # Il rimborso aumenta il saldo del conto (come un'entrata)
        modificatore = (
            Decimal("-1")
            if transazione.tipo == TipoTransazione.USCITA
            else Decimal("1")
        )
        conto.saldo += transazione.importo * modificatore

        # AGGIORNAMENTO lastImport / Usage
        # Usiamo i valori finali (quelli del padre se rimborso, o quelli inviati se normale)
        update_category_usage(db, new_trans.categoria_id, new_trans.sottocategoria_id)

        update_conto_usage(db, transazione.conto_id)

        db.commit()
        db.refresh(new_trans)
        return new_trans

    except Exception as e:
        db.rollback()
        # Log dell'errore per debugging interno
        print(f"Error: {e}")
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
        .order_by(None)
        .with_entities(func.sum(Transazione.importo))
        .scalar()
        or Decimal("0.00")  # <--- Qui
    )

    # 4. Calcolo Totale Uscite
    total_uscita = (
        base_query.filter((Transazione.tipo == TipoTransazione.USCITA))
        .order_by(None)
        .with_entities(func.sum(Transazione.importo))
        .scalar()
        or Decimal("0.00")  # <--- Qui
    )

    total_rimborsi = (
        base_query.filter((Transazione.tipo == TipoTransazione.RIMBORSO))
        .order_by(None)
        .with_entities(func.sum(Transazione.importo))
        .scalar()
        or Decimal("0.00")  # <--- Qui
    )

    # 5. Recupero dati paginati (qui l'ordinamento serve e rimane quello di base_query)
    data = base_query.offset(offset).limit(size).all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "total_entrata": total_entrata,
        "total_uscita": total_uscita,
        "total_rimborsi": total_rimborsi,
        "data": data,
    }


@router.get("", response_model=list[TransazioneOut])
def get_recent_transazioni(
    filters: TransazioneFilters = Depends(),
    n: int = None,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    query = db.query(Transazione).filter(Transazione.user_id == current_user_id)

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

    # (Codice iniziale invariato fino al blocco try)
    try:
        # Salviamo importo netto vecchio (o importo se None)
        old_importo_netto = (
            db_trans.importo_netto
            if db_trans.importo_netto is not None
            else db_trans.importo
        )

        # A. STORNO dal vecchio conto
        mod_vecchio = (
            Decimal("1") if db_trans.tipo == TipoTransazione.USCITA else Decimal("-1")
        )
        if conto_vecchio:
            conto_vecchio.saldo += db_trans.importo * mod_vecchio

        # B. AGGIORNAMENTO DATI
        update_data = transazione_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_trans, key, value)

        db.flush()

        # --- LOGICA CORRETTA AGGIORNAMENTO IMPORTO NETTO ---
        new_importo = Decimal(str(db_trans.importo))
        diff_importo = new_importo - old_importo

        # Caso 1: Aggiorno il SUO importo_netto
        # Il nuovo importo netto è il vecchio importo netto + la variazione dell'importo lordo
        db_trans.importo_netto = old_importo_netto + diff_importo

        # Caso 2: Se è un RIMBORSO, aggiorno il PADRE
        if db_trans.tipo == TipoTransazione.RIMBORSO and db_trans.parent_transaction_id:
            parent = (
                db.query(Transazione)
                .filter(Transazione.id == db_trans.parent_transaction_id)
                .first()
            )
            if parent:
                if parent.importo_netto is None:
                    parent.importo_netto = parent.importo

                # Se l'importo del rimborso aumenta (diff > 0), il netto del padre DEVE DIMINUIRE
                parent.importo_netto -= diff_importo

                # Forza SQLAlchemy a tracciare la modifica
                db.add(parent)

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
        mod_nuovo = (
            Decimal("-1") if db_trans.tipo == TipoTransazione.USCITA else Decimal("1")
        )
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
