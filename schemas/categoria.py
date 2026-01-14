from pydantic import BaseModel
from typing import List, Optional
from .sottocategoria import SottocategoriaCreate, SottocategoriaOut

class CategoriaBase(BaseModel):
    nome: str

class CategoriaCreate(CategoriaBase):
    sottocategorie: Optional[List[SottocategoriaCreate]] = None

class CategoriaOut(CategoriaBase):
    id: int
    sottocategorie: List[SottocategoriaOut] = []

    class Config:
        from_attributes = True