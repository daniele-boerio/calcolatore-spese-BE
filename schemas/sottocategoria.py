from datetime import datetime
from pydantic import BaseModel


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
    categoria_id: int

    class Config:
        from_attributes = True
