from pydantic import BaseModel, ConfigDict
from typing import Optional


class InstitutionOut(BaseModel):
    # An Enable Banking ASPSP. Identified by name + country (no single id).
    name: str
    country: str
    logo: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BankAuthStart(BaseModel):
    conto_id: int
    aspsp_name: str
    aspsp_country: str


class BankAuthStartResponse(BaseModel):
    url: str


class BankSessionConfirm(BaseModel):
    state: str
    code: str


class BankSessionConfirmResponse(BaseModel):
    conto_id: int
    account_id: str
    status: str
