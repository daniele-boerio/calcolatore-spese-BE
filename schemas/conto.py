from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from datetime import date


class ContoBase(BaseModel):
    nome: str
    saldo: float
    ricarica_automatica: bool = False
    budget_obiettivo: Optional[float] = None
    soglia_minima: Optional[float] = None
    conto_sorgente_id: Optional[int] = None
    frequenza_controllo: Optional[str] = None  # "SETTIMANALE" o "MENSILE"
    prossimo_controllo: Optional[date] = None
    color: Optional[str] = None


class ContoCreate(ContoBase):
    pass


class ContoUpdate(BaseModel):
    nome: Optional[str] = None
    saldo: Optional[float] = None
    ricarica_automatica: Optional[bool] = None
    budget_obiettivo: Optional[float] = None
    soglia_minima: Optional[float] = None
    conto_sorgente_id: Optional[int] = None
    frequenza_controllo: Optional[str] = None
    prossimo_controllo: Optional[date] = None
    color: Optional[str] = None


class ContoOut(ContoBase):
    id: int

    creationDate: datetime
    lastUpdate: datetime

    class Config:
        from_attributes = True


class ContoFilters(BaseModel):
    sort_by: Optional[str] = "nome"
    sort_order: Optional[str] = "asc"
    nome: Optional[str] = None
    saldo_min: Optional[float] = None
    saldo_max: Optional[float] = None
    ricarica_automatica: Optional[bool] = None
    conto_sorgente_id: Optional[int] = None
