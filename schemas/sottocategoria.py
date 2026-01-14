from pydantic import BaseModel

class SottocategoriaBase(BaseModel):
    nome: str

class SottocategoriaCreate(SottocategoriaBase):
    pass

class SottocategoriaUpdate(SottocategoriaBase):
    pass

class SottocategoriaOut(SottocategoriaBase): # Eredita 'nome' da SottocategoriaBase
    id: int
    categoria_id: int
    class Config:
        from_attributes = True