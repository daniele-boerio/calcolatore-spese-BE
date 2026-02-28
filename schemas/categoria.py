from datetime import datetime
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


class CategoriaFilters(BaseModel):
    sort_by: Optional[str] = "nome"
    sort_order: Optional[str] = "desc"
    solo_entrata: Optional[bool] = None
    solo_uscita: Optional[bool] = None
    solo_rimborso: Optional[bool] = None
