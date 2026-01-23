from datetime import datetime
from pydantic import BaseModel

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