from datetime import datetime
from pydantic import BaseModel
from datetime import date
from typing import Optional
from schemas.transazione import TipoTransazione
from fastapi import Query


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


class RicorrenzaFilters:
    def __init__(
        self,
        # Ora mettiamo Query() in TUTTI i campi per blindarli nella query string
        sort_by: Optional[list[str]] = Query(["data:desc", "id:desc"]),
        nome: Optional[str] = Query(None),
        tipo: Optional[str] = Query(None),
        importo_min: Optional[float] = Query(None),
        importo_max: Optional[float] = Query(None),
        frequenza: Optional[str] = Query(None),
        prossima_esecuzione_inizio: Optional[date] = Query(None),
        prossima_esecuzione_fine: Optional[date] = Query(None),
        attiva: Optional[bool] = Query(None),
        conto_id: Optional[list[int]] = Query(None),
        categoria_id: Optional[list[int]] = Query(None),
        sottocategoria_id: Optional[list[int]] = Query(None),
        tag_id: Optional[list[int]] = Query(None),
    ):
        self.sort_by = sort_by
        self.nome = nome
        self.tipo = tipo
        self.importo_min = importo_min
        self.importo_max = importo_max
        self.frequenza = frequenza
        self.prossima_esecuzione_inizio = prossima_esecuzione_inizio
        self.prossima_esecuzione_fine = prossima_esecuzione_fine
        self.attiva = attiva
        self.conto_id = conto_id
        self.categoria_id = categoria_id
        self.sottocategoria_id = sottocategoria_id
        self.tag_id = tag_id

    # Creiamo questo metodo per non rompere la tua funzione apply_filters_and_sort
    def model_dump(self):
        # Restituisce un dizionario ignorando i valori None
        return {k: v for k, v in self.__dict__.items() if v is not None}
