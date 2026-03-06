from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator, ConfigDict
from typing import Optional
from decimal import Decimal


class UserBase(BaseModel):
    email: EmailStr
    username: str


class UserCreate(UserBase):
    password: str


class UserOut(UserBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    # Se vuoi mostrare il budget anche nel profilo utente, aggiungilo qui:
    # total_budget: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    username: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserBudgetUpdate(BaseModel):
    # Cambiato in Decimal per coerenza finanziaria
    total_budget: Optional[Decimal] = None

    @field_validator("total_budget", mode="after")
    @classmethod
    def round_budget(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            # Arrotonda a 2 decimali per la visualizzazione nel budget
            return v.quantize(Decimal("0.01"))
        return v


class UserResponse(BaseModel):
    username: str
    email: str
    # Aggiungiamo il budget alla risposta se serve al frontend per la BudgetCard
    total_budget: Optional[Decimal] = None

    @field_validator("total_budget", mode="after")
    @classmethod
    def round_budget(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(Decimal("0.01"))
        return v

    model_config = ConfigDict(from_attributes=True)
