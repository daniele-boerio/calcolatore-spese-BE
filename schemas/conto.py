from pydantic import BaseModel
from typing import Optional

# 1. Base: Campi comuni a tutte le operazioni sui conti
class ContoBase(BaseModel):
    nome: str
    saldo: float

# 2. Create: Eredita tutto dalla Base (usato per la creazione iniziale)
class ContoCreate(ContoBase):
    pass

# 3. Update: Campi opzionali (usato per modificare solo il nome o solo il saldo)
class ContoUpdate(BaseModel):
    nome: Optional[str] = None
    saldo: Optional[float] = None

# 4. Out: Risposta inviata al Frontend (aggiunge ID e user_id)
class ContoOut(ContoBase):
    id: int
    user_id: int

    class Config:
        from_attributes = True