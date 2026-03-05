from datetime import datetime
from fastapi import Query
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
    default: bool = False


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
    default: bool = False


class ContoOut(ContoBase):
    id: int

    creationDate: datetime
    lastUpdate: datetime
    lastImport: datetime

    class Config:
        from_attributes = True


class ContoFilters:
    def __init__(
        self,
        # Ora mettiamo Query() in TUTTI i campi per blindarli nella query string
        sort_by: Optional[list[str]] = Query(["nome:asc"]),
        nome: Optional[str] = Query(None),
        saldo_min: Optional[float] = Query(None),
        saldo_max: Optional[float] = Query(None),
        ricarica_automatica: Optional[bool] = Query(None),
    ):
        self.sort_by = sort_by
        self.nome = nome
        self.saldo_min = saldo_min
        self.saldo_max = saldo_max
        self.ricarica_automatica = ricarica_automatica

    # Creiamo questo metodo per non rompere la tua funzione apply_filters_and_sort
    def model_dump(self):
        # Restituisce un dizionario ignorando i valori None
        return {k: v for k, v in self.__dict__.items() if v is not None}
