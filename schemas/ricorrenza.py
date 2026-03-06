from datetime import datetime, date
from pydantic import BaseModel, field_validator, ConfigDict
from typing import Optional, List
from decimal import Decimal
from schemas.transazione import TipoTransazione
from fastapi import Query


# 1. Base: Definiamo l'importo come Decimal e aggiungiamo il validator
class RicorrenzaBase(BaseModel):
    nome: str
    importo: Decimal
    tipo: TipoTransazione
    frequenza: str  # "GIORNALIERA", "SETTIMANALE", "MENSILE", "ANNUALE"
    prossima_esecuzione: date
    attiva: Optional[bool] = True
    conto_id: int
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None

    @field_validator("importo", mode="after")
    @classmethod
    def round_importo(cls, v: Decimal) -> Decimal:
        if v is not None:
            return v.quantize(Decimal("0.01"))
        return v


# 2. Create: Eredita tutto (incluso il validator)
class RicorrenzaCreate(RicorrenzaBase):
    pass


# 3. Update: Usiamo Decimal anche qui per le modifiche
class RicorrenzaUpdate(BaseModel):
    nome: Optional[str] = None
    importo: Optional[Decimal] = None
    frequenza: Optional[str] = None
    prossima_esecuzione: Optional[date] = None
    attiva: Optional[bool] = None
    conto_id: Optional[int] = None
    categoria_id: Optional[int] = None
    sottocategoria_id: Optional[int] = None
    tag_id: Optional[int] = None

    @field_validator("importo", mode="after")
    @classmethod
    def round_importo(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            return v.quantize(Decimal("0.01"))
        return v


# 4. Out: Standard V2
class RicorrenzaOut(RicorrenzaBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime
    attiva: bool

    model_config = ConfigDict(from_attributes=True)


# 5. Filters: Aggiornati i range di importo a Decimal
class RicorrenzaFilters:
    def __init__(
        self,
        sort_by: Optional[List[str]] = Query(["prossima_esecuzione:asc", "id:desc"]),
        nome: Optional[str] = Query(None),
        tipo: Optional[str] = Query(None),
        importo_min: Optional[Decimal] = Query(None),
        importo_max: Optional[Decimal] = Query(None),
        frequenza: Optional[str] = Query(None),
        prossima_esecuzione_inizio: Optional[date] = Query(None),
        prossima_esecuzione_fine: Optional[date] = Query(None),
        attiva: Optional[bool] = Query(None),
        conto_id: Optional[List[int]] = Query(None),
        categoria_id: Optional[List[int]] = Query(None),
        sottocategoria_id: Optional[List[int]] = Query(None),
        tag_id: Optional[List[int]] = Query(None),
    ):
        self.sort_by = sort_by
        self.nome = nome
        self.tipo = tipo
        self.importo_min = importo_min
        self.importo_max = importo_max
        self.frequenza = frequenza
        self.prossima_esecuzione_inizio = prossima_esecuzione_inizio
        self.prossima_esecuzione_fine = prossima_esecuzione_fine
        self.attiva = attiva
        self.conto_id = conto_id
        self.categoria_id = categoria_id
        self.sottocategoria_id = sottocategoria_id
        self.tag_id = tag_id

    def model_dump(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}
