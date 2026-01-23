from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from datetime import date

# --- SCHEMI INVESTIMENTO (Il Titolo) ---

class InvestimentoBase(BaseModel):
    isin: str
    ticker: Optional[str] = None
    nome_titolo: str
    
class InvestimentoCreate(InvestimentoBase):
    pass

class InvestimentoOut(InvestimentoBase):
    id: int
    user_id: int
    # Includiamo i prezzi calcolati dal BE per la UI
    prezzo_attuale: Optional[float] = None
    data_ultimo_aggiornamento: Optional[date] = None

    class Config:
        from_attributes = True


# --- SCHEMI STORICO (Le Operazioni) ---

class StoricoInvestimentoBase(BaseModel):
    investimento_id: int
    data: date
    quantita: float  # Positiva per acquisto, negativa per vendita
    prezzo_unitario: float
    valore_attuale: Optional[float] = None

class StoricoInvestimentoCreate(StoricoInvestimentoBase):
    pass

class StoricoInvestimentoOut(StoricoInvestimentoBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    
    class Config:
        from_attributes = True