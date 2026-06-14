from pydantic import BaseModel, field_validator, ConfigDict
from typing import Optional
from datetime import datetime
from decimal import Decimal


class DebitoBase(BaseModel):
    nome: str
    ammontare: Decimal
    residuo: Optional[Decimal] = None
    descrizione: Optional[str] = None
    conto_id: Optional[int] = None

    @field_validator("ammontare", "residuo", mode="after")
    @classmethod
    def round_decimals(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(Decimal("0.01"))
        return v


class DebitoCreate(DebitoBase):
    pass


class DebitoUpdate(BaseModel):
    nome: Optional[str] = None
    ammontare: Optional[Decimal] = None
    residuo: Optional[Decimal] = None
    descrizione: Optional[str] = None
    conto_id: Optional[int] = None

    @field_validator("ammontare", "residuo", mode="after")
    @classmethod
    def round_decimals(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(Decimal("0.01"))
        return v


class DebitoOut(DebitoBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime

    model_config = ConfigDict(from_attributes=True)
