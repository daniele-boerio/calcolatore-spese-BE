from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import auth
from schemas import TransazioneCreate, TransazioneOut, TransazionePagination, TransazioneUpdate
from schemas.transazione import TipoTransazione
from models import Conto, Transazione

router = APIRouter(
    prefix="/transazioni",      # Tutti gli endpoint in questo file inizieranno con /transazioni
    tags=["Transazioni"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT TRANSAZIONI ---

@router.post("", response_model=TransazioneOut)
def create_transazione(
    transazione: TransazioneCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # 1. Recuperiamo il conto (ci serve sia per la sicurezza che per il saldo)
    conto = db.query(Conto).filter(
        Conto.id == transazione.conto_id,
        Conto.user_id == current_user_id
    ).first()

    if not conto:
        raise HTTPException(status_code=404, detail="Conto non trovato o non autorizzato")

    # 2. Se è un RIMBORSO, un controllo rapido di esistenza del padre
    if transazione.tipo == TipoTransazione.RIMBORSO and transazione.parent_transaction_id:
        parent_exists = db.query(Transazione).filter(
            Transazione.id == transazione.parent_transaction_id,
            Transazione.user_id == current_user_id
        ).first()
        
        if not parent_exists:
            raise HTTPException(status_code=400, detail="La transazione originale non esiste")

    # 3. Creazione record
    new_trans = Transazione(**transazione.model_dump(), user_id=current_user_id)
    db.add(new_trans)

    # 4. Aggiornamento Saldo
    # Usiamo una logica compatta: le uscite sottraggono, tutto il resto somma
    modificatore = -1 if transazione.tipo == TipoTransazione.USCITA else 1
    conto.saldo += (transazione.importo * modificatore)

    db.commit()
    db.refresh(new_trans)
    return new_trans

@router.get("/paginated", response_model=TransazionePagination)
def get_transazioni(
    page: int = 1,
    size: int = 10,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    offset = (page - 1) * size
    
    # Query di base
    query = db.query(Transazione).filter(
        Transazione.user_id == current_user_id
    )
    
    # Conteggio totale per la paginazione nel frontend
    total = query.count()
    
    # Recupero dati della pagina specifica
    data = query.order_by(
            Transazione.data.desc(),
            Transazione.creationDate.desc(),
            Transazione.lastUpdate.desc(),
            Transazione.id.desc())\
        .offset(offset)\
        .limit(size)\
        .all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "data": data
    }

@router.get("", response_model=list[TransazioneOut])
def get_recent_transazioni(
    n: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Recupera gli ultimi n record
    return db.query(Transazione)\
        .filter(Transazione.user_id == current_user_id)\
        .order_by(
            Transazione.data.desc(),           
            Transazione.creationDate.desc(),
            Transazione.lastUpdate.desc(),
            Transazione.id.desc()
        )\
        .limit(n)\
        .all()

@router.put("/{transazione_id}", response_model=TransazioneOut)
def update_transazione(
    transazione_id: int, 
    transazione_data: TransazioneUpdate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # 1. Recuperiamo la transazione esistente
    db_trans = db.query(Transazione).filter(
        Transazione.id == transazione_id, 
        Transazione.user_id == current_user_id
    ).first()

    if not db_trans:
        raise HTTPException(status_code=404, detail="Transazione non trovata")

    # 2. Recuperiamo il conto associato
    conto = db.query(Conto).filter(
        Conto.id == db_trans.conto_id, # Usiamo l'ID già presente nel DB
        Conto.user_id == current_user_id
    ).first()

    # A. STORNO: Riportiamo il saldo a come era PRIMA della transazione originale
    # Se era un'uscita, restituiamo i soldi al conto. Se era un'entrata/rimborso, li togliamo.
    if db_trans.tipo == TipoTransazione.USCITA:
        conto.saldo += db_trans.importo
    else:
        conto.saldo -= db_trans.importo

    # B. AGGIORNAMENTO DATI: Ora modifichiamo l'oggetto con i nuovi valori
    update_data = transazione_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_trans, key, value)

    # C. APPLICAZIONE NUOVO IMPORTO: Calcoliamo il saldo con i nuovi dati
    if db_trans.tipo == TipoTransazione.USCITA:
        conto.saldo -= db_trans.importo
    else:
        conto.saldo += db_trans.importo

    # ---------------------------------------------

    db.commit()
    db.refresh(db_trans)
    return db_trans

@router.delete("/{transazione_id}")
def delete_transazione(
    transazione_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # 1. Recuperiamo la transazione (usando lo user_id diretto per sicurezza)
    db_trans = db.query(Transazione).filter(
        Transazione.id == transazione_id, 
        Transazione.user_id == current_user_id
    ).first()

    if not db_trans:
        raise HTTPException(status_code=404, detail="Transazione non trovata")

    # 2. Recuperiamo il conto associato per aggiornare il saldo
    conto = db.query(Conto).filter(
        Conto.id == db_trans.conto_id,
        Conto.user_id == current_user_id
    ).first()

    if not conto:
        raise HTTPException(status_code=404, detail="Conto associato non trovato")

    # 3. Reversione saldo: dobbiamo annullare l'effetto della transazione
    if db_trans.tipo.upper() == "USCITA":
        conto.saldo += db_trans.importo
    else:
        conto.saldo -= db_trans.importo

    # 4. Cancellazione e commit
    db.delete(db_trans)
    db.commit()

    return {"message": "Transazione eliminata correttamente e saldo aggiornato"}

@router.get("/tag/{tag_id}", response_model=list[TransazioneOut])
def get_transazioni_by_tag(
    tag_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Recuperiamo le transazioni filtrando direttamente per tag_id e user_id
    # Non serve la JOIN se vogliamo solo le transazioni di quel tag
    transazioni = db.query(Transazione).filter(
        Transazione.tag_id == tag_id,
        Transazione.user_id == current_user_id
    ).order_by(Transazione.data.desc()).all()

    return transazioni