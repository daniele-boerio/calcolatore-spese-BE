from datetime import datetime
from fastapi import Query
from pydantic import BaseModel, ConfigDict  # Aggiornato a V2
from typing import Optional, List


class SottocategoriaBase(BaseModel):
    nome: str
    solo_entrata: bool = True
    solo_uscita: bool = True


class SottocategoriaCreate(SottocategoriaBase):
    categoria_id: int


class SottocategoriaUpdate(SottocategoriaBase):
    nome: Optional[str] = None
    solo_entrata: Optional[bool] = None
    solo_uscita: Optional[bool] = None


class SottocategoriaOut(SottocategoriaBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    lastImport: datetime
    categoria_id: int

    # Configurazione moderna per Pydantic V2
    model_config = ConfigDict(from_attributes=True)


class SottocategoriaFilters:
    def __init__(
        self,
        sort_by: Optional[List[str]] = Query(["nome:asc"]),
        # Aggiunto filtro utile: filtrare sottocategorie per categoria padre
        categoria_id: Optional[int] = Query(None),
        nome: Optional[str] = Query(None),
    ):
        self.sort_by = sort_by
        self.categoria_id = categoria_id
        self.nome = nome

    def model_dump(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}
