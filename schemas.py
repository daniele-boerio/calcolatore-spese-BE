from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, date

class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str

class UserOut(BaseModel):
    id: int
    email: EmailStr
    username: str

    class Config:
        from_attributes = True

# Per i Conti
class ContoCreate(BaseModel):
    nome: str

class ContoOut(ContoCreate):
    id: int
    user_id: int
    class Config:
        from_attributes = True

# Per le Categorie
class CategoriaCreate(BaseModel):
    nome: str
    parent_id: Optional[int] = None

class CategoriaOut(CategoriaCreate):
    id: int
    user_id: int
    class Config:
        from_attributes = True

class TransazioneCreate(BaseModel):
    importo: float
    tipo: str  # "ENTRATA" o "USCITA"
    descrizione: Optional[str] = None
    conto_id: int
    categoria_id: int
    data: Optional[datetime] = None

class TransazioneOut(TransazioneCreate):
    id: int
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    username: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

# Per creare l'anagrafica del titolo (es. ISIN: IE00B4L5Y983)
class InvestimentoCreate(BaseModel):
    isin: str
    nome_titolo: str

class InvestimentoOut(InvestimentoCreate):
    id: int
    user_id: int
    class Config:
        from_attributes = True

# Per registrare acquisti, vendite o semplicemente l'andamento del valore
class StoricoInvestimentoCreate(BaseModel):
    investimento_id: int
    data: date
    quantita: float  # Positiva per acquisto, negativa per vendita, 0 per solo aggiornamento prezzo
    prezzo_unitario: float
    valore_attuale: Optional[float] = None # Valore totale della posizione in quella data

class StoricoInvestimentoOut(StoricoInvestimentoCreate):
    id: int
    class Config:
        from_attributes = True