from pydantic import BaseModel, field_validator, ConfigDict
from typing import Optional, List
from datetime import datetime, date
from enum import Enum
from fastapi import Query
from decimal import Decimal


class TipoTransazione(str, Enum):
    ENTRATA = "ENTRATA"
    USCITA = "USCITA"
    RIMBORSO = "RIMBORSO"


# 1. Base: Cambiamo importo in Decimal
class TransazioneBase(BaseModel):
    importo: Decimal
    tipo: TipoTransazione
    data: date = date.today()
    descrizione: Optional[str] = None
    conto_id: int
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None
    parent_transaction_id: Optional[int] = None

    @field_validator("importo", mode="after")
    @classmethod
    def round_importo(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))


# 2. Create e Update (Ereditano il validator dalla Base)
class TransazioneCreate(TransazioneBase):
    pass


class TransazioneUpdate(TransazioneBase):
    pass


# 3. Out: Aggiungiamo importo_netto come Decimal
class TransazioneOut(TransazioneBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    importo_netto: Optional[Decimal] = None

    @field_validator("importo_netto", mode="after")
    @classmethod
    def round_netto(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(Decimal("0.01"))
        return v

    model_config = ConfigDict(from_attributes=True)


# 4. Pagination: Arrotondiamo i totali globali
class TransazionePagination(BaseModel):
    total: int
    page: int
    size: int
    total_entrata: Decimal
    total_uscita: Decimal
    total_rimborsi: Decimal
    data: List[TransazioneOut]

    @field_validator("total_entrata", "total_uscita", "total_rimborsi", mode="after")
    @classmethod
    def round_totals(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))


# 5. Filters: Aggiornata per gestire Decimal nei range di prezzo
class TransazioneFilters:
    def __init__(
        self,
        sort_by: Optional[List[str]] = Query(["data:desc", "id:desc"]),
        importo_min: Optional[Decimal] = Query(None),
        importo_max: Optional[Decimal] = Query(None),
        tipo: Optional[str] = Query(None),
        data_inizio: Optional[date] = Query(None),
        data_fine: Optional[date] = Query(None),
        descrizione: Optional[str] = Query(None),
        conto_id: Optional[List[int]] = Query(None),
        categoria_id: Optional[List[List[int]]] = Query(
            None
        ),  # FastAPI gestisce meglio List se non forzate
        sottocategoria_id: Optional[List[int]] = Query(None),
        tag_id: Optional[List[int]] = Query(None),
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

    def model_dump(self):
        # Piccola correzione: se è Decimal, lo lasciamo tale per la query SQL
        return {k: v for k, v in self.__dict__.items() if v is not None}
