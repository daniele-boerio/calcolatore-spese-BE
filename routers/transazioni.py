from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from schemas import (
    TransazioneCreate,
    TransazioneOut,
    TransazionePagination,
    TransazioneSplitRequest,
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
from models import Debito

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
        .filter(
            Conto.id == transazione.conto_id,
            Conto.user_id == current_user_id,
            Conto.deleted_at.is_(None),
        )
        .first()
    )

    if not conto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or not authorized",
        )

    # --- RICARICA (giroconto): serve un conto destinazione valido e diverso ---
    # --- ACCANTONAMENTO: conto destinazione OPZIONALE (salvadanaio), ma se c'è
    #     dev'essere valido e diverso dal sorgente. ---
    conto_dest = None
    if transazione.tipo == TipoTransazione.RICARICA:
        if not transazione.conto_destinazione_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A transfer requires a destination account",
            )
        if transazione.conto_destinazione_id == transazione.conto_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source and destination accounts must differ",
            )
        conto_dest = (
            db.query(Conto)
            .filter(
                Conto.id == transazione.conto_destinazione_id,
                Conto.user_id == current_user_id,
                Conto.deleted_at.is_(None),
            )
            .first()
        )
        if not conto_dest:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Destination account not found or not authorized",
            )
    elif (
        transazione.tipo == TipoTransazione.ACCANTONAMENTO
        and transazione.conto_destinazione_id
    ):
        if transazione.conto_destinazione_id == transazione.conto_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source and destination accounts must differ",
            )
        conto_dest = (
            db.query(Conto)
            .filter(
                Conto.id == transazione.conto_destinazione_id,
                Conto.user_id == current_user_id,
                Conto.deleted_at.is_(None),
            )
            .first()
        )
        if not conto_dest:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Destination account not found or not authorized",
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

        # --- NUOVA LOGICA: AUTOCOMPILAZIONE DESCRIZIONE ---
        desc_text = trans_data.get("descrizione")
        # Se non c'è descrizione o è solo composta da spazi vuoti
        if not desc_text or not str(desc_text).strip():
            # Primo tentativo: Recupera il nome della Sottocategoria
            if trans_data.get("sottocategoria_id"):
                sotto = (
                    db.query(Sottocategoria)
                    .filter(Sottocategoria.id == trans_data["sottocategoria_id"])
                    .first()
                )
                if sotto:
                    trans_data["descrizione"] = sotto.nome

            # Secondo tentativo (se ancora vuoto): Recupera il nome della Categoria
            if not trans_data.get("descrizione"):
                if trans_data.get("categoria_id"):
                    cat = (
                        db.query(Categoria)
                        .filter(Categoria.id == trans_data["categoria_id"])
                        .first()
                    )
                    if cat:
                        trans_data["descrizione"] = cat.nome
        # ----------------------------------------------------

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
        if transazione.tipo in (
            TipoTransazione.RICARICA,
            TipoTransazione.ACCANTONAMENTO,
        ):
            # Giroconto/accantonamento: i soldi escono dalla sorgente. Per la
            # RICARICA il conto destinazione c'è sempre; per l'ACCANTONAMENTO
            # è opzionale (salvadanaio): se presente, lo accreditiamo.
            conto.saldo -= transazione.importo
            if conto_dest:
                conto_dest.saldo += transazione.importo
                db.add(conto_dest)
        else:
            # Il rimborso aumenta il saldo del conto (come un'entrata)
            modificatore = (
                Decimal("-1")
                if transazione.tipo == TipoTransazione.USCITA
                else Decimal("1")
            )
            conto.saldo += transazione.importo * modificatore

        # --- GESTIONE DEBITO (se fornito) ---
        if getattr(transazione, "debito_id", None):
            db_debito = (
                db.query(Debito)
                .filter(
                    Debito.id == transazione.debito_id,
                    Debito.user_id == current_user_id,
                )
                .first()
            )
            if not db_debito:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referenced debito not found",
                )

            # Sottrai l'importo dal residuo del debito; non andare sotto zero
            if db_debito.residuo is None:
                db_debito.residuo = db_debito.ammontare

            nuovo_residuo = db_debito.residuo - transazione.importo
            if nuovo_residuo < Decimal("0"):
                nuovo_residuo = Decimal("0.00")

            db_debito.residuo = nuovo_residuo
            db.add(db_debito)
        # --------------------------------------

        # AGGIORNAMENTO lastImport / Usage
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


@router.post("/{transazione_id}/split", response_model=list[TransazioneOut])
def split_transazione(
    transazione_id: int,
    split_request: TransazioneSplitRequest,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    original = (
        db.query(Transazione)
        .filter(
            Transazione.id == transazione_id,
            Transazione.user_id == current_user_id,
            Transazione.deleted_at.is_(None),
        )
        .first()
    )

    if not original:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original transaction not found",
        )

    if original.tipo == TipoTransazione.RIMBORSO or original.parent_transaction_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refund transactions cannot be split",
        )

    if original.split_group_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Split transactions cannot be split again",
        )

    if original.debito_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transactions linked to debt cannot be split",
        )

    if (
        db.query(Transazione)
        .filter(Transazione.parent_transaction_id == original.id)
        .count()
        > 0
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transactions with refunds cannot be split",
        )

    total_parts = sum(part.importo for part in split_request.parts)
    if total_parts != original.importo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sum of split parts must equal original transaction amount",
        )

    for part in split_request.parts:
        if part.importo <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Each split part must have a positive amount",
            )
        if part.debito_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Split parts cannot reference debt",
            )

    split_transactions = []
    for part in split_request.parts:
        new_trans = Transazione(
            importo=part.importo,
            importo_netto=part.importo,
            tipo=original.tipo,
            data=original.data,
            descrizione=part.descrizione or original.descrizione,
            conto_id=original.conto_id,
            categoria_id=part.categoria_id,
            sottocategoria_id=part.sottocategoria_id,
            tag_id=part.tag_id,
            user_id=current_user_id,
            split_group_id=original.id,
        )
        db.add(new_trans)
        split_transactions.append(new_trans)

    db.delete(original)

    try:
        db.commit()
        for transaction in split_transactions:
            db.refresh(transaction)
        return split_transactions
    except Exception as e:
        db.rollback()
        print(f"Error splitting transaction: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while splitting the transaction",
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
            Transazione.id == transazione_id,
            Transazione.user_id == current_user_id,
            Transazione.deleted_at.is_(None),
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
    old_debito_id = db_trans.debito_id
    old_tipo = db_trans.tipo
    old_conto_dest_id = db_trans.conto_destinazione_id

    try:
        # Salviamo importo netto vecchio (o importo se None)
        old_importo_netto = (
            db_trans.importo_netto
            if db_trans.importo_netto is not None
            else db_trans.importo
        )

        # A. STORNO del vecchio movimento
        if old_tipo in (TipoTransazione.RICARICA, TipoTransazione.ACCANTONAMENTO):
            # Giroconto/accantonamento: la sorgente riprende i soldi, l'eventuale
            # destinazione li perde
            if conto_vecchio:
                conto_vecchio.saldo += old_importo
            if old_conto_dest_id:
                old_dest = (
                    db.query(Conto)
                    .filter(
                        Conto.id == old_conto_dest_id,
                        Conto.user_id == current_user_id,
                    )
                    .first()
                )
                if old_dest:
                    old_dest.saldo -= old_importo
                    db.add(old_dest)
        else:
            mod_vecchio = (
                Decimal("1")
                if old_tipo == TipoTransazione.USCITA
                else Decimal("-1")
            )
            if conto_vecchio:
                conto_vecchio.saldo += old_importo * mod_vecchio

        # B. AGGIORNAMENTO DATI
        update_data = transazione_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_trans, key, value)

        # --- AUTOCOMPILAZIONE DESCRIZIONE ANCHE IN MODIFICA ---
        if not db_trans.descrizione or not str(db_trans.descrizione).strip():
            if db_trans.sottocategoria_id:
                sotto = (
                    db.query(Sottocategoria)
                    .filter(Sottocategoria.id == db_trans.sottocategoria_id)
                    .first()
                )
                if sotto:
                    db_trans.descrizione = sotto.nome

            if not db_trans.descrizione and db_trans.categoria_id:
                cat = (
                    db.query(Categoria)
                    .filter(Categoria.id == db_trans.categoria_id)
                    .first()
                )
                if cat:
                    db_trans.descrizione = cat.nome
        # ------------------------------------------------------

        db.flush()

        # --- PROPAGAZIONE CATEGORIA/SOTTOCATEGORIA AI RIMBORSI ---
        # Cerchiamo tutti i rimborsi che hanno questa transazione come "padre"
        rimborsi_figli = (
            db.query(Transazione)
            .filter(Transazione.parent_transaction_id == db_trans.id)
            .all()
        )

        # Allineiamo categoria, sottocategoria e tag ai figli
        for rimborso in rimborsi_figli:
            rimborso.categoria_id = db_trans.categoria_id
            rimborso.sottocategoria_id = db_trans.sottocategoria_id
            rimborso.tag_id = db_trans.tag_id
            db.add(rimborso)
        # ---------------------------------------------------------

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
            .filter(
                Conto.id == db_trans.conto_id,
                Conto.user_id == current_user_id,
                Conto.deleted_at.is_(None),
            )
            .first()
        )

        if not conto_nuovo:
            raise HTTPException(
                status_code=404, detail="New associated account not found"
            )

        # D. APPLICAZIONE del nuovo movimento
        if db_trans.tipo in (
            TipoTransazione.RICARICA,
            TipoTransazione.ACCANTONAMENTO,
        ):
            conto_dest_nuovo = None
            if db_trans.conto_destinazione_id:
                if db_trans.conto_destinazione_id == db_trans.conto_id:
                    raise HTTPException(
                        status_code=400,
                        detail="Source and destination accounts must differ",
                    )
                conto_dest_nuovo = (
                    db.query(Conto)
                    .filter(
                        Conto.id == db_trans.conto_destinazione_id,
                        Conto.user_id == current_user_id,
                        Conto.deleted_at.is_(None),
                    )
                    .first()
                )
                if not conto_dest_nuovo:
                    raise HTTPException(
                        status_code=404,
                        detail="Destination account not found or unauthorized",
                    )
            elif db_trans.tipo == TipoTransazione.RICARICA:
                # Il giroconto richiede sempre una destinazione; l'accantonamento no.
                raise HTTPException(
                    status_code=400,
                    detail="A transfer requires a different destination account",
                )
            conto_nuovo.saldo -= db_trans.importo
            if conto_dest_nuovo:
                conto_dest_nuovo.saldo += db_trans.importo
                db.add(conto_dest_nuovo)
        else:
            mod_nuovo = (
                Decimal("-1")
                if db_trans.tipo == TipoTransazione.USCITA
                else Decimal("1")
            )
            conto_nuovo.saldo += db_trans.importo * mod_nuovo

        # D-bis. RESIDUO DEBITO: storna il vecchio effetto e applica il nuovo,
        # così cambi di importo (o di debito) restano coerenti col residuo.
        def _adjust_debito_residuo(debito_id, delta):
            if debito_id is None:
                return
            debito = (
                db.query(Debito)
                .filter(Debito.id == debito_id, Debito.user_id == current_user_id)
                .first()
            )
            if debito is None:
                return
            if debito.residuo is None:
                debito.residuo = debito.ammontare
            nuovo = debito.residuo + delta
            if nuovo < Decimal("0"):
                nuovo = Decimal("0.00")
            if debito.ammontare is not None and nuovo > debito.ammontare:
                nuovo = debito.ammontare
            debito.residuo = nuovo
            db.add(debito)

        # Reverse del vecchio (restituisce l'importo pagato), apply del nuovo (sottrae)
        _adjust_debito_residuo(old_debito_id, old_importo)
        _adjust_debito_residuo(db_trans.debito_id, -db_trans.importo)

        # E. AGGIORNAMENTO lastImport (usiamo i nuovi ID se sono cambiati)
        update_category_usage(db, db_trans.categoria_id, db_trans.sottocategoria_id)
        update_conto_usage(db, db_trans.conto_id)

        db.commit()
        db.refresh(db_trans)
        return db_trans

    except HTTPException:
        db.rollback()
        raise
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
            Transazione.id == transazione_id,
            Transazione.user_id == current_user_id,
            Transazione.deleted_at.is_(None),
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
        if db_trans.tipo in (
            TipoTransazione.RICARICA,
            TipoTransazione.ACCANTONAMENTO,
        ):
            # Giroconto/accantonamento: la sorgente riprende i soldi, l'eventuale
            # destinazione li perde
            conto.saldo += db_trans.importo
            if db_trans.conto_destinazione_id:
                conto_dest = (
                    db.query(Conto)
                    .filter(
                        Conto.id == db_trans.conto_destinazione_id,
                        Conto.user_id == current_user_id,
                    )
                    .first()
                )
                if conto_dest:
                    conto_dest.saldo -= db_trans.importo
                    db.add(conto_dest)
        elif db_trans.tipo == TipoTransazione.USCITA:
            conto.saldo += db_trans.importo
        else:
            conto.saldo -= db_trans.importo

        # Se la transazione era collegata a un debito, ripristina il residuo
        # (operazione inversa di create/pay), senza superare l'ammontare totale.
        if db_trans.debito_id is not None:
            db_debito = (
                db.query(Debito)
                .filter(
                    Debito.id == db_trans.debito_id,
                    Debito.user_id == current_user_id,
                )
                .first()
            )
            if db_debito is not None:
                if db_debito.residuo is None:
                    db_debito.residuo = db_debito.ammontare
                nuovo_residuo = db_debito.residuo + db_trans.importo
                if (
                    db_debito.ammontare is not None
                    and nuovo_residuo > db_debito.ammontare
                ):
                    nuovo_residuo = db_debito.ammontare
                db_debito.residuo = nuovo_residuo
                db.add(db_debito)

        # Se questa transazione è il PADRE di rimborsi, alla cancellazione i figli
        # vengono eliminati in cascata: prima dobbiamo stornare il loro effetto
        # sul saldo (ognuno sul proprio conto), altrimenti il saldo resta sfasato.
        figli_rimborsi = (
            db.query(Transazione)
            .filter(Transazione.parent_transaction_id == db_trans.id)
            .all()
        )
        for figlio in figli_rimborsi:
            conto_figlio = (
                db.query(Conto)
                .filter(
                    Conto.id == figlio.conto_id,
                    Conto.user_id == current_user_id,
                )
                .first()
            )
            if conto_figlio is not None:
                if figlio.tipo == TipoTransazione.USCITA:
                    conto_figlio.saldo += figlio.importo
                else:
                    conto_figlio.saldo -= figlio.importo

        db.delete(db_trans)
        db.commit()
        return {"message": "Transaction successfully deleted and balance updated"}
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the transaction",
        )
