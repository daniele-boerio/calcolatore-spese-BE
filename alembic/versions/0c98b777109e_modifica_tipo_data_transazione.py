"""modifica tipo data transazione

Revision ID: 0c98b777109e
Revises: 38e99e834af6
Create Date: 2026-02-10 11:34:31.201141

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0c98b777109e"
down_revision: Union[str, Sequence[str], None] = "38e99e834af6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cambia il tipo della colonna da DateTime a Date
    # 'postgresql' richiede 'postgresql_using' se ci sono già dati
    op.execute("ALTER TABLE transazioni ALTER COLUMN data TYPE DATE USING data::date")


def downgrade() -> None:
    # Torna a DateTime (Timestamp)
    op.execute(
        "ALTER TABLE transazioni ALTER COLUMN data TYPE TIMESTAMP WITHOUT TIME ZONE USING data::timestamp"
    )
