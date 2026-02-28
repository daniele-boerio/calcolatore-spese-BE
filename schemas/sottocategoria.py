from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class SottocategoriaBase(BaseModel):
    nome: str
    solo_entrata: bool = True
    solo_uscita: bool = True
    solo_rimborso: bool = True


class SottocategoriaCreate(SottocategoriaBase):
    pass


class SottocategoriaUpdate(SottocategoriaBase):
    pass


class SottocategoriaOut(SottocategoriaBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    lastImport: datetime
    categoria_id: int

    class Config:
        from_attributes = True


class SottocategoriaFilters(BaseModel):
    sort_by: Optional[str] = "nome"
    sort_order: Optional[str] = "desc"
