from datetime import datetime
from fastapi import Query
from pydantic import BaseModel, ConfigDict  # Aggiornato a V2
from typing import List, Optional
from .sottocategoria import SottocategoriaCreate, SottocategoriaOut


class CategoriaBase(BaseModel):
    nome: str
    solo_entrata: bool = True
    solo_uscita: bool = True
    solo_rimborso: bool = True


class CategoriaCreate(CategoriaBase):
    sottocategorie: Optional[List[SottocategoriaCreate]] = None


class CategoriaUpdate(BaseModel):  # Rendo i campi opzionali per la PATCH
    nome: Optional[str] = None
    solo_entrata: Optional[bool] = None
    solo_uscita: Optional[bool] = None
    solo_rimborso: Optional[bool] = None


class CategoriaOut(CategoriaBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    lastImport: datetime
    sottocategorie: List[SottocategoriaOut] = []

    # Configurazione moderna Pydantic V2
    model_config = ConfigDict(from_attributes=True)


class CategoriaFilters:
    def __init__(
        self,
        # Default ordinamento per nome
        sort_by: Optional[List[str]] = Query(["nome:asc"]),
        nome: Optional[str] = Query(None),
        solo_entrata: Optional[bool] = Query(None),
        solo_uscita: Optional[bool] = Query(None),
        solo_rimborso: Optional[bool] = Query(None),
    ):
        self.sort_by = sort_by
        self.nome = nome
        self.solo_entrata = solo_entrata
        self.solo_uscita = solo_uscita
        self.solo_rimborso = solo_rimborso

    def model_dump(self):
        # Mantiene la compatibilità con la tua funzione di filtraggio
        return {k: v for k, v in self.__dict__.items() if v is not None}
