from datetime import datetime
from fastapi.params import Query
from pydantic import BaseModel
from typing import Optional


class TagBase(BaseModel):
    nome: str


class TagCreate(TagBase):
    pass


class TagUpdate(TagBase):
    pass


class TagOut(TagBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime

    class Config:
        from_attributes = True


class TagFilters:
    def __init__(
        self,
        # Ora mettiamo Query() in TUTTI i campi per blindarli nella query string
        sort_by: Optional[list[str]] = Query(["nome:asc"]),
    ):
        self.sort_by = sort_by

    # Creiamo questo metodo per non rompere la tua funzione apply_filters_and_sort
    def model_dump(self):
        # Restituisce un dizionario ignorando i valori None
        return {k: v for k, v in self.__dict__.items() if v is not None}
