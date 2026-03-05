from datetime import datetime
from fastapi import Query
from pydantic import BaseModel
from typing import List, Optional
from .sottocategoria import SottocategoriaCreate, SottocategoriaOut


class CategoriaBase(BaseModel):
    nome: str
    solo_entrata: bool = True
    solo_uscita: bool = True
    solo_rimborso: bool = True


class CategoriaCreate(CategoriaBase):
    sottocategorie: Optional[List[SottocategoriaCreate]] = None


class CategoriaUpdate(CategoriaBase):
    nome: str


class CategoriaOut(CategoriaBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    lastImport: datetime
    sottocategorie: List[SottocategoriaOut] = []

    class Config:
        from_attributes = True


class CategoriaFilters:
    def __init__(
        self,
        # Ora mettiamo Query() in TUTTI i campi per blindarli nella query string
        sort_by: Optional[list[str]] = Query(["nome:asc"]),
        solo_entrata: Optional[bool] = Query(None),
        solo_uscita: Optional[bool] = Query(None),
        solo_rimborso: Optional[bool] = Query(None),
    ):
        self.sort_by = sort_by
        self.solo_entrata = solo_entrata
        self.solo_uscita = solo_uscita
        self.solo_rimborso = solo_rimborso

    # Creiamo questo metodo per non rompere la tua funzione apply_filters_and_sort
    def model_dump(self):
        # Restituisce un dizionario ignorando i valori None
        return {k: v for k, v in self.__dict__.items() if v is not None}
