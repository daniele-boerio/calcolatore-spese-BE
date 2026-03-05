from datetime import date
from pydantic import BaseModel
from typing import Optional
from fastapi import Query

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

    storico: list[StoricoInvestimentoOut] = []

    class Config:
        from_attributes = True


class InvestimentoFilters:
    def __init__(
        self,
        # Ora mettiamo Query() in TUTTI i campi per blindarli nella query string
        sort_by: Optional[list[str]] = Query(["nome_titolo:asc"]),
        isin: Optional[str] = Query(None),
        ticker: Optional[str] = Query(None),
        nome_titolo: Optional[str] = Query(None),
        # Range per quantità e valore
        quantita_min: Optional[float] = Query(None),
        quantita_max: Optional[float] = Query(None),
        valore_attuale_min: Optional[float] = Query(None),
        valore_attuale_max: Optional[float] = Query(None),
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

    # Creiamo questo metodo per non rompere la tua funzione apply_filters_and_sort
    def model_dump(self):
        # Restituisce un dizionario ignorando i valori None
        return {k: v for k, v in self.__dict__.items() if v is not None}
