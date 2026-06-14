from pydantic import BaseModel, ConfigDict
from enum import Enum
from datetime import datetime, date
from decimal import Decimal
from typing import Optional


class BankConnectorProvider(str, Enum):
    NORDIGEN = "NORDIGEN"
    MOCK = "MOCK"


class BankConnectorConfigBase(BaseModel):
    provider: BankConnectorProvider
    account_id: Optional[str] = None
    institution_id: Optional[str] = None
    client_id: Optional[str] = None
    secret: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class BankConnectorConfigCreate(BankConnectorConfigBase):
    pass


class BankConnectorConfigUpdate(BaseModel):
    provider: Optional[BankConnectorProvider] = None
    account_id: Optional[str] = None
    institution_id: Optional[str] = None
    client_id: Optional[str] = None
    secret: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class BankConnectorConfigOut(BaseModel):
    provider: BankConnectorProvider
    account_id: Optional[str] = None
    institution_id: Optional[str] = None
    last_sync: Optional[datetime] = None
    last_error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BankConnectorSyncResponse(BaseModel):
    new_proposals: int
    last_sync: datetime
    until: datetime

    model_config = ConfigDict(from_attributes=True)


class BankTransactionProposalStatus(str, Enum):
    PENDING = "PENDING"
    IMPORTED = "IMPORTED"
    DISCARDED = "DISCARDED"


class BankTransactionProposalOut(BaseModel):
    id: int
    provider: str
    external_id: Optional[str] = None
    tipo: str
    data: date
    importo: Decimal
    descrizione: Optional[str] = None
    status: BankTransactionProposalStatus
    imported_transaction_id: Optional[int] = None
    creationDate: datetime
    lastUpdate: datetime

    model_config = ConfigDict(from_attributes=True)


class BankTransactionProposalImport(BaseModel):
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None
    descrizione: Optional[str] = None
