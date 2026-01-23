from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional
from .sottocategoria import SottocategoriaCreate, SottocategoriaOut

class CategoriaBase(BaseModel):
    nome: str

class CategoriaCreate(CategoriaBase):
    sottocategorie: Optional[List[SottocategoriaCreate]] = None

class CategoriaUpdate(CategoriaBase):
    nome: str

class CategoriaOut(CategoriaBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    sottocategorie: List[SottocategoriaOut] = []

    class Config:
        from_attributes = True