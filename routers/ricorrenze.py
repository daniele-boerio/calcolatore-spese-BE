from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
import auth
from models import Ricorrenza, Conto, Debito
from schemas import (
    RicorrenzaOut,
    RicorrenzaCreate,
    RicorrenzaUpdate,
    RicorrenzaFilters,
    RicorrenzaEseguiRequest,
)
from services import apply_filters_and_sort, esegui_ricorrenza
from routers.transazioni import resolve_tassonomia
from datetime import date

router = APIRouter(prefix="/ricorrenze", tags=["Ricorrenze"])


def verifica_riferimenti(db: Session, user_id: int, dati: dict, attuale=None):
    """Categoria, sottocategoria, tag e debito devono essere dell'utente.

    Gli id arrivano dal client e la ricorrenza li copia su ogni transazione che
    genera: senza controllo, una ricorrenza potrebbe scrivere ogni mese sulla
    tassonomia o sul debito di un altro utente. `attuale` è la ricorrenza in
    modifica, per completare i campi che il payload non tocca.
    """

    def valore(campo):
        if campo in dati:
            return dati[campo]
        return getattr(attuale, campo, None)

    resolve_tassonomia(
        db,
        user_id,
        valore("categoria_id"),
        valore("sottocategoria_id"),
        valore("tag_id"),
    )

    debito_id = valore("debito_id")
    if debito_id is not None:
        debito = (
            db.query(Debito)
            .filter(Debito.id == debito_id, Debito.user_id == user_id)
            .first()
        )
        if not debito:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debt not found or not authorized",
            )

    data_fine = valore("data_fine")
    prossima = valore("prossima_esecuzione")
    if data_fine is not None and prossima is not None and data_fine < prossima:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The end date cannot precede the next execution",
        )


@router.post("", response_model=RicorrenzaOut)
def create_ricorrenza(
    ricorrenza: RicorrenzaCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # 1. Verify that the account belongs to the user
    conto = (
        db.query(Conto)
        .filter(
            Conto.id == ricorrenza.conto_id,
            Conto.user_id == current_user_id,
            Conto.deleted_at.is_(None),
        )
        .first()
    )

    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or unauthorized",
        )

    verifica_riferimenti(db, current_user_id, ricorrenza.model_dump())

    try:
        new_ric = Ricorrenza(**ricorrenza.model_dump(), user_id=current_user_id)
        db.add(new_ric)
        db.commit()
        db.refresh(new_ric)
        return new_ric
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the recurring transaction",
        )


@router.get("", response_model=List[RicorrenzaOut])
def get_ricorrenze(
    filters: RicorrenzaFilters = Depends(),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    query = db.query(Ricorrenza).filter(Ricorrenza.user_id == current_user_id)

    query = apply_filters_and_sort(
        query,
        Ricorrenza,
        filters=filters,
    )

    return query.all()


@router.put("/{ricorrenza_id}", response_model=RicorrenzaOut)
def update_ricorrenza(
    ricorrenza_id: int,
    ric_data: RicorrenzaUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_ric = (
        db.query(Ricorrenza)
        .filter(Ricorrenza.id == ricorrenza_id, Ricorrenza.user_id == current_user_id)
        .first()
    )

    if not db_ric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring transaction not found",
        )

    update_dict = ric_data.model_dump(exclude_unset=True)

    # Se si cambia il conto, verifichiamo che appartenga all'utente.
    # Fuori dal try: l'HTTPException non va mascherato come 500.
    if update_dict.get("conto_id") is not None:
        conto = (
            db.query(Conto)
            .filter(
                Conto.id == update_dict["conto_id"],
                Conto.user_id == current_user_id,
                Conto.deleted_at.is_(None),
            )
            .first()
        )
        if not conto:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found or unauthorized",
            )

    verifica_riferimenti(db, current_user_id, update_dict, attuale=db_ric)

    try:
        for key, value in update_dict.items():
            setattr(db_ric, key, value)

        db.commit()
        db.refresh(db_ric)
        return db_ric
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update the recurring transaction",
        )


@router.post("/{ricorrenza_id}/esegui", response_model=RicorrenzaOut)
def esegui_ricorrenza_ora(
    ricorrenza_id: int,
    body: Optional[RicorrenzaEseguiRequest] = None,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    """Registra adesso una ricorrenza già scaduta.

    Serve quando lo scheduler notturno non è passato (macchina spenta, deploy
    a cavallo di mezzanotte): la ricorrenza resta indietro e da qui la si
    sblocca a mano. Non anticipa niente — una ricorrenza non ancora scaduta
    viene rifiutata — quindi non può fare doppioni con il task.

    Registra una sola occorrenza, la più vecchia: se ne mancano altre, la
    ricorrenza resta fra le scadute e si registra di nuovo. Per quelle a
    importo variabile è l'unico modo di registrarle, con l'importo vero.
    """
    db_ric = (
        db.query(Ricorrenza)
        .filter(Ricorrenza.id == ricorrenza_id, Ricorrenza.user_id == current_user_id)
        .first()
    )

    if not db_ric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring transaction not found",
        )

    if not db_ric.attiva:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A suspended recurring transaction cannot be executed",
        )

    today = date.today()

    if db_ric.prossima_esecuzione > today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This recurring transaction is not due yet",
        )

    importo = body.importo if body is not None else None

    if db_ric.importo_variabile and importo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A variable recurring transaction needs the actual amount",
        )

    try:
        esegui_ricorrenza(db, db_ric, today, importo=importo)
        db.commit()
        db.refresh(db_ric)
        return db_ric
    except ValueError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot execute the recurring transaction: {e}",
        )
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute the recurring transaction",
        )


@router.delete("/{ricorrenza_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ricorrenza(
    ricorrenza_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_ric = (
        db.query(Ricorrenza)
        .filter(Ricorrenza.id == ricorrenza_id, Ricorrenza.user_id == current_user_id)
        .first()
    )

    if not db_ric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring transaction not found",
        )

    try:
        db.delete(db_ric)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the recurring transaction",
        )
