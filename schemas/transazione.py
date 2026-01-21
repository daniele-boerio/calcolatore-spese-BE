from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from .tag import TagOut  # Import relativo dal file tag.py nella stessa cartella

# 1. Base: Campi comuni sia alla creazione che alla visualizzazione
class TransazioneBase(BaseModel):
    importo: float
    tipo: str
    data: Optional[datetime] = None
    descrizione: Optional[str] = None
    conto_id: int
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None
    parent_transaction_id: Optional[int] = None

# 2. Create: Eredita tutto dalla Base (non serve aggiungere altro)
class TransazioneCreate(TransazioneBase):
    pass

# 3. Out: Eredita dalla Base e aggiunge i campi specifici per la risposta API
class TransazioneOut(TransazioneBase):
    id: int
    # Sovrascriviamo 'tag' per mostrare l'oggetto TagOut completo invece del solo ID
    tag: Optional[TagOut] = None
    # Rendiamo 'data' obbligatoria nell'output (perché nel DB ci sarà sempre)
    data: datetime 

    class Config:
        from_attributes = True