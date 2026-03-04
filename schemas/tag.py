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


class TagFilters(BaseModel):
    sort_by: Optional[list[str]] = Query(["nome:asc"])
