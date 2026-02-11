from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
from enum import Enum


class TipoTransazione(str, Enum):
    ENTRATA = "ENTRATA"
    USCITA = "USCITA"
    RIMBORSO = "RIMBORSO"


# 1. Base: Campi comuni sia alla creazione che alla visualizzazione
class TransazioneBase(BaseModel):
    importo: float
    tipo: TipoTransazione
    data: date = date.today()
    descrizione: Optional[str] = None
    conto_id: int
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None
    parent_transaction_id: Optional[int] = None


# 2. Create: Eredita tutto dalla Base (non serve aggiungere altro)
class TransazioneCreate(TransazioneBase):
    pass


class TransazioneUpdate(TransazioneBase):
    pass


# 3. Out: Eredita dalla Base e aggiunge i campi specifici per la risposta API
class TransazioneOut(TransazioneBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime

    class Config:
        from_attributes = True


class TransazionePagination(BaseModel):
    total: int  # Numero totale di transazioni per l'utente
    page: int  # Pagina attuale
    size: int  # Numero di elementi per pagina
    data: list[TransazioneOut]  # La lista effettiva delle transazioni


class TransazioneFilters(BaseModel):
    sort_by: Optional[str] = "data"
    sort_order: Optional[str] = "desc"
    # Campi per il range di importo
    importo_min: Optional[float] = None
    importo_max: Optional[float] = None
    # Altri filtri (resi opzionali)
    tipo: Optional[str] = None
    data_inizio: Optional[date] = None
    data_fine: Optional[date] = None
    descrizione: Optional[str] = None
    conto_id: Optional[int] = None
    categoria_id: Optional[int] = None
    tag_id: Optional[int] = None
