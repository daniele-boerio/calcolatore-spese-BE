from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator, ConfigDict, Field
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


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(
        ..., min_length=8, description="La nuova password (min. 8 caratteri)"
    )


class UserUpdate(BaseModel):
    """Quello che l'utente può cambiare di sé dal profilo.

    Solo lo username: l'email identifica l'account (ci arriva il link di reset
    password) e cambiarla è un'altra cosa; la password si cambia dal flusso di
    reset, che passa dalla casella di posta.
    """

    username: str


class UserBudgetUpdate(BaseModel):
    """Aggiornamento parziale: i campi non inviati restano com'erano.

    I due budget sono cose diverse — `total_budget` è l'obiettivo di risparmio,
    `monthly_spending_budget` il tetto di spesa — e si impostano da due controlli
    separati, quindi l'endpoint legge solo i campi presenti nel payload.
    """

    # Cambiato in Decimal per coerenza finanziaria
    total_budget: Optional[Decimal] = None
    monthly_spending_budget: Optional[Decimal] = None

    @field_validator("total_budget", "monthly_spending_budget", mode="after")
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
    monthly_spending_budget: Optional[Decimal] = None
    # True solo per l'utente admin dell'Open Banking (vedi OPEN_BANKING_ADMIN_EMAIL)
    is_open_banking_admin: bool = False
    # Tag da preselezionare nel form di nuova transazione (vedi User.last_tag_id)
    last_tag_id: Optional[int] = None

    @field_validator("total_budget", "monthly_spending_budget", mode="after")
    @classmethod
    def round_budget(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(Decimal("0.01"))
        return v

    model_config = ConfigDict(from_attributes=True)
