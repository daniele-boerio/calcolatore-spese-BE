"""add_monthly_spending_budget_to_users

Revision ID: b3d4e5f6a7c8
Revises: a7b8c9d0e1f2
Create Date: 2026-09-03 00:00:00.000000

Tetto di spesa mensile, distinto da `total_budget` che è l'obiettivo di
risparmio. Nullable senza default: gli utenti esistenti restano senza tetto
impostato, e l'hero della Home mostra le spese del mese senza barra finché non
lo scelgono.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d4e5f6a7c8'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('monthly_spending_budget', sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'monthly_spending_budget')
