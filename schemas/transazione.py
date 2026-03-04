from pydantic import BaseModel
from typing import Optional, Union
from datetime import datetime, date
from enum import Enum
from fastapi import Query


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
    importo_netto: float

    class Config:
        from_attributes = True


class TransazionePagination(BaseModel):
    total: int  # Numero totale di transazioni per l'utente
    page: int  # Pagina attuale
    size: int  # Numero di elementi per pagina
    total_entrata: float  # valore delle entrate
    total_uscita: float  # Valore delle uscite
    data: list[TransazioneOut]  # La lista effettiva delle transazioni


class TransazioneFilters(BaseModel):
    sort_by: Optional[list[str]] = Query(["data:desc", "id:desc"])
    importo_min: Optional[float] = None
    importo_max: Optional[float] = None
    tipo: Optional[str] = None
    data_inizio: Optional[date] = None
    data_fine: Optional[date] = None
    descrizione: Optional[str] = None

    # Usiamo List[int] per permettere più valori
    conto_id: Optional[list[int]] = None
    categoria_id: Optional[list[int]] = Query(
        None, description="Filter by one or more category IDs"
    )
    sottocategoria_id: Optional[list[int]] = Query(
        None, description="Filter by one or more subcategory IDs"
    )
    tag_id: Optional[list[int]] = Query(
        None, description="Filter by one or more tag IDs"
    )
