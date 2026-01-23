import datetime
from enum import Enum
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
    conto_id: int
    categoria_id: Optional[int] = None
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
    tag_id: Optional[int] = None

class RicorrenzaOut(RicorrenzaBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    attiva: bool
    user_id: int

    class Config:
        from_attributes = True