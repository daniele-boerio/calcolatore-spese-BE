from datetime import datetime
from pydantic import BaseModel
from datetime import date
from typing import Optional
from schemas.transazione import TipoTransazione


class RicorrenzaBase(BaseModel):
    nome: str
    importo: float
    tipo: TipoTransazione  # "ENTRATA", "USCITA" o "RIMBORSO"
    frequenza: str  # "GIORNALIERA", "SETTIMANALE", "MENSILE", "ANNUALE"
    prossima_esecuzione: date
    attiva: Optional[bool] = True
    conto_id: int
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None


class RicorrenzaCreate(RicorrenzaBase):
    pass


class RicorrenzaUpdate(BaseModel):
    nome: Optional[str] = None
    importo: Optional[float] = None
    frequenza: Optional[str] = None
    prossima_esecuzione: Optional[date] = None
    attiva: Optional[bool] = None
    conto_id: Optional[int] = None
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None


class RicorrenzaOut(RicorrenzaBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    attiva: bool

    class Config:
        from_attributes = True


class RicorrenzaFilters(BaseModel):
    sort_by: Optional[str] = "prossima_esecuzione"
    sort_order: Optional[str] = "asc"
    nome: Optional[str] = None
    # Range per l'importo
    importo_min: Optional[float] = None
    importo_max: Optional[float] = None
    frequenza: Optional[str] = None
    # Range per la data di esecuzione
    prossima_esecuzione_inizio: Optional[date] = None
    prossima_esecuzione_fine: Optional[date] = None
    attiva: Optional[bool] = None
    conto_id: Optional[int] = None
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None
