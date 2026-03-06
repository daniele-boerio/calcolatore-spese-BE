from datetime import datetime
from fastapi.params import Query
from pydantic import BaseModel, ConfigDict  # Usiamo ConfigDict
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

    # Standard Pydantic V2
    model_config = ConfigDict(from_attributes=True)


class TagFilters:
    def __init__(
        self,
        # Default ordinamento per nome ascendente
        sort_by: Optional[list[str]] = Query(["nome:asc"]),
        nome: Optional[str] = Query(
            None
        ),  # Aggiunto filtro per nome se volessi cercarne uno specifico
    ):
        self.sort_by = sort_by
        self.nome = nome

    def model_dump(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}
