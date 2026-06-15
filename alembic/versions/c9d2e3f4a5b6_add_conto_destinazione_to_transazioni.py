"""add_conto_destinazione_to_transazioni

Revision ID: c9d2e3f4a5b6
Revises: b7f1c2a3d4e5
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b7f1c2a3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'transazioni',
        sa.Column('conto_destinazione_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_transazioni_conto_destinazione',
        'transazioni',
        'conti',
        ['conto_destinazione_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_transazioni_conto_destinazione', 'transazioni', type_='foreignkey'
    )
    op.drop_column('transazioni', 'conto_destinazione_id')
