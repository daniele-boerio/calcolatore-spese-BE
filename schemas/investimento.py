from datetime import date
from pydantic import BaseModel
from typing import Optional, List

# --- SCHEMI STORICO (Operazioni di Acquisto/Vendita) ---


class StoricoInvestimentoBase(BaseModel):
    data: date
    quantita: float  # Positiva per acquisto, negativa per vendita
    prezzo_unitario: float


class StoricoInvestimentoCreate(StoricoInvestimentoBase):
    pass


class StoricoInvestimentoUpdate(BaseModel):
    data: Optional[date] = None
    quantita: Optional[float] = None
    prezzo_unitario: Optional[float] = None


class StoricoInvestimentoOut(StoricoInvestimentoBase):
    id: int
    investimento_id: int

    class Config:
        from_attributes = True


# --- SCHEMI INVESTIMENTO (Anagrafica Titolo) ---


class InvestimentoBase(BaseModel):
    isin: str
    ticker: Optional[str] = None
    nome_titolo: str


class InvestimentoCreate(InvestimentoBase):
    # Dati per la prima operazione automatica
    quantita_iniziale: float
    prezzo_carico_iniziale: float
    data_iniziale: date


class InvestimentoUpdate(BaseModel):
    # Tutti i campi opzionali per la PATCH
    isin: Optional[str] = None
    ticker: Optional[str] = None
    nome_titolo: Optional[str] = None


class InvestimentoOut(InvestimentoBase):
    id: int
    prezzo_attuale: Optional[float] = None
    data_ultimo_aggiornamento: Optional[date] = None

    storico: List[StoricoInvestimentoOut] = []

    class Config:
        from_attributes = True
