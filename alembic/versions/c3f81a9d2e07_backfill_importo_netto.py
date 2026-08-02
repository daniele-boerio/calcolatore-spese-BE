"""backfill importo_netto

La migration 9cd85e955956 ha aggiunto `transazioni.importo_netto` nullable senza
popolarlo: tutte le transazioni preesistenti sono rimaste a NULL. Gli aggregati
che sommavano la colonna nuda (`func.sum(importo_netto)`) le scartavano, mentre
quelli con `coalesce(importo_netto, importo)` le contavano — stesso mese, totali
diversi a seconda dell'endpoint.

Il codice ora usa ovunque `services.importo_effettivo()` (il coalesce), quindi
questo backfill non è strettamente necessario per la correttezza; serve a non
lasciare due rappresentazioni dello stesso dato nel DB. Per una transazione senza
rimborsi il netto coincide con il lordo, quindi la copia è sempre corretta.

Revision ID: c3f81a9d2e07
Revises: a7c1f2d3e4b5
Create Date: 2026-08-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3f81a9d2e07"
down_revision: Union[str, Sequence[str], None] = "a7c1f2d3e4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Copia l'importo lordo sulle righe con netto mancante."""
    op.execute(
        sa.text(
            "UPDATE transazioni SET importo_netto = importo "
            "WHERE importo_netto IS NULL"
        )
    )


def downgrade() -> None:
    """Nessun downgrade: non sappiamo quali righe avevano il netto a NULL.

    Azzerarle tutte perderebbe i netti calcolati dai rimborsi reali, che è un
    danno peggiore del disallineamento che stiamo sistemando.
    """
    pass
