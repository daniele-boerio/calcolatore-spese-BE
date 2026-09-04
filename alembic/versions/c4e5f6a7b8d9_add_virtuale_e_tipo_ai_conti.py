"""add_virtuale_e_tipo_ai_conti

Revision ID: c4e5f6a7b8d9
Revises: b3d4e5f6a7c8
Create Date: 2026-09-04 00:00:00.000000

Due colonne su `conti`.

`virtuale` distingue il conto creato dall'app da quelli creati dall'utente:
serve al "Portafoglio" che l'app apre da sola per chi non vuole modellare i
propri conti. Resta invisibile nell'interfaccia finché è l'unico, e i
movimenti che ci stanno sopra si leggono come "senza conto".

`tipo` (corrente / salvadanaio / prepagata) è quello che decide la forma della
card in elenco: fino a oggi si tirava a indovinare da `budget_obiettivo` e dal
collegamento bancario. Nullable: i conti esistenti restano senza tipo e
continuano a comportarsi come prima.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4e5f6a7b8d9"
down_revision: Union[str, Sequence[str], None] = "b3d4e5f6a7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conti",
        sa.Column(
            "virtuale",
            sa.Boolean(),
            nullable=False,
            # I conti che esistono già li ha creati l'utente, non l'app.
            server_default=sa.false(),
        ),
    )
    op.add_column("conti", sa.Column("tipo", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("conti", "tipo")
    op.drop_column("conti", "virtuale")
