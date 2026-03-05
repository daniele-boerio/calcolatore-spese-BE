from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
from enum import Enum
from fastapi import Query


class TipoTransazione(str, Enum):
    ENTRATA = "ENTRATA"
    USCITA = "USCITA"
    RIMBORSO = "RIMBORSO"


# 1. Base: Campi comuni sia alla creazione che alla visualizzazione
class TransazioneBase(BaseModel):
    importo: float
    tipo: TipoTransazione
    data: date = date.today()
    descrizione: Optional[str] = None
    conto_id: int
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None
    parent_transaction_id: Optional[int] = None


# 2. Create: Eredita tutto dalla Base (non serve aggiungere altro)
class TransazioneCreate(TransazioneBase):
    pass


class TransazioneUpdate(TransazioneBase):
    pass


# 3. Out: Eredita dalla Base e aggiunge i campi specifici per la risposta API
class TransazioneOut(TransazioneBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    importo_netto: float

    class Config:
        from_attributes = True


class TransazionePagination(BaseModel):
    total: int  # Numero totale di transazioni per l'utente
    page: int  # Pagina attuale
    size: int  # Numero di elementi per pagina
    total_entrata: float  # valore delle entrate
    total_uscita: float  # Valore delle uscite
    data: list[TransazioneOut]  # La lista effettiva delle transazioni


class TransazioneFilters:
    def __init__(
        self,
        # Ora mettiamo Query() in TUTTI i campi per blindarli nella query string
        sort_by: Optional[list[str]] = Query(["data:desc", "id:desc"]),
        importo_min: Optional[float] = Query(None),
        importo_max: Optional[float] = Query(None),
        tipo: Optional[str] = Query(None),
        data_inizio: Optional[date] = Query(None),
        data_fine: Optional[date] = Query(None),
        descrizione: Optional[str] = Query(None),
        conto_id: Optional[list[int]] = Query(None),
        categoria_id: Optional[list[int]] = Query(None),
        sottocategoria_id: Optional[list[int]] = Query(None),
        tag_id: Optional[list[int]] = Query(None),
    ):
        self.sort_by = sort_by
        self.importo_min = importo_min
        self.importo_max = importo_max
        self.tipo = tipo
        self.data_inizio = data_inizio
        self.data_fine = data_fine
        self.descrizione = descrizione
        self.conto_id = conto_id
        self.categoria_id = categoria_id
        self.sottocategoria_id = sottocategoria_id
        self.tag_id = tag_id

    # Creiamo questo metodo per non rompere la tua funzione apply_filters_and_sort
    def model_dump(self, exclude_unset=True, exclude_none=True):
        # Restituisce un dizionario ignorando i valori None
        return {k: v for k, v in self.__dict__.items() if v is not None}
