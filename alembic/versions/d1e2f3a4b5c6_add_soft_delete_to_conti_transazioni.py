"""add_soft_delete_to_conti_transazioni

Aggiunge una colonna `deleted_at` (nullable, indicizzata) a `conti` e
`transazioni` per il soft-delete dei conti. Cancellare un conto ora ne
valorizza `deleted_at` (e quello delle sue transazioni) invece di eseguire
un DELETE fisico con ON DELETE CASCADE, che distruggeva irreversibilmente
tutte le transazioni.

Revision ID: d1e2f3a4b5c6
Revises: c9d2e3f4a5b6
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c9d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'conti',
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        op.f('ix_conti_deleted_at'), 'conti', ['deleted_at'], unique=False
    )
    op.add_column(
        'transazioni',
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        op.f('ix_transazioni_deleted_at'),
        'transazioni',
        ['deleted_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_transazioni_deleted_at'), table_name='transazioni')
    op.drop_column('transazioni', 'deleted_at')
    op.drop_index(op.f('ix_conti_deleted_at'), table_name='conti')
    op.drop_column('conti', 'deleted_at')
