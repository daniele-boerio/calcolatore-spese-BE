from datetime import datetime, date
from fastapi import Query
from pydantic import BaseModel, field_validator, ConfigDict
from typing import Optional, List
from decimal import Decimal


class ContoBase(BaseModel):
    nome: str
    saldo: Decimal
    ricarica_automatica: bool = False
    budget_obiettivo: Optional[Decimal] = None
    soglia_minima: Optional[Decimal] = None
    conto_sorgente_id: Optional[int] = None
    frequenza_controllo: Optional[str] = None  # "SETTIMANALE" o "MENSILE"
    prossimo_controllo: Optional[date] = None
    color: Optional[str] = None
    default: bool = False
    bank_connector_provider: Optional[str] = None
    bank_connector_account_id: Optional[str] = None
    bank_connector_institution_id: Optional[str] = None
    bank_connector_last_sync: Optional[datetime] = None
    bank_connector_last_error: Optional[str] = None

    # Validatore universale per i campi monetari del conto
    @field_validator("saldo", "budget_obiettivo", "soglia_minima", mode="after")
    @classmethod
    def round_money(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(Decimal("0.01"))
        return v


class ContoCreate(ContoBase):
    pass


class ContoUpdate(BaseModel):
    nome: Optional[str] = None
    saldo: Optional[Decimal] = None
    ricarica_automatica: Optional[bool] = None
    budget_obiettivo: Optional[Decimal] = None
    soglia_minima: Optional[Decimal] = None
    conto_sorgente_id: Optional[int] = None
    frequenza_controllo: Optional[str] = None
    prossimo_controllo: Optional[date] = None
    color: Optional[str] = None
    default: Optional[bool] = None
    bank_connector_provider: Optional[str] = None
    bank_connector_account_id: Optional[str] = None
    bank_connector_institution_id: Optional[str] = None
    bank_connector_last_sync: Optional[datetime] = None

    @field_validator("saldo", "budget_obiettivo", "soglia_minima", mode="after")
    @classmethod
    def round_money_opt(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(Decimal("0.01"))
        return v


class ContoOut(ContoBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    lastImport: datetime

    model_config = ConfigDict(from_attributes=True)


class ContoFilters:
    def __init__(
        self,
        sort_by: Optional[str] = Query(None),
        nome: Optional[str] = Query(None),
        saldo_min: Optional[Decimal] = Query(None),
        saldo_max: Optional[Decimal] = Query(None),
        ricarica_automatica: Optional[bool] = Query(None),
    ):
        self.sort_by = sort_by
        self.nome = nome
        self.saldo_min = saldo_min
        self.saldo_max = saldo_max
        self.ricarica_automatica = ricarica_automatica

    def model_dump(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}


class PeriodoOut(BaseModel):
    start: date
    end: date


class SavingsBudgetOut(BaseModel):
    """Obiettivo di risparmio: quanto l'utente punta a mettere da parte."""

    total_budget: Optional[Decimal] = None
    remaining: Decimal
    percentage: Optional[float] = None
    period: PeriodoOut


class SpendingBudgetOut(BaseModel):
    """Tetto di spesa: quanto l'utente si concede di spendere nel mese.

    È il riferimento dell'hero della Home. `remaining` può essere negativo — è lo
    sforamento — e resta `None` finché un tetto non è stato impostato.
    """

    budget: Optional[Decimal] = None
    spent: Decimal
    # Uscite ricorrenti attive non ancora scattate entro fine mese.
    projected: Decimal
    remaining: Optional[Decimal] = None
    percentage: Optional[float] = None


class CurrentMonthBudgetOut(BaseModel):
    monthly_budget: SavingsBudgetOut
    spending: SpendingBudgetOut
    income: Decimal
    saved: Decimal
