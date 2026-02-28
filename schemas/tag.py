from datetime import datetime
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
    sort_by: Optional[str] = "nome"
    sort_order: Optional[str] = "desc"
