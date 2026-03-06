from datetime import date, datetime
from pydantic import BaseModel, field_validator, ConfigDict
from typing import Optional, List
from fastapi import Query
from decimal import Decimal

# --- UTILS PER ARROTONDAMENTO INVESTIMENTI ---
# Usiamo 6 decimali per quote e prezzi unitari (precisione titoli)
PRECISIONE_TITOLI = Decimal("0.000001")
# Usiamo 2 decimali per controvalori in Euro
PRECISIONE_MONETA = Decimal("0.01")

# --- SCHEMI STORICO (Operazioni di Acquisto/Vendita) ---


class StoricoInvestimentoBase(BaseModel):
    data: date
    quantita: Decimal  # Positiva per acquisto, negativa per vendita
    prezzo_unitario: Decimal

    @field_validator("quantita", "prezzo_unitario", mode="after")
    @classmethod
    def round_titoli(cls, v: Decimal) -> Decimal:
        return v.quantize(PRECISIONE_TITOLI)


class StoricoInvestimentoCreate(StoricoInvestimentoBase):
    pass


class StoricoInvestimentoUpdate(BaseModel):
    data: Optional[date] = None
    quantita: Optional[Decimal] = None
    prezzo_unitario: Optional[Decimal] = None

    @field_validator("quantita", "prezzo_unitario", mode="after")
    @classmethod
    def round_titoli_opt(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(PRECISIONE_TITOLI)
        return v


class StoricoInvestimentoOut(StoricoInvestimentoBase):
    id: int
    investimento_id: int

    model_config = ConfigDict(from_attributes=True)


# --- SCHEMI INVESTIMENTO (Anagrafica Titolo) ---


class InvestimentoBase(BaseModel):
    isin: str
    ticker: Optional[str] = None
    nome_titolo: str


class InvestimentoCreate(InvestimentoBase):
    quantita_iniziale: Decimal
    prezzo_carico_iniziale: Decimal
    data_iniziale: date

    @field_validator("quantita_iniziale", "prezzo_carico_iniziale", mode="after")
    @classmethod
    def round_iniziali(cls, v: Decimal) -> Decimal:
        return v.quantize(PRECISIONE_TITOLI)


class InvestimentoUpdate(BaseModel):
    isin: Optional[str] = None
    ticker: Optional[str] = None
    nome_titolo: Optional[str] = None


class InvestimentoOut(InvestimentoBase):
    id: int
    prezzo_attuale: Optional[Decimal] = None
    data_ultimo_aggiornamento: Optional[date] = None
    storico: List[StoricoInvestimentoOut] = []

    # Campi calcolati che arriveranno dalle property del modello DB
    quantita_totale: Optional[Decimal] = None
    valore_posizione: Optional[Decimal] = None
    prezzo_medio_carico: Optional[Decimal] = None

    @field_validator(
        "prezzo_attuale", "prezzo_medio_carico", "quantita_totale", mode="after"
    )
    @classmethod
    def round_high_precision(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(PRECISIONE_TITOLI)
        return v

    @field_validator("valore_posizione", mode="after")
    @classmethod
    def round_money(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(PRECISIONE_MONETA)
        return v

    model_config = ConfigDict(from_attributes=True)


# --- FILTRI ---


class InvestimentoFilters:
    def __init__(
        self,
        sort_by: Optional[List[str]] = Query(["nome_titolo:asc"]),
        isin: Optional[str] = Query(None),
        ticker: Optional[str] = Query(None),
        nome_titolo: Optional[str] = Query(None),
        quantita_min: Optional[Decimal] = Query(None),
        quantita_max: Optional[Decimal] = Query(None),
        valore_attuale_min: Optional[Decimal] = Query(None),
        valore_attuale_max: Optional[Decimal] = Query(None),
        data_inizio: Optional[date] = Query(None),
        data_fine: Optional[date] = Query(None),
    ):
        self.sort_by = sort_by
        self.isin = isin
        self.ticker = ticker
        self.nome_titolo = nome_titolo
        self.quantita_min = quantita_min
        self.quantita_max = quantita_max
        self.valore_attuale_min = valore_attuale_min
        self.valore_attuale_max = valore_attuale_max
        self.data_inizio = data_inizio
        self.data_fine = data_fine

    def model_dump(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}
